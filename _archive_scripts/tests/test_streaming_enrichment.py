"""Test streaming endpoint enrichment for all 4 workflows."""
import requests
import json

url = "http://localhost:5000/api/agentic/execute/stream"
queries = [
    ("Budget-Ops", "Check budget for Operations department CAPEX, 50000"),
    ("Risk-Vendor", "Assess risks for ordering from Office Depot LLC, 25000"),
    ("Approval-PR", "Route PR-2026-0500 for IT department, amount 80000"),
    ("Vendor-Elec", "Find best vendor for electronics under 40000"),
]

for name, q in queries:
    print(f"\n--- {name}: {q} ---")
    r = requests.post(url, json={"request": q}, stream=True, timeout=30)
    for line in r.iter_lines():
        if line:
            txt = line.decode("utf-8")
            if txt.startswith("data: "):
                d = json.loads(txt[6:])
                etype = d.get("type", "")
                if etype == "complete":
                    res = d.get("result", {})
                    pr_res = res.get("primary_result", {}).get("result", res)
                    dept = pr_res.get("department", "-")
                    risk = pr_res.get("risk_level", "-")
                    prn = pr_res.get("pr_number", "-")
                    rec = pr_res.get("primary_recommendation", {})
                    vendor = rec.get("vendor_name", "-") if isinstance(rec, dict) else "-"
                    status = pr_res.get("status", "-")
                    print(f"  status={status} dept={dept} risk={risk} pr={prn} vendor={vendor}")
                elif etype == "error":
                    msg = d.get("message", "?")
                    print(f"  ERROR: {msg}")
    print()
