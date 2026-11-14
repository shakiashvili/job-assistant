import asyncio
import ipaddress
import logging
import urllib.parse
import httpx
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Any
from ..config import ENABLE_PLAYWRIGHT, GENERATED_RESUMES_DIR
from ..db.profile_repository import ground_truth_store
from ..services.gemini_service import gemini_service
from ..services.portal_detector import detect_portal_from_html, detect_portal_from_url
from ..services.company_validator import company_validator
from ..services.cv_generator_service import cv_generator_service
from ..services.salary_service import salary_service
from ..services.scrapers.base_scraper import evaluate_remote_and_language_gate
from ..db.models import (
    JobAuditResponse, JobDetails, ScoreBreakdown, Blocker, GapItem, TailoredCVResult
)

logger = logging.getLogger(__name__)


def validate_safe_external_url(url: str) -> str:
    """
    Validates that a user-supplied URL does not target loopback, RFC1918 private networks,
    link-local cloud metadata endpoints (169.254.169.254), or arbitrary local files (SSRF protection).
    """
    clean = (url or "").strip()
    if not clean:
        return clean
    if clean.startswith("mock://"):
        return clean
    if clean.startswith("file://"):
        if "mock_portal" in clean.replace("\\", "/"):
            return clean
        raise ValueError("SSRF Protection: arbitrary file:// URLs are forbidden.")

    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"SSRF Protection: unsupported URL scheme '{parsed.scheme}'. Only http/https allowed.")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("SSRF Protection: URL is missing a valid hostname.")

    blocked_hosts = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "169.254.169.254",
        "metadata.google.internal",
        "metadata",
    }
    if host in blocked_hosts or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError(f"SSRF Protection: internal or loopback host '{host}' is forbidden.")

    try:
        ip_obj = ipaddress.ip_address(host)
        if (
            ip_obj.is_loopback
            or ip_obj.is_private
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise ValueError(f"SSRF Protection: non-public IP address '{host}' is forbidden.")
    except ValueError as ve:
        if "SSRF Protection" in str(ve):
            raise

    return clean


def _fetch_spa_html_with_playwright(url: str) -> str:
    """Isolated headless Playwright fallback for client-side hydrated SPA job boards."""
    validate_safe_external_url(url)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=12000)
            page.wait_for_timeout(500)
            return page.content()
        finally:
            browser.close()


class AuditService:
    async def fetch_url_content(self, url: str) -> str:
        """
        Hybrid fetching strategy for job pages with SSRF protection:
        1. Validates URL against SSRF blocklist (loopback, RFC1918 private IPs, cloud metadata, file://).
        2. Fast HTTP fetch via httpx with realistic browser headers.
        3. Optional headless Playwright fallback if ENABLE_PLAYWRIGHT=true and body text < 150 chars.
        """
        validate_safe_external_url(url)
        html_text = ""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,ka;q=0.8",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, headers=headers) as client:
                resp = await client.get(url)
                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_target = resp.headers.get("location", "")
                    if redirect_target:
                        resolved_redirect = urllib.parse.urljoin(url, redirect_target)
                        validate_safe_external_url(resolved_redirect)
                        resp = await client.get(resolved_redirect)
                if resp.status_code == 200:
                    html_text = resp.text
        except ValueError:
            raise
        except Exception as e:
            logger.debug(f"Fast httpx fetch note for {url}: {e}")

        soup = BeautifulSoup(html_text or "", "html.parser")
        body_text = (soup.body.get_text(" ", strip=True) if soup.body else soup.get_text(" ", strip=True)).strip()

        if len(body_text) < 150 and url.startswith(("http://", "https://", "file://")):
            if not ENABLE_PLAYWRIGHT:
                logger.info(
                    f"Body text length ({len(body_text)} < 150 chars) on {url}, "
                    "but ENABLE_PLAYWRIGHT=false; skipping headless Chromium SPA hydration and using httpx HTML."
                )
            else:
                logger.info(f"Body text length ({len(body_text)} < 150 chars) on {url}; falling back to headless Playwright SPA hydration.")
                try:
                    html_text = await asyncio.to_thread(_fetch_spa_html_with_playwright, url)
                except Exception as pw_err:
                    logger.warning(f"Headless Playwright SPA hydration fallback failed for {url}: {pw_err}")

        return html_text

    async def audit_job(
        self,
        raw_text: Optional[str] = None,
        job_url: Optional[str] = None,
        variant: str = "qa_automation",
        cv_language: str = "en",
        skills_md_override: Optional[str] = None,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> JobAuditResponse:
        """
        Audits job description against the user's CandidateProfile + skills.md across any industry,
        enforces SSRF protection on job_url, validates company reviews, computes transparent match scores,
        and generates a tailored per-vacancy PDF/DOCX CV in English ('en') or Georgian ('ka').
        """
        is_fetchable_url = bool(job_url and ("://" in job_url or not raw_text))
        if is_fetchable_url and job_url:
            validate_safe_external_url(job_url)

        ground_truth = ground_truth_store.get_data(owner_email=owner_email, user_id=user_id)
        candidate = ground_truth.get("candidate", {})
        skills_md = (
            skills_md_override
            or ground_truth.get("skills_md_raw")
            or ground_truth_store.get_skills_md(owner_email=owner_email, user_id=user_id)
        )

        md_skills = ground_truth_store.extract_skills_from_md(skills_md) if skills_md else []
        candidate_skills = ground_truth.get("skills", {})
        all_candidate_skills_list = list(dict.fromkeys(
            md_skills + candidate_skills.get("core", []) + candidate_skills.get("secondary", [])
        ))
        all_candidate_skills = set(s.lower() for s in all_candidate_skills_list)
        skills_md_lower = (skills_md or "").lower()

        extracted_text = raw_text or ""
        inferred_portal = detect_portal_from_url(job_url or "")
        url_fetched = False

        if is_fetchable_url and job_url:
            try:
                html_content = await self.fetch_url_content(job_url)
                url_fetched = bool(html_content)
                p_type, meta = detect_portal_from_html(html_content, job_url)
                if not extracted_text:
                    extracted_text = meta["description_text"]
                if p_type != "generic":
                    inferred_portal = p_type
            except ValueError:
                raise
            except Exception as e:
                logger.warning(f"Could not fetch url {job_url}: {e}")
                if not extracted_text:
                    extracted_text = f"Job listing at {job_url}"

        raw_details = gemini_service.extract_job_details(extracted_text, portal=inferred_portal)
        details = JobDetails(**raw_details)

        # Market & Strict Explicit Salary Extraction (never fabricates unstated salary amounts)
        market = "GE" if details.portal in ("jobs.ge", "hr.ge", "headhunter.ge") else (
            "UA_REMOTE" if details.portal == "dou.ua" else "INT_REMOTE"
        )
        details.market = market
        sal_info = salary_service.extract_vacancy_salary(
            title=details.title,
            description=extracted_text,
        )
        details.salary_min = sal_info["min_salary"]
        details.salary_max = sal_info["max_salary"]
        details.salary_currency = sal_info["currency"]
        details.salary_estimated_by_ai = False
        if sal_info["min_salary"] and sal_info["max_salary"]:
            details.salary_range = f"{sal_info['min_salary']:g} – {sal_info['max_salary']:g} {sal_info['currency']}/mo (Extracted from Job)"
        elif sal_info.get("is_unpaid"):
            details.salary_range = "Unpaid Internship / No Compensation"
        else:
            details.salary_range = "Salary not specified"

        # 1. Skills Match & Gaps Analysis
        req_skills = details.required_skills or []
        nice_skills = details.nice_to_have_skills or []
        matched = []
        missing = []
        gaps: List[GapItem] = []

        is_ka = cv_language == "ka"

        for req in req_skills:
            req_l = req.lower()
            if any(req_l in c or c in req_l for c in all_candidate_skills) or req_l in skills_md_lower:
                matched.append(req)
            else:
                missing.append(req)
                gaps.append(GapItem(
                    skill_or_area=req,
                    severity="high",
                    gap_description=(
                        f"ვაკანსია მოითხოვს '{req}' უნარს, რომელიც პირდაპირ არ ჩანს თქვენს skills.md ფაილში."
                        if is_ka else
                        f"Vacancy lists '{req}' as a core requirement, which is not explicitly listed in your current skills.md."
                    ),
                    bridge_strategy=(
                        f"რეზიუმეში (CV) ხაზი გაუსვით მომიჯნავე პრაქტიკულ გამოცდილებას და სწრაფი ათვისების უნარს {req} მიმართულებით."
                        if is_ka else
                        f"Emphasize transferable hands-on experience and fast onboarding with {req} in the tailored summary."
                    )
                ))

        matched_nice_count = 0
        for nice in nice_skills:
            nice_l = nice.lower()
            if any(nice_l in c or c in nice_l for c in all_candidate_skills) or nice_l in skills_md_lower:
                matched_nice_count += 1
                if nice not in matched:
                    matched.append(nice)
            else:
                gaps.append(GapItem(
                    skill_or_area=nice,
                    severity="low",
                    gap_description=f"Preferred skill '{nice}' is not currently listed in skills.md.",
                    bridge_strategy=f"Mention adjacent domain familiarity with {nice} during the interview."
                ))

        req_matched_count = len(req_skills) - len(missing)
        skills_score = int(round((req_matched_count / max(len(req_skills), 1)) * 100)) if req_skills else 80
        skills_score = min(100, max(0, skills_score))

        # 2. Experience Match (read real experience from uploaded CandidateProfile)
        prof_record = ground_truth_store.get_profile_record(owner_email=owner_email, user_id=user_id)
        candidate_exp_years = float(getattr(prof_record, "experience_years", 1.5) or 1.5)
        required_exp = details.experience_years_required or 1
        if candidate_exp_years >= required_exp:
            exp_score = 100
        else:
            diff = required_exp - candidate_exp_years
            exp_score = max(35, int(round(100 - (diff * 20))))

        # 3. Transparent ATS & Recruiter Match Scores (no arbitrary +24 / +20 inflation constants)
        nice_bonus = int(round((matched_nice_count / max(len(nice_skills), 1)) * 15)) if nice_skills else 10
        ats_score = min(100, max(35, int(round(skills_score * 0.85 + nice_bonus))))
        recruiter_score = min(100, max(35, int(round((skills_score * 0.60) + (exp_score * 0.40)))))

        # 4. Company Validation (3+ Reviews Gate)
        comp_validation = company_validator.validate_company(details.company, extracted_text)
        blockers: List[Blocker] = []

        if not comp_validation.passed_gate:
            blockers.append(Blocker(
                category="company_reviews",
                severity="critical",
                description=f"Company '{details.company}' failed the 3+ reviews validation gate ({comp_validation.review_count} reviews found).",
                candidate_status="Policy requires 3+ verified employee reviews on job portals before applying."
            ))

        # 5. Work Authorization & Remote B2B Compatibility
        visa_score = 100
        visa_text = (details.visa_requirements or "").lower()
        if "us citizen" in visa_text or "citizenship required" in visa_text or "citizenship mandatory" in visa_text:
            visa_score = 10
            blockers.append(Blocker(
                category="visa",
                severity="critical",
                description="Position mandates US Citizenship / Clearances.",
                candidate_status="Candidate operates from Georgia / Remote B2B Contractor."
            ))
        elif "security clearance" in visa_text:
            visa_score = 10
            blockers.append(Blocker(
                category="clearance",
                severity="critical",
                description="Active government security clearance required.",
                candidate_status="No government security clearance held."
            ))

        lang_score = 100
        _, gate_status, gate_reason, detected_langs = evaluate_remote_and_language_gate(
            title=details.title,
            description=extracted_text,
            location_text=details.location or "Remote",
            portal=details.portal,
        )
        if gate_status == "FILTERED_OUT":
            lang_score = 0
            blockers.append(Blocker(
                category="language",
                severity="critical",
                description=f"Filtered Out ({gate_reason}): Vacancy requires local Slavic/Polish fluency or non-remote attendance.",
                candidate_status="Strict English Remote filter active for international portals."
            ))

        overall_score = int(round(
            (skills_score * 0.45) +
            (ats_score * 0.25) +
            (recruiter_score * 0.25) +
            (visa_score * 0.05)
        ))
        if any(b.severity == "critical" for b in blockers):
            overall_score = min(overall_score, 45)

        # 6. Craft Human-Tone Narratives & Generate Per-Vacancy PDF CV
        narratives = gemini_service.craft_human_tone_narratives(
            job_details=details.model_dump(),
            skills_md=skills_md,
            matched_skills=matched,
            missing_skills=missing,
            cv_language=cv_language,
            candidate_name=candidate.get("full_name", "Candidate")
        )

        cv_result_dict = cv_generator_service.generate_vacancy_cv(
            job_title=details.title,
            company=details.company,
            portal=details.portal,
            matched_skills=matched,
            missing_skills=missing,
            human_summary=narratives["human_tone_summary"],
            motivation_statement=narratives["motivation_statement"],
            dou_motivational_letter=narratives["dou_motivational_letter"],
            skills_md_override=skills_md,
            cv_language=cv_language,
            owner_email=owner_email,
        )
        tailored_cv = TailoredCVResult(**cv_result_dict)
        if details.salary_range:
            tailored_cv.expected_salary = details.salary_range

        if user_id is not None and tailored_cv.pdf_filename:
            from ..routers.ground_truth import record_candidate_document
            record_candidate_document(
                user_id=user_id,
                filename=tailored_cv.pdf_filename,
                file_path=GENERATED_RESUMES_DIR / tailored_cv.pdf_filename,
                doc_type="generated_audit_cv",
                target_company=details.company,
                target_role=details.title,
            )

        recommended_variant = variant
        lang_label = "Georgian (ქართული)" if cv_language == "ka" else "English"
        notes = (
            f"Generated {lang_label} Human-Tone PDF ({tailored_cv.pdf_filename}) tailored for {details.company} ({details.industry}). "
            f"Company validation: {comp_validation.review_count} reviews ({comp_validation.rating}★, {comp_validation.verification_status})."
        )

        taxonomy = ground_truth.get("parsed_skills_taxonomy") or {}
        provenance: Dict[str, str] = {
            "url_fetched": "VERIFIED" if url_fetched else "RAW_TEXT",
            "ai_assisted": "GEMINI_LIVE" if gemini_service.is_available else "DETERMINISTIC_ENGINE",
            "profile_user_uploaded": "VERIFIED" if taxonomy.get("user_uploaded", False) else "SEED_PROFILE",
            "company_verification_status": str(comp_validation.verification_status),
            "salary_source": "EXTRACTED_FROM_TEXT" if sal_info.get("min_salary") else "UNAVAILABLE",
        }

        return JobAuditResponse(
            job_details=details,
            match_score=overall_score,
            score_breakdown=ScoreBreakdown(
                skills_match=skills_score,
                ats_match=ats_score,
                recruiter_match=recruiter_score,
                experience_match=exp_score,
                visa_match=visa_score,
                language_match=lang_score
            ),
            matched_skills=matched,
            missing_skills=missing,
            gaps=gaps,
            company_validation=comp_validation,
            tailored_cv=tailored_cv,
            blockers=blockers,
            recommended_variant=recommended_variant,
            recommendation_notes=notes,
            data_provenance=provenance,
        )


audit_service = AuditService()
