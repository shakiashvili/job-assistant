import logging
from fastapi import APIRouter, HTTPException, Depends
from ..db.models import StageApplicationRequest, StageApplicationResponse, User
from ..services.auth_service import get_current_user
from ..services.playwright_service import playwright_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Stage Application"])


@router.post("/stage-application", response_model=StageApplicationResponse)
async def stage_application_endpoint(
    request: StageApplicationRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Playwright automation runner that validates company reviews,
    generates & attaches the per-vacancy Human-Tone PDF CV, fills all inputs
    from the signed-in user's Candidate Profile, pauses on CAPTCHA checkpoints,
    and stages the application cleanly.
    """
    if not request.job_url:
        raise HTTPException(status_code=400, detail="'job_url' is required.")

    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    uid = current_user.id if owner else None

    try:
        response = await playwright_service.stage_application(
            job_url=request.job_url,
            variant=request.variant or "",
            custom_pdf_filename=request.custom_pdf_filename,
            custom_answers=request.custom_answers,
            applicant_summary=request.applicant_summary,
            motivation_letter=request.motivation_letter,
            expected_salary=request.expected_salary,
            start_date=request.start_date,
            bypass_company_gate=bool(request.bypass_company_gate),
            auto_submit=bool(request.auto_submit),
            headless=request.headless if request.headless is not None else False,
            timeout_seconds=request.timeout_seconds or 15,
            owner_email=owner,
            user_id=uid,
        )
        return response
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Playwright staging failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Application staging failed due to an internal error.")
