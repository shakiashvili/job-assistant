import hashlib
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, Optional, Set, Tuple
from sqlmodel import Session, select

from ..config import GENERATED_RESUMES_DIR, RESUMES_DIR
from ..services.storage_service import storage_service
from .database import engine
from .models import CandidateDocument, CVVersion, User

logger = logging.getLogger(__name__)

_SAFE_GEN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,180}\.(pdf|docx|html|eml|md|txt)$", re.IGNORECASE)
USER_CV_DIR = RESUMES_DIR / "user_uploads"


def is_valid_safe_doc_name(filename: Optional[str]) -> Optional[str]:
    """Validates a single-segment generated/uploaded document filename cleanly."""
    raw = (filename or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw or "\x00" in raw:
        return None
    safe_name = Path(raw).name
    if safe_name != raw or not _SAFE_GEN_NAME_RE.match(safe_name):
        return None
    return safe_name


def resolve_user_id_by_email(owner_email: Optional[str]) -> Optional[int]:
    """Resolves a non-guest User.id by encrypted email blind index without raising."""
    clean = (owner_email or "").strip().lower()
    if not clean or clean == "guest@talentflow.local":
        return None
    try:
        from ..services.crypto_service import blind_index_candidates

        candidates = blind_index_candidates(clean)
        with Session(engine) as session:
            user = session.exec(select(User).where(User.email_hash.in_(candidates))).first()
            return user.id if user else None
    except Exception as exc:
        logger.debug("Could not resolve user_id from owner_email: %s", exc)
        return None


def user_generated_resumes_dir(
    user_id: Optional[int] = None,
    owner_email: Optional[str] = None,
) -> Path:
    """
    Returns an isolated generated-CV storage directory per authenticated user:
    - Authenticated users (`user_id` resolved): `GENERATED_RESUMES_DIR / f"user_{user_id}"`
    - Unauthenticated direct unit calls (`user_id is None`): root `GENERATED_RESUMES_DIR`
    """
    uid = user_id if user_id is not None else resolve_user_id_by_email(owner_email)
    gen_root = GENERATED_RESUMES_DIR.resolve()
    gen_root.mkdir(parents=True, exist_ok=True)
    if uid is None:
        return gen_root
    target = (gen_root / f"user_{int(uid)}").resolve()
    if not target.is_relative_to(gen_root):
        raise ValueError("Invalid generated resume storage directory.")
    target.mkdir(parents=True, exist_ok=True)
    return target


def user_uploaded_resumes_dir(user_id: Optional[int] = None) -> Path:
    """Returns dedicated per-user uploaded CV directory under USER_CV_DIR."""
    base = USER_CV_DIR.resolve()
    base.mkdir(parents=True, exist_ok=True)
    folder = f"user_{int(user_id)}" if user_id is not None else "guest"
    target = (base / folder).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Invalid user upload directory.")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _hydrate_owned_generated_file(
    safe_name: str,
    user_dir: Path,
    owned_docs: list[CandidateDocument],
    owned_vers: list[CVVersion],
) -> Optional[Path]:
    """Hydrates a missing user-owned generated CV artifact from S3/R2, encrypted DB blob, or CVVersion HTML."""
    target = (user_dir / safe_name).resolve()
    if not target.is_relative_to(user_dir):
        return None
    for d in owned_docs:
        if d.filename == safe_name:
            hydrated = storage_service.hydrate_local_file(
                target,
                storage_backend=getattr(d, "storage_backend", None),
                object_key=getattr(d, "object_key", None),
                encrypted_content=getattr(d, "encrypted_content", None),
                expected_sha256=d.sha256_hash,
            )
            if hydrated is not None and hydrated.is_file():
                return hydrated
    if safe_name.lower().endswith(".html"):
        for v in owned_vers:
            if v.rendered_html:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(v.rendered_html, encoding="utf-8")
                return target
    return None


def resolve_owned_generated_document(
    filename: str,
    user_id: Optional[int],
    *,
    is_guest: bool = False,
) -> Tuple[Optional[Path], Optional[str]]:
    """
    Fail-closed resolution for generated resumes (.pdf/.docx/.html/.eml):
    - Authenticated non-guest users MUST have a matching CandidateDocument or CVVersion owned by `user_id`
      AND a physical file strictly within `GENERATED_RESUMES_DIR / f"user_{user_id}"`.
    - Local guest callers (only reachable outside production) are still blocked (`forbidden`) from files
      owned by any non-guest user or stored inside any `user_<id>` folder.
    Returns `(resolved_path, error_reason)` where `error_reason` is `None`, `'invalid'`, `'forbidden'`, or `'not_found'`.
    """
    safe_name = is_valid_safe_doc_name(filename)
    if not safe_name:
        return None, "invalid"

    stem = Path(safe_name).stem
    candidate_names = {safe_name, f"{stem}.pdf", f"{stem}.docx"}
    gen_root = GENERATED_RESUMES_DIR.resolve()

    with Session(engine) as session:
        docs = session.exec(
            select(CandidateDocument).where(CandidateDocument.filename.in_(list(candidate_names)))
        ).all()
        versions = session.exec(
            select(CVVersion).where(
                CVVersion.pdf_filename.in_(list(candidate_names))
                | CVVersion.docx_filename.in_(list(candidate_names))
            )
        ).all()

        owned_docs = [d for d in docs if user_id is not None and d.user_id == user_id]
        owned_vers = [v for v in versions if user_id is not None and v.user_id == user_id]

        if not is_guest:
            if user_id is None:
                return None, "forbidden"

            user_dir = user_generated_resumes_dir(user_id)
            if not owned_docs and not owned_vers:
                if any(d.user_id is not None and d.user_id != user_id for d in docs) or any(
                    v.user_id is not None and v.user_id != user_id for v in versions
                ):
                    return None, "forbidden"
                return None, "not_found"

            for d in owned_docs:
                if d.filename == safe_name and d.storage_path:
                    cand = Path(d.storage_path).resolve()
                    if cand.is_relative_to(user_dir) and cand.is_file():
                        return cand, None

            sibling = (user_dir / safe_name).resolve()
            if sibling.is_relative_to(user_dir) and sibling.is_file():
                return sibling, None

            hydrated = _hydrate_owned_generated_file(safe_name, user_dir, owned_docs, owned_vers)
            if hydrated is not None:
                return hydrated, None
            return None, "not_found"

        # Guest caller (non-production local mode only): serve guest's own file first if recorded
        if user_id is not None and (owned_docs or owned_vers):
            guest_dir = user_generated_resumes_dir(user_id)
            for d in owned_docs:
                if d.filename == safe_name and d.storage_path:
                    cand = Path(d.storage_path).resolve()
                    if cand.is_relative_to(guest_dir) and cand.is_file():
                        return cand, None
            guest_cand = (guest_dir / safe_name).resolve()
            if guest_cand.is_relative_to(guest_dir) and guest_cand.is_file():
                return guest_cand, None
            hydrated = _hydrate_owned_generated_file(safe_name, guest_dir, owned_docs, owned_vers)
            if hydrated is not None:
                return hydrated, None

        if any(d.user_id is not None and d.user_id != user_id for d in docs) or any(
            v.user_id is not None and v.user_id != user_id for v in versions
        ):
            return None, "forbidden"

        if user_id is not None:
            guest_dir = user_generated_resumes_dir(user_id)
            guest_cand = (guest_dir / safe_name).resolve()
            if guest_cand.is_relative_to(guest_dir) and guest_cand.is_file():
                return guest_cand, None

        # Only unowned direct root files (from unauthenticated local Python unit helpers) may resolve for guest
        root_cand = (gen_root / safe_name).resolve()
        if root_cand.parent == gen_root and root_cand.is_relative_to(gen_root) and root_cand.is_file():
            return root_cand, None
        return None, "not_found"


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
        backend_name, obj_key, enc_blob = storage_service.persist_document(
            user_id=user_id,
            doc_type=doc_type,
            filename=filename,
            raw_bytes=raw_bytes,
        )
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
                existing.storage_backend = backend_name
                existing.object_key = obj_key
                existing.encrypted_content = enc_blob
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
                storage_backend=backend_name,
                object_key=obj_key,
                encrypted_content=enc_blob,
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


def migrate_legacy_generated_resumes(session: Optional[Session] = None) -> Dict[str, int]:
    """
    Migrates pre-isolation generated CV files from flat GENERATED_RESUMES_DIR root into
    per-user directories (`GENERATED_RESUMES_DIR / f"user_{user_id}"`) and updates
    `CandidateDocument.storage_path`.

    Fail-closed collision safety:
    - Files claimed by multiple distinct user IDs are skipped (never assigned blindly).
    - Unowned files with no non-null CandidateDocument/CVVersion user_id are untouched.
    """
    gen_root = GENERATED_RESUMES_DIR.resolve()
    if not gen_root.exists():
        return {"moved_files": 0, "updated_records": 0, "skipped_ambiguous": 0, "skipped_existing": 0}

    def _run(db: Session) -> Dict[str, int]:
        moved_files = 0
        updated_records = 0
        skipped_ambiguous = 0
        skipped_existing = 0

        file_owners: Dict[str, Set[int]] = {}
        stem_owners: Dict[str, Set[int]] = {}
        docs_by_name: Dict[str, list[CandidateDocument]] = {}

        docs = db.exec(
            select(CandidateDocument).where(
                CandidateDocument.user_id.is_not(None),
                CandidateDocument.doc_type != "uploaded_cv",
            )
        ).all()
        for doc in docs:
            safe = is_valid_safe_doc_name(doc.filename)
            if not safe or doc.user_id is None:
                continue
            uid = int(doc.user_id)
            file_owners.setdefault(safe, set()).add(uid)
            stem_owners.setdefault(Path(safe).stem, set()).add(uid)
            docs_by_name.setdefault(safe, []).append(doc)

        versions = db.exec(select(CVVersion).where(CVVersion.user_id.is_not(None))).all()
        for ver in versions:
            if ver.user_id is None:
                continue
            uid = int(ver.user_id)
            for raw_name in (ver.pdf_filename, ver.docx_filename):
                safe = is_valid_safe_doc_name(raw_name)
                if not safe:
                    continue
                file_owners.setdefault(safe, set()).add(uid)
                stem_owners.setdefault(Path(safe).stem, set()).add(uid)

        # Also attribute unambiguous sibling root artifacts (.html/.eml/.docx/.pdf sharing exact stem)
        for item in list(gen_root.iterdir()):
            if not item.is_file():
                continue
            safe = is_valid_safe_doc_name(item.name)
            if not safe or safe in file_owners:
                continue
            s_owners = stem_owners.get(Path(safe).stem)
            if s_owners and len(s_owners) == 1:
                file_owners[safe] = set(s_owners)

        for fname, owners in file_owners.items():
            if len(owners) > 1:
                logger.warning(
                    "Skipping legacy CV migration for '%s': claimed by multiple users %s",
                    fname,
                    sorted(owners),
                )
                skipped_ambiguous += 1
                continue
            if not owners:
                continue

            uid = next(iter(owners))
            user_dir = user_generated_resumes_dir(uid)
            root_src = (gen_root / fname).resolve()
            dest = (user_dir / fname).resolve()
            if root_src.parent != gen_root or not dest.is_relative_to(user_dir):
                continue

            if root_src.is_file():
                if not dest.exists():
                    shutil.move(str(root_src), str(dest))
                    moved_files += 1
                else:
                    skipped_existing += 1

            if dest.is_file():
                for doc in docs_by_name.get(fname, []):
                    if doc.user_id == uid and doc.storage_path != str(dest):
                        doc.storage_path = str(dest)
                        db.add(doc)
                        updated_records += 1

        if updated_records:
            db.commit()

        return {
            "moved_files": moved_files,
            "updated_records": updated_records,
            "skipped_ambiguous": skipped_ambiguous,
            "skipped_existing": skipped_existing,
        }

    if session is not None:
        return _run(session)
    with Session(engine) as own_session:
        return _run(own_session)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="TalentFlow generated-document repository maintenance CLI")
    parser.add_argument(
        "--migrate-legacy-cvs",
        action="store_true",
        help="Move unambiguous legacy shared generated CVs into per-user directories",
    )
    args = parser.parse_args()
    if args.migrate_legacy_cvs:
        summary = migrate_legacy_generated_resumes()
        print(f"Legacy CV migration complete: {summary}")
