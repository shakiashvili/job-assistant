import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.db.database import engine, init_db
from app.db.models import User
from app.db.profile_repository import ground_truth_store
from app.services.auth_service import create_access_token, hash_password

client = TestClient(app)


def _create_isolated_user(prefix: str):
    init_db()
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    with Session(engine) as session:
        user = User(
            email=email,
            hashed_password=hash_password("TestPass123!"),
            full_name="Answer Tester",
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        uid = user.id
    token = create_access_token({"sub": email, "user_id": uid})
    return uid, email, {"Authorization": f"Bearer {token}"}


def test_generate_screening_answers_zero_fabrication_and_verified_grounding():
    uid, email, headers = _create_isolated_user("ans_iso")

    # 1. User uploads minimal skills WITHOUT salary, notice period, or EU visa claim
    client.post(
        "/api/profile/upload-skills",
        data={
            "content": "# Nino Gelashvili — Software QA Engineer\n## Core Skills\n- Playwright, Python, REST API",
            "run_live_scrape": "false",
        },
        headers=headers,
    )

    payload = {
        "questions": [
            {"id": "q1", "question": "What is your desired gross annual salary?", "field_type": "text"},
            {"id": "q2", "question": "What is your earliest start date or notice period?", "field_type": "text"},
            {"id": "q3", "question": "Are you legally authorized to work in Germany/EU without sponsorship?", "field_type": "select"},
            {"id": "q4", "question": "Applicant summary — introduce yourself briefly", "field_type": "textarea"},
        ],
        "job_title": "Junior QA Automation Engineer",
        "company": "MacPaw",
        "portal": "dou.ua",
    }

    res_unverified = client.post("/api/generate-answers", json=payload, headers=headers)
    assert res_unverified.status_code == 200
    d1 = res_unverified.json()
    assert len(d1["answers"]) == 4
    assert d1["default_start_date"] == ""
    assert "dou_motivational_letter" in d1
    assert "applicant_summary" in d1

    a1_map = {a["question"]: a for a in d1["answers"]}
    assert a1_map["What is your desired gross annual salary?"]["answer"] == ""
    assert a1_map["What is your desired gross annual salary?"]["verification_status"] == "REQUIRES_CONFIRMATION"
    assert a1_map["What is your earliest start date or notice period?"]["answer"] == ""
    assert a1_map["What is your earliest start date or notice period?"]["verification_status"] == "REQUIRES_CONFIRMATION"
    assert a1_map["Are you legally authorized to work in Germany/EU without sponsorship?"]["answer"] == ""
    assert a1_map["Are you legally authorized to work in Germany/EU without sponsorship?"]["verification_status"] == "REQUIRES_CONFIRMATION"
    assert "1 week after offer" not in a1_map["Applicant summary — introduce yourself briefly"]["answer"]

    # 2. User updates verified Ground Truth vault with explicit salary, notice period, and EU work permit
    gt = ground_truth_store.get_data(owner_email=email, user_id=uid)
    gt["candidate"]["compensation"]["expected_salary_eur"] = 42000
    gt["candidate"]["compensation"]["notice_period"] = "2 weeks notice"
    gt["candidate"]["work_authorization"]["eu_work_permit"] = True
    ground_truth_store.update_data(gt, owner_email=email, user_id=uid)

    res_verified = client.post("/api/generate-answers", json=payload, headers=headers)
    assert res_verified.status_code == 200
    d2 = res_verified.json()
    assert d2["default_start_date"] == "2 weeks notice"

    a2_map = {a["question"]: a for a in d2["answers"]}
    assert "42,000" in a2_map["What is your desired gross annual salary?"]["answer"]
    assert a2_map["What is your earliest start date or notice period?"]["answer"] == "2 weeks notice"
    assert "Yes" in a2_map["Are you legally authorized to work in Germany/EU without sponsorship?"]["answer"]
