"""Complete UAT test — run before Phase 2."""
import os, json, time, urllib.request, sys
os.environ['DATA_SOURCE'] = 'demo_odoo'
os.environ['DATABASE_URL'] = 'postgresql://postgres:YourStr0ng!Pass@127.0.0.1:5433/odoo_procurement_demo'
sys.path.insert(0, '.')

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
        json.loads(r.read().decode())
        results.append(("PASS", name))
    except urllib.error.HTTPError as e:
        bt = ""
        try: bt = e.read().decode()[:80]
        except: pass
        results.append(("FAIL", name + " [HTTP %d: %s]" % (e.code, bt)))
    except Exception as e:
        results.append(("FAIL", name + " [%s]" % str(e)[:60]))

print("=" * 70)
print("COMPLETE UAT BEFORE PHASE 2")
print("=" * 70)

# 1. Health
api("Health", BASE + "/api/health")
api("Stats", BASE + "/api/stats")
api("Config", BASE + "/api/config/data-source")

# 2. ERP switching
api("Switch SAP", BASE + "/api/config/data-source", "POST", {"data_source": "demo_sap_s4"})
api("Switch Oracle", BASE + "/api/config/data-source", "POST", {"data_source": "demo_oracle"})
api("Switch Odoo", BASE + "/api/config/data-source", "POST", {"data_source": "demo_odoo"})

# 3. Import
api("Import tables", BASE + "/api/import/tables")
api("Table: odoo_partners", BASE + "/api/import/table/odoo_partners?limit=2")

# 4. Quality
api("Quality scan", BASE + "/api/quality/scan/odoo_partners")

# 5. Dashboard
api("Dashboard", BASE + "/api/agentic/dashboard/data")

# 6. Agents
api("Agents", BASE + "/api/agentic/agents")

# 7. Approvals
time.sleep(2)
api("Approval chains", BASE + "/api/agentic/approval-chains")
time.sleep(2)
api("Pending approvals", BASE + "/api/agentic/pending-approvals")
time.sleep(2)
api("Pending count", BASE + "/api/agentic/pending-approvals/count")

# 8. Chat
time.sleep(3)
api("Chat hello", BASE + "/api/chat", "POST", {"message": "hello", "session_id": "uat-1"})
time.sleep(3)
api("Chat budget", BASE + "/api/chat", "POST", {"message": "show budget status", "session_id": "uat-2"}, timeout=45)

# 9. Execute
time.sleep(5)
api("Execute budget", BASE + "/api/agentic/execute", "POST",
    {"request": "check budget for IT CAPEX", "session_id": "uat-3"}, timeout=45)
time.sleep(5)
api("Execute risk", BASE + "/api/agentic/execute", "POST",
    {"request": "assess risk for PO from vendor Lopez", "session_id": "uat-4"}, timeout=45)

# 10. Pipeline
time.sleep(5)
api("Pipeline dry-run", BASE + "/api/agentic/pipeline/run", "POST", {
    "po_document": {"document_ref": "PO-UAT", "raw_content": "PO for 100 items $50 each"},
    "invoice_document": {"document_ref": "INV-UAT", "raw_content": "Invoice $5000"},
    "dry_run": True,
}, timeout=60)

# 11. Adapter methods
print("\n--- Adapter Methods ---")
from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
a = PostgreSQLAdapter()
for name, func in [
    ("vendors", lambda: a.get_vendors(limit=3)),
    ("items", lambda: a.get_items()),
    ("POs", lambda: a.get_purchase_orders(limit=3)),
    ("invoices", lambda: a.get_vendor_invoices(limit=3)),
    ("quotes", lambda: a.get_vendor_quotes(limit=5)),
    ("RFQs", lambda: a.get_rfq_headers(limit=5)),
    ("vendor_perf", lambda: a.get_vendor_performance()),
    ("approved_suppliers", lambda: a.get_approved_suppliers()),
    ("ap_aging", lambda: a.get_ap_aging()),
    ("fx_rates", lambda: a.get_exchange_rates()),
    ("approval_rules", lambda: a.get_approval_rules()),
    ("cost_centers", lambda: a.get_cost_centers()),
    ("budget", lambda: a.get_budget_tracking()),
    ("contracts", lambda: a.get_contracts(limit=5)),
    ("spend", lambda: a.get_spend_analytics(limit=5)),
    ("pending", lambda: a.get_pending_approvals()),
    ("GRNs", lambda: a.get_grn_headers(limit=3)),
]:
    try:
        r = func()
        c = len(r) if r else 0
        results.append(("PASS" if c > 0 else "EMPTY", "Adapter: %s (%d)" % (name, c)))
    except Exception as e:
        results.append(("FAIL", "Adapter: %s [%s]" % (name, str(e)[:50])))

# 12. PO creation all 5 ERPs
print("\n--- PO Creation ---")
from backend.services.adapters.factory import reset_adapter
for ds, label in [("demo_odoo","Odoo"), ("demo_sap","SAP"), ("demo_dynamics","D365"), ("demo_oracle","Oracle"), ("demo_erpnext","ERPNext")]:
    os.environ['DATA_SOURCE'] = ds
    reset_adapter()
    aa = PostgreSQLAdapter()
    try:
        r = aa.create_purchase_order_from_pr(dict(
            pr_number="PR-UAT-%s" % label, vendor_name="%s Vendor" % label,
            product_name="Test", quantity=10, unit_price=100,
            total_amount=1000, department="Test", currency="USD"
        ))
        results.append(("PASS" if r.get("success") else "FAIL", "PO Create (%s)" % label))
    except Exception as e:
        results.append(("FAIL", "PO Create (%s) [%s]" % (label, str(e)[:50])))

os.environ['DATA_SOURCE'] = 'demo_odoo'
reset_adapter()

# 13. DB table checks
print("\n--- DB Tables ---")
import psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
for t in ['vendor_quotes','ap_aging','rfq_headers','qc_templates','workflow_runs','workflow_tasks',
          'workflow_events','po_amendments','rtv_headers','bank_statements','procurement_records',
          'approval_rules','budget_tracking','exchange_rates','users','email_templates','notification_log']:
    try:
        cur.execute("SELECT count(*) FROM %s" % t)
        c = cur.fetchone()[0]
        results.append(("PASS" if c > 0 else "READY", "DB: %s (%d)" % (t, c)))
    except:
        results.append(("FAIL", "DB: %s MISSING" % t))
        conn.rollback()
cur.close(); conn.close()

# RESULTS
print("\n" + "=" * 70)
print("UAT RESULTS")
print("=" * 70)
p = sum(1 for s,_ in results if s == "PASS")
e = sum(1 for s,_ in results if s in ("EMPTY","READY"))
f = sum(1 for s,_ in results if s == "FAIL")
for s, n in results:
    icon = "PASS" if s == "PASS" else ("----" if s in ("EMPTY","READY") else "FAIL")
    print("  %s  %s" % (icon, n))
print("\n  PASS: %d | EMPTY/READY: %d | FAIL: %d | TOTAL: %d" % (p, e, f, len(results)))
print("  SCORE: %.0f%%" % ((p / len(results)) * 100))
if f > 0:
    print("\n  FAILURES:")
    for s, n in results:
        if s == "FAIL": print("    - %s" % n)
