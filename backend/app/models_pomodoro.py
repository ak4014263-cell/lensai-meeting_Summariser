"""
Pomodoro Timer Models - Advanced Time Tracking
Supports timer sessions, breaks, idle detection, and productivity analytics
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from .database import Base


class PomodoroSessionType(str, enum.Enum):
    """Pomodoro session types"""
    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class PomodoroSessionStatus(str, enum.Enum):
    """Session status"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    IDLE = "idle"


class PomodoroSettings(Base):
    """User-specific Pomodoro timer settings"""
    __tablename__ = "pomodoro_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    # Timer durations (in minutes)
    focus_duration = Column(Integer, default=25)
    short_break_duration = Column(Integer, default=5)
    long_break_duration = Column(Integer, default=15)
    sessions_before_long_break = Column(Integer, default=4)
    
    # Auto-start settings
    auto_start_breaks = Column(Boolean, default=False)
    auto_start_focus = Column(Boolean, default=False)
    
    # Idle detection
    idle_detection_enabled = Column(Boolean, default=True)
    idle_threshold_minutes = Column(Integer, default=5)
    
    # Notifications
    sound_enabled = Column(Boolean, default=True)
    notification_enabled = Column(Boolean, default=True)
    
    # Daily goal
    daily_goal_sessions = Column(Integer, default=8)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="pomodoro_settings", uselist=False)


class PomodoroSession(Base):
    """Individual Pomodoro timer session"""
    __tablename__ = "pomodoro_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    
    # Session details
    session_type = Column(SQLEnum(PomodoroSessionType), nullable=False)
    status = Column(SQLEnum(PomodoroSessionStatus), default=PomodoroSessionStatus.ACTIVE)
    
    # Timing
    planned_duration = Column(Integer, nullable=False)  # Minutes
    actual_duration = Column(Integer, nullable=True)  # Minutes (when completed)
    
    start_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    
    # Idle tracking
    idle_time_seconds = Column(Integer, default=0)
    was_interrupted = Column(Boolean, default=False)
    
    # Session tracking
    session_number = Column(Integer, nullable=True)  # Position in sequence (1-4 before long break)
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="pomodoro_sessions")
    task = relationship("Task", backref="pomodoro_sessions")
    idle_periods = relationship("PomodoroIdlePeriod", back_populates="session", cascade="all, delete-orphan")


class PomodoroIdlePeriod(Base):
    """Track idle periods during a session"""
    __tablename__ = "pomodoro_idle_periods"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("pomodoro_sessions.id"), nullable=False)
    
    # Idle period details
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    
    # User action
    resumed_automatically = Column(Boolean, default=False)
    user_dismissed = Column(Boolean, default=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    session = relationship("PomodoroSession", back_populates="idle_periods")


class PomodoroStatistics(Base):
    """Daily/weekly Pomodoro statistics for analytics"""
    __tablename__ = "pomodoro_statistics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Time period
    date = Column(DateTime, nullable=False)  # Date for daily stats
    
    # Session counts
    focus_sessions_completed = Column(Integer, default=0)
    focus_sessions_cancelled = Column(Integer, default=0)
    total_focus_minutes = Column(Integer, default=0)
    
    # Break stats
    short_breaks_taken = Column(Integer, default=0)
    long_breaks_taken = Column(Integer, default=0)
    breaks_skipped = Column(Integer, default=0)
    
    # Productivity metrics
    total_idle_minutes = Column(Integer, default=0)
    interruption_count = Column(Integer, default=0)
    completion_rate = Column(Float, default=0.0)  # Percentage
    
    # Tasks
    tasks_completed = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="pomodoro_statistics")


class PomodoroStreak(Base):
    """Track user's Pomodoro streaks"""
    __tablename__ = "pomodoro_streaks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    # Current streak
    current_streak_days = Column(Integer, default=0)
    current_streak_start = Column(DateTime, nullable=True)
    
    # Best streak
    longest_streak_days = Column(Integer, default=0)
    longest_streak_start = Column(DateTime, nullable=True)
    longest_streak_end = Column(DateTime, nullable=True)
    
    # Last activity
    last_session_date = Column(DateTime, nullable=True)
    
    # Metadata
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="pomodoro_streak", uselist=False)
