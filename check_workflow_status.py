"""
Procure-AI: Workflow Status Checker
Checks all active workflows, explains why they're paused,
and lists actions needed to unblock payment.
"""
import json, os, psycopg2
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# ── Step name metadata ──
STEP_MAP = {
    'compliance_check': ('1', 'Compliance Check'),
    'budget_verification': ('2', 'Budget Verification'),
    'vendor_selection': ('3', 'Vendor Selection'),
    'vendor_confirmation': ('4', 'Vendor Confirmation'),
    'pr_creation': ('5', 'PR Creation'),
    'approval_routing': ('6', 'Approval Routing'),
    'approval_wait': ('7', 'Manager Approval'),
    'po_creation': ('8', 'PO Creation'),
    'delivery_tracking': ('9', 'Delivery Tracking'),
    'grn_entry': ('10', 'Goods Receipt'),
    'quality_inspection': ('11', 'Quality Inspection'),
    'invoice_matching': ('12', 'Invoice Matching'),
    'three_way_match': ('13', '3-Way Match'),
    'payment_readiness': ('14', 'Payment Readiness'),
    'payment_execution': ('15', 'Payment Execution'),
}

PAYMENT_PREREQS = [
    ('vendor_confirmation', 'Select vendor from shortlist', 'Go to Pipeline page > select vendor card'),
    ('approval_wait', 'Get manager approval for PR', 'Go to Pending Approvals > approve PR'),
    ('po_creation', 'PO must be created', 'Automatic after approval'),
    ('delivery_tracking', 'Delivery must be tracked', 'Automatic after PO creation'),
    ('grn_entry', 'Confirm goods received', 'Go to Goods Receipt page > confirm delivery'),
    ('quality_inspection', 'Pass quality inspection', 'Automatic after GRN'),
    ('invoice_matching', 'Match invoice to PO', 'Automatic after QC'),
    ('three_way_match', 'Verify 3-way match (PO+GRN+Invoice)', 'Automatic after invoice match'),
    ('payment_readiness', 'Pass payment readiness check', 'Automatic after 3-way match'),
    ('payment_execution', 'Execute payment', 'Automatic / final release approval'),
]

SEP = '=' * 95

# ── Get all workflows ──
cur.execute("""
    SELECT workflow_run_id, workflow_type, status, started_at, completed_at,
           trigger_data::text, total_tasks, completed_tasks, failed_tasks,
           pr_number, po_number, created_by
    FROM workflow_runs
    ORDER BY started_at DESC
    LIMIT 10
""")
workflows = cur.fetchall()

print(SEP)
print("  PROCURE-AI WORKFLOW STATUS REPORT")
print(SEP)
print(f"  Total workflows found: {len(workflows)}")
print()

# ── Summary table ──
for r in workflows:
    wf_id, wf_type, status, started, completed, trigger_str, total, done, failed, pr_num, po_num, _ = r
    trigger = json.loads(trigger_str) if trigger_str else {}
    dept = trigger.get('department', '?')
    product = trigger.get('product_name', '?')[:25]
    budget = trigger.get('budget', 0)
    icon = {'running': '~', 'completed': 'OK', 'failed': 'X', 'paused': '||'}.get(status, '?')
    print(f"  [{icon:>2}] {wf_id}  {wf_type:<12}  {status:<18}  {dept:<10}  ${budget:>10,.0f}  {product}")

# ── Detailed analysis per workflow ──
for r in workflows:
    wf_id, wf_type, wf_status, started, completed, trigger_str, total, done_count, failed_count, pr_num, po_num, _ = r
    trigger = json.loads(trigger_str) if trigger_str else {}

    print()
    print(SEP)
    print(f"  WORKFLOW: {wf_id}")
    print(f"  Type: {wf_type}  |  Status: {wf_status}  |  Started: {str(started)[:19]}")
    print(f"  Dept: {trigger.get('department','?')}  |  Product: {trigger.get('product_name','?')}  |  Budget: ${trigger.get('budget',0):,.0f}  |  Qty: {trigger.get('quantity',0)}")
    if pr_num:
        print(f"  PR: {pr_num}")
    if po_num:
        print(f"  PO: {po_num}")
    print("-" * 95)

    # Get tasks
    cur.execute("""
        SELECT task_id, task_name, task_type, agent_name, status,
               output_data::text, wait_type, wait_reason,
               started_at, completed_at, execution_time_ms, error_message
        FROM workflow_tasks
        WHERE workflow_run_id = %s
        ORDER BY started_at ASC NULLS LAST, id ASC
    """, (wf_id,))
    tasks = cur.fetchall()

    completed_tasks = []
    waiting_tasks = []
    pending_tasks = []

    print()
    print("  PIPELINE STEPS:")
    for t in tasks:
        tid, tname, ttype, agent, tstatus, output_str, wait_type, wait_reason, tstarted, tcompleted, exec_ms, err = t
        output = json.loads(output_str) if output_str else {}
        step_num, step_label = STEP_MAP.get(tname, ('?', tname.replace('_', ' ').title()))

        icon = {
            'completed': '  [DONE]  ',
            'running':   '  [>>>]   ',
            'waiting_human': '  [!!]    ',
            'pending':   '  [...]   ',
            'failed':    '  [X]     ',
        }.get(tstatus, '  [?]     ')

        timing = f" ({exec_ms}ms)" if exec_ms else ""
        agent_label = f" [{agent}]" if agent else ""

        print(f"  {icon}Step {step_num:>2}: {step_label:<25}{agent_label}{timing}")

        if tstatus == 'completed':
            completed_tasks.append(tname)
            if output.get('action'):
                print(f"               Result: {output['action']}")
            if output.get('vendor'):
                print(f"               Vendor: {output['vendor']}")
            if output.get('pr_number'):
                print(f"               PR: {output['pr_number']}")
            if output.get('po_number'):
                print(f"               PO: {output['po_number']}")
        elif tstatus == 'waiting_human':
            waiting_tasks.append(tname)
            print(f"               BLOCKED: Waiting for human input")
            if wait_type:
                print(f"               Gate type: {wait_type}")
            if wait_reason:
                print(f"               Reason: {wait_reason}")
        elif tstatus == 'pending':
            pending_tasks.append(tname)
        elif tstatus == 'failed':
            if err:
                print(f"               Error: {err}")

    # ── Why is the pipeline paused? ──
    print()
    print("  WHY IS THE PIPELINE PAUSED?")
    if waiting_tasks:
        for wt in waiting_tasks:
            sn, sl = STEP_MAP.get(wt, ('?', wt))
            if wt == 'vendor_confirmation':
                print(f"  >> Step {sn} ({sl}): A vendor must be selected from the shortlist.")
                print(f"     The system found qualified vendors but needs YOUR confirmation.")
                print(f"     Without a vendor, the PR cannot be created.")
            elif wt == 'approval_wait':
                print(f"  >> Step {sn} ({sl}): Manager approval is required.")
                print(f"     The PR has been created and routed. A manager must approve or reject.")
                print(f"     Without approval, a PO cannot be generated.")
            elif wt == 'grn_entry':
                print(f"  >> Step {sn} ({sl}): Goods receipt confirmation is needed.")
                print(f"     The PO has been sent to the vendor. Confirm when goods arrive.")
                print(f"     Without GRN, invoice matching and payment cannot proceed.")
            else:
                print(f"  >> Step {sn} ({sl}): Human input required.")
    elif wf_status == 'completed':
        print(f"  >> Pipeline is COMPLETE. All {done_count} steps finished.")
    else:
        print(f"  >> Pipeline status: {wf_status}. May be actively processing.")

    # ── Actions to unblock payment ──
    print()
    print("  ACTIONS NEEDED TO UNBLOCK PAYMENT:")
    blocker_num = 0
    for prereq_name, desc, action in PAYMENT_PREREQS:
        if prereq_name not in completed_tasks:
            blocker_num += 1
            is_waiting = prereq_name in waiting_tasks
            marker = "ACTION REQUIRED" if is_waiting else "PENDING"
            print(f"    {blocker_num}. [{marker}] {desc}")
            if is_waiting:
                print(f"       How: {action}")

    if blocker_num == 0:
        print("    None! All prerequisites met. Payment complete or ready.")

    # ── Next action ──
    print()
    print("  NEXT ACTION:")
    if waiting_tasks:
        wt = waiting_tasks[0]
        sn, sl = STEP_MAP.get(wt, ('?', wt))
        if wt == 'vendor_confirmation':
            print(f"  -> Select a vendor: POST /api/agentic/p2p/resume (action=confirm_vendor)")
        elif wt == 'approval_wait':
            print(f"  -> Approve PR: POST /api/agentic/p2p/resume (action=approve)")
        elif wt == 'grn_entry':
            print(f"  -> Confirm goods received: POST /api/agentic/p2p/resume (action=confirm_grn)")
        else:
            print(f"  -> Resolve '{wt}' via Pipeline page or resume endpoint")
    elif wf_status == 'completed':
        print("  -> No action needed. Workflow complete.")
    else:
        print(f"  -> Monitor. Status: {wf_status}")

# ── Audit trail for latest ──
if workflows:
    latest_id = workflows[0][0]
    cur.execute("""
        SELECT event_type, event_data::text, source_agent, created_at
        FROM workflow_events
        WHERE workflow_run_id = %s
        ORDER BY created_at ASC
    """, (latest_id,))
    events = cur.fetchall()

    if events:
        print()
        print(SEP)
        print(f"  AUDIT TRAIL FOR: {latest_id}")
        print(SEP)
        for e in events:
            etype, edata_str, agent, ecreated = e
            edata = json.loads(edata_str) if edata_str else {}
            task_name = edata.get('task_name', '')
            print(f"  {str(ecreated)[:19]}  |  {etype:<30}  |  {task_name}")

print()
print(SEP)
cur.close()
conn.close()
