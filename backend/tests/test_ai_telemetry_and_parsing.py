import io
import uuid
import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from docx import Document as DocxDocument
from reportlab.pdfgen import canvas as pdf_canvas

from app.main import app
from app.db.database import engine, init_db
from app.db.models import User, AICacheEntry, AIOperationLog
from app.services.auth_service import hash_password, create_access_token
from app.services.cv_parser_service import cv_parser_service
from app.services.gemini_service import gemini_service
from app.services.matcher_service import matcher_service

client = TestClient(app)


def _make_user(prefix: str) -> tuple[int, str, dict]:
    init_db()
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    with Session(engine) as session:
        user = User(
            email=email,
            hashed_password=hash_password("PassTest123!"),
            full_name="Test Candidate",
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        uid = user.id
    token = create_access_token(data={"sub": email, "user_id": uid})
    return uid, email, {"Authorization": f"Bearer {token}"}


def _build_real_docx_bytes(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    doc = DocxDocument()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(buf)
    return buf.getvalue()


def _build_real_pdf_bytes(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf)
    y = 780
    for line in lines:
        c.drawString(50, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def test_universal_cv_parser_pdf_docx_md_and_malformed_rejection():
    docx_bytes = _build_real_docx_bytes([
        "Elena Beridze",
        "Product Marketing Specialist",
        "Email: elena.beridze@example.com",
        "Skills: HubSpot, Google Analytics, SQL, Copywriting",
        "Work Experience: Campaign Manager at Acme Media (2023 - Present)",
    ])
    parsed_docx = cv_parser_service.extract_text_from_bytes(docx_bytes, filename="elena_cv.docx")
    assert "Elena Beridze" in parsed_docx
    assert "HubSpot" in parsed_docx

    pdf_bytes = _build_real_pdf_bytes([
        "Davit Kapanadze",
        "Financial Analyst | Financial Modeling, Excel, SQL, PowerBI",
        "Email: davit.k@example.com | 1.5 years experience",
    ])
    parsed_pdf = cv_parser_service.extract_text_from_bytes(pdf_bytes, filename="davit_cv.pdf")
    assert "Davit Kapanadze" in parsed_pdf
    assert "PowerBI" in parsed_pdf

    # Malformed PDF & DOCX bytes must raise ValueError cleanly (no fake parsing)
    with pytest.raises(ValueError):
        cv_parser_service.extract_text_from_bytes(b"not-a-pdf-body", filename="bad.pdf")
    with pytest.raises(ValueError):
        cv_parser_service.extract_text_from_bytes(b"not-a-zip-docx", filename="bad.docx")


def test_profile_upload_docx_and_pdf_returns_honest_missing_fields():
    _, _, headers = _make_user("cv_upload")

    # Minimal marketing DOCX missing phone, linkedin, education
    docx_bytes = _build_real_docx_bytes([
        "Mariam Kiknadze",
        "Digital Marketing Specialist",
        "Skills: SEO, Google Ads, Meta Business Suite, Content Strategy",
        "Experience: 1.5 years",
    ])
    res = client.post(
        "/api/profile/upload-skills",
        files={"file": ("mariam_cv.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"run_live_scrape": "false"},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert 0 < body["completeness_score"] <= 100
    assert isinstance(body["missing_fields"], list)
    assert "phone" in body["missing_fields"]
    # Must NEVER inject hardcoded QA tools into a Marketing candidate
    all_skills = body["parsed_skills"].get("verified_skills") or body["parsed_skills"].get("all_skills") or []
    skills_joined = " ".join(all_skills).lower()
    assert "pytest" not in skills_joined
    assert "playwright" not in skills_joined

    # Corrupted PDF upload returns HTTP 400
    bad_res = client.post(
        "/api/profile/upload-skills",
        files={"file": ("corrupt.pdf", b"%PDF-1.4\nbroken-eof", "application/pdf")},
        data={"run_live_scrape": "false"},
        headers=headers,
    )
    assert bad_res.status_code == 400


def test_matcher_never_injects_default_qa_tools_into_blank_or_non_qa_md():
    mkt_md = """# Nika Maisuradze
- **Role:** Supply Chain Coordinator
- **Experience:** 1.5 years

## Skills
- SAP ERP, Inventory Forecasting, Excel, Logistics
"""
    parsed = matcher_service.parse_skills_markdown(mkt_md, enrich_with_ai=False)
    all_sk = " ".join(parsed.get("all_skills") or []).lower()
    assert "sap erp" in all_sk
    assert "pytest" not in all_sk
    assert "playwright" not in all_sk
    assert "jira" not in all_sk


def test_centralized_gemini_cache_and_telemetry_logging(monkeypatch):
    init_db()
    calls = {"count": 0}
    unique_token = uuid.uuid4().hex[:10]

    class _FakeModels:
        def generate_content(self, model, contents, config=None):
            calls["count"] += 1
            return SimpleNamespace(
                text='{"summary": "Tailored test summary for ' + unique_token + '", "score": 88}',
                usage_metadata=SimpleNamespace(
                    prompt_token_count=120,
                    candidates_token_count=45,
                    total_token_count=165,
                ),
            )

    fake_client = SimpleNamespace(models=_FakeModels())
    monkeypatch.setattr(gemini_service, "_client", fake_client)

    task_name = f"test_json_cache_{unique_token}"
    prompt = f"Return JSON summary for token {unique_token}"

    first = gemini_service.generate_json(prompt=prompt, task_type=task_name, model_tier="fast", ttl_seconds=1200)
    assert first is not None
    assert first["score"] == 88
    assert calls["count"] == 1

    # Second identical call must hit AICacheEntry and skip SDK call completely
    second = gemini_service.generate_json(prompt=prompt, task_type=task_name, model_tier="fast", ttl_seconds=1200)
    assert second == first
    assert calls["count"] == 1

    with Session(engine) as session:
        logs = session.exec(
            select(AIOperationLog)
            .where(AIOperationLog.operation_type == task_name)
            .order_by(AIOperationLog.id.asc())
        ).all()
        assert len(logs) == 2
        assert logs[0].cache_hit is False
        assert logs[0].status == "SUCCESS"
        assert logs[0].total_tokens == 165
        assert logs[0].estimated_cost_usd > 0
        assert logs[1].cache_hit is True
        assert logs[1].total_tokens == 0
        assert logs[1].estimated_cost_usd == 0.0

        # Cleanup test artifacts
        for row in logs:
            session.delete(row)
        cache_rows = session.exec(select(AICacheEntry).where(AICacheEntry.operation_type == task_name)).all()
        for cr in cache_rows:
            session.delete(cr)
        session.commit()
