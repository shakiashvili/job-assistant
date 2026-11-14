import asyncio
import logging
import math
import re as _re
import uuid
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
from pydantic import BaseModel
from sqlalchemy import func, case
from sqlmodel import Session, select, or_

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
from ..services.auth_service import get_current_user
from ..services.scrapers.scraper_orchestrator import scraper_orchestrator
from ..services.scrapers.base_scraper import sanitize_company_name
from ..services.salary_service import salary_service
from ..services.backup_service import backup_service
from .ground_truth import _purge_stale_unapplied_jobs, MAX_UPLOAD_SIZE_BYTES, record_candidate_document
from ..config import GENERATED_RESUMES_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Database Profile, Scrapers & Market Intelligence"])


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
    owner = ps.get("owner_email")
    if owner and user_email != "guest@talentflow.local" and owner != user_email:
        return False
    return True


@router.post("/profile/upload-skills")
async def upload_skills_profile(
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None),
    run_live_scrape: bool = Form(True),
    current_user: User = Depends(get_current_user),
):
    """
    Accepts a .md or .txt file upload (e.g., skills.md) or markdown form content,
    validates upload size, extracts role & technical capabilities into the user's CandidateProfile,
    purges stale unapplied matches for this user, and scrapes live role-matching vacancies.
    """
    md_text = ""
    filename = "skills.md"
    if file is not None:
        filename = file.filename or "skills.md"
        raw_bytes = await file.read()
        if len(raw_bytes) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        if len(raw_bytes) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="Uploaded file exceeds 10 MB maximum size limit.")
        md_text = raw_bytes.decode("utf-8", errors="replace")
    elif content is not None:
        if len(content.encode("utf-8")) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="Content exceeds 10 MB maximum size limit.")
        md_text = content
    else:
        raise HTTPException(status_code=400, detail="Provide a .md/.txt file upload or 'content' field.")

    try:
        owner = current_user.email if current_user.email != "guest@talentflow.local" else None
        profile: CandidateProfile = ground_truth_store.ingest_skills_markdown(
            md_text,
            owner_email=owner,
            user_id=current_user.id,
        )

        with Session(engine) as session:
            db_prof = session.get(CandidateProfile, profile.id)
            if db_prof:
                skills_copy = dict(db_prof.parsed_skills or {})
                skills_copy["user_uploaded"] = True
                if owner:
                    skills_copy["owner_email"] = owner
                if current_user.id is not None:
                    skills_copy["user_id"] = current_user.id
                    db_prof.user_id = current_user.id
                db_prof.parsed_skills = skills_copy
                session.add(db_prof)
                session.commit()
                session.refresh(db_prof)
                profile = db_prof

        _purge_stale_unapplied_jobs(user=current_user)

        scrape_summary: Optional[Dict[str, Any]] = None
        if run_live_scrape:
            try:
                scrape_summary = await scraper_orchestrator.run_scrapers(
                    allow_network=True,
                    owner_email=owner,
                    user_id=current_user.id,
                )
            except Exception as sc_err:
                logger.warning(f"Post-upload live scrape skipped/partial: {sc_err}")

        clean_taxonomy = {
            k: v for k, v in (profile.parsed_skills or {}).items() if k != "ground_truth_vault"
        }
        return {
            "status": "success",
            "id": profile.id,
            "full_name": profile.full_name,
            "experience_years": profile.experience_years,
            "profile_uploaded": True,
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
        raise HTTPException(status_code=500, detail=str(e))


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


async def _run_background_scrape_task(
    task_id: str,
    portals: Optional[List[str]],
    allow_network: bool,
    owner_email: Optional[str],
    user_id: Optional[int],
) -> None:
    try:
        res = await scraper_orchestrator.run_scrapers(
            portals=portals,
            allow_network=allow_network,
            owner_email=owner_email,
            user_id=user_id,
        )
        with Session(engine) as session:
            t_row = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == task_id)).first()
            if t_row:
                t_row.status = "COMPLETED"
                t_row.progress_pct = 100
                t_row.result_summary = {
                    "total_processed": int(res.get("total_processed") or 0),
                    "staged_ready_count": int(res.get("staged_ready_count") or 0),
                    "filtered_out_count": int(res.get("filtered_out_count") or 0),
                }
                t_row.completed_at = utc_now()
                session.add(t_row)
                session.commit()
    except Exception as exc:
        logger.error(f"Background scrape task {task_id} failed: {exc}")
        with Session(engine) as session:
            t_row = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == task_id)).first()
            if t_row:
                t_row.status = "FAILED"
                t_row.error_message = str(exc)
                t_row.completed_at = utc_now()
                session.add(t_row)
                session.commit()


@router.post("/jobs/scrape/async")
async def trigger_async_scrape(
    request: Optional[ScrapeRequest] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Launches a non-blocking background scrape task with per-user duplicate run deduplication.
    Returns a task_id that can be polled via GET /api/jobs/scrape/status/{task_id}.
    """
    init_db()
    portals = request.portals if request else None
    allow_net = request.allow_network if request else True
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None

    with Session(engine) as session:
        existing_running = session.exec(
            select(ScrapeTask).where(
                ScrapeTask.user_id == current_user.id,
                ScrapeTask.status == "RUNNING",
            )
        ).first()
        if existing_running:
            return {
                "task_id": existing_running.task_id,
                "status": existing_running.status,
                "deduplicated": True,
                "message": "An active scrape task is already running for your account.",
            }

        task_id = f"scrape-{uuid.uuid4().hex[:10]}"
        task_row = ScrapeTask(
            task_id=task_id,
            user_id=current_user.id,
            status="RUNNING",
            portals=portals or scraper_orchestrator.DEFAULT_PORTALS,
            progress_pct=10,
        )
        session.add(task_row)
        session.commit()

    if not allow_net:
        await _run_background_scrape_task(task_id, portals, False, owner, current_user.id)
    else:
        asyncio.create_task(
            _run_background_scrape_task(task_id, portals, allow_net, owner, current_user.id)
        )

    with Session(engine) as session:
        t_now = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == task_id)).first()
        return {
            "task_id": task_id,
            "status": t_now.status if t_now else "RUNNING",
            "deduplicated": False,
        }


@router.get("/jobs/scrape/status/{task_id}")
def get_scrape_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """Returns progress and completion metrics for a background scrape task."""
    with Session(engine) as session:
        t_row = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == task_id)).first()
        if not t_row:
            raise HTTPException(status_code=404, detail=f"Scrape task {task_id} not found.")
        if t_row.user_id is not None and current_user.email != "guest@talentflow.local" and t_row.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden: scrape task belongs to another user.")
        summary = t_row.result_summary or {}
        return {
            "task_id": t_row.task_id,
            "status": t_row.status,
            "portals": t_row.portals,
            "progress_pct": t_row.progress_pct,
            "total_processed": summary.get("total_processed", 0),
            "staged_count": summary.get("staged_ready_count", 0),
            "filtered_out_count": summary.get("filtered_out_count", 0),
            "error_message": t_row.error_message,
            "created_at": t_row.created_at.isoformat() if t_row.created_at else None,
            "completed_at": t_row.completed_at.isoformat() if t_row.completed_at else None,
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
    search: Optional[str] = Query(None, description="Keyword search across title, company, description"),
    country: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    remote_type: Optional[str] = Query(None, description="REMOTE, HYBRID, or ONSITE"),
    salary_min: Optional[float] = Query(None),
    language: Optional[str] = Query(None),
    technology: Optional[str] = Query(None),
    only_new: bool = Query(False, description="Exclude jobs already applied to or saved"),
    only_saved: bool = Query(False, description="Only return jobs bookmarked by current user"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Lists suitable JobPosting records with SQL-backed filtering, single-query conditional aggregation
    for tier/status counts, and server-side pagination.
    """
    init_db()
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
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

        base_conds = []
        if not include_filtered:
            base_conds.append(JobPosting.status != "FILTERED_OUT")
        if portal and portal.upper() != "ALL":
            base_conds.append(JobPosting.portal == portal)
        if market and market.upper() != "ALL":
            base_conds.append(JobPosting.market == market)
        if min_score is not None and min_score > 0:
            base_conds.append(JobPosting.suitability_score >= min_score)
        if search and search.strip():
            kw = f"%{search.strip()}%"
            base_conds.append(
                or_(
                    JobPosting.title.ilike(kw),
                    JobPosting.company.ilike(kw),
                    JobPosting.description_raw.ilike(kw),
                )
            )
        if country and country.strip():
            base_conds.append(JobPosting.market.ilike(f"%{country.strip()}%"))
        if city and city.strip():
            base_conds.append(JobPosting.market.ilike(f"%{city.strip()}%"))
        if remote_type and remote_type.upper() != "ALL":
            rt_up = remote_type.strip().upper()
            if rt_up == "REMOTE":
                base_conds.append(JobPosting.is_remote == True)  # noqa: E712
            else:
                base_conds.append(JobPosting.remote_type == rt_up)
        if salary_min is not None and salary_min > 0:
            base_conds.append(JobPosting.salary_max >= salary_min)
        if technology and technology.strip():
            tkw = f"%{technology.strip()}%"
            base_conds.append(
                or_(
                    JobPosting.title.ilike(tkw),
                    JobPosting.description_raw.ilike(tkw),
                )
            )
        if language and language.strip():
            lkw = f"%{language.strip()}%"
            base_conds.append(JobPosting.description_raw.ilike(lkw))
        if only_saved and current_user.id is not None:
            saved_sub = select(SavedJob.job_posting_id).where(SavedJob.user_id == current_user.id)
            base_conds.append(JobPosting.id.in_(saved_sub))
        if only_new and current_user.id is not None:
            applied_sub = select(ApplicationRecord.job_posting_id).where(
                ApplicationRecord.user_id == current_user.id,
                ApplicationRecord.job_posting_id.is_not(None),
            )
            base_conds.append(JobPosting.id.not_in(applied_sub))

        # Single conditional-aggregation SQL query replacing 6 separate COUNT(*) queries!
        agg_stmt = select(
            func.count().label("all_cnt"),
            func.sum(case((JobPosting.match_tier == "DIRECT", 1), else_=0)).label("direct_cnt"),
            func.sum(case((JobPosting.match_tier == "ADJACENT", 1), else_=0)).label("adjacent_cnt"),
            func.sum(
                case(
                    ((JobPosting.match_tier == "PUBLIC_INTERNSHIP") | (JobPosting.portal == "hr.gov.ge"), 1),
                    else_=0,
                )
            ).label("intern_cnt"),
            func.sum(case((JobPosting.status == "STAGED", 1), else_=0)).label("staged_cnt"),
            func.sum(case((JobPosting.status == "AUDITED", 1), else_=0)).label("audited_cnt"),
        ).select_from(JobPosting)
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
            conditions.append(JobPosting.status == status)
            has_extra_filter = True
        if tier and tier.upper() != "ALL":
            t_low = tier.strip().lower()
            has_extra_filter = True
            if t_low == "direct":
                conditions.append(JobPosting.match_tier == "DIRECT")
            elif t_low == "adjacent":
                conditions.append(JobPosting.match_tier == "ADJACENT")
            elif t_low in ("internship", "public_internship"):
                conditions.append((JobPosting.match_tier == "PUBLIC_INTERNSHIP") | (JobPosting.portal == "hr.gov.ge"))

        if has_extra_filter:
            count_stmt = select(func.count()).select_from(JobPosting).where(*conditions)
            total = int(session.exec(count_stmt).one() or 0)
        else:
            total = all_cnt

        total_pages = max(1, math.ceil(total / limit))

        stmt = select(JobPosting)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = (
            stmt.order_by(JobPosting.suitability_score.desc(), JobPosting.scraped_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = session.exec(stmt).all()

        items: List[Dict[str, Any]] = []
        for r in rows:
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
                clean_t = _re.sub(r"🔥+", "", raw_t)
                clean_t = _re.sub(r"\bResponds Quickly\b.*$", "", clean_t, flags=_re.I)
                clean_t = _re.sub(r"\s+(?:up\s+to|to|from)\s+[\$€£]\s*\d[\d,]*.*$", "", clean_t, flags=_re.I)
                if dumped.get("company") and len(dumped["company"]) > 2:
                    ci = clean_t.find(f" {dumped['company']}")
                    if ci > 4:
                        clean_t = clean_t[:ci]
                dumped["title"] = _re.sub(r"\s+", " ", clean_t).strip() or raw_t
                if dumped.get("salary_min") is None:
                    sal_ex = salary_service.extract_explicit_salary(f"{raw_t}\n{dumped.get('description_raw', '')}")
                    if sal_ex:
                        dumped["salary_min"], dumped["salary_max"], dumped["salary_currency"] = sal_ex
                        dumped["salary_is_estimated"] = False
                        dumped["salary_estimated_by_ai"] = False
            items.append(dumped)

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "tier_counts": tier_counts,
            "status_counts": status_counts,
        }


@router.post("/jobs/{job_id}/save")
def save_job_bookmark(
    job_id: int,
    notes: str = "",
    current_user: User = Depends(get_current_user),
):
    """Bookmarks a job posting for the current user."""
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
            return {"status": "saved", "id": existing.id, "job_id": job_id}
        sj = SavedJob(user_id=current_user.id, job_posting_id=job_id, notes=notes)
        session.add(sj)
        session.commit()
        session.refresh(sj)
        return {"status": "saved", "id": sj.id, "job_id": job_id}


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
def create_database_backup(current_user: User = Depends(get_current_user)):
    """Creates a hot atomic SQLite database backup with SHA-256 verification."""
    return backup_service.create_backup(reason="api")


@router.get("/admin/backups")
def list_database_backups(current_user: User = Depends(get_current_user)):
    """Lists available database backup snapshots."""
    return {"backups": backup_service.list_backups()}


@router.post("/salary/estimate")
def estimate_job_salary(req: SalaryEstimateRequest):
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
        )

        if pkg.get("cv_filename"):
            record_candidate_document(
                user_id=current_user.id,
                filename=pkg["cv_filename"],
                file_path=GENERATED_RESUMES_DIR / pkg["cv_filename"],
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
