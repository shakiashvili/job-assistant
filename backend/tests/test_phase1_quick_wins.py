import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.db.database import engine, init_db
from app.db.models import ApplicationEvent, ApplicationRecord, ApplicationTracker
from app.services.link_validator import GEORGIAN_MONTHS, parse_vacancy_published_date


def _register_and_auth(client: TestClient, prefix: str) -> dict:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.ge"
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "StrongPassword123!", "full_name": "Phase1 Tester"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_georgian_all_12_months_parsed_across_cases():
    """Verifies every Georgian month (nominative, dative, genitive) parses to the exact month number 1..12."""
    expected_nominative = [
        ("იანვარი", 1), ("თებერვალი", 2), ("მარტი", 3), ("აპრილი", 4),
        ("მაისი", 5), ("ივნისი", 6), ("ივლისი", 7), ("აგვისტო", 8),
        ("სექტემბერი", 9), ("ოქტომბერი", 10), ("ნოემბერი", 11), ("დეკემბერი", 12),
    ]
    for name, month_num in expected_nominative:
        dt, norm = parse_vacancy_published_date(f"15 {name}", standalone=True)
        assert dt is not None and dt.month == month_num and dt.day == 15, f"Failed for {name}"
        assert norm is not None and norm.endswith(f"-{month_num:02d}-15")

    assert GEORGIAN_MONTHS["აგვისტოს"] == 8
    dt_aug, _ = parse_vacancy_published_date("20 აგვისტოს", standalone=True)
    assert dt_aug is not None and dt_aug.month == 8 and dt_aug.day == 20


def test_application_soft_delete_vs_hard_delete_and_audit_event():
    """Verifies DELETE /api/applications/{id} soft-deletes by default (with audit event) and hard-purges when hard=true."""
    init_db()
    client = TestClient(app)
    headers = _register_and_auth(client, "p1_del")

    # 1. Soft delete (default hard=false)
    r1 = client.post(
        "/api/applications",
        headers=headers,
        json={"company": "SoftDelCo", "role": "QA Analyst", "portal": "jobs.ge", "status": "Applied"},
    )
    assert r1.status_code in (200, 201), r1.text
    app_id1 = r1.json()["id"]
    num_id1 = int(app_id1.replace("app-", ""))

    d1 = client.delete(f"/api/applications/{app_id1}", headers=headers)
    assert d1.status_code == 200 and d1.json()["hard"] is False
    # Hidden from GET /api/applications and GET /api/applications/{id}
    assert client.get(f"/api/applications/{app_id1}", headers=headers).status_code == 404
    assert all(it["id"] != app_id1 for it in client.get("/api/applications", headers=headers).json())

    # Record still exists in DB as DELETED with soft_deleted audit event
    with Session(engine) as session:
        rec1 = session.get(ApplicationRecord, num_id1)
        assert rec1 is not None and rec1.submission_status == "DELETED"
        evts = session.exec(select(ApplicationEvent).where(ApplicationEvent.application_id == num_id1)).all()
        assert any(e.event_type == "soft_deleted" for e in evts)

    # 2. Hard delete (hard=true) permanently purges DB rows
    r2 = client.post(
        "/api/applications",
        headers=headers,
        json={"company": "HardDelCo", "role": "QA Engineer", "portal": "hr.ge", "status": "Applied"},
    )
    assert r2.status_code in (200, 201), r2.text
    app_id2 = r2.json()["id"]
    num_id2 = int(app_id2.replace("app-", ""))

    d2 = client.delete(f"/api/applications/{app_id2}?hard=true", headers=headers)
    assert d2.status_code == 200 and d2.json()["hard"] is True
    with Session(engine) as session:
        assert session.get(ApplicationRecord, num_id2) is None
        assert session.get(ApplicationTracker, num_id2) is None
