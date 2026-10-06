"""
Pomodoro Timer API Routes - Advanced Time Tracking
Supports timer sessions, breaks, idle detection, and productivity analytics
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
from datetime import datetime, timedelta, date
from pydantic import BaseModel

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_pomodoro import (
    PomodoroSettings, PomodoroSession, PomodoroIdlePeriod,
    PomodoroStatistics, PomodoroStreak,
    PomodoroSessionType, PomodoroSessionStatus
)


router = APIRouter(prefix="/pomodoro", tags=["pomodoro"])


# ─────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────

class PomodoroSettingsUpdate(BaseModel):
    focus_duration: Optional[int] = None
    short_break_duration: Optional[int] = None
    long_break_duration: Optional[int] = None
    sessions_before_long_break: Optional[int] = None
    auto_start_breaks: Optional[bool] = None
    auto_start_focus: Optional[bool] = None
    idle_detection_enabled: Optional[bool] = None
    idle_threshold_minutes: Optional[int] = None
    sound_enabled: Optional[bool] = None
    notification_enabled: Optional[bool] = None
    daily_goal_sessions: Optional[int] = None


class PomodoroSettingsResponse(BaseModel):
    id: int
    user_id: int
    focus_duration: int
    short_break_duration: int
    long_break_duration: int
    sessions_before_long_break: int
    auto_start_breaks: bool
    auto_start_focus: bool
    idle_detection_enabled: bool
    idle_threshold_minutes: int
    sound_enabled: bool
    notification_enabled: bool
    daily_goal_sessions: int
    
    class Config:
        from_attributes = True


class PomodoroSessionCreate(BaseModel):
    session_type: PomodoroSessionType
    planned_duration: int
    task_id: Optional[int] = None
    session_number: Optional[int] = None


class PomodoroSessionUpdate(BaseModel):
    status: Optional[PomodoroSessionStatus] = None
    notes: Optional[str] = None
    actual_duration: Optional[int] = None
    idle_time_seconds: Optional[int] = None
    was_interrupted: Optional[bool] = None


class PomodoroSessionResponse(BaseModel):
    id: int
    user_id: int
    task_id: Optional[int]
    session_type: str
    status: str
    planned_duration: int
    actual_duration: Optional[int]
    start_time: datetime
    end_time: Optional[datetime]
    paused_at: Optional[datetime]
    idle_time_seconds: int
    was_interrupted: bool
    session_number: Optional[int]
    notes: Optional[str]
    
    class Config:
        from_attributes = True


class IdlePeriodCreate(BaseModel):
    session_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None


class IdlePeriodResponse(BaseModel):
    id: int
    session_id: int
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[int]
    resumed_automatically: bool
    user_dismissed: bool
    
    class Config:
        from_attributes = True


class StatisticsResponse(BaseModel):
    date: datetime
    focus_sessions_completed: int
    focus_sessions_cancelled: int
    total_focus_minutes: int
    short_breaks_taken: int
    long_breaks_taken: int
    breaks_skipped: int
    total_idle_minutes: int
    interruption_count: int
    completion_rate: float
    tasks_completed: int
    
    class Config:
        from_attributes = True


class StreakResponse(BaseModel):
    current_streak_days: int
    current_streak_start: Optional[datetime]
    longest_streak_days: int
    longest_streak_start: Optional[datetime]
    longest_streak_end: Optional[datetime]
    last_session_date: Optional[datetime]
    
    class Config:
        from_attributes = True


class DashboardResponse(BaseModel):
    """Comprehensive Pomodoro dashboard data"""
    today_stats: Optional[StatisticsResponse]
    week_stats: List[StatisticsResponse]
    streak: StreakResponse
    active_session: Optional[PomodoroSessionResponse]
    settings: PomodoroSettingsResponse


# ─────────────────────────────────────────────────────────────
# Settings Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/settings", response_model=PomodoroSettingsResponse)
def get_settings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's Pomodoro settings (creates default if not exists)"""
    settings = db.query(PomodoroSettings).filter(
        PomodoroSettings.user_id == current_user.id
    ).first()
    
    if not settings:
        # Create default settings
        settings = PomodoroSettings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    return settings


@router.patch("/settings", response_model=PomodoroSettingsResponse)
def update_settings(
    settings_data: PomodoroSettingsUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user's Pomodoro settings"""
    settings = db.query(PomodoroSettings).filter(
        PomodoroSettings.user_id == current_user.id
    ).first()
    
    if not settings:
        settings = PomodoroSettings(user_id=current_user.id)
        db.add(settings)
    
    for key, value in settings_data.dict(exclude_unset=True).items():
        setattr(settings, key, value)
    
    db.commit()
    db.refresh(settings)
    return settings


# ─────────────────────────────────────────────────────────────
# Session Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=PomodoroSessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(
    session_data: PomodoroSessionCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start a new Pomodoro session"""
    # Check if there's an active session
    active_session = db.query(PomodoroSession).filter(
        PomodoroSession.user_id == current_user.id,
        PomodoroSession.status == PomodoroSessionStatus.ACTIVE
    ).first()
    
    if active_session:
        raise HTTPException(
            status_code=400,
            detail="An active session already exists. Complete or cancel it first."
        )
    
    new_session = PomodoroSession(
        user_id=current_user.id,
        **session_data.dict(),
        start_time=datetime.utcnow()
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    return new_session


@router.get("/sessions/active", response_model=Optional[PomodoroSessionResponse])
def get_active_session(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the current active session if any"""
    session = db.query(PomodoroSession).filter(
        PomodoroSession.user_id == current_user.id,
        PomodoroSession.status.in_([PomodoroSessionStatus.ACTIVE, PomodoroSessionStatus.PAUSED])
    ).first()
    
    return session


@router.patch("/sessions/{session_id}", response_model=PomodoroSessionResponse)
def update_session(
    session_id: int,
    session_data: PomodoroSessionUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a session (pause, resume, complete, cancel)"""
    session = db.query(PomodoroSession).filter(
        PomodoroSession.id == session_id,
        PomodoroSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Handle status changes
    if session_data.status:
        if session_data.status == PomodoroSessionStatus.COMPLETED:
            session.end_time = datetime.utcnow()
            if not session.actual_duration:
                duration = (session.end_time - session.start_time).total_seconds() / 60
                session.actual_duration = int(duration)
            
            # Update statistics
            _update_statistics(db, current_user.id, session)
            
        elif session_data.status == PomodoroSessionStatus.PAUSED:
            session.paused_at = datetime.utcnow()
            
        elif session_data.status == PomodoroSessionStatus.ACTIVE:
            session.paused_at = None
            
        elif session_data.status == PomodoroSessionStatus.CANCELLED:
            session.end_time = datetime.utcnow()
    
    # Update other fields
    for key, value in session_data.dict(exclude_unset=True, exclude={"status"}).items():
        setattr(session, key, value)
    
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=List[PomodoroSessionResponse])
def list_sessions(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    task_id: Optional[int] = None,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's Pomodoro sessions"""
    query = db.query(PomodoroSession).filter(
        PomodoroSession.user_id == current_user.id
    )
    
    if start_date:
        query = query.filter(PomodoroSession.start_time >= datetime.combine(start_date, datetime.min.time()))
    
    if end_date:
        query = query.filter(PomodoroSession.start_time <= datetime.combine(end_date, datetime.max.time()))
    
    if task_id:
        query = query.filter(PomodoroSession.task_id == task_id)
    
    sessions = query.order_by(PomodoroSession.start_time.desc()).limit(limit).all()
    return sessions


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a session"""
    session = db.query(PomodoroSession).filter(
        PomodoroSession.id == session_id,
        PomodoroSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    db.delete(session)
    db.commit()
    return None


# ─────────────────────────────────────────────────────────────
# Idle Detection Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/idle", response_model=IdlePeriodResponse, status_code=status.HTTP_201_CREATED)
def report_idle(
    session_id: int,
    idle_data: IdlePeriodCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Report an idle period detected by the client"""
    session = db.query(PomodoroSession).filter(
        PomodoroSession.id == session_id,
        PomodoroSession.user_id == current_user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    idle_period = PomodoroIdlePeriod(**idle_data.dict())
    db.add(idle_period)
    
    # Update session idle time
    if idle_data.duration_seconds:
        session.idle_time_seconds += idle_data.duration_seconds
        session.was_interrupted = True
    
    db.commit()
    db.refresh(idle_period)
    return idle_period


@router.patch("/idle/{idle_id}/dismiss")
def dismiss_idle(
    idle_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark idle period as dismissed by user"""
    idle_period = db.query(PomodoroIdlePeriod).join(
        PomodoroSession
    ).filter(
        PomodoroIdlePeriod.id == idle_id,
        PomodoroSession.user_id == current_user.id
    ).first()
    
    if not idle_period:
        raise HTTPException(status_code=404, detail="Idle period not found")
    
    idle_period.user_dismissed = True
    db.commit()
    
    return {"status": "dismissed"}


# ─────────────────────────────────────────────────────────────
# Statistics & Analytics Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/statistics", response_model=List[StatisticsResponse])
def get_statistics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get Pomodoro statistics for a date range"""
    if not start_date:
        start_date = date.today() - timedelta(days=7)
    if not end_date:
        end_date = date.today()
    
    stats = db.query(PomodoroStatistics).filter(
        PomodoroStatistics.user_id == current_user.id,
        PomodoroStatistics.date >= datetime.combine(start_date, datetime.min.time()),
        PomodoroStatistics.date <= datetime.combine(end_date, datetime.max.time())
    ).order_by(PomodoroStatistics.date).all()
    
    return stats


@router.get("/statistics/today", response_model=Optional[StatisticsResponse])
def get_today_statistics(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get today's Pomodoro statistics"""
    today = date.today()
    stats = db.query(PomodoroStatistics).filter(
        PomodoroStatistics.user_id == current_user.id,
        func.date(PomodoroStatistics.date) == today
    ).first()
    
    if not stats:
        # Create empty stats for today
        stats = PomodoroStatistics(
            user_id=current_user.id,
            date=datetime.combine(today, datetime.min.time())
        )
        db.add(stats)
        db.commit()
        db.refresh(stats)
    
    return stats


@router.get("/streak", response_model=StreakResponse)
def get_streak(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user's Pomodoro streak"""
    streak = db.query(PomodoroStreak).filter(
        PomodoroStreak.user_id == current_user.id
    ).first()
    
    if not streak:
        streak = PomodoroStreak(user_id=current_user.id)
        db.add(streak)
        db.commit()
        db.refresh(streak)
    
    return streak


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get comprehensive Pomodoro dashboard data"""
    # Get today's stats
    today = date.today()
    today_stats = db.query(PomodoroStatistics).filter(
        PomodoroStatistics.user_id == current_user.id,
        func.date(PomodoroStatistics.date) == today
    ).first()
    
    # Get week stats
    week_ago = today - timedelta(days=7)
    week_stats = db.query(PomodoroStatistics).filter(
        PomodoroStatistics.user_id == current_user.id,
        PomodoroStatistics.date >= datetime.combine(week_ago, datetime.min.time())
    ).order_by(PomodoroStatistics.date).all()
    
    # Get streak
    streak = db.query(PomodoroStreak).filter(
        PomodoroStreak.user_id == current_user.id
    ).first()
    if not streak:
        streak = PomodoroStreak(user_id=current_user.id)
        db.add(streak)
        db.commit()
        db.refresh(streak)
    
    # Get active session
    active_session = db.query(PomodoroSession).filter(
        PomodoroSession.user_id == current_user.id,
        PomodoroSession.status.in_([PomodoroSessionStatus.ACTIVE, PomodoroSessionStatus.PAUSED])
    ).first()
    
    # Get settings
    settings = db.query(PomodoroSettings).filter(
        PomodoroSettings.user_id == current_user.id
    ).first()
    if not settings:
        settings = PomodoroSettings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    return {
        "today_stats": today_stats,
        "week_stats": week_stats,
        "streak": streak,
        "active_session": active_session,
        "settings": settings
    }


# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────

def _update_statistics(db: Session, user_id: int, session: PomodoroSession):
    """Update daily statistics when a session completes"""
    today = date.today()
    stats = db.query(PomodoroStatistics).filter(
        PomodoroStatistics.user_id == user_id,
        func.date(PomodoroStatistics.date) == today
    ).first()
    
    if not stats:
        stats = PomodoroStatistics(
            user_id=user_id,
            date=datetime.combine(today, datetime.min.time())
        )
        db.add(stats)
    
    # Update counts based on session type and status
    if session.session_type == PomodoroSessionType.FOCUS:
        if session.status == PomodoroSessionStatus.COMPLETED:
            stats.focus_sessions_completed += 1
            stats.total_focus_minutes += session.actual_duration or 0
        elif session.status == PomodoroSessionStatus.CANCELLED:
            stats.focus_sessions_cancelled += 1
    elif session.session_type == PomodoroSessionType.SHORT_BREAK:
        if session.status == PomodoroSessionStatus.COMPLETED:
            stats.short_breaks_taken += 1
        else:
            stats.breaks_skipped += 1
    elif session.session_type == PomodoroSessionType.LONG_BREAK:
        if session.status == PomodoroSessionStatus.COMPLETED:
            stats.long_breaks_taken += 1
        else:
            stats.breaks_skipped += 1
    
    # Update idle time
    stats.total_idle_minutes += session.idle_time_seconds // 60
    
    # Update interruption count
    if session.was_interrupted:
        stats.interruption_count += 1
    
    # Calculate completion rate
    total_sessions = stats.focus_sessions_completed + stats.focus_sessions_cancelled
    if total_sessions > 0:
        stats.completion_rate = (stats.focus_sessions_completed / total_sessions) * 100
    
    db.commit()
    
    # Update streak
    _update_streak(db, user_id)


def _update_streak(db: Session, user_id: int):
    """Update user's Pomodoro streak"""
    streak = db.query(PomodoroStreak).filter(
        PomodoroStreak.user_id == user_id
    ).first()
    
    if not streak:
        streak = PomodoroStreak(user_id=user_id)
        db.add(streak)
    
    today = date.today()
    last_date = streak.last_session_date.date() if streak.last_session_date else None
    
    # Update streak logic
    if not last_date:
        # First session ever
        streak.current_streak_days = 1
        streak.current_streak_start = datetime.combine(today, datetime.min.time())
    elif last_date == today:
        # Already logged today, no change
        pass
    elif last_date == today - timedelta(days=1):
        # Consecutive day
        streak.current_streak_days += 1
    else:
        # Streak broken
        streak.current_streak_days = 1
        streak.current_streak_start = datetime.combine(today, datetime.min.time())
    
    # Update longest streak
    if streak.current_streak_days > streak.longest_streak_days:
        streak.longest_streak_days = streak.current_streak_days
        streak.longest_streak_start = streak.current_streak_start
        streak.longest_streak_end = datetime.combine(today, datetime.min.time())
    
    streak.last_session_date = datetime.combine(today, datetime.min.time())
    db.commit()
