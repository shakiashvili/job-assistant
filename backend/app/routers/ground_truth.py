import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
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


def record_candidate_document(
    user_id: Optional[int],
    filename: str,
    file_path: Path,
    doc_type: str = "generated_pdf",
    target_company: str = "",
    target_role: str = "",
) -> Optional[CandidateDocument]:
    if not file_path.exists():
        return None
    try:
        raw_bytes = file_path.read_bytes()
        sha = hashlib.sha256(raw_bytes).hexdigest()
        size_b = len(raw_bytes)
        with Session(engine) as session:
            existing = session.exec(
                select(CandidateDocument).where(CandidateDocument.filename == filename)
            ).first()
            if existing:
                if user_id is not None:
                    existing.user_id = user_id
                existing.storage_path = str(file_path)
                existing.size_bytes = size_b
                existing.sha256_hash = sha
                existing.version_number = (existing.version_number or 1) + 1
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing

            doc = CandidateDocument(
                user_id=user_id,
                doc_type=doc_type,
                filename=filename,
                original_filename=filename,
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


def _verify_document_ownership(filename: str, current_user: User) -> None:
    safe_name = Path(filename).name
    stem = Path(safe_name).stem
    with Session(engine) as session:
        docs = session.exec(
            select(CandidateDocument).where(
                (CandidateDocument.filename == safe_name)
                | (CandidateDocument.filename == f"{stem}.pdf")
                | (CandidateDocument.filename == f"{stem}.docx")
            )
        ).all()
        for doc in docs:
            if doc.user_id is not None and doc.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden: document belongs to another user.",
                )


def _is_file_visible_to_user(filename: str, current_user: User, owner_map: Dict[str, Optional[int]]) -> bool:
    safe_name = Path(filename).name
    stem = Path(safe_name).stem
    doc_uid = owner_map.get(safe_name) or owner_map.get(f"{stem}.pdf")
    if doc_uid is not None:
        return doc_uid == current_user.id
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
    """Updates and persists candidate profile vault for the current user."""
    try:
        updated = ground_truth_store.update_data(
            payload,
            owner_email=current_user.email,
            user_id=current_user.id,
        )
        return {"status": "success", "message": "Ground truth updated successfully", "data": updated}
    except Exception as e:
        logger.error(f"Error updating ground truth: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        extracted = ground_truth_store.extract_skills_from_md(md_content)
        return {
            "status": "success",
            "preset_id": preset_id,
            "content": md_content,
            "extracted_skills": extracted,
            "ground_truth": updated_gt,
            "message": f"Loaded '{preset_id}' profile template ({len(extracted)} skills synced).",
        }
    except Exception as e:
        logger.error(f"Error applying preset {preset_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skills-md")
def save_skills_md_text(
    payload: SkillsMdPayload,
    current_user: User = Depends(get_current_user),
):
    """Updates candidate_skills.md from raw markdown text for the current user."""
    if len(payload.content.encode("utf-8")) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Markdown payload exceeds 10 MB limit.")
    try:
        updated_gt = ground_truth_store.save_skills_md(
            payload.content,
            owner_email=current_user.email,
            user_id=current_user.id,
        )
        _purge_stale_unapplied_jobs(user=current_user)
        extracted = ground_truth_store.extract_skills_from_md(payload.content)
        return {
            "status": "success",
            "message": f"Saved candidate_skills.md ({len(extracted)} skills synced).",
            "extracted_skills": extracted,
            "ground_truth": updated_gt,
        }
    except Exception as e:
        logger.error(f"Error saving skills.md: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skills-md/upload")
async def upload_skills_md_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Accepts an uploaded .md skills file, validates size, saves it for the current user, and syncs skills."""
    raw_bytes = await file.read()
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds 10 MB maximum size limit.")
    try:
        md_text = raw_bytes.decode("utf-8", errors="replace")
        updated_gt = ground_truth_store.save_skills_md(
            md_text,
            owner_email=current_user.email,
            user_id=current_user.id,
        )
        _purge_stale_unapplied_jobs(user=current_user)
        extracted = ground_truth_store.extract_skills_from_md(md_text)
        return {
            "status": "success",
            "filename": file.filename or "candidate_skills.md",
            "content": md_text,
            "extracted_skills": extracted,
            "ground_truth": updated_gt,
            "message": f"Uploaded {file.filename} and synced {len(extracted)} skills!",
        }
    except Exception as e:
        logger.error(f"Error uploading skills.md file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cv-variants")
def get_cv_variants(current_user: User = Depends(get_current_user)):
    """Lists CV variants for the current user."""
    return ground_truth_store.get_data(
        owner_email=current_user.email,
        user_id=current_user.id,
    ).get("cv_variants", {})


@router.get("/resumes/my-cvs")
def list_my_uploaded_cvs(current_user: User = Depends(get_current_user)):
    """Lists user-uploaded personal CV files (.pdf, .docx, .md) scoped to the current user."""
    files = []
    USER_CV_DIR.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        docs = session.exec(select(CandidateDocument)).all()
        owner_map = {d.filename: d.user_id for d in docs}

    for f in sorted(USER_CV_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".doc", ".md", ".txt"):
            if not _is_file_visible_to_user(f.name, current_user, owner_map):
                continue
            files.append({
                "filename": f.name,
                "url": f"/api/resumes/user/{f.name}",
                "ext": f.suffix.lower().lstrip("."),
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
    return files


@router.post("/resumes/my-cvs/upload")
async def upload_personal_cv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Uploads a personal resume (.pdf, .docx, .md, .txt) with size/type validation and ownership tracking."""
    safe_name = Path(file.filename or "resume.pdf").name
    ext = Path(safe_name).suffix.lower()
    if ext not in (".pdf", ".docx", ".doc", ".md", ".txt"):
        raise HTTPException(status_code=400, detail="Unsupported format. Upload .pdf, .docx, .md, or .txt.")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds 10 MB maximum size limit.")
    if ext == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid PDF file header.")
    if ext == ".docx" and not content.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="Invalid DOCX file header.")

    USER_CV_DIR.mkdir(parents=True, exist_ok=True)
    dest = USER_CV_DIR / safe_name
    dest.write_bytes(content)

    record_candidate_document(
        user_id=current_user.id,
        filename=safe_name,
        file_path=dest,
        doc_type="uploaded_cv",
    )

    return {
        "status": "ok",
        "filename": safe_name,
        "url": f"/api/resumes/user/{safe_name}",
        "ext": ext.lstrip("."),
        "size_kb": round(len(content) / 1024, 1),
    }


@router.delete("/resumes/my-cvs/{filename}")
def delete_personal_cv(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Deletes an uploaded personal resume after verifying ownership."""
    safe_name = Path(filename).name
    _verify_document_ownership(safe_name, current_user)
    target = USER_CV_DIR / safe_name
    if target.exists() and target.is_file():
        target.unlink()
        with Session(engine) as session:
            session.exec(
                delete(CandidateDocument).where(CandidateDocument.filename == safe_name)
            )
            session.commit()
        return {"status": "deleted", "filename": safe_name}
    raise HTTPException(status_code=404, detail="File not found")


@router.get("/resumes/user/{filename}")
def get_user_cv_file(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Downloads or previews a user-uploaded personal CV after verifying ownership."""
    safe_name = Path(filename).name
    _verify_document_ownership(safe_name, current_user)
    target = USER_CV_DIR / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Uploaded CV not found")
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
    if pkg.get("cv_filename"):
        pdf_p = GENERATED_RESUMES_DIR / pkg["cv_filename"]
        record_candidate_document(
            user_id=current_user.id,
            filename=pkg["cv_filename"],
            file_path=pdf_p,
            doc_type=f"generated_{req.edition}_cv",
            target_company=company,
            target_role=role,
        )
    return {"status": "ok", "edition": req.edition, **pkg}


@router.get("/resumes/generated")
def list_generated_resumes(current_user: User = Depends(get_current_user)):
    """Lists dynamically generated per-vacancy PDF, DOCX & HTML CVs visible to the current user."""
    files = []
    with Session(engine) as session:
        docs = session.exec(select(CandidateDocument)).all()
        owner_map = {d.filename: d.user_id for d in docs}

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
    """Downloads or previews a generated PDF, Word (.docx), or HTML resume after verifying ownership."""
    safe_name = Path(filename).name
    _verify_document_ownership(safe_name, current_user)
    file_path = GENERATED_RESUMES_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Generated Resume file not found")
    lower = safe_name.lower()
    if lower.endswith(".html"):
        return FileResponse(path=file_path, media_type="text/html; charset=utf-8")
    dl_headers = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
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


@router.get("/resumes/{filename}")
def get_resume_pdf(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Downloads or previews a base or generated PDF/DOCX/HTML resume after verifying ownership."""
    safe_name = Path(filename).name
    _verify_document_ownership(safe_name, current_user)
    file_path = RESUMES_DIR / safe_name
    if not file_path.exists():
        file_path = GENERATED_RESUMES_DIR / safe_name
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Resume file not found")
    lower = safe_name.lower()
    if lower.endswith(".html"):
        return FileResponse(path=file_path, media_type="text/html; charset=utf-8")
    dl_headers = {"Content-Disposition": f'attachment; filename="{safe_name}"'}
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
