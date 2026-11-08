import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import MOCK_PORTALS_DIR, GEMINI_MODEL
from .services.gemini_service import gemini_service
from .routers.audit import router as audit_router
from .routers.answers import router as answers_router
from .routers.stage import router as stage_router
from .routers.ground_truth import router as ground_truth_router
from .routers.tracker import router as tracker_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("job_assistant_backend")

app = FastAPI(
    title="AI Job Application Assistant API",
    description="Backend service for job description audits, grounded screening answers, and Playwright human-in-the-loop application staging.",
    version="1.0.0"
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
        "version": "1.0.0",
        "status": "online",
        "docs_url": "/docs",
        "mock_greenhouse": "/mock-portals/greenhouse_sample.html",
        "mock_lever": "/mock-portals/lever_sample.html",
    }


@app.get("/api/health")
def healthcheck():
    return {
        "status": "healthy",
        "gemini": {
            "model": GEMINI_MODEL,
            "connected": gemini_service.is_available,
            "mode": "live_gemini_2.5_flash" if gemini_service.is_available else "ground_truth_heuristic_engine"
        }
    }
