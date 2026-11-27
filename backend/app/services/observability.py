"""Lightweight operational telemetry and structured request logging for TalentFlow AI."""

import json
import logging
import threading
import time
from typing import Any, Dict

logger = logging.getLogger("talentflow.observability")


class RuntimeMetrics:
    """Thread-safe in-process HTTP metrics counter exposed via /api/metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._requests_total = 0
        self._errors_5xx = 0
        self._latency_ms_sum = 0.0

    def record(self, *, status_code: int, latency_ms: float) -> None:
        with self._lock:
            self._requests_total += 1
            if status_code >= 500:
                self._errors_5xx += 1
            self._latency_ms_sum += max(0.0, latency_ms)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            total = self._requests_total
            avg_ms = round(self._latency_ms_sum / total, 2) if total else 0.0
            return {
                "uptime_seconds": round(time.monotonic() - self._started_at, 1),
                "http_requests_total": total,
                "http_errors_5xx": self._errors_5xx,
                "avg_latency_ms": avg_ms,
            }


def log_structured_request(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
) -> None:
    """Emits a PII-free structured JSON log line for slow or failing HTTP requests."""
    payload = {
        "event": "http_request",
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
    }
    if status_code >= 500:
        logger.error(json.dumps(payload))
    elif latency_ms >= 1500.0:
        logger.warning(json.dumps(payload))


runtime_metrics = RuntimeMetrics()
