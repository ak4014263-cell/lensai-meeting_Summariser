"""
Automation Workflows API Routes
Supports workflow creation, execution, and monitoring
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel
import json

from ..database import get_db
from ..auth.router import get_current_user
from .. import models
from ..models_automation import (
    AutomationWorkflow, WorkflowAction, WorkflowExecution,
    ActionExecutionResult, IntegrationMapping,
    TriggerType, ActionType, WorkflowStatus
)
from ..models_tasks import Task, TaskStatus, TaskPriority
from ..models_goals import Goal, GoalStatus


router = APIRouter(prefix="/automation", tags=["automation"])


# ─────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────

class WorkflowActionCreate(BaseModel):
    action_type: ActionType
    action_config: Dict[str, Any]
    order: int = 0
    run_condition: Optional[Dict[str, Any]] = None
    continue_on_error: bool = True


class AutomationWorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_type: TriggerType
    trigger_config: Optional[Dict[str, Any]] = None
    conditions: Optional[List[Dict[str, Any]]] = None
    workspace_id: Optional[int] = None
    delay_seconds: int = 0
    max_executions: Optional[int] = None
    schedule_cron: Optional[str] = None
    actions: List[WorkflowActionCreate]


class AutomationWorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[WorkflowStatus] = None
    conditions: Optional[List[Dict[str, Any]]] = None
    delay_seconds: Optional[int] = None


class AutomationWorkflowResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    trigger_type: str
    status: str
    execution_count: int
    last_executed_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


class WorkflowExecutionResponse(BaseModel):
    id: int
    workflow_id: int
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    actions_executed: int
    actions_failed: int
    error_message: Optional[str]
    
    class Config:
        from_attributes = True


class IntegrationMappingCreate(BaseModel):
    source_type: str
    source_id: int
    target_type: str
    target_id: int
    mapping_type: str = "manual_link"
    sync_enabled: bool = True


# ─────────────────────────────────────────────────────────────
# Workflow Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/workflows", response_model=AutomationWorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    workflow_data: AutomationWorkflowCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new automation workflow"""
    # Create workflow
    new_workflow = AutomationWorkflow(
        name=workflow_data.name,
        description=workflow_data.description,
        trigger_type=workflow_data.trigger_type,
        trigger_config=json.dumps(workflow_data.trigger_config) if workflow_data.trigger_config else None,
        conditions=json.dumps(workflow_data.conditions) if workflow_data.conditions else None,
        workspace_id=workflow_data.workspace_id,
        delay_seconds=workflow_data.delay_seconds,
        max_executions=workflow_data.max_executions,
        schedule_cron=workflow_data.schedule_cron,
        created_by_id=current_user.id
    )
    
    db.add(new_workflow)
    db.flush()  # Get workflow ID
    
    # Create actions
    for action_data in workflow_data.actions:
        action = WorkflowAction(
            workflow_id=new_workflow.id,
            action_type=action_data.action_type,
            action_config=json.dumps(action_data.action_config),
            order=action_data.order,
            run_condition=json.dumps(action_data.run_condition) if action_data.run_condition else None,
            continue_on_error=action_data.continue_on_error
        )
        db.add(action)
    
    db.commit()
    db.refresh(new_workflow)
    
    return new_workflow


@router.get("/workflows", response_model=List[AutomationWorkflowResponse])
def list_workflows(
    workspace_id: Optional[int] = None,
    trigger_type: Optional[TriggerType] = None,
    status: Optional[WorkflowStatus] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List automation workflows"""
    query = db.query(AutomationWorkflow)
    
    if workspace_id:
        query = query.filter(AutomationWorkflow.workspace_id == workspace_id)
    
    if trigger_type:
        query = query.filter(AutomationWorkflow.trigger_type == trigger_type)
    
    if status:
        query = query.filter(AutomationWorkflow.status == status)
    
    workflows = query.order_by(AutomationWorkflow.created_at.desc()).all()
    return workflows


@router.get("/workflows/{workflow_id}", response_model=AutomationWorkflowResponse)
def get_workflow(
    workflow_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific workflow with actions"""
    workflow = db.query(AutomationWorkflow).filter(
        AutomationWorkflow.id == workflow_id
    ).first()
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    return workflow


@router.patch("/workflows/{workflow_id}", response_model=AutomationWorkflowResponse)
def update_workflow(
    workflow_id: int,
    workflow_data: AutomationWorkflowUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a workflow"""
    workflow = db.query(AutomationWorkflow).filter(
        AutomationWorkflow.id == workflow_id
    ).first()
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    for key, value in workflow_data.dict(exclude_unset=True).items():
        if key == "conditions" and value is not None:
            setattr(workflow, key, json.dumps(value))
        else:
            setattr(workflow, key, value)
    
    db.commit()
    db.refresh(workflow)
    return workflow


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workflow_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a workflow"""
    workflow = db.query(AutomationWorkflow).filter(
        AutomationWorkflow.id == workflow_id
    ).first()
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    db.delete(workflow)
    db.commit()
    return None


@router.post("/workflows/{workflow_id}/trigger")
def trigger_workflow_manually(
    workflow_id: int,
    trigger_data: Optional[Dict[str, Any]] = None,
    background_tasks: BackgroundTasks = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger a workflow execution"""
    workflow = db.query(AutomationWorkflow).filter(
        AutomationWorkflow.id == workflow_id
    ).first()
    
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    if workflow.status != WorkflowStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Workflow is not active")
    
    # Execute workflow
    execution = _execute_workflow(db, workflow, trigger_data or {})
    
    return {
        "execution_id": execution.id,
        "workflow_id": workflow.id,
        "status": execution.status,
        "message": "Workflow triggered successfully"
    }


# ─────────────────────────────────────────────────────────────
# Execution History Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/workflows/{workflow_id}/executions", response_model=List[WorkflowExecutionResponse])
def get_workflow_executions(
    workflow_id: int,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get execution history for a workflow"""
    executions = db.query(WorkflowExecution).filter(
        WorkflowExecution.workflow_id == workflow_id
    ).order_by(WorkflowExecution.started_at.desc()).limit(limit).all()
    
    return executions


@router.get("/executions/{execution_id}")
def get_execution_details(
    execution_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed execution results"""
    execution = db.query(WorkflowExecution).filter(
        WorkflowExecution.id == execution_id
    ).first()
    
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    # Get action results
    action_results = db.query(ActionExecutionResult).filter(
        ActionExecutionResult.execution_id == execution_id
    ).order_by(ActionExecutionResult.started_at).all()
    
    return {
        "execution": {
            "id": execution.id,
            "workflow_id": execution.workflow_id,
            "started_at": execution.started_at,
            "completed_at": execution.completed_at,
            "status": execution.status,
            "actions_executed": execution.actions_executed,
            "actions_failed": execution.actions_failed,
            "error_message": execution.error_message,
            "trigger_data": json.loads(execution.trigger_data) if execution.trigger_data else None
        },
        "action_results": [
            {
                "action_id": ar.action_id,
                "status": ar.status,
                "started_at": ar.started_at,
                "completed_at": ar.completed_at,
                "error_message": ar.error_message,
                "result_data": json.loads(ar.result_data) if ar.result_data else None
            }
            for ar in action_results
        ]
    }


# ─────────────────────────────────────────────────────────────
# Integration Mapping Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/mappings", status_code=status.HTTP_201_CREATED)
def create_mapping(
    mapping_data: IntegrationMappingCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create an integration mapping (e.g., link meeting to task)"""
    new_mapping = IntegrationMapping(
        **mapping_data.dict(),
        created_by_id=current_user.id
    )
    db.add(new_mapping)
    db.commit()
    db.refresh(new_mapping)
    
    return new_mapping


@router.get("/mappings")
def list_mappings(
    source_type: Optional[str] = None,
    target_type: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List integration mappings"""
    query = db.query(IntegrationMapping)
    
    if source_type:
        query = query.filter(IntegrationMapping.source_type == source_type)
    
    if target_type:
        query = query.filter(IntegrationMapping.target_type == target_type)
    
    mappings = query.order_by(IntegrationMapping.created_at.desc()).all()
    return mappings


# ─────────────────────────────────────────────────────────────
# Built-in Workflow Helpers (Meeting → Task, Task → Goal)
# ─────────────────────────────────────────────────────────────

@router.post("/meeting-to-task/{meeting_id}")
def create_tasks_from_meeting(
    meeting_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create tasks from meeting action items"""
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    # Get action items from meeting
    action_items = db.query(models.ActionItem).filter(
        models.ActionItem.meeting_id == meeting_id
    ).all()
    
    created_tasks = []
    for item in action_items:
        # Check if task already exists
        existing_mapping = db.query(IntegrationMapping).filter(
            IntegrationMapping.source_type == "action_item",
            IntegrationMapping.source_id == item.id,
            IntegrationMapping.target_type == "task"
        ).first()
        
        if existing_mapping:
            continue  # Already created
        
        # Create task
        new_task = Task(
            title=item.text,
            description=f"Action item from meeting: {meeting.title}",
            status=TaskStatus.TODO,
            priority=TaskPriority.NORMAL,
            assignee_id=item.assignee_id,
            created_by_id=current_user.id,
            meeting_id=meeting_id,
            action_item_id=item.id
        )
        db.add(new_task)
        db.flush()
        
        # Create mapping
        mapping = IntegrationMapping(
            source_type="action_item",
            source_id=item.id,
            target_type="task",
            target_id=new_task.id,
            mapping_type="auto_created",
            created_by_id=current_user.id
        )
        db.add(mapping)
        
        created_tasks.append(new_task.id)
    
    db.commit()
    
    return {
        "meeting_id": meeting_id,
        "tasks_created": len(created_tasks),
        "task_ids": created_tasks
    }


@router.post("/task-to-goal/{task_id}")
def link_task_to_goal(
    task_id: int,
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Link a task to a goal and set up auto-sync"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    
    # Create mapping
    mapping = IntegrationMapping(
        source_type="task",
        source_id=task_id,
        target_type="goal",
        target_id=goal_id,
        mapping_type="manual_link",
        sync_enabled=True,
        created_by_id=current_user.id
    )
    db.add(mapping)
    db.commit()
    
    return {
        "task_id": task_id,
        "goal_id": goal_id,
        "message": "Task linked to goal successfully"
    }


# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────

def _execute_workflow(db: Session, workflow: AutomationWorkflow, trigger_data: Dict[str, Any]) -> WorkflowExecution:
    """Execute a workflow and all its actions"""
    # Create execution record
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        trigger_data=json.dumps(trigger_data),
        status="running"
    )
    db.add(execution)
    db.flush()
    
    # Check conditions
    if workflow.conditions:
        conditions = json.loads(workflow.conditions)
        if not _evaluate_conditions(conditions, trigger_data):
            execution.status = "skipped"
            execution.completed_at = datetime.utcnow()
            db.commit()
            return execution
    
    # Execute actions in order
    actions = db.query(WorkflowAction).filter(
        WorkflowAction.workflow_id == workflow.id
    ).order_by(WorkflowAction.order).all()
    
    for action in actions:
        try:
            result = _execute_action(db, action, trigger_data)
            
            # Record action result
            action_result = ActionExecutionResult(
                execution_id=execution.id,
                action_id=action.id,
                status="success",
                completed_at=datetime.utcnow(),
                result_data=json.dumps(result)
            )
            db.add(action_result)
            execution.actions_executed += 1
            
        except Exception as e:
            # Record failure
            action_result = ActionExecutionResult(
                execution_id=execution.id,
                action_id=action.id,
                status="failed",
                completed_at=datetime.utcnow(),
                error_message=str(e)
            )
            db.add(action_result)
            execution.actions_failed += 1
            
            if not action.continue_on_error:
                execution.status = "failed"
                execution.error_message = str(e)
                break
    
    # Complete execution
    if execution.status == "running":
        execution.status = "completed"
    execution.completed_at = datetime.utcnow()
    
    # Update workflow stats
    workflow.execution_count += 1
    workflow.last_executed_at = datetime.utcnow()
    
    db.commit()
    db.refresh(execution)
    
    return execution


def _evaluate_conditions(conditions: List[Dict[str, Any]], data: Dict[str, Any]) -> bool:
    """Evaluate if conditions are met"""
    # Simple condition evaluation - can be expanded
    for condition in conditions:
        field = condition.get("field")
        operator = condition.get("operator")
        value = condition.get("value")
        
        data_value = data.get(field)
        
        if operator == "equals" and data_value != value:
            return False
        elif operator == "not_equals" and data_value == value:
            return False
        elif operator == "contains" and value not in str(data_value):
            return False
        elif operator == "greater_than" and not (data_value > value):
            return False
        elif operator == "less_than" and not (data_value < value):
            return False
    
    return True


def _execute_action(db: Session, action: WorkflowAction, trigger_data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a single workflow action"""
    config = json.loads(action.action_config)
    
    if action.action_type == ActionType.CREATE_TASK:
        # Create a task
        new_task = Task(
            title=config.get("title", "Automated Task"),
            description=config.get("description"),
            status=TaskStatus(config.get("status", "todo")),
            priority=TaskPriority(config.get("priority", "normal")),
            assignee_id=config.get("assignee_id"),
            created_by_id=trigger_data.get("user_id", 1),  # Default to system user
            list_id=config.get("list_id")
        )
        db.add(new_task)
        db.flush()
        return {"task_id": new_task.id, "action": "task_created"}
    
    elif action.action_type == ActionType.UPDATE_GOAL:
        # Update a goal
        goal_id = config.get("goal_id") or trigger_data.get("goal_id")
        if goal_id:
            goal = db.query(Goal).filter(Goal.id == goal_id).first()
            if goal:
                if "current_value" in config:
                    goal.current_value = config["current_value"]
                if "status" in config:
                    goal.status = GoalStatus(config["status"])
                db.flush()
                return {"goal_id": goal.id, "action": "goal_updated"}
    
    elif action.action_type == ActionType.SEND_NOTIFICATION:
        # Send notification (placeholder)
        return {"action": "notification_sent", "message": config.get("message")}
    
    return {"action": "no_op"}
