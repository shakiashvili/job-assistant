from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy import JSON, Text, UniqueConstraint, Index, event
from ..services.crypto_service import EncryptedString, EncryptedText, EncryptedJSON, blind_index
from ..schemas.api_schemas import (  # noqa: F401
    JobDetails,
    GapItem,
    CompanyValidation,
    TailoredCVResult,
    Blocker,
    JobAuditRequest,
    ScoreBreakdown,
    JobAuditResponse,
    ScreeningQuestion,
    GenerateAnswersRequest,
    ScreeningAnswer,
    GenerateAnswersResponse,
    StageApplicationRequest,
    StageApplicationResponse,
    PortalVacancyItem,
    ApplicationItem,
    ApplicationCreate,
    ApplicationUpdate,
    TrackerAnalyticsResponse,
    SavedSearchCreate,
    SavedSearchOut,
    NotificationOut,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(sa_column=Column(EncryptedString, nullable=False))
    email_hash: str = Field(default="", unique=True, index=True)
    hashed_password: str
    full_name: str = Field(default="Candidate", sa_column=Column(EncryptedString, nullable=False))
    is_active: bool = Field(default=True)
    is_admin: bool = Field(default=False)
    gmail_oauth_token: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(EncryptedJSON))
    created_at: datetime = Field(default_factory=utc_now)

    # Relationships
    applications: List["ApplicationTracker"] = Relationship(back_populates="user")
    action_plans: List["SkillActionPlan"] = Relationship(back_populates="user")


class UserOTP(SQLModel, table=True):
    __tablename__ = "user_otps"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(sa_column=Column(EncryptedString, nullable=False))
    email_hash: str = Field(default="", index=True)
    otp_code: str = Field(sa_column=Column(EncryptedString, nullable=False))
    expires_at: datetime = Field(index=True)
    is_used: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class CandidateProfile(SQLModel, table=True):
    __tablename__ = "candidate_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    raw_markdown: str = Field(default="", sa_column=Column(EncryptedText, nullable=False))
    full_name: str = Field(default="Candidate", sa_column=Column(EncryptedString, nullable=False))
    email: str = Field(default="candidate@example.com", sa_column=Column(EncryptedString, nullable=False))
    phone: str = Field(default="+000 000 0000", sa_column=Column(EncryptedString, nullable=False))
    location: str = Field(default="Remote / Georgia", sa_column=Column(EncryptedString, nullable=False))
    github_url: str = Field(default="https://github.com/example-candidate", sa_column=Column(EncryptedString, nullable=False))
    linkedin_url: str = Field(default="https://linkedin.com/in/example-candidate", sa_column=Column(EncryptedString, nullable=False))
    parsed_skills: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(EncryptedJSON, nullable=False))
    experience_years: float = Field(default=0.0)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


class CandidateSkill(SQLModel, table=True):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        Index("ix_candidate_skills_user_cat", "user_id", "category"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    profile_id: Optional[int] = Field(default=None, foreign_key="candidate_profiles.id", index=True)
    skill_name: str = Field(index=True)
    category: str = Field(default="core")  # core, secondary, language, tool
    proficiency: Optional[str] = Field(default=None)
    years_used: Optional[float] = Field(default=None)
    is_verified: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class CandidateExperience(SQLModel, table=True):
    __tablename__ = "candidate_experiences"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    profile_id: Optional[int] = Field(default=None, foreign_key="candidate_profiles.id", index=True)
    company: str = Field(default="")
    role_title: str = Field(default="")
    location: Optional[str] = Field(default=None)
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    is_current: bool = Field(default=False)
    highlights: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class CandidateEducation(SQLModel, table=True):
    __tablename__ = "candidate_educations"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    profile_id: Optional[int] = Field(default=None, foreign_key="candidate_profiles.id", index=True)
    institution: str = Field(default="")
    degree: str = Field(default="")
    field_of_study: Optional[str] = Field(default=None)
    graduation_year: Optional[str] = Field(default=None)
    coursework: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class CandidateDocument(SQLModel, table=True):
    __tablename__ = "candidate_documents"
    __table_args__ = (
        Index("ix_candidate_documents_user_type", "user_id", "doc_type"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    job_posting_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    filename: str = Field(index=True)
    original_filename: str = Field(default="")
    storage_path: str = Field(default="")
    doc_type: str = Field(default="generated_pdf", index=True)  # uploaded_cv, generated_pdf, generated_docx, generated_html
    cv_style: str = Field(default="tailored")  # ats, recruiter, tailored, base
    cv_language: str = Field(default="en")
    version_number: int = Field(default=1)
    size_bytes: int = Field(default=0)
    sha256_hash: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class JobPosting(SQLModel, table=True):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("portal", "external_id", name="uq_portal_external_id"),
        Index("ix_job_postings_user_status_score", "user_id", "status", "suitability_score"),
        Index("ix_job_postings_portal_status_score", "portal", "status", "suitability_score"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    portal: str = Field(index=True)  # "jobs.ge", "hr.ge", "dou.ua", "djinni.co", "lever", "greenhouse", "linkedin.com", "custom"
    external_id: str = Field(index=True)
    title: str = Field(index=True)
    company: str = Field(index=True)
    url: str = Field(unique=True, index=True)
    market: str = Field(default="GLOBAL_REMOTE", index=True)
    is_remote: bool = Field(default=True)
    remote_type: str = Field(default="REMOTE")  # REMOTE, HYBRID, ONSITE
    employment_type: str = Field(default="FULL_TIME")  # FULL_TIME, CONTRACT_B2B, INTERNSHIP, PART_TIME
    experience_min_years: Optional[float] = Field(default=None)
    seniority_level: Optional[str] = Field(default=None)
    country: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    channel: str = Field(default="WEB_FORM")
    delivery_channel: str = Field(default="WEB_FORM")
    target_email: Optional[str] = Field(default=None)
    email_subject: Optional[str] = Field(default=None)
    email_subject_template: Optional[str] = Field(default=None)
    description_raw: str = Field(default="", sa_column=Column(Text, nullable=False))
    detected_languages: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    language_requirements: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    salary_min: Optional[float] = Field(default=None)
    salary_max: Optional[float] = Field(default=None)
    salary_currency: Optional[str] = Field(default=None)
    salary_is_estimated: bool = Field(default=False)
    salary_estimated_by_ai: bool = Field(default=False)
    suitability_score: float = Field(default=0.0, index=True)
    match_score: float = Field(default=0.0)
    match_tier: str = Field(default="DIRECT", index=True)  # "DIRECT", "ADJACENT", "PUBLIC_INTERNSHIP"
    adjacent_role_tag: Optional[str] = Field(default=None)
    skill_overlap_pct: Optional[int] = Field(default=None)
    match_breakdown: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="DISCOVERED", index=True)
    filter_out_reason: Optional[str] = Field(default=None)
    match_rationale: str = Field(default="", sa_column=Column(Text, nullable=False))
    posting_date: Optional[str] = Field(default=None)
    deadline_text: Optional[str] = Field(default=None)
    is_expired: bool = Field(default=False)
    is_link_live: bool = Field(default=True)
    scraped_at: datetime = Field(default_factory=utc_now, index=True)


class UserJobMatch(SQLModel, table=True):
    """Per-candidate evaluation of a shared JobPosting, preventing multi-user match overwrites."""
    __tablename__ = "user_job_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "job_posting_id", name="uq_user_job_match"),
        Index("ix_user_job_matches_user_status_score", "user_id", "status", "suitability_score"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    job_posting_id: int = Field(foreign_key="job_postings.id", index=True)
    suitability_score: float = Field(default=0.0, index=True)
    match_score: float = Field(default=0.0)
    match_tier: str = Field(default="DIRECT", index=True)
    adjacent_role_tag: Optional[str] = Field(default=None)
    skill_overlap_pct: Optional[int] = Field(default=None)
    matched_skills: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    missing_skills: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    match_breakdown: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="STAGED", index=True)  # DISCOVERED, STAGED, AUDITED, FILTERED_OUT, APPLIED, IGNORED
    filter_out_reason: Optional[str] = Field(default=None)
    match_rationale: str = Field(default="", sa_column=Column(Text, nullable=False))
    is_saved: bool = Field(default=False, index=True)
    is_ignored: bool = Field(default=False)
    is_new: bool = Field(default=True, index=True)
    evaluated_at: datetime = Field(default_factory=utc_now, index=True)


class SavedJob(SQLModel, table=True):
    __tablename__ = "saved_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "job_posting_id", name="uq_user_saved_job"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    job_posting_id: int = Field(foreign_key="job_postings.id", index=True)
    notes: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class ApplicationTracker(SQLModel, table=True):
    __tablename__ = "application_tracker"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    job_posting_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    company_name: str = Field(index=True)
    job_title: str
    job_url: Optional[str] = None
    portal: str = Field(default="custom")
    status: str = Field(default="STAGED", index=True)
    salary_expected: Optional[str] = None
    salary_offered: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    follow_up_date: Optional[str] = None
    cv_pdf_path: Optional[str] = None
    cv_version_id: Optional[int] = Field(default=None, foreign_key="candidate_documents.id")
    cover_letter_text: Optional[str] = None
    outcome: Optional[str] = None
    applied_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    is_deleted: bool = Field(default=False, index=True)

    user: Optional[User] = Relationship(back_populates="applications")
    interviews: List["InterviewRound"] = Relationship(back_populates="application")


class ApplicationRecord(SQLModel, table=True):
    __tablename__ = "application_records"
    __table_args__ = (
        Index("ix_application_records_user_status", "user_id", "submission_status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    vacancy_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    job_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    job_posting_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    cv_pdf_path: str = Field(default="")
    custom_cv_path: str = Field(default="")
    cv_version_id: Optional[int] = Field(default=None, foreign_key="candidate_documents.id")
    cover_letter: str = Field(default="", sa_column=Column(Text, nullable=False))
    cover_letter_text: str = Field(default="", sa_column=Column(Text, nullable=False))
    submitted_salary: Optional[str] = Field(default=None)
    salary_offered: Optional[str] = Field(default=None)
    recruiter_name: Optional[str] = Field(default=None)
    recruiter_email: Optional[str] = Field(default=None)
    follow_up_date: Optional[str] = Field(default=None)
    outcome: Optional[str] = Field(default=None)
    screening_answers: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    submission_status: str = Field(default="STAGED", index=True)
    interview_date: Optional[datetime] = Field(default=None)
    interview_notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    applied_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


class ApplicationEvent(SQLModel, table=True):
    __tablename__ = "application_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    from_status: Optional[str] = Field(default=None)
    to_status: str = Field(default="STAGED")
    event_type: str = Field(default="status_change")
    note: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class InterviewRound(SQLModel, table=True):
    __tablename__ = "interview_rounds"

    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application_tracker.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    round_type: str = Field(default="HR_SCREEN")  # HR_SCREEN, TECH_INTERVIEW, FINAL_ROUND, SYSTEM_DESIGN
    scheduled_at: Optional[datetime] = None
    company_intel_summary: Optional[str] = None
    predicted_questions: Optional[List[Dict[str, Any]]] = Field(default=[], sa_column=Column(JSON))
    technical_glossary: Optional[List[Dict[str, Any]]] = Field(default=[], sa_column=Column(JSON))
    follow_up_questions: Optional[List[str]] = Field(default=[], sa_column=Column(JSON))
    candidate_notes: Optional[str] = None
    reflection_notes: Optional[str] = None
    status: str = Field(default="SCHEDULED")  # SCHEDULED, COMPLETED, CANCELLED

    application: Optional[ApplicationTracker] = Relationship(back_populates="interviews")


class InterviewNote(SQLModel, table=True):
    __tablename__ = "interview_notes"

    id: Optional[int] = Field(default=None, primary_key=True)
    interview_round_id: Optional[int] = Field(default=None, foreign_key="interview_rounds.id", index=True)
    application_id: Optional[int] = Field(default=None, index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    note_type: str = Field(default="reflection")  # preparation, reflection, question_note
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class SkillActionPlan(SQLModel, table=True):
    __tablename__ = "skill_action_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    skill_name: str = Field(index=True)
    category: str = Field(default="AUTOMATION")
    days_to_learn: int = Field(default=7)
    milestones: List[Dict[str, Any]] = Field(default=[], sa_column=Column(JSON))
    is_completed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

    user: Optional[User] = Relationship(back_populates="action_plans")


class SavedSearch(SQLModel, table=True):
    __tablename__ = "saved_searches"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(index=True)
    filters: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    notify_on_new: bool = Field(default=True)
    last_run_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    job_posting_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    saved_search_id: Optional[int] = Field(default=None, foreign_key="saved_searches.id")
    title: str
    message: str = Field(default="", sa_column=Column(Text, nullable=False))
    notification_type: str = Field(default="new_match", index=True)  # new_match, follow_up_due, system
    is_read: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class ScrapeTask(SQLModel, table=True):
    __tablename__ = "scrape_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(unique=True, index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    status: str = Field(default="RUNNING", index=True)  # PENDING, RUNNING, COMPLETED, FAILED
    portals: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    progress_pct: int = Field(default=0)
    current_portal: Optional[str] = Field(default=None)
    result_summary: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    completed_at: Optional[datetime] = Field(default=None)


# Canonical and backwards-compatible aliases
Application = ApplicationTracker
JobVacancy = JobPosting
LiveJobVacancy = JobPosting


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def _sync_user_email_hash(mapper, connection, target: User) -> None:
    target.email_hash = blind_index(target.email)


@event.listens_for(UserOTP, "before_insert")
@event.listens_for(UserOTP, "before_update")
def _sync_otp_email_hash(mapper, connection, target: UserOTP) -> None:
    target.email_hash = blind_index(target.email)


@event.listens_for(ApplicationTracker, "before_delete")
def _cascade_delete_tracker_children(mapper, connection, target: ApplicationTracker) -> None:
    if target.id is not None:
        from sqlalchemy import select as sa_select
        round_ids_subq = sa_select(InterviewRound.id).where(InterviewRound.application_id == target.id)
        connection.execute(
            InterviewNote.__table__.delete().where(
                (InterviewNote.application_id == target.id)
                | (InterviewNote.interview_round_id.in_(round_ids_subq))
            )
        )
        connection.execute(InterviewRound.__table__.delete().where(InterviewRound.application_id == target.id))
        connection.execute(ApplicationEvent.__table__.delete().where(ApplicationEvent.application_id == target.id))


@event.listens_for(JobPosting, "before_delete")
def _cascade_delete_job_posting_children(mapper, connection, target: JobPosting) -> None:
    if target.id is not None:
        from sqlalchemy import select as sa_select
        tracker_ids_subq = sa_select(ApplicationTracker.id).where(ApplicationTracker.job_posting_id == target.id)
        round_ids_subq = sa_select(InterviewRound.id).where(InterviewRound.application_id.in_(tracker_ids_subq))
        connection.execute(
            InterviewNote.__table__.delete().where(
                (InterviewNote.application_id.in_(tracker_ids_subq))
                | (InterviewNote.interview_round_id.in_(round_ids_subq))
            )
        )
        connection.execute(InterviewRound.__table__.delete().where(InterviewRound.application_id.in_(tracker_ids_subq)))
        connection.execute(ApplicationEvent.__table__.delete().where(ApplicationEvent.application_id.in_(tracker_ids_subq)))
        connection.execute(UserJobMatch.__table__.delete().where(UserJobMatch.job_posting_id == target.id))
        connection.execute(SavedJob.__table__.delete().where(SavedJob.job_posting_id == target.id))
        connection.execute(Notification.__table__.delete().where(Notification.job_posting_id == target.id))
        connection.execute(CandidateDocument.__table__.delete().where(CandidateDocument.job_posting_id == target.id))
        connection.execute(
            ApplicationRecord.__table__.delete().where(
                (ApplicationRecord.job_id == target.id)
                | (ApplicationRecord.job_posting_id == target.id)
                | (ApplicationRecord.vacancy_id == target.id)
            )
        )
        connection.execute(ApplicationTracker.__table__.delete().where(ApplicationTracker.job_posting_id == target.id))


