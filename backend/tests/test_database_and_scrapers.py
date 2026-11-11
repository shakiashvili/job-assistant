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
    from app.config import SKILLS_MD_FILE
    original_text = SKILLS_MD_FILE.read_text(encoding="utf-8") if SKILLS_MD_FILE.exists() else None
    try:
        sample_skills_md = """# Giorgi Shakiashvili — QA Automation Engineer

## Summary
QA Automation Engineer with 1.5 years of experience building scalable test suites.

## Core Skills
- **Automation:** Playwright, Selenium, Cypress, Appium, PyTest, JUnit
- **Languages:** Python, TypeScript, Java, SQL, Bash
- **API & Performance:** Postman, REST Assured, REST API, k6, JMeter
- **CI/CD & DevOps:** GitHub Actions, GitLab CI, Docker, Kubernetes
"""
        files = {"file": ("skills.md", io.BytesIO(sample_skills_md.encode("utf-8")), "text/markdown")}
        res = client.post("/api/profile/upload-skills", files=files, data={"run_live_scrape": "false"})
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
        assert parsed["years_of_experience"] == 1.5
    finally:
        if original_text is not None:
            SKILLS_MD_FILE.write_text(original_text, encoding="utf-8")

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

    # 3b. Ukraine-only location restriction on remote portal -> FILTERED_OUT
    is_rem_ua, status_ua, reason_ua, _ = evaluate_remote_and_language_gate(
        title="QA Engineer",
        description="Ukraine-based role. Requirements: Playwright, Python. English B2.",
        location_text="Full Remote · Ukraine",
        portal="djinni.co",
    )
    assert status_ua == "FILTERED_OUT"
    assert "Location Gate" in reason_ua

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
    from app.services.scrapers.scraper_orchestrator import scraper_orchestrator
    from app.services.scrapers.jobs_ge_scraper import jobs_ge_scraper
    from app.services.scrapers.hr_ge_scraper import hr_ge_scraper
    from app.services.scrapers.dou_scraper import dou_scraper
    from app.services.scrapers.djinni_scraper import djinni_scraper
    from app.services.link_validator import validate_live_html_content
    from app.services.profile_service import profile_service

    # 1. Verify dead fallback mock arrays are completely purged (allow_network=False -> 0 jobs)
    assert jobs_ge_scraper._fallback_curated_listings() == []
    assert hr_ge_scraper._fallback_curated_listings() == []
    assert dou_scraper._fallback_curated_listings() == []
    assert djinni_scraper._fallback_curated_listings() == []

    res_offline = client.post("/api/jobs/scrape", json={"allow_network": False})
    assert res_offline.status_code == 200
    assert res_offline.json()["total_processed"] == 0

    # 2. Verify dynamic role-based query mapping from QA skills.md
    search_cfg = profile_service.get_search_queries_for_profile({"target_industry": "qa_tech", "qa_automation": ["Playwright"]})
    assert "https://jobs.ge/ge/?page=1&q=QA&cid=6" in search_cfg["jobs_ge_urls"]
    assert "https://jobs.ge/ge/?page=1&q=Tester&cid=6" in search_cfg["jobs_ge_urls"]
    assert search_cfg["djinni_url"] == "https://djinni.co/jobs/?primary_keyword=QA&employment=remote"

    # 3. Verify Jobs.ge #job_list_table parser constructs canonical URLs & ignores VIP banners/client links
    sample_jobsge_table = """
    <div class="vip-banner"><a href="/ge/?view=jobs&id=999999">VIP Ad Outside Table</a></div>
    <table id="job_list_table">
      <tr>
        <td><a href="/ge/?view=jobs&id=761313">QA Automation Engineer</a></td>
        <td><a href="/ge/?view=client&client=bog">Bank of Georgia</a></td>
      </tr>
      <tr>
        <td><a href="/ge/?view=jobs&id=763944">Manual QA Tester</a></td>
        <td><a href="/ge/?view=client&client=genofit">GenofIT</a></td>
      </tr>
    </table>
    """
    parsed_ge = jobs_ge_scraper.parse_html_listings(sample_jobsge_table)
    assert len(parsed_ge) == 2
    assert parsed_ge[0]["url"] == "https://jobs.ge/ge/?view=jobs&id=761313"
    assert parsed_ge[1]["url"] == "https://jobs.ge/ge/?view=jobs&id=763944"

    # 4. Verify live Jobs.ge HTML health check rejects blank/expired 200 OK pages
    blank_jobsge_html = """<html><body><div class="dtable"><table>
      <tr><td>დასახელება:</td></tr>
      <tr><td>მომწოდებელი:</td></tr>
      <tr><td>გამოქვეყნდა: / ბოლო ვადა:</td></tr>
    </table></div></body></html>"""
    is_valid_blank, _ = validate_live_html_content("https://jobs.ge/ge/?view=jobs&id=541092", blank_jobsge_html)
    assert is_valid_blank is False

    active_jobsge_html = """<html><body><div class="dtable"><table>
      <tr><td>დასახელება: QA Automation Engineer</td></tr>
      <tr><td>მომწოდებელი: Bank of Georgia</td></tr>
      <tr><td>გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი</td></tr>
      <tr><td>Looking for QA Automation Engineer with Playwright, Python, PyTest, REST API, Docker. Send CV to qa@bog.ge</td></tr>
    </table></div></body></html>"""
    is_valid_active, clean_txt = validate_live_html_content("https://jobs.ge/ge/?view=jobs&id=761313", active_jobsge_html)
    assert is_valid_active is True
    assert "Playwright" in clean_txt

    # 5. Verify ingest_scraped_jobs enforces domain/seniority/language gates & persists only valid matches
    discovered_batch = [
        {
            "portal": "jobs.ge",
            "external_id": "jobsge-761313",
            "title": "QA Automation Engineer (Playwright / Python)",
            "company": "Bank of Georgia",
            "url": "https://jobs.ge/ge/?view=jobs&id=761313",
            "market": "GE_DOMESTIC",
            "is_remote": True,
            "channel": "EMAIL",
            "target_email": "talent@bog.ge",
            "email_subject": "QA Automation Engineer - [Name]",
            "detected_languages": ["English", "Georgian"],
            "language_requirements": ["English", "Georgian"],
            "description_raw": "QA Automation Engineer. Stack: Playwright, Python, PyTest, REST API, Docker. Send CV to talent@bog.ge",
            "status": "DISCOVERED",
        },
        {
            "portal": "hr.ge",
            "external_id": "hrge-499959",
            "title": "QA Test Engineer (PyTest & API)",
            "company": "GenofIT",
            "url": "https://www.hr.ge/announcement/499959/qa",
            "market": "GE_DOMESTIC",
            "is_remote": True,
            "channel": "WEB_FORM",
            "detected_languages": ["English", "Georgian"],
            "language_requirements": ["English", "Georgian"],
            "description_raw": "QA Test Engineer. Requirements: Playwright, PyTest, Postman, REST API, SQL.",
            "status": "DISCOVERED",
        },
        {
            "portal": "dou.ua",
            "external_id": "dou-377767",
            "title": "QA Engineer (Remote)",
            "company": "Qencode",
            "url": "https://jobs.dou.ua/companies/qencode/vacancies/377767/",
            "market": "UA_REMOTE",
            "is_remote": True,
            "channel": "WEB_FORM",
            "detected_languages": ["English"],
            "language_requirements": ["English"],
            "description_raw": "Remote QA Engineer. English B2+. Requirements: Playwright, Python, Postman, REST API, GitHub Actions.",
            "status": "DISCOVERED",
        },
        {
            "portal": "djinni.co",
            "external_id": "djinni-855686",
            "title": "QA Automation Engineer (1.5+ yrs)",
            "company": "Stormotion",
            "url": "https://djinni.co/jobs/855686-qa-engineer/",
            "market": "GLOBAL_REMOTE",
            "is_remote": True,
            "channel": "WEB_FORM",
            "detected_languages": ["English"],
            "language_requirements": ["English"],
            "description_raw": "Full Remote Worldwide. English working language. Playwright, Cypress, Python, REST API, Docker.",
            "status": "DISCOVERED",
        },
        {
            "portal": "jobs.ge",
            "external_id": "jobsge-760613",
            "title": "უფროსი Back-End დეველოპერი",
            "company": "OtherCo",
            "url": "https://jobs.ge/ge/?view=jobs&id=760613",
            "market": "GE_DOMESTIC",
            "is_remote": False,
            "channel": "WEB_FORM",
            "detected_languages": ["Georgian"],
            "language_requirements": ["Georgian"],
            "description_raw": "Senior Backend developer .NET role.",
            "status": "DISCOVERED",
        },
        {
            "portal": "djinni.co",
            "external_id": "djinni-852542",
            "title": "QA Engineer (Salesforce)",
            "company": "Advirix",
            "url": "https://djinni.co/jobs/852542-qa-engineer-salesforce/",
            "market": "GLOBAL_REMOTE",
            "is_remote": True,
            "channel": "WEB_FORM",
            "detected_languages": ["English"],
            "language_requirements": ["English"],
            "description_raw": "Full Remote · Worldwide | Test Salesforce flows and Apex integrations.",
            "status": "DISCOVERED",
        },
    ]

    payload = scraper_orchestrator.ingest_scraped_jobs(discovered_batch)
    assert payload["staged_ready_count"] >= 3
    assert payload["filtered_out_count"] >= 2

    jobs = payload["jobs"]
    portals_seen = {j["portal"] for j in jobs}
    assert {"jobs.ge", "hr.ge", "dou.ua", "djinni.co"}.issubset(portals_seen)

    # Verify FILTERED_OUT jobs (like Senior/Backend 'უფროსი Back-End დეველოპერი') are NEVER leaked or saved
    filtered_jobs = [j for j in jobs if j["status"] == "FILTERED_OUT"]
    assert len(filtered_jobs) == 0

    # Verify Georgian EMAIL channel extraction is persisted
    email_jobs = [j for j in jobs if j.get("channel") == "EMAIL"]
    assert len(email_jobs) >= 1
    assert email_jobs[0]["target_email"] == "talent@bog.ge"

    # Verify jobs with suitability_score >= 75% were auto-promoted to STAGED without fabricating unstated salaries
    staged_jobs = [j for j in jobs if j["status"] == "STAGED"]
    assert len(staged_jobs) >= 3
    for sj in staged_jobs:
        assert sj["suitability_score"] >= 75.0
        assert sj["salary_estimated_by_ai"] is False

    with Session(engine) as session:
        app_records = session.exec(select(ApplicationRecord)).all()
        assert len(app_records) >= 3
        # Ensure off-domain Senior job & Salesforce specialization mismatch were NOT stored in JobPosting DB
        disq = session.exec(select(JobPosting).where(JobPosting.external_id == "jobsge-760613")).first()
        assert disq is None
        sf_disq = session.exec(select(JobPosting).where(JobPosting.external_id == "djinni-852542")).first()
        assert sf_disq is None
