"""Daily deduplicated job digest alerts over Email (Gmail SMTP/OAuth) and Telegram Bot API."""

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from sqlmodel import Session, and_, col, select

from ..config import reload_env_files
from ..db.database import engine, init_db
from ..db.models import (
    ApplicationRecord,
    ApplicationTracker,
    DigestDeliveryLog,
    JobPosting,
    Notification,
    SavedSearch,
    User,
    UserJobMatch,
    utc_now,
)
from ..db.profile_repository import ground_truth_store
from .gmail_service import gmail_service
from .job_query_service import POST_DISCOVERED_MATCH_STATUSES, PRE_APPLIED_TRACKER_STATUSES
from .matcher_service import matcher_service, skills_match_token

logger = logging.getLogger(__name__)

_TIER_LABELS: Dict[str, str] = {
    "DIRECT": "Direct Matches",
    "ADJACENT": "Adjacent Roles",
    "PUBLIC_INTERNSHIP": "Public Sector & Internships",
}


def _maybe_reload_env() -> None:
    if not os.getenv("PYTEST_CURRENT_TEST"):
        reload_env_files()


def get_digest_timezone_name() -> str:
    _maybe_reload_env()
    return (os.getenv("DAILY_DIGEST_TIMEZONE") or "Asia/Tbilisi").strip() or "Asia/Tbilisi"


def get_local_digest_date(now_utc: Optional[datetime] = None, tz_name: Optional[str] = None) -> str:
    """Returns local calendar YYYY-MM-DD in the configured digest timezone (default Asia/Tbilisi)."""
    tz_label = tz_name or get_digest_timezone_name()
    base = now_utc or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    try:
        local_dt = base.astimezone(ZoneInfo(tz_label))
    except ZoneInfoNotFoundError:
        local_dt = base + timedelta(hours=4)
    return local_dt.strftime("%Y-%m-%d")


def _job_matches_saved_filter(
    job: JobPosting,
    match: UserJobMatch,
    filters: Dict[str, Any],
    min_score_floor: float,
) -> bool:
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


def _extract_skill_gaps(
    job: JobPosting,
    u_match: UserJobMatch,
    cand_skills: List[str],
    cand_blob: str,
) -> Tuple[List[str], List[str]]:
    matched = [str(s) for s in (u_match.matched_skills or []) if str(s).strip()][:8]
    missing = [str(s) for s in (u_match.missing_skills or []) if str(s).strip()][:8]
    if not matched and not missing and cand_skills:
        reqs = matcher_service.extract_job_requirements(job.title or "", job.description_raw or "")
        for req in reqs[:12]:
            if skills_match_token(req, cand_skills, cand_blob):
                if req not in matched:
                    matched.append(req)
            elif req not in missing:
                missing.append(req)
    return matched[:8], missing[:8]


def _serialize_digest_job(
    job: JobPosting,
    u_match: UserJobMatch,
    cand_skills: List[str],
    cand_blob: str,
) -> Dict[str, Any]:
    score = round(float(u_match.suitability_score or 0.0), 1)
    mismatch_pct = round(max(0.0, 100.0 - score), 1)
    matched, missing = _extract_skill_gaps(job, u_match, cand_skills, cand_blob)
    tier = str(u_match.match_tier or ("PUBLIC_INTERNSHIP" if job.portal == "hr.gov.ge" else "DIRECT"))
    return {
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "portal": job.portal,
        "url": job.url,
        "score": score,
        "mismatch_pct": mismatch_pct,
        "tier": tier,
        "matched_skills": matched,
        "missing_skills": missing,
    }


def _load_candidate_skill_context(user_id: int) -> Tuple[List[str], str]:
    profile = ground_truth_store.get_profile_record(user_id=user_id)
    if profile is None:
        return [], ""
    ps = profile.parsed_skills if isinstance(profile.parsed_skills, dict) else {}
    raw_skills = list(ps.get("all_skills") or ps.get("verified_skills") or [])
    if not raw_skills and (profile.raw_markdown or "").strip():
        parsed = matcher_service.parse_skills_markdown(profile.raw_markdown)
        raw_skills = list(parsed.get("all_skills") or [])
    cleaned = [str(s).strip() for s in raw_skills if str(s).strip()]
    return cleaned, " ".join(cleaned)


def _norm_url(url: Optional[str]) -> str:
    return (url or "").strip().rstrip("/").lower()


def _load_progressed_applications(session: Session, user_id: int) -> Tuple[Set[int], Set[str]]:
    """Returns (job_posting_ids, normalized_urls) for vacancies already past Discovered (Applied, HR Screening, etc.)."""
    progressed_ids: Set[int] = set()
    progressed_urls: Set[str] = set()
    trackers = session.exec(
        select(ApplicationTracker).where(
            col(ApplicationTracker.user_id) == user_id,
            col(ApplicationTracker.is_deleted) == False,
            col(ApplicationTracker.status).not_in(PRE_APPLIED_TRACKER_STATUSES),
        )
    ).all()
    for tr in trackers:
        if tr.job_posting_id is not None:
            progressed_ids.add(int(tr.job_posting_id))
        u_norm = _norm_url(tr.job_url)
        if u_norm:
            progressed_urls.add(u_norm)

    records = session.exec(
        select(ApplicationRecord.job_posting_id).where(
            col(ApplicationRecord.user_id) == user_id,
            col(ApplicationRecord.job_posting_id).is_not(None),
            col(ApplicationRecord.submission_status).not_in(PRE_APPLIED_TRACKER_STATUSES),
        )
    ).all()
    for rid in records:
        if rid is not None:
            progressed_ids.add(int(rid))
    return progressed_ids, progressed_urls


def _is_progressed(job: JobPosting, progressed_ids: Set[int], progressed_urls: Set[str]) -> bool:
    if job.id is not None and int(job.id) in progressed_ids:
        return True
    u_norm = _norm_url(job.url)
    return bool(u_norm and u_norm in progressed_urls)


def _load_previously_sent_and_yesterday(
    session: Session,
    user_id: int,
    today_date: str,
    progressed_ids: Set[int],
    progressed_urls: Set[str],
) -> Tuple[Set[int], List[Dict[str, Any]]]:
    """Returns (all previously sent job_posting_ids, compact reminder items from yesterday excluding progressed apps)."""
    prev_logs = session.exec(
        select(DigestDeliveryLog)
        .where(col(DigestDeliveryLog.user_id) == user_id)
        .order_by(col(DigestDeliveryLog.sent_at).desc())
    ).all()
    sent_job_ids: Set[int] = {
        int(lg.job_posting_id) for lg in prev_logs if lg.job_posting_id is not None
    }

    # Find the most recent previous digest date before today (typically yesterday)
    prev_dates = sorted({lg.digest_date for lg in prev_logs if lg.digest_date < today_date}, reverse=True)
    if not prev_dates:
        return sent_job_ids, []
    last_prev_date = prev_dates[0]
    yest_job_ids = [
        int(lg.job_posting_id)
        for lg in prev_logs
        if lg.digest_date == last_prev_date and lg.job_posting_id is not None
    ]
    if not yest_job_ids:
        return sent_job_ids, []

    pending_ids = [jid for jid in dict.fromkeys(yest_job_ids) if jid not in progressed_ids][:12]
    if not pending_ids:
        return sent_job_ids, []

    yest_rows = session.exec(
        select(JobPosting, UserJobMatch)
        .join(
            UserJobMatch,
            and_(
                col(UserJobMatch.job_posting_id) == col(JobPosting.id),
                col(UserJobMatch.user_id) == user_id,
            ),
        )
        .where(
            col(JobPosting.id).in_(pending_ids),
            col(UserJobMatch.status).not_in(POST_DISCOVERED_MATCH_STATUSES),
        )
    ).all()
    reminders = [
        {
            "job_id": jp.id,
            "title": jp.title,
            "company": jp.company,
            "portal": jp.portal,
            "score": round(float(um.suitability_score or 0.0), 1),
            "mismatch_pct": round(max(0.0, 100.0 - float(um.suitability_score or 0.0)), 1),
            "sent_date": last_prev_date,
        }
        for jp, um in yest_rows
        if not _is_progressed(jp, progressed_ids, progressed_urls)
    ][:10]
    return sent_job_ids, reminders


def _group_all_vacancies(
    rows: List[Tuple[JobPosting, UserJobMatch]],
    sent_job_ids: Set[int],
    floor: float,
    limit_per_group: int,
    cand_skills: List[str],
    cand_blob: str,
) -> Tuple[List[Dict[str, Any]], int, List[int]]:
    """Groups every new non-sent vacancy across Direct, Adjacent, and Public Sector tiers."""
    by_tier: Dict[str, List[Dict[str, Any]]] = {
        "DIRECT": [],
        "ADJACENT": [],
        "PUBLIC_INTERNSHIP": [],
    }
    new_job_ids: List[int] = []
    for job, u_match in rows:
        if job.id is None or job.id in sent_job_ids:
            continue
        if float(u_match.suitability_score or 0.0) < floor:
            continue
        item = _serialize_digest_job(job, u_match, cand_skills, cand_blob)
        tier_key = item["tier"] if item["tier"] in by_tier else "DIRECT"
        if len(by_tier[tier_key]) < limit_per_group:
            by_tier[tier_key].append(item)
            new_job_ids.append(int(job.id))

    groups: List[Dict[str, Any]] = []
    total = 0
    for tk in ("DIRECT", "ADJACENT", "PUBLIC_INTERNSHIP"):
        if by_tier[tk]:
            total += len(by_tier[tk])
            groups.append({
                "search_id": None,
                "search_name": _TIER_LABELS[tk],
                "matches": by_tier[tk],
            })
    return groups, total, new_job_ids


def _group_saved_searches(
    session: Session,
    searches: List[SavedSearch],
    rows: List[Tuple[JobPosting, UserJobMatch]],
    sent_job_ids: Set[int],
    floor: float,
    limit_per_search: int,
    cand_skills: List[str],
    cand_blob: str,
) -> Tuple[List[Dict[str, Any]], int, List[int]]:
    groups: List[Dict[str, Any]] = []
    seen_in_digest: Set[int] = set()
    new_job_ids: List[int] = []
    total = 0
    for s_row in searches:
        filters = dict(s_row.filters or {})
        matched_jobs: List[Dict[str, Any]] = []
        for job, u_match in rows:
            if job.id is None or job.id in sent_job_ids or job.id in seen_in_digest:
                continue
            if _job_matches_saved_filter(job, u_match, filters, floor):
                matched_jobs.append(_serialize_digest_job(job, u_match, cand_skills, cand_blob))
                seen_in_digest.add(int(job.id))
                new_job_ids.append(int(job.id))
                if len(matched_jobs) >= limit_per_search:
                    break
        if matched_jobs:
            total += len(matched_jobs)
            groups.append({
                "search_id": s_row.id,
                "search_name": s_row.name,
                "matches": matched_jobs,
            })
            s_row.last_run_at = utc_now()
            session.add(s_row)
    return groups, total, new_job_ids


def collect_saved_search_digest(
    user_id: int,
    *,
    min_score_override: Optional[float] = None,
    limit_per_search: int = 15,
    include_all_vacancies: bool = True,
    digest_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Collects ONLY new (never previously sent) vacancies across ALL tiers (or saved searches),
    computes Match % / Mismatch % + missing skills for each, and attaches yesterday's reminder.
    """
    init_db()
    today_date = digest_date or get_local_digest_date()
    floor = float(min_score_override) if min_score_override is not None else 0.0
    cand_skills, cand_blob = _load_candidate_skill_context(user_id)

    with Session(engine) as session:
        searches = list(
            session.exec(
                select(SavedSearch).where(
                    col(SavedSearch.user_id) == user_id,
                    col(SavedSearch.notify_on_new) == True,
                )
            ).all()
        )
        progressed_ids, progressed_urls = _load_progressed_applications(session, user_id)
        sent_job_ids, yesterday_reminders = _load_previously_sent_and_yesterday(
            session, user_id, today_date, progressed_ids, progressed_urls
        )

        raw_rows = list(
            session.exec(
                select(JobPosting, UserJobMatch)
                .join(
                    UserJobMatch,
                    and_(
                        col(UserJobMatch.job_posting_id) == col(JobPosting.id),
                        col(UserJobMatch.user_id) == user_id,
                    ),
                )
                .where(
                    col(JobPosting.is_expired) == False,
                    col(UserJobMatch.status) != "FILTERED_OUT",
                    col(UserJobMatch.status).not_in(POST_DISCOVERED_MATCH_STATUSES),
                    col(UserJobMatch.is_ignored) == False,
                )
                .order_by(col(UserJobMatch.suitability_score).desc(), col(JobPosting.scraped_at).desc())
                .limit(250)
            ).all()
        )
        rows = [(jp, um) for jp, um in raw_rows if not _is_progressed(jp, progressed_ids, progressed_urls)]

        if include_all_vacancies:
            groups, total_matches, new_job_ids = _group_all_vacancies(
                rows, sent_job_ids, floor, limit_per_search, cand_skills, cand_blob
            )
            mode = "all_vacancies"
        elif searches:
            groups, total_matches, new_job_ids = _group_saved_searches(
                session, searches, rows, sent_job_ids, floor, limit_per_search, cand_skills, cand_blob
            )
            mode = "saved_searches"
        else:
            groups, total_matches, new_job_ids = [], 0, []
            mode = "no_saved_search"
        session.commit()

    return {
        "digest_date": today_date,
        "mode": mode,
        "searches_evaluated": len(searches),
        "total_matches": total_matches,
        "previously_sent_skipped": len(sent_job_ids),
        "new_job_ids": new_job_ids,
        "groups": groups,
        "yesterday_reminders": yesterday_reminders,
    }


def format_digest_text(digest: Dict[str, Any]) -> str:
    """Renders a clear plain-text / Telegram-friendly daily digest with match %, mismatch %, and missing skills."""
    date_lbl = digest.get("digest_date") or get_local_digest_date()
    groups = digest.get("groups") or []
    reminders = digest.get("yesterday_reminders") or []
    lines: List[str] = []

    if not groups:
        if digest.get("mode") == "no_saved_search":
            lines.append(
                f"TalentFlow Daily Digest ({date_lbl}): No saved job search was configured for today. "
                "Enable 'All Vacancies' or save a search filter in Discovery Feed to receive daily matches."
            )
        else:
            lines.append(
                f"TalentFlow Daily Digest ({date_lbl}): No new matching vacancies were found today "
                f"({digest.get('previously_sent_skipped', 0)} previously sent vacancy(ies) were not resent)."
            )
    else:
        lines.append(
            f"TalentFlow Daily Job Digest ({date_lbl}) — {digest['total_matches']} NEW vacancy(ies):"
        )
        for grp in groups:
            lines.append(f"\n[{grp['search_name']}]")
            for m in grp["matches"]:
                miss_list = m.get("missing_skills") or []
                match_list = m.get("matched_skills") or []
                miss_txt = ", ".join(miss_list[:5]) if miss_list else "None detected"
                match_txt = ", ".join(match_list[:4]) if match_list else "Profile fit"
                lines.append(
                    f"• {m['title']} @ {m['company']} ({m['portal']})\n"
                    f"  Match: {m['score']}% | Mismatch/Gap: {m['mismatch_pct']}%\n"
                    f"  Matched: {match_txt}\n"
                    f"  Missing skills: {miss_txt}\n"
                    f"  Link: {m['url']}"
                )

    if reminders:
        sent_day = reminders[0].get("sent_date", "yesterday")
        lines.append(f"\nReminder — Yesterday's vacancies ({sent_day}, not re-sent in full):")
        for r in reminders[:6]:
            lines.append(
                f"- {r['title']} @ {r['company']} ({r['portal']}) — Match {r['score']}% | Gap {r['mismatch_pct']}%"
            )

    return "\n".join(lines)


def _split_telegram_chunks(text: str, max_len: int = 3900) -> List[str]:
    if len(text) <= max_len:
        return [text]
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > max_len and cur:
            chunks.append("".join(cur).strip())
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += len(line)
    if cur:
        chunks.append("".join(cur).strip())
    return chunks


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    http_post: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Dispatches a daily digest message via Telegram Bot API (auto-chunking messages > 3900 chars)."""
    if not bot_token or not chat_id:
        return {"sent": False, "reason": "telegram_not_configured"}
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    poster = http_post or httpx.post
    chunks = _split_telegram_chunks(text)
    last_code = 0
    try:
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
            resp = poster(url, json=payload, timeout=12.0)
            last_code = int(getattr(resp, "status_code", 0) or 0)
            if last_code != 200:
                return {"sent": False, "status_code": last_code, "chunks_sent": 0}
        return {"sent": True, "status_code": last_code, "chunks_sent": len(chunks)}
    except Exception as exc:
        logger.warning("Telegram digest dispatch failed: %s", exc)
        return {"sent": False, "error": str(exc)[:180]}


def _record_delivered_digest(
    user_id: int,
    digest_date: str,
    job_ids: List[int],
    channels_label: str,
) -> None:
    with Session(engine) as session:
        session.add(
            DigestDeliveryLog(
                user_id=user_id,
                job_posting_id=None,
                digest_date=digest_date,
                channels=channels_label,
            )
        )
        for jid in job_ids:
            session.add(
                DigestDeliveryLog(
                    user_id=user_id,
                    job_posting_id=jid,
                    digest_date=digest_date,
                    channels=channels_label,
                )
            )
        session.commit()


def has_daily_digest_run_today(user_id: int, digest_date: Optional[str] = None) -> bool:
    """Checks whether today's digest run has already been logged for user_id."""
    init_db()
    target_date = digest_date or get_local_digest_date()
    with Session(engine) as session:
        hit = session.exec(
            select(DigestDeliveryLog.id)
            .where(
                col(DigestDeliveryLog.user_id) == user_id,
                col(DigestDeliveryLog.digest_date) == target_date,
                col(DigestDeliveryLog.job_posting_id).is_(None),
            )
            .limit(1)
        ).first()
    return hit is not None


def get_user_digest_status(user_id: int) -> Dict[str, Any]:
    """Returns daily 09:00 AM schedule metadata and delivery history stats for the UI."""
    init_db()
    _maybe_reload_env()
    tz_name = get_digest_timezone_name()
    hour = int(os.getenv("DAILY_DIGEST_HOUR", "9") or "9")
    minute = int(os.getenv("DAILY_DIGEST_MINUTE", "0") or "0")
    enabled = (os.getenv("DAILY_DIGEST_ENABLED", "true") or "true").strip().lower() not in ("0", "false", "no", "off")
    with Session(engine) as session:
        logs = list(
            session.exec(
                select(DigestDeliveryLog)
                .where(col(DigestDeliveryLog.user_id) == user_id)
                .order_by(col(DigestDeliveryLog.sent_at).desc())
            ).all()
        )
    sent_jobs = len({lg.job_posting_id for lg in logs if lg.job_posting_id is not None})
    last_date = logs[0].digest_date if logs else None
    return {
        "enabled": enabled,
        "schedule_time": f"{hour:02d}:{minute:02d}",
        "timezone": tz_name,
        "last_digest_date": last_date,
        "total_unique_vacancies_sent": sent_jobs,
        "telegram_configured": bool((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()),
        "telegram_default_chat_id_set": bool((os.getenv("TELEGRAM_DEFAULT_CHAT_ID") or "").strip()),
    }


def dispatch_saved_search_digest(
    user: User,
    *,
    channels: Optional[List[str]] = None,
    telegram_chat_id: Optional[str] = None,
    min_score: Optional[float] = None,
    include_all_vacancies: bool = True,
    dry_run: bool = False,
    digest_date: Optional[str] = None,
    http_post: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """
    Collects deduplicated daily matches (all tiers or saved searches) with mismatch % & missing skills,
    always sends a clear status message even when 0 new jobs exist, and logs sent job IDs.
    """
    if user.id is None:
        return {"status": "skipped", "reason": "no_user_id"}
    digest = collect_saved_search_digest(
        user.id,
        min_score_override=min_score,
        include_all_vacancies=include_all_vacancies,
        digest_date=digest_date,
    )
    body_text = format_digest_text(digest)
    active_channels = [c.lower() for c in (channels or ["in_app", "email", "telegram"])]
    delivery: Dict[str, Any] = {}
    date_lbl = digest["digest_date"]
    total_new = int(digest["total_matches"])
    subject = (
        f"TalentFlow Daily Jobs ({date_lbl}): {total_new} New Vacancy(ies)"
        if total_new > 0
        else f"TalentFlow Daily Jobs ({date_lbl}): No New Vacancies Today"
    )

    if "in_app" in active_channels:
        if dry_run:
            delivery["in_app"] = {"sent": False, "dry_run": True}
        else:
            with Session(engine) as session:
                session.add(
                    Notification(
                        user_id=user.id,
                        title=(
                            f"Daily Job Digest ({date_lbl}): {total_new} new matches"
                            if total_new > 0
                            else f"Daily Job Digest ({date_lbl}): No new vacancies today"
                        ),
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
                subject=subject,
                body_text=body_text,
                mode="send",
            )
            delivery["email"] = {
                "sent": res.get("status") == "success",
                "mode": res.get("channel") or res.get("action") or res.get("mode"),
            }

    if "telegram" in active_channels:
        _maybe_reload_env()
        bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        chat_id = (telegram_chat_id or os.getenv("TELEGRAM_DEFAULT_CHAT_ID") or "").strip()
        if dry_run:
            delivery["telegram"] = {"sent": False, "dry_run": True, "configured": bool(bot_token and chat_id)}
        else:
            delivery["telegram"] = send_telegram_message(bot_token, chat_id, body_text, http_post=http_post)

    if not dry_run:
        _record_delivered_digest(
            user_id=user.id,
            digest_date=date_lbl,
            job_ids=list(digest.get("new_job_ids") or []),
            channels_label=",".join(active_channels),
        )

    return {
        "status": "preview" if dry_run else ("dispatched" if total_new > 0 else "dispatched_empty_notice"),
        "digest": digest,
        "preview_text": body_text,
        "delivery": delivery,
    }
