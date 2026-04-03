"""Verify streaming enrichment for risk and approval."""
import requests
import json

url = "http://localhost:5000/api/agentic/execute/stream"
queries = [
    ("Risk", "Assess risks for ordering from Office Depot LLC, 25000"),
    ("Approval", "Route PR-2026-0500 for IT department, amount 80000"),
]

for name, q in queries:
    print(f"\n=== {name}: {q} ===")
    r = requests.post(url, json={"request": q}, stream=True, timeout=30)
    for line in r.iter_lines():
        if line:
            txt = line.decode("utf-8")
            if txt.startswith("data: "):
                d = json.loads(txt[6:])
                if d.get("type") == "complete":
                    # Navigate to deepest result
                    data = d.get("data", {})
                    outer = data.get("result", {})
                    inner_result = outer.get("result", {})
                    pr = inner_result.get("primary_result", {}).get("result", {})
                    
                    if name == "Risk":
                        print(f"  risk_level: {pr.get('risk_level')}")
                        print(f"  risk_score: {pr.get('risk_score')}")
                        concerns = pr.get("breakdown", {}).get("vendor_risk", {}).get("concerns", [])
                        print(f"  vendor_concerns: {concerns}")
                        print(f"  can_proceed: {pr.get('can_proceed')}")
                    elif name == "Approval":
                        print(f"  pr_number: {pr.get('pr_number')}")
                        print(f"  status: {pr.get('status')}")
                        approvers = pr.get("assigned_approvers", [])
                        print(f"  n_approvers: {len(approvers)}")
                        for a in approvers:
                            print(f"    L{a.get('approval_level')}: {a.get('approver_name')}")
