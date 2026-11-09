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
    parsed_skills: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utc_now, index=True)


class JobPosting(SQLModel, table=True):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("portal", "external_id", name="uq_portal_external_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portal: str = Field(index=True)  # "jobs.ge", "hr.ge", "dou.ua", "djinni.co", etc.
    external_id: str = Field(index=True)  # unique per portal
    title: str
    company: str
    url: str = Field(unique=True, index=True)
    market: str = Field(default="INT_REMOTE", index=True)  # "GE", "UA_REMOTE", "INT_REMOTE"
    is_remote: bool = Field(default=True)
    language_requirements: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    description_raw: str = Field(default="", sa_column=Column(Text, nullable=False))
    salary_min: Optional[float] = Field(default=None)
    salary_max: Optional[float] = Field(default=None)
    salary_currency: Optional[str] = Field(default=None)
    salary_estimated_by_ai: bool = Field(default=False)
    suitability_score: float = Field(default=0.0, index=True)
    match_rationale: str = Field(default="", sa_column=Column(Text, nullable=False))
    status: str = Field(default="DISCOVERED", index=True)  # "DISCOVERED", "FILTERED_OUT", "AUDITED", "STAGED", "APPLIED", "REJECTED"
    scraped_at: datetime = Field(default_factory=utc_now, index=True)


class ApplicationRecord(SQLModel, table=True):
    __tablename__ = "application_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_posting_id: Optional[int] = Field(default=None, foreign_key="job_postings.id", index=True)
    custom_cv_path: str = Field(default="")
    cover_letter_text: str = Field(default="", sa_column=Column(Text, nullable=False))
    submission_status: str = Field(default="STAGED", index=True)  # "STAGED", "SUBMITTED", "INTERVIEW", "REJECTED"
    applied_at: datetime = Field(default_factory=utc_now, index=True)
