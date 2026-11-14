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
from ..db.profile_repository import ground_truth_store
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
    labels = (
        {
            "auto": "ტესტ-ავტომატიზაცია და ფრეიმვორქები",
            "lang": "პროგრამირება და სკრიპტინგი",
            "api": "API და Backend ვალიდაცია",
            "infra": "CI/CD და ინფრასტრუქტურა",
            "mgmt": "მეთოდოლოგიები და ტესტ-მენეჯმენტი",
        }
        if cv_language == "ka"
        else {
            "auto": "Test Automation & Frameworks",
            "lang": "Programming & Scripting",
            "api": "API & Backend Validation",
            "infra": "CI/CD, Cloud & Infrastructure",
            "mgmt": "Methodologies & Test Management",
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

    return [(labels[key], vals) for key, vals in buckets.items() if vals]


def _add_docx_hyperlink(paragraph, display_text: str, url: str) -> None:
    """Inserts a genuine native clickable OOXML hyperlink into a python-docx paragraph."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE

    if not url:
        r = paragraph.add_run(display_text)
        r.font.size = __import__("docx.shared", fromlist=["Pt"]).Pt(9.5)
        return

    part = paragraph.part
    r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
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
    """Returns candidate's true professional seniority/headline (never degraded to an intern vacancy title)."""
    industry = str((parsed_skills or {}).get("target_industry") or "qa_tech").lower()
    raw_hl = str(candidate.get("headline") or "").strip()
    skills_blob = " ".join(skills).lower()
    if industry == "qa_tech" or any(k in skills_blob for k in ["playwright", "pytest", "selenium", "cypress"]):
        return "QA Automation Engineer & SDET | Playwright • Python • API • CI/CD"
    if raw_hl and not any(w in raw_hl.lower() for w in ["intern", "trainee", "სტაჟიორ"]):
        return raw_hl
    return raw_hl or "QA Automation Engineer & SDET"

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


def _register_unicode_font() -> str:
    """
    Registers a Unicode TrueType font family (Normal, Bold, Italic, BoldItalic) in ReportLab
    with cross-platform support and verified Georgian + Latin glyph coverage so <b>/<i> tags
    never break Georgian scripts or fall back to square boxes.
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

    # 2. Cross-platform OS font families (Segoe UI & NotoSansGeorgian prioritized first for Georgian glyphs + full bold/italic)
    family_candidates.extend([
        # Windows (Segoe UI supports full Georgian Unicode + native Bold/Italic/BoldItalic; Sylfaen as fallback)
        (
            "SegoeUI",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/segoeuii.ttf",
            "C:/Windows/Fonts/segoeuiz.ttf",
        ),
        (
            "Sylfaen",
            "C:/Windows/Fonts/sylfaen.ttf",
            None,
            None,
            None,
        ),
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


UNICODE_FONT_NAME = _register_unicode_font()


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
    """Extracts spoken languages from live skills.md first, then CandidateProfile, instead of hardcoding values."""
    lang_text = ""

    if skills_md:
        # Check inline `Languages: ...` / `**Languages:** ...` or markdown section `## Languages`
        inline_m = re.search(
            r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(?:languages|spoken languages|ენები)(?:\*\*)?\s*:\s*\**\s*(.+)$",
            skills_md,
        )
        if inline_m:
            lang_text = inline_m.group(1).strip().strip("*")
        else:
            sec_m = re.search(
                r"(?ims)^#{1,4}\s*(?:languages|spoken languages|ენები)[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)",
                skills_md,
            )
            if sec_m:
                lines = [
                    re.sub(r"^[-*•]\s*", "", ln).strip()
                    for ln in sec_m.group(1).splitlines()
                    if ln.strip()
                ]
                lang_text = ", ".join(lines[:5])

    if not lang_text:
        raw_langs = candidate.get("languages")
        if isinstance(raw_langs, dict):
            parts = [f"{k} ({v})" if v else str(k) for k, v in raw_langs.items() if k]
            lang_text = ", ".join(parts)
        elif isinstance(raw_langs, list):
            parts = []
            for item in raw_langs:
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("language") or "").strip()
                    lvl = str(item.get("level") or item.get("proficiency") or "").strip()
                    if name:
                        parts.append(f"{name} ({lvl})" if lvl else name)
                elif str(item or "").strip():
                    parts.append(str(item).strip())
            lang_text = ", ".join(parts)
        elif isinstance(raw_langs, str) and raw_langs.strip():
            lang_text = raw_langs.strip()

    if lang_text:
        return f"ენები: {lang_text}" if is_ka else f"Languages: {lang_text}"
    return "ენები: ქართული (მშობლიური), ინგლისური (თავისუფლად)" if is_ka else "Languages: English, Georgian"


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
        skills_md = skills_md_override or gt.get("skills_md_raw") or ground_truth_store.get_skills_md(owner_email=owner_email)
        parsed_md = ground_truth_store.parse_profile_from_md(skills_md) if skills_md else {}

        candidate = dict(gt.get("candidate", {}))
        if parsed_md.get("full_name"):
            candidate["full_name"] = parsed_md["full_name"]
        if parsed_md.get("headline"):
            candidate["headline"] = parsed_md["headline"]
        if parsed_md.get("email"):
            candidate["email"] = parsed_md["email"]
        if parsed_md.get("phone"):
            candidate["phone"] = parsed_md["phone"]
        if parsed_md.get("location") and not _format_candidate_location(candidate.get("location")):
            loc_parts = [p.strip() for p in str(parsed_md["location"]).split(",", 1)]
            candidate["location"] = {
                "city": loc_parts[0],
                "country": loc_parts[1] if len(loc_parts) > 1 else "",
            }

        cand_links = dict(candidate.get("links") or {})
        if skills_md:
            gh_m = re.search(r"(https?://(?:www\.)?github\.com/[A-Za-z0-9._-]+/?)", skills_md, re.I)
            li_m = re.search(r"(https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9._-]+/?)", skills_md, re.I)
            if gh_m and not cand_links.get("github"):
                cand_links["github"] = gh_m.group(1).rstrip("/")
            if li_m and not cand_links.get("linkedin"):
                cand_links["linkedin"] = li_m.group(1).rstrip("/")
        candidate["links"] = cand_links

        core_skills = parsed_md.get("skills") or gt.get("skills", {}).get("core", []) or []
        raw_work_history = parsed_md.get("work_history") or gt.get("work_history", [])
        education = parsed_md.get("education") or gt.get("education", [])

        # Tailor bullet ordering per job description & matched requirements (ZERO fabrication)
        target_kws = list(dict.fromkeys((matched_skills or []) + (required_skills or []) + re.findall(r"[A-Za-z]{3,}", job_title or "")))
        prioritized_wh: List[Dict[str, Any]] = []
        for job in raw_work_history:
            j_copy = dict(job)
            j_copy["highlights"] = _prioritize_job_highlights(j_copy.get("highlights") or [], target_kws)
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

        ps = gt.get("parsed_skills_taxonomy") or {}
        candidate_headline = resolve_candidate_headline(candidate, core_skills, ps)
        safe_company = sanitize_company_name(company, fallback="")
        clean_full_for_slug = re.sub(r"\([^)]*\)", "", str(candidate.get("full_name", "Candidate"))).strip()
        cand_slug = ascii_filename_slug(clean_full_for_slug or str(candidate.get("full_name", "Candidate")), default="Candidate", max_len=24)

        lang_suffix = "_KA" if cv_language == "ka" else ""
        role_tag = "QA_Engineer" if (ps.get("target_industry", "qa_tech") == "qa_tech") else ascii_filename_slug(candidate_headline.split("|")[0], default="Specialist", max_len=18)
        job_role_slug = ascii_filename_slug(job_title, default="Role", max_len=20)
        languages_line = _format_candidate_languages(candidate, skills_md, cv_language == "ka")

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
            cv_language=cv_language,
            cv_style=cv_style,
            languages_line=languages_line,
        )

        start_date_str = "1 კვირა შეთავაზებიდან (1 week after offer)" if cv_language == "ka" else "1 week after offer"

        return {
            "pdf_filename": pdf_filename,
            "pdf_url": f"/api/resumes/generated/{pdf_filename}",
            "docx_filename": docx_filename,
            "docx_url": f"/api/resumes/generated/{docx_filename}",
            "html_preview_url": f"/api/resumes/generated/{html_filename}",
            "pdf_path": str(pdf_path),
            "docx_path": str(docx_path),
            "cv_language": cv_language,
            "candidate_name": candidate.get("full_name", "Candidate"),
            "target_role": candidate_headline,
            "human_tone_summary": human_summary,
            "applicant_summary": human_summary,
            "motivation_statement": motivation_statement,
            "dou_motivational_letter": dou_motivational_letter,
            "tailored_highlights": tailored_highlights,
            "ats_keywords_covered": matched_skills or display_skills[:8],
            "start_date_default": start_date_str,
            "expected_salary": "Negotiable / Market Rate",
        }

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
        cv_language: str = "en",
        cv_style: str = "tailored",
        candidate_headline: Optional[str] = None,
        languages_line: Optional[str] = None,
    ) -> None:
        """Builds a clean, editable Microsoft Word (.docx) CV in ATS, Recruiter, or Job-Tailored edition."""
        from docx import Document
        from docx.shared import Inches, Pt, RGBColor

        is_ka = cv_language == "ka"
        doc = Document()
        for sec in doc.sections:
            sec.top_margin = Inches(0.6)
            sec.bottom_margin = Inches(0.6)
            sec.left_margin = Inches(0.7)
            sec.right_margin = Inches(0.7)

        accent = RGBColor(0x0F, 0x17, 0x2A) if cv_style == "ats" else RGBColor(0x03, 0x69, 0xA1)
        subtle = RGBColor(0x47, 0x55, 0x69)

        full_name = str(candidate.get("full_name", "Candidate"))
        email = str(candidate.get("email") or "").strip()
        if email == "candidate@example.com":
            email = ""
        raw_phone = str(candidate.get("phone") or "").strip()
        phone = "" if (not raw_phone or "+000" in raw_phone or re.fullmatch(r"[+\s0()-]+", raw_phone)) else raw_phone
        loc = _format_candidate_location(candidate.get("location"))
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

        role_heading = candidate_headline or str(candidate.get("headline") or "QA Automation Engineer & SDET | Playwright • Python • API • CI/CD")
        if cv_style == "ats":
            role_heading = f"{role_heading} (ATS Edition)"
        p_role = doc.add_paragraph()
        p_role.paragraph_format.space_after = Pt(3)
        r_role = p_role.add_run(role_heading)
        r_role.bold = True
        r_role.font.size = Pt(11.5)
        r_role.font.color.rgb = accent

        p_contact = doc.add_paragraph()
        p_contact.paragraph_format.space_after = Pt(8)
        contact_items: List[tuple[str, str]] = []
        if email:
            contact_items.append((email, normalize_contact_href(email, is_email=True)))
        if phone:
            contact_items.append((phone, ""))
        if loc:
            contact_items.append((loc, ""))
        if linkedin and "alex-mercer" not in linkedin.lower():
            contact_items.append((linkedin, normalize_contact_href(linkedin)))
        elif linkedin:
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
            if href:
                _add_docx_hyperlink(p_contact, label, href)
            else:
                rt = p_contact.add_run(label)
                rt.font.size = Pt(9.5)
                rt.font.color.rgb = subtle

        def add_section_heading(title_text: str) -> None:
            p_h = doc.add_paragraph()
            p_h.paragraph_format.space_before = Pt(8)
            p_h.paragraph_format.space_after = Pt(3)
            run = p_h.add_run(title_text)
            run.bold = True
            run.font.size = Pt(10.5)
            run.font.color.rgb = accent

        lbl_summary = "პროფესიული მიმოხილვა" if is_ka else ("PROFESSIONAL SUMMARY" if cv_style != "recruiter" else f"EXECUTIVE PROFILE — {target_role.upper()}")
        lbl_skills = "ტექნიკური კომპეტენციების მატრიცა" if is_ka else ("TECHNICAL SKILLS MATRIX" if cv_style == "ats" else "CORE COMPETENCIES & STACK")
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "WORK EXPERIENCE"
        lbl_edu = "განათლება და ენები" if is_ka else "EDUCATION & LANGUAGES"

        add_section_heading(lbl_summary)
        p_sum = doc.add_paragraph(human_summary)
        p_sum.paragraph_format.space_after = Pt(4)
        for r in p_sum.runs:
            r.font.size = Pt(10)

        add_section_heading(lbl_skills)
        grouped = group_skills_into_ats_buckets(display_skills[:30], cv_language=cv_language)
        if grouped:
            for bucket_title, bucket_items in grouped:
                p_sk = doc.add_paragraph()
                p_sk.paragraph_format.space_after = Pt(2)
                rk = p_sk.add_run(f"{bucket_title}: ")
                rk.bold = True
                rk.font.size = Pt(9.5)
                rv = p_sk.add_run(", ".join(bucket_items))
                rv.font.size = Pt(9.5)
        else:
            p_sk = doc.add_paragraph(", ".join(display_skills[:24]) or "QA Testing, Test Automation, REST API")
            p_sk.paragraph_format.space_after = Pt(4)
            for r in p_sk.runs:
                r.font.size = Pt(10)

        if work_history:
            add_section_heading(lbl_exp)
            for job in work_history[:5]:
                dates = f"{job.get('start_date', '')} – {job.get('end_date', '')}".strip(" –")
                p_j = doc.add_paragraph()
                p_j.paragraph_format.space_before = Pt(4)
                p_j.paragraph_format.space_after = Pt(2)
                rj = p_j.add_run(f"{job.get('role', '')} — {job.get('company', '')}")
                rj.bold = True
                rj.font.size = Pt(10.5)
                if dates:
                    rd = p_j.add_run(f"   ({dates})")
                    rd.font.size = Pt(9.5)
                    rd.font.color.rgb = subtle
                for b in clean_bullets(job.get("highlights"))[:5]:
                    p_b = doc.add_paragraph(style="List Bullet")
                    p_b.paragraph_format.space_after = Pt(2)
                    rb = p_b.add_run(str(b))
                    rb.font.size = Pt(9.5)

        add_section_heading(lbl_edu)
        if education:
            for edu in education:
                yr_val = edu.get("graduation_year")
                yr_suffix = f" ({yr_val})" if yr_val else ""
                p_e = doc.add_paragraph(f"{edu.get('degree', '')} — {edu.get('institution', '')}{yr_suffix}")
                p_e.paragraph_format.space_after = Pt(2)
                for r in p_e.runs:
                    r.font.size = Pt(9.5)
        langs_line = languages_line or _format_candidate_languages(candidate, "", is_ka)
        p_lang = doc.add_paragraph(langs_line)
        for r in p_lang.runs:
            r.font.size = Pt(9.5)

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
        cv_language: str = "en",
        candidate_headline: Optional[str] = None,
        cv_style: str = "tailored",
        languages_line: Optional[str] = None,
    ) -> None:
        """
        Generates a clean, ATS-compliant single-column PDF resume using ReportLab:
        Header -> Summary -> Technical Skills Matrix -> Work Experience -> Education & Certifications.
        """
        is_ka = cv_language == "ka"
        font_name = UNICODE_FONT_NAME

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

        if cv_style in ("ats", "recruiter"):
            lbl_summary = (
                "პროფესიული მიმოხილვა"
                if is_ka
                else ("EXECUTIVE PROFILE" if cv_style == "recruiter" else "PROFESSIONAL SUMMARY")
            )
        else:
            lbl_summary = (
                f"პროფესიული მიმოხილვა ({escape(target_company)})"
                if is_ka
                else f"PROFESSIONAL SUMMARY — TAILORED FOR {escape(target_company.upper())}"
            )
        lbl_skills = "ტექნიკური კომპეტენციების მატრიცა" if is_ka else "TECHNICAL SKILLS MATRIX"
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "WORK EXPERIENCE"
        lbl_edu = "განათლება და სერტიფიკატები" if is_ka else "EDUCATION & CERTIFICATIONS"

        story = []

        # 1. Header (ALWAYS showcase true candidate persona headline, never degrade to intern title)
        role_display = candidate_headline or str(candidate.get("headline") or "QA Automation Engineer & SDET | Playwright • Python • API • CI/CD")
        if cv_style == "ats":
            role_display = f"{role_display} (ATS Edition)"
        story.append(Paragraph(f"<b>{full_name}</b>", header_style))
        story.append(Paragraph(escape(role_display), role_style))
        if pdf_links:
            story.append(Paragraph(" | ".join(x for x in pdf_links if x), contact_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=6))

        # 2. Summary
        story.append(Paragraph(f"<b>{lbl_summary}</b>", sec_title_style))
        story.append(Paragraph(escape(human_summary), body_style))

        # 3. Technical Skills Matrix (grouped by ATS domains)
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
        story.append(Paragraph(f"<b>{lbl_skills}</b>", sec_title_style))
        grouped_pdf = group_skills_into_ats_buckets(display_skills[:30], cv_language=cv_language)
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

        # 5. Education & Certifications
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
        story.append(Paragraph(f"<b>{lbl_edu}</b>", sec_title_style))
        for edu in education:
            deg = escape(str(edu.get("degree", "")))
            inst = escape(str(edu.get("institution", "")))
            raw_yr = edu.get("graduation_year")
            yr_suffix = f" ({escape(str(raw_yr))})" if raw_yr else ""
            story.append(Paragraph(f"<b>{deg}</b> — {inst}{yr_suffix}", body_style))

        lang_line = languages_line or _format_candidate_languages(candidate, "", is_ka)
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

        if cv_style in ("ats", "recruiter"):
            lbl_summary = (
                "პროფესიული მიმოხილვა"
                if is_ka
                else ("EXECUTIVE PROFILE" if cv_style == "recruiter" else "PROFESSIONAL SUMMARY")
            )
        else:
            lbl_summary = (
                f"პროფესიული მიმოხილვა ({esc(target_company)})"
                if is_ka
                else f"PROFESSIONAL SUMMARY (TAILORED FOR {esc(target_company.upper())})"
            )
        lbl_skills = "ტექნიკური კომპეტენციების მატრიცა" if is_ka else "TECHNICAL SKILLS MATRIX"
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "WORK EXPERIENCE"
        lbl_edu = "განათლება და სერტიფიკატები" if is_ka else "EDUCATION & CERTIFICATIONS"

        grouped_html = group_skills_into_ats_buckets(display_skills[:30], cv_language=cv_language)
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
                <strong style="font-size:13px; color:#0f172a;">{esc(job.get('role', ''))} — <span style="color:#0284c7;">{esc(job.get('company', ''))}</span></strong>
                <span style="font-size:11px; color:#64748b;">{esc(dates)}</span>
              </div>
              <ul style="margin:6px 0 0 18px; padding:0; font-size:12px; color:#334155; line-height:1.5;">
                {bullets}
              </ul>
            </div>
            """

        edu_blocks = ""
        for edu in education:
            yr_val = edu.get("graduation_year")
            yr_suffix = f" ({esc(yr_val)})" if yr_val else ""
            edu_blocks += f"<div style='font-size:12px; color:#334155;'><strong>{esc(edu.get('degree', ''))}</strong> — {esc(edu.get('institution', ''))}{yr_suffix}</div>"

        role_display_html = candidate_headline or str(candidate.get('headline') or 'QA Automation Engineer & SDET | Playwright • Python • API • CI/CD')
        if cv_style == "ats":
            role_display_html = f"{role_display_html} (ATS Edition)"
        lang_line_html = languages_line or _format_candidate_languages(candidate, "", is_ka)

        return f"""<!DOCTYPE html>
<html lang="{esc(cv_language)}">
<head>
  <meta charset="UTF-8" />
  <title>{esc(full_name)} — {esc(target_role)} CV</title>
  <style>
    body {{
      font-family: 'Sylfaen', 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
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
    <p class="summary">{esc(human_summary)}</p>

    <div class="section-title">{lbl_skills}</div>
    <div>{skills_badges}</div>

    <div class="section-title">{lbl_exp}</div>
    {exp_blocks}

    <div class="section-title">{lbl_edu}</div>
    {edu_blocks}
    <div style="font-size:12px; color:#475569; margin-top:6px;">
      {esc(lang_line_html)}
    </div>
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

        # Clean subject & sanitize company (never address location strings or portal chrome)
        real_company = sanitize_company_name(company, target_email=target_email, fallback="")

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

        if cover_lang == "ka":
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
                f"დიდი ინტერესით გიგზავნით განაცხადს „{job_title}“ პოზიციაზე {hook_company}. "
                f"მაქვს {exp_years:g} წლიანი პრაქტიკული გამოცდილება {ka_area} ({skills_highlight}).\n\n"
                f"{proof_para}\n\n"
                f"მოხარული ვიქნები შევუერთდე {cta_company} გუნდს და წვლილი შევიტანო {ka_goal}. თანდართულია ამ პოზიციისთვის მორგებული ჩემი რეზიუმე (CV).\n\n"
                f"პატივისცემით,\n{contact_footer}"
            )
        else:
            en_area, en_action, en_goal = en_tuple
            salutation = f"Dear {real_company} Hiring Team," if real_company else "Dear Hiring Team,"
            target_phrase = f"at {real_company}" if real_company else "with your team"
            req_snippet = ", ".join(req_skills[:5]) if req_skills else skills_highlight
            gap_bridge = (
                f" Beyond core alignment on {skills_highlight}, my adaptable foundation enables me to ramp quickly on {', '.join(missing[:2])}."
                if missing and not is_non_tech_domain
                else ""
            )
            proof_para = (
                f"Across my roles at {companies_phrase}, I applied {skills_highlight}—focusing on {en_action} to meet core role needs ({req_snippet}).{gap_bridge}"
                if companies_phrase
                else f"In my hands-on work spanning {skills_highlight}, I focus on {en_action} aligned with your role priorities ({req_snippet}).{gap_bridge}"
            )
            cta_team = f"{real_company}'s" if real_company else "your team's"
            cover_letter = (
                f"{salutation}\n\n"
                f"I am writing to apply for the {job_title} role {target_phrase}. With {exp_years:g} years of hands-on experience in {en_area} ({skills_highlight}), my background directly aligns with your stated requirements in {req_snippet}.\n\n"
                f"{proof_para}\n\n"
                f"I would welcome the opportunity to discuss how my tailored CV and experience can support {cta_team} {en_goal}.\n\n"
                f"Best regards,\n{contact_footer}"
            )

        return {
            "company": real_company or company,
            "title": job_title,
            "recipient_email": target_email or "",
            "subject": clean_subject,
            "cover_letter": cover_letter,
            "cv_language": cv_lang,
            "docx_filename": cv_res["docx_filename"],
            "docx_url": cv_res["docx_url"],
            "pdf_filename": cv_res["pdf_filename"],
            "pdf_url": cv_res["pdf_url"],
            "docx_path": cv_res["docx_path"],
            "pdf_path": cv_res["pdf_path"],
        }


cv_generator_service = CVGeneratorService()
