"""Background daily 09:00 AM (Asia/Tbilisi) Email + Telegram job digest scheduler."""

import asyncio
import contextlib
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlmodel import Session, col, select

from ..config import reload_env_files
from ..db.database import engine, init_db
from ..db.models import CandidateProfile, User
from .digest_service import (
    dispatch_saved_search_digest,
    get_digest_timezone_name,
    has_daily_digest_run_today,
)

logger = logging.getLogger(__name__)


def _local_now(tz_name: str) -> datetime:
    now_utc = datetime.now(UTC)
    try:
        return now_utc.astimezone(ZoneInfo(tz_name))
    except ZoneInfoNotFoundError:
        return now_utc + timedelta(hours=4)


def run_due_daily_digests(now_local: Optional[datetime] = None) -> int:
    """
    Synchronously dispatches today's 09:00 AM Email + Telegram digest for all active users
    who have a profile and have not yet received today's daily digest.
    Returns count of users dispatched.
    """
    reload_env_files()
    enabled = (os.getenv("DAILY_DIGEST_ENABLED", "true") or "true").strip().lower() not in ("0", "false", "no", "off")
    if not enabled:
        return 0

    tz_name = get_digest_timezone_name()
    target_hour = int(os.getenv("DAILY_DIGEST_HOUR", "9") or "9")
    target_minute = int(os.getenv("DAILY_DIGEST_MINUTE", "0") or "0")
    local_dt = now_local or _local_now(tz_name)
    if (local_dt.hour, local_dt.minute) < (target_hour, target_minute):
        return 0

    today_str = local_dt.strftime("%Y-%m-%d")
    init_db()
    with Session(engine) as session:
        users = list(
            session.exec(
                select(User).where(
                    col(User.is_active) == True,
                    col(User.email) != "guest@talentflow.local",
                )
            ).all()
        )
        profile_user_ids = {
            int(pid)
            for pid in session.exec(
                select(CandidateProfile.user_id).where(col(CandidateProfile.user_id).is_not(None))
            ).all()
            if pid is not None
        }

    dispatched = 0
    for user in users:
        if user.id is None or user.id not in profile_user_ids:
            continue
        if has_daily_digest_run_today(user.id, digest_date=today_str):
            continue
        try:
            res = dispatch_saved_search_digest(
                user,
                channels=["in_app", "email", "telegram"],
                include_all_vacancies=True,
                min_score=0.0,
                dry_run=False,
                digest_date=today_str,
            )
            logger.info(
                "Daily 09:00 digest sent for user_id=%s date=%s status=%s matches=%s delivery=%s",
                user.id,
                today_str,
                res.get("status"),
                (res.get("digest") or {}).get("total_matches"),
                res.get("delivery"),
            )
            dispatched += 1
        except Exception as exc:
            logger.warning("Daily 09:00 digest failed for user_id=%s: %s", user.id, exc)
    return dispatched


class DailyDigestScheduler:
    """Lightweight asyncio scheduler polling every 60s to fire the 09:00 AM daily job digest."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="talentflow-daily-digest-scheduler")

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _loop(self) -> None:
        # Short initial delay so startup finishes cleanly before first check
        await asyncio.sleep(5)
        while True:
            try:
                await asyncio.to_thread(run_due_daily_digests)
            except Exception as exc:
                logger.debug("Daily digest scheduler tick warning: %s", exc)
            await asyncio.sleep(60)


daily_digest_scheduler = DailyDigestScheduler()
