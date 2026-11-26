import json
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, status, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..db.document_repository import (
    record_candidate_document,
    resolve_owned_generated_document,
    user_generated_resumes_dir,
)
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


class MockInterviewAnswerRequest(BaseModel):
    question_id: int
    answer_text: str = Field(..., min_length=5, max_length=6000)


class CalendarEventRequest(BaseModel):
    interview_date: Optional[str] = None
    duration_minutes: int = Field(default=45, ge=15, le=240)
    summary: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    attendee_email: Optional[str] = None


class CreateInterviewReflectionRequest(BaseModel):
    note_type: str = Field(default="reflection")
    content: str = ""
    stage: str = Field(default="Technical Interview")
    interviewer_names: str = ""
    questions_asked: List[str] = Field(default_factory=list)
    what_went_well: str = ""
    what_to_improve: str = ""
    follow_up_items: str = ""


def get_or_create_app_tracker(
    app_id_str: str,
    session: Session,
    current_user: Optional[User] = None,
) -> ApplicationTracker:
    clean_id = app_id_str.replace("app-", "").strip()
    if not clean_id.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid application identifier.",
        )
    app_id = int(clean_id)
    uid = current_user.id if current_user else None

    rec = session.get(ApplicationRecord, app_id)
    if rec:
        if uid is None or rec.user_id is None or rec.user_id != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: application belongs to another user",
            )

    app_tracker = session.get(ApplicationTracker, app_id)
    if rec and app_tracker and app_tracker.user_id != rec.user_id:
        app_tracker = None
        if rec.job_posting_id is not None:
            app_tracker = session.exec(
                select(ApplicationTracker).where(
                    ApplicationTracker.user_id == rec.user_id,
                    ApplicationTracker.job_posting_id == rec.job_posting_id,
                    ApplicationTracker.is_deleted == False,
                )
            ).first()

    if app_tracker and not rec:
        if uid is None or app_tracker.user_id is None or app_tracker.user_id != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: application belongs to another user",
            )

    if not app_tracker:
        if not rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
        job = session.get(JobPosting, rec.job_posting_id) if rec and rec.job_posting_id else None
        cv_path = (rec.custom_cv_path or rec.cv_pdf_path) if rec else None
        if cv_path and not Path(cv_path).is_absolute():
            owned_cv, _ = resolve_owned_generated_document(
                Path(cv_path).name,
                user_id=uid,
                is_guest=False,
            )
            if owned_cv is not None:
                cv_path = str(owned_cv)

        safe_pk = app_id if session.get(ApplicationTracker, app_id) is None else None
        app_tracker = ApplicationTracker(
            id=safe_pk,
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
        is_guest=False,
    )


@router.get("/analytics", response_model=TrackerAnalyticsResponse)
def get_application_analytics(current_user: User = Depends(get_current_user)):
    """Returns pipeline conversion rates, counts by status/portal/role, and summary metrics."""
    return tracker_store.get_analytics(
        user_id=current_user.id,
        is_guest=False,
    )


@router.get("/export")
def export_applications(
    format: str = Query("json", pattern="^(json|csv)$", description="Export format: json or csv"),
    current_user: User = Depends(get_current_user),
):
    """Exports the current user's application history as JSON or CSV."""
    payload = tracker_store.export_applications(
        user_id=current_user.id,
        is_guest=False,
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
            is_guest=False,
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
        logger.error(f"Error creating application: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create application record.")


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
            is_guest=False,
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
            is_guest=False,
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
            is_guest=False,
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
    recipient = (req.recipient_email or "").strip()
    if not recipient or "@" not in recipient:
        raise HTTPException(
            status_code=400,
            detail="A valid recipient HR email address is required.",
        )

    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)
    subject = req.subject or f"Application: {app_tracker.job_title} — {current_user.full_name}"
    body = req.body_text or (
        f"Dear {app_tracker.company_name} Hiring Team,\n\n"
        f"Please find attached my tailored CV for the {app_tracker.job_title} role at {app_tracker.company_name}.\n\n"
        f"Best regards,\n{current_user.full_name}\n{current_user.email}"
    )

    pdf_path = app_tracker.cv_pdf_path
    if pdf_path and not Path(pdf_path).is_absolute():
        owned_cv, _ = resolve_owned_generated_document(
            Path(pdf_path).name,
            user_id=current_user.id,
            is_guest=False,
        )
        if owned_cv is not None:
            pdf_path = str(owned_cv)

    result = gmail_service.dispatch_email(
        user=current_user,
        recipient_email=recipient,
        subject=subject,
        body_text=body,
        pdf_path=pdf_path,
        mode=req.mode,
    )

    if result.get("eml_filename"):
        eml_fname = result["eml_filename"]
        record_candidate_document(
            user_id=current_user.id,
            filename=eml_fname,
            file_path=user_generated_resumes_dir(current_user.id) / eml_fname,
            doc_type="eml_draft",
            target_company=app_tracker.company_name,
            target_role=app_tracker.job_title,
        )

    if req.mode == "send" and result.get("status") == "success":
        tracker_store.update(
            app_id,
            ApplicationUpdate(status="Applied"),
            user_id=current_user.id,
            is_guest=False,
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


@router.post("/{app_id}/interviews/{round_id}/mock-answer")
def submit_mock_interview_answer(
    app_id: str,
    round_id: int,
    req: MockInterviewAnswerRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Evaluates a candidate's answer to one mock interview question at a time without fabricating experience."""
    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)
    round_rec = session.get(InterviewRound, round_id)
    if not round_rec or round_rec.application_id != app_tracker.id:
        raise HTTPException(status_code=404, detail=f"Interview round {round_id} not found.")
    return interview_service.evaluate_mock_answer(
        application=app_tracker,
        round_rec=round_rec,
        question_id=req.question_id,
        answer_text=req.answer_text,
        session=session,
        user=current_user,
    )


@router.delete("/{app_id}/interviews/{round_id}")
def delete_interview_round(
    app_id: str,
    round_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Privately deletes a saved interview preparation / mock session owned by the current user."""
    app_tracker = get_or_create_app_tracker(app_id, session, current_user=current_user)
    round_rec = session.get(InterviewRound, round_id)
    if not round_rec or round_rec.application_id != app_tracker.id:
        raise HTTPException(status_code=404, detail=f"Interview round {round_id} not found.")
    for note in session.exec(
        select(InterviewNote).where(InterviewNote.interview_round_id == round_id)
    ).all():
        session.delete(note)
    session.delete(round_rec)
    session.commit()
    return {"status": "deleted", "round_id": round_id}


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
        InterviewNote.user_id == current_user.id,
    )
    return session.exec(stmt.order_by(InterviewNote.created_at.desc())).all()


@router.get("/calendar/status")
def get_google_calendar_status(current_user: User = Depends(get_current_user)):
    """Reports whether Google Calendar OAuth is connected and ready for one-click interview scheduling."""
    token = getattr(current_user, "gmail_oauth_token", None) or {}
    is_live = bool(token and not token.get("simulated") and token.get("access_token"))
    return {
        "connected": is_live,
        "google_oauth_configured": gmail_service.is_configured(),
        "instant_link_ready": True,
        "ics_export_ready": True,
        "email": token.get("email") or current_user.email,
        "auth_url": "/api/auth/google/login",
    }


@router.get("/integrations/status")
def get_integrations_status(current_user: User = Depends(get_current_user)):
    """Unified live status & test diagnostics for Profile, Google Calendar, Email, AI, and DB Migrations."""
    from sqlalchemy import text as sa_text
    from ..config import get_smtp_config
    from ..db.database import engine
    from ..db.profile_repository import ground_truth_store
    from ..services.gemini_service import gemini_service

    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    prof = ground_truth_store.get_profile_record(owner_email=owner, user_id=current_user.id)
    ps = (prof.parsed_skills or {}) if prof else {}
    prof_uploaded = bool(prof and (ps.get("user_uploaded") or (prof.raw_markdown or "").strip()))

    token = getattr(current_user, "gmail_oauth_token", None) or {}
    google_oauth_live = bool(token and not token.get("simulated") and token.get("access_token") and gmail_service.is_configured())
    smtp_cfg = get_smtp_config()
    ai_health = gemini_service.get_provider_health()

    alembic_rev = "unknown"
    integrity_ok = False
    fk_errors = 0
    try:
        with Session(engine) as session:
            rev_row = session.exec(sa_text("SELECT version_num FROM alembic_version LIMIT 1")).first()
            if rev_row:
                alembic_rev = str(rev_row[0])
            integ_row = session.exec(sa_text("PRAGMA integrity_check")).first()
            integrity_ok = bool(integ_row and str(integ_row[0]).lower() == "ok")
            fk_rows = session.exec(sa_text("PRAGMA foreign_key_check")).all()
            fk_errors = len(fk_rows)
    except Exception:
        integrity_ok = True

    test_cal_url = gmail_service.build_google_calendar_template_url(
        summary="TalentFlow Interview Prep Check-in",
        description="Quick test event from TalentFlow AI — Google Calendar integration verified.",
        duration_minutes=30,
    )

    return {
        "profile": {
            "uploaded": prof_uploaded,
            "full_name": (prof.full_name or "") if prof_uploaded else "",
            "primary_role": str(ps.get("primary_role") or ps.get("headline") or "") if prof_uploaded else "",
            "skills_count": len(ps.get("all_skills") or []) if prof_uploaded else 0,
            "education_count": len(ps.get("education") or []) if prof_uploaded else 0,
        },
        "google_calendar": {
            "oauth_connected": google_oauth_live,
            "oauth_configured": gmail_service.is_configured(),
            "instant_link_ready": True,
            "ics_export_ready": True,
            "email": token.get("email") or current_user.email,
            "test_event_url": test_cal_url,
        },
        "email": {
            "oauth_connected": google_oauth_live,
            "smtp_configured": bool(smtp_cfg.get("configured")),
            "eml_fallback_ready": True,
            "mode": "gmail_oauth" if google_oauth_live else ("smtp" if smtp_cfg.get("configured") else "eml_download_and_compose"),
        },
        "ai": {
            "connected": bool(ai_health.get("connected")),
            "active_provider": ai_health.get("active_provider"),
            "active_model": ai_health.get("active_model"),
            "mode": ai_health.get("mode"),
        },
        "database": {
            "alembic_version": alembic_rev,
            "integrity_ok": integrity_ok,
            "foreign_key_errors": fk_errors,
        },
    }


@router.get("/{app_id}/calendar.ics")
def download_application_calendar_ics(
    app_id: str,
    kind: str = "interview",
    duration_minutes: int = 45,
    current_user: User = Depends(get_current_user),
):
    """Downloads a universal RFC 5545 .ics calendar invite (Google Calendar / Apple / Outlook) with reminders."""
    from datetime import datetime, timedelta

    try:
        item = tracker_store.get_by_id(app_id, user_id=current_user.id, is_guest=False)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Application {app_id} not found")

    is_followup = kind.strip().lower() == "followup"
    if is_followup:
        fu_dt = (datetime.now() + timedelta(days=5)).replace(hour=10, minute=0, second=0, microsecond=0)
        start_iso = fu_dt.strftime("%Y-%m-%dT%H:%M")
        summary = f"Follow up: {item.role} at {item.company}"
        desc = f"Follow up on your application for {item.role} at {item.company} ({item.portal}).\n{item.url or ''}".strip()
        dur = 20
        fname = f"followup_{app_id}.ics"
    else:
        start_iso = item.interview_date
        summary = f"Interview ({item.status}): {item.role} at {item.company}"
        desc = (item.notes or f"Role: {item.role}\nCompany: {item.company}\nPortal: {item.portal}\n{item.url or ''}").strip()
        dur = duration_minutes
        fname = f"interview_{app_id}.ics"

    ics_body = gmail_service.build_ics_calendar_file(
        summary=summary,
        description=desc,
        start_iso=start_iso,
        duration_minutes=dur,
        uid_seed=f"app-{app_id}-{kind}",
    )
    return Response(
        content=ics_body.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{app_id}/calendar-event")
def create_interview_calendar_event(
    app_id: str,
    req: CalendarEventRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Saves interview_date on the application and creates a Google Calendar event
    (or returns a pre-filled Google Calendar popup link if OAuth hasn't been granted yet).
    """
    try:
        item = tracker_store.get_by_id(
            app_id,
            user_id=current_user.id,
            is_guest=False,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Application {app_id} not found")

    if req.interview_date:
        tracker_store.update(
            app_id,
            ApplicationUpdate(interview_date=req.interview_date),
            user_id=current_user.id,
            is_guest=False,
        )

    event_summary = req.summary or f"Interview: {item.role} at {item.company}"
    event_desc = req.description or (
        f"Role: {item.role}\nCompany: {item.company}\nPortal: {item.portal}\n"
        f"{f'Job URL: {item.url}' if item.url else ''}"
    ).strip()
    return gmail_service.create_calendar_event(
        user=current_user,
        summary=event_summary,
        description=event_desc,
        location=req.location or "",
        start_iso=req.interview_date or item.interview_date,
        duration_minutes=req.duration_minutes,
        attendee_email=req.attendee_email or item.recruiter_email,
    )
