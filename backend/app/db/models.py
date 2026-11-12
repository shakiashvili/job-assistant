from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy import JSON, Text, UniqueConstraint, event
from ..services.crypto_service import EncryptedString, EncryptedText, EncryptedJSON, blind_index


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


class ApplicationTracker(SQLModel, table=True):
    __tablename__ = "application_tracker"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    company_name: str = Field(index=True)
    job_title: str
    job_url: Optional[str] = None
    portal: str = Field(default="custom")
    status: str = Field(default="STAGED", index=True)  # STAGED, APPLIED, HR_SCREEN, TECH_INTERVIEW, FINAL_ROUND, OFFER, REJECTED
    salary_offered: Optional[str] = None
    cv_pdf_path: Optional[str] = None
    cover_letter_text: Optional[str] = None
    applied_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    is_deleted: bool = Field(default=False, index=True)

    user: Optional[User] = Relationship(back_populates="applications")
    interviews: List["InterviewRound"] = Relationship(back_populates="application")


class InterviewRound(SQLModel, table=True):
    __tablename__ = "interview_rounds"

    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application_tracker.id", index=True)
    round_type: str = Field(default="HR_SCREEN")  # HR_SCREEN, TECH_INTERVIEW, FINAL_ROUND, SYSTEM_DESIGN
    scheduled_at: Optional[datetime] = None
    company_intel_summary: Optional[str] = None
    predicted_questions: Optional[List[Dict[str, Any]]] = Field(default=[], sa_column=Column(JSON))
    candidate_notes: Optional[str] = None
    status: str = Field(default="SCHEDULED")  # SCHEDULED, COMPLETED, CANCELLED

    application: Optional[ApplicationTracker] = Relationship(back_populates="interviews")


class SkillActionPlan(SQLModel, table=True):
    __tablename__ = "skill_action_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    skill_name: str = Field(index=True)  # e.g. "Docker", "k6 Performance Testing"
    category: str = Field(default="AUTOMATION")  # AUTOMATION, API, DEVOPS, CODING
    days_to_learn: int = Field(default=7)
    milestones: List[Dict[str, Any]] = Field(default=[], sa_column=Column(JSON))
    is_completed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

    user: Optional[User] = Relationship(back_populates="action_plans")


class CandidateProfile(SQLModel, table=True):
    __tablename__ = "candidate_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
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


class JobPosting(SQLModel, table=True):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("portal", "external_id", name="uq_portal_external_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portal: str = Field(index=True)  # "jobs.ge", "hr.ge", "dou.ua", "djinni.co", "lever", "greenhouse", "custom"
    external_id: str = Field(index=True)  # unique index per portal
    title: str = Field(index=True)
    company: str = Field(index=True)
    url: str = Field(unique=True, index=True)
    market: str = Field(default="GLOBAL_REMOTE", index=True)  # "GE_DOMESTIC", "UA_REMOTE", "GLOBAL_REMOTE"
    is_remote: bool = Field(default=True)
    channel: str = Field(default="WEB_FORM")  # "WEB_FORM", "EMAIL", "EXTERNAL_LINK"
    delivery_channel: str = Field(default="WEB_FORM")
    target_email: Optional[str] = Field(default=None)
    email_subject: Optional[str] = Field(default=None)
    email_subject_template: Optional[str] = Field(default=None)
    description_raw: str = Field(default="", sa_column=Column(Text, nullable=False))
    detected_languages: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    language_requirements: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    salary_min: Optional[float] = Field(default=None)
    salary_max: Optional[float] = Field(default=None)
    salary_currency: Optional[str] = Field(default=None)  # "GEL", "USD", "EUR"
    salary_is_estimated: bool = Field(default=False)
    salary_estimated_by_ai: bool = Field(default=False)
    suitability_score: float = Field(default=0.0, index=True)
    match_score: float = Field(default=0.0)
    match_tier: str = Field(default="DIRECT", index=True)  # "DIRECT", "ADJACENT", "PUBLIC_INTERNSHIP"
    adjacent_role_tag: Optional[str] = Field(default=None)
    skill_overlap_pct: Optional[int] = Field(default=None)
    match_breakdown: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="DISCOVERED", index=True)  # "DISCOVERED", "FILTERED_OUT", "READY", "AUDITED", "STAGED", "APPLIED", "REJECTED"
    filter_out_reason: Optional[str] = Field(default=None)
    match_rationale: str = Field(default="", sa_column=Column(Text, nullable=False))
    deadline_text: Optional[str] = Field(default=None)
    is_link_live: bool = Field(default=True)
    scraped_at: datetime = Field(default_factory=utc_now, index=True)


class ApplicationRecord(SQLModel, table=True):
    __tablename__ = "application_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    vacancy_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    job_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    job_posting_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    cv_pdf_path: str = Field(default="")
    custom_cv_path: str = Field(default="")
    cover_letter: str = Field(default="", sa_column=Column(Text, nullable=False))
    cover_letter_text: str = Field(default="", sa_column=Column(Text, nullable=False))
    submitted_salary: Optional[str] = Field(default=None)
    screening_answers: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    submission_status: str = Field(default="STAGED", index=True)  # "STAGED", "APPLIED", "HR_SCREEN", "TECH_INTERVIEW", "OFFER", "REJECTED"
    interview_date: Optional[datetime] = Field(default=None)
    interview_notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    applied_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


# Backwards compatibility and master prompt aliases
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
