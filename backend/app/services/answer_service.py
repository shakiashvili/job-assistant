import logging
from typing import Any, Dict, List, Optional
from sqlmodel import Session, select
from ..db.database import engine, init_db
from ..db.models import CandidateProfile
from ..db.profile_repository import ground_truth_store
from ..services.gemini_service import gemini_service
from ..models.schemas import (
    GenerateAnswersRequest, GenerateAnswersResponse, ScreeningAnswer
)

logger = logging.getLogger(__name__)


def load_live_candidate_profile(user_email: Optional[str] = None) -> Dict[str, Any]:
    """Loads the active SQLModel CandidateProfile payload strictly honoring user ownership."""
    try:
        init_db()
        with Session(engine) as session:
            profiles = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).all()
            chosen: Optional[CandidateProfile] = None
            target_low = (user_email or "").strip().lower()
            is_named_user = bool(target_low and target_low != "guest@talentflow.local")
            if is_named_user:
                for p in profiles:
                    ps = p.parsed_skills or {}
                    owner = str(ps.get("owner_email") or "").strip().lower()
                    if owner == target_low:
                        chosen = p
                        break
            elif profiles:
                chosen = profiles[0]
            if chosen:
                ps = dict(chosen.parsed_skills or {})
                ps["experience_years"] = chosen.experience_years
                ps["years_of_experience"] = ps.get("years_of_experience") or chosen.experience_years
                ps["skills_markdown"] = getattr(chosen, "raw_markdown", "") or ""
                ps["headline"] = ps.get("headline") or ps.get("primary_role") or "Specialist"
                ps["full_name"] = chosen.full_name
                ps["email"] = chosen.email
                ps["phone"] = chosen.phone
                ps["location"] = chosen.location
                ps["links"] = {
                    "github": chosen.github_url,
                    "linkedin": chosen.linkedin_url,
                }
                return ps
    except Exception as e:
        logger.debug(f"Live CandidateProfile load fallback: {e}")
    return {}


class AnswerService:
    def generate_answers(
        self,
        request: GenerateAnswersRequest,
        user: Optional[Any] = None,
    ) -> GenerateAnswersResponse:
        data = dict(ground_truth_store.get_data())
        live_profile = load_live_candidate_profile(getattr(user, "email", None))

        candidate = dict(data.get("candidate", {}))
        skills_md = (
            live_profile.get("skills_markdown")
            or data.get("skills_md_raw")
            or ground_truth_store.get_skills_md()
        )
        data["skills_md_raw"] = skills_md

        parsed_profile = ground_truth_store.parse_profile_from_md(skills_md) if skills_md else {}
        if live_profile.get("full_name"):
            candidate["full_name"] = live_profile["full_name"]
        if live_profile.get("headline"):
            candidate["headline"] = live_profile["headline"]
        data["candidate"] = candidate

        verified_skills = (
            live_profile.get("verified_skills")
            or live_profile.get("all_skills")
            or parsed_profile.get("skills", [])
            or data.get("skills", {}).get("core", [])
        )
        lang = (request.cv_language or "en").lower()

        questions_dicts = [q.model_dump() for q in request.questions]
        job_details = {
            "title": request.job_title or live_profile.get("primary_role") or parsed_profile.get("headline") or "Specialist",
            "company": request.company or "Hiring Team",
            "industry": live_profile.get("target_industry") or "qa_tech",
            "summary": request.job_description or "",
        }

        raw_answers = gemini_service.generate_grounded_answers(
            questions=questions_dicts,
            candidate_data=data,
            job_details=job_details,
            variant=request.variant or str(live_profile.get("target_industry") or "qa_automation"),
            cv_language=lang,
            candidate_profile=live_profile,
        )

        cand_name = (
            parsed_profile.get("full_name")
            or live_profile.get("full_name")
            or candidate.get("full_name")
            or "Candidate"
        )
        narratives = gemini_service.craft_human_tone_narratives(
            job_details=job_details,
            skills_md=skills_md,
            matched_skills=[str(s) for s in verified_skills[:6]],
            missing_skills=[],
            cv_language=lang,
            candidate_name=cand_name,
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
            variant_used=request.variant or str(live_profile.get("target_industry") or "qa_automation"),
            candidate_name=cand_name,
            applicant_summary=narratives["human_tone_summary"],
            motivation_letter=narratives["motivation_statement"],
            dou_motivational_letter=narratives["dou_motivational_letter"],
            default_start_date="1 კვირა შეთავაზებიდან (1 week after offer)" if lang == "ka" else "1 week after offer",
        )


answer_service = AnswerService()
