import uuid
from pathlib import Path
from docx import Document
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import init_db
from app.db.profile_repository import profile_repository, filter_spoken_language_entries, is_programming_token
from app.services.cv_generator_service import cv_generator_service, _clean_foreign_script_text, _format_candidate_languages
from app.services.gemini_service import gemini_service
from app.services.gmail_service import GMAIL_SCOPES, gmail_service

client = TestClient(app)


def _auth_headers(email_prefix: str = "qa_tester") -> dict:
    init_db()
    email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@talentflow.local"
    password = "StrongPassword123!"
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": "Giorgi Test"},
    )
    if reg.status_code in (200, 201):
        token = reg.json()["access_token"]
    else:
        login = client.post("/api/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_education_grouping_certifications_and_no_fabricated_honors():
    """Groups each university degree + modules + GPA cleanly without fabricating Honors or Erasmus+."""
    md_path = Path(__file__).resolve().parents[2] / "data" / "candidate_skills.md"
    md_content = md_path.read_text(encoding="utf-8")
    parsed = profile_repository.parse_profile_from_md(md_content)

    edu = parsed.get("education", [])
    assert len(edu) == 2
    assert "Honors" not in str(edu)
    assert "Erasmus" not in str(edu)

    msc = edu[0]
    assert "Master of Science" in msc["degree"]
    assert "Tbilisi State University" in msc["institution"]
    assert "Macroeconomic Policy" in msc["modules"]

    bsc = edu[1]
    assert "Bachelor of Science" in bsc["degree"]
    assert bsc["gpa"] == "3.13 / 4.00"
    assert "Applied Econometrics" in bsc["modules"]

    certs = parsed.get("certifications", [])
    assert len(certs) >= 3
    assert certs[0].startswith("Fullstack QA Lab Program — Vention Development")


def test_spoken_languages_never_leak_programming_languages():
    """Spoken language extraction accepts human languages and rejects TypeScript/Python/SQL/HTML5."""
    assert is_programming_token("TypeScript") is True
    assert is_programming_token("Python") is True
    assert is_programming_token("SQL") is True
    assert is_programming_token("HTML5/CSS3") is True
    assert is_programming_token("Georgian") is False
    assert is_programming_token("English") is False

    mixed = [
        "TypeScript",
        "JavaScript",
        "Python",
        {"language": "HTML5/CSS3", "proficiency": "Fluent"},
        {"language": "Georgian", "proficiency": "Native"},
        {"language": "English", "proficiency": "C1"},
    ]
    cleaned = filter_spoken_language_entries(mixed)
    names = [c["language"] for c in cleaned]
    assert names == ["Georgian", "English"]

    candidate_stub = {"languages": mixed}
    formatted = _format_candidate_languages(candidate_stub, "", is_ka=False)
    assert "TypeScript" not in formatted
    assert "Python" not in formatted
    assert "Georgian: Native" in formatted
    assert "English: C1" in formatted


def test_foreign_script_stripping_and_georgian_sylfaen_docx_pdf(tmp_path):
    """Strips accidental Cyrillic script from EN/KA CVs and applies Sylfaen font in Georgian Word/PDF builds."""
    assert _clean_foreign_script_text("STARTRIBE LTD. Разработка", "en") == "STARTRIBE LTD."
    narratives = gemini_service.craft_human_tone_narratives(
        job_details={
            "title": "Junior QA Engineer",
            "company": "STARTRIBE LTD. Разработка",
            "description": "Manual and automated API testing using Postman, Playwright, SQL.",
        },
        skills_md=Path(__file__).resolve().parents[2].joinpath("data", "candidate_skills.md").read_text(encoding="utf-8"),
        matched_skills=["Playwright", "Postman", "SQL"],
        missing_skills=[],
        cv_language="en",
        candidate_name="Giorgi Shakiashvili",
    )
    combined_nar = " ".join(narratives.values())
    assert "Разработка" not in combined_nar
    assert "tailored for" not in combined_nar.lower()
    assert "one week" not in combined_nar.lower()
    assert narratives.get("cover_letter") and narratives.get("dou_motivational_letter")

    ka_docx = tmp_path / "test_ka.docx"
    cv_generator_service._build_docx_cv(
        filepath=ka_docx,
        candidate={
            "full_name": "გიორგი შაკიაშვილი",
            "email": "giorgi@example.com",
            "phone": "+995 555 00 00 00",
            "location": "თბილისი, საქართველო",
            "languages": [{"language": "Georgian", "proficiency": "Native"}],
        },
        target_role="Junior QA Engineer",
        target_company="ExampleTech",
        human_summary="QA ინჟინერი ტესტირების ავტომატიზაციის გამოცდილებით.",
        display_skills=["Playwright", "Python", "PyTest"],
        work_history=[
            {
                "role": "Junior QA Engineer",
                "company": "ExampleTech",
                "start_date": "2025",
                "end_date": "Present",
                "highlights": ["შექმნა ავტომატური ტესტები Playwright-ზე."],
            }
        ],
        education=[
            {
                "degree": "Bachelor of Science in Economics (BSc)",
                "institution": "Ivane Javakhishvili Tbilisi State University (TSU)",
                "dates": "2022 – 2026",
                "gpa": "3.13 / 4.00",
                "modules": ["Applied Econometrics", "Corporate Finance"],
            }
        ],
        cv_language="ka",
    )
    assert ka_docx.exists()
    doc = Document(str(ka_docx))
    font_names = [
        run.font.name
        for para in doc.paragraphs
        for run in para.runs
        if run.font.name
    ]
    assert "Sylfaen" in font_names

    ka_pdf = tmp_path / "test_ka.pdf"
    cv_generator_service._build_reportlab_single_column_pdf(
        filepath=ka_pdf,
        candidate={
            "full_name": "გიორგი შაკიაშვილი",
            "email": "giorgi@example.com",
            "location": "თბილისი",
            "languages": [{"language": "Georgian", "proficiency": "Native"}],
        },
        target_role="Junior QA Engineer",
        target_company="ExampleTech",
        human_summary="QA ინჟინერი.",
        display_skills=["Playwright", "PyTest"],
        work_history=[],
        education=[
            {
                "degree": "BSc in Economics",
                "institution": "TSU",
                "dates": "2022 – 2026",
                "gpa": "3.13 / 4.00",
                "modules": ["Applied Econometrics"],
            }
        ],
        cv_language="ka",
    )
    assert ka_pdf.exists() and ka_pdf.stat().st_size > 1000


def test_kanban_rejected_status_and_google_calendar_api():
    """Verifies separate Rejected stage persistence, interview_date updates, and Google Calendar event endpoint."""
    assert "https://www.googleapis.com/auth/calendar.events" in GMAIL_SCOPES

    headers = _auth_headers("kanban_cal")

    cal_status = client.get("/api/applications/calendar/status", headers=headers)
    assert cal_status.status_code == 200
    assert cal_status.json()["auth_url"] == "/api/auth/google/login"

    create_res = client.post(
        "/api/applications",
        headers=headers,
        json={
            "role": "QA Automation Engineer",
            "company": "Digis",
            "url": f"https://example.com/jobs/digis-{uuid.uuid4().hex[:6]}",
            "portal": "Generic",
            "status": "Discovered",
            "match_score": 88,
        },
    )
    assert create_res.status_code in (200, 201)
    app_id = create_res.json()["id"]

    # Drag/move to Technical Interview + set interview_date
    patch_interview = client.patch(
        f"/api/applications/{app_id}",
        headers=headers,
        json={
            "status": "Technical Interview",
            "interview_date": "2026-11-20T14:30:00",
            "notes": "Live Playwright coding round",
        },
    )
    assert patch_interview.status_code == 200
    assert patch_interview.json()["status"] == "Technical Interview"
    assert patch_interview.json()["interview_date"] is not None

    # Create calendar event (falls back cleanly to pre-filled Google Calendar URL if user isn't OAuth connected in CI)
    cal_res = client.post(
        f"/api/applications/{app_id}/calendar-event",
        headers=headers,
        json={
            "summary": "Technical Interview: QA Automation Engineer @ Digis",
            "interview_date": "2026-11-20T14:30:00",
            "duration_minutes": 60,
            "location": "Google Meet",
            "description": "Technical QA interview",
        },
    )
    assert cal_res.status_code == 200
    cal_data = cal_res.json()
    assert cal_data["needs_oauth"] is True
    assert "calendar.google.com/calendar/render" in cal_data["google_calendar_template_url"]
    assert "Technical+Interview" in cal_data["html_link"] or "Technical%20Interview" in cal_data["html_link"]

    tpl = gmail_service.build_google_calendar_template_url(
        summary="QA Interview",
        start_iso="2026-11-20T14:30:00",
    )
    assert "action=TEMPLATE" in tpl

    # Move another or same card to separate Rejected column & verify analytics separation
    patch_rejected = client.patch(
        f"/api/applications/{app_id}",
        headers=headers,
        json={"status": "Rejected"},
    )
    assert patch_rejected.status_code == 200
    assert patch_rejected.json()["status"] == "Rejected"

    analytics = client.get("/api/applications/analytics", headers=headers)
    assert analytics.status_code == 200
    assert analytics.json()["by_status"].get("Rejected", 0) >= 1
    assert analytics.json()["rejections"] >= 1


def test_profile_updates_automatically_sync_to_saved_and_generated_cvs():
    """Updating fields on Profile Vault must automatically update both existing CV Studio versions (.docx/.pdf/.html) and newly generated CVs."""
    from app.config import GENERATED_RESUMES_DIR

    headers = _auth_headers("profile_cv_sync")

    # 1. Initial skills.md upload
    initial_md = Path(__file__).resolve().parents[2].joinpath("data", "candidate_skills.md").read_text(encoding="utf-8")
    up_res = client.post("/api/skills-md", headers=headers, json={"content": initial_md})
    assert up_res.status_code == 200

    # 2. Generate an ATS CV edition (creates CVVersion + .docx + .pdf + .html)
    gen1 = client.post(
        "/api/resumes/generate-edition",
        headers=headers,
        json={"edition": "ats", "cv_language": "en"},
    )
    assert gen1.status_code == 200
    ver_id = gen1.json()["cv_version_id"]
    assert ver_id is not None

    # 3. Edit Profile Vault via PUT /api/ground-truth (new phone, headline, skill, language, education module)
    gt = client.get("/api/ground-truth", headers=headers).json()
    gt["candidate"]["phone"] = "+995 599 88 77 66"
    gt["candidate"]["headline"] = "Lead QA Automation Engineer (Playwright & FastAPI)"
    gt["candidate"]["languages"] = [
        {"language": "Georgian", "proficiency": "Native"},
        {"language": "English", "proficiency": "C1"},
        {"language": "French", "proficiency": "B1"},
    ]
    gt["skills"]["core"] = list(gt["skills"]["core"]) + ["Cypress E2E"]
    if gt.get("education"):
        gt["education"][0]["modules"] = list(gt["education"][0].get("modules") or []) + ["Economic Data Engineering"]

    save_res = client.put("/api/ground-truth", headers=headers, json=gt)
    assert save_res.status_code == 200
    assert save_res.json().get("synced_cv_versions", 0) >= 1

    # 4. Existing CVVersion + rendered Word (.docx) & HTML must reflect Profile edits immediately
    versions_res = client.get("/api/cv-versions", headers=headers)
    assert versions_res.status_code == 200
    versions = versions_res.json()["items"]
    matched = [v for v in versions if v["id"] == ver_id][0]
    assert matched["structured_json"]["candidate"]["phone"] == "+995 599 88 77 66"
    assert "Cypress E2E" in matched["structured_json"]["skills"]
    assert "French" in matched["structured_json"]["languages_line"]
    assert "+995 599 88 77 66" in matched["rendered_html"]
    assert "Cypress E2E" in matched["rendered_html"]
    assert "Lead QA Automation Engineer" in matched["rendered_html"]

    docx_path = GENERATED_RESUMES_DIR / matched["docx_filename"]
    assert docx_path.exists()
    docx_text = "\n".join(p.text for p in Document(str(docx_path)).paragraphs)
    assert "+995 599 88 77 66" in docx_text
    assert "Cypress E2E" in docx_text
    assert "French" in docx_text

    # 5. Brand-new CV generation after Profile edit must ALSO use updated Profile (not stale raw_markdown)
    gen2 = client.post(
        "/api/resumes/generate-edition",
        headers=headers,
        json={"edition": "recruiter", "cv_language": "en"},
    )
    assert gen2.status_code == 200
    docx2 = GENERATED_RESUMES_DIR / gen2.json()["docx_filename"]
    docx2_text = "\n".join(p.text for p in Document(str(docx2)).paragraphs)
    assert "+995 599 88 77 66" in docx2_text
    assert "Cypress E2E" in docx2_text
    assert "French" in docx2_text
