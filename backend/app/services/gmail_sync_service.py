"""Human-approved Gmail status detection and follow-up email draft service."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
import httpx

from ..db.models import ApplicationItem, User

logger = logging.getLogger(__name__)

_STAGE_RULES: List[Tuple[str, float, Tuple[str, ...]]] = [
    (
        "Offer",
        0.93,
        (
            "job offer", "pleased to offer", "formal offer", "offer letter", "offer of employment",
            "welcome to the team", "სამუშაო შეთავაზება", "გილოცავთ",
        ),
    ),
    (
        "Rejected",
        0.91,
        (
            "unfortunately", "not moving forward", "decided not to proceed", "other candidates",
            "regret to inform", "position has been filled", "not selected",
            "სამწუხაროდ", "ვერ გადახვედით", "სხვა კანდიდატ",
        ),
    ),
    (
        "Technical Interview",
        0.88,
        (
            "technical interview", "coding interview", "live coding", "system design",
            "engineering interview", "tech round", "ტექნიკური გასაუბრება",
        ),
    ),
    (
        "Assessment",
        0.86,
        (
            "home assignment", "take-home", "coding test", "technical assignment",
            "online assessment", "hackerrank", "codility", "ტექნიკური დავალება",
        ),
    ),
    (
        "HR Screening",
        0.85,
        (
            "interview invitation", "invite you to an interview", "schedule a call",
            "introductory call", "hr call", "screening call", "meet with our recruiter",
            "გასაუბრებაზე", "გასაუბრების დანიშვნა", "შეხვედრა",
        ),
    ),
]


def classify_employer_email(subject: str, snippet: str = "", body: str = "") -> Dict[str, Any]:
    """Deterministically classifies an employer reply into a Kanban stage suggestion."""
    haystack = f"{subject}\n{snippet}\n{body}".lower()
    for stage, confidence, markers in _STAGE_RULES:
        for marker in markers:
            if marker in haystack:
                return {
                    "suggested_status": stage,
                    "confidence": confidence,
                    "matched_signal": marker,
                }
    return {"suggested_status": None, "confidence": 0.0, "matched_signal": ""}


def _normalize_company_tokens(name: str) -> List[str]:
    clean = re.sub(r"[^a-z0-9\u10A0-\u10FF]+", " ", (name or "").lower()).strip()
    stop = {"ltd", "llc", "inc", "corp", "bank", "group", "georgia", "company", "hiring", "technologies", "tech"}
    return [t for t in clean.split() if len(t) >= 3 and t not in stop]


def _message_matches_application(msg: Dict[str, Any], app: ApplicationItem) -> bool:
    sender = str(msg.get("from") or "").lower()
    subject = str(msg.get("subject") or "").lower()
    snippet = str(msg.get("snippet") or "").lower()
    combined = f"{sender} {subject} {snippet}"

    rec_email = str(getattr(app, "recruiter_email", None) or "").strip().lower()
    if rec_email and rec_email in sender:
        return True

    comp_clean = (app.company or "").strip().lower()
    if len(comp_clean) >= 4 and comp_clean in combined:
        return True

    tokens = _normalize_company_tokens(app.company or "")
    return any(tok in sender or tok in subject for tok in tokens)


def fetch_recent_gmail_messages(oauth_token: Optional[Dict[str, Any]], max_results: int = 20) -> List[Dict[str, Any]]:
    """Fetches recent Gmail inbox message headers & snippets using an existing OAuth access token."""
    if not isinstance(oauth_token, dict) or not oauth_token.get("access_token"):
        return []
    access_token = str(oauth_token["access_token"]).strip()
    headers = {"Authorization": f"Bearer {access_token}"}
    out: List[Dict[str, Any]] = []
    try:
        with httpx.Client(timeout=12.0) as client:
            list_resp = client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                params={"maxResults": min(max_results, 30), "q": "newer_than:30d"},
                headers=headers,
            )
            if list_resp.status_code != 200:
                return []
            ids = [m.get("id") for m in (list_resp.json().get("messages") or []) if m.get("id")]
            for msg_id in ids[:max_results]:
                detail = client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                    headers=headers,
                )
                if detail.status_code != 200:
                    continue
                payload = detail.json()
                hdrs = {
                    h.get("name", "").lower(): h.get("value", "")
                    for h in ((payload.get("payload") or {}).get("headers") or [])
                }
                out.append({
                    "id": msg_id,
                    "from": hdrs.get("from", ""),
                    "subject": hdrs.get("subject", ""),
                    "date": hdrs.get("date", ""),
                    "snippet": payload.get("snippet", ""),
                })
    except Exception as exc:
        logger.warning("Gmail inbox metadata sync skipped: %s", exc)
    return out


def build_status_suggestions(
    applications: List[ApplicationItem],
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Matches employer email messages to tracked applications and emits human-reviewable stage suggestions."""
    suggestions: List[Dict[str, Any]] = []
    seen_app_ids: set[str] = set()
    for msg in messages:
        cls = classify_employer_email(
            subject=str(msg.get("subject") or ""),
            snippet=str(msg.get("snippet") or ""),
            body=str(msg.get("body") or ""),
        )
        suggested = cls["suggested_status"]
        if not suggested:
            continue
        for app in applications:
            if app.id in seen_app_ids or app.status == suggested:
                continue
            if _message_matches_application(msg, app):
                seen_app_ids.add(app.id)
                suggestions.append({
                    "application_id": app.id,
                    "company": app.company,
                    "role": app.role,
                    "current_status": app.status,
                    "suggested_status": suggested,
                    "confidence": cls["confidence"],
                    "matched_signal": cls["matched_signal"],
                    "email_subject": str(msg.get("subject") or "")[:180],
                    "email_from": str(msg.get("from") or "")[:120],
                    "email_snippet": str(msg.get("snippet") or "")[:240],
                })
                break
    return suggestions


def build_followup_email_draft(
    app: ApplicationItem,
    user: User,
    *,
    days_since_applied: int = 5,
    language: str = "en",
) -> Dict[str, Any]:
    """Generates a polite, concise follow-up email draft and pre-filled Gmail compose URL."""
    cand_name = (user.full_name or "Candidate").strip()
    recipient = (app.recruiter_email or "").strip()
    if language == "ka":
        subject = f"განაცხადის სტატუსის დაზუსტება: {app.role} — {cand_name}"
        body = (
            f"მოგესალმებით, {app.company}-ის გუნდს,\n\n"
            f"დაახლოებით {days_since_applied} დღის წინ გამოვაგზავნე განაცხადი „{app.role}“ პოზიციაზე. "
            f"კვლავ ძალიან დაინტერესებული ვარ თქვენს გუნდში ჩართვით და სიამოვნებით მოგაწვდით დამატებით ინფორმაციას საჭიროების შემთხვევაში.\n\n"
            f"მადლობა დროისთვის!\n\nპატივისცემით,\n{cand_name}"
        )
    else:
        subject = f"Following up: {app.role} Application — {cand_name}"
        body = (
            f"Dear {app.company} Hiring Team,\n\n"
            f"I hope you are having a good week. I applied for the {app.role} position about {days_since_applied} days ago "
            f"and wanted to briefly reaffirm my interest in contributing to your team.\n\n"
            f"Please let me know if I can share any additional details or work samples to support your review.\n\n"
            f"Best regards,\n{cand_name}"
        )
    compose_url = (
        "https://mail.google.com/mail/?view=cm&fs=1"
        f"&to={quote(recipient)}"
        f"&su={quote(subject)}"
        f"&body={quote(body)}"
    )
    return {
        "application_id": app.id,
        "recipient_email": recipient,
        "subject": subject,
        "body_text": body,
        "gmail_compose_url": compose_url,
        "recommended_cadence_days": days_since_applied,
    }
