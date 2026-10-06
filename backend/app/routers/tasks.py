"""
Task Management API Routes (ClickUp-inspired)
Full CRUD operations for tasks, lists, folders, and workspaces
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_tasks import (
    Task, TaskList, TaskFolder, Workspace, TaskComment,
    TaskAttachment, TaskChecklist, ChecklistItem,
    TaskDependency, TimeEntry, WorkspaceMember,
    TaskStatus, TaskPriority
)
from pydantic import BaseModel


router = APIRouter(prefix="/tasks", tags=["tasks"])


# ─────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.NORMAL
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    estimated_hours: Optional[float] = None
    parent_task_id: Optional[int] = None
    list_id: Optional[int] = None
    meeting_id: Optional[int] = None
    tags: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None
    start_date: Optional[datetime] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    tags: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    status: str
    priority: str
    assignee_id: Optional[int]
    created_by_id: int
    due_date: Optional[datetime]
    start_date: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    parent_task_id: Optional[int]
    list_id: Optional[int]
    meeting_id: Optional[int]
    tags: Optional[str]
    
    class Config:
        from_attributes = True


class CommentCreate(BaseModel):
    content: str
    parent_comment_id: Optional[int] = None
    assigned_to_id: Optional[int] = None


class CommentResponse(BaseModel):
    id: int
    task_id: int
    user_id: int
    content: str
    parent_comment_id: Optional[int]
    assigned_to_id: Optional[int]
    is_resolved: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class ChecklistCreate(BaseModel):
    title: str
    items: List[str] = []


class ChecklistResponse(BaseModel):
    id: int
    task_id: int
    title: str
    position: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_personal: bool = False


class WorkspaceResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_personal: bool
    owner_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class ListCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    folder_id: Optional[int] = None


class ListResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    color: Optional[str]
    icon: Optional[str]
    folder_id: Optional[int]
    position: int
    is_archived: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────
# Workspace Routes
# ─────────────────────────────────────────────────────────────

@router.post("/workspaces", response_model=WorkspaceResponse)
def create_workspace(
    workspace: WorkspaceCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new workspace"""
    new_workspace = Workspace(
        name=workspace.name,
        description=workspace.description,
        is_personal=workspace.is_personal,
        owner_id=current_user.id
    )
    db.add(new_workspace)
    db.commit()
    db.refresh(new_workspace)
    
    # Add creator as admin member
    member = WorkspaceMember(
        workspace_id=new_workspace.id,
        user_id=current_user.id,
        role="owner"
    )
    db.add(member)
    db.commit()
    
    return new_workspace


@router.get("/workspaces", response_model=List[WorkspaceResponse])
def list_workspaces(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all workspaces user has access to"""
    workspaces = db.query(Workspace).join(WorkspaceMember).filter(
        WorkspaceMember.user_id == current_user.id
    ).all()
    return workspaces


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get workspace details"""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    # Check access
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == current_user.id
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return workspace


# ─────────────────────────────────────────────────────────────
# Task List Routes
# ─────────────────────────────────────────────────────────────

@router.post("/lists", response_model=ListResponse)
def create_list(
    list_data: ListCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new task list"""
    new_list = TaskList(
        name=list_data.name,
        description=list_data.description,
        color=list_data.color,
        icon=list_data.icon,
        folder_id=list_data.folder_id,
        created_by_id=current_user.id
    )
    db.add(new_list)
    db.commit()
    db.refresh(new_list)
    return new_list


@router.get("/lists", response_model=List[ListResponse])
def list_task_lists(
    folder_id: Optional[int] = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all task lists"""
    query = db.query(TaskList).filter(TaskList.is_archived == False)
    if folder_id:
        query = query.filter(TaskList.folder_id == folder_id)
    
    lists = query.order_by(TaskList.position).all()
    return lists


# ─────────────────────────────────────────────────────────────
# Task Routes
# ─────────────────────────────────────────────────────────────

@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    task: TaskCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new task"""
    new_task = Task(
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        assignee_id=task.assignee_id,
        created_by_id=current_user.id,
        due_date=task.due_date,
        start_date=task.start_date,
        estimated_hours=task.estimated_hours,
        parent_task_id=task.parent_task_id,
        list_id=task.list_id,
        meeting_id=task.meeting_id,
        tags=task.tags
    )
    
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return new_task


@router.get("", response_model=List[TaskResponse])
@router.get("/", response_model=List[TaskResponse])
def list_tasks(
    status: Optional[TaskStatus] = Query(None),
    priority: Optional[TaskPriority] = Query(None),
    assignee_id: Optional[int] = Query(None),
    list_id: Optional[int] = Query(None),
    meeting_id: Optional[int] = Query(None),
    parent_task_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List tasks with filtering"""
    query = db.query(Task)
    
    # Apply filters
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if list_id:
        query = query.filter(Task.list_id == list_id)
    if meeting_id:
        query = query.filter(Task.meeting_id == meeting_id)
    if parent_task_id:
        query = query.filter(Task.parent_task_id == parent_task_id)
    if search:
        query = query.filter(
            (Task.title.ilike(f"%{search}%")) | 
            (Task.description.ilike(f"%{search}%"))
        )
    
    tasks = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return tasks


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific task"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    task_update: TaskUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a task"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Update fields
    update_data = task_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)
    
    # Auto-set completed_at when status changes to completed
    if task_update.status == TaskStatus.COMPLETED and not task.completed_at:
        task.completed_at = datetime.utcnow()
    
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a task"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    db.delete(task)
    db.commit()
    return None


# ─────────────────────────────────────────────────────────────
# Task Comments Routes
# ─────────────────────────────────────────────────────────────

@router.post("/{task_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def create_comment(
    task_id: int,
    comment: CommentCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a comment to a task"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    new_comment = TaskComment(
        task_id=task_id,
        user_id=current_user.id,
        content=comment.content,
        parent_comment_id=comment.parent_comment_id,
        assigned_to_id=comment.assigned_to_id
    )
    
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)
    return new_comment


@router.get("/{task_id}/comments", response_model=List[CommentResponse])
def list_comments(
    task_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all comments for a task"""
    comments = db.query(TaskComment).filter(
        TaskComment.task_id == task_id
    ).order_by(TaskComment.created_at).all()
    return comments


# ─────────────────────────────────────────────────────────────
# Task Checklists Routes
# ─────────────────────────────────────────────────────────────

@router.post("/{task_id}/checklists", response_model=ChecklistResponse, status_code=status.HTTP_201_CREATED)
def create_checklist(
    task_id: int,
    checklist: ChecklistCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a checklist to a task"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    new_checklist = TaskChecklist(
        task_id=task_id,
        title=checklist.title
    )
    db.add(new_checklist)
    db.flush()
    
    # Add items
    for idx, item_content in enumerate(checklist.items):
        item = ChecklistItem(
            checklist_id=new_checklist.id,
            content=item_content,
            position=idx
        )
        db.add(item)
    
    db.commit()
    db.refresh(new_checklist)
    return new_checklist


# ─────────────────────────────────────────────────────────────
# Integration with Meetings (Auto-create tasks from action items)
# ─────────────────────────────────────────────────────────────

@router.post("/from-meeting/{meeting_id}", response_model=List[TaskResponse])
def create_tasks_from_meeting(
    meeting_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Auto-generate tasks from meeting action items"""
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    action_items = db.query(models.ActionItem).filter(
        models.ActionItem.meeting_id == meeting_id
    ).all()
    
    created_tasks = []
    for action_item in action_items:
        # Check if task already exists for this action item
        existing = db.query(Task).filter(Task.action_item_id == action_item.id).first()
        if existing:
            continue
        
        # Parse owner and deadline from action item
        assignee_id = None
        if action_item.owner:
            # Try to find user by email/name
            user = db.query(models.User).filter(
                models.User.email.ilike(f"%{action_item.owner}%")
            ).first()
            if user:
                assignee_id = user.id
        
        # Create task
        task = Task(
            title=action_item.text[:200],  # First 200 chars as title
            description=action_item.text,
            status=TaskStatus.TODO,
            priority=TaskPriority.NORMAL,
            assignee_id=assignee_id or current_user.id,
            created_by_id=current_user.id,
            meeting_id=meeting_id,
            action_item_id=action_item.id
        )
        
        db.add(task)
        created_tasks.append(task)
    
    db.commit()
    for task in created_tasks:
        db.refresh(task)
    
    return created_tasks


# ─────────────────────────────────────────────────────────────
# Statistics & Analytics
# ─────────────────────────────────────────────────────────────

@router.get("/stats/overview")
def get_task_stats(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get task statistics for current user"""
    total_tasks = db.query(Task).count()
    my_tasks = db.query(Task).filter(Task.assignee_id == current_user.id).count()
    completed_tasks = db.query(Task).filter(
        Task.assignee_id == current_user.id,
        Task.status == TaskStatus.COMPLETED
    ).count()
    overdue_tasks = db.query(Task).filter(
        Task.assignee_id == current_user.id,
        Task.status != TaskStatus.COMPLETED,
        Task.due_date < datetime.utcnow()
    ).count()
    
    return {
        "total_tasks": total_tasks,
        "my_tasks": my_tasks,
        "completed": completed_tasks,
        "overdue": overdue_tasks,
        "completion_rate": (completed_tasks / my_tasks * 100) if my_tasks > 0 else 0
    }
