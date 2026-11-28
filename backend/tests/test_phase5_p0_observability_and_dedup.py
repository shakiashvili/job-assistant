from fastapi.testclient import TestClient

from app.main import app
from app.services.job_query_service import cluster_cross_portal_jobs
from app.services.scrapers.scraper_orchestrator import ScraperOrchestrator

client = TestClient(app)


def test_observability_request_id_healthz_readyz_and_metrics():
    r_live = client.get("/healthz", headers={"X-Request-ID": "req-phase5-trace"})
    assert r_live.status_code == 200
    assert r_live.json()["status"] == "alive"
    assert r_live.headers.get("X-Request-ID") == "req-phase5-trace"

    r_ready = client.get("/readyz")
    assert r_ready.status_code == 200
    assert r_ready.json()["database_reachable"] is True
    assert r_ready.headers.get("X-Request-ID")

    r_metrics = client.get("/api/metrics")
    assert r_metrics.status_code == 200
    body = r_metrics.json()
    assert body["http"]["http_requests_total"] >= 2
    assert body["scrapers"]["total_sources"] == 12
    assert "b2b_hub_enabled" in body["features"]


def test_scraper_health_zero_results_three_runs_alert():
    orch = ScraperOrchestrator()
    orch._record_source_health("jobs.ge", "ok", 0, 120)
    orch._record_source_health("jobs.ge", "ok", 0, 110)
    h2 = next(s for s in orch.get_source_health() if s["portal"] == "jobs.ge")
    assert h2["consecutive_zero_runs"] == 2
    assert h2["zero_run_alert"] is False

    orch._record_source_health("jobs.ge", "ok", 0, 105)
    h3 = next(s for s in orch.get_source_health() if s["portal"] == "jobs.ge")
    assert h3["consecutive_zero_runs"] == 3
    assert h3["zero_run_alert"] is True

    # Non-zero run clears alert
    orch._record_source_health("jobs.ge", "ok", 8, 95)
    h4 = next(s for s in orch.get_source_health() if s["portal"] == "jobs.ge")
    assert h4["consecutive_zero_runs"] == 0
    assert h4["zero_run_alert"] is False


def test_cross_portal_deduplication_attaches_also_on_portals():
    items = [
        {"id": 1, "portal": "jobs.ge", "company": "TBC Bank", "title": "Junior QA Engineer", "suitability_score": 88},
        {"id": 2, "portal": "hr.ge", "company": "TBC Bank!", "title": "Junior QA Engineer", "suitability_score": 84},
        {"id": 3, "portal": "headhunter.ge", "company": "TBC Bank", "title": "Junior QA Engineer", "suitability_score": 80},
        {"id": 4, "portal": "jobs.ge", "company": "Payze", "title": "QA Analyst", "suitability_score": 79},
    ]
    clustered = cluster_cross_portal_jobs(items)
    assert len(clustered) == 2
    tbc = clustered[0]
    assert tbc["portal"] == "jobs.ge"
    assert tbc["also_on_portals"] == ["hr.ge", "headhunter.ge"]
    assert clustered[1]["also_on_portals"] == []
