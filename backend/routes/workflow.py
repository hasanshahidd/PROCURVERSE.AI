"""
Workflow Routes — P2P Workflow Management API
==============================================
POST /api/workflow/create          — Create a new workflow (PR_TO_PO, INVOICE_TO_PAY, GOODS_RECEIPT)
POST /api/workflow/{id}/advance    — Advance workflow (find and run next ready tasks)
POST /api/workflow/task/{id}/complete — Complete a task with result
POST /api/workflow/task/{id}/fail  — Fail a task (triggers retry or halt)
POST /api/workflow/task/{id}/resume — Resume a human-waiting task
GET  /api/workflow/{id}            — Get full workflow status
GET  /api/workflow/list            — List all workflows
GET  /api/workflow/types           — List available workflow types
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services.workflow_engine import (
    create_workflow, advance_workflow, complete_task, fail_task,
    resume_from_human, get_workflow_status, list_workflows,
    WORKFLOW_TEMPLATES,
)

log = logging.getLogger(__name__)
router = APIRouter()


class CreateWorkflowRequest(BaseModel):
    workflow_type: str
    trigger_data: dict = {}
    created_by: str = 'system'


class TaskResultRequest(BaseModel):
    result: dict = {}


class TaskFailRequest(BaseModel):
    error: str


class HumanInputRequest(BaseModel):
    input_data: dict = {}


@router.post("/create")
async def api_create_workflow(body: CreateWorkflowRequest):
    """Create a new P2P workflow with all its tasks."""
    result = create_workflow(body.workflow_type, body.trigger_data, body.created_by)
    if not result.get('success'):
        raise HTTPException(400, result.get('error', 'Failed to create workflow'))
    return result


@router.post("/{workflow_run_id}/advance")
async def api_advance_workflow(workflow_run_id: str):
    """Find ready tasks and start them."""
    result = advance_workflow(workflow_run_id)
    if not result.get('success'):
        raise HTTPException(400, result.get('error', 'Failed to advance'))
    return result


@router.post("/task/{task_id}/complete")
async def api_complete_task(task_id: str, body: TaskResultRequest):
    """Mark a task as completed and trigger downstream."""
    result = complete_task(task_id, body.result)
    if not result.get('success'):
        raise HTTPException(400, result.get('error', 'Failed to complete task'))
    return result


@router.post("/task/{task_id}/fail")
async def api_fail_task(task_id: str, body: TaskFailRequest):
    """Mark a task as failed (will retry if under limit)."""
    result = fail_task(task_id, body.error)
    if not result.get('success'):
        raise HTTPException(400, result.get('error', 'Failed'))
    return result


@router.post("/task/{task_id}/resume")
async def api_resume_task(task_id: str, body: HumanInputRequest):
    """Resume a task that was waiting for human input."""
    result = resume_from_human(task_id, body.input_data)
    if not result.get('success'):
        raise HTTPException(400, result.get('error', 'Failed to resume'))
    return result


@router.get("/{workflow_run_id}")
async def api_get_workflow(workflow_run_id: str):
    """Get full workflow status with tasks and events."""
    result = get_workflow_status(workflow_run_id)
    if not result.get('success'):
        raise HTTPException(404, result.get('error', 'Not found'))
    return result


@router.get("/list/all")
async def api_list_workflows(
    status: Optional[str] = Query(None),
    workflow_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List all workflows with optional filters."""
    workflows = list_workflows(status=status, workflow_type=workflow_type, limit=limit)
    return {'total': len(workflows), 'workflows': workflows}


@router.get("/types/available")
async def api_workflow_types():
    """List available workflow types and their task definitions."""
    types = {}
    for wf_type, template in WORKFLOW_TEMPLATES.items():
        types[wf_type] = {
            'name': template['name'],
            'total_tasks': len(template['tasks']),
            'tasks': [
                {
                    'name': t['name'],
                    'type': t['type'],
                    'agent': t.get('agent', ''),
                    'wait_type': t.get('wait_type', ''),
                    'depends_on': t.get('depends_on', []),
                }
                for t in template['tasks']
            ],
        }
    return types
