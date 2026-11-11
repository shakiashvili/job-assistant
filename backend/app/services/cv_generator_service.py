import hashlib
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
from ..storage.ground_truth_store import ground_truth_store
from ..services.gemini_service import GEORGIAN_SKILL_TRANSLATIONS

logger = logging.getLogger(__name__)

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
    Registers a Unicode TrueType font in ReportLab with cross-platform support:
    Checks repository assets/fonts, standard Linux paths, macOS paths, and Windows paths.
    """
    font_candidates = []

    # 1. Check project assets/fonts directory for bundled fonts (Linux/Docker/Windows)
    if FONTS_DIR.exists():
        for f in FONTS_DIR.glob("*.ttf"):
            font_candidates.append((f.stem, str(f)))

    # 2. Cross-platform OS paths
    font_candidates.extend([
        # Windows
        ("Sylfaen", "C:/Windows/Fonts/sylfaen.ttf"),
        ("SegoeUI", "C:/Windows/Fonts/segoeui.ttf"),
        ("ArialUnicode", "C:/Windows/Fonts/arial.ttf"),
        # Linux / Docker
        ("NotoSansGeorgian", "/usr/share/fonts/truetype/noto/NotoSansGeorgian-Regular.ttf"),
        ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("LiberationSans", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        # macOS
        ("ArialUnicodeMac", "/Library/Fonts/Arial Unicode.ttf"),
        ("ArialMac", "/System/Library/Fonts/Supplemental/Arial.ttf"),
    ])

    for font_name, font_path in font_candidates:
        if Path(font_path).exists():
            try:
                if font_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(font_name, font_path))
                return font_name
            except Exception as e:
                logger.debug(f"Could not register TTF {font_path}: {e}")
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
    ) -> Dict[str, Any]:
        gt = ground_truth_store.get_data()
        skills_md = skills_md_override or gt.get("skills_md_raw") or ground_truth_store.get_skills_md()
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

        core_skills = gt.get("skills", {}).get("core", []) or parsed_md.get("skills") or []
        work_history = parsed_md.get("work_history") or gt.get("work_history", [])
        education = gt.get("education", [])

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

        lang_suffix = "KA" if cv_language == "ka" else "EN"
        safe_company = safe_unicode_slug(company, default="Company", max_len=22)
        safe_role = safe_unicode_slug(job_title, default="Role", max_len=26)
        uid = uuid.uuid4().hex[:6]
        base_name = f"CV_{safe_company}_{safe_role}_{uid}_{lang_suffix}"
        pdf_filename = f"{base_name}.pdf"
        docx_filename = f"{base_name}.docx"
        html_filename = f"{base_name}.html"
        pdf_path = GENERATED_RESUMES_DIR / pdf_filename
        docx_path = GENERATED_RESUMES_DIR / docx_filename
        html_path = GENERATED_RESUMES_DIR / html_filename

        # Also write the canonical non-versioned link so legacy lookups still succeed
        canonical_base = f"CV_{safe_company}_{safe_role}_{lang_suffix}"
        canonical_pdf = GENERATED_RESUMES_DIR / f"{canonical_base}.pdf"
        canonical_docx = GENERATED_RESUMES_DIR / f"{canonical_base}.docx"
        canonical_html = GENERATED_RESUMES_DIR / f"{canonical_base}.html"

        tailored_highlights = []
        for job in work_history:
            for h in job.get("highlights", [])[:2]:
                tailored_highlights.append(f"{job.get('role')} @ {job.get('company')}: {h}")

        # 1. Build Single-Column ATS HTML Preview
        html_content = self._build_cv_html(
            candidate=candidate,
            target_role=job_title,
            target_company=company,
            human_summary=human_summary,
            display_skills=display_skills,
            work_history=work_history,
            education=education,
            cv_language=cv_language,
        )
        html_path.write_text(html_content, encoding="utf-8")

        # 2. Build Clean Single-Column PDF via ReportLab
        self._build_reportlab_single_column_pdf(
            filepath=pdf_path,
            candidate=candidate,
            target_role=job_title,
            target_company=company,
            human_summary=human_summary,
            display_skills=display_skills,
            work_history=work_history,
            education=education,
            cv_language=cv_language,
        )

        # 3. Build Ready Microsoft Word (.docx) CV via python-docx
        self._build_docx_cv(
            filepath=docx_path,
            candidate=candidate,
            target_role=job_title,
            target_company=company,
            human_summary=human_summary,
            display_skills=display_skills,
            work_history=work_history,
            education=education,
            cv_language=cv_language,
            cv_style=cv_style,
        )

        try:
            canonical_html.write_text(html_content, encoding="utf-8")
            import shutil
            shutil.copy2(pdf_path, canonical_pdf)
            shutil.copy2(docx_path, canonical_docx)
        except Exception as e:
            logger.debug(f"Canonical resume copy note: {e}")

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
            "target_role": job_title,
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
        email = str(candidate.get("email", "candidate@example.com"))
        phone = str(candidate.get("phone", "+000 000 0000"))
        loc_dict = candidate.get("location", {})
        loc = (
            f"{loc_dict.get('city', 'Tbilisi')}, {loc_dict.get('country', 'Georgia')}"
            if isinstance(loc_dict, dict)
            else str(loc_dict)
        )
        links = candidate.get("links", {}) if isinstance(candidate.get("links"), dict) else {}
        linkedin = str(links.get("linkedin", ""))
        github = str(links.get("github", ""))

        p_name = doc.add_paragraph()
        p_name.paragraph_format.space_after = Pt(2)
        r_name = p_name.add_run(full_name)
        r_name.bold = True
        r_name.font.size = Pt(18)
        r_name.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)

        role_heading = target_role if cv_style != "ats" else f"{target_role} | ATS Edition"
        p_role = doc.add_paragraph()
        p_role.paragraph_format.space_after = Pt(3)
        r_role = p_role.add_run(role_heading)
        r_role.bold = True
        r_role.font.size = Pt(11.5)
        r_role.font.color.rgb = accent

        contact_parts = [x for x in [email, phone, loc, linkedin, github] if x]
        p_contact = doc.add_paragraph()
        p_contact.paragraph_format.space_after = Pt(8)
        r_contact = p_contact.add_run("  |  ".join(contact_parts))
        r_contact.font.size = Pt(9.5)
        r_contact.font.color.rgb = subtle

        def add_section_heading(title_text: str) -> None:
            p_h = doc.add_paragraph()
            p_h.paragraph_format.space_before = Pt(8)
            p_h.paragraph_format.space_after = Pt(3)
            run = p_h.add_run(title_text)
            run.bold = True
            run.font.size = Pt(10.5)
            run.font.color.rgb = accent

        lbl_summary = "პროფესიული მიმოხილვა" if is_ka else ("PROFESSIONAL SUMMARY" if cv_style != "recruiter" else f"EXECUTIVE PROFILE — {target_role.upper()}")
        lbl_skills = "ძირითადი უნარები" if is_ka else ("TECHNICAL SKILLS MATRIX" if cv_style == "ats" else "CORE COMPETENCIES & STACK")
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "WORK EXPERIENCE"
        lbl_edu = "განათლება და ენები" if is_ka else "EDUCATION & LANGUAGES"

        add_section_heading(lbl_summary)
        p_sum = doc.add_paragraph(human_summary)
        p_sum.paragraph_format.space_after = Pt(4)
        for r in p_sum.runs:
            r.font.size = Pt(10)

        add_section_heading(lbl_skills)
        skills_text = ", ".join(display_skills[:24]) if display_skills else "QA Testing, Test Automation, REST API"
        p_sk = doc.add_paragraph(skills_text)
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
                for b in job.get("highlights", [])[:5]:
                    p_b = doc.add_paragraph(style="List Bullet")
                    p_b.paragraph_format.space_after = Pt(2)
                    rb = p_b.add_run(str(b))
                    rb.font.size = Pt(9.5)

        add_section_heading(lbl_edu)
        if education:
            for edu in education:
                p_e = doc.add_paragraph(f"{edu.get('degree', '')} — {edu.get('institution', '')} ({edu.get('graduation_year', '')})")
                p_e.paragraph_format.space_after = Pt(2)
                for r in p_e.runs:
                    r.font.size = Pt(9.5)
        langs_line = (
            "ენები: ქართული (მშობლიური), ინგლისური (თავისუფლად)"
            if is_ka
            else "Languages: English (Fluent), Georgian (Native)  |  Availability: 1 week after offer"
        )
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
        email = escape(str(candidate.get("email", "candidate@example.com")))
        phone = escape(str(candidate.get("phone", "+000 000 0000")))
        loc_dict = candidate.get("location", {})
        loc = escape(
            f"{loc_dict.get('city', 'Tbilisi')}, {loc_dict.get('country', 'Georgia')}"
            if isinstance(loc_dict, dict)
            else str(loc_dict)
        )
        linkedin = escape(str(candidate.get("links", {}).get("linkedin", "linkedin.com/in/alex-mercer-qa")))

        lbl_summary = (
            f"პროფესიული მიმოხილვა ({escape(target_company)})"
            if is_ka
            else f"PROFESSIONAL SUMMARY — TAILORED FOR {escape(target_company.upper())}"
        )
        lbl_skills = "ძირითადი უნარები და ტექნიკური მატრიცა" if is_ka else "TECHNICAL SKILLS MATRIX"
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "WORK EXPERIENCE"
        lbl_edu = "განათლება და სერტიფიკატები" if is_ka else "EDUCATION & CERTIFICATIONS"
        lbl_start = "მზადყოფნა: შეთავაზებიდან 1 კვირაში" if is_ka else "Availability: 1 week after offer"

        story = []

        # 1. Header
        story.append(Paragraph(f"<b>{full_name}</b>", header_style))
        story.append(Paragraph(escape(target_role), role_style))
        story.append(
            Paragraph(
                f"{email} | {phone} | {loc} | {linkedin} | {lbl_start}",
                contact_style,
            )
        )
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=6))

        # 2. Summary
        story.append(Paragraph(f"<b>{lbl_summary}</b>", sec_title_style))
        story.append(Paragraph(escape(human_summary), body_style))

        # 3. Technical Skills Matrix
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
        story.append(Paragraph(f"<b>{lbl_skills}</b>", sec_title_style))
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
            for b in job.get("highlights", [])[:4]:
                story.append(Paragraph(f"• {escape(str(b))}", bullet_style))
            story.append(Spacer(1, 3))

        # 5. Education & Certifications
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceBefore=4, spaceAfter=4))
        story.append(Paragraph(f"<b>{lbl_edu}</b>", sec_title_style))
        for edu in education:
            deg = escape(str(edu.get("degree", "")))
            inst = escape(str(edu.get("institution", "")))
            yr = escape(str(edu.get("graduation_year", "")))
            story.append(Paragraph(f"<b>{deg}</b> — {inst} ({yr})", body_style))

        lang_line = (
            "ენები: ქართული (მშობლიური), ინგლისური (თავისუფლად C1/C2) | მუშაობის დაწყება: 1 კვირა შეთავაზებიდან"
            if is_ka
            else "Languages: English (Fluent C1/C2), Georgian (Native) | Notice Period: 1 week after offer"
        )
        story.append(Paragraph(lang_line, body_style))

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
    ) -> str:
        is_ka = cv_language == "ka"
        full_name = candidate.get("full_name", "Candidate")
        email = candidate.get("email", "candidate@example.com")
        phone = candidate.get("phone", "+000 000 0000")
        loc_dict = candidate.get("location", {})
        loc = (
            f"{loc_dict.get('city', 'Tbilisi')}, {loc_dict.get('country', 'Georgia')}"
            if isinstance(loc_dict, dict)
            else str(loc_dict)
        )
        linkedin = candidate.get("links", {}).get("linkedin", "linkedin.com/in/candidate")

        lbl_summary = f"პროფესიული მიმოხილვა ({target_company})" if is_ka else f"PROFESSIONAL SUMMARY (TAILORED FOR {target_company.upper()})"
        lbl_skills = "ძირითადი უნარები და კომპეტენციები" if is_ka else "TECHNICAL SKILLS MATRIX"
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "WORK EXPERIENCE"
        lbl_edu = "განათლება და სერტიფიკატები" if is_ka else "EDUCATION & CERTIFICATIONS"
        lbl_start = "მუშაობის დაწყება: შეთავაზებიდან 1 კვირაში" if is_ka else "Availability: 1 week after offer"

        skills_badges = "".join(
            f'<span style="display:inline-block; background:#f1f5f9; color:#0f172a; border:1px solid #cbd5e1; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:600; margin:0 6px 6px 0;">{s}</span>'
            for s in display_skills[:20]
        )

        exp_blocks = ""
        for job in work_history[:4]:
            bullets = "".join(f"<li style='margin-bottom:4px;'>{b}</li>" for b in job.get("highlights", [])[:4])
            dates = f"{job.get('start_date', '')} – {job.get('end_date', '')}".strip(" –")
            exp_blocks += f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex; justify-content:space-between; align-items:baseline;">
                <strong style="font-size:13px; color:#0f172a;">{job.get('role', '')} — <span style="color:#0284c7;">{job.get('company', '')}</span></strong>
                <span style="font-size:11px; color:#64748b;">{dates}</span>
              </div>
              <ul style="margin:6px 0 0 18px; padding:0; font-size:12px; color:#334155; line-height:1.5;">
                {bullets}
              </ul>
            </div>
            """

        edu_blocks = ""
        for edu in education:
            edu_blocks += f"<div style='font-size:12px; color:#334155;'><strong>{edu.get('degree', '')}</strong> — {edu.get('institution', '')} ({edu.get('graduation_year', '')})</div>"

        return f"""<!DOCTYPE html>
<html lang="{cv_language}">
<head>
  <meta charset="UTF-8" />
  <title>{full_name} — {target_role} CV</title>
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
      <h1 class="name">{full_name}</h1>
      <div class="role">{target_role}</div>
      <div class="contact">
        {email} &nbsp;•&nbsp; {phone} &nbsp;•&nbsp; {loc} &nbsp;•&nbsp; {linkedin} &nbsp;•&nbsp; <strong>{lbl_start}</strong>
      </div>
    </div>

    <div class="section-title">{lbl_summary}</div>
    <p class="summary">{human_summary}</p>

    <div class="section-title">{lbl_skills}</div>
    <div>{skills_badges}</div>

    <div class="section-title">{lbl_exp}</div>
    {exp_blocks}

    <div class="section-title">{lbl_edu}</div>
    {edu_blocks}
    <div style="font-size:12px; color:#475569; margin-top:6px;">
      {"ენები: ქართული (მშობლიური), ინგლისური (თავისუფლად C1/C2) • მზადყოფნა: შეთავაზებიდან 1 კვირაში" if is_ka else "Languages: English (Fluent), Georgian (Native) • Notice Period: 1 week after offer"}
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
    ) -> Dict[str, Any]:
        """
        Generates a complete, ready-to-send email package for any vacancy:
        - Tailored Word (.docx) and PDF CV built from the candidate's live skills.md
        - Job-specific Cover Letter (Georgian for Georgian postings, English otherwise)
        - Clean email subject with [Name] resolved to actual candidate full_name
        """
        from .gemini_service import gemini_service
        from .matcher_service import matcher_service

        gt = ground_truth_store.get_data()
        candidate = dict(gt.get("candidate", {}))
        skills_md = gt.get("skills_md_raw") or ""
        cand_name = str(candidate.get("full_name") or "Candidate").strip()
        cand_email = str(candidate.get("email") or "").strip()
        cand_phone = str(candidate.get("phone") or "").strip()
        links = candidate.get("links", {}) if isinstance(candidate.get("links"), dict) else {}
        cand_linkedin = str(links.get("linkedin") or "").strip()

        lang = cv_language
        if lang == "auto":
            ka_chars = len(re.findall(r"[\u10A0-\u10FF]", f"{job_title}\n{description}"))
            lang = "ka" if ka_chars >= 25 else "en"

        req_skills = matcher_service.extract_job_requirements(job_title, description)
        cand_skills = [str(s) for s in (gt.get("skills", {}).get("core") or [])]
        matched = [
            r for r in req_skills if any(r.lower() in c.lower() or c.lower() in r.lower() for c in cand_skills)
        ] or cand_skills[:6]
        missing = [r for r in req_skills if r not in matched]

        narratives = gemini_service.craft_human_tone_narratives(
            job_details={"title": job_title, "company": company, "portal": portal, "required_skills": req_skills},
            skills_md=skills_md,
            matched_skills=matched,
            missing_skills=missing,
            cv_language=lang,
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
            cv_language=lang,
            cv_style=cv_style,
        )

        # Clean subject: never leave '[Name]' or hardcoded wrong roles
        if email_subject_template and "qa automation engineer - [name]" not in email_subject_template.lower():
            clean_subject = re.sub(r"\[(?:your\s+)?name\]", cand_name, email_subject_template, flags=re.I).strip()
        else:
            clean_subject = f"{job_title} — {cand_name}" if lang == "ka" else f"Application for {job_title} — {cand_name}"

        contact_footer = "\n".join(x for x in [cand_name, cand_email, cand_phone, cand_linkedin] if x)
        skills_highlight = ", ".join(matched[:6]) if matched else ", ".join(cand_skills[:6])

        if lang == "ka":
            cover_letter = (
                f"მოგესალმებით {company}-ის გუნდს,\n\n"
                f"გწერთ თქვენს მიერ გამოქვეყნებულ „{job_title}“ პოზიციასთან დაკავშირებით. "
                f"პროფესიული ინტერესითა და პრაქტიკული გამოცდილებით ვფლობ ისეთ უნარებს, როგორიცაა {skills_highlight}, "
                f"და მზად ვარ მაქსიმალურად ჩავერთო {company}-ის პროექტებში.\n\n"
                f"{narratives['motivation_statement']}\n\n"
                f"თანდართული სახით გიგზავნით ჩემს რეზიუმეს (Word / PDF: {cv_res['docx_filename']}).\n\n"
                f"პატივისცემით,\n{contact_footer}"
            )
        else:
            cover_letter = (
                f"Dear {company} Hiring Team,\n\n"
                f"I am writing to apply for the {job_title} position at {company}. "
                f"With hands-on experience across {skills_highlight}, I can contribute immediately to product quality and reliable test execution.\n\n"
                f"{narratives['motivation_statement']}\n\n"
                f"Please find my tailored CV ({cv_res['docx_filename']}) attached. I am available to start 1 week after offer.\n\n"
                f"Best regards,\n{contact_footer}"
            )

        return {
            "company": company,
            "title": job_title,
            "recipient_email": target_email or "",
            "subject": clean_subject,
            "cover_letter": cover_letter,
            "cv_language": lang,
            "docx_filename": cv_res["docx_filename"],
            "docx_url": cv_res["docx_url"],
            "pdf_filename": cv_res["pdf_filename"],
            "pdf_url": cv_res["pdf_url"],
        }


cv_generator_service = CVGeneratorService()
