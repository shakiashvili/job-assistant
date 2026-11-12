import asyncio
import logging
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select
from ...db.database import engine, init_db, delete_job_posting_cascade
from ...db.models import CandidateProfile, JobPosting, ApplicationRecord, utc_now
from ..salary_service import salary_service
from ..matcher_service import matcher_service
from ..profile_service import profile_service
from ..link_validator import parse_vacancy_deadline
from .base_scraper import sanitize_company_name
from .jobs_ge_scraper import jobs_ge_scraper
from .hr_ge_scraper import hr_ge_scraper
from .hr_gov_scraper import hr_gov_scraper
from .dou_scraper import dou_scraper
from .djinni_scraper import djinni_scraper
from .justjoin_scraper import justjoin_scraper
from .headhunter_scraper import headhunter_scraper
from .linkedin_scraper import linkedin_scraper

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    """
    Universal Domain-Agnostic Multi-Portal Scraper Orchestrator:
    1. Builds primary, adjacent, public-sector internship, and remote queries dynamically from CandidateProfile.
    2. Scrapes Jobs.ge, HR.ge, HeadHunter.ge, HR.gov.ge, DOU.ua, Djinni.co, JustJoin.it, and LinkedIn.
    3. Deduplicates across (portal, external_id), (url), and (title, company).
    4. Evaluates jobs across 3 actionable tiers (DIRECT, ADJACENT, PUBLIC_INTERNSHIP) under a strict 2.0-yr cap.
    """

    SCRAPER_MAP = {
        "jobs.ge": jobs_ge_scraper,
        "hr.ge": hr_ge_scraper,
        "hr.gov.ge": hr_gov_scraper,
        "headhunter.ge": headhunter_scraper,
        "dou.ua": dou_scraper,
        "djinni.co": djinni_scraper,
        "justjoin.it": justjoin_scraper,
        "linkedin.com": linkedin_scraper,
    }

    async def run_scrapers(
        self,
        portals: Optional[List[str]] = None,
        allow_network: bool = True,
    ) -> Dict[str, Any]:
        init_db()
        target_portals = portals or list(self.SCRAPER_MAP.keys())

        if not allow_network:
            return self.ingest_scraped_jobs([])

        with Session(engine) as session:
            profile = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).first()
            parsed_skills = profile.parsed_skills if profile else {}
            headline = parsed_skills.get("headline", "") if isinstance(parsed_skills, dict) else ""
            cand_langs = parsed_skills.get("spoken_languages", ["English", "Georgian"]) if isinstance(parsed_skills, dict) else ["English", "Georgian"]
            search_cfg = profile_service.get_search_queries_for_profile(parsed_skills, headline=headline)

        combined_kw = list(dict.fromkeys(
            (search_cfg.get("domain_keywords") or []) + (search_cfg.get("adjacent_keywords") or [])
        ))

        tasks = []
        for p in target_portals:
            if p == "jobs.ge":
                tasks.append(jobs_ge_scraper.scrape(allow_network=True, search_urls=search_cfg.get("jobs_ge_urls")))
            elif p == "hr.ge":
                tasks.append(hr_ge_scraper.scrape(
                    allow_network=True,
                    search_urls=search_cfg.get("hr_ge_urls"),
                    domain_keywords=combined_kw,
                ))
            elif p == "hr.gov.ge":
                tasks.append(hr_gov_scraper.scrape(
                    allow_network=True,
                    queries=search_cfg.get("hr_gov_queries"),
                    domain_keywords=combined_kw,
                ))
            elif p == "headhunter.ge":
                hh_urls = search_cfg.get("headhunter_urls") or ([search_cfg.get("headhunter_url")] if search_cfg.get("headhunter_url") else [])
                if hh_urls:
                    tasks.append(headhunter_scraper.scrape(
                        allow_network=True,
                        search_urls=hh_urls,
                        domain_keywords=combined_kw,
                        candidate_languages=cand_langs,
                    ))
            elif p == "dou.ua":
                dou_url = search_cfg.get("dou_url")
                if dou_url:
                    tasks.append(dou_scraper.scrape(allow_network=True, search_url=dou_url, candidate_languages=cand_langs))
            elif p == "djinni.co":
                djinni_url = search_cfg.get("djinni_exp_url") or search_cfg.get("djinni_url")
                if djinni_url:
                    tasks.append(djinni_scraper.scrape(allow_network=True, search_url=djinni_url, candidate_languages=cand_langs))
            elif p == "justjoin.it":
                justjoin_url = search_cfg.get("justjoin_url")
                if justjoin_url:
                    tasks.append(justjoin_scraper.scrape(allow_network=True, search_url=justjoin_url, candidate_languages=cand_langs))
            elif p == "linkedin.com":
                li_urls = search_cfg.get("linkedin_urls") or []
                tasks.append(linkedin_scraper.scrape(
                    allow_network=True,
                    search_urls=li_urls,
                    domain_keywords=combined_kw,
                    candidate_languages=cand_langs,
                ))

        raw_discovered: List[Dict[str, Any]] = []
        if tasks:
            batches = await asyncio.gather(*tasks, return_exceptions=True)
            for b in batches:
                if isinstance(b, list):
                    raw_discovered.extend(b)
                elif isinstance(b, Exception):
                    logger.warning(f"Portal scraper task error: {b}")

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
                company = sanitize_company_name(
                    item.get("company"),
                    target_email=item.get("target_email"),
                    fallback="Hiring Company",
                )
                desc = item.get("description_raw", "")
                market = item.get("market", "GLOBAL_REMOTE")
                initial_status = item.get("status", "DISCOVERED")
                initial_rationale = item.get("filter_out_reason") or item.get("match_rationale") or ""

                # 1. Explicit salary extraction ONLY (never fabricate fake salary if unmentioned)
                sal_info = salary_service.extract_vacancy_salary(
                    title=title,
                    description=desc,
                )

                # 2. Check application deadline & expiration
                dl_date, dl_str, is_expired = parse_vacancy_deadline(desc)
                if is_expired:
                    initial_status = "FILTERED_OUT"
                    initial_rationale = f"Vacancy expired on {dl_str}"

                # 3. Multi-Tier Optimal Match Evaluation (DIRECT, ADJACENT, PUBLIC_INTERNSHIP + Strict 2.0-Yr Guard)
                tier_res = matcher_service.evaluate_job_tiered(
                    title=title,
                    description=desc,
                    parsed_skills=parsed_skills,
                    current_status=initial_status,
                    existing_rationale=initial_rationale,
                    portal=portal,
                )
                score = tier_res["suitability_score"]
                final_status = tier_res["status"]
                match_rationale = tier_res["match_rationale"]
                match_tier = tier_res.get("match_tier") or item.get("match_tier") or "DIRECT"
                adj_tag = tier_res.get("adjacent_role_tag")
                overlap_pct = tier_res.get("skill_overlap_pct")

                filter_reason = (initial_rationale or match_rationale) if final_status == "FILTERED_OUT" else None
                if final_status == "FILTERED_OUT":
                    filtered_out_count += 1
                    existing_disq = session.exec(
                        select(JobPosting).where(
                            (JobPosting.url == url)
                            | ((JobPosting.portal == portal) & (JobPosting.external_id == ext_id))
                        )
                    ).first()
                    if existing_disq and existing_disq.status not in ("APPLIED", "REJECTED"):
                        delete_job_posting_cascade(session, existing_disq)
                        session.commit()
                    continue
                elif final_status == "STAGED":
                    staged_count += 1

                langs = item.get("detected_languages") or item.get("language_requirements") or ["English"]
                is_est = bool(sal_info["salary_estimated_by_ai"])

                # 4. Upsert JobPosting by (portal, external_id) or url
                existing = session.exec(
                    select(JobPosting).where(
                        (JobPosting.url == url)
                        | ((JobPosting.portal == portal) & (JobPosting.external_id == ext_id))
                    )
                ).first()

                if existing:
                    existing.title = title
                    existing.company = company
                    existing.url = url
                    existing.market = market
                    existing.is_remote = bool(item.get("is_remote", True))
                    existing.channel = item.get("channel", "WEB_FORM")
                    existing.delivery_channel = item.get("delivery_channel") or item.get("channel", "WEB_FORM")
                    existing.target_email = item.get("target_email")
                    existing.email_subject = item.get("email_subject")
                    existing.email_subject_template = item.get("email_subject_template") or item.get("email_subject")
                    existing.detected_languages = langs
                    existing.language_requirements = langs
                    existing.description_raw = desc
                    existing.salary_min = sal_info["min_salary"]
                    existing.salary_max = sal_info["max_salary"]
                    existing.salary_currency = sal_info["currency"]
                    existing.salary_is_estimated = is_est
                    existing.salary_estimated_by_ai = is_est
                    existing.suitability_score = score
                    existing.match_score = score
                    existing.match_tier = match_tier
                    existing.adjacent_role_tag = adj_tag
                    existing.skill_overlap_pct = overlap_pct
                    existing.filter_out_reason = filter_reason
                    existing.match_rationale = match_rationale
                    existing.deadline_text = dl_str or item.get("deadline_text")
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
                        delivery_channel=item.get("delivery_channel") or item.get("channel", "WEB_FORM"),
                        target_email=item.get("target_email"),
                        email_subject=item.get("email_subject"),
                        email_subject_template=item.get("email_subject_template") or item.get("email_subject"),
                        detected_languages=langs,
                        language_requirements=langs,
                        description_raw=desc,
                        salary_min=sal_info["min_salary"],
                        salary_max=sal_info["max_salary"],
                        salary_currency=sal_info["currency"],
                        salary_is_estimated=is_est,
                        salary_estimated_by_ai=is_est,
                        suitability_score=score,
                        match_score=score,
                        match_tier=match_tier,
                        adjacent_role_tag=adj_tag,
                        skill_overlap_pct=overlap_pct,
                        status=final_status,
                        filter_out_reason=filter_reason,
                        match_rationale=match_rationale,
                        deadline_text=dl_str or item.get("deadline_text"),
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
                "jobs": [j for j in serialized_jobs if j.get("status") != "FILTERED_OUT"],
            }


scraper_orchestrator = ScraperOrchestrator()
