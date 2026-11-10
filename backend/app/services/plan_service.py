import json
import logging
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select

from ..config import GEMINI_MODEL
from ..db.models import User, SkillActionPlan, CandidateProfile, JobPosting
from ..services.gemini_service import gemini_service
from ..storage.ground_truth_store import ground_truth_store

logger = logging.getLogger(__name__)

# Curated fallback action plans if Gemini API is unavailable or rate-limited
CURATED_SKILL_ROADMAPS = [
    {
        "skill_name": "Docker & Containerized Test Runners",
        "category": "DEVOPS",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "Understand Docker architecture, images vs containers, and write basic Dockerfile", "completed": False, "resource_url": "https://docs.docker.com/get-started/"},
            {"day": 2, "task": "Containerize a Playwright/Pytest automated test runner with multi-stage builds", "completed": False, "resource_url": "https://playwright.dev/python/docs/docker"},
            {"day": 3, "task": "Configure Docker Compose for testing with dependent databases and mock APIs", "completed": False, "resource_url": "https://docs.docker.com/compose/"},
            {"day": 4, "task": "Run headless browser tests in isolated containers with mounted volume reports", "completed": False, "resource_url": "https://pytest-with-eric.com/pytest-advanced/pytest-docker/"},
            {"day": 5, "task": "Integrate containerized test suite into GitHub Actions workflow", "completed": False, "resource_url": "https://docs.github.com/en/actions"},
            {"day": 6, "task": "Debug test failures using container logs and interactive exec sessions", "completed": False, "resource_url": "https://docs.docker.com/engine/reference/commandline/exec/"},
            {"day": 7, "task": "Document setup in README and publish container image to GHCR registry", "completed": False, "resource_url": "https://docs.github.com/en/packages/working-with-a-github-packages-registry"},
        ]
    },
    {
        "skill_name": "k6 Performance & Load Testing",
        "category": "AUTOMATION",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "Install Grafana k6 and understand Virtual Users (VUs) and iterations", "completed": False, "resource_url": "https://k6.io/docs/get-started/running-k6/"},
            {"day": 2, "task": "Script HTTP GET/POST scenarios with custom headers and JSON payloads", "completed": False, "resource_url": "https://k6.io/docs/using-k6/http-requests/"},
            {"day": 3, "task": "Set performance thresholds (p95 < 200ms, error rate < 1%)", "completed": False, "resource_url": "https://k6.io/docs/using-k6/thresholds/"},
            {"day": 4, "task": "Model realistic traffic ramp-up, steady load, and ramp-down stages", "completed": False, "resource_url": "https://k6.io/docs/using-k6/scenarios/"},
            {"day": 5, "task": "Parameterize test data with external JSON and CSV datasets", "completed": False, "resource_url": "https://k6.io/docs/examples/data-parameterization/"},
            {"day": 6, "task": "Export load testing metrics to HTML dashboards and Prometheus/Grafana", "completed": False, "resource_url": "https://k6.io/docs/results-output/"},
            {"day": 7, "task": "Execute stress and spike tests against candidate API endpoints", "completed": False, "resource_url": "https://k6.io/docs/testing-guides/stress-testing/"},
        ]
    },
    {
        "skill_name": "TypeScript & Playwright SDET Specialization",
        "category": "CODING",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "TypeScript fundamentals: types, interfaces, generics, and async/await", "completed": False, "resource_url": "https://www.typescriptlang.org/docs/handbook/intro.html"},
            {"day": 2, "task": "Initialize Playwright TypeScript project with eslint and prettier configs", "completed": False, "resource_url": "https://playwright.dev/docs/intro"},
            {"day": 3, "task": "Build Page Object Model (POM) with strict typing for locators and components", "completed": False, "resource_url": "https://playwright.dev/docs/pom"},
            {"day": 4, "task": "Implement API request mocking and intercepting network payloads", "completed": False, "resource_url": "https://playwright.dev/docs/network"},
            {"day": 5, "task": "Set up cross-browser parallel execution with Playwright Sharding", "completed": False, "resource_url": "https://playwright.dev/docs/test-sharding"},
            {"day": 6, "task": "Implement custom fixtures and authentication state persistence", "completed": False, "resource_url": "https://playwright.dev/docs/test-fixtures"},
            {"day": 7, "task": "Configure HTML report publishing and artifact retention on CI", "completed": False, "resource_url": "https://playwright.dev/docs/test-reporters"},
        ]
    }
]


class PlanService:
    """
    AI-driven skill gap analyzer and interactive action plan generator.
    """

    def generate_plans_for_user(self, user: User, session: Session) -> List[SkillActionPlan]:
        """
        Analyzes the candidate's existing profile against scanned vacancies,
        identifies top missing trainable skills, and persists 7-day action plans.
        """
        # 1. Fetch Candidate Skills
        gt = ground_truth_store.get_data()
        existing_skills = set(gt.get("skills", {}).get("core", []))
        candidate_prof = session.exec(select(CandidateProfile)).first()
        if candidate_prof and candidate_prof.parsed_skills:
            for s in candidate_prof.parsed_skills.get("core_skills", []):
                existing_skills.add(s)

        # 2. Check if user already has active plans
        existing_plans = session.exec(
            select(SkillActionPlan).where(SkillActionPlan.user_id == user.id)
        ).all()
        if existing_plans:
            return existing_plans

        # 3. Attempt Gemini-driven plan generation if available
        created_plans = []
        if gemini_service.is_available:
            try:
                plans_data = self._generate_with_gemini(list(existing_skills))
                for pd in plans_data:
                    plan = SkillActionPlan(
                        user_id=user.id,
                        skill_name=pd["skill_name"],
                        category=pd.get("category", "AUTOMATION"),
                        days_to_learn=pd.get("days_to_learn", 7),
                        milestones=pd.get("milestones", []),
                        is_completed=False,
                    )
                    session.add(plan)
                    created_plans.append(plan)
                session.commit()
                for p in created_plans:
                    session.refresh(p)
                return created_plans
            except Exception as e:
                logger.warning(f"Gemini skill plan generation failed, falling back to curated taxonomy: {e}")

        # 4. Fallback to Curated High-Impact QA / SDET Roadmaps
        for item in CURATED_SKILL_ROADMAPS:
            plan = SkillActionPlan(
                user_id=user.id,
                skill_name=item["skill_name"],
                category=item["category"],
                days_to_learn=item["days_to_learn"],
                milestones=item["milestones"],
                is_completed=False,
            )
            session.add(plan)
            created_plans.append(plan)

        session.commit()
        for p in created_plans:
            session.refresh(p)
        return created_plans

    def _generate_with_gemini(self, existing_skills: List[str]) -> List[Dict[str, Any]]:
        prompt = f"""
You are a Staff QA Architect and Engineering Career Coach.
Analyze the candidate's existing skills: {json.dumps(existing_skills)}.
Identify the top 3 high-impact trainable skills they lack to land Senior QA Automation & SDET positions in international markets (e.g. Docker, k6, TypeScript, AWS for QA, Kubernetes).

Return ONLY valid JSON matching this exact structure:
[
  {{
    "skill_name": "Docker for Test Automation",
    "category": "DEVOPS",
    "days_to_learn": 7,
    "milestones": [
      {{"day": 1, "task": "Learn basic commands and containers", "completed": false, "resource_url": "https://docs.docker.com"}},
      {{"day": 2, "task": "Containerize a test suite", "completed": false, "resource_url": "https://playwright.dev/docs/docker"}},
      {{"day": 3, "task": "Configure Docker Compose for testing", "completed": false, "resource_url": "https://docs.docker.com/compose"}},
      {{"day": 4, "task": "Run headless browser tests in container", "completed": false, "resource_url": "https://pytest-with-eric.com"}},
      {{"day": 5, "task": "Connect container to CI runner", "completed": false, "resource_url": "https://docs.github.com"}},
      {{"day": 6, "task": "Debug containerized test logs", "completed": false, "resource_url": "https://docs.docker.com"}},
      {{"day": 7, "task": "Publish reusable test image", "completed": false, "resource_url": "https://github.com"}}
    ]
  }}
]
"""
        response_text = gemini_service._call_gemini_with_retry(prompt)
        parsed = gemini_service.safe_parse_json(response_text)
        if isinstance(parsed, list) and len(parsed) >= 1:
            return parsed
        raise ValueError("Invalid Gemini action plan JSON shape")

    def toggle_milestone(self, plan: SkillActionPlan, milestone_index: int, session: Session) -> SkillActionPlan:
        """
        Toggles milestone status. When 100% of milestones are checked off,
        automatically adds this skill to the candidate's active skills database!
        """
        import copy
        from sqlalchemy.orm.attributes import flag_modified

        milestones = copy.deepcopy(list(plan.milestones))
        if 0 <= milestone_index < len(milestones):
            current_status = milestones[milestone_index].get("completed", False)
            milestones[milestone_index]["completed"] = not current_status

        plan.milestones = milestones
        all_done = all(m.get("completed", False) for m in milestones)
        plan.is_completed = all_done
        flag_modified(plan, "milestones")
        session.add(plan)

        # If completed, ingest skill into CandidateProfile
        if all_done:
            self._ingest_mastered_skill(plan.skill_name, session)

        session.commit()
        session.refresh(plan)
        return plan

    def _ingest_mastered_skill(self, skill_name: str, session: Session) -> None:
        """Dynamically ingests newly learned skill into candidate profile & ground truth."""
        try:
            candidate_prof = session.exec(select(CandidateProfile)).first()
            if candidate_prof:
                parsed = dict(candidate_prof.parsed_skills or {})
                core = list(parsed.get("core_skills", []))
                if skill_name not in core:
                    core.append(skill_name)
                    parsed["core_skills"] = core
                    candidate_prof.parsed_skills = parsed
                    session.add(candidate_prof)
                    logger.info(f"Ingested completed skill '{skill_name}' into CandidateProfile database!")

            # Also update ground_truth.json
            gt = ground_truth_store.get_data()
            gt_core = gt.setdefault("skills", {}).setdefault("core", [])
            if skill_name not in gt_core:
                gt_core.append(skill_name)
                ground_truth_store.save_data(gt)
                logger.info(f"Ingested completed skill '{skill_name}' into ground_truth.json!")
        except Exception as e:
            logger.warning(f"Error updating candidate profile with completed skill: {e}")


plan_service = PlanService()
