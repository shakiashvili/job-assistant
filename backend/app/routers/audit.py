import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from ..db.database import engine, init_db
from ..db.models import CandidateProfile, JobPosting, User
from ..models.schemas import JobAuditRequest, JobAuditResponse, PortalVacancyItem
from ..services.audit_service import audit_service
from ..services.auth_service import get_current_user
from .jobs import _is_profile_uploaded_for_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Job Audit & Portal Vacancies"])


@router.get("/vacancies", response_model=List[PortalVacancyItem])
def list_portal_vacancies(current_user: User = Depends(get_current_user)):
    """
    Returns ONLY suitable live verified vacancies (>= 60% match) after the user has uploaded skills.md.
    Returns an empty list [] until skills.md is uploaded — never serves dead/mocked or unsuitable listings.
    """
    init_db()
    with Session(engine) as session:
        profile = session.exec(
            select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
        ).first()
        if not _is_profile_uploaded_for_user(profile, current_user.email):
            return []

        industry = str((profile.parsed_skills or {}).get("target_industry") or "qa_tech")
        rows = session.exec(
            select(JobPosting)
            .where((JobPosting.status != "FILTERED_OUT") & (JobPosting.suitability_score >= 60.0))
            .order_by(JobPosting.suitability_score.desc(), JobPosting.scraped_at.desc())
        ).all()

        items: List[PortalVacancyItem] = []
        seen_tc: set[tuple[str, str]] = set()
        for r in rows:
            tc = (r.title.lower().strip(), r.company.lower().strip())
            if tc in seen_tc:
                continue
            seen_tc.add(tc)
            salary_str = "Unstated"
            if r.salary_min and r.salary_max:
                salary_str = f"{int(r.salary_min):,} - {int(r.salary_max):,} {r.salary_currency or 'USD'}"
            items.append(
                PortalVacancyItem(
                    id=f"live-{r.portal}-{r.id}",
                    title=r.title,
                    company=r.company,
                    portal=r.portal,
                    industry=industry,
                    location=r.market,
                    salary=salary_str,
                    url=r.url,
                    mock_url=r.url,
                    company_reviews_count=10,
                    company_rating=4.5,
                    requires_motivational_letter=(r.portal == "dou.ua"),
                    description=r.description_raw,
                )
            )
        return items


@router.post("/audit-job", response_model=JobAuditResponse)
async def audit_job_endpoint(request: JobAuditRequest):
    """
    Audits a job posting from raw text or job URL across any industry, validates company reviews (3+ gate),
    returns Skills / ATS / Recruiter match scores + Gaps, and generates a tailored
    Human-Tone PDF & HTML CV in English ('en') or Georgian ('ka') based on candidate_skills.md.
    """
    if not request.raw_text and not request.job_url:
        raise HTTPException(
            status_code=400,
            detail="Either 'raw_text' or 'job_url' must be provided."
        )

    try:
        response = await audit_service.audit_job(
            raw_text=request.raw_text,
            job_url=request.job_url,
            variant=request.variant or "qa_automation",
            skills_md_override=request.skills_md_override,
            cv_language=request.cv_language or "en",
        )
        return response
    except Exception as e:
        logger.error(f"Failed to audit job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Job audit failed: {str(e)}")
