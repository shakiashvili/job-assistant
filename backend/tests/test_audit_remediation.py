import os
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from jose import jwt
from sqlmodel import Session, select

from app.config import GENERATED_RESUMES_DIR
from app.db.database import engine
from app.db.models import ApplicationRecord, JobPosting
from app.main import app
from app.routers import auth as auth_router
from app.services.auth_service import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    get_user_by_email,
)
from app.services.crypto_service import blind_index, decrypt_str, encrypt_str, rotate_encrypted_value
from app.services.cv_generator_service import cv_generator_service, resolve_candidate_headline
from app.services.gemini_service import gemini_service
from app.services.gmail_service import gmail_service
from app.services.playwright_service import playwright_service


client = TestClient(app)


def _register_headers(prefix: str = "crit") -> tuple[str, dict[str, str]]:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": "StrongPassword123!", "full_name": f"{prefix.title()} User"},
    )
    assert res.status_code == 201, res.text
    return email, {"Authorization": f"Bearer {res.json()['access_token']}"}


def _guest_headers() -> dict[str, str]:
    # In non-production dev/test mode, unauthenticated calls resolve via get_current_user to guest@talentflow.local
    return {}


def test_crit_01_and_08_cross_tenant_idor_and_shared_job_isolation():
    user1_email, user1_hdr = _register_headers("owner1")
    _, user2_hdr = _register_headers("owner2")
    guest_hdr = _guest_headers()

    create_res = client.post(
        "/api/applications",
        headers=user1_hdr,
        json={"company": "Acme Health", "role": "Staff Nurse", "portal": "direct", "status": "Saved"},
    )
    assert create_res.status_code == 200, create_res.text
    app_id = create_res.json()["id"]

    # Another registered user and guest cannot access or mutate user1's record
    assert client.get(f"/api/applications/{app_id}", headers=user2_hdr).status_code == 403
    assert client.get(f"/api/applications/{app_id}", headers=guest_hdr).status_code == 403
    assert client.patch(f"/api/applications/{app_id}", headers=guest_hdr, json={"status": "Applied"}).status_code == 403
    assert client.delete(f"/api/applications/{app_id}", headers=guest_hdr).status_code == 403
    assert client.post(
        f"/api/applications/{app_id}/send-email",
        headers=guest_hdr,
        json={"recipient_email": "hr@acme.example", "subject": "Hi", "body_text": "Test", "mode": "draft"},
    ).status_code == 403
    assert client.post(
        "/api/applications/999999/send-email",
        headers=user1_hdr,
        json={"recipient_email": "hr@acme.example", "subject": "Hi", "body_text": "Test", "mode": "draft"},
    ).status_code == 404

    # CRIT-08: Tracking a shared JobPosting and editing company/role stays local to user1's tracker
    owner1_email, owner1_hdr = user1_email, user1_hdr
    with Session(engine) as session:
        owner1_row = get_user_by_email(session, owner1_email)
        assert owner1_row is not None
        shared_job = JobPosting(
            external_id=f"shared-{uuid.uuid4().hex[:8]}",
            portal="jobs.ge",
            title="Shared Accountant",
            company="Original Shared Corp",
            location="Tbilisi",
            url="https://jobs.ge/en/?view=jobs&id=123456",
            suitability_score=82,
            user_id=None,
        )
        session.add(shared_job)
        session.commit()
        session.refresh(shared_job)
        shared_job_id = shared_job.id

        rec = ApplicationRecord(
            user_id=owner1_row.id,
            job_id=shared_job_id,
            job_posting_id=shared_job_id,
            submission_status="Saved",
        )
        session.add(rec)
        session.commit()
        session.refresh(rec)
        tracked_id = f"app-{rec.id}"

    upd = client.patch(
        f"/api/applications/{tracked_id}",
        headers=owner1_hdr,
        json={"company": "User1 Custom Alias", "role": "Senior Accountant", "status": "Applied"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["company"] == "User1 Custom Alias"
    assert upd.json()["role"] == "Senior Accountant"

    with Session(engine) as session:
        refreshed = session.exec(select(JobPosting).where(JobPosting.id == shared_job_id)).first()
        assert refreshed is not None
        assert refreshed.company == "Original Shared Corp"
        assert refreshed.title == "Shared Accountant"


def test_crit_02_03_04_and_09_jwt_admin_attachment_and_crypto():
    # CRIT-02: Only explicit token_type=="access" is accepted
    legacy_no_type = jwt.encode({"sub": "a@example.com"}, SECRET_KEY, algorithm=ALGORITHM)
    refresh_tok = create_refresh_token({"sub": "a@example.com", "uid": 1})
    access_tok = create_access_token({"sub": "a@example.com", "uid": 1})
    assert decode_access_token(legacy_no_type) is None
    assert decode_access_token(refresh_tok) is None
    assert decode_access_token(access_tok)["sub"] == "a@example.com"

    # CRIT-03: configure-smtp requires admin user even outside production
    _, non_admin_hdr = _register_headers("nonadmin")
    orig_prod = auth_router.IS_PRODUCTION
    try:
        auth_router.IS_PRODUCTION = False
        smtp_res = client.post(
            "/api/auth/configure-smtp",
            headers=non_admin_hdr,
            json={"gmail_user": "sender@example.com", "gmail_app_password": "abcd efgh ijkl mnop"},
        )
        assert smtp_res.status_code == 403
    finally:
        auth_router.IS_PRODUCTION = orig_prod

    # CRIT-04: Attachment traversal outside GENERATED_RESUMES_DIR is blocked
    outside_file = GENERATED_RESUMES_DIR.parent / f"secret_{uuid.uuid4().hex[:6]}.txt"
    outside_file.write_text("TOP SECRET", encoding="utf-8")
    try:
        assert gmail_service._resolve_safe_attachment_path(str(outside_file)) is None
        assert gmail_service._resolve_safe_attachment_path(f"../{outside_file.name}") is None
        mime = gmail_service.build_mime_message(
            sender_email="sender@example.com",
            to_email="hr@example.com",
            subject="Test",
            body_text="Body",
            pdf_path=str(outside_file),
        )
        attachments = list(mime.iter_attachments()) if hasattr(mime, "iter_attachments") else []
        assert attachments == []
    finally:
        if outside_file.exists():
            outside_file.unlink()

    # CRIT-09: Plaintext starting with enc: cannot bypass encryption, rotate fails closed on bad key,
    # and BLIND_INDEX_KEY separates HMAC key from encryption key
    evil_plain = "enc:user-supplied-plaintext"
    cipher = encrypt_str(evil_plain)
    assert cipher != evil_plain
    assert cipher.startswith("enc:v1:")
    assert decrypt_str(cipher) == evil_plain

    try:
        rotate_encrypted_value(cipher, "wrong-old-secret", "new-secret")
        raised = False
    except Exception:
        raised = True
    assert raised is True

    orig_bk = os.environ.get("BLIND_INDEX_KEY")
    try:
        os.environ["BLIND_INDEX_KEY"] = "key-alpha-1"
        h1 = blind_index("alice@example.com")
        os.environ["BLIND_INDEX_KEY"] = "key-beta-2"
        h2 = blind_index("alice@example.com")
        assert h1 != h2
    finally:
        if orig_bk is None:
            os.environ.pop("BLIND_INDEX_KEY", None)
        else:
            os.environ["BLIND_INDEX_KEY"] = orig_bk


def test_crit_06_and_07_zero_fabrication_cv_narratives_and_playwright(monkeypatch):
    # CRIT-06: Path traversal in playwright_service.get_resume_path fails closed
    outside = GENERATED_RESUMES_DIR.parent.parent / f"outside_{uuid.uuid4().hex[:6]}.pdf"
    outside.write_bytes(b"%PDF-1.4\n")
    try:
        assert playwright_service.get_resume_path("", custom_pdf_filename=str(outside)) is None
        assert playwright_service.get_resume_path("", custom_pdf_filename=f"../../{outside.name}") is None
    finally:
        if outside.exists():
            outside.unlink()

    # CRIT-07: Non-QA profiles never receive hardcoded QA headline or synthetic QA/VIP bullets
    nurse_headline = resolve_candidate_headline(
        {"headline": "", "primary_role": "Registered ICU Nurse"},
        ["Critical Care Nursing", "ECG Monitoring"],
        {"primary_role": "Registered ICU Nurse"},
    )
    assert "QA Automation" not in nurse_headline
    assert "SDET" not in nurse_headline
    assert "Registered ICU Nurse" in nurse_headline

    monkeypatch.setattr(gemini_service, "generate_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(type(gemini_service), "is_available", property(lambda self: False))

    override_md = (
        "# Maya Beridze\n\n"
        "Email: maya.nurse@example.ge\n"
        "Phone: +995555112233\n\n"
        "## Work Experience\n\n"
        "### Tbilisi Central Hospital — Registered ICU Nurse (2021 - Present)\n"
        "- Monitored post-operative cardiac patients across 12-bed ICU shifts.\n"
        "- Administered IV medications and maintained clinical chart accuracy.\n\n"
        "## Core Technical Skills\n"
        "- Critical Care Nursing\n- ECG Monitoring\n"
    )
    out = cv_generator_service.generate_vacancy_cv(
        job_title="ICU Nurse",
        company="MedCenter",
        portal="jobs.ge",
        matched_skills=["Critical Care Nursing"],
        missing_skills=[],
        human_summary="Experienced ICU nurse specializing in post-operative patient monitoring.",
        motivation_statement="",
        dou_motivational_letter="",
        skills_md_override=override_md,
        cv_language="en",
        cv_style="tailored",
    )
    try:
        rendered_html = (GENERATED_RESUMES_DIR / out["html_filename"]).read_text(encoding="utf-8")
        assert "Maya Beridze" in rendered_html
        assert "Registered ICU Nurse" in rendered_html
        assert "QA Automation" not in rendered_html
        assert "Playwright" not in rendered_html
        assert out.get("cover_letter") is not None
    finally:
        for fname_key in ("html_filename", "docx_filename", "pdf_filename"):
            fn = out.get(fname_key)
            if fn:
                fp = GENERATED_RESUMES_DIR / fn
                if fp.exists():
                    fp.unlink()

    narratives = gemini_service.craft_human_tone_narratives(
        job_details={
            "title": "Head Pastry Chef",
            "company": "Boulangerie",
            "description": "Lead morning viennoiserie production and kitchen hygiene compliance.",
        },
        skills_md=(
            "# Nino Chef\n\n"
            "## Work Experience\n\n"
            "### Cafe Rustaveli — Pastry Chef (2020 - Present)\n"
            "- Prepared croissant dough daily.\n\n"
            "## Core Technical Skills\n- Laminated Dough\n- Food Safety\n"
        ),
        matched_skills=["Laminated Dough", "Food Safety"],
        missing_skills=[],
        cv_language="en",
        candidate_name="Nino Chef",
        letter_language="ka",
    )
    combined = " ".join([narratives["human_tone_summary"], narratives["cover_letter"], narratives["dou_motivational_letter"]])
    assert "VIP operations" not in combined
    assert "VIP კომუნიკაციის" not in combined
    assert "PostgreSQL verification" not in combined
    assert narratives["cover_letter"] != narratives["dou_motivational_letter"]

    ka_out = gemini_service.translate_bullets_to_georgian(["Prepared croissant dough daily."])
    assert ka_out == ["Prepared croissant dough daily."]
