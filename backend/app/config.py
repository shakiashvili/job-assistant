import os
from pathlib import Path
from typing import Any, Dict

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def reload_env_files() -> None:
    """Loads environment variables from project root .env and backend/.env dynamically."""
    env_candidates = [PROJECT_ROOT / ".env", BASE_DIR / ".env"]
    try:
        from dotenv import load_dotenv
        for p in env_candidates:
            if p.exists():
                load_dotenv(dotenv_path=p, override=True)
        return
    except ImportError:
        pass

    for p in env_candidates:
        if p.exists():
            try:
                for raw_line in p.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k:
                        os.environ[k] = v
            except Exception:
                pass


# Initial load at startup
reload_env_files()

GROUND_TRUTH_FILE = DATA_DIR / "ground_truth.json"
SKILLS_MD_FILE = DATA_DIR / "candidate_skills.md"
APPLICATIONS_FILE = DATA_DIR / "applications.json"
RESUMES_DIR = DATA_DIR / "resumes"
GENERATED_RESUMES_DIR = RESUMES_DIR / "generated"
TEST_FORMS_DIR = BASE_DIR / "tests" / "fixtures" / "forms"
MOCK_PORTALS_DIR = TEST_FORMS_DIR

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


def get_smtp_config() -> Dict[str, Any]:
    """Reads fresh SMTP / Gmail App Password settings from .env / environment."""
    reload_env_files()
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
    port = int(os.getenv("SMTP_PORT", "465").strip() or "465")
    user = (os.getenv("SMTP_USER") or os.getenv("GMAIL_USER") or "").strip()
    raw_pwd = os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD") or ""
    # Strip internal spaces often copied from Google's 16-char App Password UI
    password = raw_pwd.replace(" ", "").strip()
    from_email = (os.getenv("SMTP_FROM_EMAIL") or user).strip()
    return {
        "configured": bool(user and password),
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from_email": from_email,
    }
