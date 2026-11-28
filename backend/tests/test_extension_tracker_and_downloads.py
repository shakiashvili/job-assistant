import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.database import engine, init_db
from app.db.models import ApplicationTracker, User
from app.main import app

client = TestClient(app)


def _register_with_skills(prefix: str):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPassword123!", "full_name": "Giorgi Test"},
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    up = client.post(
        "/api/extension/upload-skills",
        headers=headers,
        json={
            "filename": "skills.md",
            "content": (
                "# Giorgi Test\n"
                "Headline: Junior QA Engineer\n"
                "1.0 years experience\n"
                "## Experience\n"
                "### QA Engineer Intern | EPAM Systems (2025 - Present)\n"
                "- Built Playwright UI tests and REST API validation suites in Postman and SQL.\n"
                "## Skills\n"
                "- Playwright, Python, SQL, REST API, Postman, Jira\n"
            ),
        },
    )
    assert up.status_code == 200, up.text
    return headers, email


def test_extension_prepare_downloads_pdf_and_docx_and_cleans_jobs_ge_placeholders():
    headers_a, _ = _register_with_skills("ext_dl_a")
    headers_b, _ = _register_with_skills("ext_dl_b")

    # Simulate jobs.ge page where naive DOM scraping passed "Jobs.GE" / "Jobs"
    prep = client.post(
        "/api/extension/prepare-application",
        headers=headers_a,
        json={
            "url": "https://jobs.ge/ge/?view=jobs&id=699123",
            "portal": "jobs.ge",
            "job_title": "Jobs.GE",
            "company_name": "Jobs",
            "job_description": (
                "დასახელება: ხარისხის უზრუნველყოფის სპეციალისტი (Junior QA)\n"
                "მომწოდებელი: ბანკი ქართუ\n"
                "მოთხოვნები: SQL, Postman, REST API, Playwright, Jira. გამოაგზავნეთ CV: cv@cartubank.ge\n"
            ),
            "cv_language": "en",
            "fields": [],
        },
    )
    assert prep.status_code == 200, prep.text
    body = prep.json()

    assert body["company_name"] == "ბანკი ქართუ"
    assert "Jobs.GE" not in body["job_title"]
    pdf_name = body["tailored_cv"]["pdf_filename"]
    docx_name = body["tailored_cv"]["docx_filename"]
    assert pdf_name and pdf_name.endswith(".pdf")
    assert docx_name and docx_name.endswith(".docx")
    assert "Jobs_Jobs_GE" not in pdf_name

    # Owner downloads BOTH PDF and Word (.docx) via extension endpoint with strict Bearer auth
    r_pdf = client.get(f"/api/extension/download-cv/{pdf_name}", headers=headers_a)
    assert r_pdf.status_code == 200, r_pdf.text
    assert r_pdf.content.startswith(b"%PDF")
    assert "attachment" in r_pdf.headers.get("content-disposition", "")

    r_docx = client.get(f"/api/extension/download-cv/{docx_name}", headers=headers_a)
    assert r_docx.status_code == 200, r_docx.text
    assert r_docx.content[:2] == b"PK"
    assert "attachment" in r_docx.headers.get("content-disposition", "")

    # Unauthenticated -> 401; different user -> 403
    assert client.get(f"/api/extension/download-cv/{pdf_name}").status_code == 401
    assert client.get(f"/api/extension/download-cv/{pdf_name}", headers=headers_b).status_code == 403


def test_extension_log_application_persists_to_kanban_tracker_and_reconciles_orphans():
    init_db()
    headers, _ = _register_with_skills("ext_trk")
    job_url = f"https://jobs.ge/ge/?view=jobs&id={uuid.uuid4().hex[:6]}"

    # 1. Mark as Applied via extension -> MUST appear immediately on GET /api/applications
    res_log = client.post(
        "/api/extension/log-application",
        headers=headers,
        json={
            "company_name": "Cartu Bank",
            "job_title": "Junior QA Specialist",
            "job_url": job_url,
            "portal": "jobs.ge",
            "salary_offered": "2500 GEL",
            "cv_pdf_path": "Sample_Tailored_CV.pdf",
            "cover_letter_text": "Dear Cartu Bank Hiring Team...",
            "status": "APPLIED",
        },
    )
    assert res_log.status_code == 200, res_log.text
    assert res_log.json()["status"] == "created"

    board = client.get("/api/applications", headers=headers)
    assert board.status_code == 200, board.text
    items = board.json()
    matched = [it for it in items if it["url"] == job_url]
    assert len(matched) == 1
    assert matched[0]["company"] == "Cartu Bank"
    assert matched[0]["role"] == "Junior QA Specialist"
    assert matched[0]["status"] == "Applied"
    assert matched[0]["cv_pdf_url"] == "/api/resumes/generated/Sample_Tailored_CV.pdf"

    # 2. Updating the same URL updates cleanly without duplicating
    res_upd = client.post(
        "/api/extension/log-application",
        headers=headers,
        json={
            "company_name": "Cartu Bank",
            "job_title": "Junior QA Specialist",
            "job_url": job_url,
            "portal": "jobs.ge",
            "status": "HR_SCREEN",
        },
    )
    assert res_upd.status_code == 200
    assert res_upd.json()["status"] == "updated"
    board2 = client.get("/api/applications", headers=headers).json()
    matched2 = [it for it in board2 if it["url"] == job_url]
    assert len(matched2) == 1
    assert matched2[0]["status"] == "HR Screening"

    # 3. Legacy orphaned ApplicationTracker row reconciles cleanly on startup without adding extra get_all() queries
    from app.db.tracker_repository import tracker_store

    me_id = client.get("/api/auth/me", headers=headers).json()["id"]
    orphan_url = f"https://jobs.ge/ge/?view=jobs&id=orphan_{uuid.uuid4().hex[:6]}"
    with Session(engine) as session:
        assert session.get(User, me_id) is not None
        session.add(
            ApplicationTracker(
                user_id=me_id,
                company_name="Legacy Bank",
                job_title="Legacy QA Role",
                job_url=orphan_url,
                portal="jobs.ge",
                status="APPLIED",
            )
        )
        session.commit()

    tracker_store.reconcile_all_orphaned_trackers()
    board3 = client.get("/api/applications", headers=headers).json()
    orphan_match = [it for it in board3 if it["url"] == orphan_url]
    assert len(orphan_match) == 1
    assert orphan_match[0]["status"] == "Applied"


def test_saved_jobs_endpoint_returns_200_instead_of_404():
    headers, _ = _register_with_skills("ext_saved")
    res = client.get("/api/jobs/saved", headers=headers)
    assert res.status_code == 200
    assert isinstance(res.json().get("items"), list)
