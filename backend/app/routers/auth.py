import logging
import re
import secrets
from datetime import timedelta, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..config import BASE_DIR, reload_env_files, get_smtp_config
from ..db.database import get_session, delete_job_posting_cascade
from ..db.models import User, UserOTP, CandidateProfile, JobPosting, utc_now
from ..services.crypto_service import blind_index, mask_email
from ..services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    get_current_user,
    get_user_by_email,
    security_bearer,
    check_rate_limit,
    record_login_failure,
    reset_login_attempts,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Authentication & RBAC"])


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, description="Valid email address")
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    full_name: str = Field("Candidate", min_length=2)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5)
    password: str = Field(..., min_length=1)


class SendOTPRequest(BaseModel):
    email: str = Field(..., min_length=5, description="Email address for 1-time passwordless code")


class VerifyOTPRequest(BaseModel):
    email: str = Field(..., min_length=5)
    otp_code: str = Field(..., min_length=6, max_length=6, description="6-digit verification code")


class ConfigureSmtpRequest(BaseModel):
    gmail_user: str = Field(..., min_length=5, description="Gmail address for outgoing OTPs")
    gmail_app_password: str = Field(..., min_length=8, description="16-character Google App Password")


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    is_admin: bool
    has_gmail_oauth: bool = False


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10, description="Valid refresh token for sliding session renewal")


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: UserOut


def _build_auth_response(user: User) -> AuthResponse:
    """Issues a fresh Access Token (60m) and Refresh Token (14d) for an authenticated user."""
    claims = {"sub": user.email, "is_admin": user.is_admin, "user_id": user.id}
    return AuthResponse(
        access_token=create_access_token(claims),
        refresh_token=create_refresh_token(claims),
        token_type="bearer",
        user=UserOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_admin=user.is_admin,
            has_gmail_oauth=bool(user.gmail_oauth_token),
        ),
    )


def sanitize_email(email: str) -> str:
    return email.strip().lower()


def _sync_profile_owner_on_auth(session: Session, clean_email: str, force_reset: bool = False) -> None:
    """Preserves each user's uploaded skills.md profile across logins/registrations without wiping others."""
    all_profiles = session.exec(select(CandidateProfile)).all()
    user_has_profile = any(
        str((p.parsed_skills or {}).get("owner_email") or "").strip().lower() == clean_email
        for p in all_profiles
    )
    if force_reset and not user_has_profile:
        for prof in all_profiles:
            skills_copy = dict(prof.parsed_skills or {})
            row_owner = str(skills_copy.get("owner_email") or "").strip().lower()
            if not row_owner:
                skills_copy["user_uploaded"] = False
                prof.parsed_skills = skills_copy
                session.add(prof)
        for stale_job in session.exec(select(JobPosting).where(JobPosting.status != "APPLIED")).all():
            delete_job_posting_cascade(session, stale_job)
    session.commit()


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register_user(req: RegisterRequest, session: Session = Depends(get_session)):
    clean_email = sanitize_email(req.email)

    existing = get_user_by_email(session, clean_email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    # Secure password validation
    if len(req.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters long.",
        )

    hashed = hash_password(req.password)
    user = User(
        email=clean_email,
        hashed_password=hashed,
        full_name=req.full_name.strip() or "Candidate",
        is_active=True,
        is_admin=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    _sync_profile_owner_on_auth(session, clean_email, force_reset=True)
    return _build_auth_response(user)


@router.post("/login", response_model=AuthResponse)
def login_user(req: LoginRequest, session: Session = Depends(get_session)):
    clean_email = sanitize_email(req.email)
    check_rate_limit(clean_email)

    user = get_user_by_email(session, clean_email)
    if not user or not verify_password(req.password, user.hashed_password):
        record_login_failure(clean_email)
        # Constant-time message prevents user enumeration attacks
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Please contact an administrator.",
        )

    reset_login_attempts(clean_email)
    _sync_profile_owner_on_auth(session, clean_email, force_reset=False)
    return _build_auth_response(user)


@router.get("/smtp-status")
def get_smtp_delivery_status():
    """Returns whether local Gmail SMTP delivery is configured without exposing credentials."""
    cfg = get_smtp_config()
    return {"smtp_configured": cfg["configured"]}


def _write_env_updates(env_path: Path, updates: dict[str, str]) -> None:
    """Safely updates keys in local gitignored backend/.env while preserving existing entries."""
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    remaining = dict(updates)
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in remaining:
                val = remaining.pop(k)
                new_lines.append(f"{k}={val}")
                continue
        new_lines.append(line)

    for k, val in remaining.items():
        new_lines.append(f"{k}={val}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@router.post("/configure-smtp")
def configure_smtp_sender(
    req: ConfigureSmtpRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
):
    """
    Validates and saves local Gmail SMTP credentials into gitignored backend/.env
    so passwordless OTP codes can be dispatched without manually editing files.
    """
    cfg = get_smtp_config()
    if cfg["configured"]:
        payload = decode_access_token(credentials.credentials) if credentials else None
        if not payload or not payload.get("sub"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SMTP is already configured. Sign in first to change sender credentials.",
            )

    clean_user = req.gmail_user.strip().lower()
    clean_pass = req.gmail_app_password.replace(" ", "").strip()
    if any(ch in clean_user + clean_pass for ch in ("\r", "\n", "\x00")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid characters in SMTP credentials.")

    from ..services.gmail_service import gmail_service

    ok, msg = gmail_service.verify_smtp_credentials(clean_user, clean_pass)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    _write_env_updates(
        BASE_DIR / ".env",
        {
            "GMAIL_USER": clean_user,
            "GMAIL_APP_PASSWORD": clean_pass,
            "SMTP_USER": clean_user,
            "SMTP_PASSWORD": clean_pass,
        },
    )
    reload_env_files()

    return {
        "status": "ok",
        "smtp_configured": True,
        "sender_masked": mask_email(clean_user),
        "message": f"Verified and saved local Gmail SMTP sender ({mask_email(clean_user)}). Git ignores backend/.env.",
    }


@router.post("/request-otp")
@router.post("/send-otp")
def send_otp_code(req: SendOTPRequest, session: Session = Depends(get_session)):
    """
    Generates a secure 6-digit numeric OTP code for passwordless Gmail/email authentication.
    Valid for 10 minutes. Dispatches via Gmail/SMTP (never logged in plaintext).
    """
    clean_email = sanitize_email(req.email)
    email_digest = blind_index(clean_email)
    check_rate_limit(clean_email)

    # Invalidate previous unused OTPs for this email
    prev_otps = session.exec(
        select(UserOTP).where((UserOTP.email_hash == email_digest) & (UserOTP.is_used == False))
    ).all()
    for o in prev_otps:
        o.is_used = True
        session.add(o)

    # Generate 6-digit code
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = utc_now() + timedelta(minutes=10)

    otp_record = UserOTP(
        email=clean_email,
        email_hash=email_digest,
        otp_code=code,
        expires_at=expires_at,
        is_used=False,
    )
    session.add(otp_record)
    session.commit()

    logger.info(f"Generated passwordless OTP for {mask_email(clean_email)} (expires in 10 mins)")

    # Send via real Gmail SMTP
    from ..services.gmail_service import gmail_service
    delivery = gmail_service.send_otp_email(to_email=clean_email, code=code)

    if delivery["smtp_configured"] and not delivery["delivered"]:
        logger.error(f"Failed to send OTP email to {mask_email(clean_email)}: {delivery['error']}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=delivery["error"] or "Failed to send OTP verification email via Gmail SMTP.",
        )

    if not delivery["smtp_configured"]:
        logger.warning(f"OTP generated for {mask_email(clean_email)}, but Gmail SMTP is not configured in backend/.env.")
        return {
            "status": "ok",
            "delivered": False,
            "smtp_configured": False,
            "message": (
                "Email could not be delivered to Gmail because GMAIL_USER and GMAIL_APP_PASSWORD "
                "are not set in backend/.env. Configure them below (local only) or use Register / Sign In with Password."
            ),
        }

    return {
        "status": "ok",
        "delivered": True,
        "smtp_configured": True,
        "message": f"Verification code sent to {mask_email(clean_email)}. Check your Gmail inbox (valid for 10 minutes).",
    }


@router.post("/verify-otp", response_model=AuthResponse)
def verify_otp_code(req: VerifyOTPRequest, session: Session = Depends(get_session)):
    """
    Verifies the 6-digit OTP code and returns a signed JWT token.
    Automatically creates a candidate User record if signing in for the first time.
    """
    clean_email = sanitize_email(req.email)
    clean_code = req.otp_code.strip()
    email_digest = blind_index(clean_email)

    active_otps = session.exec(
        select(UserOTP)
        .where((UserOTP.email_hash == email_digest) & (UserOTP.is_used == False))
        .order_by(UserOTP.id.desc())
    ).all()

    otp_record = None
    for cand in active_otps:
        if cand.otp_code and secrets.compare_digest(cand.otp_code.strip(), clean_code):
            otp_record = cand
            break

    now_utc = utc_now()
    expires_at = otp_record.expires_at if otp_record else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if not otp_record or not expires_at or expires_at < now_utc:
        record_login_failure(clean_email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code. Please request a new OTP.",
        )

    # Mark OTP as consumed
    otp_record.is_used = True
    session.add(otp_record)

    # Find or auto-provision user
    user = get_user_by_email(session, clean_email)
    if not user:
        candidate_name = clean_email.split("@")[0].replace(".", " ").title()
        user = User(
            email=clean_email,
            hashed_password=hash_password(secrets.token_urlsafe(24)),
            full_name=candidate_name,
            is_active=True,
            is_admin=False,
        )
        session.add(user)

    session.commit()
    session.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Please contact an administrator.",
        )

    reset_login_attempts(clean_email)
    _sync_profile_owner_on_auth(session, clean_email, force_reset=False)
    return _build_auth_response(user)


@router.post("/refresh", response_model=AuthResponse)
def refresh_session(req: RefreshTokenRequest, session: Session = Depends(get_session)):
    """
    Exchanges a valid Refresh Token (14 days) for a fresh Access Token (60 mins)
    and a rotated sliding Refresh Token so active users stay signed in seamlessly.
    """
    payload = decode_refresh_token(req.refresh_token.strip())
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_email = payload.get("sub")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed refresh token claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_email(session, sanitize_email(user_email))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account removed.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or disabled by admin.",
        )

    return _build_auth_response(user)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_admin=current_user.is_admin,
        has_gmail_oauth=bool(current_user.gmail_oauth_token),
    )


@router.get("/google/login")
def google_login(state: Optional[str] = "talentflow_oauth"):
    """Returns Google OAuth consent URL for user authentication & Gmail dispatch permissions."""
    from ..services.gmail_service import gmail_service
    url = gmail_service.get_authorization_url(state=state or "talentflow_oauth")
    return {"authorization_url": url}


@router.get("/google/callback")
def google_callback(
    code: str,
    state: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """Exchanges code for Google OAuth tokens and links to the active user profile."""
    from fastapi.responses import RedirectResponse
    from ..services.gmail_service import gmail_service
    from ..config import FRONTEND_URL

    token_data = gmail_service.exchange_code_for_token(code)
    user = session.exec(select(User).order_by(User.id.asc())).first()
    if user:
        user.gmail_oauth_token = token_data
        session.add(user)
        session.commit()
        logger.info(f"Stored Google OAuth token for user '{mask_email(user.email)}'")

    return RedirectResponse(url=f"{FRONTEND_URL}?google_auth=success")

