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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("job_assistant_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


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

# CORS Middleware (permitting Chrome extension and Vite dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(jobs_router)
app.include_router(audit_router)
app.include_router(answers_router)
app.include_router(stage_router)
app.include_router(ground_truth_router)
app.include_router(tracker_router)

# Mount Mock Portals for local testing and extension preview
if MOCK_PORTALS_DIR.exists():
    app.mount("/mock-portals", StaticFiles(directory=str(MOCK_PORTALS_DIR), html=True), name="mock-portals")


@app.get("/")
def root():
    return {
        "service": "AI Job Application Assistant API",
        "version": "2.0.0",
        "status": "online",
        "database": "SQLModel / SQLAlchemy Active",
        "docs_url": "/docs",
        "mock_greenhouse": "/mock-portals/greenhouse_sample.html",
        "mock_lever": "/mock-portals/lever_sample.html",
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
