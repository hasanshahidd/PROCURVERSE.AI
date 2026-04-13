"""Quick test: verify all 4 workflows through streaming endpoint."""
import requests, json

def test_streaming(name, body):
    r = requests.post(
        "http://localhost:5000/api/agentic/execute/stream",
        json=body,
        stream=True,
        headers={"Accept": "text/event-stream"},
    )
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            try:
                event = json.loads(line[5:].strip())
                if event.get("type") == "complete":
                    d = event.get("data", {})
                    r2 = d.get("result", {})
                    inner = r2.get("result", {})
                    pr = inner.get("primary_result", {})
                    dec = pr.get("decision", {})
                    payload = pr.get("result", {})
                    agent = pr.get("agent", "?")
                    action = dec.get("action", "?")[:50]
                    conf = dec.get("confidence", "?")
                    pstatus = payload.get("status", "n/a")[:30]
                    print(f"  {name}: agent={agent}, action={action}, confidence={conf}, payload_status={pstatus}")
                    return True
            except Exception as e:
                print(f"  {name}: parse error: {e}")
    print(f"  {name}: NO COMPLETE EVENT")
    return False

print("=== Testing all 4 workflows via streaming ===\n")

test_streaming("BUDGET", {
    "request": "Check IT budget for 50000",
    "pr_data": {"department": "IT", "budget": 50000, "budget_category": "CAPEX"},
})
test_streaming("RISK", {
    "request": "Assess vendor risk for TechFlow 120000",
    "pr_data": {"vendor_name": "TechFlow", "budget": 120000, "urgency": "High"},
})
test_streaming("VENDOR", {
    "request": "Recommend best vendor for office supplies budget 30000",
    "pr_data": {"category": "Office Supplies", "budget": 30000},
})
test_streaming("APPROVAL", {
    "request": "Route approval for PR in Finance dept 75000",
    "pr_data": {"pr_number": "PR-2026-0099", "department": "Finance", "budget": 75000},
})

print("\n=== Done ===")
