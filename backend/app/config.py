import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

GROUND_TRUTH_FILE = DATA_DIR / "ground_truth.json"
SKILLS_MD_FILE = DATA_DIR / "candidate_skills.md"
APPLICATIONS_FILE = DATA_DIR / "applications.json"
RESUMES_DIR = DATA_DIR / "resumes"
GENERATED_RESUMES_DIR = RESUMES_DIR / "generated"
MOCK_PORTALS_DIR = BASE_DIR / "mock_portals"

GENERATED_RESUMES_DIR.mkdir(parents=True, exist_ok=True)

ASSETS_DIR = BASE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# Relational Database URL (Supports PostgreSQL or SQLite)
DEFAULT_SQLITE_PATH = DATA_DIR / "job_assistant.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}")

# Settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
