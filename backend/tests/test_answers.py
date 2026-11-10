from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_generate_screening_answers():
    payload = {
        "questions": [
            {
                "id": "q1",
                "question": "What is your desired gross annual salary?",
                "field_type": "text"
            },
            {
                "id": "q2",
                "question": "What is your earliest start date or notice period?",
                "field_type": "text"
            },
            {
                "id": "q3",
                "question": "Are you legally authorized to work in Germany/EU without sponsorship?",
                "field_type": "select"
            },
            {
                "id": "q4",
                "question": "Applicant summary — introduce yourself briefly",
                "field_type": "textarea"
            }
        ],
        "job_title": "Senior QA Automation Engineer",
        "company": "MacPaw",
        "portal": "dou.ua",
        "variant": "qa_automation"
    }

    response = client.post("/api/generate-answers", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["answers"]) == 4
    assert data["default_start_date"] == "1 week after offer"
    assert "dou_motivational_letter" in data
    assert "applicant_summary" in data

    answers_map = {a["question"]: a["answer"] for a in data["answers"]}
    assert "38,000" in answers_map["What is your desired gross annual salary?"] or "85,000" in answers_map["What is your desired gross annual salary?"]
    assert answers_map["What is your earliest start date or notice period?"] == "1 week after offer"
    assert "Yes" in answers_map["Are you legally authorized to work in Germany/EU without sponsorship?"]
    assert "1 week after offer" in answers_map["Applicant summary — introduce yourself briefly"]
