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
