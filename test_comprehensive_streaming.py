"""Comprehensive test: all query types through streaming endpoint."""
import requests, json, time

BASE = "http://localhost:5000/api/agentic/execute/stream"

def test(name, body, expect_agent=None, expect_ds=None):
    start = time.time()
    r = requests.post(BASE, json=body, stream=True, headers={"Accept": "text/event-stream"})
    events = []
    result_agent = None
    result_ds = None
    result_status = None
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            try:
                event = json.loads(line[5:].strip())
                events.append(event.get("type"))
                if event.get("type") == "complete":
                    d = event.get("data", {})
                    res = d.get("result", {})
                    result_agent = res.get("agent", "?")
                    result_ds = res.get("data_source", "?")
                    result_status = res.get("status", "?")
                    # Check for inner agent
                    inner = res.get("result", {})
                    if isinstance(inner, dict) and inner.get("primary_result"):
                        pr = inner["primary_result"]
                        result_agent = pr.get("agent", result_agent)
                    break
            except:
                pass
    elapsed = int((time.time() - start) * 1000)
    ok = True
    if expect_agent and result_agent != expect_agent:
        ok = False
    if expect_ds and result_ds != expect_ds:
        ok = False
    status_icon = "✅" if ok else "❌"
    print(f"  {status_icon} {name}: agent={result_agent}, ds={result_ds}, status={result_status}, events={len(events)}, {elapsed}ms")
    if not ok:
        if expect_agent and result_agent != expect_agent:
            print(f"      Expected agent={expect_agent}, got={result_agent}")
        if expect_ds and result_ds != expect_ds:
            print(f"      Expected ds={expect_ds}, got={result_ds}")
    return ok

print("=" * 70)
print("COMPREHENSIVE STREAMING TEST")
print("=" * 70)

results = []

print("\n--- Core Agentic Workflows ---")
results.append(test("Budget", {
    "request": "Check IT budget for 50000 CAPEX",
    "pr_data": {"department": "IT", "budget": 50000, "budget_category": "CAPEX"}
}, expect_agent="BudgetVerificationAgent", expect_ds="agentic"))

results.append(test("Risk", {
    "request": "Assess vendor risk for TechFlow 120000",
    "pr_data": {"vendor_name": "TechFlow", "budget": 120000, "urgency": "High"}
}, expect_agent="RiskAssessmentAgent", expect_ds="agentic"))

results.append(test("Vendor", {
    "request": "Recommend best vendor for office supplies 30000",
    "pr_data": {"category": "Office Supplies", "budget": 30000}
}, expect_agent="VendorSelectionAgent", expect_ds="agentic"))

results.append(test("Approval", {
    "request": "Route approval for PR in Finance 75000",
    "pr_data": {"pr_number": "PR-2026-0099", "department": "Finance", "budget": 75000}
}, expect_agent="ApprovalRoutingAgent", expect_ds="agentic"))

print("\n--- Non-Agentic Queries ---")
results.append(test("Greeting", {
    "request": "hello",
    "pr_data": {}
}, expect_agent="AssistantBot", expect_ds="general"))

results.append(test("Odoo POs", {
    "request": "show all purchase orders",
    "pr_data": {}
}, expect_agent="OdooDataService", expect_ds="odoo"))

print("\n--- Multi-Intent ---")
results.append(test("Multi: Budget+Approval", {
    "request": "Check budget for IT 50000 CAPEX and route for approval",
    "pr_data": {"department": "IT", "budget": 50000, "budget_category": "CAPEX"}
}, expect_agent="MultiIntentOrchestrator", expect_ds="multi-intent"))

passed = sum(results)
total = len(results)
print(f"\n{'=' * 70}")
print(f"RESULTS: {passed}/{total} PASSED")
print(f"{'=' * 70}")
