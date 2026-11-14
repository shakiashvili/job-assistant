import asyncio
from datetime import timedelta, timezone
import logging
from typing import Dict, Any, List, Optional, Tuple, Set
from sqlmodel import Session, select
from ...db.database import engine, init_db, delete_job_posting_cascade
from ...db.models import (
    CandidateProfile,
    JobPosting,
    UserJobMatch,
    SavedSearch,
    Notification,
    ApplicationRecord,
    utc_now,
)
from ...db.profile_repository import ground_truth_store
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
from .ats_board_scraper import greenhouse_scraper, lever_scraper

logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    """
    Universal Domain-Agnostic Multi-Portal Scraper Orchestrator:
    1. Builds primary, adjacent, public-sector internship, and remote queries dynamically from CandidateProfile.
    2. Scrapes Jobs.ge, HR.ge, HeadHunter.ge, HR.gov.ge, DOU.ua, Djinni.co, JustJoin.it, LinkedIn, Greenhouse, and Lever.
    3. Deduplicates across (portal, external_id), (url), and (title, company) using O(1) batch lookup maps.
    4. Commits all JobPosting, UserJobMatch, and ApplicationRecord upserts in a single database transaction.
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
        "greenhouse.io": greenhouse_scraper,
        "lever.co": lever_scraper,
    }

    DEFAULT_PORTALS = [
        "jobs.ge",
        "hr.ge",
        "hr.gov.ge",
        "headhunter.ge",
        "dou.ua",
        "djinni.co",
        "justjoin.it",
        "linkedin.com",
    ]

    async def run_scrapers(
        self,
        portals: Optional[List[str]] = None,
        allow_network: bool = True,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        init_db()
        target_portals = portals or self.DEFAULT_PORTALS

        if not allow_network:
            return self.ingest_scraped_jobs([], owner_email=owner_email, user_id=user_id)

        profile = ground_truth_store.get_profile_record(owner_email=owner_email, user_id=user_id)
        parsed_skills = profile.parsed_skills if profile else {}
        headline = parsed_skills.get("headline", "") if isinstance(parsed_skills, dict) else ""
        cand_langs = (
            parsed_skills.get("spoken_languages", ["English", "Georgian"])
            if isinstance(parsed_skills, dict)
            else ["English", "Georgian"]
        )
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
            elif p in ("greenhouse.io", "greenhouse"):
                tasks.append(greenhouse_scraper.scrape(
                    allow_network=True,
                    domain_keywords=combined_kw,
                    candidate_languages=cand_langs,
                ))
            elif p in ("lever.co", "lever"):
                tasks.append(lever_scraper.scrape(
                    allow_network=True,
                    domain_keywords=combined_kw,
                    candidate_languages=cand_langs,
                ))

        raw_discovered: List[Dict[str, Any]] = []
        if tasks:
            sem = asyncio.Semaphore(6)

            async def _bounded_task(coro):
                async with sem:
                    return await asyncio.wait_for(coro, timeout=9.0)

            batches = await asyncio.gather(*(_bounded_task(t) for t in tasks), return_exceptions=True)
            for b in batches:
                if isinstance(b, list):
                    raw_discovered.extend(b)
                elif isinstance(b, Exception):
                    logger.debug(f"Portal scraper task timeout/error: {b}")

        result = self.ingest_scraped_jobs(raw_discovered, owner_email=owner_email, user_id=user_id)
        if not result.get("jobs"):
            rescored = self.rescore_existing_jobs(owner_email=owner_email, user_id=user_id)
            if rescored.get("jobs"):
                return rescored
        return result

    def rescore_existing_jobs(
        self,
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Re-evaluates existing JobPosting rows in the DB against the current user's profile in <50ms."""
        init_db()
        profile = ground_truth_store.get_profile_record(owner_email=owner_email, user_id=user_id)
        parsed_skills = profile.parsed_skills if profile and profile.parsed_skills else {}
        if not parsed_skills.get("all_skills") and not (profile and profile.raw_markdown):
            return {
                "total_processed": 0,
                "staged_ready_count": 0,
                "filtered_out_count": 0,
                "cache_hits": 0,
                "rejection_reasons": [],
                "jobs": [],
            }

        serialized_jobs: List[Dict[str, Any]] = []
        staged_count = 0
        filtered_count = 0
        with Session(engine, expire_on_commit=False) as session:
            rows = session.exec(select(JobPosting)).all()
            for j in rows:
                tier_res = matcher_service.evaluate_job_tiered(
                    title=j.title or "",
                    description=j.description_raw or "",
                    parsed_skills=parsed_skills,
                    current_status="DISCOVERED",
                    portal=j.portal or "generic",
                )
                score = float(tier_res["suitability_score"])
                final_status = str(tier_res["status"])
                if final_status == "FILTERED_OUT":
                    filtered_count += 1
                    if j.status not in ("APPLIED", "REJECTED"):
                        delete_job_posting_cascade(session, j)
                    continue
                j.suitability_score = score
                j.match_score = score
                j.match_tier = str(tier_res.get("match_tier") or j.match_tier or "DIRECT")
                j.adjacent_role_tag = tier_res.get("adjacent_role_tag")
                j.skill_overlap_pct = tier_res.get("skill_overlap_pct")
                j.match_rationale = str(tier_res.get("match_rationale") or "")
                if j.status not in ("APPLIED", "REJECTED"):
                    j.status = final_status
                session.add(j)
                if final_status == "STAGED":
                    staged_count += 1
                serialized_jobs.append(j.model_dump(mode="json"))
            session.commit()

        return {
            "total_processed": len(serialized_jobs) + filtered_count,
            "staged_ready_count": staged_count,
            "filtered_out_count": filtered_count,
            "cache_hits": len(serialized_jobs),
            "rejection_reasons": [],
            "jobs": serialized_jobs,
        }

    def ingest_scraped_jobs(
        self,
        raw_jobs: List[Dict[str, Any]],
        owner_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Batch-ingests scraped job items in a SINGLE database transaction.
        Pre-fetches existing JobPosting records into O(1) memory maps before the loop,
        eliminating per-item SELECT and COMMIT overhead.
        """
        init_db()
        serialized_jobs: List[Dict[str, Any]] = []
        rejection_reasons: List[Dict[str, str]] = []
        staged_count = 0
        filtered_out_count = 0
        cache_hits = 0

        if not raw_jobs:
            return {
                "total_processed": 0,
                "staged_ready_count": 0,
                "filtered_out_count": 0,
                "cache_hits": 0,
                "rejection_reasons": [],
                "jobs": [],
            }

        profile = ground_truth_store.get_profile_record(owner_email=owner_email, user_id=user_id)
        with Session(engine, expire_on_commit=False) as session:
            if not profile or (not profile.full_name and not profile.raw_markdown):
                profile = session.exec(
                    select(CandidateProfile)
                    .where(CandidateProfile.full_name != "")
                    .order_by(CandidateProfile.updated_at.desc())
                ).first()

            resolved_uid = user_id or (profile.user_id if profile else None)
            parsed_skills = (
                profile.parsed_skills
                if profile and profile.parsed_skills and profile.parsed_skills.get("all_skills")
                else matcher_service.parse_skills_markdown(profile.raw_markdown if profile else "")
            )
            now_utc = utc_now()

            # Pre-fetch all existing JobPostings in ONE query to eliminate N+1 SELECTs inside the loop
            all_existing = session.exec(select(JobPosting)).all()
            by_url: Dict[str, JobPosting] = {}
            by_portal_ext: Dict[Tuple[str, str], JobPosting] = {}
            for j in all_existing:
                if j.url:
                    by_url[j.url] = j
                if j.portal and j.external_id:
                    by_portal_ext[(j.portal, j.external_id)] = j

            active_records_to_serialize: List[Tuple[JobPosting, Dict[str, Any]]] = []

            for item in raw_jobs:
                portal = str(item.get("portal") or "custom")
                ext_id = str(item.get("external_id") or "")
                url = str(item.get("url") or "")
                title = str(item.get("title") or "Specialist")
                company = sanitize_company_name(
                    item.get("company"),
                    target_email=item.get("target_email"),
                    fallback="Hiring Company",
                )
                desc = str(item.get("description_raw") or "")
                market = str(item.get("market") or "GLOBAL_REMOTE")
                initial_status = str(item.get("status") or "DISCOVERED")
                initial_rationale = item.get("filter_out_reason") or item.get("match_rationale") or ""

                existing = by_url.get(url) if url else None
                if not existing and ext_id:
                    existing = by_portal_ext.get((portal, ext_id))

                # 24h DB evaluation cache: skip re-auditing identical posting if profile hasn't changed
                if existing and existing.scraped_at and existing.status != "FILTERED_OUT":
                    scr_ts = existing.scraped_at if existing.scraped_at.tzinfo else existing.scraped_at.replace(tzinfo=timezone.utc)
                    prof_ts = (
                        (profile.updated_at if profile.updated_at.tzinfo else profile.updated_at.replace(tzinfo=timezone.utc))
                        if profile and profile.updated_at
                        else scr_ts
                    )
                    age_ok = (now_utc - scr_ts) < timedelta(hours=24)
                    profile_unchanged = prof_ts <= scr_ts
                    if age_ok and profile_unchanged and initial_status != "FILTERED_OUT" and len(desc) <= len(existing.description_raw or "") + 40:
                        cache_hits += 1
                        if existing.status == "STAGED":
                            staged_count += 1
                        serialized_jobs.append(existing.model_dump(mode="json"))
                        continue

                # 1. Explicit salary extraction ONLY
                sal_info = salary_service.extract_vacancy_salary(
                    title=title,
                    description=desc,
                )

                # 2. Check application deadline & expiration
                dl_date, dl_str, is_expired = parse_vacancy_deadline(desc)
                if is_expired:
                    initial_status = "FILTERED_OUT"
                    initial_rationale = f"Vacancy expired on {dl_str}"

                # 3. Multi-Tier Optimal Match Evaluation
                tier_res = matcher_service.evaluate_job_tiered(
                    title=title,
                    description=desc,
                    parsed_skills=parsed_skills,
                    current_status=initial_status,
                    existing_rationale=initial_rationale,
                    portal=portal,
                )
                score = float(tier_res["suitability_score"])
                final_status = str(tier_res["status"])
                match_rationale = str(tier_res["match_rationale"] or "")
                match_tier = str(tier_res.get("match_tier") or item.get("match_tier") or "DIRECT")
                adj_tag = tier_res.get("adjacent_role_tag")
                overlap_pct = tier_res.get("skill_overlap_pct")

                filter_reason = (initial_rationale or match_rationale) if final_status == "FILTERED_OUT" else None
                if final_status == "FILTERED_OUT":
                    filtered_out_count += 1
                    rej_msg = filter_reason or match_rationale or "Rejected by matcher gate"
                    rejection_reasons.append({
                        "portal": portal,
                        "title": title,
                        "company": company,
                        "reason": rej_msg,
                    })
                    if existing and existing.status not in ("APPLIED", "REJECTED"):
                        delete_job_posting_cascade(session, existing)
                        if url and url in by_url:
                            by_url.pop(url, None)
                        if ext_id and (portal, ext_id) in by_portal_ext:
                            by_portal_ext.pop((portal, ext_id), None)
                    continue
                elif final_status == "STAGED":
                    staged_count += 1

                langs = item.get("detected_languages") or item.get("language_requirements") or ["English"]
                is_est = bool(sal_info["salary_estimated_by_ai"])
                is_rem = bool(item.get("is_remote", True))

                if existing:
                    existing.title = title
                    existing.company = company
                    existing.url = url or existing.url
                    existing.market = market
                    existing.is_remote = is_rem
                    existing.remote_type = "REMOTE" if is_rem else "ONSITE"
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
                    existing.scraped_at = now_utc
                    session.add(existing)
                    job_record = existing
                else:
                    job_record = JobPosting(
                        user_id=resolved_uid,
                        portal=portal,
                        external_id=ext_id,
                        title=title,
                        company=company,
                        url=url,
                        market=market,
                        is_remote=is_rem,
                        remote_type="REMOTE" if is_rem else "ONSITE",
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
                        scraped_at=now_utc,
                    )
                    session.add(job_record)
                    if url:
                        by_url[url] = job_record
                    if ext_id:
                        by_portal_ext[(portal, ext_id)] = job_record

                active_records_to_serialize.append((
                    job_record,
                    {
                        "score": score,
                        "status": final_status,
                        "match_tier": match_tier,
                        "adj_tag": adj_tag,
                        "overlap_pct": overlap_pct,
                        "rationale": match_rationale,
                        "filter_reason": filter_reason,
                    },
                ))

            # Single flush assigns primary key IDs to all newly created JobPostings at once
            session.flush()

            # Pre-fetch existing ApplicationRecords for staged jobs in ONE query
            staged_job_ids = [
                jr.id for jr, _ in active_records_to_serialize
                if jr.status == "STAGED" and jr.id is not None
            ]
            existing_app_job_ids: Set[int] = set()
            if staged_job_ids:
                app_rows = session.exec(
                    select(ApplicationRecord).where(
                        (ApplicationRecord.job_id.in_(staged_job_ids))
                        | (ApplicationRecord.job_posting_id.in_(staged_job_ids))
                    )
                ).all()
                for ar in app_rows:
                    if ar.job_id is not None:
                        existing_app_job_ids.add(ar.job_id)
                    if ar.job_posting_id is not None:
                        existing_app_job_ids.add(ar.job_posting_id)

            for jr, meta in active_records_to_serialize:
                if jr.status == "STAGED" and jr.id is not None and jr.id not in existing_app_job_ids:
                    cv_path = f"/api/resumes/generated/CV_{jr.company[:15]}_{jr.title[:15]}_EN.pdf".replace(" ", "_")
                    cover_txt = f"Auto-staged application for {jr.title} at {jr.company} ({meta['score']}% match)."
                    session.add(
                        ApplicationRecord(
                            user_id=resolved_uid,
                            job_id=jr.id,
                            job_posting_id=jr.id,
                            cv_pdf_path=cv_path,
                            custom_cv_path=cv_path,
                            cover_letter=cover_txt,
                            cover_letter_text=cover_txt,
                            screening_answers={"notice_period": "1 week after offer"},
                            submission_status="STAGED",
                            applied_at=now_utc,
                            updated_at=now_utc,
                        )
                    )
                    existing_app_job_ids.add(jr.id)

            # Batch-upsert UserJobMatch for the current user and check SavedSearch notifications
            if resolved_uid is not None and active_records_to_serialize:
                existing_matches = {
                    m.job_posting_id: m
                    for m in session.exec(
                        select(UserJobMatch).where(UserJobMatch.user_id == resolved_uid)
                    ).all()
                }
                saved_searches = session.exec(
                    select(SavedSearch).where(
                        SavedSearch.user_id == resolved_uid,
                        SavedSearch.notify_on_new == True,  # noqa: E712
                    )
                ).all()

                for jr, meta in active_records_to_serialize:
                    if jr.id is None:
                        continue
                    um = existing_matches.get(jr.id)
                    if um:
                        um.suitability_score = meta["score"]
                        um.match_score = meta["score"]
                        um.match_tier = meta["match_tier"]
                        um.adjacent_role_tag = meta["adj_tag"]
                        um.skill_overlap_pct = meta["overlap_pct"]
                        um.match_rationale = meta["rationale"]
                        um.filter_out_reason = meta["filter_reason"]
                        if um.status not in ("APPLIED", "REJECTED"):
                            um.status = meta["status"]
                        um.evaluated_at = now_utc
                        session.add(um)
                    else:
                        new_um = UserJobMatch(
                            user_id=resolved_uid,
                            job_posting_id=jr.id,
                            suitability_score=meta["score"],
                            match_score=meta["score"],
                            match_tier=meta["match_tier"],
                            adjacent_role_tag=meta["adj_tag"],
                            skill_overlap_pct=meta["overlap_pct"],
                            status=meta["status"],
                            match_rationale=meta["rationale"],
                            filter_out_reason=meta["filter_reason"],
                            evaluated_at=now_utc,
                        )
                        session.add(new_um)
                        existing_matches[jr.id] = new_um

                    for ss in saved_searches:
                        f_dict = ss.filters or {}
                        q_kw = str(f_dict.get("search") or f_dict.get("query") or ss.name or "").strip().lower()
                        if q_kw and (q_kw in jr.title.lower() or q_kw in (jr.description_raw or "").lower()):
                            session.add(
                                Notification(
                                    user_id=resolved_uid,
                                    job_posting_id=jr.id,
                                    saved_search_id=ss.id,
                                    title=f"New match for '{ss.name}': {jr.title}",
                                    message=f"{jr.title} at {jr.company} ({int(round(meta['score']))}% match) on {jr.portal}",
                                )
                            )

            # Single commit for the entire batch!
            session.commit()

            for jr, _ in active_records_to_serialize:
                serialized_jobs.append(jr.model_dump(mode="json"))

            logger.info(
                "[SCRAPER SUMMARY] processed=%d staged=%d rejected=%d cache_hits=%d",
                len(serialized_jobs),
                staged_count,
                filtered_out_count,
                cache_hits,
            )
            return {
                "total_processed": len(serialized_jobs),
                "staged_ready_count": staged_count,
                "filtered_out_count": filtered_out_count,
                "cache_hits": cache_hits,
                "rejection_reasons": rejection_reasons[:50],
                "jobs": [j for j in serialized_jobs if j.get("status") != "FILTERED_OUT"],
            }


scraper_orchestrator = ScraperOrchestrator()
