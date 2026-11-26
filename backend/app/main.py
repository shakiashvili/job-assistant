import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text
from .config import GEMINI_MODEL, GEMINI_FAST_MODEL, DATABASE_URL, FRONTEND_URL, ENABLE_PLAYWRIGHT, IS_PRODUCTION
from .db.database import engine, init_db
from .services.gemini_service import gemini_service
from .services.scrape_worker import SCRAPE_WORKER_MODE, scrape_queue
from .services.storage_service import storage_service
from .routers.audit import router as audit_router
from .routers.answers import router as answers_router
from .routers.stage import router as stage_router
from .routers.ground_truth import router as ground_truth_router
from .routers.tracker import router as tracker_router
from .routers.jobs import router as jobs_router
from .routers.auth import router as auth_router
from .routers.admin import router as admin_router
from .routers.plans import router as plans_router
from .routers.extension import router as extension_router
from .routers.b2b import router as b2b_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("job_assistant_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        from .services.auth_service import purge_expired_rate_limits
        purge_expired_rate_limits()
    except Exception as exc:
        logger.debug("Startup expired rate-limit cleanup skipped: %s", exc)
    try:
        scrape_queue.start_embedded_worker()
    except Exception as exc:
        logger.warning("Durable scrape worker startup warning: %s", exc)
    if not gemini_service.is_available:
        logger.warning(
            "⚠️ GEMINI_API_KEY is not configured or invalid. The backend is running in "
            "deterministic ground_truth_heuristic_engine mode with full multi-industry support."
        )
    else:
        logger.info(f"✅ Gemini API active using model '{gemini_service.model_name}'.")
    yield
    try:
        await scrape_queue.stop_embedded_worker()
    except Exception as exc:
        logger.debug("Durable scrape worker shutdown note: %s", exc)
    # Clean up lingering Playwright sessions and browser processes on shutdown
    try:
        from .services.playwright_service import playwright_service
        await playwright_service.close_all_sessions()
        logger.info("Playwright active browser sessions cleanly terminated.")
    except Exception as e:
        logger.debug(f"Playwright session shutdown cleanup: {e}")


app = FastAPI(
    title="AI Job Application Assistant API",
    description=(
        "Production backend with SQLModel/SQLAlchemy relational persistence, "
        "multi-portal discovery, remote B2B analytics, and CV tailoring."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("X-XSS-Protection", "0")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    if IS_PRODUCTION:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."},
    )


# Tight CORS configuration: strict production allowlist (never inherit localhost in production)
def _is_localhost_origin(origin: str) -> bool:
    low = (origin or "").strip().lower()
    return any(h in low for h in ("://localhost", "://127.0.0.1", "://0.0.0.0", "://[::1]"))


CORS_ALLOWED_ORIGINS = [] if IS_PRODUCTION else [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
if FRONTEND_URL:
    _norm_fe = FRONTEND_URL.rstrip("/")
    if (not IS_PRODUCTION or not _is_localhost_origin(_norm_fe)) and _norm_fe not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(_norm_fe)
for _env_key in ("CORS_ORIGINS", "ALLOWED_ORIGINS"):
    _extra_origins = os.getenv(_env_key, "")
    for _orig in _extra_origins.split(","):
        _clean = _orig.strip().rstrip("/")
        if _clean and (not IS_PRODUCTION or not _is_localhost_origin(_clean)) and _clean not in CORS_ALLOWED_ORIGINS:
            CORS_ALLOWED_ORIGINS.append(_clean)

_ext_ids_raw = os.getenv("CORS_ALLOWED_EXTENSION_IDS", "")
_has_explicit_ext_ids = False
for _ext_id in _ext_ids_raw.split(","):
    _clean_eid = _ext_id.strip().lower()
    if _clean_eid:
        _has_explicit_ext_ids = True
        _ext_origin = f"chrome-extension://{_clean_eid}"
        if _ext_origin not in CORS_ALLOWED_ORIGINS:
            CORS_ALLOWED_ORIGINS.append(_ext_origin)

_custom_cors_regex = os.getenv("CORS_ALLOW_REGEX", "").strip()
if _custom_cors_regex:
    CORS_ORIGIN_REGEX = _custom_cors_regex
elif IS_PRODUCTION or _has_explicit_ext_ids:
    CORS_ORIGIN_REGEX = None
else:
    CORS_ORIGIN_REGEX = r"^chrome-extension://[a-z0-9]{16,64}$"

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)

# Include Routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(plans_router)
app.include_router(jobs_router)
app.include_router(audit_router)
app.include_router(answers_router)
app.include_router(stage_router)
app.include_router(ground_truth_router)
app.include_router(tracker_router)
app.include_router(extension_router)
app.include_router(b2b_router)

@app.get("/")
def root():
    return {
        "service": "AI Job Application Assistant API",
        "version": "2.0.0",
        "status": "online",
        "database": "SQLModel / SQLAlchemy Active",
        "docs_url": "/docs",
    }


@app.get("/health/live")
@app.get("/api/health/live")
def liveness_check():
    """Lightweight process liveness probe (does not query external dependencies)."""
    return {"status": "alive"}


@app.get("/health")
@app.get("/api/health")
@app.get("/api/health/ready")
def healthcheck():
    """Readiness probe that runs a live `SELECT 1` database check and returns HTTP 503 if unreachable."""
    db_type = "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Readiness database connectivity check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "unreachable",
                "database_type": db_type,
                "database_reachable": False,
                "storage": storage_service.get_storage_status(),
                "scrape_worker_mode": SCRAPE_WORKER_MODE,
                "playwright_enabled": ENABLE_PLAYWRIGHT,
            },
        )

    ai_health = gemini_service.get_provider_health()
    return {
        "status": "healthy",
        "database": db_type,
        "database_reachable": True,
        "storage": storage_service.get_storage_status(),
        "scrape_worker_mode": SCRAPE_WORKER_MODE,
        "playwright_enabled": ENABLE_PLAYWRIGHT,
        "gemini": {
            "model": GEMINI_MODEL,
            "fast_model": GEMINI_FAST_MODEL,
            "connected": gemini_service.is_available,
            "mode": f"live_{GEMINI_MODEL}" if gemini_service.is_available else "ground_truth_heuristic_engine",
        },
        "ai": ai_health,
    }
