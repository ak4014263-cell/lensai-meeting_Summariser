"""
Kanban Board API Routes - Advanced Task Management
Supports board creation, column management, card positioning, drag-drop
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_kanban import KanbanBoard, KanbanColumn, KanbanCard, KanbanSwimlane, BoardView
from ..models_tasks import Task, TaskStatus, Workspace


router = APIRouter(prefix="/kanban", tags=["kanban"])


# ─────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────

class KanbanBoardCreate(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_id: int
    list_id: Optional[int] = None
    show_subtasks: bool = True
    group_by: str = "status"
    color_by: str = "priority"
    card_fields: Optional[str] = None


class KanbanBoardUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    show_subtasks: Optional[bool] = None
    group_by: Optional[str] = None
    color_by: Optional[str] = None
    card_fields: Optional[str] = None
    is_default: Optional[bool] = None


class KanbanBoardResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    workspace_id: int
    list_id: Optional[int]
    show_subtasks: bool
    group_by: str
    color_by: str
    card_fields: Optional[str]
    is_default: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class KanbanColumnCreate(BaseModel):
    board_id: int
    name: str
    color: Optional[str] = None
    status_value: Optional[str] = None
    position: int = 0
    wip_limit: Optional[int] = None


class KanbanColumnUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    position: Optional[int] = None
    is_collapsed: Optional[bool] = None
    wip_limit: Optional[int] = None


class KanbanColumnResponse(BaseModel):
    id: int
    board_id: int
    name: str
    color: Optional[str]
    status_value: Optional[str]
    position: int
    is_collapsed: bool
    wip_limit: Optional[int]
    
    class Config:
        from_attributes = True


class KanbanCardCreate(BaseModel):
    task_id: int
    column_id: int
    swimlane_id: Optional[int] = None
    position: float = 0.0


class KanbanCardMove(BaseModel):
    column_id: int
    swimlane_id: Optional[int] = None
    position: float


class KanbanCardResponse(BaseModel):
    id: int
    task_id: int
    column_id: int
    swimlane_id: Optional[int]
    position: float
    
    class Config:
        from_attributes = True


class KanbanSwimlaneCreate(BaseModel):
    board_id: int
    name: str
    group_value: Optional[str] = None
    position: int = 0


class KanbanSwimlaneResponse(BaseModel):
    id: int
    board_id: int
    name: str
    group_value: Optional[str]
    position: int
    is_collapsed: bool
    
    class Config:
        from_attributes = True


class BoardViewCreate(BaseModel):
    board_id: int
    name: str
    filters: Optional[str] = None
    sort_by: Optional[str] = None
    is_shared: bool = False


class BoardViewResponse(BaseModel):
    id: int
    board_id: int
    user_id: int
    name: str
    filters: Optional[str]
    sort_by: Optional[str]
    is_shared: bool
    
    class Config:
        from_attributes = True


class TaskWithCardInfo(BaseModel):
    """Task with Kanban card positioning info"""
    id: int
    title: str
    description: Optional[str]
    status: str
    priority: str
    assignee_id: Optional[int]
    due_date: Optional[datetime]
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    tags: Optional[str]
    card_id: int
    card_position: float
    column_id: int
    swimlane_id: Optional[int]
    
    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# Board Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/boards", response_model=KanbanBoardResponse, status_code=status.HTTP_201_CREATED)
def create_kanban_board(
    board_data: KanbanBoardCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new Kanban board"""
    # Verify workspace access or auto-provision default workspace
    workspace = None
    if board_data.workspace_id:
        workspace = db.query(Workspace).filter(Workspace.id == board_data.workspace_id).first()
    
    if not workspace:
        workspace = db.query(Workspace).filter(Workspace.owner_id == current_user.id).first()
    if not workspace:
        workspace = db.query(Workspace).first()
    if not workspace:
        workspace = Workspace(
            name="Main Workspace",
            description="Default Workspace",
            owner_id=current_user.id,
            is_personal=True
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
    
    board_dict = board_data.dict()
    board_dict["workspace_id"] = workspace.id

    new_board = KanbanBoard(
        **board_dict,
        created_by_id=current_user.id
    )
    db.add(new_board)
    db.commit()
    db.refresh(new_board)
    
    # Create default columns if none exist
    if board_data.group_by == "status":
        default_columns = [
            {"name": "To Do", "status_value": "todo", "position": 0, "color": "#cccccc"},
            {"name": "In Progress", "status_value": "in_progress", "position": 1, "color": "#4a90e2"},
            {"name": "In Review", "status_value": "in_review", "position": 2, "color": "#f5a623"},
            {"name": "Completed", "status_value": "completed", "position": 3, "color": "#7ed321"},
        ]
        for col_data in default_columns:
            column = KanbanColumn(board_id=new_board.id, **col_data)
            db.add(column)
        db.commit()
    
    return new_board


@router.get("/boards", response_model=List[KanbanBoardResponse])
def list_kanban_boards(
    workspace_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all Kanban boards (optionally filtered by workspace)"""
    query = db.query(KanbanBoard)
    
    if workspace_id:
        query = query.filter(KanbanBoard.workspace_id == workspace_id)
    
    boards = query.order_by(KanbanBoard.created_at.desc()).all()
    return boards


@router.get("/boards/{board_id}", response_model=KanbanBoardResponse)
def get_kanban_board(
    board_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific Kanban board"""
    board = db.query(KanbanBoard).filter(KanbanBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


@router.patch("/boards/{board_id}", response_model=KanbanBoardResponse)
def update_kanban_board(
    board_id: int,
    board_data: KanbanBoardUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a Kanban board"""
    board = db.query(KanbanBoard).filter(KanbanBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    for key, value in board_data.dict(exclude_unset=True).items():
        setattr(board, key, value)
    
    db.commit()
    db.refresh(board)
    return board


@router.delete("/boards/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kanban_board(
    board_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a Kanban board"""
    board = db.query(KanbanBoard).filter(KanbanBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    db.delete(board)
    db.commit()
    return None


# ─────────────────────────────────────────────────────────────
# Column Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/columns", response_model=KanbanColumnResponse, status_code=status.HTTP_201_CREATED)
def create_column(
    column_data: KanbanColumnCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new board column"""
    # Verify board exists
    board = db.query(KanbanBoard).filter(KanbanBoard.id == column_data.board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    new_column = KanbanColumn(**column_data.dict())
    db.add(new_column)
    db.commit()
    db.refresh(new_column)
    return new_column


@router.get("/boards/{board_id}/columns", response_model=List[KanbanColumnResponse])
def list_board_columns(
    board_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all columns for a board"""
    columns = db.query(KanbanColumn).filter(
        KanbanColumn.board_id == board_id
    ).order_by(KanbanColumn.position).all()
    return columns


@router.patch("/columns/{column_id}", response_model=KanbanColumnResponse)
def update_column(
    column_id: int,
    column_data: KanbanColumnUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a board column"""
    column = db.query(KanbanColumn).filter(KanbanColumn.id == column_id).first()
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")
    
    for key, value in column_data.dict(exclude_unset=True).items():
        setattr(column, key, value)
    
    db.commit()
    db.refresh(column)
    return column


@router.delete("/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_column(
    column_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a board column"""
    column = db.query(KanbanColumn).filter(KanbanColumn.id == column_id).first()
    if not column:
        raise HTTPException(status_code=404, detail="Column not found")
    
    db.delete(column)
    db.commit()
    return None


# ─────────────────────────────────────────────────────────────
# Card Endpoints (Drag & Drop)
# ─────────────────────────────────────────────────────────────

@router.post("/cards", response_model=KanbanCardResponse, status_code=status.HTTP_201_CREATED)
def create_card(
    card_data: KanbanCardCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a task to the Kanban board"""
    # Verify task exists
    task = db.query(Task).filter(Task.id == card_data.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Check if card already exists
    existing_card = db.query(KanbanCard).filter(KanbanCard.task_id == card_data.task_id).first()
    if existing_card:
        raise HTTPException(status_code=400, detail="Task already on a Kanban board")
    
    new_card = KanbanCard(**card_data.dict())
    db.add(new_card)
    db.commit()
    db.refresh(new_card)
    return new_card


@router.get("/boards/{board_id}/cards")
def list_board_cards(
    board_id: int,
    column_id: Optional[int] = None,
    swimlane_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all cards on a board with task details"""
    # Get board to verify it exists
    board = db.query(KanbanBoard).filter(KanbanBoard.id == board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    # Query cards with task details
    query = db.query(
        Task.id,
        Task.title,
        Task.description,
        Task.status,
        Task.priority,
        Task.assignee_id,
        Task.due_date,
        Task.estimated_hours,
        Task.actual_hours,
        Task.tags,
        KanbanCard.id.label("card_id"),
        KanbanCard.position.label("card_position"),
        KanbanCard.column_id,
        KanbanCard.swimlane_id
    ).join(
        KanbanCard, Task.id == KanbanCard.task_id
    ).join(
        KanbanColumn, KanbanCard.column_id == KanbanColumn.id
    ).filter(
        KanbanColumn.board_id == board_id
    )
    
    if column_id:
        query = query.filter(KanbanCard.column_id == column_id)
    
    if swimlane_id:
        query = query.filter(KanbanCard.swimlane_id == swimlane_id)
    
    cards = query.order_by(KanbanCard.column_id, KanbanCard.position).all()
    
    # Convert to response format
    result = []
    for card in cards:
        result.append({
            "id": card.id,
            "title": card.title,
            "description": card.description,
            "status": card.status.value if card.status else None,
            "priority": card.priority.value if card.priority else None,
            "assignee_id": card.assignee_id,
            "due_date": card.due_date,
            "estimated_hours": card.estimated_hours,
            "actual_hours": card.actual_hours,
            "tags": card.tags,
            "card_id": card.card_id,
            "card_position": card.card_position,
            "column_id": card.column_id,
            "swimlane_id": card.swimlane_id
        })
    
    return result


@router.patch("/cards/{card_id}/move", response_model=KanbanCardResponse)
def move_card(
    card_id: int,
    move_data: KanbanCardMove,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Move a card (drag & drop operation)"""
    card = db.query(KanbanCard).filter(KanbanCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    # Update card position
    card.column_id = move_data.column_id
    card.swimlane_id = move_data.swimlane_id
    card.position = move_data.position
    card.updated_at = datetime.utcnow()
    
    # Update task status based on column
    column = db.query(KanbanColumn).filter(KanbanColumn.id == move_data.column_id).first()
    if column and column.status_value:
        task = db.query(Task).filter(Task.id == card.task_id).first()
        if task:
            try:
                task.status = TaskStatus(column.status_value)
                if column.status_value == "completed":
                    task.completed_at = datetime.utcnow()
            except ValueError:
                pass  # Invalid status value, skip update
    
    db.commit()
    db.refresh(card)
    return card


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(
    card_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a card from the board (doesn't delete the task)"""
    card = db.query(KanbanCard).filter(KanbanCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    
    db.delete(card)
    db.commit()
    return None


# ─────────────────────────────────────────────────────────────
# Swimlane Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/swimlanes", response_model=KanbanSwimlaneResponse, status_code=status.HTTP_201_CREATED)
def create_swimlane(
    swimlane_data: KanbanSwimlaneCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new swimlane"""
    board = db.query(KanbanBoard).filter(KanbanBoard.id == swimlane_data.board_id).first()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    
    new_swimlane = KanbanSwimlane(**swimlane_data.dict())
    db.add(new_swimlane)
    db.commit()
    db.refresh(new_swimlane)
    return new_swimlane


@router.get("/boards/{board_id}/swimlanes", response_model=List[KanbanSwimlaneResponse])
def list_board_swimlanes(
    board_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all swimlanes for a board"""
    swimlanes = db.query(KanbanSwimlane).filter(
        KanbanSwimlane.board_id == board_id
    ).order_by(KanbanSwimlane.position).all()
    return swimlanes


# ─────────────────────────────────────────────────────────────
# Board View Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/views", response_model=BoardViewResponse, status_code=status.HTTP_201_CREATED)
def create_board_view(
    view_data: BoardViewCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Save a custom board view"""
    new_view = BoardView(
        **view_data.dict(),
        user_id=current_user.id
    )
    db.add(new_view)
    db.commit()
    db.refresh(new_view)
    return new_view


@router.get("/boards/{board_id}/views", response_model=List[BoardViewResponse])
def list_board_views(
    board_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List saved views for a board"""
    views = db.query(BoardView).filter(
        BoardView.board_id == board_id,
        (BoardView.user_id == current_user.id) | (BoardView.is_shared == True)
    ).all()
    return views
