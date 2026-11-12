import logging
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from ..storage.ground_truth_store import ground_truth_store, PROFESSION_MD_PRESETS
from ..config import RESUMES_DIR, GENERATED_RESUMES_DIR
from ..database import engine, delete_job_posting_cascade
from ..models.db_models import JobPosting
from sqlmodel import Session, select

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Ground Truth, Skills.md & Resumes"])


def _purge_stale_unapplied_jobs() -> None:
    """Clears unapplied vacancies whenever the user switches profession preset or uploads new skills.md."""
    try:
        with Session(engine) as session:
            for job in session.exec(select(JobPosting)).all():
                if job.status != "APPLIED":
                    delete_job_posting_cascade(session, job)
            session.commit()
    except Exception as e:
        logger.debug(f"Purge unapplied jobs skipped: {e}")
USER_CV_DIR = RESUMES_DIR / "user_uploads"
USER_CV_DIR.mkdir(parents=True, exist_ok=True)


class SkillsMdPayload(BaseModel):
    content: str


class GenerateEditionRequest(BaseModel):
    edition: str = "ats"  # "ats", "recruiter", or "tailored"
    target_role: Optional[str] = None
    target_company: Optional[str] = None
    job_description: Optional[str] = ""
    cv_language: str = "en"


@router.get("/ground-truth")
def get_ground_truth():
    """Returns candidate profile, skills, work history, FAQ bank, and skills_md_raw."""
    return ground_truth_store.get_data()


@router.put("/ground-truth")
def update_ground_truth(payload: Dict[str, Any]):
    """Updates and persists ground_truth.json."""
    try:
        updated = ground_truth_store.update_data(payload)
        return {"status": "success", "message": "Ground truth updated successfully", "data": updated}
    except Exception as e:
        logger.error(f"Error updating ground truth: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills-md")
def get_skills_md():
    """Returns the attached candidate_skills.md content and extracted skills."""
    content = ground_truth_store.get_skills_md()
    extracted = ground_truth_store.extract_skills_from_md(content)
    return {
        "filename": "candidate_skills.md",
        "content": content,
        "extracted_skills": extracted,
    }


@router.get("/skills-md/presets")
def get_skills_md_presets():
    """Returns built-in multi-industry .md skills templates (QA, Receptionist/Hospitality, Customer Service, Healthcare/Hospital)."""
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
def apply_skills_md_preset(preset_id: str):
    """Loads a multi-industry .md preset while preserving non-example candidate identity and purging stale jobs."""
    try:
        prev_gt = ground_truth_store.get_data()
        prev_cand = dict(prev_gt.get("candidate") or {})
        has_real_identity = (
            prev_cand.get("email")
            and not str(prev_cand.get("email")).endswith("@example.com")
            and "candidate" not in str(prev_cand.get("email")).lower()
        )

        md_content = ground_truth_store.get_preset_md(preset_id)
        updated_gt = ground_truth_store.save_skills_md(md_content)
        if has_real_identity:
            cand = dict(updated_gt.get("candidate") or {})
            for key in ("full_name", "first_name", "last_name", "email", "phone", "links"):
                if prev_cand.get(key):
                    cand[key] = prev_cand[key]
            updated_gt["candidate"] = cand
            updated_gt = ground_truth_store.update_data(updated_gt)

        _purge_stale_unapplied_jobs()
        extracted = ground_truth_store.extract_skills_from_md(md_content)
        return {
            "status": "success",
            "preset_id": preset_id,
            "content": md_content,
            "extracted_skills": extracted,
            "ground_truth": updated_gt,
            "message": f"Loaded '{preset_id}' profile template ({len(extracted)} skills synced)."
        }
    except Exception as e:
        logger.error(f"Error applying preset {preset_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skills-md")
def save_skills_md_text(payload: SkillsMdPayload):
    """Updates candidate_skills.md from raw markdown text, synchronizes ground_truth, and purges stale jobs."""
    try:
        updated_gt = ground_truth_store.save_skills_md(payload.content)
        _purge_stale_unapplied_jobs()
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
async def upload_skills_md_file(file: UploadFile = File(...)):
    """Accepts an uploaded .md skills file, saves it, syncs skills, and purges stale jobs."""
    try:
        raw_bytes = await file.read()
        md_text = raw_bytes.decode("utf-8", errors="replace")
        updated_gt = ground_truth_store.save_skills_md(md_text)
        _purge_stale_unapplied_jobs()
        extracted = ground_truth_store.extract_skills_from_md(md_text)
        return {
            "status": "success",
            "filename": file.filename or "candidate_skills.md",
            "content": md_text,
            "extracted_skills": extracted,
            "ground_truth": updated_gt,
            "message": f"Uploaded {file.filename} and synced {len(extracted)} skills!"
        }
    except Exception as e:
        logger.error(f"Error uploading skills.md file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cv-variants")
def get_cv_variants():
    """Lists CV variants across industries."""
    return ground_truth_store.get_cv_variants()


@router.get("/resumes/my-cvs")
def list_my_uploaded_cvs():
    """Lists user-uploaded personal CV files (.pdf, .docx, .md) cleanly."""
    files = []
    USER_CV_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(USER_CV_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".doc", ".md", ".txt"):
            files.append({
                "filename": f.name,
                "url": f"/api/resumes/user/{f.name}",
                "ext": f.suffix.lower().lstrip("."),
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
    return files


@router.post("/resumes/my-cvs/upload")
async def upload_personal_cv(file: UploadFile = File(...)):
    """Uploads a personal resume (.pdf, .docx, .md, .txt) into local gitignored storage."""
    safe_name = Path(file.filename or "resume.pdf").name
    ext = Path(safe_name).suffix.lower()
    if ext not in (".pdf", ".docx", ".doc", ".md", ".txt"):
        raise HTTPException(status_code=400, detail="Unsupported format. Upload .pdf, .docx, .md, or .txt.")
    USER_CV_DIR.mkdir(parents=True, exist_ok=True)
    dest = USER_CV_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {
        "status": "ok",
        "filename": safe_name,
        "url": f"/api/resumes/user/{safe_name}",
        "ext": ext.lstrip("."),
        "size_kb": round(len(content) / 1024, 1),
    }


@router.delete("/resumes/my-cvs/{filename}")
def delete_personal_cv(filename: str):
    """Deletes an uploaded personal resume."""
    safe_name = Path(filename).name
    target = USER_CV_DIR / safe_name
    if target.exists() and target.is_file():
        target.unlink()
        return {"status": "deleted", "filename": safe_name}
    raise HTTPException(status_code=404, detail="File not found")


@router.get("/resumes/user/{filename}")
def get_user_cv_file(filename: str):
    """Downloads or previews a user-uploaded personal CV."""
    safe_name = Path(filename).name
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
def generate_cv_edition(req: GenerateEditionRequest):
    """Generates an ATS-Optimized, Recruiter-Ready, or Job-Tailored CV (Word .docx + PDF) + Cover Letter."""
    from ..services.cv_generator_service import cv_generator_service

    gt = ground_truth_store.get_data()
    cand = gt.get("candidate", {})
    default_role = cand.get("headline") or "QA Automation & Manual QA Engineer"
    role = (req.target_role or "").strip() or default_role
    company = (req.target_company or "").strip() or ("ATS Edition" if req.edition == "ats" else "Recruiter Edition" if req.edition == "recruiter" else "Target Company")

    pkg = cv_generator_service.prepare_email_application_package(
        job_title=role,
        company=company,
        description=req.job_description or "",
        cv_language=req.cv_language or "en",
        cv_style=req.edition or "ats",
    )
    return {"status": "ok", "edition": req.edition, **pkg}


@router.get("/resumes/generated")
def list_generated_resumes():
    """Lists all dynamically generated per-vacancy PDF, DOCX & HTML CVs."""
    files = []
    if GENERATED_RESUMES_DIR.exists():
        for f in sorted(GENERATED_RESUMES_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
            html_sibling = f.with_suffix(".html")
            docx_sibling = f.with_suffix(".docx")
            files.append({
                "filename": f.name,
                "url": f"/api/resumes/generated/{f.name}",
                "docx_url": f"/api/resumes/generated/{docx_sibling.name}" if docx_sibling.exists() else None,
                "html_url": f"/api/resumes/generated/{html_sibling.name}" if html_sibling.exists() else None,
                "size_kb": round(f.stat().st_size / 1024, 1)
            })
    return files


@router.get("/resumes/generated/{filename}")
def get_generated_resume_file(filename: str):
    """Downloads or previews a generated PDF, Word (.docx), or HTML resume."""
    safe_name = Path(filename).name
    file_path = GENERATED_RESUMES_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Generated Resume file not found")
    lower = safe_name.lower()
    if lower.endswith(".html"):
        return FileResponse(path=file_path, media_type="text/html; charset=utf-8")
    if lower.endswith(".docx"):
        return FileResponse(
            path=file_path,
            filename=safe_name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    return FileResponse(path=file_path, filename=safe_name, media_type="application/pdf")


@router.get("/resumes/{filename}")
def get_resume_pdf(filename: str):
    """Downloads or previews a base variant PDF resume."""
    file_path = RESUMES_DIR / filename
    if not file_path.exists():
        gen_path = GENERATED_RESUMES_DIR / filename
        if gen_path.exists():
            if filename.lower().endswith(".html"):
                return FileResponse(path=gen_path, media_type="text/html; charset=utf-8")
            return FileResponse(path=gen_path, filename=filename, media_type="application/pdf")
        raise HTTPException(status_code=404, detail="Resume PDF not found")
    return FileResponse(path=file_path, filename=filename, media_type="application/pdf")
