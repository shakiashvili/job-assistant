from collections import Counter
import copy
import json
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus
from sqlmodel import Session, select
from sqlalchemy.orm.attributes import flag_modified

from ..db.models import User, SkillActionPlan, CandidateProfile, JobPosting
from ..db.profile_repository import profile_repository
from ..services.gemini_service import gemini_service, safe_parse_json
from ..services.matcher_service import matcher_service

logger = logging.getLogger(__name__)


def _default_docs_url(skill: str) -> str:
    low = skill.lower()
    known = {
        "playwright": "https://playwright.dev/docs/intro",
        "cypress": "https://docs.cypress.io/guides/overview/why-cypress",
        "docker": "https://docs.docker.com/get-started/",
        "k6": "https://k6.io/docs/",
        "typescript": "https://www.typescriptlang.org/docs/",
        "graphql": "https://graphql.org/learn/",
        "appium": "https://appium.io/docs/en/latest/",
        "python": "https://docs.python.org/3/tutorial/",
        "sql": "https://www.postgresql.org/docs/current/tutorial.html",
        "kubernetes": "https://kubernetes.io/docs/tutorials/",
        "github actions": "https://docs.github.com/en/actions",
        "selenium": "https://www.selenium.dev/documentation/",
        "pytest": "https://docs.pytest.org/en/stable/",
    }
    for k, url in known.items():
        if k in low:
            return url
    return f"https://roadmap.sh/search?q={quote_plus(skill)}"


def _build_dynamic_skill_roadmap(skill_name: str, role: str = "Specialist") -> Dict[str, Any]:
    """
    Domain-agnostic dynamic fallback roadmap generator when Gemini/Search API is offline:
    builds a structured 7-day learning plan with Official Docs, YouTube Tutorials, and Blog Guides.
    """
    docs_url = _default_docs_url(skill_name)
    yt_q = quote_plus(f"{skill_name} tutorial practical project")
    yt_deep_q = quote_plus(f"{skill_name} crash course best practices")
    blog_dev_q = quote_plus(f"{skill_name} guide examples")
    blog_med_q = quote_plus(f"{skill_name} architecture best practices")

    steps = [
        ("Environment Setup & Core Concepts", f"Install & configure {skill_name} locally and walk through official quickstart exercises."),
        ("Core Workflows & Syntax Mastery", f"Build 3 foundational {skill_name} examples tailored to {role} real-world scenarios."),
        ("Error Handling & Edge Cases", f"Practice debugging failures, inspecting logs, and validating negative edge cases in {skill_name}."),
        ("Real Dataset / API Integration", f"Connect {skill_name} with a staging dataset, REST endpoint, or sandbox workflow."),
        ("Automation & Repeatable Workflows", f"Automate a repeatable {skill_name} checklist or pipeline step ready for code review."),
        ("Performance, Security & Quality Review", f"Audit {skill_name} outputs against industry benchmarks and troubleshoot bottlenecks."),
        ("Portfolio Deliverable & Documentation", f"Publish a clean GitHub/portfolio project showcasing verified {skill_name} competence."),
    ]

    milestones = []
    for idx, (stage, task_desc) in enumerate(steps, start=1):
        yt_list = [
            {
                "title": f"{skill_name}: {stage} (Video Walkthrough)",
                "channel": "YouTube Engineering Tutorials",
                "url": f"https://www.youtube.com/results?search_query={quote_plus(f'{skill_name} {stage} tutorial')}",
            },
            {
                "title": f"{skill_name} Full Crash Course & Hands-On Lab",
                "channel": "YouTube Tech Deep Dive",
                "url": f"https://www.youtube.com/results?search_query={yt_deep_q}",
            },
        ]
        blogs_list = [
            {
                "title": f"{skill_name} Practical Guide: {stage}",
                "source": "DEV Community",
                "url": f"https://dev.to/search?q={blog_dev_q}",
            },
            {
                "title": f"{skill_name} Production Best Practices",
                "source": "Engineering Blogs",
                "url": f"https://medium.com/search?q={blog_med_q}",
            },
        ]
        milestones.append(
            {
                "day": idx,
                "task": f"[{stage}] {task_desc}",
                "completed": False,
                "resource_url": docs_url,
                "tutorial_url": f"https://www.youtube.com/results?search_query={yt_q}",
                "youtube_videos": yt_list,
                "blog_posts": blogs_list,
            }
        )

    low = skill_name.lower()
    category = (
        "DEVOPS" if any(k in low for k in ("docker", "kubernetes", "ci", "aws", "cloud"))
        else ("API" if any(k in low for k in ("api", "graphql", "postman", "sql")) else "CORE_GAP")
    )
    return {
        "skill_name": skill_name,
        "category": category,
        "days_to_learn": 7,
        "milestones": milestones,
    }


class PlanService:
    """
    AI-driven skill gap analyzer & interactive roadmap generator powered by Gemini 2.5 Flash
    (+ optional Google Search grounding), generating live YouTube video tutorials and engineering blog posts.
    """

    def generate_plans_for_user(
        self,
        user: User,
        session: Session,
        force_refresh: bool = False,
    ) -> List[SkillActionPlan]:
        gt = profile_repository.get_data()
        existing_skills: set[str] = {str(s) for s in (gt.get("skills", {}).get("core") or [])}
        candidate_prof = session.exec(
            select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
        ).first()
        primary_role = "Specialist"
        if candidate_prof and isinstance(candidate_prof.parsed_skills, dict):
            primary_role = str(candidate_prof.parsed_skills.get("primary_role") or candidate_prof.parsed_skills.get("headline") or "Specialist")
            for key in ("verified_skills", "all_skills", "qa_automation", "manual_qa", "languages", "api_and_performance", "cicd_and_devops", "core_skills"):
                for s in candidate_prof.parsed_skills.get(key) or []:
                    existing_skills.add(str(s))
        existing_lower = {s.lower() for s in existing_skills}

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

        # Compare CandidateProfile against missing requirements across live JobPosting rows
        gap_counts: Counter = Counter()
        market_jobs = session.exec(
            select(JobPosting).where(JobPosting.status != "FILTERED_OUT").limit(35)
        ).all()
        for job in market_jobs:
            reqs = matcher_service.extract_job_requirements(job.title, job.description_raw)
            for req in reqs:
                rl = req.lower()
                if not any(rl in ex or ex in rl for ex in existing_lower):
                    gap_counts[req] += 1

        top_gaps = [skill for skill, _ in gap_counts.most_common(6)]
        role_low = primary_role.lower()
        is_qa_profile = any(k in role_low for k in ("qa", "test", "sdet", "quality"))
        has_ai_skill = any("ai " in ex or "ai-" in ex or "llm" in ex or "gemini" in ex or "copilot" in ex for ex in existing_lower)
        if is_qa_profile and not has_ai_skill and not any("ai" in g.lower() or "llm" in g.lower() for g in top_gaps):
            top_gaps.insert(0, "AI-Assisted QA & LLM Test Engineering")
        if not top_gaps:
            # Suggest domain-appropriate growth areas if 0 gaps exist yet in DB
            if "logistics" in role_low or "supply" in role_low:
                top_gaps = ["SAP SCM", "SQL Analytics", "Power BI"]
            elif "finance" in role_low or "account" in role_low:
                top_gaps = ["IFRS Reporting", "Python Financial Modeling", "Power BI"]
            else:
                top_gaps = ["AI-Assisted QA & LLM Test Engineering", "Docker", "k6 Performance Testing"]

        plans_data: List[Dict[str, Any]] = []
        if gemini_service.is_available:
            try:
                plans_data = self._generate_with_gemini(
                    existing_skills=list(existing_skills),
                    top_gaps=top_gaps[:3],
                    primary_role=primary_role,
                )
            except Exception as e:
                logger.warning(f"Gemini skill roadmap generation fallback: {e}")

        if not plans_data:
            plans_data = [_build_dynamic_skill_roadmap(skill, role=primary_role) for skill in top_gaps[:3]]

        created_plans: List[SkillActionPlan] = []
        for pd in plans_data[:3]:
            milestones = pd.get("milestones", [])
            # Ensure every milestone guarantees clickable YouTube & Blog links cleanly
            skill_lbl = str(pd.get("skill_name") or top_gaps[0])
            for m in milestones:
                if isinstance(m, dict):
                    m.setdefault("resource_url", _default_docs_url(skill_lbl))
                    if not m.get("youtube_videos"):
                        m["youtube_videos"] = [
                            {
                                "title": f"{skill_lbl} Tutorial ({m.get('day', 1)})",
                                "channel": "YouTube Search",
                                "url": f"https://www.youtube.com/results?search_query={quote_plus(skill_lbl + ' tutorial')}",
                            }
                        ]
                    if not m.get("blog_posts"):
                        m["blog_posts"] = [
                            {
                                "title": f"{skill_lbl} Technical Guide",
                                "source": "DEV Community",
                                "url": f"https://dev.to/search?q={quote_plus(skill_lbl)}",
                            }
                        ]
                    m.setdefault("tutorial_url", m["youtube_videos"][0]["url"])

            plan = SkillActionPlan(
                user_id=user.id,
                skill_name=skill_lbl,
                category=str(pd.get("category", "CORE_GAP")),
                days_to_learn=int(pd.get("days_to_learn", len(milestones) or 7)),
                milestones=milestones,
                is_completed=False,
            )
            session.add(plan)
            created_plans.append(plan)

        session.commit()
        for p in created_plans:
            session.refresh(p)
        return created_plans

    def _generate_with_gemini(
        self,
        existing_skills: List[str],
        top_gaps: List[str],
        primary_role: str = "Specialist",
    ) -> List[Dict[str, Any]]:
        prompt = f"""
You are a Staff Career Architect & Technical Curriculum Designer.
Candidate Role: {primary_role}
Existing verified skills: {json.dumps(existing_skills[:25])}
Top missing skill gaps from matched job vacancies: {json.dumps(top_gaps)}

Build up to 3 focused 7-day interactive learning roadmaps (one per missing skill).
For EACH milestone (day 1..7), include:
- "day": integer (1..7)
- "task": concise hands-on deliverable
- "completed": false
- "resource_url": official documentation URL
- "youtube_videos": list of 2 objects {{"title": str, "channel": str, "url": str}} (real YouTube tutorial or specific YouTube search URL)
- "blog_posts": list of 2 objects {{"title": str, "source": str, "url": str}} (technical blog/article URLs)
- "tutorial_url": primary YouTube tutorial URL

Return ONLY a valid JSON array of objects with keys: skill_name, category, days_to_learn, milestones.
"""
        resp_obj = None
        if gemini_service.client:
            try:
                from google.genai import types
                cfg = types.GenerateContentConfig(
                    temperature=0.2,
                    tools=[{"google_search": {}}],
                )
                resp = gemini_service.client.models.generate_content(
                    model=gemini_service.model,
                    contents=prompt,
                    config=cfg,
                )
                resp_obj = resp.text
            except Exception:
                resp = gemini_service._call_gemini_with_retry(prompt, temperature=0.2)
                resp_obj = getattr(resp, "text", None)

        if resp_obj:
            cleaned = resp_obj.strip()
            if cleaned.startswith("```"):
                import re as _re
                cleaned = _re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=_re.I).strip()
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, list) and parsed:
                    return parsed
            except Exception:
                pass
            parsed_dict = safe_parse_json(resp_obj)
            if isinstance(parsed_dict, list) and parsed_dict:
                return parsed_dict
        raise ValueError("Invalid Gemini action plan JSON shape")

    def toggle_milestone(self, plan: SkillActionPlan, milestone_index: int, session: Session) -> SkillActionPlan:
        milestones = copy.deepcopy(list(plan.milestones))
        if 0 <= milestone_index < len(milestones):
            current_status = milestones[milestone_index].get("completed", False)
            milestones[milestone_index]["completed"] = not current_status

        plan.milestones = milestones
        all_done = all(m.get("completed", False) for m in milestones)
        plan.is_completed = all_done
        flag_modified(plan, "milestones")
        session.add(plan)

        if all_done:
            self._ingest_mastered_skill(plan.skill_name, session)

        session.commit()
        session.refresh(plan)
        return plan

    def _ingest_mastered_skill(self, skill_name: str, session: Session) -> None:
        try:
            candidate_prof = session.exec(
                select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())
            ).first()
            if candidate_prof:
                parsed = dict(candidate_prof.parsed_skills or {})
                all_sk = list(parsed.get("all_skills", []))
                if skill_name not in all_sk:
                    all_sk.append(skill_name)
                    parsed["all_skills"] = all_sk
                    candidate_prof.parsed_skills = parsed
                    session.add(candidate_prof)
                    logger.info("Ingested mastered skill '%s' into CandidateProfile", skill_name)

            gt = profile_repository.get_data()
            gt_core = gt.setdefault("skills", {}).setdefault("core", [])
            if skill_name not in gt_core:
                gt_core.append(skill_name)
                profile_repository.update_data(gt)
        except Exception as e:
            logger.warning(f"Error updating candidate profile with completed skill: {e}")


plan_service = PlanService()
