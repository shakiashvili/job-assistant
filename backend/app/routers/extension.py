import logging
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..db.database import engine, get_session, init_db
from ..db.models import ApplicationTracker, User, utc_now
from ..services.answer_service import load_live_candidate_profile
from ..services.auth_service import decode_access_token, get_user_by_email
from ..services.cv_generator_service import cv_generator_service
from ..services.gemini_service import gemini_service
from ..services.matcher_service import matcher_service
from ..services.salary_service import salary_service
from ..db.profile_repository import ground_truth_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/extension", tags=["Chrome Extension Copilot"])
_ext_bearer = HTTPBearer(auto_error=False)


def require_extension_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_ext_bearer),
    session: Session = Depends(get_session),
) -> User:
    """Strictly requires a valid Bearer JWT from the logged-in user (no anonymous guest fallback)."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Extension authentication required. Please sign in with your TalentFlow account.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = get_user_by_email(session, str(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or inactive.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _infer_portal(url: str, hint: Optional[str] = None) -> str:
    if hint and hint.strip() and hint.strip().lower() not in ("auto", "unknown"):
        return hint.strip().lower()
    low = (url or "").lower()
    for token, name in [
        ("linkedin.com", "linkedin.com"),
        ("myworkdayjobs.com", "workday"),
        ("greenhouse.io", "greenhouse"),
        ("lever.co", "lever"),
        ("djinni.co", "djinni.co"),
        ("dou.ua", "dou.ua"),
        ("vacancy.hr.gov.ge", "hr.gov.ge"),
        ("hr.gov.ge", "hr.gov.ge"),
        ("jobs.ge", "jobs.ge"),
        ("headhunter.ge", "headhunter.ge"),
        ("hr.ge", "hr.ge"),
        ("justjoin.it", "justjoin.it"),
    ]:
        if token in low:
            return name
    return "generic"


def _match_select_option(raw_answer: str, options: List[str]) -> str:
    if not options:
        return raw_answer
    ans_low = raw_answer.strip().lower()
    for opt in options:
        if opt.strip().lower() == ans_low:
            return opt
    if ans_low.startswith("yes"):
        for opt in options:
            if opt.strip().lower().startswith(("yes", "true", "დიახ")):
                return opt
    if ans_low.startswith("no"):
        for opt in options:
            if opt.strip().lower().startswith(("no", "false", "არა")):
                return opt
    for opt in options:
        opt_l = opt.strip().lower()
        if opt_l and (opt_l in ans_low or ans_low in opt_l):
            return opt
    return options[0]


class FormFieldSchema(BaseModel):
    field_id: str
    name: Optional[str] = None
    label: str = ""
    field_type: str = "text"
    placeholder: Optional[str] = None
    required: bool = False
    options: List[str] = Field(default_factory=list)


class PrepareApplicationRequest(BaseModel):
    url: str
    portal: Optional[str] = None
    job_title: Optional[str] = ""
    company_name: Optional[str] = ""
    location: Optional[str] = ""
    job_description: Optional[str] = ""
    raw_page_text: Optional[str] = ""
    cv_language: Optional[str] = None
    fields: List[FormFieldSchema] = Field(default_factory=list)


class FieldAnswerItem(BaseModel):
    field_id: str
    label: str
    field_type: str
    value: str
    confidence: float = 0.92
    source: str = "candidate_profile"


class PrepareApplicationResponse(BaseModel):
    status: str = "ready"
    portal: str
    job_title: str
    company_name: str
    extraction_failed: bool = False
    match_score: float
    match_tier: str
    seniority_warning: Optional[str] = None
    seniority_blocked: bool = False
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    salary_info: Dict[str, Any]
    company_intel: Dict[str, Any]
    tailored_cv: Dict[str, Any]
    cover_letter: str
    applicant_summary: str
    field_answers: List[FieldAnswerItem] = Field(default_factory=list)


class LogApplicationRequest(BaseModel):
    company_name: str = Field(..., min_length=1)
    job_title: str = Field(..., min_length=1)
    job_url: str = Field(..., min_length=1)
    portal: str = "custom"
    salary_offered: Optional[str] = None
    cv_pdf_path: Optional[str] = None
    cover_letter_text: Optional[str] = None
    status: str = "APPLIED"


@router.get("/profile")
def get_extension_profile(current_user: User = Depends(require_extension_user)) -> Dict[str, Any]:
    """Returns the live CandidateProfile summary for the authenticated extension user."""
    live = load_live_candidate_profile(current_user.email)
    uploaded = bool(live and live.get("user_uploaded", False))
    if not uploaded:
        return {
            "user_email": current_user.email,
            "full_name": current_user.full_name or "",
            "primary_role": "",
            "detected_industry": "",
            "target_industry": "",
            "years_of_experience": 0.0,
            "verified_skills": [],
            "profile_uploaded": False,
        }

    gt = ground_truth_store.get_data(owner_email=current_user.email)
    cand = gt.get("candidate", {})
    skills_md = live.get("skills_markdown") or gt.get("skills_md_raw") or ""
    parsed_md = ground_truth_store.parse_profile_from_md(skills_md) if skills_md else {}

    return {
        "user_email": current_user.email,
        "full_name": live.get("full_name") or parsed_md.get("full_name") or current_user.full_name or cand.get("full_name", "Candidate"),
        "primary_role": live.get("primary_role") or parsed_md.get("headline") or cand.get("headline", "Specialist"),
        "detected_industry": live.get("detected_industry") or "General Professional",
        "target_industry": live.get("target_industry") or "qa_tech",
        "years_of_experience": float(live.get("years_of_experience") or live.get("experience_years") or 1.5),
        "verified_skills": list(live.get("verified_skills") or live.get("all_skills") or parsed_md.get("skills") or [])[:25],
        "profile_uploaded": True,
    }


@router.post("/upload-skills")
async def extension_upload_skills(
    request: Request,
    current_user: User = Depends(require_extension_user),
) -> Dict[str, Any]:
    """Allows the Chrome Extension user to upload or refresh their own skills.md profile directly."""
    md_text = ""
    filename = "skills.md"
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            body = {}
        md_text = str((body or {}).get("content") or "")
        filename = str((body or {}).get("filename") or "skills.md")
    else:
        form = await request.form()
        uploaded_file = form.get("file")
        if uploaded_file is not None and hasattr(uploaded_file, "read"):
            filename = getattr(uploaded_file, "filename", None) or "skills.md"
            raw_bytes = await uploaded_file.read()
            md_text = raw_bytes.decode("utf-8", errors="replace")
        elif form.get("content") is not None:
            md_text = str(form.get("content") or "")

    if not md_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a non-empty .md/.txt skills profile.",
        )

    profile = ground_truth_store.ingest_skills_markdown(md_text, owner_email=current_user.email)
    ps = dict(profile.parsed_skills or {})
    return {
        "status": "success",
        "user_email": current_user.email,
        "full_name": profile.full_name,
        "primary_role": ps.get("primary_role") or ps.get("headline") or "Specialist",
        "detected_industry": ps.get("detected_industry") or "General Professional",
        "target_industry": ps.get("target_industry") or "qa_tech",
        "years_of_experience": float(profile.experience_years or 1.5),
        "verified_skills": list(ps.get("verified_skills") or ps.get("all_skills") or [])[:25],
        "profile_uploaded": True,
        "filename": filename,
    }


@router.post("/prepare-application", response_model=PrepareApplicationResponse)
def prepare_application(
    req: PrepareApplicationRequest,
    current_user: User = Depends(require_extension_user),
) -> PrepareApplicationResponse:
    """
    Universal Copilot Analyzer & Form Solver for LinkedIn, Workday, Greenhouse, Lever, and Georgian portals:
    1. Resolves honest Job Title & Employer (never hallucinates mock companies if DOM extraction fails).
    2. Loads the authenticated user's live CandidateProfile and runs matcher_service strict <=2.0 yr gate.
    3. Extracts explicit salary or builds benchmark estimate via salary_service.
    4. Summarizes company & role talking points via Gemini / heuristic fallback.
    5. Builds tailored ATS PDF + DOCX resume for direct DataTransfer attachment.
    6. Generates grounded per-field answers matching form controls & select options.
    """
    live_profile = load_live_candidate_profile(current_user.email)
    if not live_profile or not bool(live_profile.get("user_uploaded", False)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PROFILE_REQUIRED: Please upload your skills.md profile before generating a tailored CV or cover letter.",
            headers={"X-Profile-Required": "true"},
        )

    portal = _infer_portal(req.url, req.portal)
    dom_title = (req.job_title or "").strip()
    dom_company = (req.company_name or "").strip()
    desc_text = (req.job_description or req.raw_page_text or "").strip()

    extraction_failed = False
    if not dom_title or not dom_company or dom_title.lower() in ("unknown", "unknown title") or dom_company.lower() in ("unknown", "unknown company"):
        fallback_blob = "\n".join(x for x in [dom_title, f"Company: {dom_company}" if dom_company else "", desc_text] if x)
        extracted = gemini_service.extract_job_details(fallback_blob or req.url, portal=portal)
        job_title = dom_title or extracted.get("title") or "Unknown Title"
        company_name = dom_company or extracted.get("company") or "Unknown Company"
        extraction_failed = bool(
            extracted.get("extraction_failed")
            or job_title == "Unknown Title"
            or company_name == "Unknown Company"
        )
    else:
        job_title = dom_title
        company_name = dom_company

    gt = dict(ground_truth_store.get_data(owner_email=current_user.email))
    skills_md = live_profile.get("skills_markdown") or gt.get("skills_md_raw") or ""
    gt["skills_md_raw"] = skills_md

    if live_profile:
        parsed_skills = dict(live_profile)
        parsed_skills.setdefault("verified_skills", live_profile.get("all_skills") or [])
    else:
        parsed_skills = matcher_service.parse_skills_markdown(skills_md)

    raw_prof_name = str(live_profile.get("full_name") or "").strip()
    user_acct_name = str(current_user.full_name or "").strip()
    gt_name = str(gt.get("candidate", {}).get("full_name") or "").strip()
    cand_name = (
        raw_prof_name if raw_prof_name and raw_prof_name.lower() != "candidate"
        else (user_acct_name if user_acct_name and user_acct_name.lower() != "candidate"
              else (gt_name or "Candidate"))
    )
    cand_copy = dict(gt.get("candidate", {}))
    cand_copy["full_name"] = cand_name
    if live_profile.get("headline"):
        cand_copy["headline"] = live_profile["headline"]
    if live_profile.get("email") and "example.com" not in str(live_profile["email"]):
        cand_copy["email"] = live_profile["email"]
    elif current_user.email and cand_copy.get("email", "").endswith("@example.com"):
        cand_copy["email"] = current_user.email
    if live_profile.get("phone") and "+000" not in str(live_profile["phone"]):
        cand_copy["phone"] = live_profile["phone"]
    if live_profile.get("links"):
        cand_copy["links"] = {k: v for k, v in live_profile["links"].items() if v}
    gt["candidate"] = cand_copy

    # Determine output language cleanly
    if req.cv_language in ("en", "ka"):
        cv_lang = req.cv_language
    elif len(re.findall(r"[\u10A0-\u10FF]", f"{job_title} {desc_text[:600]}")) >= 12 or portal in ("jobs.ge", "hr.ge", "hr.gov.ge"):
        cv_lang = "ka"
    else:
        cv_lang = "en"

    # Match + Strict Experience Cap Evaluation
    tier_res = matcher_service.evaluate_job_tiered(
        title=job_title if job_title != "Unknown Title" else "",
        description=desc_text,
        parsed_skills=parsed_skills,
        portal=portal,
    )
    match_score = float(tier_res.get("suitability_score") or 0.0)
    match_tier = str(tier_res.get("match_tier") or "DIRECT")
    matched_skills = list(tier_res.get("matched_skills") or [])
    missing_skills = list(tier_res.get("missing_skills") or [])
    rationale = str(tier_res.get("match_rationale") or "")

    seniority_blocked = False
    seniority_warning: Optional[str] = None
    if tier_res.get("status") == "FILTERED_OUT" and (
        "experience" in rationale.lower()
        or "senior" in rationale.lower()
        or "cap" in rationale.lower()
        or "lead" in rationale.lower()
    ):
        seniority_blocked = True
        seniority_warning = rationale

    # Salary Extraction / Benchmark Estimate
    market = (
        "GE"
        if portal in ("jobs.ge", "hr.ge", "headhunter.ge", "hr.gov.ge") or "georgia" in (req.location or "").lower()
        else ("UA_REMOTE" if portal == "dou.ua" else "INT_REMOTE")
    )
    sal_explicit = salary_service.extract_vacancy_salary(title=job_title, description=desc_text)
    if sal_explicit.get("min_salary") or sal_explicit.get("max_salary"):
        salary_info = {
            "min_salary": sal_explicit["min_salary"],
            "max_salary": sal_explicit["max_salary"],
            "currency": sal_explicit["currency"],
            "is_unpaid": False,
            "stated_in_posting": True,
            "ai_estimated": False,
            "display": f"{sal_explicit['min_salary']:g} – {sal_explicit['max_salary']:g} {sal_explicit['currency']}/mo (Stated)",
        }
    elif sal_explicit.get("is_unpaid"):
        salary_info = {
            "min_salary": None,
            "max_salary": None,
            "currency": None,
            "is_unpaid": True,
            "stated_in_posting": True,
            "ai_estimated": False,
            "display": "Unpaid / Internship",
        }
    else:
        est = salary_service.estimate_salary(title=job_title, description=desc_text, market=market, portal=portal)
        salary_info = {
            "min_salary": est.get("min_salary"),
            "max_salary": est.get("max_salary"),
            "currency": est.get("currency") or "USD",
            "is_unpaid": False,
            "stated_in_posting": False,
            "ai_estimated": True,
            "display": f"{est.get('salary_range_str', 'Market Rate')} (Benchmark Estimate)",
        }

    # Company Intel & Narratives
    company_intel = gemini_service.research_company_intel(
        company=company_name,
        job_title=job_title,
        description=desc_text,
        cv_language=cv_lang,
    )
    req_skills = matcher_service.extract_job_requirements(job_title, desc_text)
    job_details = {
        "title": job_title,
        "company": company_name,
        "industry": str(parsed_skills.get("target_industry") or "qa_tech"),
        "portal": portal,
        "summary": desc_text[:1600],
        "description": desc_text[:2000],
        "required_skills": req_skills or matched_skills,
        "work_history": gt.get("work_history") or [],
        "education": gt.get("education") or [],
    }
    narratives = gemini_service.craft_human_tone_narratives(
        job_details=job_details,
        skills_md=skills_md,
        matched_skills=matched_skills or [str(s) for s in (parsed_skills.get("verified_skills") or [])[:6]],
        missing_skills=missing_skills,
        cv_language=cv_lang,
        candidate_name=cand_name,
    )

    # Tailored ATS PDF + DOCX CV
    cv_res = cv_generator_service.generate_vacancy_cv(
        job_title=job_title,
        company=company_name,
        portal=portal,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        human_summary=narratives["human_tone_summary"],
        motivation_statement=narratives["motivation_statement"],
        dou_motivational_letter=narratives["dou_motivational_letter"],
        skills_md_override=skills_md,
        cv_language=cv_lang,
        required_skills=req_skills,
        owner_email=current_user.email,
        vault_override=gt,
    )

    # Per-field answers
    field_answers: List[FieldAnswerItem] = []
    non_file_fields = [f for f in req.fields if f.field_type != "file"]
    if non_file_fields:
        q_dicts = [
            {
                "id": f.field_id,
                "question": f.label or f.placeholder or f.name or f.field_id,
                "field_type": f.field_type,
                "options": f.options,
            }
            for f in non_file_fields
        ]
        raw_ans = gemini_service.generate_grounded_answers(
            questions=q_dicts,
            candidate_data=gt,
            job_details=job_details,
            variant=str(parsed_skills.get("target_industry") or "qa_automation"),
            cv_language=cv_lang,
            candidate_profile=parsed_skills,
        )
        for f, ans_obj in zip(non_file_fields, raw_ans):
            val = str(ans_obj.get("answer", "")).strip() if isinstance(ans_obj, dict) else ""
            q_label = (f.label or f.placeholder or f.name or "").lower()
            if any(k in q_label for k in ("cover letter", "motivational", "motivation letter", "სამოტივაციო")):
                val = narratives["dou_motivational_letter"]
            elif any(k in q_label for k in ("motivation", "why us", "why do you want", "message to")) and len(val) < 120:
                val = narratives["dou_motivational_letter"]
            elif any(k in q_label for k in ("summary", "about yourself", "headline")) and len(val) < 80:
                val = narratives["human_tone_summary"]
            if f.options and f.field_type in ("select", "radio"):
                val = _match_select_option(val, f.options)
            elif f.field_type == "checkbox":
                val = "true" if any(w in q_label for w in ("agree", "consent", "privacy", "terms", "authorized", "confirm")) or val.lower().startswith("yes") else "false"
            field_answers.append(
                FieldAnswerItem(
                    field_id=f.field_id,
                    label=f.label or f.name or f.field_id,
                    field_type=f.field_type,
                    value=val,
                    confidence=float(ans_obj.get("confidence", 0.92)) if isinstance(ans_obj, dict) else 0.9,
                    source=str(ans_obj.get("source_ground_truth_field", "candidate_profile")) if isinstance(ans_obj, dict) else "candidate_profile",
                )
            )

    return PrepareApplicationResponse(
        status="warning_seniority" if seniority_blocked else "ready",
        portal=portal,
        job_title=job_title,
        company_name=company_name,
        extraction_failed=extraction_failed,
        match_score=round(match_score, 1),
        match_tier=match_tier,
        seniority_warning=seniority_warning,
        seniority_blocked=seniority_blocked,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        salary_info=salary_info,
        company_intel=company_intel,
        tailored_cv={
            "pdf_filename": cv_res.get("pdf_filename"),
            "pdf_url": cv_res.get("pdf_url"),
            "docx_filename": cv_res.get("docx_filename"),
            "docx_url": cv_res.get("docx_url"),
            "cv_language": cv_lang,
        },
        cover_letter=narratives["dou_motivational_letter"],
        applicant_summary=narratives["human_tone_summary"],
        field_answers=field_answers,
    )


@router.post("/log-application")
def log_extension_application(
    req: LogApplicationRequest,
    current_user: User = Depends(require_extension_user),
) -> Dict[str, Any]:
    """Records a completed human-reviewed external/Easy-Apply submission in the user's Kanban tracker."""
    init_db()
    allowed_statuses = {"STAGED", "APPLIED", "HR_SCREEN", "TECH_INTERVIEW", "FINAL_ROUND", "OFFER", "REJECTED"}
    target_status = req.status.upper() if req.status and req.status.upper() in allowed_statuses else "APPLIED"

    with Session(engine) as session:
        existing = session.exec(
            select(ApplicationTracker).where(
                (ApplicationTracker.user_id == current_user.id)
                & (ApplicationTracker.job_url == req.job_url)
                & (ApplicationTracker.is_deleted == False)
            )
        ).first()
        if existing:
            existing.status = target_status
            existing.salary_offered = req.salary_offered or existing.salary_offered
            existing.cv_pdf_path = req.cv_pdf_path or existing.cv_pdf_path
            existing.cover_letter_text = req.cover_letter_text or existing.cover_letter_text
            existing.updated_at = utc_now()
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return {"status": "updated", "application_id": existing.id, "company_name": existing.company_name, "job_title": existing.job_title}

        app_row = ApplicationTracker(
            user_id=current_user.id,
            company_name=req.company_name.strip(),
            job_title=req.job_title.strip(),
            job_url=req.job_url.strip(),
            portal=req.portal or "custom",
            status=target_status,
            salary_offered=req.salary_offered,
            cv_pdf_path=req.cv_pdf_path,
            cover_letter_text=req.cover_letter_text,
            applied_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(app_row)
        session.commit()
        session.refresh(app_row)
        return {"status": "created", "application_id": app_row.id, "company_name": app_row.company_name, "job_title": app_row.job_title}
