from collections import Counter
import json
import logging
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select

from ..config import GEMINI_MODEL
from ..db.models import User, SkillActionPlan, CandidateProfile, JobPosting
from ..services.gemini_service import gemini_service
from ..services.matcher_service import matcher_service
from ..storage.ground_truth_store import ground_truth_store

logger = logging.getLogger(__name__)

# Curated rich 7-day action plans keyed by trainable QA/SDET skill
CURATED_SKILL_ROADMAPS: List[Dict[str, Any]] = [
    {
        "match_keys": ["k6", "performance", "load testing"],
        "skill_name": "k6 Performance & Load Testing",
        "category": "AUTOMATION",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "Install Grafana k6 CLI and run a local HTTP smoke script with VUs and duration checks", "completed": False, "resource_url": "https://k6.io/docs/get-started/running-k6/", "tutorial_url": "https://grafana.com/blog/2024/01/30/a-complete-guide-to-load-testing-with-k6/"},
            {"day": 2, "task": "Script authenticated REST GET/POST endpoints with custom headers and JSON assertions", "completed": False, "resource_url": "https://k6.io/docs/using-k6/http-requests/", "tutorial_url": "https://k6.io/docs/examples/"},
            {"day": 3, "task": "Define automated SLO thresholds (p95 latency < 250ms, http_req_failed < 1%)", "completed": False, "resource_url": "https://k6.io/docs/using-k6/thresholds/", "tutorial_url": "https://k6.io/docs/testing-guides/api-load-testing/"},
            {"day": 4, "task": "Configure ramping-vus executors to simulate peak traffic spikes and soak runs", "completed": False, "resource_url": "https://k6.io/docs/using-k6/scenarios/", "tutorial_url": "https://k6.io/docs/testing-guides/stress-testing/"},
            {"day": 5, "task": "Parameterize dynamic test data payloads using SharedArray from JSON/CSV datasets", "completed": False, "resource_url": "https://k6.io/docs/examples/data-parameterization/", "tutorial_url": "https://k6.io/docs/javascript-api/k6-data/sharedarray/"},
            {"day": 6, "task": "Integrate k6 performance threshold gates directly into GitHub Actions CI", "completed": False, "resource_url": "https://k6.io/docs/integrations/", "tutorial_url": "https://grafana.com/docs/k6/latest/using-k6/k6-github-action/"},
            {"day": 7, "task": "Export HTML summary reports and benchmark a real portfolio API service", "completed": False, "resource_url": "https://k6.io/docs/results-output/", "tutorial_url": "https://github.com/benc-uk/k6-reporter"},
        ],
    },
    {
        "match_keys": ["docker", "container"],
        "skill_name": "Docker & Containerized Test Runners",
        "category": "DEVOPS",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "Build a minimal Dockerfile packaging Python/PyTest + Playwright dependencies", "completed": False, "resource_url": "https://docs.docker.com/get-started/", "tutorial_url": "https://playwright.dev/python/docs/docker"},
            {"day": 2, "task": "Use multi-stage Docker builds and layer caching to cut test image build times by 50%", "completed": False, "resource_url": "https://docs.docker.com/build/building/multi-stage/", "tutorial_url": "https://docs.docker.com/build/cache/"},
            {"day": 3, "task": "Orchestrate App + Postgres + QA test runner services with Docker Compose healthchecks", "completed": False, "resource_url": "https://docs.docker.com/compose/", "tutorial_url": "https://pytest-with-eric.com/pytest-advanced/pytest-docker/"},
            {"day": 4, "task": "Mount host artifact volumes to collect Playwright traces, screenshots, and HTML reports", "completed": False, "resource_url": "https://docs.docker.com/storage/volumes/", "tutorial_url": "https://playwright.dev/python/docs/trace-viewer-intro"},
            {"day": 5, "task": "Run parallelized containerized tests inside GitHub Actions with clean exit codes", "completed": False, "resource_url": "https://docs.github.com/en/actions", "tutorial_url": "https://docs.docker.com/build/ci/github-actions/"},
            {"day": 6, "task": "Inspect live container logs and troubleshoot flaky network calls via docker exec", "completed": False, "resource_url": "https://docs.docker.com/reference/cli/docker/container/exec/", "tutorial_url": "https://docs.docker.com/config/containers/logging/"},
            {"day": 7, "task": "Publish your reusable QA runner container image to GitHub Container Registry (GHCR)", "completed": False, "resource_url": "https://docs.github.com/en/packages/working-with-a-github-packages-registry", "tutorial_url": "https://docs.docker.com/get-started/workshop/04_sharing_app/"},
        ],
    },
    {
        "match_keys": ["cypress"],
        "skill_name": "Cypress End-to-End Automation",
        "category": "AUTOMATION",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "Initialize a Cypress project and explore automatic retry-ability and time-travel debugging", "completed": False, "resource_url": "https://docs.cypress.io/guides/getting-started/installing-cypress", "tutorial_url": "https://learn.cypress.io/testing-your-first-application"},
            {"day": 2, "task": "Master cy.intercept() to stub and assert REST network responses deterministically", "completed": False, "resource_url": "https://docs.cypress.io/api/commands/intercept", "tutorial_url": "https://learn.cypress.io/advanced-cypress-concepts/intercepting-network-requests"},
            {"day": 3, "task": "Implement reusable custom commands (Cypress.Commands.add) and session caching", "completed": False, "resource_url": "https://docs.cypress.io/api/cypress-api/custom-commands", "tutorial_url": "https://docs.cypress.io/api/commands/session"},
            {"day": 4, "task": "Build App Actions / Page Object abstractions in TypeScript with clean selectors", "completed": False, "resource_url": "https://docs.cypress.io/guides/tooling/typescript-support", "tutorial_url": "https://www.cypress.io/blog/stop-using-page-objects-and-start-using-app-actions"},
            {"day": 5, "task": "Execute API-only contract assertions using cy.request() alongside UI flows", "completed": False, "resource_url": "https://docs.cypress.io/api/commands/request", "tutorial_url": "https://learn.cypress.io/testing-your-first-application/how-to-test-api-requests"},
            {"day": 6, "task": "Configure Cypress GitHub Action with video/screenshot failure artifact uploads", "completed": False, "resource_url": "https://docs.cypress.io/guides/continuous-integration/github-actions", "tutorial_url": "https://github.com/cypress-io/github-action"},
            {"day": 7, "task": "Run a full regression suite against a staging web app and add CI badge to README", "completed": False, "resource_url": "https://docs.cypress.io/guides/guides/command-line", "tutorial_url": "https://docs.cypress.io/guides/dashboard/introduction"},
        ],
    },
    {
        "match_keys": ["typescript"],
        "skill_name": "TypeScript & Playwright SDET Specialization",
        "category": "CODING",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "Master TypeScript strict types, generics, async/await promises, and utility types", "completed": False, "resource_url": "https://www.typescriptlang.org/docs/handbook/intro.html", "tutorial_url": "https://www.typescriptlang.org/docs/handbook/typescript-from-scratch.html"},
            {"day": 2, "task": "Scaffold a Playwright TypeScript project using role/label accessibility locators", "completed": False, "resource_url": "https://playwright.dev/docs/intro", "tutorial_url": "https://playwright.dev/docs/locators"},
            {"day": 3, "task": "Design strictly typed Page Object Models and reusable authenticated fixtures", "completed": False, "resource_url": "https://playwright.dev/docs/pom", "tutorial_url": "https://playwright.dev/docs/test-fixtures"},
            {"day": 4, "task": "Use Playwright APIRequestContext + UI interception for hybrid API+UI verification", "completed": False, "resource_url": "https://playwright.dev/docs/api-testing", "tutorial_url": "https://playwright.dev/docs/network"},
            {"day": 5, "task": "Enable sharded parallel execution with trace-on-first-retry reporting", "completed": False, "resource_url": "https://playwright.dev/docs/test-sharding", "tutorial_url": "https://playwright.dev/docs/trace-viewer"},
            {"day": 6, "task": "Add ESLint + strict tsconfig rules for zero-warning test maintainability", "completed": False, "resource_url": "https://playwright.dev/docs/test-typescript", "tutorial_url": "https://typescript-eslint.io/getting-started/"},
            {"day": 7, "task": "Deploy Playwright HTML report to GitHub Pages automatically from CI", "completed": False, "resource_url": "https://playwright.dev/docs/test-reporters", "tutorial_url": "https://playwright.dev/docs/ci-intro"},
        ],
    },
    {
        "match_keys": ["appium", "mobile"],
        "skill_name": "Mobile Test Automation (Appium)",
        "category": "AUTOMATION",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "Set up Appium 2 server with UiAutomator2 (Android) and Appium Inspector", "completed": False, "resource_url": "https://appium.io/docs/en/latest/quickstart/", "tutorial_url": "https://appium.io/docs/en/latest/intro/"},
            {"day": 2, "task": "Inspect mobile accessibility IDs and build resilient mobile locators", "completed": False, "resource_url": "https://appium.io/docs/en/latest/guides/migrating-1-to-2/", "tutorial_url": "https://appium.github.io/appium-inspector/"},
            {"day": 3, "task": "Automate login, scroll gestures, and WebView switches in Python or JavaScript", "completed": False, "resource_url": "https://appium.io/docs/en/latest/guides/actions/", "tutorial_url": "https://appium.io/docs/en/latest/ecosystem/clients/"},
            {"day": 4, "task": "Execute cross-device tests using Android Emulator + Playwright/Appium matrix", "completed": False, "resource_url": "https://developer.android.com/studio/run/emulator-commandline", "tutorial_url": "https://appium.io/docs/en/latest/guides/execute-methods/"},
            {"day": 5, "task": "Capture device logs and failure screenshots automatically in PyTest fixtures", "completed": False, "resource_url": "https://docs.pytest.org/en/stable/how-to/fixtures.html", "tutorial_url": "https://appium.io/docs/en/latest/guides/troubleshooting/"},
            {"day": 6, "task": "Handle biometric/OTP permission dialogs via adb / capabilities cleanly", "completed": False, "resource_url": "https://developer.android.com/tools/adb", "tutorial_url": "https://appium.io/docs/en/latest/guides/caps/"},
            {"day": 7, "task": "Publish a sample mobile regression suite runnable on emulator in CI", "completed": False, "resource_url": "https://github.com/reactivecircus/android-emulator-runner", "tutorial_url": "https://appium.io/docs/en/latest/quickstart/test-py/"},
        ],
    },
    {
        "match_keys": ["graphql", "swagger", "openapi"],
        "skill_name": "GraphQL & OpenAPI Contract Testing",
        "category": "API",
        "days_to_learn": 7,
        "milestones": [
            {"day": 1, "task": "Understand GraphQL queries, mutations, introspection schemas, and error arrays", "completed": False, "resource_url": "https://graphql.org/learn/", "tutorial_url": "https://learning.postman.com/docs/sending-requests/graphql/graphql-overview/"},
            {"day": 2, "task": "Automate GraphQL schema & variable validation tests in PyTest or Postman", "completed": False, "resource_url": "https://swagger.io/specification/", "tutorial_url": "https://schemathesis.readthedocs.io/"},
            {"day": 3, "task": "Use Schemathesis / OpenAPI fuzzing to catch 500 errors and edge-case inputs", "completed": False, "resource_url": "https://schemathesis.readthedocs.io/en/stable/", "tutorial_url": "https://docs.pytest.org/en/stable/"},
            {"day": 4, "task": "Validate negative auth paths (expired JWT, RBAC 403, rate limits)", "completed": False, "resource_url": "https://owasp.org/API-Security/", "tutorial_url": "https://owasp.org/www-project-api-security/"},
            {"day": 5, "task": "Test pagination cursors, idempotency keys, and concurrent write safety", "completed": False, "resource_url": "https://graphql.org/learn/pagination/", "tutorial_url": "https://learning.postman.com/docs/tests-and-scripts/write-scripts/test-scripts/"},
            {"day": 6, "task": "Generate Allure API contract test reports inside GitHub Actions", "completed": False, "resource_url": "https://allurereport.org/docs/pytest/", "tutorial_url": "https://docs.github.com/en/actions"},
            {"day": 7, "task": "Add automated contract check before merge on a public REST/GraphQL demo API", "completed": False, "resource_url": "https://swagger.io/tools/swagger-ui/", "tutorial_url": "https://graphql.org/learn/validation/"},
        ],
    },
]


class PlanService:
    """
    AI-driven skill gap analyzer and interactive action plan generator.
    """

    def generate_plans_for_user(
        self,
        user: User,
        session: Session,
        force_refresh: bool = False,
    ) -> List[SkillActionPlan]:
        """
        Analyzes the candidate's existing profile against live matching vacancies in DB,
        identifies top 3 missing trainable skills, and persists 7-day learning roadmaps
        complete with official docs + curated tutorials + hands-on tasks.
        """
        # 1. Fetch Candidate Skills (read all_skills & vault core safely)
        gt = ground_truth_store.get_data()
        existing_skills: set[str] = {str(s) for s in (gt.get("skills", {}).get("core") or [])}
        candidate_prof = session.exec(select(CandidateProfile)).first()
        if candidate_prof and isinstance(candidate_prof.parsed_skills, dict):
            for key in ("all_skills", "qa_automation", "manual_qa", "languages", "api_and_performance", "cicd_and_devops", "core_skills"):
                for s in candidate_prof.parsed_skills.get(key) or []:
                    existing_skills.add(str(s))
        existing_lower = {s.lower() for s in existing_skills}

        # 2. Check active plans (replace unstarted/incomplete plans when user explicitly clicks Generate)
        existing_plans = session.exec(
            select(SkillActionPlan).where(SkillActionPlan.user_id == user.id)
        ).all()
        if existing_plans and not force_refresh:
            return existing_plans
        if force_refresh and existing_plans:
            for ep in existing_plans:
                if not ep.is_completed:
                    session.delete(ep)
            session.commit()

        # 3. Extract real missing skills across matched JobPosting vacancies
        gap_counts: Counter = Counter()
        market_jobs = session.exec(
            select(JobPosting).where(JobPosting.status != "FILTERED_OUT").limit(25)
        ).all()
        for job in market_jobs:
            reqs = matcher_service.extract_job_requirements(job.title, job.description_raw)
            for req in reqs:
                rl = req.lower()
                if not any(rl in ex or ex in rl for ex in existing_lower):
                    gap_counts[req] += 1

        top_gaps = [skill for skill, _ in gap_counts.most_common(6)]

        # 4. Attempt Gemini-driven personalized roadmap generation if API key is configured
        created_plans: List[SkillActionPlan] = []
        if gemini_service.is_available:
            try:
                plans_data = self._generate_with_gemini(list(existing_skills), top_gaps)
                for pd in plans_data[:3]:
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
                logger.warning(f"Gemini skill plan generation fallback: {e}")

        # 5. Match real missing skills against curated rich QA/SDET roadmaps (skipping already-known skills first)
        selected_templates: List[Dict[str, Any]] = []
        used_names: set[str] = set()

        for gap in top_gaps:
            gl = gap.lower()
            for tmpl in CURATED_SKILL_ROADMAPS:
                if tmpl["skill_name"] in used_names:
                    continue
                if any(mk in gl or gl in mk for mk in tmpl["match_keys"]):
                    selected_templates.append(tmpl)
                    used_names.add(tmpl["skill_name"])
                    break
            if len(selected_templates) >= 3:
                break

        # Fill remaining slots with genuinely unpossessed high-impact QA roadmaps
        for tmpl in CURATED_SKILL_ROADMAPS:
            if len(selected_templates) >= 3:
                break
            if tmpl["skill_name"] in used_names:
                continue
            already_has = any(any(mk in ex for ex in existing_lower) for mk in tmpl["match_keys"])
            if not already_has:
                selected_templates.append(tmpl)
                used_names.add(tmpl["skill_name"])

        if not selected_templates:
            selected_templates = CURATED_SKILL_ROADMAPS[:3]

        for item in selected_templates[:3]:
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

    def _generate_with_gemini(self, existing_skills: List[str], top_gaps: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        prompt = f"""
You are a Staff QA Architect and Engineering Career Coach.
Existing skills: {json.dumps(existing_skills[:25])}.
Top missing skills detected from matching vacancies: {json.dumps(top_gaps or [])}.
For the top 3 missing trainable skills, build a focused 7-day learning roadmap where EVERY day has an official documentation URL (`resource_url`), a practical engineering guide/tutorial URL (`tutorial_url`), and a concrete hands-on task.

Return ONLY valid JSON list of 3 objects with keys `skill_name`, `category`, `days_to_learn`, `milestones`.
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
                all_sk = list(parsed.get("all_skills", []))
                if skill_name not in all_sk:
                    all_sk.append(skill_name)
                    parsed["all_skills"] = all_sk
                    candidate_prof.parsed_skills = parsed
                    session.add(candidate_prof)
                    logger.info(f"Ingested completed skill '{skill_name}' into CandidateProfile database!")

            # Also update relational vault
            gt = ground_truth_store.get_data()
            gt_core = gt.setdefault("skills", {}).setdefault("core", [])
            if skill_name not in gt_core:
                gt_core.append(skill_name)
                ground_truth_store.update_data(gt)
                logger.info(f"Ingested completed skill '{skill_name}' into CandidateProfile vault!")
        except Exception as e:
            logger.warning(f"Error updating candidate profile with completed skill: {e}")


plan_service = PlanService()
