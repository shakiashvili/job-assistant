import asyncio
import logging
import re as _re
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session, select

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
    User,
)
from ..db.profile_repository import ground_truth_store
from ..services.auth_service import get_current_user, get_current_admin
from ..services.scrapers.scraper_orchestrator import scraper_orchestrator
from ..services.scrapers.base_scraper import classify_georgia_b2b_suitability
from ..services.job_query_service import JobFilters, query_jobs_paginated
from ..services.salary_service import salary_service
from ..services.backup_service import backup_service
from ..services.scrape_worker import (
    SCRAPE_WORKER_MODE,
    execute_scrape_task,
    recover_stale_scrape_tasks,
    scrape_queue,
)
from ..services.upload_utils import read_upload_bounded
from .ground_truth import MAX_UPLOAD_SIZE_BYTES, record_candidate_document
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
    """Returns True when the user has EITHER an uploaded CV/skills file OR a ready manually completed profile."""
    if not profile:
        return False
    ps = profile.parsed_skills or {}
    owner = str(ps.get("owner_email") or "").strip().lower()
    clean_user = (user_email or "").strip().lower()
    if owner and clean_user != owner:
        return False
    if bool(ps.get("user_uploaded", False)) or str(ps.get("profile_status") or "").lower() == "ready":
        return True
    vault = ps.get("ground_truth_vault") if isinstance(ps.get("ground_truth_vault"), dict) else {}
    return bool(
        (ps.get("all_skills") or [])
        or (vault.get("work_history") or [])
        or (vault.get("education") or [])
    )


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


@router.post("/jobs/scrape/async")
async def trigger_async_scrape(
    request: Optional[ScrapeRequest] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Enqueues a durable DB-backed background scrape task with stale-task recovery,
    heartbeats, execution timeouts, and per-user duplicate run deduplication.
    Requires an uploaded CV/skills profile when allow_network=True.
    """
    portals = request.portals if request else None
    allow_net = request.allow_network if request else True
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    if allow_net:
        prof = ground_truth_store.get_profile_record(owner_email=owner, user_id=current_user.id)
        if not _is_profile_uploaded_for_user(prof, current_user.email) and not (prof and (prof.raw_markdown or "").strip()):
            raise HTTPException(
                status_code=400,
                detail="Please upload your CV or skills file in Profile Vault first so TalentFlow targets roles matching your real skills and experience.",
            )

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


@router.get('/jobs')
def list_scraped_jobs(
    filters: JobFilters = Depends(),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return query_jobs_paginated(filters, current_user, _is_profile_uploaded_for_user)


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


@router.get("/jobs/saved")
def list_saved_job_bookmarks(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Lists all bookmarked jobs for the current authenticated user."""
    with Session(engine) as session:
        rows = session.exec(
            select(SavedJob, JobPosting)
            .join(JobPosting, SavedJob.job_posting_id == JobPosting.id)
            .where(SavedJob.user_id == current_user.id)
            .order_by(SavedJob.created_at.desc())
        ).all()
        items = [
            {
                "saved_id": sj.id,
                "notes": sj.notes or "",
                "saved_at": sj.created_at.isoformat() if sj.created_at else "",
                "job": {
                    "id": job.id,
                    "portal": job.portal,
                    "external_id": job.external_id,
                    "title": job.title,
                    "company": job.company,
                    "url": job.url,
                    "market": job.market,
                    "is_remote": job.is_remote,
                    "suitability_score": job.suitability_score,
                    "status": job.status,
                },
            }
            for sj, job in rows
        ]
        return {"items": items}


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


class JobFeedbackRequest(BaseModel):
    action: str = Field(default="dismiss", description="'dismiss', 'irrelevant', or 'restore'")
    reason: Optional[str] = Field(
        default=None,
        description="irrelevant_role, too_senior, wrong_location, low_salary, already_applied, not_interested",
    )
    note: Optional[str] = None


@router.post("/jobs/{job_id}/feedback")
def submit_job_feedback(
    job_id: int,
    payload: JobFeedbackRequest,
    current_user: User = Depends(get_current_user),
):
    """Records per-user relevance feedback / dismissal without mutating the candidate's verified profile."""
    from ..db.models import UserJobMatch, utc_now

    with Session(engine) as session:
        job = session.get(JobPosting, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job posting not found.")
        um = session.exec(
            select(UserJobMatch).where(
                UserJobMatch.user_id == current_user.id,
                UserJobMatch.job_posting_id == job_id,
            )
        ).first()
        if not um:
            um = UserJobMatch(
                user_id=current_user.id,
                job_posting_id=job_id,
                suitability_score=0.0,
                match_score=0.0,
                match_tier=job.match_tier or "DIRECT",
                status="IGNORED",
            )
        act = (payload.action or "dismiss").strip().lower()
        mb = dict(um.match_breakdown or {})
        if act == "restore":
            um.is_ignored = False
            if um.status == "IGNORED":
                um.status = "STAGED"
            mb.pop("dismiss_reason", None)
            mb.pop("dismiss_note", None)
        else:
            um.is_ignored = True
            um.status = "IGNORED"
            mb["dismiss_reason"] = (payload.reason or "not_interested").strip().lower()
            if payload.note:
                mb["dismiss_note"] = payload.note.strip()[:400]
            mb["feedback_at"] = utc_now().isoformat()
        um.match_breakdown = mb
        session.add(um)
        session.commit()
        return {
            "status": "restored" if act == "restore" else "dismissed",
            "job_id": job_id,
            "is_ignored": um.is_ignored,
            "reason": mb.get("dismiss_reason"),
        }


@router.delete("/jobs/{job_id}/feedback")
def clear_job_feedback(
    job_id: int,
    current_user: User = Depends(get_current_user),
):
    """Restores a previously dismissed vacancy back into the user's feed."""
    return submit_job_feedback(
        job_id=job_id,
        payload=JobFeedbackRequest(action="restore"),
        current_user=current_user,
    )


def _to_saved_search_out(r: SavedSearch) -> SavedSearchOut:
    return SavedSearchOut(
        id=r.id,
        user_id=r.user_id,
        name=r.name,
        filters=r.filters or {},
        notify_on_new=r.notify_on_new,
        last_run_at=r.last_run_at.isoformat() if r.last_run_at else None,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


def _to_notification_out(r: Notification) -> NotificationOut:
    return NotificationOut(
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


@router.get("/saved-searches", response_model=List[SavedSearchOut])
def list_saved_searches(current_user: User = Depends(get_current_user)):
    """Lists saved search filters for the current user."""
    with Session(engine) as session:
        rows = session.exec(
            select(SavedSearch)
            .where(SavedSearch.user_id == current_user.id)
            .order_by(SavedSearch.created_at.desc())
        ).all()
        return [_to_saved_search_out(r) for r in rows]


@router.post("/saved-searches", response_model=SavedSearchOut)
def create_saved_search(
    req: SavedSearchCreate,
    current_user: User = Depends(get_current_user),
):
    """Creates a saved search filter and alert rule for the current user."""
    with Session(engine) as session:
        row = SavedSearch(user_id=current_user.id, name=req.name, filters=req.filters, notify_on_new=req.notify_on_new)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_saved_search_out(row)


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
        return [_to_notification_out(r) for r in rows]


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
        return _to_notification_out(row)


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
