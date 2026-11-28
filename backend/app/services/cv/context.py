from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CVRenderContext:
    """Single typed render context consolidating the 12-16 positional parameters of CV builders."""

    full_name: str
    headline: str
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    summary: str = ""
    display_skills: List[str] = field(default_factory=list)
    work_history: List[Dict[str, Any]] = field(default_factory=list)
    education: List[Dict[str, Any]] = field(default_factory=list)
    projects: List[Dict[str, Any]] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    languages_line: str = ""
    cv_language: str = "en"
    cv_style: str = "tailored"
    target_role: str = ""
    target_company: str = ""


def build_cv_render_context(
    *,
    candidate: Dict[str, Any],
    summary: str = "",
    display_skills: Optional[List[str]] = None,
    work_history: Optional[List[Dict[str, Any]]] = None,
    education: Optional[List[Dict[str, Any]]] = None,
    projects: Optional[List[Dict[str, Any]]] = None,
    certifications: Optional[List[str]] = None,
    languages_line: Optional[str] = None,
    cv_language: str = "en",
    cv_style: str = "tailored",
    target_role: str = "",
    target_company: str = "",
) -> CVRenderContext:
    """Builds a normalized, zero-fabrication CVRenderContext strictly from verified candidate fields."""
    loc = candidate.get("location")
    if isinstance(loc, dict):
        loc_str = ", ".join(p for p in (str(loc.get("city") or "").strip(), str(loc.get("country") or "").strip()) if p)
    else:
        loc_str = str(loc or "").strip()

    raw_links = candidate.get("links")
    links: Dict[str, Any] = raw_links if isinstance(raw_links, dict) else {}
    return CVRenderContext(
        full_name=str(candidate.get("full_name") or "").strip(),
        headline=str(candidate.get("headline") or target_role or "").strip(),
        email=str(candidate.get("email") or "").strip(),
        phone=str(candidate.get("phone") or "").strip(),
        location=loc_str,
        linkedin=str(links.get("linkedin") or "").strip(),
        github=str(links.get("github") or "").strip(),
        portfolio=str(links.get("portfolio") or "").strip(),
        summary=str(summary or candidate.get("summary") or "").strip(),
        display_skills=[str(s).strip() for s in (display_skills or []) if str(s).strip()],
        work_history=list(work_history or []),
        education=list(education or []),
        projects=list(projects or []),
        certifications=[str(c).strip() for c in (certifications or []) if str(c).strip()],
        languages_line=str(languages_line or "").strip(),
        cv_language=(cv_language or "en").strip().lower(),
        cv_style=(cv_style or "tailored").strip().lower(),
        target_role=str(target_role or "").strip(),
        target_company=str(target_company or "").strip(),
    )
