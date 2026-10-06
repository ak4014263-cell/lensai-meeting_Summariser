"""
Task Templates & Recurring Tasks Models
Supports task templates, recurring task rules, and auto-generation
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
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


class RecurrenceFrequency(str, enum.Enum):
    """Recurrence frequency options"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class TaskTemplate(Base):
    """Reusable task templates"""
    __tablename__ = "task_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Template fields (matches Task model)
    title_template = Column(String(500), nullable=False)
    description_template = Column(Text, nullable=True)
    
    # Default values
    default_priority = Column(String(50), nullable=True)  # urgent, high, normal, low
    default_status = Column(String(50), default="todo")
    default_estimated_hours = Column(Integer, nullable=True)
    default_tags = Column(Text, nullable=True)  # JSON array
    
    # Assignment
    default_assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    list_id = Column(Integer, ForeignKey("task_lists.id"), nullable=True)
    
    # Checklist template
    checklist_template = Column(Text, nullable=True)  # JSON array of checklist items
    
    # Custom fields
    custom_fields_template = Column(Text, nullable=True)  # JSON
    
    # Organization
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    category = Column(String(100), nullable=True)  # e.g., "Development", "Marketing"
    
    # Settings
    is_public = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    
    # Metadata
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Usage stats
    usage_count = Column(Integer, default=0)
    
    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id], backref="task_templates")
    default_assignee = relationship("User", foreign_keys=[default_assignee_id])
    workspace = relationship("Workspace")
    list = relationship("TaskList")
    recurring_rules = relationship("RecurringTaskRule", back_populates="template", cascade="all, delete-orphan")


class RecurringTaskRule(Base):
    """Rules for automatically generating recurring tasks"""
    __tablename__ = "recurring_task_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Template link
    template_id = Column(Integer, ForeignKey("task_templates.id"), nullable=True)
    
    # Recurrence settings
    frequency = Column(SQLEnum(RecurrenceFrequency), nullable=False)
    interval = Column(Integer, default=1)  # Every N days/weeks/months
    
    # Week settings (for weekly recurrence)
    days_of_week = Column(String(50), nullable=True)  # JSON array: [0,1,2,3,4] for Mon-Fri
    
    # Month settings (for monthly recurrence)
    day_of_month = Column(Integer, nullable=True)  # 1-31
    week_of_month = Column(Integer, nullable=True)  # 1-5
    
    # Time settings
    time_of_day = Column(String(10), nullable=True)  # "09:00"
    timezone = Column(String(50), default="UTC")
    
    # Date range
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)
    
    # Generation settings
    advance_creation_days = Column(Integer, default=0)  # Create task N days before due
    
    # Task fields (if not using template)
    task_title = Column(String(500), nullable=True)
    task_description = Column(Text, nullable=True)
    task_priority = Column(String(50), nullable=True)
    task_estimated_hours = Column(Integer, nullable=True)
    task_assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    task_list_id = Column(Integer, ForeignKey("task_lists.id"), nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True)
    is_paused = Column(Boolean, default=False)
    
    # Tracking
    last_generated_at = Column(DateTime, nullable=True)
    next_generation_at = Column(DateTime, nullable=True)
    total_generated = Column(Integer, default=0)
    
    # Metadata
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    template = relationship("TaskTemplate", back_populates="recurring_rules")
    created_by = relationship("User", foreign_keys=[created_by_id], backref="recurring_rules")
    assignee = relationship("User", foreign_keys=[task_assignee_id])
    list = relationship("TaskList")
    generated_tasks = relationship("GeneratedTask", back_populates="rule", cascade="all, delete-orphan")


class GeneratedTask(Base):
    """Track tasks generated from recurring rules"""
    __tablename__ = "generated_tasks"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("recurring_task_rules.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    
    # Generation info
    scheduled_for = Column(DateTime, nullable=False)  # When it was scheduled
    generated_at = Column(DateTime, default=datetime.utcnow)
    
    # Status tracking
    was_completed = Column(Boolean, default=False)
    was_skipped = Column(Boolean, default=False)
    completion_date = Column(DateTime, nullable=True)
    
    # Relationships
    rule = relationship("RecurringTaskRule", back_populates="generated_tasks")
    task = relationship("Task", backref="generation_info")


class TemplateCategory(Base):
    """Categorize templates for better organization"""
    __tablename__ = "template_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)
    color = Column(String(7), nullable=True)
    
    # Organization
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    parent_category_id = Column(Integer, ForeignKey("template_categories.id"), nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    workspace = relationship("Workspace")
    parent_category = relationship("TemplateCategory", remote_side=[id], backref="subcategories")


class TemplateUsageLog(Base):
    """Track template usage for analytics"""
    __tablename__ = "template_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("task_templates.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    
    used_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    template = relationship("TaskTemplate")
    user = relationship("User")
    task = relationship("Task")
