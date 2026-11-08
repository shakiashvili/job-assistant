import logging
from fastapi import APIRouter, HTTPException
from ..models.schemas import StageApplicationRequest, StageApplicationResponse
from ..services.playwright_service import playwright_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Stage Application"])


@router.post("/stage-application", response_model=StageApplicationResponse)
async def stage_application_endpoint(request: StageApplicationRequest):
    """
    Playwright automation runner that validates company reviews (3+ gate),
    generates & attaches the per-vacancy Human-Tone PDF CV, fills all inputs
    (including DOU.ua motivational letter, applicant summary, salary, and '1 week after offer' start date),
    handles CAPTCHA checkboxes, and stages/submits the application.
    """
    if not request.job_url:
        raise HTTPException(status_code=400, detail="'job_url' is required.")

    try:
        response = await playwright_service.stage_application(
            job_url=request.job_url,
            variant=request.variant or "qa_automation",
            custom_pdf_filename=request.custom_pdf_filename,
            custom_answers=request.custom_answers,
            applicant_summary=request.applicant_summary,
            motivation_letter=request.motivation_letter,
            expected_salary=request.expected_salary,
            start_date=request.start_date or "1 week after offer",
            bypass_company_gate=bool(request.bypass_company_gate),
            auto_submit=bool(request.auto_submit),
            headless=request.headless if request.headless is not None else False,
            timeout_seconds=request.timeout_seconds or 15
        )
        return response
    except Exception as e:
        logger.error(f"Playwright staging failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Playwright staging failed: {str(e)}")
