import asyncio
from datetime import timedelta, timezone
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse
from typing import Dict, Any, List, Optional, Tuple
from sqlmodel import Session, select
from ...db.database import engine, init_db, delete_job_posting_cascade
from ...db.models import (
    JobPosting,
    UserJobMatch,
    SavedSearch,
    Notification,
    utc_now,
)
from ...db.profile_repository import ground_truth_store
from ..salary_service import salary_service
from ..matcher_service import matcher_service
from ..profile_service import profile_service
from ..link_validator import parse_vacancy_deadline, parse_vacancy_published_date
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
from .remote_b2b_scrapers import remotive_scraper, himalayas_scraper, remoteok_scraper

logger = logging.getLogger(__name__)

_TRACKING_PARAM_PREFIXES = ("utm_", "ref", "fbclid", "gclid", "trk", "source", "gh_src")
_NON_ALNUM_RE = re.compile(r"[^\w\u10A0-\u10FF]+", re.UNICODE)


def normalize_job_url(url: str) -> str:
    """Normalizes a vacancy URL for cross-run and cross-source deduplication."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
        kept_params = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if not any(k.lower().startswith(p) for p in _TRACKING_PARAM_PREFIXES)
        ]
        kept_params.sort()
        query = urlencode(kept_params)
        return f"{host}{path}?{query}" if query else f"{host}{path}"
    except Exception:
        return raw.lower().rstrip("/")


def canonical_title_company(title: str, company: str) -> Optional[Tuple[str, str]]:
    """Builds a normalized (title, company) dedupe key when both are meaningful."""
    t_norm = _NON_ALNUM_RE.sub(" ", (title or "").lower()).strip()
    c_norm = _NON_ALNUM_RE.sub(" ", (company or "").lower()).strip()
    if not t_norm or not c_norm or c_norm in ("hiring company", "unknown", "confidential", "company"):
        return None
    return (t_norm, c_norm)


class ScraperOrchestrator:
    """
    Universal Domain-Agnostic Multi-Portal Scraper Orchestrator:
    1. Builds primary, adjacent, public-sector, and remote B2B queries dynamically from CandidateProfile.
    2. Dispatches configured scrapers via SCRAPER_MAP with per-portal health & timing telemetry.
    3. Deduplicates across normalized URL, (portal, external_id), and canonical (title, company).
    4. Commits all JobPosting and UserJobMatch upserts in a single database transaction.
    """

    SCRAPER_MAP = {
        "jobs.ge": jobs_ge_scraper,
        "hr.ge": hr_ge_scraper,
        "hr.gov.ge": hr_gov_scraper,
        "headhunter.ge": headhunter_scraper,
        "remotive.com": remotive_scraper,
        "himalayas.app": himalayas_scraper,
        "remoteok.com": remoteok_scraper,
        "dou.ua": dou_scraper,
        "djinni.co": djinni_scraper,
        "justjoin.it": justjoin_scraper,
        "linkedin.com": linkedin_scraper,
        "greenhouse.io": greenhouse_scraper,
        "lever.co": lever_scraper,
    }

    PORTAL_ALIASES = {
        "greenhouse": "greenhouse.io",
        "lever": "lever.co",
    }

    DEFAULT_PORTALS = [
        "jobs.ge",
        "hr.ge",
        "hr.gov.ge",
        "headhunter.ge",
        "remotive.com",
        "himalayas.app",
        "remoteok.com",
        "dou.ua",
        "djinni.co",
        "justjoin.it",
        "greenhouse.io",
        "lever.co",
        "linkedin.com",
    ]

    def __init__(self) -> None:
        self._source_health: Dict[str, Dict[str, Any]] = {}

    def get_source_health(self) -> List[Dict[str, Any]]:
        """Returns per-portal health and latest scrape telemetry for all known sources."""
        items: List[Dict[str, Any]] = []
        for portal in self.SCRAPER_MAP:
            entry = self._source_health.get(portal)
            if entry:
                items.append(dict(entry))
            else:
                items.append({
                    "portal": portal,
                    "status": "idle",
                    "last_run_at": None,
                    "last_count": 0,
                    "last_latency_ms": 0,
                    "last_error": None,
                    "consecutive_failures": 0,
                })
        return items

    def _record_source_health(
        self,
        portal: str,
        status: str,
        count: int,
        latency_ms: int,
        error: Optional[str] = None,
    ) -> None:
        prev = self._source_health.get(portal) or {}
        failures = 0 if status in ("ok", "disabled") else int(prev.get("consecutive_failures", 0)) + 1
        self._source_health[portal] = {
            "portal": portal,
            "status": status,
            "last_run_at": utc_now().isoformat(),
            "last_count": count,
            "last_latency_ms": latency_ms,
            "last_error": error,
            "consecutive_failures": failures,
        }

    def _build_portal_coro(
        self,
        portal: str,
        search_cfg: Dict[str, Any],
        combined_kw: List[str],
        cand_langs: List[str],
        max_allowed_years: float,
    ):
        canonical = self.PORTAL_ALIASES.get(portal, portal)
        scraper = self.SCRAPER_MAP.get(canonical)
        if not scraper:
            return None, canonical

        if canonical == "jobs.ge":
            return scraper.scrape(allow_network=True, search_urls=search_cfg.get("jobs_ge_urls")), canonical
        if canonical == "hr.ge":
            return scraper.scrape(allow_network=True, search_urls=search_cfg.get("hr_ge_urls"), domain_keywords=combined_kw), canonical
        if canonical == "hr.gov.ge":
            return scraper.scrape(allow_network=True, queries=search_cfg.get("hr_gov_queries"), domain_keywords=combined_kw), canonical
        if canonical == "headhunter.ge":
            hh_urls = search_cfg.get("headhunter_urls") or ([search_cfg["headhunter_url"]] if search_cfg.get("headhunter_url") else [])
            return (scraper.scrape(allow_network=True, search_urls=hh_urls, domain_keywords=combined_kw, candidate_languages=cand_langs) if hh_urls else None), canonical
        if canonical == "dou.ua":
            url = search_cfg.get("dou_url")
            return (scraper.scrape(allow_network=True, search_url=url, candidate_languages=cand_langs) if url else None), canonical
        if canonical == "djinni.co":
            url = search_cfg.get("djinni_exp_url") or search_cfg.get("djinni_url")
            return (scraper.scrape(allow_network=True, search_url=url, candidate_languages=cand_langs) if url else None), canonical
        if canonical == "justjoin.it":
            url = search_cfg.get("justjoin_url")
            return (scraper.scrape(allow_network=True, search_url=url, candidate_languages=cand_langs) if url else None), canonical
        if canonical == "linkedin.com":
            return scraper.scrape(
                allow_network=True,
                search_urls=search_cfg.get("linkedin_urls") or [],
                domain_keywords=combined_kw,
                candidate_languages=cand_langs,
                max_allowed_years=max_allowed_years,
            ), canonical
        # Greenhouse, Lever, Remotive, Himalayas, RemoteOK share a unified signature
        return scraper.scrape(allow_network=True, domain_keywords=combined_kw, candidate_languages=cand_langs), canonical

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
            parsed_skills.get("spoken_languages") or []
            if isinstance(parsed_skills, dict)
            else []
        )
        max_allowed_years = float(parsed_skills.get("max_allowed_years") or 2.0) if isinstance(parsed_skills, dict) else 2.0
        search_cfg = profile_service.get_search_queries_for_profile(parsed_skills, headline=headline)

        combined_kw = list(dict.fromkeys(
            (search_cfg.get("domain_keywords") or []) + (search_cfg.get("adjacent_keywords") or [])
        ))

        scheduled: List[Tuple[str, Any]] = []
        for p in target_portals:
            coro, canonical = self._build_portal_coro(p, search_cfg, combined_kw, cand_langs, max_allowed_years)
            if coro is not None:
                scheduled.append((canonical, coro))

        raw_discovered: List[Dict[str, Any]] = []
        if scheduled:
            sem = asyncio.Semaphore(8)

            async def _bounded_task(portal_name: str, coro):
                started = time.perf_counter()
                try:
                    async with sem:
                        data = await asyncio.wait_for(coro, timeout=32.0)
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    items = data if isinstance(data, list) else []
                    self._record_source_health(portal_name, "ok", len(items), latency_ms)
                    return items
                except asyncio.TimeoutError:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    self._record_source_health(portal_name, "timeout", 0, latency_ms, "Timed out after 32s")
                    logger.debug("Portal scraper %s timed out", portal_name)
                    return []
                except Exception as exc:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    self._record_source_health(portal_name, "error", 0, latency_ms, str(exc)[:180])
                    logger.debug("Portal scraper %s failed: %s", portal_name, exc)
                    return []

            batches = await asyncio.gather(*(_bounded_task(name, coro) for name, coro in scheduled))
            for b in batches:
                if isinstance(b, list):
                    raw_discovered.extend(b)

        result = self.ingest_scraped_jobs(raw_discovered, owner_email=owner_email, user_id=user_id)
        if not result.get("jobs"):
            rescored = self.rescore_existing_jobs(owner_email=owner_email, user_id=user_id)
            if rescored.get("jobs"):
                return rescored
        return result

    @staticmethod
    def _upsert_user_match(
        session: Session,
        existing_matches: Dict[int, UserJobMatch],
        *,
        user_id: int,
        job_id: int,
        score: float,
        match_tier: str,
        adj_tag: Optional[str],
        overlap_pct: Optional[int],
        status: str,
        rationale: str,
        filter_reason: Optional[str],
        now_utc,
    ) -> UserJobMatch:
        um = existing_matches.get(job_id)
        if um:
            um.suitability_score = score
            um.match_score = score
            um.match_tier = match_tier
            um.adjacent_role_tag = adj_tag
            um.skill_overlap_pct = overlap_pct
            um.match_rationale = rationale
            um.filter_out_reason = filter_reason
            if um.status not in ("APPLIED", "REJECTED"):
                um.status = status
            um.evaluated_at = now_utc
        else:
            um = UserJobMatch(
                user_id=user_id,
                job_posting_id=job_id,
                suitability_score=score,
                match_score=score,
                match_tier=match_tier,
                adjacent_role_tag=adj_tag,
                skill_overlap_pct=overlap_pct,
                status=status,
                match_rationale=rationale,
                filter_out_reason=filter_reason,
                evaluated_at=now_utc,
            )
            existing_matches[job_id] = um
        session.add(um)
        return um

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
            return {"total_processed": 0, "staged_ready_count": 0, "filtered_out_count": 0, "cache_hits": 0, "rejection_reasons": [], "jobs": []}

        serialized_jobs: List[Dict[str, Any]] = []
        staged_count = 0
        filtered_count = 0
        resolved_uid = user_id or (profile.user_id if profile else None)
        now_utc = utc_now()
        with Session(engine, expire_on_commit=False) as session:
            rows = session.exec(select(JobPosting)).all()
            existing_matches = (
                {m.job_posting_id: m for m in session.exec(select(UserJobMatch).where(UserJobMatch.user_id == resolved_uid)).all()}
                if resolved_uid is not None
                else {}
            )
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
                match_tier = str(tier_res.get("match_tier") or j.match_tier or "DIRECT")
                adj_tag = tier_res.get("adjacent_role_tag")
                overlap_pct = tier_res.get("skill_overlap_pct")
                rationale = str(tier_res.get("match_rationale") or "")
                filter_reason = str(tier_res.get("filter_out_reason") or "")

                if resolved_uid is not None and j.id is not None:
                    um = self._upsert_user_match(
                        session, existing_matches, user_id=resolved_uid, job_id=j.id,
                        score=score, match_tier=match_tier, adj_tag=adj_tag, overlap_pct=overlap_pct,
                        status=final_status, rationale=rationale, filter_reason=filter_reason, now_utc=now_utc,
                    )
                    if final_status == "FILTERED_OUT":
                        filtered_count += 1
                        continue
                    item_dict = {
                        **j.model_dump(mode="json"),
                        "suitability_score": score,
                        "match_score": score,
                        "match_tier": match_tier,
                        "adjacent_role_tag": adj_tag,
                        "skill_overlap_pct": overlap_pct,
                        "match_rationale": rationale,
                        "status": um.status,
                    }
                    if final_status == "STAGED":
                        staged_count += 1
                    serialized_jobs.append(item_dict)
                else:
                    if final_status == "FILTERED_OUT":
                        filtered_count += 1
                        continue
                    j.suitability_score = score
                    j.match_score = score
                    j.match_tier = match_tier
                    j.adjacent_role_tag = adj_tag
                    j.skill_overlap_pct = overlap_pct
                    j.match_rationale = rationale
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
            resolved_uid = user_id or (profile.user_id if profile and profile.user_id is not None else None)
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
            by_title_company: Dict[Tuple[str, str], JobPosting] = {}
            for j in all_existing:
                if j.url:
                    by_url[normalize_job_url(j.url)] = j
                if j.portal and j.external_id:
                    by_portal_ext[(j.portal, j.external_id)] = j
                tc_key = canonical_title_company(j.title or "", j.company or "")
                if tc_key and tc_key not in by_title_company:
                    by_title_company[tc_key] = j

            active_records_to_serialize: List[Tuple[JobPosting, Dict[str, Any]]] = []
            seen_in_batch: set[Tuple[str, str]] = set()

            for item in raw_jobs:
                portal = str(item.get("portal") or "custom")
                ext_id = str(item.get("external_id") or "")
                url = str(item.get("url") or "")
                norm_url = normalize_job_url(url)
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
                tc_key = canonical_title_company(title, company)

                existing = by_url.get(norm_url) if norm_url else None
                if not existing and ext_id:
                    existing = by_portal_ext.get((portal, ext_id))
                if not existing and tc_key:
                    existing = by_title_company.get(tc_key)

                # Skip duplicate postings within the same scrape batch unless richer description
                if tc_key and tc_key in seen_in_batch and existing and len(desc) <= len(existing.description_raw or "") + 40:
                    cache_hits += 1
                    continue
                if tc_key:
                    seen_in_batch.add(tc_key)

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
                    needs_date_backfill = existing.published_at is None and bool(item.get("published_at") or item.get("posting_date"))
                    if age_ok and profile_unchanged and not needs_date_backfill and initial_status != "FILTERED_OUT" and len(desc) <= len(existing.description_raw or "") + 40:
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

                # 2. Check application deadline, expiration & publication date
                dl_date, dl_str, is_expired = parse_vacancy_deadline(desc)
                if is_expired:
                    initial_status = "FILTERED_OUT"
                    initial_rationale = f"Vacancy expired on {dl_str}"
                pub_dt = item.get("published_at")
                pub_str = item.get("posting_date")
                if pub_dt is None:
                    if pub_str:
                        pub_dt, pub_str_norm = parse_vacancy_published_date(str(pub_str), standalone=True)
                        pub_str = pub_str_norm or pub_str
                    else:
                        pub_dt, pub_str = parse_vacancy_published_date(desc, standalone=False)
                if pub_dt is not None and not pub_str:
                    pub_str = pub_dt.strftime("%Y-%m-%d")

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
                    if existing:
                        if is_expired:
                            existing.is_expired = True
                            existing.status = "FILTERED_OUT"
                            existing.filter_out_reason = rej_msg
                            session.add(existing)
                        elif (
                            existing.user_id is not None
                            and resolved_uid is not None
                            and existing.user_id == resolved_uid
                            and existing.status not in ("APPLIED", "REJECTED")
                        ):
                            delete_job_posting_cascade(session, existing)
                            if norm_url and norm_url in by_url:
                                by_url.pop(norm_url, None)
                            if ext_id and (portal, ext_id) in by_portal_ext:
                                by_portal_ext.pop((portal, ext_id), None)
                            if tc_key and tc_key in by_title_company:
                                by_title_company.pop(tc_key, None)
                    continue
                elif final_status == "STAGED":
                    staged_count += 1

                langs = item.get("detected_languages") or item.get("language_requirements") or ["English"]
                is_est = bool(sal_info["salary_estimated_by_ai"])
                is_rem = bool(item.get("is_remote", True))
                job_fields = {
                    "title": title,
                    "company": company,
                    "url": url or (existing.url if existing else ""),
                    "market": market,
                    "is_remote": is_rem,
                    "remote_type": "REMOTE" if is_rem else "ONSITE",
                    "channel": item.get("channel", "WEB_FORM"),
                    "delivery_channel": item.get("delivery_channel") or item.get("channel", "WEB_FORM"),
                    "target_email": item.get("target_email"),
                    "email_subject": item.get("email_subject"),
                    "email_subject_template": item.get("email_subject_template") or item.get("email_subject"),
                    "detected_languages": langs,
                    "language_requirements": langs,
                    "description_raw": desc,
                    "salary_min": sal_info["min_salary"],
                    "salary_max": sal_info["max_salary"],
                    "salary_currency": sal_info["currency"],
                    "salary_is_estimated": is_est,
                    "salary_estimated_by_ai": is_est,
                    "suitability_score": score,
                    "match_score": score,
                    "match_tier": match_tier,
                    "adjacent_role_tag": adj_tag,
                    "skill_overlap_pct": overlap_pct,
                    "filter_out_reason": filter_reason,
                    "match_rationale": match_rationale,
                    "deadline_text": dl_str or item.get("deadline_text"),
                    "scraped_at": now_utc,
                }
                if existing:
                    for k, v in job_fields.items():
                        setattr(existing, k, v)
                    if pub_dt is not None:
                        existing.published_at = pub_dt
                    if pub_str:
                        existing.posting_date = pub_str
                    if existing.status not in ("APPLIED", "REJECTED"):
                        existing.status = final_status
                    session.add(existing)
                    job_record = existing
                else:
                    job_record = JobPosting(
                        user_id=resolved_uid,
                        portal=portal,
                        external_id=ext_id,
                        status=final_status,
                        posting_date=pub_str,
                        published_at=pub_dt,
                        **job_fields,
                    )
                    session.add(job_record)
                    if norm_url:
                        by_url[norm_url] = job_record
                    if ext_id:
                        by_portal_ext[(portal, ext_id)] = job_record
                    if tc_key:
                        by_title_company[tc_key] = job_record

                active_records_to_serialize.append((
                    job_record,
                    {"score": score, "status": final_status, "match_tier": match_tier, "adj_tag": adj_tag, "overlap_pct": overlap_pct, "rationale": match_rationale, "filter_reason": filter_reason},
                ))

            session.flush()

            if resolved_uid is not None and active_records_to_serialize:
                existing_matches = {
                    m.job_posting_id: m
                    for m in session.exec(select(UserJobMatch).where(UserJobMatch.user_id == resolved_uid)).all()
                }
                saved_searches = session.exec(
                    select(SavedSearch).where(SavedSearch.user_id == resolved_uid, SavedSearch.notify_on_new == True)  # noqa: E712
                ).all()

                for jr, meta in active_records_to_serialize:
                    if jr.id is None:
                        continue
                    self._upsert_user_match(
                        session, existing_matches, user_id=resolved_uid, job_id=jr.id,
                        score=meta["score"], match_tier=meta["match_tier"], adj_tag=meta["adj_tag"],
                        overlap_pct=meta["overlap_pct"], status=meta["status"],
                        rationale=meta["rationale"], filter_reason=meta["filter_reason"], now_utc=now_utc,
                    )

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
