from app.services.b2b_tax_service import GEO_TAX_CONFIG, compute_georgia_b2b_net, compute_timezone_matrix
from app.services.cv.context import build_cv_render_context
from app.services.matching.gates import (
    DisciplineGate,
    LanguageGate,
    SeniorityGate,
    run_gate_pipeline,
)


def test_b2b_tax_service_citation_and_threshold_crossing():
    assert "Article 90" in GEO_TAX_CONFIG["citation"]
    assert GEO_TAX_CONFIG["effective_as_of"]
    assert "not legal or tax advice" in GEO_TAX_CONFIG["disclaimer"].lower()

    res = compute_georgia_b2b_net(
        amount=5000.0,
        currency="USD",
        billing_period="monthly",
        hours_per_month=160,
        fx=2.70,
        fx_source="custom",
        fx_as_of=None,
        include_pension_for_labor=True,
        transfer_fee_pct=0.5,
        ytd_revenue_gel=0.0,
    )
    assert res["under_500k_cap"] is True
    assert res["b2b_small_business"]["tax_rate_pct"] == 1.0
    assert res["tax_rule_source"] == GEO_TAX_CONFIG["citation"]

    tz = compute_timezone_matrix(11, 19)
    assert len(tz["regions"]) == 5
    assert "Asia/Tbilisi" in tz["base_timezone"]


def test_matching_gate_pipeline_characterization():
    qa_profile = {
        "target_industry": "qa_tech",
        "primary_role": "Junior QA Engineer",
        "years_of_experience": 0.5,
        "max_allowed_years": 1.0,
        "all_skills": ["Playwright", "Python", "SQL", "REST API", "Jira"],
        "spoken_languages": ["Georgian (Native)", "English (C1)"],
    }

    # Senior 5+ years role must fail SeniorityGate
    res_senior = SeniorityGate().evaluate(
        title="Senior QA Automation Lead",
        description="Minimum 5+ years of QA engineering leadership required.",
        parsed_skills=qa_profile,
    )
    assert res_senior.passed is False and res_senior.reason

    # Entry QA role passes full pipeline
    results = run_gate_pipeline(
        title="Junior QA Engineer",
        description="Manual testing, Playwright automation, Python, SQL, REST API testing.",
        parsed_skills=qa_profile,
        portal="jobs.ge",
    )
    assert all(r.passed for r in results), results
    assert DisciplineGate().evaluate(
        title="Junior QA Engineer",
        description="Playwright SQL REST API",
        parsed_skills=qa_profile,
    ).metadata["tier"] == "DIRECT"
    assert LanguageGate().evaluate(
        title="QA Engineer (вільно володіє українською)",
        description="Потрібен досвід тестування та вільне володіння українською мовою. Remote.",
        parsed_skills=qa_profile,
        portal="dou.ua",
    ).passed is False


def test_cv_render_context_dataclass_preserves_verified_fields_only():
    ctx = build_cv_render_context(
        candidate={
            "full_name": "Nino Beridze",
            "headline": "Financial Analyst",
            "email": "nino@example.ge",
            "phone": "+995 599 000111",
            "location": {"city": "Tbilisi", "country": "Georgia"},
            "links": {"linkedin": "https://linkedin.com/in/nino"},
        },
        summary="Verified IFRS analyst.",
        display_skills=["IFRS", "SQL", "Excel"],
        cv_language="en",
        cv_style="ats",
    )
    assert ctx.full_name == "Nino Beridze"
    assert ctx.location == "Tbilisi, Georgia"
    assert ctx.display_skills == ["IFRS", "SQL", "Excel"]
    assert ctx.cv_style == "ats"
