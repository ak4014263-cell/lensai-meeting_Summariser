"""
Goals & Dashboards API Routes (Phase 4)
OKR-style goal tracking with custom dashboards
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime
import json

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_goals import (
    Goal, KeyResult, GoalUpdate, Dashboard, DashboardWidget, Milestone,
    GoalStatus, GoalPeriod, WidgetType
)
from pydantic import BaseModel


router = APIRouter(prefix="/goals", tags=["goals"])


# Pydantic Models
class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    workspace_id: Optional[int] = None
    parent_goal_id: Optional[int] = None
    target_value: Optional[float] = None
    unit: Optional[str] = "percent"
    period: GoalPeriod = GoalPeriod.QUARTERLY
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    color: str = "#3B82F6"
    icon: Optional[str] = None


class GoalUpdate_Model(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[GoalStatus] = None
    current_value: Optional[float] = None
    target_value: Optional[float] = None
    due_date: Optional[datetime] = None
    is_archived: Optional[bool] = None


class KeyResultCreate(BaseModel):
    title: str
    description: Optional[str] = None
    target_value: float
    unit: Optional[str] = "percent"
    owner_id: Optional[int] = None
    linked_task_id: Optional[int] = None


class KeyResultUpdate(BaseModel):
    current_value: Optional[float] = None
    status: Optional[GoalStatus] = None


class GoalUpdateCreate(BaseModel):
    content: str
    new_value: Optional[float] = None


class DashboardCreate(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_id: Optional[int] = None
    is_default: bool = False
    is_public: bool = False


class WidgetCreate(BaseModel):
    widget_type: WidgetType
    title: Optional[str] = None
    position_x: int = 0
    position_y: int = 0
    width: int = 4
    height: int = 3
    config: Optional[dict] = {}


class MilestoneCreate(BaseModel):
    title: str
    description: Optional[str] = None
    workspace_id: Optional[int] = None
    goal_id: Optional[int] = None
    due_date: Optional[datetime] = None


# ===== GOAL ENDPOINTS =====

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_goal(
    goal: GoalCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new goal"""
    new_goal = Goal(
        **goal.dict(),
        owner_id=current_user.id
    )
    db.add(new_goal)
    db.commit()
    db.refresh(new_goal)
    return new_goal


@router.get("/")
def list_goals(
    workspace_id: Optional[int] = None,
    status: Optional[GoalStatus] = None,
    period: Optional[GoalPeriod] = None,
    archived: bool = False,
    skip: int = 0,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all goals"""
    query = db.query(Goal).filter(
        Goal.owner_id == current_user.id,
        Goal.is_archived == archived
    )
    
    if workspace_id:
        query = query.filter(Goal.workspace_id == workspace_id)
    if status:
        query = query.filter(Goal.status == status)
    if period:
        query = query.filter(Goal.period == period)
    
    return query.order_by(Goal.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{goal_id}")
def get_goal(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific goal"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    if goal.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return goal


@router.patch("/{goal_id}")
def update_goal(
    goal_id: int,
    goal_update: GoalUpdate_Model,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a goal"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    if goal.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Track value change for updates
    previous_value = goal.current_value
    
    update_data = goal_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(goal, field, value)
    
    goal.updated_at = datetime.utcnow()
    
    # Auto-calculate status based on progress
    if goal.target_value and goal.current_value is not None:
        progress = (goal.current_value / goal.target_value) * 100
        if progress >= 100:
            goal.status = GoalStatus.COMPLETED
        elif progress >= 75:
            goal.status = GoalStatus.ON_TRACK
        elif progress >= 50:
            goal.status = GoalStatus.AT_RISK
        else:
            goal.status = GoalStatus.OFF_TRACK
    
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/{goal_id}")
def delete_goal(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a goal"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal or goal.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    db.delete(goal)
    db.commit()
    return {"message": "Goal deleted"}


# ===== KEY RESULTS =====

@router.post("/{goal_id}/key-results", status_code=status.HTTP_201_CREATED)
def create_key_result(
    goal_id: int,
    key_result: KeyResultCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a key result for a goal"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal or goal.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    new_kr = KeyResult(
        goal_id=goal_id,
        **key_result.dict()
    )
    db.add(new_kr)
    db.commit()
    db.refresh(new_kr)
    return new_kr


@router.get("/{goal_id}/key-results")
def get_key_results(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all key results for a goal"""
    key_results = db.query(KeyResult).filter(KeyResult.goal_id == goal_id).all()
    return key_results


@router.patch("/key-results/{kr_id}")
def update_key_result(
    kr_id: int,
    kr_update: KeyResultUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a key result"""
    kr = db.query(KeyResult).filter(KeyResult.id == kr_id).first()
    if not kr:
        raise HTTPException(status_code=404, detail="Key result not found")
    
    update_data = kr_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(kr, field, value)
    
    kr.updated_at = datetime.utcnow()
    
    # Update parent goal progress
    goal = db.query(Goal).filter(Goal.id == kr.goal_id).first()
    if goal:
        # Calculate average progress of all key results
        all_krs = db.query(KeyResult).filter(KeyResult.goal_id == goal.id).all()
        total_progress = sum((kr.current_value / kr.target_value * 100) for kr in all_krs if kr.target_value)
        goal.current_value = total_progress / len(all_krs) if all_krs else 0
        goal.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(kr)
    return kr


# ===== GOAL UPDATES =====

@router.post("/{goal_id}/updates", status_code=status.HTTP_201_CREATED)
def add_goal_update(
    goal_id: int,
    update: GoalUpdateCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a progress update to a goal"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    previous_value = goal.current_value
    
    new_update = GoalUpdate(
        goal_id=goal_id,
        user_id=current_user.id,
        content=update.content,
        previous_value=previous_value,
        new_value=update.new_value
    )
    
    if update.new_value is not None:
        goal.current_value = update.new_value
        goal.updated_at = datetime.utcnow()
    
    db.add(new_update)
    db.commit()
    db.refresh(new_update)
    return new_update


@router.get("/{goal_id}/updates")
def get_goal_updates(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all updates for a goal"""
    updates = db.query(GoalUpdate).filter(
        GoalUpdate.goal_id == goal_id
    ).order_by(GoalUpdate.created_at.desc()).all()
    return updates


# ===== DASHBOARD ENDPOINTS =====

@router.post("/dashboards", status_code=status.HTTP_201_CREATED)
def create_dashboard(
    dashboard: DashboardCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a custom dashboard"""
    new_dashboard = Dashboard(
        **dashboard.dict(),
        owner_id=current_user.id
    )
    db.add(new_dashboard)
    db.commit()
    db.refresh(new_dashboard)
    return new_dashboard


@router.get("/dashboards")
def list_dashboards(
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all dashboards"""
    query = db.query(Dashboard).filter(Dashboard.owner_id == current_user.id)
    
    if workspace_id:
        query = query.filter(Dashboard.workspace_id == workspace_id)
    
    return query.order_by(Dashboard.is_default.desc(), Dashboard.created_at.desc()).all()


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(
    dashboard_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific dashboard with widgets"""
    dashboard = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    if dashboard.owner_id != current_user.id and not dashboard.is_public:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return dashboard


@router.post("/dashboards/{dashboard_id}/widgets", status_code=status.HTTP_201_CREATED)
def add_widget(
    dashboard_id: int,
    widget: WidgetCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a widget to a dashboard"""
    dashboard = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not dashboard or dashboard.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    new_widget = DashboardWidget(
        dashboard_id=dashboard_id,
        widget_type=widget.widget_type,
        title=widget.title,
        position_x=widget.position_x,
        position_y=widget.position_y,
        width=widget.width,
        height=widget.height,
        config=json.dumps(widget.config) if widget.config else None
    )
    db.add(new_widget)
    db.commit()
    db.refresh(new_widget)
    return new_widget


@router.delete("/dashboards/widgets/{widget_id}")
def remove_widget(
    widget_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a widget from a dashboard"""
    widget = db.query(DashboardWidget).filter(DashboardWidget.id == widget_id).first()
    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found")
    
    dashboard = db.query(Dashboard).filter(Dashboard.id == widget.dashboard_id).first()
    if not dashboard or dashboard.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    db.delete(widget)
    db.commit()
    return {"message": "Widget removed"}


# ===== MILESTONES =====

@router.post("/milestones", status_code=status.HTTP_201_CREATED)
def create_milestone(
    milestone: MilestoneCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a milestone"""
    new_milestone = Milestone(**milestone.dict())
    db.add(new_milestone)
    db.commit()
    db.refresh(new_milestone)
    return new_milestone


@router.get("/milestones")
def list_milestones(
    workspace_id: Optional[int] = None,
    goal_id: Optional[int] = None,
    completed: Optional[bool] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List milestones"""
    query = db.query(Milestone)
    
    if workspace_id:
        query = query.filter(Milestone.workspace_id == workspace_id)
    if goal_id:
        query = query.filter(Milestone.goal_id == goal_id)
    if completed is not None:
        query = query.filter(Milestone.is_completed == completed)
    
    return query.order_by(Milestone.due_date.asc()).all()


@router.patch("/milestones/{milestone_id}/complete")
def complete_milestone(
    milestone_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark a milestone as completed"""
    milestone = db.query(Milestone).filter(Milestone.id == milestone_id).first()
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")
    
    milestone.is_completed = True
    milestone.completed_at = datetime.utcnow()
    db.commit()
    
    return {"message": "Milestone completed"}


# ===== ANALYTICS =====

@router.get("/analytics/progress")
def get_progress_analytics(
    workspace_id: Optional[int] = None,
    period: Optional[GoalPeriod] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get goal progress analytics"""
    query = db.query(Goal).filter(Goal.owner_id == current_user.id)
    
    if workspace_id:
        query = query.filter(Goal.workspace_id == workspace_id)
    if period:
        query = query.filter(Goal.period == period)
    
    goals = query.all()
    
    # Calculate statistics
    total = len(goals)
    completed = len([g for g in goals if g.status == GoalStatus.COMPLETED])
    on_track = len([g for g in goals if g.status == GoalStatus.ON_TRACK])
    at_risk = len([g for g in goals if g.status == GoalStatus.AT_RISK])
    off_track = len([g for g in goals if g.status == GoalStatus.OFF_TRACK])
    
    avg_progress = sum(g.current_value or 0 for g in goals) / total if total > 0 else 0
    
    return {
        "total_goals": total,
        "completed": completed,
        "on_track": on_track,
        "at_risk": at_risk,
        "off_track": off_track,
        "completion_rate": (completed / total * 100) if total > 0 else 0,
        "average_progress": avg_progress
    }


# ─────────────────────────────────────────────────────────────
# Goal Hierarchy Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/{goal_id}/hierarchy")
def get_goal_hierarchy(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get goal with all its children in a tree structure"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    def build_tree(g):
        """Recursively build goal tree"""
        children = db.query(Goal).filter(Goal.parent_goal_id == g.id).all()
        return {
            "id": g.id,
            "title": g.title,
            "status": g.status.value,
            "progress": (g.current_value / g.target_value * 100) if g.target_value else 0,
            "current_value": g.current_value,
            "target_value": g.target_value,
            "unit": g.unit,
            "due_date": g.due_date,
            "owner_id": g.owner_id,
            "children": [build_tree(child) for child in children]
        }
    
    return build_tree(goal)


@router.get("/{goal_id}/ancestors")
def get_goal_ancestors(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all parent goals up to the root"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    ancestors = []
    current = goal
    
    while current.parent_goal_id:
        parent = db.query(Goal).filter(Goal.id == current.parent_goal_id).first()
        if not parent:
            break
        ancestors.append({
            "id": parent.id,
            "title": parent.title,
            "progress": (parent.current_value / parent.target_value * 100) if parent.target_value else 0
        })
        current = parent
    
    return ancestors


@router.post("/{goal_id}/calculate-progress")
def calculate_cascading_progress(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Calculate and update goal progress based on child goals and key results.
    Cascades up to parent goals.
    """
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    # Calculate progress from child goals
    children = db.query(Goal).filter(Goal.parent_goal_id == goal_id).all()
    key_results = db.query(KeyResult).filter(KeyResult.goal_id == goal_id).all()
    
    total_progress = 0
    count = 0
    
    # Average progress from children
    for child in children:
        if child.target_value:
            child_progress = (child.current_value / child.target_value) * 100
            total_progress += child_progress
            count += 1
    
    # Average progress from key results
    for kr in key_results:
        if kr.target_value:
            kr_progress = (kr.current_value / kr.target_value) * 100
            total_progress += kr_progress
            count += 1
    
    if count > 0:
        avg_progress = total_progress / count
        
        # Update goal's current_value based on progress
        if goal.target_value:
            goal.current_value = (avg_progress / 100) * goal.target_value
        
        # Update status based on progress
        if avg_progress >= 100:
            goal.status = GoalStatus.COMPLETED
        elif avg_progress >= 75:
            goal.status = GoalStatus.ON_TRACK
        elif avg_progress >= 50:
            goal.status = GoalStatus.AT_RISK
        elif avg_progress > 0:
            goal.status = GoalStatus.OFF_TRACK
        
        db.commit()
        
        # Cascade to parent if exists
        if goal.parent_goal_id:
            calculate_cascading_progress(goal.parent_goal_id, current_user, db)
    
    db.refresh(goal)
    return {
        "goal_id": goal.id,
        "progress": (goal.current_value / goal.target_value * 100) if goal.target_value else 0,
        "status": goal.status.value,
        "cascaded_to_parent": goal.parent_goal_id is not None
    }


@router.get("/tree")
def get_goals_tree(
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all goals organized in a tree structure (roots only, with nested children)"""
    query = db.query(Goal).filter(Goal.parent_goal_id == None)
    
    if workspace_id:
        query = query.filter(Goal.workspace_id == workspace_id)
    
    roots = query.all()
    
    def build_tree(g):
        """Recursively build goal tree"""
        children = db.query(Goal).filter(Goal.parent_goal_id == g.id).all()
        kr_count = db.query(KeyResult).filter(KeyResult.goal_id == g.id).count()
        
        return {
            "id": g.id,
            "title": g.title,
            "description": g.description,
            "status": g.status.value,
            "progress": (g.current_value / g.target_value * 100) if g.target_value else 0,
            "current_value": g.current_value,
            "target_value": g.target_value,
            "unit": g.unit,
            "due_date": g.due_date,
            "owner_id": g.owner_id,
            "color": g.color,
            "icon": g.icon,
            "key_results_count": kr_count,
            "children_count": len(children),
            "children": [build_tree(child) for child in children]
        }
    
    return [build_tree(root) for root in roots]


@router.get("/{goal_id}/alignment")
def check_goal_alignment(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Check if a goal is aligned with parent goals and provide alignment insights.
    Shows contribution to parent goals.
    """
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    # Get alignment chain
    alignment_chain = []
    current = goal
    
    while current.parent_goal_id:
        parent = db.query(Goal).filter(Goal.id == current.parent_goal_id).first()
        if not parent:
            break
        
        # Calculate contribution
        siblings = db.query(Goal).filter(Goal.parent_goal_id == parent.id).all()
        contribution = 0
        if len(siblings) > 0 and parent.target_value:
            child_total = sum((s.current_value / s.target_value * 100) if s.target_value else 0 for s in siblings)
            if child_total > 0:
                current_contribution = (current.current_value / current.target_value * 100) if current.target_value else 0
                contribution = (current_contribution / child_total) * 100
        
        alignment_chain.append({
            "parent_id": parent.id,
            "parent_title": parent.title,
            "parent_progress": (parent.current_value / parent.target_value * 100) if parent.target_value else 0,
            "contribution_percentage": round(contribution, 2),
            "status_match": parent.status == current.status
        })
        
        current = parent
    
    return {
        "goal_id": goal.id,
        "is_aligned": len(alignment_chain) > 0,
        "alignment_depth": len(alignment_chain),
        "alignment_chain": alignment_chain,
        "has_children": db.query(Goal).filter(Goal.parent_goal_id == goal_id).count() > 0
    }
