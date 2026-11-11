import logging
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy import event, inspect
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
connect_args = {"check_same_thread": False} if is_sqlite else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


def init_db() -> None:
    """
    Initializes relational tables in SQLite (with WAL mode) or PostgreSQL.
    Automatically upgrades schema if older prototype tables exist without new columns.
    """
    try:
        inspector = inspect(engine)
        needs_upgrade = False
        if inspector.has_table("job_postings"):
            cols = {c["name"] for c in inspector.get_columns("job_postings")}
            if "channel" not in cols or "filter_out_reason" not in cols or "salary_is_estimated" not in cols or "delivery_channel" not in cols or "deadline_text" not in cols or "is_link_live" not in cols:
                needs_upgrade = True
        if inspector.has_table("application_records"):
            app_cols = {c["name"] for c in inspector.get_columns("application_records")}
            if "vacancy_id" not in app_cols or "submitted_salary" not in app_cols:
                needs_upgrade = True
        if inspector.has_table("users"):
            user_cols = {c["name"] for c in inspector.get_columns("users")}
            if "email_hash" not in user_cols:
                needs_upgrade = True
        if inspector.has_table("user_otps"):
            otp_cols = {c["name"] for c in inspector.get_columns("user_otps")}
            if "email_hash" not in otp_cols:
                needs_upgrade = True

        if needs_upgrade:
            logger.info("Upgrading database schema to encrypted relational schema...")
            SQLModel.metadata.drop_all(engine)
            if is_sqlite:
                try:
                    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                        conn.exec_driver_sql("VACUUM")
                except Exception as ve:
                    logger.debug(f"SQLite vacuum skipped: {ve}")
    except Exception as e:
        logger.debug(f"Schema inspection note: {e}")

    SQLModel.metadata.create_all(engine)


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
