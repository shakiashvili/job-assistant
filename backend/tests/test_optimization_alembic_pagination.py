from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import init_db
from app.services.profile_service import profile_service
from app.services.matcher_service import matcher_service
from app.services.scrapers.scraper_orchestrator import scraper_orchestrator

client = TestClient(app)


def test_legacy_storage_removed_and_neutral_vault_defaults():
    storage_dir = Path(__file__).resolve().parents[1] / "app" / "storage"
    assert not storage_dir.exists(), "Legacy app/storage/ directory must be deleted"

    from app.db.profile_repository import profile_repository
    norm = profile_repository._normalize_vault({}, profile_repository.get_profile_record())
    wa = norm["candidate"]["work_authorization"]
    assert isinstance(wa["citizenship"], list)
    assert isinstance(wa["us_work_authorization"], str)


def test_education_coursework_extraction_internships_and_rejection_diagnostics():
    init_db()
    md = """# Tamar Kapanadze
Headline: Junior Software & QA Analyst
1 year experience

## Education
- BSc in Computer Science | Tbilisi State University | 2025
- EPAM QA Automation Bootcamp | Certificate 2025

## Core Skills
- Python, SQL, Playwright, Manual Testing, REST API
"""
    extracted = profile_service.extract_structured_profile(md)
    assert len(extracted.parsed_skills.education) >= 1
    assert any("Computer Science" in str(e.get("degree", "")) or "Computer Science" in str(e.get("field_of_study", "")) for e in extracted.parsed_skills.education)
    assert len(extracted.parsed_skills.courses_and_certifications) >= 1
    assert extracted.eligible_internships is True
    assert len(extracted.internship_tracks) >= 1

    ps = extracted.parsed_skills.model_dump()
    ps["target_industry"] = extracted.target_industry
    ps["primary_role"] = extracted.primary_role
    ps["eligible_internships"] = extracted.eligible_internships
    ps["years_of_experience"] = extracted.experience_years

    # Intern/Trainee graduate role aligns cleanly via education + internship eligibility
    intern_res = matcher_service.evaluate_job_tiered(
        title="Software Testing Intern / Graduate Trainee",
        description="Looking for Computer Science student or recent grad for QA Internship program.",
        parsed_skills=ps,
        portal="jobs.ge",
    )
    assert intern_res["status"] != "FILTERED_OUT"

    # Duty & seniority mismatch strictly rejected AND logged into rejection_reasons
    batch = [
        {
            "portal": "jobs.ge",
            "external_id": "opt-rej-duty-1",
            "title": "QA Operations Specialist",
            "company": "BigEnterprise",
            "url": "https://jobs.ge/ge/?view=jobs&id=9900111",
            "market": "GE_DOMESTIC",
            "description_raw": "You will manage a team of 12 engineers and own full P&L budgeting.",
            "status": "DISCOVERED",
        },
        {
            "portal": "jobs.ge",
            "external_id": "opt-ok-1",
            "title": "Junior QA Engineer",
            "company": "GoodTech",
            "url": "https://jobs.ge/ge/?view=jobs&id=9900112",
            "market": "GE_DOMESTIC",
            "description_raw": "Python, Playwright, SQL, REST API testing. 1 year experience.",
            "status": "DISCOVERED",
        },
    ]
    res = scraper_orchestrator.ingest_scraped_jobs(batch)
    assert res["filtered_out_count"] >= 1
    assert any("manage a team of" in r["reason"].lower() for r in res.get("rejection_reasons", []))


def test_server_side_pagination_and_cache_and_cv_listing():
    init_db()
    up = client.post(
        "/api/profile/upload-skills",
        data={
            "content": "# QA Candidate\n1.5 years experience\n## Core Skills\n- Playwright, Python, PyTest, REST API, SQL\n",
            "run_live_scrape": "false",
        },
    )
    assert up.status_code == 200

    # Seed 15 matching vacancies across portals
    batch = [
        {
            "portal": "djinni.co",
            "external_id": f"page-test-{i}",
            "title": f"Junior QA Engineer #{i}",
            "company": f"TestCorp {i}",
            "url": f"https://djinni.co/jobs/9988{i:02d}-qa/",
            "market": "GLOBAL_REMOTE",
            "is_remote": True,
            "detected_languages": ["English"],
            "language_requirements": ["English"],
            "description_raw": "Remote Worldwide. English working language. Playwright, Python, PyTest, REST API, SQL.",
            "status": "DISCOVERED",
        }
        for i in range(15)
    ]
    ingest_1 = scraper_orchestrator.ingest_scraped_jobs(batch)
    assert ingest_1["total_processed"] == 15

    # Re-ingesting identical batch hits 24h DB evaluation cache
    ingest_2 = scraper_orchestrator.ingest_scraped_jobs(batch)
    assert ingest_2["cache_hits"] == 15

    # Page 1 & Page 2 server-side pagination check
    p1 = client.get("/api/jobs?page=1&limit=5&min_score=60").json()
    p2 = client.get("/api/jobs?page=2&limit=5&min_score=60").json()
    assert len(p1["items"]) == 5
    assert p1["total"] >= 15
    assert p1["page"] == 1
    assert p1["limit"] == 5
    assert p1["total_pages"] >= 3
    assert len(p2["items"]) == 5
    assert p1["items"][0]["id"] != p2["items"][0]["id"]

    # CVVariantManager full list with min_score=0 & limit=100
    all_res = client.get("/api/jobs?page=1&limit=100&min_score=0").json()
    assert len(all_res["items"]) >= 15


def test_dynamic_youtube_and_blog_roadmaps_without_static_dict():
    from app.services import plan_service as ps_mod
    assert not hasattr(ps_mod, "CURATED_SKILL_ROADMAPS")

    init_db()
    client.post(
        "/api/profile/upload-skills",
        data={
            "content": "# Supply Chain Specialist\n1.5 years experience\n## Skills\n- Logistics, WMS, Procurement\n",
            "run_live_scrape": "false",
        },
    )
    res = client.post("/api/profile/generate-action-plan?force_refresh=true")
    assert res.status_code == 200
    plans = res.json()
    assert len(plans) >= 1
    m0 = plans[0]["milestones"][0]
    assert isinstance(m0.get("youtube_videos"), list) and len(m0["youtube_videos"]) >= 1
    assert "youtube.com" in m0["youtube_videos"][0]["url"]
    assert isinstance(m0.get("blog_posts"), list) and len(m0["blog_posts"]) >= 1
    assert m0.get("resource_url", "").startswith("http")

    # Restore default QA preset for suite consistency
    client.post("/api/skills-md/preset/qa_tech")


def test_alembic_initial_schema_migration_present():
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*_initial_schema.py"))
    assert len(migration_files) == 1
