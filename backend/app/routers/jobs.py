import asyncio
import logging
import math
import re as _re
import uuid
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
from pydantic import BaseModel
from sqlalchemy import String, cast, func, case
from sqlmodel import Session, select, or_, and_

from ..db.database import engine, init_db
from ..db.models import (
    CandidateProfile,
    JobPosting,
    SavedJob,
    SavedSearch,
    SavedSearchCreate,
    SavedSearchOut,
    Notification,
    NotificationOut,
    ScrapeTask,
    ApplicationRecord,
    User,
    utc_now,
)
from ..db.profile_repository import ground_truth_store
from ..services.auth_service import get_current_user, get_current_admin
from ..services.scrapers.scraper_orchestrator import scraper_orchestrator
from ..services.scrapers.base_scraper import sanitize_company_name, classify_georgia_b2b_suitability
from ..services.salary_service import salary_service
from ..services.backup_service import backup_service
from ..services.scrape_worker import (
    SCRAPE_WORKER_MODE,
    execute_scrape_task,
    recover_stale_scrape_tasks,
    scrape_queue,
)
from ..services.upload_utils import read_upload_bounded
from pathlib import Path
from .ground_truth import _purge_stale_unapplied_jobs, MAX_UPLOAD_SIZE_BYTES, record_candidate_document
from ..db.document_repository import user_generated_resumes_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Database Profile, Scrapers & Market Intelligence"])

_DJINNI_FIRE_RE = _re.compile(r"🔥+")
_DJINNI_RESPONDS_RE = _re.compile(r"\bResponds Quickly\b.*$", flags=_re.I)
_DJINNI_SALARY_TAIL_RE = _re.compile(r"\s+(?:up\s+to|to|from)\s+[\$€£]\s*\d[\d,]*.*$", flags=_re.I)
_WHITESPACE_RE = _re.compile(r"\s+")


class ScrapeRequest(BaseModel):
    portals: Optional[List[str]] = None
    allow_network: bool = True


class SalaryEstimateRequest(BaseModel):
    title: str
    description: str
    market: str = "INT_REMOTE"
    portal: str = "generic"


def _is_profile_uploaded_for_user(profile: Optional[CandidateProfile], user_email: str) -> bool:
    if not profile:
        return False
    ps = profile.parsed_skills or {}
    if not bool(ps.get("user_uploaded", False)):
        return False
    owner = str(ps.get("owner_email") or "").strip().lower()
    clean_user = (user_email or "").strip().lower()
    if owner and clean_user != owner:
        return False
    return True


@router.post("/profile/upload-skills")
async def upload_skills_profile(
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None),
    run_live_scrape: bool = Form(False),
    current_user: User = Depends(get_current_user),
):
    """
    Accepts .pdf, .docx, .md, or .txt CV/skills uploads or markdown form content,
    validates size & format, extracts role & technical capabilities into the user's CandidateProfile,
    computes missing fields & completeness score, and rescores existing jobs.
    """
    from ..services.cv_parser_service import cv_parser_service

    md_text = ""
    filename = "skills.md"
    if file is not None:
        filename = file.filename or "skills.md"
        raw_bytes = await read_upload_bounded(file, MAX_UPLOAD_SIZE_BYTES)
        if len(raw_bytes) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        try:
            md_text = cv_parser_service.extract_text_from_bytes(raw_bytes, filename=filename)
        except ValueError as parse_err:
            raise HTTPException(status_code=400, detail=str(parse_err))
    elif content is not None:
        if len(content.encode("utf-8")) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="Content exceeds 10 MB maximum size limit.")
        md_text = content
    else:
        raise HTTPException(status_code=400, detail="Provide a .pdf/.docx/.md/.txt file upload or 'content' field.")

    try:
        owner = current_user.email if current_user.email != "guest@talentflow.local" else None
        uid = current_user.id if owner else None
        profile: CandidateProfile = ground_truth_store.ingest_skills_markdown(
            md_text,
            owner_email=owner,
            user_id=uid,
        )

        with Session(engine) as session:
            db_prof = session.get(CandidateProfile, profile.id)
            if db_prof:
                skills_copy = dict(db_prof.parsed_skills or {})
                skills_copy["user_uploaded"] = True
                if owner:
                    skills_copy["owner_email"] = owner
                    if uid is not None:
                        skills_copy["user_id"] = uid
                        db_prof.user_id = uid
                else:
                    skills_copy.pop("owner_email", None)
                    skills_copy.pop("user_id", None)
                    db_prof.user_id = None
                db_prof.parsed_skills = skills_copy
                session.add(db_prof)
                session.commit()
                session.refresh(db_prof)
                profile = db_prof

        scrape_summary: Optional[Dict[str, Any]] = None
        if run_live_scrape:
            try:
                scrape_summary = await scraper_orchestrator.run_scrapers(
                    allow_network=True,
                    owner_email=owner,
                    user_id=uid,
                )
            except Exception as sc_err:
                logger.warning(f"Post-upload live scrape skipped/partial: {sc_err}")
        else:
            try:
                scrape_summary = scraper_orchestrator.rescore_existing_jobs(
                    owner_email=owner,
                    user_id=uid,
                )
            except Exception as rs_err:
                logger.debug(f"Post-upload rescore skipped: {rs_err}")

        clean_taxonomy = {
            k: v for k, v in (profile.parsed_skills or {}).items() if k != "ground_truth_vault"
        }
        gt_after = ground_truth_store.get_data(owner_email=owner, user_id=uid)
        completeness_score, missing_fields = cv_parser_service.compute_missing_fields(gt_after)
        return {
            "status": "success",
            "id": profile.id,
            "full_name": profile.full_name,
            "experience_years": profile.experience_years,
            "profile_uploaded": True,
            "completeness_score": completeness_score,
            "missing_fields": missing_fields,
            "filename": filename,
            "raw_markdown": profile.raw_markdown,
            "parsed_skills": clean_taxonomy,
            "scrape_summary": scrape_summary,
            "updated_at": profile.updated_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to ingest skills.md into CandidateProfile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process skills profile upload.")


@router.get("/profile")
def get_candidate_profile_db(current_user: User = Depends(get_current_user)):
    """Returns the current CandidateProfile record from the relational database scoped to the current user."""
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    profile = ground_truth_store.get_profile_record(owner_email=owner, user_id=current_user.id)
    uploaded = _is_profile_uploaded_for_user(profile, current_user.email)
    clean_taxonomy = {
        k: v for k, v in (profile.parsed_skills or {}).items() if k != "ground_truth_vault"
    }
    return {
        "id": profile.id,
        "full_name": profile.full_name if uploaded else "",
        "email": profile.email if uploaded else "",
        "phone": profile.phone if uploaded else "",
        "location": profile.location if uploaded else "",
        "github_url": profile.github_url if uploaded else "",
        "linkedin_url": profile.linkedin_url if uploaded else "",
        "experience_years": profile.experience_years if uploaded else 0.0,
        "profile_uploaded": uploaded,
        "raw_markdown": profile.raw_markdown if uploaded else "",
        "parsed_skills": clean_taxonomy if uploaded else {},
        "updated_at": profile.updated_at.isoformat(),
    }


@router.post("/jobs/scrape")
async def trigger_multi_portal_scrape(
    request: Optional[ScrapeRequest] = None,
    current_user: User = Depends(get_current_user),
):
    """Runs the live multi-portal scraper engine for the current user's profile."""
    portals = request.portals if request else None
    allow_net = request.allow_network if request else True
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    return await scraper_orchestrator.run_scrapers(
        portals=portals,
        allow_network=allow_net,
        owner_email=owner,
        user_id=current_user.id,
    )


@router.post("/jobs/scrape/async")
async def trigger_async_scrape(
    request: Optional[ScrapeRequest] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Enqueues a durable DB-backed background scrape task with stale-task recovery,
    heartbeats, execution timeouts, and per-user duplicate run deduplication.
    Returns a task_id that can be polled via GET /api/jobs/scrape/status/{task_id}.
    """
    portals = request.portals if request else None
    allow_net = request.allow_network if request else True
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None

    enqueued = scrape_queue.enqueue_task(
        user_id=current_user.id,
        portals=portals,
        allow_network=allow_net,
    )
    if enqueued.get("deduplicated"):
        return enqueued

    task_id = enqueued["task_id"]
    if not allow_net:
        await execute_scrape_task(task_id, owner_email=owner)
    elif SCRAPE_WORKER_MODE != "external":
        # If FastAPI lifespan embedded consumer is active, notify_worker() wakes it.
        # When invoked in contexts without lifespan (e.g. direct TestClient), dispatch cleanly.
        if scrape_queue._consumer_task is None or scrape_queue._consumer_task.done():
            asyncio.create_task(execute_scrape_task(task_id, owner_email=owner))

    with Session(engine) as session:
        t_now = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == task_id)).first()
        return {
            "task_id": task_id,
            "status": t_now.status if t_now else "QUEUED",
            "deduplicated": False,
        }


@router.get("/jobs/scrape/status/{task_id}")
def get_scrape_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """Returns progress and completion metrics for a durable background scrape task."""
    recover_stale_scrape_tasks()
    with Session(engine) as session:
        t_row = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == task_id)).first()
        if not t_row:
            raise HTTPException(status_code=404, detail=f"Scrape task {task_id} not found.")
        if t_row.user_id is None or t_row.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden: scrape task belongs to another user.")
        summary = t_row.result_summary or {}
        return {
            "task_id": t_row.task_id,
            "status": t_row.status,
            "portals": t_row.portals,
            "progress_pct": t_row.progress_pct,
            "attempt_count": t_row.attempt_count,
            "max_attempts": t_row.max_attempts,
            "worker_id": t_row.worker_id,
            "heartbeat_at": t_row.heartbeat_at.isoformat() if t_row.heartbeat_at else None,
            "total_processed": summary.get("total_processed", 0),
            "staged_count": summary.get("staged_ready_count", 0),
            "filtered_out_count": summary.get("filtered_out_count", 0),
            "error_message": t_row.error_message,
            "created_at": t_row.created_at.isoformat() if t_row.created_at else None,
            "completed_at": t_row.completed_at.isoformat() if t_row.completed_at else None,
        }


@router.get("/jobs/sources/health")
def get_job_sources_health(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns per-portal scraper health, last successful sync, latency, and error diagnostics."""
    del current_user
    return {
        "sources": scraper_orchestrator.get_source_health(),
        "default_portals": list(scraper_orchestrator.DEFAULT_PORTALS),
    }


@router.get("/jobs")
async def list_scraped_jobs(
    page: int = Query(1, ge=1, description="1-based page index"),
    limit: int = Query(12, ge=1, le=200, description="Page size"),
    portal: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tier: Optional[str] = Query(None, description="Optional tier filter: direct, adjacent, or internship"),
    min_score: Optional[float] = Query(60.0, description="Minimum suitability score threshold."),
    include_filtered: bool = Query(False, description="Include FILTERED_OUT (blocked/disqualified) jobs."),
    search: Optional[str] = Query(None, description="Multi-keyword search across title, company, description, rationale"),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    remote_type: Optional[str] = Query(None, description="REMOTE, HYBRID, or ONSITE"),
    salary_min: Optional[float] = Query(None),
    language: Optional[str] = Query(None),
    technology: Optional[str] = Query(None),
    experience_level: Optional[str] = Query(None, description="intern, junior, mid, or senior"),
    employment_type: Optional[str] = Query(None, description="full_time, part_time, contract, or internship"),
    sort_by: str = Query("relevance", description="relevance, newest, salary_desc, or company_asc"),
    only_new: bool = Query(False, description="Exclude jobs already applied to or saved"),
    only_saved: bool = Query(False, description="Only return jobs bookmarked by current user"),
    b2b_only: bool = Query(False, description="Only return remote B2B / international contractor eligible roles"),
    geo_eligible_only: bool = Query(False, description="Exclude roles with foreign US/EU residency locks"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Lists suitable JobPosting records scoped strictly to the current user via UserJobMatch,
    with single-query conditional aggregation, Georgia B2B eligibility tagging, and pagination.
    """
    from ..db.models import UserJobMatch

    init_db()
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    uid = current_user.id if owner else None
    profile = ground_truth_store.get_profile_record(owner_email=owner, user_id=current_user.id)

    with Session(engine) as session:
        if not _is_profile_uploaded_for_user(profile, current_user.email):
            return {
                "items": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "total_pages": 1,
                "tier_counts": {"ALL": 0, "DIRECT": 0, "ADJACENT": 0, "PUBLIC_INTERNSHIP": 0},
                "status_counts": {"ALL": 0, "STAGED": 0, "AUDITED": 0},
            }

        use_user_matches = uid is not None
        score_col = func.coalesce(UserJobMatch.suitability_score, JobPosting.suitability_score) if use_user_matches else JobPosting.suitability_score
        status_col = func.coalesce(UserJobMatch.status, JobPosting.status) if use_user_matches else JobPosting.status
        tier_col = func.coalesce(UserJobMatch.match_tier, JobPosting.match_tier) if use_user_matches else JobPosting.match_tier

        base_conds = [JobPosting.is_expired == False]
        if not include_filtered:
            base_conds.append(status_col != "FILTERED_OUT")
        if portal and portal.upper() != "ALL":
            base_conds.append(JobPosting.portal == portal)
        if market and market.upper() != "ALL":
            base_conds.append(JobPosting.market == market)
        if min_score is not None and min_score > 0:
            base_conds.append(score_col >= min_score)
        def _esc_like(val: str) -> str:
            return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        if search and search.strip():
            tokens = [tok for tok in _re.split(r"[\s,;]+", search.strip()) if len(tok) >= 2][:6]
            if not tokens:
                tokens = [search.strip()]
            for tok in tokens:
                kw = f"%{_esc_like(tok)}%"
                base_conds.append(
                    or_(
                        JobPosting.title.ilike(kw, escape="\\"),
                        JobPosting.company.ilike(kw, escape="\\"),
                        JobPosting.description_raw.ilike(kw, escape="\\"),
                        JobPosting.match_rationale.ilike(kw, escape="\\"),
                    )
                )
        if country and country.strip():
            c_clean = country.strip()
            ckw = f"%{_esc_like(c_clean)}%"
            c_missing = or_(JobPosting.country.is_(None), JobPosting.country == "")
            c_fallbacks = [JobPosting.market.ilike(ckw, escape="\\")]
            if c_clean.lower() in ("georgia", "ge", "sakartvelo"):
                c_fallbacks.append(JobPosting.market.ilike("GE%", escape="\\"))
                c_fallbacks.append(JobPosting.country.ilike("%GE%", escape="\\"))
            base_conds.append(
                or_(
                    JobPosting.country.ilike(ckw, escape="\\"),
                    and_(c_missing, or_(*c_fallbacks)),
                )
            )
        if city and city.strip():
            city_clean = city.strip()
            city_kw = f"%{_esc_like(city_clean)}%"
            city_missing = or_(JobPosting.city.is_(None), JobPosting.city == "")
            base_conds.append(
                or_(
                    JobPosting.city.ilike(city_kw, escape="\\"),
                    and_(
                        city_missing,
                        or_(
                            JobPosting.market.ilike(city_kw, escape="\\"),
                            JobPosting.description_raw.ilike(city_kw, escape="\\"),
                        ),
                    ),
                )
            )
        if remote_type and remote_type.upper() != "ALL":
            rt_up = remote_type.strip().upper()
            if rt_up == "REMOTE":
                base_conds.append(JobPosting.is_remote == True)  # noqa: E712
            else:
                base_conds.append(JobPosting.remote_type == rt_up)
        if salary_min is not None and salary_min > 0:
            base_conds.append(JobPosting.salary_max >= salary_min)
        if technology and technology.strip():
            tech_tokens = [tok for tok in _re.split(r"[,;]+", technology.strip()) if tok.strip()][:5]
            for tech_tok in tech_tokens:
                tkw = f"%{_esc_like(tech_tok.strip())}%"
                base_conds.append(
                    or_(
                        JobPosting.title.ilike(tkw, escape="\\"),
                        JobPosting.description_raw.ilike(tkw, escape="\\"),
                        JobPosting.match_rationale.ilike(tkw, escape="\\"),
                    )
                )
        if language and language.strip():
            lkw = f"%{_esc_like(language.strip())}%"
            base_conds.append(
                or_(
                    JobPosting.description_raw.ilike(lkw, escape="\\"),
                    cast(JobPosting.language_requirements, String).ilike(lkw, escape="\\"),
                )
            )
        if experience_level and experience_level.strip().lower() not in ("all", ""):
            exp_low = experience_level.strip().lower()
            exp_patterns = {
                "intern": ["intern", "trainee", "სტაჟირ", "graduate", "entry"],
                "junior": ["junior", "entry", "associate", "0-2", "1-2", "1+ year"],
                "mid": ["mid", "middle", "2-4", "3-5", "3+ year", "regular"],
                "senior": ["senior", "lead", "principal", "staff", "5+ year", "architect"],
            }.get(exp_low, [exp_low])
            base_conds.append(
                or_(
                    *[
                        or_(
                            JobPosting.title.ilike(f"%{_esc_like(p)}%", escape="\\"),
                            JobPosting.description_raw.ilike(f"%{_esc_like(p)}%", escape="\\"),
                        )
                        for p in exp_patterns
                    ]
                )
            )
        if employment_type and employment_type.strip().lower() not in ("all", ""):
            emp_low = employment_type.strip().lower()
            emp_patterns = {
                "full_time": ["full-time", "full time", "სრული განაკვეთ"],
                "part_time": ["part-time", "part time", "ნახევარი განაკვეთ"],
                "contract": ["contract", "b2b", "freelance", "contractor"],
                "internship": ["intern", "internship", "სტაჟირ"],
            }.get(emp_low, [emp_low])
            base_conds.append(
                or_(
                    *[
                        or_(
                            JobPosting.title.ilike(f"%{_esc_like(p)}%", escape="\\"),
                            JobPosting.description_raw.ilike(f"%{_esc_like(p)}%", escape="\\"),
                        )
                        for p in emp_patterns
                    ]
                )
            )
        if only_saved and current_user.id is not None:
            saved_sub = select(SavedJob.job_posting_id).where(SavedJob.user_id == current_user.id)
            base_conds.append(JobPosting.id.in_(saved_sub))
        if only_new and current_user.id is not None:
            applied_sub = select(ApplicationRecord.job_posting_id).where(
                ApplicationRecord.user_id == current_user.id,
                ApplicationRecord.job_posting_id.is_not(None),
            )
            base_conds.append(JobPosting.id.not_in(applied_sub))
        if b2b_only:
            base_conds.append(
                or_(
                    JobPosting.portal.in_(["remotive.com", "himalayas.app", "remoteok.com", "djinni.co", "dou.ua", "justjoin.it", "greenhouse.io", "lever.co"]),
                    JobPosting.market.in_(["GLOBAL_REMOTE", "INT_REMOTE", "EU_REMOTE"]),
                )
            )

        def _serialize_job_row(entry: Any) -> Dict[str, Any]:
            if use_user_matches:
                r, um = entry
                dumped = r.model_dump(mode="json")
                if um is not None:
                    dumped["suitability_score"] = um.suitability_score
                    dumped["match_score"] = um.match_score
                    dumped["match_tier"] = um.match_tier or dumped.get("match_tier")
                    dumped["adjacent_role_tag"] = um.adjacent_role_tag
                    dumped["skill_overlap_pct"] = um.skill_overlap_pct
                    dumped["status"] = um.status
                    dumped["match_rationale"] = um.match_rationale or dumped.get("match_rationale")
            else:
                r = entry
                dumped = r.model_dump(mode="json")

            if str(dumped.get("salary_currency") or "").lower() in ("gel", "ლარი", "ᲚᲐᲠᲘ", "₾"):
                dumped["salary_currency"] = "GEL"
            dumped["company"] = sanitize_company_name(
                dumped.get("company"),
                target_email=dumped.get("target_email"),
                fallback="Employer",
            )
            if dumped.get("portal") == "djinni.co" and dumped.get("title"):
                raw_t = str(dumped["title"])
                clean_t = _DJINNI_FIRE_RE.sub("", raw_t)
                clean_t = _DJINNI_RESPONDS_RE.sub("", clean_t)
                clean_t = _DJINNI_SALARY_TAIL_RE.sub("", clean_t)
                if dumped.get("company") and len(dumped["company"]) > 2:
                    ci = clean_t.find(f" {dumped['company']}")
                    if ci > 4:
                        clean_t = clean_t[:ci]
                dumped["title"] = _WHITESPACE_RE.sub(" ", clean_t).strip() or raw_t
                if dumped.get("salary_min") is None:
                    sal_ex = salary_service.extract_explicit_salary(f"{raw_t}\n{dumped.get('description_raw', '')}")
                    if sal_ex:
                        dumped["salary_min"], dumped["salary_max"], dumped["salary_currency"] = sal_ex
                        dumped["salary_is_estimated"] = False
                        dumped["salary_estimated_by_ai"] = False
            if dumped.get("salary_min") is None and dumped.get("salary_max") is None:
                dumped["salary_source"] = "missing"
            elif dumped.get("salary_is_estimated") or dumped.get("salary_estimated_by_ai"):
                dumped["salary_source"] = "ai_estimated"
            else:
                dumped["salary_source"] = "verified"
            dumped["posting_date"] = dumped.get("scraped_at")

            loc_parts = [str(dumped.get(k) or "").strip() for k in ("city", "country", "market") if dumped.get(k)]
            geo_info = classify_georgia_b2b_suitability(
                title=str(dumped.get("title") or ""),
                description=str(dumped.get("description_raw") or ""),
                location_text=", ".join(loc_parts),
                portal=str(dumped.get("portal") or ""),
                market=str(dumped.get("market") or ""),
                salary_currency=dumped.get("salary_currency"),
            )
            dumped.update(geo_info)
            return dumped

        sort_norm = (sort_by or "relevance").strip().lower()
        if sort_norm == "newest":
            order_clauses = (JobPosting.scraped_at.desc(), score_col.desc())
        elif sort_norm == "salary_desc":
            order_clauses = (func.coalesce(JobPosting.salary_max, JobPosting.salary_min, -1).desc(), score_col.desc())
        elif sort_norm == "company_asc":
            order_clauses = (JobPosting.company.asc(), score_col.desc())
        else:
            order_clauses = (score_col.desc(), JobPosting.scraped_at.desc())

        if geo_eligible_only:
            if use_user_matches:
                base_stmt = select(JobPosting, UserJobMatch).outerjoin(
                    UserJobMatch,
                    (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == uid),
                )
            else:
                base_stmt = select(JobPosting)
            if base_conds:
                base_stmt = base_stmt.where(*base_conds)
            base_stmt = base_stmt.order_by(*order_clauses)
            all_geo_items = [
                dumped
                for entry in session.exec(base_stmt).all()
                if (dumped := _serialize_job_row(entry)).get("georgia_eligible")
            ]

            tier_counts = {"ALL": len(all_geo_items), "DIRECT": 0, "ADJACENT": 0, "PUBLIC_INTERNSHIP": 0}
            status_counts = {"ALL": len(all_geo_items), "STAGED": 0, "AUDITED": 0}
            for it in all_geo_items:
                mt = it.get("match_tier")
                if mt == "DIRECT":
                    tier_counts["DIRECT"] += 1
                elif mt == "ADJACENT":
                    tier_counts["ADJACENT"] += 1
                if mt == "PUBLIC_INTERNSHIP" or it.get("portal") == "hr.gov.ge":
                    tier_counts["PUBLIC_INTERNSHIP"] += 1
                st_val = it.get("status")
                if st_val == "STAGED":
                    status_counts["STAGED"] += 1
                elif st_val == "AUDITED":
                    status_counts["AUDITED"] += 1

            eligible_filtered = all_geo_items
            if status and status.upper() != "ALL":
                eligible_filtered = [it for it in eligible_filtered if it.get("status") == status]
            if tier and tier.upper() != "ALL":
                t_low = tier.strip().lower()
                if t_low == "direct":
                    eligible_filtered = [it for it in eligible_filtered if it.get("match_tier") == "DIRECT"]
                elif t_low == "adjacent":
                    eligible_filtered = [it for it in eligible_filtered if it.get("match_tier") == "ADJACENT"]
                elif t_low in ("internship", "public_internship"):
                    eligible_filtered = [
                        it
                        for it in eligible_filtered
                        if it.get("match_tier") == "PUBLIC_INTERNSHIP" or it.get("portal") == "hr.gov.ge"
                    ]

            total = len(eligible_filtered)
            total_pages = max(1, math.ceil(total / limit))
            offset = (page - 1) * limit
            items = eligible_filtered[offset : offset + limit]
            return {
                "items": items,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "tier_counts": tier_counts,
                "status_counts": status_counts,
            }

        agg_stmt = select(
            func.count().label("all_cnt"),
            func.sum(case((tier_col == "DIRECT", 1), else_=0)).label("direct_cnt"),
            func.sum(case((tier_col == "ADJACENT", 1), else_=0)).label("adjacent_cnt"),
            func.sum(
                case(
                    ((tier_col == "PUBLIC_INTERNSHIP") | (JobPosting.portal == "hr.gov.ge"), 1),
                    else_=0,
                )
            ).label("intern_cnt"),
            func.sum(case((status_col == "STAGED", 1), else_=0)).label("staged_cnt"),
            func.sum(case((status_col == "AUDITED", 1), else_=0)).label("audited_cnt"),
        ).select_from(JobPosting)
        if use_user_matches:
            agg_stmt = agg_stmt.outerjoin(
                UserJobMatch,
                (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == uid),
            )
        if base_conds:
            agg_stmt = agg_stmt.where(*base_conds)

        agg_row = session.exec(agg_stmt).one()
        all_cnt = int(agg_row[0] or 0)
        tier_counts = {
            "ALL": all_cnt,
            "DIRECT": int(agg_row[1] or 0),
            "ADJACENT": int(agg_row[2] or 0),
            "PUBLIC_INTERNSHIP": int(agg_row[3] or 0),
        }
        status_counts = {
            "ALL": all_cnt,
            "STAGED": int(agg_row[4] or 0),
            "AUDITED": int(agg_row[5] or 0),
        }

        conditions = list(base_conds)
        has_extra_filter = False
        if status and status.upper() != "ALL":
            conditions.append(status_col == status)
            has_extra_filter = True
        if tier and tier.upper() != "ALL":
            t_low = tier.strip().lower()
            has_extra_filter = True
            if t_low == "direct":
                conditions.append(tier_col == "DIRECT")
            elif t_low == "adjacent":
                conditions.append(tier_col == "ADJACENT")
            elif t_low in ("internship", "public_internship"):
                conditions.append((tier_col == "PUBLIC_INTERNSHIP") | (JobPosting.portal == "hr.gov.ge"))

        if has_extra_filter:
            count_stmt = select(func.count()).select_from(JobPosting)
            if use_user_matches:
                count_stmt = count_stmt.outerjoin(
                    UserJobMatch,
                    (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == uid),
                )
            total = int(session.exec(count_stmt.where(*conditions)).one() or 0)
        else:
            total = all_cnt

        total_pages = max(1, math.ceil(total / limit))

        if use_user_matches:
            stmt = select(JobPosting, UserJobMatch).outerjoin(
                UserJobMatch,
                (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == uid),
            )
        else:
            stmt = select(JobPosting)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = (
            stmt.order_by(*order_clauses)
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = session.exec(stmt).all()
        items = [_serialize_job_row(entry) for entry in rows]

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "tier_counts": tier_counts,
            "status_counts": status_counts,
        }


def _build_jd_snapshot(job: JobPosting) -> Dict[str, Any]:
    """Captures an immutable job description snapshot at bookmark/application time."""
    from ..db.models import utc_now

    return {
        "job_id": job.id,
        "portal": job.portal,
        "title": job.title,
        "company": job.company,
        "url": job.url,
        "market": job.market,
        "location": ", ".join(x for x in (job.city, job.country) if x) or None,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "description_raw": job.description_raw,
        "captured_at": utc_now().isoformat(),
    }


@router.post("/jobs/{job_id}/save")
def save_job_bookmark(
    job_id: int,
    notes: str = "",
    current_user: User = Depends(get_current_user),
):
    """Bookmarks a job posting for the current user with an immutable JD snapshot."""
    with Session(engine) as session:
        job = session.get(JobPosting, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job posting not found.")
        existing = session.exec(
            select(SavedJob).where(
                SavedJob.user_id == current_user.id,
                SavedJob.job_posting_id == job_id,
            )
        ).first()
        if existing:
            if not existing.jd_snapshot:
                existing.jd_snapshot = _build_jd_snapshot(job)
                session.add(existing)
                session.commit()
                session.refresh(existing)
            return {"status": "saved", "id": existing.id, "job_id": job_id, "jd_snapshot": existing.jd_snapshot}
        sj = SavedJob(
            user_id=current_user.id,
            job_posting_id=job_id,
            notes=notes,
            jd_snapshot=_build_jd_snapshot(job),
        )
        session.add(sj)
        session.commit()
        session.refresh(sj)
        return {"status": "saved", "id": sj.id, "job_id": job_id, "jd_snapshot": sj.jd_snapshot}


@router.delete("/jobs/{job_id}/save")
def remove_saved_job_bookmark(
    job_id: int,
    current_user: User = Depends(get_current_user),
):
    """Removes a bookmarked job for the current user."""
    with Session(engine) as session:
        existing = session.exec(
            select(SavedJob).where(
                SavedJob.user_id == current_user.id,
                SavedJob.job_posting_id == job_id,
            )
        ).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Saved job bookmark not found.")
        session.delete(existing)
        session.commit()
        return {"status": "removed", "job_id": job_id}


@router.get("/saved-searches", response_model=List[SavedSearchOut])
def list_saved_searches(current_user: User = Depends(get_current_user)):
    """Lists saved search filters for the current user."""
    with Session(engine) as session:
        rows = session.exec(
            select(SavedSearch)
            .where(SavedSearch.user_id == current_user.id)
            .order_by(SavedSearch.created_at.desc())
        ).all()
        return [
            SavedSearchOut(
                id=r.id,
                user_id=r.user_id,
                name=r.name,
                filters=r.filters or {},
                notify_on_new=r.notify_on_new,
                last_run_at=r.last_run_at.isoformat() if r.last_run_at else None,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
            for r in rows
        ]


@router.post("/saved-searches", response_model=SavedSearchOut)
def create_saved_search(
    req: SavedSearchCreate,
    current_user: User = Depends(get_current_user),
):
    """Creates a saved search filter and alert rule for the current user."""
    with Session(engine) as session:
        row = SavedSearch(
            user_id=current_user.id,
            name=req.name,
            filters=req.filters,
            notify_on_new=req.notify_on_new,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return SavedSearchOut(
            id=row.id,
            user_id=row.user_id,
            name=row.name,
            filters=row.filters or {},
            notify_on_new=row.notify_on_new,
            last_run_at=row.last_run_at.isoformat() if row.last_run_at else None,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )


@router.delete("/saved-searches/{search_id}")
def delete_saved_search(
    search_id: int,
    current_user: User = Depends(get_current_user),
):
    """Deletes a saved search after verifying ownership."""
    with Session(engine) as session:
        row = session.get(SavedSearch, search_id)
        if not row:
            raise HTTPException(status_code=404, detail="Saved search not found.")
        if row.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden: saved search belongs to another user.")
        session.delete(row)
        session.commit()
        return {"status": "deleted", "id": search_id}


@router.get("/notifications", response_model=List[NotificationOut])
def list_notifications(current_user: User = Depends(get_current_user)):
    """Lists job match notifications for the current user."""
    with Session(engine) as session:
        rows = session.exec(
            select(Notification)
            .where(Notification.user_id == current_user.id)
            .order_by(Notification.created_at.desc())
            .limit(50)
        ).all()
        return [
            NotificationOut(
                id=r.id,
                user_id=r.user_id,
                job_posting_id=r.job_posting_id,
                saved_search_id=r.saved_search_id,
                title=r.title,
                message=r.message,
                notification_type=r.notification_type,
                is_read=r.is_read,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
            for r in rows
        ]


@router.patch("/notifications/{notif_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notif_id: int,
    current_user: User = Depends(get_current_user),
):
    """Marks a notification as read after verifying ownership."""
    with Session(engine) as session:
        row = session.get(Notification, notif_id)
        if not row:
            raise HTTPException(status_code=404, detail="Notification not found.")
        if row.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden: notification belongs to another user.")
        row.is_read = True
        session.add(row)
        session.commit()
        session.refresh(row)
        return NotificationOut(
            id=row.id,
            user_id=row.user_id,
            job_posting_id=row.job_posting_id,
            saved_search_id=row.saved_search_id,
            title=row.title,
            message=row.message,
            notification_type=row.notification_type,
            is_read=row.is_read,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )


@router.post("/admin/backup")
def create_database_backup(current_user: User = Depends(get_current_admin)):
    """Creates a hot atomic SQLite database backup with SHA-256 verification (Admin only)."""
    return backup_service.create_backup(reason="api")


@router.get("/admin/backups")
def list_database_backups(current_user: User = Depends(get_current_admin)):
    """Lists available database backup snapshots (Admin only)."""
    return {"backups": backup_service.list_backups()}


@router.post("/salary/estimate")
def estimate_job_salary(
    req: SalaryEstimateRequest,
    current_user: User = Depends(get_current_user),
):
    """Estimates or extracts salary range without asking the user for input."""
    return salary_service.estimate_salary(
        title=req.title,
        description=req.description,
        market=req.market,
        portal=req.portal,
    )


@router.post("/jobs/{job_id}/prepare-email-package")
def prepare_job_email_package(
    job_id: int,
    cv_language: str = Query("auto"),
    create_draft: bool = Query(True),
    current_user: User = Depends(get_current_user),
):
    """
    Prepares a complete tailored Word (.docx) CV + Cover Letter + clean Subject line,
    records document ownership, and saves a Gmail Draft with the tailored .docx CV attached.
    """
    from ..services.cv_generator_service import cv_generator_service
    from ..services.gmail_service import gmail_service

    init_db()
    with Session(engine) as session:
        job = session.get(JobPosting, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Vacancy not found")

        owner = current_user.email if current_user.email != "guest@talentflow.local" else None
        pkg = cv_generator_service.prepare_email_application_package(
            job_title=job.title,
            company=job.company,
            description=job.description_raw,
            portal=job.portal,
            target_email=job.target_email,
            email_subject_template=job.email_subject,
            cv_language=cv_language,
            cv_style="tailored",
            owner_email=owner,
            user_id=current_user.id,
        )

        user_gen_dir = user_generated_resumes_dir(current_user.id)
        for fname_key in ("pdf_filename", "docx_filename", "cv_filename"):
            fname_val = pkg.get(fname_key)
            if fname_val:
                record_candidate_document(
                    user_id=current_user.id,
                    filename=fname_val,
                    file_path=user_gen_dir / fname_val,
                    doc_type="generated_email_cv",
                    target_company=job.company,
                    target_role=job.title,
                )

        draft_res = {
            "draft_created": False,
            "draft_id": None,
            "attached_files": [pkg["docx_filename"]],
            "drafts_url": None,
            "mode_used": "skipped",
            "error": None,
        }
        if create_draft:
            draft_res = gmail_service.create_gmail_draft(
                recipient_email=pkg["recipient_email"],
                subject=pkg["subject"],
                body_text=pkg["cover_letter"],
                attachment_paths=[pkg.get("docx_path") or pkg["docx_filename"]],
                user=current_user,
            )

        pkg["gmail_draft_saved"] = bool(draft_res.get("draft_created"))
        pkg["gmail_draft_id"] = draft_res.get("draft_id")
        pkg["gmail_drafts_url"] = draft_res.get("drafts_url")
        pkg["attached_files"] = draft_res.get("attached_files", [pkg["docx_filename"]])
        pkg["draft_mode_used"] = draft_res.get("mode_used")
        pkg["draft_error"] = draft_res.get("error")
        return pkg


@router.get("/analytics/candidate")
def get_candidate_analytics(current_user: User = Depends(get_current_user)):
    """
    Real SQL-computed candidate funnel analytics, match tier summary, and profile completeness check.
    """
    from ..db.models import UserJobMatch, ApplicationTracker, InterviewRound, CVVersion

    init_db()
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    uid = current_user.id if owner else None
    profile = ground_truth_store.get_profile_record(owner_email=owner, user_id=uid)
    gt = ground_truth_store.get_data(owner_email=owner, user_id=uid)
    cand = gt.get("candidate") or {}
    ps = (profile.parsed_skills or {}) if profile else {}

    checks = {
        "full_name": bool((cand.get("full_name") or "").strip() and cand.get("full_name") != "Candidate"),
        "email": bool((cand.get("email") or "").strip()),
        "phone": bool((cand.get("phone") or "").strip()),
        "location": bool(isinstance(cand.get("location"), dict) and (cand["location"].get("city") or cand["location"].get("country"))),
        "skills": bool((gt.get("skills") or {}).get("core")),
        "work_history": bool(gt.get("work_history")),
        "education": bool(gt.get("education")),
        "links": bool(isinstance(cand.get("links"), dict) and (cand["links"].get("linkedin") or cand["links"].get("github") or cand["links"].get("portfolio"))),
    }
    missing_fields = [k for k, ok in checks.items() if not ok]
    completeness_pct = int(round((sum(1 for ok in checks.values() if ok) / len(checks)) * 100))

    with Session(engine) as session:
        if uid is not None:
            matched_pairs = session.exec(
                select(UserJobMatch, JobPosting)
                .join(JobPosting, JobPosting.id == UserJobMatch.job_posting_id)
                .where(UserJobMatch.user_id == uid)
            ).all()
            matching_jobs = [m for m, _ in matched_pairs if m.status != "FILTERED_OUT"]
            matching_job_postings = [j for m, j in matched_pairs if m.status != "FILTERED_OUT"]
            ready_to_apply = sum(1 for m in matching_jobs if float(m.suitability_score or 0) >= 75.0)
        else:
            jobs = session.exec(
                select(JobPosting).where(JobPosting.status != "FILTERED_OUT")
            ).all()
            matching_jobs = jobs
            matching_job_postings = jobs
            ready_to_apply = sum(1 for j in jobs if float(j.suitability_score or 0) >= 75.0)

        tier_counts: Dict[str, int] = {"DIRECT": 0, "ADJACENT": 0, "PUBLIC_INTERNSHIP": 0}
        for row in matching_jobs:
            t = str(getattr(row, "match_tier", None) or "DIRECT")
            tier_counts[t] = tier_counts.get(t, 0) + 1

        remote_b2b_count = 0
        local_ge_count = 0
        for jp in matching_job_postings:
            ginfo = classify_georgia_b2b_suitability(
                title=str(jp.title or ""),
                description=str(jp.description_raw or ""),
                location_text=str(jp.market or ""),
                portal=str(jp.portal or ""),
                market=str(jp.market or ""),
                salary_currency=jp.salary_currency,
            )
            if ginfo["contract_mode"] == "GE_LOCAL":
                local_ge_count += 1
            elif ginfo["contract_mode"] == "REMOTE_B2B" and ginfo["georgia_eligible"]:
                remote_b2b_count += 1

        saved_count = len(
            session.exec(
                select(SavedJob).where(SavedJob.user_id == current_user.id)
            ).all()
        )
        apps = session.exec(
            select(ApplicationTracker).where(
                ApplicationTracker.user_id == current_user.id,
                ApplicationTracker.is_deleted == False,  # noqa: E712
            )
        ).all()
        app_status_counts: Dict[str, int] = {}
        for a in apps:
            app_status_counts[a.status] = app_status_counts.get(a.status, 0) + 1

        upcoming_interviews = session.exec(
            select(InterviewRound)
            .where(InterviewRound.user_id == current_user.id)
            .order_by(InterviewRound.scheduled_at.asc())
        ).all()
        cv_versions_count = len(
            session.exec(
                select(CVVersion).where(CVVersion.user_id == current_user.id)
            ).all()
        )

    applied_count = sum(
        v for k, v in app_status_counts.items()
        if k in ("APPLIED", "HR_SCREEN", "TECH_INTERVIEW", "FINAL_ROUND", "OFFER", "Applied", "Interviewing", "Technical Interview", "Offer")
    )
    interview_count = sum(
        v for k, v in app_status_counts.items()
        if k in ("HR_SCREEN", "TECH_INTERVIEW", "FINAL_ROUND", "OFFER", "Interviewing", "Technical Interview", "Offer")
    )
    offer_count = sum(v for k, v in app_status_counts.items() if k in ("OFFER", "Offer"))

    return {
        "profile_uploaded": _is_profile_uploaded_for_user(profile, current_user.email),
        "completeness_score": completeness_pct,
        "missing_fields": missing_fields,
        "detected_industry": ps.get("detected_industry") or "Not detected yet",
        "primary_role": ps.get("primary_role") or (cand.get("headline") or ""),
        "matching_jobs_count": len(matching_jobs),
        "remote_b2b_matches_count": remote_b2b_count,
        "local_georgia_matches_count": local_ge_count,
        "ready_to_apply_count": ready_to_apply,
        "tier_breakdown": tier_counts,
        "saved_jobs_count": saved_count,
        "active_applications_count": len(apps),
        "applied_count": applied_count,
        "interviews_count": interview_count,
        "offers_count": offer_count,
        "cv_versions_count": cv_versions_count,
        "response_rate_pct": round((interview_count / applied_count) * 100.0, 1) if applied_count > 0 else 0.0,
        "applications_by_status": app_status_counts,
        "upcoming_interviews": [
            {
                "id": ir.id,
                "application_id": ir.application_id,
                "round_type": ir.round_type,
                "scheduled_at": ir.scheduled_at.isoformat() if ir.scheduled_at else None,
                "interviewer": ir.interviewer,
            }
            for ir in upcoming_interviews[:5]
        ],
    }
