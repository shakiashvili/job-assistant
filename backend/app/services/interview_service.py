import logging
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select

from ..db.models import ApplicationTracker, InterviewRound
from ..services.gemini_service import gemini_service
from ..db.profile_repository import ground_truth_store

logger = logging.getLogger(__name__)


class InterviewService:
    """
    AI-powered Interview Copilot generating company intelligence summaries,
    10 round-tailored interview questions, grounded STAR answer frameworks,
    technical glossary, and strategic candidate follow-up questions.
    """

    def _get_candidate_context(
        self,
        application: ApplicationTracker,
        user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        owner_email = getattr(user, "email", None) if user else None
        user_id = getattr(user, "id", None) if user else application.user_id
        data = ground_truth_store.get_data(owner_email=owner_email, user_id=user_id)
        cand = data.get("candidate") or {}
        skills = (data.get("skills") or {}).get("core") or []
        work_history = data.get("work_history") or []
        taxonomy = data.get("parsed_skills_taxonomy") or {}
        return {
            "full_name": cand.get("full_name") or "Candidate",
            "headline": cand.get("headline") or taxonomy.get("primary_role") or application.job_title or "Specialist",
            "skills": [str(s) for s in skills[:20]],
            "work_history": work_history[:5],
            "achievements": taxonomy.get("achievements") or [],
            "experience_years": taxonomy.get("years_of_experience", 1.5),
        }

    def prepare_interview(
        self,
        application: ApplicationTracker,
        round_type: str = "HR_SCREEN",
        session: Optional[Session] = None,
        user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Analyzes the company, role, and candidate profile to produce company intelligence,
        round-specific predicted questions, grounded STAR frameworks, technical glossary,
        and strategic follow-up questions to ask the interviewer.
        """
        company = application.company_name or "Hiring Company"
        role = application.job_title or "Specialist"
        cand_ctx = self._get_candidate_context(application, user=user)

        if session and application.id:
            existing_round = session.exec(
                select(InterviewRound).where(
                    InterviewRound.application_id == application.id,
                    InterviewRound.round_type == round_type,
                )
            ).first()
            if existing_round and existing_round.predicted_questions:
                heuristic_extra = self._build_glossary_and_followups(company, role, round_type, cand_ctx)
                return {
                    "round_id": existing_round.id,
                    "application_id": application.id,
                    "company_name": company,
                    "job_title": role,
                    "round_type": existing_round.round_type,
                    "status": existing_round.status,
                    "company_intel": existing_round.company_intel_summary,
                    "predicted_questions": existing_round.predicted_questions,
                    "technical_glossary": heuristic_extra["technical_glossary"],
                    "follow_up_questions": heuristic_extra["follow_up_questions"],
                    "candidate_notes": existing_round.candidate_notes or "",
                }

        if gemini_service.is_available:
            try:
                intel_data = self._generate_with_gemini(company, role, round_type, cand_ctx)
            except Exception as e:
                logger.warning(f"Gemini interview prep generation failed, using profile-grounded framework: {e}")
                intel_data = self._generate_heuristic(company, role, round_type, cand_ctx)
        else:
            intel_data = self._generate_heuristic(company, role, round_type, cand_ctx)

        extra = self._build_glossary_and_followups(company, role, round_type, cand_ctx)
        technical_glossary = intel_data.get("technical_glossary") or extra["technical_glossary"]
        follow_up_questions = intel_data.get("follow_up_questions") or extra["follow_up_questions"]

        round_rec = None
        if session and application.id:
            round_rec = InterviewRound(
                application_id=application.id,
                round_type=round_type,
                company_intel_summary=intel_data["company_intel"],
                predicted_questions=intel_data["predicted_questions"],
                status="SCHEDULED",
            )
            session.add(round_rec)
            session.commit()
            session.refresh(round_rec)

        return {
            "round_id": round_rec.id if round_rec else 1,
            "application_id": application.id,
            "company_name": company,
            "job_title": role,
            "round_type": round_type,
            "status": "SCHEDULED",
            "company_intel": intel_data["company_intel"],
            "predicted_questions": intel_data["predicted_questions"],
            "technical_glossary": technical_glossary,
            "follow_up_questions": follow_up_questions,
            "candidate_notes": "",
        }

    def _build_glossary_and_followups(
        self,
        company: str,
        role: str,
        round_type: str,
        cand_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        skills = cand_ctx.get("skills") or []
        top_skills = skills[:5] if skills else ["Core Domain Methodology", "Quality Standards", "Process Improvement"]
        glossary = [
            {
                "term": sk,
                "definition": f"Practical application of {sk} in {role} workflows, focusing on reliability, maintainability, and measurable team outcomes.",
            }
            for sk in top_skills
        ]
        follow_ups = [
            f"What does success look like in the first 90 days for the {role} role at {company}?",
            f"How does the {company} team currently balance delivery velocity with quality and operational stability?",
            f"What are the biggest technical or workflow challenges the team is prioritizing this quarter?",
            "How do cross-functional teams collaborate during release cycles and incident retrospectives?",
        ]
        return {
            "technical_glossary": glossary,
            "follow_up_questions": follow_ups,
        }

    def _generate_with_gemini(
        self,
        company: str,
        role: str,
        round_type: str,
        cand_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        skills_str = ", ".join(cand_ctx.get("skills") or []) or "general professional skills"
        wh_summary = "; ".join(
            f"{w.get('role', 'Role')} at {w.get('company', 'Company')}"
            for w in (cand_ctx.get("work_history") or [])
            if isinstance(w, dict)
        ) or "Verified experience in candidate profile"

        prompt = f"""
You are an Executive Recruiter and Hiring Manager preparing a candidate for an interview.
Company: {company}
Role: {role}
Round Type: {round_type}
Candidate Verified Skills: {skills_str}
Candidate Verified Experience: {wh_summary}

STRICT GROUNDING RULE:
- Ground all STAR strategies ONLY in the candidate's verified skills and experience listed above.
- NEVER invent fake metrics, percentages, or unverified employers. Instead, frame the "result" around clear qualitative impact or instruct the candidate which real metric from their work to cite.

Provide:
1. "company_intel": A 3-sentence overview of the role expectations at {company}, key operational priorities, and collaboration culture.
2. "predicted_questions": 10 questions tailored to this round (4 Technical, 3 Behavioral, 3 Scenario).
   For each question include "id" (1..10), "category" ("Technical" | "Behavioral" | "Scenario"), "question", and "star_strategy" ("situation", "task", "action", "result").
3. "technical_glossary": 4-5 key concepts with "term" and "definition".
4. "follow_up_questions": 4 thoughtful questions the candidate should ask the interviewer.

Return ONLY valid JSON.
"""
        response_text = gemini_service._call_gemini_with_retry(prompt)
        parsed = gemini_service.safe_parse_json(response_text)
        if isinstance(parsed, dict) and "predicted_questions" in parsed and len(parsed["predicted_questions"]) >= 5:
            return parsed
        raise ValueError("Invalid Gemini interview prep shape")

    def _generate_heuristic(
        self,
        company: str,
        role: str,
        round_type: str,
        cand_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Profile-grounded interview intelligence without fabricated metrics."""
        skills = cand_ctx.get("skills") or []
        wh = cand_ctx.get("work_history") or []
        primary_skill = skills[0] if len(skills) > 0 else "core domain tools"
        secondary_skill = skills[1] if len(skills) > 1 else "structured verification"
        third_skill = skills[2] if len(skills) > 2 else "collaborative workflows"
        recent_company = (
            wh[0].get("company")
            if wh and isinstance(wh[0], dict) and wh[0].get("company")
            else "your recent role"
        )
        recent_highlight = (
            (wh[0].get("highlights") or [None])[0]
            if wh and isinstance(wh[0], dict) and wh[0].get("highlights")
            else f"applying {primary_skill} and {secondary_skill} in production workflows"
        )

        intel_summary = (
            f"For the {role} position at {company}, interviewers focus on practical mastery of {primary_skill}, "
            f"{secondary_skill}, and structured problem-solving. Expect evaluation of your hands-on background "
            f"at {recent_company} and how you communicate trade-offs across cross-functional teams."
        )

        questions = [
            {
                "id": 1,
                "category": "Technical",
                "question": f"How have you applied {primary_skill} and {secondary_skill} in your day-to-day workflows?",
                "star_strategy": {
                    "situation": f"Reference your work at {recent_company} where {primary_skill} was part of the delivery workflow.",
                    "task": f"Explain the quality or operational goal you were responsible for supporting with {primary_skill}.",
                    "action": f"Walk through your concrete workflow ({recent_highlight}) and how you combined {primary_skill} with {secondary_skill}.",
                    "result": "Share the verified outcome from your project without exaggerating metrics, emphasizing reliability and maintainability.",
                },
            },
            {
                "id": 2,
                "category": "Technical",
                "question": f"How do you validate complex workflows and edge cases using {secondary_skill} and {third_skill}?",
                "star_strategy": {
                    "situation": f"Describe a feature or service release at {recent_company} with multiple integration points.",
                    "task": "Ensure both positive paths and edge/error states were thoroughly verified before release.",
                    "action": f"Detail how you structured checks using {secondary_skill} and documented findings with {third_skill}.",
                    "result": "Highlight how early defect detection prevented regressions before production handoff.",
                },
            },
            {
                "id": 3,
                "category": "Technical",
                "question": f"When working on {role} responsibilities, how do you prioritize tasks when timelines are tight?",
                "star_strategy": {
                    "situation": f"Frame a busy release cycle from your experience at {recent_company}.",
                    "task": "Prioritize highest-risk paths first while keeping stakeholders informed of coverage.",
                    "action": f"Explain your risk-based prioritization criteria and how you leveraged {primary_skill} for high-impact checks.",
                    "result": "Demonstrate predictable delivery and transparent risk communication with the team.",
                },
            },
            {
                "id": 4,
                "category": "Technical",
                "question": f"How do you diagnose and document an intermittent or hard-to-reproduce issue in a live environment?",
                "star_strategy": {
                    "situation": "Describe an issue where initial reproduction steps were unclear.",
                    "task": "Isolate the root trigger and provide actionable evidence for resolution.",
                    "action": f"Explain how you inspected logs, environment state, and inputs using {secondary_skill} and {third_skill}.",
                    "result": "Resulted in a deterministic reproduction path and a permanent regression check.",
                },
            },
            {
                "id": 5,
                "category": "Behavioral",
                "question": "Tell me about a time you identified a process gap and proposed a practical improvement.",
                "star_strategy": {
                    "situation": f"Draw from your tenure at {recent_company} when a recurring workflow bottleneck slowed the team.",
                    "task": "Introduce a repeatable improvement that reduced manual overhead.",
                    "action": f"Describe how you standardized the workflow using {primary_skill} and shared documentation with peers.",
                    "result": "Improved consistency across the team and made onboarding smoother.",
                },
            },
            {
                "id": 6,
                "category": "Behavioral",
                "question": "Describe a situation where you had to align with a teammate or stakeholder on a technical or priority disagreement.",
                "star_strategy": {
                    "situation": "A release or task priority discussion where perspectives differed on urgency.",
                    "task": "Reach an objective, evidence-based consensus without slowing team momentum.",
                    "action": "Presented clear reproduction evidence, user impact assessment, and practical mitigation options.",
                    "result": "Aligned the team on an agreed remediation plan while maintaining constructive collaboration.",
                },
            },
            {
                "id": 7,
                "category": "Behavioral",
                "question": f"Why are you interested in joining {company} as a {role} at this stage of your career?",
                "star_strategy": {
                    "situation": f"Summarize your {cand_ctx.get('experience_years', 1.5)} years of hands-on experience in {cand_ctx.get('headline')}.",
                    "task": f"Connect your verified strengths in {primary_skill} and {secondary_skill} to {company}'s mission.",
                    "action": f"Highlight specific aspects of {company}'s product and engineering standards where you can contribute immediately.",
                    "result": "Convey genuine motivation, realistic expectations, and readiness to grow with the team.",
                },
            },
            {
                "id": 8,
                "category": "Scenario",
                "question": "A critical issue is reported right before a scheduled release. Walk through your immediate response.",
                "star_strategy": {
                    "situation": "High-urgency pre-release scenario requiring calm triage.",
                    "task": "Assess blast radius, reproduce deterministically, and communicate release readiness status.",
                    "action": "Verify scope across affected workflows, coordinate with engineering/product owners, and verify the hotfix.",
                    "result": "Clear go/no-go decision backed by objective verification.",
                },
            },
            {
                "id": 9,
                "category": "Scenario",
                "question": "How do you handle a task or feature where written requirements are incomplete or evolving?",
                "star_strategy": {
                    "situation": "Fast-moving project with partial specifications.",
                    "task": "Clarify expected behavior and edge cases early before implementation drifts.",
                    "action": "Formulate concrete boundary questions, review workflows with stakeholders, and document agreed acceptance criteria.",
                    "result": "Prevented rework and established clear shared expectations.",
                },
            },
            {
                "id": 10,
                "category": "Scenario",
                "question": f"What would your first 30-60-90 days look like in the {role} role at {company}?",
                "star_strategy": {
                    "situation": f"Joining {company} and ramping up on existing domain workflows and architecture.",
                    "task": "Deliver early value while learning internal systems and team conventions.",
                    "action": f"Days 1-30: master domain context and existing {primary_skill} setup; Days 31-60: own core workflows independently; Days 61-90: drive reliability improvements.",
                    "result": "Smooth integration into the team with measurable, dependable contributions.",
                },
            },
        ]

        extra = self._build_glossary_and_followups(company, role, round_type, cand_ctx)
        return {
            "company_intel": intel_summary,
            "predicted_questions": questions,
            "technical_glossary": extra["technical_glossary"],
            "follow_up_questions": extra["follow_up_questions"],
        }


interview_service = InterviewService()
