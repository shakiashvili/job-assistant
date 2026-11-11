import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from ..database import engine, init_db, delete_job_posting_cascade
from ..models.db_models import CandidateProfile, JobPosting, User
from ..storage.ground_truth_store import ground_truth_store
from ..services.auth_service import get_current_user
from ..services.scrapers.scraper_orchestrator import scraper_orchestrator
from ..services.salary_service import salary_service
from ..services.matcher_service import matcher_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Database Profile, Scrapers & Market Intelligence"])


class ScrapeRequest(BaseModel):
    portals: Optional[List[str]] = None  # ["jobs.ge", "hr.ge", "dou.ua", "djinni.co"]
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
    extracts role & technical capabilities into CandidateProfile, purges stale off-domain rows,
    and dynamically scrapes live role-matching suitable vacancies across portals.
    """
    md_text = ""
    filename = "skills.md"
    if file is not None:
        filename = file.filename or "skills.md"
        raw_bytes = await file.read()
        md_text = raw_bytes.decode("utf-8", errors="replace")
    elif content is not None:
        md_text = content
    else:
        raise HTTPException(status_code=400, detail="Provide a .md/.txt file upload or 'content' field.")

    try:
        profile: CandidateProfile = ground_truth_store.ingest_skills_markdown(md_text)

        # Stamp ownership and clear old unapplied vacancies so ONLY suitable matches for this skills.md remain
        with Session(engine) as session:
            db_prof = session.get(CandidateProfile, profile.id)
            if db_prof:
                skills_copy = dict(db_prof.parsed_skills or {})
                skills_copy["user_uploaded"] = True
                if current_user.email != "guest@talentflow.local":
                    skills_copy["owner_email"] = current_user.email
                db_prof.parsed_skills = skills_copy
                session.add(db_prof)
            jobs = session.exec(select(JobPosting)).all()
            for job in jobs:
                if job.status != "APPLIED":
                    delete_job_posting_cascade(session, job)
            session.commit()
            if db_prof:
                session.refresh(db_prof)
                profile = db_prof

        scrape_summary: Optional[Dict[str, Any]] = None
        if run_live_scrape:
            try:
                scrape_summary = await scraper_orchestrator.run_scrapers(allow_network=True)
            except Exception as sc_err:
                logger.warning(f"Post-upload live scrape skipped/partial: {sc_err}")

        clean_taxonomy = {
            k: v for k, v in profile.parsed_skills.items() if k != "ground_truth_vault"
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
    except Exception as e:
        logger.error(f"Failed to ingest skills.md into CandidateProfile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile")
def get_candidate_profile_db(current_user: User = Depends(get_current_user)):
    """Returns the current CandidateProfile record from the relational database."""
    profile = ground_truth_store.get_profile_record()
    uploaded = _is_profile_uploaded_for_user(profile, current_user.email)
    clean_taxonomy = {
        k: v for k, v in profile.parsed_skills.items() if k != "ground_truth_vault"
    }
    return {
        "id": profile.id,
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "location": profile.location,
        "github_url": profile.github_url,
        "linkedin_url": profile.linkedin_url,
        "experience_years": profile.experience_years,
        "profile_uploaded": uploaded,
        "raw_markdown": profile.raw_markdown if uploaded else "",
        "parsed_skills": clean_taxonomy if uploaded else {},
        "updated_at": profile.updated_at.isoformat(),
    }


@router.post("/jobs/scrape")
async def trigger_multi_portal_scrape(request: Optional[ScrapeRequest] = None):
    """
    Runs the live multi-portal scraper engine across Jobs.ge, HR.ge, DOU.ua, and Djinni.co:
    - Uses target role & search queries from uploaded CandidateProfile (skills.md).
    - Enforces Live HTTP GET content health check (rejects blank 200 OK pages).
    - Enforces Domain, Seniority, Suitability (>=60%), Remote & Strict English-only Language Gates.
    """
    portals = request.portals if request else None
    allow_net = request.allow_network if request else True
    return await scraper_orchestrator.run_scrapers(portals=portals, allow_network=allow_net)


@router.get("/jobs")
async def list_scraped_jobs(
    portal: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    min_score: Optional[float] = Query(60.0, description="Minimum suitability score threshold (default 60% so only suitable vacancies return)."),
    include_filtered: bool = Query(False, description="Include FILTERED_OUT (blocked/disqualified) jobs. Hidden by default."),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Lists ONLY suitable JobPosting records matching the candidate's uploaded skills.md profile.
    Returns an empty list until the candidate uploads skills.md.
    """
    init_db()
    with Session(engine) as session:
        profile = session.exec(
            select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
        ).first()
        if not _is_profile_uploaded_for_user(profile, current_user.email):
            return []

        stmt = select(JobPosting).order_by(JobPosting.suitability_score.desc(), JobPosting.scraped_at.desc())
        rows = session.exec(stmt).all()
        from ..services.scrapers.base_scraper import sanitize_company_name
        filtered = []
        for r in rows:
            if not include_filtered and r.status == "FILTERED_OUT":
                continue
            if portal and r.portal != portal:
                continue
            if market and r.market != market:
                continue
            if status and r.status != status:
                continue
            if min_score is not None and r.suitability_score < min_score:
                continue
            dumped = r.model_dump(mode="json")
            dumped["company"] = sanitize_company_name(dumped.get("company"), target_email=dumped.get("target_email"), fallback="კომპანია")
            filtered.append(dumped)
        return filtered


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
    current_user: User = Depends(get_current_user),
):
    """
    Prepares a complete tailored Word (.docx) CV + Cover Letter + clean Subject line
    for drafting an application email to a vacancy (e.g. from Jobs.ge / HR.ge).
    """
    from ..services.cv_generator_service import cv_generator_service

    init_db()
    with Session(engine) as session:
        job = session.get(JobPosting, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Vacancy not found")

        return cv_generator_service.prepare_email_application_package(
            job_title=job.title,
            company=job.company,
            description=job.description_raw,
            portal=job.portal,
            target_email=job.target_email,
            email_subject_template=job.email_subject,
            cv_language=cv_language,
            cv_style="tailored",
        )
