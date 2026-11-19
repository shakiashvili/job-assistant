import hashlib
import logging
from pathlib import Path
from typing import Optional
from sqlmodel import Session, select

from .database import engine
from .models import CandidateDocument

logger = logging.getLogger(__name__)


def record_candidate_document(
    user_id: Optional[int],
    filename: str,
    file_path: Path,
    doc_type: str = "generated_pdf",
    target_company: str = "",
    target_role: str = "",
    original_filename: Optional[str] = None,
) -> Optional[CandidateDocument]:
    """Persists or versions a user-owned CandidateDocument record with SHA-256 integrity hash."""
    if not file_path.exists():
        return None
    try:
        raw_bytes = file_path.read_bytes()
        sha = hashlib.sha256(raw_bytes).hexdigest()
        size_b = len(raw_bytes)
        with Session(engine) as session:
            stmt = select(CandidateDocument).where(
                CandidateDocument.filename == filename,
                CandidateDocument.doc_type == doc_type,
            )
            if user_id is not None:
                stmt = stmt.where(CandidateDocument.user_id == user_id)
            else:
                stmt = stmt.where(CandidateDocument.user_id.is_(None))
            existing = session.exec(stmt).first()
            if existing:
                existing.storage_path = str(file_path)
                existing.size_bytes = size_b
                existing.sha256_hash = sha
                if original_filename:
                    existing.original_filename = original_filename
                existing.version_number = (existing.version_number or 1) + 1
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing

            doc = CandidateDocument(
                user_id=user_id,
                doc_type=doc_type,
                filename=filename,
                original_filename=original_filename or filename,
                storage_path=str(file_path),
                size_bytes=size_b,
                sha256_hash=sha,
                version_number=1,
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            return doc
    except Exception as e:
        logger.debug(f"Could not record CandidateDocument for {filename}: {e}")
        return None
