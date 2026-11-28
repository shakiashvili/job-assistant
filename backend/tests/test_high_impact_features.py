import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db.database import engine, init_db
from app.db.models import JobPosting, Notification, UserJobMatch
from app.main import app
from app.services.digest_service import dispatch_saved_search_digest
from app.services.gmail_sync_service import classify_employer_email

client = TestClient(app)


def _register_and_upload(prefix: str):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPassword123!", "full_name": "Nino FeatureTest"},
    )
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    up = client.post(
        "/api/extension/upload-skills",
        headers=headers,
        json={
            "filename": "skills.md",
            "content": (
                "# Nino FeatureTest\n"
                "Headline: Junior QA Engineer\n"
                "1.0 years experience\n"
                "## Experience\n"
                "### QA Engineer Intern | EPAM Systems (2025 - Present)\n"
                "- Automated REST API and Playwright UI regression tests.\n"
                "## Skills\n"
                "- Playwright, Python, SQL, REST API, Postman, Jira\n"
            ),
        },
    )
    assert up.status_code == 200, up.text
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]
    return headers, user_id


def test_feature1_and_2_extension_gmail_draft_and_duplicate_badge():
    headers, _ = _register_and_upload("feat12")
    job_url = f"https://jobs.ge/ge/?view=jobs&id={uuid.uuid4().hex[:6]}"

    # Before applying: check-url returns already_tracked=False
    chk0 = client.get("/api/extension/check-url", params={"url": job_url, "company": "Cartu Bank", "title": "Junior QA"}, headers=headers)
    assert chk0.status_code == 200
    assert chk0.json()["already_tracked"] is False

    # Prepare CV + verify match_explanation gates
    prep = client.post(
        "/api/extension/prepare-application",
        headers=headers,
        json={
            "url": job_url,
            "portal": "jobs.ge",
            "job_title": "Junior QA Engineer",
            "company_name": "Cartu Bank",
            "job_description": "Manual testing, Playwright, SQL, Postman, Kubernetes.",
            "cv_language": "en",
            "fields": [],
        },
    )
    assert prep.status_code == 200, prep.text
    prep_body = prep.json()
    assert len(prep_body["match_explanation"]) >= 3
    assert all("gate" in g and "passed" in g for g in prep_body["match_explanation"])

    # 1-Click Prepare Gmail Draft & auto-mark APPLIED on Kanban board
    gm = client.post(
        "/api/extension/prepare-gmail-draft",
        headers=headers,
        json={
            "recipient_email": "cv@cartubank.ge",
            "company_name": "Cartu Bank",
            "job_title": "Junior QA Engineer",
            "job_url": job_url,
            "portal": "jobs.ge",
            "cover_letter": prep_body["cover_letter"],
            "pdf_filename": prep_body["tailored_cv"]["pdf_filename"],
            "docx_filename": prep_body["tailored_cv"]["docx_filename"],
            "mark_applied": True,
        },
    )
    assert gm.status_code == 200, gm.text
    gm_data = gm.json()
    assert gm_data["recipient_email"] == "cv@cartubank.ge"
    assert "mail.google.com" in gm_data["gmail_compose_url"]
    assert gm_data["attached_filename"] == prep_body["tailored_cv"]["pdf_filename"]
    assert gm_data["tracker"]["status"] == "created"

    # Now check-url detects exact URL AND cross-portal same company+role duplicate!
    chk1 = client.get("/api/extension/check-url", params={"url": job_url}, headers=headers)
    assert chk1.status_code == 200
    assert chk1.json()["already_tracked"] is True
    assert chk1.json()["match_reason"] == "exact_url"
    assert chk1.json()["status"] == "Applied"

    chk2 = client.get(
        "/api/extension/check-url",
        params={"url": "https://hr.ge/announcement/99999", "company": "Cartu Bank", "title": "Junior QA Engineer"},
        headers=headers,
    )
    assert chk2.status_code == 200
    assert chk2.json()["already_tracked"] is True
    assert chk2.json()["match_reason"] == "same_company_and_role"


def test_feature3_add_single_missing_skill_to_action_plan():
    headers, _ = _register_and_upload("feat3")
    r1 = client.post(
        "/api/action-plans/add-skill",
        headers=headers,
        json={"skill_name": "Kubernetes", "target_role": "QA Automation Engineer"},
    )
    assert r1.status_code == 200, r1.text
    p1 = r1.json()
    assert p1["skill_name"] == "Kubernetes"
    assert p1["days_to_learn"] == 7
    assert len(p1["milestones"]) == 7

    # Idempotent: adding same skill again returns existing plan ID
    r2 = client.post(
        "/api/action-plans/add-skill",
        headers=headers,
        json={"skill_name": "kubernetes", "target_role": "QA Automation Engineer"},
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == p1["id"]


def test_feature4_gmail_reply_classifier_sync_approve_undo_and_followup_draft():
    headers, _ = _register_and_upload("feat4")

    # Bilingual reply classification unit checks
    assert classify_employer_email("Interview Invitation - TBC Bank")["suggested_status"] == "HR Screening"
    assert classify_employer_email("გასაუბრებაზე მოწვევა")["suggested_status"] == "HR Screening"
    assert classify_employer_email("Technical Assignment for QA")["suggested_status"] == "Assessment"
    assert classify_employer_email("Job Offer: Junior QA")["suggested_status"] == "Offer"
    assert classify_employer_email("Update", "Unfortunately we decided not to proceed")["suggested_status"] == "Rejected"

    # Create a tracked application
    created = client.post(
        "/api/applications",
        headers=headers,
        json={
            "company": "Payze",
            "role": "Junior QA Engineer",
            "portal": "jobs.ge",
            "url": f"https://jobs.ge/ge/?view=jobs&id={uuid.uuid4().hex[:6]}",
            "status": "Applied",
            "recruiter_email": "hr@payze.io",
        },
    )
    assert created.status_code == 200, created.text
    app_id = created.json()["id"]

    # Scan Gmail replies (injected messages for hermetic offline test) -> suggests stage move WITHOUT auto-mutating
    sync = client.post(
        "/api/applications/gmail/sync-suggestions",
        headers=headers,
        json={
            "messages": [
                {
                    "id": "m1",
                    "from": "Recruiting <hr@payze.io>",
                    "subject": "Technical Interview with Payze Engineering",
                    "snippet": "We would like to invite you to a technical interview next Tuesday.",
                }
            ]
        },
    )
    assert sync.status_code == 200, sync.text
    suggestions = sync.json()["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["application_id"] == app_id
    assert suggestions[0]["suggested_status"] == "Technical Interview"

    # Confirm board was NOT auto-mutated before user approval
    assert client.get(f"/api/applications/{app_id}", headers=headers).json()["status"] == "Applied"

    # User approves suggestion -> returns previous_status for Undo
    approved = client.post(
        f"/api/applications/{app_id}/apply-status-suggestion",
        headers=headers,
        json={"suggested_status": "Technical Interview", "reason": "Confirmed from Gmail"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["previous_status"] == "Applied"
    assert approved.json()["new_status"] == "Technical Interview"

    # Follow-up email draft (+5 days, EN and KA)
    fu_en = client.post(
        f"/api/applications/{app_id}/follow-up-draft",
        headers=headers,
        json={"days_since_applied": 5, "language": "en", "save_to_gmail": False},
    )
    assert fu_en.status_code == 200, fu_en.text
    assert "Payze" in fu_en.json()["body_text"]
    assert "mail.google.com" in fu_en.json()["gmail_compose_url"]

    fu_ka = client.post(
        f"/api/applications/{app_id}/follow-up-draft",
        headers=headers,
        json={"days_since_applied": 5, "language": "ka", "save_to_gmail": False},
    )
    assert fu_ka.status_code == 200
    assert "მოგესალმებით" in fu_ka.json()["body_text"]


def test_feature5_saved_search_digest_in_app_and_telegram_dispatch(monkeypatch):
    init_db()
    headers, user_id = _register_and_upload("feat5")

    # Create a saved search alert
    ss = client.post(
        "/api/saved-searches",
        headers=headers,
        json={"name": "Georgia QA Roles", "filters": {"portal": "jobs.ge", "min_score": 70}, "notify_on_new": True},
    )
    assert ss.status_code == 200, ss.text

    # Seed one high-match JobPosting + UserJobMatch
    with Session(engine) as session:
        jp = JobPosting(
            user_id=user_id,
            portal="jobs.ge",
            external_id=f"dig-{uuid.uuid4().hex[:6]}",
            title="Junior QA Engineer",
            company="TBC Tech",
            url=f"https://jobs.ge/ge/?view=jobs&id=dig_{uuid.uuid4().hex[:6]}",
            market="GE",
            is_remote=False,
            language_requirements=["English", "Georgian"],
            description_raw="Playwright SQL Postman",
            suitability_score=88.0,
            match_score=88.0,
            status="STAGED",
        )
        session.add(jp)
        session.commit()
        session.refresh(jp)
        session.add(
            UserJobMatch(
                user_id=user_id,
                job_posting_id=jp.id,
                suitability_score=88.0,
                match_tier="DIRECT",
                status="STAGED",
                is_ignored=False,
            )
        )
        session.commit()

    # Dry-run via API endpoint
    r_prev = client.post(
        "/api/saved-searches/send-digest",
        headers=headers,
        json={"channels": ["in_app", "email", "telegram"], "dry_run": True},
    )
    assert r_prev.status_code == 200, r_prev.text
    assert r_prev.json()["digest"]["total_matches"] >= 1
    assert "TBC Tech" in r_prev.json()["preview_text"]

    # Real in-app + mocked Telegram dispatch
    sent_calls = []

    class _FakeResp:
        status_code = 200

    def fake_post(url, json=None, timeout=10.0):
        sent_calls.append((url, json))
        return _FakeResp()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    with Session(engine) as session:
        from app.db.models import User
        user_obj = session.get(User, user_id)
    out = dispatch_saved_search_digest(
        user_obj,
        channels=["in_app", "telegram"],
        telegram_chat_id="123456789",
        dry_run=False,
        http_post=fake_post,
    )
    assert out["status"] == "dispatched"
    assert out["delivery"]["in_app"]["sent"] is True
    assert out["delivery"]["telegram"]["sent"] is True
    assert len(sent_calls) == 1
    assert "api.telegram.org/botfake-bot-token/sendMessage" in sent_calls[0][0]

    with Session(engine) as session:
        notifs = session.exec(select(Notification).where(Notification.user_id == user_id)).all()
        assert any("Saved-Search Digest" in n.title for n in notifs)


def test_discovery_feed_returns_explainable_gates_and_skill_gaps():
    headers, user_id = _register_and_upload("expl")
    with Session(engine) as session:
        jp = JobPosting(
            portal="jobs.ge",
            external_id=f"expl_{uuid.uuid4().hex[:6]}",
            title="Junior QA Automation Engineer",
            company="Bank of Georgia",
            url=f"https://jobs.ge/ge/?view=jobs&id=expl_{uuid.uuid4().hex[:6]}",
            market="GE",
            is_remote=False,
            language_requirements=["English", "Georgian"],
            description_raw="Looking for QA with Playwright, SQL, Postman, Docker and Kubernetes.",
            suitability_score=84.0,
            match_score=84.0,
            status="STAGED",
        )
        session.add(jp)
        session.commit()
        session.refresh(jp)
        session.add(
            UserJobMatch(
                user_id=user_id,
                job_posting_id=jp.id,
                suitability_score=84.0,
                match_tier="ADJACENT",
                status="STAGED",
                matched_skills=["Playwright", "SQL", "Postman"],
                missing_skills=["Kubernetes", "Docker"],
                is_ignored=False,
            )
        )
        session.commit()

    resp = client.get("/api/jobs", params={"portal": "jobs.ge", "limit": 20}, headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    hit = next((it for it in items if it["company"] == "Bank of Georgia"), None)
    assert hit is not None
    assert "Playwright" in hit["matched_skills"]
    assert "Kubernetes" in hit["missing_skills"]
    assert len(hit["match_explanation"]) >= 3
    assert {g["gate"] for g in hit["match_explanation"]} >= {"seniority_gate", "discipline_gate", "language_gate"}
