import hashlib
import html as html_lib
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

from ..config import GENERATED_RESUMES_DIR, FONTS_DIR
from ..db.profile_repository import ground_truth_store, filter_spoken_language_entries
from ..services.gemini_service import GEORGIAN_SKILL_TRANSLATIONS
from ..services.scrapers.base_scraper import sanitize_company_name

logger = logging.getLogger(__name__)

_KA_TO_LATIN = {
    "ა": "a", "ბ": "b", "გ": "g", "დ": "d", "ე": "e", "ვ": "v", "ზ": "z", "თ": "t", "ი": "i",
    "კ": "k", "ლ": "l", "მ": "m", "ნ": "n", "ო": "o", "პ": "p", "ჟ": "zh", "რ": "r", "ს": "s",
    "ტ": "t", "უ": "u", "ფ": "p", "ქ": "k", "ღ": "gh", "ყ": "q", "შ": "sh", "ჩ": "ch", "ც": "ts",
    "ძ": "dz", "წ": "ts", "ჭ": "ch", "ხ": "kh", "ჯ": "j", "ჰ": "h",
}


def normalize_contact_href(raw: str, is_email: bool = False) -> str:
    """Normalizes LinkedIn, GitHub, Portfolio, or Email into an actionable href/mailto URL."""
    val = (raw or "").strip()
    if not val:
        return ""
    if is_email or ("@" in val and not val.startswith("http")):
        return val if val.startswith("mailto:") else f"mailto:{val}"
    if val.startswith(("http://", "https://")):
        return val
    return f"https://{val.lstrip('/')}"


def group_skills_into_ats_buckets(skills: List[str], cv_language: str = "en") -> List[tuple[str, List[str]]]:
    """Categorizes genuine candidate skills into 5 structured ATS scanner buckets without fabrication."""
    buckets = {
        "auto": [],
        "lang": [],
        "api": [],
        "infra": [],
        "mgmt": [],
    }
    has_qa_bucket = bool(buckets["auto"])
    mgmt_label = (
        ("მეთოდოლოგიები და ტესტ-მენეჯმენტი" if has_qa_bucket else "ძირითადი პროფესიული კომპეტენციები")
        if cv_language == "ka"
        else ("Methodologies & Test Management" if has_qa_bucket else "Core Domain Competencies")
    )
    labels = (
        {
            "auto": "ტესტ-ავტომატიზაცია და ფრეიმვორქები",
            "lang": "პროგრამირება და სკრიპტინგი",
            "api": "API და Backend ვალიდაცია",
            "infra": "CI/CD და ინფრასტრუქტურა",
            "mgmt": mgmt_label,
        }
        if cv_language == "ka"
        else {
            "auto": "Test Automation & Frameworks",
            "lang": "Programming & Technical Stack",
            "api": "API & Backend Validation",
            "infra": "CI/CD, Cloud & Infrastructure",
            "mgmt": mgmt_label,
        }
    )

    for raw in skills:
        s = str(raw or "").strip()
        if not s:
            continue
        low = s.lower()
        if any(k in low for k in ["playwright", "selenium", "cypress", "pytest", "robot framework", "appium", "testng", "junit", "webdriver", "კაპი", "ავტომატ"]):
            buckets["auto"].append(s)
        elif low in ("python", "typescript", "javascript", "sql", "bash", "java", "c#", "go", "html", "css") or any(k in low for k in ["python", "typescript", "javascript", "sql", "bash"]):
            buckets["lang"].append(s)
        elif any(k in low for k in ["postman", "rest api", "swagger", "openapi", "graphql", "k6", "jmeter", "http", "json", "xml", "chrome devtools", "api"]):
            buckets["api"].append(s)
        elif any(k in low for k in ["github actions", "gitlab ci", "ci/cd", "docker", "linux", "git", "jenkins", "kubernetes", "aws", "cloud"]):
            buckets["infra"].append(s)
        else:
            buckets["mgmt"].append(s)

    # Recompute mgmt label after classifying items so non-QA candidates don't get QA Test Management label
    if not buckets["auto"] and buckets["mgmt"]:
        labels["mgmt"] = "ძირითადი პროფესიული კომპეტენციები" if cv_language == "ka" else "Core Domain Competencies"

    return [(labels[key], vals) for key, vals in buckets.items() if vals]


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


def _clean_foreign_script_text(raw: Any, cv_language: str = "en") -> str:
    """Prevents foreign script contamination (e.g. Cyrillic 'Разработка') inside EN/KA CVs."""
    s = str(raw or "")
    if not s:
        return ""
    # Always strip accidental Cyrillic fragments from non-Russian CVs
    s = re.sub(r"[\u0400-\u04FF]+", "", s)
    if cv_language == "en":
        s = re.sub(r"[\u10A0-\u10FF]+", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return s.strip(" -–—•|")


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


def clean_bullets(highlights: Optional[List[Any]]) -> List[str]:
    """Filters out blank bullets and Markdown divider artifacts such as '--' or '---'."""
    if not highlights:
        return []
    result = []
    for h in highlights:
        s = str(h or "").strip()
        if s and not re.fullmatch(r"[-*_•–—.\s]+", s):
            result.append(s)
    return result


def resolve_candidate_headline(candidate: Dict[str, Any], skills: List[str], parsed_skills: Dict[str, Any]) -> str:
    """Returns candidate's true professional seniority/headline across ANY domain without QA bias."""
    ps = parsed_skills or {}
    industry = str(ps.get("target_industry") or "").lower()
    primary_role = str(ps.get("primary_role") or "").strip()
    raw_hl = str(candidate.get("headline") or "").strip()
    skills_blob = " ".join(skills).lower()

    if raw_hl and not any(w in raw_hl.lower() for w in ["intern", "trainee", "სტაჟიორ"]):
        if industry == "qa_tech" and any(k in skills_blob for k in ["playwright", "pytest", "selenium", "cypress"]) and "qa" in raw_hl.lower():
            return "QA Automation Engineer & SDET | Playwright • Python • API • CI/CD"
        return raw_hl
    if primary_role:
        return primary_role
    if industry == "qa_tech" or any(k in skills_blob for k in ["playwright", "pytest", "selenium", "cypress"]):
        return "QA Automation Engineer & SDET | Playwright • Python • API • CI/CD"
    return raw_hl or "Specialist"

RESUME_STRATEGIST_SYSTEM_PROMPT = """You are an elite technical CV strategist specializing in QA Automation and SDET careers.
Your goal is to tailor the candidate's existing experience to the provided vacancy description for maximum ATS keyword alignment and recruiter impact.

STRICT CONSTRAINTS (ZERO TOLERANCE FOR FABRICATION):
1. TRUTHFUL GROUNDING: Every bullet point, tool, framework, company, and timeline MUST come strictly from the candidate's verified profile. NEVER invent skills, tools, degrees, or certifications that the candidate does not possess.
2. NATURAL HUMANIZED TONE: Use an active, confident, and natural tone (implied first person: "Architected", "Implemented", "Automated", "Stabilized"). Avoid generic AI buzzwords ("visionary", "spearheaded synergy", "passionate maven").
3. ATS TERMINOLOGY MIRRORING: If the vacancy mentions "End-to-End UI Testing" and the candidate has "E2E Playwright Automation", match the vacancy's exact phrasing while retaining factual truth.
4. METRICS & IMPACT: Format technical achievements using Google's X-Y-Z formula: Accomplished [X] measured by [Y] by doing [Z] (e.g., "Reduced regression test cycle time by 45% by architecting parallelized Playwright suites in GitHub Actions").
5. CLEAN ATS FORMAT:
   - Header (Contact Info, Location, GitHub, LinkedIn)
   - Professional Summary (3 lines maximum: QA seniority, core automation framework, domain focus)
   - Technical Skill Matrix (Languages, Test Automation, API, CI/CD, Methodologies)
   - Professional Experience (Reverse chronological; 3-5 concise, metric-driven bullets per role)
   - Education & Certifications"""


def _register_unicode_font(prefer_georgian: bool = False) -> str:
    """
    Registers a Unicode TrueType font family (Normal, Bold, Italic, BoldItalic) in ReportLab
    with cross-platform support. Prioritizes Sylfaen when prefer_georgian=True for crisp Georgian rendering.
    """
    family_candidates: List[tuple[str, str, Optional[str], Optional[str], Optional[str]]] = []

    # 1. Check project assets/fonts directory for bundled fonts (Linux/Docker/Windows)
    if FONTS_DIR.exists():
        for f in sorted(FONTS_DIR.glob("*.ttf")):
            if any(tag in f.stem.lower() for tag in ("-bold", "-italic", "-oblique", "bold", "italic")):
                continue
            stem_base = f.stem.replace("-Regular", "")
            bold_c = next(
                (p for p in [f.with_name(f"{stem_base}-Bold.ttf"), f.with_name(f"{stem_base}Bold.ttf")] if p.exists()),
                None,
            )
            italic_c = next(
                (p for p in [f.with_name(f"{stem_base}-Italic.ttf"), f.with_name(f"{stem_base}-Oblique.ttf")] if p.exists()),
                None,
            )
            bi_c = next(
                (p for p in [f.with_name(f"{stem_base}-BoldItalic.ttf"), f.with_name(f"{stem_base}-BoldOblique.ttf")] if p.exists()),
                None,
            )
            family_candidates.append((f.stem, str(f), str(bold_c) if bold_c else None, str(italic_c) if italic_c else None, str(bi_c) if bi_c else None))

    sylfaen_tuple = (
        "Sylfaen",
        "C:/Windows/Fonts/sylfaen.ttf",
        None,
        None,
        None,
    )
    segoe_tuple = (
        "SegoeUI",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/segoeuii.ttf",
        "C:/Windows/Fonts/segoeuiz.ttf",
    )
    # 2. Cross-platform OS font families
    if prefer_georgian:
        family_candidates.extend([
            sylfaen_tuple,
            segoe_tuple,
        ])
    else:
        family_candidates.extend([
            segoe_tuple,
            sylfaen_tuple,
        ])

    family_candidates.extend([
        (
            "ArialUnicode",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/ariali.ttf",
            "C:/Windows/Fonts/arialbi.ttf",
        ),
        # Linux / Docker
        (
            "NotoSansGeorgian",
            "/usr/share/fonts/truetype/noto/NotoSansGeorgian-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansGeorgian-Bold.ttf",
            None,
            None,
        ),
        (
            "DejaVuSans",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        ),
        (
            "LiberationSans",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        ),
        # macOS
        (
            "ArialUnicodeMac",
            "/Library/Fonts/Arial Unicode.ttf",
            None,
            None,
            None,
        ),
        (
            "ArialMac",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
        ),
    ])

    for font_name, normal_path, bold_path, italic_path, bi_path in family_candidates:
        if not Path(normal_path).exists():
            continue
        try:
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, normal_path))
            bold_name = f"{font_name}-Bold"
            italic_name = f"{font_name}-Italic"
            bi_name = f"{font_name}-BoldItalic"
            b_file = bold_path if (bold_path and Path(bold_path).exists()) else normal_path
            i_file = italic_path if (italic_path and Path(italic_path).exists()) else normal_path
            bi_file = bi_path if (bi_path and Path(bi_path).exists()) else b_file
            for sub_name, sub_path in [(bold_name, b_file), (italic_name, i_file), (bi_name, bi_file)]:
                if sub_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(sub_name, sub_path))
            pdfmetrics.registerFontFamily(
                font_name,
                normal=font_name,
                bold=bold_name,
                italic=italic_name,
                boldItalic=bi_name,
            )
            return font_name
        except Exception as e:
            logger.debug(f"Could not register TTF family {font_name} ({normal_path}): {e}")
    return "Helvetica"


UNICODE_FONT_NAME = _register_unicode_font(prefer_georgian=False)
GEORGIAN_PDF_FONT_NAME = _register_unicode_font(prefer_georgian=True)


def safe_unicode_slug(text: str, default: str = "item", max_len: int = 24) -> str:
    """
    Produces a safe, cross-platform filename slug that preserves Unicode characters
    (Georgian ქართული, Cyrillic, Umlauts) and falls back to a deterministic hash
    if stripped of non-word symbols, avoiding empty filename bugs like CV___Role_EN.pdf.
    """
    if not text:
        return default
    slug = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    if not slug or len(slug.replace("_", "")) == 0:
        slug = f"{default}_{hashlib.md5(text.encode('utf-8', errors='ignore')).hexdigest()[:6]}"
    return slug[:max_len]


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
    """Normalizes a single grouped degree entry into clean header + detail metadata (no duplicates)."""
    deg = _clean_foreign_script_text(edu.get("degree") or "", "ka" if is_ka else "en")
    inst = _clean_foreign_script_text(edu.get("institution") or "", "ka" if is_ka else "en")
    dates = _clean_foreign_script_text(
        edu.get("dates") or edu.get("graduation_year") or "",
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
    if gpa and f"gpa" not in focus.lower():
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
    ) -> Dict[str, Any]:
        gt = vault_override if vault_override else ground_truth_store.get_data(owner_email=owner_email)
        ps = dict(gt.get("_parsed_skills") or {})
        raw_vault_md = str(gt.get("skills_md_raw") or "")
        has_explicit_md_override = bool(
            skills_md_override
            and str(skills_md_override).strip()
            and str(skills_md_override).strip() != raw_vault_md.strip()
        )
        skills_md = skills_md_override or raw_vault_md or ground_truth_store.get_skills_md(owner_email=owner_email)
        parsed_md = ground_truth_store.parse_profile_from_md(skills_md) if skills_md else {}

        candidate = dict(gt.get("candidate", {}))
        for fld in ("full_name", "headline", "email", "phone"):
            if has_explicit_md_override and parsed_md.get(fld):
                candidate[fld] = parsed_md[fld]
            elif not candidate.get(fld) and parsed_md.get(fld):
                candidate[fld] = parsed_md[fld]
        if parsed_md.get("location") and (has_explicit_md_override or not _format_candidate_location(candidate.get("location"))):
            loc_parts = [p.strip() for p in str(parsed_md["location"]).split(",", 1)]
            candidate["location"] = {
                "city": loc_parts[0],
                "country": loc_parts[1] if len(loc_parts) > 1 else "",
            }

        cand_links = dict(candidate.get("links") or {})
        if skills_md:
            gh_m = re.search(r"(https?://(?:www\.)?github\.com/[A-Za-z0-9._-]+/?)", skills_md, re.I)
            li_m = re.search(r"(https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9._-]+/?)", skills_md, re.I)
            if gh_m and (has_explicit_md_override or not cand_links.get("github")):
                cand_links["github"] = gh_m.group(1).rstrip("/")
            if li_m and (has_explicit_md_override or not cand_links.get("linkedin")):
                cand_links["linkedin"] = li_m.group(1).rstrip("/")
        candidate["links"] = cand_links

        if has_explicit_md_override:
            core_skills = parsed_md.get("skills") or (gt.get("skills", {}) or {}).get("core", []) or []
            raw_work_history = parsed_md.get("work_history") or gt.get("work_history", [])
            education = parsed_md.get("education") or gt.get("education", [])
            projects = parsed_md.get("projects") or gt.get("projects", [])
            certifications = parsed_md.get("certifications") or gt.get("certifications") or ps.get("courses_and_certifications") or []
        else:
            core_skills = (gt.get("skills", {}) or {}).get("core") or parsed_md.get("skills") or []
            raw_work_history = gt.get("work_history") if gt.get("work_history") else (parsed_md.get("work_history") or [])
            education = gt.get("education") if gt.get("education") else (parsed_md.get("education") or [])
            projects = gt.get("projects") if gt.get("projects") else (parsed_md.get("projects") or [])
            certifications = gt.get("certifications") or parsed_md.get("certifications") or ps.get("courses_and_certifications") or []

        # Sanitize target role, company & summary strictly into the target CV language
        clean_job_title = _clean_foreign_script_text(job_title, cv_language) or "Specialist"
        clean_summary = _clean_foreign_script_text(human_summary, cv_language)

        # Tailor bullet ordering per job description & matched requirements (ZERO fabrication)
        target_kws = list(dict.fromkeys((matched_skills or []) + (required_skills or []) + re.findall(r"[A-Za-z]{3,}", clean_job_title or "")))
        prioritized_wh: List[Dict[str, Any]] = []
        for job in raw_work_history:
            j_copy = dict(job)
            j_copy["role"] = _clean_foreign_script_text(j_copy.get("role") or "", cv_language)
            j_copy["company"] = _clean_foreign_script_text(j_copy.get("company") or "", cv_language)
            j_copy["highlights"] = [
                _clean_foreign_script_text(b, cv_language)
                for b in _prioritize_job_highlights(j_copy.get("highlights") or [], target_kws)
            ]
            j_copy["highlights"] = [b for b in j_copy["highlights"] if b]
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
        role_tag = "QA_Engineer" if (ps.get("target_industry", "qa_tech") == "qa_tech") else ascii_filename_slug(candidate_headline.split("|")[0], default="Specialist", max_len=18)
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

        pdf_filename = f"{base_name}.pdf"
        docx_filename = f"{base_name}.docx"
        html_filename = f"{base_name}.html"
        pdf_path = GENERATED_RESUMES_DIR / pdf_filename
        docx_path = GENERATED_RESUMES_DIR / docx_filename
        html_path = GENERATED_RESUMES_DIR / html_filename

        tailored_highlights = []
        for job in work_history:
            for h in clean_bullets(job.get("highlights"))[:2]:
                tailored_highlights.append(f"{job.get('role')} @ {job.get('company')}: {h}")

        # 1. Build Single-Column ATS HTML Preview
        html_content = self._build_cv_html(
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
        )
        html_path.write_text(html_content, encoding="utf-8")

        # 2. Build Clean Single-Column PDF via ReportLab
        self._build_reportlab_single_column_pdf(
            filepath=pdf_path,
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
        )

        # 3. Build Ready Microsoft Word (.docx) CV via python-docx
        self._build_docx_cv(
            filepath=docx_path,
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
        )

        start_date_str = "1 კვირა შეთავაზებიდან (1 week after offer)" if cv_language == "ka" else "1 week after offer"

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
        }

        return {
            "pdf_filename": pdf_filename,
            "pdf_url": f"/api/resumes/generated/{pdf_filename}",
            "docx_filename": docx_filename,
            "docx_url": f"/api/resumes/generated/{docx_filename}",
            "html_filename": html_filename,
            "html_preview_url": f"/api/resumes/generated/{html_filename}",
            "rendered_html": html_content,
            "pdf_path": str(pdf_path),
            "docx_path": str(docx_path),
            "cv_language": cv_language,
            "candidate_name": candidate.get("full_name", "Candidate"),
            "target_role": candidate_headline,
            "human_tone_summary": human_summary,
            "applicant_summary": human_summary,
            "motivation_statement": motivation_statement,
            "dou_motivational_letter": dou_motivational_letter,
            "cv_sections": cv_sections,
            "tailored_highlights": tailored_highlights,
            "ats_keywords_covered": matched_skills or display_skills[:8],
            "start_date_default": start_date_str,
            "expected_salary": "Negotiable / Market Rate",
        }

    def render_cv_from_sections(
        self,
        sections: Dict[str, Any],
        base_name_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Re-renders HTML, PDF, and DOCX cleanly from user-edited structured CV JSON sections."""
        cand = dict(sections.get("candidate") or {})
        headline = str(sections.get("headline") or cand.get("headline") or sections.get("target_role") or "Specialist").strip()
        target_role = str(sections.get("target_role") or headline).strip()
        target_company = str(sections.get("target_company") or "Tailored").strip()
        cv_language = str(sections.get("cv_language") or "en").strip() or "en"
        cv_style = str(sections.get("cv_style") or "tailored").strip() or "tailored"
        human_summary = str(sections.get("summary") or "").strip()
        display_skills = [str(s).strip() for s in (sections.get("skills") or []) if str(s).strip()]
        work_history = []
        for raw_w in (sections.get("work_history") or []):
            if not isinstance(raw_w, dict):
                continue
            w_copy = dict(raw_w)
            w_bullets = w_copy.get("highlights") or w_copy.get("bullets") or []
            w_copy["highlights"] = list(w_bullets)
            w_copy["bullets"] = list(w_bullets)
            work_history.append(w_copy)
        education = list(sections.get("education") or [])
        projects = list(sections.get("projects") or [])
        certifications = list(sections.get("certifications") or [])
        languages_line = str(sections.get("languages_line") or _format_candidate_languages(cand, "", cv_language == "ka"))

        if base_name_override:
            base_name = Path(base_name_override).stem
        else:
            cand_slug = ascii_filename_slug(str(cand.get("full_name") or "Candidate"), default="Candidate", max_len=24)
            role_slug = ascii_filename_slug(target_role, default="CV", max_len=20)
            short_id = uuid.uuid4().hex[:6]
            base_name = f"{cand_slug}_{role_slug}_{short_id}_Edited"

        pdf_filename = f"{base_name}.pdf"
        docx_filename = f"{base_name}.docx"
        html_filename = f"{base_name}.html"
        pdf_path = GENERATED_RESUMES_DIR / pdf_filename
        docx_path = GENERATED_RESUMES_DIR / docx_filename
        html_path = GENERATED_RESUMES_DIR / html_filename

        html_content = self._build_cv_html(
            candidate=cand,
            candidate_headline=headline,
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
        html_path.write_text(html_content, encoding="utf-8")

        self._build_reportlab_single_column_pdf(
            filepath=pdf_path,
            candidate=cand,
            candidate_headline=headline,
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

        self._build_docx_cv(
            filepath=docx_path,
            candidate=cand,
            candidate_headline=headline,
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

        return {
            "pdf_filename": pdf_filename,
            "docx_filename": docx_filename,
            "html_filename": html_filename,
            "pdf_url": f"/api/resumes/generated/{pdf_filename}",
            "docx_url": f"/api/resumes/generated/{docx_filename}",
            "html_preview_url": f"/api/resumes/generated/{html_filename}",
            "rendered_html": html_content,
        }

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
            except Exception:
                pass
        for sec in doc.sections:
            sec.top_margin = Inches(0.55)
            sec.bottom_margin = Inches(0.55)
            sec.left_margin = Inches(0.65)
            sec.right_margin = Inches(0.65)

        accent = RGBColor(0x0F, 0x17, 0x2A) if cv_style == "ats" else RGBColor(0x03, 0x69, 0xA1)
        subtle = RGBColor(0x47, 0x55, 0x69)

        full_name = _clean_foreign_script_text(candidate.get("full_name", "Candidate"), cv_language) or str(candidate.get("full_name", "Candidate"))
        email = str(candidate.get("email") or "").strip()
        if email == "candidate@example.com":
            email = ""
        raw_phone = str(candidate.get("phone") or "").strip()
        phone = "" if (not raw_phone or "+000" in raw_phone or re.fullmatch(r"[+\s0()-]+", raw_phone)) else raw_phone
        loc = _clean_foreign_script_text(_format_candidate_location(candidate.get("location")), cv_language)
        links = candidate.get("links", {}) if isinstance(candidate.get("links"), dict) else {}
        linkedin = str(links.get("linkedin", "")).strip()
        github = str(links.get("github", "")).strip()
        portfolio = str(links.get("portfolio", "")).strip()

        p_name = doc.add_paragraph()
        p_name.paragraph_format.space_after = Pt(2)
        r_name = p_name.add_run(full_name)
        r_name.bold = True
        r_name.font.size = Pt(18)
        r_name.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
        _apply_docx_run_font(r_name, font_family)

        role_heading = _clean_foreign_script_text(candidate_headline or str(candidate.get("headline") or "Specialist"), cv_language) or "Specialist"
        p_role = doc.add_paragraph()
        p_role.paragraph_format.space_after = Pt(3)
        r_role = p_role.add_run(role_heading)
        r_role.bold = True
        r_role.font.size = Pt(11.5)
        r_role.font.color.rgb = accent
        _apply_docx_run_font(r_role, font_family)

        p_contact = doc.add_paragraph()
        p_contact.paragraph_format.space_after = Pt(8)
        contact_items: List[tuple[str, str]] = []
        if loc:
            contact_items.append((loc, ""))
        if phone:
            contact_items.append((phone, ""))
        if email:
            contact_items.append((email, normalize_contact_href(email, is_email=True)))
        if linkedin:
            contact_items.append((linkedin, normalize_contact_href(linkedin)))
        if github:
            contact_items.append((github, normalize_contact_href(github)))
        if portfolio:
            contact_items.append((portfolio, normalize_contact_href(portfolio)))

        for idx, (label, href) in enumerate(contact_items):
            if idx > 0:
                sep = p_contact.add_run("  |  ")
                sep.font.size = Pt(9.5)
                sep.font.color.rgb = subtle
                _apply_docx_run_font(sep, font_family)
            if href:
                _add_docx_hyperlink(p_contact, label, href, font_name=font_family)
            else:
                rt = p_contact.add_run(label)
                rt.font.size = Pt(9.5)
                rt.font.color.rgb = subtle
                _apply_docx_run_font(rt, font_family)

        def add_section_heading(title_text: str) -> None:
            p_h = doc.add_paragraph()
            p_h.paragraph_format.space_before = Pt(8)
            p_h.paragraph_format.space_after = Pt(3)
            run = p_h.add_run(title_text)
            run.bold = True
            run.font.size = Pt(10.5)
            run.font.color.rgb = accent
            _apply_docx_run_font(run, font_family)

        lbl_summary = "პროფესიული მიმოხილვა" if is_ka else ("EXECUTIVE PROFILE" if cv_style == "recruiter" else "PROFESSIONAL SUMMARY")
        lbl_skills = "ტექნიკური კომპეტენციები და სტეკი" if is_ka else "TECHNICAL SKILLS & STACK"
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "PROFESSIONAL EXPERIENCE"
        lbl_proj = "რელევანტური პროექტები" if is_ka else "RELEVANT PROJECTS"
        lbl_edu = "განათლება და სპეციალიზებული ტრენინგები" if is_ka else "EDUCATION & SPECIALIZED TRAINING"
        lbl_lang = "ენები" if is_ka else "LANGUAGES"

        add_section_heading(lbl_summary)
        p_sum = doc.add_paragraph(_clean_foreign_script_text(human_summary, cv_language))
        p_sum.paragraph_format.space_after = Pt(4)
        for r in p_sum.runs:
            r.font.size = Pt(10)
            _apply_docx_run_font(r, font_family)

        add_section_heading(lbl_skills)
        grouped = group_skills_into_ats_buckets(display_skills[:60], cv_language=cv_language)
        if grouped:
            for bucket_title, bucket_items in grouped:
                p_sk = doc.add_paragraph(style="List Bullet")
                p_sk.paragraph_format.space_after = Pt(2)
                rk = p_sk.add_run(f"{bucket_title}: ")
                rk.bold = True
                rk.font.size = Pt(9.5)
                _apply_docx_run_font(rk, font_family)
                rv = p_sk.add_run(", ".join(bucket_items))
                rv.font.size = Pt(9.5)
                _apply_docx_run_font(rv, font_family)
        else:
            p_sk = doc.add_paragraph(", ".join(display_skills[:24]) or "Manual QA, REST API, Test Design")
            p_sk.paragraph_format.space_after = Pt(4)
            for r in p_sk.runs:
                r.font.size = Pt(10)
                _apply_docx_run_font(r, font_family)

        if work_history:
            add_section_heading(lbl_exp)
            for job in work_history[:5]:
                dates = f"{job.get('start_date', '')} – {job.get('end_date', '')}".strip(" –")
                loc_j = _clean_foreign_script_text(job.get("location") or "", cv_language)
                meta_tail = f"  •  {dates}" if dates else ""
                if loc_j:
                    meta_tail += f" ({loc_j})"
                p_j = doc.add_paragraph()
                p_j.paragraph_format.space_before = Pt(4)
                p_j.paragraph_format.space_after = Pt(2)
                rj = p_j.add_run(f"{job.get('role', '')} | {job.get('company', '')}")
                rj.bold = True
                rj.font.size = Pt(10.5)
                _apply_docx_run_font(rj, font_family)
                if meta_tail:
                    rd = p_j.add_run(meta_tail)
                    rd.font.size = Pt(9.5)
                    rd.font.color.rgb = subtle
                    _apply_docx_run_font(rd, font_family)
                for b in clean_bullets(job.get("highlights"))[:5]:
                    p_b = doc.add_paragraph(style="List Bullet")
                    p_b.paragraph_format.space_after = Pt(2)
                    rb = p_b.add_run(str(b))
                    rb.font.size = Pt(9.5)
                    _apply_docx_run_font(rb, font_family)

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
                hdr_txt = f"{p_t} | {p_org}" if p_org else p_t
                rp = p_hdr.add_run(hdr_txt)
                rp.bold = True
                rp.font.size = Pt(10)
                _apply_docx_run_font(rp, font_family)
                if p_dt:
                    rp_dt = p_hdr.add_run(f"  •  {p_dt}")
                    rp_dt.font.size = Pt(9)
                    rp_dt.font.color.rgb = subtle
                    _apply_docx_run_font(rp_dt, font_family)
                for b in clean_bullets(proj.get("highlights"))[:3]:
                    p_pb = doc.add_paragraph(style="List Bullet")
                    p_pb.paragraph_format.space_after = Pt(1.5)
                    rpb = p_pb.add_run(_clean_foreign_script_text(b, cv_language))
                    rpb.font.size = Pt(9.5)
                    _apply_docx_run_font(rpb, font_family)

        if education or certifications:
            add_section_heading(lbl_edu)
            for edu in (education or []):
                row = _format_education_row(edu, is_ka)
                if row["title"]:
                    p_e = doc.add_paragraph(style="List Bullet")
                    p_e.paragraph_format.space_after = Pt(2)
                    re_t = p_e.add_run(row["title"])
                    re_t.bold = True
                    re_t.font.size = Pt(9.5)
                    _apply_docx_run_font(re_t, font_family)
                    if row["detail"]:
                        re_d = p_e.add_run(f" — {row['detail']}")
                        re_d.font.size = Pt(9.5)
                        _apply_docx_run_font(re_d, font_family)
            for cert in (certifications or [])[:4]:
                cert_c = _clean_foreign_script_text(cert, cv_language)
                if cert_c:
                    p_c = doc.add_paragraph(style="List Bullet")
                    p_c.paragraph_format.space_after = Pt(2)
                    rc = p_c.add_run(cert_c)
                    rc.font.size = Pt(9.5)
                    _apply_docx_run_font(rc, font_family)

        langs_line = languages_line or _format_candidate_languages(candidate, "", is_ka)
        if langs_line:
            add_section_heading(lbl_lang)
            p_lang = doc.add_paragraph(langs_line)
            p_lang.paragraph_format.space_after = Pt(2)
            for r in p_lang.runs:
                r.font.size = Pt(9.5)
                _apply_docx_run_font(r, font_family)

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

        styles = getSampleStyleSheet()
        header_style = ParagraphStyle(
            "CVHeaderName",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=2,
        )
        role_style = ParagraphStyle(
            "CVTargetRole",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=11.5,
            leading=15,
            textColor=colors.HexColor("#0284c7"),
            spaceAfter=4,
        )
        contact_style = ParagraphStyle(
            "CVContact",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#475569"),
            spaceAfter=6,
        )
        sec_title_style = ParagraphStyle(
            "CVSectionTitle",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#0369a1"),
            spaceBefore=8,
            spaceAfter=4,
        )
        body_style = ParagraphStyle(
            "CVBody",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=4,
        )
        bullet_style = ParagraphStyle(
            "CVBullet",
            parent=body_style,
            leftIndent=12,
            spaceAfter=2.5,
        )

        full_name = escape(str(candidate.get("full_name", "Candidate")))
        raw_email = str(candidate.get("email", "candidate@example.com")).strip()
        email = escape(raw_email) if raw_email and raw_email != "candidate@example.com" else ""
        raw_phone = str(candidate.get("phone") or "").strip()
        phone = "" if (not raw_phone or "+000" in raw_phone or re.fullmatch(r"[+\s0()-]+", raw_phone)) else escape(raw_phone)
        loc = escape(_format_candidate_location(candidate.get("location")))
        links = candidate.get("links", {}) if isinstance(candidate.get("links"), dict) else {}
        raw_linkedin = str(links.get("linkedin", "")).strip()
        raw_github = str(links.get("github", "")).strip()
        raw_portfolio = str(links.get("portfolio", "")).strip()

        pdf_links = []
        if email:
            pdf_links.append(
                f'<link href="{escape(normalize_contact_href(raw_email, is_email=True))}" color="#0369a1"><u>{email}</u></link>'
            )
        if phone:
            pdf_links.append(phone)
        if loc:
            pdf_links.append(loc)
        if raw_linkedin:
            pdf_links.append(
                f'<link href="{escape(normalize_contact_href(raw_linkedin))}" color="#0369a1"><u>{escape(raw_linkedin)}</u></link>'
            )
        if raw_github:
            pdf_links.append(
                f'<link href="{escape(normalize_contact_href(raw_github))}" color="#0369a1"><u>{escape(raw_github)}</u></link>'
            )
        if raw_portfolio:
            pdf_links.append(
                f'<link href="{escape(normalize_contact_href(raw_portfolio))}" color="#0369a1"><u>{escape(raw_portfolio)}</u></link>'
            )

        lbl_summary = "პროფესიული მიმოხილვა" if is_ka else ("EXECUTIVE PROFILE" if cv_style == "recruiter" else "PROFESSIONAL SUMMARY")
        lbl_skills = "ტექნიკური კომპეტენციები და სტეკი" if is_ka else "TECHNICAL SKILLS & STACK"
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "PROFESSIONAL EXPERIENCE"
        lbl_proj = "რელევანტური პროექტები" if is_ka else "RELEVANT PROJECTS"
        lbl_edu = "განათლება და სპეციალიზებული ტრენინგები" if is_ka else "EDUCATION & SPECIALIZED TRAINING"
        lbl_lang = "ენები" if is_ka else "LANGUAGES"

        story = []

        # 1. Header (ALWAYS showcase true candidate persona headline without ugly tags)
        role_display = _clean_foreign_script_text(candidate_headline or str(candidate.get("headline") or "Specialist"), cv_language) or "Specialist"
        story.append(Paragraph(f"<b>{full_name}</b>", header_style))
        story.append(Paragraph(escape(role_display), role_style))
        if pdf_links:
            story.append(Paragraph("  |  ".join(x for x in pdf_links if x), contact_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=6))

        # 2. Summary
        story.append(Paragraph(f"<b>{lbl_summary}</b>", sec_title_style))
        story.append(Paragraph(escape(_clean_foreign_script_text(human_summary, cv_language)), body_style))

        # 3. Technical Skills Matrix (grouped by ATS domains)
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
        story.append(Paragraph(f"<b>{lbl_skills}</b>", sec_title_style))
        grouped_pdf = group_skills_into_ats_buckets(display_skills[:60], cv_language=cv_language)
        if grouped_pdf:
            for b_title, b_items in grouped_pdf:
                items_esc = ", ".join(escape(x) for x in b_items)
                story.append(Paragraph(f"<b>{escape(b_title)}:</b> {items_esc}", body_style))
        else:
            skills_text = " • ".join(escape(s) for s in display_skills[:20])
            story.append(Paragraph(skills_text, body_style))

        # 4. Work Experience
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
        story.append(Paragraph(f"<b>{lbl_exp}</b>", sec_title_style))
        for job in work_history[:4]:
            r_title = escape(str(job.get("role", "")))
            r_comp = escape(str(job.get("company", "")))
            r_dates = escape(f"{job.get('start_date', '')} - {job.get('end_date', '')}".strip(" -"))
            story.append(Paragraph(f"<b>{r_title}</b> | {r_comp} ({r_dates})", body_style))
            for b in clean_bullets(job.get("highlights"))[:4]:
                story.append(Paragraph(f"• {escape(str(b))}", bullet_style))
            story.append(Spacer(1, 3))

        # 5. Relevant Projects (when present)
        if projects:
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
            story.append(Paragraph(f"<b>{lbl_proj}</b>", sec_title_style))
            for proj in projects[:3]:
                if not isinstance(proj, dict):
                    continue
                p_t = escape(_clean_foreign_script_text(proj.get("title") or "", cv_language))
                p_org = escape(_clean_foreign_script_text(proj.get("organization") or "", cv_language))
                p_dt = escape(_clean_foreign_script_text(proj.get("dates") or "", cv_language))
                hdr = f"<b>{p_t}</b>"
                if p_org:
                    hdr += f" | {p_org}"
                if p_dt:
                    hdr += f" ({p_dt})"
                story.append(Paragraph(hdr, body_style))
                for b in clean_bullets(proj.get("highlights"))[:3]:
                    story.append(Paragraph(f"• {escape(_clean_foreign_script_text(b, cv_language))}", bullet_style))

        # 6. Grouped Education & Specialized Training
        if education or certifications:
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
            story.append(Paragraph(f"<b>{lbl_edu}</b>", sec_title_style))
            for edu in (education or []):
                row = _format_education_row(edu, is_ka)
                if row["title"]:
                    txt = f"• <b>{escape(row['title'])}</b>"
                    if row["detail"]:
                        txt += f" — {escape(row['detail'])}"
                    story.append(Paragraph(txt, body_style))
            for cert in (certifications or [])[:4]:
                cert_c = _clean_foreign_script_text(cert, cv_language)
                if cert_c:
                    story.append(Paragraph(f"• {escape(cert_c)}", body_style))

        # 7. Spoken Languages ONLY
        lang_line = languages_line or _format_candidate_languages(candidate, "", is_ka)
        if lang_line:
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
            story.append(Paragraph(f"<b>{lbl_lang}</b>", sec_title_style))
            story.append(Paragraph(escape(lang_line), body_style))

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
        esc = lambda v: html_lib.escape(str(v or ""), quote=True)
        full_name = str(candidate.get("full_name", "Candidate"))
        raw_email = str(candidate.get("email") or "").strip()
        email = "" if raw_email == "candidate@example.com" else raw_email
        raw_phone = str(candidate.get("phone") or "").strip()
        phone = "" if (not raw_phone or "+000" in raw_phone or re.fullmatch(r"[+\s0()-]+", raw_phone)) else raw_phone
        loc = _format_candidate_location(candidate.get("location"))
        links = candidate.get("links", {}) if isinstance(candidate.get("links"), dict) else {}
        linkedin = str(links.get("linkedin", "")).strip()
        github = str(links.get("github", "")).strip()
        portfolio = str(links.get("portfolio", "")).strip()

        html_contact_parts = []
        if email:
            html_contact_parts.append(
                f'<a href="{esc(normalize_contact_href(email, is_email=True))}" style="color:#0369a1;">{esc(email)}</a>'
            )
        if phone:
            html_contact_parts.append(esc(phone))
        if loc:
            html_contact_parts.append(esc(loc))
        if linkedin:
            html_contact_parts.append(
                f'<a href="{esc(normalize_contact_href(linkedin))}" target="_blank" style="color:#0369a1;">{esc(linkedin)}</a>'
            )
        if github:
            html_contact_parts.append(
                f'<a href="{esc(normalize_contact_href(github))}" target="_blank" style="color:#0369a1;">{esc(github)}</a>'
            )
        if portfolio:
            html_contact_parts.append(
                f'<a href="{esc(normalize_contact_href(portfolio))}" target="_blank" style="color:#0369a1;">{esc(portfolio)}</a>'
            )
        html_contact_line = " &nbsp;•&nbsp; ".join(x for x in html_contact_parts if x)

        lbl_summary = "პროფესიული მიმოხილვა" if is_ka else ("EXECUTIVE PROFILE" if cv_style == "recruiter" else "PROFESSIONAL SUMMARY")
        lbl_skills = "ტექნიკური კომპეტენციები და სტეკი" if is_ka else "TECHNICAL SKILLS & STACK"
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "PROFESSIONAL EXPERIENCE"
        lbl_proj = "რელევანტური პროექტები" if is_ka else "RELEVANT PROJECTS"
        lbl_edu = "განათლება და სპეციალიზებული ტრენინგები" if is_ka else "EDUCATION & SPECIALIZED TRAINING"
        lbl_lang = "ენები" if is_ka else "LANGUAGES"

        grouped_html = group_skills_into_ats_buckets(display_skills[:60], cv_language=cv_language)
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
        for job in work_history[:4]:
            bullets = "".join(f"<li style='margin-bottom:4px;'>{esc(b)}</li>" for b in clean_bullets(job.get("highlights"))[:4])
            dates = f"{job.get('start_date', '')} – {job.get('end_date', '')}".strip(" –")
            exp_blocks += f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex; justify-content:space-between; align-items:baseline;">
                <strong style="font-size:13px; color:#0f172a;">{esc(job.get('role', ''))} | <span style="color:#0284c7;">{esc(job.get('company', ''))}</span></strong>
                <span style="font-size:11px; color:#64748b;">{esc(dates)}</span>
              </div>
              <ul style="margin:6px 0 0 18px; padding:0; font-size:12px; color:#334155; line-height:1.5;">
                {bullets}
              </ul>
            </div>
            """

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

    <div class="section-title">{lbl_exp}</div>
    {exp_blocks}

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
    ) -> Dict[str, Any]:
        """
        Generates a complete, ready-to-send email package for any vacancy:
        - Tailored Word (.docx) and PDF CV built from the candidate's live skills.md
        - Job-specific Cover Letter (Georgian for Georgian postings, English otherwise)
        - Clean email subject with [Name] resolved to actual candidate full_name
        """
        from .gemini_service import gemini_service
        from .matcher_service import matcher_service

        gt = ground_truth_store.get_data(owner_email=owner_email)
        candidate = dict(gt.get("candidate", {}))
        ps = gt.get("parsed_skills_taxonomy") or {}
        skills_md = skills_md_override or gt.get("skills_md_raw") or ""
        cand_name = str(candidate.get("full_name") or "Candidate").strip()
        raw_phone = str(candidate.get("phone") or "").strip(" -\t\r\n")
        # Never inject placeholder '+000 000 0000' or '-' into outgoing emails
        cand_phone = "" if (not raw_phone or re.fullmatch(r"[+\s0()-]+", raw_phone) or "000 000" in raw_phone) else raw_phone
        links = candidate.get("links", {}) if isinstance(candidate.get("links"), dict) else {}
        cand_linkedin = str(links.get("linkedin") or "").strip(" -\t\r\n")

        target_industry = str(ps.get("target_industry") or "qa_tech").lower()
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
        cand_skills = [str(s) for s in (gt.get("skills", {}).get("core") or [])]
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
        )

        # Clean subject & sanitize company (never address location strings, portal chrome, or foreign-script leaks)
        real_company = _clean_foreign_script_text(
            sanitize_company_name(company, target_email=target_email, fallback=""),
            cover_lang,
        )

        # Dynamic target domain identification: never leak QA terms into Support/Receptionist/Healthcare/Finance
        target_role_lower = f"{job_title} {description[:500]}".lower()
        if any(w in target_role_lower for w in ["მხარდაჭერ", "მონიტორინგ", "support", "monitoring", "helpdesk", "service desk", "it support"]):
            effective_domain = "technical_support"
        elif any(w in target_role_lower for w in ["რეცეფციონ", "რეგისტრატორ", "მიმღებ", "reception", "front desk", "hospitality", "hotel", "სასტუმრო"]):
            effective_domain = "receptionist_hospitality"
        elif any(w in target_role_lower for w in ["პაციენტ", "კლინიკ", "საავადმყოფ", "სამედიცინო", "patient", "clinic", "hospital", "medical"]):
            effective_domain = "healthcare_hospital"
        elif any(w in target_role_lower for w in ["მომხმარებელ", "ქოლ-ცენტრ", "operator", "customer", "call center", "client service"]):
            effective_domain = "customer_service"
        elif any(w in target_role_lower for w in ["ლოჯისტიკ", "საწყობ", "მარაგ", "ტვირთ", "logistics", "supply chain", "procurement", "warehouse"]):
            effective_domain = "logistics_supply_chain"
        elif any(w in target_role_lower for w in ["ბუღალტერ", "ფინანს", "აუდიტ", "accountant", "finance", "accounting", "auditor"]):
            effective_domain = "finance_accounting"
        elif any(w in target_role_lower for w in ["მარკეტინგ", "marketing", "smm", "content"]):
            effective_domain = "marketing_growth"
        elif any(w in target_role_lower for w in ["გაყიდვ", "sales", "account executive", "business development"]):
            effective_domain = "sales_bd"
        elif any(w in target_role_lower for w in ["qa", "quality assurance", "tester", "ტესტ", "ავტომატიზ", "test engineer"]):
            effective_domain = "qa_tech"
        else:
            effective_domain = target_industry if target_industry != "hospitality_reception" else "receptionist_hospitality"

        clean_subject = ""
        if email_subject_template:
            clean_subject = re.sub(r"\[(?:your\s+)?(?:name|სახელი(?:\s*გვარი)?|full\s*name)\]", cand_name, email_subject_template, flags=re.I).strip()
            clean_subject = clean_subject.replace("[Name]", cand_name).replace("[name]", cand_name)
            if effective_domain != "qa_tech" and "qa" in clean_subject.lower() and "qa" not in job_title.lower():
                clean_subject = f"{job_title} — {cand_name}"
            if "qa automation engineer" in clean_subject.lower() and "automation" not in job_title.lower():
                clean_subject = f"{job_title} — {cand_name}"
        if not clean_subject:
            clean_subject = f"{job_title} — {cand_name}" if cover_lang == "ka" else f"Application for {job_title} — {cand_name}"

        # Clean sign-off: excludes email & excludes placeholder phones/dashes
        contact_footer = "\n".join(x for x in [cand_name, cand_phone, cand_linkedin] if x and x != "-")

        # Domain-aware skills highlight: never inject test runners or automation tools into hospitality/admin cover letters
        is_non_tech_domain = effective_domain in (
            "receptionist_hospitality", "healthcare_hospital", "customer_service", "logistics_supply_chain"
        )
        if is_non_tech_domain:
            tech_noise = {"playwright", "selenium", "cypress", "appium", "pytest", "junit", "postman", "jmeter", "webdriver", "qa", "automation", "regression", "api testing", "test cases"}
            clean_cand_skills = [s for s in cand_skills if not any(t in s.lower() for t in tech_noise)]
            clean_matched = [r for r in matched if not any(t in r.lower() for t in tech_noise)]
            if clean_matched:
                skills_highlight = ", ".join(clean_matched[:5])
            elif clean_cand_skills:
                skills_highlight = ", ".join(clean_cand_skills[:5])
            else:
                skills_highlight = (
                    "სტუმართმოყვარეობა, ორგანიზებულობა, კომუნიკაცია"
                    if cover_lang == "ka"
                    else "multilingual communication, organization, customer care"
                )
        else:
            skills_highlight = ", ".join(matched[:6]) if matched else ", ".join(cand_skills[:6])

        # Extract authentic prior companies & experience years from ground truth (never invent employers)
        work_companies = []
        for w in (gt.get("work_history") or []):
            comp_raw = sanitize_company_name(w.get("company"), fallback="")
            if comp_raw and comp_raw not in work_companies:
                work_companies.append(comp_raw)
        companies_phrase = ", ".join(work_companies[:3])
        exp_years = ps.get("years_of_experience") or 1.5

        # Domain-specific focus descriptions (NEVER leak QA terms into Hospitality/Logistics/Finance/Healthcare emails!)
        domain_focus_ka = {
            "technical_support": (
                "ტექნიკური მხარდაჭერის, მონიტორინგისა და სისტემური ინციდენტების მართვის მიმართულებით",
                "ინციდენტების ოპერატიულ დიაგნოსტიკას (SQL, Jira, API), სისტემური ლოგების მონიტორინგსა და მომხმარებელთა მოთხოვნების სწრაფ მოგვარებას",
                "სისტემების სტაბილურ მუშაობასა და მაღალი ხარისხის ტექნიკური მხარდაჭერის უზრუნველყოფაში",
            ),
            "receptionist_hospitality": ("სტუმარმასპინძლობის, Front Desk ოპერაციებისა და სტუმრების მომსახურების სფეროში", "სტუმრების მაღალი სტანდარტით მიღებას, ჯავშნების გამართულ კოორდინაციას და მშვიდ, პროფესიონალურ კომუნიკაციას", "სერვისის ხარისხისა და სტუმრების კმაყოფილების ზრდაში"),
            "healthcare_hospital": ("პაციენტთა კოორდინაციის, სამედიცინო რეგისტრაციისა და კლინიკის ადმინისტრირების მიმართულებით", "პაციენტების სწრაფ და ყურადღებიან მიღებას, სადაზღვევო პროცესებისა და ექიმების განრიგის ზუსტ მართვას", "კლინიკის ადმინისტრაციული პროცესების გამართულობაში"),
            "customer_service": ("მომხმარებელთა მომსახურების, მხარდაჭერისა და კლიენტებთან კომუნიკაციის მიმართულებით", "მომხმარებელთა მომართვების სწრაფ გადაჭრას, CRM სისტემების ეფექტურ მართვასა და მაღალი CSAT სტანდარტის შენარჩუნებას", "მომხმარებელთა გამოცდილების გაუმჯობესებაში"),
            "logistics_supply_chain": ("ლოჯისტიკის, მიწოდების ჯაჭვისა და შესყიდვების კოორდინაციის მიმართულებით", "ტვირთების გადაზიდვის კოორდინაციას, მარაგებისა და დოკუმენტაციის კონტროლს და მომწოდებლებთან ოპერატიულ მუშაობას", "ლოჯისტიკური ოპერაციების სისწრაფესა და სიზუსტეში"),
            "finance_accounting": ("ფინანსების, ბუღალტრული აღრიცხვისა და ანალიტიკის მიმართულებით", "ფინანსური ოპერაციების აღრიცხვას, რეპორტინგის მომზადებასა და მონაცემების ზუსტ კონტროლს", "ფინანსური პროცესების სიზუსტესა და გამართულობაში"),
            "marketing_growth": ("მარკეტინგის, ციფრული კამპანიებისა და ბრენდის კომუნიკაციის მიმართულებით", "ციფრული კამპანიების დაგეგმვას, კონტენტის მართვასა და შედეგების ანალიტიკას", "მარკეტინგული მიზნებისა და ზრდის მიღწევაში"),
            "sales_bd": ("გაყიდვების, კლიენტების მოზიდვისა და ბიზნესის განვითარების მიმართულებით", "პარტნიორებთან ურთიერთობების მართვას, მოლაპარაკებების წარმოებასა და გაყიდვების გეგმების შესრულებას", "გაყიდვებისა და კლიენტთა ბაზის გაფართოებაში"),
            "qa_tech": ("QA ავტომატიზაციასა და API/Manual ტესტირებაში", "ავტომატიზებული რეგრესიული ტესტების შექმნას, REST API კონტრაქტების შემოწმებასა და ხარვეზების ადრეულ აღმოჩენას", "ტესტირებისა და პროდუქტის ხარისხის სტაბილურობაში"),
        }
        domain_focus_en = {
            "technical_support": (
                "technical support, systems monitoring, and incident triage",
                "diagnosing system logs, validating API/SQL data flows, and resolving client escalations within SLA",
                "support responsiveness, system reliability, and customer satisfaction",
            ),
            "receptionist_hospitality": ("front office operations and guest relations", "delivering seamless check-ins, accurate reservation coordination, and warm multilingual hospitality", "guest satisfaction and smooth front-desk operations"),
            "healthcare_hospital": ("patient coordination and clinical administration", "managing patient intake, appointment scheduling, and insurance authorizations with accuracy and care", "patient service quality and smooth clinic workflows"),
            "customer_service": ("customer support and client operations", "resolving escalations cleanly across chat, phone, and CRM channels while sustaining high CSAT", "support responsiveness and client retention"),
            "logistics_supply_chain": ("logistics, procurement, and supply chain operations", "coordinating shipments, supplier schedules, inventory tracking, and customs documentation cleanly", "supply chain efficiency and on-time delivery"),
            "finance_accounting": ("finance, accounting, and analytical reporting", "maintaining accurate financial reconciliations, reporting workflows, and compliance controls", "financial accuracy and operational clarity"),
            "marketing_growth": ("digital marketing and campaign growth", "planning acquisition campaigns, managing content workflows, and tracking conversion analytics", "brand reach and measurable growth"),
            "sales_bd": ("B2B sales and account management", "building client pipelines, managing onboarding, and hitting revenue targets through consultative outreach", "client acquisition and revenue execution"),
            "qa_tech": ("QA automation and manual/API test engineering", "automating regression coverage, validating REST API contracts, and catching critical defects before release", "release confidence and test stability"),
        }

        # Map domain focus safely (fallback for any custom domain without mentioning QA!)
        ind_key = effective_domain

        ka_tuple = domain_focus_ka.get(
            ind_key,
            (
                f"{detected_industry}-ის მიმართულებით",
                f"ყოველდღიური სამუშაო პროცესების გამართულ შესრულებასა და მაღალი ხარისხის შედეგების მიღწევას ({skills_highlight})",
                "თქვენი გუნდის ოპერაციულ ეფექტიანობასა და წარმატებაში",
            ),
        )
        en_tuple = domain_focus_en.get(
            ind_key,
            (
                f"{detected_industry}",
                f"executing day-to-day workflows reliably and delivering measurable outcomes using {skills_highlight}",
                "your team's operational quality and goals",
            ),
        )

        def _finalize_ai_letter(raw_text: str) -> str:
            """Preserves AI-crafted narrative while enforcing clean sign-off without email leakage."""
            cleaned = (raw_text or "").strip()
            cand_email = str(candidate.get("email") or "").strip()
            if cand_email:
                cleaned = cleaned.replace(cand_email, "").strip()
            # Strip generic signature block if Gemini already added one, then attach clean footer
            cleaned = re.sub(
                r"\n+(?:Best regards|Sincerely|Kind regards|Warm regards|პატივისცემით),?\s*\n+[\s\S]*$",
                "",
                cleaned,
                flags=re.I,
            ).strip()
            if cover_lang == "ka" and real_company and f"მოგესალმებით, {real_company}-ის გუნდს" not in cleaned:
                cleaned = f"მოგესალმებით, {real_company}-ის გუნდს,\n\n{cleaned}"
            closing = f"პატივისცემით,\n{contact_footer}" if cover_lang == "ka" else f"Best regards,\n{contact_footer}"
            return f"{cleaned}\n\n{closing}".strip()

        ai_cover = (narratives.get("cover_letter") or "").strip()
        ai_motiv = (narratives.get("dou_motivational_letter") or "").strip()

        if gemini_service.is_available and (ai_cover or ai_motiv):
            cover_letter = _finalize_ai_letter(ai_cover or ai_motiv)
            motivational_letter = _finalize_ai_letter(ai_motiv or ai_cover)
        elif cover_lang == "ka":
            ka_area, ka_action, ka_goal = ka_tuple
            salutation = f"მოგესალმებით, {real_company}-ის გუნდს," if real_company else "მოგესალმებით, გუნდს,"
            hook_company = f"{real_company}-ში" if real_company else "თქვენს კომპანიაში"
            req_snippet = ", ".join(req_skills[:4]) if req_skills else skills_highlight
            proof_para = (
                f"{companies_phrase}-ში მუშაობისას პრაქტიკულად გამოვიყენე {skills_highlight} — ვუზრუნველყოფდი {ka_action}, რაც პირდაპირ პასუხობს ვაკანსიის მოთხოვნებს ({req_snippet})."
                if companies_phrase
                else f"ჩემს ყოველდღიურ პრაქტიკაში ({skills_highlight}) ფოკუსირებული ვარ {ka_action}-ზე, რაც შეესაბამება პოზიციის მოთხოვნებს ({req_snippet})."
            )
            cta_company = f"{real_company}-ის" if real_company else "თქვენი გუნდის"
            cover_letter = (
                f"{salutation}\n\n"
                f"გიგზავნით განაცხადს „{job_title}“ პოზიციაზე {hook_company}. "
                f"ჩემი {exp_years:g} წლიანი გამოცდილება ({skills_highlight}) პირდაპირ შეესაბამება პოზიციის მოთხოვნებს ({req_snippet}).\n\n"
                f"{proof_para} თანდართულია განახლებული რეზიუმე (CV).\n\n"
                f"პატივისცემით,\n{contact_footer}"
            )
            gap_ka = (
                f" იმ მიმართულებებში, სადაც დამატებითი ადაპტაციაა საჭირო ({', '.join(missing[:2])}), ჩემი პრაქტიკული საფუძველი სწრაფი ათვისების შესაძლებლობას მაძლევს."
                if missing and not is_non_tech_domain
                else ""
            )
            motivational_letter = (
                f"{salutation}\n\n"
                f"დიდი ინტერესით გიგზავნით სამოტივაციო წერილს „{job_title}“ პოზიციაზე {hook_company}. "
                f"თქვენი გუნდის პრიორიტეტები ({req_snippet}) სრულ თანხვედრაშია ჩემს პროფესიულ გამოცდილებასთან {ka_area} ({skills_highlight}).\n\n"
                f"{proof_para}{gap_ka}\n\n"
                f"მოხარული ვიქნები შევუერთდე {cta_company} გუნდს და წვლილი შევიტანო {ka_goal}. თანდართულია ამ პოზიციისთვის მორგებული ჩემი რეზიუმე (CV).\n\n"
                f"პატივისცემით,\n{contact_footer}"
            )
        else:
            en_area, en_action, en_goal = en_tuple
            salutation = f"Dear {real_company} Hiring Team," if real_company else "Dear Hiring Team,"
            target_phrase = f"at {real_company}" if real_company else "with your team"
            req_snippet = ", ".join(req_skills[:5]) if req_skills else skills_highlight
            gap_bridge = (
                f" Where additional ramp-up is helpful ({', '.join(missing[:2])}), my core engineering foundation supports fast onboarding."
                if missing and not is_non_tech_domain
                else ""
            )
            cta_team = f"{real_company}'s" if real_company else "your team's"
            cover_letter = (
                f"{salutation}\n\n"
                f"Please find attached my tailored CV for the {job_title} position {target_phrase}. "
                f"With {exp_years:g} years of verified experience in {skills_highlight}, my background aligns directly with {req_snippet}.\n\n"
                f"I look forward to discussing how I can contribute to {cta_team} {en_goal}.\n\n"
                f"Best regards,\n{contact_footer}"
            )
            proof_para = (
                f"Across my roles at {companies_phrase}, I applied {skills_highlight}—focusing on {en_action} to meet core requirements ({req_snippet}).{gap_bridge}"
                if companies_phrase
                else f"In my hands-on work spanning {skills_highlight}, I focus on {en_action} aligned with your priorities ({req_snippet}).{gap_bridge}"
            )
            motivational_letter = (
                f"{salutation}\n\n"
                f"I am excited to apply for the {job_title} role {target_phrase}. With {exp_years:g} years of hands-on experience in {en_area} ({skills_highlight}), I want to bring measurable impact directly to your stated goals around {req_snippet}.\n\n"
                f"{proof_para}\n\n"
                f"I would welcome the chance to connect with {cta_team} team and share how my tailored experience supports {en_goal}.\n\n"
                f"Best regards,\n{contact_footer}"
            )

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
            "docx_path": cv_res["docx_path"],
            "pdf_path": cv_res["pdf_path"],
        }


cv_generator_service = CVGeneratorService()
