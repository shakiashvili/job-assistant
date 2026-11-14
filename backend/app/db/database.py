import logging
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy import event
from ..config import DATABASE_URL
from .models import (
    User,
    UserOTP,
    ApplicationTracker,
    InterviewRound,
    SkillActionPlan,
    CandidateProfile,
    JobPosting,
    ApplicationRecord,
)  # noqa: F401

logger = logging.getLogger(__name__)

is_sqlite = DATABASE_URL.startswith("sqlite")
if is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
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
        cursor.close()


_MIGRATION_RUN_DONE = False


def init_db() -> None:
    """
    Initializes and migrates relational database schema using Alembic as the single source of truth.
    Runs `alembic upgrade head` to ensure all migrations are applied cleanly without
    conflicting with SQLModel.metadata.create_all or manual ALTER TABLE statements.
    """
    global _MIGRATION_RUN_DONE
    if _MIGRATION_RUN_DONE:
        return
    try:
        from pathlib import Path
        from alembic import command
        from alembic.config import Config

        base_dir = Path(__file__).resolve().parents[2]
        alembic_ini = base_dir / "alembic.ini"
        if alembic_ini.exists():
            cfg = Config(str(alembic_ini))
            command.upgrade(cfg, "head")
            _MIGRATION_RUN_DONE = True
    except Exception as e:
        logger.debug(f"Alembic auto-upgrade note: {e}")


def get_session() -> Generator[Session, None, None]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


def delete_job_posting_cascade(session: Session, job: JobPosting) -> None:
    """Safely deletes child ApplicationRecord references before deleting a JobPosting."""
    if job.id is not None:
        children = session.exec(
            select(ApplicationRecord).where(
                (ApplicationRecord.job_id == job.id)
                | (ApplicationRecord.job_posting_id == job.id)
                | (ApplicationRecord.vacancy_id == job.id)
            )
        ).all()
        for child in children:
            session.delete(child)
    session.delete(job)
