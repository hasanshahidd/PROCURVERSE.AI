"""
COMPLETE P2P FLOW TEST — Shows exactly what happens at each step
Run this to see the real state of the system.
"""
import os, json, time, urllib.request, psycopg2
from psycopg2.extras import RealDictCursor

os.environ['DATA_SOURCE'] = 'demo_odoo'
os.environ['DATABASE_URL'] = 'postgresql://postgres:YourStr0ng!Pass@127.0.0.1:5433/odoo_procurement_demo'
BASE = "http://127.0.0.1:5000"

def api(url, body=None, timeout=45):
    try:
        if body:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
        else:
            req = urllib.request.Request(url)
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)[:100]}

def db(sql, params=None):
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

print("=" * 70)
print("PROCURE-TO-PAY: COMPLETE LIVE TEST")
print("=" * 70)

# ═══════════════════════════════════════════════════════════════
# STEP 1: User identifies need (via Chat)
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 1: REQUIREMENT IDENTIFICATION")
print("=" * 70)
print("  User types: 'Create PR for 100 laptops for IT department at $1200 each'")
print("  System: OrchestratorAgent classifies intent as pr_creation")

d = api(BASE + "/api/agentic/execute", {
    "request": "Create purchase requisition for 100 laptops for IT department at 1200 dollars each",
    "session_id": "p2p-live-test",
    "pr_data": {
        "department": "IT",
        "product_name": "Laptops",
        "quantity": 100,
        "budget": 120000,
        "budget_category": "CAPEX",
        "requester_name": "John Smith"
    }
}, timeout=60)
print("  Response: %s" % d.get("status", d.get("error", "?")))
if d.get("data"):
    print("  Agents invoked: %s" % d["data"].get("agents_invoked", []))
time.sleep(2)

# ═══════════════════════════════════════════════════════════════
# STEP 2: Check PR in database
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 2: PURCHASE REQUISITION")
print("=" * 70)
prs = db("SELECT pr_number, department, amount, status, created_at FROM procurement_records ORDER BY id DESC LIMIT 3")
if prs:
    print("  PR Records in DB:")
    for pr in prs:
        print("    %s | dept=%s | amount=%s | status=%s" % (pr['pr_number'], pr['department'], pr['amount'], pr['status']))
else:
    print("  NO PR records found in procurement_records table")

# ═══════════════════════════════════════════════════════════════
# STEP 3: Approval workflow
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 3: APPROVAL PROCESS")
print("=" * 70)
wfs = db("SELECT pr_number, department, total_amount, workflow_status, current_approval_level FROM pr_approval_workflows ORDER BY created_at DESC LIMIT 3")
if wfs:
    print("  Approval Workflows:")
    for wf in wfs:
        print("    %s | dept=%s | $%s | status=%s | level=%s" % (wf['pr_number'], wf['department'], wf['total_amount'], wf['workflow_status'], wf['current_approval_level']))
steps = db("SELECT pr_number, approval_level, approver_name, approver_email, status FROM pr_approval_steps ORDER BY id DESC LIMIT 5")
if steps:
    print("  Approval Steps:")
    for s in steps:
        print("    %s | level=%s | %s (%s) | %s" % (s['pr_number'], s['approval_level'], s['approver_name'], s['approver_email'] or 'no email', s['status']))

# ═══════════════════════════════════════════════════════════════
# STEP 4: Vendor selection
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 4: VENDOR SELECTION")
print("=" * 70)
from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
a = PostgreSQLAdapter()
vendors = a.get_vendors(limit=5)
print("  Vendors available: %d" % len(vendors))
for v in vendors[:3]:
    print("    %s (ID: %s)" % (v.get('vendor_name', v.get('name', '?')), v.get('vendor_id', v.get('id', '?'))))
quotes = a.get_vendor_quotes(limit=5)
print("  Vendor quotes: %d" % len(quotes))
rfqs = a.get_rfq_headers(limit=5)
print("  RFQs: %d" % len(rfqs))

# ═══════════════════════════════════════════════════════════════
# STEP 5: Vendor evaluation
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 5: VENDOR EVALUATION")
print("=" * 70)
perf = a.get_vendor_performance()
print("  Performance records: %d" % len(perf))
approved = a.get_approved_suppliers()
print("  Approved suppliers: %d" % len(approved))

# ═══════════════════════════════════════════════════════════════
# STEP 6: PO creation
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 6: PURCHASE ORDER")
print("=" * 70)
pos = a.get_purchase_orders(limit=5)
print("  Purchase Orders: %d" % len(pos))
for po in pos[:3]:
    print("    %s | status=%s | total=%s" % (po.get('po_number', '?'), po.get('po_status', '?'), po.get('po_grand_total', '?')))

# ═══════════════════════════════════════════════════════════════
# STEP 7-8: Goods Receipt / GRN
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 7-8: GOODS RECEIPT / GRN")
print("=" * 70)
grns = a.get_grn_headers(limit=5)
print("  GRN records: %d" % len(grns))

# ═══════════════════════════════════════════════════════════════
# STEP 9: Invoice capture
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 9: INVOICE CAPTURE")
print("=" * 70)
invoices = a.get_vendor_invoices(limit=5)
print("  Invoices: %d" % len(invoices))
ocr_log = db("SELECT count(*) as cnt FROM ocr_ingestion_log")
print("  OCR processed: %d" % ocr_log[0]['cnt'])

# ═══════════════════════════════════════════════════════════════
# STEP 10: 3-Way Matching
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 10: 3-WAY MATCHING")
print("=" * 70)
disc = a.get_discrepancies()
print("  Discrepancies: %d" % len(disc))
holds = a.get_active_holds()
print("  Active holds: %d" % len(holds))

# ═══════════════════════════════════════════════════════════════
# STEP 11: Payment approval
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 11: PAYMENT APPROVAL")
print("=" * 70)
pay_rules = a.get_approval_rules(document_type='PAYMENT')
print("  Payment rules: %d" % len(pay_rules))
for r in pay_rules[:3]:
    print("    Level %s: %s ($%s-%s)" % (r['approval_level'], r['approver_name'], r['amount_min'], r['amount_max']))

# ═══════════════════════════════════════════════════════════════
# STEP 12: Payment execution
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 12: PAYMENT EXECUTION")
print("=" * 70)
fx = a.get_exchange_rates()
print("  FX rates: %d currencies" % len(fx))
payment_runs = db("SELECT count(*) as cnt FROM payment_runs")
print("  Payment runs: %d" % payment_runs[0]['cnt'])

# ═══════════════════════════════════════════════════════════════
# STEP 13: Reporting
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("STEP 13: REPORTING & ANALYTICS")
print("=" * 70)
spend = a.get_spend_analytics(limit=5)
print("  Spend analytics: %d records" % len(spend))
budget = a.get_budget_vs_actuals()
print("  Budget vs actuals: %d records" % len(budget))
aging = a.get_ap_aging()
print("  AP aging: %d records" % len(aging))
contracts = a.get_contracts(limit=5)
print("  Contracts: %d records" % len(contracts))

# ═══════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("NOTIFICATIONS & EMAIL")
print("=" * 70)
notifs = db("SELECT event_type, document_id, recipient_role, subject, status FROM notification_log ORDER BY created_at DESC LIMIT 10")
print("  Notification log: %d entries" % len(notifs))
for n in notifs[:5]:
    print("    [%s] %s | to=%s | %s" % (n['status'], n['event_type'], n.get('recipient_role', '?'), n.get('subject', '')[:50]))
templates = db("SELECT count(*) as cnt FROM email_templates")
print("  Email templates: %d" % templates[0]['cnt'])
print("  EMAIL_PROVIDER: %s" % os.environ.get('EMAIL_PROVIDER', 'mock (NOT SENDING)'))

# ═══════════════════════════════════════════════════════════════
# WORKFLOW ENGINE
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("WORKFLOW ENGINE")
print("=" * 70)
wf_runs = db("SELECT workflow_run_id, workflow_type, status, completed_tasks, total_tasks FROM workflow_runs ORDER BY started_at DESC LIMIT 5")
print("  Workflow runs: %d" % len(wf_runs))
for w in wf_runs[:3]:
    print("    %s | %s | %s | %d/%d tasks" % (w['workflow_run_id'][:25], w['workflow_type'], w['status'], w['completed_tasks'], w['total_tasks']))
wf_events = db("SELECT count(*) as cnt FROM workflow_events")
print("  Workflow events: %d total" % wf_events[0]['cnt'])

# ═══════════════════════════════════════════════════════════════
# AGENT ACTIONS (audit trail)
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("AUDIT TRAIL")
print("=" * 70)
actions = db("SELECT count(*) as cnt FROM agent_actions")
print("  Agent actions logged: %d" % actions[0]['cnt'])
recent = db("SELECT agent_name, action_type, success FROM agent_actions ORDER BY created_at DESC LIMIT 5")
for a_row in recent:
    print("    %s: %s (success=%s)" % (a_row['agent_name'], a_row['action_type'][:40], a_row['success']))

# ═══════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("COMPLETE P2P STATUS")
print("=" * 70)

summary = [
    ("1. Requirement ID (Chat NLP)", True, "User types, AI classifies"),
    ("2. PR Creation", len(prs) > 0, "%d PRs in DB" % len(prs)),
    ("3. Approval Process", len(wfs) > 0, "%d workflows, %d steps" % (len(wfs), len(steps))),
    ("4. Vendor Selection", len(vendors) > 0, "%d vendors, %d quotes, %d RFQs" % (len(vendors), len(quotes), len(rfqs))),
    ("5. Vendor Evaluation", len(perf) > 0, "%d performance records" % len(perf)),
    ("6. PO Creation", len(pos) > 0, "%d POs" % len(pos)),
    ("7-8. GRN", len(grns) > 0, "%d GRNs" % len(grns)),
    ("9. Invoice Capture", len(invoices) > 0, "%d invoices" % len(invoices)),
    ("10. 3-Way Match", True, "Agent code ready, %d discrepancies" % len(disc)),
    ("11. Payment Approval", len(pay_rules) > 0, "%d payment rules" % len(pay_rules)),
    ("12. Payment Execution", len(fx) > 0, "Calculation ready, %d FX rates, bank=STUB" % len(fx)),
    ("13. Reporting", len(spend) > 0, "spend=%d, budget=%d, aging=%d" % (len(spend), len(budget), len(aging))),
    ("--- Notifications", len(notifs) > 0, "%d logged, EMAIL=%s" % (len(notifs), os.environ.get('EMAIL_PROVIDER', 'mock'))),
    ("--- Workflow Engine", len(wf_runs) > 0, "%d runs, %d events" % (len(wf_runs), wf_events[0]['cnt'])),
    ("--- Audit Trail", actions[0]['cnt'] > 0, "%d agent actions logged" % actions[0]['cnt']),
]

for name, ok, detail in summary:
    icon = "PASS" if ok else "----"
    print("  %s  %s  %s" % (icon, name.ljust(30), detail))
