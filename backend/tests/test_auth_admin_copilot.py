import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.db.database import engine, init_db
from app.db.models import User, ApplicationTracker, SkillActionPlan, InterviewRound
from app.services.auth_service import hash_password, create_access_token, get_user_by_email

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_auth_registration_and_login_flow():
    test_email = "jane.sdet@talentflow.local"
    test_password = "SecurePassword123!"

    # 1. Register
    reg_res = client.post("/api/auth/register", json={
        "email": test_email,
        "password": test_password,
        "full_name": "Jane Doe SDET"
    })
    # Could be 201 or 400 if already exists from repeated run
    if reg_res.status_code == 201:
        data = reg_res.json()
        assert "access_token" in data
        assert data["user"]["email"] == test_email
        assert data["user"]["is_admin"] is False
    else:
        assert reg_res.status_code == 400

    # 2. Login with valid password
    login_res = client.post("/api/auth/login", json={
        "email": test_email,
        "password": test_password
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    assert token

    # 3. /api/auth/me
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == test_email

    # 4. Login with invalid password
    bad_login = client.post("/api/auth/login", json={
        "email": test_email,
        "password": "WrongPassword!"
    })
    assert bad_login.status_code == 401


def test_admin_rbac_protection():
    # 1. Non-admin user attempts access to /api/admin/metrics -> 403 Forbidden
    user_token = create_access_token({"sub": "regular.user@talentflow.local", "is_admin": False})
    with Session(engine) as session:
        if not get_user_by_email(session, "regular.user@talentflow.local"):
            session.add(User(
                email="regular.user@talentflow.local",
                hashed_password=hash_password("Pass1234!"),
                is_admin=False
            ))
            session.commit()

    forbidden_res = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {user_token}"})
    assert forbidden_res.status_code == 403
    assert "Admin privileges required" in forbidden_res.json()["detail"]

    # 2. Admin user access -> 200 OK
    admin_token = create_access_token({"sub": "chief.admin@talentflow.local", "is_admin": True})
    with Session(engine) as session:
        admin_user = get_user_by_email(session, "chief.admin@talentflow.local")
        if not admin_user:
            admin_user = User(
                email="chief.admin@talentflow.local",
                hashed_password=hash_password("AdminPass123!"),
                is_admin=True,
                full_name="Chief Admin"
            )
            session.add(admin_user)
            session.commit()

    admin_res = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_res.status_code == 200
    metrics = admin_res.json()
    assert "total_users" in metrics
    assert "interview_conversion_rate" in metrics

    # 3. Admin user list
    users_res = client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert users_res.status_code == 200
    assert isinstance(users_res.json(), list)


def test_action_plans_and_milestone_completion():
    # 1. Generate action plans
    res = client.post("/api/profile/generate-action-plan")
    assert res.status_code == 200
    plans = res.json()
    assert len(plans) >= 1
    first_plan = plans[0]
    plan_id = first_plan["id"]
    assert "skill_name" in first_plan
    assert len(first_plan["milestones"]) >= 1

    # 2. Toggle first milestone
    patch_res = client.patch(f"/api/action-plans/{plan_id}/milestones/0")
    assert patch_res.status_code == 200
    updated = patch_res.json()
    initial_state = first_plan["milestones"][0]["completed"]
    assert updated["milestones"][0]["completed"] != initial_state


def test_gmail_dispatch_and_mime_assembly():
    # 1. Google login link
    login_link = client.get("/api/auth/google/login")
    assert login_link.status_code == 200
    assert "authorization_url" in login_link.json()

    # 2. Create sample application
    create_res = client.post("/api/applications", json={
        "company": "AutoQA Global Systems",
        "role": "Staff SDET Architect",
        "status": "Saved",
        "match_score": 92
    })
    assert create_res.status_code == 200
    app_data = create_res.json()
    app_id = app_data["id"]

    # 3. Prepare email draft
    email_res = client.post(f"/api/applications/{app_id}/send-email", json={
        "mode": "draft",
        "recipient_email": "talent@autoqa-global.com",
        "subject": "Application for QA Automation Engineer - Giorgi Shakiashvili",
        "body_text": "Attached is my tailored CV for the Staff SDET role."
    })
    assert email_res.status_code == 200
    data = email_res.json()
    assert data["status"] == "success"
    assert data["mode"] == "draft"
    assert data["recipient"] == "talent@autoqa-global.com"


def test_interview_preparation_copilot():
    # 1. Get or create application
    apps = client.get("/api/applications").json()
    app_id = apps[0]["id"] if apps else "app-1"

    # 2. Prepare interview for Technical round
    prep_res = client.post(f"/api/applications/{app_id}/prepare-interview", json={
        "round_type": "TECH_INTERVIEW"
    })
    assert prep_res.status_code == 200
    data = prep_res.json()
    assert "company_intel" in data
    assert len(data["predicted_questions"]) == 10

    first_q = data["predicted_questions"][0]
    assert "question" in first_q
    assert "star_strategy" in first_q
    assert "situation" in first_q["star_strategy"]
    assert "action" in first_q["star_strategy"]
    assert "result" in first_q["star_strategy"]

    # 3. Retrieve persistent interviews
    interviews_res = client.get(f"/api/applications/{app_id}/interviews")
    assert interviews_res.status_code == 200
    assert len(interviews_res.json()) >= 1
