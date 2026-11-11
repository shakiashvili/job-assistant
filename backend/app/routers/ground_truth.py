import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from ..storage.ground_truth_store import ground_truth_store, PROFESSION_MD_PRESETS
from ..config import RESUMES_DIR, GENERATED_RESUMES_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Ground Truth, Skills.md & Resumes"])


class SkillsMdPayload(BaseModel):
    content: str


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
    """Loads a multi-industry .md preset into candidate_skills.md and syncs ground_truth.json."""
    try:
        md_content = ground_truth_store.get_preset_md(preset_id)
        updated_gt = ground_truth_store.save_skills_md(md_content)
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
    """Updates candidate_skills.md from raw markdown text and synchronizes ground_truth.json."""
    try:
        updated_gt = ground_truth_store.save_skills_md(payload.content)
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
    """Accepts an uploaded .md skills file, saves it, and syncs skills into ground_truth.json."""
    try:
        raw_bytes = await file.read()
        md_text = raw_bytes.decode("utf-8", errors="replace")
        updated_gt = ground_truth_store.save_skills_md(md_text)
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


@router.get("/resumes/generated")
def list_generated_resumes():
    """Lists all dynamically generated per-vacancy PDF & HTML CVs."""
    files = []
    if GENERATED_RESUMES_DIR.exists():
        for f in sorted(GENERATED_RESUMES_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
            html_sibling = f.with_suffix(".html")
            files.append({
                "filename": f.name,
                "url": f"/api/resumes/generated/{f.name}",
                "html_url": f"/api/resumes/generated/{html_sibling.name}" if html_sibling.exists() else None,
                "size_kb": round(f.stat().st_size / 1024, 1)
            })
    return files


@router.get("/resumes/generated/{filename}")
def get_generated_resume_file(filename: str):
    """Downloads or previews a dynamically generated per-vacancy PDF or HTML resume."""
    file_path = GENERATED_RESUMES_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Generated Resume file not found")
    if filename.lower().endswith(".html"):
        return FileResponse(path=file_path, media_type="text/html; charset=utf-8")
    return FileResponse(path=file_path, filename=filename, media_type="application/pdf")


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
