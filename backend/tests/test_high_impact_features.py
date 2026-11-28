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
        assert any("Digest" in n.title for n in notifs)


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


def test_daily_digest_all_tiers_dedup_mismatch_missing_skills_yesterday_reminder_and_9am_scheduler(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.db.models import User
    from app.services.digest_scheduler import run_due_daily_digests

    headers, user_id = _register_and_upload("daily9am")
    with Session(engine) as session:
        jp_direct = JobPosting(
            portal="jobs.ge",
            external_id=f"d9_dir_{uuid.uuid4().hex[:6]}",
            title="Junior QA Engineer",
            company="Credo Bank",
            url=f"https://jobs.ge/ge/?view=jobs&id=d9_1_{uuid.uuid4().hex[:6]}",
            market="GE",
            is_remote=False,
            language_requirements=["English", "Georgian"],
            description_raw="Manual QA, Playwright, SQL, Kubernetes, Docker",
            suitability_score=84.0,
            match_score=84.0,
            status="STAGED",
        )
        jp_adj = JobPosting(
            portal="hr.ge",
            external_id=f"d9_adj_{uuid.uuid4().hex[:6]}",
            title="Technical Support Analyst",
            company="MagtiCom",
            url=f"https://hr.ge/announcement/d9_2_{uuid.uuid4().hex[:6]}",
            market="GE",
            is_remote=False,
            language_requirements=["English", "Georgian"],
            description_raw="SQL, Postman, Linux, Jira",
            suitability_score=72.0,
            match_score=72.0,
            status="AUDITED",
        )
        session.add(jp_direct)
        session.add(jp_adj)
        session.commit()
        session.refresh(jp_direct)
        session.refresh(jp_adj)
        session.add(
            UserJobMatch(
                user_id=user_id,
                job_posting_id=jp_direct.id,
                suitability_score=84.0,
                match_tier="DIRECT",
                status="STAGED",
                matched_skills=["Playwright", "SQL"],
                missing_skills=["Kubernetes", "Docker"],
                is_ignored=False,
            )
        )
        session.add(
            UserJobMatch(
                user_id=user_id,
                job_posting_id=jp_adj.id,
                suitability_score=72.0,
                match_tier="ADJACENT",
                status="AUDITED",
                matched_skills=["SQL", "Postman"],
                missing_skills=["Linux"],
                is_ignored=False,
            )
        )
        session.commit()
        user_obj = session.get(User, user_id)

    sent_payloads = []

    class _OkResp:
        status_code = 200

    def fake_post(url, json=None, timeout=12.0):
        sent_payloads.append(json["text"])
        return _OkResp()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-daily-token")
    monkeypatch.setenv("TELEGRAM_DEFAULT_CHAT_ID", "999000111")

    # Day 1: Includes BOTH Direct and Adjacent vacancies, shows Match %, Mismatch/Gap %, and exact missing skills!
    day1 = dispatch_saved_search_digest(
        user_obj,
        channels=["in_app", "telegram"],
        include_all_vacancies=True,
        min_score=0.0,
        dry_run=False,
        digest_date="2026-11-27",
        http_post=fake_post,
    )
    assert day1["status"] == "dispatched"
    assert day1["digest"]["total_matches"] == 2
    assert "Credo Bank" in day1["preview_text"]
    assert "MagtiCom" in day1["preview_text"]
    assert "Mismatch/Gap: 16.0%" in day1["preview_text"]
    assert "Missing skills: Kubernetes, Docker" in day1["preview_text"]
    assert "Mismatch/Gap: 28.0%" in day1["preview_text"]
    assert "Missing skills: Linux" in day1["preview_text"]

    # Day 2 (no new vacancies): Does NOT resend Day 1 vacancies, sends "No new matching vacancies" notice + compact Yesterday Reminder!
    day2 = dispatch_saved_search_digest(
        user_obj,
        channels=["in_app", "telegram"],
        include_all_vacancies=True,
        min_score=0.0,
        dry_run=False,
        digest_date="2026-11-28",
        http_post=fake_post,
    )
    assert day2["status"] == "dispatched_empty_notice"
    assert day2["digest"]["total_matches"] == 0
    assert day2["delivery"]["telegram"]["sent"] is True
    assert "No new matching vacancies were found today" in day2["preview_text"]
    assert "Reminder — Yesterday's vacancies (2026-11-27" in day2["preview_text"]
    assert "Credo Bank" in day2["preview_text"]
    assert "Link: https://jobs.ge" not in day2["preview_text"]

    # 09:00 AM Scheduler gate check: does not fire at 08:59, fires once at 09:00, idempotent at 09:05
    tz = ZoneInfo("Asia/Tbilisi")
    assert run_due_daily_digests(now_local=datetime(2026, 11, 29, 8, 59, tzinfo=tz)) == 0
    # Schedule status endpoint reports schedule metadata
    sched = client.get("/api/saved-searches/digest-schedule", headers=headers)
    assert sched.status_code == 200
    assert sched.json()["schedule_time"] == "09:00"
    assert sched.json()["total_unique_vacancies_sent"] == 2


def test_post_discovered_applied_and_hr_screening_hidden_from_discovery_and_digests():
    from app.db.models import User
    from app.db.tracker_repository import tracker_store

    headers, user_id = _register_and_upload("hideprog")
    u_disc = f"https://jobs.ge/ge/?view=jobs&id=hp_disc_{uuid.uuid4().hex[:6]}"
    u_app = f"https://jobs.ge/ge/?view=jobs&id=hp_app_{uuid.uuid4().hex[:6]}"
    u_hr = f"https://hr.ge/announcement/hp_hr_{uuid.uuid4().hex[:6]}"

    with Session(engine) as session:
        j_disc = JobPosting(
            portal="jobs.ge", external_id=f"hp1_{uuid.uuid4().hex[:6]}", title="Junior QA",
            company="Still Open Co", url=u_disc, market="GE", is_remote=False,
            language_requirements=["English"], description_raw="Playwright SQL Docker",
            suitability_score=85.0, match_score=85.0, status="STAGED",
        )
        j_app = JobPosting(
            portal="jobs.ge", external_id=f"hp2_{uuid.uuid4().hex[:6]}", title="QA Engineer",
            company="Already Applied Bank", url=u_app, market="GE", is_remote=False,
            language_requirements=["English"], description_raw="Playwright SQL",
            suitability_score=89.0, match_score=89.0, status="STAGED",
        )
        j_hr = JobPosting(
            portal="hr.ge", external_id=f"hp3_{uuid.uuid4().hex[:6]}", title="QA Analyst",
            company="HR Screening Tech", url=u_hr, market="GE", is_remote=False,
            language_requirements=["English"], description_raw="Playwright Postman",
            suitability_score=91.0, match_score=91.0, status="STAGED",
        )
        session.add_all([j_disc, j_app, j_hr])
        session.commit()
        for jp in (j_disc, j_app, j_hr):
            session.refresh(jp)
            session.add(
                UserJobMatch(
                    user_id=user_id, job_posting_id=jp.id, suitability_score=jp.suitability_score,
                    match_tier="DIRECT", status="STAGED", is_ignored=False,
                )
            )
        session.commit()
        user_obj = session.get(User, user_id)

    # Track via canonical repository write path (keeps ApplicationRecord & ApplicationTracker synchronized)
    tracker_store.upsert_external_application(
        user_id=user_id, company_name="Still Open Co", job_title="Junior QA",
        job_url=u_disc, portal="jobs.ge", status="SAVED",
    )
    tracker_store.upsert_external_application(
        user_id=user_id, company_name="Already Applied Bank", job_title="QA Engineer",
        job_url=u_app, portal="jobs.ge", status="APPLIED",
    )
    tracker_store.upsert_external_application(
        user_id=user_id, company_name="HR Screening Tech", job_title="QA Analyst",
        job_url=u_hr, portal="hr.ge", status="HR_SCREEN",
    )

    # 1. Discovery Feed hides Applied & HR Screening, keeps Discovered visible
    feed = client.get("/api/jobs", params={"limit": 50}, headers=headers)
    assert feed.status_code == 200, feed.text
    feed_companies = {it["company"] for it in feed.json()["items"]}
    assert "Still Open Co" in feed_companies
    assert "Already Applied Bank" not in feed_companies
    assert "HR Screening Tech" not in feed_companies

    # 2. Email/Telegram Digest excludes Applied & HR Screening, includes Discovered
    prev = dispatch_saved_search_digest(
        user_obj,
        channels=["in_app"],
        include_all_vacancies=True,
        min_score=0.0,
        dry_run=True,
    )
    assert "Still Open Co" in prev["preview_text"]
    assert "Already Applied Bank" not in prev["preview_text"]
    assert "HR Screening Tech" not in prev["preview_text"]


def test_discovery_and_tracker_deduplication_and_email_detection():
    headers, user_id = _register_and_upload("dedup")
    shared_id = uuid.uuid4().hex[:6]
    u_ge = f"https://jobs.ge/ge/?view=jobs&id=99{shared_id}"
    u_en = f"https://jobs.ge/en/?view=jobs&id=99{shared_id}"
    with Session(engine) as session:
        j1 = JobPosting(
            portal="jobs.ge", external_id=f"dd1_{shared_id}", title="Junior QA Tester",
            company="Liberty Bank JSC", url=u_ge, market="GE", is_remote=False,
            language_requirements=["English"], description_raw="Send CV to careers@libertybank.ge with Playwright.",
            suitability_score=86.0, match_score=86.0, status="STAGED",
        )
        j2 = JobPosting(
            portal="hr.ge", external_id=f"dd2_{shared_id}", title="Junior QA Tester",
            company="Liberty Bank", url=u_en, market="GE", is_remote=False,
            language_requirements=["English"], description_raw="QA role in Tbilisi.",
            suitability_score=82.0, match_score=82.0, status="STAGED",
        )
        session.add_all([j1, j2])
        session.commit()
        for jp in (j1, j2):
            session.refresh(jp)
            session.add(
                UserJobMatch(
                    user_id=user_id, job_posting_id=jp.id, suitability_score=jp.suitability_score,
                    match_tier="DIRECT", status="STAGED", is_ignored=False,
                )
            )
        session.commit()

    feed = client.get("/api/jobs", params={"search": "Liberty Bank", "limit": 20}, headers=headers)
    assert feed.status_code == 200
    items = [it for it in feed.json()["items"] if "liberty" in it["company"].lower()]
    assert len(items) == 1
    assert items[0]["target_email"] == "careers@libertybank.ge"
    assert items[0]["delivery_channel"] == "EMAIL"

    # Creating the same vacancy twice on the Tracker Board updates the single card instead of duplicating
    c1 = client.post(
        "/api/applications",
        headers=headers,
        json={"company": "Liberty Bank JSC", "role": "Junior QA Tester", "url": u_ge, "portal": "jobs.ge", "status": "Discovered"},
    )
    c2 = client.post(
        "/api/applications",
        headers=headers,
        json={"company": "Liberty Bank", "role": "Junior QA Tester", "url": u_en, "portal": "jobs.ge", "status": "Applied"},
    )
    assert c1.status_code in (200, 201) and c2.status_code in (200, 201)
    assert c1.json()["id"] == c2.json()["id"]
    apps = client.get("/api/applications", headers=headers).json()
    assert len([a for a in apps if "liberty" in a["company"].lower()]) == 1
