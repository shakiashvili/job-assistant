import sys
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure backend package is importable regardless of working directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402
from app.db.database import init_db  # noqa: E402
from app.services.audit_service import validate_safe_external_url  # noqa: E402
from app.services.auth_service import (  # noqa: E402
    create_access_token,
    hash_password,
    reset_login_attempts,
)
from app.db.models import User  # noqa: E402
from app.db.database import engine  # noqa: E402
from sqlmodel import Session  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_db():
    init_db()


def _create_user_headers(prefix: str, is_admin: bool = False):
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    with Session(engine) as session:
        user = User(
            email=email,
            hashed_password=hash_password("SecTestPass123!"),
            full_name=f"Sec {prefix}",
            is_active=True,
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        uid = user.id
    tok = create_access_token({"sub": email, "user_id": uid, "is_admin": is_admin})
    return uid, email, {"Authorization": f"Bearer {tok}"}


def test_sqli_payloads_on_login_and_jobs():
    """Verify SQL injection and LIKE wildcard payloads never bypass auth or leak SQL internals."""
    sqli_payloads = [
        "' OR 1=1 --",
        "admin' --",
        "1'; DROP TABLE job_postings; --",
        "' UNION SELECT 1, 'admin', 'hash' --",
        "%27%20OR%20%271%27=%271",
        "%%%%%_____\\\\\\",
        "' OR SLEEP(5) --",
    ]

    for idx, payload in enumerate(sqli_payloads):
        login_res = client.post(
            "/api/auth/login",
            json={"email": f"{payload}@sqli-test-{idx}.local", "password": payload},
        )
        assert login_res.status_code in (401, 422), (
            f"Unexpected status {login_res.status_code} for SQLi login payload: {payload}"
        )
        for leak in ("traceback", "sqlite", "sqlalchemy", "syntax error"):
            assert leak not in login_res.text.lower()

        jobs_res = client.get(
            "/api/jobs",
            params={
                "search": payload,
                "portal": payload,
                "technology": payload,
                "language": payload,
                "country": payload,
                "page": 1,
                "limit": 12,
            },
        )
        assert jobs_res.status_code == 200, (
            f"Unexpected status {jobs_res.status_code} on /api/jobs with SQLi search payload: {payload}"
        )
        body = jobs_res.json()
        assert "items" in body and isinstance(body["items"], list)


def test_protected_routes_reject_unauthenticated_or_tampered_tokens():
    """Verify RBAC & JWT boundaries on extension, admin, auth/me, and refresh endpoints."""
    assert client.get("/api/extension/profile").status_code == 401
    assert client.get("/api/admin/users").status_code in (401, 403)
    assert client.get("/api/admin/metrics").status_code in (401, 403)

    for bad_token in (
        "not.a.jwt",
        "Bearer.fake.token",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJoYWNrZXIifQ.invalidsig",
    ):
        headers = {"Authorization": f"Bearer {bad_token}"}
        assert client.get("/api/auth/me", headers=headers).status_code == 401
        assert client.get("/api/admin/users", headers=headers).status_code == 401


def test_refresh_token_rotation_and_type_isolation():
    """Verify 60m access + 14d refresh flow: refresh tokens cannot act as access tokens and vice versa."""
    unique_email = f"sec-refresh-{uuid.uuid4().hex[:8]}@example.com"
    password = "StrongSecurityPassword123!"

    reg = client.post(
        "/api/auth/register",
        json={"email": unique_email, "password": password, "full_name": "Security Audit User"},
    )
    assert reg.status_code == 201
    reg_data = reg.json()
    access_tok = reg_data["access_token"]
    refresh_tok = reg_data["refresh_token"]
    assert access_tok and refresh_tok

    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_tok}"}).status_code == 200
    assert client.get("/api/extension/profile", headers={"Authorization": f"Bearer {access_tok}"}).status_code == 200

    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh_tok}"}).status_code == 401
    assert client.get("/api/extension/profile", headers={"Authorization": f"Bearer {refresh_tok}"}).status_code == 401

    assert client.post("/api/auth/refresh", json={"refresh_token": access_tok}).status_code == 401

    ok_refresh = client.post("/api/auth/refresh", json={"refresh_token": refresh_tok})
    assert ok_refresh.status_code == 200
    assert ok_refresh.json()["user"]["email"] == unique_email


def test_brute_force_login_and_otp_rate_limit_lockout():
    """Verify rate-limiting locks out both password login and 6-digit OTP verification after 5 failures."""
    target_email = f"bruteforce-{uuid.uuid4().hex[:8]}@example.com"
    reset_login_attempts(target_email)
    reset_login_attempts(f"otp_verify:{target_email}")

    client.post(
        "/api/auth/register",
        json={"email": target_email, "password": "RealPassword999!", "full_name": "Rate Limit Target"},
    )

    for attempt in range(5):
        res = client.post(
            "/api/auth/login",
            json={"email": target_email, "password": f"WrongPass-{attempt}"},
        )
        assert res.status_code == 401

    locked = client.post(
        "/api/auth/login",
        json={"email": target_email, "password": "WrongPass-final"},
    )
    assert locked.status_code == 429

    # OTP guessing lockout
    client.post("/api/auth/send-otp", json={"email": target_email})
    for attempt in range(5):
        otp_res = client.post(
            "/api/auth/verify-otp",
            json={"email": target_email, "otp_code": f"00000{attempt}"},
        )
        assert otp_res.status_code == 400

    otp_locked = client.post(
        "/api/auth/verify-otp",
        json={"email": target_email, "otp_code": "999999"},
    )
    assert otp_locked.status_code == 429

    reset_login_attempts(target_email)
    reset_login_attempts(f"otp_verify:{target_email}")


def test_ssrf_url_validation_and_playwright_stage_blocks():
    """Verify internal, metadata, loopback, credentialed, and non-HTTP URLs are blocked in Audit & Stage."""
    malicious_urls = [
        "http://127.0.0.1:8000/api/health",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:8000/",
        "http://[::ffff:127.0.0.1]/",
        "http://10.0.0.1/internal",
        "http://192.168.1.1/router",
        "http://user:secret@example.com/",
        "javascript:alert(1)",
        "ftp://example.com/file",
    ]
    for url in malicious_urls:
        with pytest.raises(ValueError):
            validate_safe_external_url(url)

        stage_res = client.post(
            "/api/stage-application",
            json={"job_url": url, "variant": "qa_automation"},
        )
        assert stage_res.status_code == 400, f"Stage accepted SSRF URL: {url}"

        audit_res = client.post(
            "/api/audit-job",
            json={"job_url": url, "variant": "qa_automation"},
        )
        assert audit_res.status_code == 400, f"Audit accepted SSRF URL: {url}"


def test_path_traversal_blocked_and_security_headers_present():
    """Verify security headers exist and path traversal / invalid resume filenames are rejected."""
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.headers.get("X-Content-Type-Options") == "nosniff"
    assert health.headers.get("X-Frame-Options") == "DENY"
    assert health.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    for bad_name in [
        "..\\..\\.env",
        "../../backend/.env",
        "%2e%2e%2f.env",
        "secret.env",
        "evil.py",
    ]:
        r1 = client.get(f"/api/resumes/generated/{bad_name}")
        r2 = client.get(f"/api/resumes/{bad_name}")
        assert r1.status_code in (400, 404), f"Unexpected status {r1.status_code} for {bad_name}"
        assert r2.status_code in (400, 404), f"Unexpected status {r2.status_code} for {bad_name}"


def test_html_resume_preview_enforces_csp_and_production_blocks_guest_and_env_writes(monkeypatch):
    """Verify HTML CV previews enforce script-blocking CSP and production locks guest & SMTP .env writes."""
    import app.services.auth_service as auth_svc_mod
    import app.routers.auth as auth_router_mod

    # Generate a legitimate HTML preview and verify CSP header blocks inline scripts
    _, _, hdrs = _create_user_headers("csp_owner")
    gen = client.post(
        "/api/cv-editions/generate",
        headers=hdrs,
        json={"edition": "ats", "cv_language": "en", "target_role": "QA Engineer", "target_company": "CSPTest"},
    )
    if gen.status_code == 200 and gen.json().get("html_url"):
        html_res = client.get(gen.json()["html_url"], headers=hdrs)
        assert html_res.status_code == 200
        assert "default-src 'none'" in (html_res.headers.get("Content-Security-Policy") or "")
        assert html_res.headers.get("X-Content-Type-Options") == "nosniff"

    # Simulate production mode -> anonymous requests must return 401 and configure-smtp must return 403
    monkeypatch.setattr(auth_svc_mod, "IS_PRODUCTION", True)
    monkeypatch.setattr(auth_router_mod, "IS_PRODUCTION", True)

    assert client.get("/api/applications").status_code == 401
    assert client.get("/api/ground-truth").status_code == 401
    smtp_res = client.post(
        "/api/auth/configure-smtp",
        json={"gmail_user": "attacker@gmail.com", "gmail_app_password": "abcd efgh ijkl mnop"},
    )
    assert smtp_res.status_code == 403
