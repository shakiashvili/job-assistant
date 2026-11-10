from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from .db_models import CandidateProfile, JobPosting, ApplicationRecord  # noqa: F401


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
