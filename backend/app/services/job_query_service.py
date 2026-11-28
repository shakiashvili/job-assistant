import math
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
from fastapi import Query
from sqlalchemy import String, case, cast, func
from sqlalchemy import select as sa_select
from sqlmodel import Session, and_, col, or_, select

from ..db.database import engine, init_db
from ..db.models import ApplicationRecord, ApplicationTracker, JobPosting, SavedJob, User, UserJobMatch, utc_now
from ..db.profile_repository import ground_truth_store
from .matcher_service import matcher_service, skills_match_token
from .matching.gates import run_gate_pipeline
from .salary_service import salary_service
from .scrapers.base_scraper import classify_georgia_b2b_suitability, sanitize_company_name
from .scrapers.scraper_orchestrator import scraper_orchestrator

_DJINNI_FIRE_RE = re.compile(r"🔥\s*|\s*⚡\s*")
_DJINNI_RESPONDS_RE = re.compile(r"\bResponds\s+to\s+\d+%.*$", re.I)
_DJINNI_SALARY_TAIL_RE = re.compile(r"\s+(?:to|up\s+to|from)?\s*[\$€£]\s*\d[\d,]*(?:\s*-\s*[\$€£]?\d[\d,]*)?.*$", re.I)
_WHITESPACE_RE = re.compile(r"\s+")
_EMAIL_IN_TEXT_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_LEGAL_SUFFIX_RE = re.compile(r"\b(?:ltd|llc|jsc|inc|corp|gmbh|შპს|სს)\b", re.I)
_JOBS_GE_ID_RE = re.compile(r"jobs\.ge/(?:ge|en)/?\?.*?\bid=(\d+)", re.I)
_IGNORED_EMAIL_DOMAINS = ("jobs.ge", "hr.ge", "headhunter.ge", "hr.gov.ge", "example.com", "sentry.io")

INDUSTRY_KEYWORDS: Dict[str, List[str]] = {
    "software_it": ["software", "qa", "developer", "engineer", "devops", "python", "java", "react", "frontend", "backend", "it ", "ტესტ", "პროგრამ"],
    "finance_banking": ["finance", "bank", "accountant", "audit", "ifrs", "credit", "treasury", "ფინანს", "ბანკ", "ბუღალტ", "აუდიტ"],
    "economics_analytics": ["econom", "business analyst", "data analyst", "bi ", "sql", "analytics", "ეკონომ", "ანალიტიკ"],
    "operations_admin": ["operations", "office manager", "administrator", "coordinator", "project manager", "ოპერაცი", "ადმინისტრ"],
    "marketing_sales": ["marketing", "sales", "seo", "smm", "account manager", "business development", "მარკეტინგ", "გაყიდვ"],
    "human_resources": ["hr", "human resource", "recruiter", "talent acquisition", "people operations", "რეკრუტ"],
    "customer_support": ["customer support", "customer service", "helpdesk", "client care", "call center", "მომხმარებ"],
    "logistics_supply": ["logistics", "supply chain", "procurement", "warehouse", "freight", "ლოგისტიკ", "შესყიდვ"],
    "legal_compliance": ["legal", "lawyer", "compliance", "aml", "kyc", "counsel", "იურისტ", "კომპლაენს"],
    "healthcare_education": ["medical", "clinic", "hospital", "nurse", "doctor", "teacher", "lecturer", "სამედიცინო", "კლინიკ"],
    "hospitality": ["hotel", "receptionist", "hospitality", "concierge", "tourism", "სასტუმრო", "ტურიზმ"],
    "public_sector": ["ministry", "agency", "municipality", "public", "state", "სამინისტრო", "სააგენტო", "საჯარო"],
}

EXPERIENCE_PATTERNS: Dict[str, List[str]] = {
    "intern": ["intern", "trainee", "სტაჟირ", "graduate", "entry"],
    "junior": ["junior", "entry", "associate", "0-2", "1-2", "1+ year"],
    "mid": ["mid", "middle", "2-4", "3-5", "3+ year", "regular"],
    "senior": ["senior", "lead", "principal", "staff", "5+ year", "architect"],
}

EMPLOYMENT_PATTERNS: Dict[str, List[str]] = {
    "full_time": ["full-time", "full time", "სრული განაკვეთ"],
    "part_time": ["part-time", "part time", "ნახევარი განაკვეთ"],
    "contract": ["contract", "b2b", "freelance", "contractor"],
    "internship": ["intern", "internship", "სტაჟირ"],
}

B2B_PORTALS = [
    "remotive.com", "himalayas.app", "remoteok.com", "djinni.co",
    "dou.ua", "justjoin.it", "greenhouse.io", "lever.co",
]


class JobFilters:
    """FastAPI dependency encapsulating all 26 vacancy search, filter, sort, and pagination query params."""

    def __init__(
        self,
        page: int = Query(1, ge=1),
        limit: int = Query(12, ge=1, le=200),
        portal: Optional[str] = None,
        market: Optional[str] = None,
        status: Optional[str] = None,
        tier: Optional[str] = Query(None),
        min_score: Optional[float] = Query(60.0),
        include_filtered: bool = Query(False),
        include_dismissed: bool = Query(False),
        industry: Optional[str] = Query(None),
        search: Optional[str] = Query(None),
        country: Optional[str] = Query(None),
        city: Optional[str] = Query(None),
        remote_type: Optional[str] = Query(None),
        salary_min: Optional[float] = Query(None),
        language: Optional[str] = Query(None),
        technology: Optional[str] = Query(None),
        experience_level: Optional[str] = Query(None),
        employment_type: Optional[str] = Query(None),
        sort_by: str = Query("newest"),
        posted_within_days: Optional[int] = Query(None, ge=1, le=365),
        only_new: bool = Query(False),
        only_saved: bool = Query(False),
        b2b_only: bool = Query(False),
        geo_eligible_only: bool = Query(False),
    ) -> None:
        self.page = page
        self.limit = limit
        self.portal = portal
        self.market = market
        self.status = status
        self.tier = tier
        self.min_score = min_score
        self.include_filtered = include_filtered
        self.include_dismissed = include_dismissed
        self.industry = industry
        self.search = search
        self.country = country
        self.city = city
        self.remote_type = remote_type
        self.salary_min = salary_min
        self.language = language
        self.technology = technology
        self.experience_level = experience_level
        self.employment_type = employment_type
        self.sort_by = sort_by
        self.posted_within_days = posted_within_days
        self.only_new = only_new
        self.only_saved = only_saved
        self.b2b_only = b2b_only
        self.geo_eligible_only = geo_eligible_only


def _esc_like(val: str) -> str:
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _or_title_desc(patterns: List[str]) -> Any:
    return or_(
        *[
            or_(
                col(JobPosting.title).ilike(f"%{_esc_like(p)}%", escape="\\"),
                col(JobPosting.description_raw).ilike(f"%{_esc_like(p)}%", escape="\\"),
            )
            for p in patterns
        ]
    )


def _add_text_and_industry_conds(conds: List[Any], f: JobFilters) -> None:
    if f.industry and f.industry.strip().lower() not in ("all", ""):
        kws = INDUSTRY_KEYWORDS.get(f.industry.strip().lower(), [f.industry.strip().lower()])
        conds.append(
            or_(
                *[
                    or_(
                        col(JobPosting.title).ilike(f"%{_esc_like(k)}%", escape="\\"),
                        col(JobPosting.description_raw).ilike(f"%{_esc_like(k)}%", escape="\\"),
                        col(JobPosting.company).ilike(f"%{_esc_like(k)}%", escape="\\"),
                    )
                    for k in kws
                ]
            )
        )
    if f.search and f.search.strip():
        tokens = [t for t in re.split(r"[\s,;]+", f.search.strip()) if len(t) >= 2][:6] or [f.search.strip()]
        for tok in tokens:
            kw = f"%{_esc_like(tok)}%"
            conds.append(
                or_(
                    col(JobPosting.title).ilike(kw, escape="\\"),
                    col(JobPosting.company).ilike(kw, escape="\\"),
                    col(JobPosting.description_raw).ilike(kw, escape="\\"),
                    col(JobPosting.match_rationale).ilike(kw, escape="\\"),
                )
            )
    if f.technology and f.technology.strip():
        for tech_tok in [t for t in re.split(r"[,;]+", f.technology.strip()) if t.strip()][:5]:
            conds.append(_or_title_desc([tech_tok.strip()]))
    if f.language and f.language.strip().lower() not in ("all", ""):
        lkw = f"%{_esc_like(f.language.strip())}%"
        conds.append(or_(col(JobPosting.description_raw).ilike(lkw, escape="\\"), cast(col(JobPosting.language_requirements), String).ilike(lkw, escape="\\")))


def _add_location_and_scope_conds(conds: List[Any], f: JobFilters, user_id: Optional[int]) -> None:
    if f.country and f.country.strip():
        c_clean = f.country.strip()
        ckw = f"%{_esc_like(c_clean)}%"
        c_fallbacks = [col(JobPosting.market).ilike(ckw, escape="\\")]
        if c_clean.lower() in ("georgia", "ge", "sakartvelo"):
            c_fallbacks.extend([col(JobPosting.market).ilike("GE%", escape="\\"), col(JobPosting.country).ilike("%GE%", escape="\\")])
        conds.append(or_(col(JobPosting.country).ilike(ckw, escape="\\"), and_(or_(col(JobPosting.country).is_(None), col(JobPosting.country) == ""), or_(*c_fallbacks))))
    if f.city and f.city.strip():
        city_kw = f"%{_esc_like(f.city.strip())}%"
        conds.append(or_(col(JobPosting.city).ilike(city_kw, escape="\\"), and_(or_(col(JobPosting.city).is_(None), col(JobPosting.city) == ""), or_(col(JobPosting.market).ilike(city_kw, escape="\\"), col(JobPosting.description_raw).ilike(city_kw, escape="\\")))))
    if f.remote_type and f.remote_type.upper() != "ALL":
        rt_up = f.remote_type.strip().upper()
        conds.append((col(JobPosting.is_remote) == True) if rt_up == "REMOTE" else (col(JobPosting.remote_type) == rt_up))
    if f.salary_min is not None and f.salary_min > 0:
        conds.append(col(JobPosting.salary_max) >= f.salary_min)
    if f.experience_level and f.experience_level.strip().lower() not in ("all", ""):
        conds.append(_or_title_desc(EXPERIENCE_PATTERNS.get(f.experience_level.strip().lower(), [f.experience_level.strip().lower()])))
    if f.employment_type and f.employment_type.strip().lower() not in ("all", ""):
        conds.append(_or_title_desc(EMPLOYMENT_PATTERNS.get(f.employment_type.strip().lower(), [f.employment_type.strip().lower()])))
    if f.only_saved and user_id is not None:
        conds.append(col(JobPosting.id).in_(select(SavedJob.job_posting_id).where(col(SavedJob.user_id) == user_id)))
    if f.only_new and user_id is not None:
        conds.append(col(JobPosting.id).not_in(select(ApplicationRecord.job_posting_id).where(col(ApplicationRecord.user_id) == user_id, col(ApplicationRecord.job_posting_id).is_not(None))))
    if f.b2b_only:
        conds.append(or_(col(JobPosting.portal).in_(B2B_PORTALS), col(JobPosting.market).in_(["GLOBAL_REMOTE", "INT_REMOTE", "EU_REMOTE"])))
    if f.posted_within_days is not None:
        conds.append(func.coalesce(col(JobPosting.published_at), col(JobPosting.scraped_at)) >= utc_now() - timedelta(days=f.posted_within_days))


PRE_APPLIED_TRACKER_STATUSES: Tuple[str, ...] = (
    "DISCOVERED", "SAVED", "STAGED", "AUDITED", "Discovered", "Saved",
)
POST_DISCOVERED_MATCH_STATUSES: Tuple[str, ...] = (
    "APPLIED", "SUBMITTED", "HR_SCREEN", "HR Screening",
    "INTERVIEW", "INTERVIEWING", "TECH_INTERVIEW", "Technical Interview",
    "FINAL_INTERVIEW", "FINAL_ROUND", "ASSESSMENT", "Assessment",
    "OFFER", "Offer", "REJECTED", "Rejected", "Applied", "Interviewing",
)


def _add_post_discovered_exclusion(conds: List[Any], f: JobFilters, status_col: Any, user_id: Optional[int]) -> None:
    """Hides vacancies already past Discovered (Applied, HR Screening, Interview, Offer, Rejected) with 0 extra queries."""
    if f.status and f.status.upper() not in ("ALL", "DISCOVERED", "STAGED", "AUDITED"):
        return
    conds.append(status_col.not_in(POST_DISCOVERED_MATCH_STATUSES))
    if user_id is None:
        return
    tracker_ids = select(ApplicationTracker.job_posting_id).where(
        col(ApplicationTracker.user_id) == user_id,
        col(ApplicationTracker.is_deleted) == False,
        col(ApplicationTracker.job_posting_id).is_not(None),
        col(ApplicationTracker.status).not_in(PRE_APPLIED_TRACKER_STATUSES),
    )
    tracker_urls = select(ApplicationTracker.job_url).where(
        col(ApplicationTracker.user_id) == user_id,
        col(ApplicationTracker.is_deleted) == False,
        col(ApplicationTracker.job_url).is_not(None),
        col(ApplicationTracker.job_url) != "",
        col(ApplicationTracker.status).not_in(PRE_APPLIED_TRACKER_STATUSES),
    )
    record_ids = select(ApplicationRecord.job_posting_id).where(
        col(ApplicationRecord.user_id) == user_id,
        col(ApplicationRecord.job_posting_id).is_not(None),
        col(ApplicationRecord.submission_status).not_in(PRE_APPLIED_TRACKER_STATUSES),
    )
    conds.append(col(JobPosting.id).not_in(tracker_ids))
    conds.append(col(JobPosting.id).not_in(record_ids))
    conds.append(col(JobPosting.url).not_in(tracker_urls))


def _build_base_conditions(f: JobFilters, use_user_matches: bool, score_col: Any, status_col: Any, user_id: Optional[int]) -> List[Any]:
    conds: List[Any] = [col(JobPosting.is_expired) == False]
    if use_user_matches and not f.include_dismissed:
        conds.append(col(UserJobMatch.is_ignored) == False)
    if not f.include_filtered:
        conds.append(status_col != "FILTERED_OUT")
    _add_post_discovered_exclusion(conds, f, status_col, user_id)
    if f.portal and f.portal.upper() != "ALL":
        conds.append(col(JobPosting.portal) == f.portal)
    if f.market and f.market.upper() != "ALL":
        conds.append(col(JobPosting.market) == f.market)
    if f.min_score is not None and f.min_score > 0:
        conds.append(score_col >= f.min_score)
    _add_text_and_industry_conds(conds, f)
    _add_location_and_scope_conds(conds, f, user_id)
    return conds


def _build_order_clauses(sort_by: str, score_col: Any) -> tuple[Any, Any]:
    freshness = func.coalesce(col(JobPosting.published_at), col(JobPosting.scraped_at))
    norm = (sort_by or "newest").strip().lower()
    if norm == "newest":
        return (freshness.desc(), score_col.desc())
    if norm == "salary_desc":
        return (func.coalesce(col(JobPosting.salary_max), col(JobPosting.salary_min), -1).desc(), freshness.desc())
    if norm == "company_asc":
        return (col(JobPosting.company).asc(), freshness.desc())
    return (score_col.desc(), freshness.desc())


def _normalize_djinni_and_salary(dumped: Dict[str, Any]) -> None:
    if str(dumped.get("salary_currency") or "").lower() in ("gel", "ლარი", "ᲚᲐᲠᲘ", "₾"):
        dumped["salary_currency"] = "GEL"
    dumped["company"] = sanitize_company_name(dumped.get("company"), target_email=dumped.get("target_email"), fallback="Employer")
    if dumped.get("portal") == "djinni.co" and dumped.get("title"):
        raw_t = str(dumped["title"])
        clean_t = _DJINNI_SALARY_TAIL_RE.sub("", _DJINNI_RESPONDS_RE.sub("", _DJINNI_FIRE_RE.sub("", raw_t)))
        if dumped.get("company") and len(dumped["company"]) > 2 and (ci := clean_t.find(f" {dumped['company']}")) > 4:
            clean_t = clean_t[:ci]
        dumped["title"] = _WHITESPACE_RE.sub(" ", clean_t).strip() or raw_t
        if dumped.get("salary_min") is None:
            sal_ex = salary_service.extract_explicit_salary(f"{raw_t}\n{dumped.get('description_raw', '')}")
            if sal_ex:
                dumped["salary_min"], dumped["salary_max"], dumped["salary_currency"] = sal_ex
                dumped["salary_is_estimated"] = dumped["salary_estimated_by_ai"] = False
    dumped["salary_source"] = "missing" if (dumped.get("salary_min") is None and dumped.get("salary_max") is None) else ("ai_estimated" if (dumped.get("salary_is_estimated") or dumped.get("salary_estimated_by_ai")) else "verified")
    if not dumped.get("posting_date"):
        dumped["posting_date"] = dumped.get("published_at") or dumped.get("scraped_at")
    if not (dumped.get("target_email") or "").strip():
        desc_blob = f"{dumped.get('description_raw') or ''}"
        for m_em in _EMAIL_IN_TEXT_RE.findall(desc_blob):
            em_low = m_em.lower()
            if em_low.startswith("noreply@") or em_low.startswith("no-reply@"):
                continue
            if any(em_low.endswith(f"@{dom}") for dom in _IGNORED_EMAIL_DOMAINS):
                continue
            dumped["target_email"] = m_em
            dumped["delivery_channel"] = "EMAIL"
            break


def _resolve_parsed_skills(profile: Any) -> Optional[Dict[str, Any]]:
    """Extracts parsed skills directly from the already-loaded CandidateProfile (0 extra DB queries)."""
    if profile is None:
        return None
    ps = getattr(profile, "parsed_skills", None)
    if isinstance(ps, dict) and ps:
        parsed = dict(ps)
        exp = getattr(profile, "experience_years", None)
        if exp is not None:
            parsed.setdefault("experience_years", exp)
            parsed.setdefault("years_experience", exp)
            parsed.setdefault("years_of_experience", exp)
        parsed.setdefault("verified_skills", parsed.get("all_skills") or [])
        return parsed
    raw_md = getattr(profile, "raw_markdown", None) or ""
    if raw_md.strip():
        return matcher_service.parse_skills_markdown(raw_md)
    return None


def _compute_explainability(
    dumped: Dict[str, Any],
    um: Any,
    parsed_skills: Optional[Dict[str, Any]],
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    matched = list(um.matched_skills or [])[:12] if um is not None else []
    missing = list(um.missing_skills or [])[:10] if um is not None else []
    title = str(dumped.get("title") or "")
    desc = str(dumped.get("description_raw") or "")
    if parsed_skills and not matched and not missing:
        req_skills = matcher_service.extract_job_requirements(title, desc)
        cand_skills = list(parsed_skills.get("all_skills") or parsed_skills.get("verified_skills") or [])
        cand_blob = " ".join(str(s) for s in cand_skills)
        for req in req_skills[:14]:
            if skills_match_token(req, cand_skills, cand_blob):
                if req not in matched:
                    matched.append(req)
            elif req not in missing:
                missing.append(req)
    gate_expl: List[Dict[str, Any]] = []
    if parsed_skills:
        gates = run_gate_pipeline(
            title=title,
            description=desc,
            parsed_skills=parsed_skills,
            portal=str(dumped.get("portal") or "generic"),
            company=str(dumped.get("company") or ""),
        )
        gate_expl = [
            {
                "gate": g.gate_name,
                "passed": g.passed,
                "reason": g.reason,
                "penalty": g.penalty,
                "metadata": g.metadata or {},
            }
            for g in gates
        ]
    return matched[:12], missing[:10], gate_expl


def _serialize_job_row(
    entry: Any,
    use_user_matches: bool,
    parsed_skills: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    r, um = entry if use_user_matches else (entry, None)
    dumped = r.model_dump(mode="json")
    if um is not None:
        dumped.update({
            "suitability_score": um.suitability_score,
            "match_score": um.match_score,
            "match_tier": um.match_tier or dumped.get("match_tier"),
            "adjacent_role_tag": um.adjacent_role_tag,
            "skill_overlap_pct": um.skill_overlap_pct,
            "status": um.status,
            "match_rationale": um.match_rationale or dumped.get("match_rationale"),
        })
    _normalize_djinni_and_salary(dumped)

    loc_text = ", ".join(str(dumped.get(k) or "").strip() for k in ("city", "country", "market") if dumped.get(k))
    geo_info = classify_georgia_b2b_suitability(
        title=str(dumped.get("title") or ""),
        description=str(dumped.get("description_raw") or ""),
        location_text=loc_text,
        portal=str(dumped.get("portal") or ""),
        market=str(dumped.get("market") or ""),
        salary_currency=dumped.get("salary_currency"),
    )
    dumped.update(geo_info)
    sal_meta = salary_service.detect_salary_metadata(f"{dumped.get('title') or ''}\n{dumped.get('description_raw') or ''}", dumped.get("salary_min"), dumped.get("salary_max"))
    dumped.update({"salary_period": sal_meta["salary_period"], "salary_gross_net": sal_meta["gross_net"], "normalized_monthly_min": sal_meta["normalized_monthly_min"], "normalized_monthly_max": sal_meta["normalized_monthly_max"]})

    mb = dict(um.match_breakdown or {}) if um is not None and isinstance(um.match_breakdown, dict) else {}
    desc_len = len(str(dumped.get("description_raw") or ""))
    matched_sk, missing_sk, gate_expl = _compute_explainability(dumped, um, parsed_skills)
    dumped["is_ignored"] = bool(um.is_ignored) if um is not None else False
    dumped["dismiss_reason"] = mb.get("dismiss_reason")
    dumped["matched_skills"] = matched_sk
    dumped["missing_skills"] = missing_sk
    dumped["match_explanation"] = gate_expl
    dumped["recommendation_breakdown"] = {
        "overall_relevance_score": round(float(dumped.get("suitability_score") or 0.0), 1),
        "score_disclaimer": "Heuristic profile-to-vacancy fit score (not a hiring probability).",
        "skills_match_pct": dumped.get("skill_overlap_pct"),
        "matched_skills": matched_sk,
        "missing_skills": missing_sk,
        "experience_compatibility": "Unknown experience requirement" if dumped.get("experience_min_years") is None else f"Requires ~{dumped.get('experience_min_years'):g}+ yr(s)",
        "location_compatibility": geo_info.get("contract_mode") or dumped.get("remote_type") or "UNKNOWN",
        "language_compatibility": ", ".join(dumped.get("language_requirements") or []) or "Not specified",
        "eligibility_restrictions": geo_info.get("eligibility_note") or "",
        "why_recommended": dumped.get("match_rationale") or "",
        "matching_confidence": "high" if desc_len >= 200 else ("medium" if desc_len >= 60 else "low"),
    }
    return dumped


def _maybe_rescore_first_time(session: Session, uid: int, owner: Optional[str]) -> bool:
    has_match = session.exec(select(UserJobMatch.id).where(UserJobMatch.user_id == uid).limit(1)).first()
    if has_match is None and session.exec(select(JobPosting.id).limit(1)).first() is not None:
        scraper_orchestrator.rescore_existing_jobs(owner_email=owner, user_id=uid)
        return True
    return False


def _query_geo_eligible(
    session: Session,
    f: JobFilters,
    base_conds: List[Any],
    order_clauses: tuple[Any, Any],
    use_user_matches: bool,
    uid: Optional[int],
    owner: Optional[str],
    parsed_skills: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    join_cond = and_(col(UserJobMatch.job_posting_id) == col(JobPosting.id), col(UserJobMatch.user_id) == uid)
    stmt: Any = select(JobPosting, UserJobMatch).join(UserJobMatch, join_cond) if use_user_matches else select(JobPosting)
    if base_conds:
        stmt = stmt.where(*base_conds)
    items_geo = [d for e in session.exec(stmt.order_by(*order_clauses)).all() if (d := _serialize_job_row(e, use_user_matches, parsed_skills)).get("georgia_eligible")]
    if use_user_matches and not items_geo and not f.only_saved and uid is not None and _maybe_rescore_first_time(session, uid, owner):
        items_geo = [d for e in session.exec(stmt.order_by(*order_clauses)).all() if (d := _serialize_job_row(e, use_user_matches, parsed_skills)).get("georgia_eligible")]

    tier_counts = {
        "ALL": len(items_geo),
        "DIRECT": sum(1 for it in items_geo if it.get("match_tier") == "DIRECT"),
        "ADJACENT": sum(1 for it in items_geo if it.get("match_tier") == "ADJACENT"),
        "PUBLIC_INTERNSHIP": sum(1 for it in items_geo if it.get("match_tier") == "PUBLIC_INTERNSHIP" or it.get("portal") == "hr.gov.ge"),
    }
    status_counts = {
        "ALL": len(items_geo),
        "STAGED": sum(1 for it in items_geo if it.get("status") == "STAGED"),
        "AUDITED": sum(1 for it in items_geo if it.get("status") == "AUDITED"),
    }
    t_low = (f.tier or "").strip().lower()
    filtered = [
        it for it in items_geo
        if (not f.status or f.status.upper() == "ALL" or it.get("status") == f.status)
        and (
            not t_low or t_low == "all"
            or (t_low == "direct" and it.get("match_tier") == "DIRECT")
            or (t_low == "adjacent" and it.get("match_tier") == "ADJACENT")
            or (t_low in ("internship", "public_internship") and (it.get("match_tier") == "PUBLIC_INTERNSHIP" or it.get("portal") == "hr.gov.ge"))
        )
    ]
    offset = (f.page - 1) * f.limit
    deduped = cluster_cross_portal_jobs(filtered)
    return {"items": deduped[offset : offset + f.limit], "total": len(deduped), "page": f.page, "limit": f.limit, "total_pages": max(1, math.ceil(len(deduped) / f.limit)), "tier_counts": tier_counts, "status_counts": status_counts}


def _canonical_job_url_key(url: Any) -> str:
    raw = str(url or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"^https?://(?:www\.)?", "", raw).rstrip("/")
    m_jge = _JOBS_GE_ID_RE.search(raw)
    if m_jge:
        return f"jobs.ge/id={m_jge.group(1)}"
    return raw


def _canonical_company_title_key(company: Any, title: Any) -> Optional[Tuple[str, str]]:
    comp = _LEGAL_SUFFIX_RE.sub("", str(company or "").lower())
    comp = re.sub(r"[^a-z0-9\u10A0-\u10FF]+", " ", comp).strip()
    t = re.sub(r"[^a-z0-9\u10A0-\u10FF]+", " ", str(title or "").lower()).strip()
    if not comp or not t or comp in ("hiring company", "unknown", "confidential", "company", "employer"):
        return None
    return (comp, t)


def cluster_cross_portal_jobs(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicates vacancies by canonical URL (including jobs.ge /ge/ vs /en/) AND normalized (company, title).
    Preserves target_email/EMAIL channel and higher suitability_score when merging duplicates.
    """
    clustered: List[Dict[str, Any]] = []
    by_url: Dict[str, Dict[str, Any]] = {}
    by_ct: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for raw in items:
        item = dict(raw)
        item.setdefault("also_on_portals", [])
        portal = str(item.get("portal") or "").strip()
        url_key = _canonical_job_url_key(item.get("url"))
        ct_key = _canonical_company_title_key(item.get("company"), item.get("title"))

        primary = by_url.get(url_key) if url_key else None
        if primary is None and ct_key is not None:
            primary = by_ct.get(ct_key)

        if primary is None:
            clustered.append(item)
            if url_key:
                by_url[url_key] = item
            if ct_key is not None:
                by_ct[ct_key] = item
        else:
            if portal and portal != primary.get("portal") and portal not in primary["also_on_portals"]:
                primary["also_on_portals"].append(portal)
            if not primary.get("target_email") and item.get("target_email"):
                primary["target_email"] = item["target_email"]
                primary["delivery_channel"] = "EMAIL"
            if float(item.get("suitability_score") or 0.0) > float(primary.get("suitability_score") or 0.0):
                primary["suitability_score"] = item["suitability_score"]
    return clustered


def query_jobs_paginated(filters: JobFilters, current_user: User, is_profile_ready_fn: Any) -> Dict[str, Any]:
    """Executes user-scoped paginated job discovery with single-query tier/status aggregation."""
    init_db()
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    uid = current_user.id if owner else None
    profile = ground_truth_store.get_profile_record(owner_email=owner, user_id=current_user.id)

    with Session(engine) as session:
        if not is_profile_ready_fn(profile, current_user.email):
            return {"items": [], "total": 0, "page": filters.page, "limit": filters.limit, "total_pages": 1, "tier_counts": {"ALL": 0, "DIRECT": 0, "ADJACENT": 0, "PUBLIC_INTERNSHIP": 0}, "status_counts": {"ALL": 0, "STAGED": 0, "AUDITED": 0}}

        use_um = uid is not None
        score_col: Any = col(UserJobMatch.suitability_score) if use_um else col(JobPosting.suitability_score)
        status_col: Any = col(UserJobMatch.status) if use_um else col(JobPosting.status)
        tier_col: Any = col(UserJobMatch.match_tier) if use_um else col(JobPosting.match_tier)
        join_cond = and_(col(UserJobMatch.job_posting_id) == col(JobPosting.id), col(UserJobMatch.user_id) == uid)

        parsed_skills = _resolve_parsed_skills(profile)
        base_conds = _build_base_conditions(filters, use_um, score_col, status_col, current_user.id)
        order_clauses = _build_order_clauses(filters.sort_by, score_col)
        if filters.geo_eligible_only:
            return _query_geo_eligible(session, filters, base_conds, order_clauses, use_um, uid, owner, parsed_skills)

        agg_stmt: Any = sa_select(
            func.count().label("all_cnt"),
            func.sum(case((tier_col == "DIRECT", 1), else_=0)).label("direct_cnt"),
            func.sum(case((tier_col == "ADJACENT", 1), else_=0)).label("adjacent_cnt"),
            func.sum(case((or_(tier_col == "PUBLIC_INTERNSHIP", col(JobPosting.portal) == "hr.gov.ge"), 1), else_=0)).label("intern_cnt"),
            func.sum(case((status_col == "STAGED", 1), else_=0)).label("staged_cnt"),
            func.sum(case((status_col == "AUDITED", 1), else_=0)).label("audited_cnt"),
        ).select_from(JobPosting)
        if use_um:
            agg_stmt = agg_stmt.join(UserJobMatch, join_cond)
        if base_conds:
            agg_stmt = agg_stmt.where(*base_conds)

        agg_row = session.exec(agg_stmt).one()
        if use_um and int(agg_row.all_cnt or 0) == 0 and not filters.only_saved and uid is not None and _maybe_rescore_first_time(session, uid, owner):
            agg_row = session.exec(agg_stmt).one()

        all_cnt = int(agg_row[0] or 0)
        conditions = list(base_conds)
        extra = False
        if filters.status and filters.status.upper() != "ALL":
            conditions.append(status_col == filters.status)
            extra = True
        t_low = (filters.tier or "").strip().lower()
        if t_low and t_low != "all":
            extra = True
            if t_low == "direct":
                conditions.append(tier_col == "DIRECT")
            elif t_low == "adjacent":
                conditions.append(tier_col == "ADJACENT")
            elif t_low in ("internship", "public_internship"):
                conditions.append(or_(tier_col == "PUBLIC_INTERNSHIP", col(JobPosting.portal) == "hr.gov.ge"))

        if extra:
            c_stmt: Any = select(func.count()).select_from(JobPosting)
            if use_um:
                c_stmt = c_stmt.join(UserJobMatch, join_cond)
            total = int(session.exec(c_stmt.where(*conditions)).one() or 0)
        else:
            total = all_cnt

        stmt: Any = select(JobPosting, UserJobMatch).join(UserJobMatch, join_cond) if use_um else select(JobPosting)
        rows = session.exec(stmt.where(*conditions).order_by(*order_clauses).offset((filters.page - 1) * filters.limit).limit(filters.limit)).all()
        return {
            "items": cluster_cross_portal_jobs([_serialize_job_row(e, use_um, parsed_skills) for e in rows]),
            "total": total,
            "page": filters.page,
            "limit": filters.limit,
            "total_pages": max(1, math.ceil(total / filters.limit)),
            "tier_counts": {"ALL": all_cnt, "DIRECT": int(agg_row[1] or 0), "ADJACENT": int(agg_row[2] or 0), "PUBLIC_INTERNSHIP": int(agg_row[3] or 0)},
            "status_counts": {"ALL": all_cnt, "STAGED": int(agg_row[4] or 0), "AUDITED": int(agg_row[5] or 0)},
        }
