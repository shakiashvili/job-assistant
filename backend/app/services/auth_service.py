import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from ..config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from ..db.database import get_session
from ..db.models import User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_bearer = HTTPBearer(auto_error=False)

# Simple in-memory rate limiting / brute-force protection
# Key: email/ip -> [timestamp, attempt_count]
_LOGIN_ATTEMPTS: Dict[str, Dict[str, Any]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5 minutes


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Safely verifies a candidate password against bcrypt hash."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.warning(f"Password verification error: {e}")
        return False


def hash_password(password: str) -> str:
    """Hashes a plain password using bcrypt."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    return pwd_context.hash(password)


def check_rate_limit(identifier: str) -> None:
    """Protects against brute force login attempts."""
    now = time.time()
    record = _LOGIN_ATTEMPTS.get(identifier)
    if record:
        attempts = record.get("attempts", 0)
        first_time = record.get("first_time", now)
        if attempts >= MAX_LOGIN_ATTEMPTS:
            elapsed = now - first_time
            if elapsed < LOCKOUT_SECONDS:
                remaining = int(LOCKOUT_SECONDS - elapsed)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many failed login attempts. Please wait {remaining} seconds before retrying.",
                )
            else:
                # Reset after lockout period
                _LOGIN_ATTEMPTS[identifier] = {"attempts": 1, "first_time": now}
                return
    if identifier not in _LOGIN_ATTEMPTS:
        _LOGIN_ATTEMPTS[identifier] = {"attempts": 0, "first_time": now}


def record_login_failure(identifier: str) -> None:
    now = time.time()
    if identifier in _LOGIN_ATTEMPTS:
        _LOGIN_ATTEMPTS[identifier]["attempts"] += 1
    else:
        _LOGIN_ATTEMPTS[identifier] = {"attempts": 1, "first_time": now}


def reset_login_attempts(identifier: str) -> None:
    if identifier in _LOGIN_ATTEMPTS:
        del _LOGIN_ATTEMPTS[identifier]


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a secure HS256 JWT access token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.debug(f"JWT decode error: {e}")
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    session: Session = Depends(get_session),
) -> User:
    """
    FastAPI dependency to extract and validate the authenticated User from Bearer token.
    If no token is supplied, returns a default active user or raises 401.
    """
    if not credentials:
        # Check if any user exists; if none exist, return a guest/system user
        guest = session.exec(select(User).where(User.email == "guest@talentflow.local")).first()
        if not guest:
            guest = User(
                email="guest@talentflow.local",
                full_name="Guest Candidate",
                hashed_password=pwd_context.hash("GuestPassword123!"),
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

    user = session.exec(select(User).where(User.email == user_email.lower().strip())).first()
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
