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
