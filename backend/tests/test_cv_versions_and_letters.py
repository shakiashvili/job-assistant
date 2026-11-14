import io
import uuid
import base64
from fastapi.testclient import TestClient
from docx import Document as DocxDocument

from app.main import app
from app.db.database import engine, init_db
from app.db.models import User
from app.services.auth_service import hash_password, create_access_token

client = TestClient(app)


def _auth_user(prefix: str) -> tuple[int, str, dict]:
    init_db()
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"
    with __import__("sqlmodel").Session(engine) as session:
        user = User(
            email=email,
            hashed_password=hash_password("CvTestPass123!"),
            full_name="Luka Beridze",
            is_active=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        uid = user.id
    token = create_access_token(data={"sub": email, "user_id": uid})
    return uid, email, {"Authorization": f"Bearer {token}"}


def test_cv_studio_version_lifecycle_inline_edit_and_non_qa_domain():
    _, _, headers_owner = _auth_user("cv_owner")
    _, _, headers_other = _auth_user("cv_other")

    marketing_md = """# Luka Beridze
- **Role:** Brand & Performance Marketing Specialist
- **Email:** luka.beridze@example.com
- **Location:** Tbilisi, Georgia
- **Experience:** 1.5 years

## Skills
- Meta Ads, Google Analytics 4, SEO, Copywriting, HubSpot

## Work Experience
### Performance Marketing Specialist | GrowthLab Agency | 2024 - Present
- Managed paid acquisition budgets across Meta and Google Search campaigns.
- Built weekly attribution dashboards in Looker Studio.

## Education
- BBA in Marketing | Caucasus University (2024)
"""
    up = client.post(
        "/api/profile/upload-skills",
        data={"content": marketing_md, "run_live_scrape": "false"},
        headers=headers_owner,
    )
    assert up.status_code == 200

    # 1. Generate tailored edition -> creates CVVersion + returns separate cover_letter vs motivational_letter
    gen_res = client.post(
        "/api/resumes/generate-edition",
        json={
            "edition": "tailored",
            "target_role": "Performance Marketing Specialist",
            "target_company": "PeakCommerce",
            "job_description": "Looking for Performance Marketing Specialist with Google Analytics 4, Meta Ads, and HubSpot experience.",
            "cv_language": "en",
        },
        headers=headers_owner,
    )
    assert gen_res.status_code == 200
    gen = gen_res.json()
    assert gen["cv_version_id"] is not None
    assert gen["rendered_html"]
    assert "PeakCommerce" in gen["cover_letter"]
    assert gen.get("motivational_letter")
    # Domain neutrality check: must not fabricate QA automation terms or hardcoded availability cliché
    assert "1 week after offer" not in gen["cover_letter"].lower()
    assert "qa automation" not in gen["rendered_html"].lower()

    version_id = gen["cv_version_id"]

    # 2. List CV versions -> owner sees it, other user does not
    list_owner = client.get("/api/cv-versions", headers=headers_owner)
    assert list_owner.status_code == 200
    assert any(v["id"] == version_id for v in list_owner.json()["items"])

    list_other = client.get("/api/cv-versions", headers=headers_other)
    assert list_other.status_code == 200
    assert not any(v["id"] == version_id for v in list_other.json()["items"])

    # 3. Other user cannot PATCH or DELETE owner's CV version
    assert (
        client.patch(
            f"/api/cv-versions/{version_id}",
            json={"title": "Hijacked"},
            headers=headers_other,
        ).status_code
        in (403, 404)
    )
    assert client.delete(f"/api/cv-versions/{version_id}", headers=headers_other).status_code in (403, 404)

    # 4. Owner edits summary & skills inline -> re-renders HTML, PDF, and DOCX cleanly
    patch_res = client.patch(
        f"/api/cv-versions/{version_id}",
        json={
            "title": "Updated Marketing Edition",
            "structured_json": {
                **(gen["cv_sections"] or {}),
                "summary": "Performance-focused marketer specializing in ROAS optimization and GA4 funnel analytics.",
                "skills": ["Google Analytics 4", "Meta Ads", "HubSpot", "Looker Studio"],
            },
        },
        headers=headers_owner,
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["version_number"] == 2
    assert "ROAS optimization" in patched["rendered_html"]
    assert patched["docx_url"] and client.get(patched["docx_url"], headers=headers_owner).content[:2] == b"PK"

    # 5. Clean delete
    del_res = client.delete(f"/api/cv-versions/{version_id}", headers=headers_owner)
    assert del_res.status_code == 200


def test_extension_upload_skills_supports_base64_docx():
    _, _, headers = _auth_user("ext_docx")
    buf = io.BytesIO()
    doc = DocxDocument()
    doc.add_paragraph("Sopho Tsereteli")
    doc.add_paragraph("UI/UX Designer | Figma, Design Systems, Prototyping")
    doc.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    res = client.post(
        "/api/extension/upload-skills",
        json={
            "filename": "sopho_cv.docx",
            "content_base64": f"data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{b64}",
        },
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["profile_uploaded"] is True
    assert "Figma" in " ".join(data["verified_skills"])
    assert "completeness_score" in data
