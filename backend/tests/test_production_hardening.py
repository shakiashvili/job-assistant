import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlmodel import Session, select

from app.main import app
from app.config import BASE_DIR, GENERATED_RESUMES_DIR, PROJECT_ROOT, TEST_FORMS_DIR, resolve_gemini_model_pricing
from app.db.database import DATABASE_URL, engine, init_db
from app.db.document_repository import migrate_legacy_generated_resumes, user_generated_resumes_dir
from app.db.models import AuthRateLimit, CandidateDocument
from app.services import auth_service as auth_service_mod
from app.services.ats_checker import check_pdf_ats_parseability
from app.services.auth_service import (
    check_rate_limit,
    consume_rate_limit,
    hash_password,
    purge_expired_rate_limits,
    record_login_failure,
    reset_login_attempts,
)
from app.services.crypto_service import (
    _derive_fernet_bytes,
    blind_index,
    encrypt_str,
    reindex_all_blind_indices,
)
from app.services.gemini_service import GeminiService

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


def test_generated_cv_user_directory_isolation_and_fail_closed_staging(monkeypatch):
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

        sample_form_url = (TEST_FORMS_DIR / "greenhouse_sample.html").as_uri()
        stray_stage = client.post(
            "/api/stage-application",
            headers=hdr_b,
            json={
                "job_url": sample_form_url,
                "variant": "qa_automation",
                "custom_pdf_filename": stray_name,
                "headless": True,
                "timeout_seconds": 5,
            },
        )
        # Removed /api/stage-application route returns 404 (server-side Playwright auto-staging retired)
        assert stray_stage.status_code == 404
    finally:
        if stray_path.exists():
            stray_path.unlink()

    # Create a User-A-only tailored CV with a distinct filename and verify User B is forbidden from downloading it
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
    assert rep_partial["status"] == "WARN"

    # 2b. Full name + clean single-column layout + sections (score >= 75), but missing expected contact -> MUST WARN, not PASS
    missing_contact_pdf = tmp_path / "missing_contact.pdf"
    c_mc = canvas.Canvas(str(missing_contact_pdf), pagesize=A4)
    c_mc.drawString(50, 780, "Nino Kvaratskhelia")
    c_mc.drawString(50, 755, "Professional Summary: Experienced quality engineer testing APIs and web services.")
    c_mc.drawString(50, 730, "Technical Skills: Python, PyTest, Playwright, FastAPI, Docker, PostgreSQL")
    c_mc.drawString(50, 705, "Work Experience: Built automated integration suites across microservice endpoints.")
    c_mc.drawString(50, 680, "Education: B.Sc. in Computer Science, Tbilisi State University")
    c_mc.save()

    rep_mc = check_pdf_ats_parseability(
        missing_contact_pdf,
        candidate_name="Nino Kvaratskhelia",
        expected_email="nino.real@example.ge",
    )
    assert rep_mc["score"] >= 75
    assert rep_mc["candidate_name_present"] is True
    assert rep_mc["contact_present"] is False
    assert rep_mc["status"] == "WARN"

    # 2c. Complete valid single-column CV with full name + expected email -> PASS
    complete_pdf = tmp_path / "complete_valid.pdf"
    c_ok = canvas.Canvas(str(complete_pdf), pagesize=A4)
    c_ok.drawString(50, 780, "Nino Kvaratskhelia | nino.real@example.ge")
    c_ok.drawString(50, 755, "Professional Summary: Experienced quality engineer testing APIs and web services.")
    c_ok.drawString(50, 730, "Technical Skills: Python, PyTest, Playwright, FastAPI, Docker, PostgreSQL")
    c_ok.drawString(50, 705, "Work Experience: Built automated integration suites across microservice endpoints.")
    c_ok.save()

    rep_ok = check_pdf_ats_parseability(
        complete_pdf,
        candidate_name="Nino Kvaratskhelia",
        expected_email="nino.real@example.ge",
    )
    assert rep_ok["status"] == "PASS"
    assert rep_ok["candidate_name_present"] is True
    assert rep_ok["contact_present"] is True

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

        # Expired SQL rows from one-off probes are cleaned up while active buckets are preserved
        stale_key_1 = hashlib.sha256(f"probe_{uuid.uuid4().hex}@example.com".encode()).hexdigest()
        stale_key_2 = hashlib.sha256(f"probe_{uuid.uuid4().hex}@example.com".encode()).hexdigest()
        active_key = hashlib.sha256(f"active_{uuid.uuid4().hex}@example.com".encode()).hexdigest()
        now_val = time.time()
        with Session(engine) as sess:
            sess.add(AuthRateLimit(bucket_key=stale_key_1, attempts=1, window_started_at=now_val - 900, expires_at=now_val - 300))
            sess.add(AuthRateLimit(bucket_key=stale_key_2, attempts=2, window_started_at=now_val - 900, expires_at=now_val - 120))
            sess.add(AuthRateLimit(bucket_key=active_key, attempts=5, window_started_at=now_val, expires_at=now_val + 600))
            sess.commit()

        deleted = purge_expired_rate_limits()
        assert deleted >= 2
        with Session(engine) as sess:
            assert sess.get(AuthRateLimit, stale_key_1) is None
            assert sess.get(AuthRateLimit, stale_key_2) is None
            assert sess.get(AuthRateLimit, active_key) is not None

        # Throttled periodic sweep during live consume_rate_limit also prunes expired buckets
        stale_key_3 = hashlib.sha256(f"probe_{uuid.uuid4().hex}@example.com".encode()).hexdigest()
        with Session(engine) as sess:
            sess.add(AuthRateLimit(bucket_key=stale_key_3, attempts=1, window_started_at=now_val - 900, expires_at=now_val - 60))
            sess.commit()
        auth_service_mod._LAST_RATE_LIMIT_PRUNE_TS = 0.0
        probe_bucket = f"otp_request:prune_trigger_{uuid.uuid4().hex[:8]}@example.com"
        consume_rate_limit(probe_bucket, max_attempts=5, window_seconds=120)
        reset_login_attempts(probe_bucket)
        with Session(engine) as sess:
            assert sess.get(AuthRateLimit, stale_key_3) is None
            active_row = sess.get(AuthRateLimit, active_key)
            assert active_row is not None
            sess.delete(active_row)
            sess.commit()
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


def test_legacy_blind_index_upgrade_cli_reindex_and_deploy_config(monkeypatch):
    """
    P1/P2: Simulates pre-upgrade accounts whose email_hash was derived from legacy ENCRYPTION_KEY,
    verifies login with BLIND_INDEX_KEY_PREVIOUS + ENCRYPTION_KEY rotation, executes the CLI `--reindex`
    command, and verifies login continues working after removing BLIND_INDEX_KEY_PREVIOUS.
    """
    from cryptography.fernet import Fernet

    init_db()

    render_text = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")
    env_tmpl_text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    deploy_doc = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "key: BLIND_INDEX_KEY" in render_text
    assert "BLIND_INDEX_KEY=" in env_tmpl_text
    assert "BLIND_INDEX_KEY" in deploy_doc and "--reindex" in deploy_doc

    legacy_passphrase = f"legacy-nonfernet-enc-secret-{uuid.uuid4().hex[:8]}"
    new_enc_key = Fernet.generate_key().decode("utf-8")
    new_blind_key = f"independent-blind-key-{uuid.uuid4().hex}"

    # Create two legacy user rows as existed prior to independent BLIND_INDEX_KEY separation
    legacy_fernet_bytes = _derive_fernet_bytes(legacy_passphrase)
    legacy_fernet = Fernet(legacy_fernet_bytes)
    legacy_hmac_secret = hashlib.sha256(legacy_fernet_bytes + b":blind-index").digest()

    email_login_upgrade = f"legacy_login_{uuid.uuid4().hex[:8]}@example.com"
    email_cli_reindex = f"legacy_cli_{uuid.uuid4().hex[:8]}@example.com"
    pw = "LegacyAccountPass123!"

    with Session(engine) as sess:
        from sqlalchemy import text as sa_text

        for em, nm in ((email_login_upgrade, "Legacy Login User"), (email_cli_reindex, "Legacy CLI User")):
            legacy_hash = hmac.new(legacy_hmac_secret, em.lower().encode("utf-8"), hashlib.sha256).hexdigest()
            enc_em = f"enc:v1:{legacy_fernet.encrypt(em.encode('utf-8')).decode('utf-8')}"
            enc_nm = f"enc:v1:{legacy_fernet.encrypt(nm.encode('utf-8')).decode('utf-8')}"
            sess.connection().execute(
                sa_text(
                    "INSERT INTO users (email, email_hash, hashed_password, full_name, is_active, is_admin, created_at) "
                    "VALUES (:email, :email_hash, :hpw, :fn, :active, :admin, CURRENT_TIMESTAMP)"
                ),
                {
                    "email": enc_em,
                    "email_hash": legacy_hash,
                    "hpw": hash_password(pw),
                    "fn": enc_nm,
                    "active": True,
                    "admin": False,
                },
            )
        sess.commit()

    # Step 1: Upgrade keys with transition PREVIOUS vars enabled
    monkeypatch.setenv("ENCRYPTION_KEY", new_enc_key)
    monkeypatch.setenv("ENCRYPTION_KEY_PREVIOUS", legacy_passphrase)
    monkeypatch.setenv("BLIND_INDEX_KEY", new_blind_key)
    monkeypatch.setenv("BLIND_INDEX_KEY_PREVIOUS", legacy_passphrase)

    # First user logs in via BLIND_INDEX_KEY_PREVIOUS (even with non-Fernet legacy ENCRYPTION_KEY)
    login_u1 = client.post("/api/auth/login", json={"email": email_login_upgrade, "password": pw})
    assert login_u1.status_code == 200, login_u1.text
    assert login_u1.json()["user"]["full_name"] == "Legacy Login User"

    # Step 2: Run the exact CLI `--reindex` command for remaining dormant legacy accounts
    cli_env = os.environ.copy()
    cli_env["ENCRYPTION_KEY"] = new_enc_key
    cli_env["ENCRYPTION_KEY_PREVIOUS"] = legacy_passphrase
    cli_env["BLIND_INDEX_KEY"] = new_blind_key
    cli_env["BLIND_INDEX_KEY_PREVIOUS"] = ""
    cli_env["DATABASE_URL"] = DATABASE_URL
    cli_env["PYTHONPATH"] = str(BASE_DIR)
    cli_res = subprocess.run(
        [sys.executable, "-m", "app.services.crypto_service", "--reindex"],
        cwd=str(BASE_DIR),
        env=cli_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli_res.returncode == 0, cli_res.stderr or cli_res.stdout
    assert "Blind index reindexing complete" in cli_res.stdout

    # Step 3: Remove BLIND_INDEX_KEY_PREVIOUS — both legacy accounts still log in cleanly!
    monkeypatch.setenv("BLIND_INDEX_KEY_PREVIOUS", "")
    login_u1_after = client.post("/api/auth/login", json={"email": email_login_upgrade, "password": pw})
    login_u2_after = client.post("/api/auth/login", json={"email": email_cli_reindex, "password": pw})
    assert login_u1_after.status_code == 200, login_u1_after.text
    assert login_u2_after.status_code == 200, login_u2_after.text
    assert login_u2_after.json()["user"]["full_name"] == "Legacy CLI User"


def test_legacy_shared_cv_migration_moves_owned_and_blocks_collisions():
    """
    P2: Verifies one-time/startup migration moves unambiguous legacy generated CVs from flat
    GENERATED_RESUMES_DIR into user_<id>/ directories and updates CandidateDocument.storage_path,
    while refusing to move colliding multi-owner or unowned root files.
    """
    uid_a, _, hdr_a = _register_and_upload_same_candidate("mig_a", "MigrationCorpA")
    uid_b, _, hdr_b = _register_and_upload_same_candidate("mig_b", "MigrationCorpB")

    tag = uuid.uuid4().hex[:8]
    legacy_pdf = f"Legacy_Owned_{tag}.pdf"
    legacy_html = f"Legacy_Owned_{tag}.html"
    colliding_pdf = f"Legacy_Shared_{tag}.pdf"
    unowned_pdf = f"Legacy_Unowned_{tag}.pdf"

    root_pdf = GENERATED_RESUMES_DIR / legacy_pdf
    root_html = GENERATED_RESUMES_DIR / legacy_html
    root_col = GENERATED_RESUMES_DIR / colliding_pdf
    root_unowned = GENERATED_RESUMES_DIR / unowned_pdf

    user_a_dir = user_generated_resumes_dir(uid_a)
    user_b_dir = user_generated_resumes_dir(uid_b)
    dest_pdf = user_a_dir / legacy_pdf
    dest_html = user_a_dir / legacy_html

    try:
        root_pdf.write_bytes(b"%PDF-1.4\n%LegacyOwnedByA\n")
        root_html.write_text("<html><body>LegacyOwnedByA</body></html>", encoding="utf-8")
        root_col.write_bytes(b"%PDF-1.4\n%CollidingShared\n")
        root_unowned.write_bytes(b"%PDF-1.4\n%UnownedRoot\n")

        with Session(engine) as sess:
            sess.add(
                CandidateDocument(
                    user_id=uid_a,
                    doc_type="generated_pdf",
                    filename=legacy_pdf,
                    original_filename=legacy_pdf,
                    storage_path=str(root_pdf),
                    size_bytes=len(root_pdf.read_bytes()),
                )
            )
            sess.add(
                CandidateDocument(
                    user_id=uid_a,
                    doc_type="generated_pdf",
                    filename=colliding_pdf,
                    original_filename=colliding_pdf,
                    storage_path=str(root_col),
                    size_bytes=10,
                )
            )
            sess.add(
                CandidateDocument(
                    user_id=uid_b,
                    doc_type="generated_pdf",
                    filename=colliding_pdf,
                    original_filename=colliding_pdf,
                    storage_path=str(root_col),
                    size_bytes=10,
                )
            )
            sess.commit()

        stats = migrate_legacy_generated_resumes()
        assert stats["moved_files"] >= 2
        assert stats["updated_records"] >= 1
        assert stats["skipped_ambiguous"] >= 1

        # Unambiguous files moved cleanly out of root into user_<a>/ and DB path updated
        assert not root_pdf.exists() and dest_pdf.is_file()
        assert not root_html.exists() and dest_html.is_file()
        with Session(engine) as sess:
            migrated_doc = sess.exec(
                select(CandidateDocument).where(
                    CandidateDocument.user_id == uid_a,
                    CandidateDocument.filename == legacy_pdf,
                )
            ).first()
            assert migrated_doc is not None
            assert Path(migrated_doc.storage_path).resolve() == dest_pdf.resolve()

        # Owner can now download moved PDF & HTML; User B cannot
        dl_a = client.get(f"/api/resumes/generated/{legacy_pdf}", headers=hdr_a)
        assert dl_a.status_code == 200 and b"LegacyOwnedByA" in dl_a.content
        assert client.get(f"/api/resumes/generated/{legacy_pdf}", headers=hdr_b).status_code in (403, 404)

        # Colliding & unowned root files stay out of per-user directories and remain blocked
        assert root_col.exists() and not (user_a_dir / colliding_pdf).exists() and not (user_b_dir / colliding_pdf).exists()
        assert client.get(f"/api/resumes/generated/{colliding_pdf}", headers=hdr_a).status_code in (403, 404)
        assert root_unowned.exists() and client.get(f"/api/resumes/generated/{unowned_pdf}", headers=hdr_a).status_code in (403, 404)

        # Second migration run is a clean idempotent no-op for the migrated file
        stats_2 = migrate_legacy_generated_resumes()
        assert stats_2["moved_files"] == 0
    finally:
        for p in (root_pdf, root_html, root_col, root_unowned, dest_pdf, dest_html):
            if p.exists():
                p.unlink()


def test_durable_cv_storage_survives_local_disk_wipe_and_s3_roundtrip(monkeypatch):
    """
    P1: Verifies uploaded and generated CVs survive ephemeral local disk wipes via encrypted DB blobs
    and via S3/R2 object storage (including per-user key isolation and remote delete cleanup).
    """
    from app.db.document_repository import user_uploaded_resumes_dir
    from app.services.storage_service import storage_service

    uid_a, _, hdr_a = _register_and_upload_same_candidate("dur_a", "DurableAlpha")
    uid_b, _, hdr_b = _register_and_upload_same_candidate("dur_b", "DurableBeta")

    # Part A: Encrypted DB blob persistence (S3 unset) survives local disk wipe
    monkeypatch.setenv("S3_BUCKET", "")
    up_name = f"durable_upload_{uuid.uuid4().hex[:6]}.pdf"
    up_bytes = b"%PDF-1.4\n%DurableUploadedBytesAlpha\n"
    up_resp = client.post(
        "/api/resumes/my-cvs/upload",
        headers=hdr_a,
        files={"file": (up_name, up_bytes, "application/pdf")},
        data={"parse_into_profile": "false"},
    )
    assert up_resp.status_code == 200, up_resp.text

    gen_resp = client.post(
        "/api/resumes/generate-edition",
        headers=hdr_a,
        json={"edition": "ats", "cv_language": "en"},
    )
    assert gen_resp.status_code == 200, gen_resp.text
    gen_body = gen_resp.json()
    gen_pdf_name = gen_body["pdf_filename"]
    gen_pdf_path = Path(gen_body["pdf_path"])
    gen_pdf_bytes = gen_pdf_path.read_bytes()
    cv_ver_id = gen_body["cv_version_id"]

    # Simulate ephemeral container restart wiping both local upload and generated files
    local_up_path = user_uploaded_resumes_dir(uid_a) / up_name
    assert local_up_path.is_file() and gen_pdf_path.is_file()
    local_up_path.unlink()
    gen_pdf_path.unlink()
    assert not local_up_path.exists() and not gen_pdf_path.exists()

    # Listing still reports both durable documents after local disk wipe
    my_cvs = client.get("/api/resumes/my-cvs", headers=hdr_a)
    assert my_cvs.status_code == 200
    assert any(item["filename"] == up_name for item in my_cvs.json())

    gen_list = client.get("/api/resumes/generated", headers=hdr_a)
    assert gen_list.status_code == 200
    assert any(item["filename"] == gen_pdf_name for item in gen_list.json())

    # Downloading transparently re-hydrates exact bytes for owner, while blocking User B
    dl_up = client.get(f"/api/resumes/user/{up_name}", headers=hdr_a)
    assert dl_up.status_code == 200 and dl_up.content == up_bytes
    assert client.get(f"/api/resumes/user/{up_name}", headers=hdr_b).status_code in (403, 404)

    dl_gen = client.get(f"/api/resumes/generated/{gen_pdf_name}", headers=hdr_a)
    assert dl_gen.status_code == 200 and dl_gen.content == gen_pdf_bytes
    assert client.get(f"/api/resumes/generated/{gen_pdf_name}", headers=hdr_b).status_code in (403, 404)

    # ATS check also succeeds cleanly after wipe + rehydration
    gen_pdf_path.unlink()
    ats_after_wipe = client.get(f"/api/cv-versions/{cv_ver_id}/ats-check", headers=hdr_a)
    assert ats_after_wipe.status_code == 200, ats_after_wipe.text

    # Part B: S3/R2 object-storage roundtrip with per-user object key & remote deletion
    fake_s3: dict[str, bytes] = {}
    monkeypatch.setenv("S3_BUCKET", "talentflow-test-bucket")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://r2.example.invalid")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "test-ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "test-sk")
    monkeypatch.setattr(storage_service, "put_s3_object", lambda key, data, content_type="": fake_s3.__setitem__(key, data))
    monkeypatch.setattr(storage_service, "get_s3_object", lambda key: fake_s3.get(key))
    monkeypatch.setattr(storage_service, "delete_s3_object", lambda key: fake_s3.pop(key, None) is not None)

    s3_name = f"s3_cv_{uuid.uuid4().hex[:6]}.pdf"
    s3_bytes = b"%PDF-1.4\n%S3StoredResumePayload\n"
    s3_up = client.post(
        "/api/resumes/my-cvs/upload",
        headers=hdr_a,
        files={"file": (s3_name, s3_bytes, "application/pdf")},
        data={"parse_into_profile": "false"},
    )
    assert s3_up.status_code == 200, s3_up.text
    expected_key = f"talentflow/users/user_{uid_a}/uploads/{s3_name}"
    assert expected_key in fake_s3 and fake_s3[expected_key] == s3_bytes

    s3_local = user_uploaded_resumes_dir(uid_a) / s3_name
    s3_local.unlink()
    dl_s3 = client.get(f"/api/resumes/user/{s3_name}", headers=hdr_a)
    assert dl_s3.status_code == 200 and dl_s3.content == s3_bytes

    del_s3 = client.delete(f"/api/resumes/my-cvs/{s3_name}", headers=hdr_a)
    assert del_s3.status_code == 200
    assert expected_key not in fake_s3


def test_durable_scrape_stale_recovery_and_timeout(monkeypatch):
    """
    P1: Verifies interrupted RUNNING scrape tasks left by process restarts do not permanently
    block users: stale tasks re-queue up to max_attempts, then fail cleanly, and timeouts fail fast.
    """
    import asyncio
    from datetime import timedelta
    from app.db.models import ScrapeTask, utc_now
    from app.services.scrape_worker import execute_scrape_task, recover_stale_scrape_tasks
    from app.services.scrapers.scraper_orchestrator import scraper_orchestrator

    uid, _, hdr = _register_and_upload_same_candidate("scrape_dur", "ScrapeCorp")
    stale_tid_maxed = f"scrape-stale-max-{uuid.uuid4().hex[:8]}"
    stale_tid_retry = f"scrape-stale-ret-{uuid.uuid4().hex[:8]}"
    old_hb = utc_now() - timedelta(minutes=15)

    with Session(engine) as sess:
        sess.add(
            ScrapeTask(
                task_id=stale_tid_maxed,
                user_id=uid,
                status="RUNNING",
                portals=["jobs.ge"],
                allow_network=False,
                worker_id="crashed-worker-old",
                started_at=old_hb,
                heartbeat_at=old_hb,
                attempt_count=2,
                max_attempts=2,
                timeout_seconds=60,
            )
        )
        sess.commit()

    # Calling /api/jobs/scrape/async must recover the dead RUNNING task -> FAILED and launch a new task!
    resp = client.post("/api/jobs/scrape/async", headers=hdr, json={"allow_network": False, "portals": ["jobs.ge"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deduplicated"] is False
    assert body["task_id"] != stale_tid_maxed
    assert body["status"] == "COMPLETED"

    old_status = client.get(f"/api/jobs/scrape/status/{stale_tid_maxed}", headers=hdr)
    assert old_status.status_code == 200
    assert old_status.json()["status"] == "FAILED"

    # A stale RUNNING task with remaining retries transitions back to QUEUED for worker recovery
    with Session(engine) as sess:
        sess.add(
            ScrapeTask(
                task_id=stale_tid_retry,
                user_id=uid,
                status="RUNNING",
                portals=["jobs.ge"],
                allow_network=False,
                worker_id="crashed-worker-retry",
                started_at=old_hb,
                heartbeat_at=old_hb,
                attempt_count=1,
                max_attempts=2,
                timeout_seconds=60,
            )
        )
        sess.commit()

    rec = recover_stale_scrape_tasks()
    assert rec["requeued"] >= 1
    with Session(engine) as sess:
        requeued_row = sess.exec(select(ScrapeTask).where(ScrapeTask.task_id == stale_tid_retry)).first()
        assert requeued_row is not None and requeued_row.status == "QUEUED"

    # Hard execution timeout marks a hung scrape task FAILED cleanly
    timeout_tid = f"scrape-timeout-{uuid.uuid4().hex[:8]}"
    with Session(engine) as sess:
        sess.add(
            ScrapeTask(
                task_id=timeout_tid,
                user_id=uid,
                status="QUEUED",
                portals=["jobs.ge"],
                allow_network=False,
                attempt_count=0,
                max_attempts=1,
                timeout_seconds=1,
            )
        )
        sess.commit()

    async def _slow_scrape(*args, **kwargs):
        await asyncio.sleep(3)
        return {"total_processed": 0}

    monkeypatch.setattr(scraper_orchestrator, "run_scrapers", _slow_scrape)
    asyncio.run(execute_scrape_task(timeout_tid))
    with Session(engine) as sess:
        timed_out = sess.exec(select(ScrapeTask).where(ScrapeTask.task_id == timeout_tid)).first()
        assert timed_out is not None
        assert timed_out.status == "FAILED"
        assert "timeout" in (timed_out.error_message or "").lower()


def test_https_otp_email_delivery_and_disabled_mode(monkeypatch):
    """
    P2: Verifies OTP email delivery supports HTTPS APIs (Resend over port 443, avoiding blocked
    Render Free SMTP ports) and honestly disables OTP with HTTP 503 when OTP_EMAIL_ENABLED=false.
    """
    import httpx
    from types import SimpleNamespace

    captured: dict = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return SimpleNamespace(status_code=200, text='{"id":"re_ok"}')

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setenv("OTP_EMAIL_ENABLED", "true")
    monkeypatch.setenv("RESEND_API_KEY", "re_live_test_token")
    monkeypatch.setenv("EMAIL_FROM", "TalentFlow AI <noreply@talentflow.example>")

    st = client.get("/api/auth/smtp-status")
    assert st.status_code == 200
    st_json = st.json()
    assert st_json["otp_available"] is True
    assert st_json["provider"] == "resend"

    otp_email = f"otp_https_{uuid.uuid4().hex[:8]}@example.com"
    send_resp = client.post("/api/auth/send-otp", json={"email": otp_email})
    assert send_resp.status_code == 200, send_resp.text
    assert send_resp.json()["delivered"] is True
    assert send_resp.json()["provider"] == "resend"
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["json"]["to"] == [otp_email]

    # When OTP is disabled explicitly, status reports disabled and send-otp returns 503
    monkeypatch.setenv("OTP_EMAIL_ENABLED", "false")
    st_dis = client.get("/api/auth/email-status")
    assert st_dis.status_code == 200
    assert st_dis.json()["otp_available"] is False
    assert st_dis.json()["provider"] == "disabled"

    send_dis = client.post("/api/auth/send-otp", json={"email": otp_email})
    assert send_dis.status_code == 503


def test_health_readiness_db_check_and_render_docs_accuracy(monkeypatch):
    """
    P2: Verifies /api/health and /api/health/ready execute a live DB connectivity check
    (returning 503 on DB outage while /api/health/live stays 200) and deployment config/docs are accurate.
    """
    import app.main as main_mod

    live = client.get("/api/health/live")
    assert live.status_code == 200 and live.json()["status"] == "alive"

    ready = client.get("/api/health/ready")
    assert ready.status_code == 200
    r_json = ready.json()
    assert r_json["status"] == "healthy"
    assert r_json["database_reachable"] is True
    assert r_json["storage"]["durable"] is True

    def _broken_connect():
        raise RuntimeError("Simulated database outage")

    monkeypatch.setattr(main_mod.engine, "connect", _broken_connect)
    down_health = client.get("/api/health")
    down_ready = client.get("/api/health/ready")
    still_live = client.get("/api/health/live")
    assert down_health.status_code == 503 and down_health.json()["status"] == "unhealthy"
    assert down_ready.status_code == 503 and down_ready.json()["database_reachable"] is False
    assert still_live.status_code == 200

    # Verify render.yaml & DEPLOYMENT.md reflect non-ephemeral storage and accurate Render Postgres expiry
    render_yaml = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")
    deploy_md = (PROJECT_ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "plan: starter" in render_yaml
    assert "mountPath: /app/data" in render_yaml
    assert "30 days" in deploy_md and "14-day" in deploy_md
    assert "90 days" not in deploy_md

    compose_yaml = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "BLIND_INDEX_KEY" in compose_yaml
    assert "ENCRYPTION_KEY" in compose_yaml
    assert "./data:/app/data" in compose_yaml
    assert "postgres:16-alpine" in compose_yaml


def test_strict_fail_closed_ownership_blocks_null_user_id_tracker_and_scrape_rows():
    """
    Verifies residual user_id=None / guest@talentflow.local bypasses are completely removed:
    neither guest nor registered users can read/modify orphaned user_id=None tracker records or scrape tasks.
    """
    from app.db.models import ApplicationRecord, ScrapeTask
    from app.db.tracker_repository import tracker_store

    init_db()
    uid, _, hdr = _register_and_upload_same_candidate("strict_own", "StrictOwnerCo")

    orphan_tid = f"scrape-orphan-{uuid.uuid4().hex[:8]}"
    with Session(engine) as sess:
        orphan_rec = ApplicationRecord(
            user_id=None,
            submission_status="SAVED",
            notes="Orphaned legacy application",
        )
        sess.add(orphan_rec)
        sess.add(
            ScrapeTask(
                task_id=orphan_tid,
                user_id=None,
                status="COMPLETED",
                portals=["jobs.ge"],
            )
        )
        sess.commit()
        sess.refresh(orphan_rec)
        orphan_app_id = f"app-{orphan_rec.id}"

    # Orphaned ApplicationRecord (user_id=None) must be blocked even if caller passes is_guest=True
    assert tracker_store._ownership_matches(None, uid, is_guest=True) is False
    assert tracker_store._ownership_matches(None, None, is_guest=True) is False
    assert all(it.id != orphan_app_id for it in tracker_store.get_all(user_id=uid, is_guest=True))
    assert tracker_store.get_all(user_id=None, is_guest=True) == []

    # Guest (no Authorization header) and authenticated user both get 403 on orphaned app & scrape task
    assert client.get(f"/api/applications/{orphan_app_id}").status_code == 403
    assert client.get(f"/api/applications/{orphan_app_id}", headers=hdr).status_code == 403
    assert client.get(f"/api/jobs/scrape/status/{orphan_tid}").status_code == 403
    assert client.get(f"/api/jobs/scrape/status/{orphan_tid}", headers=hdr).status_code == 403
