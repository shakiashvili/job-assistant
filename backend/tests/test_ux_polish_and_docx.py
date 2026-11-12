import io
from pathlib import Path
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.db.database import init_db, engine
from app.db.models import JobPosting
from app.services.matcher_service import matcher_service
from app.services.salary_service import salary_service
from app.services.scrapers.justjoin_scraper import justjoin_scraper
from app.services.scrapers.djinni_scraper import djinni_scraper
from app.services.scrapers.base_scraper import evaluate_remote_and_language_gate

client = TestClient(app)


def test_clean_skills_extraction_rejects_dates_companies_and_duplicates():
    """Ensures dates, companies, locations, sentence fragments, and duplicate casings never become skill chips."""
    dirty_md = """# Candidate — QA Engineer

## Core Skills
- **Automation:** Playwright, Selenium, Selenium WebDriver, PyTest, pytest, TypeScript, Typescript
- **API:** Postman, REST API, rest api, GitHub Actions, github actions, GitLab CI, gitlab ci, CI/CD, ci/cd
- *Vention Development — Vention Teams** • *Tbilisi, Georgia (Remote)* *May 2026 – September 2026*
- Conducted functional, regression, smoke testing, execution checklists, verifying request parameters, authentication tokens, JSON response schemas, and HTTP status codes.
"""
    taxonomy = matcher_service.parse_skills_markdown(dirty_md)
    all_skills = taxonomy["all_skills"]
    joined = " | ".join(all_skills)

    assert "Playwright" in all_skills
    assert "PyTest" in all_skills
    assert "TypeScript" in all_skills
    assert "GitHub Actions" in all_skills
    assert "REST API" in all_skills

    # Case-insensitive dedupe
    assert all_skills.count("TypeScript") == 1
    assert "Typescript" not in all_skills
    assert "Pytest" not in all_skills
    assert "Github Actions" not in all_skills

    # No dates, companies, locations, or sentence fragments
    assert "2026" not in joined
    assert "Vention" not in joined
    assert "Tbilisi" not in joined
    assert "Conducted functional" not in joined
    assert "HTTP status codes" not in joined


def test_salary_extraction_never_fabricates_unstated_or_unpaid_salaries():
    """Verifies GenofIT unpaid internship and unstated postings return None salary rather than fake AI numbers."""
    genofit_desc = """
    დასახელება: Manual QA სტაჟიორი
    მომწოდებელი: GenofIT
    ანაზღაურება: სტაჟირება არ ითვალისწინებს ანაზღაურებასა და დასაქმების გარანტიას;
    """
    res_unpaid = salary_service.extract_vacancy_salary("Manual QA სტაჟიორი", genofit_desc)
    assert res_unpaid["min_salary"] is None
    assert res_unpaid["max_salary"] is None
    assert res_unpaid["currency"] is None
    assert res_unpaid["is_unpaid"] is True
    assert res_unpaid["salary_estimated_by_ai"] is False

    res_none = salary_service.extract_vacancy_salary("QA Automation Engineer", "Looking for Playwright and Python skills.")
    assert res_none["min_salary"] is None
    assert res_none["max_salary"] is None
    assert res_none["salary_estimated_by_ai"] is False


def test_ground_truth_vault_never_returns_null_faq_or_compensation():
    """Verifies ProfileVault tabs (Visas & Work Auth, Work History, FAQ Bank) always receive non-null structures."""
    init_db()
    res = client.get("/api/ground-truth")
    assert res.status_code == 200
    gt = res.json()
    assert isinstance(gt.get("faq_bank"), list) and len(gt["faq_bank"]) >= 1
    assert isinstance(gt.get("work_history"), list)
    assert isinstance(gt.get("skills", {}).get("core"), list)
    assert isinstance(gt.get("candidate", {}).get("compensation", {}).get("expected_salary_eur"), (int, float))
    assert isinstance(gt.get("candidate", {}).get("work_authorization", {}).get("us_work_authorization"), str)


def test_deep_scrapers_justjoin_djinni_and_dou():
    """Verifies JustJoin Polish filter, Djinni clean titles, and DOU English body parsing."""
    # 1. JustJoin Polish-only offer is FILTERED_OUT; English remote is DISCOVERED
    _, status_pl, reason_pl, langs_pl = evaluate_remote_and_language_gate(
        title="Tester manualny",
        description="Model pracy: remote. Poszukujemy doświadczonego Testera Manualnego. Długofalowa współpraca.",
        location_text="Warsaw, Remote",
        portal="justjoin.it",
    )
    assert status_pl == "FILTERED_OUT"
    assert "Polish" in reason_pl

    _, status_en, _, langs_en = evaluate_remote_and_language_gate(
        title="QA Automation Engineer (Playwright)",
        description="Remote B2B across Europe. English working language. Stack: Playwright, TypeScript, CI/CD.",
        location_text="Remote EU / B2B",
        portal="justjoin.it",
    )
    assert status_en == "DISCOVERED"
    assert "English" in langs_en

    # 2. DOU vacancy with Ukrainian cities list in location_meta but English job body passes cleanly
    _, dou_st, _, _ = evaluate_remote_and_language_gate(
        title="QA Engineer, AI & Video",
        description="At Qencode we are looking for a QA Engineer with Playwright, Python, REST API. Remote global.",
        location_text="Київ, Харків, Львів, Дніпро, віддалено",
        portal="dou.ua",
    )
    assert dou_st == "DISCOVERED"

    # 3. JustJoin SSR link parser extracts clean offers
    sample_jj = '<a href="/job-offer/acme-qa-remote"></a><a href="/job-offer/acme-qa-remote">QA Automation Engineer</a>'
    parsed_jj = justjoin_scraper.parse_html_listings(sample_jj)
    assert len(parsed_jj) == 1
    assert parsed_jj[0]["title"] == "QA Automation Engineer"
    assert parsed_jj[0]["portal"] == "justjoin.it"

    # 4. Djinni anchor link parser ignores wrapper $ badges
    sample_dj = '<div class="job-item"><h2 class="job-item__position"><a class="job_item__header-link" href="/jobs/745818-manual-qa/">Manual QA</a><span>Qoders Family</span></h2><div class="fw-medium">Full Remote · Worldwide</div></div>'
    parsed_dj = djinni_scraper.parse_html_listings(sample_dj)
    assert len(parsed_dj) == 1
    assert parsed_dj[0]["title"] == "Manual QA"


def test_prepare_gmail_package_with_word_docx_cover_letter_and_my_cvs():
    """Tests tailored Cover Letter + Word (.docx) CV generation and My CVs upload/list/delete endpoints."""
    init_db()
    with Session(engine) as session:
        job = JobPosting(
            portal="jobs.ge",
            external_id="jobsge-genofit-test",
            title="Manual QA სტაჟიორი",
            company="GenofIT",
            url="https://jobs.ge/ge/?view=jobs&id=763944-test",
            market="GE_DOMESTIC",
            is_remote=True,
            channel="EMAIL",
            delivery_channel="EMAIL",
            target_email="info@genofit.tech",
            email_subject="QA Automation Engineer - [Name]",
            description_raw="QA Bridge არის GenofIT-ის ონლაინ სტაჟირება. Manual Testing, Postman, Test Cases. ანაზღაურება: სტაჟირება არ ითვალისწინებს ანაზღაურებას.",
            status="STAGED",
            suitability_score=80.0,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    try:
        pkg_res = client.post(f"/api/jobs/{job_id}/prepare-email-package")
        assert pkg_res.status_code == 200
        pkg = pkg_res.json()
        assert "[Name]" not in pkg["subject"]
        assert "Manual QA" in pkg["subject"]
        assert "GenofIT" in pkg["cover_letter"]
        assert pkg["docx_filename"].endswith(".docx")

        docx_dl = client.get(pkg["docx_url"])
        assert docx_dl.status_code == 200
        assert docx_dl.content[:2] == b"PK"  # Valid OOXML .docx zip container

        # Test ATS & Recruiter Word (.docx) + PDF master edition builder
        ed_res = client.post("/api/resumes/generate-edition", json={"edition": "ats", "cv_language": "en"})
        assert ed_res.status_code == 200
        ed = ed_res.json()
        assert ed["docx_filename"].endswith(".docx")
        assert client.get(ed["docx_url"]).content[:2] == b"PK"

        # Test My CVs upload, list, download, delete
        up_res = client.post(
            "/api/resumes/my-cvs/upload",
            files={"file": ("My_Test_Resume.docx", io.BytesIO(b"PK\x03\x04dummy-docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert up_res.status_code == 200
        my_list = client.get("/api/resumes/my-cvs").json()
        assert any(x["filename"] == "My_Test_Resume.docx" for x in my_list)
        del_res = client.delete("/api/resumes/my-cvs/My_Test_Resume.docx")
        assert del_res.status_code == 200
    finally:
        with Session(engine) as session:
            db_job = session.get(JobPosting, job_id)
            if db_job:
                session.delete(db_job)
                session.commit()


def test_jobsge_location_never_parsed_as_company_and_clean_highlights():
    """Ensures 'საქართველოს მასშტაბით' is never treated as company name and '---' never yields '--' bullet."""
    from app.services.scrapers.jobs_ge_scraper import jobs_ge_scraper
    from app.services.scrapers.base_scraper import sanitize_company_name
    from app.storage.ground_truth_store import ground_truth_store
    from app.services.cv_generator_service import cv_generator_service

    # 1. Jobs.ge row without view=client link & last column location
    html_row = """
    <table id="job_list_table">
      <tr>
        <td><a href="/ge/?view=jobs&id=763944">Manual QA სტაჟიორი</a></td>
        <td>02 ნოემბერი</td>
        <td>საქართველოს მასშტაბით</td>
      </tr>
    </table>
    """
    parsed = jobs_ge_scraper.parse_html_listings(html_row)
    assert len(parsed) == 1
    assert parsed[0]["company"] != "საქართველოს მასშტაბით"
    assert sanitize_company_name("საქართველოს მასშტაბით", target_email="info@genofit.tech") == "Genofit"

    # 2. Markdown horizontal divider --- never yields '--' highlight bullet
    md = """# Candidate — QA Engineer
## Work Experience
### Software QA Intern | Exactpro Systems
*Sep 2023 – Jan 2024*
- Validated trading calculations and API responses.
---
## Skills
- Playwright, Python, PyTest
"""
    parsed_profile = ground_truth_store.parse_profile_from_md(md)
    highlights = parsed_profile["work_history"][0]["highlights"]
    assert "--" not in highlights
    assert len(highlights) == 1

    # 3. Clean ASCII filenames, no intern title downgrade, & sanitized cover letter even with location string
    pkg = cv_generator_service.prepare_email_application_package(
        job_title="Manual QA სტაჟიორი",
        company="საქართველოს მასშტაბით",
        description="QA Bridge ტესტირების სტაჟირება. Manual Testing, Test Cases.",
        portal="jobs.ge",
        cv_language="ka",
        cv_style="ats",
    )
    assert "საქართველოს მასშტაბით" not in pkg["cover_letter"]
    assert pkg["docx_filename"].isascii()
    assert pkg["pdf_filename"].isascii()
    assert "QA_Engineer_ATS" in pkg["docx_filename"]


def test_action_plan_generation_includes_docs_and_tutorials():
    """Verifies AI Skill Gap Roadmap generation creates plans with official docs + practical tutorial links."""
    init_db()
    client.post("/api/profile/upload-skills", data={
        "content": "# Candidate\n## Skills\n- Playwright, Python, PyTest\n",
        "run_live_scrape": "false",
    })
    res = client.post("/api/profile/generate-action-plan")
    assert res.status_code == 200
    plans = res.json()
    assert len(plans) >= 1
    first_ms = plans[0]["milestones"][0]
    assert first_ms.get("resource_url", "").startswith("http")
    assert first_ms.get("tutorial_url", "").startswith("http")


def test_jobsge_nav_link_company_blocked_djinni_clean_title_and_salary_to_700():
    """Ensures 'ამ ორგანიზაციის ყველა განცხადება' never overwrites company names and Djinni 'to $700' parses cleanly."""
    from app.services.scrapers.base_scraper import sanitize_company_name

    assert sanitize_company_name("ამ ორგანიზაციის ყველა განცხადება", target_email="hr@a1qa.com") == "a1qa".capitalize() or sanitize_company_name("ამ ორგანიზაციის ყველა განცხადება", fallback="K") == "K"
    assert sanitize_company_name("ამ ორგანიზაციის ყველა განცხადება", fallback="Fallback") == "Fallback"

    dirty_dj_html = """
    <div class="job-item">
      <a class="job_item__header-link" href="/jobs/749999-trainee-manual-qa/">
        <h2 class="job-item__position">Trainee/Junior Manual QA Engineer</h2>
        <span class="mr-2">SoftPlus Ukraine</span>
        <span>Responds Quickly</span>
        <span>to $700</span>
      </a>
      <a href="/jobs/company-softplus-123/">SoftPlus Ukraine</a>
      <div class="fw-medium">Full Remote</div>
    </div>
    """
    parsed = djinni_scraper.parse_html_listings(dirty_dj_html)
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Trainee/Junior Manual QA Engineer"
    assert "Responds Quickly" not in parsed[0]["title"]
    assert "$700" not in parsed[0]["title"]
    assert "SoftPlus" in parsed[0]["company"]

    sal = salary_service.extract_vacancy_salary(parsed[0]["title"], parsed[0]["description_raw"])
    assert sal["min_salary"] == 700.0
    assert sal["max_salary"] == 700.0
    assert sal["currency"] == "USD"


def test_language_skill_gate_unlocks_ua_ru_pl_and_headhunter_parser():
    """Verifies UA/RU/PL jobs pass ONLY when candidate's skills.md includes that language, plus HeadHunter.ge parser."""
    from app.services.scrapers.headhunter_scraper import headhunter_scraper

    # Ukrainian job: blocked without Ukrainian, allowed when Ukrainian in skills.md
    _, st_no_uk, _, _ = evaluate_remote_and_language_gate(
        title="Manual QA Engineer",
        description="Віддалена робота. Вимоги: досвід тестування API, Postman, вільно володієте українською.",
        location_text="Київ, віддалено",
        portal="dou.ua",
        candidate_languages=["English", "Georgian"],
    )
    assert st_no_uk == "FILTERED_OUT"

    _, st_with_uk, _, _ = evaluate_remote_and_language_gate(
        title="Manual QA Engineer",
        description="Віддалена робота. Вимоги: досвід тестування API, Postman, вільно володієте українською.",
        location_text="Київ, віддалено",
        portal="dou.ua",
        candidate_languages=["English", "Georgian", "Ukrainian"],
    )
    assert st_with_uk == "DISCOVERED"

    # Russian HeadHunter.ge job: blocked without Russian, allowed with Russian
    _, st_no_ru, _, _ = evaluate_remote_and_language_gate(
        title="QA Engineer",
        description="Требования: опыт тестирования веб-приложений и REST API от 1 года, знание SQL и Postman.",
        location_text="Тбилиси",
        portal="headhunter.ge",
        candidate_languages=["English", "Georgian"],
    )
    assert st_no_ru == "FILTERED_OUT"

    _, st_with_ru, _, _ = evaluate_remote_and_language_gate(
        title="QA Engineer",
        description="Требования: опыт тестирования веб-приложений и REST API от 1 года, знание SQL и Postman.",
        location_text="Тбилиси",
        portal="headhunter.ge",
        candidate_languages=["English", "Georgian", "Russian"],
    )
    assert st_with_ru == "DISCOVERED"

    # Polish JustJoin job: allowed when Polish in skills.md
    _, st_with_pl, _, _ = evaluate_remote_and_language_gate(
        title="Tester manualny",
        description="Model pracy: remote. Poszukujemy doświadczonego Testera Manualnego. Długofalowa współpraca.",
        location_text="Warsaw, Remote",
        portal="justjoin.it",
        candidate_languages=["English", "Polish"],
    )
    assert st_with_pl == "DISCOVERED"

    # HeadHunter.ge card parser
    hh_html = """
    <div data-qa="vacancy-serp__vacancy">
      <a data-qa="serp-item__title" href="https://tbilisi.headhunter.ge/vacancy/123456789?from=serp">Software QA Engineer</a>
      <a data-qa="vacancy-serp__vacancy-employer" href="/employer/555">Itransition Software Georgia LLC</a>
      <span data-qa="vacancy-serp__vacancy-address">Тбилиси</span>
    </div>
    """
    hh_parsed = headhunter_scraper.parse_html_listings(hh_html)
    assert len(hh_parsed) == 1
    assert hh_parsed[0]["portal"] == "headhunter.ge"
    assert hh_parsed[0]["external_id"] == "hh-123456789"
    assert hh_parsed[0]["company"] == "Itransition Software Georgia LLC"


def test_clickable_docx_hyperlinks_english_tech_cv_no_email_footer_and_mime_attachment():
    """Verifies tech role auto-language -> EN CV, clickable GitHub/LinkedIn OOXML links in .docx, no email in CL footer, and MIME .docx attach."""
    import zipfile
    from app.services.cv_generator_service import cv_generator_service
    from app.services.gmail_service import gmail_service

    init_db()
    client.post("/api/profile/upload-skills", data={
        "content": (
            "# Giorgi Test — QA Automation Engineer\n"
            "Email: candidate@example.com | Phone: +995 555 112233\n"
            "GitHub: https://github.com/testqa | LinkedIn: https://linkedin.com/in/testqa\n\n"
            "## Core Skills\n"
            "- Playwright, Python, PyTest, TestRail, REST API, Docker\n\n"
            "## Work Experience\n"
            "### Software QA Intern | Exactpro Systems\n"
            "*September 2023 – January 2024*\n"
            "- Validated financial calculation rules against benchmark specifications.\n"
        ),
        "run_live_scrape": "false",
    })

    # auto language on Georgian QA tech listing -> crisp English CV + Georgian cover letter + no candidate email in footer
    pkg = cv_generator_service.prepare_email_application_package(
        job_title="Manual QA სტაჟიორი",
        company="GenofIT",
        description="ვეძებთ მანუალ QA სტაჟიორს. მოთხოვნები: Manual Testing, Test Cases, Jira.",
        portal="jobs.ge",
        target_email="hr@genofit.tech",
        cv_language="auto",
        cv_style="tailored",
    )
    assert pkg["cv_language"] == "en"
    assert "candidate@example.com" not in pkg["cover_letter"]
    assert "მოგესალმებით, GenofIT-ის გუნდს" in pkg["cover_letter"]

    # Check Word .docx contains clickable OOXML hyperlink targets
    with zipfile.ZipFile(pkg["docx_path"], "r") as zf:
        rels_xml = zf.read("word/_rels/document.xml.rels").decode("utf-8", errors="ignore")
        doc_xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    assert "github.com/testqa" in rels_xml
    assert "linkedin.com/in/testqa" in rels_xml
    assert "<w:hyperlink" in doc_xml

    # Check MIME builder attaches .docx cleanly for Gmail Drafts
    mime_msg = gmail_service.build_mime_message(
        sender_email="sender@example.com",
        to_email="hr@genofit.tech",
        subject=pkg["subject"],
        body_text=pkg["cover_letter"],
        attachment_paths=[pkg["docx_path"]],
    )
    filenames = [part.get_filename() for part in mime_msg.walk() if part.get_filename()]
    assert pkg["docx_filename"] in filenames

    # AI QA roadmap must NOT falsely skip 'AI' just because candidate has 'TestRail'
    ai_res = client.post("/api/profile/generate-action-plan")
    assert ai_res.status_code == 200
    plan_titles = [p["skill_name"] for p in ai_res.json()]
    assert any("AI" in t for t in plan_titles)


def test_universal_domain_agnostic_ingestion_query_builder_hr_gov_and_multi_tier():
    """Tests Logistics/QA domain-agnostic ingestion, dynamic queries, hr.gov.ge parser, 2.0-yr cap, and Direct/Adjacent tiers."""
    from app.services.profile_service import profile_service
    from app.services.scrapers.query_builder import build_search_queries
    from app.services.scrapers.hr_gov_scraper import hr_gov_scraper

    # 1. Non-IT Logistics skills.md adapts cleanly without QA bias
    logistics_md = """# Nika Kapanadze — Supply Chain & Logistics Coordinator
## Contact & Personal Info
- **Email:** logistics.test@example.com
- **Experience:** 1.5 years in freight coordination and procurement.
## Core Skills
- Logistics, Supply Chain, Procurement, Incoterms, Customs Clearance, Excel, 1C, ERP
"""
    log_prof = profile_service.extract_structured_profile(logistics_md)
    assert "Logistics" in log_prof.detected_industry
    assert "Logistics" in log_prof.primary_role or "Supply Chain" in log_prof.primary_role
    assert log_prof.max_allowed_years <= 2.0
    assert len(log_prof.adjacent_roles) >= 2
    assert any("Procurement" in r for r in log_prof.adjacent_roles)

    # Dynamic queries for Logistics must NOT lock Jobs.ge to IT cid=6
    log_queries = build_search_queries({
        "target_industry": log_prof.target_industry,
        "detected_industry": log_prof.detected_industry,
        "primary_role": log_prof.primary_role,
        "adjacent_roles": log_prof.adjacent_roles,
        "verified_skills": log_prof.verified_skills,
        "years_of_experience": log_prof.experience_years,
    })
    assert len(log_queries["jobs_ge_urls"]) >= 2
    assert all("cid=6" not in u for u in log_queries["jobs_ge_urls"])
    assert "სტაჟიორი" in log_queries["internship_queries"]

    # 2. Strict 2.0-year guard + Direct vs Adjacent tier evaluation for QA candidate
    qa_parsed = {
        "target_industry": "qa_tech",
        "primary_role": "QA Automation Engineer",
        "adjacent_roles": ["Technical Support Engineer L2/L3", "Data Quality Analyst"],
        "verified_skills": ["Playwright", "Python", "PyTest", "Postman", "REST API", "SQL", "Linux"],
        "all_skills": ["Playwright", "Python", "PyTest", "Postman", "REST API", "SQL", "Linux"],
        "years_of_experience": 1.5,
        "max_allowed_years": 2.0,
        "seniority_level": "JUNIOR",
        "search_queries": build_search_queries({
            "target_industry": "qa_tech",
            "primary_role": "QA Automation Engineer",
            "adjacent_roles": ["Technical Support Engineer L2/L3", "Data Quality Analyst"],
            "verified_skills": ["Playwright", "Python", "PyTest", "Postman", "REST API", "SQL", "Linux"],
            "years_of_experience": 1.5,
        }),
    }

    # Reject Middle+ or 2-3 years exp under strict 2.0 cap
    res_mid_plus = matcher_service.evaluate_job_tiered(
        title="Middle+ QA Automation Engineer",
        description="Requires Playwright and Python.",
        parsed_skills=qa_parsed,
    )
    assert res_mid_plus["status"] == "FILTERED_OUT"

    res_3yr = matcher_service.evaluate_job_tiered(
        title="QA Engineer",
        description="Requires 2-3 years of experience in manual and API testing.",
        parsed_skills=qa_parsed,
    )
    assert res_3yr["status"] == "FILTERED_OUT"

    # Tier 1 DIRECT match
    res_direct = matcher_service.evaluate_job_tiered(
        title="Junior QA Automation Engineer (Playwright / Python)",
        description="1-2 years experience. Requirements: Playwright, Python, PyTest, REST API.",
        parsed_skills=qa_parsed,
        portal="djinni.co",
    )
    assert res_direct["status"] == "STAGED"
    assert res_direct["match_tier"] == "DIRECT"
    assert res_direct["suitability_score"] >= 80.0

    # Tier 2 ADJACENT transferable match (QA skills SQL + Postman + Linux -> Technical Support L2/L3)
    res_adj = matcher_service.evaluate_job_tiered(
        title="Technical Support Engineer L2",
        description="Troubleshooting customer API integrations using Postman, SQL, REST API, and Linux logs. 1 year experience.",
        parsed_skills=qa_parsed,
        portal="jobs.ge",
    )
    assert res_adj["status"] != "FILTERED_OUT"
    assert res_adj["match_tier"] == "ADJACENT"
    assert res_adj["adjacent_role_tag"] and "Skill Overlap" in res_adj["adjacent_role_tag"]
    assert res_adj["skill_overlap_pct"] and res_adj["skill_overlap_pct"] >= 65

    # 3. HR.gov.ge parser + Tier 3 PUBLIC_INTERNSHIP classification
    hr_gov_html = """
    <table>
      <tr>
        <td><img src="/src/images/other32.png"/></td>
        <td><a href="/JobProvider/UserOrgVaks/Details/103915?active=1">სტრატეგიული კოორდინაციისა და ანალიტიკის სამსახურის სტაჟიორი</a></td>
        <td><a href="/JobProvider/UserOrgVaks/Details/103915?active=1">სსიპ - დაცული ტერიტორიების სააგენტო</a></td>
        <td>15.11.2026</td>
      </tr>
    </table>
    """
    hr_gov_items = hr_gov_scraper.parse_html_listings(hr_gov_html)
    assert len(hr_gov_items) == 1
    assert hr_gov_items[0]["portal"] == "hr.gov.ge"
    assert hr_gov_items[0]["company"] == "სსიპ - დაცული ტერიტორიების სააგენტო"
    assert hr_gov_items[0]["deadline_text"] == "15.11.2026"

    res_pub = matcher_service.evaluate_job_tiered(
        title=hr_gov_items[0]["title"],
        description="სტაჟირება ანალიტიკის მიმართულებით. SQL, Excel, მონაცემთა დამუშავება.",
        parsed_skills=qa_parsed,
        portal="hr.gov.ge",
    )
    assert res_pub["status"] != "FILTERED_OUT"
    assert res_pub["match_tier"] == "PUBLIC_INTERNSHIP"

    # 4. Preset switching purges stale JobPosting rows cleanly (fixes Screenshot 3)
    with Session(engine) as s:
        s.add(JobPosting(
            portal="jobs.ge",
            external_id="stale-qa-switch-test",
            title="Stale QA Role",
            company="OldCorp",
            url="https://jobs.ge/ge/?view=jobs&id=9999991",
            status="STAGED",
            suitability_score=90.0,
        ))
        s.commit()

    sw_res = client.post("/api/skills-md/preset/receptionist_hospitality")
    assert sw_res.status_code == 200
    # Receptionist email package must NEVER leak QA wording, placeholder +000 phones, or raw .docx filenames into Cover Letter
    from app.services.cv_generator_service import cv_generator_service
    rec_pkg = cv_generator_service.prepare_email_application_package(
        job_title="რეცეფციონისტი/ადმინისტრატორი",
        company="მზიური გარდენსი",
        description="ვეძებთ რეცეფციონისტს სასტუმროში. Front Desk, Check-in, Hospitality, Opera PMS.",
        portal="jobs.ge",
        target_email="hr@hotel.example",
        cv_language="auto",
    )
    assert "QA" not in rec_pkg["cover_letter"]
    assert "REST API" not in rec_pkg["cover_letter"]
    assert "+000" not in rec_pkg["cover_letter"]
    assert ".docx" not in rec_pkg["cover_letter"]
    assert "nino_kalandadze_nino_kalanda" not in rec_pkg["docx_filename"].lower()
    assert rec_pkg["docx_filename"] == "Nino_Kalandadze_mziuri_gardensi_CV_KA.docx" or "Nino_Kalandadze" in rec_pkg["docx_filename"]

    from sqlmodel import select
    with Session(engine) as s:
        leftover = s.exec(select(JobPosting).where(JobPosting.external_id == "stale-qa-switch-test")).all()
        assert len(leftover) == 0
    # Restore QA preset after switch check
    client.post("/api/skills-md/preset/qa_tech")
