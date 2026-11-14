import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, status, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..config import GENERATED_RESUMES_DIR
from ..db.database import get_session, engine
from ..db.models import (
    User,
    ApplicationTracker,
    ApplicationRecord,
    ApplicationEvent,
    JobPosting,
    InterviewRound,
    InterviewNote,
    ApplicationItem,
    ApplicationCreate,
    ApplicationUpdate,
    TrackerAnalyticsResponse,
)
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


class CreateInterviewReflectionRequest(BaseModel):
    note_type: str = Field(default="reflection")
    content: str = ""
    stage: str = Field(default="Technical Interview")
    interviewer_names: str = ""
    questions_asked: List[str] = Field(default_factory=list)
    what_went_well: str = ""
    what_to_improve: str = ""
    follow_up_items: str = ""


def _is_guest_user(user: User) -> bool:
    return (user.email or "").strip().lower() == "guest@talentflow.local"


def get_or_create_app_tracker(
    app_id_str: str,
    session: Session,
    current_user: Optional[User] = None,
) -> ApplicationTracker:
    clean_id = app_id_str.replace("app-", "")
    app_id = int(clean_id) if clean_id.isdigit() else 1
    is_guest = _is_guest_user(current_user) if current_user else True
    uid = current_user.id if current_user else None

    rec = session.get(ApplicationRecord, app_id)
    if rec and rec.user_id is not None and uid is not None and not is_guest and rec.user_id != uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: application belongs to another user",
        )

    app_tracker = session.get(ApplicationTracker, app_id)
    if app_tracker and app_tracker.user_id is not None and uid is not None and not is_guest and app_tracker.user_id != uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: application belongs to another user",
        )

    if not app_tracker:
        job = session.get(JobPosting, rec.job_posting_id) if rec and rec.job_posting_id else None
        cv_path = (rec.custom_cv_path or rec.cv_pdf_path) if rec else None
        if cv_path and not Path(cv_path).is_absolute():
            candidate_file = GENERATED_RESUMES_DIR / Path(cv_path).name
            if candidate_file.exists():
                cv_path = str(candidate_file)

        app_tracker = ApplicationTracker(
            id=app_id,
            user_id=rec.user_id if rec and rec.user_id is not None else uid,
            job_posting_id=rec.job_posting_id if rec else None,
            company_name=job.company if job else "Hiring Company",
            job_title=job.title if job else "Specialist",
            job_url=job.url if job else None,
            portal=job.portal if job else "custom",
            status=rec.submission_status if rec else "STAGED",
            cv_pdf_path=cv_path,
            cover_letter_text=rec.cover_letter_text if rec else None,
            is_deleted=False,
        )
        session.add(app_tracker)
        session.commit()
        session.refresh(app_tracker)
    return app_tracker


@router.get("", response_model=List[ApplicationItem])
def list_applications(current_user: User = Depends(get_current_user)):
    """Lists all tracked applications scoped to the current user in a single JOIN query."""
    return tracker_store.get_all(
        user_id=current_user.id,
        is_guest=_is_guest_user(current_user),
    )


@router.get("/analytics", response_model=TrackerAnalyticsResponse)
def get_application_analytics(current_user: User = Depends(get_current_user)):
    """Returns pipeline conversion rates, counts by status/portal/role, and summary metrics."""
    return tracker_store.get_analytics(
        user_id=current_user.id,
        is_guest=_is_guest_user(current_user),
    )


@router.get("/export")
def export_applications(
    format: str = Query("json", pattern="^(json|csv)$", description="Export format: json or csv"),
    current_user: User = Depends(get_current_user),
):
    """Exports the current user's application history as JSON or CSV."""
    payload = tracker_store.export_applications(
        user_id=current_user.id,
        is_guest=_is_guest_user(current_user),
        fmt=format,
    )
    if format.lower() == "csv":
        return Response(
            content=payload,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="applications_export.csv"'},
        )
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="applications_export.json"'},
    )


@router.get("/{app_id}", response_model=ApplicationItem)
def get_application(
    app_id: str,
    current_user: User = Depends(get_current_user),
):
    """Retrieves a single application record if owned by the current user."""
    try:
        item = tracker_store.get_by_id(
            app_id,
            user_id=current_user.id,
            is_guest=_is_guest_user(current_user),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Application {app_id} not found")
    return item


@router.post("", response_model=ApplicationItem)
def create_application(
    item: ApplicationCreate,
    current_user: User = Depends(get_current_user),
):
    """Adds a new application to the tracker board for the current user."""
    try:
        return tracker_store.create(item, user_id=current_user.id)
    except Exception as e:
        logger.error(f"Error creating application: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{app_id}", response_model=ApplicationItem)
@router.patch("/{app_id}", response_model=ApplicationItem)
def update_application(
    app_id: str,
    item_update: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
):
    """Updates status, notes, recruiter details, follow-up date, or outcome for an application."""
    try:
        updated = tracker_store.update(
            app_id,
            item_update,
            user_id=current_user.id,
            is_guest=_is_guest_user(current_user),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return updated


@router.delete("/{app_id}")
def delete_application(
    app_id: str,
    hard: bool = Query(False, description="Permanent hard delete if true"),
    current_user: User = Depends(get_current_user),
):
    """Removes an application from tracking after verifying ownership."""
    try:
        deleted = tracker_store.delete(
            app_id,
            user_id=current_user.id,
            is_guest=_is_guest_user(current_user),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return {"status": "success", "message": f"Application {app_id} deleted"}


@router.get("/{app_id}/events")
def list_application_events(
    app_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Returns audit history events for a specific application."""
    try:
        item = tracker_store.get_by_id(
            app_id,
            user_id=current_user.id,
            is_guest=_is_guest_user(current_user),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Application {app_id} not found")

    clean_id = str(app_id).replace("app-", "")
    num_id = int(clean_id) if clean_id.isdigit() else -1
    events = session.exec(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == num_id)
        .order_by(ApplicationEvent.created_at.desc())
    ).all()
    return events


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
    """
    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)

    recipient = (req.recipient_email or "").strip()
    if not recipient or "@" not in recipient:
        raise HTTPException(
            status_code=400,
            detail="A valid recipient HR email address is required.",
        )
    subject = req.subject or f"Application: {app_tracker.job_title} — {current_user.full_name}"
    body = req.body_text or (
        f"Dear {app_tracker.company_name} Hiring Team,\n\n"
        f"Please find attached my tailored CV for the {app_tracker.job_title} role at {app_tracker.company_name}.\n\n"
        f"Best regards,\n{current_user.full_name}\n{current_user.email}"
    )

    pdf_path = app_tracker.cv_pdf_path
    if pdf_path and not Path(pdf_path).is_absolute():
        candidate_file = GENERATED_RESUMES_DIR / Path(pdf_path).name
        if candidate_file.exists():
            pdf_path = str(candidate_file)

    result = gmail_service.dispatch_email(
        user=current_user,
        recipient_email=recipient,
        subject=subject,
        body_text=body,
        pdf_path=pdf_path,
        mode=req.mode,
    )

    if req.mode == "send":
        tracker_store.update(
            app_id,
            ApplicationUpdate(status="Applied"),
            user_id=current_user.id,
            is_guest=_is_guest_user(current_user),
        )

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
    Generates company intelligence, targeted interview questions, STAR strategies,
    technical glossary, and candidate follow-up questions grounded in the candidate's profile.
    """
    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)
    brief = interview_service.prepare_interview(
        application=app_tracker,
        round_type=req.round_type,
        session=session,
        user=current_user,
    )
    return brief


@router.get("/{app_id}/interviews")
def list_application_interviews(
    app_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Retrieves all prepared interview rounds and question briefs for this application."""
    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)
    rounds = session.exec(
        select(InterviewRound)
        .where(InterviewRound.application_id == app_tracker.id)
        .order_by(InterviewRound.id.desc())
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
    """Saves candidate interview reflections and updates round status after checking ownership."""
    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)
    round_rec = session.get(InterviewRound, round_id)
    if not round_rec or round_rec.application_id != app_tracker.id:
        raise HTTPException(status_code=404, detail=f"Interview round {round_id} not found.")

    if req.candidate_notes is not None:
        round_rec.candidate_notes = req.candidate_notes
    if req.status is not None:
        round_rec.status = req.status

    session.add(round_rec)
    session.commit()
    session.refresh(round_rec)
    return round_rec


@router.post("/{app_id}/interviews/{round_id}/notes")
def create_interview_reflection_note(
    app_id: str,
    round_id: int,
    req: CreateInterviewReflectionRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Persists a structured InterviewNote reflection (questions asked, what went well, what to improve)."""
    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)
    content_str = req.content or json.dumps(
        {
            "stage": req.stage,
            "interviewer_names": req.interviewer_names,
            "questions_asked": req.questions_asked,
            "what_went_well": req.what_went_well,
            "what_to_improve": req.what_to_improve,
            "follow_up_items": req.follow_up_items,
        },
        ensure_ascii=False,
    )
    note = InterviewNote(
        user_id=current_user.id or 1,
        application_id=app_tracker.id,
        interview_round_id=round_id,
        note_type=req.note_type or "reflection",
        content=content_str,
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


@router.get("/{app_id}/interviews/{round_id}/notes")
def list_interview_reflection_notes(
    app_id: str,
    round_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Lists structured InterviewNote reflections for an interview round."""
    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)
    stmt = select(InterviewNote).where(
        InterviewNote.application_id == app_tracker.id,
        InterviewNote.interview_round_id == round_id,
    )
    if not _is_guest_user(current_user):
        stmt = stmt.where(InterviewNote.user_id == current_user.id)
    return session.exec(stmt.order_by(InterviewNote.created_at.desc())).all()
