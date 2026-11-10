import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select, func

from ..db.database import get_session
from ..db.models import User, ApplicationTracker, JobPosting
from ..services.auth_service import get_current_admin
from ..services.gemini_service import gemini_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["Dedicated Admin Dashboard"])


class AdminUserOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    application_count: int = 0
    has_gmail_oauth: bool = False


class AdminUpdateUserRequest(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    full_name: Optional[str] = None


class PlatformMetricsOut(BaseModel):
    total_users: int
    active_users: int
    admin_users: int
    total_tracked_applications: int
    applications_by_status: Dict[str, int]
    interview_conversion_rate: float
    total_discovered_jobs: int
    gemini_api_status: str
    database_status: str = "healthy"


@router.get("/users", response_model=List[AdminUserOut])
def list_all_users(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    """Admin-only endpoint: Lists all registered accounts and their application statistics."""
    users = session.exec(select(User).order_by(User.id.desc())).all()
    results = []
    for u in users:
        app_count = len(session.exec(select(ApplicationTracker).where(ApplicationTracker.user_id == u.id, ApplicationTracker.is_deleted == False)).all())
        results.append(
            AdminUserOut(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                is_active=u.is_active,
                is_admin=u.is_admin,
                created_at=u.created_at,
                application_count=app_count,
                has_gmail_oauth=bool(u.gmail_oauth_token),
            )
        )
    return results


@router.get("/metrics", response_model=PlatformMetricsOut)
def get_platform_metrics(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    """Admin-only endpoint: Computes aggregate platform health, user engagement, and conversion metrics."""
    users = session.exec(select(User)).all()
    total_users = len(users)
    active_users = sum(1 for u in users if u.is_active)
    admin_users = sum(1 for u in users if u.is_admin)

    apps = session.exec(select(ApplicationTracker).where(ApplicationTracker.is_deleted == False)).all()
    total_apps = len(apps)

    status_counts: Dict[str, int] = {}
    interview_count = 0
    for a in apps:
        status_counts[a.status] = status_counts.get(a.status, 0) + 1
        if a.status in ["HR_SCREEN", "TECH_INTERVIEW", "FINAL_ROUND", "OFFER", "Interviewing", "Technical Interview", "Offer"]:
            interview_count += 1

    conversion_rate = round((interview_count / total_apps * 100), 1) if total_apps > 0 else 0.0
    discovered_jobs_count = len(session.exec(select(JobPosting)).all())

    return PlatformMetricsOut(
        total_users=total_users,
        active_users=active_users,
        admin_users=admin_users,
        total_tracked_applications=total_apps,
        applications_by_status=status_counts,
        interview_conversion_rate=conversion_rate,
        total_discovered_jobs=discovered_jobs_count,
        gemini_api_status="online" if gemini_service.is_available else "heuristic_fallback",
        database_status="healthy",
    )


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user_status(
    user_id: int,
    req: AdminUpdateUserRequest,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    """Admin-only endpoint: Updates active state, role, or metadata of any user."""
    target = session.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found.")

    if req.is_active is not None:
        if target.id == admin.id and not req.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own admin account.")
        target.is_active = req.is_active

    if req.is_admin is not None:
        if target.id == admin.id and not req.is_admin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot revoke your own admin rights.")
        target.is_admin = req.is_admin

    if req.full_name is not None:
        target.full_name = req.full_name.strip() or target.full_name

    session.add(target)
    session.commit()
    session.refresh(target)

    app_count = len(session.exec(select(ApplicationTracker).where(ApplicationTracker.user_id == target.id, ApplicationTracker.is_deleted == False)).all())
    return AdminUserOut(
        id=target.id,
        email=target.email,
        full_name=target.full_name,
        is_active=target.is_active,
        is_admin=target.is_admin,
        created_at=target.created_at,
        application_count=app_count,
        has_gmail_oauth=bool(target.gmail_oauth_token),
    )


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    """Admin-only endpoint: Deactivates or removes a user account."""
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own admin account.")

    target = session.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found.")

    target.is_active = False
    session.add(target)
    session.commit()
    return {"status": "success", "message": f"User {target.email} has been deactivated."}
