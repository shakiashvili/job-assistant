import logging
import os
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine
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
    CVVersion,
    AIOperationLog,
    AICacheEntry,
    AuthRateLimit,
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
    Initializes and migrates relational database schema using Alembic as the single source of truth
    for file-backed and server databases. Migration failures propagate loudly rather than being masked
    by create_all(). In-memory SQLite engines still use metadata.create_all() because Alembic opens its
    own connection pool.
    """
    global _MIGRATION_RUN_DONE
    if _MIGRATION_RUN_DONE and not force:
        return

    from pathlib import Path

    base_dir = Path(__file__).resolve().parents[2]
    alembic_ini = base_dir / "alembic.ini"
    is_in_memory = is_sqlite and (
        engine.url.database in (None, "", ":memory:")
        or ":memory:" in str(engine.url)
    )

    if alembic_ini.exists() and not is_in_memory:
        try:
            from sqlalchemy import inspect as sa_inspect
            from alembic import command
            from alembic.config import Config

            cfg = Config(str(alembic_ini))
            cfg.set_main_option(
                "sqlalchemy.url",
                engine.url.render_as_string(hide_password=False).replace("%", "%%"),
            )
            # Safely adopt pre-Alembic legacy databases created via create_all() without crashing on initial_schema
            with engine.connect() as conn:
                inspector = sa_inspect(conn)
                existing_tables = set(inspector.get_table_names())
                has_alembic = "alembic_version" in existing_tables
                has_legacy_core = "users" in existing_tables and "job_postings" in existing_tables
                alembic_empty = False
                if has_alembic:
                    from sqlalchemy import text as sa_text
                    alembic_empty = conn.execute(sa_text("SELECT COUNT(*) FROM alembic_version")).scalar() == 0
            if has_legacy_core and (not has_alembic or alembic_empty):
                logger.info("Adopting pre-Alembic database schema at baseline revision 75cd228268f5 before upgrading.")
                command.stamp(cfg, "75cd228268f5")
            command.upgrade(cfg, "head")
        except Exception as e:
            logger.critical(f"Alembic migration failed — refusing to mask schema error: {e}")
            raise RuntimeError(f"Database migration failed: {e}") from e
    else:
        try:
            SQLModel.metadata.create_all(engine)
        except Exception as e:
            logger.error(f"Database schema initialization failed: {e}")
            raise

    try:
        from .document_repository import migrate_legacy_generated_resumes

        migrate_legacy_generated_resumes()
    except Exception as e:
        logger.warning("Legacy generated CV migration step reported a non-fatal warning: %s", e)

    _MIGRATION_RUN_DONE = True


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


