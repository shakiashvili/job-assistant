import uuid
from fastapi.testclient import TestClient

from app.main import app
from app.services.gemini_service import gemini_service
from app.services.scrapers.linkedin_scraper import LinkedInScraper, build_linkedin_search_urls
from app.services.scrapers.query_builder import build_search_queries

client = TestClient(app)


def test_no_fabricated_fallback_companies_or_titles():
    res = gemini_service._fallback_extract_job_details("Some generic role description without headers", portal="generic")
    assert res["company"] == "Unknown Company"
    assert res["title"] == "Unknown Title"
    assert res["extraction_failed"] is True
    assert "CloudScale" not in res["company"]
    assert "Rooms Hotel" not in res["company"]
    assert "Senior QA Automation Engineer" not in res["title"]


def test_linkedin_query_builder_and_scraper_parsing():
    urls = build_linkedin_search_urls("Junior QA Engineer", ["Playwright", "Python"], cap_exp=2.0)
    assert any("f_E=1%2C2%2C3" in u and "f_WT=2" in u for u in urls)

    pkg = build_search_queries({"target_industry": "qa_tech", "primary_role": "Junior QA Engineer", "years_of_experience": 1.5})
    assert "linkedin_urls" in pkg and len(pkg["linkedin_urls"]) >= 2

    sample_html = """
    <ul>
      <li>
        <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:400112233">
          <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/junior-qa-engineer-at-bolt-400112233/?trk=public_jobs"></a>
          <h3 class="base-search-card__title">Junior QA Automation Engineer</h3>
          <h4 class="base-search-card__subtitle"><a href="#">Bolt</a></h4>
          <span class="job-search-card__location">Remote (Worldwide)</span>
          <span class="job-card-container__apply-method">Easy Apply</span>
        </div>
      </li>
      <li>
        <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:400112244">
          <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/manual-qa-intern-400112244/"></a>
          <h3 class="base-search-card__title">Manual QA Intern</h3>
          <h4 class="base-search-card__subtitle">TBC Tech</h4>
          <span class="job-search-card__location">Tbilisi, Georgia</span>
        </div>
      </li>
      <li>
        <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:400112255">
          <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/senior-staff-qa-lead-400112255/"></a>
          <h3 class="base-search-card__title">Senior Staff QA Lead</h3>
          <h4 class="base-search-card__subtitle">EnterpriseCorp</h4>
          <span class="job-search-card__location">Remote</span>
        </div>
      </li>
    </ul>
    """
    parsed = LinkedInScraper().parse_html_listings(sample_html)
    assert len(parsed) == 3

    easy = next(j for j in parsed if "Bolt" in j["company"])
    assert easy["delivery_channel"] == "EASY_APPLY"
    assert easy["status"] != "FILTERED_OUT"

    ext = next(j for j in parsed if "TBC Tech" in j["company"])
    assert ext["delivery_channel"] == "EXTERNAL_ATS"
    assert ext["market"] == "GE_DOMESTIC"

    senior = next(j for j in parsed if "Senior Staff" in j["title"])
    assert senior["status"] == "FILTERED_OUT"


def test_extension_prepare_and_log_application_with_jwt_and_seniority_guard():
    # 1. Extension endpoints strictly enforce Bearer JWT
    unauth = client.post("/api/extension/prepare-application", json={"url": "https://www.linkedin.com/jobs/view/123"})
    assert unauth.status_code == 401

    # 2. Register & obtain JWT
    email = f"ext_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/api/auth/register", json={"email": email, "password": "TestPassword123!", "full_name": "Nino Test"})
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Upload skills so CandidateProfile is populated for this user
    up = client.post(
        "/api/profile/upload-skills",
        headers=headers,
        data={
            "content": "# Nino Test\nHeadline: Junior QA Engineer\n1.5 years experience\n## Skills\n- Python, Playwright, REST API, SQL\n",
            "run_live_scrape": "false",
        },
    )
    assert up.status_code == 200

    # 3. Prepare application for Junior LinkedIn role with structured fields
    prep = client.post(
        "/api/extension/prepare-application",
        headers=headers,
        json={
            "url": "https://www.linkedin.com/jobs/view/junior-qa-123456/",
            "job_title": "Junior QA Automation Engineer",
            "company_name": "MacPaw",
            "location": "Remote",
            "job_description": "Looking for Junior QA Engineer with Playwright, Python, REST API, and SQL. 1+ year experience.",
            "fields": [
                {"field_id": "f0", "label": "First Name", "field_type": "text"},
                {"field_id": "f1", "label": "How many years of Python experience?", "field_type": "number"},
                {"field_id": "f2", "label": "Are you legally authorized to work remotely?", "field_type": "select", "options": ["Yes", "No"]},
                {"field_id": "f3", "label": "Why do you want to join MacPaw?", "field_type": "textarea"},
            ],
        },
    )
    assert prep.status_code == 200
    body = prep.json()
    assert body["portal"] == "linkedin.com"
    assert body["seniority_blocked"] is False
    assert body["tailored_cv"]["pdf_url"].endswith(".pdf")
    assert body["company_intel"]["summary"]
    ans_map = {a["field_id"]: a["value"] for a in body["field_answers"]}
    assert ans_map["f0"] == "Nino"
    assert ans_map["f1"] in ("1.5", "1", "2")
    assert ans_map["f2"] == "Yes"
    assert len(ans_map["f3"]) > 30

    # 4. Senior 5+ years role triggers seniority_warning banner
    sen_prep = client.post(
        "/api/extension/prepare-application",
        headers=headers,
        json={
            "url": "https://www.linkedin.com/jobs/view/senior-999/",
            "job_title": "Senior QA Architect",
            "company_name": "Epam",
            "job_description": "Requires 6+ years of enterprise architecture leadership.",
            "fields": [],
        },
    )
    assert sen_prep.status_code == 200
    assert sen_prep.json()["seniority_blocked"] is True
    assert sen_prep.json()["seniority_warning"]

    # 5. Log submitted application into Kanban tracker
    log_res = client.post(
        "/api/extension/log-application",
        headers=headers,
        json={
            "company_name": "MacPaw",
            "job_title": "Junior QA Automation Engineer",
            "job_url": "https://www.linkedin.com/jobs/view/junior-qa-123456/",
            "portal": "linkedin.com",
            "salary_offered": "$1,500 - $2,000 USD",
            "cv_pdf_path": body["tailored_cv"]["pdf_filename"],
            "status": "APPLIED",
        },
    )
    assert log_res.status_code == 200
    assert log_res.json()["status"] in ("created", "updated")


def test_answers_solve_screening_dynamic_non_qa_grounding():
    up = client.post(
        "/api/profile/upload-skills",
        data={
            "content": (
                "# Sandro Logistics\nHeadline: Supply Chain & Logistics Coordinator\n"
                "2 years experience in Freight Dispatch, WMS, Procurement, SAP\n"
                "## Skills\n- Logistics, Supply Chain, WMS, Procurement, SAP\n"
            ),
            "run_live_scrape": "false",
        },
    )
    assert up.status_code == 200
    res = client.post(
        "/api/answers/solve-screening",
        json={
            "questions": [
                {"id": "q1", "question": "How many years of experience do you have?", "field_type": "number"},
                {"id": "q2", "question": "Applicant summary — introduce yourself", "field_type": "textarea"},
            ],
            "job_title": "Logistics Coordinator",
            "company": "DHL Georgia",
            "variant": "logistics_supply_chain",
        },
    )
    assert res.status_code == 200
    data = res.json()
    ans_map = {a["question"]: a["answer"] for a in data["answers"]}
    assert ans_map["How many years of experience do you have?"] == "2"
    assert "QA Automation" not in data["applicant_summary"]

    # Restore QA profile for suite consistency
    client.post("/api/skills-md/preset/qa_tech")


def test_extension_requires_uploaded_profile_no_sample_cv_and_tailored_letter_no_notice_clutter():
    """
    Verifies:
    1. Newly registered account without skills.md upload cannot generate 'Sample QA Candidate' CVs (400 PROFILE_REQUIRED).
    2. Registering another user never wipes an earlier user's uploaded skills.md profile.
    3. /api/extension/upload-skills parses inline bullet Location & +phone, removes '1 week after offer' / '| , |' clutter,
       and generates a job-requirement & CV-matched motivational letter referencing real workplaces.
    """
    from docx import Document
    from app.config import GENERATED_RESUMES_DIR

    user_a = f"giorgi_{uuid.uuid4().hex[:8]}@example.com"
    user_b = f"other_{uuid.uuid4().hex[:8]}@example.com"
    pw = "StrongPassword123!"

    reg_a = client.post("/api/auth/register", json={"email": user_a, "password": pw, "full_name": "Giorgi Shakiashvili"})
    assert reg_a.status_code == 201
    hdr_a = {"Authorization": f"Bearer {reg_a.json()['access_token']}"}

    # Before upload: profile_uploaded is False and prepare-application refuses with 400 (no Sample QA Candidate fallback!)
    prof_before = client.get("/api/extension/profile", headers=hdr_a)
    assert prof_before.status_code == 200
    assert prof_before.json()["profile_uploaded"] is False

    blocked = client.post(
        "/api/extension/prepare-application",
        headers=hdr_a,
        json={"url": "https://jobs.dou.ua/companies/acme/vacancies/12345/", "job_title": "QA Engineer", "company_name": "Acme"},
    )
    assert blocked.status_code == 400
    assert "PROFILE_REQUIRED" in blocked.json()["detail"]

    # Upload rich markdown directly through the extension endpoint
    sample_md = """# Giorgi Shakiashvili

**QA Engineer • Tech & FinTech Testing • QA Automation**
Tbilisi, Georgia • +995 571-15-68-07 • [giorgishakiashvili21@gmail.com](mailto:giorgishakiashvili21@gmail.com)
[LinkedIn Profile](https://linkedin.com/in/george-shakiashvili) • [GitHub Portfolio](https://github.com/GiorgiShakiashvili)

## Experience (1.5 Years Total)

### QA Intern | EPAM Systems
*Tbilisi, Georgia • Nov 2024 – May 2025*
- Built automated Playwright end-to-end tests in TypeScript and integrated checks into GitHub Actions.
- Validated REST API contracts with Postman and SQL queries across staging builds.

### Software QA Intern | Vention Development
*Tbilisi, Georgia • Jun 2024 – Oct 2024*
- Authored regression test suites in Jira and verified release stability across sprints.

## Core Skills
- Playwright, TypeScript, Python, Postman, REST API, SQL, GitHub Actions, Jira

## Education
- Master of Science in Economics — Tbilisi State University
"""
    up_a = client.post("/api/extension/upload-skills", headers=hdr_a, json={"content": sample_md, "filename": "skills.md"})
    assert up_a.status_code == 200
    assert up_a.json()["profile_uploaded"] is True
    assert up_a.json()["full_name"] == "Giorgi Shakiashvili"

    # Registering User B MUST NOT wipe User A's uploaded profile!
    reg_b = client.post("/api/auth/register", json={"email": user_b, "password": pw, "full_name": "Other Candidate"})
    assert reg_b.status_code == 201
    hdr_b = {"Authorization": f"Bearer {reg_b.json()['access_token']}"}
    assert client.get("/api/extension/profile", headers=hdr_b).json()["profile_uploaded"] is False
    assert client.get("/api/extension/profile", headers=hdr_a).json()["profile_uploaded"] is True

    # Prepare tailored application as User A
    prep = client.post(
        "/api/extension/prepare-application",
        headers=hdr_a,
        json={
            "url": "https://jobs.dou.ua/companies/fintech-co/vacancies/88888/",
            "job_title": "Junior QA Automation Engineer",
            "company_name": "FinTechCo",
            "job_description": "Requirements: Playwright, TypeScript, REST API testing, SQL, CI/CD with GitHub Actions.",
            "fields": [
                {"field_id": "cl", "label": "Cover Letter / Motivation", "field_type": "textarea"},
            ],
        },
    )
    assert prep.status_code == 200
    body = prep.json()
    letter = body["cover_letter"]
    assert "Sample QA Candidate" not in letter
    assert "1 week after offer" not in letter.lower()
    assert "notice period" not in letter.lower()
    assert "EPAM Systems" in letter or "Vention Development" in letter
    assert "Playwright" in letter or "REST API" in letter
    assert "Giorgi Shakiashvili" in letter

    # Verify generated PDF, DOCX, and HTML preview contain zero '| , |' or '1 week after offer' / 'Notice Period' clutter
    pdf_path = GENERATED_RESUMES_DIR / body["tailored_cv"]["pdf_filename"]
    docx_path = GENERATED_RESUMES_DIR / body["tailored_cv"]["docx_filename"]
    html_path = pdf_path.with_suffix(".html")
    assert pdf_path.exists() and pdf_path.read_bytes().startswith(b"%PDF-")
    assert docx_path.exists()
    assert html_path.exists()

    docx_text = "\n".join(p.text for p in Document(str(docx_path)).paragraphs)
    html_text = html_path.read_text(encoding="utf-8")
    for rendered in (docx_text, html_text):
        assert "Giorgi Shakiashvili" in rendered
        assert "Sample QA Candidate" not in rendered
        assert ", |" not in rendered
        assert "| ," not in rendered
        assert "Tbilisi, Georgia" in rendered
        assert "+995 571-15-68-07" in rendered
        assert "1 week after offer" not in rendered.lower()
        assert "notice period" not in rendered.lower()
        assert "(None)" not in rendered


def test_cv_filename_uniqueness_html_escape_languages_and_download_headers():
    """Verifies role-specific CV filenames, HTML XSS escaping, dynamic Languages from skills.md, ATS header, and Content-Disposition."""
    import uuid
    from pathlib import Path
    from docx import Document
    from app.config import GENERATED_RESUMES_DIR
    from app.services.cv_generator_service import cv_generator_service, UNICODE_FONT_NAME
    from reportlab.pdfbase import pdfmetrics

    # Bold/Italic family registered on Unicode font (if not Helvetica)
    if UNICODE_FONT_NAME != "Helvetica":
        assert f"{UNICODE_FONT_NAME}-Bold" in pdfmetrics.getRegisteredFontNames()

    skills_custom = """# Test User (<script>alert(1)</script>)
Headline: Backend Engineer
Email: test.lang@example.com
Location: Batumi, Georgia
Languages: English (C2), German (B2), Georgian (Native)

## Core Skills
Python, FastAPI, PostgreSQL
"""
    pkg1 = cv_generator_service.prepare_email_application_package(
        job_title="QA Engineer",
        company="TBC Bank",
        description="Python Playwright",
        skills_md_override=skills_custom,
        cv_language="en",
    )
    pkg2 = cv_generator_service.prepare_email_application_package(
        job_title="Automation SDET",
        company="TBC Bank",
        description="Python Playwright",
        skills_md_override=skills_custom,
        cv_language="en",
    )
    assert pkg1["pdf_filename"] != pkg2["pdf_filename"]
    assert pkg1["docx_filename"] != pkg2["docx_filename"]

    html_raw = (GENERATED_RESUMES_DIR / pkg1["pdf_filename"]).with_suffix(".html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html_raw
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_raw
    assert "German (B2)" in html_raw

    docx_raw = "\n".join(p.text for p in Document(str(GENERATED_RESUMES_DIR / pkg1["docx_filename"])).paragraphs)
    assert "German (B2)" in docx_raw

    # ATS Edition must NOT say "TAILORED FOR ATS EDITION"
    ats_pkg = cv_generator_service.prepare_email_application_package(
        job_title="Backend Engineer",
        company="ATS Edition",
        description="",
        skills_md_override=skills_custom,
        cv_language="en",
        cv_style="ats",
    )
    ats_html = (GENERATED_RESUMES_DIR / ats_pkg["pdf_filename"]).with_suffix(".html").read_text(encoding="utf-8")
    assert "TAILORED FOR ATS EDITION" not in ats_html

    # Explicit Content-Disposition: attachment header on PDF and DOCX downloads
    client = TestClient(app)
    for url_key in ("pdf_url", "docx_url"):
        resp = client.get(pkg1[url_key])
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()


def test_prod_secret_key_enforced_gmail_oauth_and_tracker_blank_recipient(monkeypatch):
    """Verifies production SECRET_KEY guard, OAuth-first email dispatch, BACKEND_URL callback, and blank recipient rejection."""
    import os
    import subprocess
    import sys
    import uuid
    from pathlib import Path
    from app.db.models import User
    from app.services.gmail_service import gmail_service

    # 1. Production environment without custom SECRET_KEY must raise RuntimeError
    env_copy = dict(os.environ)
    env_copy["ENVIRONMENT"] = "production"
    env_copy["SECRET_KEY"] = ""
    proc = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env_copy,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "RuntimeError" in proc.stderr or "SECRET_KEY" in proc.stderr

    # 2. Simulated Google auth callback URL uses GOOGLE_REDIRECT_URI rather than hardcoded localhost:8000
    monkeypatch.setattr("app.services.gmail_service.GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr("app.services.gmail_service.GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setattr("app.services.gmail_service.GOOGLE_REDIRECT_URI", "https://api.example.com/api/auth/google/callback")
    auth_url = gmail_service.get_authorization_url("state123")
    assert auth_url.startswith("https://api.example.com/api/auth/google/callback?")

    # 3. send_application_email uses connected Google OAuth before SMTP
    fake_user = User(
        email="oauth@example.com",
        hashed_password="x",
        full_name="OAuth User",
        gmail_oauth_token={"access_token": "tok", "refresh_token": "ref", "simulated": False},
    )
    monkeypatch.setattr(gmail_service, "is_configured", lambda: True)
    called = {}

    def fake_dispatch(**kwargs):
        called.update(kwargs)
        return {"status": "success", "mode": "send", "channel": "gmail_oauth", "message_id": "m1", "thread_id": "t1"}

    monkeypatch.setattr(gmail_service, "dispatch_email", fake_dispatch)
    res = gmail_service.send_application_email("hr@real.com", "Subj", "Body", user=fake_user)
    assert res["delivered"] is True
    assert res["channel"] == "gmail_oauth"
    assert res["thread_id"] == "t1"
    assert called["recipient_email"] == "hr@real.com"

    # 4. /api/applications/{app_id}/send-email rejects blank recipient instead of guessing hr@company.com
    client = TestClient(app)
    u_email = f"tracker_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/api/auth/register", json={"email": u_email, "password": "StrongPassword123!", "full_name": "Test User"})
    assert reg.status_code == 201
    hdr = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    bad_send = client.post(
        "/api/applications/999999/send-email",
        headers=hdr,
        json={"recipient_email": "", "subject": "Hello", "body_text": "World", "mode": "draft"},
    )
    assert bad_send.status_code == 400

