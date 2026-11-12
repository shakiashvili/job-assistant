from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Column, Relationship
from sqlalchemy import JSON, Text, UniqueConstraint, Index, event
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
        Index("ix_job_postings_user_status_score", "user_id", "status", "suitability_score"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    portal: str = Field(index=True)  # "jobs.ge", "hr.ge", "dou.ua", "djinni.co", "lever", "greenhouse", "linkedin.com", "custom"
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


# --- Audit & Validation Schemas ---

class JobDetails(BaseModel):
    title: str = Field(..., description="Detected job title")
    company: str = Field("Unknown Company", description="Company offering the position")
    portal: str = Field("generic", description="Detected job portal (djinni, dou.ua, jobs.ge, hr.ge, headhunter.ge, justjoin.it, greenhouse, lever)")
    industry: str = Field("general", description="Detected industry: qa_tech, hospitality_reception, customer_service, healthcare_hospital, general")
    market: str = Field("INT_REMOTE", description="GE, UA_REMOTE, or INT_REMOTE")
    experience_years_required: Optional[int] = Field(None, description="Minimum years of experience required")
    required_skills: List[str] = Field(default_factory=list, description="Must-have skills / qualifications")
    nice_to_have_skills: List[str] = Field(default_factory=list, description="Nice-to-have or preferred skills")
    visa_requirements: Optional[str] = Field(None, description="Visa sponsorship / work authorization policy")
    language_requirements: List[str] = Field(default_factory=list, description="Languages required")
    location: str = Field("Tbilisi / Remote", description="Location or remote / abroad market policy")
    remote_policy: str = Field("Flexible / On-site / Remote", description="Remote, Hybrid, Abroad, or On-site")
    salary_range: Optional[str] = Field(None, description="Detected or AI-estimated salary range")
    salary_min: Optional[float] = Field(None, description="Extracted or AI-estimated min salary")
    salary_max: Optional[float] = Field(None, description="Extracted or AI-estimated max salary")
    salary_currency: Optional[str] = Field(None, description="Salary currency: USD, EUR, GEL, GBP")
    salary_estimated_by_ai: bool = Field(False, description="True if predicted by AI, False if extracted from posting")
    extraction_failed: bool = Field(False, description="True if company or title could not be reliably extracted")
    summary: str = Field("", description="Executive summary of the job description")


class GapItem(BaseModel):
    skill_or_area: str
    severity: str = Field("moderate", description="high, moderate, low")
    gap_description: str
    bridge_strategy: str = Field(..., description="How our human-tone CV bridges this gap honestly")


class CompanyValidation(BaseModel):
    company_name: str
    reputation: str = Field("UNVERIFIED", description="VERIFIED, UNVERIFIED, or BLACKLISTED")
    review_count: int = Field(0, description="Total reviews found across job portals")
    reviews_count: int = Field(0, description="Total reviews count (canonical field)")
    rating: Optional[float] = Field(None, description="Average star rating out of 5.0, or None if UNVERIFIED")
    is_blacklisted: bool = Field(False, description="True if blacklisted or <3 reviews")
    passed_gate: bool = Field(True, description="True if not blacklisted")
    portals_checked: List[str] = Field(default_factory=list)
    verdict: str
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)


class TailoredCVResult(BaseModel):
    pdf_filename: str
    pdf_url: str
    docx_filename: Optional[str] = None
    docx_url: Optional[str] = None
    html_preview_url: Optional[str] = None
    cv_language: str = "en"  # "en" or "ka" (Georgian)
    candidate_name: str = "Candidate"
    target_role: str = ""
    human_tone_summary: str
    applicant_summary: str
    motivation_statement: str
    dou_motivational_letter: str
    tailored_highlights: List[str]
    ats_keywords_covered: List[str]
    start_date_default: str = "1 week after offer"
    expected_salary: str = "Negotiable / Market Rate"


class Blocker(BaseModel):
    category: str = Field(..., description="visa, experience, language, skill, company_reviews")
    severity: str = Field(..., description="critical, warning, or info")
    description: str = Field(..., description="Reason for concern or blocker")
    candidate_status: str = Field(..., description="Candidate's current reality from skills.md / ground_truth")


class JobAuditRequest(BaseModel):
    raw_text: Optional[str] = Field(None, description="Pasted job description text")
    job_url: Optional[str] = Field(None, description="Direct URL to job posting")
    variant: Optional[str] = Field("qa_automation", description="Selected CV variant")
    cv_language: Optional[str] = Field("en", description="'en' (English) or 'ka' (Georgian / ქართული)")
    skills_md_override: Optional[str] = Field(None, description="Optional live markdown skills override")


class ScoreBreakdown(BaseModel):
    skills_match: int = Field(..., ge=0, le=100)
    ats_match: int = Field(..., ge=0, le=100)
    recruiter_match: int = Field(..., ge=0, le=100)
    experience_match: int = Field(..., ge=0, le=100)
    visa_match: int = Field(..., ge=0, le=100)
    language_match: int = Field(..., ge=0, le=100)


class JobAuditResponse(BaseModel):
    job_details: JobDetails
    match_score: int = Field(..., ge=0, le=100, description="Overall weighted match score 0-100")
    score_breakdown: ScoreBreakdown
    matched_skills: List[str]
    missing_skills: List[str]
    gaps: List[GapItem]
    company_validation: CompanyValidation
    tailored_cv: TailoredCVResult
    blockers: List[Blocker]
    recommended_variant: str
    recommendation_notes: str


# --- Screening Answers Schemas ---

class ScreeningQuestion(BaseModel):
    id: Optional[str] = None
    question: str
    field_type: Optional[str] = "text"
    options: Optional[List[str]] = None


class GenerateAnswersRequest(BaseModel):
    questions: List[ScreeningQuestion]
    job_title: Optional[str] = None
    company: Optional[str] = None
    job_description: Optional[str] = None
    portal: Optional[str] = None
    variant: Optional[str] = "qa_automation"
    cv_language: Optional[str] = "en"


class ScreeningAnswer(BaseModel):
    question: str
    field_type: str = "text"
    answer: str
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    source_ground_truth_field: Optional[str] = None


class GenerateAnswersResponse(BaseModel):
    answers: List[ScreeningAnswer]
    variant_used: str
    candidate_name: str
    applicant_summary: str
    motivation_letter: str
    dou_motivational_letter: str
    default_start_date: str = "1 week after offer"


# --- Stage Application Schemas ---

class StageApplicationRequest(BaseModel):
    job_url: str
    variant: Optional[str] = "qa_automation"
    cv_language: Optional[str] = "en"
    custom_pdf_filename: Optional[str] = None
    custom_answers: Optional[Dict[str, str]] = None
    applicant_summary: Optional[str] = None
    motivation_letter: Optional[str] = None
    expected_salary: Optional[str] = None
    start_date: Optional[str] = "1 week after offer"
    bypass_company_gate: Optional[bool] = False
    auto_submit: Optional[bool] = False
    headless: Optional[bool] = False
    timeout_seconds: Optional[int] = 45


class StageApplicationResponse(BaseModel):
    status: str  # staged, submitted, blocked_by_reviews, error
    portal_detected: str
    fields_filled: List[str]
    captcha_status: str = "none_detected"
    file_uploaded: bool
    resume_file_path: Optional[str] = None
    company_validation: Optional[CompanyValidation] = None
    message: str
    manual_review_needed: bool = True
    page_title: Optional[str] = None


# --- Vacancy Feed Schema ---

class PortalVacancyItem(BaseModel):
    id: str
    title: str
    company: str
    portal: str
    industry: str = "qa_tech"  # qa_tech, hospitality_reception, customer_service, healthcare_hospital
    location: str
    salary: str
    url: str
    mock_url: str
    company_reviews_count: int
    company_rating: float
    requires_motivational_letter: bool = False
    description: str


# --- Tracker Schemas ---

class ApplicationItem(BaseModel):
    id: str
    company: str
    role: str
    portal: Optional[str] = "generic"
    url: str
    status: str = "Discovered"
    match_score: Optional[int] = None
    ats_score: Optional[int] = None
    recruiter_score: Optional[int] = None
    salary_estimate: Optional[str] = None
    interview_date: Optional[str] = None
    company_reviews: Optional[int] = None
    cv_pdf_url: Optional[str] = None
    variant_used: Optional[str] = "qa_automation"
    applied_date: Optional[str] = None
    notes: Optional[str] = None


class ApplicationCreate(BaseModel):
    company: str
    role: str
    portal: Optional[str] = "generic"
    url: Optional[str] = None
    status: Optional[str] = "Discovered"
    match_score: Optional[int] = None
    ats_score: Optional[int] = None
    recruiter_score: Optional[int] = None
    salary_estimate: Optional[str] = None
    interview_date: Optional[str] = None
    company_reviews: Optional[int] = None
    cv_pdf_url: Optional[str] = None
    variant_used: Optional[str] = "qa_automation"
    applied_date: Optional[str] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    company: Optional[str] = None
    role: Optional[str] = None
    portal: Optional[str] = None
    url: Optional[str] = None
    status: Optional[str] = None
    match_score: Optional[int] = None
    ats_score: Optional[int] = None
    recruiter_score: Optional[int] = None
    salary_estimate: Optional[str] = None
    interview_date: Optional[str] = None
    company_reviews: Optional[int] = None
    cv_pdf_url: Optional[str] = None
    variant_used: Optional[str] = None
    applied_date: Optional[str] = None
    notes: Optional[str] = None

