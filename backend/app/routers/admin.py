import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select, func

from ..db.database import get_session
from ..db.models import User, ApplicationTracker, JobPosting, AIOperationLog, AICacheEntry
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


@router.get("/ai-metrics")
def get_ai_observability_metrics(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    """Admin-only endpoint: AI telemetry, cache hit rate, latency, token usage, and estimated cost."""
    logs = session.exec(
        select(AIOperationLog).order_by(AIOperationLog.created_at.desc()).limit(500)
    ).all()
    cache_rows = session.exec(select(AICacheEntry)).all()

    total = len(logs)
    success_cnt = sum(1 for l in logs if l.status == "SUCCESS")
    cache_hits = sum(1 for l in logs if l.cache_hit)
    rate_limited = sum(1 for l in logs if l.status == "RATE_LIMITED")
    failed_cnt = sum(1 for l in logs if l.status in ("FAILED", "VALIDATION_ERROR"))
    unconfigured_cnt = sum(1 for l in logs if l.status == "UNCONFIGURED")

    latencies = sorted(l.duration_ms for l in logs if l.duration_ms is not None)
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    p95_latency = latencies[int(0.95 * (len(latencies) - 1))] if latencies else 0

    prompt_tokens_total = sum(l.input_tokens for l in logs if l.input_tokens is not None)
    output_tokens_total = sum(l.output_tokens for l in logs if l.output_tokens is not None)
    total_tokens_sum = sum(l.total_tokens for l in logs if l.total_tokens is not None)
    cost_known = [l.estimated_cost_usd for l in logs if l.estimated_cost_usd is not None]
    estimated_cost_total = round(sum(cost_known), 6) if cost_known else None

    by_task: Dict[str, Dict[str, Any]] = {}
    for l in logs:
        bucket = by_task.setdefault(
            l.operation_type,
            {"count": 0, "success": 0, "cache_hits": 0, "errors": 0, "avg_latency_ms": 0.0, "_lat_sum": 0},
        )
        bucket["count"] += 1
        if l.status == "SUCCESS":
            bucket["success"] += 1
        elif l.status in ("FAILED", "VALIDATION_ERROR", "RATE_LIMITED"):
            bucket["errors"] += 1
        if l.cache_hit:
            bucket["cache_hits"] += 1
        bucket["_lat_sum"] += int(l.duration_ms or 0)
    for b in by_task.values():
        b["avg_latency_ms"] = round(b.pop("_lat_sum") / max(1, b["count"]), 1)

    recent_logs = [
        {
            "id": l.id,
            "task_type": l.operation_type,
            "model_name": l.model_name,
            "status": l.status,
            "latency_ms": l.duration_ms,
            "cache_hit": l.cache_hit,
            "prompt_tokens": l.input_tokens,
            "output_tokens": l.output_tokens,
            "total_tokens": l.total_tokens,
            "estimated_cost_usd": l.estimated_cost_usd,
            "error_type": l.error_category,
            "created_at": l.created_at.isoformat() if l.created_at else "",
        }
        for l in logs[:25]
    ]

    return {
        "gemini_configured": gemini_service.is_available,
        "quality_model": gemini_service.model_name,
        "fast_model": gemini_service.fast_model_name,
        "total_requests": total,
        "success_count": success_cnt,
        "cache_hits": cache_hits,
        "cache_hit_rate": round((cache_hits / total) * 100.0, 1) if total else 0.0,
        "active_cache_entries": len(cache_rows),
        "rate_limited_count": rate_limited,
        "failed_count": failed_cnt,
        "unconfigured_count": unconfigured_cnt,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "prompt_tokens": prompt_tokens_total,
        "output_tokens": output_tokens_total,
        "total_tokens": total_tokens_sum,
        "estimated_cost_usd": estimated_cost_total,
        "by_task": by_task,
        "recent_logs": recent_logs,
    }
