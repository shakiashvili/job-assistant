import pytest
from app.services.playwright_service import playwright_service
from app.config import MOCK_PORTALS_DIR


@pytest.mark.asyncio
async def test_playwright_dou_ua_staging():
    mock_url = (MOCK_PORTALS_DIR / "dou_sample.html").as_uri()
    result = await playwright_service.stage_application(
        job_url=mock_url,
        variant="qa_automation",
        headless=True,
        timeout_seconds=3
    )

    assert result.status == "staged"
    assert result.portal_detected == "dou.ua"
    assert "full_name" in result.fields_filled
    assert "applicant_summary" in result.fields_filled
    assert "dou_motivational_letter" in result.fields_filled
    assert "start_date_1_week" in result.fields_filled
    assert "captcha_verified" in result.fields_filled
    assert result.captcha_status == "solved"
    assert result.file_uploaded is True


@pytest.mark.asyncio
async def test_playwright_greenhouse_staging():
    mock_url = (MOCK_PORTALS_DIR / "greenhouse_sample.html").as_uri()
    result = await playwright_service.stage_application(
        job_url=mock_url,
        variant="qa_automation",
        headless=True,
        timeout_seconds=3
    )

    assert result.status == "staged"
    assert result.portal_detected == "greenhouse"
    assert "first_name" in result.fields_filled
    assert "last_name" in result.fields_filled
    assert "email" in result.fields_filled
    assert "resume_pdf" in result.fields_filled
    assert "captcha_verified" in result.fields_filled
    assert result.file_uploaded is True


@pytest.mark.asyncio
async def test_playwright_lever_staging():
    mock_url = (MOCK_PORTALS_DIR / "lever_sample.html").as_uri()
    result = await playwright_service.stage_application(
        job_url=mock_url,
        variant="qa_automation",
        headless=True,
        timeout_seconds=3
    )

    assert result.status == "staged"
    assert result.portal_detected == "lever"
    assert "full_name" in result.fields_filled
    assert "email" in result.fields_filled
    assert "resume_pdf" in result.fields_filled
    assert "captcha_verified" in result.fields_filled
    assert result.file_uploaded is True
