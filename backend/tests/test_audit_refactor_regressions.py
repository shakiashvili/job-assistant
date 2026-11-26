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


def test_jobs_ge_published_date_parsing_and_newest_sort_and_recency_filter():
    from datetime import datetime, timedelta, timezone
    from app.services.link_validator import parse_vacancy_published_date
    from app.services.scrapers.jobs_ge_scraper import JobsGeScraper

    dt_ka, norm_ka = parse_vacancy_published_date("24 ნოემბერი", standalone=True)
    assert dt_ka is not None and dt_ka.month == 11 and dt_ka.day == 24
    assert norm_ka is not None and norm_ka.endswith("-11-24")

    dt_iso, norm_iso = parse_vacancy_published_date("2026-11-24T09:30:00Z", standalone=True)
    assert dt_iso is not None and norm_iso == "2026-11-24"

    dt_yest, _ = parse_vacancy_published_date("Yesterday", standalone=True)
    assert dt_yest is not None

    sample_html = """
    <table id="job_list_table">
      <tr><th></th><th>Title</th><th></th><th>Company</th><th>Published</th><th>Deadline</th></tr>
      <tr>
        <td></td>
        <td><a class="vip" href="/ge/?view=jobs&id=777123">ხარისხის უზრუნველყოფის სპეციალისტი NEW</a></td>
        <td></td>
        <td><a href="/ge/?view=client&client=procredit">პროკრედიტ ბანკი</a></td>
        <td>24 ნოემბერი</td>
        <td>24 დეკემბერი</td>
      </tr>
    </table>
    """
    listings = JobsGeScraper().parse_html_listings(sample_html)
    assert len(listings) == 1
    assert listings[0]["title"] == "ხარისხის უზრუნველყოფის სპეციალისტი"
    assert listings[0]["published_at"] is not None
    assert listings[0]["posting_date"].endswith("-11-24")
    assert listings[0]["deadline_text"] == "24 დეკემბერი"

    init_db()
    client = TestClient(app)
    headers = _register_and_auth(client, "recency_sort_test@example.ge")
    up = client.post(
        "/api/skills-md",
        headers=headers,
        json={"content": "# Giorgi QA — Junior QA Engineer\n## Skills\n- Playwright, Python, SQL, Manual Testing, REST API\n"},
    )
    assert up.status_code == 200
    uid = client.get("/api/auth/me", headers=headers).json()["id"]
    now = datetime.now(timezone.utc)
    old_dt = now - timedelta(days=11)
    fresh_dt = now - timedelta(hours=6)

    with Session(engine) as session:
        j_old = JobPosting(
            user_id=uid,
            portal="jobs.ge",
            external_id="recency-old-1",
            title="Legacy QA Automation Role",
            company="OldCorp",
            url="https://jobs.ge/ge/?view=jobs&id=991001",
            market="GE_DOMESTIC",
            is_remote=False,
            description_raw="Playwright Python QA testing role.",
            suitability_score=95.0,
            match_tier="DIRECT",
            status="STAGED",
            published_at=old_dt,
            posting_date=old_dt.strftime("%Y-%m-%d"),
        )
        j_new = JobPosting(
            user_id=uid,
            portal="jobs.ge",
            external_id="recency-new-1",
            title="Fresh QA Testing Specialist",
            company="NewBank",
            url="https://jobs.ge/ge/?view=jobs&id=991002",
            market="GE_DOMESTIC",
            is_remote=False,
            description_raw="Manual QA testing SQL REST API role.",
            suitability_score=80.0,
            match_tier="DIRECT",
            status="STAGED",
            published_at=fresh_dt,
            posting_date=fresh_dt.strftime("%Y-%m-%d"),
        )
        session.add(j_old)
        session.add(j_new)
        session.flush()
        session.add(UserJobMatch(user_id=uid, job_posting_id=j_old.id, suitability_score=95.0, match_score=95.0, status="STAGED"))
        session.add(UserJobMatch(user_id=uid, job_posting_id=j_new.id, suitability_score=80.0, match_score=80.0, status="STAGED"))
        session.commit()

    # Default sort is newest posted (fresh job before higher-scoring 11-day-old job)
    r_newest = client.get("/api/jobs?search=QA", headers=headers)
    assert r_newest.status_code == 200
    newest_titles = [it["title"] for it in r_newest.json()["items"]]
    assert newest_titles.index("Fresh QA Testing Specialist") < newest_titles.index("Legacy QA Automation Role")

    # posted_within_days=3 excludes the 11-day-old posting
    r_3d = client.get("/api/jobs?search=QA&posted_within_days=3", headers=headers)
    assert r_3d.status_code == 200
    recent_titles = [it["title"] for it in r_3d.json()["items"]]
    assert "Fresh QA Testing Specialist" in recent_titles
    assert "Legacy QA Automation Role" not in recent_titles


def test_hiring_perspective_experience_domain_language_and_education_matching():
    from app.services.matcher_service import matcher_service

    parsed_entry_qa = {
        "target_industry": "qa_tech",
        "detected_industry": "QA & Software Testing",
        "primary_role": "Junior QA Engineer",
        "years_of_experience": 0.5,
        "max_allowed_years": 1.0,
        "eligible_internships": True,
        "all_skills": ["Manual Testing", "Playwright", "Python", "SQL", "REST API", "Jira", "Postman"],
        "spoken_languages": ["Georgian (Native)", "English (C1)"],
        "education": [
            {
                "degree": "Bachelor of Business Analytics and Computer Science",
                "field_of_study": "Data Analytics, Economics, Statistics, Software Engineering",
                "institution": "TSU",
            }
        ],
    }

    # 1. Must reject 2+ years requirement (EN & KA) for entry-level candidate
    res_2yr_en = matcher_service.evaluate_job_tiered(
        title="QA Engineer",
        description="Requirements: minimum 2+ years of commercial QA experience with Playwright and SQL.",
        parsed_skills=parsed_entry_qa,
        portal="jobs.ge",
    )
    assert res_2yr_en["status"] == "FILTERED_OUT"

    res_2yr_ka = matcher_service.evaluate_job_tiered(
        title="ხარისხის უზრუნველყოფის სპეციალისტი",
        description="მოთხოვნები: მინიმუმ 2 წელი სამუშაო გამოცდილება QA ტესტირებაში და SQL-ში.",
        parsed_skills=parsed_entry_qa,
        portal="jobs.ge",
    )
    assert res_2yr_ka["status"] == "FILTERED_OUT"

    # 2. Must reject Customer Service & foreign-language-gated non-QA roles
    res_cs = matcher_service.evaluate_job_tiered(
        title="Customer Service Representative",
        description="Handle inbound calls, live chat inquiries, and customer complaints in our call center.",
        parsed_skills=parsed_entry_qa,
        portal="jobs.ge",
    )
    assert res_cs["status"] == "FILTERED_OUT"

    res_it_lang = matcher_service.evaluate_job_tiered(
        title="იტალიურენოვანი მომხმარებელთა მრჩეველი",
        description="მომხმარებელთა კონსულტაცია იტალიურ ენაზე.",
        parsed_skills=parsed_entry_qa,
        portal="jobs.ge",
    )
    assert res_it_lang["status"] == "FILTERED_OUT"

    # 3. Must accept Georgian entry-level QA Specialist (e.g. ProCredit Bank)
    res_procredit = matcher_service.evaluate_job_tiered(
        title="ხარისხის უზრუნველყოფის სპეციალისტი",
        description="პროგრამული უზრუნველყოფის ტესტირება, ტესტ-ქეისების შედგენა, REST API და SQL შემოწმება, Jira.",
        parsed_skills=parsed_entry_qa,
        portal="jobs.ge",
    )
    assert res_procredit["status"] != "FILTERED_OUT"
    assert res_procredit["suitability_score"] >= 60.0

    # 4. Must accept education-aligned internship / graduate role
    res_edu_intern = matcher_service.evaluate_job_tiered(
        title="ბიზნეს ანალიტიკის სტაჟიორი (Graduate Internship)",
        description="სტაჟირება ეკონომიკის, სტატისტიკის და მონაცემთა ანალიტიკის სტუდენტებისთვის და კურსდამთავრებულებისთვის.",
        parsed_skills=parsed_entry_qa,
        portal="jobs.ge",
    )
    assert res_edu_intern["status"] != "FILTERED_OUT"
    assert res_edu_intern["match_tier"] == "ADJACENT"
    assert "Public Sector" not in (res_edu_intern["adjacent_role_tag"] or "")


def test_legacy_pre_alembic_database_adopted_cleanly_by_migrations(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlmodel import SQLModel
    from app.config import BASE_DIR

    legacy_db = tmp_path / "legacy_pre_alembic.db"
    db_url = f"sqlite:///{legacy_db}"
    eng = create_engine(db_url)
    SQLModel.metadata.create_all(eng)
    # Simulate a pre-Alembic DB that has users + job_postings tables without alembic_version or published_at
    with eng.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_job_postings_published_at"))
        conn.execute(text("ALTER TABLE job_postings DROP COLUMN published_at"))
    eng.dispose()

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)

    # Stamp base revision just like init_db() does for legacy pre-Alembic DBs, then upgrade to head
    command.stamp(cfg, "75cd228268f5")
    command.upgrade(cfg, "head")

    eng_after = create_engine(db_url)
    insp = inspect(eng_after)
    cols = {c["name"] for c in insp.get_columns("job_postings")}
    assert "published_at" in cols
    assert "alembic_version" in set(insp.get_table_names())
    eng_after.dispose()


def test_multi_industry_query_builder_covers_all_jobs_ge_categories_and_portals():
    from app.services.scrapers.query_builder import build_search_queries

    cases = [
        ("finance_accounting", "Financial Analyst", "cid=3", "keywords=Finance"),
        ("marketing_growth", "Digital Marketing Specialist", "cid=4", "primary_keyword=Marketing"),
        ("logistics_supply_chain", "Logistics Coordinator", "cid=5", "keywords=Logistics"),
        ("hr_recruiting", "HR Generalist", "cid=1", "primary_keyword=HR"),
        ("public_admin_legal", "Legal Counsel", "cid=7", "keywords=Legal"),
        ("healthcare_hospital", "Clinical Coordinator", "cid=8", None),
        ("receptionist_hospitality", "Front Desk Receptionist", "cid=10", None),
    ]
    for ind, role, expected_cid, expected_djinni in cases:
        cfg = build_search_queries({"target_industry": ind, "primary_role": role, "years_of_experience": 1.5}, headline=role)
        assert any(expected_cid in u for u in cfg["jobs_ge_urls"]), f"{ind} missing {expected_cid}"
        assert any("area=28" in u and "order_by=publication_time" in u for u in cfg["headhunter_urls"])
        assert any("Tbilisi%2C+Georgia" in u for u in cfg["linkedin_urls"])
        if expected_djinni:
            assert expected_djinni in (cfg["djinni_url"] or "")


def test_hr_ge_ng_state_and_dou_ukrainian_date_and_word_boundary_matching():
    from app.services.scrapers.base_scraper import matches_domain_keywords, parse_portal_published_at
    from app.services.scrapers.hr_ge_scraper import HrGeScraper

    # Word boundary safety
    assert matches_domain_keywords("Senior QA Automation Engineer", ["qa"]) is True
    assert matches_domain_keywords("Equal Opportunity Manager", ["qa"]) is False
    assert matches_domain_keywords("Three Years Operations Lead", ["hr"]) is False
    assert matches_domain_keywords("HR Business Partner", ["hr"]) is True

    # Ukrainian/Russian & millisecond epoch date parsing
    dt_ua, str_ua = parse_portal_published_at("18 листопада")
    assert dt_ua is not None and dt_ua.month == 11 and dt_ua.day == 18 and str_ua.endswith("-11-18")
    dt_ms, str_ms = parse_portal_published_at(1795521600000)
    assert dt_ms is not None and str_ms is not None

    # HR.ge Angular ng-state JSON extraction
    ng_html = """<html><body><script id="ng-state" type="application/json">
    {"items":[{"announcementId":503759,"title":"ფინანსური ანალიტიკოსი","customerName":"TBC Bank","publishDate":"2026-11-24T13:09:21.107","deadlineDate":"2026-12-23T19:59:00","locations":["თბილისი"]}]}
    </script></body></html>"""
    parsed = HrGeScraper().parse_html_listings(ng_html, domain_keywords=["ფინანს", "finance"])
    assert len(parsed) == 1
    assert parsed[0]["company"] == "TBC Bank"
    assert parsed[0]["posting_date"] == "2026-11-24"
    assert parsed[0]["published_at"] is not None


def test_multi_industry_off_domain_matching_excludes_unrelated_professions():
    from app.services.matcher_service import matcher_service

    finance_profile = {
        "target_industry": "finance_accounting",
        "primary_role": "Financial Analyst",
        "verified_skills": ["IFRS", "Financial Modeling", "Excel", "Audit", "SQL"],
        "years_of_experience": 1.5,
        "max_allowed_years": 2.0,
        "spoken_languages": ["English", "Georgian"],
        "education": [{"degree": "BSc", "field_of_study": "Finance and Economics"}],
    }
    res_nurse = matcher_service.evaluate_job_tiered(
        title="Clinic Nurse / ექთანი",
        description="Patient intake, clinical nursing care, blood sampling.",
        parsed_skills=finance_profile,
        portal="jobs.ge",
    )
    assert res_nurse["status"] == "FILTERED_OUT"

    res_swe = matcher_service.evaluate_job_tiered(
        title="Backend Software Engineer (Go/Kubernetes)",
        description="Build microservices in Go, Docker, Kubernetes.",
        parsed_skills=finance_profile,
        portal="jobs.ge",
    )
    assert res_swe["status"] == "FILTERED_OUT"

    res_fin = matcher_service.evaluate_job_tiered(
        title="Junior Financial Analyst",
        description="Prepare IFRS financial reports, Excel financial modeling, audit support.",
        parsed_skills=finance_profile,
        portal="jobs.ge",
    )
    assert res_fin["status"] != "FILTERED_OUT"
    assert res_fin["suitability_score"] >= 70.0


def test_top_one_percent_cv_adaptive_skill_buckets_and_ats_pass_multi_industry(tmp_path):
    from app.services.cv_generator_service import CVGeneratorService, group_skills_into_ats_buckets

    fin_buckets = group_skills_into_ats_buckets(
        ["IFRS", "Financial Modeling", "Audit", "Excel", "1C", "SQL", "Risk Controls"],
        cv_language="en",
        headline="Financial Analyst",
    )
    fin_titles = [b[0] for b in fin_buckets]
    assert "Financial Reporting & Analysis" in fin_titles
    assert "Accounting, ERP & BI Systems" in fin_titles
    assert not any("Test Automation" in t for t in fin_titles)

    mkt_buckets = group_skills_into_ats_buckets(
        ["SEO", "Google Ads", "Content Marketing", "GA4", "HubSpot"],
        cv_language="en",
        headline="Digital Marketing Specialist",
    )
    assert any("Acquisition" in b[0] for b in mkt_buckets)
    assert any("Analytics" in b[0] for b in mkt_buckets)

    # Full PDF + DOCX + HTML render + deterministic ATS check for non-IT Financial Analyst
    svc = CVGeneratorService()
    vault = {
        "candidate": {
            "full_name": "Nino Beridze",
            "headline": "Financial Analyst",
            "email": "nino.beridze@example.ge",
            "phone": "+995 599 123 456",
            "location": {"city": "Tbilisi", "country": "Georgia"},
            "links": {"linkedin": "https://linkedin.com/in/nino-beridze"},
            "languages": [{"language": "Georgian", "proficiency": "Native"}, {"language": "English", "proficiency": "C1"}],
        },
        "skills": {"core": ["IFRS", "Financial Modeling", "Audit", "Excel", "1C", "Power BI", "Budgeting"]},
        "work_history": [
            {
                "role": "Junior Financial Analyst",
                "company": "Credo Bank",
                "location": "Tbilisi, Georgia",
                "start_date": "2024-06",
                "end_date": "Present",
                "highlights": [
                    "Built automated monthly IFRS P&L and cash-flow variance models in Excel and Power BI.",
                    "Reconciled 1,200+ monthly ledger entries in 1C with 99.8% audit accuracy.",
                ],
            }
        ],
        "education": [{"degree": "BSc in Finance", "institution": "Tbilisi State University", "dates": "2020 - 2024", "gpa": "3.8/4.0"}],
        "projects": [],
        "certifications": ["ACCA Financial Accounting (FA)"],
        "_parsed_skills": {"target_industry": "finance_accounting", "primary_role": "Financial Analyst"},
    }
    res = svc.generate_vacancy_cv(
        job_title="Financial Analyst",
        company="TBC Bank",
        portal="jobs.ge",
        matched_skills=["IFRS", "Financial Modeling", "Excel", "Power BI"],
        missing_skills=[],
        human_summary="Financial Analyst with verified experience in IFRS reporting, budgeting, and Power BI analytics across Credo Bank.",
        motivation_statement="Applying to support TBC Bank's FP&A reporting.",
        dou_motivational_letter="Dear TBC Bank team...",
        cv_language="en",
        cv_style="tailored",
        vault_override=vault,
    )
    assert res["ats_parse_report"]["status"] == "PASS", res["ats_parse_report"]
    assert res["ats_parse_report"]["score"] >= 90
    assert "Financial Reporting &amp; Analysis" in res["rendered_html"]
    assert "@media print" in res["rendered_html"]


def test_dynamic_experience_bounds_adapt_to_any_candidate():
    from app.services.profile_service import compute_dynamic_experience_bounds

    assert compute_dynamic_experience_bounds(None)[1:] == (1.0, "JUNIOR", "Entry-Level / Intern")
    assert compute_dynamic_experience_bounds(1.0)[1] == 1.5
    assert compute_dynamic_experience_bounds(1.5)[1] == 2.0
    assert compute_dynamic_experience_bounds(2.0)[1] == 2.0
    _, cap_mid, sen_mid, _ = compute_dynamic_experience_bounds(4.0)
    assert cap_mid == 5.5 and sen_mid == "MID"
    _, cap_sr, sen_sr, _ = compute_dynamic_experience_bounds(10.0)
    assert cap_sr >= 10.0 and sen_sr == "LEAD"


def test_public_sector_is_only_state_employers_never_private_companies():
    from app.services.matcher_service import is_public_sector_vacancy

    assert is_public_sector_vacancy("hr.gov.ge", "სსიპ - კოლეჯი") is True
    assert is_public_sector_vacancy("jobs.ge", "თბილისის მერია") is True
    assert is_public_sector_vacancy("jobs.ge", "სსიპ - საჯარო რეესტრის ეროვნული სააგენტო") is True
    assert is_public_sector_vacancy("hr.ge", "საქართველოს ფინანსთა სამინისტრო") is True
    for private in ("Andersen", "Itransition", "ProCredit Bank", "TBC Bank", "EPAM"):
        assert is_public_sector_vacancy("headhunter.ge", private) is False
        assert is_public_sector_vacancy("jobs.ge", private) is False


def test_entry_qa_profile_junior_procredit_accepted_middle_senior_rejected_andersen_not_public():
    from app.services.matcher_service import matcher_service

    qa_entry = {
        "target_industry": "qa_tech",
        "primary_role": "QA Engineer",
        "verified_skills": ["Manual Testing", "Jira", "SQL", "Postman", "REST API", "Playwright"],
        "years_of_experience": None,
        "max_allowed_years": 1.0,
        "seniority_level": "JUNIOR",
        "spoken_languages": ["English", "Georgian"],
        "eligible_internships": True,
    }
    body_tpl = (
        "პროკრედიტ ბანკი აცხადებს ვაკანსიას ხარისხის უზრუნველყოფის სპეციალისტის ({lvl}) "
        "პოზიციაზე — ვებ აპლიკაციებისა და Core სისტემების მიმართულებით. ტესტ-ქეისები, Jira, SQL, API ტესტირება."
    )
    junior = matcher_service.evaluate_job_tiered(
        title="ხარისხის უზრუნველყოფის სპეციალისტი (Junior QA)",
        description=body_tpl.format(lvl="Junior QA"),
        parsed_skills=qa_entry, portal="jobs.ge", company="პროკრედიტ ბანკი",
    )
    assert junior["status"] != "FILTERED_OUT"
    assert junior["match_tier"] == "DIRECT"

    senior = matcher_service.evaluate_job_tiered(
        title="ხარისხის უზრუნველყოფის სპეციალისტი",
        description=body_tpl.format(lvl="Middle / Senior QA"),
        parsed_skills=qa_entry, portal="jobs.ge", company="პროკრედიტ ბანკი",
    )
    assert senior["status"] == "FILTERED_OUT"

    andersen = matcher_service.evaluate_job_tiered(
        title="QA Manual Trainee",
        description="Andersen QA trainee program: manual testing, SQL, Jira, test cases. Remote friendly.",
        parsed_skills=qa_entry, portal="headhunter.ge", company="Andersen",
    )
    assert andersen["status"] != "FILTERED_OUT"
    assert andersen["match_tier"] == "DIRECT"
    assert "Public Sector" not in (andersen["match_rationale"] or "")

    off_domain = matcher_service.evaluate_job_tiered(
        title="Cloud Platform Engineer",
        description="Kubernetes, Terraform, Python, Git, SQL. Entry level welcome.",
        parsed_skills=qa_entry, portal="greenhouse.io", company="Gitlab",
    )
    assert off_domain["status"] == "FILTERED_OUT"

    two_plus = matcher_service.evaluate_job_tiered(
        title="QA Engineer",
        description="Requirements: 2+ years of QA experience, Selenium, SQL.",
        parsed_skills=qa_entry, portal="jobs.ge", company="Some Co",
    )
    assert two_plus["status"] == "FILTERED_OUT"

    # URLs like recruiting.procredit-group.com must never extract 'Recruiting' as a required skill
    reqs = matcher_service.extract_job_requirements(
        "ხარისხის უზრუნველყოფის სპეციალისტი (Junior QA)",
        "ტესტირება SQL Postman API. Apply at https://recruiting.procredit-group.com/jobs/123 or hr@procredit.ge",
    )
    assert "Recruiting" not in reqs and "HR" not in reqs


def test_ingest_scraped_jobs_sibling_delete_no_foreign_key_error(tmp_path):
    from sqlmodel import Session, select
    from app.db.database import engine
    from app.db.models import CandidateProfile, JobPosting, User
    from app.services.scrapers.scraper_orchestrator import scraper_orchestrator

    with Session(engine) as session:
        user = User(email="fk-guard@example.com", hashed_password="x", full_name="FK Guard")
        session.add(user)
        session.commit()
        session.refresh(user)
        uid = user.id
        prof = CandidateProfile(
            user_id=uid,
            headline="Junior QA Engineer",
            raw_markdown="Junior QA Engineer. Skills: Manual Testing, SQL, Postman, REST API, Jira. Languages: Georgian, English.",
            parsed_skills={
                "target_industry": "qa_tech",
                "primary_role": "Junior QA Engineer",
                "all_skills": ["Manual Testing", "SQL", "Postman", "REST API", "Jira"],
                "verified_skills": ["Manual Testing", "SQL", "Postman", "REST API", "Jira"],
                "years_of_experience": None,
                "max_allowed_years": 1.0,
                "seniority_level": "JUNIOR",
                "spoken_languages": ["English", "Georgian"],
            },
        )
        session.add(prof)
        # Pre-existing legacy row with un-qualified title that matches both sibling postings by title+company
        old_row = JobPosting(
            user_id=uid,
            portal="jobs.ge",
            external_id="jobsge-770150",
            title="ხარისხის უზრუნველყოფის სპეციალისტი",
            company="პროკრედიტ ბანკი",
            url="https://jobs.ge/ge/?view=jobs&id=770150",
            market="GE_DOMESTIC",
            status="AUDITED",
            description_raw="Old description",
        )
        session.add(old_row)
        session.commit()

    res = scraper_orchestrator.ingest_scraped_jobs(
        raw_jobs=[
            {
                "portal": "jobs.ge",
                "external_id": "jobsge-770150",
                "title": "ხარისხის უზრუნველყოფის სპეციალისტი (Junior QA)",
                "company": "პროკრედიტ ბანკი",
                "url": "https://jobs.ge/ge/?view=jobs&id=770150",
                "market": "GE_DOMESTIC",
                "description_raw": "პროკრედიტ ბანკი აცხადებს ვაკანსიას Junior QA პოზიციაზე. SQL, Postman, REST API, ტესტ-ქეისები.",
            },
            {
                "portal": "jobs.ge",
                "external_id": "jobsge-770149",
                "title": "ხარისხის უზრუნველყოფის სპეციალისტი (Middle / Senior QA)",
                "company": "პროკრედიტ ბანკი",
                "url": "https://jobs.ge/ge/?view=jobs&id=770149",
                "market": "GE_DOMESTIC",
                "description_raw": "პროკრედიტ ბანკი აცხადებს ვაკანსიას Middle / Senior QA პოზიციაზე. მინიმუმ 3 წლიანი გამოცდილება.",
            },
        ],
        user_id=uid,
    )
    assert res["filtered_out_count"] >= 1
    titles = [j["title"] for j in res["jobs"]]
    assert any("Junior QA" in t for t in titles)
    assert not any("Middle / Senior" in t for t in titles)
    with Session(engine) as session:
        rows = session.exec(select(JobPosting).where(JobPosting.user_id == uid)).all()
        assert len(rows) == 1 and "Junior QA" in rows[0].title


def test_yaml_skill_meta_never_leaks_and_pdf_cv_with_cover_letter_is_recruiter_grade():
    from app.db.profile_repository import profile_repository
    from app.services.cv_generator_service import cv_generator_service
    from app.services.matcher_service import matcher_service

    # 1. AI SKILL.md with YAML frontmatter & coaching prompts must NEVER pollute name, skills, or education
    ai_skill_md = """---
name: giorgi-career-intelligence-interview-coach
description: Career coach prompt
---
# Career Intelligence Coach
- **Location:** **Tbilisi, Georgia**

## Core Skills
- Playwright, FastAPI, PostgreSQL, Senior QA Automation Engineer, Technical QA Hiring Manager, Interview Coach, QA Automation Mentor

## Education
- Tbilisi State University (TSU), Faculty of Economics
- 2022–2026
- Graduated with honors
- Treat the Economics degree as a source of transferable value rather than automatically as a disadvantage.
- Potential transferable strengths include:
- analytical reasoning
- Do not claim experience in a domain unless evidence supports it.
# 2. Verified Work Experience
- Use these as the baseline unless Giorgi provides updated documentation.
"""
    parsed_ai = profile_repository.parse_profile_from_md(ai_skill_md)
    assert "giorgi-career-intelligence-interview-coach" not in (parsed_ai.get("full_name") or "").lower()
    assert "**" not in (parsed_ai.get("location") or "")
    edu_degs = [e.get("degree", "") for e in (parsed_ai.get("education") or [])]
    assert len(edu_degs) <= 1
    assert not any("Treat the Economics" in d or "Do not claim" in d or "Verified Work" in d for d in edu_degs)
    tax = matcher_service.parse_skills_markdown(ai_skill_md)
    skills_low = [s.lower() for s in tax["all_skills"]]
    assert "FastAPI" in tax["all_skills"] and "PostgreSQL" in tax["all_skills"]
    for persona in ("interview coach", "technical qa hiring manager", "qa automation mentor"):
        assert persona not in skills_low

    # 2. Real PDF-extracted CV with ALL-CAPS headers, \uf0b7 bullets, and pipe-separated languages parses cleanly
    pdf_cv_md = """# GIORGI SHAKIASHVILI
Junior QA Specialist | Web Application Testing | API & SQL Validation
Tbilisi, Georgia | +995 571 15 68 07 | giorgishakiashvili21@gmail.com
## Summary
Detail-oriented Junior QA Specialist with commercial testing experience at EPAM Systems and Exactpro Systems.
CORE COMPETENCIES & TECHNICAL SKILLS
\uf0b7 API & Database Testing: REST API, Postman, SQL, PostgreSQL, FastAPI, Playwright, Jira
## Work Experience
Full-Stack QA Trainee (Lab) — Vention Teams May 2026 – Sep 2026
\uf0b7 Executed 30+ REST API test cases in Postman and ran PostgreSQL queries to verify backend records.
EPAM Systems Aug 2024 – Jun 2025
Junior Software Testing Engineer Jan 2025 – Jun 2025
\uf0b7 Validated REST API responses in Postman and logged reproducible defects in Jira.
Software Quality Assurance Intern — Exactpro Systems Sep 2023 – Jan 2024
\uf0b7 Executed manual functional testing of financial systems following STLC procedures.
EDUCATION & TECHNICAL TRAINING
\uf0b7 M.Sc. in Economics - Tbilisi State University (TSU) | 2026 – Present — Focus on financial markets.
\uf0b7 B.Sc. in Economics - Tbilisi State University (TSU) | Sep 2022 – Jul 2026 — Qua
ntitative foundation in statistics and financial logic.
\uf0b7 Technical Programs: EPAM Python Test Automation Mentoring Program (2025) • Quantori Python & Docker School (2024).
## Languages
Georgian: Native | English: Professional Working Proficiency
"""
    p = profile_repository.parse_profile_from_md(pdf_cv_md)
    assert p["full_name"] == "GIORGI SHAKIASHVILI"
    assert len(p["education"]) == 2
    assert "Quantitative foundation" in p["education"][1]["field_of_study"]
    assert len(p["certifications"]) == 2
    assert len(p["work_history"]) == 3
    assert [w["company"] for w in p["work_history"]] == ["Vention Teams", "EPAM Systems", "Exactpro Systems"]
    assert len(p["spoken_languages"]) == 2
    assert {l["language"] for l in p["spoken_languages"]} == {"Georgian", "English"}

    # 3. Generated ProCredit Bank Junior QA Cover Letter & CV are full, tailored, and clean
    pkg = cv_generator_service.prepare_email_application_package(
        job_title="Junior QA Specialist",
        company="ProCredit Bank",
        description="",
        cv_language="en",
        cv_style="tailored",
        skills_md_override=pdf_cv_md,
    )
    cl = pkg["cover_letter"]
    assert len(cl) >= 480, f"Cover letter too short ({len(cl)} chars): {cl}"
    assert cl.count("\n\n") >= 4
    assert "giorgi-career-intelligence-interview-coach" not in cl.lower()
    assert "GIORGI SHAKIASHVILI" in cl
    assert "across" not in pkg["human_tone_summary"].lower() or pkg["human_tone_summary"].lower().count("across") <= 1
    assert "ProCredit Bank" in cl
    assert "Tbilisi State University" in cl
    assert "**Tbilisi" not in pkg["rendered_html"]


def test_upload_first_gate_blocks_scraping_before_skills_upload_and_google_calendar_ics_and_integrations():
    client = TestClient(app)
    email = "no_upload_gate@example.com"
    headers = _register_and_auth(client, email)

    # 1. User who has NOT uploaded CV/skills file must NOT auto-target QA or any jobs
    r_scrape = client.post("/api/jobs/scrape", json={"allow_network": True}, headers=headers)
    assert r_scrape.status_code == 400
    assert "upload" in r_scrape.json()["detail"].lower()

    # 2. Integrations status reports DB integrity, Alembic head, profile=not uploaded, and Google Calendar ready
    r_int = client.get("/api/applications/integrations/status", headers=headers)
    assert r_int.status_code == 200
    integ = r_int.json()
    assert integ["profile"]["uploaded"] is False
    assert integ["google_calendar"]["instant_link_ready"] is True
    assert integ["google_calendar"]["ics_export_ready"] is True
    assert "calendar.google.com/calendar/render" in integ["google_calendar"]["test_event_url"]
    assert integ["database"]["integrity_ok"] is True
    assert integ["database"]["foreign_key_errors"] == 0

    # 3. Google Calendar event creation & universal .ics export (interview + followup)
    r_app = client.post(
        "/api/applications",
        json={
            "company": "ProCredit Bank",
            "role": "Junior QA Specialist",
            "portal": "jobs.ge",
            "url": "https://jobs.ge/ge/?view=jobs&id=770150",
            "status": "HR Screening",
        },
        headers=headers,
    )
    assert r_app.status_code in (200, 201)
    app_id = r_app.json()["id"]

    r_cal = client.post(
        f"/api/applications/{app_id}/calendar-event",
        json={"interview_date": "2026-11-28T11:00", "duration_minutes": 45},
        headers=headers,
    )
    assert r_cal.status_code == 200
    cal_data = r_cal.json()
    assert "calendar.google.com/calendar/render" in cal_data["google_calendar_template_url"]
    assert "ProCredit+Bank" in cal_data["google_calendar_template_url"]

    r_ics = client.get(f"/api/applications/{app_id}/calendar.ics?kind=interview", headers=headers)
    assert r_ics.status_code == 200
    assert "text/calendar" in r_ics.headers.get("content-type", "")
    assert "BEGIN:VCALENDAR" in r_ics.text and "BEGIN:VALARM" in r_ics.text and "ProCredit Bank" in r_ics.text

    r_fu = client.get(f"/api/applications/{app_id}/calendar.ics?kind=followup", headers=headers)
    assert r_fu.status_code == 200
    assert "Follow up: Junior QA Specialist at ProCredit Bank" in r_fu.text


def test_fresh_database_alembic_upgrade_head_clean(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from app.config import BASE_DIR

    fresh_db = tmp_path / "fresh_alembic.db"
    db_url = f"sqlite:///{fresh_db}"
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    eng = create_engine(db_url)
    with eng.connect() as conn:
        assert conn.execute(text("PRAGMA integrity_check")).fetchall() == [("ok",)]
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert rev == "a3c9d14e7b52"
    eng.dispose()
