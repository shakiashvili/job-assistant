import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.db.database import engine, init_db
from app.db.models import JobPosting, UserJobMatch
from app.services.salary_service import salary_service


def _register_and_auth(client: TestClient, prefix: str) -> dict:
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@example.ge"
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "StrongPassword123!", "full_name": "Evolution Tester"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_phase2_safe_import_preview_selective_merge_and_profile_intelligence():
    """Verifies safe CV import preview (zero silent overwrite), selective per-section merge, and profile intelligence checks."""
    init_db()
    client = TestClient(app)
    headers = _register_and_auth(client, "phase2_prof")

    # Seed an existing manual profile with confirmed identity, duplicate skill variants, and a bad timeline
    manual = {
        "candidate": {
            "first_name": "Nino",
            "last_name": "Kapanadze",
            "full_name": "Nino Kapanadze",
            "headline": "Confirmed Financial Analyst",
            "summary": "Confirmed summary that must not be silently overwritten.",
            "email": "nino.confirmed@example.ge",
            "phone": "+995 599 111222",
            "location": {"city": "Tbilisi", "country": "Georgia", "open_to_relocation": False, "remote_preference": "Remote"},
            "links": {"linkedin": "https://linkedin.com/in/nino-k", "github": "", "portfolio": ""},
            "languages": [{"language": "Georgian", "proficiency": "Native"}],
        },
        "skills": {"core": ["JS", "JavaScript", "IFRS", "SQL"], "secondary": []},
        "work_history": [
            {
                "role": "Analyst",
                "company": "TBC Bank",
                "location": "Tbilisi",
                "start_date": "2025",
                "end_date": "2023",
                "highlights": ["Built financial reporting dashboards"],
            }
        ],
        "education": [{"degree": "B.Sc. Economics", "institution": "TSU", "dates": "2020-2024"}],
        "projects": [{"title": "IFRS Automation Tool", "organization": "Personal", "dates": "2025", "highlights": ["Automated balance checks"]}],
        "certifications": ["ACCA F1"],
    }
    assert client.put("/api/ground-truth", json=manual, headers=headers).status_code == 200

    # 1. Profile intelligence detects duplicate skill group (JS / JavaScript) and end-before-start timeline warning
    r_intel = client.get("/api/profile/intelligence", headers=headers)
    assert r_intel.status_code == 200, r_intel.text
    intel = r_intel.json()
    assert any(d["canonical"] == "javascript" for d in intel["duplicate_skills"])
    assert any("precedes start year" in w["message"] for w in intel["timeline_warnings"])

    # 2. Import preview extracts structured sections WITHOUT overwriting existing profile
    imported_md = (
        "# Different Name — Senior Software Engineer\n"
        "## Summary\nNew extracted summary.\n"
        "## Core Skills\n- Python, Power BI, SQL\n"
        "## Work Experience\n"
        "### Data Analyst | Bank of Georgia | Jan 2024 - Jan 2025\n"
        "- Built SQL reports.\n"
    ).encode("utf-8")
    r_prev = client.post(
        "/api/profile/import-preview",
        files={"file": ("resume.md", imported_md, "text/markdown")},
        headers=headers,
    )
    assert r_prev.status_code == 200, r_prev.text
    prev = r_prev.json()
    assert prev["diff_summary"]["extracted_skills_count"] >= 2
    assert prev["diff_summary"]["existing_has_data"] is True

    # Confirm DB was NOT modified by preview
    gt_after_preview = client.get("/api/ground-truth", headers=headers).json()
    assert gt_after_preview["candidate"]["headline"] == "Confirmed Financial Analyst"
    assert "Power BI" not in gt_after_preview["skills"]["core"]

    # 3. Apply selective merge: candidate=merge (keep existing confirmed fields), skills=merge, work_history=skip
    r_apply = client.post(
        "/api/profile/import-apply",
        headers=headers,
        json={
            "filename": "resume.md",
            "extracted": prev["extracted"],
            "section_modes": {
                "candidate": "merge",
                "skills": "merge",
                "work_history": "skip",
                "education": "skip",
                "projects": "skip",
                "certifications": "skip",
            },
        },
    )
    assert r_apply.status_code == 200, r_apply.text
    applied = r_apply.json()["data"]
    assert applied["candidate"]["headline"] == "Confirmed Financial Analyst"
    assert applied["candidate"]["full_name"] == "Nino Kapanadze"
    core_lower = {s.lower() for s in applied["skills"]["core"]}
    assert "power bi" in core_lower and "ifrs" in core_lower
    assert len(applied["work_history"]) == 1 and applied["work_history"][0]["company"] == "TBC Bank"


def test_phase3_salary_normalization_industry_filter_and_feedback_loop():
    """Verifies normalized salary period/gross-net extraction, backend industry filter, recommendation breakdown, and dismiss/restore feedback."""
    # 1. Salary period & gross/net normalization (never compares annual to monthly directly)
    s_annual = salary_service.extract_vacancy_salary("Senior Analyst", "Compensation: $60,000 - $72,000 per year gross.")
    assert s_annual["salary_period"] == "annual"
    assert s_annual["gross_net"] == "gross"
    assert s_annual["normalized_monthly_min"] == 5000.0
    assert s_annual["normalized_monthly_max"] == 6000.0

    s_monthly = salary_service.extract_vacancy_salary("Accountant", "Salary: 4,000 - 5,000 GEL net per month.")
    assert s_monthly["salary_period"] == "monthly"
    assert s_monthly["gross_net"] == "net"
    assert s_monthly["normalized_monthly_min"] == 4000.0

    # 2. Industry filter, recommendation_breakdown, and per-user dismiss/restore feedback
    init_db()
    client = TestClient(app)
    headers = _register_and_auth(client, "phase3_jobs")
    assert client.post(
        "/api/skills-md",
        headers=headers,
        json={"content": "# Finance Candidate — Financial Accountant\n## Skills\n- IFRS, Audit, Excel, SQL, Financial Reporting\n"},
    ).status_code == 200
    uid = client.get("/api/auth/me", headers=headers).json()["id"]

    with Session(engine) as session:
        j_fin = JobPosting(
            user_id=uid,
            portal="jobs.ge",
            external_id=f"p3-fin-{uuid.uuid4().hex[:6]}",
            title="Junior Financial Accountant (IFRS)",
            company="Liberty Bank",
            url=f"https://jobs.ge/ge/?view=jobs&id={uuid.uuid4().hex[:8]}",
            market="GE_DOMESTIC",
            is_remote=False,
            description_raw="Monthly salary 3000 - 4000 GEL net. IFRS reporting, audit support, Excel and SQL.",
            salary_min=3000.0,
            salary_max=4000.0,
            salary_currency="GEL",
            suitability_score=88.0,
            match_tier="DIRECT",
            status="STAGED",
        )
        j_hosp = JobPosting(
            user_id=uid,
            portal="hr.ge",
            external_id=f"p3-hosp-{uuid.uuid4().hex[:6]}",
            title="Hotel Receptionist & Concierge",
            company="Tbilisi Boutique Hotel",
            url=f"https://hr.ge/announcement/{uuid.uuid4().hex[:8]}",
            market="GE_DOMESTIC",
            is_remote=False,
            description_raw="Front desk hotel hospitality operations.",
            suitability_score=70.0,
            match_tier="ADJACENT",
            status="STAGED",
        )
        session.add(j_fin)
        session.add(j_hosp)
        session.flush()
        session.add(UserJobMatch(user_id=uid, job_posting_id=j_fin.id, suitability_score=88.0, match_score=88.0, status="STAGED", matched_skills=["IFRS", "SQL"], missing_skills=["SAP"]))
        session.add(UserJobMatch(user_id=uid, job_posting_id=j_hosp.id, suitability_score=70.0, match_score=70.0, status="STAGED"))
        session.commit()
        fin_id = j_fin.id

    r_ind = client.get("/api/jobs?industry=finance_banking", headers=headers)
    assert r_ind.status_code == 200
    items = r_ind.json()["items"]
    assert any(it["id"] == fin_id for it in items)
    assert all(it["company"] != "Tbilisi Boutique Hotel" for it in items)

    fin_item = next(it for it in items if it["id"] == fin_id)
    assert fin_item["salary_period"] == "monthly"
    assert fin_item["salary_gross_net"] == "net"
    assert "not a hiring probability" in fin_item["recommendation_breakdown"]["score_disclaimer"].lower()

    # Dismiss with reason -> hides from default feed without modifying profile
    r_fb = client.post(
        f"/api/jobs/{fin_id}/feedback",
        headers=headers,
        json={"action": "dismiss", "reason": "wrong_location", "note": "Prefer remote only"},
    )
    assert r_fb.status_code == 200 and r_fb.json()["is_ignored"] is True
    r_after = client.get("/api/jobs?industry=finance_banking", headers=headers)
    assert all(it["id"] != fin_id for it in r_after.json()["items"])

    # Restore dismissed job
    r_restore = client.delete(f"/api/jobs/{fin_id}/feedback", headers=headers)
    assert r_restore.status_code == 200 and r_restore.json()["is_ignored"] is False
    r_restored_list = client.get("/api/jobs?industry=finance_banking", headers=headers)
    assert any(it["id"] == fin_id for it in r_restored_list.json()["items"])


def test_phase4_5_6_blank_duplicate_cv_immutable_app_snapshot_and_mock_interview():
    """Verifies blank & Georgian CV creation, CV duplication, immutable application snapshot surviving CV deletion, accurate analytics, and interactive mock interview + private deletion."""
    init_db()
    client = TestClient(app)
    headers = _register_and_auth(client, "phase456_e2e")

    assert client.post(
        "/api/skills-md",
        headers=headers,
        json={
            "content": (
                "# Giorgi Test — QA Automation Engineer\n"
                "## Skills\n- Playwright, Python, SQL, REST API, Jira\n"
                "## Work Experience\n"
                "### QA Engineer | TechLab | Jan 2025 - Jan 2026\n"
                "- Built Playwright E2E regression tests and API validation suites.\n"
            )
        },
    ).status_code == 200

    # Phase 4: Create a blank Georgian CV and duplicate it
    r_blank = client.post(
        "/api/cv-versions",
        headers=headers,
        json={
            "title": "Blank Georgian CV",
            "target_role": "ხარისხის უზრუნველყოფის სპეციალისტი",
            "target_company": "ProCredit Bank",
            "edition": "minimalist",
            "language": "ka",
            "blank": True,
            "cover_letter": "მოგესალმებით, გიგზავნით ჩემს რეზიუმეს.",
            "motivational_letter": "ჩემი მოტივაციაა ხარისხის სტანდარტების გაუმჯობესება.",
        },
    )
    assert r_blank.status_code == 200, r_blank.text
    cv1 = r_blank.json()
    assert cv1["language"] == "ka"
    assert cv1["structured_json"].get("created_from_blank") is True
    assert cv1["pdf_filename"] and cv1["docx_filename"]

    r_dup = client.post(f"/api/cv-versions/{cv1['id']}/duplicate", headers=headers)
    assert r_dup.status_code == 200, r_dup.text
    cv2 = r_dup.json()
    assert cv2["id"] != cv1["id"]
    assert cv2["version_number"] == cv1["version_number"] + 1
    assert cv2["cover_letter"] == cv1["cover_letter"]
    assert cv2["motivational_letter"] == cv1["motivational_letter"]

    # Phase 5: Create application linked to cv1 + a separate unsent Interested draft, then delete cv1
    r_app = client.post(
        "/api/applications",
        headers=headers,
        json={
            "company": "ProCredit Bank",
            "role": "Junior QA Engineer",
            "portal": "jobs.ge",
            "status": "HR Screening",
            "cv_version_id": cv1["id"],
            "follow_up_date": "2025-01-01",
            "recruiter_name": "Ana HR",
            "recruiter_email": "hr@procredit.ge",
            "notes": "Requires Playwright, Python, SQL, and Docker knowledge.",
        },
    )
    assert r_app.status_code in (200, 201), r_app.text
    app_id = r_app.json()["id"]

    # Add an unsent Interested draft — must NOT dilute submitted response_rate_pct
    assert client.post(
        "/api/applications",
        headers=headers,
        json={"company": "DraftCo", "role": "QA Analyst", "portal": "hr.ge", "status": "Interested"},
    ).status_code in (200, 201)

    # Delete cv1 — historical document snapshot inside the application MUST survive intact!
    assert client.delete(f"/api/cv-versions/{cv1['id']}", headers=headers).status_code == 200
    r_app_get = client.get(f"/api/applications/{app_id}", headers=headers)
    assert r_app_get.status_code == 200
    doc_snap = r_app_get.json()["jd_snapshot"]["document_snapshot"]
    assert doc_snap is not None
    assert doc_snap["title"] == "Blank Georgian CV"
    assert doc_snap["cover_letter"] == cv1["cover_letter"]

    # Analytics: 1 submitted (HR Screening) + 1 unsent Interested -> 100% response/interview rate over submitted, 1 due follow-up
    r_ana = client.get("/api/applications/analytics", headers=headers)
    assert r_ana.status_code == 200
    ana = r_ana.json()
    assert ana["applications_submitted"] == 1
    assert ana["response_rate_pct"] == 100.0
    assert ana["follow_ups_due"] == 1
    assert "Blank Georgian CV" in ana["by_cv_version"]

    # Phase 6: Vacancy-grounded interview prep, interactive 1-question mock answer evaluation, and private deletion
    r_prep = client.post(
        f"/api/applications/{app_id}/prepare-interview",
        headers=headers,
        json={"round_type": "TECH_INTERVIEW"},
    )
    assert r_prep.status_code == 200, r_prep.text
    brief = r_prep.json()
    assert len(brief["prep_plan"]) >= 3
    assert "Docker" in brief["experience_gaps"]
    round_id = brief["round_id"]
    first_q_id = brief["predicted_questions"][0]["id"]

    r_mock = client.post(
        f"/api/applications/{app_id}/interviews/{round_id}/mock-answer",
        headers=headers,
        json={
            "question_id": first_q_id,
            "answer_text": (
                "During my QA role at TechLab, my goal was to prevent checkout regressions before release. "
                "I built automated Playwright smoke tests in Python and validated REST API endpoints, "
                "which caught two critical schema defects before deployment."
            ),
        },
    )
    assert r_mock.status_code == 200, r_mock.text
    mock_res = r_mock.json()
    assert mock_res["evaluation"]["relevance_score"] >= 60
    assert mock_res["evaluation"]["star_coverage"]["action"] is True
    assert "Playwright" in mock_res["evaluation"]["covered_verified_skills"]
    assert mock_res["mock_progress"]["answered_count"] == 1

    # Private deletion of interview session
    r_del_round = client.delete(f"/api/applications/{app_id}/interviews/{round_id}", headers=headers)
    assert r_del_round.status_code == 200
    r_rounds = client.get(f"/api/applications/{app_id}/interviews", headers=headers)
    assert r_rounds.status_code == 200
    assert all(r["id"] != round_id for r in r_rounds.json())
