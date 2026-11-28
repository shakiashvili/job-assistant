import pytest
from datetime import datetime, UTC
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.db.database import init_db, engine
from app.db.models import UserOTP, CandidateProfile
from app.services.crypto_service import blind_index
from app.services.matcher_service import matcher_service
from app.services.profile_service import profile_service
from app.services.link_validator import parse_vacancy_deadline, verify_vacancy_liveness

client = TestClient(app)


def test_passwordless_otp_flow():
    init_db()
    email = "otp.test.candidate@example.com"

    # 1. Send OTP
    send_res = client.post("/api/auth/send-otp", json={"email": email})
    assert send_res.status_code == 200
    data = send_res.json()
    assert data["status"] == "ok"
    assert "demo_code" not in data  # Security: never leak OTP code in HTTP response
    assert "delivered" in data and "smtp_configured" in data

    # 2. Check DB record via blind index & verify raw column ciphertext
    with Session(engine) as session:
        otp_rec = session.exec(
            select(UserOTP)
            .where((UserOTP.email_hash == blind_index(email)) & (UserOTP.is_used == False))
            .order_by(UserOTP.created_at.desc())
        ).first()
        assert otp_rec is not None
        assert otp_rec.is_used is False
        exp = otp_rec.expires_at if otp_rec.expires_at.tzinfo else otp_rec.expires_at.replace(tzinfo=UTC)
        assert exp > datetime.now(UTC)
        code = otp_rec.otp_code
        assert len(code) == 6

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
    assert profile.experience_years is None
    assert profile.experience_status == "internship_or_project"
    assert profile.max_allowed_years <= 2.0
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

    # 3. English deadline format (ISO and day-first/month-first named months)
    text_en = "Apply before: 2026-11-30. Seniority: Mid-level."
    dl_date, dl_str, is_expired = parse_vacancy_deadline(text_en)
    assert dl_str == "2026-11-30"
    assert is_expired is False

    dl_date, dl_str, is_expired = parse_vacancy_deadline("Apply before 15 January 2024")
    assert dl_date == datetime(2024, 1, 15, 23, 59, 59, tzinfo=UTC)
    assert dl_str == "15 January 2024"
    assert is_expired is True

    dl_date, dl_str, is_expired = parse_vacancy_deadline("Deadline: January 15, 2024")
    assert dl_date == datetime(2024, 1, 15, 23, 59, 59, tzinfo=UTC)
    assert is_expired is True

    dl_date, dl_str, is_expired = parse_vacancy_deadline("ბოლო ვადა: 15 იანვარი 2024")
    assert dl_date == datetime(2024, 1, 15, 23, 59, 59, tzinfo=UTC)
    assert is_expired is True

    dl_date, dl_str, is_expired = parse_vacancy_deadline("Closing date: 30 Dec 2027")
    assert dl_date == datetime(2027, 12, 30, 23, 59, 59, tzinfo=UTC)
    assert is_expired is False

    assert parse_vacancy_deadline("Published on 15 January 2024") == (None, None, False)


@pytest.mark.asyncio
async def test_link_liveness_verifier(monkeypatch):
    import socket
    import httpx
    from app.services import link_validator

    # HIGH-03: Loopback / localhost URLs must NEVER bypass SSRF checks
    loopback = await verify_vacancy_liveness("http://localhost:8000/api/health")
    assert loopback is False

    # Dummy fake domains return False
    not_live = await verify_vacancy_liveness("https://example.com/not-a-real-job-url")
    assert not_live is False

    # Valid external URL with live HTML passes, while open-redirect to metadata IP is blocked
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )

    valid_html = (
        "<html><body><table class='dtable'>"
        "<tr><td>დასახელება: QA Automation Engineer</td></tr>"
        "<tr><td>მომწოდებელი: Acme Corp Georgia</td></tr>"
        "<tr><td>Detailed requirements include Python, Playwright, pytest, REST API testing, CI/CD pipelines and Agile QA workflows.</td></tr>"
        "</table></body></html>"
    )

    def _mock_handler(request: httpx.Request) -> httpx.Response:
        if "redirect-ssrf" in str(request.url):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(200, text=valid_html)

    transport = httpx.MockTransport(_mock_handler)
    orig_client_cls = link_validator.httpx.AsyncClient
    monkeypatch.setattr(
        link_validator.httpx,
        "AsyncClient",
        lambda **kw: orig_client_cls(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}),
    )

    assert await verify_vacancy_liveness("https://jobs.ge/en/?view=jobs&id=549201") is True
    assert await verify_vacancy_liveness("https://jobs.ge/redirect-ssrf") is False


def test_pii_encryption_at_rest():
    """Verifies User, UserOTP, and CandidateProfile store Fernet ciphertext in raw SQLite columns."""
    import uuid
    from sqlalchemy import text

    init_db()
    tag = uuid.uuid4().hex[:8]
    reg_email = f"enc.user.{tag}@example.com"
    reg_res = client.post("/api/auth/register", json={
        "email": reg_email,
        "password": "StrongPassword123!",
        "full_name": "Encrypted Test User",
    })
    assert reg_res.status_code == 201

    otp_email = f"enc.otp.{tag}@example.com"
    client.post("/api/auth/send-otp", json={"email": otp_email})

    with engine.connect() as conn:
        raw_user = conn.execute(
            text("SELECT email, full_name, email_hash FROM users WHERE email_hash = :h"),
            {"h": blind_index(reg_email)},
        ).fetchone()
        assert raw_user is not None
        assert str(raw_user[0]).startswith("enc:")
        assert reg_email not in str(raw_user[0])
        assert str(raw_user[1]).startswith("enc:")
        assert "Encrypted Test User" not in str(raw_user[1])
        assert raw_user[2] == blind_index(reg_email)

        raw_otps = conn.execute(
            text("SELECT email, otp_code, email_hash FROM user_otps WHERE email_hash = :h"),
            {"h": blind_index(otp_email)},
        ).fetchall()
        assert len(raw_otps) >= 1
        raw_email, raw_code, row_hash = raw_otps[-1]
        assert str(raw_email).startswith("enc:")
        assert otp_email not in str(raw_email)
        assert str(raw_code).startswith("enc:")
        assert row_hash == blind_index(otp_email)

    with Session(engine) as session:
        prof = session.exec(select(CandidateProfile)).first()
        if not prof:
            prof = CandidateProfile(
                raw_markdown="# Secret Profile\nEmail: hidden@example.com",
                full_name="Hidden Candidate",
                email="hidden@example.com",
            )
            session.add(prof)
            session.commit()
            session.refresh(prof)
        raw_prof = session.connection().execute(
            text("SELECT email, full_name, raw_markdown FROM candidate_profiles WHERE id = :id"),
            {"id": prof.id},
        ).fetchone()
        assert str(raw_prof[0]).startswith("enc:")
        assert str(raw_prof[1]).startswith("enc:")
        assert str(raw_prof[2]).startswith("enc:")
