import asyncio
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.db.database import engine, init_db
from app.db.models import JobPosting, UserJobMatch
from app.services.profile_service import profile_service
from app.services.matcher_service import matcher_service, skills_match_token
from app.services.cv_generator_service import cv_generator_service
from app.services.gemini_service import (
    GeminiService,
    is_free_openrouter_model,
    minimize_pii_for_llm,
)
from app.services.scrapers.base_scraper import (
    evaluate_remote_and_language_gate,
    is_georgia_country_location,
)
from app.services.scrapers.linkedin_scraper import LinkedInScraper
from app.services.scrapers.scraper_orchestrator import (
    canonical_title_company,
    normalize_job_url,
    scraper_orchestrator,
)


def _register_and_auth(client: TestClient, email: str):
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": "StrongPassword123!", "full_name": "Nino Kapanadze"},
    )
    if res.status_code == 200:
        token = res.json()["access_token"]
    else:
        login = client.post("/api/auth/login", json={"email": email, "password": "StrongPassword123!"})
        assert login.status_code == 200
        token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_non_it_accountant_profile_date_experience_and_cv_generation():
    accountant_md = """# Nino Kapanadze — Senior Financial Accountant
Email: nino.kapanadze@example.ge
Phone: +995 599 11 22 33
Location: Tbilisi, Georgia

## Professional Summary
Experienced accountant specializing in IFRS reporting, tax compliance, payroll, and audit coordination.

## Core Skills
- IFRS, Financial Reporting, Tax Compliance, Excel, 1C Accounting, Oris, Payroll, Jira

## Work Experience
### Senior Accountant | TBC Partner Audit | 2018 – Present
- Managed monthly IFRS financial statements and Georgian tax declarations (RS.ge) for 14 corporate clients.
- Coordinated annual statutory audits and reconciled multi-currency ledgers in Excel and 1C Accounting.

## Languages
- Georgian (Native)
- English (C1)
"""
    extracted = profile_service.extract_structured_profile(accountant_md)
    assert extracted.target_industry == "finance_accounting"
    assert extracted.experience_years is not None and extracted.experience_years >= 6.0
    assert extracted.seniority_level in ("SENIOR", "LEAD")
    assert extracted.max_allowed_years is not None and extracted.max_allowed_years >= 8.0

    # Ensure token-boundary skill matching prevents substring false hits
    assert not skills_match_token("HR", ["Chrome", "Charting"])
    assert not skills_match_token("BI", ["Billing"])
    assert skills_match_token("IFRS", ["IFRS", "Excel"])

    # Verify non-IT CV uses Core Competencies heading & non-IT cover letter avoids engineering leak
    pkg = cv_generator_service.prepare_email_application_package(
        job_title="Senior Accountant",
        company="Liberty Finance",
        description="Looking for a Senior Accountant experienced in IFRS, Excel, Tax Compliance, and SAP FICO.",
        portal="jobs.ge",
        cv_language="en",
        skills_md_override=accountant_md,
    )
    rendered_html = pkg.get("rendered_html") or ""
    assert "CORE COMPETENCIES" in rendered_html
    assert "TECHNICAL SKILLS" not in rendered_html
    assert "engineering foundation" not in (pkg.get("motivational_letter") or "").lower()
    assert "engineering foundation" not in (pkg.get("cover_letter") or "").lower()
    assert isinstance(pkg.get("matched_skills"), list)
    assert isinstance(pkg.get("missing_skills"), list)


def test_ai_provider_free_tier_guard_pii_minimization_and_fallback(monkeypatch):
    # 1. PII minimization redacts direct identifiers while keeping professional content
    raw = "Contact jane.doe@corp.ge or +995 599 123 456, IBAN GE29NB0000000101904917, ID 01024012345. Skills: IFRS, SQL."
    sanitized = minimize_pii_for_llm(raw)
    assert "jane.doe@corp.ge" not in sanitized
    assert "599 123 456" not in sanitized
    assert "GE29NB0000000101904917" not in sanitized
    assert "01024012345" not in sanitized
    assert "IFRS, SQL" in sanitized

    # 2. Paid OpenRouter model is blocked when AI_ALLOW_PAID_FALLBACK=false
    assert is_free_openrouter_model("google/gemma-3-27b-it:free") is True
    assert is_free_openrouter_model("openai/gpt-4o") is False

    svc = GeminiService(
        api_key="",
        openrouter_api_key="or-test-key",
        provider_mode="openrouter",
        allow_paid_fallback=False,
    )
    svc.openrouter_model = "openai/gpt-4o"
    svc.openrouter_fast_model = "openai/gpt-4o"
    assert svc.openrouter_available is False

    # 3. Auto fallback from rate-limited Gemini to free OpenRouter model
    svc_fb = GeminiService(
        api_key="",
        openrouter_api_key="or-test-key",
        provider_mode="auto",
        allow_paid_fallback=False,
    )
    svc_fb._client = object()  # simulate configured primary Gemini client
    svc_fb.openrouter_fast_model = "meta-llama/llama-3.3-70b-instruct:free"

    def _fail_gemini(*args, **kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    def _ok_openrouter(*args, **kwargs):
        return ('{"ok": true, "provider": "openrouter_free"}', 12, 8, 20, 0.0, 0)

    monkeypatch.setattr(svc_fb, "_call_gemini_with_retry", _fail_gemini)
    monkeypatch.setattr(svc_fb, "_call_openrouter_with_retry", _ok_openrouter)

    parsed = svc_fb.generate_json("Return status json", task_type="test_fallback", use_cache=False)
    assert parsed == {"ok": True, "provider": "openrouter_free"}
    health = svc_fb.get_provider_health()
    assert health["last_provider_used"] == "openrouter"
    assert health["free_tier_guard_enforced"] is True


def test_georgia_us_state_vs_country_and_linkedin_tos_safe_default(monkeypatch):
    assert is_georgia_country_location("tbilisi, georgia") is True
    assert is_georgia_country_location("atlanta, georgia, united states") is False
    assert is_georgia_country_location("savannah, ga") is False

    _, status_us, _, _ = evaluate_remote_and_language_gate(
        title="Financial Analyst",
        description="On-site role in Atlanta, Georgia, United States.",
        location_text="Atlanta, Georgia, United States",
        portal="linkedin.com",
    )
    assert status_us == "FILTERED_OUT"

    _, status_ge, _, _ = evaluate_remote_and_language_gate(
        title="Financial Analyst",
        description="Office role in Tbilisi, Georgia.",
        location_text="Tbilisi, Georgia",
        portal="linkedin.com",
    )
    assert status_ge == "DISCOVERED"

    # LinkedIn public scrape disabled by default
    monkeypatch.setenv("ENABLE_LINKEDIN_PUBLIC_SCRAPE", "false")
    li = LinkedInScraper()
    assert asyncio.run(li.scrape(allow_network=True)) == []

    # Account Manager is not rejected as a senior engineering title
    sample_html = """
    <div class="job-search-card">
      <h3 class="base-search-card__title">Account Manager</h3>
      <h4 class="base-search-card__subtitle">Global Corp</h4>
      <span class="job-search-card__location">Tbilisi, Georgia</span>
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/123456789?trk=abc">View</a>
    </div>
    """
    cards = li.parse_html_listings(sample_html, max_allowed_years=2.0)
    assert len(cards) == 1
    assert cards[0]["status"] == "DISCOVERED"
    assert cards[0]["market"] == "GE_DOMESTIC"


def test_cross_source_deduplication_and_job_search_sorting_and_health():
    init_db()
    assert normalize_job_url("https://www.Jobs.ge/ge/?view=jobs&id=101&utm_source=fb") == normalize_job_url(
        "http://jobs.ge/ge/?id=101&view=jobs"
    )
    assert canonical_title_company("Financial Analyst!", "TBC Bank") == ("financial analyst", "tbc bank")
    assert canonical_title_company("Analyst", "Hiring Company") is None

    client = TestClient(app)
    health_res = client.get("/api/health")
    assert health_res.status_code == 200
    assert "ai" in health_res.json()

    headers = _register_and_auth(client, "search_refactor_test@example.ge")
    src_res = client.get("/api/jobs/sources/health", headers=headers)
    assert src_res.status_code == 200
    portals = [s["portal"] for s in src_res.json().get("sources", [])]
    assert "jobs.ge" in portals and "greenhouse.io" in portals

    # Upload Accountant profile so jobs endpoint is unlocked for this user
    up = client.post(
        "/api/skills-md",
        headers=headers,
        json={"content": "# Nino Kapanadze — Financial Analyst\n## Skills\n- IFRS, Excel, SQL, Financial Modeling\n"},
    )
    assert up.status_code == 200
    me = client.get("/api/auth/me", headers=headers).json()
    uid = me["id"]

    with Session(engine) as session:
        j1 = JobPosting(
            user_id=uid,
            portal="jobs.ge",
            external_id="refactor-search-1",
            title="Accountant IFRS Specialist",
            company="Alpha Finance",
            url="https://jobs.ge/ge/?view=jobs&id=990001",
            market="GE_DOMESTIC",
            is_remote=False,
            salary_min=2000,
            salary_max=2500,
            salary_currency="GEL",
            description_raw="Full-time Senior IFRS accounting role using Excel and SQL in Tbilisi.",
            suitability_score=82.0,
            match_tier="DIRECT",
            status="STAGED",
        )
        j2 = JobPosting(
            user_id=uid,
            portal="remotive.com",
            external_id="refactor-search-2",
            title="Remote Financial Analyst",
            company="Beta Global",
            url="https://remotive.com/remote-jobs/finance/990002",
            market="GLOBAL_REMOTE",
            is_remote=True,
            salary_min=4500,
            salary_max=5500,
            salary_currency="USD",
            description_raw="Remote contract role for Financial Modeling, IFRS, and SQL analytics.",
            suitability_score=88.0,
            match_tier="DIRECT",
            status="STAGED",
        )
        session.add(j1)
        session.add(j2)
        session.flush()
        session.add(UserJobMatch(user_id=uid, job_posting_id=j1.id, suitability_score=82.0, match_score=82.0, status="STAGED"))
        session.add(UserJobMatch(user_id=uid, job_posting_id=j2.id, suitability_score=88.0, match_score=88.0, status="STAGED"))
        session.commit()

    # Multi-keyword token AND search across title + description
    r_search = client.get("/api/jobs?search=Accountant+SQL", headers=headers)
    assert r_search.status_code == 200
    titles = [it["title"] for it in r_search.json()["items"]]
    assert "Accountant IFRS Specialist" in titles

    # Salary descending sort puts Beta Global ($4500) before Alpha Finance (2000 GEL)
    r_sort = client.get("/api/jobs?search=IFRS&sort_by=salary_desc", headers=headers)
    assert r_sort.status_code == 200
    items = r_sort.json()["items"]
    assert len(items) >= 2
    assert items[0]["company"] == "Beta Global"
