import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..db.database import get_session
from ..db.models import User, SkillActionPlan
from ..services.auth_service import get_current_user
from ..services.plan_service import _build_dynamic_skill_roadmap, plan_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Skill Gap Action Plans"])


class ActionPlanOut(BaseModel):
    id: int
    skill_name: str
    category: str
    days_to_learn: int
    milestones: List[Dict[str, Any]]
    is_completed: bool
    progress_percent: int = 0


def plan_to_out(plan: SkillActionPlan) -> ActionPlanOut:
    milestones = plan.milestones or []
    total = len(milestones)
    completed = sum(1 for m in milestones if m.get("completed", False))
    percent = int(round((completed / total) * 100)) if total > 0 else 0
    return ActionPlanOut(
        id=plan.id,
        skill_name=plan.skill_name,
        category=plan.category,
        days_to_learn=plan.days_to_learn,
        milestones=milestones,
        is_completed=plan.is_completed,
        progress_percent=percent,
    )


@router.post("/profile/generate-action-plan", response_model=List[ActionPlanOut])
def generate_action_plans(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Analyzes candidate skills against market vacancies, identifies top 3 high-impact missing skills,
    and generates 7-day interactive step-by-step learning roadmaps.
    """
    plans = plan_service.generate_plans_for_user(user=current_user, session=session, force_refresh=True)
    return [plan_to_out(p) for p in plans]


class AddSkillPlanRequest(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=120)
    target_role: Optional[str] = Field(default="Specialist", max_length=120)


@router.post("/action-plans/add-skill", response_model=ActionPlanOut)
def add_single_skill_to_action_plan(
    req: AddSkillPlanRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Creates (or returns existing) 7-day learning roadmap for one specific missing skill."""
    clean_skill = req.skill_name.strip()
    if not clean_skill:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill name is required.")

    existing_plans = session.exec(
        select(SkillActionPlan).where(SkillActionPlan.user_id == current_user.id)
    ).all()
    for p in existing_plans:
        if (p.skill_name or "").strip().lower() == clean_skill.lower():
            return plan_to_out(p)

    roadmap = _build_dynamic_skill_roadmap(clean_skill, role=(req.target_role or "Specialist").strip())
    new_plan = SkillActionPlan(
        user_id=current_user.id,
        skill_name=roadmap["skill_name"],
        category=roadmap["category"],
        days_to_learn=roadmap["days_to_learn"],
        milestones=roadmap["milestones"],
        is_completed=False,
    )
    session.add(new_plan)
    session.commit()
    session.refresh(new_plan)
    return plan_to_out(new_plan)


@router.get("/action-plans", response_model=List[ActionPlanOut])
def list_action_plans(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Lists all active and completed skill roadmaps for the current candidate."""
    plans = session.exec(
        select(SkillActionPlan).where(SkillActionPlan.user_id == current_user.id).order_by(SkillActionPlan.id.asc())
    ).all()
    if not plans:
        # Auto-generate starter plans if none exist yet
        plans = plan_service.generate_plans_for_user(user=current_user, session=session, force_refresh=True)
    return [plan_to_out(p) for p in plans]


@router.patch("/action-plans/{plan_id}/milestones/{milestone_index}", response_model=ActionPlanOut)
def toggle_milestone_completion(
    plan_id: int,
    milestone_index: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Checks off or untoggles a learning milestone.
    When 100% of milestones are checked off, dynamically ingests the newly mastered skill
    into candidate profile so all subsequent vacancy audits and CV generations include it!
    """
    plan = session.get(SkillActionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Action plan {plan_id} not found.")
    if plan.user_id is not None and plan.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: action plan belongs to another user.")

    updated_plan = plan_service.toggle_milestone(plan=plan, milestone_index=milestone_index, session=session)
    return plan_to_out(updated_plan)


@router.delete("/action-plans/{plan_id}")
def delete_action_plan(
    plan_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Removes a skill roadmap."""
    plan = session.get(SkillActionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Action plan {plan_id} not found.")
    if plan.user_id is not None and plan.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: action plan belongs to another user.")

    session.delete(plan)
    session.commit()
    return {"status": "success", "message": f"Action plan for '{plan.skill_name}' removed."}
