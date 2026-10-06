"""
Task Management Models (LensAI-inspired)
Separate file to keep models organized
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


class TaskStatus(str, enum.Enum):
    """Task status options"""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    """Task priority levels"""
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Task(Base):
    """Main task model - inspired by LensAI tasks"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    
    # Status and priority
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.TODO, nullable=False)
    priority = Column(SQLEnum(TaskPriority), default=TaskPriority.NORMAL, nullable=False)
    
    # Assignment
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Dates
    due_date = Column(DateTime, nullable=True)
    start_date = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Time tracking
    estimated_hours = Column(Float, nullable=True)
    actual_hours = Column(Float, nullable=True, default=0.0)
    
    # Hierarchy
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    list_id = Column(Integer, ForeignKey("task_lists.id"), nullable=True)
    
    # Integration with meetings
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=True)
    action_item_id = Column(Integer, ForeignKey("action_items.id"), nullable=True)
    
    # Metadata
    tags = Column(Text, nullable=True)  # JSON array of tags
    custom_fields = Column(Text, nullable=True)  # JSON for custom fields
    
    # Relationships
    assignee = relationship("User", foreign_keys=[assignee_id], backref="assigned_tasks")
    created_by = relationship("User", foreign_keys=[created_by_id], backref="created_tasks")
    parent_task = relationship("Task", remote_side=[id], backref="subtasks")
    meeting = relationship("Meeting", backref="tasks")
    action_item = relationship("ActionItem", backref="task", uselist=False)
    list = relationship("TaskList", back_populates="tasks")
    
    comments = relationship("TaskComment", back_populates="task", cascade="all, delete-orphan")
    attachments = relationship("TaskAttachment", back_populates="task", cascade="all, delete-orphan")
    checklists = relationship("TaskChecklist", back_populates="task", cascade="all, delete-orphan")
    time_entries = relationship("TimeEntry", back_populates="task", cascade="all, delete-orphan")
    dependencies = relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.task_id",
        back_populates="task",
        cascade="all, delete-orphan"
    )


class TaskList(Base):
    """Task lists/workflows - like LensAI lists"""
    __tablename__ = "task_lists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(7), nullable=True)  # Hex color
    icon = Column(String(50), nullable=True)  # Emoji or icon name
    
    # Organization
    folder_id = Column(Integer, ForeignKey("task_folders.id"), nullable=True)
    position = Column(Integer, default=0)
    
    # Settings
    is_archived = Column(Boolean, default=False)
    is_template = Column(Boolean, default=False)
    
    # Ownership
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    created_by = relationship("User", backref="task_lists")
    folder = relationship("TaskFolder", back_populates="lists")
    tasks = relationship("Task", back_populates="list", cascade="all, delete-orphan")


class TaskFolder(Base):
    """Folders to organize lists - like LensAI folders"""
    __tablename__ = "task_folders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(7), nullable=True)
    
    # Organization
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    position = Column(Integer, default=0)
    
    # Settings
    is_archived = Column(Boolean, default=False)
    
    # Ownership
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    created_by = relationship("User", backref="task_folders")
    workspace = relationship("Workspace", back_populates="folders")
    lists = relationship("TaskList", back_populates="folder", cascade="all, delete-orphan")


class Workspace(Base):
    """Workspace - top-level organization"""
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Settings
    is_personal = Column(Boolean, default=False)
    
    # Ownership
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    owner = relationship("User", backref="owned_workspaces")
    folders = relationship("TaskFolder", back_populates="workspace", cascade="all, delete-orphan")
    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    # Phase 2: Documents
    documents = relationship("Document", back_populates="workspace")
    doc_folders = relationship("DocFolder", back_populates="workspace")
    # Phase 3: Chat
    chat_channels = relationship("Channel", back_populates="workspace")
    # Phase 4: Goals
    goals = relationship("Goal", back_populates="workspace")


class WorkspaceMember(Base):
    """Workspace membership and permissions"""
    __tablename__ = "workspace_members"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(50), default="member")  # owner, admin, member, guest
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", backref="workspace_memberships")


class TaskComment(Base):
    """Comments on tasks"""
    __tablename__ = "task_comments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    
    # Threading
    parent_comment_id = Column(Integer, ForeignKey("task_comments.id"), nullable=True)
    
    # Assignment (for assigned comments)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_resolved = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    task = relationship("Task", back_populates="comments")
    user = relationship("User", foreign_keys=[user_id], backref="task_comments")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id], backref="assigned_comments")
    parent_comment = relationship("TaskComment", remote_side=[id], backref="replies")


class TaskAttachment(Base):
    """File attachments on tasks"""
    __tablename__ = "task_attachments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)  # bytes
    file_type = Column(String(100), nullable=True)  # MIME type
    
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    task = relationship("Task", back_populates="attachments")
    user = relationship("User", backref="task_attachments")


class TaskChecklist(Base):
    """Checklists within tasks"""
    __tablename__ = "task_checklists"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    title = Column(String(255), nullable=False)
    position = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    task = relationship("Task", back_populates="checklists")
    items = relationship("ChecklistItem", back_populates="checklist", cascade="all, delete-orphan")


class ChecklistItem(Base):
    """Individual items in a checklist"""
    __tablename__ = "checklist_items"

    id = Column(Integer, primary_key=True, index=True)
    checklist_id = Column(Integer, ForeignKey("task_checklists.id"), nullable=False)
    content = Column(String(500), nullable=False)
    is_completed = Column(Boolean, default=False)
    position = Column(Integer, default=0)
    
    # Assignment
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    checklist = relationship("TaskChecklist", back_populates="items")
    assigned_to = relationship("User", backref="checklist_items")


class TaskDependency(Base):
    """Task dependencies (blocking relationships)"""
    __tablename__ = "task_dependencies"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    depends_on_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    dependency_type = Column(String(50), default="blocks")  # blocks, blocked_by
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    task = relationship("Task", foreign_keys=[task_id], back_populates="dependencies")
    depends_on_task = relationship("Task", foreign_keys=[depends_on_task_id])


class TimeEntry(Base):
    """Time tracking entries"""
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=True)
    
    description = Column(Text, nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    
    is_billable = Column(Boolean, default=False)
    hourly_rate = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="time_entries")
    task = relationship("Task", back_populates="time_entries")
    meeting = relationship("Meeting", backref="time_entries")

