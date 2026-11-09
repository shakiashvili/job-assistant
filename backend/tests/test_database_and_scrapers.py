import io
from pathlib import Path
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.db.database import engine
from app.db.models import CandidateProfile, JobPosting, ApplicationRecord
from app.services.salary_service import salary_service
from app.services.company_validator import company_validator
from app.services.portal_detector import detect_portal_from_url
from app.services.scrapers.base_scraper import (
    evaluate_remote_and_language_gate,
    parse_contact_method_and_email,
)

client = TestClient(app)


def test_bug1_company_validator_no_synthetic_md5():
    """Verify unknown companies return neutral UNVERIFIED status without MD5 fabrication."""
    unknown = company_validator.validate_company("CompletelyUnknownCompanyXYZ_2026")
    assert unknown.reputation == "UNVERIFIED"
    assert unknown.rating is None
    assert unknown.reviews_count == 0
    assert unknown.review_count == 0
    assert unknown.is_blacklisted is False
    assert unknown.passed_gate is True

    # Known verified company still returns verified stats
    verified = company_validator.validate_company("TBC Bank")
    assert verified.reputation == "VERIFIED"
    assert verified.rating is not None and verified.rating >= 4.0
    assert verified.reviews_count >= 3


def test_bug2_canonical_hostname_portal_detection():
    """Verify portal_detector uses urllib.parse.urlparse hostname matching instead of mock file paths."""
    assert detect_portal_from_url("https://jobs.dou.ua/companies/macpaw/vacancies/123/") == "dou.ua"
    assert detect_portal_from_url("https://djinni.co/jobs/650112-senior-qa/") == "djinni.co"
    assert detect_portal_from_url("https://jobs.ge/en/?view=jobs&id=541209") == "jobs.ge"
    assert detect_portal_from_url("https://www.hr.ge/announcement/391044/qa-lead") == "hr.ge"
    assert detect_portal_from_url("https://boards.greenhouse.io/datadog/jobs/1") == "greenhouse"
    assert detect_portal_from_url("https://jobs.lever.co/spotify/1") == "lever"


def test_upload_skills_endpoint_and_candidate_profile_db():
    sample_skills_md = """# Alex Mercer — Lead QA Automation Engineer & SDET

## Summary
Senior QA Automation Engineer with 6+ years of experience building scalable test suites.

## Core Skills
- **Automation:** Playwright, Selenium, Cypress, Appium, PyTest, JUnit
- **Languages:** Python, TypeScript, Java, SQL, Bash
- **API & Performance:** Postman, REST Assured, REST API, k6, JMeter
- **CI/CD & DevOps:** GitHub Actions, GitLab CI, Docker, Kubernetes
"""
    files = {"file": ("skills.md", io.BytesIO(sample_skills_md.encode("utf-8")), "text/markdown")}
    res = client.post("/api/profile/upload-skills", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    parsed = data["parsed_skills"]
    assert "Playwright" in parsed["qa_automation"]
    assert "Selenium" in parsed["qa_automation"]
    assert "Cypress" in parsed["qa_automation"]
    assert "PyTest" in parsed["qa_automation"]
    assert "Python" in parsed["languages"]
    assert "TypeScript" in parsed["languages"]
    assert "SQL" in parsed["languages"]
    assert "Postman" in parsed["api_and_performance"]
    assert "k6" in parsed["api_and_performance"]
    assert "GitHub Actions" in parsed["cicd_and_devops"]
    assert "Docker" in parsed["cicd_and_devops"]
    assert "Kubernetes" in parsed["cicd_and_devops"]
    assert parsed["years_of_experience"] == 6.0

    # Verify persistence in relational CandidateProfile table
    with Session(engine) as session:
        prof = session.exec(select(CandidateProfile).order_by(CandidateProfile.updated_at.desc())).first()
        assert prof is not None
        assert "Playwright" in prof.parsed_skills["qa_automation"]


def test_strict_remote_and_language_gate_and_contact_extraction():
    # 1. Ukrainian language requirement -> FILTERED_OUT
    is_rem, status, reason, langs = evaluate_remote_and_language_gate(
        title="Senior QA Engineer",
        description="Requirements: Playwright, Python. Обов'язково вільна українська мова, fluent Ukrainian.",
        location_text="Remote",
        portal="dou.ua",
    )
    assert status == "FILTERED_OUT"
    assert "Requires local language" in reason
    assert "Ukrainian" in langs

    # 2. Russian language requirement -> FILTERED_OUT
    is_rem2, status2, reason2, langs2 = evaluate_remote_and_language_gate(
        title="QA Automation Engineer",
        description="Stack: Selenium, Java. Требования: русский на разговорном уровне.",
        location_text="Remote",
        portal="djinni.co",
    )
    assert status2 == "FILTERED_OUT"
    assert "Requires local language" in reason2
    assert "Russian" in langs2

    # 3. English-only remote position -> DISCOVERED
    is_rem3, status3, reason3, langs3 = evaluate_remote_and_language_gate(
        title="Senior QA Automation Engineer (Playwright/Python)",
        description="Full Remote role. Working language is English (Upper-Intermediate B2+).",
        location_text="Remote Worldwide",
        portal="djinni.co",
    )
    assert is_rem3 is True
    assert status3 == "DISCOVERED"
    assert "English" in langs3

    # 4. Georgian portal email contact vs web form extraction
    ch, email, subj = parse_contact_method_and_email(
        "Please send your CV to: talent@tbcbank.com.ge and indicate subject: 'Senior QA Automation Engineer'."
    )
    assert ch == "EMAIL"
    assert email == "talent@tbcbank.com.ge"
    assert "Senior QA Automation Engineer" in subj


def test_automated_ai_salary_estimator():
    # 1. Explicit salary extraction via regex ($3,000 - $4,500)
    explicit_usd = salary_service.estimate_salary(
        title="Senior QA Automation Engineer",
        description="We offer $3,000 - $4,500 per month for a remote Playwright engineer.",
        market="INT_REMOTE",
    )
    assert explicit_usd["salary_estimated_by_ai"] is False
    assert explicit_usd["min_salary"] == 3000.0
    assert explicit_usd["max_salary"] == 4500.0
    assert explicit_usd["currency"] == "USD"

    # 2. Explicit GEL salary extraction (5000-7000 GEL)
    explicit_gel = salary_service.estimate_salary(
        title="Lead QA Engineer",
        description="Compensation range: 5000-7000 GEL net in Tbilisi.",
        market="GE",
    )
    assert explicit_gel["salary_estimated_by_ai"] is False
    assert explicit_gel["min_salary"] == 5000.0
    assert explicit_gel["max_salary"] == 7000.0
    assert explicit_gel["currency"] == "GEL"

    # 3. Unstated salary -> AI estimation based on seniority, market & tech stack
    estimated_ge = salary_service.estimate_salary(
        title="Senior SDET (Playwright + Python)",
        description="Requirements: 5+ years Python, Playwright, PyTest, Docker, CI/CD. Competitive salary.",
        market="GE",
        portal="jobs.ge",
    )
    assert estimated_ge["salary_estimated_by_ai"] is True
    assert estimated_ge["currency"] == "GEL"
    assert estimated_ge["min_salary"] >= 4000.0
    assert estimated_ge["max_salary"] > estimated_ge["min_salary"]


def test_multi_portal_scrapers_and_suitability_promotion():
    res = client.post("/api/jobs/scrape", json={"allow_network": False})
    assert res.status_code == 200
    payload = res.json()
    assert payload["total_processed"] >= 6
    assert payload["staged_ready_count"] >= 3
    assert payload["filtered_out_count"] >= 2

    jobs = payload["jobs"]
    portals_seen = {j["portal"] for j in jobs}
    assert {"jobs.ge", "hr.ge", "dou.ua", "djinni.co"}.issubset(portals_seen)

    # Verify FILTERED_OUT jobs have reason "Requires local language"
    filtered_jobs = [j for j in jobs if j["status"] == "FILTERED_OUT"]
    assert len(filtered_jobs) >= 2
    assert any("Requires local language" in j["match_rationale"] for j in filtered_jobs)

    # Verify Georgian EMAIL channel extraction is persisted
    email_jobs = [j for j in jobs if j.get("channel") == "EMAIL"]
    assert len(email_jobs) >= 1
    assert email_jobs[0]["target_email"] is not None

    # Verify jobs with suitability_score >= 75% were auto-promoted to STAGED and linked to ApplicationRecord
    staged_jobs = [j for j in jobs if j["status"] == "STAGED"]
    assert len(staged_jobs) >= 3
    for sj in staged_jobs:
        assert sj["suitability_score"] >= 75.0
        assert sj["salary_min"] is not None and sj["salary_max"] is not None

    with Session(engine) as session:
        app_records = session.exec(select(ApplicationRecord)).all()
        assert len(app_records) >= 3
