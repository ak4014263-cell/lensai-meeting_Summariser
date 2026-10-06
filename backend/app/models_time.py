"""
Enhanced Time Tracking Models (Phase 5)
Comprehensive time tracking with reports and analytics
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base
import enum


class TimeEntryType(str, enum.Enum):
    """Time entry types"""
    MANUAL = "manual"
    TIMER = "timer"
    AUTO = "auto"  # Auto-tracked


class BillableStatus(str, enum.Enum):
    """Billable status"""
    BILLABLE = "billable"
    NON_BILLABLE = "non_billable"
    INVOICED = "invoiced"


class TimeEntryEnhanced(Base):
    """Enhanced time entries (extends the one from tasks)"""
    __tablename__ = "time_entries_enhanced"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # User and workspace
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    
    # What was worked on
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    project_id = Column(Integer, nullable=True)  # Future: project tracking
    
    # Time details
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration = Column(Integer, nullable=True)  # Duration in seconds
    
    # Description
    description = Column(Text, nullable=True)
    
    # Type and billing
    entry_type = Column(SQLEnum(TimeEntryType), default=TimeEntryType.MANUAL)
    billable_status = Column(SQLEnum(BillableStatus), default=BillableStatus.NON_BILLABLE)
    hourly_rate = Column(Float, nullable=True)
    
    # Tags for categorization
    tags = Column(Text, nullable=True)  # JSON array
    
    # Auto-tracking metadata
    is_running = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User")
    workspace = relationship("Workspace")


class TimeReport(Base):
    """Saved time reports"""
    __tablename__ = "time_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    
    # Report configuration (JSON)
    config = Column(Text, nullable=True)  # Filters, grouping, etc.
    
    # Time range
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    
    # Schedule for recurring reports
    is_scheduled = Column(Boolean, default=False)
    schedule_frequency = Column(String(50), nullable=True)  # "weekly", "monthly"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User")
    workspace = relationship("Workspace")


class ProductivityMetric(Base):
    """Daily productivity metrics"""
    __tablename__ = "productivity_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    date = Column(DateTime, nullable=False, index=True)
    
    # Metrics
    total_time_logged = Column(Integer, default=0)  # Seconds
    tasks_completed = Column(Integer, default=0)
    meetings_attended = Column(Integer, default=0)
    messages_sent = Column(Integer, default=0)
    documents_created = Column(Integer, default=0)
    
    # Focus score (0-100)
    focus_score = Column(Float, default=0)
    
    # Goals progress
    goals_updated = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User")


class WorkBreak(Base):
    """Track work breaks"""
    __tablename__ = "work_breaks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration = Column(Integer, nullable=True)  # Seconds
    
    break_type = Column(String(50), default="break")  # "break", "lunch", "meeting"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User")


class TimeGoal(Base):
    """Weekly/monthly time goals"""
    __tablename__ = "time_goals"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    
    title = Column(String(255), nullable=False)
    target_hours = Column(Float, nullable=False)
    
    # Time period
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    
    # Filters (what time counts toward this goal)
    task_filter = Column(Text, nullable=True)  # JSON
    
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User")
    workspace = relationship("Workspace")
