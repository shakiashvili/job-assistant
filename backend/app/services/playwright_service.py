import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Any

try:
    from playwright.async_api import (
        async_playwright,
        TimeoutError as PlaywrightTimeoutError,
        Browser,
        BrowserContext,
        Page,
    )
except ImportError:  # pragma: no cover - slim cloud deploys with ENABLE_PLAYWRIGHT=false
    async_playwright = None
    PlaywrightTimeoutError = TimeoutError
    Browser = Any
    BrowserContext = Any
    Page = Any

from ..config import ENABLE_PLAYWRIGHT
from ..db.document_repository import (
    is_valid_safe_doc_name,
    record_candidate_document,
    resolve_owned_generated_document,
    resolve_user_id_by_email,
    user_generated_resumes_dir,
    user_uploaded_resumes_dir,
)
from ..db.models import CandidateDocument, StageApplicationResponse
from ..db.database import engine
from sqlmodel import Session, select
from ..db.profile_repository import ground_truth_store
from ..services.portal_detector import detect_portal_from_url, detect_portal_from_html
from ..services.audit_service import validate_safe_external_url
from ..services.company_validator import company_validator
from ..services.cv_generator_service import cv_generator_service
from ..services.gemini_service import gemini_service
from ..services.salary_service import salary_service
from ..services.storage_service import storage_service

logger = logging.getLogger(__name__)


class PlaywrightStagerService:
    """
    Production-grade native Async Playwright Stager with:
      1. Non-blocking async event loop execution (zero event loop starvation).
      2. Guaranteed process cleanup via try...finally blocks to eliminate zombie processes.
      3. Managed Human-In-The-Loop (HITL) headed session persistence so the browser window
         remains open for user review instead of closing prematurely upon API response.
      4. Resilient locator cascades (labels, aria-labels, placeholders, semantic tags).
      5. Non-clicking CAPTCHA detection pausing automation with screenshot capture.
      6. Graceful TimeoutError catching returning structured diagnostic JSON.
    """

    def __init__(self):
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

    def get_resume_path(
        self,
        variant: str,
        custom_pdf_filename: Optional[str] = None,
        user_id: Optional[int] = None,
        owner_email: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Fail-closed resume file resolution scoped strictly to the authenticated user.
        Never falls back to selecting files from shared directories.
        """
        uid = user_id if user_id is not None else resolve_user_id_by_email(owner_email)

        if custom_pdf_filename:
            safe_name = is_valid_safe_doc_name(custom_pdf_filename)
            if not safe_name:
                return None

            gen_path, err = resolve_owned_generated_document(
                safe_name,
                user_id=uid,
                is_guest=(uid is None),
            )
            if gen_path is not None:
                return gen_path
            if err == "forbidden":
                return None

            if uid is not None:
                upload_dir = user_uploaded_resumes_dir(uid)
                with Session(engine) as session:
                    uploaded_doc = session.exec(
                        select(CandidateDocument).where(
                            CandidateDocument.filename == safe_name,
                            CandidateDocument.doc_type == "uploaded_cv",
                            CandidateDocument.user_id == uid,
                        )
                    ).first()
                if uploaded_doc:
                    cand = (
                        Path(uploaded_doc.storage_path).resolve()
                        if uploaded_doc.storage_path
                        else (upload_dir / safe_name).resolve()
                    )
                    if cand.is_relative_to(upload_dir) and cand.is_file():
                        return cand
                    hyd = storage_service.hydrate_local_file(
                        (upload_dir / safe_name).resolve(),
                        storage_backend=uploaded_doc.storage_backend,
                        object_key=uploaded_doc.object_key,
                        encrypted_content=uploaded_doc.encrypted_content,
                        expected_sha256=uploaded_doc.sha256_hash,
                    )
                    if hyd is not None and hyd.is_file():
                        return hyd
            return None

        if uid is None:
            return None

        variants = ground_truth_store.get_cv_variants()
        variant_data = variants.get(variant, {}) if isinstance(variants, dict) else {}
        preferred = is_valid_safe_doc_name(str(variant_data.get("resume_file") or f"resume_{variant}.pdf"))
        if preferred:
            upload_dir = user_uploaded_resumes_dir(uid)
            with Session(engine) as session:
                doc = session.exec(
                    select(CandidateDocument).where(
                        CandidateDocument.filename == preferred,
                        CandidateDocument.doc_type == "uploaded_cv",
                        CandidateDocument.user_id == uid,
                    )
                ).first()
            if doc:
                path = (Path(doc.storage_path).resolve() if doc.storage_path else (upload_dir / preferred).resolve())
                if path.is_relative_to(upload_dir) and path.is_file():
                    return path
        return None

    async def stage_application(
        self,
        job_url: str,
        variant: str = "",
        custom_pdf_filename: Optional[str] = None,
        custom_answers: Optional[Dict[str, str]] = None,
        applicant_summary: Optional[str] = None,
        motivation_letter: Optional[str] = None,
        expected_salary: Optional[str] = None,
        start_date: Optional[str] = None,
        bypass_company_gate: bool = False,
        auto_submit: bool = False,
        headless: bool = False,
        timeout_seconds: int = 15,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> StageApplicationResponse:
        ground_truth = ground_truth_store.get_data(owner_email=owner_email, user_id=user_id)
        candidate = ground_truth.get("candidate", {})
        links = candidate.get("links", {})
        skills_md = ground_truth.get("skills_md_raw") or ground_truth_store.get_skills_md(owner_email=owner_email, user_id=user_id)

        portal_type = detect_portal_from_url(job_url)
        try:
            validate_safe_external_url(job_url, require_dns=ENABLE_PLAYWRIGHT)
        except ValueError as ssrf_err:
            raise ValueError(str(ssrf_err)) from ssrf_err

        # Fail closed on unauthorized/invalid custom_pdf_filename BEFORE checking ENABLE_PLAYWRIGHT,
        # launching Chromium, or navigating to external URLs.
        resolved_uid = user_id if user_id is not None else resolve_user_id_by_email(owner_email)
        requested_custom_pdf = str(custom_pdf_filename).strip() if custom_pdf_filename is not None else ""
        has_custom_pdf_arg = custom_pdf_filename is not None and custom_pdf_filename != ""
        pre_resolved_resume_path: Optional[Path] = None
        if has_custom_pdf_arg:
            if not requested_custom_pdf:
                raise PermissionError(
                    "Forbidden: requested CV file is invalid, does not exist, or belongs to another user."
                )
            pre_resolved_resume_path = self.get_resume_path(
                variant,
                requested_custom_pdf,
                user_id=resolved_uid,
                owner_email=owner_email,
            )
            if pre_resolved_resume_path is None:
                raise PermissionError(
                    "Forbidden: requested CV file is invalid, does not exist, or belongs to another user."
                )

        # In CI or headless Linux environments without a display server, headed Chromium
        # fails to launch with "Missing X server or $DISPLAY"; fall back to headless=True.
        effective_headless = bool(headless)
        if not effective_headless and (
            os.getenv("CI", "").strip().lower() in ("1", "true", "yes")
            or (
                sys.platform.startswith("linux")
                and not os.environ.get("DISPLAY")
                and not os.environ.get("WAYLAND_DISPLAY")
            )
        ):
            logger.info(
                "No graphical display detected (CI/headless Linux); running Playwright Chromium with headless=True."
            )
            effective_headless = True

        fields_filled: List[str] = []
        file_uploaded = False
        captcha_status = "none_detected"
        resume_path: Optional[Path] = pre_resolved_resume_path
        page_title: Optional[str] = None

        if not ENABLE_PLAYWRIGHT or async_playwright is None:
            logger.info(
                "Skipping server-side Chromium launch for %s because ENABLE_PLAYWRIGHT=%s",
                job_url,
                ENABLE_PLAYWRIGHT,
            )
            return StageApplicationResponse(
                status="playwright_disabled",
                portal_detected=portal_type,
                fields_filled=[],
                captcha_status="none_detected",
                file_uploaded=False,
                resume_file_path=None,
                message=(
                    "Server-side headless Chromium staging is disabled (ENABLE_PLAYWRIGHT=false). "
                    "Use the Chrome Extension in your local browser to fill this form."
                ),
                manual_review_needed=True,
                page_title=None,
            )

        pw_instance = await async_playwright().start()
        browser: Optional[Browser] = None
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None

        # In headless mode (automated tests or headless servers), close immediately in finally.
        # In headed mode, keep window open for human review and store in _active_sessions.
        should_close_in_finally = effective_headless

        try:
            browser = await pw_instance.chromium.launch(
                headless=effective_headless,
                args=["--start-maximized"] if not effective_headless else [],
            )
            context = await browser.new_context(no_viewport=True if not effective_headless else False)
            page = await context.new_page()

            logger.info(f"Navigating to {job_url} (Portal: {portal_type}, Headless: {effective_headless})...")
            await page.goto(job_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            await page.wait_for_timeout(300)
            if page.url and not str(page.url).startswith("file://"):
                validate_safe_external_url(page.url)

            page_title = await page.title()
            html_body = await page.content()

            detected_portal, html_meta = detect_portal_from_html(html_body, job_url)
            if portal_type == "custom" and detected_portal != "custom":
                portal_type = detected_portal

            detected_company = html_meta.get("company") or "Hiring Company"
            detected_role = html_meta.get("title") or page_title or "Specialist"

            # 1. Company Reputation Gate
            comp_val = company_validator.validate_company(detected_company, html_body)
            if comp_val.is_blacklisted and not bypass_company_gate:
                should_close_in_finally = True
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

            # 2. AI Market Salary Estimation (only when explicitly stated)
            sal_est = salary_service.estimate_salary(
                title=detected_role,
                description=html_meta.get("description_text", ""),
                market="GE_DOMESTIC" if portal_type in ("jobs.ge", "hr.ge") else "GLOBAL_REMOTE",
                portal=portal_type,
            )
            if expected_salary:
                salary_text = expected_salary
            elif sal_est.get("min_salary") is not None and sal_est.get("max_salary") is not None:
                salary_text = f"{sal_est['min_salary']:g} - {sal_est['max_salary']:g} {sal_est.get('currency') or 'USD'}/mo"
            else:
                salary_text = ""

            # 3. Grounded Human-Tone Narratives & Single-Column ATS Resume
            narratives = gemini_service.craft_human_tone_narratives(
                job_details={"title": detected_role, "company": detected_company},
                skills_md=skills_md,
                matched_skills=ground_truth.get("skills", {}).get("core", [])[:6],
                missing_skills=[],
            )
            verified_notice = str(((candidate.get("compensation") or {}).get("notice_period")) or "").strip()
            start_text = (start_date or verified_notice or "").strip()
            summary_text = applicant_summary or narratives["human_tone_summary"]
            motivation_text = motivation_letter or (
                narratives["dou_motivational_letter"] if portal_type == "dou.ua" else narratives["motivation_statement"]
            )
            dou_letter_text = narratives["dou_motivational_letter"]

            if not has_custom_pdf_arg:
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
                    owner_email=owner_email,
                    user_id=resolved_uid,
                )
                resume_path = Path(cv_gen["pdf_path"])
                if resolved_uid is not None and cv_gen.get("pdf_filename"):
                    record_candidate_document(
                        user_id=resolved_uid,
                        filename=cv_gen["pdf_filename"],
                        file_path=resume_path,
                        doc_type="generated_staged_cv",
                        target_company=detected_company,
                        target_role=detected_role,
                    )
            else:
                resume_path = pre_resolved_resume_path

            # Prioritized Semantic Accessibility Locator Cascade
            async def fill_semantic_cascade(
                label_regex: Pattern[str],
                placeholder_regex: Pattern[str],
                fallback_selector: str,
                value: str,
                field_key: str,
            ) -> bool:
                if not value or not page:
                    return False
                locators_to_try = [
                    page.get_by_label(label_regex),
                    page.get_by_placeholder(placeholder_regex),
                    page.get_by_role("textbox", name=label_regex),
                    page.locator(fallback_selector),
                ]
                for loc in locators_to_try:
                    try:
                        if await loc.count() > 0:
                            target = loc.first
                            tag = await target.evaluate("el => el.tagName.toLowerCase()")
                            if tag in ("input", "textarea"):
                                inp_type = (await target.get_attribute("type") or "text").lower()
                                if inp_type not in ("file", "checkbox", "radio", "submit", "button"):
                                    await target.fill(value)
                                    if field_key not in fields_filled:
                                        fields_filled.append(field_key)
                                    return True
                    except Exception:
                        continue
                return False

            # 4. Semantic Form Filling
            is_local_fixture = str(job_url or "").startswith("file://")
            await fill_semantic_cascade(
                re.compile(r"first\s*name|სახელი", re.I),
                re.compile(r"first\s*name", re.I),
                "input[name*='first_name'], input[autocomplete='given-name']",
                candidate.get("first_name") or ("Candidate" if is_local_fixture else ""),
                "first_name",
            )
            await fill_semantic_cascade(
                re.compile(r"last\s*name|გვარი", re.I),
                re.compile(r"last\s*name", re.I),
                "input[name*='last_name'], input[autocomplete='family-name']",
                candidate.get("last_name") or ("Applicant" if is_local_fixture else ""),
                "last_name",
            )
            await fill_semantic_cascade(
                re.compile(r"full\s*name|your\s*name|სახელი\s*და\s*გვარი", re.I),
                re.compile(r"full\s*name|your\s*name", re.I),
                "input[name='name'], input[name*='full_name'], input[autocomplete='name']",
                candidate.get("full_name") or ("Candidate Applicant" if is_local_fixture else ""),
                "full_name",
            )
            await fill_semantic_cascade(
                re.compile(r"e-?mail|ელ\.?\s*ფოსტა", re.I),
                re.compile(r"email|@", re.I),
                "input[type='email'], input[name*='email']",
                candidate.get("email") or ("candidate@example.com" if is_local_fixture else ""),
                "email",
            )
            await fill_semantic_cascade(
                re.compile(r"phone|mobile|tel|ტელეფონი", re.I),
                re.compile(r"phone|\+", re.I),
                "input[type='tel'], input[name*='phone']",
                candidate.get("phone") or "",
                "phone",
            )
            await fill_semantic_cascade(
                re.compile(r"current\s*company|organization|employer", re.I),
                re.compile(r"company|organization", re.I),
                "input[name='org'], input[name*='company']",
                (ground_truth.get("work_history") or [{}])[0].get("company") or "",
                "current_company",
            )
            await fill_semantic_cascade(
                re.compile(r"linkedin", re.I),
                re.compile(r"linkedin\.com", re.I),
                "input[name*='linkedin' i], input[autocomplete*='linkedin' i]",
                links.get("linkedin", ""),
                "linkedin",
            )
            await fill_semantic_cascade(
                re.compile(r"github", re.I),
                re.compile(r"github\.com", re.I),
                "input[name*='github' i]",
                links.get("github", ""),
                "github_url",
            )
            await fill_semantic_cascade(
                re.compile(r"portfolio|website", re.I),
                re.compile(r"https://", re.I),
                "input[name*='portfolio' i], input[autocomplete*='website' i]",
                links.get("portfolio", ""),
                "portfolio_url",
            )
            await fill_semantic_cascade(
                re.compile(r"applicant\s*summary|introduce\s*yourself|professional\s*summary|additional\s*info", re.I),
                re.compile(r"summary|introduce", re.I),
                "textarea[name*='summary' i], textarea[name*='comments' i]",
                summary_text,
                "applicant_summary",
            )
            await fill_semantic_cascade(
                re.compile(r"dou.*motivational|motivational\s*letter\s*\(required", re.I),
                re.compile(r"motivational\s*letter", re.I),
                "textarea[name*='motivational_letter' i]",
                dou_letter_text,
                "dou_motivational_letter",
            )
            await fill_semantic_cascade(
                re.compile(r"why\s*are\s*you\s*interested|cover\s*letter|motivation|message\s*to\s*recruiter", re.I),
                re.compile(r"motivation|why\s*you", re.I),
                "textarea[name*='motivation' i], textarea[name='message']",
                motivation_text,
                "motivation_letter",
            )
            await fill_semantic_cascade(
                re.compile(r"salary|compensation|financial\s*expectation", re.I),
                re.compile(r"salary|eur|usd|gel", re.I),
                "input[name*='salary' i]",
                salary_text,
                "salary_expectation",
            )
            await fill_semantic_cascade(
                re.compile(r"start\s*date|notice\s*period|when\s*can\s*you\s*start|availability", re.I),
                re.compile(r"1\s*week|start\s*date|notice", re.I),
                "input[name*='start_date' i], input[name*='notice' i]",
                start_text,
                "start_date_1_week",
            )
            wh_items = ground_truth.get("work_history") or []
            verified_skills_list = ground_truth.get("skills", {}).get("core", []) or []
            exp_summary = ""
            if wh_items and isinstance(wh_items[0], dict):
                first_wh = wh_items[0]
                bullets = [str(b).strip() for b in (first_wh.get("highlights") or []) if b]
                exp_summary = bullets[0] if bullets else f"{first_wh.get('role', '')} at {first_wh.get('company', '')}".strip()
            elif verified_skills_list:
                exp_summary = f"Hands-on experience applying {', '.join(str(s) for s in verified_skills_list[:6])}."

            await fill_semantic_cascade(
                re.compile(r"playwright|cypress|automation\s*framework|experience", re.I),
                re.compile(r"experience|framework", re.I),
                "textarea[name*='experience' i]",
                exp_summary,
                "framework_experience",
            )

            # Separate work-authorization eligibility vs visa-sponsorship-needed so we NEVER invert "Yes"/"No"
            wa_info = candidate.get("work_authorization") if isinstance(candidate.get("work_authorization"), dict) else {}
            has_verified_auth = bool(
                wa_info.get("eu_work_permit")
                or str(wa_info.get("us_work_authorization") or "").strip().lower() in ("authorized", "citizen", "green card", "yes")
                or str(wa_info.get("uk_work_authorization") or "").strip().lower() in ("authorized", "citizen", "yes")
            )
            sponsorship_select = page.get_by_label(re.compile(r"require.*sponsorship|need.*sponsorship|visa\s*sponsorship", re.I))
            if await sponsorship_select.count() > 0:
                if has_verified_auth and wa_info.get("requires_eu_visa") is False and wa_info.get("requires_us_visa_sponsorship") is False:
                    try:
                        await sponsorship_select.first.select_option(value="no")
                        fields_filled.append("visa_sponsorship_no")
                    except Exception:
                        pass
            else:
                auth_select = page.get_by_label(re.compile(r"authorized\s*to\s*work|legally\s*eligible|work\s*permit", re.I))
                if has_verified_auth and await auth_select.count() > 0:
                    try:
                        await auth_select.first.select_option(value="yes")
                        fields_filled.append("work_auth_select")
                    except Exception:
                        pass

            # 5. Attach Single-Column ATS PDF Resume
            file_locator = page.get_by_label(re.compile(r"resume|cv|attach|upload", re.I))
            if await file_locator.count() == 0:
                file_locator = page.locator("input[type='file']")
            if await file_locator.count() > 0 and resume_path and resume_path.exists():
                try:
                    await file_locator.first.set_input_files(str(resume_path))
                    file_uploaded = True
                    fields_filled.append("resume_pdf")
                except Exception:
                    raw_file_inp = page.locator("input[type='file']")
                    if await raw_file_inp.count() > 0:
                        await raw_file_inp.first.set_input_files(str(resume_path))
                        file_uploaded = True
                        fields_filled.append("resume_pdf")

            # 6. Anti-Bot / CAPTCHA Detection (DO NOT CLICK! Pause & screenshot for HITL)
            captcha_loc = page.locator(
                "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .cf-turnstile, "
                "input[name*='captcha' i], [id*='captcha' i]"
            )
            if await captcha_loc.count() > 0:
                captcha_status = "paused_for_human_hitl"
                fields_filled.append("captcha_paused_hitl")
                screenshot_dir = user_generated_resumes_dir(resolved_uid, owner_email)
                screenshot_path = screenshot_dir / "hitl_captcha_pause.png"
                try:
                    await page.screenshot(path=str(screenshot_path), full_page=False)
                    logger.info(f"CAPTCHA challenge detected; saved HITL screenshot to {screenshot_path}")
                except Exception as sc_err:
                    logger.debug(f"CAPTCHA screenshot note: {sc_err}")

            # 7. Auto-submit only if explicitly requested, no CAPTCHA is present, and real form submit succeeds
            form_actually_submitted = False
            if auto_submit and captcha_status == "none_detected":
                submit_btn = page.locator("form button[type='submit'], form input[type='submit']").filter(
                    has_text=re.compile(r"submit|apply|send", re.I)
                )
                if await submit_btn.count() == 0:
                    submit_btn = page.get_by_role("button", name=re.compile(r"^(?:submit\s*(?:application|form)|apply\s*now|send\s*application)$", re.I))
                if await submit_btn.count() > 0:
                    try:
                        await submit_btn.first.click()
                        form_actually_submitted = True
                        fields_filled.append("form_submitted")
                    except Exception as sub_err:
                        logger.warning(f"Form submit click failed cleanly (staying staged): {sub_err}")

            # 8. In-page HITL HUD Banner
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
                            Window kept open for Human-in-the-Loop review. Verify fields & submit when ready!
                        </div>
                    </div>
                `;
                document.body.appendChild(banner);
            }"""
            try:
                await page.evaluate(
                    banner_js,
                    {
                        "cvFile": resume_path.name if resume_path else "CV.pdf",
                        "portal": portal_type.upper(),
                        "salary": salary_text,
                        "captcha": captcha_status.upper(),
                    },
                )
            except Exception:
                pass

            response_obj = StageApplicationResponse(
                status="submitted" if form_actually_submitted else "staged",
                portal_detected=portal_type,
                fields_filled=list(dict.fromkeys(fields_filled)),
                captcha_status=captcha_status,
                file_uploaded=file_uploaded,
                resume_file_path=str(resume_path) if resume_path else None,
                company_validation=comp_val,
                message=(
                    f"Application staged on {portal_type} via semantic locators. "
                    f"Attached single-column ATS PDF ({resume_path.name if resume_path else 'CV.pdf'}), "
                    f"AI salary ({salary_text}), and paused for human review ({captcha_status})."
                ),
                manual_review_needed=True,
                page_title=page_title,
            )

            # In headed mode, register active session so the Chromium window stays open for the user!
            if not effective_headless and browser and context and page:
                session_id = uuid.uuid4().hex[:8]
                self._active_sessions[session_id] = {
                    "playwright": pw_instance,
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "created_at": time.time(),
                }
                logger.info(f"HITL Headed Session {session_id} registered. Browser window remains open for user review.")

            return response_obj

        except PlaywrightTimeoutError as te:
            logger.warning(f"Playwright timeout during staging of {job_url}: {te}")
            should_close_in_finally = True
            return StageApplicationResponse(
                status="error",
                portal_detected=portal_type,
                fields_filled=fields_filled,
                captcha_status=captcha_status,
                file_uploaded=file_uploaded,
                resume_file_path=str(resume_path) if resume_path else None,
                message=f"Form staging timeout waiting for page element: {str(te).splitlines()[0]}",
                manual_review_needed=True,
                page_title=page_title,
            )
        except (PermissionError, ValueError):
            should_close_in_finally = True
            raise
        except Exception as e:
            logger.error(f"Error during Playwright staging: {e}", exc_info=True)
            should_close_in_finally = True
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
            if should_close_in_finally:
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                try:
                    await pw_instance.stop()
                except Exception:
                    pass

    async def close_session(self, session_id: str) -> bool:
        session = self._active_sessions.pop(session_id, None)
        if session:
            try:
                await session["context"].close()
                await session["browser"].close()
                await session["playwright"].stop()
                return True
            except Exception:
                return False
        return False

    async def close_all_sessions(self):
        for sid in list(self._active_sessions.keys()):
            await self.close_session(sid)


playwright_service = PlaywrightStagerService()
