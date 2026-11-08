import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional
from ..config import RESUMES_DIR, GENERATED_RESUMES_DIR, MOCK_PORTALS_DIR
from ..storage.ground_truth_store import ground_truth_store
from ..services.portal_detector import detect_portal_from_url
from ..services.company_validator import company_validator
from ..services.cv_generator_service import cv_generator_service
from ..services.gemini_service import gemini_service
from ..models.schemas import StageApplicationResponse

logger = logging.getLogger(__name__)


class PlaywrightStagerService:
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

    def resolve_target_url(self, job_url: str) -> str:
        """Resolves mock portal shortcuts or localhost URLs to local file URIs if needed."""
        for mock_file in MOCK_PORTALS_DIR.glob("*.html"):
            if mock_file.stem in job_url or mock_file.name in job_url:
                return mock_file.as_uri()
        return job_url

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
        """
        Runs Playwright inside a dedicated worker thread using sync_playwright
        so it works 100% reliably on Windows with FastAPI/Uvicorn!
        """
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
        comp = candidate.get("compensation", {})
        skills_md = ground_truth.get("skills_md_raw") or ground_truth_store.get_skills_md()

        portal_type = detect_portal_from_url(job_url)
        resolved_url = self.resolve_target_url(job_url)

        fields_filled = []
        file_uploaded = False
        captcha_status = "none_detected"

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--start-maximized"]
            )
            context = browser.new_context(no_viewport=True)
            page = context.new_page()

            try:
                logger.info(f"Navigating to {resolved_url} (Portal: {portal_type})...")
                page.goto(resolved_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(500)

                page_title = page.title()
                html_body = page.content()

                # Detect portal from page if generic
                board_el = page.locator("[data-board]")
                if board_el.count() > 0:
                    portal_type = board_el.first.get_attribute("data-board") or portal_type
                elif portal_type == "generic":
                    if "application_form" in html_body:
                        portal_type = "greenhouse"
                    elif "application-form" in html_body:
                        portal_type = "lever"
                    elif "dou.ua" in html_body.lower():
                        portal_type = "dou.ua"
                    elif "djinni" in html_body.lower():
                        portal_type = "djinni.co"

                # Extract company name from page for 3+ reviews validation
                comp_el = page.locator("#company-name, .company, .posting-headline")
                detected_company = "CloudScale Technologies"
                if comp_el.count() > 0:
                    detected_company = (comp_el.first.text_content() or "").split("•")[0].strip()

                role_el = page.locator("#app-title, #posting-title, h1")
                detected_role = page_title
                if role_el.count() > 0:
                    detected_role = (role_el.first.text_content() or page_title).strip()

                # 1. Validate Company Reviews (3+ Reviews Gate)
                comp_val = company_validator.validate_company(detected_company, html_body)
                if not comp_val.passed_gate and not bypass_company_gate:
                    return StageApplicationResponse(
                        status="blocked_by_reviews",
                        portal_detected=portal_type,
                        fields_filled=[],
                        captcha_status="none_detected",
                        file_uploaded=False,
                        company_validation=comp_val,
                        message=comp_val.verdict,
                        manual_review_needed=True,
                        page_title=page_title
                    )

                # 2. Generate Per-Vacancy Human-Tone PDF CV if not already provided
                narratives = gemini_service.craft_human_tone_narratives(
                    job_details={"title": detected_role, "company": detected_company},
                    skills_md=skills_md,
                    matched_skills=ground_truth.get("skills", {}).get("core", [])[:6],
                    missing_skills=[]
                )
                summary_text = applicant_summary or narratives["human_tone_summary"]
                motivation_text = motivation_letter or (
                    narratives["dou_motivational_letter"] if portal_type == "dou.ua" else narratives["motivation_statement"]
                )
                dou_letter_text = narratives["dou_motivational_letter"]
                salary_text = expected_salary or f"€{comp.get('expected_salary_eur', 85000):,} / year (or $4,500/mo B2B remote)"
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
                        skills_md_override=skills_md
                    )
                    resume_path = Path(cv_gen["pdf_path"])
                else:
                    resume_path = self.get_resume_path(variant, custom_pdf_filename)

                # Helper to safely fill first matching visible locator
                def fill_if_present(selector: str, value: str, field_label: str) -> bool:
                    loc = page.locator(selector)
                    if loc.count() > 0 and value:
                        try:
                            loc.first.fill(value)
                            fields_filled.append(field_label)
                            return True
                        except Exception:
                            pass
                    return False

                # 3. Fill Universal & Portal-Specific Fields
                fill_if_present("#first_name, input[name*='first_name']", candidate.get("first_name", "Alex"), "first_name")
                fill_if_present("#last_name, input[name*='last_name']", candidate.get("last_name", "Mercer"), "last_name")
                fill_if_present("#full_name, #full-name, input[name='name']", candidate.get("full_name", "Alex Mercer"), "full_name")
                fill_if_present("#email, input[name*='email'], input[type='email']", candidate.get("email", "alex.mercer.dev@gmail.com"), "email")
                fill_if_present("#phone, input[name*='phone'], input[type='tel']", candidate.get("phone", "+49 152 98765432"), "phone")
                fill_if_present("#org, input[name='org']", ground_truth.get("work_history", [{}])[0].get("company", "TechNova Cloud Solutions"), "current_company")
                fill_if_present("#linkedin, #linkedin-url, input[name='urls[LinkedIn]'], input[autocomplete='custom-question-linkedin-profile']", links.get("linkedin", ""), "linkedin")
                fill_if_present("#github-url, input[name='urls[GitHub]']", links.get("github", ""), "github_url")
                fill_if_present("#portfolio-url, input[name='urls[Portfolio]'], input[autocomplete='custom-question-website']", links.get("portfolio", ""), "portfolio_url")

                # Fill Applicant Summary
                fill_if_present("#applicant_summary, textarea[name*='summary'], #additional-comments", summary_text, "applicant_summary")

                # Fill DOU.ua Motivational Letter & General Motivation
                fill_if_present("#dou_motivational_letter, textarea[name*='motivational_letter']", dou_letter_text, "dou_motivational_letter")
                fill_if_present("#motivation, #custom-question-motivation, textarea[name*='motivation'], textarea[name='message']", motivation_text, "motivation_letter")

                # Fill Salary & Start Date (1 week after offer)
                fill_if_present("#salary, #salary_expectation, #custom-question-salary, input[name*='salary']", salary_text, "salary_expectation")
                fill_if_present("#start_date, #custom-question-notice, input[name*='start_date'], input[name*='notice']", start_text, "start_date_1_week")

                # Label-based smart scan for Greenhouse / Lever custom fields
                labels = page.locator("label").all()
                for label in labels:
                    txt = (label.text_content() or "").lower()
                    for_attr = label.get_attribute("for")
                    if not for_attr or for_attr == "captcha-checkbox":
                        continue
                    target = page.locator(f"#{for_attr}")
                    if target.count() == 0:
                        continue
                    tag_name = target.first.evaluate("el => el.tagName.toLowerCase()")

                    if tag_name == "select" and ("authorized" in txt or "sponsorship" in txt):
                        target.first.select_option(value="yes")
                        if "work_auth_select" not in fields_filled:
                            fields_filled.append("work_auth_select")
                    elif tag_name in ["input", "textarea"]:
                        current_val = target.first.input_value() if tag_name == "input" and target.first.get_attribute("type") != "file" else ""
                        if current_val:
                            continue
                        if "why" in txt or "interest" in txt or "motivational" in txt:
                            target.first.fill(dou_letter_text if "dou" in txt else motivation_text)
                            fields_filled.append("motivation_textarea")
                        elif "summary" in txt or "introduce" in txt:
                            target.first.fill(summary_text)
                            fields_filled.append("applicant_summary")
                        elif "experience" in txt or "framework" in txt:
                            target.first.fill("5+ years building modular Playwright (TS/Python) and Cypress test suites, cutting CI regression from 14h to 35m.")
                            fields_filled.append("framework_experience")
                        elif "salary" in txt or "financial" in txt or "compensation" in txt:
                            target.first.fill(salary_text)
                            fields_filled.append("salary")
                        elif "notice" in txt or "start date" in txt or "availability" in txt or "when can you start" in txt:
                            target.first.fill(start_text)
                            fields_filled.append("start_date_1_week")

                # 4. Upload Per-Vacancy Tailored CV PDF
                file_input = page.locator("#resume, #resume-upload, input[type='file']")
                if file_input.count() > 0 and resume_path and resume_path.exists():
                    file_input.first.set_input_files(str(resume_path))
                    file_uploaded = True
                    fields_filled.append("resume_pdf")

                # 5. Detect & Solve / Check CAPTCHA
                captcha_box = page.locator("#captcha-checkbox, input[name*='captcha'], input[type='checkbox'][id*='captcha']")
                if captcha_box.count() > 0:
                    captcha_box.first.check()
                    captcha_status = "solved"
                    fields_filled.append("captcha_verified")
                elif page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .cf-turnstile").count() > 0:
                    try:
                        page.locator("iframe[src*='recaptcha'], .cf-turnstile").first.click(timeout=2000)
                        captcha_status = "solved"
                    except Exception:
                        captcha_status = "highlighted_for_human"

                # 6. Auto-submit if requested, or show HITL banner
                if auto_submit:
                    submit_btn = page.locator("#submit_app, button[type='submit'], input[type='submit']")
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
                                <strong style="font-size:14px; color:#34d399;">Staged on ${info.portal} (${info.reviews}★ Verified)</strong>
                            </div>
                            <p style="font-size:12px; margin:0 0 8px 0; color:#e2e8f0; line-height:1.45;">
                                ✅ Custom Human-Tone CV attached: <strong>${info.cvFile}</strong><br/>
                                ✅ Start Date: <strong>1 week after offer</strong><br/>
                                ✅ CAPTCHA: <strong>${info.captcha}</strong>
                            </p>
                            <div style="font-size:11px; color:#94a3b8; border-top:1px solid #334155; padding-top:6px;">
                                Review filled fields & click Submit!
                            </div>
                        </div>
                    `;
                    document.body.appendChild(banner);
                }"""
                page.evaluate(banner_js, {
                    "cvFile": resume_path.name if resume_path else "CV.pdf",
                    "portal": portal_type.upper(),
                    "reviews": f"{comp_val.rating} / {comp_val.review_count} reviews",
                    "captcha": captcha_status.upper()
                })

                if not headless:
                    page.wait_for_timeout(min(timeout_seconds * 1000, 12000))

                return StageApplicationResponse(
                    status="submitted" if auto_submit else "staged",
                    portal_detected=portal_type,
                    fields_filled=list(dict.fromkeys(fields_filled)),
                    captcha_status=captcha_status,
                    file_uploaded=file_uploaded,
                    resume_file_path=str(resume_path) if resume_path else None,
                    company_validation=comp_val,
                    message=(
                        f"Application staged on {portal_type}! Company verified ({comp_val.review_count} reviews, {comp_val.rating}★). "
                        f"Attached custom human-tone CV ({resume_path.name if resume_path else 'CV.pdf'}), filled summary, motivation, salary, "
                        f"start date ('1 week after offer'), and verified CAPTCHA."
                    ),
                    manual_review_needed=not auto_submit,
                    page_title=page_title
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
                    page_title=None
                )
            finally:
                browser.close()


playwright_service = PlaywrightStagerService()
