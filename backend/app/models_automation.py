"""
Automation Workflows Models
Supports workflow automation with triggers, conditions, and actions
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


class TriggerType(str, enum.Enum):
    """Automation trigger types"""
    MEETING_COMPLETED = "meeting_completed"
    MEETING_STARTED = "meeting_started"
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    TASK_STATUS_CHANGED = "task_status_changed"
    TASK_OVERDUE = "task_overdue"
    GOAL_CREATED = "goal_created"
    GOAL_COMPLETED = "goal_completed"
    GOAL_AT_RISK = "goal_at_risk"
    TIME_ENTRY_CREATED = "time_entry_created"
    POMODORO_COMPLETED = "pomodoro_completed"
    DOCUMENT_CREATED = "document_created"
    SCHEDULED = "scheduled"  # Time-based trigger


class ActionType(str, enum.Enum):
    """Automation action types"""
    CREATE_TASK = "create_task"
    UPDATE_TASK = "update_task"
    ASSIGN_TASK = "assign_task"
    CREATE_GOAL = "create_goal"
    UPDATE_GOAL = "update_goal"
    SEND_NOTIFICATION = "send_notification"
    SEND_EMAIL = "send_email"
    CREATE_DOCUMENT = "create_document"
    ADD_COMMENT = "add_comment"
    CREATE_TIME_ENTRY = "create_time_entry"
    WEBHOOK = "webhook"


class WorkflowStatus(str, enum.Enum):
    """Workflow status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"


class AutomationWorkflow(Base):
    """Automation workflow definition"""
    __tablename__ = "automation_workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Trigger configuration
    trigger_type = Column(SQLEnum(TriggerType), nullable=False)
    trigger_config = Column(Text, nullable=True)  # JSON config for trigger
    
    # Conditions (optional filters)
    conditions = Column(Text, nullable=True)  # JSON array of conditions
    
    # Status
    status = Column(SQLEnum(WorkflowStatus), default=WorkflowStatus.ACTIVE)
    
    # Organization
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=True)
    
    # Execution settings
    delay_seconds = Column(Integer, default=0)  # Delay before executing
    max_executions = Column(Integer, nullable=True)  # Limit number of executions
    execution_count = Column(Integer, default=0)
    
    # Schedule (for scheduled triggers)
    schedule_cron = Column(String(100), nullable=True)  # Cron expression
    
    # Metadata
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_executed_at = Column(DateTime, nullable=True)
    
    # Relationships
    created_by = relationship("User", backref="automation_workflows")
    workspace = relationship("Workspace")
    actions = relationship("WorkflowAction", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowAction.order")
    executions = relationship("WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowAction(Base):
    """Action to perform when workflow is triggered"""
    __tablename__ = "workflow_actions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("automation_workflows.id"), nullable=False)
    
    # Action configuration
    action_type = Column(SQLEnum(ActionType), nullable=False)
    action_config = Column(Text, nullable=False)  # JSON configuration
    
    # Execution order
    order = Column(Integer, default=0)
    
    # Conditional execution
    run_condition = Column(Text, nullable=True)  # JSON condition for this action
    
    # Error handling
    continue_on_error = Column(Boolean, default=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    workflow = relationship("AutomationWorkflow", back_populates="actions")


class WorkflowExecution(Base):
    """Log of workflow executions"""
    __tablename__ = "workflow_executions"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("automation_workflows.id"), nullable=False)
    
    # Execution details
    trigger_data = Column(Text, nullable=True)  # JSON data that triggered workflow
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Status
    status = Column(String(50), default="running")  # running, completed, failed, cancelled
    error_message = Column(Text, nullable=True)
    
    # Results
    actions_executed = Column(Integer, default=0)
    actions_failed = Column(Integer, default=0)
    results = Column(Text, nullable=True)  # JSON results from actions
    
    # Relationships
    workflow = relationship("AutomationWorkflow", back_populates="executions")
    action_results = relationship("ActionExecutionResult", back_populates="execution", cascade="all, delete-orphan")


class ActionExecutionResult(Base):
    """Result of individual action execution"""
    __tablename__ = "action_execution_results"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("workflow_executions.id"), nullable=False)
    action_id = Column(Integer, ForeignKey("workflow_actions.id"), nullable=False)
    
    # Execution details
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Status
    status = Column(String(50), default="running")  # running, success, failed, skipped
    error_message = Column(Text, nullable=True)
    
    # Result data
    result_data = Column(Text, nullable=True)  # JSON result from action
    
    # Relationships
    execution = relationship("WorkflowExecution", back_populates="action_results")
    action = relationship("WorkflowAction")


class IntegrationMapping(Base):
    """Map external entities to internal entities for automation"""
    __tablename__ = "integration_mappings"

    id = Column(Integer, primary_key=True, index=True)
    
    # Source (e.g., meeting action item)
    source_type = Column(String(100), nullable=False)  # "meeting", "action_item", etc.
    source_id = Column(Integer, nullable=False)
    
    # Target (e.g., task, goal)
    target_type = Column(String(100), nullable=False)  # "task", "goal", etc.
    target_id = Column(Integer, nullable=False)
    
    # Mapping metadata
    mapping_type = Column(String(100), nullable=False)  # "auto_created", "manual_link"
    workflow_id = Column(Integer, ForeignKey("automation_workflows.id"), nullable=True)
    
    # Sync settings
    sync_enabled = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relationships
    workflow = relationship("AutomationWorkflow")
    created_by = relationship("User")
