import logging
from fastapi import APIRouter, Depends, HTTPException
from ..db.models import User, GenerateAnswersRequest, GenerateAnswersResponse
from ..services.answer_service import answer_service
from ..services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Screening Answers"])


@router.post("/generate-answers", response_model=GenerateAnswersResponse)
@router.post("/answers/solve-screening", response_model=GenerateAnswersResponse)
async def generate_answers_endpoint(
    request: GenerateAnswersRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Takes portal screening questions and returns grounded answers backed by the
    authenticated user's live DB CandidateProfile and ground_truth store.
    """
    if not request.questions:
        raise HTTPException(status_code=400, detail="At least one screening question must be provided.")

    try:
        response = answer_service.generate_answers(request, user=current_user)
        return response
    except Exception as e:
        logger.error(f"Failed to generate answers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Answer generation failed: {str(e)}")
