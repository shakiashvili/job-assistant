import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlmodel import Session, select
from ..database import engine, init_db
from ..models.db_models import CandidateProfile, JobPosting
from ..storage.ground_truth_store import ground_truth_store
from ..services.scrapers.scraper_orchestrator import scraper_orchestrator
from ..services.salary_service import salary_service
from ..services.matcher_service import matcher_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Database Profile, Scrapers & Market Intelligence"])


class ScrapeRequest(BaseModel):
    portals: Optional[List[str]] = None  # ["jobs.ge", "hr.ge", "dou.ua", "djinni.co"]
    allow_network: bool = False


class SalaryEstimateRequest(BaseModel):
    title: str
    description: str
    market: str = "INT_REMOTE"
    portal: str = "generic"


@router.post("/profile/upload-skills")
async def upload_skills_profile(
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None),
):
    """
    Accepts a .md or .txt file upload (e.g., skills.md) or markdown form content,
    parses QA/SDET technical capabilities (Automation, Languages, API & Performance, CI/CD & DevOps)
    via Gemini 2.5 Flash + taxonomy parser, and persists it into CandidateProfile in the SQL database.
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

        # Re-evaluate all existing JobPosting records in DB against the new CandidateProfile
        with Session(engine) as session:
            jobs = session.exec(select(JobPosting)).all()
            for job in jobs:
                score, new_status, rationale, _, _ = matcher_service.evaluate_job(
                    title=job.title,
                    description=job.description_raw,
                    parsed_skills=profile.parsed_skills,
                    current_status=job.status,
                    existing_rationale=job.match_rationale,
                )
                job.suitability_score = score
                job.status = new_status
                job.match_rationale = rationale
                session.add(job)
            session.commit()

        clean_taxonomy = {
            k: v for k, v in profile.parsed_skills.items() if k != "ground_truth_vault"
        }
        return {
            "status": "success",
            "id": profile.id,
            "filename": filename,
            "raw_markdown": profile.raw_markdown,
            "parsed_skills": clean_taxonomy,
            "updated_at": profile.updated_at.isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to ingest skills.md into CandidateProfile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile")
def get_candidate_profile_db():
    """Returns the current CandidateProfile record from the relational database."""
    profile = ground_truth_store.get_profile_record()
    clean_taxonomy = {
        k: v for k, v in profile.parsed_skills.items() if k != "ground_truth_vault"
    }
    return {
        "id": profile.id,
        "raw_markdown": profile.raw_markdown,
        "parsed_skills": clean_taxonomy,
        "updated_at": profile.updated_at.isoformat(),
    }


@router.post("/jobs/scrape")
async def trigger_multi_portal_scrape(request: Optional[ScrapeRequest] = None):
    """
    Runs the multi-portal scraper engine across Jobs.ge, HR.ge, DOU.ua, and Djinni.co:
    - Enforces Remote & Strict English-only Language Gate (marks Ukrainian/Russian required roles as FILTERED_OUT).
    - Extracts or AI-estimates salary ranges (salary_estimated_by_ai).
    - Computes suitability_score (0-100%) and auto-promotes >= 75% matches to STAGED.
    """
    portals = request.portals if request else None
    allow_net = request.allow_network if request else False
    return await scraper_orchestrator.run_scrapers(portals=portals, allow_network=allow_net)


@router.get("/jobs")
async def list_scraped_jobs(
    portal: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None),
) -> List[Dict[str, Any]]:
    """Lists JobPosting records from the relational database, auto-seeding if empty."""
    init_db()
    with Session(engine) as session:
        count = len(session.exec(select(JobPosting)).all())
    if count < 4:
        await scraper_orchestrator.run_scrapers(allow_network=False)

    with Session(engine) as session:
        stmt = select(JobPosting).order_by(JobPosting.suitability_score.desc(), JobPosting.scraped_at.desc())
        rows = session.exec(stmt).all()
        filtered = []
        for r in rows:
            if portal and r.portal != portal:
                continue
            if market and r.market != market:
                continue
            if status and r.status != status:
                continue
            if min_score is not None and r.suitability_score < min_score:
                continue
            filtered.append(r.model_dump(mode="json"))
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
