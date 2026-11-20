import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select, update

from ..db.database import engine, init_db
from ..db.models import ScrapeTask, User, utc_now
from .scrapers.scraper_orchestrator import scraper_orchestrator

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
SCRAPE_STALE_TIMEOUT_SECONDS = int(os.getenv("SCRAPE_STALE_TIMEOUT_SECONDS", "180"))
SCRAPE_EXECUTION_TIMEOUT_SECONDS = int(os.getenv("SCRAPE_EXECUTION_TIMEOUT_SECONDS", "240"))
SCRAPE_HEARTBEAT_INTERVAL_SECONDS = max(2, int(os.getenv("SCRAPE_HEARTBEAT_INTERVAL_SECONDS", "15")))
SCRAPE_WORKER_MODE = os.getenv("SCRAPE_WORKER_MODE", "embedded").strip().lower() or "embedded"
SCRAPE_POLL_INTERVAL_SECONDS = max(1, int(os.getenv("SCRAPE_POLL_INTERVAL_SECONDS", "5")))


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _touch_heartbeat(task_id: str) -> None:
    try:
        with Session(engine) as session:
            session.exec(
                update(ScrapeTask)
                .where(ScrapeTask.task_id == task_id, ScrapeTask.status == "RUNNING")
                .values(heartbeat_at=utc_now())
            )
            session.commit()
    except Exception as exc:
        logger.debug("Scrape heartbeat touch skipped for %s: %s", task_id, exc)


def recover_stale_scrape_tasks(
    session: Optional[Session] = None,
    *,
    now: Optional[datetime] = None,
    stale_after_seconds: Optional[int] = None,
    force_recover_foreign_workers: bool = False,
) -> Dict[str, int]:
    """
    Detects zombie RUNNING scrape tasks left behind by server restarts, OOM kills, or hung workers.
    - Tasks with remaining retry budget (`attempt_count < max_attempts`) are re-queued (`QUEUED`).
    - Tasks that exhausted retries transition cleanly to `FAILED` so users are never stuck indefinitely.
    """
    now_utc = _ensure_utc(now) or utc_now()
    threshold = int(stale_after_seconds if stale_after_seconds is not None else SCRAPE_STALE_TIMEOUT_SECONDS)

    def _run(db: Session) -> Dict[str, int]:
        requeued = 0
        failed = 0
        running_rows = db.exec(select(ScrapeTask).where(ScrapeTask.status == "RUNNING")).all()
        for row in running_rows:
            ref_dt = _ensure_utc(row.heartbeat_at or row.started_at or row.created_at)
            age_seconds = (now_utc - ref_dt).total_seconds() if ref_dt is not None else float(threshold + 1)
            is_foreign_dead = force_recover_foreign_workers and (row.worker_id != WORKER_ID)
            if age_seconds < threshold and not is_foreign_dead:
                continue

            attempts = int(row.attempt_count or 0)
            max_att = int(row.max_attempts or 2)
            if attempts < max_att:
                row.status = "QUEUED"
                row.worker_id = None
                row.heartbeat_at = now_utc
                row.error_message = "Recovered after server restart or worker timeout; re-queued automatically."
                requeued += 1
            else:
                row.status = "FAILED"
                row.worker_id = None
                row.completed_at = now_utc
                row.error_message = (
                    "Scrape task timed out or was interrupted by a server restart after maximum retry attempts."
                )
                failed += 1
            db.add(row)

        if requeued or failed:
            db.commit()
            logger.warning(
                "Recovered stale scrape tasks (requeued=%s, failed=%s, worker=%s)",
                requeued,
                failed,
                WORKER_ID,
            )
        return {"requeued": requeued, "failed": failed}

    if session is not None:
        return _run(session)
    with Session(engine) as own_session:
        return _run(own_session)


def claim_queued_scrape_task(task_id: Optional[str] = None) -> Optional[ScrapeTask]:
    """Atomically claims one QUEUED scrape task for execution by this worker."""
    now_utc = utc_now()
    with Session(engine) as session:
        stmt = select(ScrapeTask).where(ScrapeTask.status == "QUEUED")
        if task_id:
            stmt = stmt.where(ScrapeTask.task_id == task_id)
        stmt = stmt.order_by(ScrapeTask.created_at.asc())
        candidate = session.exec(stmt).first()
        if not candidate:
            return None

        next_attempt = int(candidate.attempt_count or 0) + 1
        claim_res = session.exec(
            update(ScrapeTask)
            .where(ScrapeTask.task_id == candidate.task_id, ScrapeTask.status == "QUEUED")
            .values(
                status="RUNNING",
                worker_id=WORKER_ID,
                started_at=now_utc,
                heartbeat_at=now_utc,
                attempt_count=next_attempt,
                progress_pct=max(10, int(candidate.progress_pct or 0)),
            )
        )
        session.commit()
        if (claim_res.rowcount or 0) != 1:
            return None
        return session.exec(select(ScrapeTask).where(ScrapeTask.task_id == candidate.task_id)).first()


def _resolve_owner_email(user_id: Optional[int]) -> Optional[str]:
    if user_id is None:
        return None
    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user or user.email == "guest@talentflow.local":
            return None
        return user.email


async def execute_scrape_task(task_id: str, owner_email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Claims a durable QUEUED scrape task and runs it with periodic heartbeats and a strict timeout."""
    claimed = claim_queued_scrape_task(task_id=task_id)
    if not claimed:
        return None

    resolved_owner = owner_email if owner_email is not None else _resolve_owner_email(claimed.user_id)
    timeout_s = max(1, int(claimed.timeout_seconds or SCRAPE_EXECUTION_TIMEOUT_SECONDS))
    stop_hb = asyncio.Event()

    async def _heartbeat_loop() -> None:
        while not stop_hb.is_set():
            try:
                await asyncio.wait_for(stop_hb.wait(), timeout=SCRAPE_HEARTBEAT_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                _touch_heartbeat(claimed.task_id)

    hb_task = asyncio.create_task(_heartbeat_loop())
    try:
        res = await asyncio.wait_for(
            scraper_orchestrator.run_scrapers(
                portals=claimed.portals or None,
                allow_network=bool(claimed.allow_network),
                owner_email=resolved_owner,
                user_id=claimed.user_id,
            ),
            timeout=timeout_s,
        )
        summary = {
            "total_processed": int(res.get("total_processed") or 0),
            "staged_ready_count": int(res.get("staged_ready_count") or 0),
            "filtered_out_count": int(res.get("filtered_out_count") or 0),
        }
        with Session(engine) as session:
            t_row = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == claimed.task_id)).first()
            if t_row:
                t_row.status = "COMPLETED"
                t_row.progress_pct = 100
                t_row.result_summary = summary
                t_row.error_message = None
                t_row.heartbeat_at = utc_now()
                t_row.completed_at = utc_now()
                session.add(t_row)
                session.commit()
        return summary
    except asyncio.TimeoutError:
        err_msg = f"Scrape task exceeded execution timeout ({timeout_s}s)."
        logger.error("Background scrape task %s timed out after %ss", claimed.task_id, timeout_s)
        with Session(engine) as session:
            t_row = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == claimed.task_id)).first()
            if t_row:
                t_row.status = "FAILED"
                t_row.error_message = err_msg
                t_row.heartbeat_at = utc_now()
                t_row.completed_at = utc_now()
                session.add(t_row)
                session.commit()
        return None
    except Exception as exc:
        logger.error("Background scrape task %s failed: %s", claimed.task_id, exc)
        with Session(engine) as session:
            t_row = session.exec(select(ScrapeTask).where(ScrapeTask.task_id == claimed.task_id)).first()
            if t_row:
                t_row.status = "FAILED"
                t_row.error_message = str(exc)
                t_row.heartbeat_at = utc_now()
                t_row.completed_at = utc_now()
                session.add(t_row)
                session.commit()
        return None
    finally:
        stop_hb.set()
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass


class DurableScrapeQueue:
    """
    Durable DB-backed scrape task queue supporting:
    - Embedded mode (single web container with startup stale-task recovery & background drain loop).
    - External worker mode (`SCRAPE_WORKER_MODE=external` + `python -m app.services.scrape_worker`).
    """

    def __init__(self) -> None:
        self._consumer_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._wake_event: Optional[asyncio.Event] = None

    def enqueue_task(
        self,
        *,
        user_id: Optional[int],
        portals: Optional[List[str]],
        allow_network: bool,
        timeout_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        init_db()
        recover_stale_scrape_tasks()

        with Session(engine) as session:
            existing_active = session.exec(
                select(ScrapeTask).where(
                    ScrapeTask.user_id == user_id,
                    ScrapeTask.status.in_(["QUEUED", "RUNNING"]),
                )
            ).first()
            if existing_active:
                return {
                    "task_id": existing_active.task_id,
                    "status": existing_active.status,
                    "deduplicated": True,
                    "message": "An active scrape task is already queued or running for your account.",
                }

            task_id = f"scrape-{uuid.uuid4().hex[:10]}"
            now_utc = utc_now()
            task_row = ScrapeTask(
                task_id=task_id,
                user_id=user_id,
                status="QUEUED",
                portals=portals or scraper_orchestrator.DEFAULT_PORTALS,
                allow_network=bool(allow_network),
                progress_pct=0,
                heartbeat_at=now_utc,
                attempt_count=0,
                max_attempts=2,
                timeout_seconds=int(timeout_seconds or SCRAPE_EXECUTION_TIMEOUT_SECONDS),
            )
            session.add(task_row)
            session.commit()

        self.notify_worker()
        return {
            "task_id": task_id,
            "status": "QUEUED",
            "deduplicated": False,
        }

    def notify_worker(self) -> None:
        if self._wake_event is not None:
            try:
                self._wake_event.set()
            except Exception:
                pass

    async def process_one_queued_task(self) -> bool:
        recover_stale_scrape_tasks()
        with Session(engine) as session:
            queued = session.exec(
                select(ScrapeTask)
                .where(ScrapeTask.status == "QUEUED")
                .order_by(ScrapeTask.created_at.asc())
            ).first()
            next_id = queued.task_id if queued else None
        if not next_id:
            return False
        await execute_scrape_task(next_id)
        return True

    async def _worker_loop(self) -> None:
        logger.info("Durable scrape worker started (mode=%s, worker_id=%s)", SCRAPE_WORKER_MODE, WORKER_ID)
        assert self._stop_event is not None and self._wake_event is not None
        while not self._stop_event.is_set():
            try:
                ran = await self.process_one_queued_task()
                if ran:
                    continue
            except Exception as exc:
                logger.warning("Durable scrape worker cycle warning: %s", exc)
            self._wake_event.clear()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=SCRAPE_POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass

    def start_embedded_worker(self) -> None:
        if SCRAPE_WORKER_MODE == "external":
            recover_stale_scrape_tasks(force_recover_foreign_workers=False)
            logger.info("SCRAPE_WORKER_MODE=external; API server will enqueue tasks for dedicated worker processes.")
            return
        recover_stale_scrape_tasks(force_recover_foreign_workers=True)
        if self._consumer_task is not None and not self._consumer_task.done():
            return
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._consumer_task = asyncio.create_task(self._worker_loop())

    async def stop_embedded_worker(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._wake_event is not None:
            self._wake_event.set()
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None


scrape_queue = DurableScrapeQueue()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="TalentFlow AI Standalone Durable Scrape Worker")
    parser.add_argument("--once", action="store_true", help="Recover stale tasks, process one queued task, and exit")
    args = parser.parse_args()

    init_db()
    recover_stale_scrape_tasks(force_recover_foreign_workers=False)
    if args.once:
        asyncio.run(scrape_queue.process_one_queued_task())
    else:
        async def _run_forever() -> None:
            scrape_queue._stop_event = asyncio.Event()
            scrape_queue._wake_event = asyncio.Event()
            await scrape_queue._worker_loop()

        asyncio.run(_run_forever())
