import re
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Tuple

from .cv_parser_service import cv_parser_service
from .matcher_service import matcher_service

SKILL_ALIAS_GROUPS: Dict[str, str] = {
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "ms excel": "excel",
    "microsoft excel": "excel",
    "excel": "excel",
    "rest": "rest api",
    "rest api": "rest api",
    "restful api": "rest api",
    "ci/cd": "ci/cd",
    "cicd": "ci/cd",
    "qa": "quality assurance",
    "quality assurance": "quality assurance",
    "ml": "machine learning",
    "machine learning": "machine learning",
    "powerbi": "power bi",
    "power bi": "power bi",
    "node": "node.js",
    "nodejs": "node.js",
    "node.js": "node.js",
    "react.js": "react",
    "reactjs": "react",
    "react": "react",
}

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _extract_year_bounds(start_str: Optional[str], end_str: Optional[str], dates_str: Optional[str] = None) -> Tuple[Optional[int], Optional[int], bool]:
    s_raw = str(start_str or "").strip()
    e_raw = str(end_str or "").strip()
    d_raw = str(dates_str or "").strip()
    is_present = any(w in (e_raw + " " + d_raw).lower() for w in ("present", "current", "now", "დღემდე"))

    s_years = [int(y) for y in _YEAR_RE.findall(s_raw)]
    e_years = [int(y) for y in _YEAR_RE.findall(e_raw)]
    if s_years or e_years:
        return (s_years[0] if s_years else None), (e_years[-1] if e_years else None), is_present

    d_years = [int(y) for y in _YEAR_RE.findall(d_raw)]
    if len(d_years) >= 2:
        return d_years[0], d_years[-1], is_present
    if len(d_years) == 1:
        return d_years[0], (None if is_present else d_years[0]), is_present
    return None, None, is_present


def build_import_preview(
    raw_bytes: bytes,
    filename: str,
    existing_gt: Dict[str, Any],
) -> Dict[str, Any]:
    """Extracts structured candidate sections from an uploaded document WITHOUT mutating saved profile data."""
    from ..db.profile_repository import ground_truth_store

    md_text = cv_parser_service.extract_text_from_bytes(raw_bytes, filename=filename)
    parsed = ground_truth_store.parse_profile_from_md(md_text)
    taxonomy = matcher_service.parse_skills_markdown(md_text)

    full_name = str(parsed.get("full_name") or "").strip()
    name_parts = full_name.split()
    loc_str = str(parsed.get("location") or "").strip()
    loc_parts = [p.strip() for p in loc_str.split(",") if p.strip()]

    extracted_skills = list(dict.fromkeys([
        str(s).strip()
        for s in (parsed.get("skills") or taxonomy.get("all_skills") or [])
        if str(s).strip()
    ]))
    extracted_work = parsed.get("work_history") if isinstance(parsed.get("work_history"), list) else []
    extracted_edu = parsed.get("education") if isinstance(parsed.get("education"), list) else (
        taxonomy.get("education") if isinstance(taxonomy.get("education"), list) else []
    )
    extracted_projects = parsed.get("projects") if isinstance(parsed.get("projects"), list) else []
    extracted_certs = parsed.get("certifications") if isinstance(parsed.get("certifications"), list) else (
        taxonomy.get("courses_and_certifications") if isinstance(taxonomy.get("courses_and_certifications"), list) else []
    )
    extracted_langs = parsed.get("languages") if isinstance(parsed.get("languages"), list) else []

    extracted_payload = {
        "candidate": {
            "full_name": full_name,
            "first_name": name_parts[0] if name_parts else "",
            "last_name": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
            "headline": str(parsed.get("headline") or taxonomy.get("primary_role") or "").strip(),
            "summary": str(parsed.get("summary") or "").strip(),
            "email": str(parsed.get("email") or "").strip(),
            "phone": str(parsed.get("phone") or "").strip(),
            "location": {
                "city": loc_parts[0] if loc_parts else "",
                "country": loc_parts[1] if len(loc_parts) > 1 else "",
            },
            "links": {
                "linkedin": str(parsed.get("linkedin_url") or "").strip(),
                "github": str(parsed.get("github_url") or "").strip(),
                "portfolio": "",
            },
            "languages": extracted_langs,
        },
        "skills": {"core": extracted_skills, "secondary": []},
        "work_history": extracted_work,
        "education": extracted_edu,
        "projects": extracted_projects,
        "certifications": extracted_certs,
        "raw_markdown": md_text,
    }

    existing_skills_low = {s.lower() for s in ((existing_gt.get("skills") or {}).get("core") or [])}
    new_skills = [s for s in extracted_skills if s.lower() not in existing_skills_low]
    existing_wh = existing_gt.get("work_history") or []
    existing_edu = existing_gt.get("education") or []
    existing_proj = existing_gt.get("projects") or []
    existing_certs = existing_gt.get("certifications") or []

    return {
        "filename": filename,
        "extracted": extracted_payload,
        "diff_summary": {
            "existing_skills_count": len(existing_skills_low),
            "extracted_skills_count": len(extracted_skills),
            "new_skills_count": len(new_skills),
            "existing_work_count": len(existing_wh),
            "extracted_work_count": len(extracted_work),
            "existing_education_count": len(existing_edu),
            "extracted_education_count": len(extracted_edu),
            "existing_projects_count": len(existing_proj),
            "extracted_projects_count": len(extracted_projects),
            "existing_certifications_count": len(existing_certs),
            "extracted_certifications_count": len(extracted_certs),
            "existing_has_data": bool(existing_skills_low or existing_wh or existing_edu),
        },
        "recommended_modes": {
            "candidate": "merge" if existing_gt.get("candidate", {}).get("full_name") else "replace",
            "skills": "merge",
            "work_history": "merge",
            "education": "merge",
            "projects": "merge",
            "certifications": "merge",
            "languages": "merge",
        },
        "raw_text_preview": md_text[:2500],
    }


def apply_import_merge(
    existing_gt: Dict[str, Any],
    extracted: Dict[str, Any],
    section_modes: Optional[Dict[str, str]] = None,
    source_filename: str = "imported_cv",
) -> Dict[str, Any]:
    """
    Merges candidate-approved extracted sections into existing ground truth according to explicit per-section modes:
    - 'merge': preserve existing values and append only non-duplicate extracted items / fill blank scalar fields
    - 'replace': replace section with reviewed extracted values
    - 'skip': leave existing section untouched
    """
    modes = {
        "candidate": "merge",
        "skills": "merge",
        "work_history": "merge",
        "education": "merge",
        "projects": "merge",
        "certifications": "merge",
        "languages": "merge",
        **(section_modes or {}),
    }

    merged = dict(existing_gt or {})
    cur_cand = dict(merged.get("candidate") or {})
    ext_cand = dict(extracted.get("candidate") or {})

    cand_mode = modes.get("candidate", "merge")
    if cand_mode != "skip":
        for field in ("full_name", "first_name", "last_name", "headline", "summary", "email", "phone"):
            ext_val = str(ext_cand.get(field) or "").strip()
            cur_val = str(cur_cand.get(field) or "").strip()
            if cand_mode == "replace" and ext_val:
                cur_cand[field] = ext_val
            elif cand_mode == "merge" and not cur_val and ext_val:
                cur_cand[field] = ext_val

        cur_loc = dict(cur_cand.get("location") or {})
        ext_loc = dict(ext_cand.get("location") or {})
        for lf in ("city", "country"):
            ev = str(ext_loc.get(lf) or "").strip()
            cv = str(cur_loc.get(lf) or "").strip()
            if (cand_mode == "replace" and ev) or (cand_mode == "merge" and not cv and ev):
                cur_loc[lf] = ev
        cur_cand["location"] = cur_loc

        cur_links = dict(cur_cand.get("links") or {})
        ext_links = dict(ext_cand.get("links") or {})
        for lk in ("linkedin", "github", "portfolio"):
            ev = str(ext_links.get(lk) or "").strip()
            cv = str(cur_links.get(lk) or "").strip()
            if (cand_mode == "replace" and ev) or (cand_mode == "merge" and not cv and ev):
                cur_links[lk] = ev
        cur_cand["links"] = cur_links

    lang_mode = modes.get("languages", "merge")
    cur_langs = list(cur_cand.get("languages") or [])
    ext_langs = list(ext_cand.get("languages") or extracted.get("languages") or [])
    if lang_mode == "replace":
        cur_cand["languages"] = ext_langs
    elif lang_mode == "merge" and ext_langs:
        seen_lang = {str(x.get("language") or "").strip().lower() for x in cur_langs if isinstance(x, dict)}
        for item in ext_langs:
            if isinstance(item, dict):
                lk = str(item.get("language") or "").strip().lower()
                if lk and lk not in seen_lang:
                    cur_langs.append(item)
                    seen_lang.add(lk)
        cur_cand["languages"] = cur_langs

    merged["candidate"] = cur_cand

    # Skills
    sk_mode = modes.get("skills", "merge")
    cur_skills = dict(merged.get("skills") or {"core": [], "secondary": []})
    cur_core = [str(s).strip() for s in (cur_skills.get("core") or []) if str(s).strip()]
    ext_core = [str(s).strip() for s in ((extracted.get("skills") or {}).get("core") or []) if str(s).strip()]
    if sk_mode == "replace":
        cur_skills["core"] = ext_core
    elif sk_mode == "merge":
        seen_sk = {s.lower() for s in cur_core}
        for s in ext_core:
            if s.lower() not in seen_sk:
                cur_core.append(s)
                seen_sk.add(s.lower())
        cur_skills["core"] = cur_core
    merged["skills"] = cur_skills

    # Work history
    wh_mode = modes.get("work_history", "merge")
    cur_wh = list(merged.get("work_history") or [])
    ext_wh = list(extracted.get("work_history") or [])
    if wh_mode == "replace":
        merged["work_history"] = ext_wh
    elif wh_mode == "merge":
        seen_wh = {
            (str(w.get("role") or "").strip().lower(), str(w.get("company") or "").strip().lower())
            for w in cur_wh
            if isinstance(w, dict)
        }
        for w in ext_wh:
            if isinstance(w, dict):
                key = (str(w.get("role") or "").strip().lower(), str(w.get("company") or "").strip().lower())
                if any(key) and key not in seen_wh:
                    cur_wh.append(w)
                    seen_wh.add(key)
        merged["work_history"] = cur_wh

    # Education
    edu_mode = modes.get("education", "merge")
    cur_edu = list(merged.get("education") or [])
    ext_edu = list(extracted.get("education") or [])
    if edu_mode == "replace":
        merged["education"] = ext_edu
    elif edu_mode == "merge":
        seen_edu = {
            (str(e.get("degree") or "").strip().lower(), str(e.get("institution") or "").strip().lower())
            for e in cur_edu
            if isinstance(e, dict)
        }
        for e in ext_edu:
            if isinstance(e, dict):
                key = (str(e.get("degree") or "").strip().lower(), str(e.get("institution") or "").strip().lower())
                if any(key) and key not in seen_edu:
                    cur_edu.append(e)
                    seen_edu.add(key)
        merged["education"] = cur_edu

    # Projects
    proj_mode = modes.get("projects", "merge")
    cur_proj = list(merged.get("projects") or [])
    ext_proj = list(extracted.get("projects") or [])
    if proj_mode == "replace":
        merged["projects"] = ext_proj
    elif proj_mode == "merge":
        seen_proj = {str(p.get("title") or "").strip().lower() for p in cur_proj if isinstance(p, dict)}
        for p in ext_proj:
            if isinstance(p, dict):
                tk = str(p.get("title") or "").strip().lower()
                if tk and tk not in seen_proj:
                    cur_proj.append(p)
                    seen_proj.add(tk)
        merged["projects"] = cur_proj

    # Certifications
    cert_mode = modes.get("certifications", "merge")
    cur_certs = [str(c).strip() for c in (merged.get("certifications") or []) if str(c).strip()]
    ext_certs = [str(c).strip() for c in (extracted.get("certifications") or []) if str(c).strip()]
    if cert_mode == "replace":
        merged["certifications"] = ext_certs
    elif cert_mode == "merge":
        seen_c = {c.lower() for c in cur_certs}
        for c in ext_certs:
            if c.lower() not in seen_c:
                cur_certs.append(c)
                seen_c.add(c.lower())
        merged["certifications"] = cur_certs

    merged["import_provenance"] = {
        "source_filename": source_filename,
        "imported_at": datetime.now(UTC).isoformat(),
        "modes": modes,
        "reviewed_by_candidate": True,
    }
    merged["profile_status"] = "reviewed"
    if extracted.get("raw_markdown") and not merged.get("skills_md_raw"):
        merged["skills_md_raw"] = str(extracted["raw_markdown"])
    return merged


def compute_profile_intelligence(
    gt_data: Dict[str, Any],
    parsed_skills: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Computes completeness, duplicate skill groups, experience/education timeline warnings, and provenance."""
    ps = parsed_skills if isinstance(parsed_skills, dict) else (gt_data.get("parsed_skills_taxonomy") or {})
    completeness_score, missing_fields = cv_parser_service.compute_missing_fields(gt_data)

    core_skills = [str(s).strip() for s in ((gt_data.get("skills") or {}).get("core") or []) if str(s).strip()]
    canonical_buckets: Dict[str, List[str]] = {}
    for sk in core_skills:
        low = sk.lower()
        canon = SKILL_ALIAS_GROUPS.get(low, re.sub(r"[\s._-]+", " ", low).strip())
        canonical_buckets.setdefault(canon, []).append(sk)
    duplicate_skills = [
        {"canonical": canon, "variants": variants}
        for canon, variants in canonical_buckets.items()
        if len(variants) > 1
    ]

    now_year = datetime.now(UTC).year
    timeline_warnings: List[Dict[str, str]] = []
    current_roles_count = 0
    for job in gt_data.get("work_history") or []:
        if not isinstance(job, dict):
            continue
        label = f"{job.get('role') or 'Role'} at {job.get('company') or 'Company'}"
        s_yr, e_yr, is_pres = _extract_year_bounds(job.get("start_date"), job.get("end_date"))
        if job.get("is_current") or is_pres:
            current_roles_count += 1
        if s_yr is None and e_yr is None:
            timeline_warnings.append({
                "section": "work_history",
                "severity": "info",
                "message": f"Missing dates for '{label}'. Add start/end dates for accurate experience calculation.",
            })
        elif s_yr is not None and e_yr is not None and e_yr < s_yr:
            timeline_warnings.append({
                "section": "work_history",
                "severity": "warning",
                "message": f"End year ({e_yr}) precedes start year ({s_yr}) for '{label}'.",
            })
        if s_yr is not None and s_yr > now_year + 1:
            timeline_warnings.append({
                "section": "work_history",
                "severity": "warning",
                "message": f"Start year ({s_yr}) is in the future for '{label}'.",
            })
    if current_roles_count > 1:
        timeline_warnings.append({
            "section": "work_history",
            "severity": "info",
            "message": f"{current_roles_count} roles are marked as current/Present. Confirm if concurrent or update past end dates.",
        })

    for edu in gt_data.get("education") or []:
        if not isinstance(edu, dict):
            continue
        label = str(edu.get("degree") or edu.get("institution") or "Education entry")
        s_yr, e_yr, _ = _extract_year_bounds(edu.get("start_year"), edu.get("end_year"), edu.get("dates"))
        if s_yr is not None and e_yr is not None and e_yr < s_yr:
            timeline_warnings.append({
                "section": "education",
                "severity": "warning",
                "message": f"Graduation year ({e_yr}) precedes start year ({s_yr}) for '{label}'.",
            })

    recommendations: List[str] = []
    rec_map = {
        "full_name": "Add your full name so CVs and cover letters use your real identity.",
        "email": "Add a valid contact email for employer replies and CV headers.",
        "phone": "Add a phone number for recruiter screening calls.",
        "location": "Add your city and country to improve local and remote eligibility accuracy.",
        "skills": "Add at least 5 verified core skills to power job matching.",
        "work_history": "Add work experience, internships, or projects with concrete achievements.",
        "education": "Add your academic degree or training to unlock graduate and adjacent roles.",
        "links": "Add LinkedIn, GitHub, or portfolio URLs for stronger recruiter credibility.",
    }
    for mf in missing_fields:
        if mf in rec_map:
            recommendations.append(rec_map[mf])
    if duplicate_skills:
        recommendations.append(f"Consolidate {len(duplicate_skills)} duplicate skill group(s) to keep your CV crisp.")
    if not str((gt_data.get("candidate") or {}).get("summary") or "").strip():
        recommendations.append("Write a concise 2-3 sentence professional summary.")

    provenance = gt_data.get("import_provenance") or ps.get("import_provenance") or {
        "source_type": ps.get("profile_source") or "manual",
        "reviewed_by_candidate": True,
    }
    profile_status = str(gt_data.get("profile_status") or ps.get("profile_status") or (
        "ready" if completeness_score >= 60 and (core_skills or (gt_data.get("work_history") or [])) else "draft"
    ))

    return {
        "completeness_score": completeness_score,
        "missing_fields": missing_fields,
        "recommendations": recommendations,
        "duplicate_skills": duplicate_skills,
        "timeline_warnings": timeline_warnings,
        "profile_status": profile_status,
        "provenance": provenance,
        "counts": {
            "skills": len(core_skills),
            "work_history": len(gt_data.get("work_history") or []),
            "education": len(gt_data.get("education") or []),
            "projects": len(gt_data.get("projects") or []),
            "certifications": len(gt_data.get("certifications") or []),
            "languages": len((gt_data.get("candidate") or {}).get("languages") or []),
        },
    }
