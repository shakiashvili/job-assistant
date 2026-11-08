from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_audit_job_with_raw_text_and_pdf_generation():
    # Ensure QA preset is active first
    client.post("/api/skills-md/preset/qa_tech")
    sample_job = """
    Senior QA Automation Engineer at MacPaw
    Location: Remote (EU / Ukraine / Georgia)
    Requirements:
    - 4+ years of test automation experience with Playwright or Cypress
    - Strong programming skills in Python or TypeScript
    - REST API testing experience
    - GitHub Actions and Docker
    """
    response = client.post("/api/audit-job", json={
        "raw_text": sample_job,
        "job_url": "dou_sample",
        "variant": "qa_automation",
        "cv_language": "en",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["match_score"] >= 80
    assert data["score_breakdown"]["skills_match"] >= 80
    assert data["score_breakdown"]["ats_match"] >= 80
    assert data["score_breakdown"]["recruiter_match"] >= 80
    assert data["company_validation"]["passed_gate"] is True
    assert data["company_validation"]["review_count"] >= 3
    assert data["tailored_cv"]["pdf_filename"].endswith(".pdf")
    assert "1 week after offer" in data["tailored_cv"]["start_date_default"]


def test_receptionist_and_georgian_cv_generation():
    # Switch to Receptionist & Hospitality preset
    preset_res = client.post("/api/skills-md/preset/receptionist_hospitality")
    assert preset_res.status_code == 200

    receptionist_job = """
    Front Desk Receptionist / Guest Relations Officer at Rooms Hotel Tbilisi (Adjara Group)
    Portal: jobs.ge
    Requirements:
    - Front Office Operations, Check-in / Check-out, Guest Relations
    - Opera PMS, Fidelio, Booking.com Extranet, POS Terminals
    - Georgian and English fluency
    """
    response = client.post("/api/audit-job", json={
        "raw_text": receptionist_job,
        "job_url": "https://jobs.ge/ge/?view=jobs&id=549201",
        "variant": "receptionist_hospitality",
        "cv_language": "ka",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["company_validation"]["passed_gate"] is True
    assert data["tailored_cv"]["cv_language"] == "ka"
    assert data["tailored_cv"]["pdf_filename"].endswith("_KA.pdf")
    assert data["tailored_cv"]["html_preview_url"].endswith("_KA.html")
    assert "კვირა" in data["tailored_cv"]["start_date_default"]

    # Switch back to QA preset for subsequent tests
    client.post("/api/skills-md/preset/qa_tech")


def test_audit_job_detects_blockers_and_low_reviews():
    unverified_job = """
    Lead Automation Architect at NoReviewStealthCorp (1 review)
    Location: Washington, DC, United States
    Requirements:
    - Active Top Secret US Security Clearance required
    - US Citizenship mandatory
    """
    response = client.post("/api/audit-job", json={
        "raw_text": unverified_job,
        "variant": "qa_automation"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["match_score"] <= 55
    assert data["company_validation"]["passed_gate"] is False
    blocker_categories = [b["category"] for b in data["blockers"]]
    assert "company_reviews" in blocker_categories
