import logging
from typing import List
from ..storage.ground_truth_store import ground_truth_store
from ..services.gemini_service import gemini_service
from ..models.schemas import (
    GenerateAnswersRequest, GenerateAnswersResponse, ScreeningAnswer
)

logger = logging.getLogger(__name__)


class AnswerService:
    def generate_answers(self, request: GenerateAnswersRequest) -> GenerateAnswersResponse:
        data = ground_truth_store.get_data()
        candidate = data.get("candidate", {})
        skills_md = data.get("skills_md_raw") or ground_truth_store.get_skills_md()
        parsed_profile = ground_truth_store.parse_profile_from_md(skills_md)
        lang = (request.cv_language or "en").lower()

        questions_dicts = [q.model_dump() for q in request.questions]
        job_details = {
            "title": request.job_title or parsed_profile.get("headline") or "Specialist",
            "company": request.company or "Hiring Team",
            "summary": request.job_description or ""
        }

        raw_answers = gemini_service.generate_grounded_answers(
            questions=questions_dicts,
            candidate_data=data,
            job_details=job_details,
            variant=request.variant or "qa_automation",
            cv_language=lang,
        )

        narratives = gemini_service.craft_human_tone_narratives(
            job_details=job_details,
            skills_md=skills_md,
            matched_skills=parsed_profile.get("skills", [])[:6] or data.get("skills", {}).get("core", [])[:6],
            missing_skills=[],
            cv_language=lang,
            candidate_name=parsed_profile.get("full_name", candidate.get("full_name", "Candidate")),
        )

        formatted_answers: List[ScreeningAnswer] = []
        for ans in raw_answers:
            if isinstance(ans, dict):
                formatted_answers.append(ScreeningAnswer(
                    question=ans.get("question", ""),
                    field_type=ans.get("field_type", "text"),
                    answer=str(ans.get("answer", "")),
                    confidence=float(ans.get("confidence", 0.92)),
                    source_ground_truth_field=ans.get("source_ground_truth_field", "candidate_skills.md")
                ))

        return GenerateAnswersResponse(
            answers=formatted_answers,
            variant_used=request.variant or "qa_automation",
            candidate_name=parsed_profile.get("full_name", candidate.get("full_name", "Candidate")),
            applicant_summary=narratives["human_tone_summary"],
            motivation_letter=narratives["motivation_statement"],
            dou_motivational_letter=narratives["dou_motivational_letter"],
            default_start_date="1 კვირა შეთავაზებიდან (1 week after offer)" if lang == "ka" else "1 week after offer",
        )


answer_service = AnswerService()
