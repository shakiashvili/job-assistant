import logging
from fastapi import APIRouter, HTTPException
from ..models.schemas import GenerateAnswersRequest, GenerateAnswersResponse
from ..services.answer_service import answer_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Screening Answers"])


@router.post("/generate-answers", response_model=GenerateAnswersResponse)
async def generate_answers_endpoint(request: GenerateAnswersRequest):
    """
    Takes portal screening questions + candidate ground_truth.json
    and returns grounded, professional answers customized for the role.
    """
    if not request.questions:
        raise HTTPException(status_code=400, detail="At least one screening question must be provided.")

    try:
        response = answer_service.generate_answers(request)
        return response
    except Exception as e:
        logger.error(f"Failed to generate answers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Answer generation failed: {str(e)}")
