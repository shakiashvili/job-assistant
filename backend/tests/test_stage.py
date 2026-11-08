import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import MOCK_PORTALS_DIR

client = TestClient(app)


def test_stage_application_endpoint():
    mock_url = (MOCK_PORTALS_DIR / "greenhouse_sample.html").as_uri()
    payload = {
        "job_url": mock_url,
        "variant": "qa_automation",
        "headless": True,
        "timeout_seconds": 3
    }
    response = client.post("/api/stage-application", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "staged"
    assert data["portal_detected"] == "greenhouse"
    assert data["file_uploaded"] is True
    assert "resume_pdf" in data["fields_filled"]
    assert data["manual_review_needed"] is True
