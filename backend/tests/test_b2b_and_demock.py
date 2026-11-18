import pytest
import httpx
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.services.gmail_service import gmail_service
import app.services.gmail_service as gmail_mod
from app.services.scrapers.base_scraper import classify_georgia_b2b_suitability
from app.services.scrapers.remote_b2b_scrapers import (
    RemotiveScraper,
    HimalayasScraper,
    RemoteOkScraper,
)
from app.db.database import engine, init_db
from app.db.models import JobPosting, User, UserJobMatch
from app.services.auth_service import create_access_token, hash_password, get_user_by_email

client = TestClient(app)


def test_b2b_tax_calculator_under_and_over_500k_cap():
    # Under 500k GEL/year: $3,000 USD/month * 2.72 * 12 = 97,920 GEL (< 500k) -> 1% tax
    res_under = client.post(
        "/api/b2b/tax-calculator",
        json={
            "amount": 3000,
            "currency": "USD",
            "billing_period": "monthly",
            "hours_per_month": 160,
            "custom_fx_to_gel": 2.72,
            "transfer_fee_pct": 0.5,
        },
    )
    assert res_under.status_code == 200
    d1 = res_under.json()
    assert d1["under_500k_cap"] is True
    assert d1["b2b_small_business"]["tax_rate_pct"] == 1.0
    assert d1["b2b_small_business"]["net_gel"] > d1["standard_labor_contract"]["net_gel"]
    assert d1["monthly_b2b_advantage_gel"] > 1000

    # Above 500k GEL/year: $20,000 USD/month * 2.72 * 12 = 652,800 GEL (> 500k) -> 3% tax
    res_over = client.post(
        "/api/b2b/tax-calculator",
        json={
            "amount": 20000,
            "currency": "USD",
            "billing_period": "monthly",
            "custom_fx_to_gel": 2.72,
        },
    )
    assert res_over.status_code == 200
    d2 = res_over.json()
    assert d2["under_500k_cap"] is False
    assert d2["b2b_small_business"]["tax_rate_pct"] == 3.0


def test_timezone_matrix_and_b2b_proposal():
    init_db()
    tz_res = client.get("/api/b2b/timezone-matrix?work_start_get=11&work_end_get=19")
    assert tz_res.status_code == 200
    tz_data = tz_res.json()
    assert "Tbilisi" in tz_data["base_timezone"]
    assert len(tz_data["regions"]) >= 5

    with Session(engine) as session:
        u = get_user_by_email(session, "b2b.tester@example.com")
        if not u:
            u = User(
                email="b2b.tester@example.com",
                hashed_password=hash_password("TestPass123!"),
                full_name="B2B Tester",
                is_active=True,
            )
            session.add(u)
            session.commit()
            session.refresh(u)
        uid = u.id

    token = create_access_token({"sub": "b2b.tester@example.com", "user_id": uid})
    headers = {"Authorization": f"Bearer {token}"}
    prop_en = client.post(
        "/api/b2b/proposal",
        headers=headers,
        json={
            "target_role": "QA Automation Engineer",
            "target_company": "NordicCloud",
            "client_region": "EU (CET)",
            "contract_rate": "$40/hr B2B",
            "requirements_snippet": "Playwright, Python, REST API testing",
            "language": "en",
        },
    )
    assert prop_en.status_code == 200
    body_en = prop_en.json()
    assert "proposal_text" in body_en and len(body_en["proposal_text"]) > 80
    assert "NordicCloud" in body_en["proposal_text"]

    prop_ka = client.post(
        "/api/b2b/proposal",
        headers=headers,
        json={
            "target_role": "QA Engineer",
            "target_company": "NordicCloud",
            "language": "ka",
        },
    )
    assert prop_ka.status_code == 200
    assert len(prop_ka.json()["proposal_text"]) > 50


def test_classify_georgia_b2b_suitability():
    ge_local = classify_georgia_b2b_suitability(
        portal="jobs.ge",
        location_text="Tbilisi",
        description="Junior QA Engineer in Tbilisi",
        market="GE_DOMESTIC",
    )
    assert ge_local["contract_mode"] == "GE_LOCAL"
    assert ge_local["georgia_eligible"] is True

    global_b2b = classify_georgia_b2b_suitability(
        portal="remotive.com",
        location_text="Worldwide / EMEA",
        description="Remote B2B Contractor role open to EMEA candidates",
        market="GLOBAL_REMOTE",
    )
    assert global_b2b["contract_mode"] == "REMOTE_B2B"
    assert global_b2b["georgia_eligible"] is True

    us_only = classify_georgia_b2b_suitability(
        portal="remoteok.com",
        location_text="US Only",
        description="Must be authorized to work in the United States. W2 only.",
        market="GLOBAL_REMOTE",
    )
    assert us_only["contract_mode"] == "REGION_LOCKED"
    assert us_only["georgia_eligible"] is False


def test_gmail_dispatch_real_eml_fallback_and_oauth_not_simulated(monkeypatch):
    # OAuth endpoint must not emit fake simulated_local_google_oauth_code when unconfigured
    res = client.get("/api/auth/google/login")
    if res.status_code == 200:
        assert "simulated" not in str(res.json()).lower()
    else:
        assert res.status_code == 400

    # Unconfigured dispatch writes a real .eml artifact instead of claiming simulated success
    monkeypatch.setattr(gmail_mod, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(gmail_mod, "GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setattr(
        gmail_mod,
        "get_smtp_config",
        lambda: {"configured": False, "smtp_user": "", "smtp_pass": "", "smtp_host": "", "smtp_port": 465},
    )

    dummy_user = User(email="candidate@example.com", hashed_password="x", full_name="Candidate", gmail_oauth_token=None)
    dispatch = gmail_service.dispatch_email(
        user=dummy_user,
        recipient_email="hr@example.com",
        subject="QA Engineer Application",
        body_text="Hello hiring team, attached is my CV.",
        mode="send",
    )
    assert dispatch["status"] == "needs_transport"
    assert dispatch["simulated"] is False
    assert dispatch.get("eml_filename", "").endswith(".eml")
    assert dispatch.get("eml_url", "").startswith("/api/resumes/generated/")
    eml_dl = client.get(dispatch["eml_url"])
    assert eml_dl.status_code == 200
    assert "QA Engineer Application" in eml_dl.text


def test_user_job_match_isolation():
    init_db()
    with Session(engine) as session:
        u1 = get_user_by_email(session, "iso_a@example.com")
        if not u1:
            u1 = User(
                email="iso_a@example.com",
                hashed_password=hash_password("TestPass123!"),
                full_name="Iso A",
                is_active=True,
            )
            session.add(u1)
            session.commit()
            session.refresh(u1)

        u2 = get_user_by_email(session, "iso_b@example.com")
        if not u2:
            u2 = User(
                email="iso_b@example.com",
                hashed_password=hash_password("TestPass123!"),
                full_name="Iso B",
                is_active=True,
            )
            session.add(u2)
            session.commit()
            session.refresh(u2)

        job = session.exec(
            select(JobPosting).where(JobPosting.external_id == "iso-test-job-1")
        ).first()
        if not job:
            job = JobPosting(
                portal="remotive.com",
                external_id="iso-test-job-1",
                title="Remote Python QA Engineer",
                company="IsoCorp",
                url="https://remotive.com/remote-jobs/qa/iso-test-job-1",
                market="GLOBAL_REMOTE",
                is_remote=True,
                description_raw="Worldwide remote contractor QA Python Playwright",
                status="DISCOVERED",
                suitability_score=50.0,
            )
            session.add(job)
            session.commit()
            session.refresh(job)

        for uid, score, st in [(u1.id, 91.0, "STAGED"), (u2.id, 66.0, "AUDITED")]:
            existing_m = session.exec(
                select(UserJobMatch).where(
                    UserJobMatch.user_id == uid,
                    UserJobMatch.job_posting_id == job.id,
                )
            ).first()
            if existing_m:
                existing_m.suitability_score = score
                existing_m.status = st
                session.add(existing_m)
            else:
                session.add(
                    UserJobMatch(
                        user_id=uid,
                        job_posting_id=job.id,
                        suitability_score=score,
                        status=st,
                        match_tier="DIRECT",
                    )
                )
        u1_id = u1.id
        u2_id = u2.id
        session.commit()

    # Upload profiles for iso_a and iso_b so /api/jobs feed is unlocked for both
    tok_a = create_access_token({"sub": "iso_a@example.com", "user_id": u1_id})
    tok_b = create_access_token({"sub": "iso_b@example.com", "user_id": u2_id})
    client.post(
        "/api/profile/upload-skills",
        data={"content": "# QA Engineer\n- Playwright, Python", "run_live_scrape": "false"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    client.post(
        "/api/profile/upload-skills",
        data={"content": "# QA Engineer\n- Playwright, Python", "run_live_scrape": "false"},
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    # Re-pin their isolated UserJobMatch scores after upload rescore
    with Session(engine) as session:
        job = session.exec(select(JobPosting).where(JobPosting.external_id == "iso-test-job-1")).first()
        for uid, score, st in [(u1_id, 91.0, "STAGED"), (u2_id, 66.0, "AUDITED")]:
            m = session.exec(
                select(UserJobMatch).where(UserJobMatch.user_id == uid, UserJobMatch.job_posting_id == job.id)
            ).first()
            if m:
                m.suitability_score = score
                m.status = st
                session.add(m)
        session.commit()

    res_a = client.get("/api/jobs?search=IsoCorp&min_score=60", headers={"Authorization": f"Bearer {tok_a}"})
    res_b = client.get("/api/jobs?search=IsoCorp&min_score=60", headers={"Authorization": f"Bearer {tok_b}"})
    assert res_a.status_code == 200 and res_b.status_code == 200
    items_a = res_a.json()["items"]
    items_b = res_b.json()["items"]
    assert items_a[0]["suitability_score"] == 91.0
    assert items_a[0]["status"] == "STAGED"
    assert items_b[0]["suitability_score"] == 66.0
    assert items_b[0]["status"] == "AUDITED"


@pytest.mark.asyncio
async def test_remote_b2b_scrapers_deterministic_parsing(monkeypatch):
    class _FakeResp:
        def __init__(self, data):
            self.status_code = 200
            self._data = data

        def json(self):
            return self._data

    async def fake_get(self, url, **kwargs):
        url_s = str(url)
        if "remotive.com" in url_s:
            return _FakeResp({
                "jobs": [{
                    "id": 101,
                    "title": "QA Automation Engineer",
                    "company_name": "RemoteCo",
                    "candidate_required_location": "Worldwide",
                    "job_type": "full_time",
                    "salary": "$4,000/mo",
                    "url": "https://remotive.com/job/101",
                    "description": "<p>Playwright and Python API automation testing.</p>",
                }]
            })
        if "himalayas.app" in url_s:
            return _FakeResp({
                "jobs": [{
                    "title": "Software Tester (SDET)",
                    "companyName": "CloudCo",
                    "companySlug": "cloudco",
                    "locationRestrictions": ["EMEA"],
                    "timezoneRestrictions": [1, 2, 4],
                    "minSalary": 45000,
                    "maxSalary": 60000,
                    "currency": "USD",
                    "guid": "https://himalayas.app/jobs/cloudco/sdet?ref=1",
                    "description": "Selenium and Pytest automation.",
                }]
            })
        if "remoteok.com" in url_s:
            return _FakeResp([
                {"legal": "header"},
                {
                    "id": "999",
                    "position": "Python QA Contractor",
                    "company": "B2BStudio",
                    "location": "Anywhere",
                    "tags": ["python", "qa", "playwright"],
                    "salary_min": 50000,
                    "salary_max": 70000,
                    "url": "/remote-jobs/999",
                    "description": "Async Playwright contractor role.",
                },
            ])
        return _FakeResp({})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    r1 = await RemotiveScraper().scrape(allow_network=True, domain_keywords=["qa", "playwright"], candidate_languages=["en"])
    r2 = await HimalayasScraper().scrape(allow_network=True, domain_keywords=["sdet", "selenium"], candidate_languages=["en"])
    r3 = await RemoteOkScraper().scrape(allow_network=True, domain_keywords=["qa", "python"], candidate_languages=["en"])

    assert len(r1) == 1 and r1[0]["portal"] == "remotive.com" and r1[0]["market"] == "GLOBAL_REMOTE"
    assert len(r2) == 1 and r2[0]["portal"] == "himalayas.app" and "45000-60000 USD" in r2[0]["description_raw"]
    assert len(r3) == 1 and r3[0]["portal"] == "remoteok.com" and r3[0]["url"] == "https://remoteok.com/remote-jobs/999"
