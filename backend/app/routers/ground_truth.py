import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select, delete

from ..db.profile_repository import ground_truth_store, PROFESSION_MD_PRESETS
from ..db.models import (
    User,
    JobPosting,
    UserJobMatch,
    SavedJob,
    ApplicationRecord,
    ApplicationTracker,
    CandidateDocument,
    CVVersion,
    utc_now,
)
from ..services.auth_service import get_current_user
from ..services.answer_service import load_live_candidate_profile
from ..config import RESUMES_DIR, GENERATED_RESUMES_DIR
from ..db.database import engine, delete_job_posting_cascade

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Ground Truth, Skills.md & Resumes"])

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

USER_CV_DIR = RESUMES_DIR / "user_uploads"
USER_CV_DIR.mkdir(parents=True, exist_ok=True)


def _is_guest(user: Optional[User]) -> bool:
    return not user or (user.email or "").strip().lower() == "guest@talentflow.local"


def _purge_stale_unapplied_jobs(user: Optional[User] = None) -> None:
    """
    Clears stale unapplied job matches for the current user when they switch profession preset
    or upload a new skills.md, without deleting JobPosting records tracked or matched by other users.
    """
    try:
        with Session(engine) as session:
            if user and user.id is not None:
                session.exec(
                    delete(UserJobMatch).where(UserJobMatch.user_id == user.id)
                )

            # Only purge global unapplied JobPosting rows if no user has saved/applied to them
            # and no other user has a UserJobMatch pointing to them
            if _is_guest(user):
                for job in session.exec(select(JobPosting)).all():
                    if job.status != "APPLIED":
                        other_match = session.exec(
                            select(UserJobMatch).where(UserJobMatch.job_posting_id == job.id)
                        ).first()
                        other_saved = session.exec(
                            select(SavedJob).where(SavedJob.job_posting_id == job.id)
                        ).first()
                        if not other_match and not other_saved:
                            delete_job_posting_cascade(session, job)
            session.commit()
    except Exception as e:
        logger.debug(f"Purge unapplied jobs skipped: {e}")


def _user_cv_dir(user_id: Optional[int]) -> Path:
    """Returns the dedicated per-user upload directory inside USER_CV_DIR."""
    folder = f"user_{user_id}" if user_id is not None else "guest"
    d = (USER_CV_DIR / folder).resolve()
    if not d.is_relative_to(USER_CV_DIR.resolve()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user storage directory.")
    d.mkdir(parents=True, exist_ok=True)
    return d


def record_candidate_document(
    user_id: Optional[int],
    filename: str,
    file_path: Path,
    doc_type: str = "generated_pdf",
    target_company: str = "",
    target_role: str = "",
    original_filename: Optional[str] = None,
) -> Optional[CandidateDocument]:
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


_SAFE_DOC_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,180}\.(pdf|docx|html|eml|md|txt)$", re.IGNORECASE)
_HTML_PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; font-src 'self' data:; img-src data:;"


def _sanitize_safe_filename(filename: str) -> str:
    raw = (filename or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw or "\x00" in raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid document filename.")
    safe_name = Path(raw).name
    if not _SAFE_DOC_NAME_RE.match(safe_name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported or unsafe document filename.")
    return safe_name


def _sanitize_uploaded_cv_name(raw_filename: Optional[str]) -> str:
    raw = (raw_filename or "resume.pdf").strip()
    if "/" in raw or "\\" in raw or ".." in raw or "\x00" in raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid uploaded filename.")
    base = Path(raw).name
    ext = Path(base).suffix.lower()
    if ext not in (".pdf", ".docx", ".md", ".txt"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported format. Upload .pdf, .docx, .md, or .txt.")
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(base).stem).strip("._-") or "resume"
    candidate_name = f"{stem[:150]}{ext}"
    return _sanitize_safe_filename(candidate_name)


def _verify_document_ownership(filename: str, current_user: User) -> None:
    safe_name = _sanitize_safe_filename(filename)
    stem = Path(safe_name).stem
    with Session(engine) as session:
        docs = session.exec(
            select(CandidateDocument).where(
                (CandidateDocument.filename == safe_name)
                | (CandidateDocument.filename == f"{stem}.pdf")
                | (CandidateDocument.filename == f"{stem}.docx")
            )
        ).all()
        if any(doc.user_id == current_user.id for doc in docs):
            return
        for doc in docs:
            if doc.user_id is not None and doc.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: document belongs to another user.",
                )


def _is_file_visible_to_user(filename: str, current_user: User, owner_map: Dict[str, Any]) -> bool:
    safe_name = Path(filename).name
    stem = Path(safe_name).stem
    owners: set = set()
    for key in (safe_name, f"{stem}.pdf", f"{stem}.docx"):
        val = owner_map.get(key)
        if isinstance(val, (set, list, tuple)):
            owners.update(v for v in val if v is not None)
        elif val is not None:
            owners.add(val)
    if owners:
        return current_user.id in owners
    return _is_guest(current_user)


class SkillsMdPayload(BaseModel):
    content: str


class GenerateEditionRequest(BaseModel):
    edition: str = "ats"  # "ats", "recruiter", or "tailored"
    target_role: Optional[str] = None
    target_company: Optional[str] = None
    job_description: Optional[str] = ""
    job_url: Optional[str] = None
    cv_language: str = "en"


@router.get("/ground-truth")
def get_ground_truth(current_user: User = Depends(get_current_user)):
    """Returns candidate profile, skills, work history, FAQ bank, and skills_md_raw for the current user."""
    return ground_truth_store.get_data(
        owner_email=current_user.email,
        user_id=current_user.id,
    )


@router.put("/ground-truth")
def update_ground_truth(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
):
    """Updates candidate profile vault and automatically syncs all saved CVs & Word/PDF editions."""
    from ..services.cv_generator_service import cv_generator_service

    try:
        updated = ground_truth_store.update_data(
            payload,
            owner_email=current_user.email,
            user_id=current_user.id,
        )
        synced_cv_versions = cv_generator_service.sync_user_cv_versions(
            user_id=current_user.id,
            owner_email=current_user.email,
        )
        return {
            "status": "success",
            "message": "Ground truth updated successfully",
            "synced_cv_versions": synced_cv_versions,
            "data": updated,
        }
    except Exception as e:
        logger.error(f"Error updating ground truth: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update profile data.")


@router.get("/skills-md")
def get_skills_md(current_user: User = Depends(get_current_user)):
    """Returns the attached candidate_skills.md content and extracted skills for the current user."""
    content = ground_truth_store.get_skills_md(
        owner_email=current_user.email,
        user_id=current_user.id,
    )
    extracted = ground_truth_store.extract_skills_from_md(content)
    return {
        "filename": "candidate_skills.md",
        "content": content,
        "extracted_skills": extracted,
    }


@router.get("/skills-md/presets")
def get_skills_md_presets():
    """Returns built-in multi-industry .md skills templates."""
    return {
        "presets": [
            {
                "id": "qa_tech",
                "label": "💻 QA Automation & Tech",
                "role": "QA Automation Engineer & SDET",
                "content": PROFESSION_MD_PRESETS["qa_tech"]["content"],
            },
            {
                "id": "receptionist_hospitality",
                "label": "🏨 Receptionist & Hospitality (EN/KA)",
                "role": "Front Desk Receptionist & Guest Relations",
                "content": PROFESSION_MD_PRESETS["receptionist_hospitality"]["content"],
            },
            {
                "id": "customer_service",
                "label": "🎧 Customer Service & Support (EN/KA)",
                "role": "Senior Customer Service Specialist",
                "content": PROFESSION_MD_PRESETS["customer_service"]["content"],
            },
            {
                "id": "healthcare_hospital",
                "label": "🏥 Hospital & Healthcare Admin (EN/KA)",
                "role": "Hospital Patient Coordinator / Medical Receptionist",
                "content": PROFESSION_MD_PRESETS["healthcare_hospital"]["content"],
            },
        ]
    }


@router.post("/skills-md/preset/{preset_id}")
def apply_skills_md_preset(
    preset_id: str,
    current_user: User = Depends(get_current_user),
):
    """Loads a multi-industry .md preset for the current user while preserving non-example candidate identity."""
    try:
        prev_gt = ground_truth_store.get_data(
            owner_email=current_user.email,
            user_id=current_user.id,
        )
        prev_cand = dict(prev_gt.get("candidate") or {})
        has_real_identity = (
            prev_cand.get("email")
            and not str(prev_cand.get("email")).endswith("@example.com")
            and "candidate" not in str(prev_cand.get("email")).lower()
        )

        md_content = ground_truth_store.get_preset_md(preset_id)
        updated_gt = ground_truth_store.save_skills_md(
            md_content,
            owner_email=current_user.email,
            user_id=current_user.id,
        )
        if has_real_identity:
            cand = dict(updated_gt.get("candidate") or {})
            for key in ("full_name", "first_name", "last_name", "email", "phone", "links"):
                if prev_cand.get(key):
                    cand[key] = prev_cand[key]
            updated_gt["candidate"] = cand
            updated_gt = ground_truth_store.update_data(
                updated_gt,
                owner_email=current_user.email,
                user_id=current_user.id,
            )

        _purge_stale_unapplied_jobs(user=current_user)
        from ..services.cv_generator_service import cv_generator_service
        synced_cv_versions = cv_generator_service.sync_user_cv_versions(
            user_id=current_user.id,
            owner_email=current_user.email,
        )
        extracted = ground_truth_store.extract_skills_from_md(md_content)
        return {
            "status": "success",
            "preset_id": preset_id,
            "content": md_content,
            "extracted_skills": extracted,
            "synced_cv_versions": synced_cv_versions,
            "ground_truth": updated_gt,
            "message": f"Loaded '{preset_id}' profile template ({len(extracted)} skills synced).",
        }
    except Exception as e:
        logger.error(f"Error applying preset {preset_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to apply profile preset.")


@router.post("/skills-md")
def save_skills_md_text(
    payload: SkillsMdPayload,
    current_user: User = Depends(get_current_user),
):
    """Updates candidate_skills.md from raw markdown text for the current user."""
    if len(payload.content.encode("utf-8")) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Markdown payload exceeds 10 MB limit.")
    try:
        from ..services.scrapers.scraper_orchestrator import scraper_orchestrator
        owner = current_user.email if not _is_guest(current_user) else None
        uid = current_user.id if not _is_guest(current_user) else None
        updated_gt = ground_truth_store.save_skills_md(
            payload.content,
            owner_email=owner,
            user_id=uid,
        )
        scraper_orchestrator.rescore_existing_jobs(owner_email=owner, user_id=uid)
        from ..services.cv_generator_service import cv_generator_service
        synced_cv_versions = cv_generator_service.sync_user_cv_versions(
            user_id=current_user.id,
            owner_email=current_user.email,
        )
        extracted = ground_truth_store.extract_skills_from_md(payload.content)
        return {
            "status": "success",
            "message": f"Saved candidate_skills.md ({len(extracted)} skills synced).",
            "extracted_skills": extracted,
            "synced_cv_versions": synced_cv_versions,
            "ground_truth": updated_gt,
        }
    except Exception as e:
        logger.error(f"Error saving skills.md: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save skills profile.")


@router.post("/skills-md/upload")
async def upload_skills_md_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Accepts .pdf, .docx, .md, or .txt resume/skills uploads, parses profile & computes missing fields."""
    from ..services.cv_parser_service import cv_parser_service

    raw_bytes = await file.read()
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds 10 MB maximum size limit.")
    filename = file.filename or "candidate_skills.md"
    try:
        md_text = cv_parser_service.extract_text_from_bytes(raw_bytes, filename=filename)
    except ValueError as parse_err:
        raise HTTPException(status_code=400, detail=str(parse_err))
    try:
        from ..services.scrapers.scraper_orchestrator import scraper_orchestrator
        owner = current_user.email if not _is_guest(current_user) else None
        uid = current_user.id if not _is_guest(current_user) else None
        updated_gt = ground_truth_store.save_skills_md(
            md_text,
            owner_email=owner,
            user_id=uid,
        )
        scraper_orchestrator.rescore_existing_jobs(owner_email=owner, user_id=uid)
        from ..services.cv_generator_service import cv_generator_service
        synced_cv_versions = cv_generator_service.sync_user_cv_versions(
            user_id=current_user.id,
            owner_email=current_user.email,
        )
        extracted = ground_truth_store.extract_skills_from_md(md_text)
        completeness_score, missing_fields = cv_parser_service.compute_missing_fields(updated_gt)
        return {
            "status": "success",
            "filename": filename,
            "content": md_text,
            "extracted_skills": extracted,
            "synced_cv_versions": synced_cv_versions,
            "completeness_score": completeness_score,
            "missing_fields": missing_fields,
            "ground_truth": updated_gt,
            "message": f"Uploaded {filename} and synced {len(extracted)} skills!",
        }
    except Exception as e:
        logger.error(f"Error uploading skills/CV file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process uploaded CV file.")


@router.get("/cv-variants")
def get_cv_variants(current_user: User = Depends(get_current_user)):
    """Lists CV variants for the current user."""
    return ground_truth_store.get_data(
        owner_email=current_user.email,
        user_id=current_user.id,
    ).get("cv_variants", {})


@router.get("/resumes/my-cvs")
def list_my_uploaded_cvs(current_user: User = Depends(get_current_user)):
    """Lists user-uploaded personal CV files (.pdf, .docx, .md, .txt) strictly scoped to the current user."""
    files = []
    seen_names: set[str] = set()
    user_dir = _user_cv_dir(current_user.id)
    base_resolved = USER_CV_DIR.resolve()

    with Session(engine) as session:
        user_docs = session.exec(
            select(CandidateDocument)
            .where(
                CandidateDocument.user_id == current_user.id,
                CandidateDocument.doc_type == "uploaded_cv",
            )
            .order_by(CandidateDocument.created_at.desc())
        ).all()

    for doc in user_docs:
        p = Path(doc.storage_path).resolve() if doc.storage_path else (user_dir / doc.filename).resolve()
        if not p.is_relative_to(base_resolved) or not p.is_file():
            continue
        if p.suffix.lower() not in (".pdf", ".docx", ".md", ".txt"):
            continue
        if doc.filename in seen_names:
            continue
        seen_names.add(doc.filename)
        files.append({
            "filename": doc.filename,
            "original_filename": doc.original_filename or doc.filename,
            "url": f"/api/resumes/user/{doc.filename}",
            "ext": p.suffix.lower().lstrip("."),
            "size_kb": round(p.stat().st_size / 1024, 1),
        })

    for f in sorted(user_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".md", ".txt") and f.name not in seen_names:
            seen_names.add(f.name)
            files.append({
                "filename": f.name,
                "original_filename": f.name,
                "url": f"/api/resumes/user/{f.name}",
                "ext": f.suffix.lower().lstrip("."),
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
    return files


@router.post("/resumes/my-cvs/upload")
async def upload_personal_cv(
    file: UploadFile = File(...),
    parse_into_profile: bool = Form(True),
    current_user: User = Depends(get_current_user),
):
    """Uploads a personal resume (.pdf, .docx, .md, .txt) into isolated per-user storage and optionally parses it."""
    from ..services.cv_parser_service import cv_parser_service

    safe_name = _sanitize_uploaded_cv_name(file.filename)
    ext = Path(safe_name).suffix.lower()

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds 10 MB maximum size limit.")
    if ext == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid PDF file header.")
    if ext == ".docx" and not content.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="Invalid DOCX file header.")

    parsed_summary: Optional[Dict[str, Any]] = None
    if parse_into_profile:
        try:
            extracted_md = cv_parser_service.extract_text_from_bytes(content, filename=safe_name)
            owner = current_user.email if not _is_guest(current_user) else None
            uid = current_user.id if not _is_guest(current_user) else None
            updated_gt = ground_truth_store.save_skills_md(
                extracted_md,
                owner_email=owner,
                user_id=uid,
            )
            from ..services.cv_generator_service import cv_generator_service
            synced_cv_versions = cv_generator_service.sync_user_cv_versions(
                user_id=current_user.id,
                owner_email=current_user.email,
            )
            completeness_score, missing_fields = cv_parser_service.compute_missing_fields(updated_gt)
            parsed_summary = {
                "completeness_score": completeness_score,
                "missing_fields": missing_fields,
                "extracted_skills_count": len((updated_gt.get("skills") or {}).get("core") or []),
                "synced_cv_versions": synced_cv_versions,
            }
        except ValueError as parse_err:
            parsed_summary = {
                "completeness_score": None,
                "missing_fields": [],
                "parse_warning": str(parse_err),
            }

    user_dir = _user_cv_dir(current_user.id)
    dest = (user_dir / safe_name).resolve()
    if not dest.is_relative_to(user_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid upload path.")
    dest.write_bytes(content)

    record_candidate_document(
        user_id=current_user.id,
        filename=safe_name,
        file_path=dest,
        doc_type="uploaded_cv",
        original_filename=Path(file.filename or safe_name).name,
    )

    return {
        "status": "ok",
        "filename": safe_name,
        "url": f"/api/resumes/user/{safe_name}",
        "ext": ext.lstrip("."),
        "size_kb": round(len(content) / 1024, 1),
        "parsed_profile": parsed_summary,
    }


def _resolve_user_uploaded_cv(filename: str, current_user: User) -> tuple[Path, Optional[int]]:
    """Resolves an uploaded personal CV strictly for current_user (raising 403 if owned solely by another user)."""
    safe_name = _sanitize_safe_filename(filename)
    base_resolved = USER_CV_DIR.resolve()
    user_dir = _user_cv_dir(current_user.id)

    with Session(engine) as session:
        user_doc = session.exec(
            select(CandidateDocument).where(
                CandidateDocument.filename == safe_name,
                CandidateDocument.doc_type == "uploaded_cv",
                CandidateDocument.user_id == current_user.id,
            )
        ).first()
        if user_doc:
            candidate_path = Path(user_doc.storage_path).resolve() if user_doc.storage_path else (user_dir / safe_name).resolve()
            if candidate_path.is_relative_to(base_resolved) and candidate_path.is_file():
                return candidate_path, user_doc.id

        local_candidate = (user_dir / safe_name).resolve()
        if local_candidate.is_relative_to(user_dir.resolve()) and local_candidate.is_file():
            return local_candidate, None

        other_doc = session.exec(
            select(CandidateDocument).where(
                CandidateDocument.filename == safe_name,
                CandidateDocument.doc_type == "uploaded_cv",
                CandidateDocument.user_id != current_user.id,
            )
        ).first()
        if other_doc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: document belongs to another user.",
            )

        if _is_guest(current_user):
            legacy = (USER_CV_DIR / safe_name).resolve()
            if legacy.is_relative_to(base_resolved) and legacy.is_file():
                return legacy, None

    raise HTTPException(status_code=404, detail="Uploaded CV not found")


@router.delete("/resumes/my-cvs/{filename}")
def delete_personal_cv(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Deletes an uploaded personal resume strictly scoped to current_user."""
    target, doc_id = _resolve_user_uploaded_cv(filename, current_user)
    safe_name = _sanitize_safe_filename(filename)
    target.unlink()
    with Session(engine) as session:
        stmt = delete(CandidateDocument).where(
            CandidateDocument.user_id == current_user.id,
            CandidateDocument.doc_type == "uploaded_cv",
            CandidateDocument.filename == safe_name,
        )
        if doc_id is not None:
            stmt = delete(CandidateDocument).where(
                CandidateDocument.id == doc_id,
                CandidateDocument.user_id == current_user.id,
            )
        session.exec(stmt)
        session.commit()
    return {"status": "deleted", "filename": safe_name}


@router.get("/resumes/user/{filename}")
def get_user_cv_file(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Downloads or previews a user-uploaded personal CV strictly scoped to current_user."""
    target, _ = _resolve_user_uploaded_cv(filename, current_user)
    safe_name = _sanitize_safe_filename(filename)
    lower = safe_name.lower()
    if lower.endswith(".docx"):
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif lower.endswith(".pdf"):
        media = "application/pdf"
    else:
        media = "text/plain; charset=utf-8"
    return FileResponse(path=target, filename=safe_name, media_type=media)


@router.post("/resumes/generate-edition")
def generate_cv_edition(
    req: GenerateEditionRequest,
    current_user: User = Depends(get_current_user),
):
    """Generates an ATS-Optimized, Recruiter-Ready, or Job-Tailored CV (Word .docx + PDF) + Cover Letter."""
    from ..services.cv_generator_service import cv_generator_service

    live = load_live_candidate_profile(current_user.email)
    gt = ground_truth_store.get_data(
        owner_email=current_user.email,
        user_id=current_user.id,
    )
    cand = gt.get("candidate", {})
    default_role = live.get("primary_role") or live.get("headline") or cand.get("headline") or "Specialist"
    role = (req.target_role or "").strip() or default_role
    company = (
        (req.target_company or "").strip()
        or ("ATS Edition" if req.edition == "ats" else "Recruiter Edition" if req.edition == "recruiter" else "Target Company")
    )
    desc = (req.job_description or "").strip()
    if req.job_url and req.job_url.strip():
        desc = f"{desc}\nJob URL: {req.job_url.strip()}".strip()

    pkg = cv_generator_service.prepare_email_application_package(
        job_title=role,
        company=company,
        description=desc,
        skills_md_override=live.get("skills_markdown") or None,
        owner_email=current_user.email,
        cv_language=req.cv_language or "en",
        cv_style=req.edition or "ats",
    )
    recorded_names: set[str] = set()
    for fname_key in ("pdf_filename", "docx_filename", "cv_filename"):
        fname_val = pkg.get(fname_key)
        if fname_val and fname_val not in recorded_names:
            recorded_names.add(fname_val)
            file_p = GENERATED_RESUMES_DIR / fname_val
            record_candidate_document(
                user_id=current_user.id,
                filename=fname_val,
                file_path=file_p,
                doc_type=f"generated_{req.edition}_cv",
                target_company=company,
                target_role=role,
            )

    cv_version_id: Optional[int] = None
    try:
        with Session(engine) as session:
            cv_ver = CVVersion(
                user_id=current_user.id,
                title=f"{role} — {company} ({req.edition.upper()})",
                target_company=company,
                target_role=role,
                edition=req.edition or "ats",
                cv_language=pkg.get("cv_language") or req.cv_language or "en",
                structured_content=pkg.get("cv_sections") or {},
                rendered_html=pkg.get("rendered_html") or "",
                pdf_filename=pkg.get("pdf_filename"),
                docx_filename=pkg.get("docx_filename"),
                version_number=1,
            )
            session.add(cv_ver)
            session.commit()
            session.refresh(cv_ver)
            cv_version_id = cv_ver.id
    except Exception as ver_err:
        logger.debug("Could not persist CVVersion snapshot: %s", ver_err)

    return {"status": "ok", "edition": req.edition, "cv_version_id": cv_version_id, **pkg}


class CVVersionCreateRequest(BaseModel):
    title: str
    target_company: str = ""
    target_role: str = ""
    edition: str = "tailored"
    language: str = "en"
    job_posting_id: Optional[int] = None
    structured_json: Dict[str, Any] = {}


class CVVersionPatchRequest(BaseModel):
    title: Optional[str] = None
    target_company: Optional[str] = None
    target_role: Optional[str] = None
    structured_json: Optional[Dict[str, Any]] = None
    language: Optional[str] = None
    edition: Optional[str] = None


def _serialize_cv_version(v: CVVersion) -> Dict[str, Any]:
    html_name = f"{Path(v.pdf_filename).stem}.html" if v.pdf_filename else None
    return {
        "id": v.id,
        "user_id": v.user_id,
        "job_posting_id": v.job_posting_id,
        "title": v.title,
        "target_company": v.target_company,
        "target_role": v.target_role,
        "edition": v.edition,
        "language": v.cv_language,
        "structured_json": v.structured_content or {},
        "rendered_html": v.rendered_html or "",
        "pdf_filename": v.pdf_filename,
        "docx_filename": v.docx_filename,
        "pdf_url": f"/api/resumes/generated/{v.pdf_filename}" if v.pdf_filename else None,
        "docx_url": f"/api/resumes/generated/{v.docx_filename}" if v.docx_filename else None,
        "html_preview_url": f"/api/resumes/generated/{html_name}" if html_name else None,
        "version_number": v.version_number,
        "is_active": v.is_active,
        "created_at": v.created_at.isoformat() if v.created_at else "",
        "updated_at": v.updated_at.isoformat() if v.updated_at else "",
    }


@router.get("/cv-versions")
def list_cv_versions(current_user: User = Depends(get_current_user)):
    """Lists all saved editable CV Studio versions for the current user."""
    with Session(engine) as session:
        rows = session.exec(
            select(CVVersion)
            .where(CVVersion.user_id == current_user.id)
            .order_by(CVVersion.updated_at.desc())
        ).all()
        return {"items": [_serialize_cv_version(r) for r in rows]}


@router.post("/cv-versions")
def create_cv_version(
    req: CVVersionCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Creates a new editable CV Studio version and renders its HTML, PDF, and DOCX files."""
    from ..services.cv_generator_service import cv_generator_service

    sections = dict(req.structured_json or {})
    if not sections:
        gt = ground_truth_store.get_data(owner_email=current_user.email, user_id=current_user.id)
        cand = gt.get("candidate") or {}
        sections = {
            "candidate": cand,
            "summary": cand.get("headline") or "",
            "skills": (gt.get("skills") or {}).get("core") or [],
            "work_history": gt.get("work_history") or [],
            "education": gt.get("education") or [],
            "target_role": req.target_role or cand.get("headline") or "Specialist",
            "target_company": req.target_company or "Tailored",
            "cv_language": req.language,
            "cv_style": req.edition,
        }

    rendered = cv_generator_service.render_cv_from_sections(sections)
    for fname in (rendered.get("pdf_filename"), rendered.get("docx_filename")):
        if fname:
            record_candidate_document(
                user_id=current_user.id,
                filename=fname,
                file_path=GENERATED_RESUMES_DIR / fname,
                doc_type=f"cv_studio_{req.edition}",
                target_company=req.target_company,
                target_role=req.target_role,
            )

    with Session(engine) as session:
        ver = CVVersion(
            user_id=current_user.id,
            job_posting_id=req.job_posting_id,
            title=req.title,
            target_company=req.target_company,
            target_role=req.target_role,
            edition=req.edition,
            cv_language=req.language,
            structured_content=sections,
            rendered_html=rendered.get("rendered_html") or "",
            pdf_filename=rendered.get("pdf_filename"),
            docx_filename=rendered.get("docx_filename"),
            version_number=1,
        )
        session.add(ver)
        session.commit()
        session.refresh(ver)
        return _serialize_cv_version(ver)


@router.patch("/cv-versions/{version_id}")
def update_cv_version(
    version_id: int,
    req: CVVersionPatchRequest,
    current_user: User = Depends(get_current_user),
):
    """Updates structured CV Studio sections and re-renders HTML, PDF, and DOCX files cleanly."""
    from ..services.cv_generator_service import cv_generator_service

    with Session(engine) as session:
        ver = session.get(CVVersion, version_id)
        if not ver or ver.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="CV version not found.")

        sections = dict(req.structured_json if req.structured_json is not None else (ver.structured_content or {}))
        if req.language:
            ver.cv_language = req.language
            sections["cv_language"] = req.language
        if req.edition:
            ver.edition = req.edition
            sections["cv_style"] = req.edition
        if req.target_role is not None and req.target_role.strip():
            ver.target_role = req.target_role.strip()
            sections["target_role"] = ver.target_role
        if req.target_company is not None and req.target_company.strip():
            ver.target_company = req.target_company.strip()
            sections["target_company"] = ver.target_company
        if req.title is not None and req.title.strip():
            ver.title = req.title.strip()

        rendered = cv_generator_service.render_cv_from_sections(
            sections,
            base_name_override=ver.pdf_filename,
        )
        for fname in (rendered.get("pdf_filename"), rendered.get("docx_filename")):
            if fname:
                record_candidate_document(
                    user_id=current_user.id,
                    filename=fname,
                    file_path=GENERATED_RESUMES_DIR / fname,
                    doc_type=f"cv_studio_{ver.edition}",
                    target_company=ver.target_company,
                    target_role=ver.target_role,
                )

        ver.structured_content = sections
        ver.rendered_html = rendered.get("rendered_html") or ""
        ver.pdf_filename = rendered.get("pdf_filename") or ver.pdf_filename
        ver.docx_filename = rendered.get("docx_filename") or ver.docx_filename
        ver.version_number = (ver.version_number or 1) + 1
        ver.updated_at = utc_now()
        session.add(ver)
        session.commit()
        session.refresh(ver)
        return _serialize_cv_version(ver)


@router.delete("/cv-versions/{version_id}")
def delete_cv_version(
    version_id: int,
    current_user: User = Depends(get_current_user),
):
    """Deletes an editable CV Studio version owned by the current user."""
    with Session(engine) as session:
        ver = session.get(CVVersion, version_id)
        if not ver or ver.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="CV version not found.")
        session.delete(ver)
        session.commit()
        return {"status": "deleted", "id": version_id}


@router.get("/resumes/generated")
def list_generated_resumes(current_user: User = Depends(get_current_user)):
    """Lists dynamically generated per-vacancy PDF, DOCX & HTML CVs visible to the current user."""
    files = []
    with Session(engine) as session:
        docs = session.exec(select(CandidateDocument)).all()
        owner_map: Dict[str, set] = {}
        for d in docs:
            owner_map.setdefault(d.filename, set()).add(d.user_id)

    if GENERATED_RESUMES_DIR.exists():
        for f in sorted(GENERATED_RESUMES_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not _is_file_visible_to_user(f.name, current_user, owner_map):
                continue
            html_sibling = f.with_suffix(".html")
            docx_sibling = f.with_suffix(".docx")
            files.append({
                "filename": f.name,
                "url": f"/api/resumes/generated/{f.name}",
                "docx_url": f"/api/resumes/generated/{docx_sibling.name}" if docx_sibling.exists() else None,
                "html_url": f"/api/resumes/generated/{html_sibling.name}" if html_sibling.exists() else None,
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
    return files


@router.get("/resumes/generated/{filename}")
def get_generated_resume_file(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Downloads or previews a generated PDF, Word (.docx), EML, or sandboxed HTML resume after verifying ownership."""
    safe_name = _sanitize_safe_filename(filename)
    _verify_document_ownership(safe_name, current_user)
    file_path = (GENERATED_RESUMES_DIR / safe_name).resolve()
    if not file_path.is_relative_to(GENERATED_RESUMES_DIR.resolve()) or not file_path.exists():
        raise HTTPException(status_code=404, detail="Generated Resume file not found")
    lower = safe_name.lower()
    if lower.endswith(".html"):
        return FileResponse(
            path=file_path,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Security-Policy": _HTML_PREVIEW_CSP,
                "X-Content-Type-Options": "nosniff",
            },
        )
    dl_headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Content-Type-Options": "nosniff",
    }
    if lower.endswith(".docx"):
        return FileResponse(
            path=file_path,
            filename=safe_name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=dl_headers,
        )
    if lower.endswith(".eml"):
        return FileResponse(
            path=file_path,
            filename=safe_name,
            media_type="message/rfc822",
            headers=dl_headers,
        )
    return FileResponse(
        path=file_path,
        filename=safe_name,
        media_type="application/pdf",
        headers=dl_headers,
    )


@router.get("/resumes/{filename}")
def get_resume_pdf(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Downloads or previews a base or generated PDF/DOCX/HTML resume after verifying ownership."""
    safe_name = _sanitize_safe_filename(filename)
    _verify_document_ownership(safe_name, current_user)
    file_path = (RESUMES_DIR / safe_name).resolve()
    if not file_path.is_relative_to(RESUMES_DIR.resolve()) or not file_path.exists():
        file_path = (GENERATED_RESUMES_DIR / safe_name).resolve()
        if not file_path.is_relative_to(GENERATED_RESUMES_DIR.resolve()) or not file_path.exists():
            raise HTTPException(status_code=404, detail="Resume file not found")
    lower = safe_name.lower()
    if lower.endswith(".html"):
        return FileResponse(
            path=file_path,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Security-Policy": _HTML_PREVIEW_CSP,
                "X-Content-Type-Options": "nosniff",
            },
        )
    dl_headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Content-Type-Options": "nosniff",
    }
    if lower.endswith(".docx"):
        return FileResponse(
            path=file_path,
            filename=safe_name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=dl_headers,
        )
    return FileResponse(
        path=file_path,
        filename=safe_name,
        media_type="application/pdf",
        headers=dl_headers,
    )
