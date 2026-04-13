"""
P2P Tracker — Single source of truth for "where is my procurement?"
===================================================================
Answers: What stage is my PR at? What's pending? What needs my action?

GET /api/p2p/active           — All active P2P workflows with current stage
GET /api/p2p/journey/{id}     — Full journey of one PR (every step, timestamp, who did what)
GET /api/p2p/my-actions       — What needs MY action right now?
GET /api/p2p/summary          — Dashboard numbers (active, pending, completed, blocked)
GET /api/p2p/guide/{id}       — Human-friendly guide: what happened, what's next, what to type
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from backend.services.rbac import require_auth

import os
import psycopg2
from psycopg2.extras import RealDictCursor
import json

log = logging.getLogger(__name__)
router = APIRouter()

DB_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:YourStr0ng!Pass@127.0.0.1:5433/odoo_procurement_demo')


def _conn():
    return psycopg2.connect(DB_URL)


def _serialize(rows):
    """Convert DB rows to JSON-safe dicts."""
    result = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, 'isoformat'):
                d[k] = v.isoformat()
        result.append(d)
    return result


# ── GET /api/p2p/summary ────────────────────────────────────────────────────

@router.get("/summary")
async def p2p_summary(current_user: dict = Depends(require_auth())):
    """
    Dashboard numbers: how many workflows are active, completed, blocked, waiting.
    """
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT status, count(*) FROM workflow_runs GROUP BY status")
        status_counts = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("SELECT count(*) FROM workflow_runs WHERE workflow_type = 'P2P_FULL'")
        p2p_total = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM pending_approvals WHERE status = 'pending'")
        pending_approvals = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM procurement_records WHERE status = 'pending_approval'")
        prs_pending = cur.fetchone()[0]

        return {
            "total_workflows": sum(status_counts.values()),
            "p2p_workflows": p2p_total,
            "by_status": {
                "running": status_counts.get("running", 0),
                "waiting_human": status_counts.get("waiting_human", 0),
                "completed": status_counts.get("completed", 0),
                "failed": status_counts.get("failed", 0),
            },
            "pending_approvals": pending_approvals,
            "prs_awaiting_approval": prs_pending,
        }
    finally:
        cur.close()
        conn.close()


# ── GET /api/p2p/active ─────────────────────────────────────────────────────

@router.get("/active")
async def p2p_active(
    status: Optional[str] = Query(None, description="Filter: running, waiting_human, completed, failed"),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_auth()),
):
    """
    All active P2P workflows with their current stage.
    Each workflow shows: workflow_id, status, current step, progress %, timestamps.
    """
    conn = _conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        conditions = ["workflow_type = 'P2P_FULL'"]
        params = []
        if status:
            conditions.append("status = %s")
            params.append(status)

        where = " AND ".join(conditions)
        params.append(limit)

        cur.execute(f"""
            SELECT workflow_run_id, status, total_tasks, completed_tasks,
                   failed_tasks, started_at, completed_at, trigger_data
            FROM workflow_runs
            WHERE {where}
            ORDER BY started_at DESC
            LIMIT %s
        """, params)
        workflows = _serialize(cur.fetchall())

        # For each workflow, find the current step
        for wf in workflows:
            wf_id = wf['workflow_run_id']
            progress = round((wf['completed_tasks'] / wf['total_tasks']) * 100, 1) if wf['total_tasks'] > 0 else 0
            wf['progress_pct'] = progress

            # Parse trigger_data for context
            td = wf.get('trigger_data')
            if isinstance(td, str):
                try:
                    td = json.loads(td)
                except Exception:
                    td = {}
            wf['department'] = td.get('department', '') if isinstance(td, dict) else ''
            wf['product'] = td.get('product_name', '') if isinstance(td, dict) else ''
            wf['requester'] = td.get('requester', '') if isinstance(td, dict) else ''
            wf['budget'] = td.get('budget', 0) if isinstance(td, dict) else 0

            # Current step = last non-pending task
            cur.execute("""
                SELECT task_name, status, agent_name, wait_type
                FROM workflow_tasks WHERE workflow_run_id = %s
                ORDER BY id
            """, (wf_id,))
            tasks = cur.fetchall()

            current_step = None
            next_step = None
            waiting_for = None
            for t in tasks:
                ts = t['status']
                tn = t['task_name']
                if ts == 'waiting_human':
                    current_step = tn
                    waiting_for = t['wait_type']
                    break
                elif ts == 'running':
                    current_step = tn
                    break
                elif ts == 'pending' and next_step is None:
                    next_step = tn

            wf['current_step'] = current_step or next_step or 'completed'
            wf['current_step_label'] = (current_step or next_step or 'completed').replace('_', ' ').title()
            wf['waiting_for'] = waiting_for

            # Remove raw trigger_data from response
            wf.pop('trigger_data', None)

        return {"total": len(workflows), "workflows": workflows}
    finally:
        cur.close()
        conn.close()


# ── GET /api/p2p/{workflow_id} ──────────────────────────────────────────────

@router.get("/journey/{workflow_run_id}")
async def p2p_journey(workflow_run_id: str, current_user: dict = Depends(require_auth())):
    """
    Full journey of one workflow — every step with status, timestamp, who did what.
    This is the "PR timeline" view.
    """
    conn = _conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Workflow header
        cur.execute("SELECT * FROM workflow_runs WHERE workflow_run_id = %s", (workflow_run_id,))
        wf = cur.fetchone()
        if not wf:
            raise HTTPException(404, f"Workflow {workflow_run_id} not found")
        wf = dict(wf)
        for k, v in wf.items():
            if hasattr(v, 'isoformat'):
                wf[k] = v.isoformat()

        # Parse trigger_data
        td = wf.get('trigger_data')
        if isinstance(td, str):
            try:
                td = json.loads(td)
            except Exception:
                td = {}

        # All tasks
        cur.execute("""
            SELECT task_id, task_name, task_type, agent_name, status,
                   wait_type, started_at, completed_at, execution_time_ms,
                   output_data, error_message
            FROM workflow_tasks WHERE workflow_run_id = %s ORDER BY id
        """, (workflow_run_id,))
        tasks = _serialize(cur.fetchall())

        # Build step-by-step journey
        journey = []
        for i, t in enumerate(tasks, 1):
            step = {
                "step_number": i,
                "name": t['task_name'],
                "label": t['task_name'].replace('_', ' ').title(),
                "type": t['task_type'],
                "agent": t['agent_name'] or 'Human',
                "status": t['status'],
                "started_at": t.get('started_at'),
                "completed_at": t.get('completed_at'),
                "duration_ms": t.get('execution_time_ms'),
                "waiting_for": t.get('wait_type'),
                "error": t.get('error_message'),
            }

            # Extract summary from output_data
            out = t.get('output_data')
            if isinstance(out, str):
                try:
                    out = json.loads(out)
                except Exception:
                    out = {}
            if isinstance(out, dict):
                step['summary'] = out.get('summary', out.get('message', ''))
                step['pr_number'] = out.get('pr_number')
                step['po_number'] = out.get('po_number')
            else:
                step['summary'] = ''

            journey.append(step)

        progress = round((wf['completed_tasks'] / wf['total_tasks']) * 100, 1) if wf['total_tasks'] > 0 else 0

        return {
            "workflow_id": workflow_run_id,
            "workflow_type": wf.get('workflow_type'),
            "status": wf.get('status'),
            "progress_pct": progress,
            "completed": wf.get('completed_tasks', 0),
            "total": wf.get('total_tasks', 0),
            "department": td.get('department', '') if isinstance(td, dict) else '',
            "product": td.get('product_name', '') if isinstance(td, dict) else '',
            "requester": td.get('requester', '') if isinstance(td, dict) else '',
            "budget": td.get('budget', 0) if isinstance(td, dict) else 0,
            "started_at": wf.get('started_at'),
            "completed_at": wf.get('completed_at'),
            "journey": journey,
        }
    finally:
        cur.close()
        conn.close()


# ── GET /api/p2p/my-actions ─────────────────────────────────────────────────

@router.get("/my-actions")
async def p2p_my_actions(current_user: dict = Depends(require_auth())):
    """
    What needs MY action right now?
    Returns all tasks across all workflows that are waiting for human input.
    """
    conn = _conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT t.task_id, t.task_name, t.wait_type, t.started_at,
                   w.workflow_run_id, w.workflow_type, w.trigger_data,
                   w.completed_tasks, w.total_tasks
            FROM workflow_tasks t
            JOIN workflow_runs w ON t.workflow_run_id = w.workflow_run_id
            WHERE t.status = 'waiting_human'
            ORDER BY t.started_at ASC
        """)
        waiting = _serialize(cur.fetchall())

        actions = []
        for t in waiting:
            td = t.get('trigger_data')
            if isinstance(td, str):
                try:
                    td = json.loads(td)
                except Exception:
                    td = {}

            action_type = t['wait_type'] or t['task_name']
            action_label = {
                'vendor_selection': 'Select a vendor from the shortlist',
                'approval': 'Approve or reject this purchase request',
                'goods_receipt': 'Confirm goods have been received',
                'payment_approval': 'Approve payment for processing',
            }.get(action_type, f'Action needed: {action_type}')

            actions.append({
                "task_id": t['task_id'],
                "action_type": action_type,
                "action_label": action_label,
                "workflow_id": t['workflow_run_id'],
                "workflow_type": t['workflow_type'],
                "department": td.get('department', '') if isinstance(td, dict) else '',
                "product": td.get('product_name', '') if isinstance(td, dict) else '',
                "budget": td.get('budget', 0) if isinstance(td, dict) else 0,
                "progress": f"{t['completed_tasks']}/{t['total_tasks']}",
                "waiting_since": t.get('started_at'),
                "resume_url": f"/api/workflow/task/{t['task_id']}/resume",
            })

        return {"total": len(actions), "actions": actions}
    finally:
        cur.close()
        conn.close()


# ── GET /api/p2p/guide/{workflow_run_id} ────────────────────────────────────

@router.get("/guide/{workflow_run_id}")
async def p2p_guide(workflow_run_id: str, current_user: dict = Depends(require_auth())):
    """
    Human-friendly guide: what just happened, what's next, what to type in chat.
    This is the endpoint that answers "I'm lost, what do I do now?"
    """
    from backend.services.workflow_engine import get_guided_status
    result = get_guided_status(workflow_run_id)
    if not result.get("success"):
        raise HTTPException(404, result.get("error", "Workflow not found"))
    return result
