import json
import logging
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select

from ..db.models import ApplicationTracker, InterviewRound
from ..services.gemini_service import gemini_service
from ..storage.ground_truth_store import ground_truth_store

logger = logging.getLogger(__name__)


class InterviewService:
    """
    AI-powered Interview Copilot generating company intelligence summaries,
    10 round-tailored interview questions, and STAR answer strategies.
    """

    def prepare_interview(
        self,
        application: ApplicationTracker,
        round_type: str = "HR_SCREEN",
        session: Session = None,
    ) -> Dict[str, Any]:
        """
        Analyzes the company, role, and requirements, producing deep company intelligence,
        round-specific predicted questions, and winning STAR frameworks.
        """
        company = application.company_name or "Hiring Company"
        role = application.job_title or "Senior QA Automation Engineer / SDET"

        # Check if an existing interview record for this round already exists
        if session:
            existing_round = session.exec(
                select(InterviewRound).where(
                    InterviewRound.application_id == application.id,
                    InterviewRound.round_type == round_type,
                )
            ).first()
            if existing_round and existing_round.predicted_questions:
                return {
                    "round_id": existing_round.id,
                    "application_id": application.id,
                    "company_name": company,
                    "job_title": role,
                    "round_type": existing_round.round_type,
                    "status": existing_round.status,
                    "company_intel": existing_round.company_intel_summary,
                    "predicted_questions": existing_round.predicted_questions,
                    "candidate_notes": existing_round.candidate_notes or "",
                }

        # Attempt AI generation with Gemini
        if gemini_service.is_available:
            try:
                intel_data = self._generate_with_gemini(company, role, round_type)
            except Exception as e:
                logger.warning(f"Gemini interview prep generation failed, using structured expert framework: {e}")
                intel_data = self._generate_heuristic(company, role, round_type)
        else:
            intel_data = self._generate_heuristic(company, role, round_type)

        # Persist to database
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
            "candidate_notes": "",
        }

    def _generate_with_gemini(self, company: str, role: str, round_type: str) -> Dict[str, Any]:
        prompt = f"""
You are an Executive Tech Recruiter and Principal QA Engineering Hiring Manager.
Prepare a comprehensive Interview Intelligence Brief for:
Company: {company}
Role: {role}
Round Type: {round_type} (Options: HR_SCREEN, TECH_INTERVIEW, FINAL_ROUND)

Provide:
1. "company_intel": A 3-sentence deep intelligence overview (what product they build, monetization/business model, and engineering culture).
2. "predicted_questions": Exactly 10 questions tailored specifically to this round:
   - 4 Technical / Domain questions (testing methodologies, architecture, automation frameworks)
   - 3 Behavioral questions assessing cultural fit and collaboration
   - 3 Scenario / Problem-Solving questions (handling outages, flaky tests, ambiguous requirements)
For EACH of the 10 questions, include:
   - "id": 1 to 10
   - "category": "Technical" | "Behavioral" | "Scenario"
   - "question": The exact question the interviewer will ask
   - "star_strategy":
       - "situation": What context to frame
       - "task": The objective/responsibility to highlight
       - "action": Specific technical decisions, tools used, and communication steps taken
       - "result": Measurable outcome (e.g. 99% pass rate, reduced test run from 4 hours to 18 mins)

Return ONLY valid JSON matching this schema:
{{
  "company_intel": "...",
  "predicted_questions": [
    {{
      "id": 1,
      "category": "Technical",
      "question": "...",
      "star_strategy": {{
        "situation": "...",
        "task": "...",
        "action": "...",
        "result": "..."
      }}
    }}
  ]
}}
"""
        response_text = gemini_service._call_gemini_with_retry(prompt)
        parsed = gemini_service.safe_parse_json(response_text)
        if isinstance(parsed, dict) and "predicted_questions" in parsed and len(parsed["predicted_questions"]) >= 5:
            return parsed
        raise ValueError("Invalid Gemini interview prep shape")

    def _generate_heuristic(self, company: str, role: str, round_type: str) -> Dict[str, Any]:
        """Deterministic, battle-tested interview intelligence for QA & Engineering roles."""
        is_tech = round_type in ["TECH_INTERVIEW", "TECHNICAL_INTERVIEW", "SYSTEM_DESIGN"]
        is_final = round_type in ["FINAL_ROUND", "LEADERSHIP"]

        intel_summary = (
            f"{company} operates a high-availability digital platform requiring robust quality assurance, fast CI/CD delivery, "
            f"and zero-regression deployments. Their engineering culture emphasizes test reliability, clean automation architecture, "
            f"and cross-functional ownership between developers, SDETs, and product managers."
        )

        questions = [
            {
                "id": 1,
                "category": "Technical",
                "question": f"How do you design an end-to-end test framework in Playwright or Cypress to minimize flakiness in CI pipelines?",
                "star_strategy": {
                    "situation": "Our regression test suite had intermittent failures causing blocked CI deployments and developer fatigue.",
                    "task": "Redesign the locator strategy and network wait conditions to achieve 99.5%+ test suite reliability.",
                    "action": "Migrated from arbitrary sleep timers to Playwright auto-waiting assertions, isolated test states with storageState cookies, and mocked volatile 3rd party APIs.",
                    "result": "Reduced false-positive alerts by 85% and cut overall CI pipeline runtime from 45 to 12 minutes."
                }
            },
            {
                "id": 2,
                "category": "Technical",
                "question": "What is your approach to testing asynchronous microservices, REST APIs, and database state validations?",
                "star_strategy": {
                    "situation": "Backend endpoints relied on eventual consistency with Kafka message queues, causing race conditions in validation.",
                    "task": "Build automated API integration tests validating payload schemas and database writes without UI latency.",
                    "action": "Wrote PyTest fixtures with atomic database transactions, polled Kafka consumer offsets with exponential backoff, and validated JSON schemas using Pydantic.",
                    "result": "Discovered 14 data corruption edge cases before production release with sub-second API execution time."
                }
            },
            {
                "id": 3,
                "category": "Technical",
                "question": "How do you integrate automated tests into Docker containers and GitHub Actions / GitLab CI?",
                "star_strategy": {
                    "situation": "Local test passes were failing in the build server due to environment discrepancies and missing headless browser dependencies.",
                    "task": "Standardize test execution across local workstations and cloud CI runners.",
                    "action": "Built lightweight multi-stage Docker images containing pinned Playwright browser binaries, headless flags, and automated artifact uploads on failure.",
                    "result": "Zero 'works on my machine' defects; 100% reproducible execution in Linux CI."
                }
            },
            {
                "id": 4,
                "category": "Technical",
                "question": "How do you decide what percentage of testing should be automated versus exploratory or manual testing?",
                "star_strategy": {
                    "situation": "A team was attempting to automate 100% of ephemeral UI animations, creating brittle tests with high maintenance costs.",
                    "task": "Establish a pragmatic testing pyramid balancing automated smoke/regression with exploratory discovery.",
                    "action": "Audited test ROI: prioritized critical user journeys (signup, checkout, billing) in Playwright and reserved exploratory testing for exploratory edge-case UX flows.",
                    "result": "Maintained high release velocity with zero critical checkout incidents over 12 months."
                }
            },
            {
                "id": 5,
                "category": "Behavioral",
                "question": "Tell me about a time a software developer pushed back against a critical bug you discovered right before release.",
                "star_strategy": {
                    "situation": "A developer argued that a race condition on checkout was an unlikely edge case that shouldn't delay a major sprint release.",
                    "task": "Advocate for user experience and business integrity without creating team friction.",
                    "action": "Recorded a clear Playwright trace and HAR network log reproducing the money-loss bug under high concurrency, then framed the fix collaboratively in the PR.",
                    "result": "Developer acknowledged the issue, implemented the fix within 2 hours, and thanked the QA team for preventing revenue loss."
                }
            },
            {
                "id": 6,
                "category": "Behavioral",
                "question": f"Why do you want to join {company}, and what impact do you expect to make in your first 90 days?",
                "star_strategy": {
                    "situation": f"Researching {company}'s market trajectory and observing their growth in customer-facing digital services.",
                    "task": "Demonstrate proactive ownership and alignment with company goals.",
                    "action": "First 30 days: absorb architecture and CI flows; Day 60: automate key regression gaps; Day 90: establish automated quality gates and mentor colleagues.",
                    "result": "Delivers measurable quality improvements from day one without disrupting active sprint momentum."
                }
            },
            {
                "id": 7,
                "category": "Behavioral",
                "question": "Describe a situation where a production bug slipped through testing. How did you respond and prevent recurrence?",
                "star_strategy": {
                    "situation": "A timezone daylight-savings mismatch slipped into production affecting scheduled notifications for European users.",
                    "task": "Lead a blameless post-mortem and engineer permanent preventive safeguards.",
                    "action": "Identified the test coverage gap, wrote unit and integration tests asserting across UTC and international timezones, and added timezone matrix testing in CI.",
                    "result": "Zero recurring timezone defects; established team-wide standard for temporal data testing."
                }
            },
            {
                "id": 8,
                "category": "Scenario",
                "question": "If you are given 2 days to test a brand new feature with incomplete documentation, what is your plan?",
                "star_strategy": {
                    "situation": "Sprint requirements shifted rapidly and product specs were only partially documented 48 hours prior to launch.",
                    "task": "Ensure zero critical regressions and complete high-risk path validation under severe time constraints.",
                    "action": "Constructed a lightweight mind map of critical paths, conducted a 20-minute alignment sync with the lead developer, and executed risk-based exploratory charter testing.",
                    "result": "Identified 3 blocking validation issues and signed off on a stable, on-time customer release."
                }
            },
            {
                "id": 9,
                "category": "Scenario",
                "question": "How would you handle a situation where test runs in CI are taking over 2 hours and slowing down team PR merges?",
                "star_strategy": {
                    "situation": "A legacy sequential test suite grew to 1,200 tests taking 140 minutes, causing developer PR gridlock.",
                    "task": "Cut CI feedback loops to under 15 minutes without sacrificing test coverage.",
                    "action": "Implemented Playwright test sharding across 4 parallel runners, removed redundant UI tests covered by API tests, and cached browser binaries.",
                    "result": "CI execution dropped from 140 minutes to 11 minutes; developer productivity increased significantly."
                }
            },
            {
                "id": 10,
                "category": "Scenario",
                "question": "How do you track quality metrics (defect escape rate, MTTR, test coverage) to prove QA value to executive leadership?",
                "star_strategy": {
                    "situation": "Leadership questioned the engineering ROI of automated testing versus manual verification.",
                    "task": "Quantify quality data in business terms: release velocity, customer satisfaction, and downtime reduction.",
                    "action": "Created an automated weekly dashboard displaying Defect Escape Rate (< 2%), Test Execution Time, and Regression Cycle Reductions.",
                    "result": "Executive team greenlit dedicated budget for cloud test infrastructure and test runner scaling."
                }
            }
        ]

        return {
            "company_intel": intel_summary,
            "predicted_questions": questions,
        }


interview_service = InterviewService()
