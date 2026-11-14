import uuid
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, select

from app.main import app
from app.db.database import engine, init_db
from app.db.models import (
    User,
    CandidateProfile,
    CandidateSkill,
    CandidateEducation,
    UserJobMatch,
)
from app.db.tracker_repository import tracker_store
from app.services.auth_service import hash_password, create_access_token
from app.services.crypto_service import encrypt_str, decrypt_str, rotate_encrypted_value
from app.services.backup_service import backup_service
from app.services.scrapers.scraper_orchestrator import scraper_orchestrator

client = TestClient(app)


def _create_authenticated_user(email_prefix: str, full_name: str) -> tuple[int, str, dict]:
    init_db()
    email = f"{email_prefix}_{uuid.uuid4().hex[:6]}@example.com"
    with Session(engine) as session:
        user = User(
            email=email,
            hashed_password=hash_password("TestPass123!"),
            full_name=full_name,
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        uid = user.id
    token = create_access_token(data={"sub": email, "user_id": uid})
    return uid, email, {"Authorization": f"Bearer {token}"}


def test_scenario_a_multi_user_profile_isolation_and_normalized_tables():
    """
    Scenario A: User A and User B have completely isolated CandidateProfiles,
    and uploading skills.md populates normalized CandidateSkill & CandidateEducation rows.
    """
    uid_a, email_a, headers_a = _create_authenticated_user("alice_qa", "Alice QA")
    uid_b, email_b, headers_b = _create_authenticated_user("bob_hosp", "Bob Hospitality")

    alice_md = """# Alice QA — QA Automation Engineer
- **Email:** alice@example.com
- **Experience:** 1.5 years

## Core Skills
- Playwright, Python, PyTest, REST API, SQL, Docker

## Education
- BSc in Computer Science | Tbilisi State University (2024)
"""
    res_a = client.post(
        "/api/profile/upload-skills",
        data={"content": alice_md, "run_live_scrape": "false"},
        headers=headers_a,
    )
    assert res_a.status_code == 200
    assert res_a.json()["profile_uploaded"] is True

    # User B has NOT uploaded a profile yet — must NOT see Alice's profile!
    res_b_initial = client.get("/api/profile", headers=headers_b)
    assert res_b_initial.status_code == 200
    b_data = res_b_initial.json()
    assert b_data["profile_uploaded"] is False
    assert "Alice" not in (b_data.get("full_name") or "")

    # User B uploads their own Hospitality profile
    bob_md = """# Bob Hospitality — Front Desk Receptionist
- **Email:** bob@example.com
- **Experience:** 2 years

## Core Skills
- Opera PMS, Fidelio, Guest Relations, Check-in / Check-out
"""
    res_b_up = client.post(
        "/api/profile/upload-skills",
        data={"content": bob_md, "run_live_scrape": "false"},
        headers=headers_b,
    )
    assert res_b_up.status_code == 200

    # Verify Alice's profile is still intact and isolated from Bob's
    res_a_check = client.get("/api/profile", headers=headers_a)
    assert res_a_check.status_code == 200
    assert "Playwright" in res_a_check.json()["raw_markdown"]
    assert "Opera PMS" not in res_a_check.json()["raw_markdown"]

    # Verify normalized CandidateSkill and CandidateEducation rows exist for Alice
    with Session(engine) as session:
        alice_skills = session.exec(
            select(CandidateSkill).where(CandidateSkill.user_id == uid_a)
        ).all()
        assert len(alice_skills) >= 3
        alice_edu = session.exec(
            select(CandidateEducation).where(CandidateEducation.user_id == uid_a)
        ).all()
        assert len(alice_edu) >= 1


def test_scenario_b_cross_user_anti_idor_protection():
    """
    Scenario B: User B cannot read, update, or delete User A's applications,
    action plans, saved searches, or uploaded CV files (returns 403 Forbidden).
    """
    uid_a, email_a, headers_a = _create_authenticated_user("owner_a", "Owner A")
    uid_b, email_b, headers_b = _create_authenticated_user("intruder_b", "Intruder B")

    # 1. User A creates an application with enriched tracker fields
    app_res = client.post(
        "/api/applications",
        json={
            "company": "PrivateCorp",
            "role": "QA Engineer",
            "portal": "jobs.ge",
            "url": f"https://jobs.ge/private-{uuid.uuid4().hex[:6]}",
            "status": "Applied",
            "recruiter_name": "Nino HR",
            "recruiter_email": "nino@privatecorp.ge",
            "follow_up_date": "2026-12-01",
            "salary_expected": "2500 USD",
        },
        headers=headers_a,
    )
    assert app_res.status_code == 200
    app_id = app_res.json()["id"]
    assert app_res.json()["recruiter_name"] == "Nino HR"

    # User B attempts to GET, PUT, and DELETE User A's application -> 403 Forbidden
    assert client.get(f"/api/applications/{app_id}", headers=headers_b).status_code == 403
    assert client.put(f"/api/applications/{app_id}", json={"status": "Rejected"}, headers=headers_b).status_code == 403
    assert client.delete(f"/api/applications/{app_id}", headers=headers_b).status_code == 403

    # 2. User A creates a SavedSearch; User B attempts to delete it -> 403 Forbidden
    ss_res = client.post(
        "/api/saved-searches",
        json={"name": "Remote Playwright", "filters": {"search": "Playwright"}, "notify_on_new": True},
        headers=headers_a,
    )
    assert ss_res.status_code == 200
    ss_id = ss_res.json()["id"]
    assert client.delete(f"/api/saved-searches/{ss_id}", headers=headers_b).status_code == 403

    # 3. User A generates Action Plans; User B attempts to toggle or delete User A's plan -> 403 Forbidden
    plans_res = client.post("/api/profile/generate-action-plan", headers=headers_a)
    assert plans_res.status_code == 200
    plan_id = plans_res.json()[0]["id"]
    assert client.patch(f"/api/action-plans/{plan_id}/milestones/0", headers=headers_b).status_code == 403
    assert client.delete(f"/api/action-plans/{plan_id}", headers=headers_b).status_code == 403

    # 4. User A uploads a personal PDF CV; User B attempts to download or delete it -> 403 Forbidden
    cv_name = f"alice_private_{uuid.uuid4().hex[:6]}.pdf"
    up_res = client.post(
        "/api/resumes/my-cvs/upload",
        files={"file": (cv_name, b"%PDF-1.4 Alice Private Resume Content", "application/pdf")},
        headers=headers_a,
    )
    assert up_res.status_code == 200
    assert client.get(f"/api/resumes/user/{cv_name}", headers=headers_b).status_code == 403
    assert client.delete(f"/api/resumes/my-cvs/{cv_name}", headers=headers_b).status_code == 403


def test_scenario_c_ssrf_and_upload_validation():
    """
    Scenario C: SSRF protection blocks loopback, RFC1918 private IPs, cloud metadata, and arbitrary file:// URLs.
    Upload validation blocks corrupt PDF headers and empty files.
    """
    _, _, headers = _create_authenticated_user("sec_tester", "Security Tester")

    unsafe_urls = [
        "http://127.0.0.1:8000/api/health",
        "http://localhost:8000/api/ground-truth",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/admin",
        "http://10.0.0.1/internal",
        "file:///etc/passwd",
    ]
    for bad_url in unsafe_urls:
        res = client.post("/api/audit-job", json={"job_url": bad_url}, headers=headers)
        assert res.status_code == 400, f"Expected 400 for SSRF URL {bad_url}, got {res.status_code}"
        assert "SSRF Protection" in res.json()["detail"]

    # Invalid PDF magic bytes rejected with 400
    bad_pdf = client.post(
        "/api/resumes/my-cvs/upload",
        files={"file": ("fake.pdf", b"NOT_A_VALID_PDF_HEADER", "application/pdf")},
        headers=headers,
    )
    assert bad_pdf.status_code == 400

    # Empty upload rejected with 400
    empty_md = client.post(
        "/api/skills-md/upload",
        files={"file": ("empty.md", b"", "text/markdown")},
        headers=headers,
    )
    assert empty_md.status_code == 400


def test_scenario_d_encryption_versioning_and_rotation():
    """
    Scenario D: Encryption uses versioned enc:v1: prefix and supports lossless key rotation.
    """
    secret = "candidate.secret@example.com"
    ct = encrypt_str(secret)
    assert ct.startswith("enc:v1:")
    assert decrypt_str(ct) == secret

    # Legacy enc: prefix (without v1:) still decrypts and rotates cleanly to enc:v1:
    legacy_ct = "enc:" + ct[len("enc:v1:"):]
    assert decrypt_str(legacy_ct) == secret
    rotated = rotate_encrypted_value(legacy_ct)
    assert rotated.startswith("enc:v1:")
    assert decrypt_str(rotated) == secret


def test_scenario_e_atomic_database_backup_and_integrity_check():
    """
    Scenario E: DatabaseBackupService creates an atomic SQLite snapshot with SHA-256 checksum
    and PRAGMA integrity_check verification.
    """
    meta = backup_service.create_backup(reason="pytest_verification")
    assert meta["integrity_check"] == "ok"
    assert len(meta["sha256"]) == 64
    assert meta["size_bytes"] > 0

    backups = backup_service.list_backups()
    assert any(b["filename"] == meta["filename"] for b in backups)


def test_scenario_f_query_count_optimizations():
    """
    Scenario F: Verifies N+1 query elimination on tracker_store.get_all(),
    single-query conditional aggregation on GET /api/jobs, and batch transaction in ingest_scraped_jobs().
    """
    uid, email, headers = _create_authenticated_user("perf_user", "Perf User")
    client.post(
        "/api/profile/upload-skills",
        data={
            "content": "# Perf User — QA Automation Engineer\n## Core Skills\n- Playwright, Python, PyTest, SQL, REST API",
            "run_live_scrape": "false",
        },
        headers=headers,
    )

    # 1. Batch ingest 10 jobs and count SQL statements
    sample_jobs = [
        {
            "portal": "djinni.co",
            "external_id": f"perf-batch-{i}-{uuid.uuid4().hex[:6]}",
            "title": f"QA Automation Engineer {i}",
            "company": f"TechCo {i}",
            "url": f"https://djinni.co/jobs/perf-{i}-{uuid.uuid4().hex[:6]}/",
            "description_raw": "Remote QA Automation Engineer with 1 year of Playwright, Python, PyTest, SQL, REST API.",
            "is_remote": True,
            "market": "GLOBAL_REMOTE",
        }
        for i in range(10)
    ]

    queries: list[str] = []

    def _count_sql(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", _count_sql)
    try:
        queries.clear()
        res = scraper_orchestrator.ingest_scraped_jobs(sample_jobs, owner_email=email, user_id=uid)
        ingest_query_count = len(queries)
        select_query_count = sum(1 for q in queries if q.strip().upper().startswith("SELECT"))
        assert res["total_processed"] == 10
        # Batch pre-fetch executes <= 5 SELECT queries total regardless of batch size (0 per-item SELECTs!)
        assert select_query_count <= 5, f"Expected <=5 SELECT queries for batch ingest, got {select_query_count}"
        assert ingest_query_count <= 36, f"Expected <=36 total statements for batch ingest, got {ingest_query_count}"

        # 2. Tracker get_all() must execute in 1 single JOIN query regardless of application count
        queries.clear()
        apps = tracker_store.get_all(user_id=uid, is_guest=False)
        tracker_query_count = len(queries)
        assert len(apps) >= 5
        assert tracker_query_count == 1, f"Expected 1 JOIN query in tracker_store.get_all(), got {tracker_query_count}"

        # 3. GET /api/jobs must execute in <= 4 queries (down from 10)
        queries.clear()
        jobs_resp = client.get("/api/jobs?page=1&limit=12", headers=headers)
        jobs_query_count = len(queries)
        assert jobs_resp.status_code == 200
        assert jobs_query_count <= 4, f"Expected <=4 queries for GET /api/jobs, got {jobs_query_count}"
    finally:
        event.remove(engine, "before_cursor_execute", _count_sql)


def test_scenario_g_saved_searches_notifications_analytics_export_and_interview_copilot():
    """
    Scenario G-I: Saved searches trigger notifications on new job ingestion;
    async scrape deduplicates and reports status; analytics & CSV export work;
    interview copilot returns grounded STAR strategies, glossary, follow-ups, and saves reflection notes.
    """
    uid, email, headers = _create_authenticated_user("journey_user", "Journey User")
    client.post(
        "/api/profile/upload-skills",
        data={
            "content": "# Journey User — QA Automation Engineer\n## Core Skills\n- Playwright, Cypress, Python, REST API, SQL",
            "run_live_scrape": "false",
        },
        headers=headers,
    )

    # Create a SavedSearch watching for "Playwright"
    ss = client.post(
        "/api/saved-searches",
        json={"name": "Playwright Alert", "filters": {"search": "Playwright"}, "notify_on_new": True},
        headers=headers,
    )
    assert ss.status_code == 200

    # Ingest a matching job -> should create UserJobMatch and Notification for this user
    scraper_orchestrator.ingest_scraped_jobs(
        [
            {
                "portal": "djinni.co",
                "external_id": f"notif-{uuid.uuid4().hex[:6]}",
                "title": "Junior QA Automation Engineer (Playwright)",
                "company": "AlertCo",
                "url": f"https://djinni.co/jobs/notif-{uuid.uuid4().hex[:6]}/",
                "description_raw": "Remote Junior QA Automation role using Playwright, Python, REST API, and SQL. 1 year experience.",
                "is_remote": True,
                "market": "GLOBAL_REMOTE",
            }
        ],
        owner_email=email,
        user_id=uid,
    )

    notifs = client.get("/api/notifications", headers=headers)
    assert notifs.status_code == 200
    notif_list = notifs.json()
    assert len(notif_list) >= 1
    nid = notif_list[0]["id"]
    mark_res = client.patch(f"/api/notifications/{nid}/read", headers=headers)
    assert mark_res.status_code == 200
    assert mark_res.json()["is_read"] is True

    # Async scrape endpoint & status polling
    async_res = client.post("/api/jobs/scrape/async", json={"allow_network": False}, headers=headers)
    assert async_res.status_code == 200
    task_id = async_res.json()["task_id"]
    st_res = client.get(f"/api/jobs/scrape/status/{task_id}", headers=headers)
    assert st_res.status_code == 200
    assert st_res.json()["status"] == "COMPLETED"

    # Analytics & CSV export
    an_res = client.get("/api/applications/analytics", headers=headers)
    assert an_res.status_code == 200
    assert "total_tracked" in an_res.json()
    assert "interview_conversion_rate_pct" in an_res.json()

    csv_res = client.get("/api/applications/export?format=csv", headers=headers)
    assert csv_res.status_code == 200
    assert "company,role,status" in csv_res.text

    # Interview Copilot & Reflection Note persistence
    apps = client.get("/api/applications", headers=headers).json()
    app_id = apps[0]["id"]
    prep_res = client.post(
        f"/api/applications/{app_id}/prepare-interview",
        json={"round_type": "TECH_INTERVIEW"},
        headers=headers,
    )
    assert prep_res.status_code == 200
    prep_data = prep_res.json()
    assert len(prep_data["predicted_questions"]) == 10
    assert len(prep_data["technical_glossary"]) >= 3
    assert len(prep_data["follow_up_questions"]) >= 3
    # Ensure no fabricated "85%" metric in heuristic STAR strategy
    assert "85%" not in str(prep_data["predicted_questions"])

    round_id = prep_data["round_id"]
    note_res = client.post(
        f"/api/applications/{app_id}/interviews/{round_id}/notes",
        json={
            "stage": "Technical Interview",
            "interviewer_names": "Lead QA",
            "questions_asked": ["How do you structure Playwright fixtures?"],
            "what_went_well": "Explained API schema checks clearly",
            "what_to_improve": "Deepen Docker networking examples",
        },
        headers=headers,
    )
    assert note_res.status_code == 200
    notes_list = client.get(f"/api/applications/{app_id}/interviews/{round_id}/notes", headers=headers)
    assert notes_list.status_code == 200
    assert len(notes_list.json()) >= 1
