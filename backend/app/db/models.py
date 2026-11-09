from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, Text, UniqueConstraint


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CandidateProfile(SQLModel, table=True):
    __tablename__ = "candidate_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    raw_markdown: str = Field(default="", sa_column=Column(Text, nullable=False))
    full_name: str = Field(default="Alex Mercer")
    email: str = Field(default="alex.mercer.dev@gmail.com")
    phone: str = Field(default="+49 152 98765432")
    location: str = Field(default="Berlin / Tbilisi (Remote)")
    github_url: str = Field(default="https://github.com/alex-mercer-automation")
    linkedin_url: str = Field(default="https://linkedin.com/in/alex-mercer-qa")
    parsed_skills: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    experience_years: float = Field(default=5.0)
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
    target_email: Optional[str] = Field(default=None)
    email_subject: Optional[str] = Field(default=None)
    description_raw: str = Field(default="", sa_column=Column(Text, nullable=False))
    detected_languages: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    language_requirements: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    salary_min: Optional[float] = Field(default=None)
    salary_max: Optional[float] = Field(default=None)
    salary_currency: Optional[str] = Field(default=None)  # "GEL", "USD", "EUR"
    salary_is_estimated: bool = Field(default=False)
    salary_estimated_by_ai: bool = Field(default=False)
    suitability_score: float = Field(default=0.0, index=True)
    status: str = Field(default="DISCOVERED", index=True)  # "DISCOVERED", "FILTERED_OUT", "AUDITED", "STAGED", "APPLIED", "REJECTED"
    filter_out_reason: Optional[str] = Field(default=None)
    match_rationale: str = Field(default="", sa_column=Column(Text, nullable=False))
    scraped_at: datetime = Field(default_factory=utc_now, index=True)


class ApplicationRecord(SQLModel, table=True):
    __tablename__ = "application_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    job_posting_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    cv_pdf_path: str = Field(default="")
    custom_cv_path: str = Field(default="")
    cover_letter: str = Field(default="", sa_column=Column(Text, nullable=False))
    cover_letter_text: str = Field(default="", sa_column=Column(Text, nullable=False))
    screening_answers: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    submission_status: str = Field(default="STAGED", index=True)  # "STAGED", "APPLIED", "TECH_INTERVIEW", "OFFER", "REJECTED"
    interview_notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    applied_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)
