"""
Time Tracking API Routes (Phase 5)
Comprehensive time tracking with reports and analytics
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract
from typing import List, Optional
from datetime import datetime, timedelta
import json

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_time import (
    TimeEntryEnhanced, TimeReport, ProductivityMetric, WorkBreak, TimeGoal,
    TimeEntryType, BillableStatus
)
from pydantic import BaseModel


router = APIRouter(prefix="/time", tags=["time-tracking"])


# Pydantic Models
class TimeEntryCreate(BaseModel):
    description: Optional[str] = None
    task_id: Optional[int] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: Optional[int] = None
    entry_type: TimeEntryType = TimeEntryType.MANUAL
    billable_status: BillableStatus = BillableStatus.NON_BILLABLE
    hourly_rate: Optional[float] = None
    tags: Optional[List[str]] = []


class TimeEntryUpdate(BaseModel):
    description: Optional[str] = None
    end_time: Optional[datetime] = None
    duration: Optional[int] = None
    billable_status: Optional[BillableStatus] = None
    tags: Optional[List[str]] = None


class TimerStart(BaseModel):
    description: Optional[str] = None
    task_id: Optional[int] = None
    tags: Optional[List[str]] = []


class ReportCreate(BaseModel):
    name: str
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    config: Optional[dict] = {}


class TimeGoalCreate(BaseModel):
    title: str
    target_hours: float
    start_date: datetime
    end_date: datetime
    task_filter: Optional[dict] = {}


# ===== TIME ENTRY ENDPOINTS =====

@router.post("/entries", status_code=status.HTTP_201_CREATED)
def create_entry(
    entry: TimeEntryCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a time entry"""
    # Calculate duration if not provided
    duration = entry.duration
    if not duration and entry.end_time:
        duration = int((entry.end_time - entry.start_time).total_seconds())
    
    new_entry = TimeEntryEnhanced(
        user_id=current_user.id,
        description=entry.description,
        task_id=entry.task_id,
        start_time=entry.start_time,
        end_time=entry.end_time,
        duration=duration,
        entry_type=entry.entry_type,
        billable_status=entry.billable_status,
        hourly_rate=entry.hourly_rate,
        tags=json.dumps(entry.tags) if entry.tags else None
    )
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    return new_entry


@router.get("/entries")
def list_entries(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    task_id: Optional[int] = None,
    billable: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List time entries with filters"""
    query = db.query(TimeEntryEnhanced).filter(TimeEntryEnhanced.user_id == current_user.id)
    
    if start_date:
        query = query.filter(TimeEntryEnhanced.start_time >= start_date)
    if end_date:
        query = query.filter(TimeEntryEnhanced.start_time <= end_date)
    if task_id:
        query = query.filter(TimeEntryEnhanced.task_id == task_id)
    if billable is not None:
        if billable:
            query = query.filter(TimeEntryEnhanced.billable_status == BillableStatus.BILLABLE)
        else:
            query = query.filter(TimeEntryEnhanced.billable_status == BillableStatus.NON_BILLABLE)
    
    return query.order_by(TimeEntryEnhanced.start_time.desc()).offset(skip).limit(limit).all()


@router.get("/entries/{entry_id}")
def get_entry(
    entry_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific time entry"""
    entry = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.id == entry_id,
        TimeEntryEnhanced.user_id == current_user.id
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")
    
    return entry


@router.patch("/entries/{entry_id}")
def update_entry(
    entry_id: int,
    entry_update: TimeEntryUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a time entry"""
    entry = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.id == entry_id,
        TimeEntryEnhanced.user_id == current_user.id
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")
    
    update_data = entry_update.dict(exclude_unset=True)
    
    # Handle tags separately
    if 'tags' in update_data:
        update_data['tags'] = json.dumps(update_data['tags'])
    
    for field, value in update_data.items():
        setattr(entry, field, value)
    
    # Recalculate duration if end_time changed
    if entry_update.end_time and entry.start_time:
        entry.duration = int((entry_update.end_time - entry.start_time).total_seconds())
    
    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/entries/{entry_id}")
def delete_entry(
    entry_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a time entry"""
    entry = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.id == entry_id,
        TimeEntryEnhanced.user_id == current_user.id
    ).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")
    
    db.delete(entry)
    db.commit()
    return {"message": "Time entry deleted"}


# ===== TIMER ENDPOINTS =====

@router.post("/timer/start")
def start_timer(
    timer: TimerStart,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start a timer"""
    # Check if there's already a running timer
    running = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.user_id == current_user.id,
        TimeEntryEnhanced.is_running == True
    ).first()
    
    if running:
        return {"message": "Timer already running", "entry": running}
    
    new_timer = TimeEntry(
        user_id=current_user.id,
        description=timer.description,
        task_id=timer.task_id,
        start_time=datetime.utcnow(),
        entry_type=TimeEntryType.TIMER,
        is_running=True,
        tags=json.dumps(timer.tags) if timer.tags else None
    )
    db.add(new_timer)
    db.commit()
    db.refresh(new_timer)
    return new_timer


@router.post("/timer/stop")
def stop_timer(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stop the running timer"""
    timer = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.user_id == current_user.id,
        TimeEntryEnhanced.is_running == True
    ).first()
    
    if not timer:
        raise HTTPException(status_code=404, detail="No running timer")
    
    timer.end_time = datetime.utcnow()
    timer.duration = int((timer.end_time - timer.start_time).total_seconds())
    timer.is_running = False
    db.commit()
    db.refresh(timer)
    return timer


@router.get("/timer/current")
def get_current_timer(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get currently running timer"""
    timer = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.user_id == current_user.id,
        TimeEntryEnhanced.is_running == True
    ).first()
    
    if not timer:
        return {"running": False}
    
    # Calculate elapsed time
    elapsed = int((datetime.utcnow() - timer.start_time).total_seconds())
    
    return {
        "running": True,
        "entry": timer,
        "elapsed_seconds": elapsed
    }


# ===== ANALYTICS ENDPOINTS =====

@router.get("/analytics/summary")
def get_time_summary(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get time tracking summary"""
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=7)
    if not end_date:
        end_date = datetime.utcnow()
    
    entries = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.user_id == current_user.id,
        TimeEntryEnhanced.start_time >= start_date,
        TimeEntryEnhanced.start_time <= end_date
    ).all()
    
    total_seconds = sum(e.duration or 0 for e in entries)
    total_hours = total_seconds / 3600
    
    billable_seconds = sum(
        e.duration or 0 for e in entries 
        if e.billable_status == BillableStatus.BILLABLE
    )
    billable_hours = billable_seconds / 3600
    
    billable_amount = sum(
        (e.duration or 0) / 3600 * (e.hourly_rate or 0) 
        for e in entries 
        if e.billable_status == BillableStatus.BILLABLE
    )
    
    # Group by date
    daily_totals = {}
    for entry in entries:
        date_key = entry.start_time.date().isoformat()
        if date_key not in daily_totals:
            daily_totals[date_key] = 0
        daily_totals[date_key] += (entry.duration or 0) / 3600
    
    return {
        "total_hours": round(total_hours, 2),
        "billable_hours": round(billable_hours, 2),
        "non_billable_hours": round(total_hours - billable_hours, 2),
        "billable_amount": round(billable_amount, 2),
        "entries_count": len(entries),
        "daily_totals": daily_totals,
        "average_daily_hours": round(total_hours / max(len(daily_totals), 1), 2)
    }


@router.get("/analytics/by-task")
def get_time_by_task(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get time breakdown by task"""
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow()
    
    # Query with aggregation
    results = db.query(
        TimeEntryEnhanced.task_id,
        func.sum(TimeEntryEnhanced.duration).label('total_duration'),
        func.count(TimeEntryEnhanced.id).label('entry_count')
    ).filter(
        TimeEntryEnhanced.user_id == current_user.id,
        TimeEntryEnhanced.start_time >= start_date,
        TimeEntryEnhanced.start_time <= end_date,
        TimeEntryEnhanced.task_id.isnot(None)
    ).group_by(TimeEntryEnhanced.task_id).all()
    
    task_breakdown = []
    for task_id, total_duration, entry_count in results:
        # Get task details
        from ..models_tasks import Task
        task = db.query(Task).filter(Task.id == task_id).first()
        
        task_breakdown.append({
            "task_id": task_id,
            "task_title": task.title if task else "Unknown Task",
            "total_hours": round((total_duration or 0) / 3600, 2),
            "entry_count": entry_count
        })
    
    # Sort by time spent
    task_breakdown.sort(key=lambda x: x['total_hours'], reverse=True)
    
    return task_breakdown


@router.get("/analytics/weekly-comparison")
def get_weekly_comparison(
    weeks: int = 4,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Compare time across recent weeks"""
    weekly_data = []
    
    for i in range(weeks):
        week_end = datetime.utcnow() - timedelta(days=i*7)
        week_start = week_end - timedelta(days=7)
        
        entries = db.query(TimeEntryEnhanced).filter(
            TimeEntryEnhanced.user_id == current_user.id,
            TimeEntryEnhanced.start_time >= week_start,
            TimeEntryEnhanced.start_time < week_end
        ).all()
        
        total_hours = sum((e.duration or 0) for e in entries) / 3600
        
        weekly_data.append({
            "week_start": week_start.date().isoformat(),
            "week_end": week_end.date().isoformat(),
            "total_hours": round(total_hours, 2),
            "entries_count": len(entries)
        })
    
    return weekly_data


# ===== REPORTS =====

@router.post("/reports", status_code=status.HTTP_201_CREATED)
def create_report(
    report: ReportCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a saved report"""
    new_report = TimeReport(
        name=report.name,
        description=report.description,
        user_id=current_user.id,
        start_date=report.start_date,
        end_date=report.end_date,
        config=json.dumps(report.config) if report.config else None
    )
    db.add(new_report)
    db.commit()
    db.refresh(new_report)
    return new_report


@router.get("/reports")
def list_reports(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all saved reports"""
    reports = db.query(TimeReport).filter(
        TimeReport.user_id == current_user.id
    ).order_by(TimeReport.created_at.desc()).all()
    return reports


# ===== PRODUCTIVITY METRICS =====

@router.get("/productivity/today")
def get_today_productivity(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get today's productivity metrics"""
    today = datetime.utcnow().date()
    
    metric = db.query(ProductivityMetric).filter(
        ProductivityMetric.user_id == current_user.id,
        func.date(ProductivityMetric.date) == today
    ).first()
    
    if not metric:
        # Calculate on the fly
        from ..models_tasks import Task
        
        time_logged = db.query(func.sum(TimeEntryEnhanced.duration)).filter(
            TimeEntryEnhanced.user_id == current_user.id,
            func.date(TimeEntryEnhanced.start_time) == today
        ).scalar() or 0
        
        tasks_completed = db.query(Task).filter(
            Task.assignee_id == current_user.id,
            func.date(Task.completed_at) == today
        ).count()
        
        return {
            "date": today.isoformat(),
            "total_time_logged": time_logged,
            "tasks_completed": tasks_completed,
            "focus_score": 0
        }
    
    return metric


@router.get("/productivity/trend")
def get_productivity_trend(
    days: int = 30,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get productivity trend over time"""
    start_date = datetime.utcnow() - timedelta(days=days)
    
    metrics = db.query(ProductivityMetric).filter(
        ProductivityMetric.user_id == current_user.id,
        ProductivityMetric.date >= start_date
    ).order_by(ProductivityMetric.date.asc()).all()
    
    return metrics


# ===== TIME GOALS =====

@router.post("/goals", status_code=status.HTTP_201_CREATED)
def create_time_goal(
    goal: TimeGoalCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a time goal"""
    new_goal = TimeGoal(
        user_id=current_user.id,
        title=goal.title,
        target_hours=goal.target_hours,
        start_date=goal.start_date,
        end_date=goal.end_date,
        task_filter=json.dumps(goal.task_filter) if goal.task_filter else None
    )
    db.add(new_goal)
    db.commit()
    db.refresh(new_goal)
    return new_goal


@router.get("/goals")
def list_time_goals(
    active_only: bool = True,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List time goals"""
    query = db.query(TimeGoal).filter(TimeGoal.user_id == current_user.id)
    
    if active_only:
        query = query.filter(TimeGoal.is_active == True)
    
    return query.order_by(TimeGoal.created_at.desc()).all()


@router.get("/goals/{goal_id}/progress")
def get_goal_progress(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get progress toward a time goal"""
    goal = db.query(TimeGoal).filter(
        TimeGoal.id == goal_id,
        TimeGoal.user_id == current_user.id
    ).first()
    
    if not goal:
        raise HTTPException(status_code=404, detail="Time goal not found")
    
    # Calculate actual hours
    entries = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.user_id == current_user.id,
        TimeEntryEnhanced.start_time >= goal.start_date,
        TimeEntryEnhanced.start_time <= goal.end_date
    ).all()
    
    actual_hours = sum((e.duration or 0) for e in entries) / 3600
    progress_percent = (actual_hours / goal.target_hours * 100) if goal.target_hours > 0 else 0
    
    return {
        "goal": goal,
        "target_hours": goal.target_hours,
        "actual_hours": round(actual_hours, 2),
        "remaining_hours": round(goal.target_hours - actual_hours, 2),
        "progress_percent": round(progress_percent, 2),
        "is_achieved": actual_hours >= goal.target_hours
    }


# ===== BREAKS =====

@router.post("/breaks/start")
def start_break(
    break_type: str = "break",
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start a break"""
    # Stop any running timer
    timer = db.query(TimeEntryEnhanced).filter(
        TimeEntryEnhanced.user_id == current_user.id,
        TimeEntryEnhanced.is_running == True
    ).first()
    
    if timer:
        timer.end_time = datetime.utcnow()
        timer.duration = int((timer.end_time - timer.start_time).total_seconds())
        timer.is_running = False
    
    new_break = WorkBreak(
        user_id=current_user.id,
        start_time=datetime.utcnow(),
        break_type=break_type
    )
    db.add(new_break)
    db.commit()
    db.refresh(new_break)
    return new_break


@router.post("/breaks/end")
def end_break(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """End current break"""
    work_break = db.query(WorkBreak).filter(
        WorkBreak.user_id == current_user.id,
        WorkBreak.end_time.is_(None)
    ).first()
    
    if not work_break:
        raise HTTPException(status_code=404, detail="No active break")
    
    work_break.end_time = datetime.utcnow()
    work_break.duration = int((work_break.end_time - work_break.start_time).total_seconds())
    db.commit()
    return work_break
