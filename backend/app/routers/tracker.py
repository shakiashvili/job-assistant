import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..db.database import get_session, engine
from ..db.models import User, ApplicationTracker, ApplicationRecord, JobPosting, InterviewRound
from ..models.schemas import ApplicationItem, ApplicationCreate, ApplicationUpdate
from ..services.auth_service import get_current_user
from ..services.gmail_service import gmail_service
from ..services.interview_service import interview_service
from ..db.tracker_repository import tracker_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/applications", tags=["Application Tracker & Interview Copilot"])


class SendEmailRequest(BaseModel):
    recipient_email: Optional[str] = None
    subject: Optional[str] = None
    body_text: Optional[str] = None
    mode: str = Field(default="draft", description="'draft' (saves to Gmail) or 'send' (dispatches immediately)")


class PrepareInterviewRequest(BaseModel):
    round_type: str = Field(default="HR_SCREEN", description="HR_SCREEN, TECH_INTERVIEW, FINAL_ROUND, SYSTEM_DESIGN")


class UpdateInterviewNotesRequest(BaseModel):
    candidate_notes: Optional[str] = None
    status: Optional[str] = None


def get_or_create_app_tracker(app_id_str: str, session: Session) -> ApplicationTracker:
    clean_id = app_id_str.replace("app-", "")
    app_id = int(clean_id) if clean_id.isdigit() else 1

    app_tracker = session.get(ApplicationTracker, app_id)
    if not app_tracker:
        rec = session.get(ApplicationRecord, app_id)
        job = session.get(JobPosting, rec.job_posting_id) if rec and rec.job_posting_id else None
        app_tracker = ApplicationTracker(
            id=app_id,
            company_name=job.company if job else "Hiring Company",
            job_title=job.title if job else "QA Engineer",
            job_url=job.url if job else None,
            portal=job.portal if job else "custom",
            status=rec.submission_status if rec else "STAGED",
            cv_pdf_path=rec.custom_cv_path if rec else None,
            cover_letter_text=rec.cover_letter_text if rec else None,
            is_deleted=False,
        )
        session.add(app_tracker)
        session.commit()
        session.refresh(app_tracker)
    return app_tracker


@router.get("", response_model=List[ApplicationItem])
def list_applications():
    """Lists all tracked applications (Saved, Applied, Interviewing, Rejected)."""
    return tracker_store.get_all()


@router.post("", response_model=ApplicationItem)
def create_application(item: ApplicationCreate):
    """Adds a new application to the tracker board."""
    try:
        return tracker_store.create(item)
    except Exception as e:
        logger.error(f"Error creating application: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{app_id}", response_model=ApplicationItem)
def update_application(app_id: str, item_update: ApplicationUpdate):
    """Updates status, notes, or details for an application."""
    updated = tracker_store.update(app_id, item_update)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return updated


@router.delete("/{app_id}")
def delete_application(app_id: str, hard: bool = Query(False, description="Permanent hard delete if true")):
    """Removes or soft-deletes an application from tracking."""
    deleted = tracker_store.delete(app_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return {"status": "success", "message": f"Application {app_id} deleted"}


@router.post("/{app_id}/send-email")
def send_or_draft_application_email(
    app_id: str,
    req: SendEmailRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Builds an RFC 2822 MIME email package containing recipient HR email, custom subject line,
    cover letter body, and generated PDF resume attachment.
    Dispatches directly to user's connected Gmail account as a Draft or sent email.
    """
    app_tracker = get_or_create_app_tracker(app_id, session)

    recipient = req.recipient_email or f"hr@{app_tracker.company_name.lower().replace(' ', '')}.com"
    subject = req.subject or f"Application: {app_tracker.job_title} - {current_user.full_name}"
    body = req.body_text or (
        f"Dear {app_tracker.company_name} Hiring Team,\n\n"
        f"I am writing to express my strong enthusiasm for the {app_tracker.job_title} position. "
        f"With deep expertise in automated test engineering, CI/CD pipeline acceleration, and high-reliability systems, "
        f"I am confident in making an immediate positive impact on your product quality.\n\n"
        f"Please find attached my tailored CV. I look forward to discussing how my experience aligns with your engineering goals.\n\n"
        f"Best regards,\n{current_user.full_name}\n{current_user.email}"
    )

    result = gmail_service.dispatch_email(
        user=current_user,
        recipient_email=recipient,
        subject=subject,
        body_text=body,
        pdf_path=app_tracker.cv_pdf_path,
        mode=req.mode,
    )

    if req.mode == "send":
        tracker_store.update(app_id, ApplicationUpdate(status="Applied"))

    return result


@router.post("/{app_id}/prepare-interview")
def prepare_for_interview(
    app_id: str,
    req: PrepareInterviewRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Interview Preparation Copilot:
    Generates company intelligence, 10 targeted interview questions (Technical, Behavioral, Scenario),
    and winning STAR-framework response strategies.
    """
    app_tracker = get_or_create_app_tracker(app_id, session)
    brief = interview_service.prepare_interview(
        application=app_tracker,
        round_type=req.round_type,
        session=session,
    )
    return brief


@router.get("/{app_id}/interviews")
def list_application_interviews(
    app_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Retrieves all prepared interview rounds and question briefs for this application."""
    clean_id = app_id.replace("app-", "")
    target_id = int(clean_id) if clean_id.isdigit() else 1
    rounds = session.exec(
        select(InterviewRound).where(InterviewRound.application_id == target_id).order_by(InterviewRound.id.desc())
    ).all()
    return rounds


@router.patch("/{app_id}/interviews/{round_id}")
def update_interview_round(
    app_id: str,
    round_id: int,
    req: UpdateInterviewNotesRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Saves candidate interview reflections and update round status."""
    round_rec = session.get(InterviewRound, round_id)
    if not round_rec:
        raise HTTPException(status_code=404, detail=f"Interview round {round_id} not found.")

    if req.candidate_notes is not None:
        round_rec.candidate_notes = req.candidate_notes
    if req.status is not None:
        round_rec.status = req.status

    session.add(round_rec)
    session.commit()
    session.refresh(round_rec)
    return round_rec
