"""
Goals & Dashboards System Models (Phase 4)
OKR-style goal tracking with custom dashboards
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base
import enum


class GoalStatus(str, enum.Enum):
    """Goal status"""
    NOT_STARTED = "not_started"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OFF_TRACK = "off_track"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class GoalPeriod(str, enum.Enum):
    """Goal time periods"""
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class WidgetType(str, enum.Enum):
    """Dashboard widget types"""
    TASKS_SUMMARY = "tasks_summary"
    GOALS_PROGRESS = "goals_progress"
    TIME_TRACKING = "time_tracking"
    MEETINGS_CALENDAR = "meetings_calendar"
    CHAT_ACTIVITY = "chat_activity"
    DOCUMENT_LIST = "document_list"
    CUSTOM_CHART = "custom_chart"


class Goal(Base):
    """Goals (OKR-style objectives) with hierarchy support"""
    __tablename__ = "goals"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    
    status = Column(SQLEnum(GoalStatus), default=GoalStatus.NOT_STARTED)
    
    # Hierarchy support
    parent_goal_id = Column(Integer, ForeignKey("goals.id"), nullable=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    
    # Assignment
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Progress tracking
    target_value = Column(Float, nullable=True)  # Target number (e.g., 100 for 100%)
    current_value = Column(Float, default=0)  # Current progress
    unit = Column(String(50), nullable=True)  # "percent", "count", "currency", etc.
    
    # Time period
    period = Column(SQLEnum(GoalPeriod), default=GoalPeriod.QUARTERLY)
    start_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    
    # Metadata
    color = Column(String(20), default="#3B82F6")
    icon = Column(String(100), nullable=True)
    is_archived = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    workspace = relationship("Workspace", back_populates="goals")
    key_results = relationship("KeyResult", back_populates="goal", cascade="all, delete-orphan")
    child_goals = relationship("Goal", backref="parent_goal", remote_side=[id])
    updates = relationship("GoalUpdate", back_populates="goal", cascade="all, delete-orphan")


class KeyResult(Base):
    """Key Results for goals (OKR)"""
    __tablename__ = "key_results"
    
    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False)
    
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    
    # Progress
    target_value = Column(Float, nullable=False)
    current_value = Column(Float, default=0)
    unit = Column(String(50), nullable=True)
    
    status = Column(SQLEnum(GoalStatus), default=GoalStatus.NOT_STARTED)
    
    # Assignment
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Task linkage
    linked_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    goal = relationship("Goal", back_populates="key_results")
    owner = relationship("User")


class GoalUpdate(Base):
    """Progress updates for goals"""
    __tablename__ = "goal_updates"
    
    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    content = Column(Text, nullable=False)
    previous_value = Column(Float, nullable=True)
    new_value = Column(Float, nullable=True)
    
    status_change = Column(String(100), nullable=True)  # "on_track -> at_risk"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    goal = relationship("Goal", back_populates="updates")
    user = relationship("User")


class Dashboard(Base):
    """Custom dashboards"""
    __tablename__ = "dashboards"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    is_default = Column(Boolean, default=False)
    is_public = Column(Boolean, default=False)
    
    # Layout configuration (JSON)
    layout_config = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    owner = relationship("User")
    workspace = relationship("Workspace")
    widgets = relationship("DashboardWidget", back_populates="dashboard", cascade="all, delete-orphan")


class DashboardWidget(Base):
    """Dashboard widgets"""
    __tablename__ = "dashboard_widgets"
    
    id = Column(Integer, primary_key=True, index=True)
    dashboard_id = Column(Integer, ForeignKey("dashboards.id"), nullable=False)
    
    widget_type = Column(SQLEnum(WidgetType), nullable=False)
    
    title = Column(String(255), nullable=True)
    
    # Position and size
    position_x = Column(Integer, default=0)
    position_y = Column(Integer, default=0)
    width = Column(Integer, default=4)  # Grid units
    height = Column(Integer, default=3)
    
    # Widget-specific config (JSON)
    config = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    dashboard = relationship("Dashboard", back_populates="widgets")


class Milestone(Base):
    """Project milestones"""
    __tablename__ = "milestones"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=True)
    
    due_date = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    is_completed = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    workspace = relationship("Workspace")
    goal = relationship("Goal")
