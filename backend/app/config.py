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

# Security & JWT Auth
SECRET_KEY = os.getenv("SECRET_KEY", "talentflow-ai-ultra-secure-jwt-secret-key-production-hardening-64chars-min-entropy")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours

# Google OAuth2 Credentials & URLs
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
