import logging
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Session, select

from ..db.database import get_session
from ..db.models import User
from ..services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
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


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    is_admin: bool
    has_gmail_oauth: bool = False


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def sanitize_email(email: str) -> str:
    return email.strip().lower()


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register_user(req: RegisterRequest, session: Session = Depends(get_session)):
    clean_email = sanitize_email(req.email)

    existing = session.exec(select(User).where(User.email == clean_email)).first()
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

    token = create_access_token({"sub": user.email, "is_admin": user.is_admin, "user_id": user.id})
    return AuthResponse(
        access_token=token,
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


@router.post("/login", response_model=AuthResponse)
def login_user(req: LoginRequest, session: Session = Depends(get_session)):
    clean_email = sanitize_email(req.email)
    check_rate_limit(clean_email)

    user = session.exec(select(User).where(User.email == clean_email)).first()
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
    token = create_access_token({"sub": user.email, "is_admin": user.is_admin, "user_id": user.id})
    return AuthResponse(
        access_token=token,
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
        logger.info(f"Stored Google OAuth token for user '{user.email}'")

    return RedirectResponse(url=f"{FRONTEND_URL}?google_auth=success")

