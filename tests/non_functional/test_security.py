import os
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
from app.services.auth_service import (  # noqa: E402
    create_access_token,
    create_refresh_token,
    reset_login_attempts,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_db():
    init_db()


def test_sqli_payloads_on_login_and_jobs():
    """Verify SQL injection payloads never bypass auth or trigger SQL 500 errors."""
    sqli_payloads = [
        "' OR 1=1 --",
        "admin' --",
        "1'; DROP TABLE jobposting; --",
        "' UNION SELECT 1, 'admin', 'hash' --",
        "%27%20OR%20%271%27=%271",
    ]

    for idx, payload in enumerate(sqli_payloads):
        login_res = client.post(
            "/api/auth/login",
            json={"email": f"{payload}@sqli-test-{idx}.local", "password": payload},
        )
        assert login_res.status_code in (401, 422), (
            f"Unexpected status {login_res.status_code} for SQLi login payload: {payload}"
        )
        assert "traceback" not in login_res.text.lower()
        assert "sqlite" not in login_res.text.lower()

        jobs_res = client.get("/api/jobs", params={"search": payload, "portal": payload, "page": 1, "limit": 12})
        assert jobs_res.status_code == 200, (
            f"Unexpected status {jobs_res.status_code} on /api/jobs with SQLi search payload: {payload}"
        )
        body = jobs_res.json()
        assert "items" in body and isinstance(body["items"], list)


def test_protected_routes_reject_unauthenticated_or_tampered_tokens():
    """Verify RBAC & JWT boundaries on extension, admin, auth/me, and refresh endpoints."""
    # Strict JWT-required extension route returns 401 without token
    ext_res = client.get("/api/extension/profile")
    assert ext_res.status_code == 401

    # Admin RBAC endpoints deny anonymous / non-admin callers
    assert client.get("/api/admin/users").status_code in (401, 403)
    assert client.get("/api/admin/metrics").status_code in (401, 403)

    # Malformed / forged Bearer tokens fail with 401 on /api/auth/me & /api/admin/users
    for bad_token in ("not.a.jwt", "Bearer.fake.token", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJoYWNrZXIifQ.invalidsig"):
        headers = {"Authorization": f"Bearer {bad_token}"}
        assert client.get("/api/auth/me", headers=headers).status_code == 401
        assert client.get("/api/admin/users", headers=headers).status_code == 401


def test_refresh_token_rotation_and_type_isolation():
    """Verify 60m access + 14d refresh flow: refresh tokens cannot act as access tokens and vice versa."""
    unique_email = f"sec-refresh-{uuid.uuid4().hex[:8]}@talentflow.local"
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

    # Access token must work on /api/auth/me and /api/extension/profile
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_tok}"}).status_code == 200
    assert client.get("/api/extension/profile", headers={"Authorization": f"Bearer {access_tok}"}).status_code == 200

    # Refresh token MUST NOT be accepted as an Access Bearer token
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh_tok}"}).status_code == 401
    assert client.get("/api/extension/profile", headers={"Authorization": f"Bearer {refresh_tok}"}).status_code == 401

    # Access token MUST NOT be accepted at /api/auth/refresh
    bad_refresh = client.post("/api/auth/refresh", json={"refresh_token": access_tok})
    assert bad_refresh.status_code == 401

    # Valid refresh token issues fresh access + refresh pair
    ok_refresh = client.post("/api/auth/refresh", json={"refresh_token": refresh_tok})
    assert ok_refresh.status_code == 200
    refreshed_data = ok_refresh.json()
    assert refreshed_data["access_token"]
    assert refreshed_data["refresh_token"]
    assert refreshed_data["user"]["email"] == unique_email


def test_brute_force_login_rate_limit_lockout():
    """Verify rate-limiting locks out an account after 5 consecutive failed password attempts."""
    target_email = f"bruteforce-{uuid.uuid4().hex[:8]}@talentflow.local"
    reset_login_attempts(target_email)

    client.post(
        "/api/auth/register",
        json={"email": target_email, "password": "RealPassword999!", "full_name": "Rate Limit Target"},
    )

    for attempt in range(5):
        res = client.post(
            "/api/auth/login",
            json={"email": target_email, "password": f"WrongPass-{attempt}"},
        )
        assert res.status_code == 401, f"Attempt {attempt + 1} should return 401, got {res.status_code}"

    # 6th attempt must be blocked with HTTP 429 Too Many Requests
    locked = client.post(
        "/api/auth/login",
        json={"email": target_email, "password": "WrongPass-final"},
    )
    assert locked.status_code == 429
    assert "too many" in locked.text.lower() or "lock" in locked.text.lower()
    reset_login_attempts(target_email)
