"""
Unified Analytics Dashboard API - Advanced Metrics & Insights
Aggregates data from Tasks, Time Tracking, Goals, and Meetings
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case
from typing import List, Optional
from datetime import datetime, timedelta, date
from pydantic import BaseModel

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_tasks import Task, TaskStatus, TaskPriority
from ..models_goals import Goal, KeyResult, GoalStatus
from ..models_pomodoro import PomodoroSession, PomodoroStatistics, PomodoroSessionType
from ..models_time import TimeEntryEnhanced


router = APIRouter(prefix="/analytics", tags=["analytics"])


# ─────────────────────────────────────────────────────────────
# Response Models
# ─────────────────────────────────────────────────────────────

class TaskMetrics(BaseModel):
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    overdue_tasks: int
    completion_rate: float
    avg_completion_time_hours: Optional[float]
    tasks_by_priority: dict
    tasks_by_status: dict


class TimeMetrics(BaseModel):
    total_hours_tracked: float
    billable_hours: float
    non_billable_hours: float
    hours_by_project: dict
    hours_by_day: dict
    avg_daily_hours: float


class GoalMetrics(BaseModel):
    total_goals: int
    active_goals: int
    completed_goals: int
    avg_progress: float
    on_track_count: int
    at_risk_count: int
    off_track_count: int
    goals_by_period: dict


class PomodoroMetrics(BaseModel):
    total_sessions: int
    completed_sessions: int
    cancelled_sessions: int
    total_focus_hours: float
    avg_session_length: float
    completion_rate: float
    productivity_score: float


class ProductivityTrends(BaseModel):
    date: date
    tasks_completed: int
    hours_tracked: float
    pomodoro_sessions: int
    productivity_score: float


class UnifiedDashboard(BaseModel):
    """Complete analytics dashboard"""
    period_start: date
    period_end: date
    task_metrics: TaskMetrics
    time_metrics: TimeMetrics
    goal_metrics: GoalMetrics
    pomodoro_metrics: PomodoroMetrics
    trends: List[ProductivityTrends]
    top_performing_days: List[dict]
    insights: List[str]


# ─────────────────────────────────────────────────────────────
# Analytics Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=UnifiedDashboard)
def get_unified_dashboard(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get unified analytics dashboard with all metrics"""
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()
    
    # Get all metrics
    task_metrics = _get_task_metrics(db, current_user.id, start_date, end_date, workspace_id)
    time_metrics = _get_time_metrics(db, current_user.id, start_date, end_date, workspace_id)
    goal_metrics = _get_goal_metrics(db, current_user.id, workspace_id)
    pomodoro_metrics = _get_pomodoro_metrics(db, current_user.id, start_date, end_date)
    trends = _get_productivity_trends(db, current_user.id, start_date, end_date)
    top_days = _get_top_performing_days(db, current_user.id, start_date, end_date)
    insights = _generate_insights(task_metrics, time_metrics, goal_metrics, pomodoro_metrics, trends)
    
    return {
        "period_start": start_date,
        "period_end": end_date,
        "task_metrics": task_metrics,
        "time_metrics": time_metrics,
        "goal_metrics": goal_metrics,
        "pomodoro_metrics": pomodoro_metrics,
        "trends": trends,
        "top_performing_days": top_days,
        "insights": insights
    }


@router.get("/tasks/metrics", response_model=TaskMetrics)
def get_task_metrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get task-specific metrics"""
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()
    
    return _get_task_metrics(db, current_user.id, start_date, end_date, workspace_id)


@router.get("/time/metrics", response_model=TimeMetrics)
def get_time_metrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get time tracking metrics"""
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()
    
    return _get_time_metrics(db, current_user.id, start_date, end_date, workspace_id)


@router.get("/goals/metrics", response_model=GoalMetrics)
def get_goal_metrics(
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get goal-specific metrics"""
    return _get_goal_metrics(db, current_user.id, workspace_id)


@router.get("/pomodoro/metrics", response_model=PomodoroMetrics)
def get_pomodoro_metrics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get Pomodoro timer metrics"""
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()
    
    return _get_pomodoro_metrics(db, current_user.id, start_date, end_date)


@router.get("/trends", response_model=List[ProductivityTrends])
def get_productivity_trends(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get daily productivity trends"""
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()
    
    return _get_productivity_trends(db, current_user.id, start_date, end_date)


@router.get("/export")
def export_analytics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    format: str = "json",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Export analytics data (JSON or CSV)"""
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()
    
    dashboard = get_unified_dashboard(start_date, end_date, None, current_user, db)
    
    if format == "json":
        return dashboard
    elif format == "csv":
        # Return CSV format (simplified)
        return {"error": "CSV export coming soon"}
    else:
        raise HTTPException(status_code=400, detail="Invalid format. Use 'json' or 'csv'")


# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────

def _get_task_metrics(db: Session, user_id: int, start_date: date, end_date: date, workspace_id: Optional[int]) -> TaskMetrics:
    """Calculate task metrics"""
    query = db.query(Task).filter(
        or_(Task.assignee_id == user_id, Task.created_by_id == user_id)
    )
    
    if workspace_id:
        query = query.join(models.TaskList).filter(models.TaskList.folder_id.in_(
            db.query(models.TaskFolder.id).filter(models.TaskFolder.workspace_id == workspace_id)
        ))
    
    # Filter by date range
    query = query.filter(
        Task.created_at >= datetime.combine(start_date, datetime.min.time()),
        Task.created_at <= datetime.combine(end_date, datetime.max.time())
    )
    
    tasks = query.all()
    total = len(tasks)
    completed = len([t for t in tasks if t.status == TaskStatus.COMPLETED])
    in_progress = len([t for t in tasks if t.status == TaskStatus.IN_PROGRESS])
    overdue = len([t for t in tasks if t.due_date and t.due_date < datetime.now() and t.status != TaskStatus.COMPLETED])
    
    # Completion rate
    completion_rate = (completed / total * 100) if total > 0 else 0
    
    # Average completion time
    completed_tasks = [t for t in tasks if t.status == TaskStatus.COMPLETED and t.completed_at]
    avg_time = None
    if completed_tasks:
        times = [(t.completed_at - t.created_at).total_seconds() / 3600 for t in completed_tasks]
        avg_time = sum(times) / len(times)
    
    # By priority
    priority_counts = {}
    for priority in TaskPriority:
        priority_counts[priority.value] = len([t for t in tasks if t.priority == priority])
    
    # By status
    status_counts = {}
    for status in TaskStatus:
        status_counts[status.value] = len([t for t in tasks if t.status == status])
    
    return TaskMetrics(
        total_tasks=total,
        completed_tasks=completed,
        in_progress_tasks=in_progress,
        overdue_tasks=overdue,
        completion_rate=round(completion_rate, 2),
        avg_completion_time_hours=round(avg_time, 2) if avg_time else None,
        tasks_by_priority=priority_counts,
        tasks_by_status=status_counts
    )


def _get_time_metrics(db: Session, user_id: int, start_date: date, end_date: date, workspace_id: Optional[int]) -> TimeMetrics:
    """Calculate time tracking metrics"""
    query = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.user_id == user_id,
        TimeEntryEnhanced.start_time >= datetime.combine(start_date, datetime.min.time()),
        TimeEntryEnhanced.start_time <= datetime.combine(end_date, datetime.max.time())
    )
    
    entries = query.all()
    
    total_hours = sum([e.duration_hours or 0 for e in entries])
    billable_hours = sum([e.duration_hours or 0 for e in entries if e.is_billable])
    non_billable_hours = total_hours - billable_hours
    
    # By project
    project_hours = {}
    for entry in entries:
        if entry.project_id:
            project_hours[entry.project_id] = project_hours.get(entry.project_id, 0) + (entry.duration_hours or 0)
    
    # By day
    hours_by_day = {}
    for entry in entries:
        day = entry.start_time.date()
        hours_by_day[str(day)] = hours_by_day.get(str(day), 0) + (entry.duration_hours or 0)
    
    # Average daily hours
    num_days = (end_date - start_date).days + 1
    avg_daily = total_hours / num_days if num_days > 0 else 0
    
    return TimeMetrics(
        total_hours_tracked=round(total_hours, 2),
        billable_hours=round(billable_hours, 2),
        non_billable_hours=round(non_billable_hours, 2),
        hours_by_project=project_hours,
        hours_by_day=hours_by_day,
        avg_daily_hours=round(avg_daily, 2)
    )


def _get_goal_metrics(db: Session, user_id: int, workspace_id: Optional[int]) -> GoalMetrics:
    """Calculate goal metrics"""
    query = db.query(Goal).filter(Goal.owner_id == user_id)
    
    if workspace_id:
        query = query.filter(Goal.workspace_id == workspace_id)
    
    goals = query.all()
    total = len(goals)
    active = len([g for g in goals if g.status in [GoalStatus.ON_TRACK, GoalStatus.AT_RISK, GoalStatus.OFF_TRACK]])
    completed = len([g for g in goals if g.status == GoalStatus.COMPLETED])
    
    # Average progress
    progress_values = []
    for g in goals:
        if g.target_value and g.target_value > 0:
            progress_values.append((g.current_value / g.target_value) * 100)
    avg_progress = sum(progress_values) / len(progress_values) if progress_values else 0
    
    # Status counts
    on_track = len([g for g in goals if g.status == GoalStatus.ON_TRACK])
    at_risk = len([g for g in goals if g.status == GoalStatus.AT_RISK])
    off_track = len([g for g in goals if g.status == GoalStatus.OFF_TRACK])
    
    # By period
    period_counts = {}
    from ..models_goals import GoalPeriod
    for period in GoalPeriod:
        period_counts[period.value] = len([g for g in goals if g.period == period])
    
    return GoalMetrics(
        total_goals=total,
        active_goals=active,
        completed_goals=completed,
        avg_progress=round(avg_progress, 2),
        on_track_count=on_track,
        at_risk_count=at_risk,
        off_track_count=off_track,
        goals_by_period=period_counts
    )


def _get_pomodoro_metrics(db: Session, user_id: int, start_date: date, end_date: date) -> PomodoroMetrics:
    """Calculate Pomodoro metrics"""
    from ..models_pomodoro import PomodoroSessionStatus
    
    sessions = db.query(PomodoroSession).filter(
        PomodoroSession.user_id == user_id,
        PomodoroSession.session_type == PomodoroSessionType.FOCUS,
        PomodoroSession.start_time >= datetime.combine(start_date, datetime.min.time()),
        PomodoroSession.start_time <= datetime.combine(end_date, datetime.max.time())
    ).all()
    
    total = len(sessions)
    completed = len([s for s in sessions if s.status == PomodoroSessionStatus.COMPLETED])
    cancelled = len([s for s in sessions if s.status == PomodoroSessionStatus.CANCELLED])
    
    # Total hours
    total_minutes = sum([s.actual_duration or 0 for s in sessions if s.status == PomodoroSessionStatus.COMPLETED])
    total_hours = total_minutes / 60
    
    # Average session length
    avg_length = total_minutes / completed if completed > 0 else 0
    
    # Completion rate
    completion_rate = (completed / total * 100) if total > 0 else 0
    
    # Productivity score (based on completion rate and interruptions)
    interruption_count = len([s for s in sessions if s.was_interrupted])
    interruption_rate = (interruption_count / total * 100) if total > 0 else 0
    productivity_score = completion_rate * (1 - interruption_rate / 100)
    
    return PomodoroMetrics(
        total_sessions=total,
        completed_sessions=completed,
        cancelled_sessions=cancelled,
        total_focus_hours=round(total_hours, 2),
        avg_session_length=round(avg_length, 2),
        completion_rate=round(completion_rate, 2),
        productivity_score=round(productivity_score, 2)
    )


def _get_productivity_trends(db: Session, user_id: int, start_date: date, end_date: date) -> List[ProductivityTrends]:
    """Get daily productivity trends"""
    trends = []
    current_date = start_date
    
    while current_date <= end_date:
        # Tasks completed that day
        tasks_completed = db.query(Task).filter(
            or_(Task.assignee_id == user_id, Task.created_by_id == user_id),
            Task.status == TaskStatus.COMPLETED,
            func.date(Task.completed_at) == current_date
        ).count()
        
        # Hours tracked
        hours = db.query(func.sum(TimeEntryEnhanced.duration_hours)).filter(
            TimeEntryEnhanced.user_id == user_id,
            func.date(TimeEntryEnhanced.start_time) == current_date
        ).scalar() or 0
        
        # Pomodoro sessions
        sessions = db.query(PomodoroSession).filter(
            PomodoroSession.user_id == user_id,
            PomodoroSession.session_type == PomodoroSessionType.FOCUS,
            func.date(PomodoroSession.start_time) == current_date
        ).count()
        
        # Calculate productivity score (weighted average)
        productivity_score = (
            (tasks_completed * 10) + 
            (hours * 5) + 
            (sessions * 3)
        )
        
        trends.append(ProductivityTrends(
            date=current_date,
            tasks_completed=tasks_completed,
            hours_tracked=round(hours, 2),
            pomodoro_sessions=sessions,
            productivity_score=round(productivity_score, 2)
        ))
        
        current_date += timedelta(days=1)
    
    return trends


def _get_top_performing_days(db: Session, user_id: int, start_date: date, end_date: date, limit: int = 5) -> List[dict]:
    """Get top performing days based on productivity score"""
    trends = _get_productivity_trends(db, user_id, start_date, end_date)
    
    # Sort by productivity score
    sorted_trends = sorted(trends, key=lambda x: x.productivity_score, reverse=True)
    
    return [
        {
            "date": t.date,
            "tasks_completed": t.tasks_completed,
            "hours_tracked": t.hours_tracked,
            "pomodoro_sessions": t.pomodoro_sessions,
            "productivity_score": t.productivity_score
        }
        for t in sorted_trends[:limit]
    ]


def _generate_insights(
    task_metrics: TaskMetrics,
    time_metrics: TimeMetrics,
    goal_metrics: GoalMetrics,
    pomodoro_metrics: PomodoroMetrics,
    trends: List[ProductivityTrends]
) -> List[str]:
    """Generate actionable insights based on metrics"""
    insights = []
    
    # Task insights
    if task_metrics.completion_rate < 50:
        insights.append("Your task completion rate is below 50%. Consider breaking down tasks into smaller, manageable pieces.")
    elif task_metrics.completion_rate > 80:
        insights.append("Excellent task completion rate! You're staying on top of your work.")
    
    if task_metrics.overdue_tasks > 5:
        insights.append(f"You have {task_metrics.overdue_tasks} overdue tasks. Review and reprioritize your task list.")
    
    # Time insights
    if time_metrics.avg_daily_hours < 4:
        insights.append("Your tracked time is below 4 hours per day. Consider tracking all your work activities.")
    elif time_metrics.avg_daily_hours > 10:
        insights.append("You're working over 10 hours per day on average. Consider work-life balance.")
    
    # Goal insights
    if goal_metrics.at_risk_count + goal_metrics.off_track_count > goal_metrics.on_track_count:
        insights.append("More goals are at risk or off track than on track. Review your goal strategy.")
    
    if goal_metrics.avg_progress < 30:
        insights.append("Average goal progress is low. Consider breaking goals into smaller milestones.")
    
    # Pomodoro insights
    if pomodoro_metrics.completion_rate < 70:
        insights.append("Your Pomodoro completion rate is below 70%. Try reducing distractions during focus sessions.")
    
    if pomodoro_metrics.total_sessions < 4:
        insights.append("Consider doing at least 4 focus sessions per day for better productivity.")
    
    # Trend insights
    if trends:
        recent_week = trends[-7:] if len(trends) >= 7 else trends
        avg_recent_score = sum(t.productivity_score for t in recent_week) / len(recent_week)
        
        if avg_recent_score > 50:
            insights.append("Your productivity has been strong this week. Keep up the momentum!")
        elif avg_recent_score < 20:
            insights.append("Productivity has been lower this week. Consider reviewing your schedule and priorities.")
    
    return insights
