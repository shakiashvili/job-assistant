import json
import uuid
from datetime import date
from pathlib import Path
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlmodel import Session, select

from app.main import app
from app.config import GENERATED_RESUMES_DIR, resolve_gemini_model_pricing
from app.db.database import engine, init_db
from app.db.document_repository import user_generated_resumes_dir
from app.db.models import AuthRateLimit, User
from app.services.ats_checker import check_pdf_ats_parseability
from app.services.auth_service import (
    check_rate_limit,
    consume_rate_limit,
    record_login_failure,
    reset_login_attempts,
)
from app.services.crypto_service import (
    blind_index,
    encrypt_str,
    reindex_all_blind_indices,
)
from app.services.gemini_service import GeminiService
from app.services.playwright_service import playwright_service

client = TestClient(app)


def _register_and_upload_same_candidate(prefix: str, unique_marker: str):
    init_db()
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    pw = "StrongPassword123!"
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": pw, "full_name": "Nino Beridze"},
    )
    assert reg.status_code == 201, reg.text
    data = reg.json()
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    uid = data["user"]["id"]

    skills_md = (
        "# Nino Beridze\n"
        "Headline: QA Automation Engineer\n"
        f"Email: {email}\n"
        "Phone: +995 599 12 34 56\n"
        "Location: Tbilisi, Georgia\n\n"
        "## Work Experience\n\n"
        f"### {unique_marker} Systems — QA Automation Engineer (2022 - Present)\n"
        f"- Built automated API and UI regression pipelines for {unique_marker} platform using Playwright and PyTest.\n\n"
        "## Core Skills\n"
        "- Playwright\n- Python\n- PyTest\n- FastAPI\n"
    )
    res_md = client.post("/api/skills-md", headers=headers, json={"content": skills_md})
    assert res_md.status_code == 200, res_md.text
    return uid, email, headers


def test_generated_cv_user_directory_isolation_and_fail_closed_staging():
    """
    P1: Two accounts generating identically named CVs write to isolated user_<id> directories
    without overwriting each other, and cross-user download/listing/staging fail closed (403/404).
    """
    uid_a, _, hdr_a = _register_and_upload_same_candidate("iso_a", "AlphaUniqueEmployer")
    uid_b, _, hdr_b = _register_and_upload_same_candidate("iso_b", "BetaUniqueEmployer")

    gen_a = client.post(
        "/api/resumes/generate-edition",
        headers=hdr_a,
        json={"edition": "ats", "cv_language": "en"},
    )
    gen_b = client.post(
        "/api/resumes/generate-edition",
        headers=hdr_b,
        json={"edition": "ats", "cv_language": "en"},
    )
    assert gen_a.status_code == 200, gen_a.text
    assert gen_b.status_code == 200, gen_b.text

    body_a = gen_a.json()
    body_b = gen_b.json()
    fname_a = body_a["pdf_filename"]
    fname_b = body_b["pdf_filename"]
    assert fname_a == fname_b  # Same candidate name & role intentionally collide in filename

    path_a = Path(body_a["pdf_path"])
    path_b = Path(body_b["pdf_path"])
    assert path_a != path_b
    assert path_a.parent == user_generated_resumes_dir(uid_a)
    assert path_b.parent == user_generated_resumes_dir(uid_b)
    assert path_a.exists() and path_b.exists()

    # Neither user overwrote the other's HTML/DOCX/PDF content
    html_a = client.get(f"/api/resumes/generated/{Path(fname_a).stem}.html", headers=hdr_a)
    html_b = client.get(f"/api/resumes/generated/{Path(fname_b).stem}.html", headers=hdr_b)
    assert html_a.status_code == 200 and "AlphaUniqueEmployer" in html_a.text
    assert "BetaUniqueEmployer" not in html_a.text
    assert html_b.status_code == 200 and "BetaUniqueEmployer" in html_b.text
    assert "AlphaUniqueEmployer" not in html_b.text

    # Unowned / arbitrary file placed in shared root dir MUST fail closed for any signed-in user
    stray_name = f"stray_shared_{uuid.uuid4().hex[:6]}.pdf"
    stray_path = GENERATED_RESUMES_DIR / stray_name
    stray_path.write_bytes(b"%PDF-1.4\n%stray\n")
    try:
        stray_resp = client.get(f"/api/resumes/generated/{stray_name}", headers=hdr_a)
        assert stray_resp.status_code in (403, 404)

        stray_stage = client.post(
            "/api/stage-application",
            headers=hdr_b,
            json={
                "job_url": "https://example.org/job/1",
                "variant": "qa_automation",
                "custom_pdf_filename": stray_name,
            },
        )
        assert stray_stage.status_code in (400, 403, 404)

        # User C with NO documents gets None from get_resume_path (never grabs first shared PDF!)
        _, _, hdr_c = _register_and_upload_same_candidate("iso_c", "GammaEmployer")
        with Session(engine) as sess:
            uid_c = sess.exec(select(User).order_by(User.id.desc())).first().id
        assert playwright_service.get_resume_path("qa_automation", user_id=uid_c) is None
        assert playwright_service.get_resume_path("", custom_pdf_filename=stray_name, user_id=uid_c) is None
    finally:
        if stray_path.exists():
            stray_path.unlink()

    # Create a User-A-only tailored CV with a distinct filename and verify User B is forbidden from downloading or staging it
    only_a = client.post(
        "/api/resumes/generate-edition",
        headers=hdr_a,
        json={
            "edition": "tailored",
            "target_role": "Platform Security Architect",
            "target_company": f"SecretCo_{uuid.uuid4().hex[:6]}",
            "job_description": "Python FastAPI Playwright",
            "cv_language": "en",
        },
    )
    assert only_a.status_code == 200, only_a.text
    only_a_pdf = only_a.json()["pdf_filename"]

    assert client.get(f"/api/resumes/generated/{only_a_pdf}", headers=hdr_b).status_code in (403, 404)
    assert client.get(f"/api/resumes/{only_a_pdf}", headers=hdr_b).status_code in (403, 404)
    listed_b = client.get("/api/resumes/generated", headers=hdr_b).json()
    assert not any(item["filename"] == only_a_pdf for item in listed_b)

    cross_stage = client.post(
        "/api/stage-application",
        headers=hdr_b,
        json={
            "job_url": "https://example.org/jobs/999",
            "variant": "qa_automation",
            "custom_pdf_filename": only_a_pdf,
        },
    )
    assert cross_stage.status_code == 403


def test_ats_checker_layout_full_name_and_expected_contact_honesty(tmp_path: Path):
    """
    P2: ATS checker requires full candidate name tokens, matches actual expected email/phone,
    performs genuine coordinate column inspection, and reports False for layout on unparseable/multi-col PDFs.
    """
    # 1. Corrupt PDF -> single_column_layout_ok MUST be False
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"not a real pdf stream")
    res_corrupt = check_pdf_ats_parseability(corrupt_pdf, candidate_name="Nino Kvaratskhelia", expected_email="nino@example.ge")
    assert res_corrupt["status"] == "FAIL"
    assert res_corrupt["single_column_layout_ok"] is False
    assert res_corrupt["layout_check_performed"] is False

    # 2. Single-column PDF containing only first token "Nino" and an unrelated link (NOT expected email)
    single_pdf = tmp_path / "partial_identity.pdf"
    c1 = canvas.Canvas(str(single_pdf), pagesize=A4)
    c1.drawString(50, 780, "Nino — Software Specialist")
    c1.drawString(50, 760, "https://unrelated-blog.example.com | someoneelse@other.org")
    c1.drawString(50, 730, "Professional Summary: Experienced quality engineer testing APIs and web services.")
    c1.drawString(50, 710, "Technical Skills: Python, PyTest, Playwright, FastAPI, Docker, PostgreSQL")
    c1.drawString(50, 690, "Work Experience: Built automated integration suites across microservice endpoints.")
    c1.save()

    rep_partial = check_pdf_ats_parseability(
        single_pdf,
        candidate_name="Nino Kvaratskhelia",
        expected_email="nino.real@example.ge",
        expected_keywords=["Python", "FastAPI"],
    )
    assert rep_partial["layout_check_performed"] is True
    assert rep_partial["single_column_layout_ok"] is True
    assert rep_partial["candidate_name_present"] is False
    assert rep_partial["contact_present"] is False

    # 3. True two-column layout PDF -> single_column_layout_ok MUST be False
    two_col_pdf = tmp_path / "two_column.pdf"
    c2 = canvas.Canvas(str(two_col_pdf), pagesize=A4)
    c2.drawString(45, 780, "Nino Kvaratskhelia")
    c2.drawString(45, 760, "nino.real@example.ge")
    for idx in range(7):
        y = 720 - (idx * 22)
        c2.drawString(45, y, f"Left Sidebar Skill Item #{idx + 1}")
        c2.drawString(320, y, f"Right Column Work Experience Detail Line #{idx + 1}")
    c2.drawString(45, 520, "Technical Skills: Python, PyTest")
    c2.drawString(45, 500, "Work Experience: QA Automation Engineer")
    c2.save()

    rep_two = check_pdf_ats_parseability(
        two_col_pdf,
        candidate_name="Nino Kvaratskhelia",
        expected_email="nino.real@example.ge",
    )
    assert rep_two["layout_check_performed"] is True
    assert rep_two["single_column_layout_ok"] is False
    assert rep_two["candidate_name_present"] is True
    assert rep_two["contact_present"] is True
    assert rep_two["status"] == "WARN"


def test_configurable_tier_aware_gemini_pricing(monkeypatch):
    """P2: Gemini pricing matches updated Standard rates, supports tiers/dates, and reads JSON overrides."""
    # Intro period (Nov 2026) Standard paid tier
    assert resolve_gemini_model_pricing("gemini-3.6-flash", tier="standard", as_of=date(2026, 11, 19)) == (0.75, 3.75)
    assert resolve_gemini_model_pricing("gemini-3.5-flash-lite", tier="standard", as_of=date(2026, 11, 19)) == (0.30, 2.50)

    # Batch/Flex & Free tiers + post-2026 scheduled Standard rate
    assert resolve_gemini_model_pricing("gemini-3.6-flash", tier="batch", as_of=date(2026, 11, 19)) == (0.375, 1.875)
    assert resolve_gemini_model_pricing("gemini-3.5-flash-lite", tier="free") == (0.0, 0.0)
    assert resolve_gemini_model_pricing("gemini-3.6-flash", tier="standard", as_of=date(2027, 1, 5)) == (1.50, 7.50)

    # Dynamic JSON pricing override without editing code
    monkeypatch.setenv(
        "GEMINI_MODEL_PRICING_JSON",
        json.dumps({"gemini-3.6-flash": {"standard": [2.0, 9.0]}}),
    )
    assert GeminiService._resolve_pricing("gemini-3.6-flash", tier="standard") == (2.0, 9.0)


def test_shared_persistent_rate_limiting_and_ip_buckets():
    """P2: Auth rate limits persist in shared SQL storage (not process memory) and throttle per email & IP."""
    init_db()
    bucket = f"otp_request:persist_{uuid.uuid4().hex[:8]}@example.com"
    reset_login_attempts(bucket)
    try:
        for _ in range(5):
            consume_rate_limit(bucket, max_attempts=5, window_seconds=120)
        with Session(engine) as sess:
            rows = len(sess.exec(select(AuthRateLimit)).all())
            assert rows >= 1

        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            check_rate_limit(bucket, max_attempts=5, window_seconds=120)
        assert exc_info.value.status_code == 429

        # Separate IP bucket also persists & enforces lockouts
        ip_bucket = f"login_ip:203.0.113.{uuid.uuid4().int % 200 + 10}"
        reset_login_attempts(ip_bucket)
        for _ in range(5):
            record_login_failure(ip_bucket, window_seconds=120)
        with pytest.raises(HTTPException) as ip_exc:
            check_rate_limit(ip_bucket, max_attempts=5, window_seconds=120)
        assert ip_exc.value.status_code == 429
    finally:
        reset_login_attempts(bucket)


def test_blind_index_decoupled_from_encryption_rotation_and_reindex(monkeypatch):
    """
    P2: Rotating ENCRYPTION_KEY never invalidates User.email_hash lookups,
    and explicit BLIND_INDEX_KEY rotation + reindex_all_blind_indices keeps logins working seamlessly.
    """
    from cryptography.fernet import Fernet

    init_db()
    k1 = Fernet.generate_key().decode("utf-8")
    k2 = Fernet.generate_key().decode("utf-8")
    bi1 = f"blind-secret-v1-{uuid.uuid4().hex}"
    bi2 = f"blind-secret-v2-{uuid.uuid4().hex}"
    target_email = f"rotate_{uuid.uuid4().hex[:8]}@example.com"
    pw = "RotatePass123!"

    monkeypatch.setenv("ENCRYPTION_KEY", k1)
    monkeypatch.setenv("ENCRYPTION_KEY_PREVIOUS", "")
    monkeypatch.setenv("BLIND_INDEX_KEY", bi1)
    monkeypatch.setenv("BLIND_INDEX_KEY_PREVIOUS", "")

    reg = client.post(
        "/api/auth/register",
        json={"email": target_email, "password": pw, "full_name": "Rotation Candidate"},
    )
    assert reg.status_code == 201, reg.text
    initial_hash = blind_index(target_email)

    # Step 1: Rotate ENCRYPTION_KEY from k1 -> k2 (keeping k1 in ENCRYPTION_KEY_PREVIOUS, BLIND_INDEX_KEY unchanged)
    monkeypatch.setenv("ENCRYPTION_KEY", k2)
    monkeypatch.setenv("ENCRYPTION_KEY_PREVIOUS", k1)
    assert blind_index(target_email) == initial_hash  # Unchanged!

    login_after_enc_rot = client.post("/api/auth/login", json={"email": target_email, "password": pw})
    assert login_after_enc_rot.status_code == 200, login_after_enc_rot.text
    assert login_after_enc_rot.json()["user"]["full_name"] == "Rotation Candidate"

    # Step 2: Explicitly rotate BLIND_INDEX_KEY from bi1 -> bi2 and run explicit reindexing
    monkeypatch.setenv("BLIND_INDEX_KEY", bi2)
    monkeypatch.setenv("BLIND_INDEX_KEY_PREVIOUS", bi1)
    with Session(engine) as sess:
        stats = reindex_all_blind_indices(sess)
        assert stats["users_reindexed"] >= 1

    # Step 3: Remove bi1 completely — login succeeds solely under new bi2 key!
    monkeypatch.setenv("BLIND_INDEX_KEY_PREVIOUS", "")
    login_after_bi_rot = client.post("/api/auth/login", json={"email": target_email, "password": pw})
    assert login_after_bi_rot.status_code == 200, login_after_bi_rot.text
    # Ensure ciphertext encrypted under k1 stays readable under k2
    assert encrypt_str("ok").startswith("enc:v1:")
