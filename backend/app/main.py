import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import MOCK_PORTALS_DIR, GEMINI_MODEL, DATABASE_URL
from .database import init_db
from .services.gemini_service import gemini_service
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("job_assistant_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not gemini_service.is_available:
        logger.warning(
            "⚠️ GEMINI_API_KEY is not configured or invalid. The backend is running in "
            "deterministic ground_truth_heuristic_engine mode with full multi-industry support."
        )
    else:
        logger.info(f"✅ Gemini API active using model '{gemini_service.model_name}'.")
    yield
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
        "Production-grade backend with SQLModel/SQLAlchemy relational persistence, "
        "automated multi-portal scrapers (Jobs.ge, HR.ge, DOU.ua, Djinni.co), "
        "strict remote/English language filtering, dynamic AI salary estimation, and Playwright staging."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# Standards-compliant CORS Middleware (explicit origins + regex for Chrome extensions)
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_origin_regex=r"^chrome-extension://[a-z0-9]+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

@app.get("/")
def root():
    return {
        "service": "AI Job Application Assistant API",
        "version": "2.0.0",
        "status": "online",
        "database": "SQLModel / SQLAlchemy Active",
        "docs_url": "/docs",
    }


@app.get("/api/health")
def healthcheck():
    init_db()
    return {
        "status": "healthy",
        "database": "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql",
        "gemini": {
            "model": GEMINI_MODEL,
            "connected": gemini_service.is_available,
            "mode": "live_gemini_2.5_flash" if gemini_service.is_available else "ground_truth_heuristic_engine"
        }
    }
