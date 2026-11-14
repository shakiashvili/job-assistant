import logging
import os
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy import event
from ..config import DATABASE_URL, _is_prod
from .models import (
    User,
    UserOTP,
    ApplicationTracker,
    ApplicationRecord,
    ApplicationEvent,
    InterviewRound,
    InterviewNote,
    SkillActionPlan,
    CandidateProfile,
    CandidateSkill,
    CandidateExperience,
    CandidateEducation,
    CandidateDocument,
    JobPosting,
    UserJobMatch,
    SavedJob,
    SavedSearch,
    Notification,
    ScrapeTask,
)  # noqa: F401

logger = logging.getLogger(__name__)

is_sqlite = DATABASE_URL.startswith("sqlite")
if _is_prod and is_sqlite and os.getenv("ALLOW_SQLITE_IN_PROD", "").strip().lower() not in ("1", "true", "yes"):
    raise RuntimeError(
        "FATAL DATABASE ERROR: Production environment must not silently fall back to an ephemeral SQLite database. "
        "Configure a PostgreSQL DATABASE_URL (or set ALLOW_SQLITE_IN_PROD=true if using a mounted persistent volume)."
    )

if is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 15},
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
        pool_pre_ping=True,
        pool_recycle=300,
    )

if is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()


_MIGRATION_RUN_DONE = False


def init_db(force: bool = False) -> None:
    """
    Initializes and migrates relational database schema using Alembic as the primary source of truth,
    followed by SQLModel.metadata.create_all(engine) to guarantee all tables exist in test/dev environments.
    Logs any migration errors visibly.
    """
    global _MIGRATION_RUN_DONE
    if _MIGRATION_RUN_DONE and not force:
        return
    try:
        from pathlib import Path
        from alembic import command
        from alembic.config import Config

        base_dir = Path(__file__).resolve().parents[2]
        alembic_ini = base_dir / "alembic.ini"
        if alembic_ini.exists():
            cfg = Config(str(alembic_ini))
            cfg.set_main_option("sqlalchemy.url", str(engine.url).replace("%", "%%"))
            command.upgrade(cfg, "head")
    except Exception as e:
        logger.error(f"Alembic migration error (falling back to metadata sync): {e}")

    try:
        SQLModel.metadata.create_all(engine)
        _MIGRATION_RUN_DONE = True
    except Exception as e:
        logger.error(f"Database schema initialization failed: {e}")
        raise


def get_session() -> Generator[Session, None, None]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


def delete_job_posting_cascade(session: Session, job: JobPosting) -> None:
    """Safely deletes child references before deleting a JobPosting."""
    from sqlmodel import delete
    from sqlalchemy import select as sa_select

    with session.no_autoflush:
        if job.id is not None:
            tracker_ids_subq = sa_select(ApplicationTracker.id).where(ApplicationTracker.job_posting_id == job.id)
            round_ids_subq = sa_select(InterviewRound.id).where(InterviewRound.application_id.in_(tracker_ids_subq))
            session.exec(
                delete(InterviewNote).where(
                    (InterviewNote.application_id.in_(tracker_ids_subq))
                    | (InterviewNote.interview_round_id.in_(round_ids_subq))
                )
            )
            session.exec(delete(InterviewRound).where(InterviewRound.application_id.in_(tracker_ids_subq)))
            session.exec(delete(ApplicationEvent).where(ApplicationEvent.application_id.in_(tracker_ids_subq)))
            session.exec(delete(UserJobMatch).where(UserJobMatch.job_posting_id == job.id))
            session.exec(delete(SavedJob).where(SavedJob.job_posting_id == job.id))
            session.exec(delete(Notification).where(Notification.job_posting_id == job.id))
            session.exec(delete(CandidateDocument).where(CandidateDocument.job_posting_id == job.id))
            session.exec(
                delete(ApplicationRecord).where(
                    (ApplicationRecord.job_id == job.id)
                    | (ApplicationRecord.job_posting_id == job.id)
                    | (ApplicationRecord.vacancy_id == job.id)
                )
            )
            session.exec(delete(ApplicationTracker).where(ApplicationTracker.job_posting_id == job.id))
        session.delete(job)


