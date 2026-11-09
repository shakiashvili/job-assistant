import logging
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select
from ...db.database import engine, init_db
from ...db.models import CandidateProfile, JobPosting, ApplicationRecord, utc_now
from ..salary_service import salary_service
from ..matcher_service import matcher_service
from .jobs_ge_scraper import jobs_ge_scraper
from .hr_ge_scraper import hr_ge_scraper
from .dou_scraper import dou_scraper
from .djinni_scraper import djinni_scraper

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    """
    Coordinates scraping across Jobs.ge, HR.ge, DOU.ua, and Djinni.co:
    1. Deduplicates against JobPosting by (portal, external_id) and (url).
    2. Applies Mandatory Remote & Slavic Language Gate for Ukrainian/Regional portals.
    3. Estimates or extracts salary via SalaryService (salary_is_estimated / salary_estimated_by_ai).
    4. Evaluates suitability score (0-100%) against CandidateProfile via MatcherService.
    5. Auto-promotes jobs with suitability_score >= 75% to status="STAGED" and creates an ApplicationRecord.
    """

    SCRAPER_MAP = {
        "jobs.ge": jobs_ge_scraper,
        "hr.ge": hr_ge_scraper,
        "dou.ua": dou_scraper,
        "djinni.co": djinni_scraper,
    }

    async def run_scrapers(
        self,
        portals: Optional[List[str]] = None,
        allow_network: bool = False,
    ) -> Dict[str, Any]:
        init_db()
        target_portals = portals or list(self.SCRAPER_MAP.keys())

        raw_discovered: List[Dict[str, Any]] = []
        for p in target_portals:
            scraper = self.SCRAPER_MAP.get(p)
            if not scraper:
                continue
            items = await scraper.scrape(allow_network=allow_network)
            raw_discovered.extend(items)

        return self.ingest_scraped_jobs(raw_discovered)

    def ingest_scraped_jobs(self, raw_jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
        init_db()
        serialized_jobs: List[Dict[str, Any]] = []
        staged_count = 0
        filtered_out_count = 0

        with Session(engine, expire_on_commit=False) as session:
            profile = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).first()
            parsed_skills = profile.parsed_skills if profile else matcher_service.parse_skills_markdown("")

            for item in raw_jobs:
                portal = item.get("portal", "custom")
                ext_id = item.get("external_id", "")
                url = item.get("url", "")
                title = item.get("title", "QA Engineer")
                company = item.get("company", "Company")
                desc = item.get("description_raw", "")
                market = item.get("market", "GLOBAL_REMOTE")
                initial_status = item.get("status", "DISCOVERED")
                initial_rationale = item.get("filter_out_reason") or item.get("match_rationale") or ""

                # 1. Salary extraction or AI estimation
                sal_info = salary_service.estimate_salary(
                    title=title,
                    description=desc,
                    market=market,
                    portal=portal,
                )

                # 2. Suitability & Match Evaluation
                score, final_status, match_rationale, _, _ = matcher_service.evaluate_job(
                    title=title,
                    description=desc,
                    parsed_skills=parsed_skills,
                    current_status=initial_status,
                    existing_rationale=initial_rationale,
                )

                filter_reason = initial_rationale if final_status == "FILTERED_OUT" else None
                if final_status == "FILTERED_OUT":
                    filtered_out_count += 1
                elif final_status == "STAGED":
                    staged_count += 1

                langs = item.get("detected_languages") or item.get("language_requirements") or ["English"]
                is_est = bool(sal_info["salary_estimated_by_ai"])

                # 3. Upsert JobPosting by (portal, external_id) or url
                existing = session.exec(
                    select(JobPosting).where(
                        (JobPosting.url == url)
                        | ((JobPosting.portal == portal) & (JobPosting.external_id == ext_id))
                    )
                ).first()

                if existing:
                    existing.title = title
                    existing.company = company
                    existing.market = market
                    existing.is_remote = bool(item.get("is_remote", True))
                    existing.channel = item.get("channel", "WEB_FORM")
                    existing.target_email = item.get("target_email")
                    existing.email_subject = item.get("email_subject")
                    existing.detected_languages = langs
                    existing.language_requirements = langs
                    existing.description_raw = desc
                    existing.salary_min = sal_info["min_salary"]
                    existing.salary_max = sal_info["max_salary"]
                    existing.salary_currency = sal_info["currency"]
                    existing.salary_is_estimated = is_est
                    existing.salary_estimated_by_ai = is_est
                    existing.suitability_score = score
                    existing.filter_out_reason = filter_reason
                    existing.match_rationale = match_rationale
                    if existing.status not in ("APPLIED", "REJECTED"):
                        existing.status = final_status
                    existing.scraped_at = utc_now()
                    session.add(existing)
                    session.commit()
                    session.refresh(existing)
                    job_record = existing
                else:
                    job_record = JobPosting(
                        portal=portal,
                        external_id=ext_id,
                        title=title,
                        company=company,
                        url=url,
                        market=market,
                        is_remote=bool(item.get("is_remote", True)),
                        channel=item.get("channel", "WEB_FORM"),
                        target_email=item.get("target_email"),
                        email_subject=item.get("email_subject"),
                        detected_languages=langs,
                        language_requirements=langs,
                        description_raw=desc,
                        salary_min=sal_info["min_salary"],
                        salary_max=sal_info["max_salary"],
                        salary_currency=sal_info["currency"],
                        salary_is_estimated=is_est,
                        salary_estimated_by_ai=is_est,
                        suitability_score=score,
                        status=final_status,
                        filter_out_reason=filter_reason,
                        match_rationale=match_rationale,
                        scraped_at=utc_now(),
                    )
                    session.add(job_record)
                    session.commit()
                    session.refresh(job_record)

                serialized_jobs.append(job_record.model_dump(mode="json"))

                # 4. Auto-create ApplicationRecord if promoted to STAGED (>= 75%)
                if job_record.status == "STAGED" and job_record.id is not None:
                    app_rec = session.exec(
                        select(ApplicationRecord).where(
                            (ApplicationRecord.job_id == job_record.id)
                            | (ApplicationRecord.job_posting_id == job_record.id)
                        )
                    ).first()
                    if not app_rec:
                        cv_path = f"/api/resumes/generated/CV_{company[:15]}_{title[:15]}_EN.pdf".replace(" ", "_")
                        cover_txt = f"Auto-staged application for {title} at {company} ({score}% match)."
                        app_rec = ApplicationRecord(
                            job_id=job_record.id,
                            job_posting_id=job_record.id,
                            cv_pdf_path=cv_path,
                            custom_cv_path=cv_path,
                            cover_letter=cover_txt,
                            cover_letter_text=cover_txt,
                            screening_answers={"notice_period": "1 week after offer"},
                            submission_status="STAGED",
                            applied_at=utc_now(),
                            updated_at=utc_now(),
                        )
                        session.add(app_rec)
                        session.commit()

            return {
                "total_processed": len(serialized_jobs),
                "staged_ready_count": staged_count,
                "filtered_out_count": filtered_out_count,
                "jobs": serialized_jobs,
            }


scraper_orchestrator = ScraperOrchestrator()
