import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.db.database import engine, init_db
from app.db.models import User, JobPosting, UserJobMatch
from app.services.auth_service import (
    hash_password,
    create_access_token,
    create_oauth_state_token,
    decode_oauth_state_token,
    decode_refresh_token,
)
from app.services.scrapers.scraper_orchestrator import scraper_orchestrator

client = TestClient(app)


def _create_user(prefix: str, is_admin: bool = False) -> tuple[int, str, dict]:
    init_db()
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    with Session(engine) as session:
        user = User(
            email=email,
            hashed_password=hash_password("SecTestPass123!"),
            full_name=f"Test {prefix}",
            is_active=True,
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        uid = user.id
    token = create_access_token(data={"sub": email, "user_id": uid, "is_admin": is_admin})
    return uid, email, {"Authorization": f"Bearer {token}"}


def test_oauth_state_token_integrity_and_refresh_type_enforcement():
    state = create_oauth_state_token(user_id=42, email="oauth.user@example.com")
    decoded = decode_oauth_state_token(state)
    assert decoded is not None
    assert decoded["uid"] == 42
    assert decoded["sub"] == "oauth.user@example.com"

    # Tampered state must fail verification
    assert decode_oauth_state_token(state + "tamper") is None

    # Access token must NOT validate as a refresh token or oauth state
    access = create_access_token(data={"sub": "user@example.com", "user_id": 1})
    assert decode_refresh_token(access) is None
    assert decode_oauth_state_token(access) is None


def test_admin_backup_and_ai_metrics_rbac():
    _, _, user_headers = _create_user("regular_rbac", is_admin=False)
    _, _, admin_headers = _create_user("admin_rbac", is_admin=True)

    assert client.post("/api/admin/backup", headers=user_headers).status_code == 403
    assert client.get("/api/admin/backups", headers=user_headers).status_code == 403
    assert client.get("/api/admin/ai-metrics", headers=user_headers).status_code == 403

    ai_res = client.get("/api/admin/ai-metrics", headers=admin_headers)
    assert ai_res.status_code == 200
    ai_body = ai_res.json()
    assert "total_requests" in ai_body
    assert "cache_hit_rate" in ai_body
    assert "by_task" in ai_body

    backups_res = client.get("/api/admin/backups", headers=admin_headers)
    assert backups_res.status_code == 200
    assert "backups" in backups_res.json()


def test_rescore_existing_jobs_and_analytics_are_strictly_user_isolated():
    uid_a, email_a, headers_a = _create_user("iso_a")
    uid_b, email_b, headers_b = _create_user("iso_b")

    # Seed one shared JobPosting row directly to verify rescore preserves shared postings
    ext_id = f"shared-iso-{uuid.uuid4().hex[:8]}"
    with Session(engine) as session:
        job = JobPosting(
            portal="jobs.ge",
            external_id=ext_id,
            title="Junior Data Analyst (SQL / Python)",
            company="DataFlow Corp",
            url=f"https://jobs.ge/en/?view=jobs&id={ext_id}",
            market="GE",
            is_remote=True,
            language_requirements=["en"],
            description_raw="SQL, Python, BI dashboards, 1 year experience.",
            status="DISCOVERED",
            suitability_score=50.0,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    try:
        # User A uploads Data Analyst profile -> triggers rescore for User A ONLY
        res_a = client.post(
            "/api/profile/upload-skills",
            data={
                "content": "# Ana Data\n- Role: Junior Data Analyst\n- Experience: 1.5 years\n## Skills\n- SQL, Python, PowerBI, Excel",
                "run_live_scrape": "false",
            },
            headers=headers_a,
        )
        assert res_a.status_code == 200

        # User B uploads Chef / Culinary profile -> must NOT delete shared job or overwrite User A's UserJobMatch
        res_b = client.post(
            "/api/profile/upload-skills",
            data={
                "content": "# Giorgi Chef\n- Role: Pastry Chef\n- Experience: 1.0 years\n## Skills\n- Pastry, Baking, Menu Design",
                "run_live_scrape": "false",
            },
            headers=headers_b,
        )
        assert res_b.status_code == 200

        scraper_orchestrator.rescore_existing_jobs(owner_email=email_a, user_id=uid_a)
        scraper_orchestrator.rescore_existing_jobs(owner_email=email_b, user_id=uid_b)

        with Session(engine) as session:
            # Shared JobPosting row must still exist!
            still_exists = session.exec(select(JobPosting).where(JobPosting.id == job_id)).first()
            assert still_exists is not None

            match_a = session.exec(
                select(UserJobMatch).where(
                    (UserJobMatch.user_id == uid_a) & (UserJobMatch.job_posting_id == job_id)
                )
            ).first()
            match_b = session.exec(
                select(UserJobMatch).where(
                    (UserJobMatch.user_id == uid_b) & (UserJobMatch.job_posting_id == job_id)
                )
            ).first()
            assert match_a is not None and match_b is not None
            assert match_a.suitability_score > match_b.suitability_score

        # Candidate analytics endpoints reflect per-user isolation
        an_a = client.get("/api/analytics/candidate", headers=headers_a)
        an_b = client.get("/api/analytics/candidate", headers=headers_b)
        assert an_a.status_code == 200 and an_b.status_code == 200
        assert an_a.json()["profile_uploaded"] is True
        assert an_a.json()["matching_jobs_count"] >= an_b.json()["matching_jobs_count"]
    finally:
        with Session(engine) as session:
            for row in session.exec(select(UserJobMatch).where(UserJobMatch.job_posting_id == job_id)).all():
                session.delete(row)
            jp = session.exec(select(JobPosting).where(JobPosting.id == job_id)).first()
            if jp:
                session.delete(jp)
            session.commit()
