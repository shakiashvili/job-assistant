import bcrypt
import hashlib
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, delete, select

from ..config import (
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    IS_PRODUCTION,
)
from ..db.database import engine, get_session, is_sqlite
from ..db.models import AuthRateLimit, User
from .crypto_service import blind_index_candidates

logger = logging.getLogger(__name__)

security_bearer = HTTPBearer(auto_error=False)

MAX_LOGIN_ATTEMPTS = 5
MAX_OTP_REQUESTS = 5
MAX_IP_AUTH_ATTEMPTS = int(os.getenv("MAX_IP_AUTH_ATTEMPTS", "25"))
LOCKOUT_SECONDS = 300  # 5 minutes
MAX_PASSWORD_BYTES = 72
RATE_LIMIT_PRUNE_INTERVAL_SECONDS = int(os.getenv("RATE_LIMIT_PRUNE_INTERVAL_SECONDS", "300"))
_LAST_RATE_LIMIT_PRUNE_TS = 0.0

_REDIS_CHECK_SCRIPT = """
local val = redis.call('GET', KEYS[1])
if not val then return {0, 0} end
local ttl = redis.call('TTL', KEYS[1])
return {tonumber(val), ttl}
"""

_REDIS_CONSUME_SCRIPT = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
local max_att = tonumber(ARGV[1])
local win = tonumber(ARGV[2])
if cur >= max_att then
    local ttl = redis.call('TTL', KEYS[1])
    if ttl < 1 then ttl = win end
    return {cur, ttl, 0}
end
local next_val = redis.call('INCR', KEYS[1])
if next_val == 1 then
    redis.call('EXPIRE', KEYS[1], win)
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 1 then ttl = win end
return {next_val, ttl, 1}
"""

_REDIS_INCR_SCRIPT = """
local next_val = redis.call('INCR', KEYS[1])
if next_val == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return next_val
"""


def _get_redis_client():
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    try:
        import redis  # type: ignore
        return redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1.5, socket_timeout=1.5)
    except Exception as exc:
        logger.debug("Redis rate-limiter unavailable (%s); falling back to shared SQL table.", exc)
        return None


def _bucket_key(identifier: str) -> str:
    clean = (identifier or "").strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _ensure_rate_limit_table() -> None:
    try:
        AuthRateLimit.__table__.create(engine, checkfirst=True)
    except Exception:
        pass


def purge_expired_rate_limits(
    session: Optional[Session] = None,
    *,
    now_ts: Optional[float] = None,
) -> int:
    """Deletes expired SQL auth_rate_limits rows so unique-email probes cannot bloat the table."""
    cutoff = float(now_ts) if now_ts is not None else time.time()

    def _delete_expired(db: Session) -> int:
        res = db.exec(delete(AuthRateLimit).where(AuthRateLimit.expires_at <= cutoff))
        return int(getattr(res, "rowcount", 0) or 0)

    if session is not None:
        return _delete_expired(session)

    with Session(engine) as own_session:
        deleted = _delete_expired(own_session)
        own_session.commit()
        return deleted


def _maybe_prune_expired_rate_limits(session: Session, now: float) -> None:
    global _LAST_RATE_LIMIT_PRUNE_TS
    if (now - _LAST_RATE_LIMIT_PRUNE_TS) < RATE_LIMIT_PRUNE_INTERVAL_SECONDS:
        return
    _LAST_RATE_LIMIT_PRUNE_TS = now
    try:
        purge_expired_rate_limits(session, now_ts=now)
    except Exception as exc:
        logger.debug("Expired SQL rate-limit pruning skipped: %s", exc)


def extract_client_ip(request: Optional[Request]) -> str:
    """Extracts client IP cleanly without trusting spoofable X-Forwarded-For unless configured."""
    if not request:
        return "unknown"
    trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes")
    if trust_proxy:
        xff = (request.headers.get("x-forwarded-for") or "").strip()
        if xff:
            return xff.split(",")[0].strip() or "unknown"
    return (request.client.host if request.client else "") or "unknown"


def _raise_429(remaining: int, error_detail: Optional[str], default_msg: str) -> None:
    rem = max(1, int(remaining))
    template = error_detail or default_msg
    msg = template.format(remaining=rem) if "{remaining}" in template else template
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=msg,
        headers={"Retry-After": str(rem)},
    )


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
    """Checks shared brute-force lockout state without incrementing the failure counter."""
    b_key = _bucket_key(identifier)
    r_client = _get_redis_client()
    if r_client is not None:
        try:
            count, ttl = r_client.eval(_REDIS_CHECK_SCRIPT, 1, f"tf:rl:{b_key}")
            if int(count or 0) >= max_attempts:
                _raise_429(
                    int(ttl) if int(ttl or 0) > 0 else window_seconds,
                    error_detail,
                    "Too many failed login attempts. Please wait {remaining} seconds before retrying.",
                )
            return
        except HTTPException:
            raise
        except Exception as exc:
            logger.debug("Redis check_rate_limit fallback to DB: %s", exc)

    now = time.time()
    for _ in range(2):
        try:
            with Session(engine) as session:
                row = session.get(AuthRateLimit, b_key)
                if not row:
                    return
                if row.expires_at <= now:
                    row.attempts = 0
                    row.window_started_at = now
                    row.expires_at = now + window_seconds
                    session.add(row)
                    session.commit()
                    return
                if row.attempts >= max_attempts:
                    _raise_429(
                        int(row.expires_at - now),
                        error_detail,
                        "Too many failed login attempts. Please wait {remaining} seconds before retrying.",
                    )
                return
        except OperationalError:
            _ensure_rate_limit_table()


def consume_rate_limit(
    identifier: str,
    max_attempts: int = MAX_OTP_REQUESTS,
    window_seconds: int = LOCKOUT_SECONDS,
    error_detail: Optional[str] = None,
) -> int:
    """Atomically enforces and increments a shared request quota counter across workers."""
    b_key = _bucket_key(identifier)
    r_client = _get_redis_client()
    if r_client is not None:
        try:
            count, ttl, allowed = r_client.eval(
                _REDIS_CONSUME_SCRIPT, 1, f"tf:rl:{b_key}", max_attempts, window_seconds
            )
            if not int(allowed):
                _raise_429(
                    int(ttl),
                    error_detail,
                    "Too many requests. Please wait {remaining} seconds before retrying.",
                )
            return int(count)
        except HTTPException:
            raise
        except Exception as exc:
            logger.debug("Redis consume_rate_limit fallback to DB: %s", exc)

    now = time.time()
    for _ in range(4):
        try:
            with Session(engine) as session:
                stmt = select(AuthRateLimit).where(AuthRateLimit.bucket_key == b_key)
                if not is_sqlite:
                    stmt = stmt.with_for_update()
                row = session.exec(stmt).first()
                if not row:
                    new_row = AuthRateLimit(
                        bucket_key=b_key,
                        attempts=1,
                        window_started_at=now,
                        expires_at=now + window_seconds,
                    )
                    session.add(new_row)
                    _maybe_prune_expired_rate_limits(session, now)
                    session.commit()
                    return 1

                if row.expires_at <= now:
                    row.attempts = 1
                    row.window_started_at = now
                    row.expires_at = now + window_seconds
                    session.add(row)
                    _maybe_prune_expired_rate_limits(session, now)
                    session.commit()
                    return 1

                if row.attempts >= max_attempts:
                    _raise_429(
                        int(row.expires_at - now),
                        error_detail,
                        "Too many requests. Please wait {remaining} seconds before retrying.",
                    )

                row.attempts = int(row.attempts) + 1
                session.add(row)
                _maybe_prune_expired_rate_limits(session, now)
                session.commit()
                return int(row.attempts)
        except OperationalError:
            _ensure_rate_limit_table()
        except IntegrityError:
            continue
    return max_attempts


def record_login_failure(identifier: str, window_seconds: int = LOCKOUT_SECONDS) -> None:
    b_key = _bucket_key(identifier)
    r_client = _get_redis_client()
    if r_client is not None:
        try:
            r_client.eval(_REDIS_INCR_SCRIPT, 1, f"tf:rl:{b_key}", window_seconds)
            return
        except Exception as exc:
            logger.debug("Redis record_login_failure fallback to DB: %s", exc)

    now = time.time()
    for _ in range(4):
        try:
            with Session(engine) as session:
                stmt = select(AuthRateLimit).where(AuthRateLimit.bucket_key == b_key)
                if not is_sqlite:
                    stmt = stmt.with_for_update()
                row = session.exec(stmt).first()
                if not row:
                    session.add(
                        AuthRateLimit(
                            bucket_key=b_key,
                            attempts=1,
                            window_started_at=now,
                            expires_at=now + window_seconds,
                        )
                    )
                    _maybe_prune_expired_rate_limits(session, now)
                    session.commit()
                    return
                if row.expires_at <= now:
                    row.attempts = 1
                    row.window_started_at = now
                    row.expires_at = now + window_seconds
                else:
                    row.attempts = int(row.attempts) + 1
                session.add(row)
                _maybe_prune_expired_rate_limits(session, now)
                session.commit()
                return
        except OperationalError:
            _ensure_rate_limit_table()
        except IntegrityError:
            continue


def reset_login_attempts(identifier: str) -> None:
    b_key = _bucket_key(identifier)
    r_client = _get_redis_client()
    if r_client is not None:
        try:
            r_client.delete(f"tf:rl:{b_key}")
        except Exception:
            pass
    try:
        with Session(engine) as session:
            session.exec(delete(AuthRateLimit).where(AuthRateLimit.bucket_key == b_key))
            session.commit()
    except Exception:
        pass


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
        if payload.get("token_type") != "access":
            logger.debug("Rejected non-access token presented as Bearer access token")
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
    """Looks up a user via active and previous blind-index HMAC digests."""
    candidates = blind_index_candidates(email)
    return session.exec(select(User).where(User.email_hash.in_(candidates))).first()


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
