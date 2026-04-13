"""
COMPLETE QA/UAT — Tests EVERYTHING: routes, agents, adapters, new methods, all gaps.
"""
import os, json, time, urllib.request, psycopg2
from psycopg2.extras import RealDictCursor

os.environ['DATA_SOURCE'] = 'demo_odoo'
os.environ['DATABASE_URL'] = 'postgresql://postgres:YourStr0ng!Pass@127.0.0.1:5433/odoo_procurement_demo'
BASE = "http://127.0.0.1:5000"
results = []

def api(name, url, method="GET", body=None, timeout=30):
    try:
        if method == "POST" and body:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
        else:
            req = urllib.request.Request(url)
        r = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(r.read().decode())
        results.append(("PASS", name))
        return data
    except urllib.error.HTTPError as e:
        bt = ""
        try: bt = e.read().decode()[:60]
        except: pass
        results.append(("FAIL", "%s [HTTP %d: %s]" % (name, e.code, bt)))
        return None
    except Exception as e:
        results.append(("FAIL", "%s [%s]" % (name, str(e)[:50])))
        return None

def db(name, sql, params=None):
    try:
        conn = psycopg2.connect(os.environ['DATABASE_URL'])
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cur.close(); conn.close()
        results.append(("PASS" if rows else "EMPTY", "%s (%d rows)" % (name, len(rows))))
        return rows
    except Exception as e:
        results.append(("FAIL", "%s [%s]" % (name, str(e)[:50])))
        return []

print("=" * 70)
print("COMPLETE QA/UAT — ALL SYSTEMS")
print("=" * 70)

# ═══ SECTION 1: CORE API ═══
print("\n--- 1. Core API ---")
api("Health", BASE + "/api/health")
api("Config", BASE + "/api/config/data-source")
api("Dashboard", BASE + "/api/agentic/dashboard/data")

# ═══ SECTION 2: AGENTS (22 registered) ═══
print("\n--- 2. Agent Registration ---")
d = api("Agents list", BASE + "/api/agentic/agents", timeout=60)
if d:
    count = d.get("count", 0)
    print("  Registered: %d agents" % count)
    if count >= 22:
        results.append(("PASS", "22+ agents registered (%d)" % count))
    else:
        results.append(("FAIL", "Expected 22 agents, got %d" % count))

# ═══ SECTION 3: NLP ROUTING (test fast-path for new agents) ═══
print("\n--- 3. NLP Agent Routing ---")
time.sleep(3)
test_queries = [
    ("RFQ routing", "Create RFQ for monitors"),
    ("Amendment routing", "Amend PO-001 quantity to 120"),
    ("Return routing", "Return 5 damaged items from GRN-001"),
    ("QC routing", "Run quality inspection on GRN-001"),
    ("Reconciliation routing", "Reconcile payments"),
    ("Onboarding routing", "Onboard new vendor TechCorp"),
    ("Delivery routing", "Track delivery for PO-045"),
    ("Exception routing", "Show invoice exceptions"),
    ("Payment ready routing", "Check payment readiness"),
    ("Budget routing", "Check budget for IT"),
    ("Risk routing", "Assess risk for vendor Lopez"),
    ("Spend routing", "Show spend analytics"),
]
for name, query in test_queries:
    d = api(name, BASE + "/api/agentic/execute", "POST",
            {"request": query, "session_id": "qa-%d" % hash(query)}, timeout=45)
    time.sleep(2)

# ═══ SECTION 4: ALL API ENDPOINTS ═══
print("\n--- 4. API Endpoints ---")
api("RFQ list", BASE + "/api/rfq/list")
api("Amendment list", BASE + "/api/amendments/list")
api("RTV list", BASE + "/api/rtv/list")
api("QC templates", BASE + "/api/qc/templates")
api("QC results", BASE + "/api/qc/results")
api("Recon results", BASE + "/api/reconciliation/results")
api("Recon exceptions", BASE + "/api/reconciliation/exceptions")
api("Workflow types", BASE + "/api/workflow/types/available")
api("Workflow list", BASE + "/api/workflow/list/all")
api("Import tables", BASE + "/api/import/tables")
api("Quality scan", BASE + "/api/quality/scan/odoo_partners")
api("Audit summary", BASE + "/api/audit/summary")
api("Audit accruals", BASE + "/api/audit/accruals")
api("Audit debit-notes", BASE + "/api/audit/debit-notes")
time.sleep(2)
api("Approval chains", BASE + "/api/agentic/approval-chains")
time.sleep(2)
api("Pending approvals", BASE + "/api/agentic/pending-approvals")

# ═══ SECTION 5: ADAPTER METHODS ═══
print("\n--- 5. Adapter Methods ---")
from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
a = PostgreSQLAdapter()
adapter_tests = [
    ("vendors", lambda: a.get_vendors(limit=3)),
    ("items", lambda: a.get_items()),
    ("POs", lambda: a.get_purchase_orders(limit=3)),
    ("invoices", lambda: a.get_vendor_invoices(limit=3)),
    ("quotes", lambda: a.get_vendor_quotes(limit=5)),
    ("RFQs", lambda: a.get_rfq_headers(limit=5)),
    ("performance", lambda: a.get_vendor_performance()),
    ("aging", lambda: a.get_ap_aging()),
    ("fx_rates", lambda: a.get_exchange_rates()),
    ("rules", lambda: a.get_approval_rules()),
    ("budget", lambda: a.get_budget_tracking()),
    ("spend", lambda: a.get_spend_analytics(limit=3)),
    ("GRNs", lambda: a.get_grn_headers(limit=3)),
    ("contracts", lambda: a.get_contracts(limit=3)),
    ("cost_centers", lambda: a.get_cost_centers()),
]
for name, func in adapter_tests:
    try:
        r = func()
        c = len(r) if r else 0
        results.append(("PASS" if c > 0 else "EMPTY", "Adapter: %s (%d)" % (name, c)))
    except Exception as e:
        results.append(("FAIL", "Adapter: %s [%s]" % (name, str(e)[:40])))

# ═══ SECTION 6: NEW ADAPTER METHODS (Gap fixes) ═══
print("\n--- 6. New Gap-Fix Methods ---")
try:
    r = a.release_committed_budget("IT", "CAPEX", 100)
    results.append(("PASS" if r.get("success") else "FAIL", "release_committed_budget"))
except Exception as e:
    results.append(("FAIL", "release_committed_budget [%s]" % str(e)[:40]))

try:
    r = a.lock_fx_rate("PO", "PO-QA-FX", "USD")
    results.append(("PASS" if r.get("success") else "FAIL", "lock_fx_rate (rate=%s)" % r.get("locked_rate")))
except Exception as e:
    results.append(("FAIL", "lock_fx_rate [%s]" % str(e)[:40]))

try:
    r = a.get_locked_fx_rate("PO", "PO-QA-FX")
    results.append(("PASS" if r > 0 else "FAIL", "get_locked_fx_rate (%s)" % r))
except Exception as e:
    results.append(("FAIL", "get_locked_fx_rate [%s]" % str(e)[:40]))

try:
    r = a.create_accrual("GRN-QA", "PO-QA", "QA Vendor", 5000)
    results.append(("PASS" if r.get("success") else "FAIL", "create_accrual"))
except Exception as e:
    results.append(("FAIL", "create_accrual [%s]" % str(e)[:40]))

try:
    r = a.reverse_accrual("GRN-QA", "INV-QA")
    results.append(("PASS" if r.get("success") else "FAIL", "reverse_accrual (reversed=%s)" % r.get("reversed")))
except Exception as e:
    results.append(("FAIL", "reverse_accrual [%s]" % str(e)[:40]))

try:
    r = a.create_debit_note("RTV-QA", "QA Vendor", "PO-QA", 500, "Quality failure")
    results.append(("PASS" if r.get("success") else "FAIL", "create_debit_note (%s)" % r.get("debit_note_number")))
except Exception as e:
    results.append(("FAIL", "create_debit_note [%s]" % str(e)[:40]))

# ═══ SECTION 7: PO CREATION ALL 5 ERPs ═══
print("\n--- 7. PO Creation (5 ERPs) ---")
from backend.services.adapters.factory import reset_adapter
for ds, label in [("demo_odoo","Odoo"), ("demo_sap","SAP"), ("demo_dynamics","D365"), ("demo_oracle","Oracle"), ("demo_erpnext","ERPNext")]:
    os.environ['DATA_SOURCE'] = ds
    reset_adapter()
    try:
        aa = PostgreSQLAdapter()
        r = aa.create_purchase_order_from_pr(dict(
            pr_number="QA-FINAL-%s" % label, vendor_name="QA", product_name="Test",
            quantity=1, unit_price=100, total_amount=100, department="QA", currency="USD"))
        results.append(("PASS" if r.get("success") else "FAIL", "PO Create (%s)" % label))
    except Exception as e:
        results.append(("FAIL", "PO Create (%s): %s" % (label, str(e)[:40])))
os.environ['DATA_SOURCE'] = 'demo_odoo'
reset_adapter()

# ═══ SECTION 8: DATABASE TABLES ═══
print("\n--- 8. Database Tables ---")
tables = [
    "vendor_quotes", "ap_aging", "rfq_headers", "qc_templates", "qc_results",
    "workflow_runs", "workflow_tasks", "workflow_events",
    "po_amendments", "rtv_headers", "bank_statements",
    "reconciliation_results", "reconciliation_exceptions",
    "debit_notes", "accruals", "fx_locked_rates",
    "procurement_records", "approval_rules", "budget_tracking",
    "exchange_rates", "users", "email_templates", "notification_log",
    "agent_actions", "pending_approvals",
]
for t in tables:
    db("DB: %s" % t, "SELECT count(*) as cnt FROM %s" % t)

# ═══ SECTION 9: WORKFLOW ENGINE ═══
print("\n--- 9. Workflow Engine ---")
from backend.services.workflow_engine import create_workflow, get_workflow_status
try:
    wf = create_workflow("PR_TO_PO", {"qa": True})
    results.append(("PASS" if wf.get("success") else "FAIL", "Workflow create (%s)" % wf.get("workflow_run_id", "?")))
except Exception as e:
    results.append(("FAIL", "Workflow create [%s]" % str(e)[:40]))

# ═══ FINAL RESULTS ═══
print("\n" + "=" * 70)
print("QA/UAT RESULTS")
print("=" * 70)
p = sum(1 for s,_ in results if s == "PASS")
e = sum(1 for s,_ in results if s in ("EMPTY",))
f = sum(1 for s,_ in results if s == "FAIL")
for s, n in results:
    icon = "PASS" if s == "PASS" else ("----" if s == "EMPTY" else "FAIL")
    print("  %s  %s" % (icon, n))
print("\n  PASS: %d | EMPTY: %d | FAIL: %d | TOTAL: %d" % (p, e, f, len(results)))
print("  SCORE: %.0f%%" % ((p / len(results)) * 100 if results else 0))
if f > 0:
    print("\n  FAILURES:")
    for s, n in results:
        if s == "FAIL": print("    - %s" % n)
