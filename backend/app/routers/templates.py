"""
Task Templates & Recurring Tasks API Routes
Supports template CRUD, recurring rules, and auto-generation
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import json

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_templates import (
    TaskTemplate, RecurringTaskRule, GeneratedTask, 
    TemplateCategory, TemplateUsageLog, RecurrenceFrequency
)
from ..models_tasks import Task, TaskStatus, TaskPriority


router = APIRouter(prefix="/templates", tags=["templates"])


# ─────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────

class TaskTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    title_template: str
    description_template: Optional[str] = None
    default_priority: Optional[str] = "normal"
    default_status: str = "todo"
    default_estimated_hours: Optional[int] = None
    default_tags: Optional[str] = None
    default_assignee_id: Optional[int] = None
    list_id: Optional[int] = None
    checklist_template: Optional[str] = None
    custom_fields_template: Optional[str] = None
    workspace_id: Optional[int] = None
    category: Optional[str] = None
    is_public: bool = False


class TaskTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    default_priority: Optional[str] = None
    default_estimated_hours: Optional[int] = None
    default_tags: Optional[str] = None
    is_active: Optional[bool] = None


class TaskTemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    title_template: str
    description_template: Optional[str]
    default_priority: Optional[str]
    default_status: str
    category: Optional[str]
    is_public: bool
    is_active: bool
    usage_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class RecurringTaskRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    template_id: Optional[int] = None
    frequency: RecurrenceFrequency
    interval: int = 1
    days_of_week: Optional[str] = None
    day_of_month: Optional[int] = None
    time_of_day: Optional[str] = "09:00"
    start_date: datetime
    end_date: Optional[datetime] = None
    advance_creation_days: int = 0
    task_title: Optional[str] = None
    task_description: Optional[str] = None
    task_priority: Optional[str] = None
    task_assignee_id: Optional[int] = None
    task_list_id: Optional[int] = None


class RecurringTaskRuleUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    is_paused: Optional[bool] = None
    end_date: Optional[datetime] = None


class RecurringTaskRuleResponse(BaseModel):
    id: int
    name: str
    frequency: str
    interval: int
    is_active: bool
    is_paused: bool
    last_generated_at: Optional[datetime]
    next_generation_at: Optional[datetime]
    total_generated: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class CreateTaskFromTemplate(BaseModel):
    """Request to create task from template"""
    template_id: int
    title_override: Optional[str] = None
    description_override: Optional[str] = None
    assignee_id_override: Optional[int] = None
    due_date: Optional[datetime] = None
    list_id_override: Optional[int] = None


# ─────────────────────────────────────────────────────────────
# Template Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/", response_model=TaskTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    template_data: TaskTemplateCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new task template"""
    new_template = TaskTemplate(
        **template_data.dict(),
        created_by_id=current_user.id
    )
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return new_template


@router.get("/", response_model=List[TaskTemplateResponse])
def list_templates(
    workspace_id: Optional[int] = None,
    category: Optional[str] = None,
    is_public: Optional[bool] = None,
    is_active: bool = True,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List task templates"""
    query = db.query(TaskTemplate).filter(TaskTemplate.is_active == is_active)
    
    # Filter by workspace or show public templates
    if workspace_id:
        query = query.filter(TaskTemplate.workspace_id == workspace_id)
    else:
        # Show user's templates and public templates
        query = query.filter(
            (TaskTemplate.created_by_id == current_user.id) | (TaskTemplate.is_public == True)
        )
    
    if category:
        query = query.filter(TaskTemplate.category == category)
    
    if is_public is not None:
        query = query.filter(TaskTemplate.is_public == is_public)
    
    templates = query.order_by(TaskTemplate.usage_count.desc(), TaskTemplate.created_at.desc()).all()
    return templates


@router.get("/{template_id}", response_model=TaskTemplateResponse)
def get_template(
    template_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific template"""
    template = db.query(TaskTemplate).filter(TaskTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Check access
    if not template.is_public and template.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return template


@router.patch("/{template_id}", response_model=TaskTemplateResponse)
def update_template(
    template_id: int,
    template_data: TaskTemplateUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a template"""
    template = db.query(TaskTemplate).filter(
        TaskTemplate.id == template_id,
        TaskTemplate.created_by_id == current_user.id
    ).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    for key, value in template_data.dict(exclude_unset=True).items():
        setattr(template, key, value)
    
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a template"""
    template = db.query(TaskTemplate).filter(
        TaskTemplate.id == template_id,
        TaskTemplate.created_by_id == current_user.id
    ).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    db.delete(template)
    db.commit()
    return None


@router.post("/use")
def create_task_from_template(
    request: CreateTaskFromTemplate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new task from a template"""
    template = db.query(TaskTemplate).filter(TaskTemplate.id == request.template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Check access
    if not template.is_public and template.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Create task from template
    new_task = Task(
        title=request.title_override or template.title_template,
        description=request.description_override or template.description_template,
        status=TaskStatus(template.default_status) if template.default_status else TaskStatus.TODO,
        priority=TaskPriority(template.default_priority) if template.default_priority else TaskPriority.NORMAL,
        assignee_id=request.assignee_id_override or template.default_assignee_id,
        created_by_id=current_user.id,
        list_id=request.list_id_override or template.list_id,
        due_date=request.due_date,
        estimated_hours=template.default_estimated_hours,
        tags=template.default_tags,
        custom_fields=template.custom_fields_template
    )
    
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    
    # Update template usage count
    template.usage_count += 1
    
    # Log usage
    usage_log = TemplateUsageLog(
        template_id=template.id,
        user_id=current_user.id,
        task_id=new_task.id
    )
    db.add(usage_log)
    db.commit()
    
    return {
        "task_id": new_task.id,
        "template_id": template.id,
        "message": "Task created successfully from template"
    }


# ─────────────────────────────────────────────────────────────
# Recurring Task Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/recurring", response_model=RecurringTaskRuleResponse, status_code=status.HTTP_201_CREATED)
def create_recurring_rule(
    rule_data: RecurringTaskRuleCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a recurring task rule"""
    # Validate template if provided
    if rule_data.template_id:
        template = db.query(TaskTemplate).filter(TaskTemplate.id == rule_data.template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
    
    # Calculate first generation time
    next_gen = _calculate_next_generation(rule_data.start_date, rule_data.frequency, rule_data.interval)
    
    new_rule = RecurringTaskRule(
        **rule_data.dict(),
        created_by_id=current_user.id,
        next_generation_at=next_gen
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    
    return new_rule


@router.get("/recurring", response_model=List[RecurringTaskRuleResponse])
def list_recurring_rules(
    is_active: Optional[bool] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List recurring task rules"""
    query = db.query(RecurringTaskRule).filter(
        RecurringTaskRule.created_by_id == current_user.id
    )
    
    if is_active is not None:
        query = query.filter(RecurringTaskRule.is_active == is_active)
    
    rules = query.order_by(RecurringTaskRule.created_at.desc()).all()
    return rules


@router.get("/recurring/{rule_id}", response_model=RecurringTaskRuleResponse)
def get_recurring_rule(
    rule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific recurring rule"""
    rule = db.query(RecurringTaskRule).filter(
        RecurringTaskRule.id == rule_id,
        RecurringTaskRule.created_by_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    return rule


@router.patch("/recurring/{rule_id}", response_model=RecurringTaskRuleResponse)
def update_recurring_rule(
    rule_id: int,
    rule_data: RecurringTaskRuleUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a recurring rule"""
    rule = db.query(RecurringTaskRule).filter(
        RecurringTaskRule.id == rule_id,
        RecurringTaskRule.created_by_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    for key, value in rule_data.dict(exclude_unset=True).items():
        setattr(rule, key, value)
    
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/recurring/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring_rule(
    rule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a recurring rule"""
    rule = db.query(RecurringTaskRule).filter(
        RecurringTaskRule.id == rule_id,
        RecurringTaskRule.created_by_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    db.delete(rule)
    db.commit()
    return None


@router.post("/recurring/{rule_id}/generate")
def manually_generate_task(
    rule_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually generate a task from a recurring rule"""
    rule = db.query(RecurringTaskRule).filter(
        RecurringTaskRule.id == rule_id,
        RecurringTaskRule.created_by_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    task = _generate_task_from_rule(db, rule)
    
    return {
        "task_id": task.id,
        "rule_id": rule.id,
        "message": "Task generated successfully"
    }


@router.post("/recurring/process-all")
def process_all_recurring_tasks(
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process all active recurring rules (admin/cron endpoint)"""
    # This would typically be called by a background job
    rules = db.query(RecurringTaskRule).filter(
        RecurringTaskRule.is_active == True,
        RecurringTaskRule.is_paused == False,
        RecurringTaskRule.next_generation_at <= datetime.utcnow()
    ).all()
    
    generated_count = 0
    for rule in rules:
        try:
            _generate_task_from_rule(db, rule)
            generated_count += 1
        except Exception as e:
            print(f"Error generating task from rule {rule.id}: {e}")
            continue
    
    return {
        "processed_rules": len(rules),
        "tasks_generated": generated_count
    }


@router.get("/recurring/{rule_id}/history")
def get_rule_history(
    rule_id: int,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get history of tasks generated by a rule"""
    rule = db.query(RecurringTaskRule).filter(
        RecurringTaskRule.id == rule_id,
        RecurringTaskRule.created_by_id == current_user.id
    ).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    history = db.query(GeneratedTask).filter(
        GeneratedTask.rule_id == rule_id
    ).order_by(GeneratedTask.generated_at.desc()).limit(limit).all()
    
    return [
        {
            "id": h.id,
            "task_id": h.task_id,
            "scheduled_for": h.scheduled_for,
            "generated_at": h.generated_at,
            "was_completed": h.was_completed,
            "was_skipped": h.was_skipped,
            "completion_date": h.completion_date
        }
        for h in history
    ]


# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────

def _calculate_next_generation(start_date: datetime, frequency: RecurrenceFrequency, interval: int) -> datetime:
    """Calculate the next task generation time"""
    now = datetime.utcnow()
    
    if start_date > now:
        return start_date
    
    if frequency == RecurrenceFrequency.DAILY:
        return now + timedelta(days=interval)
    elif frequency == RecurrenceFrequency.WEEKLY:
        return now + timedelta(weeks=interval)
    elif frequency == RecurrenceFrequency.MONTHLY:
        # Approximate - would need more sophisticated logic
        return now + timedelta(days=30 * interval)
    elif frequency == RecurrenceFrequency.YEARLY:
        return now + timedelta(days=365 * interval)
    else:
        return now + timedelta(days=1)


def _generate_task_from_rule(db: Session, rule: RecurringTaskRule) -> Task:
    """Generate a task from a recurring rule"""
    # Get template if specified
    if rule.template_id:
        template = db.query(TaskTemplate).filter(TaskTemplate.id == rule.template_id).first()
        title = template.title_template if template else rule.task_title
        description = template.description_template if template else rule.task_description
        priority = template.default_priority if template else rule.task_priority
        estimated_hours = template.default_estimated_hours if template else rule.task_estimated_hours
        tags = template.default_tags if template else None
    else:
        title = rule.task_title
        description = rule.task_description
        priority = rule.task_priority
        estimated_hours = rule.task_estimated_hours
        tags = None
    
    # Create task
    new_task = Task(
        title=title or "Recurring Task",
        description=description,
        status=TaskStatus.TODO,
        priority=TaskPriority(priority) if priority else TaskPriority.NORMAL,
        assignee_id=rule.task_assignee_id,
        created_by_id=rule.created_by_id,
        list_id=rule.task_list_id,
        estimated_hours=estimated_hours,
        tags=tags
    )
    
    db.add(new_task)
    db.flush()  # Get task ID without committing
    
    # Track generation
    generated = GeneratedTask(
        rule_id=rule.id,
        task_id=new_task.id,
        scheduled_for=rule.next_generation_at or datetime.utcnow()
    )
    db.add(generated)
    
    # Update rule
    rule.last_generated_at = datetime.utcnow()
    rule.total_generated += 1
    rule.next_generation_at = _calculate_next_generation(
        rule.last_generated_at,
        rule.frequency,
        rule.interval
    )
    
    db.commit()
    db.refresh(new_task)
    
    return new_task
