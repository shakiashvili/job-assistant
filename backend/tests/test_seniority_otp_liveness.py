import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlmodel import Session, select, create_engine

from app.main import app
from app.db.database import init_db, engine
from app.db.models import User, UserOTP, CandidateProfile, JobPosting
from app.services.matcher_service import matcher_service
from app.services.profile_service import profile_service
from app.services.link_validator import parse_vacancy_deadline, verify_vacancy_liveness

client = TestClient(app)


def test_passwordless_otp_flow():
    init_db()
    email = "giorgi.test.otp@talentflow.ai"

    # 1. Send OTP
    send_res = client.post("/api/auth/send-otp", json={"email": email})
    assert send_res.status_code == 200
    data = send_res.json()
    assert data["status"] == "ok"
    assert "demo_code" in data
    code = data["demo_code"]
    assert len(code) == 6

    # 2. Check DB record
    with Session(engine) as session:
        otp_rec = session.exec(
            select(UserOTP).where((UserOTP.email == email) & (UserOTP.otp_code == code))
        ).first()
        assert otp_rec is not None
        assert otp_rec.is_used is False
        assert otp_rec.expires_at > datetime.now(timezone.utc)

    # 3. Verify with wrong code -> Fail
    fail_res = client.post("/api/auth/verify-otp", json={"email": email, "otp_code": "000000"})
    assert fail_res.status_code == 400

    # 4. Verify with correct code -> Success & JWT issued
    verify_res = client.post("/api/auth/verify-otp", json={"email": email, "otp_code": code})
    assert verify_res.status_code == 200
    auth_data = verify_res.json()
    assert "access_token" in auth_data
    assert auth_data["token_type"] == "bearer"
    assert auth_data["user"]["email"] == email

    # 5. Verify OTP code cannot be re-used
    reuse_res = client.post("/api/auth/verify-otp", json={"email": email, "otp_code": code})
    assert reuse_res.status_code == 400


def test_candidate_profile_extraction_domain_agnostic():
    skills_md = """# KLIPY Sticker Search API — QA Case Study

**Portfolio project for a QA Engineer application**  
**Author:** Giorgi Shakiashvili  
**Status:** Test-design starter

## Objective
Demonstrate a structured QA approach to a REST API.

## Tools
- Postman for request execution and response assertions
- Playwright, Python, PyTest, Git
"""
    profile = profile_service.extract_structured_profile(skills_md)
    assert profile.full_name == "Giorgi Shakiashvili"
    assert profile.experience_years <= 2.0
    assert profile.seniority_level == "JUNIOR"
    assert profile.target_industry == "qa_tech"
    assert "Lead" not in profile.headline
    assert "Senior" not in profile.headline


def test_seniority_gate_disqualification():
    parsed = {
        "years_of_experience": 1.5,
        "seniority_level": "JUNIOR",
        "all_skills": ["Playwright", "Python", "PyTest", "Postman", "REST API", "Docker"],
    }

    # 1. Senior role must be disqualified by Seniority Gate
    score, status, rationale, _, _ = matcher_service.evaluate_job(
        title="Senior QA Automation Engineer (Playwright / Python)",
        description="Requires 5+ years of experience with Python and Playwright.",
        parsed_skills=parsed,
    )
    assert status == "FILTERED_OUT"
    assert "Seniority Gate" in rationale or "Experience Gate" in rationale

    # 2. Lead role must be disqualified
    score, status, rationale, _, _ = matcher_service.evaluate_job(
        title="Lead SDET / Principal Test Architect",
        description="Lead our QA division. Minimum 7 years experience.",
        parsed_skills=parsed,
    )
    assert status == "FILTERED_OUT"
    assert "Seniority Gate" in rationale

    # 3. Junior-to-Mid role matching 1.5 years experience must be promoted to STAGED
    score, status, rationale, matched, missing = matcher_service.evaluate_job(
        title="QA Automation Engineer (Playwright / Python)",
        description="Looking for QA Automation Engineer. Requirements: Playwright, Python, Postman. 1-2 years experience.",
        parsed_skills=parsed,
    )
    assert status == "STAGED"
    assert score >= 75.0


def test_link_validator_and_deadline_expiration():
    # 1. Past deadline -> Expired
    text_past = "Requirements: Python, Playwright. ბოლო ვადა: 15.01.2023. Send CV to jobs@company.ge"
    dl_date, dl_str, is_expired = parse_vacancy_deadline(text_past)
    assert dl_str == "15.01.2023"
    assert is_expired is True

    # 2. Future deadline -> Active
    text_future = "Requirements: Python, Playwright. ბოლო ვადა: 28.12.2026. Send CV to jobs@company.ge"
    dl_date, dl_str, is_expired = parse_vacancy_deadline(text_future)
    assert dl_str == "28.12.2026"
    assert is_expired is False

    # 3. English deadline format
    text_en = "Apply before: 2026-11-30. Seniority: Mid-level."
    dl_date, dl_str, is_expired = parse_vacancy_deadline(text_en)
    assert dl_str == "2026-11-30"
    assert is_expired is False


@pytest.mark.asyncio
async def test_link_liveness_verifier():
    # Local mock URLs are instantly live
    live = await verify_vacancy_liveness("http://localhost:8000/mock-portals/dou_sample.html")
    assert live is True

    # Dummy fake domains return False
    not_live = await verify_vacancy_liveness("https://example.com/not-a-real-job-url")
    assert not_live is False
