"""
Kanban Board Models - Advanced Task Management
Supports drag-drop, custom columns, swimlanes, and card positions
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
)
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base


class KanbanBoard(Base):
    """Kanban board configuration"""
    __tablename__ = "kanban_boards"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Organization
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    list_id = Column(Integer, ForeignKey("task_lists.id"), nullable=True)
    
    # Display settings
    show_subtasks = Column(Boolean, default=True)
    group_by = Column(String(50), default="status")  # status, assignee, priority, custom
    color_by = Column(String(50), default="priority")  # priority, assignee, due_date
    
    # View settings
    card_fields = Column(Text, nullable=True)  # JSON array of fields to show on cards
    is_default = Column(Boolean, default=False)
    
    # Metadata
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    created_by = relationship("User", backref="kanban_boards")
    workspace = relationship("Workspace")
    list = relationship("TaskList")
    columns = relationship("KanbanColumn", back_populates="board", cascade="all, delete-orphan", order_by="KanbanColumn.position")
    swimlanes = relationship("KanbanSwimlane", back_populates="board", cascade="all, delete-orphan")


class KanbanColumn(Base):
    """Kanban board columns (status groups)"""
    __tablename__ = "kanban_columns"

    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey("kanban_boards.id"), nullable=False)
    
    # Column details
    name = Column(String(255), nullable=False)
    color = Column(String(7), nullable=True)  # Hex color
    
    # Status mapping
    status_value = Column(String(50), nullable=True)  # Maps to TaskStatus enum
    
    # Display
    position = Column(Integer, default=0)
    is_collapsed = Column(Boolean, default=False)
    wip_limit = Column(Integer, nullable=True)  # Work-in-progress limit
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    board = relationship("KanbanBoard", back_populates="columns")
    cards = relationship("KanbanCard", back_populates="column", cascade="all, delete-orphan")


class KanbanCard(Base):
    """Task card position on Kanban board"""
    __tablename__ = "kanban_cards"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, unique=True)
    column_id = Column(Integer, ForeignKey("kanban_columns.id"), nullable=False)
    swimlane_id = Column(Integer, ForeignKey("kanban_swimlanes.id"), nullable=True)
    
    # Position in column
    position = Column(Float, default=0.0)  # Use float for easy reordering
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    task = relationship("Task", backref="kanban_card")
    column = relationship("KanbanColumn", back_populates="cards")
    swimlane = relationship("KanbanSwimlane", back_populates="cards")


class KanbanSwimlane(Base):
    """Horizontal swimlanes for grouping tasks"""
    __tablename__ = "kanban_swimlanes"

    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey("kanban_boards.id"), nullable=False)
    
    # Swimlane details
    name = Column(String(255), nullable=False)
    group_value = Column(String(255), nullable=True)  # e.g., user_id for assignee grouping
    
    # Display
    position = Column(Integer, default=0)
    is_collapsed = Column(Boolean, default=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    board = relationship("KanbanBoard", back_populates="swimlanes")
    cards = relationship("KanbanCard", back_populates="swimlane")


class BoardView(Base):
    """Saved board views with filters"""
    __tablename__ = "board_views"

    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey("kanban_boards.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # View details
    name = Column(String(255), nullable=False)
    filters = Column(Text, nullable=True)  # JSON object with filter criteria
    sort_by = Column(String(50), nullable=True)
    is_shared = Column(Boolean, default=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    board = relationship("KanbanBoard")
    user = relationship("User", backref="board_views")
