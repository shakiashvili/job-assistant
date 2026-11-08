import re
import textwrap
import logging
import concurrent.futures
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..config import GENERATED_RESUMES_DIR
from ..storage.ground_truth_store import ground_truth_store
from ..services.gemini_service import GEORGIAN_SKILL_TRANSLATIONS

logger = logging.getLogger(__name__)

_pdf_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _sanitize_pdf_text(text: str) -> str:
    """Fallback ASCII sanitizer for Type1 Helvetica when Chromium PDF is skipped."""
    replacements = {
        "—": "-", "–": "-", "•": "*", "“": '"', "”": '"', "’": "'", "‘": "'", "€": "EUR ",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class CVGeneratorService:
    """
    Generates a tailored, human-tone PDF CV for each specific job vacancy
    in either English ('en') or Georgian ('ka' - ქართული ენა)
    based on the user's attached candidate_skills.md + ground_truth.json.
    """

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

        md_skills = parsed_md.get("skills") or []
        core_skills = md_skills or gt.get("skills", {}).get("core", [])
        work_history = parsed_md.get("work_history") or gt.get("work_history", [])

        # Order skills so matched ATS keywords appear first
        matched_lower = {s.lower() for s in matched_skills}
        prioritized_skills = sorted(
            core_skills,
            key=lambda s: (0 if any(m in s.lower() or s.lower() in m for m in matched_lower) else 1)
        )

        if cv_language == "ka":
            display_skills = [GEORGIAN_SKILL_TRANSLATIONS.get(s, s) for s in prioritized_skills]
        else:
            display_skills = prioritized_skills

        lang_suffix = "KA" if cv_language == "ka" else "EN"
        safe_company = re.sub(r"[^A-Za-z0-9]+", "_", company or "Company").strip("_")[:22]
        safe_role = re.sub(r"[^A-Za-z0-9]+", "_", job_title or "Role").strip("_")[:26]
        base_name = f"CV_{safe_company}_{safe_role}_{lang_suffix}"
        pdf_filename = f"{base_name}.pdf"
        html_filename = f"{base_name}.html"
        pdf_path = GENERATED_RESUMES_DIR / pdf_filename
        html_path = GENERATED_RESUMES_DIR / html_filename

        tailored_highlights = []
        for job in work_history:
            for h in job.get("highlights", [])[:2]:
                tailored_highlights.append(f"{job.get('role')} @ {job.get('company')}: {h}")

        # 1. Build rich HTML CV (supports full Georgian Unicode & English)
        html_content = self._build_cv_html(
            candidate=candidate,
            target_role=job_title,
            target_company=company,
            human_summary=human_summary,
            display_skills=display_skills,
            work_history=work_history,
            education=gt.get("education", []),
            cv_language=cv_language,
        )
        html_path.write_text(html_content, encoding="utf-8")

        # 2. Render PDF (Uses Chromium HTML-to-PDF for Georgian 'ka' or rich layout, with instant fallback)
        rendered_via_chromium = False
        if cv_language == "ka":
            try:
                future = _pdf_executor.submit(self._render_html_to_pdf_sync, html_content, pdf_path)
                future.result(timeout=8)
                rendered_via_chromium = pdf_path.exists() and pdf_path.stat().st_size > 500
            except Exception as e:
                logger.warning(f"Chromium PDF render fallback: {e}")

        if not rendered_via_chromium:
            self._write_formatted_pdf(
                filepath=pdf_path,
                candidate=candidate,
                target_role=job_title,
                target_company=company,
                human_summary=human_summary,
                prioritized_skills=display_skills,
                work_history=work_history,
                education=gt.get("education", []),
            )

        start_date_str = "1 კვირა შეთავაზებიდან (1 week after offer)" if cv_language == "ka" else "1 week after offer"

        return {
            "pdf_filename": pdf_filename,
            "pdf_url": f"/api/resumes/generated/{pdf_filename}",
            "html_preview_url": f"/api/resumes/generated/{html_filename}",
            "pdf_path": str(pdf_path),
            "cv_language": cv_language,
            "candidate_name": candidate.get("full_name", "Alex Mercer"),
            "target_role": job_title,
            "human_tone_summary": human_summary,
            "applicant_summary": human_summary,
            "motivation_statement": motivation_statement,
            "dou_motivational_letter": dou_motivational_letter,
            "tailored_highlights": tailored_highlights,
            "ats_keywords_covered": matched_skills or display_skills[:8],
            "start_date_default": start_date_str,
            "expected_salary": f"EUR {candidate.get('compensation', {}).get('expected_salary_eur', 85000):,} / year (or local market rate)"
        }

    def _render_html_to_pdf_sync(self, html_content: str, pdf_path: Path) -> None:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html_content, wait_until="domcontentloaded")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "14mm", "bottom": "14mm", "left": "15mm", "right": "15mm"}
            )
            browser.close()

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
        full_name = candidate.get("full_name", "Alex Mercer")
        email = candidate.get("email", "alex.mercer.dev@gmail.com")
        phone = candidate.get("phone", "+995 599 12 34 56")
        loc = candidate.get("location", {}).get("city", "Tbilisi") + ", " + candidate.get("location", {}).get("country", "Georgia")
        linkedin = candidate.get("links", {}).get("linkedin", "linkedin.com/in/candidate")

        lbl_summary = f"პროფესიული მიმოხილვა ({target_company})" if is_ka else f"PROFESSIONAL SUMMARY (TAILORED FOR {target_company.upper()})"
        lbl_skills = "ძირითადი უნარები და კომპეტენციები" if is_ka else "CORE SKILLS & COMPETENCIES"
        lbl_exp = "სამუშაო გამოცდილება" if is_ka else "PROFESSIONAL WORK EXPERIENCE"
        lbl_edu = "განათლება და ენები" if is_ka else "EDUCATION & AVAILABILITY"
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

    def _write_formatted_pdf(
        self,
        filepath: Path,
        candidate: Dict[str, Any],
        target_role: str,
        target_company: str,
        human_summary: str,
        prioritized_skills: List[str],
        work_history: List[Dict[str, Any]],
        education: List[Dict[str, Any]],
    ) -> None:
        """Fast pure-Python PDF writer."""
        commands = []
        y = 755

        def add_line(text: str, font: str = "F1", size: int = 10, indent: int = 48, spacing: int = 14):
            nonlocal y
            if y < 45:
                return
            safe = _sanitize_pdf_text(text)
            commands.append(f"BT /{font} {size} Tf {indent} {y} Td ({safe}) Tj ET")
            y -= spacing

        def add_wrapped(text: str, font: str = "F1", size: int = 9, width: int = 92, indent: int = 48, spacing: int = 12):
            for line in textwrap.wrap(text, width=width):
                add_line(line, font=font, size=size, indent=indent, spacing=spacing)

        def add_divider():
            nonlocal y
            y -= 2
            commands.append(f"0.75 0.78 0.82 RG 0.8 w 48 {y + 6} m 564 {y + 6} l S")
            y -= 10

        full_name = candidate.get("full_name", "Alex Mercer")
        email = candidate.get("email", "alex.mercer.dev@gmail.com")
        phone = candidate.get("phone", "+49 152 98765432")
        loc = candidate.get("location", {}).get("city", "Tbilisi") + ", " + candidate.get("location", {}).get("country", "Georgia")
        linkedin = candidate.get("links", {}).get("linkedin", "linkedin.com/in/candidate")

        add_line(f"{full_name}  -  {target_role}", font="F2", size=15, spacing=16)
        add_line(f"{email}  |  {phone}  |  {loc}", font="F1", size=9, spacing=12)
        add_line(f"LinkedIn: {linkedin}  |  Availability: 1 week after offer", font="F1", size=8, spacing=12)
        add_divider()

        add_line(f"SUMMARY (TAILORED FOR {target_company.upper()})", font="F2", size=10, spacing=13)
        add_wrapped(human_summary, font="F1", size=9, width=95, spacing=12)
        y -= 4
        add_divider()

        add_line("CORE SKILLS & COMPETENCIES", font="F2", size=10, spacing=13)
        skills_str = ", ".join(prioritized_skills[:18])
        add_wrapped(skills_str, font="F1", size=9, width=95, spacing=12)
        y -= 4
        add_divider()

        add_line("PROFESSIONAL WORK EXPERIENCE", font="F2", size=10, spacing=14)
        for job in work_history[:3]:
            role_line = f"{job.get('role', '')}  |  {job.get('company', '')} ({job.get('start_date', '')} - {job.get('end_date', '')})"
            add_line(role_line, font="F2", size=9, spacing=12)
            for bullet in job.get("highlights", [])[:3]:
                for idx, wrapped_line in enumerate(textwrap.wrap(bullet, width=88)):
                    prefix = "* " if idx == 0 else "  "
                    add_line(prefix + wrapped_line, font="F1", size=9, indent=56, spacing=11)
            y -= 4

        add_divider()
        add_line("EDUCATION & LANGUAGES", font="F2", size=10, spacing=13)
        for edu in education:
            add_line(f"{edu.get('degree', 'Degree')} - {edu.get('institution', '')} ({edu.get('graduation_year', '')})", font="F1", size=9, spacing=12)
        add_line("Languages: English (Fluent), Georgian (Native)  |  Start Date: 1 week after offer", font="F1", size=9, spacing=12)

        content_stream = "\n".join(commands)
        stream_bytes = content_stream.encode("latin-1", "replace")
        stream_len = len(stream_bytes)

        pdf_header = (
            "%PDF-1.4\n"
            "1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
            "2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
            "3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources <</Font <</F1 4 0 R /F2 5 0 R>>>> /Contents 6 0 R>> endobj\n"
            "4 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
            "5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold>> endobj\n"
            f"6 0 obj <</Length {stream_len}>> stream\n"
        ).encode("latin-1")

        pdf_footer = (
            "\nendstream\nendobj\n"
            "xref\n0 7\n"
            "0000000000 65535 f \n"
            "trailer <</Size 7 /Root 1 0 R>>\n"
            "startxref\n0\n%%EOF"
        ).encode("latin-1")

        with open(filepath, "wb") as f:
            f.write(pdf_header + stream_bytes + pdf_footer)


cv_generator_service = CVGeneratorService()
