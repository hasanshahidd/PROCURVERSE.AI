"""Test complete PR_TO_PO workflow flow."""
import os
os.environ['DATABASE_URL'] = 'postgresql://postgres:YourStr0ng!Pass@127.0.0.1:5433/odoo_procurement_demo'

from backend.services.workflow_engine import (
    create_workflow, advance_workflow, complete_task,
    resume_from_human, get_workflow_status
)

print("WORKFLOW ENGINE - FULL PR_TO_PO FLOW")
print("=" * 60)

# 1. Create
r = create_workflow('PR_TO_PO', {'dept': 'Engineering', 'product': 'Bearings', 'qty': 500})
wf_id = r['workflow_run_id']
print("1. Created: %s (%d tasks)" % (wf_id, r['total_tasks']))

def next_task(result):
    """Extract next task ID from advance/complete result."""
    tasks = result.get('next_tasks', result.get('advanced', []))
    if tasks:
        t = tasks[0]
        print("   -> %s: %s" % (t['task_name'], t['new_status']))
        return t['task_id']
    return None

# 2. Advance (compliance_check)
r2 = advance_workflow(wf_id)
tid = next_task(r2)
print("2. compliance_check started: %s" % ("OK" if tid else "FAIL"))

# 3. Complete compliance -> budget starts
r3 = complete_task(tid, {'passed': True})
tid = next_task(r3)
print("3. compliance done, event=%s" % r3.get('event'))

# 4. Complete budget -> vendor starts
r4 = complete_task(tid, {'budget_ok': True})
tid = next_task(r4)
print("4. budget done, event=%s" % r4.get('event'))

# 5. Complete vendor -> vendor_confirmation (HUMAN wait)
r5 = complete_task(tid, {'top_vendor': 'Lopez-Sweeney'})
tid = next_task(r5)
print("5. vendor done, event=%s" % r5.get('event'))

# 6. Human confirms vendor -> pr_creation starts
r6 = resume_from_human(tid, {'vendor_confirmed': True})
tid = next_task(r6)
print("6. vendor confirmed (human), resumed=%s" % r6.get('resumed'))

# 7. Complete PR creation -> approval_routing starts
r7 = complete_task(tid, {'pr_number': 'PR-2026-WF-TEST'})
tid = next_task(r7)
print("7. PR created, event=%s" % r7.get('event'))

# 8. Complete approval routing -> approval_wait (HUMAN)
r8 = complete_task(tid, {'routed_to': 'Manager'})
tid = next_task(r8)
print("8. approval routed, event=%s" % r8.get('event'))

# 9. Human approves -> po_creation starts
r9 = resume_from_human(tid, {'approved': True, 'approver': 'Manager'})
tid = next_task(r9)
print("9. approved (human), resumed=%s" % r9.get('resumed'))

# 10. Complete PO creation -> notification starts
r10 = complete_task(tid, {'po_number': 'PO-2026-WF-TEST'})
tid = next_task(r10)
print("10. PO created, event=%s" % r10.get('event'))

# 11. Complete notification -> workflow DONE
r11 = complete_task(tid, {'notified': True})
print("11. notification done, event=%s" % r11.get('event'))

# Final status
print("\n" + "=" * 60)
print("FINAL STATUS")
print("=" * 60)
status = get_workflow_status(wf_id)
wf = status['workflow']
print("  Workflow: %s" % wf['status'])
print("  Completed: %d/%d" % (wf['completed_tasks'], wf['total_tasks']))
print("  Events: %d" % len(status['events']))
print("\n  Tasks:")
for t in status['tasks']:
    print("    %s  %s" % (t['task_name'].ljust(25), t['status']))
print("\n  Events:")
for e in status['events']:
    print("    %s" % e['event_type'])

all_done = all(t['status'] == 'completed' for t in status['tasks'])
print("\n  ALL TASKS COMPLETED: %s" % all_done)
print("  WORKFLOW STATUS: %s" % wf['status'])
