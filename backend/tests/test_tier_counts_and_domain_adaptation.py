import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.db.database import init_db, engine
from app.db.models import JobPosting, CandidateProfile, User
from app.services.scrapers.base_scraper import sanitize_company_name, evaluate_remote_and_language_gate
from app.services.matcher_service import matcher_service
from app.services.cv_generator_service import cv_generator_service

client = TestClient(app)


def test_jobsge_client_slug_sanitization():
    """Verifies that navigation boilerplate link text is never parsed as company name."""
    sanitized = sanitize_company_name(
        "ამ ორგანიზაციის ყველა განცხადება",
        target_email="info@genofit.tech",
        fallback="GenofIT",
    )
    assert sanitized == "Genofit" or sanitized == "GenofIT"
    assert "ამ ორგანიზაციის" not in sanitized

    # Location strings also rejected
    loc_clean = sanitize_company_name("საქართველოს მასშტაბით", fallback="Verified Employer")
    assert loc_clean == "Verified Employer"


def test_linkedin_us_only_location_gate():
    """Verifies that LinkedIn vacancies requiring US residency or on-site attendance are disqualified."""
    # 1. US-only on-site/hybrid
    is_rem, status, reason, _ = evaluate_remote_and_language_gate(
        title="Junior QA Analyst",
        description="Must be legally authorized to work in the United States without sponsorship.",
        location_text="Austin, Texas, United States",
        portal="linkedin.com",
    )
    assert status == "FILTERED_OUT"
    assert "US-based position" in reason

    # 2. Local Georgian position is admitted
    is_rem_ge, status_ge, reason_ge, _ = evaluate_remote_and_language_gate(
        title="Junior QA Engineer",
        description="Looking for manual QA intern in our Tbilisi office.",
        location_text="Tbilisi, Georgia",
        portal="linkedin.com",
    )
    assert status_ge == "DISCOVERED"

    # 3. True worldwide remote is admitted
    is_rem_ww, status_ww, reason_ww, _ = evaluate_remote_and_language_gate(
        title="QA Tester",
        description="Work from anywhere worldwide. B2B contractor role.",
        location_text="Remote Worldwide",
        portal="linkedin.com",
    )
    assert status_ww == "DISCOVERED"


def test_strict_experience_cap_rejects_3_plus_years():
    """Verifies Georgian, English, Ukrainian, and Russian 3+ year postings are rejected against 2.0-yr cap."""
    cap = 2.0
    cand_years = 1.5

    # Georgian "მინიმუმ 3 წელი"
    ok1, reason1 = matcher_service.validate_seniority_gate(
        candidate_years=cand_years,
        candidate_seniority="JUNIOR",
        job_title="QA Engineer",
        job_description="მოთხოვნები: მინიმუმ 3 წლიანი სამუშაო გამოცდილება QA მიმართულებით",
        max_allowed_years=cap,
    )
    assert ok1 is False
    assert "3+ years" in reason1 or "3" in reason1

    # English "at least 3 years"
    ok2, reason2 = matcher_service.validate_seniority_gate(
        candidate_years=cand_years,
        candidate_seniority="JUNIOR",
        job_title="Software QA",
        job_description="Requirements: at least 3 years of hands-on automated testing experience",
        max_allowed_years=cap,
    )
    assert ok2 is False
    assert "3" in reason2

    # Ukrainian "від 3 років"
    ok3, reason3 = matcher_service.validate_seniority_gate(
        candidate_years=cand_years,
        candidate_seniority="JUNIOR",
        job_title="QA Automation",
        job_description="Вимоги: досвід роботи від 3 років з Python та PyTest",
        max_allowed_years=cap,
    )
    assert ok3 is False

    # Russian "опыт от 3-х лет"
    ok4, reason4 = matcher_service.validate_seniority_gate(
        candidate_years=cand_years,
        candidate_seniority="JUNIOR",
        job_title="QA Engineer",
        job_description="Требования: опыт работы от 3-х лет в тестировании ПО",
        max_allowed_years=cap,
    )
    assert ok4 is False

    # 1-2 years is accepted under 2.0 cap
    ok5, _ = matcher_service.validate_seniority_gate(
        candidate_years=cand_years,
        candidate_seniority="JUNIOR",
        job_title="Junior QA Engineer",
        job_description="Requirements: 1-2 years of experience or internship graduate",
        max_allowed_years=cap,
    )
    assert ok5 is True


def test_cover_letter_domain_adaptation():
    """Verifies that Technical Support and Receptionist cover letters never speak about test automation."""
    # 1. Technical Support / Monitoring vacancy
    support_pkg = cv_generator_service.prepare_email_application_package(
        job_title="ტექნიკური მხარდაჭერის სპეციალისტი / მონიტორინგი",
        company="Devexperts",
        description="სისტემური მონიტორინგი, ინციდენტების დიაგნოსტიკა SQL და Jira, მომხმარებელთა მხარდაჭერა",
        portal="jobs.ge",
        target_email="info@hr.com.ge",
        email_subject_template="ტექნიკური მხარდაჭერის სპეციალისტი / მონიტორინგი — [Name]",
    )
    cl_sup = support_pkg["cover_letter"]
    assert "ტესტირებისა და პროდუქტის ხარისხის სტაბილურობაში" not in cl_sup
    assert "რეგრესიული ტესტები" not in cl_sup
    assert "ტექნიკური მხარდაჭერის" in cl_sup
    assert "[Name]" not in support_pkg["subject"]

    # 2. Receptionist / Front Desk vacancy
    rec_pkg = cv_generator_service.prepare_email_application_package(
        job_title="რეცეფციონისტი/ადმინისტრატორი",
        company="მზიური გარდენსი",
        description="სასტუმროს სტუმრების მიღება, რეგისტრაცია, Front Desk ოპერაციები",
        portal="jobs.ge",
        target_email="hr@nqhospitality.com",
    )
    cl_rec = rec_pkg["cover_letter"]
    body_part = cl_rec.split("პატივისცემით")[0]
    assert "qa" not in body_part.lower()
    assert "ტესტირება" not in body_part
    assert "სტუმარმასპინძლობის" in body_part or "Front Desk" in body_part or "ადმინისტრატორ" in body_part


def test_global_tier_and_status_counts():
    """Verifies that GET /api/jobs returns accurate global tier and status counts regardless of pagination limit."""
    from app.services.auth_service import get_user_by_email, create_access_token

    test_email = "count_tester@talentflow.local"
    init_db()
    with Session(engine) as session:
        # Create test user & profile
        test_user = get_user_by_email(session, test_email)
        if not test_user:
            test_user = User(
                email=test_email,
                full_name="Count Tester",
                hashed_password="hashed_pw_test",
                is_active=True,
            )
            session.add(test_user)
            session.commit()
            session.refresh(test_user)

        # Clear existing non-applied jobs
        non_app = session.exec(select(JobPosting).where(JobPosting.status != "APPLIED")).all()
        for j in non_app:
            session.delete(j)
        session.commit()

        # Ingest profile
        tax = matcher_service.parse_skills_markdown("# QA Engineer\n- Playwright, Python, PyTest, REST API, SQL, Docker")
        tax["user_uploaded"] = True
        tax["owner_email"] = test_email
        tax["target_industry"] = "qa_tech"

        prof = session.exec(select(CandidateProfile)).first()
        if not prof:
            prof = CandidateProfile(
                full_name="Count Tester",
                email=test_email,
                raw_markdown="# Profile",
                parsed_skills=tax,
            )
            session.add(prof)
        else:
            prof.parsed_skills = tax
            session.add(prof)
        session.commit()

        # Add 3 direct, 2 adjacent, 1 public internship
        for i in range(3):
            session.add(JobPosting(
                portal="jobs.ge", external_id=f"test-dir-{i}", url=f"https://jobs.ge/{i}",
                title=f"Direct Role {i}", company="Comp", match_tier="DIRECT", status="STAGED",
                suitability_score=85.0, description_raw="Desc",
            ))
        for i in range(2):
            session.add(JobPosting(
                portal="jobs.ge", external_id=f"test-adj-{i}", url=f"https://jobs.ge/adj-{i}",
                title=f"Adjacent Role {i}", company="Comp", match_tier="ADJACENT", status="AUDITED",
                suitability_score=68.0, description_raw="Desc",
            ))
        session.add(JobPosting(
            portal="hr.gov.ge", external_id="test-pub-1", url="https://hr.gov.ge/1",
            title="Internship", company="Agency", match_tier="PUBLIC_INTERNSHIP", status="STAGED",
            suitability_score=76.0, description_raw="Desc",
        ))
        session.commit()

    # Query with limit=2 (page 1 of 3)
    token = create_access_token({"sub": test_email, "is_admin": False})

    res = client.get("/api/jobs?page=1&limit=2", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()

    assert len(data["items"]) == 2
    assert data["total"] == 6
    assert data["total_pages"] == 3

    # Check global tier counts
    assert data["tier_counts"]["ALL"] == 6
    assert data["tier_counts"]["DIRECT"] == 3
    assert data["tier_counts"]["ADJACENT"] == 2
    assert data["tier_counts"]["PUBLIC_INTERNSHIP"] == 1

    # Check global status counts
    assert data["status_counts"]["ALL"] == 6
    assert data["status_counts"]["STAGED"] == 4
    assert data["status_counts"]["AUDITED"] == 2


def test_foreign_portal_hybrid_and_onsite_disqualification():
    """
    Verifies that ANY foreign vacancy (Djinni, JustJoin, DOU, LinkedIn non-GE) that is
    Hybrid or On-site is disqualified and never returned to the suitable feed.
    """
    # 1. JustJoin Hybrid in Polish ("Praca hybrydowa")
    rem1, st1, r1, _ = evaluate_remote_and_language_gate(
        title="Junior QA Engineer",
        description="Oferujemy pracę hybrydową (2 dni w biurze w Warszawie). Doświadczenie z Cypress.",
        location_text="Warszawa, Poland (Hybrid)",
        portal="justjoin.it",
    )
    assert st1 == "FILTERED_OUT"
    assert "Hybrid" in r1

    # 2. JustJoin On-site in Polish ("Praca stacjonarna")
    rem2, st2, r2, _ = evaluate_remote_and_language_gate(
        title="QA Tester",
        description="Wymagana praca stacjonarna w biurze w Krakowie.",
        location_text="Kraków, Poland (Office)",
        portal="justjoin.it",
    )
    assert st2 == "FILTERED_OUT"
    assert "On-site" in r2

    # 3. Djinni Hybrid in Ukrainian ("Київ, гібрид")
    rem3, st3, r3, _ = evaluate_remote_and_language_gate(
        title="Junior QA Automation",
        description="Гібридний формат роботи (1-2 дні в офісі у Києві).",
        location_text="Київ, гібрид",
        portal="djinni.co",
        candidate_languages=["Ukrainian", "English"],
    )
    assert st3 == "FILTERED_OUT"
    assert "Hybrid" in r3

    # 4. Djinni On-site ("Тільки офіс")
    rem4, st4, r4, _ = evaluate_remote_and_language_gate(
        title="Manual QA",
        description="Робота тільки в офісі компанії у Львові.",
        location_text="Львів, тільки офіс",
        portal="djinni.co",
        candidate_languages=["Ukrainian", "English"],
    )
    assert st4 == "FILTERED_OUT"
    assert "On-site" in r4

    # 5. LinkedIn Hybrid in Europe ("Berlin, Germany (Hybrid)")
    rem5, st5, r5, _ = evaluate_remote_and_language_gate(
        title="QA Specialist",
        description="Hybrid work policy: 3 days in Berlin office.",
        location_text="Berlin, Germany (Hybrid)",
        portal="linkedin.com",
    )
    assert st5 == "FILTERED_OUT"
    assert "Hybrid" in r5

    # 6. DOU.ua Onsite in Kyiv without remote
    rem6, st6, r6, _ = evaluate_remote_and_language_gate(
        title="Junior QA",
        description="Вакансія в офісі компанії в Києві.",
        location_text="Київ",
        portal="dou.ua",
        candidate_languages=["Ukrainian", "English"],
    )
    assert st6 == "FILTERED_OUT"
    assert "On-site" in r6 or "Remote" in r6


def test_foreign_portal_100pct_remote_accepted():
    """
    Verifies that genuine 100% remote vacancies from foreign portals are accepted.
    """
    # JustJoin 100% Remote B2B
    rem1, st1, r1, _ = evaluate_remote_and_language_gate(
        title="QA Automation Engineer",
        description="100% remote B2B role across Europe. Playwright and TypeScript.",
        location_text="Remote EU",
        portal="justjoin.it",
    )
    assert st1 == "DISCOVERED"
    assert rem1 is True

    # Djinni Full Remote
    rem2, st2, r2, _ = evaluate_remote_and_language_gate(
        title="QA Engineer",
        description="Full remote role. English B2+. Manual and API testing.",
        location_text="Тільки віддалено",
        portal="djinni.co",
    )
    assert st2 == "DISCOVERED"
    assert rem2 is True

    # LinkedIn Worldwide Remote
    rem3, st3, r3, _ = evaluate_remote_and_language_gate(
        title="QA Engineer",
        description="Worldwide remote position. Work from anywhere in the world.",
        location_text="Remote",
        portal="linkedin.com",
    )
    assert st3 == "DISCOVERED"
    assert rem3 is True


def test_domestic_georgian_onsite_and_hybrid_allowed():
    """
    Verifies that domestic Georgian vacancies (jobs.ge, hr.ge, hr.gov.ge) in Tbilisi
    are NOT filtered out by the foreign remote gate.
    """
    # Jobs.ge on-site in Tbilisi
    rem1, st1, r1, _ = evaluate_remote_and_language_gate(
        title="Manual QA სტაჟიორი",
        description="სამუშაო ადგილი: თბილისი, ვაკე. ოფისში მუშაობა.",
        location_text="თბილისი",
        portal="jobs.ge",
    )
    assert st1 == "DISCOVERED"
    assert rem1 is False  # On-site in Tbilisi is acknowledged but permitted

    # HR.ge hybrid in Tbilisi
    rem2, st2, r2, _ = evaluate_remote_and_language_gate(
        title="QA Engineer",
        description="ჰიბრიდული გრაფიკი თბილისის ოფისში.",
        location_text="Tbilisi, Georgia",
        portal="hr.ge",
    )
    assert st2 == "DISCOVERED"


def test_matcher_tiered_rejects_foreign_hybrid():
    """
    Verifies that matcher_service.evaluate_job_tiered rejects foreign hybrid vacancies.
    """
    parsed_skills = {
        "years_of_experience": 1.5,
        "max_allowed_years": 2.0,
        "seniority_level": "JUNIOR",
        "primary_role": "QA Engineer",
        "qa_automation": ["Playwright", "Cypress"],
        "spoken_languages": ["English", "Georgian"],
    }
    res = matcher_service.evaluate_job_tiered(
        title="QA Automation Engineer",
        description="We offer a hybrid setup: 2 days in office in Warsaw. Playwright required.",
        parsed_skills=parsed_skills,
        portal="justjoin.it",
    )
    assert res["status"] == "FILTERED_OUT"
    assert "Hybrid" in res["match_rationale"]

