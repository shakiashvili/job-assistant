import json
import logging
import os
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def reload_env_files(override: bool = False) -> None:
    """Loads environment variables from project root .env and backend/.env dynamically without clobbering explicit process env unless override=True."""
    env_candidates = [PROJECT_ROOT / ".env", BASE_DIR / ".env"]
    try:
        from dotenv import load_dotenv
        for p in env_candidates:
            if p.exists():
                load_dotenv(dotenv_path=p, override=override)
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
                    if k and (override or k not in os.environ):
                        os.environ[k] = v
            except OSError as env_err:
                logging.getLogger(__name__).warning("Could not read env file %s: %s", p, env_err)


# Initial load at startup
reload_env_files()

GROUND_TRUTH_FILE = DATA_DIR / "ground_truth.json"
SKILLS_MD_FILE = DATA_DIR / "candidate_skills.md"
APPLICATIONS_FILE = DATA_DIR / "applications.json"
RESUMES_DIR = DATA_DIR / "resumes"
GENERATED_RESUMES_DIR = RESUMES_DIR / "generated"
TEST_FORMS_DIR = BASE_DIR / "tests" / "fixtures" / "forms"

GENERATED_RESUMES_DIR.mkdir(parents=True, exist_ok=True)

ASSETS_DIR = BASE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# Relational Database URL (Supports PostgreSQL or SQLite)
DEFAULT_SQLITE_PATH = DATA_DIR / "job_assistant.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}")

# Settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-3.5-flash-lite")
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "30000"))
GEMINI_PRICING_TIER = os.getenv("GEMINI_PRICING_TIER", "standard").strip().lower() or "standard"
AI_DAILY_TOKEN_BUDGET_PER_USER = int(os.getenv("AI_DAILY_TOKEN_BUDGET_PER_USER", "250000"))
AI_MAX_CACHE_ENTRIES = int(os.getenv("AI_MAX_CACHE_ENTRIES", "1000"))
AI_THIRD_PARTY_CONSENT_REQUIRED = os.getenv("AI_THIRD_PARTY_CONSENT_REQUIRED", "false").strip().lower() in (
    "1", "true", "yes", "on"
)
AI_STARTUP_HEALTHCHECK = os.getenv("AI_STARTUP_HEALTHCHECK", "false").strip().lower() in (
    "1", "true", "yes", "on"
)

# Optional Free-Tier / Low-Cost OpenAI-Compatible Fallback (e.g. OpenRouter :free models)
AI_PROVIDER = os.getenv("AI_PROVIDER", "auto").strip().lower() or "auto"
AI_FALLBACK_PROVIDER = os.getenv("AI_FALLBACK_PROVIDER", "auto").strip().lower() or "auto"
AI_ALLOW_PAID_FALLBACK = os.getenv("AI_ALLOW_PAID_FALLBACK", "false").strip().lower() in ("1", "true", "yes", "on")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b-it:free").strip()
OPENROUTER_FAST_MODEL = os.getenv("OPENROUTER_FAST_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
OPENROUTER_TIMEOUT_SECONDS = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "25"))

# LinkedIn public scraping is opt-in (disabled by default for ToS-safe operation)
ENABLE_LINKEDIN_PUBLIC_SCRAPE = os.getenv("ENABLE_LINKEDIN_PUBLIC_SCRAPE", "false").strip().lower() in (
    "1", "true", "yes", "on"
)

# Per-1M token (input_usd, output_usd) schedule by model family and tier.
# Can be overridden at runtime via GEMINI_MODEL_PRICING_JSON without editing application logic.
GEMINI_DEFAULT_PRICING: Dict[str, Dict[str, Any]] = {
    "gemini-3.6-flash": {
        "effective_until_2026": {
            "free": (0.0, 0.0),
            "standard": (0.75, 3.75),
            "batch": (0.375, 1.875),
            "flex": (0.375, 1.875),
            "priority": (1.35, 6.75),
        },
        "free": (0.0, 0.0),
        "standard": (1.50, 7.50),
        "batch": (0.75, 3.75),
        "flex": (0.75, 3.75),
        "priority": (2.70, 13.50),
    },
    "gemini-3.8-flash": {
        "effective_until_2026": {
            "free": (0.0, 0.0),
            "standard": (0.75, 3.75),
            "batch": (0.375, 1.875),
            "flex": (0.375, 1.875),
            "priority": (1.35, 6.75),
        },
        "free": (0.0, 0.0),
        "standard": (1.50, 7.50),
        "batch": (0.75, 3.75),
        "flex": (0.75, 3.75),
        "priority": (2.70, 13.50),
    },
    "gemini-3.5-flash-lite": {
        "free": (0.0, 0.0),
        "standard": (0.30, 2.50),
        "batch": (0.15, 1.25),
        "flex": (0.15, 1.25),
        "priority": (0.54, 4.50),
    },
    "gemini-3-flash": {
        "free": (0.0, 0.0),
        "standard": (0.75, 3.75),
        "batch": (0.375, 1.875),
        "flex": (0.375, 1.875),
        "priority": (1.35, 6.75),
    },
    "gemini-2.5-flash-lite": {
        "free": (0.0, 0.0),
        "standard": (0.10, 0.40),
        "batch": (0.05, 0.20),
        "flex": (0.05, 0.20),
        "priority": (0.18, 0.72),
    },
    "gemini-2.5-flash": {
        "free": (0.0, 0.0),
        "standard": (0.30, 2.50),
        "batch": (0.15, 1.25),
        "flex": (0.15, 1.25),
        "priority": (0.54, 4.50),
    },
    "gemini-3-pro": {
        "free": (0.0, 0.0),
        "standard": (1.25, 10.00),
        "batch": (0.625, 5.00),
        "flex": (0.625, 5.00),
        "priority": (2.25, 18.00),
    },
    "gemini-2.5-pro": {
        "free": (0.0, 0.0),
        "standard": (1.25, 10.00),
        "batch": (0.625, 5.00),
        "flex": (0.625, 5.00),
        "priority": (2.25, 18.00),
    },
}


def resolve_gemini_model_pricing(
    model_name: str,
    tier: Optional[str] = None,
    as_of: Optional[date] = None,
) -> Tuple[float, float]:
    """
    Resolves (input_usd_per_1m, output_usd_per_1m) from GEMINI_MODEL_PRICING_JSON override
    or the configurable tier-aware schedule in GEMINI_DEFAULT_PRICING.
    """
    selected_tier = (tier or os.getenv("GEMINI_PRICING_TIER") or GEMINI_PRICING_TIER or "standard").strip().lower()
    if selected_tier == "free":
        return (0.0, 0.0)

    check_date = as_of or datetime.now(UTC).date()
    low_model = (model_name or "").strip().lower()

    pricing_table: Dict[str, Dict[str, Any]] = dict(GEMINI_DEFAULT_PRICING)
    override_raw = os.getenv("GEMINI_MODEL_PRICING_JSON", "").strip()
    if override_raw:
        try:
            loaded = json.loads(override_raw)
            if isinstance(loaded, dict):
                for mk, mv in loaded.items():
                    if isinstance(mv, dict):
                        pricing_table[str(mk).lower()] = mv
        except Exception as exc:
            logger.warning("Invalid GEMINI_MODEL_PRICING_JSON ignored: %s", exc)

    matched_entry: Optional[Dict[str, Any]] = None
    for prefix in sorted(pricing_table.keys(), key=len, reverse=True):
        if prefix in low_model:
            matched_entry = pricing_table[prefix]
            break

    if matched_entry:
        tier_map = matched_entry
        if check_date <= date(2026, 12, 31) and isinstance(matched_entry.get("effective_until_2026"), dict):
            tier_map = matched_entry["effective_until_2026"]
        rates = tier_map.get(selected_tier) or tier_map.get("standard")
        if isinstance(rates, list | tuple) and len(rates) == 2:
            return (float(rates[0]), float(rates[1]))

    if "flash-lite" in low_model:
        base = (0.30, 2.50)
    elif "pro" in low_model:
        base = (1.25, 10.00)
    else:
        base = (0.75, 3.75)

    if selected_tier in ("batch", "flex"):
        return (round(base[0] * 0.5, 4), round(base[1] * 0.5, 4))
    if selected_tier == "priority":
        return (round(base[0] * 1.8, 4), round(base[1] * 1.8, 4))
    return base
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
ENABLE_PLAYWRIGHT = os.getenv("ENABLE_PLAYWRIGHT", "true").strip().lower() in ("1", "true", "yes", "on")

# Security & JWT Auth
_DEV_FALLBACK_SECRET = "talentflow-ai-ultra-secure-jwt-secret-key-production-hardening-64chars-min-entropy"
_raw_secret = os.getenv("SECRET_KEY", "").strip()
IS_PRODUCTION = (
    os.getenv("ENVIRONMENT", "").strip().lower() in ("prod", "production")
    or os.getenv("ENV", "").strip().lower() in ("prod", "production")
    or bool(os.getenv("RENDER") or os.getenv("RAILWAY_ENVIRONMENT"))
)
_is_prod = IS_PRODUCTION
if not _raw_secret or _raw_secret == _DEV_FALLBACK_SECRET or (IS_PRODUCTION and len(_raw_secret) < 32):
    if IS_PRODUCTION:
        logger.critical(
            "FATAL SECURITY ERROR: SECRET_KEY is missing, too short (<32 chars), or uses the insecure default in production!"
        )
        raise RuntimeError(
            "SECRET_KEY environment variable must be set to a strong secret (>=32 chars) in production."
        )
    else:
        logger.warning(
            "SECRET_KEY is not configured in .env; using deterministic local development fallback."
        )
    SECRET_KEY = _DEV_FALLBACK_SECRET
else:
    SECRET_KEY = _raw_secret

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))  # 60 mins
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))  # 14 days

# Google OAuth2 Credentials & URLs
BACKEND_URL = (os.getenv("BACKEND_URL") or os.getenv("API_BASE_URL") or "http://localhost:8000").strip().rstrip("/")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", f"{BACKEND_URL}/api/auth/google/callback")
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


def get_email_delivery_config() -> Dict[str, Any]:
    """
    Resolves OTP/transactional email delivery configuration.
    Prefers HTTPS API providers (Resend / SendGrid over port 443, compatible with Render Free/PaaS)
    before falling back to SMTP (blocked on Render Free outbound ports 25/465/587).
    """
    reload_env_files()
    otp_enabled = os.getenv("OTP_EMAIL_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
    resend_key = os.getenv("RESEND_API_KEY", "").strip()
    sendgrid_key = os.getenv("SENDGRID_API_KEY", "").strip()
    from_email = (os.getenv("EMAIL_FROM") or os.getenv("RESEND_FROM_EMAIL") or "").strip()

    if not otp_enabled:
        return {
            "otp_enabled": False,
            "configured": False,
            "provider": "disabled",
            "from_email": from_email,
            "resend_api_key": "",
            "sendgrid_api_key": "",
            "can_configure_local_smtp": False,
        }

    if resend_key:
        return {
            "otp_enabled": True,
            "configured": True,
            "provider": "resend",
            "from_email": from_email or "TalentFlow AI <onboarding@resend.dev>",
            "resend_api_key": resend_key,
            "sendgrid_api_key": "",
            "can_configure_local_smtp": False,
        }

    if sendgrid_key and from_email:
        return {
            "otp_enabled": True,
            "configured": True,
            "provider": "sendgrid",
            "from_email": from_email,
            "resend_api_key": "",
            "sendgrid_api_key": sendgrid_key,
            "can_configure_local_smtp": False,
        }

    smtp_cfg = get_smtp_config()
    if smtp_cfg["configured"]:
        return {
            "otp_enabled": True,
            "configured": True,
            "provider": "smtp",
            "from_email": smtp_cfg["from_email"],
            "resend_api_key": "",
            "sendgrid_api_key": "",
            "can_configure_local_smtp": not IS_PRODUCTION,
        }

    return {
        "otp_enabled": True,
        "configured": False,
        "provider": "none",
        "from_email": from_email,
        "resend_api_key": "",
        "sendgrid_api_key": "",
        "can_configure_local_smtp": not IS_PRODUCTION,
    }
