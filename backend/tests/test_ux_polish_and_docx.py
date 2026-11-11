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
