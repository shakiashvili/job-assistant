import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import defer
from sqlmodel import Session, select, delete

from ..db.document_repository import (  # noqa: F401 - re-exported for backward compatibility
    record_candidate_document,
    resolve_owned_generated_document,
    user_generated_resumes_dir,
)
from ..db.profile_repository import ground_truth_store, PROFESSION_MD_PRESETS
from ..db.models import (
    User,
    JobPosting,
    UserJobMatch,
    SavedJob,
    CandidateDocument,
    CVVersion,
    utc_now,
)
from ..services.auth_service import get_current_user
from ..services.answer_service import load_live_candidate_profile
from ..services.storage_service import storage_service
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


def _resolve_generated_resume_for_user(filename: str, current_user: User) -> Path:
    """Resolves a generated CV file strictly after fail-closed ownership verification for current_user."""
    safe_name = _sanitize_safe_filename(filename)
    path, err = resolve_owned_generated_document(
        safe_name,
        user_id=current_user.id,
        is_guest=_is_guest(current_user),
    )
    if err == "invalid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported or unsafe document filename.")
    if err == "forbidden":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: document belongs to another user.")
    if err or path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated Resume file not found")
    return path


class SkillsMdPayload(BaseModel):
    content: str


class ProfileImportApplyRequest(BaseModel):
    filename: str = "imported_cv"
    extracted: Dict[str, Any]
    section_modes: Dict[str, str] = Field(default_factory=dict)


class GenerateEditionRequest(BaseModel):
    edition: str = "ats"  # "ats", "recruiter", or "tailored"
    target_role: Optional[str] = None
    target_company: Optional[str] = None
    job_description: Optional[str] = ""
    job_url: Optional[str] = None
    cv_language: str = "en"


@router.get("/profile/intelligence")
def get_profile_intelligence(current_user: User = Depends(get_current_user)):
    """Returns profile completeness, duplicate skill detection, timeline validation warnings, recommendations, and provenance."""
    from ..services.profile_intelligence_service import compute_profile_intelligence

    owner = current_user.email if not _is_guest(current_user) else None
    uid = current_user.id if not _is_guest(current_user) else None
    gt = ground_truth_store.get_data(owner_email=owner, user_id=uid)
    prof = ground_truth_store.get_profile_record(owner_email=owner, user_id=uid)
    return compute_profile_intelligence(gt, parsed_skills=prof.parsed_skills if prof else {})


@router.post("/profile/import-preview")
async def preview_profile_import(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Extracts structured fields from PDF/DOCX/MD/TXT for candidate review without overwriting saved profile data."""
    from ..services.profile_intelligence_service import build_import_preview
    from ..services.upload_utils import read_upload_bounded

    raw_bytes = await read_upload_bounded(file, MAX_UPLOAD_SIZE_BYTES)
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    filename = file.filename or "resume.pdf"
    owner = current_user.email if not _is_guest(current_user) else None
    uid = current_user.id if not _is_guest(current_user) else None
    existing_gt = ground_truth_store.get_data(owner_email=owner, user_id=uid)
    try:
        return build_import_preview(raw_bytes, filename=filename, existing_gt=existing_gt)
    except ValueError as parse_err:
        raise HTTPException(status_code=400, detail=str(parse_err))


@router.post("/profile/import-apply")
def apply_profile_import(
    payload: ProfileImportApplyRequest,
    current_user: User = Depends(get_current_user),
):
    """Applies candidate-reviewed extracted fields using per-section merge/replace/skip modes (never silently overwriting)."""
    from ..services.profile_intelligence_service import apply_import_merge, compute_profile_intelligence
    from ..services.scrapers.scraper_orchestrator import scraper_orchestrator
    from ..services.cv_generator_service import cv_generator_service

    owner = current_user.email if not _is_guest(current_user) else None
    uid = current_user.id if not _is_guest(current_user) else None
    existing_gt = ground_truth_store.get_data(owner_email=owner, user_id=uid)
    merged_gt = apply_import_merge(
        existing_gt=existing_gt,
        extracted=payload.extracted,
        section_modes=payload.section_modes,
        source_filename=payload.filename,
    )
    updated_gt = ground_truth_store.update_data(merged_gt, owner_email=owner, user_id=uid)
    scraper_orchestrator.rescore_existing_jobs(owner_email=owner, user_id=uid)
    synced_cv_versions = cv_generator_service.sync_user_cv_versions(
        user_id=current_user.id,
        owner_email=current_user.email,
    )
    prof = ground_truth_store.get_profile_record(owner_email=owner, user_id=uid)
    return {
        "status": "success",
        "synced_cv_versions": synced_cv_versions,
        "data": updated_gt,
        "intelligence": compute_profile_intelligence(updated_gt, parsed_skills=prof.parsed_skills if prof else {}),
    }


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
    from ..services.upload_utils import read_upload_bounded

    raw_bytes = await read_upload_bounded(file, MAX_UPLOAD_SIZE_BYTES)
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
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
            .options(defer(CandidateDocument.encrypted_content))
            .where(
                CandidateDocument.user_id == current_user.id,
                CandidateDocument.doc_type == "uploaded_cv",
            )
            .order_by(CandidateDocument.created_at.desc())
        ).all()

    for doc in user_docs:
        p = Path(doc.storage_path).resolve() if doc.storage_path else (user_dir / doc.filename).resolve()
        ext = Path(doc.filename).suffix.lower()
        if ext not in (".pdf", ".docx", ".md", ".txt"):
            continue
        is_local = p.is_relative_to(base_resolved) and p.is_file()
        is_durable_remote = bool(doc.storage_backend == "db_blob" or (doc.storage_backend == "s3" and doc.object_key))
        if not is_local and not is_durable_remote:
            continue
        if doc.filename in seen_names:
            continue
        seen_names.add(doc.filename)
        size_b = p.stat().st_size if is_local else int(doc.size_bytes or 0)
        files.append({
            "filename": doc.filename,
            "original_filename": doc.original_filename or doc.filename,
            "url": f"/api/resumes/user/{doc.filename}",
            "ext": ext.lstrip("."),
            "size_kb": round(size_b / 1024, 1),
            "storage_backend": doc.storage_backend or "local",
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
    from ..services.upload_utils import read_upload_bounded

    safe_name = _sanitize_uploaded_cv_name(file.filename)
    ext = Path(safe_name).suffix.lower()

    content = await read_upload_bounded(file, MAX_UPLOAD_SIZE_BYTES)
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
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
            hydrate_target = (user_dir / safe_name).resolve()
            if hydrate_target.is_relative_to(user_dir.resolve()):
                hydrated = storage_service.hydrate_local_file(
                    hydrate_target,
                    storage_backend=user_doc.storage_backend,
                    object_key=user_doc.object_key,
                    encrypted_content=user_doc.encrypted_content,
                    expected_sha256=user_doc.sha256_hash,
                )
                if hydrated is not None and hydrated.is_file():
                    return hydrated, user_doc.id

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
    """Deletes an uploaded personal resume strictly scoped to current_user (local cache, remote S3 object, and DB row)."""
    target, doc_id = _resolve_user_uploaded_cv(filename, current_user)
    safe_name = _sanitize_safe_filename(filename)
    if target.exists():
        target.unlink()
    with Session(engine) as session:
        if doc_id is not None:
            docs_to_remove = session.exec(
                select(CandidateDocument).where(
                    CandidateDocument.id == doc_id,
                    CandidateDocument.user_id == current_user.id,
                )
            ).all()
        else:
            docs_to_remove = session.exec(
                select(CandidateDocument).where(
                    CandidateDocument.user_id == current_user.id,
                    CandidateDocument.doc_type == "uploaded_cv",
                    CandidateDocument.filename == safe_name,
                )
            ).all()
        for doc in docs_to_remove:
            storage_service.delete_remote_document(doc.storage_backend, doc.object_key)
            session.delete(doc)
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


def _record_generated_cv_files(
    user_id: int,
    filenames: List[Optional[str]],
    *,
    doc_type: str,
    target_company: str,
    target_role: str,
) -> None:
    user_gen_dir = user_generated_resumes_dir(user_id)
    for fname in dict.fromkeys(f for f in filenames if f):
        record_candidate_document(
            user_id=user_id,
            filename=fname,
            file_path=user_gen_dir / fname,
            doc_type=doc_type,
            target_company=target_company,
            target_role=target_role,
        )


def _serve_resume_file(file_path: Path, safe_name: str) -> FileResponse:
    lower = safe_name.lower()
    if lower.endswith(".html"):
        return FileResponse(
            path=file_path,
            media_type="text/html; charset=utf-8",
            headers={"Content-Security-Policy": _HTML_PREVIEW_CSP, "X-Content-Type-Options": "nosniff"},
        )
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if lower.endswith(".docx")
        else "message/rfc822"
        if lower.endswith(".eml")
        else "application/pdf"
    )
    return FileResponse(
        path=file_path,
        filename=safe_name,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/resumes/generate-edition")
async def generate_cv_edition(
    req: GenerateEditionRequest,
    current_user: User = Depends(get_current_user),
):
    """Generates an ATS-Optimized, Recruiter-Ready, or Job-Tailored CV (Word .docx + PDF) + Cover & Motivational Letters."""
    from ..services.cv_generator_service import cv_generator_service
    from ..services.audit_service import audit_service, validate_safe_external_url
    from ..services.portal_detector import detect_portal_from_html

    live = load_live_candidate_profile(current_user.email, user_id=current_user.id)
    gt = ground_truth_store.get_data(owner_email=current_user.email, user_id=current_user.id)
    cand = gt.get("candidate", {})
    default_role = live.get("primary_role") or live.get("headline") or cand.get("headline") or "Specialist"
    role = (req.target_role or "").strip() or default_role
    company = (
        (req.target_company or "").strip()
        or ("ATS Edition" if req.edition == "ats" else "Recruiter Edition" if req.edition == "recruiter" else "Target Company")
    )
    desc = (req.job_description or "").strip()
    url_fetched = False
    url_fetch_warning: Optional[str] = None
    if req.job_url and req.job_url.strip():
        clean_url = req.job_url.strip()
        try:
            validate_safe_external_url(clean_url, require_dns=False)
            if len(desc) < 120:
                html_raw = await audit_service.fetch_url_content(clean_url)
                if html_raw:
                    _, meta = detect_portal_from_html(html_raw, clean_url)
                    fetched_desc = str(meta.get("description_text") or "").strip()
                    if len(fetched_desc) >= 80:
                        desc = f"{desc}\n\n{fetched_desc}".strip() if desc else fetched_desc
                        url_fetched = True
                    else:
                        url_fetch_warning = "Could not extract full vacancy text from URL; paste the job description for deeper tailoring."
                else:
                    url_fetch_warning = "Target job URL returned no readable text; paste the job description for deeper tailoring."
        except ValueError as ssrf_err:
            raise HTTPException(status_code=400, detail=str(ssrf_err))
        except Exception as fetch_err:
            logger.debug("Optional URL description fetch skipped for %s: %s", clean_url, fetch_err)
            url_fetch_warning = "Could not fetch job URL automatically; paste the job description for full tailoring."

    pkg = cv_generator_service.prepare_email_application_package(
        job_title=role,
        company=company,
        description=desc,
        skills_md_override=live.get("skills_markdown") or None,
        owner_email=current_user.email,
        user_id=current_user.id,
        cv_language=req.cv_language or "en",
        cv_style=req.edition or "ats",
    )
    _record_generated_cv_files(
        current_user.id,
        [pkg.get("pdf_filename"), pkg.get("docx_filename"), pkg.get("cv_filename")],
        doc_type=f"generated_{req.edition}_cv",
        target_company=company,
        target_role=role,
    )

    cv_version_id: Optional[int] = None
    persistence_status = "saved"
    persistence_error: Optional[str] = None
    try:
        with Session(engine) as session:
            cv_sections = dict(pkg.get("cv_sections") or {})
            cv_sections["template_name"] = req.edition or "ats"
            if desc:
                cv_sections["job_description_snapshot"] = desc[:6000]
            if req.job_url:
                cv_sections["job_url"] = req.job_url.strip()
            cv_ver = CVVersion(
                user_id=current_user.id,
                title=f"{role} — {company} ({req.edition.upper()})",
                target_company=company,
                target_role=role,
                edition=req.edition or "ats",
                cv_language=pkg.get("cv_language") or req.cv_language or "en",
                structured_content=cv_sections,
                rendered_html=pkg.get("rendered_html") or "",
                cover_letter=str(pkg.get("cover_letter") or ""),
                motivational_letter=str(pkg.get("motivational_letter") or ""),
                pdf_filename=pkg.get("pdf_filename"),
                docx_filename=pkg.get("docx_filename"),
                version_number=1,
            )
            session.add(cv_ver)
            session.commit()
            session.refresh(cv_ver)
            cv_version_id = cv_ver.id
    except Exception as ver_err:
        persistence_status = "partial_failure"
        persistence_error = str(ver_err)[:200]
        logger.error("Failed to persist CVVersion snapshot for user=%s: %s", current_user.id, ver_err, exc_info=True)

    return {
        "status": "ok" if persistence_status == "saved" else "partial_success",
        "persistence_status": persistence_status,
        "persistence_error": persistence_error,
        "url_fetched": url_fetched,
        "url_fetch_warning": url_fetch_warning,
        "extracted_description_preview": desc[:500] if url_fetched else None,
        "edition": req.edition,
        "cv_version_id": cv_version_id,
        **pkg,
    }


class CVVersionCreateRequest(BaseModel):
    title: str
    target_company: str = ""
    target_role: str = ""
    edition: str = "tailored"
    language: str = "en"
    blank: bool = False
    job_posting_id: Optional[int] = None
    structured_json: Dict[str, Any] = Field(default_factory=dict)
    cover_letter: Optional[str] = None
    motivational_letter: Optional[str] = None


class CVVersionPatchRequest(BaseModel):
    title: Optional[str] = None
    target_company: Optional[str] = None
    target_role: Optional[str] = None
    structured_json: Optional[Dict[str, Any]] = None
    cover_letter: Optional[str] = None
    motivational_letter: Optional[str] = None
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
        "cover_letter": v.cover_letter or "",
        "motivational_letter": v.motivational_letter or "",
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


@router.get("/cv-versions/{version_id}/ats-check")
def check_cv_version_ats_parseability(
    version_id: int,
    current_user: User = Depends(get_current_user),
):
    """Runs deterministic pypdf ATS parseability checks on a user-owned CV version PDF."""
    from ..services.ats_checker import check_pdf_ats_parseability

    with Session(engine) as session:
        ver = session.get(CVVersion, version_id)
        if not ver or ver.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="CV version not found.")
        if not ver.pdf_filename:
            raise HTTPException(status_code=400, detail="No generated PDF exists for this CV version yet.")
        safe_pdf = _sanitize_safe_filename(ver.pdf_filename)
        pdf_path, _err = resolve_owned_generated_document(
            safe_pdf,
            user_id=current_user.id,
            is_guest=_is_guest(current_user),
        )
        if pdf_path is None or not pdf_path.is_file():
            raise HTTPException(status_code=404, detail="Generated PDF file not found on disk.")
        sec = ver.structured_content or {}
        cand = sec.get("candidate") or {}
        report = check_pdf_ats_parseability(
            pdf_path,
            candidate_name=str(cand.get("full_name") or current_user.full_name or ""),
            expected_email=str(cand.get("email") or current_user.email or ""),
            expected_phone=str(cand.get("phone") or ""),
            expected_keywords=[str(s) for s in (sec.get("skills") or [])[:12]],
        )
        return {"version_id": ver.id, "pdf_filename": safe_pdf, **report}


@router.post("/cv-versions")
def create_cv_version(
    req: CVVersionCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Creates a new editable CV Studio version and renders its HTML, PDF, and DOCX files."""
    from ..services.cv_generator_service import cv_generator_service

    sections = dict(req.structured_json or {})
    if not sections:
        if req.blank:
            sections = {
                "candidate": {
                    "full_name": current_user.full_name or "",
                    "email": current_user.email or "",
                    "phone": "",
                    "location": {"city": "", "country": ""},
                },
                "headline": req.target_role or "",
                "summary": "",
                "skills": [],
                "work_history": [],
                "education": [],
                "target_role": req.target_role or "Untitled Role",
                "target_company": req.target_company or "",
                "cv_language": req.language,
                "cv_style": req.edition,
                "template_name": req.edition,
                "created_from_blank": True,
            }
        else:
            gt = ground_truth_store.get_data(owner_email=current_user.email, user_id=current_user.id)
            cand = gt.get("candidate") or {}
            sections = {
                "candidate": cand,
                "headline": req.target_role or cand.get("headline") or "",
                "summary": cand.get("summary") or cand.get("headline") or "",
                "skills": (gt.get("skills") or {}).get("core") or [],
                "work_history": gt.get("work_history") or [],
                "education": gt.get("education") or [],
                "target_role": req.target_role or cand.get("headline") or "Specialist",
                "target_company": req.target_company or "Tailored",
                "cv_language": req.language,
                "cv_style": req.edition,
                "template_name": req.edition,
            }

    rendered = cv_generator_service.render_cv_from_sections(sections, user_id=current_user.id)
    if rendered.get("ats_parse_report"):
        sections["ats_parse_report"] = rendered["ats_parse_report"]
    _record_generated_cv_files(
        current_user.id,
        [rendered.get("pdf_filename"), rendered.get("docx_filename")],
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
            cover_letter=str(req.cover_letter or ""),
            motivational_letter=str(req.motivational_letter or ""),
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
        if req.cover_letter is not None:
            ver.cover_letter = req.cover_letter
        if req.motivational_letter is not None:
            ver.motivational_letter = req.motivational_letter

        rendered = cv_generator_service.render_cv_from_sections(
            sections,
            base_name_override=ver.pdf_filename,
            user_id=current_user.id,
        )
        if rendered.get("ats_parse_report"):
            sections["ats_parse_report"] = rendered["ats_parse_report"]
        _record_generated_cv_files(
            current_user.id,
            [rendered.get("pdf_filename"), rendered.get("docx_filename")],
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


@router.post("/cv-versions/{version_id}/duplicate")
def duplicate_cv_version(
    version_id: int,
    current_user: User = Depends(get_current_user),
):
    """Duplicates an existing CV Studio version (preserving letters & structured content) for safe branching."""
    from ..services.cv_generator_service import cv_generator_service

    with Session(engine) as session:
        src = session.get(CVVersion, version_id)
        if not src or src.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="CV version not found.")

        sections = dict(src.structured_content or {})
        sections["duplicated_from_version_id"] = src.id
        rendered = cv_generator_service.render_cv_from_sections(sections, user_id=current_user.id)
        if rendered.get("ats_parse_report"):
            sections["ats_parse_report"] = rendered["ats_parse_report"]
        _record_generated_cv_files(
            current_user.id,
            [rendered.get("pdf_filename"), rendered.get("docx_filename")],
            doc_type=f"cv_studio_{src.edition}",
            target_company=src.target_company,
            target_role=src.target_role,
        )

        clone = CVVersion(
            user_id=current_user.id,
            job_posting_id=src.job_posting_id,
            title=f"{src.title} (Copy)",
            target_company=src.target_company,
            target_role=src.target_role,
            edition=src.edition,
            cv_language=src.cv_language,
            structured_content=sections,
            rendered_html=rendered.get("rendered_html") or src.rendered_html or "",
            cover_letter=src.cover_letter or "",
            motivational_letter=src.motivational_letter or "",
            pdf_filename=rendered.get("pdf_filename"),
            docx_filename=rendered.get("docx_filename"),
            version_number=(src.version_number or 1) + 1,
        )
        session.add(clone)
        session.commit()
        session.refresh(clone)
        return _serialize_cv_version(clone)


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
    """Lists dynamically generated per-vacancy PDF, DOCX & HTML CVs strictly owned by the current user."""
    files = []
    seen_names: set[str] = set()
    is_guest = _is_guest(current_user)
    user_dir = user_generated_resumes_dir(current_user.id)

    with Session(engine) as session:
        user_docs = session.exec(
            select(CandidateDocument)
            .options(defer(CandidateDocument.encrypted_content))
            .where(CandidateDocument.user_id == current_user.id)
        ).all()
        user_vers = session.exec(
            select(CVVersion)
            .options(defer(CVVersion.rendered_html), defer(CVVersion.structured_content))
            .where(CVVersion.user_id == current_user.id)
        ).all()

    owned_pdf_names: set[str] = set()
    for d in user_docs:
        if d.filename.lower().endswith(".pdf"):
            owned_pdf_names.add(d.filename)
        elif d.filename.lower().endswith(".docx"):
            owned_pdf_names.add(f"{Path(d.filename).stem}.pdf")
    for v in user_vers:
        if v.pdf_filename:
            owned_pdf_names.add(v.pdf_filename)

    if user_dir.exists():
        for f in sorted(user_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not is_guest and f.name not in owned_pdf_names:
                continue
            if f.name in seen_names:
                continue
            seen_names.add(f.name)
            html_sibling = f.with_suffix(".html")
            docx_sibling = f.with_suffix(".docx")
            files.append({
                "filename": f.name,
                "url": f"/api/resumes/generated/{f.name}",
                "docx_url": f"/api/resumes/generated/{docx_sibling.name}" if docx_sibling.exists() else None,
                "html_url": f"/api/resumes/generated/{html_sibling.name}" if html_sibling.exists() else None,
                "size_kb": round(f.stat().st_size / 1024, 1),
            })

    # Include durable DB/S3-backed generated PDFs even if ephemeral local disk cache was cleared
    durable_doc_names = {
        d.filename
        for d in user_docs
        if d.storage_backend == "db_blob" or (d.storage_backend == "s3" and d.object_key)
    }
    for d in user_docs:
        if d.doc_type == "uploaded_cv" or not d.filename.lower().endswith(".pdf"):
            continue
        if d.filename in seen_names or d.filename not in durable_doc_names:
            continue
        seen_names.add(d.filename)
        stem = Path(d.filename).stem
        docx_name = f"{stem}.docx"
        html_name = f"{stem}.html"
        files.append({
            "filename": d.filename,
            "url": f"/api/resumes/generated/{d.filename}",
            "docx_url": f"/api/resumes/generated/{docx_name}" if docx_name in durable_doc_names else None,
            "html_url": f"/api/resumes/generated/{html_name}" if html_name in durable_doc_names else None,
            "size_kb": round(int(d.size_bytes or 0) / 1024, 1),
            "storage_backend": d.storage_backend or "db_blob",
        })

    if is_guest and GENERATED_RESUMES_DIR.exists():
        with Session(engine) as session:
            non_guest_files = {
                d.filename for d in session.exec(select(CandidateDocument)).all()
                if d.user_id is not None and d.user_id != current_user.id
            }
        for f in sorted(GENERATED_RESUMES_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.name in seen_names or f.name in non_guest_files:
                continue
            seen_names.add(f.name)
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
    """Downloads or previews a generated PDF, Word (.docx), EML, or sandboxed HTML resume after fail-closed ownership verification."""
    safe_name = _sanitize_safe_filename(filename)
    return _serve_resume_file(_resolve_generated_resume_for_user(safe_name, current_user), safe_name)


@router.get("/resumes/{filename}")
def get_resume_pdf(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Downloads or previews a user-owned uploaded or generated PDF/DOCX/HTML resume after fail-closed ownership check."""
    safe_name = _sanitize_safe_filename(filename)
    file_path: Optional[Path] = None
    try:
        file_path, _ = _resolve_user_uploaded_cv(safe_name, current_user)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
    if file_path is None:
        file_path = _resolve_generated_resume_for_user(safe_name, current_user)
    return _serve_resume_file(file_path, safe_name)
