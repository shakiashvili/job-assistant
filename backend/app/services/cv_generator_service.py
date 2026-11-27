import html as html_lib
import logging
import re
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

from ..db.document_repository import record_candidate_document, resolve_user_id_by_email, user_generated_resumes_dir
from ..db.profile_repository import (
    ground_truth_store,
    filter_spoken_language_entries,
    sanitize_person_name,
    is_corrupted_education_entry,
)
from ..services.gemini_service import GEORGIAN_SKILL_TRANSLATIONS
from ..services.matcher_service import dedupe_skills_case_insensitive
from ..services.scrapers.base_scraper import sanitize_company_name
from .ats_checker import check_pdf_ats_parseability
from .cv_formatting_utils import (
    GEORGIAN_PDF_FONT_NAME,
    UNICODE_FONT_NAME,
    clean_bullets,
    clean_foreign_script_text as _clean_foreign_script_text,
    format_pdf_mixed_script as _format_pdf_mixed_script,
    normalize_contact_href,
)

logger = logging.getLogger(__name__)

_KA_TO_LATIN = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z", "თ": "t", "ი": "i",
    "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o", "პ": "p", "ჟ": "zh", "რ": "r", "ს": "s",
    "ტ": "t", "უ": "u", "ფ": "p", "ქ": "k", "ღ": "gh", "ყ": "q", "შ": "sh", "ჩ": "ch", "ც": "ts",
    "ძ": "dz", "წ": "ts", "ჭ": "ch", "ხ": "kh", "ჯ": "j", "ჰ": "h",
}


_TECH_ROLE_RE = re.compile(
    r"(?:\b(?:qa|sdet|tester|software\s+engineer|developer|programmer|devops|cloud\s+engineer|"
    r"backend|frontend|full[\s-]stack|data\s+engineer|data\s+analyst|sql|python|java|javascript|"
    r"typescript|playwright|selenium|cypress|cybersecurity|information\s+technology|it\s+support)\b|"
    r"პროგრამ|დეველოპერ|ტესტერ|ტექნიკურ)",
    re.IGNORECASE,
)


def _is_technical_profile(headline: str, skills: List[str]) -> bool:
    """Determines whether to label the skills section as Technical vs Core Competencies."""
    blob = f"{headline} {' '.join(skills[:15])}"
    return bool(_TECH_ROLE_RE.search(blob))


def _prepare_cv_render_context(
    candidate: Dict[str, Any],
    candidate_headline: str,
    display_skills: List[str],
    cv_language: str,
    cv_style: str,
) -> Dict[str, Any]:
    """Shared header, contact, and profession-aware section-label builder for DOCX, PDF, and HTML renderers."""
    is_ka = cv_language == "ka"
    raw_cand_name = sanitize_person_name(candidate.get("full_name", "")) or "Candidate"
    full_name = _clean_foreign_script_text(raw_cand_name, cv_language) or raw_cand_name
    raw_role = re.sub(r"[*_`]+", "", str(candidate_headline or candidate.get("headline") or "Specialist")).strip()
    role_heading = _clean_foreign_script_text(raw_role, cv_language) or "Specialist"
    email = re.sub(r"[*_`]+", "", str(candidate.get("email") or "")).strip()
    if email == "candidate@example.com":
        email = ""
    raw_phone = re.sub(r"[*_`]+", "", str(candidate.get("phone") or "")).strip()
    phone = "" if (not raw_phone or "+000" in raw_phone or re.fullmatch(r"[+\s0()-]+", raw_phone)) else raw_phone
    raw_loc = re.sub(r"[*_`]+", "", _format_candidate_location(candidate.get("location"))).strip()
    loc = _clean_foreign_script_text(raw_loc, cv_language)
    links = candidate.get("links", {}) if isinstance(candidate.get("links"), dict) else {}
    linkedin = str(links.get("linkedin", "")).strip()
    github = str(links.get("github", "")).strip()
    portfolio = str(links.get("portfolio", "")).strip()

    is_tech = _is_technical_profile(role_heading, display_skills)
    if is_ka:
        lbl_skills = "ტექნიკური კომპეტენციები და სტეკი" if is_tech else "ძირითადი კომპეტენციები და უნარები"
    else:
        lbl_skills = "TECHNICAL SKILLS & STACK" if is_tech else "CORE COMPETENCIES & SKILLS"

    return {
        "is_ka": is_ka,
        "full_name": full_name,
        "role_heading": role_heading,
        "email": email,
        "phone": phone,
        "loc": loc,
        "linkedin": linkedin,
        "github": github,
        "portfolio": portfolio,
        "labels": {
            "summary": "პროფესიული მიმოხილვა" if is_ka else ("EXECUTIVE PROFILE" if cv_style == "recruiter" else "PROFESSIONAL SUMMARY"),
            "skills": lbl_skills,
            "exp": "სამუშაო გამოცდილება" if is_ka else "PROFESSIONAL EXPERIENCE",
            "proj": "რელევანტური პროექტები" if is_ka else "RELEVANT PROJECTS",
            "edu": "განათლება და სპეციალიზებული ტრენინგები" if is_ka else "EDUCATION & SPECIALIZED TRAINING",
            "lang": "ენები" if is_ka else "LANGUAGES",
        },
    }


def group_skills_into_ats_buckets(
    skills: List[str],
    cv_language: str = "en",
    target_industry: Optional[str] = None,
    headline: str = "",
) -> List[tuple[str, List[str]]]:
    """
    Categorizes genuine candidate skills into 3-5 profession-adaptive ATS & recruiter buckets
    across Tech/QA, Software/Data, Finance, Marketing, Logistics, HR, Sales, Legal, Healthcare,
    and Hospitality — with zero fabrication.
    """
    clean_skills = dedupe_skills_case_insensitive([str(raw or "").strip() for raw in (skills or []) if str(raw or "").strip()])
    if not clean_skills:
        return []

    is_ka = cv_language == "ka"
    ind = (target_industry or "").lower().strip()
    probe = f"{ind} {headline} {' '.join(clean_skills[:16])}".lower()

    if not ind or ind == "general_professional":
        if any(k in probe for k in ("qa", "sdet", "playwright", "selenium", "cypress", "tester", "manual testing", "test automation", "ტესტ")):
            ind = "qa_tech"
        elif any(k in probe for k in ("ifrs", "gaap", "accountant", "accounting", "financial model", "audit", "1c", "oris", "ბუღალტ", "ფინანს")):
            ind = "finance_accounting"
        elif any(k in probe for k in ("seo", "sem", "google ads", "meta ads", "smm", "copywriting", "marketing", "მარკეტინგ")):
            ind = "marketing_growth"
        elif any(k in probe for k in ("logistics", "supply chain", "procurement", "customs", "freight", "wms", "incoterms", "ლოჯისტიკ")):
            ind = "logistics_supply_chain"
        elif any(k in probe for k in ("recruiting", "talent acquisition", "hris", "human resources", "onboarding", "რეკრუტ")):
            ind = "hr_recruiting"
        elif _TECH_ROLE_RE.search(probe):
            ind = "software_engineering"

    def _bucketize(rules: List[tuple[str, str, str, tuple[str, ...]]], fallback_key: str, fallback_en: str, fallback_ka: str) -> List[tuple[str, List[str]]]:
        buckets: Dict[str, List[str]] = {k: [] for k, _, _, _ in rules}
        buckets[fallback_key] = []
        lbls: Dict[str, str] = {k: (ka if is_ka else en) for k, en, ka, _ in rules}
        lbls[fallback_key] = fallback_ka if is_ka else fallback_en
        for s in clean_skills:
            low = s.lower()
            placed = False
            for k, _, _, kws in rules:
                if any((low == kw or (len(kw) >= 3 and kw in low)) for kw in kws):
                    buckets[k].append(s)
                    placed = True
                    break
            if not placed:
                buckets[fallback_key].append(s)
        return [(lbls[k], vals) for k, vals in buckets.items() if vals]

    if ind == "finance_accounting":
        return _bucketize(
            [
                ("rep", "Financial Reporting & Analysis", "ფინანსური რეპორტინგი და ანალიზი", ("ifrs", "gaap", "audit", "reconcil", "budget", "forecast", "model", "valuation", "tax", "payroll", "fp&a", "p&l", "accounting", "ბუღალტ", "აუდიტ", "ფინანს")),
                ("sys", "Accounting, ERP & BI Systems", "საბუღალტრო, ERP და ანალიტიკური სისტემები", ("1c", "oris", "sap", "oracle", "netsuite", "quickbooks", "excel", "power bi", "tableau", "sql", "python", "bloomberg", "erp")),
            ],
            "ops", "Risk, Compliance & Operations", "რისკები, შესაბამისობა და ოპერაციები",
        )
    if ind == "marketing_growth":
        return _bucketize(
            [
                ("perf", "Acquisition & Performance Marketing", "ციფრული რეკლამა და ზრდა", ("seo", "sem", "ppc", "google ads", "meta ads", "facebook ads", "paid", "growth", "cro", "funnel", "performance", "campaign", "lead gen")),
                ("cont", "Content, Brand & Social Media", "კონტენტი, ბრენდი და სოციალური მედია", ("content", "copywrit", "smm", "social media", "brand", "pr", "email", "crm", "storytell", "კონტენტ")),
                ("martech", "Analytics & Marketing Stack", "ანალიტიკა და მარკეტინგული ინსტრუმენტები", ("ga4", "google analytics", "tag manager", "hubspot", "salesforce", "mailchimp", "looker", "figma", "canva", "a/b", "sql", "excel")),
            ],
            "strat", "Strategy & Communications", "სტრატეგია და კომუნიკაცია",
        )
    if ind == "logistics_supply_chain":
        return _bucketize(
            [
                ("sc", "Supply Chain & Procurement", "მიწოდების ჯაჭვი და შესყიდვები", ("supply chain", "procurement", "sourcing", "vendor", "freight", "customs", "import", "export", "incoterms", "logistics", "ლოჯისტიკ", "შესყიდვ")),
                ("wms", "Warehouse, Inventory & ERP", "საწყობი, მარაგები და ERP სისტემები", ("wms", "erp", "sap", "inventory", "warehouse", "dispatch", "3pl", "excel", "sql", "1c", "საწყობ", "მარაგ")),
            ],
            "coord", "Operations & Compliance", "ოპერაციები და დოკუმენტაცია",
        )
    if ind == "hr_recruiting":
        return _bucketize(
            [
                ("ta", "Talent Acquisition & Sourcing", "ტალანტების მოზიდვა და შერჩევა", ("recruit", "sourcing", "linkedin recruiter", "screening", "interview", "ats", "employer brand", "headhunt", "რეკრუტ")),
                ("ops", "People Operations & HR Systems", "HR ოპერაციები და სისტემები", ("onboarding", "hris", "bamboohr", "workday", "payroll", "performance", "compensation", "l&d", "training", "excel")),
            ],
            "rel", "Employee Relations & Compliance", "შრომითი ურთიერთობები და ადმინისტრირება",
        )
    if ind in ("qa_tech", "software_engineering", "data_analytics"):
        is_qa = ind == "qa_tech"
        rules = [
            ("auto", "Test Automation & Frameworks" if is_qa else "Frameworks & Libraries", "ტესტ-ავტომატიზაცია და ფრეიმვორქები" if is_qa else "ფრეიმვორქები და ბიბლიოთეკები", ("playwright", "selenium", "cypress", "pytest", "robot framework", "appium", "testng", "junit", "webdriver", "react", "next.js", "fastapi", "django", "node", "spring", "pandas", "spark", "ავტომატ")),
            ("lang", "Programming & Query Languages", "პროგრამირება და სკრიპტინგი", ("python", "typescript", "javascript", "sql", "bash", "java", "c#", "go", "html", "css", "r")),
            ("api", "API, Data & Validation", "API, მონაცემები და ვალიდაცია", ("postman", "rest api", "swagger", "openapi", "graphql", "k6", "jmeter", "http", "json", "xml", "chrome devtools", "api", "power bi", "tableau", "postgresql", "mysql", "mongodb")),
            ("infra", "CI/CD, Cloud & Tooling", "CI/CD, ქლაუდი და ინფრასტრუქტურა", ("github actions", "gitlab ci", "ci/cd", "docker", "linux", "git", "jenkins", "kubernetes", "aws", "gcp", "azure", "terraform", "jira", "cloud")),
        ]
        fb_en = "Methodologies & Quality Practices" if is_qa else "Core Engineering Competencies"
        fb_ka = "მეთოდოლოგიები და ტესტ-მენეჯმენტი" if is_qa else "ძირითადი პროფესიული კომპეტენციები"
        return _bucketize(rules, "mgmt", fb_en, fb_ka)

    # Universal non-tech professional taxonomy (Sales, Legal, Healthcare, Hospitality, Customer Service, etc.)
    return _bucketize(
        [
            ("tools", "Systems, Platforms & Tools", "სისტემები და პროგრამული ინსტრუმენტები", ("crm", "salesforce", "hubspot", "zendesk", "jira", "opera", "pms", "emr", "ehr", "excel", "sap", "erp", "pos", "sql", "power bi", "ms office", "google workspace", "slack")),
            ("ops", "Client, Regulatory & Operational Execution", "კლიენტებთან ურთიერთობა და ოპერაციები", ("client", "customer", "guest", "patient", "stakeholder", "negotiation", "compliance", "contract", "legal", "sla", "scheduling", "billing", "insurance", "sales", "b2b", "კომუნიკაც", "მომსახურებ")),
        ],
        "core", "Core Domain Competencies", "ძირითადი პროფესიული კომპეტენციები",
    )


def _add_docx_bottom_border(paragraph, color_hex: str = "CBD5E1", sz: str = "6") -> None:
    """Adds a crisp subtle bottom rule under section headings in Word (.docx) without tables/textboxes."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), sz)
    bottom.set(qn("w:space"), "3")
    bottom.set(qn("w:color"), color_hex)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _apply_docx_run_font(run, font_name: str = "Calibri") -> None:
    """Explicitly sets OOXML ASCII/hAnsi/CS font attributes so Word renders Sylfaen/Calibri reliably."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run.font.name = font_name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rFonts.set(qn(attr), font_name)


def _add_docx_hyperlink(paragraph, display_text: str, url: str, font_name: str = "Calibri") -> None:
    """Inserts a genuine native clickable OOXML hyperlink into a python-docx paragraph."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE

    if not url:
        r = paragraph.add_run(display_text)
        r.font.size = __import__("docx.shared", fromlist=["Pt"]).Pt(9.5)
        _apply_docx_run_font(r, font_name)
        return

    part = paragraph.part
    r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rFonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rFonts.set(qn(attr), font_name)
    rPr.append(rFonts)
    color_el = OxmlElement("w:color")
    color_el.set(qn("w:val"), "0369A1")
    rPr.append(color_el)
    underline_el = OxmlElement("w:u")
    underline_el.set(qn("w:val"), "single")
    rPr.append(underline_el)
    sz_el = OxmlElement("w:sz")
    sz_el.set(qn("w:val"), "19")  # 9.5pt
    rPr.append(sz_el)
    new_run.append(rPr)

    t_el = OxmlElement("w:t")
    t_el.text = display_text
    new_run.append(t_el)

    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def ascii_filename_slug(text: str, default: str = "Item", max_len: int = 24) -> str:
    """Produces clean Latin-ASCII filename slugs (transliterating Georgian script cleanly)."""
    if not text:
        return default
    out = []
    for ch in text.strip():
        out.append(_KA_TO_LATIN.get(ch, ch))
    joined = "".join(out)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", joined).strip("_")
    return (slug[:max_len].strip("_")) or default


# Core bullet filtering and mixed-script PDF helpers live in cv_formatting_utils.py


def _resolve_ats_role_tag(parsed_skills: Dict[str, Any], candidate_headline: str) -> str:
    """
    Computes the canonical ASCII filename role tag for ATS and Recruiter editions from the
    candidate's verified profile role (rather than a target vacancy's title, preventing internship
    postings from downgrading the candidate's file identity).
    """
    if str((parsed_skills or {}).get("target_industry") or "").lower() == "qa_tech":
        return "QA_Engineer"
    return ascii_filename_slug(
        str(candidate_headline or "").split("|")[0],
        default="Specialist",
        max_len=24,
    )


def _extract_override_profile_taxonomy(skills_md: str) -> tuple[Dict[str, Any], List[str], str]:
    """Extracts verified industry, primary_role, and skills from an explicit skills_md override."""
    from .profile_service import profile_service

    extracted = profile_service.extract_structured_profile(skills_md)
    ps = extracted.parsed_skills.model_dump()
    ps["target_industry"] = extracted.target_industry
    ps["detected_industry"] = extracted.detected_industry
    ps["primary_role"] = extracted.primary_role
    ps["verified_skills"] = extracted.verified_skills
    return ps, list(extracted.verified_skills or ps.get("all_skills") or []), extracted.full_name


def resolve_candidate_headline(candidate: Dict[str, Any], skills: List[str], parsed_skills: Dict[str, Any]) -> str:
    """Returns the candidate's verified headline/primary_role strictly without forcing a QA/SDET title."""
    ps = parsed_skills or {}
    industry = str(ps.get("target_industry") or "").lower()
    primary_role = str(ps.get("primary_role") or "").strip()
    raw_hl = str(candidate.get("headline") or "").strip()

    if raw_hl and not any(w in raw_hl.lower() for w in ["intern", "trainee", "სტაჟიორ"]):
        return raw_hl
    if primary_role:
        return primary_role
    if industry == "qa_tech":
        return "QA Engineer"
    return raw_hl or "Specialist"


RESUME_STRATEGIST_SYSTEM_PROMPT = """You are a Top 1% Executive CV Strategist and ATS Career Architect across technology and business disciplines.
Your goal is to tailor the candidate's verified experience to the provided vacancy description for maximum ATS keyword alignment and recruiter readability.

STRICT CONSTRAINTS (ZERO TOLERANCE FOR FABRICATION):
1. TRUTHFUL GROUNDING: Every bullet point, tool, skill, company, degree, and timeline MUST come strictly from the candidate's verified profile. NEVER invent skills, honors, awards, tools, or certifications.
2. NATURAL HUMANIZED TONE: Use active, factual phrasing without generic AI clichés or unrequested availability timing.
3. CLEAN ATS FORMAT: Header, Concise Summary, Core Skill Matrix, Verified Experience, Education & Certifications."""


# Font registration and mixed-script PDF helpers live cleanly in cv_formatting_utils.py


def _format_candidate_location(loc_val: Any) -> str:
    """Formats structured or string location cleanly, returning '' instead of ', ' when empty."""
    if isinstance(loc_val, dict):
        city = str(loc_val.get("city") or "").strip()
        country = str(loc_val.get("country") or "").strip()
        return ", ".join(p for p in (city, country) if p)
    return str(loc_val or "").strip()


def _format_candidate_languages(candidate: Dict[str, Any], skills_md: str, is_ka: bool) -> str:
    """
    Extracts strictly HUMAN spoken languages from CandidateProfile first (reflecting UI edits)
    and falls back to `## Languages` section in `skills_md`, rejecting programming tokens.
    """
    lang_entries: List[Dict[str, str]] = []

    raw_langs = candidate.get("languages")
    if isinstance(raw_langs, dict):
        raw_list = [{"language": k, "proficiency": v} for k, v in raw_langs.items() if k]
        lang_entries = filter_spoken_language_entries(raw_list)
    elif isinstance(raw_langs, list) and raw_langs:
        lang_entries = filter_spoken_language_entries(raw_langs)
    elif isinstance(raw_langs, str) and raw_langs.strip():
        lang_entries = filter_spoken_language_entries([p.strip() for p in re.split(r"[|,;]", raw_langs)])

    if not lang_entries and skills_md:
        # Fallback: Check dedicated `## Languages` / `## Spoken Languages` / `## ენები` section
        sec_m = re.search(
            r"(?ims)^#{1,3}\s*(?:languages|spoken\s+languages|ენები)[^\n]*\n(.*?)(?=^#{1,3}\s|\Z)",
            skills_md,
        )
        if sec_m:
            lines = [
                re.sub(r"^[-*•]\s*", "", ln).strip()
                for ln in sec_m.group(1).splitlines()
                if ln.strip() and not re.fullmatch(r"[-*_=\s]+", ln.strip())
            ]
            lang_entries = filter_spoken_language_entries(lines)
        else:
            inline_m = re.search(
                r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:spoken\s+languages|languages|ენები)(?:\*\*)?\s*:\s*\**\s*(.+)$",
                skills_md,
            )
            if inline_m:
                lang_entries = filter_spoken_language_entries([inline_m.group(1).strip()])

    if not lang_entries:
        return ""

    ka_names = {
        "georgian": "ქართული",
        "english": "ინგლისური",
        "russian": "რუსული",
        "german": "გერმანული",
        "french": "ფრანგული",
        "spanish": "ესპანური",
        "ukrainian": "უკრაინული",
        "polish": "პოლონური",
    }
    formatted_parts = []
    for entry in lang_entries[:5]:
        name = entry["language"]
        prof = entry.get("proficiency", "")
        if is_ka:
            name = ka_names.get(name.lower(), name)
        formatted_parts.append(f"{name}: {prof}" if prof else name)

    return "  |  ".join(formatted_parts)


def _format_education_row(edu: Dict[str, Any], is_ka: bool) -> Dict[str, Any]:
    """Normalizes a single grouped degree entry into clean header + detail metadata (no duplicates or meta-prose)."""
    if is_corrupted_education_entry(edu):
        return {"title": "", "detail": ""}
    deg = _clean_foreign_script_text(re.sub(r"[*_`]+", "", str(edu.get("degree") or "")), "ka" if is_ka else "en")
    inst = _clean_foreign_script_text(re.sub(r"[*_`]+", "", str(edu.get("institution") or "")), "ka" if is_ka else "en")
    dates = _clean_foreign_script_text(
        re.sub(r"[*_`]+", "", str(edu.get("dates") or edu.get("graduation_year") or "")),
        "ka" if is_ka else "en",
    )
    if inst.lower() == deg.lower():
        inst = ""
    gpa = _clean_foreign_script_text(edu.get("gpa") or "", "ka" if is_ka else "en")
    mods = [
        _clean_foreign_script_text(m, "ka" if is_ka else "en")
        for m in (edu.get("modules") or [])
        if str(m).strip()
    ]
    focus = ""
    if mods:
        lbl = "შესწავლილი საგნები: " if is_ka else "Subjects & Modules: "
        focus = f"{lbl}{', '.join(mods)}"
    elif edu.get("field_of_study") and str(edu["field_of_study"]).strip().lower() not in (deg.lower(), inst.lower()):
        focus = _clean_foreign_script_text(edu["field_of_study"], "ka" if is_ka else "en")
    if gpa and "gpa" not in focus.lower():
        gpa_str = f"GPA: {gpa}"
        focus = f"{gpa_str}  •  {focus}" if focus else gpa_str

    header_parts = [p for p in [deg, inst] if p]
    title_line = " — ".join(header_parts)
    if dates:
        title_line = f"{title_line} ({dates})" if title_line else dates
    return {"title": title_line, "detail": focus}


def _prioritize_job_highlights(
    highlights: List[str],
    target_keywords: List[str],
) -> List[str]:
    """Ranks genuine work-history bullets mentioning job/matched requirements first without fabricating content."""
    cleaned = clean_bullets(highlights)
    if not cleaned or not target_keywords:
        return cleaned
    kws = [k.strip().lower() for k in target_keywords if k and len(k.strip()) >= 2]
    scored = []
    for idx, bullet in enumerate(cleaned):
        b_low = bullet.lower()
        hits = sum(1 for kw in kws if kw in b_low)
        scored.append((-hits, idx, bullet))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in scored]


class CVGeneratorService:
    """
    Grounded, Non-Exaggerated Single-Column ATS CV Generator using ReportLab.
    Produces clean, ATS-compliant single-column PDF resumes (and printable HTML previews)
    following the structure:
      Header -> Summary -> Technical Skills Matrix -> Work Experience -> Education & Certifications.
    """

    SYSTEM_PROMPT = RESUME_STRATEGIST_SYSTEM_PROMPT

    def generate_vacancy_cv(
        self,
        job_title: str,
        company: str,
        portal: str,
        matched_skills: List[str],
        missing_skills: List[str],
        human_summary: str,
        motivation_statement: str,
        dou_motivational_letter: str,
        skills_md_override: Optional[str] = None,
        cv_language: str = "en",
        cv_style: str = "tailored",
        required_skills: Optional[List[str]] = None,
        owner_email: Optional[str] = None,
        vault_override: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generates tailored PDF, Word (.docx), and HTML CVs from verified candidate ground truth.

        Filename contract:
        - `cv_style` in `("ats", "recruiter")`: canonical edition named after the candidate's
          verified profile role (`<Candidate>_<VerifiedRoleTag>_(ATS|RECRUITER)[_KA].ext`),
          avoiding target-job title downgrades (e.g. internship postings).
        - `cv_style == "tailored"`: vacancy-specific edition named after the target company and
          target role (`<Candidate>_<Company>_<TargetRole>_CV[_KA].ext`).
        """
        resolved_uid = user_id if user_id is not None else resolve_user_id_by_email(owner_email)
        gt = vault_override if vault_override else ground_truth_store.get_data(owner_email=owner_email, user_id=resolved_uid)
        ps = dict(gt.get("_parsed_skills") or gt.get("parsed_skills_taxonomy") or {})
        raw_vault_md = str(gt.get("skills_md_raw") or "")
        has_explicit_md_override = bool(
            skills_md_override
            and str(skills_md_override).strip()
            and str(skills_md_override).strip() != raw_vault_md.strip()
        )
        skills_md = skills_md_override or raw_vault_md or ground_truth_store.get_skills_md(owner_email=owner_email)
        parsed_md = ground_truth_store.parse_profile_from_md(skills_md) if skills_md else {}

        override_skills: List[str] = []
        if has_explicit_md_override and skills_md:
            override_ps, override_skills, _ = _extract_override_profile_taxonomy(skills_md)
            ps = override_ps

        candidate = dict(gt.get("candidate", {})) if not has_explicit_md_override else {}
        for fld in ("full_name", "headline", "email", "phone"):
            if has_explicit_md_override:
                candidate[fld] = parsed_md.get(fld) or ""
            elif not candidate.get(fld) and parsed_md.get(fld):
                candidate[fld] = parsed_md[fld]
        if has_explicit_md_override:
            if parsed_md.get("location"):
                loc_parts = [p.strip() for p in str(parsed_md["location"]).split(",", 1)]
                candidate["location"] = {"city": loc_parts[0], "country": loc_parts[1] if len(loc_parts) > 1 else ""}
            else:
                candidate["location"] = {}
        elif parsed_md.get("location") and not _format_candidate_location(candidate.get("location")):
            loc_parts = [p.strip() for p in str(parsed_md["location"]).split(",", 1)]
            candidate["location"] = {"city": loc_parts[0], "country": loc_parts[1] if len(loc_parts) > 1 else ""}

        cand_links = {} if has_explicit_md_override else dict(candidate.get("links") or {})
        if skills_md:
            gh_m = re.search(r"(https?://(?:www\.)?github\.com/[A-Za-z0-9._-]+/?)", skills_md, re.I)
            li_m = re.search(r"(https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9._-]+/?)", skills_md, re.I)
            if gh_m and (has_explicit_md_override or not cand_links.get("github")):
                cand_links["github"] = gh_m.group(1).rstrip("/")
            if li_m and (has_explicit_md_override or not cand_links.get("linkedin")):
                cand_links["linkedin"] = li_m.group(1).rstrip("/")
        candidate["links"] = cand_links

        if has_explicit_md_override:
            core_skills = parsed_md.get("skills") or override_skills or []
            raw_work_history = parsed_md.get("work_history") or []
            education = parsed_md.get("education") or []
            projects = parsed_md.get("projects") or []
            certifications = parsed_md.get("certifications") or []
        else:
            core_skills = (gt.get("skills", {}) or {}).get("core") or parsed_md.get("skills") or []
            raw_work_history = gt.get("work_history") if gt.get("work_history") else (parsed_md.get("work_history") or [])
            education = gt.get("education") if gt.get("education") else (parsed_md.get("education") or [])
            projects = gt.get("projects") if gt.get("projects") else (parsed_md.get("projects") or [])
            certifications = gt.get("certifications") or parsed_md.get("certifications") or ps.get("courses_and_certifications") or []

        core_skills = dedupe_skills_case_insensitive([str(s) for s in core_skills])
        education = [e for e in (education or []) if not is_corrupted_education_entry(e)]
        candidate["full_name"] = sanitize_person_name(candidate.get("full_name") or "") or sanitize_person_name(parsed_md.get("full_name") or "") or "Candidate"

        # Sanitize target role, company & summary strictly into the target CV language
        clean_job_title = _clean_foreign_script_text(job_title, cv_language) or "Specialist"
        clean_summary = _clean_foreign_script_text(human_summary, cv_language)

        # Tailor bullet ordering per job description & matched requirements with immutable source_bullet_id evidence tracking
        target_kws = list(dict.fromkeys((matched_skills or []) + (required_skills or []) + re.findall(r"[A-Za-z]{3,}", clean_job_title or "")))
        prioritized_wh: List[Dict[str, Any]] = []
        source_bullet_records: List[Dict[str, Any]] = []
        for job_idx, job in enumerate(raw_work_history):
            j_copy = dict(job)
            clean_role = _clean_foreign_script_text(j_copy.get("role") or "", cv_language)
            clean_comp = _clean_foreign_script_text(j_copy.get("company") or "", cv_language)
            j_copy["role"] = clean_role
            j_copy["company"] = clean_comp
            raw_highlights = clean_bullets(j_copy.get("highlights") or [])
            orig_id_map: Dict[str, tuple[str, int]] = {}
            cleaned_candidates: List[str] = []
            for b_idx, raw_b in enumerate(raw_highlights):
                c_b = _clean_foreign_script_text(raw_b, cv_language)
                if c_b:
                    src_id = f"exp-{job_idx}-b-{b_idx}"
                    cleaned_candidates.append(c_b)
                    orig_id_map.setdefault(c_b, (src_id, b_idx))
                    source_bullet_records.append({
                        "source_bullet_id": src_id,
                        "job_idx": job_idx,
                        "orig_idx": b_idx,
                        "company": clean_comp,
                        "role": clean_role,
                        "original_text": str(raw_b).strip(),
                        "cleaned_text": c_b,
                    })
            reordered = _prioritize_job_highlights(cleaned_candidates, target_kws)
            j_copy["highlights"] = [b for b in reordered if b]
            j_copy["_source_bullet_meta"] = [orig_id_map.get(b, (f"exp-{job_idx}-b-{idx}", idx)) for idx, b in enumerate(j_copy["highlights"])]
            prioritized_wh.append(j_copy)

        # Enforce 100% single-language work history when Georgian CV is explicitly built
        if cv_language == "ka" and prioritized_wh:
            from .gemini_service import gemini_service as _gs
            work_history = []
            for job in prioritized_wh:
                j_copy = dict(job)
                clean_b = clean_bullets(j_copy.get("highlights"))
                j_copy["highlights"] = _gs.translate_bullets_to_georgian(clean_b) if clean_b else []
                r_txt = str(j_copy.get("role") or "")
                r_txt = r_txt.replace("Software QA Intern", "Software QA სტაჟიორი").replace("QA Intern", "QA სტაჟიორი")
                j_copy["role"] = r_txt
                work_history.append(j_copy)
        else:
            work_history = prioritized_wh

        bullet_diffs: List[Dict[str, Any]] = []
        src_by_id = {rec["source_bullet_id"]: rec for rec in source_bullet_records}
        for job in work_history:
            meta_list = job.pop("_source_bullet_meta", [])
            final_bullets = job.get("highlights") or []
            for new_idx, final_text in enumerate(final_bullets):
                src_id, orig_idx = meta_list[new_idx] if new_idx < len(meta_list) else (f"exp-x-b-{new_idx}", new_idx)
                rec = src_by_id.get(src_id, {})
                orig_text = rec.get("original_text", final_text)
                matched_in_b = [kw for kw in target_kws if kw.lower() in f"{orig_text} {final_text}".lower()][:5]
                if cv_language == "ka" and final_text != orig_text:
                    action = "translated_ka"
                elif new_idx != orig_idx:
                    action = "prioritized"
                else:
                    action = "preserved"
                bullet_diffs.append({
                    "source_bullet_id": src_id,
                    "company": rec.get("company") or job.get("company") or "",
                    "role": rec.get("role") or job.get("role") or "",
                    "original_text": orig_text,
                    "tailored_text": final_text,
                    "action": action,
                    "matched_keywords": matched_in_b,
                    "verified_source": src_id in src_by_id,
                })

        # Order genuine skills so matched ATS keywords appear first (NO FABRICATION)
        matched_lower = {s.lower() for s in matched_skills}
        prioritized_skills = sorted(
            core_skills,
            key=lambda s: (0 if any(m in s.lower() or s.lower() in m for m in matched_lower) else 1),
        )

        if cv_language == "ka":
            display_skills = [GEORGIAN_SKILL_TRANSLATIONS.get(s, s) for s in prioritized_skills]
        else:
            display_skills = prioritized_skills

        candidate_headline = resolve_candidate_headline(candidate, core_skills, ps)
        candidate_headline = _clean_foreign_script_text(candidate_headline, cv_language) or candidate_headline
        safe_company = _clean_foreign_script_text(sanitize_company_name(company, fallback=""), cv_language)
        human_summary = clean_summary
        job_title = clean_job_title
        clean_full_for_slug = re.sub(r"\([^)]*\)", "", str(candidate.get("full_name", "Candidate"))).strip()
        cand_slug = ascii_filename_slug(clean_full_for_slug or str(candidate.get("full_name", "Candidate")), default="Candidate", max_len=24)

        lang_suffix = "_KA" if cv_language == "ka" else ""
        role_tag = _resolve_ats_role_tag(ps, candidate_headline)
        job_role_slug = ascii_filename_slug(job_title, default="Role", max_len=20)
        languages_line = (
            _format_candidate_languages({}, skills_md, cv_language == "ka")
            if has_explicit_md_override
            else ""
        ) or _format_candidate_languages(candidate, skills_md, cv_language == "ka")

        if cv_style in ("ats", "recruiter"):
            base_name = f"{cand_slug}_{role_tag}_{cv_style.upper()}{lang_suffix}"
        elif safe_company and safe_company.lower() not in ("ats edition", "recruiter edition", "target company", "hiring company"):
            comp_slug = ascii_filename_slug(safe_company, default="Role", max_len=20)
            if job_role_slug and job_role_slug.lower() != comp_slug.lower():
                base_name = f"{cand_slug}_{comp_slug}_{job_role_slug}_CV{lang_suffix}"
            else:
                base_name = f"{cand_slug}_{comp_slug}_CV{lang_suffix}"
        else:
            base_name = f"{cand_slug}_{job_role_slug or role_tag}_CV{lang_suffix}"

        tailored_highlights = [
            f"{job.get('role')} @ {job.get('company')}: {h}"
            for job in work_history
            for h in clean_bullets(job.get("highlights"))[:2]
        ]

        rendered = self._render_all_formats(
            out_dir=user_generated_resumes_dir(user_id=user_id, owner_email=owner_email),
            base_name=base_name,
            candidate=candidate,
            candidate_headline=candidate_headline,
            target_role=job_title,
            target_company=safe_company or company,
            human_summary=human_summary,
            display_skills=display_skills,
            work_history=work_history,
            education=education,
            projects=projects,
            certifications=certifications,
            cv_language=cv_language,
            cv_style=cv_style,
            languages_line=languages_line,
            expected_keywords=matched_skills or display_skills[:8],
        )

        comp_cfg = candidate.get("compensation") if isinstance(candidate.get("compensation"), dict) else {}
        start_date_str = str(comp_cfg.get("notice_period") or "").strip()
        exp_eur = comp_cfg.get("expected_salary_eur") or 0
        exp_usd = comp_cfg.get("expected_salary_usd") or 0
        expected_salary_str = (
            f"€{int(exp_eur):,}/yr" if exp_eur else (f"${int(exp_usd):,}/yr" if exp_usd else "")
        )

        cv_sections = {
            "candidate": {
                "full_name": candidate.get("full_name", "Candidate"),
                "headline": candidate_headline,
                "email": candidate.get("email", "") if candidate.get("email") != "candidate@example.com" else "",
                "phone": candidate.get("phone", ""),
                "location": candidate.get("location", {}),
                "links": candidate.get("links", {}),
                "languages": candidate.get("languages", []),
            },
            "summary": human_summary,
            "skills": display_skills,
            "work_history": work_history,
            "education": education,
            "projects": projects,
            "certifications": certifications,
            "languages_line": languages_line,
            "target_role": job_title,
            "target_company": safe_company or company,
            "cv_language": cv_language,
            "cv_style": cv_style,
            "bullet_diffs": bullet_diffs,
            "ats_parse_report": rendered["ats_parse_report"],
        }

        return {
            **rendered,
            "cv_language": cv_language,
            "candidate_name": candidate.get("full_name", "Candidate"),
            "target_role": candidate_headline,
            "human_tone_summary": human_summary,
            "applicant_summary": human_summary,
            "cover_letter": motivation_statement,
            "motivation_statement": motivation_statement,
            "dou_motivational_letter": dou_motivational_letter,
            "cv_sections": cv_sections,
            "tailored_highlights": tailored_highlights,
            "ats_keywords_covered": matched_skills or display_skills[:8],
            "bullet_diffs": bullet_diffs,
            "start_date_default": start_date_str,
            "expected_salary": expected_salary_str,
        }

    def _render_all_formats(
        self,
        *,
        out_dir: Path,
        base_name: str,
        candidate: Dict[str, Any],
        candidate_headline: str,
        target_role: str,
        target_company: str,
        human_summary: str,
        display_skills: List[str],
        work_history: List[Dict[str, Any]],
        education: List[Dict[str, Any]],
        projects: List[Dict[str, Any]],
        certifications: List[str],
        cv_language: str,
        cv_style: str,
        languages_line: str,
        expected_keywords: List[str],
    ) -> Dict[str, Any]:
        """Renders HTML, single-column PDF, and DOCX files and runs deterministic ATS verification."""
        pdf_filename, docx_filename, html_filename = f"{base_name}.pdf", f"{base_name}.docx", f"{base_name}.html"
        pdf_path, docx_path, html_path = out_dir / pdf_filename, out_dir / docx_filename, out_dir / html_filename
        common_kwargs = dict(
            candidate=candidate,
            candidate_headline=candidate_headline,
            target_role=target_role,
            target_company=target_company,
            human_summary=human_summary,
            display_skills=display_skills,
            work_history=work_history,
            education=education,
            projects=projects,
            certifications=certifications,
            cv_language=cv_language,
            cv_style=cv_style,
            languages_line=languages_line,
        )
        html_content = self._build_cv_html(**common_kwargs)
        html_path.write_text(html_content, encoding="utf-8")
        self._build_reportlab_single_column_pdf(filepath=pdf_path, **common_kwargs)
        self._build_docx_cv(filepath=docx_path, **common_kwargs)

        ats_parse_report = check_pdf_ats_parseability(
            pdf_path,
            candidate_name=str(candidate.get("full_name") or ""),
            expected_email=str(candidate.get("email") or ""),
            expected_phone=str(candidate.get("phone") or ""),
            expected_keywords=expected_keywords,
        )
        return {
            "pdf_filename": pdf_filename,
            "docx_filename": docx_filename,
            "html_filename": html_filename,
            "pdf_path": str(pdf_path),
            "docx_path": str(docx_path),
            "html_path": str(html_path),
            "pdf_url": f"/api/resumes/generated/{pdf_filename}",
            "docx_url": f"/api/resumes/generated/{docx_filename}",
            "html_preview_url": f"/api/resumes/generated/{html_filename}",
            "rendered_html": html_content,
            "ats_parse_report": ats_parse_report,
        }

    def render_cv_from_sections(
        self,
        sections: Dict[str, Any],
        base_name_override: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Re-renders HTML, PDF, and DOCX cleanly from user-edited structured CV JSON sections."""
        cand = dict(sections.get("candidate") or {})
        cand["full_name"] = sanitize_person_name(cand.get("full_name") or "") or "Candidate"
        headline = re.sub(r"[*_`]+", "", str(sections.get("headline") or cand.get("headline") or sections.get("target_role") or "Specialist")).strip()
        target_role = str(sections.get("target_role") or headline).strip()
        target_company = str(sections.get("target_company") or "Tailored").strip()
        cv_language = str(sections.get("cv_language") or "en").strip() or "en"
        cv_style = str(sections.get("cv_style") or "tailored").strip() or "tailored"
        human_summary = str(sections.get("summary") or "").strip()
        display_skills = dedupe_skills_case_insensitive([str(s).strip() for s in (sections.get("skills") or []) if str(s).strip()])
        work_history = []
        for raw_w in (sections.get("work_history") or []):
            if isinstance(raw_w, dict):
                w_copy = dict(raw_w)
                w_bullets = list(w_copy.get("highlights") or w_copy.get("bullets") or [])
                w_copy["highlights"] = w_bullets
                w_copy["bullets"] = w_bullets
                work_history.append(w_copy)
        languages_line = str(sections.get("languages_line") or _format_candidate_languages(cand, "", cv_language == "ka"))

        if base_name_override:
            base_name = Path(base_name_override).stem
        else:
            cand_slug = ascii_filename_slug(str(cand.get("full_name") or "Candidate"), default="Candidate", max_len=24)
            role_slug = ascii_filename_slug(target_role, default="CV", max_len=20)
            base_name = f"{cand_slug}_{role_slug}_{uuid.uuid4().hex[:6]}_Edited"

        return self._render_all_formats(
            out_dir=user_generated_resumes_dir(user_id=user_id),
            base_name=base_name,
            candidate=cand,
            candidate_headline=headline,
            target_role=target_role,
            target_company=target_company,
            human_summary=human_summary,
            display_skills=display_skills,
            work_history=work_history,
            education=[e for e in (sections.get("education") or []) if not is_corrupted_education_entry(e)],
            projects=list(sections.get("projects") or []),
            certifications=list(sections.get("certifications") or []),
            cv_language=cv_language,
            cv_style=cv_style,
            languages_line=languages_line,
            expected_keywords=display_skills[:8],
        )

    def sync_user_cv_versions(
        self,
        user_id: Optional[int] = None,
        owner_email: Optional[str] = None,
    ) -> int:
        """
        Propagates Candidate Profile Vault updates (contact info, headline, skills,
        work history, education, projects, certifications, spoken languages) into
        all saved CVVersion snapshots and re-renders their DOCX, PDF, and HTML files.
        """
        if user_id is None:
            return 0

        from sqlmodel import Session, select
        from ..db.database import engine
        from ..db.models import CVVersion, utc_now

        gt = ground_truth_store.get_data(owner_email=owner_email, user_id=user_id)
        updated_cand = dict(gt.get("candidate") or {})
        core_skills = [str(s).strip() for s in ((gt.get("skills") or {}).get("core") or []) if str(s).strip()]
        core_lower = {s.lower() for s in core_skills}
        skills_md_raw = str(gt.get("skills_md_raw") or "")

        synced_count = 0
        with Session(engine) as session:
            versions = session.exec(
                select(CVVersion).where(CVVersion.user_id == user_id)
            ).all()
            for ver in versions:
                try:
                    sections = dict(ver.structured_content or {})
                    merged_cand = {**dict(sections.get("candidate") or {}), **updated_cand}
                    sections["candidate"] = merged_cand
                    if updated_cand.get("headline"):
                        sections["headline"] = updated_cand["headline"]

                    ver_edition = (ver.edition or sections.get("cv_style") or "ats").lower()
                    if ver_edition in ("ats", "recruiter"):
                        sections["skills"] = list(core_skills)
                        if updated_cand.get("headline"):
                            ver.target_role = updated_cand["headline"]
                            sections["target_role"] = updated_cand["headline"]
                            comp_label = ver.target_company or (
                                "ATS Edition" if ver_edition == "ats" else "Recruiter Edition"
                            )
                            ver.title = f"{ver.target_role} — {comp_label} ({ver_edition.upper()})"
                    else:
                        existing_skills = [str(s).strip() for s in (sections.get("skills") or []) if str(s).strip()]
                        kept = [s for s in existing_skills if not core_lower or s.lower() in core_lower]
                        kept_lower = {s.lower() for s in kept}
                        sections["skills"] = kept + [s for s in core_skills if s.lower() not in kept_lower]

                    sections["work_history"] = list(gt.get("work_history") or [])
                    sections["education"] = list(gt.get("education") or [])
                    sections["projects"] = list(gt.get("projects") or [])
                    sections["certifications"] = list(gt.get("certifications") or [])
                    is_ka = (ver.cv_language or sections.get("cv_language") or "en") == "ka"
                    sections["languages_line"] = _format_candidate_languages(merged_cand, skills_md_raw, is_ka)

                    rendered = self.render_cv_from_sections(
                        sections,
                        base_name_override=ver.pdf_filename,
                        user_id=user_id,
                    )
                    for fk, fp_key in (("pdf_filename", "pdf_path"), ("docx_filename", "docx_path")):
                        fname = rendered.get(fk)
                        fpath = rendered.get(fp_key)
                        if fname and fpath:
                            record_candidate_document(
                                user_id=user_id,
                                filename=fname,
                                file_path=Path(fpath),
                                doc_type=f"cv_studio_{ver_edition}",
                                target_company=ver.target_company or "",
                                target_role=ver.target_role or "",
                            )
                    ver.structured_content = sections
                    ver.rendered_html = rendered.get("rendered_html") or ver.rendered_html
                    ver.pdf_filename = rendered.get("pdf_filename") or ver.pdf_filename
                    ver.docx_filename = rendered.get("docx_filename") or ver.docx_filename
                    ver.version_number = (ver.version_number or 1) + 1
                    ver.updated_at = utc_now()
                    session.add(ver)
                    synced_count += 1
                except Exception as sync_err:
                    logger.warning("Failed to sync CVVersion id=%s on profile update: %s", ver.id, sync_err)

            if synced_count > 0:
                session.commit()

        return synced_count

    def _build_docx_cv(
        self,
        filepath: Path,
        candidate: Dict[str, Any],
        target_role: str,
        target_company: str,
        human_summary: str,
        display_skills: List[str],
        work_history: List[Dict[str, Any]],
        education: List[Dict[str, Any]],
        projects: Optional[List[Dict[str, Any]]] = None,
        certifications: Optional[List[str]] = None,
        cv_language: str = "en",
        cv_style: str = "tailored",
        candidate_headline: Optional[str] = None,
        languages_line: Optional[str] = None,
    ) -> None:
        """Builds a clean, editable Microsoft Word (.docx) CV in ATS, Recruiter, or Job-Tailored edition."""
        from docx import Document
        from docx.shared import Inches, Pt, RGBColor

        is_ka = cv_language == "ka"
        font_family = "Sylfaen" if is_ka else "Calibri"
        doc = Document()
        for style_name in ("Normal", "List Bullet"):
            try:
                st = doc.styles[style_name]
                st.font.name = font_family
            except KeyError:
                logger.debug("DOCX style '%s' absent in template; skipping font override", style_name)
        for sec in doc.sections:
            sec.top_margin = Inches(0.50)
            sec.bottom_margin = Inches(0.50)
            sec.left_margin = Inches(0.60)
            sec.right_margin = Inches(0.60)

        accent = RGBColor(0x0F, 0x17, 0x2A) if cv_style == "ats" else RGBColor(0x03, 0x69, 0xA1)
        accent_hex = "0F172A" if cv_style == "ats" else "0369A1"
        subtle = RGBColor(0x47, 0x55, 0x69)

        ctx = _prepare_cv_render_context(candidate, candidate_headline, display_skills, cv_language, cv_style)
        full_name, role_heading = ctx["full_name"], ctx["role_heading"]
        email, phone, loc = ctx["email"], ctx["phone"], ctx["loc"]
        linkedin, github, portfolio = ctx["linkedin"], ctx["github"], ctx["portfolio"]
        lbl = ctx["labels"]

        def add_styled_run(p, text: str, *, size: float = 9.5, bold: bool = False, color=None) -> None:
            r = p.add_run(text)
            r.bold = bold
            r.font.size = Pt(size)
            if color is not None:
                r.font.color.rgb = color
            _apply_docx_run_font(r, font_family)

        def add_section_heading(title_text: str) -> None:
            p_h = doc.add_paragraph()
            p_h.paragraph_format.space_before = Pt(9)
            p_h.paragraph_format.space_after = Pt(4)
            p_h.paragraph_format.keep_with_next = True
            _add_docx_bottom_border(p_h, color_hex="CBD5E1", sz="6")
            add_styled_run(p_h, title_text, size=10.5, bold=True, color=accent)

        p_name = doc.add_paragraph()
        p_name.paragraph_format.space_after = Pt(1.5)
        add_styled_run(p_name, full_name, size=19, bold=True, color=RGBColor(0x0F, 0x17, 0x2A))

        p_role = doc.add_paragraph()
        p_role.paragraph_format.space_after = Pt(3)
        add_styled_run(p_role, role_heading, size=11.5, bold=True, color=accent)

        p_contact = doc.add_paragraph()
        p_contact.paragraph_format.space_after = Pt(6)
        _add_docx_bottom_border(p_contact, color_hex=accent_hex, sz="12")
        contact_items = [
            (val, href)
            for val, href in (
                (loc, ""),
                (phone, ""),
                (email, normalize_contact_href(email, is_email=True) if email else ""),
                (linkedin, normalize_contact_href(linkedin) if linkedin else ""),
                (github, normalize_contact_href(github) if github else ""),
                (portfolio, normalize_contact_href(portfolio) if portfolio else ""),
            )
            if val
        ]
        for idx, (label, href) in enumerate(contact_items):
            if idx > 0:
                add_styled_run(p_contact, "  |  ", color=subtle)
            if href:
                _add_docx_hyperlink(p_contact, label, href, font_name=font_family)
            else:
                add_styled_run(p_contact, label, color=subtle)

        lbl_summary, lbl_skills, lbl_exp, lbl_proj, lbl_edu, lbl_lang = (
            lbl["summary"], lbl["skills"], lbl["exp"], lbl["proj"], lbl["edu"], lbl["lang"]
        )

        if (clean_sum := _clean_foreign_script_text(human_summary, cv_language)):
            add_section_heading(lbl_summary)
            p_sum = doc.add_paragraph()
            p_sum.paragraph_format.space_after = Pt(4)
            p_sum.paragraph_format.line_spacing = 1.15
            add_styled_run(p_sum, clean_sum, size=9.8)

        if display_skills:
            add_section_heading(lbl_skills)
            grouped = group_skills_into_ats_buckets(display_skills[:60], cv_language=cv_language, headline=role_heading)
            if grouped:
                for bucket_title, bucket_items in grouped:
                    p_sk = doc.add_paragraph(style="List Bullet")
                    p_sk.paragraph_format.space_after = Pt(2)
                    p_sk.paragraph_format.line_spacing = 1.12
                    add_styled_run(p_sk, f"{bucket_title}: ", bold=True)
                    add_styled_run(p_sk, ", ".join(bucket_items))
            else:
                p_sk = doc.add_paragraph()
                p_sk.paragraph_format.space_after = Pt(4)
                add_styled_run(p_sk, ", ".join(display_skills[:24]), size=9.8)

        if work_history:
            add_section_heading(lbl_exp)
            for job in work_history[:5]:
                dates = f"{job.get('start_date', '')} – {job.get('end_date', '')}".strip(" –")
                loc_j = _clean_foreign_script_text(job.get("location") or "", cv_language)
                meta_tail = (f"  •  {dates}" if dates else "") + (f" ({loc_j})" if loc_j else "")
                p_j = doc.add_paragraph()
                p_j.paragraph_format.space_before = Pt(4)
                p_j.paragraph_format.space_after = Pt(2)
                p_j.paragraph_format.keep_with_next = True
                add_styled_run(p_j, f"{job.get('role', '')} | {job.get('company', '')}", size=10.5, bold=True)
                if meta_tail:
                    add_styled_run(p_j, meta_tail, color=subtle)
                for b in clean_bullets(job.get("highlights"))[:5]:
                    p_b = doc.add_paragraph(style="List Bullet")
                    p_b.paragraph_format.space_after = Pt(2)
                    p_b.paragraph_format.line_spacing = 1.12
                    add_styled_run(p_b, str(b))

        if projects:
            add_section_heading(lbl_proj)
            for proj in projects[:3]:
                if not isinstance(proj, dict):
                    continue
                p_t = _clean_foreign_script_text(proj.get("title") or "", cv_language)
                p_org = _clean_foreign_script_text(proj.get("organization") or "", cv_language)
                p_dt = _clean_foreign_script_text(proj.get("dates") or "", cv_language)
                p_hdr = doc.add_paragraph()
                p_hdr.paragraph_format.space_before = Pt(3)
                p_hdr.paragraph_format.space_after = Pt(1.5)
                p_hdr.paragraph_format.keep_with_next = True
                add_styled_run(p_hdr, f"{p_t} | {p_org}" if p_org else p_t, size=10, bold=True)
                if p_dt:
                    add_styled_run(p_hdr, f"  •  {p_dt}", size=9, color=subtle)
                for b in clean_bullets(proj.get("highlights"))[:3]:
                    p_pb = doc.add_paragraph(style="List Bullet")
                    p_pb.paragraph_format.space_after = Pt(1.5)
                    p_pb.paragraph_format.line_spacing = 1.12
                    add_styled_run(p_pb, _clean_foreign_script_text(b, cv_language))

        if education or certifications:
            add_section_heading(lbl_edu)
            for edu in (education or []):
                row = _format_education_row(edu, is_ka)
                if row["title"]:
                    p_e = doc.add_paragraph(style="List Bullet")
                    p_e.paragraph_format.space_after = Pt(2)
                    add_styled_run(p_e, row["title"], bold=True)
                    if row["detail"]:
                        add_styled_run(p_e, f" — {row['detail']}")
            for cert in (certifications or [])[:4]:
                if (cert_c := _clean_foreign_script_text(cert, cv_language)):
                    p_c = doc.add_paragraph(style="List Bullet")
                    p_c.paragraph_format.space_after = Pt(2)
                    add_styled_run(p_c, cert_c)

        if (langs_line := languages_line or _format_candidate_languages(candidate, "", is_ka)):
            add_section_heading(lbl_lang)
            p_lang = doc.add_paragraph()
            p_lang.paragraph_format.space_after = Pt(2)
            add_styled_run(p_lang, langs_line)

        doc.save(str(filepath))

    def _build_reportlab_single_column_pdf(
        self,
        filepath: Path,
        candidate: Dict[str, Any],
        target_role: str,
        target_company: str,
        human_summary: str,
        display_skills: List[str],
        work_history: List[Dict[str, Any]],
        education: List[Dict[str, Any]],
        projects: Optional[List[Dict[str, Any]]] = None,
        certifications: Optional[List[str]] = None,
        cv_language: str = "en",
        candidate_headline: Optional[str] = None,
        cv_style: str = "tailored",
        languages_line: Optional[str] = None,
    ) -> None:
        """
        Generates a clean, ATS-compliant single-column PDF resume using ReportLab:
        Header -> Summary -> Technical Skills Stack -> Experience -> Projects -> Education & Training -> Languages.
        Uses Sylfaen when cv_language == 'ka'.
        """
        is_ka = cv_language == "ka"
        font_name = GEORGIAN_PDF_FONT_NAME if is_ka else UNICODE_FONT_NAME

        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
            title=f"{candidate.get('full_name', 'Candidate')} - {target_role}",
        )

        accent_hex = "#0f172a" if cv_style == "ats" else "#0369a1"
        styles = getSampleStyleSheet()
        header_style = ParagraphStyle(
            "CVHeaderName",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=19,
            leading=23,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=2,
        )
        role_style = ParagraphStyle(
            "CVTargetRole",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=11.5,
            leading=15,
            textColor=colors.HexColor(accent_hex),
            spaceAfter=4,
        )
        contact_style = ParagraphStyle(
            "CVContact",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#475569"),
            spaceAfter=5,
        )
        sec_title_style = ParagraphStyle(
            "CVSectionTitle",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor(accent_hex),
            spaceBefore=7,
            spaceAfter=3.5,
            keepWithNext=True,
        )
        role_hdr_style = ParagraphStyle(
            "CVRoleHeader",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=13.5,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=3,
            spaceAfter=2,
            keepWithNext=True,
        )
        body_style = ParagraphStyle(
            "CVBody",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=3.5,
        )
        bullet_style = ParagraphStyle(
            "CVBullet",
            parent=body_style,
            leftIndent=11,
            firstLineIndent=-7,
            spaceAfter=2.2,
        )

        ctx = _prepare_cv_render_context(candidate, candidate_headline, display_skills, cv_language, cv_style)
        email = escape(ctx["email"]) if ctx["email"] else ""
        phone = escape(ctx["phone"]) if ctx["phone"] else ""
        loc = escape(ctx["loc"]) if ctx["loc"] else ""

        pdf_links = []
        if email:
            pdf_links.append(
                f'<link href="{escape(normalize_contact_href(ctx["email"], is_email=True))}" color="{accent_hex}"><u>{email}</u></link>'
            )
        if phone:
            pdf_links.append(phone)
        if loc:
            pdf_links.append(loc)
        for raw_url in (ctx["linkedin"], ctx["github"], ctx["portfolio"]):
            if raw_url:
                pdf_links.append(
                    f'<link href="{escape(normalize_contact_href(raw_url))}" color="{accent_hex}"><u>{escape(raw_url)}</u></link>'
                )

        lbl = ctx["labels"]
        lbl_summary, lbl_skills, lbl_exp, lbl_proj, lbl_edu, lbl_lang = (
            lbl["summary"], lbl["skills"], lbl["exp"], lbl["proj"], lbl["edu"], lbl["lang"]
        )

        story = []

        # 1. Header
        role_display = ctx["role_heading"]
        story.append(Paragraph(f"<b>{_format_pdf_mixed_script(str(candidate.get('full_name', 'Candidate')), font_name, GEORGIAN_PDF_FONT_NAME)}</b>", header_style))
        story.append(Paragraph(f"<b>{_format_pdf_mixed_script(role_display, font_name, GEORGIAN_PDF_FONT_NAME)}</b>", role_style))
        if pdf_links:
            story.append(Paragraph("  |  ".join(x for x in pdf_links if x), contact_style))
        story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor(accent_hex), spaceAfter=5))

        # 2. Summary
        clean_sum_pdf = _clean_foreign_script_text(human_summary, cv_language)
        if clean_sum_pdf:
            story.append(Paragraph(f"<b>{lbl_summary}</b>", sec_title_style))
            story.append(Paragraph(_format_pdf_mixed_script(clean_sum_pdf, font_name, GEORGIAN_PDF_FONT_NAME), body_style))

        # 3. Profession-Adaptive ATS Skills Matrix
        if display_skills:
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=3, spaceAfter=3))
            story.append(Paragraph(f"<b>{lbl_skills}</b>", sec_title_style))
            grouped_pdf = group_skills_into_ats_buckets(display_skills[:60], cv_language=cv_language, headline=role_display)
            if grouped_pdf:
                for b_title, b_items in grouped_pdf:
                    items_esc = ", ".join(_format_pdf_mixed_script(x, font_name, GEORGIAN_PDF_FONT_NAME) for x in b_items)
                    story.append(Paragraph(f"<b>{_format_pdf_mixed_script(b_title, font_name, GEORGIAN_PDF_FONT_NAME)}:</b> {items_esc}", body_style))
            else:
                skills_text = " • ".join(_format_pdf_mixed_script(s, font_name, GEORGIAN_PDF_FONT_NAME) for s in display_skills[:20])
                story.append(Paragraph(skills_text, body_style))

        # 4. Work Experience (only rendered when candidate has verified roles)
        if work_history:
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=3, spaceAfter=3))
            story.append(Paragraph(f"<b>{lbl_exp}</b>", sec_title_style))
            for job in work_history[:5]:
                r_title = _format_pdf_mixed_script(str(job.get("role", "")), font_name, GEORGIAN_PDF_FONT_NAME)
                r_comp = _format_pdf_mixed_script(str(job.get("company", "")), font_name, GEORGIAN_PDF_FONT_NAME)
                r_dates = _format_pdf_mixed_script(f"{job.get('start_date', '')} – {job.get('end_date', '')}".strip(" –"), font_name, GEORGIAN_PDF_FONT_NAME)
                r_loc = _format_pdf_mixed_script(_clean_foreign_script_text(job.get("location") or "", cv_language), font_name, GEORGIAN_PDF_FONT_NAME)
                meta_parts = [p for p in (r_dates, r_loc) if p]
                meta_html = f' <font color="#475569">• {" | ".join(meta_parts)}</font>' if meta_parts else ""
                story.append(Paragraph(f"<b>{r_title}</b> | {r_comp}{meta_html}", role_hdr_style))
                for b in clean_bullets(job.get("highlights"))[:5]:
                    story.append(Paragraph(f"• {_format_pdf_mixed_script(str(b), font_name, GEORGIAN_PDF_FONT_NAME)}", bullet_style))
                story.append(Spacer(1, 2.5))

        # 5. Relevant Projects (when present)
        if projects:
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=3, spaceAfter=3))
            story.append(Paragraph(f"<b>{lbl_proj}</b>", sec_title_style))
            for proj in projects[:3]:
                if not isinstance(proj, dict):
                    continue
                p_t = _format_pdf_mixed_script(_clean_foreign_script_text(proj.get("title") or "", cv_language), font_name, GEORGIAN_PDF_FONT_NAME)
                p_org = _format_pdf_mixed_script(_clean_foreign_script_text(proj.get("organization") or "", cv_language), font_name, GEORGIAN_PDF_FONT_NAME)
                p_dt = _format_pdf_mixed_script(_clean_foreign_script_text(proj.get("dates") or "", cv_language), font_name, GEORGIAN_PDF_FONT_NAME)
                hdr = f"<b>{p_t}</b>"
                if p_org:
                    hdr += f" | {p_org}"
                if p_dt:
                    hdr += f' <font color="#475569">• {p_dt}</font>'
                story.append(Paragraph(hdr, role_hdr_style))
                for b in clean_bullets(proj.get("highlights"))[:3]:
                    story.append(Paragraph(f"• {_format_pdf_mixed_script(_clean_foreign_script_text(b, cv_language), font_name, GEORGIAN_PDF_FONT_NAME)}", bullet_style))

        # 6. Grouped Education & Specialized Training
        if education or certifications:
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
            story.append(Paragraph(f"<b>{lbl_edu}</b>", sec_title_style))
            for edu in (education or []):
                row = _format_education_row(edu, is_ka)
                if row["title"]:
                    txt = f"• <b>{_format_pdf_mixed_script(row['title'], font_name, GEORGIAN_PDF_FONT_NAME)}</b>"
                    if row["detail"]:
                        txt += f" — {_format_pdf_mixed_script(row['detail'], font_name, GEORGIAN_PDF_FONT_NAME)}"
                    story.append(Paragraph(txt, body_style))
            for cert in (certifications or [])[:4]:
                cert_c = _clean_foreign_script_text(cert, cv_language)
                if cert_c:
                    story.append(Paragraph(f"• {_format_pdf_mixed_script(cert_c, font_name, GEORGIAN_PDF_FONT_NAME)}", body_style))

        # 7. Spoken Languages ONLY
        lang_line = languages_line or _format_candidate_languages(candidate, "", is_ka)
        if lang_line:
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
            story.append(Paragraph(f"<b>{lbl_lang}</b>", sec_title_style))
            story.append(Paragraph(_format_pdf_mixed_script(lang_line, font_name, GEORGIAN_PDF_FONT_NAME), body_style))

        doc.build(story)

    def _build_cv_html(
        self,
        candidate: Dict[str, Any],
        target_role: str,
        target_company: str,
        human_summary: str,
        display_skills: List[str],
        work_history: List[Dict[str, Any]],
        education: List[Dict[str, Any]],
        projects: Optional[List[Dict[str, Any]]] = None,
        certifications: Optional[List[str]] = None,
        cv_language: str = "en",
        candidate_headline: Optional[str] = None,
        cv_style: str = "tailored",
        languages_line: Optional[str] = None,
    ) -> str:
        is_ka = cv_language == "ka"

        def esc(v: Any) -> str:
            return html_lib.escape(str(v or ""), quote=True)

        ctx = _prepare_cv_render_context(candidate, candidate_headline, display_skills, cv_language, cv_style)
        full_name = ctx["full_name"]
        html_contact_parts = []
        if ctx["email"]:
            html_contact_parts.append(
                f'<a href="{esc(normalize_contact_href(ctx["email"], is_email=True))}" style="color:#0369a1;">{esc(ctx["email"])}</a>'
            )
        if ctx["phone"]:
            html_contact_parts.append(esc(ctx["phone"]))
        if ctx["loc"]:
            html_contact_parts.append(esc(ctx["loc"]))
        for raw_url in (ctx["linkedin"], ctx["github"], ctx["portfolio"]):
            if raw_url:
                html_contact_parts.append(
                    f'<a href="{esc(normalize_contact_href(raw_url))}" target="_blank" style="color:#0369a1;">{esc(raw_url)}</a>'
                )
        html_contact_line = " &nbsp;•&nbsp; ".join(x for x in html_contact_parts if x)

        lbl = ctx["labels"]
        lbl_summary, lbl_skills, lbl_exp, lbl_proj, lbl_edu, lbl_lang = (
            lbl["summary"], lbl["skills"], lbl["exp"], lbl["proj"], lbl["edu"], lbl["lang"]
        )

        grouped_html = group_skills_into_ats_buckets(display_skills[:60], cv_language=cv_language, headline=ctx["role_heading"])
        if grouped_html:
            skills_badges = "".join(
                f'<div style="font-size:11.5px; margin-bottom:4px;"><strong>{esc(b_t)}:</strong> '
                + ", ".join(esc(s) for s in b_vals)
                + "</div>"
                for b_t, b_vals in grouped_html
            )
        else:
            skills_badges = "".join(
                f'<span style="display:inline-block; background:#f1f5f9; color:#0f172a; border:1px solid #cbd5e1; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:600; margin:0 6px 6px 0;">{esc(s)}</span>'
                for s in display_skills[:20]
            )

        exp_blocks = ""
        for job in work_history[:5]:
            bullets = "".join(f"<li style='margin-bottom:3.5px;'>{esc(b)}</li>" for b in clean_bullets(job.get("highlights"))[:5])
            dates = f"{job.get('start_date', '')} – {job.get('end_date', '')}".strip(" –")
            loc_j = _clean_foreign_script_text(job.get("location") or "", cv_language)
            meta_right = " | ".join(p for p in (dates, loc_j) if p)
            exp_blocks += f"""
            <div class="exp-item" style="margin-bottom:13px;">
              <div class="role-hdr" style="display:flex; justify-content:space-between; align-items:baseline; gap:12px;">
                <strong style="font-size:13px; color:#0f172a;">{esc(job.get('role', ''))} | <span style="color:#0284c7;">{esc(job.get('company', ''))}</span></strong>
                <span style="font-size:11px; color:#64748b; white-space:nowrap;">{esc(meta_right)}</span>
              </div>
              <ul style="margin:5px 0 0 18px; padding:0; font-size:12px; color:#334155; line-height:1.5;">
                {bullets}
              </ul>
            </div>
            """
        exp_section = f'<div class="section-title">{lbl_exp}</div>\n{exp_blocks}' if exp_blocks else ""

        proj_section = ""
        if projects:
            proj_items_html = ""
            for proj in projects[:3]:
                if not isinstance(proj, dict):
                    continue
                p_t = _clean_foreign_script_text(proj.get("title") or "", cv_language)
                p_org = _clean_foreign_script_text(proj.get("organization") or "", cv_language)
                p_dt = _clean_foreign_script_text(proj.get("dates") or "", cv_language)
                p_bullets = "".join(f"<li style='margin-bottom:3px;'>{esc(_clean_foreign_script_text(b, cv_language))}</li>" for b in clean_bullets(proj.get("highlights"))[:3])
                proj_items_html += f"""
                <div style="margin-bottom:10px;">
                  <div style="display:flex; justify-content:space-between; align-items:baseline;">
                    <strong style="font-size:12.5px; color:#0f172a;">{esc(p_t)}{f' | <span style="color:#0284c7;">{esc(p_org)}</span>' if p_org else ''}</strong>
                    <span style="font-size:11px; color:#64748b;">{esc(p_dt)}</span>
                  </div>
                  <ul style="margin:4px 0 0 18px; padding:0; font-size:12px; color:#334155; line-height:1.5;">{p_bullets}</ul>
                </div>
                """
            if proj_items_html:
                proj_section = f'<div class="section-title">{lbl_proj}</div>\n{proj_items_html}'

        edu_blocks = ""
        for edu in (education or []):
            row = _format_education_row(edu, is_ka)
            if row["title"]:
                detail_html = f" — {esc(row['detail'])}" if row["detail"] else ""
                edu_blocks += f"<div style='font-size:12px; color:#334155; margin-bottom:4px;'>• <strong>{esc(row['title'])}</strong>{detail_html}</div>"
        for cert in (certifications or [])[:4]:
            cert_c = _clean_foreign_script_text(cert, cv_language)
            if cert_c:
                edu_blocks += f"<div style='font-size:12px; color:#334155; margin-bottom:3px;'>• {esc(cert_c)}</div>"

        role_display_html = _clean_foreign_script_text(candidate_headline or str(candidate.get('headline') or 'Specialist'), cv_language) or 'Specialist'
        lang_line_html = languages_line or _format_candidate_languages(candidate, "", is_ka)
        lang_section = (
            f'<div class="section-title">{lbl_lang}</div><div style="font-size:12px; color:#334155;">{esc(lang_line_html)}</div>'
            if lang_line_html
            else ""
        )

        return f"""<!DOCTYPE html>
<html lang="{esc(cv_language)}">
<head>
  <meta charset="UTF-8" />
  <title>{esc(full_name)} — {esc(target_role)} CV</title>
  <style>
    body {{
      font-family: {'"Sylfaen", "Segoe UI", sans-serif' if is_ka else '"Calibri", "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif'};
      color: #1e293b;
      margin: 0;
      padding: 24px;
      line-height: 1.5;
      background: #ffffff;
    }}
    .cv-container {{ max-width: 760px; margin: 0 auto; }}
    .header {{ border-bottom: 2px solid #0284c7; padding-bottom: 14px; margin-bottom: 16px; }}
    .name {{ font-size: 24px; font-weight: 700; color: #0f172a; margin: 0; }}
    .role {{ font-size: 15px; font-weight: 600; color: #0284c7; margin: 4px 0 8px 0; }}
    .contact {{ font-size: 11.5px; color: #475569; }}
    .section-title {{
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      color: #0369a1;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 4px;
      margin: 16px 0 10px 0;
    }}
    .summary {{ font-size: 12.5px; color: #1e293b; margin: 0; }}
    @media print {{
      @page {{ size: A4; margin: 12mm; }}
      body {{ padding: 0; }}
      .section-title, .role-hdr {{ break-after: avoid; page-break-after: avoid; }}
      .exp-item {{ break-inside: avoid; page-break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <div class="cv-container">
    <div class="header">
      <h1 class="name">{esc(full_name)}</h1>
      <div class="role">{esc(role_display_html)}</div>
      <div class="contact">
        {html_contact_line}
      </div>
    </div>

    <div class="section-title">{lbl_summary}</div>
    <p class="summary">{esc(_clean_foreign_script_text(human_summary, cv_language))}</p>

    <div class="section-title">{lbl_skills}</div>
    <div>{skills_badges}</div>

    {exp_section}

    {proj_section}

    <div class="section-title">{lbl_edu}</div>
    {edu_blocks}

    {lang_section}
  </div>
</body>
</html>"""

    def prepare_email_application_package(
        self,
        job_title: str,
        company: str,
        description: str = "",
        portal: str = "jobs.ge",
        target_email: Optional[str] = None,
        email_subject_template: Optional[str] = None,
        cv_language: str = "auto",
        cv_style: str = "tailored",
        skills_md_override: Optional[str] = None,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generates a complete, ready-to-send email package for any vacancy:
        - Tailored Word (.docx) and PDF CV built from the candidate's live skills.md
        - Job-specific Cover Letter (Georgian for Georgian postings, English otherwise)
        - Clean email subject with [Name] resolved to actual candidate full_name
        """
        from .gemini_service import gemini_service
        from .matcher_service import matcher_service

        resolved_uid = user_id if user_id is not None else resolve_user_id_by_email(owner_email)
        gt = ground_truth_store.get_data(owner_email=owner_email, user_id=resolved_uid)
        candidate = dict(gt.get("candidate", {}))
        ps = dict(gt.get("_parsed_skills") or gt.get("parsed_skills_taxonomy") or {})
        raw_vault_md = str(gt.get("skills_md_raw") or "")
        skills_md = skills_md_override or raw_vault_md
        has_explicit_override = bool(
            skills_md_override
            and str(skills_md_override).strip()
            and str(skills_md_override).strip() != raw_vault_md.strip()
        )
        if has_explicit_override and skills_md:
            override_ps, override_skills, override_name = _extract_override_profile_taxonomy(skills_md)
            override_parsed = ground_truth_store.parse_profile_from_md(skills_md)
            ps = override_ps
            if override_name:
                candidate["full_name"] = override_name
            elif override_parsed.get("full_name"):
                candidate["full_name"] = override_parsed["full_name"]
            if override_parsed.get("phone"):
                candidate["phone"] = override_parsed["phone"]
            if override_parsed.get("email"):
                candidate["email"] = override_parsed["email"]
            if override_parsed.get("work_history"):
                gt = dict(gt)
                gt["work_history"] = list(override_parsed["work_history"])
            if override_parsed.get("education"):
                gt = dict(gt)
                gt["education"] = list(override_parsed["education"])
            cand_skills = override_skills
        else:
            cand_skills = dedupe_skills_case_insensitive([str(s) for s in (gt.get("skills", {}).get("core") or [])])
        cand_name = sanitize_person_name(candidate.get("full_name") or "") or "Candidate"
        candidate["full_name"] = cand_name
        raw_phone = str(candidate.get("phone") or "").strip(" -\t\r\n")
        # Never inject placeholder '+000 000 0000' or '-' into outgoing emails
        cand_phone = "" if (not raw_phone or re.fullmatch(r"[+\s0()-]+", raw_phone) or "000 000" in raw_phone) else raw_phone
        links = candidate.get("links", {}) if isinstance(candidate.get("links"), dict) else {}
        cand_linkedin = str(links.get("linkedin") or "").strip(" -\t\r\n")

        target_industry = str(ps.get("target_industry") or "general_professional").lower()
        detected_industry = str(ps.get("detected_industry") or ps.get("primary_role") or target_industry)
        is_tech_profile = target_industry in ("qa_tech", "software_engineering", "data_analytics")

        ka_chars = len(re.findall(r"[\u10A0-\u10FF]", f"{job_title}\n{description}"))
        is_tech_role = is_tech_profile and any(
            kw in f"{job_title}\n{description[:900]}".lower()
            for kw in ["qa", "quality assurance", "tester", "test", "sdet", "automation", "developer", "engineer", "software", "analyst", "ტესტ", "ავტომატიზ", "დეველოპ", "პროგრამ"]
        )
        cover_lang = "ka" if ka_chars >= 25 else "en"
        if cv_language == "auto":
            # Technical roles always generate crisp English CV (no mixed language bullets);
            # non-technical Georgian roles use 100% Georgian CV. Cover letter follows job posting language.
            cv_lang = "en" if is_tech_role else cover_lang
        else:
            cv_lang = cv_language
            cover_lang = cv_language if cv_language in ("en", "ka") else cover_lang

        req_skills = matcher_service.extract_job_requirements(job_title, description)
        matched = [
            r for r in req_skills if any(r.lower() in c.lower() or c.lower() in r.lower() for c in cand_skills)
        ] or cand_skills[:6]
        missing = [r for r in req_skills if r not in matched]

        narratives = gemini_service.craft_human_tone_narratives(
            job_details={
                "title": job_title,
                "company": company,
                "portal": portal,
                "industry": target_industry,
                "required_skills": req_skills,
                "summary": (description or "")[:1600],
                "description": (description or "")[:2000],
                "work_history": gt.get("work_history") or [],
                "education": gt.get("education") or [],
            },
            skills_md=skills_md,
            matched_skills=matched,
            missing_skills=missing,
            cv_language=cv_lang,
            candidate_name=cand_name,
            letter_language=cover_lang,
        )

        cv_res = self.generate_vacancy_cv(
            job_title=job_title,
            company=company,
            portal=portal,
            matched_skills=matched,
            missing_skills=missing,
            human_summary=narratives["human_tone_summary"],
            motivation_statement=narratives["motivation_statement"],
            dou_motivational_letter=narratives["dou_motivational_letter"],
            skills_md_override=skills_md,
            cv_language=cv_lang,
            cv_style=cv_style,
            required_skills=req_skills,
            owner_email=owner_email,
            vault_override=gt,
            user_id=resolved_uid,
        )

        # Clean subject & sanitize company (never address location strings, portal chrome, or foreign-script leaks)
        real_company = _clean_foreign_script_text(
            sanitize_company_name(company, target_email=target_email, fallback=""),
            cover_lang,
        )

        # Dynamic target domain identification: never leak QA terms into non-tech roles
        target_role_lower = f"{job_title} {description[:500]}".lower()
        domain_rules = (
            ("technical_support", ("მხარდაჭერ", "მონიტორინგ", "support", "monitoring", "helpdesk", "service desk", "it support")),
            ("receptionist_hospitality", ("რეცეფციონ", "რეგისტრატორ", "მიმღებ", "reception", "front desk", "hospitality", "hotel", "სასტუმრო")),
            ("healthcare_hospital", ("პაციენტ", "კლინიკ", "საავადმყოფ", "სამედიცინო", "patient", "clinic", "hospital", "medical")),
            ("customer_service", ("მომხმარებელ", "ქოლ-ცენტრ", "operator", "customer", "call center", "client service")),
            ("logistics_supply_chain", ("ლოჯისტიკ", "საწყობ", "მარაგ", "ტვირთ", "logistics", "supply chain", "procurement", "warehouse")),
            ("finance_accounting", ("ბუღალტერ", "ფინანს", "აუდიტ", "accountant", "finance", "accounting", "auditor")),
            ("marketing_growth", ("მარკეტინგ", "marketing", "smm", "content")),
            ("sales_bd", ("გაყიდვ", "sales", "account executive", "business development")),
            ("hr_recruiting", ("ადამიანური რესურს", "რეკრუტ", "human resources", "recruiter", "talent acquisition", "hr generalist", "hrbp", "people operations")),
            ("public_admin_legal", ("იურისტ", "საჯარო", "lawyer", "legal counsel", "compliance", "public administration")),
            ("qa_tech", ("qa", "quality assurance", "tester", "ტესტ", "ავტომატიზ", "test engineer")),
        )
        effective_domain = next(
            (dom for dom, kws in domain_rules if any(w in target_role_lower for w in kws)),
            "receptionist_hospitality" if target_industry == "hospitality_reception" else target_industry,
        )

        clean_subject = ""
        if email_subject_template:
            clean_subject = re.sub(r"\[(?:your\s+)?(?:name|სახელი(?:\s*გვარი)?|full\s*name)\]", cand_name, email_subject_template, flags=re.I).strip()
            clean_subject = clean_subject.replace("[Name]", cand_name).replace("[name]", cand_name)
            if (effective_domain != "qa_tech" and "qa" in clean_subject.lower() and "qa" not in job_title.lower()) or (
                "qa automation engineer" in clean_subject.lower() and "automation" not in job_title.lower()
            ):
                clean_subject = f"{job_title} — {cand_name}"
        if not clean_subject:
            clean_subject = f"{job_title} — {cand_name}" if cover_lang == "ka" else f"Application for {job_title} — {cand_name}"

        contact_footer = "\n".join(x for x in [cand_name, cand_phone, cand_linkedin] if x and x != "-")
        is_non_tech_domain = effective_domain not in ("qa_tech", "technical_support", "software_engineering", "data_analytics")
        if is_non_tech_domain:
            tech_noise = {"playwright", "selenium", "cypress", "appium", "pytest", "junit", "postman", "jmeter", "webdriver", "qa", "automation", "regression", "api testing", "test cases"}
            clean_matched = [r for r in matched if not any(t in r.lower() for t in tech_noise)]
            clean_cand_skills = [s for s in cand_skills if not any(t in s.lower() for t in tech_noise)]
            skills_highlight = ", ".join((clean_matched or clean_cand_skills)[:5]) or (
                "ანალიტიკური აზროვნება, ორგანიზებულობა, პროფესიული კომუნიკაცია"
                if cover_lang == "ka"
                else "cross-functional coordination, analytical execution, stakeholder communication"
            )
        else:
            skills_highlight = ", ".join((matched or cand_skills)[:6])

        work_companies = list(dict.fromkeys(c for w in (gt.get("work_history") or []) if (c := sanitize_company_name(w.get("company"), fallback=""))))
        companies_phrase = ", ".join(work_companies[:3])
        raw_exp_years = ps.get("years_of_experience") if ps.get("years_of_experience") is not None else candidate.get("experience_years")
        exp_years: Optional[float] = float(raw_exp_years) if raw_exp_years is not None else None

        domain_focus = {
            "technical_support": (("ტექნიკური მხარდაჭერისა და მონიტორინგის მიმართულებით", "ინციდენტების დიაგნოსტიკას (SQL, Jira, API) და მოთხოვნების სწრაფ მოგვარებას", "სისტემების სტაბილურ მუშაობასა და ტექნიკურ მხარდაჭერაში"), ("technical support, systems monitoring, and incident triage", "diagnosing system logs, validating API/SQL flows, and resolving escalations within SLA", "support responsiveness and system reliability")),
            "receptionist_hospitality": (("სტუმარმასპინძლობის და Front Desk ოპერაციების სფეროში", "სტუმრების მიღებას, ჯავშნების კოორდინაციას და პროფესიონალურ კომუნიკაციას", "სერვისის ხარისხისა და სტუმრების კმაყოფილების ზრდაში"), ("front office operations and guest relations", "delivering seamless check-ins, reservation coordination, and multilingual hospitality", "guest satisfaction and smooth front-desk operations")),
            "healthcare_hospital": (("პაციენტთა კოორდინაციისა და სამედიცინო ადმინისტრირების მიმართულებით", "პაციენტების მიღებას, სადაზღვევო პროცესებისა და განრიგის ზუსტ მართვას", "კლინიკის ადმინისტრაციული პროცესების გამართულობაში"), ("patient coordination and clinical administration", "managing patient intake, scheduling, and insurance authorizations accurately", "patient service quality and smooth clinic workflows")),
            "customer_service": (("მომხმარებელთა მომსახურებისა და კომუნიკაციის მიმართულებით", "მომართვების სწრაფ გადაჭრას და CRM სისტემების ეფექტურ მართვას", "მომხმარებელთა გამოცდილების გაუმჯობესებაში"), ("customer support and client operations", "resolving escalations cleanly across chat, phone, and CRM channels", "support responsiveness and client retention")),
            "logistics_supply_chain": (("ლოჯისტიკისა და მიწოდების ჯაჭვის კოორდინაციის მიმართულებით", "ტვირთების კოორდინაციას, მარაგებისა და დოკუმენტაციის კონტროლს", "ლოჯისტიკური ოპერაციების სისწრაფესა და სიზუსტეში"), ("logistics, procurement, and supply chain operations", "coordinating shipments, supplier schedules, inventory tracking, and customs docs", "supply chain efficiency and on-time delivery")),
            "finance_accounting": (("ფინანსების, ბუღალტერიისა და ანალიტიკის მიმართულებით", "ფინანსურ აღრიცხვას, რეპორტინგის მომზადებასა და მონაცემების კონტროლს", "ფინანსური პროცესების სიზუსტეში"), ("finance, accounting, and analytical reporting", "maintaining accurate financial reconciliations, reporting, and compliance controls", "financial accuracy and operational clarity")),
            "marketing_growth": (("მარკეტინგისა და ციფრული კამპანიების მიმართულებით", "კამპანიების დაგეგმვას, კონტენტის მართვასა და შედეგების ანალიტიკას", "მარკეტინგული მიზნების მიღწევაში"), ("digital marketing and campaign growth", "planning acquisition campaigns, content workflows, and conversion analytics", "brand reach and measurable growth")),
            "sales_bd": (("გაყიდვებისა და ბიზნესის განვითარების მიმართულებით", "პარტნიორებთან ურთიერთობების მართვასა და მოლაპარაკებების წარმოებას", "გაყიდვებისა და კლიენტთა ბაზის ზრდაში"), ("B2B sales and account management", "building client pipelines, managing onboarding, and hitting revenue targets", "client acquisition and revenue execution")),
            "hr_recruiting": (("ადამიანური რესურსებისა და რეკრუტინგის მიმართულებით", "შერჩევის პროცესების წარმართვასა და ონბორდინგის კოორდინაციას", "ძლიერი გუნდის ჩამოყალიბებაში"), ("human resources, talent acquisition, and people operations", "managing hiring pipelines, onboarding, and structured HR policies", "hiring quality and team retention")),
            "public_admin_legal": (("სამართლებრივი მხარდაჭერისა და საჯარო ადმინისტრირების მიმართულებით", "ხელშეკრულებების ანალიზს, შესაბამისობის კონტროლსა და დოკუმენტაციის წარმოებას", "სამართლებრივ სიზუსტეში"), ("legal analysis, compliance, and public administration", "reviewing contracts, ensuring regulatory alignment, and maintaining legal documentation", "compliance accuracy and institutional governance")),
            "qa_tech": (("QA ავტომატიზაციასა და API/Manual ტესტირებაში", "რეგრესიული ტესტების შექმნას, REST API შემოწმებასა და ხარვეზების ადრეულ აღმოჩენას", "პროდუქტის ხარისხის სტაბილურობაში"), ("QA automation and manual/API test engineering", "automating regression coverage, validating REST APIs, and catching defects before release", "release confidence and test stability")),
        }
        ka_tuple, en_tuple = domain_focus.get(
            effective_domain,
            (
                (f"{detected_industry}-ის მიმართულებით", f"სამუშაო პროცესების გამართულ შესრულებას ({skills_highlight})", "გუნდის ოპერაციულ ეფექტიანობაში"),
                (detected_industry, f"executing day-to-day workflows reliably using {skills_highlight}", "your team's operational quality and goals"),
            ),
        )

        def _finalize_ai_letter(raw_text: str) -> str:
            cleaned = (raw_text or "").strip()
            cand_email = str(candidate.get("email") or "").strip()
            if cand_email:
                cleaned = cleaned.replace(cand_email, "").strip()
            cleaned = re.sub(r"\n+(?:Best regards|Sincerely|Kind regards|Warm regards|პატივისცემით),?\s*\n+[\s\S]*$", "", cleaned, flags=re.I).strip()
            if cover_lang == "ka" and real_company and f"მოგესალმებით, {real_company}-ის გუნდს" not in cleaned:
                cleaned = f"მოგესალმებით, {real_company}-ის გუნდს,\n\n{cleaned}"
            closing = f"პატივისცემით,\n{contact_footer}" if cover_lang == "ka" else f"Best regards,\n{contact_footer}"
            return f"{cleaned}\n\n{closing}".strip()

        # Gather verified work highlights & education for rich, non-repetitive, recruiter-grade letters
        work_entries = [w for w in (gt.get("work_history") or []) if isinstance(w, dict)]
        letter_kws = [k.lower() for k in (req_skills + matched + re.findall(r"[A-Za-z]{3,}", f"{job_title} {real_company}")) if k]
        ranked_bullets: List[tuple[str, str]] = []
        for w in work_entries:
            w_comp = sanitize_company_name(w.get("company"), fallback="")
            w_role = str(w.get("role") or "").strip()
            for b in clean_bullets(w.get("highlights")):
                if len(b) > 25:
                    ranked_bullets.append((w_comp or w_role, b.rstrip(".")))
        if ranked_bullets and letter_kws:
            ranked_bullets.sort(key=lambda pair: (-sum(1 for kw in letter_kws if kw in pair[1].lower()), len(pair[1])))
        # Prefer 2 distinct employers in the cover letter so proof points showcase breadth
        top_proof_bullets: List[tuple[str, str]] = []
        seen_proof_comps: set[str] = set()
        for pair in ranked_bullets:
            c_key = pair[0].lower()
            if c_key not in seen_proof_comps:
                top_proof_bullets.append(pair)
                seen_proof_comps.add(c_key)
                if len(top_proof_bullets) == 2:
                    break
        if len(top_proof_bullets) < 2:
            for pair in ranked_bullets:
                if pair not in top_proof_bullets:
                    top_proof_bullets.append(pair)
                    if len(top_proof_bullets) == 2:
                        break

        clean_edu_entries = [e for e in (gt.get("education") or []) if not is_corrupted_education_entry(e)]
        edu_by_inst: Dict[str, List[str]] = {}
        edu_labels: List[str] = []
        for e in clean_edu_entries[:2]:
            d_s = str(e.get("degree") or "").strip()
            i_s = str(e.get("institution") or "").strip()
            if d_s and i_s and i_s.lower() != d_s.lower():
                edu_by_inst.setdefault(i_s, []).append(d_s)
            elif d_s or i_s:
                edu_labels.append(d_s or i_s)
        for inst_k, deg_list in edu_by_inst.items():
            edu_labels.append(f"{' and '.join(deg_list)} at {inst_k}")
        edu_phrase = "; ".join(edu_labels)

        is_bank_or_fin_target = any(
            w in f"{real_company} {job_title} {description[:600]}".lower()
            for w in ("bank", "procredit", "tbc", "bog", "fintech", "financial", "payment", "ბანკ", "ფინანს")
        )
        has_econ_edu = any(w in edu_phrase.lower() for w in ("economic", "finance", "business", "ეკონომიკ", "ფინანს"))
        has_distinct_reqs = bool(req_skills) and {r.lower() for r in req_skills[:5]} != {m.lower() for m in (matched or cand_skills)[:6]}

        ai_cover = (narratives.get("cover_letter") or "").strip()
        ai_motiv = (narratives.get("dou_motivational_letter") or "").strip()
        if gemini_service.is_available and (len(ai_cover) >= 320 or len(ai_motiv) >= 320):
            cover_letter = _finalize_ai_letter(ai_cover if len(ai_cover) >= 320 else ai_motiv)
            motivational_letter = _finalize_ai_letter(ai_motiv if len(ai_motiv) >= 320 else ai_cover)
        elif cover_lang == "ka":
            ka_area, ka_action, ka_goal = ka_tuple
            salutation = f"მოგესალმებით, {real_company}-ის გუნდს," if real_company else "მოგესალმებით, გუნდს,"
            hook_company = f"{real_company}-ში" if real_company else "თქვენს კომპანიაში"
            cta_company = f"{real_company}-ის" if real_company else "თქვენი გუნდის"
            req_clause = (
                f"ვაკანსიაში გამოკვეთილი მოთხოვნები ({', '.join(req_skills[:5])}) პირდაპირ ემთხვევა ჩემს პრაქტიკულ გამოცდილებას {ka_area}."
                if has_distinct_reqs
                else f"ჩემი პრაქტიკული გამოცდილება {ka_area} და სისტემური მიდგომა პირდაპირ შეესაბამება აღნიშნული პოზიციის ამოცანებს."
            )
            exp_origin = f"{companies_phrase}-ში მუშაობისას" if companies_phrase else "პრაქტიკული პროექტებისა და გამოცდილების განმავლობაში"
            if top_proof_bullets:
                b_ka = "; ".join(f"{comp}: {txt}" if comp else txt for comp, txt in top_proof_bullets)
                proof_para = (
                    f"{exp_origin} ყოველდღიურად ვიყენებდი {skills_highlight} — ვფარავდი {ka_action}. "
                    f"კონკრეტული გამოცდილებიდან გამოვარჩევდი: {b_ka}."
                )
            else:
                proof_para = f"{exp_origin} პრაქტიკულად გამოვიყენე {skills_highlight}, რაც მოიცავდა {ka_action}."
            edu_ka_para = ""
            if edu_phrase:
                fin_ka = " რაც განსაკუთრებით ღირებულია საბანკო და კრიტიკული ბიზნეს-ლოგიკის სისტემების ტესტირებისას." if (is_bank_or_fin_target and has_econ_edu) else "."
                edu_ka_para = f"აკადემიური საფუძველი ({edu_phrase}) მაძლევს ძლიერ ანალიტიკურ და რაოდენობრივ აზროვნებას{fin_ka}"
            gap_ka = f" რაც შეეხება დამატებით მიმართულებებს ({', '.join(missing[:2])}), ჩემი არსებული ტექნიკური საფუძველი უზრუნველყოფს სწრაფ ონბორდინგს." if missing and not is_non_tech_domain else ""
            third_ka = f"{edu_ka_para}{gap_ka}".strip()

            paragraphs_ka = [
                salutation,
                f"დიდი ინტერესით გიგზავნით განაცხადს „{job_title}“ პოზიციაზე {hook_company}. {req_clause}",
                proof_para,
            ]
            if third_ka:
                paragraphs_ka.append(third_ka)
            paragraphs_ka.append(
                f"თანდართულია პოზიციისთვის მორგებული ჩემი რეზიუმე (CV). მოხარული ვიქნები შევუერთდე {cta_company} გუნდს, წვლილი შევიტანო {ka_goal} და გასაუბრებაზე დეტალურად განვიხილო ჩემი გამოცდილება."
            )
            paragraphs_ka.append(f"პატივისცემით,\n{contact_footer}")
            cover_letter = "\n\n".join(paragraphs_ka)
            motiv_paragraphs_ka = [
                salutation,
                f"განსაკუთრებული მოტივაციით გიგზავნით სამოტივაციო წერილს „{job_title}“ პოზიციაზე {hook_company}. ჩემთვის მნიშვნელოვანია იმ გუნდში მუშაობა, სადაც ხარისხი, სიზუსტე და პასუხისმგებლობა მთავარი პრიორიტეტია.",
                proof_para,
                *( [third_ka] if third_ka else [] ),
                f"დარწმუნებული ვარ, ჩემი გამოცდილება ({skills_highlight}) და სწრაფი განვითარების მოტივაცია მნიშვნელოვან ღირებულებას შეუქმნის {cta_company} გუნდს ({ka_goal}). თანდართულია ჩემი რეზიუმე (CV) და მოხარული ვიქნები გასაუბრებაზე შეხვედრით.",
                f"პატივისცემით,\n{contact_footer}",
            ]
            motivational_letter = "\n\n".join(motiv_paragraphs_ka)
        else:
            en_area, en_action, en_goal = en_tuple
            salutation = f"Dear {real_company} Hiring Team," if real_company else "Dear Hiring Team,"
            target_phrase = f"at {real_company}" if real_company else "with your team"
            cta_team = f"{real_company}'s" if real_company else "your team's"
            exp_intro = (
                f"Backed by {exp_years:g} years of verified experience across {companies_phrase}"
                if (exp_years is not None and companies_phrase)
                else (
                    f"With hands-on experience across {companies_phrase}"
                    if companies_phrase
                    else f"With verified hands-on experience in {en_area}"
                )
            )
            req_bridge = (
                f"your priorities around {', '.join(req_skills[:5])}"
                if has_distinct_reqs
                else f"your team's focus on {en_action}"
            )
            opening_para = (
                f"I am writing to apply for the {job_title} position {target_phrase}. "
                f"{exp_intro}, I bring structured execution in {en_area} that aligns directly with {req_bridge}."
            )

            if top_proof_bullets:
                b_lines = []
                for comp_lbl, b_txt in top_proof_bullets:
                    prefix = f"At {comp_lbl}, I " if comp_lbl and not b_txt.lower().startswith("i ") else ""
                    if prefix:
                        body_clause = b_txt[0].lower() + b_txt[1:] if len(b_txt) > 1 and not b_txt[:2].isupper() else b_txt
                        b_lines.append(f"{prefix}{body_clause}.")
                    else:
                        b_lines.append(f"{b_txt}.")
                proof_para = (
                    f"My hands-on toolkit spans {skills_highlight}. "
                    + " ".join(b_lines)
                )
            else:
                proof_para = (
                    f"Across my hands-on work with {skills_highlight}, I have focused on {en_action}—"
                    f"translating business requirements into verifiable, defect-free releases."
                )

            value_parts: List[str] = []
            if edu_phrase:
                if is_bank_or_fin_target and has_econ_edu:
                    value_parts.append(
                        f"Beyond core technical execution, my academic training ({edu_phrase}) equips me with analytical rigor and financial-domain intuition—directly valuable when verifying banking workflows, calculation rules, and core-system data integrity."
                    )
                else:
                    value_parts.append(
                        f"My academic foundation ({edu_phrase}) complements this technical stack with disciplined analytical reasoning, quantitative validation, and structured problem-solving."
                    )
            if missing and not is_non_tech_domain:
                value_parts.append(
                    f"Where your environment extends into {', '.join(missing[:2])}, my verified tooling foundation enables fast, self-directed ramp-up."
                )
            value_para = " ".join(value_parts)

            closing_para = (
                f"Please find my tailored CV attached for your review. I would welcome the opportunity to speak with {cta_team} hiring team "
                f"about how my background can contribute immediately to {en_goal}."
            )

            paragraphs_en = [salutation, opening_para, proof_para]
            if value_para:
                paragraphs_en.append(value_para)
            paragraphs_en.append(closing_para)
            paragraphs_en.append(f"Best regards,\n{contact_footer}")
            cover_letter = "\n\n".join(paragraphs_en)
            motiv_opening_en = (
                f"I am excited to submit my motivational letter for the {job_title} opportunity {target_phrase}. "
                f"What draws me to {real_company or 'your organization'} is the chance to apply my verified background in {en_area} "
                f"where precision, dependability, and measurable quality directly matter."
            )
            motiv_closing_en = (
                f"I am eager to bring disciplined execution, fast onboarding, and long-term commitment to {cta_team} team, "
                f"helping strengthen {en_goal}. Thank you for reviewing my attached CV—I would love to connect in an interview."
            )
            motiv_paragraphs_en = [salutation, motiv_opening_en, proof_para]
            if value_para:
                motiv_paragraphs_en.append(value_para)
            motiv_paragraphs_en.extend([motiv_closing_en, f"Best regards,\n{contact_footer}"])
            motivational_letter = "\n\n".join(motiv_paragraphs_en)

        # Deterministic ground-truth safety sanitization across outputs
        def _sanitize_letter_output(txt: str) -> str:
            out = _clean_foreign_script_text(txt, cover_lang)
            if not str(((candidate.get("compensation") or {}).get("notice_period")) or "").strip():
                out = re.sub(r"[^.!?\n]*\b1 week after offer\b[^.!?\n]*[.!?]?", "", out, flags=re.I)
            return re.sub(r"\n{3,}", "\n\n", out).strip()

        cover_letter = _sanitize_letter_output(cover_letter)
        motivational_letter = _sanitize_letter_output(motivational_letter)

        return {
            "company": real_company or company,
            "title": job_title,
            "recipient_email": target_email or "",
            "subject": clean_subject,
            "cover_letter": cover_letter,
            "motivational_letter": motivational_letter,
            "dou_motivational_letter": motivational_letter,
            "human_tone_summary": narratives.get("human_tone_summary", ""),
            "motivation_statement": narratives.get("motivation_statement", ""),
            "cv_language": cv_lang,
            "letter_language": cover_lang,
            "docx_filename": cv_res["docx_filename"],
            "docx_url": cv_res["docx_url"],
            "pdf_filename": cv_res["pdf_filename"],
            "pdf_url": cv_res["pdf_url"],
            "html_filename": cv_res.get("html_filename"),
            "html_preview_url": cv_res.get("html_preview_url"),
            "rendered_html": cv_res.get("rendered_html"),
            "cv_sections": cv_res.get("cv_sections"),
            "bullet_diffs": cv_res.get("bullet_diffs") or [],
            "ats_parse_report": cv_res.get("ats_parse_report") or {},
            "matched_skills": matched,
            "missing_skills": missing,
            "docx_path": cv_res["docx_path"],
            "pdf_path": cv_res["pdf_path"],
        }


cv_generator_service = CVGeneratorService()
