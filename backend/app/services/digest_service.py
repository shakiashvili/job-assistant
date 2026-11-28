"""Saved-search digest alerts over Email (SMTP/HTTPS) and optional Telegram Bot API."""

import logging
import os
from typing import Any, Callable, Dict, List, Optional
import httpx
from sqlmodel import Session, select

from ..db.database import engine
from ..db.models import JobPosting, Notification, SavedSearch, User, UserJobMatch, utc_now
from .gmail_service import gmail_service

logger = logging.getLogger(__name__)


def _job_matches_saved_filter(job: JobPosting, match: UserJobMatch, filters: Dict[str, Any], min_score_floor: float) -> bool:
    score = float(match.suitability_score or 0.0)
    req_min = max(float(filters.get("min_score") or 0.0), min_score_floor)
    if score < req_min:
        return False
    portal = str(filters.get("portal") or "ALL").strip()
    if portal and portal.upper() != "ALL" and (job.portal or "").lower() != portal.lower():
        return False
    search_q = str(filters.get("search") or "").strip().lower()
    if search_q:
        haystack = f"{job.title or ''} {job.company or ''} {job.description_raw or ''}".lower()
        if search_q not in haystack:
            return False
    return not (filters.get("b2b_only") and not job.is_remote)


def collect_saved_search_digest(
    user_id: int,
    *,
    min_score_override: Optional[float] = None,
    limit_per_search: int = 8,
) -> Dict[str, Any]:
    """Evaluates all active SavedSearch alerts for a user and builds a structured digest payload."""
    floor = float(min_score_override) if min_score_override is not None else 60.0
    with Session(engine) as session:
        searches = session.exec(
            select(SavedSearch).where(
                SavedSearch.user_id == user_id,
                SavedSearch.notify_on_new == True,
            )
        ).all()
        if not searches:
            return {"searches_evaluated": 0, "total_matches": 0, "groups": []}

        rows = session.exec(
            select(JobPosting, UserJobMatch)
            .join(UserJobMatch, (UserJobMatch.job_posting_id == JobPosting.id) & (UserJobMatch.user_id == user_id))
            .where(UserJobMatch.status != "FILTERED_OUT", UserJobMatch.is_ignored == False)
            .order_by(UserJobMatch.suitability_score.desc(), JobPosting.scraped_at.desc())
            .limit(200)
        ).all()

        groups: List[Dict[str, Any]] = []
        total_matches = 0
        for s_row in searches:
            filters = dict(s_row.filters or {})
            matched_jobs: List[Dict[str, Any]] = []
            for job, u_match in rows:
                if _job_matches_saved_filter(job, u_match, filters, floor):
                    matched_jobs.append({
                        "job_id": job.id,
                        "title": job.title,
                        "company": job.company,
                        "portal": job.portal,
                        "url": job.url,
                        "score": round(float(u_match.suitability_score or 0.0), 1),
                        "tier": u_match.match_tier or "DIRECT",
                    })
                    if len(matched_jobs) >= limit_per_search:
                        break
            if matched_jobs:
                total_matches += len(matched_jobs)
                groups.append({
                    "search_id": s_row.id,
                    "search_name": s_row.name,
                    "matches": matched_jobs,
                })
                s_row.last_run_at = utc_now()
                session.add(s_row)
        session.commit()

    return {
        "searches_evaluated": len(searches),
        "total_matches": total_matches,
        "groups": groups,
    }


def format_digest_text(digest: Dict[str, Any]) -> str:
    """Renders a clean plain-text / Telegram-friendly digest body."""
    if not digest.get("groups"):
        return "No new matching vacancies found for your saved searches."
    lines = [f"TalentFlow Saved-Search Digest ({digest['total_matches']} matches):"]
    for grp in digest["groups"]:
        lines.append(f"\n[{grp['search_name']}]")
        for m in grp["matches"]:
            lines.append(f"- {m['title']} @ {m['company']} ({m['portal']}, {m['score']}%): {m['url']}")
    return "\n".join(lines)


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    http_post: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Dispatches a saved-search digest message via Telegram Bot API."""
    if not bot_token or not chat_id:
        return {"sent": False, "reason": "telegram_not_configured"}
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
    poster = http_post or httpx.post
    try:
        resp = poster(url, json=payload, timeout=10.0)
        ok = getattr(resp, "status_code", 0) == 200
        return {"sent": ok, "status_code": getattr(resp, "status_code", 0)}
    except Exception as exc:
        logger.warning("Telegram digest dispatch failed: %s", exc)
        return {"sent": False, "error": str(exc)[:180]}


def dispatch_saved_search_digest(
    user: User,
    *,
    channels: Optional[List[str]] = None,
    telegram_chat_id: Optional[str] = None,
    min_score: Optional[float] = None,
    dry_run: bool = False,
    http_post: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Collects saved-search matches and delivers digests via Email, Telegram, and in-app Notification."""
    if user.id is None:
        return {"status": "skipped", "reason": "no_user_id"}
    digest = collect_saved_search_digest(user.id, min_score_override=min_score)
    body_text = format_digest_text(digest)
    active_channels = [c.lower() for c in (channels or ["in_app", "email"])]
    delivery: Dict[str, Any] = {}

    if digest["total_matches"] == 0:
        return {"status": "empty", "digest": digest, "delivery": delivery}

    if "in_app" in active_channels and not dry_run:
        with Session(engine) as session:
            session.add(
                Notification(
                    user_id=user.id,
                    title=f"Saved-Search Digest: {digest['total_matches']} matches",
                    message=body_text[:450],
                    is_read=False,
                )
            )
            session.commit()
        delivery["in_app"] = {"sent": True}

    if "email" in active_channels:
        if dry_run:
            delivery["email"] = {"sent": False, "dry_run": True}
        else:
            res = gmail_service.dispatch_email(
                user=user,
                recipient_email=user.email,
                subject=f"TalentFlow Digest: {digest['total_matches']} New Matching Vacancies",
                body_text=body_text,
                mode="send",
            )
            delivery["email"] = {
                "sent": res.get("status") == "success",
                "mode": res.get("channel") or res.get("action") or res.get("mode"),
            }

    if "telegram" in active_channels:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = (telegram_chat_id or os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")).strip()
        if dry_run:
            delivery["telegram"] = {"sent": False, "dry_run": True, "configured": bool(bot_token and chat_id)}
        else:
            delivery["telegram"] = send_telegram_message(bot_token, chat_id, body_text, http_post=http_post)

    return {
        "status": "dispatched" if not dry_run else "preview",
        "digest": digest,
        "preview_text": body_text,
        "delivery": delivery,
    }
