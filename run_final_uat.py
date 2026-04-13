"""Final UAT — Tests ALL phases end-to-end."""
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
        json.loads(r.read().decode())
        results.append(("PASS", name))
    except urllib.error.HTTPError as e:
        bt = ""
        try: bt = e.read().decode()[:60]
        except: pass
        results.append(("FAIL", "%s [HTTP %d: %s]" % (name, e.code, bt)))
    except Exception as e:
        results.append(("FAIL", "%s [%s]" % (name, str(e)[:50])))

print("=" * 70)
print("FINAL UAT — ALL PHASES")
print("=" * 70)

# CORE
api("Health", BASE + "/api/health")
api("Stats", BASE + "/api/stats")
api("Config", BASE + "/api/config/data-source")
api("Dashboard", BASE + "/api/agentic/dashboard/data")
api("Agents", BASE + "/api/agentic/agents")

# ERP SWITCH
api("Switch SAP", BASE + "/api/config/data-source", "POST", {"data_source": "demo_sap_s4"})
api("Switch back", BASE + "/api/config/data-source", "POST", {"data_source": "demo_odoo"})

# APPROVALS
time.sleep(2)
api("Approval chains", BASE + "/api/agentic/approval-chains")
time.sleep(2)
api("Pending approvals", BASE + "/api/agentic/pending-approvals")

# CHAT
time.sleep(3)
api("Chat hello", BASE + "/api/chat", "POST", {"message": "hello", "session_id": "uat-final-1"})

# EXECUTE
time.sleep(5)
api("Execute budget", BASE + "/api/agentic/execute", "POST", {"request": "check budget for IT", "session_id": "uat-final-2"}, timeout=45)

# PIPELINE
time.sleep(5)
api("Pipeline dry", BASE + "/api/agentic/pipeline/run", "POST", {
    "po_document": {"document_ref": "PO-FINAL", "raw_content": "PO 100 items $50"},
    "invoice_document": {"document_ref": "INV-FINAL", "raw_content": "Invoice $5000"},
    "dry_run": True,
}, timeout=60)

# IMPORT
api("Import tables", BASE + "/api/import/tables")

# QUALITY
api("Quality scan", BASE + "/api/quality/scan/odoo_partners")

# PHASE 3: RFQ
api("RFQ list", BASE + "/api/rfq/list")
api("RFQ create", BASE + "/api/rfq/create", "POST", {
    "title": "UAT Laptops", "department": "IT",
    "items": [{"item_name": "Laptop", "quantity": 10, "estimated_price": 1000}]
})

# PHASE 4: AMENDMENTS
api("Amendment create", BASE + "/api/amendments/create", "POST", {
    "po_number": "PO-2026-TEST", "amendment_type": "quantity_change",
    "reason": "UAT test", "old_value": "100", "new_value": "120", "amount_impact": 2400
})
api("Amendment list", BASE + "/api/amendments/list")

# PHASE 5: RTV
api("RTV create", BASE + "/api/rtv/create", "POST", {
    "grn_number": "GRN-UAT-001", "po_number": "PO-UAT-001",
    "vendor_name": "Test Vendor", "return_reason": "quality_failure",
    "items": [{"item_name": "Defective Widget", "return_qty": 5, "unit_price": 50, "condition": "damaged"}]
})
api("RTV list", BASE + "/api/rtv/list")

# PHASE 6: QC
api("QC templates", BASE + "/api/qc/templates")
api("QC inspect", BASE + "/api/qc/inspect", "POST", {
    "grn_number": "GRN-UAT-001", "template_id": 1, "item_name": "Widget",
    "inspector": "QA Tester",
    "checklist_results": [
        {"passed": True, "notes": "OK"},
        {"passed": True, "notes": "OK"},
        {"passed": False, "notes": "Damaged"},
        {"passed": True, "notes": "OK"},
        {"passed": True, "notes": "OK"},
        {"passed": True, "notes": "OK"},
    ]
})
api("QC results", BASE + "/api/qc/results")

# PHASE 7: RECONCILIATION
api("Recon results", BASE + "/api/reconciliation/results")
api("Recon exceptions", BASE + "/api/reconciliation/exceptions")

# WORKFLOW
api("Workflow types", BASE + "/api/workflow/types/available")
api("Workflow list", BASE + "/api/workflow/list/all")
api("Workflow create", BASE + "/api/workflow/create", "POST", {
    "workflow_type": "PR_TO_PO", "trigger_data": {"test": "uat"}
})

# ADAPTER
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
    ("performance", lambda: a.get_vendor_performance()),
    ("aging", lambda: a.get_ap_aging()),
    ("fx_rates", lambda: a.get_exchange_rates()),
    ("rules", lambda: a.get_approval_rules()),
    ("budget", lambda: a.get_budget_tracking()),
    ("spend", lambda: a.get_spend_analytics(limit=3)),
    ("GRNs", lambda: a.get_grn_headers(limit=3)),
]:
    try:
        r = func()
        c = len(r) if r else 0
        results.append(("PASS" if c > 0 else "EMPTY", "Adapter: %s (%d)" % (name, c)))
    except Exception as e:
        results.append(("FAIL", "Adapter: %s [%s]" % (name, str(e)[:40])))

# PO CREATION ALL ERPs
from backend.services.adapters.factory import reset_adapter
for ds, label in [("demo_odoo","Odoo"), ("demo_sap","SAP"), ("demo_dynamics","D365"), ("demo_oracle","Oracle"), ("demo_erpnext","ERPNext")]:
    os.environ['DATA_SOURCE'] = ds
    reset_adapter()
    try:
        aa = PostgreSQLAdapter()
        r = aa.create_purchase_order_from_pr(dict(pr_number="UAT-FINAL-%s" % label, vendor_name="QA", product_name="Test", quantity=1, unit_price=100, total_amount=100, department="QA", currency="USD"))
        results.append(("PASS" if r.get("success") else "FAIL", "PO Create (%s)" % label))
    except Exception as e:
        results.append(("FAIL", "PO Create (%s): %s" % (label, str(e)[:40])))
os.environ['DATA_SOURCE'] = 'demo_odoo'
reset_adapter()

# RESULTS
print("\n" + "=" * 70)
print("FINAL UAT RESULTS — ALL PHASES")
print("=" * 70)
p = sum(1 for s,_ in results if s == "PASS")
e = sum(1 for s,_ in results if s in ("EMPTY",))
f = sum(1 for s,_ in results if s == "FAIL")
for s, n in results:
    icon = "PASS" if s == "PASS" else ("----" if s == "EMPTY" else "FAIL")
    print("  %s  %s" % (icon, n))
print("\n  PASS: %d | EMPTY: %d | FAIL: %d | TOTAL: %d" % (p, e, f, len(results)))
print("  SCORE: %.0f%%" % ((p / len(results)) * 100))
if f > 0:
    print("\n  FAILURES:")
    for s, n in results:
        if s == "FAIL": print("    - %s" % n)
