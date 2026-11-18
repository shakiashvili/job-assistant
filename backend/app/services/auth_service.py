import bcrypt
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlmodel import Session, select

from ..config import (
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    IS_PRODUCTION,
)
from ..db.database import get_session
from ..db.models import User
from .crypto_service import blind_index

logger = logging.getLogger(__name__)

security_bearer = HTTPBearer(auto_error=False)

# Simple in-memory rate limiting / brute-force protection
# Key: bucket -> {"first_time": float, "attempts": int}
_LOGIN_ATTEMPTS: Dict[str, Dict[str, Any]] = {}
MAX_LOGIN_ATTEMPTS = 5
MAX_OTP_REQUESTS = 5
LOCKOUT_SECONDS = 300  # 5 minutes
MAX_PASSWORD_BYTES = 72


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Safely verifies a candidate password against a bcrypt hash without raising on oversized inputs."""
    if not plain_password or not hashed_password:
        return False
    try:
        pw_bytes = plain_password.encode("utf-8")
        if len(pw_bytes) > MAX_PASSWORD_BYTES:
            return False
        return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))
    except Exception as e:
        logger.warning(f"Password verification error: {e}")
        return False


def hash_password(password: str) -> str:
    """Hashes a plain password using bcrypt with explicit UTF-8 byte-length validation."""
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must not exceed {MAX_PASSWORD_BYTES} UTF-8 bytes.")
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt(rounds=12)).decode("utf-8")


def check_rate_limit(
    identifier: str,
    max_attempts: int = MAX_LOGIN_ATTEMPTS,
    window_seconds: int = LOCKOUT_SECONDS,
    error_detail: Optional[str] = None,
) -> None:
    """Checks brute-force lockout state without incrementing the failure counter."""
    now = time.time()
    record = _LOGIN_ATTEMPTS.get(identifier)
    if record:
        attempts = record.get("attempts", 0)
        first_time = record.get("first_time", now)
        elapsed = now - first_time
        if elapsed >= window_seconds:
            _LOGIN_ATTEMPTS[identifier] = {"attempts": 0, "first_time": now}
            return
        if attempts >= max_attempts:
            remaining = max(1, int(window_seconds - elapsed))
            detail = error_detail or (
                f"Too many failed login attempts. Please wait {remaining} seconds before retrying."
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail.format(remaining=remaining) if "{remaining}" in detail else detail,
            )
    if identifier not in _LOGIN_ATTEMPTS:
        _LOGIN_ATTEMPTS[identifier] = {"attempts": 0, "first_time": now}


def consume_rate_limit(
    identifier: str,
    max_attempts: int = MAX_OTP_REQUESTS,
    window_seconds: int = LOCKOUT_SECONDS,
    error_detail: Optional[str] = None,
) -> int:
    """Atomically enforces and increments a request quota counter (e.g. OTP dispatch throttling)."""
    now = time.time()
    record = _LOGIN_ATTEMPTS.get(identifier)
    if record:
        elapsed = now - record.get("first_time", now)
        if elapsed >= window_seconds:
            _LOGIN_ATTEMPTS[identifier] = {"attempts": 1, "first_time": now}
            return 1
        attempts = record.get("attempts", 0)
        if attempts >= max_attempts:
            remaining = max(1, int(window_seconds - elapsed))
            detail = error_detail or (
                f"Too many requests. Please wait {remaining} seconds before retrying."
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail.format(remaining=remaining) if "{remaining}" in detail else detail,
            )
        record["attempts"] = attempts + 1
        return int(record["attempts"])

    _LOGIN_ATTEMPTS[identifier] = {"attempts": 1, "first_time": now}
    return 1


def record_login_failure(identifier: str) -> None:
    now = time.time()
    record = _LOGIN_ATTEMPTS.get(identifier)
    if record and (now - record.get("first_time", now)) < LOCKOUT_SECONDS:
        record["attempts"] = record.get("attempts", 0) + 1
    else:
        _LOGIN_ATTEMPTS[identifier] = {"attempts": 1, "first_time": now}


def reset_login_attempts(identifier: str) -> None:
    if identifier in _LOGIN_ATTEMPTS:
        del _LOGIN_ATTEMPTS[identifier]


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a secure HS256 JWT access token (default 60 minutes)."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now, "token_type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a long-lived HS256 JWT refresh token (default 14 days)."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": now, "token_type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("token_type") == "refresh":
            logger.debug("Rejected refresh token presented as access token")
            return None
        return payload
    except JWTError as e:
        logger.debug(f"JWT decode error: {e}")
        return None


def decode_refresh_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("token_type") != "refresh":
            return None
        return payload
    except JWTError as e:
        logger.debug(f"Refresh JWT decode error: {e}")
        return None


def create_oauth_state_token(user_id: Optional[int], email: str) -> str:
    """Signs short-lived HS256 OAuth state linking callback tokens safely to the initiating user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "uid": user_id,
        "nonce": secrets.token_urlsafe(12),
        "token_type": "oauth_state",
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_oauth_state_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("token_type") != "oauth_state":
            return None
        return payload
    except JWTError as e:
        logger.debug(f"OAuth state token invalid: {e}")
        return None


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    """Looks up a user via HMAC-SHA256 blind index on the encrypted email column."""
    target_hash = blind_index(email)
    return session.exec(select(User).where(User.email_hash == target_hash)).first()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    session: Session = Depends(get_session),
) -> User:
    """
    FastAPI dependency to extract and validate the authenticated User from Bearer token.
    If no token is supplied, returns a default active user or raises 401.
    """
    if not credentials:
        if IS_PRODUCTION:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Please sign in.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # In non-production local/test environments, fallback to local workspace guest account
        guest = get_user_by_email(session, "guest@talentflow.local")
        if not guest:
            guest = User(
                email="guest@talentflow.local",
                full_name="Guest Candidate",
                hashed_password=hash_password("GuestPassword123!"),
                is_active=True,
                is_admin=False,
            )
            session.add(guest)
            session.commit()
            session.refresh(guest)
        return guest

    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_email: str = payload.get("sub")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_email(session, user_email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account removed",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive or disabled by admin",
        )
    return user


def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    FastAPI dependency that enforces strict RBAC:
    Returns 403 Forbidden if the authenticated user is not an Admin.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Admin privileges required.",
        )
    return current_user
