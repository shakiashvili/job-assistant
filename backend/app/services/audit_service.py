import asyncio
import logging
import httpx
from bs4 import BeautifulSoup
from typing import List, Optional
from ..storage.ground_truth_store import ground_truth_store
from ..services.gemini_service import gemini_service
from ..services.portal_detector import detect_portal_from_html, detect_portal_from_url
from ..services.company_validator import company_validator
from ..services.cv_generator_service import cv_generator_service
from ..services.salary_service import salary_service
from ..services.scrapers.base_scraper import evaluate_remote_and_language_gate
from ..models.schemas import (
    JobAuditResponse, JobDetails, ScoreBreakdown, Blocker, GapItem, TailoredCVResult
)

logger = logging.getLogger(__name__)


def _fetch_spa_html_with_playwright(url: str) -> str:
    """Isolated headless Playwright fallback for client-side hydrated SPA job boards."""
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
        Hybrid fetching strategy for job pages:
        1. Fast HTTP fetch via httpx with realistic browser headers (User-Agent, Accept-Language).
        2. If the parsed page body has fewer than 150 characters of substantive text,
           falls back to an isolated headless Playwright browser instance (page.content())
           to allow client-side SPA hydration.
        """
        html_text = ""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,ka;q=0.8",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    html_text = resp.text
        except Exception as e:
            logger.debug(f"Fast httpx fetch note for {url}: {e}")

        soup = BeautifulSoup(html_text or "", "html.parser")
        body_text = (soup.body.get_text(" ", strip=True) if soup.body else soup.get_text(" ", strip=True)).strip()

        if len(body_text) < 150 and url.startswith(("http://", "https://", "file://")):
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
    ) -> JobAuditResponse:
        """
        Audits job description against candidate_skills.md + ground_truth.json across ANY industry
        (QA/Tech, Hospitality/Receptionist, Customer Service, Hospital/Healthcare),
        validates company reviews (3+ gate), computes Skills / ATS / Recruiter match & Gaps,
        and generates a tailored per-vacancy PDF CV in English ('en') or Georgian ('ka').
        """
        ground_truth = ground_truth_store.get_data()
        candidate = ground_truth.get("candidate", {})
        skills_md = skills_md_override or ground_truth.get("skills_md_raw") or ground_truth_store.get_skills_md()

        md_skills = ground_truth_store.extract_skills_from_md(skills_md) if skills_md else []
        candidate_skills = ground_truth.get("skills", {})
        all_candidate_skills_list = list(dict.fromkeys(
            md_skills + candidate_skills.get("core", []) + candidate_skills.get("secondary", [])
        ))
        all_candidate_skills = set(s.lower() for s in all_candidate_skills_list)
        skills_md_lower = (skills_md or "").lower()

        extracted_text = raw_text or ""
        inferred_portal = detect_portal_from_url(job_url or "")

        if job_url:
            try:
                html_content = await self.fetch_url_content(job_url)
                p_type, meta = detect_portal_from_html(html_content, job_url)
                if not extracted_text:
                    extracted_text = meta["description_text"]
                if p_type != "generic":
                    inferred_portal = p_type
            except Exception as e:
                logger.warning(f"Could not fetch url {job_url}: {e}")
                if not extracted_text:
                    extracted_text = f"Job listing at {job_url}"

        raw_details = gemini_service.extract_job_details(extracted_text, portal=inferred_portal)
        details = JobDetails(**raw_details)

        # Market & Dynamic AI Salary Estimation (never asks the user for salary)
        market = "GE" if details.portal in ("jobs.ge", "hr.ge", "headhunter.ge") else (
            "UA_REMOTE" if details.portal == "dou.ua" else "INT_REMOTE"
        )
        details.market = market
        sal_est = salary_service.estimate_salary(
            title=details.title,
            description=extracted_text,
            market=market,
            portal=details.portal,
        )
        details.salary_min = sal_est["min_salary"]
        details.salary_max = sal_est["max_salary"]
        details.salary_currency = sal_est["currency"]
        details.salary_estimated_by_ai = sal_est["salary_estimated_by_ai"]
        est_badge = "AI Estimated" if sal_est["salary_estimated_by_ai"] else "Extracted from Job"
        details.salary_range = f"{sal_est['min_salary']:g} – {sal_est['max_salary']:g} {sal_est['currency']}/mo ({est_badge})"

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

        for nice in nice_skills:
            nice_l = nice.lower()
            if any(nice_l in c or c in nice_l for c in all_candidate_skills) or nice_l in skills_md_lower:
                if nice not in matched:
                    matched.append(nice)
            else:
                gaps.append(GapItem(
                    skill_or_area=nice,
                    severity="low",
                    gap_description=f"Preferred skill '{nice}' is not currently listed in skills.md.",
                    bridge_strategy=f"Mention adjacent domain familiarity with {nice} during the interview."
                ))

        skills_score = int((len(matched) / max(len(req_skills), 1)) * 100) if req_skills else 92
        skills_score = min(100, skills_score)

        # 2. Experience Match
        candidate_exp_years = 5.0
        required_exp = details.experience_years_required or 2
        if candidate_exp_years >= required_exp:
            exp_score = 100
        else:
            diff = required_exp - candidate_exp_years
            exp_score = max(45, int(100 - (diff * 18)))

        # 3. ATS & Recruiter Match Scores
        raw_ats = int(skills_score * 0.75 + 24)
        ats_score = min(98, max(55, raw_ats))
        recruiter_score = min(97, int((skills_score * 0.45) + (exp_score * 0.35) + 20))

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

        # 5. Visa / Work Auth Match
        visa_score = 100
        visa_text = (details.visa_requirements or "").lower()
        if "us citizen" in visa_text or "citizenship required" in visa_text:
            visa_score = 10
            blockers.append(Blocker(
                category="visa",
                severity="critical",
                description="Position mandates US Citizenship / Clearances.",
                candidate_status="Candidate operates from Georgia / EU / Remote Abroad."
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
                description=f"Filtered Out ({gate_reason}): Vacancy requires Ukrainian/Russian or non-remote attendance.",
                candidate_status="Strict English-only Remote filter active for Ukrainian/Regional platforms."
            ))

        overall_score = int(
            (skills_score * 0.35) +
            (ats_score * 0.25) +
            (recruiter_score * 0.25) +
            (visa_score * 0.15)
        )
        if any(b.severity == "critical" for b in blockers):
            overall_score = min(overall_score, 45)

        # 6. Craft Human-Tone Narratives & Generate Per-Vacancy PDF CV (in English or Georgian!)
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
            cv_language=cv_language
        )
        tailored_cv = TailoredCVResult(**cv_result_dict)
        if details.salary_range:
            tailored_cv.expected_salary = details.salary_range

        recommended_variant = variant
        lang_label = "Georgian (ქართული)" if cv_language == "ka" else "English"
        notes = (
            f"Generated {lang_label} Human-Tone PDF ({tailored_cv.pdf_filename}) tailored for {details.company} ({details.industry}). "
            f"Company validation: {comp_validation.review_count} reviews ({comp_validation.rating}★)."
        )

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
            recommendation_notes=notes
        )


audit_service = AuditService()
