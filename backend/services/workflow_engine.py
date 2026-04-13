"""
Workflow Engine — Persistent P2P Workflow Management
=====================================================
Manages long-running procurement workflows that span multiple HTTP requests,
human approvals, and days of processing.

Features:
  - Persistent workflow state (survives server restart)
  - Task dependency management (sequential + conditional)
  - Human-in-the-loop pause/resume (approvals, vendor selection, QC)
  - Event-driven task triggering (approval_completed -> po_creation)
  - Retry logic with backoff
  - Full audit trail in workflow_events table

Workflow types:
  PR_TO_PO:       PR creation -> compliance -> budget -> vendor -> approval -> PO
  INVOICE_TO_PAY: Invoice capture -> routing -> matching -> discrepancy -> payment
  GOODS_RECEIPT:  GRN entry -> QC inspection -> finalization
  P2P_FULL:       Full procure-to-pay (15 steps, compliance through payment)

Task statuses:
  pending -> queued -> running -> completed
                    -> waiting_human (paused for approval/input)
                    -> failed -> retrying
                    -> cancelled
"""

import os
import uuid
import logging
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import json

log = logging.getLogger(__name__)

DB_URL = os.environ.get('DATABASE_URL')


# ── Task Status Constants ────────────────────────────────────────────────────

TASK_PENDING = 'pending'
TASK_QUEUED = 'queued'
TASK_RUNNING = 'running'
TASK_WAITING_HUMAN = 'waiting_human'
TASK_COMPLETED = 'completed'
TASK_FAILED = 'failed'
TASK_RETRYING = 'retrying'
TASK_CANCELLED = 'cancelled'

WORKFLOW_PENDING = 'pending'
WORKFLOW_RUNNING = 'running'
WORKFLOW_WAITING = 'waiting_human'
WORKFLOW_COMPLETED = 'completed'
WORKFLOW_FAILED = 'failed'

# ── Workflow Type Definitions ────────────────────────────────────────────────

WORKFLOW_TEMPLATES = {
    'PR_TO_PO': {
        'name': 'Purchase Requisition to Purchase Order',
        'tasks': [
            {'name': 'compliance_check',    'type': 'agent',  'agent': 'ComplianceCheckAgent',     'depends_on': []},
            {'name': 'budget_verification', 'type': 'agent',  'agent': 'BudgetVerificationAgent',  'depends_on': ['compliance_check']},
            {'name': 'vendor_selection',    'type': 'agent',  'agent': 'VendorSelectionAgent',     'depends_on': ['budget_verification']},
            {'name': 'vendor_confirmation', 'type': 'human',  'wait_type': 'vendor_selection',     'depends_on': ['vendor_selection']},
            {'name': 'pr_creation',         'type': 'system', 'agent': 'Orchestrator',             'depends_on': ['vendor_confirmation']},
            {'name': 'approval_routing',    'type': 'agent',  'agent': 'ApprovalRoutingAgent',     'depends_on': ['pr_creation']},
            {'name': 'approval_wait',       'type': 'human',  'wait_type': 'approval',             'depends_on': ['approval_routing']},
            {'name': 'po_creation',         'type': 'system', 'agent': 'Adapter',                  'depends_on': ['approval_wait']},
            {'name': 'notification',        'type': 'system', 'agent': 'NotificationDispatcher',   'depends_on': ['po_creation']},
        ],
    },
    'INVOICE_TO_PAY': {
        'name': 'Invoice to Payment',
        'tasks': [
            {'name': 'invoice_capture',       'type': 'agent',  'agent': 'InvoiceCaptureAgent',        'depends_on': []},
            {'name': 'invoice_routing',       'type': 'agent',  'agent': 'InvoiceRoutingAgent',        'depends_on': ['invoice_capture']},
            {'name': 'invoice_matching',      'type': 'agent',  'agent': 'InvoiceMatchingAgent',       'depends_on': ['invoice_routing']},
            {'name': 'discrepancy_resolution','type': 'agent',  'agent': 'DiscrepancyResolutionAgent', 'depends_on': ['invoice_matching']},
            {'name': 'payment_readiness',     'type': 'agent',  'agent': 'PaymentReadinessAgent',      'depends_on': ['discrepancy_resolution']},
            {'name': 'payment_calculation',   'type': 'agent',  'agent': 'PaymentCalculationAgent',    'depends_on': ['payment_readiness']},
            {'name': 'payment_approval',      'type': 'agent',  'agent': 'PaymentApprovalAgent',       'depends_on': ['payment_calculation']},
            {'name': 'payment_approval_wait', 'type': 'human',  'wait_type': 'payment_approval',       'depends_on': ['payment_approval']},
            {'name': 'payment_execution',     'type': 'system', 'agent': 'PaymentExecutionService',    'depends_on': ['payment_approval_wait']},
        ],
    },
    'GOODS_RECEIPT': {
        'name': 'Goods Receipt',
        'tasks': [
            {'name': 'grn_entry',          'type': 'human',  'wait_type': 'goods_receipt',     'depends_on': []},
            {'name': 'quality_inspection', 'type': 'agent',  'agent': 'QualityInspectionAgent', 'depends_on': ['grn_entry']},
            {'name': 'grn_finalization',   'type': 'system', 'agent': 'GoodsReceiptAgent',     'depends_on': ['quality_inspection']},
        ],
    },
    'P2P_FULL': {
        'name': 'Full Procure-to-Pay',
        'tasks': [
            {'name': 'compliance_check',    'type': 'agent',  'agent': 'ComplianceCheckAgent',     'depends_on': []},
            {'name': 'budget_verification', 'type': 'agent',  'agent': 'BudgetVerificationAgent',  'depends_on': ['compliance_check']},
            {'name': 'vendor_selection',    'type': 'agent',  'agent': 'VendorSelectionAgent',     'depends_on': ['budget_verification']},
            {'name': 'vendor_confirmation', 'type': 'human',  'wait_type': 'vendor_selection',     'depends_on': ['vendor_selection']},
            {'name': 'pr_creation',         'type': 'system', 'agent': 'Orchestrator',             'depends_on': ['vendor_confirmation']},
            {'name': 'approval_routing',    'type': 'agent',  'agent': 'ApprovalRoutingAgent',     'depends_on': ['pr_creation']},
            {'name': 'approval_wait',       'type': 'human',  'wait_type': 'approval',             'depends_on': ['approval_routing']},
            {'name': 'po_creation',         'type': 'system', 'agent': 'Adapter',                  'depends_on': ['approval_wait']},
            {'name': 'delivery_tracking',   'type': 'agent',  'agent': 'DeliveryTrackingAgent',    'depends_on': ['po_creation']},
            {'name': 'grn_entry',           'type': 'human',  'wait_type': 'goods_receipt',        'depends_on': ['delivery_tracking']},
            {'name': 'quality_inspection',  'type': 'agent',  'agent': 'QualityInspectionAgent',   'depends_on': ['grn_entry']},
            {'name': 'invoice_matching',    'type': 'agent',  'agent': 'InvoiceMatchingAgent',     'depends_on': ['quality_inspection']},
            {'name': 'three_way_match',     'type': 'agent',  'agent': 'InvoiceMatchingAgent',     'depends_on': ['invoice_matching']},
            {'name': 'payment_readiness',   'type': 'agent',  'agent': 'PaymentReadinessAgent',    'depends_on': ['three_way_match']},
            {'name': 'payment_execution',   'type': 'agent',  'agent': 'PaymentCalculationAgent',  'depends_on': ['payment_readiness']},
        ],
    },
}

# ── P2P Context-Aware Suggestions ───────────────────────────────────────────
# Maps last-completed task name to suggested next actions shown in chat UI.

P2P_SUGGESTIONS = {
    "compliance_check":     ["Check budget availability", "Review compliance details"],
    "budget_verification":  ["Select vendor", "Create RFQ for competitive pricing"],
    "vendor_selection":     ["Confirm vendor choice", "Compare more vendors"],
    "vendor_confirmation":  ["Check PR creation status", "View vendor details"],
    "pr_creation":          ["Check approval status", "View PR details"],
    "approval_routing":     ["Track approval progress", "Escalate if delayed"],
    "approval_wait":        ["Create purchase order", "View approval chain"],
    "po_creation":          ["Track delivery", "Set up QC inspection criteria"],
    "delivery_tracking":    ["Confirm goods receipt", "Report delivery issues"],
    "grn_entry":            ["Run quality inspection", "Report damaged items"],
    "quality_inspection":   ["Process invoice", "Create return for rejected items"],
    "invoice_matching":     ["Run 3-way match", "Resolve discrepancies"],
    "three_way_match":      ["Check payment readiness", "Review exceptions"],
    "payment_readiness":    ["Execute payment", "Hold for review"],
    "payment_execution":    ["Reconcile payment", "Generate receipt"],
}

# ── P2P Step-by-Step Guide ──────────────────────────────────────────────────
# After each step, tells user exactly what happened, what's next, and what to type.

P2P_GUIDE = {
    "compliance_check": {
        "done": "Compliance check passed - your request meets all procurement policies.",
        "next": "Budget verification is next - the system will check if your department has enough funds.",
        "step": "2 of 15",
    },
    "budget_verification": {
        "done": "Budget verified - your department has sufficient funds for this purchase.",
        "next": "Vendor selection is next - the system will find and rank the best vendors.",
        "step": "3 of 15",
    },
    "vendor_selection": {
        "done": "Vendor shortlist ready - top 5 vendors ranked by score.",
        "next": "You need to pick a vendor. Type: 'Use [vendor name] and proceed'",
        "action_needed": True,
        "step": "4 of 15",
    },
    "vendor_confirmation": {
        "done": "Vendor confirmed.",
        "next": "PR is being created and routed for manager approval.",
        "step": "5 of 15",
    },
    "pr_creation": {
        "done": "Purchase Requisition created and saved.",
        "next": "Approval routing in progress - finding the right approver based on amount and department.",
        "step": "6 of 15",
    },
    "approval_routing": {
        "done": "Approval workflow created - sent to the appropriate manager.",
        "next": "Waiting for manager approval. Type: 'Approve PR [number]' or check status on Pending Approvals page.",
        "action_needed": True,
        "step": "7 of 15",
    },
    "approval_wait": {
        "done": "Manager approved the purchase.",
        "next": "Purchase Order is being created from the approved PR.",
        "step": "8 of 15",
    },
    "po_creation": {
        "done": "Purchase Order created and sent to vendor.",
        "next": "Delivery tracking started. The system monitors until goods arrive. When they arrive, type: 'Goods received for PO [number]'",
        "action_needed": True,
        "step": "9 of 15",
    },
    "delivery_tracking": {
        "done": "Delivery is being tracked.",
        "next": "When goods arrive at your warehouse, confirm receipt. Type: 'Goods received for PO [number]'",
        "action_needed": True,
        "step": "10 of 15",
    },
    "grn_entry": {
        "done": "Goods Receipt confirmed - items received at warehouse.",
        "next": "Quality inspection will run automatically to check the received goods.",
        "step": "11 of 15",
    },
    "quality_inspection": {
        "done": "Quality inspection completed.",
        "next": "Invoice matching is next - the system will match the vendor's invoice against the PO.",
        "step": "12 of 15",
    },
    "invoice_matching": {
        "done": "Invoice matched against Purchase Order.",
        "next": "3-way match is next - comparing PO vs GRN vs Invoice to catch discrepancies.",
        "step": "13 of 15",
    },
    "three_way_match": {
        "done": "3-way match completed (PO vs GRN vs Invoice).",
        "next": "Payment readiness check is next - verifying all conditions are met before payment.",
        "step": "14 of 15",
    },
    "payment_readiness": {
        "done": "Payment readiness confirmed - all conditions met.",
        "next": "Payment will now be calculated and executed. Almost done!",
        "step": "15 of 15",
    },
    "payment_execution": {
        "done": "Payment processed! The full procure-to-pay cycle is COMPLETE.",
        "next": "You can now: reconcile the payment, check spend analytics, or start a new procurement.",
        "final": True,
        "step": "DONE",
    },
}


def get_guided_status(workflow_run_id: str) -> dict:
    """Get user-friendly guided status: what happened, what's next, what to type."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT task_name, status, output_data
            FROM workflow_tasks WHERE workflow_run_id = %s ORDER BY id
        """, (workflow_run_id,))
        tasks = cur.fetchall()

        completed_steps = []
        current_step = None
        next_step = None
        waiting_for = None

        for t in tasks:
            if t['status'] == 'completed':
                completed_steps.append(t['task_name'])
            elif t['status'] == 'waiting_human':
                current_step = t['task_name']
                waiting_for = t['task_name']
                break
            elif t['status'] == 'running':
                current_step = t['task_name']
                break
            elif t['status'] == 'pending' and next_step is None:
                next_step = t['task_name']

        last_done = completed_steps[-1] if completed_steps else None
        progress = round((len(completed_steps) / len(tasks)) * 100) if tasks else 0

        guide = P2P_GUIDE.get(last_done, {})

        # Build narrative
        narrative = ""
        if last_done:
            narrative = guide.get("done", "")
            narrative += "\n\n"
            narrative += guide.get("next", "")

        return {
            "success": True,
            "workflow_run_id": workflow_run_id,
            "progress": f"{len(completed_steps)}/{len(tasks)} steps ({progress}%)",
            "last_completed": last_done,
            "current_step": current_step or next_step,
            "waiting_for_human": waiting_for is not None,
            "what_happened": guide.get("done", ""),
            "what_next": guide.get("next", ""),
            "action_needed": guide.get("action_needed", False),
            "is_complete": guide.get("final", False),
            "step_label": guide.get("step", ""),
            "narrative": narrative.strip(),
        }
    except Exception as e:
        log.error("get_guided_status failed: %s", e)
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def _get_conn():
    return psycopg2.connect(DB_URL)


# ── Workflow Lifecycle ───────────────────────────────────────────────────────


def update_trigger_data(workflow_run_id: str, updates: dict) -> bool:
    """Merge new key-value pairs into an existing workflow's trigger_data.

    Used to persist late-bound fields (vendor_name, pr_number, etc.) that
    are determined mid-workflow but need to survive across resume calls.
    """
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT trigger_data FROM workflow_runs WHERE workflow_run_id = %s",
            (workflow_run_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        existing = row["trigger_data"]
        if isinstance(existing, str):
            existing = json.loads(existing)
        if not isinstance(existing, dict):
            existing = {}
        existing.update(updates)
        cur.execute(
            "UPDATE workflow_runs SET trigger_data = %s WHERE workflow_run_id = %s",
            (json.dumps(existing), workflow_run_id),
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.warning("update_trigger_data failed for %s: %s", workflow_run_id, exc)
        return False


def create_workflow(workflow_type: str, trigger_data: dict, created_by: str = 'system') -> dict:
    """Create a new workflow run with all its tasks.

    Returns: dict with workflow_run_id, tasks created, status
    """
    if workflow_type not in WORKFLOW_TEMPLATES:
        return {'success': False, 'error': f'Unknown workflow type: {workflow_type}'}

    template = WORKFLOW_TEMPLATES[workflow_type]
    workflow_run_id = f"WF-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    conn = _get_conn()
    cur = conn.cursor()

    try:
        # Create workflow run
        cur.execute("""
            INSERT INTO workflow_runs
                (workflow_run_id, workflow_type, trigger_source, trigger_data,
                 status, total_tasks, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (workflow_run_id, workflow_type, 'chat',
              json.dumps(trigger_data), WORKFLOW_RUNNING,
              len(template['tasks']), created_by))

        # Create tasks
        task_ids = {}
        for task_def in template['tasks']:
            task_id = f"T-{uuid.uuid4().hex[:8]}"
            task_ids[task_def['name']] = task_id

            # Resolve dependency task IDs
            dep_ids = [task_ids[d] for d in task_def.get('depends_on', []) if d in task_ids]

            initial_status = TASK_PENDING
            wait_type = task_def.get('wait_type') if task_def['type'] == 'human' else None

            cur.execute("""
                INSERT INTO workflow_tasks
                    (task_id, workflow_run_id, task_name, task_type, agent_name,
                     status, depends_on, wait_type, input_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (task_id, workflow_run_id, task_def['name'], task_def['type'],
                  task_def.get('agent', ''), initial_status, dep_ids or None,
                  wait_type, json.dumps(trigger_data)))

        # Emit workflow_created event
        _emit_event(cur, workflow_run_id, None, 'workflow_created', {
            'workflow_type': workflow_type,
            'total_tasks': len(template['tasks']),
            'trigger_data': trigger_data,
        })

        conn.commit()
        log.info("Workflow created: %s (%s, %d tasks)", workflow_run_id, workflow_type, len(template['tasks']))

        return {
            'success': True,
            'workflow_run_id': workflow_run_id,
            'workflow_type': workflow_type,
            'total_tasks': len(template['tasks']),
            'status': WORKFLOW_RUNNING,
        }

    except Exception as e:
        conn.rollback()
        log.error("create_workflow failed: %s", e)
        return {'success': False, 'error': str(e)}
    finally:
        cur.close()
        conn.close()


def advance_workflow(workflow_run_id: str) -> dict:
    """Check for ready tasks (all dependencies met) and execute them.

    Returns: list of tasks that were started/completed
    """
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get all tasks for this workflow
        cur.execute("""
            SELECT task_id, task_name, task_type, agent_name, status,
                   depends_on, wait_type, input_data, output_data
            FROM workflow_tasks WHERE workflow_run_id = %s
            ORDER BY id
        """, (workflow_run_id,))
        tasks = cur.fetchall()

        if not tasks:
            return {'success': False, 'error': 'No tasks found'}

        # Build completed set
        completed_ids = set(t['task_id'] for t in tasks if t['status'] == TASK_COMPLETED)
        advanced = []

        for task in tasks:
            if task['status'] != TASK_PENDING:
                continue

            # Check if all dependencies are completed
            deps = task['depends_on'] or []
            if all(d in completed_ids for d in deps):
                # This task is ready to run
                if task['task_type'] == 'human':
                    # Pause for human input
                    cur.execute("""
                        UPDATE workflow_tasks SET status = %s, started_at = NOW()
                        WHERE task_id = %s
                    """, (TASK_WAITING_HUMAN, task['task_id']))
                    _emit_event(cur, workflow_run_id, task['task_id'], 'task_waiting_human', {
                        'task_name': task['task_name'],
                        'wait_type': task['wait_type'],
                    })
                    advanced.append({
                        'task_id': task['task_id'],
                        'task_name': task['task_name'],
                        'new_status': TASK_WAITING_HUMAN,
                        'wait_type': task['wait_type'],
                    })
                else:
                    # Mark as running (agent will be invoked by caller)
                    cur.execute("""
                        UPDATE workflow_tasks SET status = %s, started_at = NOW()
                        WHERE task_id = %s
                    """, (TASK_RUNNING, task['task_id']))
                    _emit_event(cur, workflow_run_id, task['task_id'], 'task_started', {
                        'task_name': task['task_name'],
                        'agent': task['agent_name'],
                    })
                    advanced.append({
                        'task_id': task['task_id'],
                        'task_name': task['task_name'],
                        'new_status': TASK_RUNNING,
                        'agent': task['agent_name'],
                    })

        conn.commit()

        # Update workflow status (separate transaction for safety)
        try:
            conn2 = _get_conn()
            cur2 = conn2.cursor()
            _update_workflow_status(cur2, workflow_run_id)
            conn2.commit()
            cur2.close()
            conn2.close()
        except Exception as e2:
            log.warning("workflow status update failed (non-blocking): %s", e2)

        return {'success': True, 'advanced': advanced}

    except Exception as e:
        conn.rollback()
        log.error("advance_workflow failed: %s", e)
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}
    finally:
        cur.close()
        conn.close()


def complete_task(task_id: str, result: dict = None) -> dict:
    """Mark a task as completed and trigger downstream tasks.

    Returns: events triggered, next tasks ready
    """
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get task
        cur.execute("SELECT * FROM workflow_tasks WHERE task_id = %s", (task_id,))
        task = cur.fetchone()
        if not task:
            return {'success': False, 'error': 'Task not found'}

        # Update task
        cur.execute("""
            UPDATE workflow_tasks
            SET status = %s, output_data = %s, completed_at = NOW(),
                execution_time_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
            WHERE task_id = %s
        """, (TASK_COMPLETED, json.dumps(result or {}), task_id))

        # Emit completion event
        event_type = 'task_completed'
        # Map task names to business events
        event_map = {
            'compliance_check': 'compliance_passed',
            'budget_verification': 'budget_verified',
            'vendor_selection': 'vendor_selected',
            'vendor_confirmation': 'vendor_confirmed',
            'pr_creation': 'pr_created',
            'approval_routing': 'approval_routed',
            'approval_wait': 'approval_completed',
            'po_creation': 'po_created',
            'invoice_capture': 'invoice_captured',
            'invoice_matching': 'match_completed',
            'payment_approval_wait': 'payment_approved',
            'payment_execution': 'payment_executed',
            'grn_entry': 'goods_received',
            'quality_inspection': 'inspection_complete',
            'three_way_match': 'three_way_match_completed',
            'payment_readiness': 'payment_ready',
            'delivery_tracking': 'delivery_tracked',
            'payment_calculation': 'payment_calculated',
        }
        business_event = event_map.get(task['task_name'], event_type)

        _emit_event(cur, task['workflow_run_id'], task_id, business_event, {
            'task_name': task['task_name'],
            'result': result,
        })

        # Update workflow counters
        cur.execute("""
            UPDATE workflow_runs
            SET completed_tasks = completed_tasks + 1,
                current_task_id = %s
            WHERE workflow_run_id = %s
        """, (task_id, task['workflow_run_id']))

        conn.commit()
        wf_run_id = task['workflow_run_id']

        # Update workflow status (separate cursor to avoid state issues)
        try:
            cur2 = conn.cursor()
            _update_workflow_status(cur2, wf_run_id)
            conn.commit()
            cur2.close()
        except Exception:
            pass

        cur.close()
        conn.close()

        # Auto-advance to find next ready tasks
        next_result = advance_workflow(wf_run_id)

        return {
            'success': True,
            'task_id': task_id,
            'task_name': task['task_name'],
            'event': business_event,
            'next_tasks': next_result.get('advanced', []),
        }

    except Exception as e:
        log.error("complete_task failed: %s", e)
        try:
            if conn and not conn.closed:
                conn.rollback()
                cur.close()
                conn.close()
        except Exception:
            pass
        return {'success': False, 'error': str(e)}


def fail_task(task_id: str, error: str) -> dict:
    """Mark a task as failed. Retry if under max_retries."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("SELECT * FROM workflow_tasks WHERE task_id = %s", (task_id,))
        task = cur.fetchone()
        if not task:
            return {'success': False, 'error': 'Task not found'}

        if task['retry_count'] < task['max_retries']:
            # Retry
            cur.execute("""
                UPDATE workflow_tasks
                SET status = %s, retry_count = retry_count + 1, error_message = %s
                WHERE task_id = %s
            """, (TASK_RETRYING, error, task_id))
            _emit_event(cur, task['workflow_run_id'], task_id, 'task_retrying', {
                'retry_count': task['retry_count'] + 1,
                'error': error,
            })
            status = TASK_RETRYING
        else:
            # Final failure
            cur.execute("""
                UPDATE workflow_tasks
                SET status = %s, error_message = %s, completed_at = NOW()
                WHERE task_id = %s
            """, (TASK_FAILED, error, task_id))
            cur.execute("""
                UPDATE workflow_runs SET failed_tasks = failed_tasks + 1
                WHERE workflow_run_id = %s
            """, (task['workflow_run_id'],))
            _emit_event(cur, task['workflow_run_id'], task_id, 'task_failed', {
                'error': error, 'retries_exhausted': True,
            })
            status = TASK_FAILED

        _update_workflow_status(cur, task['workflow_run_id'])
        conn.commit()

        return {'success': True, 'task_id': task_id, 'status': status}

    except Exception as e:
        conn.rollback()
        log.error("fail_task failed: %s", e)
        return {'success': False, 'error': str(e)}
    finally:
        cur.close()
        conn.close()


def resume_from_human(task_id: str, human_input: dict) -> dict:
    """Resume a task that was waiting for human input (approval, vendor selection, etc.)."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("SELECT * FROM workflow_tasks WHERE task_id = %s AND status = %s",
                     (task_id, TASK_WAITING_HUMAN))
        task = cur.fetchone()
        if not task:
            return {'success': False, 'error': 'Task not found or not waiting for human input'}

        # Store human input and mark as completed
        cur.execute("""
            UPDATE workflow_tasks
            SET status = %s, output_data = %s, completed_at = NOW()
            WHERE task_id = %s
        """, (TASK_COMPLETED, json.dumps(human_input), task_id))

        _emit_event(cur, task['workflow_run_id'], task_id, 'human_input_received', {
            'task_name': task['task_name'],
            'wait_type': task['wait_type'],
            'input': human_input,
        })

        cur.execute("""
            UPDATE workflow_runs SET completed_tasks = completed_tasks + 1
            WHERE workflow_run_id = %s
        """, (task['workflow_run_id'],))

        _update_workflow_status(cur, task['workflow_run_id'])
        conn.commit()

        # Auto-advance
        next_result = advance_workflow(task['workflow_run_id'])

        return {
            'success': True,
            'task_id': task_id,
            'task_name': task['task_name'],
            'resumed': True,
            'next_tasks': next_result.get('advanced', []),
        }

    except Exception as e:
        conn.rollback()
        log.error("resume_from_human failed: %s", e)
        return {'success': False, 'error': str(e)}
    finally:
        cur.close()
        conn.close()


def get_workflow_status(workflow_run_id: str) -> dict:
    """Get full workflow state including all tasks and events."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Workflow header
        cur.execute("SELECT * FROM workflow_runs WHERE workflow_run_id = %s", (workflow_run_id,))
        workflow = cur.fetchone()
        if not workflow:
            return {'success': False, 'error': 'Workflow not found'}

        # Tasks
        cur.execute("""
            SELECT task_id, task_name, task_type, agent_name, status,
                   wait_type, retry_count, started_at, completed_at,
                   execution_time_ms, error_message
            FROM workflow_tasks WHERE workflow_run_id = %s ORDER BY id
        """, (workflow_run_id,))
        tasks = cur.fetchall()

        # Events
        cur.execute("""
            SELECT event_type, task_id, event_data, created_at
            FROM workflow_events WHERE workflow_run_id = %s ORDER BY created_at
        """, (workflow_run_id,))
        events = cur.fetchall()

        # Serialize
        for t in tasks:
            for k, v in t.items():
                if hasattr(v, 'isoformat'):
                    t[k] = v.isoformat()
        for e in events:
            for k, v in e.items():
                if hasattr(v, 'isoformat'):
                    e[k] = v.isoformat()
        for k, v in workflow.items():
            if hasattr(v, 'isoformat'):
                workflow[k] = v.isoformat()

        return {
            'success': True,
            'workflow': dict(workflow),
            'tasks': [dict(t) for t in tasks],
            'events': [dict(e) for e in events],
        }

    except Exception as e:
        log.error("get_workflow_status failed: %s", e)
        return {'success': False, 'error': str(e)}
    finally:
        cur.close()
        conn.close()


def list_workflows(status: str = None, workflow_type: str = None, limit: int = 50) -> list:
    """List workflow runs with optional filters."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        conditions = []
        params = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if workflow_type:
            conditions.append("workflow_type = %s")
            params.append(workflow_type)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        cur.execute(f"""
            SELECT workflow_run_id, workflow_type, status, total_tasks,
                   completed_tasks, failed_tasks, pr_number, po_number,
                   started_at, completed_at
            FROM workflow_runs {where}
            ORDER BY started_at DESC LIMIT %s
        """, params)

        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'):
                    r[k] = v.isoformat()
        return [dict(r) for r in rows]

    except Exception as e:
        log.error("list_workflows failed: %s", e)
        return []
    finally:
        cur.close()
        conn.close()


# ── P2P Suggestion & Summary Helpers ────────────────────────────────────────

def get_suggestions(workflow_run_id: str) -> dict:
    """Return context-aware next-action suggestions based on the last completed task."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT task_id, task_name, status, wait_type
            FROM workflow_tasks WHERE workflow_run_id = %s ORDER BY id
        """, (workflow_run_id,))
        tasks = cur.fetchall()

        last_completed = None
        current_waiting = None
        for t in tasks:
            if t['status'] == TASK_COMPLETED:
                last_completed = t
            if t['status'] == TASK_WAITING_HUMAN:
                current_waiting = t

        suggestions = []
        current_step = None

        if last_completed:
            suggestions = P2P_SUGGESTIONS.get(last_completed['task_name'], [])
            current_step = last_completed['task_name']

        return {
            'success': True,
            'suggestions': suggestions,
            'current_step': current_step,
            'waiting_for': current_waiting['wait_type'] if current_waiting else None,
            'waiting_task_id': current_waiting['task_id'] if current_waiting else None,
        }

    except Exception as e:
        log.error("get_suggestions failed: %s", e)
        return {'success': False, 'suggestions': [], 'error': str(e)}
    finally:
        cur.close()
        conn.close()


def generate_workflow_summary(workflow_run_id: str) -> dict:
    """Build a narrative summary of all completed steps in a workflow."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT task_name, task_type, agent_name, status, output_data
            FROM workflow_tasks WHERE workflow_run_id = %s ORDER BY id
        """, (workflow_run_id,))
        tasks = cur.fetchall()

        if not tasks:
            return {'success': False, 'error': 'No tasks found'}

        total = len(tasks)
        completed = sum(1 for t in tasks if t['status'] == TASK_COMPLETED)
        failed = sum(1 for t in tasks if t['status'] == TASK_FAILED)
        waiting = sum(1 for t in tasks if t['status'] == TASK_WAITING_HUMAN)
        progress_pct = round((completed / total) * 100, 1) if total > 0 else 0

        steps = []
        summary_parts = []
        for t in tasks:
            step_info = {
                'name': t['task_name'],
                'status': t['status'],
                'agent': t['agent_name'] or 'human',
            }
            # Extract key summary from output_data
            out = t.get('output_data') or {}
            if isinstance(out, str):
                try:
                    out = json.loads(out)
                except Exception:
                    out = {}
            if isinstance(out, dict):
                step_info['summary'] = out.get('summary', out.get('message', ''))
            steps.append(step_info)

            # Build narrative
            status_label = t['status'].replace('_', ' ').title()
            if t['status'] == TASK_COMPLETED:
                summary_parts.append(f"{t['task_name'].replace('_', ' ').title()}: {status_label}")
            elif t['status'] == TASK_WAITING_HUMAN:
                summary_parts.append(f"{t['task_name'].replace('_', ' ').title()}: Awaiting Input")
            elif t['status'] == TASK_FAILED:
                summary_parts.append(f"{t['task_name'].replace('_', ' ').title()}: Failed")

        narrative = ". ".join(summary_parts) + "." if summary_parts else "Workflow started."

        return {
            'success': True,
            'summary': narrative,
            'progress_pct': progress_pct,
            'completed': completed,
            'total': total,
            'failed': failed,
            'waiting': waiting,
            'steps': steps,
        }

    except Exception as e:
        log.error("generate_workflow_summary failed: %s", e)
        return {'success': False, 'error': str(e)}
    finally:
        cur.close()
        conn.close()


# ── Internal Helpers ─────────────────────────────────────────────────────────

def _emit_event(cur, workflow_run_id, task_id, event_type, event_data):
    """Insert an event into workflow_events."""
    event_id = f"EVT-{uuid.uuid4().hex[:8]}"
    cur.execute("""
        INSERT INTO workflow_events (event_id, workflow_run_id, task_id, event_type, event_data)
        VALUES (%s, %s, %s, %s, %s)
    """, (event_id, workflow_run_id, task_id, event_type, json.dumps(event_data)))


def _update_workflow_status(cur, workflow_run_id):
    """Recalculate workflow status from its tasks."""
    try:
        cur.execute(
            "SELECT status FROM workflow_tasks WHERE workflow_run_id = %s",
            (workflow_run_id,)
        )
        statuses = [r[0] for r in cur.fetchall()]

        if not statuses:
            return

        if all(s == TASK_COMPLETED for s in statuses):
            cur.execute(
                "UPDATE workflow_runs SET status = %s, completed_at = NOW() WHERE workflow_run_id = %s",
                (WORKFLOW_COMPLETED, workflow_run_id)
            )
        elif any(s == TASK_FAILED for s in statuses):
            cur.execute(
                "UPDATE workflow_runs SET status = %s WHERE workflow_run_id = %s",
                (WORKFLOW_FAILED, workflow_run_id)
            )
        elif any(s == TASK_WAITING_HUMAN for s in statuses):
            cur.execute(
                "UPDATE workflow_runs SET status = %s WHERE workflow_run_id = %s",
                (WORKFLOW_WAITING, workflow_run_id)
            )
        elif any(s == TASK_RUNNING for s in statuses):
            cur.execute(
                "UPDATE workflow_runs SET status = %s WHERE workflow_run_id = %s",
                (WORKFLOW_RUNNING, workflow_run_id)
            )
    except Exception as e:
        log.warning("_update_workflow_status non-critical error: %s", e)
