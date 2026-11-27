import math
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
from fastapi import Query
from sqlalchemy import String, case, cast, func
from sqlmodel import Session, and_, or_, select

from ..db.database import engine, init_db
from ..db.models import ApplicationRecord, JobPosting, SavedJob, User, UserJobMatch, utc_now
from ..db.profile_repository import ground_truth_store
from .salary_service import salary_service
from .scrapers.base_scraper import classify_georgia_b2b_suitability, sanitize_company_name
from .scrapers.scraper_orchestrator import scraper_orchestrator

_DJINNI_FIRE_RE = re.compile(r"🔥\s*|\s*⚡\s*")
_DJINNI_RESPONDS_RE = re.compile(r"\bResponds\s+to\s+\d+%.*$", re.I)
_DJINNI_SALARY_TAIL_RE = re.compile(r"\s+(?:to|up\s+to|from)?\s*[\$€£]\s*\d[\d,]*(?:\s*-\s*[\$€£]?\d[\d,]*)?.*$", re.I)
_WHITESPACE_RE = re.compile(r"\s+")

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
                JobPosting.title.ilike(f"%{_esc_like(p)}%", escape="\\"),
                JobPosting.description_raw.ilike(f"%{_esc_like(p)}%", escape="\\"),
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
                        JobPosting.title.ilike(f"%{_esc_like(k)}%", escape="\\"),
                        JobPosting.description_raw.ilike(f"%{_esc_like(k)}%", escape="\\"),
                        JobPosting.company.ilike(f"%{_esc_like(k)}%", escape="\\"),
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
                    JobPosting.title.ilike(kw, escape="\\"),
                    JobPosting.company.ilike(kw, escape="\\"),
                    JobPosting.description_raw.ilike(kw, escape="\\"),
                    JobPosting.match_rationale.ilike(kw, escape="\\"),
                )
            )
    if f.technology and f.technology.strip():
        for tech_tok in [t for t in re.split(r"[,;]+", f.technology.strip()) if t.strip()][:5]:
            conds.append(_or_title_desc([tech_tok.strip()]))
    if f.language and f.language.strip().lower() not in ("all", ""):
        lkw = f"%{_esc_like(f.language.strip())}%"
        conds.append(or_(JobPosting.description_raw.ilike(lkw, escape="\\"), cast(JobPosting.language_requirements, String).ilike(lkw, escape="\\")))


def _add_location_and_scope_conds(conds: List[Any], f: JobFilters, user_id: Optional[int]) -> None:
    if f.country and f.country.strip():
        c_clean = f.country.strip()
        ckw = f"%{_esc_like(c_clean)}%"
        c_fallbacks = [JobPosting.market.ilike(ckw, escape="\\")]
        if c_clean.lower() in ("georgia", "ge", "sakartvelo"):
            c_fallbacks.extend([JobPosting.market.ilike("GE%", escape="\\"), JobPosting.country.ilike("%GE%", escape="\\")])
        conds.append(or_(JobPosting.country.ilike(ckw, escape="\\"), and_(or_(JobPosting.country.is_(None), JobPosting.country == ""), or_(*c_fallbacks))))
    if f.city and f.city.strip():
        city_kw = f"%{_esc_like(f.city.strip())}%"
        conds.append(or_(JobPosting.city.ilike(city_kw, escape="\\"), and_(or_(JobPosting.city.is_(None), JobPosting.city == ""), or_(JobPosting.market.ilike(city_kw, escape="\\"), JobPosting.description_raw.ilike(city_kw, escape="\\")))))
    if f.remote_type and f.remote_type.upper() != "ALL":
        rt_up = f.remote_type.strip().upper()
        conds.append((JobPosting.is_remote == True) if rt_up == "REMOTE" else (JobPosting.remote_type == rt_up))
    if f.salary_min is not None and f.salary_min > 0:
        conds.append(JobPosting.salary_max >= f.salary_min)
    if f.experience_level and f.experience_level.strip().lower() not in ("all", ""):
        conds.append(_or_title_desc(EXPERIENCE_PATTERNS.get(f.experience_level.strip().lower(), [f.experience_level.strip().lower()])))
    if f.employment_type and f.employment_type.strip().lower() not in ("all", ""):
        conds.append(_or_title_desc(EMPLOYMENT_PATTERNS.get(f.employment_type.strip().lower(), [f.employment_type.strip().lower()])))
    if f.only_saved and user_id is not None:
        conds.append(JobPosting.id.in_(select(SavedJob.job_posting_id).where(SavedJob.user_id == user_id)))
    if f.only_new and user_id is not None:
        conds.append(JobPosting.id.not_in(select(ApplicationRecord.job_posting_id).where(ApplicationRecord.user_id == user_id, ApplicationRecord.job_posting_id.is_not(None))))
    if f.b2b_only:
        conds.append(or_(JobPosting.portal.in_(B2B_PORTALS), JobPosting.market.in_(["GLOBAL_REMOTE", "INT_REMOTE", "EU_REMOTE"])))
    if f.posted_within_days is not None:
        conds.append(func.coalesce(JobPosting.published_at, JobPosting.scraped_at) >= utc_now() - timedelta(days=f.posted_within_days))


def _build_base_conditions(f: JobFilters, use_user_matches: bool, score_col: Any, status_col: Any, user_id: Optional[int]) -> List[Any]:
    conds: List[Any] = [JobPosting.is_expired == False]
    if use_user_matches and not f.include_dismissed:
        conds.append(UserJobMatch.is_ignored == False)
    if not f.include_filtered:
        conds.append(status_col != "FILTERED_OUT")
    if f.portal and f.portal.upper() != "ALL":
        conds.append(JobPosting.portal == f.portal)
    if f.market and f.market.upper() != "ALL":
        conds.append(JobPosting.market == f.market)
    if f.min_score is not None and f.min_score > 0:
        conds.append(score_col >= f.min_score)
    _add_text_and_industry_conds(conds, f)
    _add_location_and_scope_conds(conds, f, user_id)
    return conds


def _build_order_clauses(sort_by: str, score_col: Any) -> tuple[Any, Any]:
    freshness = func.coalesce(JobPosting.published_at, JobPosting.scraped_at)
    norm = (sort_by or "newest").strip().lower()
    if norm == "newest":
        return (freshness.desc(), score_col.desc())
    if norm == "salary_desc":
        return (func.coalesce(JobPosting.salary_max, JobPosting.salary_min, -1).desc(), freshness.desc())
    if norm == "company_asc":
        return (JobPosting.company.asc(), freshness.desc())
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


def _serialize_job_row(entry: Any, use_user_matches: bool) -> Dict[str, Any]:
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
    dumped["is_ignored"] = bool(um.is_ignored) if um is not None else False
    dumped["dismiss_reason"] = mb.get("dismiss_reason")
    dumped["recommendation_breakdown"] = {
        "overall_relevance_score": round(float(dumped.get("suitability_score") or 0.0), 1),
        "score_disclaimer": "Heuristic profile-to-vacancy fit score (not a hiring probability).",
        "skills_match_pct": dumped.get("skill_overlap_pct"),
        "matched_skills": list(um.matched_skills or [])[:12] if um is not None else [],
        "missing_skills": list(um.missing_skills or [])[:10] if um is not None else [],
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


def _query_geo_eligible(session: Session, f: JobFilters, base_conds: List[Any], order_clauses: tuple[Any, Any], use_user_matches: bool, uid: Optional[int], owner: Optional[str]) -> Dict[str, Any]:
    stmt = select(JobPosting, UserJobMatch).join(UserJobMatch, (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == uid)) if use_user_matches else select(JobPosting)
    if base_conds:
        stmt = stmt.where(*base_conds)
    items_geo = [d for e in session.exec(stmt.order_by(*order_clauses)).all() if (d := _serialize_job_row(e, use_user_matches)).get("georgia_eligible")]
    if use_user_matches and not items_geo and not f.only_saved and uid is not None and _maybe_rescore_first_time(session, uid, owner):
        items_geo = [d for e in session.exec(stmt.order_by(*order_clauses)).all() if (d := _serialize_job_row(e, use_user_matches)).get("georgia_eligible")]

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
    return {"items": filtered[offset : offset + f.limit], "total": len(filtered), "page": f.page, "limit": f.limit, "total_pages": max(1, math.ceil(len(filtered) / f.limit)), "tier_counts": tier_counts, "status_counts": status_counts}


def cluster_cross_portal_jobs(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Clusters duplicate vacancies across portals by normalized (company, title).
    Keeps the primary card (highest order rank) and attaches `also_on_portals` listing other portals.
    """
    clustered: List[Dict[str, Any]] = []
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for raw in items:
        item = dict(raw)
        item.setdefault("also_on_portals", [])
        comp = re.sub(r"[^a-z0-9\u10A0-\u10FF]+", " ", str(item.get("company") or "").lower()).strip()
        title = re.sub(r"[^a-z0-9\u10A0-\u10FF]+", " ", str(item.get("title") or "").lower()).strip()
        portal = str(item.get("portal") or "").strip()
        if not comp or not title or comp in ("hiring company", "unknown", "confidential", "company"):
            clustered.append(item)
            continue
        key = (comp, title)
        if key not in by_key:
            by_key[key] = item
            clustered.append(item)
        else:
            primary = by_key[key]
            if portal and portal != primary.get("portal") and portal not in primary["also_on_portals"]:
                primary["also_on_portals"].append(portal)
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
        score_col = UserJobMatch.suitability_score if use_um else JobPosting.suitability_score
        status_col = UserJobMatch.status if use_um else JobPosting.status
        tier_col = UserJobMatch.match_tier if use_um else JobPosting.match_tier

        base_conds = _build_base_conditions(filters, use_um, score_col, status_col, current_user.id)
        order_clauses = _build_order_clauses(filters.sort_by, score_col)
        if filters.geo_eligible_only:
            return _query_geo_eligible(session, filters, base_conds, order_clauses, use_um, uid, owner)

        agg_stmt = select(
            func.count().label("all_cnt"),
            func.sum(case((tier_col == "DIRECT", 1), else_=0)).label("direct_cnt"),
            func.sum(case((tier_col == "ADJACENT", 1), else_=0)).label("adjacent_cnt"),
            func.sum(case(((tier_col == "PUBLIC_INTERNSHIP") | (JobPosting.portal == "hr.gov.ge"), 1), else_=0)).label("intern_cnt"),
            func.sum(case((status_col == "STAGED", 1), else_=0)).label("staged_cnt"),
            func.sum(case((status_col == "AUDITED", 1), else_=0)).label("audited_cnt"),
        ).select_from(JobPosting)
        if use_um:
            agg_stmt = agg_stmt.join(UserJobMatch, (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == uid))
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
                conditions.append((tier_col == "PUBLIC_INTERNSHIP") | (JobPosting.portal == "hr.gov.ge"))

        if extra:
            c_stmt = select(func.count()).select_from(JobPosting)
            if use_um:
                c_stmt = c_stmt.join(UserJobMatch, (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == uid))
            total = int(session.exec(c_stmt.where(*conditions)).one() or 0)
        else:
            total = all_cnt

        stmt = select(JobPosting, UserJobMatch).join(UserJobMatch, (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == uid)) if use_um else select(JobPosting)
        rows = session.exec(stmt.where(*conditions).order_by(*order_clauses).offset((filters.page - 1) * filters.limit).limit(filters.limit)).all()
        return {
            "items": cluster_cross_portal_jobs([_serialize_job_row(e, use_um) for e in rows]),
            "total": total,
            "page": filters.page,
            "limit": filters.limit,
            "total_pages": max(1, math.ceil(total / filters.limit)),
            "tier_counts": {"ALL": all_cnt, "DIRECT": int(agg_row[1] or 0), "ADJACENT": int(agg_row[2] or 0), "PUBLIC_INTERNSHIP": int(agg_row[3] or 0)},
            "status_counts": {"ALL": all_cnt, "STAGED": int(agg_row[4] or 0), "AUDITED": int(agg_row[5] or 0)},
        }
