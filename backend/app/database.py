import logging
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine
from .config import DATABASE_URL
from .models.db_models import CandidateProfile, JobPosting, ApplicationRecord  # noqa: F401

logger = logging.getLogger(__name__)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def init_db() -> None:
    """Creates all relational tables (CandidateProfile, JobPosting, ApplicationRecord) if they do not exist."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
