import asyncio
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Pattern
from ..config import RESUMES_DIR, GENERATED_RESUMES_DIR
from ..storage.ground_truth_store import ground_truth_store
from ..services.portal_detector import detect_portal_from_url, detect_portal_from_html
from ..services.company_validator import company_validator
from ..services.cv_generator_service import cv_generator_service
from ..services.gemini_service import gemini_service
from ..services.salary_service import salary_service
from ..models.schemas import StageApplicationResponse

logger = logging.getLogger(__name__)


class PlaywrightStagerService:
    """
    Production Playwright Stager using prioritized semantic accessibility locator cascades:
      1. page.get_by_label(...)
      2. page.get_by_placeholder(...)
      3. page.get_by_role("textbox" / "combobox", name=...)
      4. Semantic input[type=...] / [name*=...] fallback.

    For CAPTCHAs (reCAPTCHA, hCaptcha, Cloudflare Turnstile, or checkbox challenges):
    - Never attempts automated clicking.
    - Detects the challenge, takes a screenshot, pauses automation, and signals the user via HITL modal.
    """

    def get_resume_path(self, variant: str, custom_pdf_filename: Optional[str] = None) -> Optional[Path]:
        if custom_pdf_filename:
            gen_path = GENERATED_RESUMES_DIR / custom_pdf_filename
            if gen_path.exists():
                return gen_path
            direct_path = RESUMES_DIR / custom_pdf_filename
            if direct_path.exists():
                return direct_path

        variants = ground_truth_store.get_cv_variants()
        variant_data = variants.get(variant, {})
        filename = variant_data.get("resume_file", f"resume_{variant}.pdf")
        path = RESUMES_DIR / filename
        if path.exists():
            return path
        resumes = list(GENERATED_RESUMES_DIR.glob("*.pdf")) + list(RESUMES_DIR.glob("*.pdf"))
        return resumes[0] if resumes else None

    async def stage_application(
        self,
        job_url: str,
        variant: str = "qa_automation",
        custom_pdf_filename: Optional[str] = None,
        custom_answers: Optional[Dict[str, str]] = None,
        applicant_summary: Optional[str] = None,
        motivation_letter: Optional[str] = None,
        expected_salary: Optional[str] = None,
        start_date: Optional[str] = "1 week after offer",
        bypass_company_gate: bool = False,
        auto_submit: bool = False,
        headless: bool = False,
        timeout_seconds: int = 12,
    ) -> StageApplicationResponse:
        return await asyncio.to_thread(
            self._stage_sync,
            job_url=job_url,
            variant=variant,
            custom_pdf_filename=custom_pdf_filename,
            custom_answers=custom_answers,
            applicant_summary=applicant_summary,
            motivation_letter=motivation_letter,
            expected_salary=expected_salary,
            start_date=start_date or "1 week after offer",
            bypass_company_gate=bypass_company_gate,
            auto_submit=auto_submit,
            headless=headless,
            timeout_seconds=timeout_seconds,
        )

    def _stage_sync(
        self,
        job_url: str,
        variant: str,
        custom_pdf_filename: Optional[str],
        custom_answers: Optional[Dict[str, str]],
        applicant_summary: Optional[str],
        motivation_letter: Optional[str],
        expected_salary: Optional[str],
        start_date: str,
        bypass_company_gate: bool,
        auto_submit: bool,
        headless: bool,
        timeout_seconds: int,
    ) -> StageApplicationResponse:
        from playwright.sync_api import sync_playwright

        ground_truth = ground_truth_store.get_data()
        candidate = ground_truth.get("candidate", {})
        links = candidate.get("links", {})
        skills_md = ground_truth.get("skills_md_raw") or ground_truth_store.get_skills_md()

        portal_type = detect_portal_from_url(job_url)
        fields_filled: List[str] = []
        file_uploaded = False
        captcha_status = "none_detected"

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--start-maximized"],
            )
            context = browser.new_context(no_viewport=True)
            page = context.new_page()

            try:
                logger.info(f"Navigating to {job_url} (Portal: {portal_type})...")
                page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(400)

                page_title = page.title()
                html_body = page.content()

                detected_portal, html_meta = detect_portal_from_html(html_body, job_url)
                if portal_type == "custom" and detected_portal != "custom":
                    portal_type = detected_portal

                detected_company = html_meta.get("company") or "Hiring Company"
                detected_role = html_meta.get("title") or page_title or "Senior QA Automation Engineer"

                # 1. Validate Company Reputation
                comp_val = company_validator.validate_company(detected_company, html_body)
                if comp_val.is_blacklisted and not bypass_company_gate:
                    return StageApplicationResponse(
                        status="blocked_by_reviews",
                        portal_detected=portal_type,
                        fields_filled=[],
                        captcha_status="none_detected",
                        file_uploaded=False,
                        company_validation=comp_val,
                        message=comp_val.verdict,
                        manual_review_needed=True,
                        page_title=page_title,
                    )

                # 2. Dynamic AI Salary Estimation (no manual user salary input required)
                sal_est = salary_service.estimate_salary(
                    title=detected_role,
                    description=html_meta.get("description_text", ""),
                    market="GE_DOMESTIC" if portal_type in ("jobs.ge", "hr.ge") else "GLOBAL_REMOTE",
                    portal=portal_type,
                )
                salary_text = expected_salary or f"{sal_est['min_salary']:g} - {sal_est['max_salary']:g} {sal_est['currency']}/mo"

                # 3. Generate Per-Vacancy Grounded PDF CV
                narratives = gemini_service.craft_human_tone_narratives(
                    job_details={"title": detected_role, "company": detected_company},
                    skills_md=skills_md,
                    matched_skills=ground_truth.get("skills", {}).get("core", [])[:6],
                    missing_skills=[],
                )
                summary_text = applicant_summary or narratives["human_tone_summary"]
                motivation_text = motivation_letter or (
                    narratives["dou_motivational_letter"] if portal_type == "dou.ua" else narratives["motivation_statement"]
                )
                dou_letter_text = narratives["dou_motivational_letter"]
                start_text = start_date or "1 week after offer"

                if not custom_pdf_filename:
                    cv_gen = cv_generator_service.generate_vacancy_cv(
                        job_title=detected_role,
                        company=detected_company,
                        portal=portal_type,
                        matched_skills=ground_truth.get("skills", {}).get("core", [])[:8],
                        missing_skills=[],
                        human_summary=summary_text,
                        motivation_statement=motivation_text,
                        dou_motivational_letter=dou_letter_text,
                        skills_md_override=skills_md,
                    )
                    resume_path = Path(cv_gen["pdf_path"])
                else:
                    resume_path = self.get_resume_path(variant, custom_pdf_filename)

                # Semantic Accessibility Locator Cascade Helper
                def fill_semantic_cascade(
                    label_regex: Pattern[str],
                    placeholder_regex: Pattern[str],
                    fallback_selector: str,
                    value: str,
                    field_key: str,
                ) -> bool:
                    if not value:
                        return False
                    locators_to_try = [
                        page.get_by_label(label_regex),
                        page.get_by_placeholder(placeholder_regex),
                        page.get_by_role("textbox", name=label_regex),
                        page.locator(fallback_selector),
                    ]
                    for loc in locators_to_try:
                        try:
                            if loc.count() > 0:
                                target = loc.first
                                tag = target.evaluate("el => el.tagName.toLowerCase()")
                                if tag in ("input", "textarea"):
                                    inp_type = (target.get_attribute("type") or "text").lower()
                                    if inp_type not in ("file", "checkbox", "radio", "submit", "button"):
                                        target.fill(value)
                                        if field_key not in fields_filled:
                                            fields_filled.append(field_key)
                                        return True
                        except Exception:
                            continue
                    return False

                # 4. Fill Form Fields via Prioritized Semantic Locators
                fill_semantic_cascade(
                    re.compile(r"first\s*name|სახელი", re.I),
                    re.compile(r"first\s*name", re.I),
                    "input[name*='first_name'], input[autocomplete='given-name']",
                    candidate.get("first_name", "Alex"),
                    "first_name",
                )
                fill_semantic_cascade(
                    re.compile(r"last\s*name|გვარი", re.I),
                    re.compile(r"last\s*name", re.I),
                    "input[name*='last_name'], input[autocomplete='family-name']",
                    candidate.get("last_name", "Mercer"),
                    "last_name",
                )
                fill_semantic_cascade(
                    re.compile(r"full\s*name|your\s*name|სახელი\s*და\s*გვარი", re.I),
                    re.compile(r"full\s*name|your\s*name", re.I),
                    "input[name='name'], input[name*='full_name'], input[autocomplete='name']",
                    candidate.get("full_name", "Alex Mercer"),
                    "full_name",
                )
                fill_semantic_cascade(
                    re.compile(r"e-?mail|ელ\.?\s*ფოსტა", re.I),
                    re.compile(r"email|@", re.I),
                    "input[type='email'], input[name*='email']",
                    candidate.get("email", "alex.mercer.dev@gmail.com"),
                    "email",
                )
                fill_semantic_cascade(
                    re.compile(r"phone|mobile|tel|ტელეფონი", re.I),
                    re.compile(r"phone|\+", re.I),
                    "input[type='tel'], input[name*='phone']",
                    candidate.get("phone", "+49 152 98765432"),
                    "phone",
                )
                fill_semantic_cascade(
                    re.compile(r"current\s*company|organization|employer", re.I),
                    re.compile(r"company|organization", re.I),
                    "input[name='org'], input[name*='company']",
                    ground_truth.get("work_history", [{}])[0].get("company", "TechNova Cloud Solutions"),
                    "current_company",
                )
                fill_semantic_cascade(
                    re.compile(r"linkedin", re.I),
                    re.compile(r"linkedin\.com", re.I),
                    "input[name*='linkedin' i], input[autocomplete*='linkedin' i]",
                    links.get("linkedin", ""),
                    "linkedin",
                )
                fill_semantic_cascade(
                    re.compile(r"github", re.I),
                    re.compile(r"github\.com", re.I),
                    "input[name*='github' i]",
                    links.get("github", ""),
                    "github_url",
                )
                fill_semantic_cascade(
                    re.compile(r"portfolio|website", re.I),
                    re.compile(r"https://", re.I),
                    "input[name*='portfolio' i], input[autocomplete*='website' i]",
                    links.get("portfolio", ""),
                    "portfolio_url",
                )
                fill_semantic_cascade(
                    re.compile(r"applicant\s*summary|introduce\s*yourself|professional\s*summary|additional\s*info", re.I),
                    re.compile(r"summary|introduce", re.I),
                    "textarea[name*='summary' i], textarea[name*='comments' i]",
                    summary_text,
                    "applicant_summary",
                )
                fill_semantic_cascade(
                    re.compile(r"dou.*motivational|motivational\s*letter\s*\(required", re.I),
                    re.compile(r"motivational\s*letter", re.I),
                    "textarea[name*='motivational_letter' i]",
                    dou_letter_text,
                    "dou_motivational_letter",
                )
                fill_semantic_cascade(
                    re.compile(r"why\s*are\s*you\s*interested|cover\s*letter|motivation|message\s*to\s*recruiter", re.I),
                    re.compile(r"motivation|why\s*you", re.I),
                    "textarea[name*='motivation' i], textarea[name='message']",
                    motivation_text,
                    "motivation_letter",
                )
                fill_semantic_cascade(
                    re.compile(r"salary|compensation|financial\s*expectation", re.I),
                    re.compile(r"salary|eur|usd|gel", re.I),
                    "input[name*='salary' i]",
                    salary_text,
                    "salary_expectation",
                )
                fill_semantic_cascade(
                    re.compile(r"start\s*date|notice\s*period|when\s*can\s*you\s*start|availability", re.I),
                    re.compile(r"1\s*week|start\s*date|notice", re.I),
                    "input[name*='start_date' i], input[name*='notice' i]",
                    start_text,
                    "start_date_1_week",
                )
                fill_semantic_cascade(
                    re.compile(r"playwright|cypress|automation\s*framework|experience", re.I),
                    re.compile(r"experience|framework", re.I),
                    "textarea[name*='experience' i]",
                    "5+ years building modular Playwright (TS/Python) and Cypress test suites, cutting CI regression from 14h to 35m.",
                    "framework_experience",
                )

                # Semantic combobox / select handling for work authorization
                auth_select = page.get_by_label(re.compile(r"authorized\s*to\s*work|sponsorship", re.I))
                if auth_select.count() > 0:
                    try:
                        auth_select.first.select_option(value="yes")
                        fields_filled.append("work_auth_select")
                    except Exception:
                        pass

                # 5. Upload Per-Vacancy Tailored CV PDF via semantic label or file input
                file_locator = page.get_by_label(re.compile(r"resume|cv|attach|upload", re.I))
                if file_locator.count() == 0:
                    file_locator = page.locator("input[type='file']")
                if file_locator.count() > 0 and resume_path and resume_path.exists():
                    try:
                        file_locator.first.set_input_files(str(resume_path))
                        file_uploaded = True
                        fields_filled.append("resume_pdf")
                    except Exception:
                        raw_file_inp = page.locator("input[type='file']")
                        if raw_file_inp.count() > 0:
                            raw_file_inp.first.set_input_files(str(resume_path))
                            file_uploaded = True
                            fields_filled.append("resume_pdf")

                # 6. Anti-Bot / CAPTCHA Detection (DO NOT CLICK! Pause & take screenshot for HITL)
                captcha_loc = page.locator(
                    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .cf-turnstile, "
                    "input[name*='captcha' i], [id*='captcha' i]"
                )
                if captcha_loc.count() > 0:
                    captcha_status = "paused_for_human_hitl"
                    fields_filled.append("captcha_paused_hitl")
                    screenshot_path = GENERATED_RESUMES_DIR / "hitl_captcha_pause.png"
                    try:
                        page.screenshot(path=str(screenshot_path), full_page=False)
                        logger.info(f"CAPTCHA challenge detected; saved HITL screenshot to {screenshot_path}")
                    except Exception as sc_err:
                        logger.debug(f"CAPTCHA screenshot note: {sc_err}")

                # 7. Only auto-submit if explicitly requested AND no CAPTCHA challenge is blocking
                if auto_submit and captcha_status == "none_detected":
                    submit_btn = page.get_by_role("button", name=re.compile(r"submit|apply|send", re.I))
                    if submit_btn.count() > 0:
                        submit_btn.first.click()
                        fields_filled.append("form_submitted")

                banner_js = """
                (info) => {
                    const existing = document.getElementById('hitl-staged-banner');
                    if (existing) existing.remove();
                    const banner = document.createElement('div');
                    banner.id = 'hitl-staged-banner';
                    banner.innerHTML = `
                        <div style="position:fixed; top:12px; right:12px; z-index:999999; background:#0f172a; color:#fff; padding:16px 20px; border-radius:12px; box-shadow:0 12px 30px rgba(0,0,0,0.45); border:2px solid #10b981; font-family:sans-serif; max-width:400px;">
                            <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                                <span style="background:#10b981; width:10px; height:10px; border-radius:50%; display:inline-block;"></span>
                                <strong style="font-size:14px; color:#34d399;">HITL Staged on ${info.portal}</strong>
                            </div>
                            <p style="font-size:12px; margin:0 0 8px 0; color:#e2e8f0; line-height:1.45;">
                                ✅ Custom Single-Column CV: <strong>${info.cvFile}</strong><br/>
                                ✅ AI Market Salary: <strong>${info.salary}</strong><br/>
                                ⚠️ CAPTCHA Status: <strong>${info.captcha}</strong>
                            </p>
                            <div style="font-size:11px; color:#94a3b8; border-top:1px solid #334155; padding-top:6px;">
                                Complete any CAPTCHA challenge manually & click Submit!
                            </div>
                        </div>
                    `;
                    document.body.appendChild(banner);
                }"""
                page.evaluate(
                    banner_js,
                    {
                        "cvFile": resume_path.name if resume_path else "CV.pdf",
                        "portal": portal_type.upper(),
                        "salary": salary_text,
                        "captcha": captcha_status.upper(),
                    },
                )

                if not headless:
                    page.wait_for_timeout(min(timeout_seconds * 1000, 12000))

                return StageApplicationResponse(
                    status="submitted" if (auto_submit and captcha_status == "none_detected") else "staged",
                    portal_detected=portal_type,
                    fields_filled=list(dict.fromkeys(fields_filled)),
                    captcha_status=captcha_status,
                    file_uploaded=file_uploaded,
                    resume_file_path=str(resume_path) if resume_path else None,
                    company_validation=comp_val,
                    message=(
                        f"Application staged on {portal_type} via semantic locators. "
                        f"Attached single-column ATS PDF ({resume_path.name if resume_path else 'CV.pdf'}), "
                        f"AI salary ({salary_text}), and paused for human CAPTCHA/review ({captcha_status})."
                    ),
                    manual_review_needed=True,
                    page_title=page_title,
                )

            except Exception as e:
                logger.error(f"Error during Playwright staging: {e}", exc_info=True)
                return StageApplicationResponse(
                    status="error",
                    portal_detected=portal_type,
                    fields_filled=fields_filled,
                    captcha_status=captcha_status,
                    file_uploaded=file_uploaded,
                    resume_file_path=None,
                    message=f"Staging encountered an issue: {str(e)}",
                    manual_review_needed=True,
                    page_title=None,
                )
            finally:
                browser.close()


playwright_service = PlaywrightStagerService()
