"""Comprehensive end-to-end test of all 4 workflows after enrichment fixes."""
import requests
import json
import sys

BASE = "http://localhost:5000/api/agentic/execute"

def test(name, query, checks):
    """Run a query and check expected fields."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"Query: {query}")
    print(f"{'='*60}")
    try:
        r = requests.post(BASE, json={"request": query}, timeout=30)
        data = r.json()
        result = data.get("result", {})
        
        print(f"Status: {data.get('status')}")
        print(f"Agent: {data.get('agent_used')}")
        
        # Print key result fields
        for key in sorted(result.keys()):
            val = result[key]
            if isinstance(val, dict):
                print(f"  {key}: {{...{len(val)} keys}}")
            elif isinstance(val, list):
                print(f"  {key}: [{len(val)} items]")
            elif isinstance(val, str) and len(val) > 100:
                print(f"  {key}: {val[:100]}...")
            else:
                print(f"  {key}: {val}")
        
        # Run checks
        passed = 0
        failed = 0
        for check_name, check_fn in checks.items():
            try:
                ok = check_fn(data, result)
                status = "✅" if ok else "❌"
                if ok:
                    passed += 1
                else:
                    failed += 1
                print(f"  {status} {check_name}")
            except Exception as e:
                failed += 1
                print(f"  ❌ {check_name}: {e}")
        
        print(f"\n  Results: {passed} passed, {failed} failed")
        return failed == 0
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        return False


results = []

# 1. BUDGET - with department
results.append(test(
    "Budget - Operations department",
    "Check budget availability for Operations department, $50000 CAPEX purchase",
    {
        "status=success": lambda d, r: d.get("status") == "success",
        "agent=budget": lambda d, r: "budget" in (d.get("agent_used") or "").lower(),
        "department=Operations": lambda d, r: r.get("department", "").lower() == "operations",
        "has available_budget": lambda d, r: r.get("available_budget") is not None or r.get("available") is not None,
        "not General": lambda d, r: r.get("department", "General").lower() != "general",
    }
))

# 2. BUDGET - Finance
results.append(test(
    "Budget - Finance OPEX",
    "What is the budget status for Finance department OPEX spending?",
    {
        "status=success": lambda d, r: d.get("status") == "success",
        "department=Finance": lambda d, r: "finance" in str(r.get("department", "")).lower(),
    }
))

# 3. RISK - with vendor name
results.append(test(
    "Risk - Office Depot LLC",
    "Assess procurement risks for a $25000 order from Office Depot LLC",
    {
        "status=success": lambda d, r: d.get("status") == "success",
        "agent=risk": lambda d, r: "risk" in (d.get("agent_used") or "").lower(),
        "risk_level exists": lambda d, r: r.get("risk_level") is not None,
        "not 'Vendor not identified'": lambda d, r: "not identified" not in str(r.get("vendor_concerns", "")),
        "risk_score < 50": lambda d, r: float(r.get("risk_score", r.get("total_risk_score", 100))) < 50,
    }
))

# 4. RISK - Acme Corporation
results.append(test(
    "Risk - Acme Corporation",
    "What are the risks of ordering from Acme Corporation for $100000?",
    {
        "status=success": lambda d, r: d.get("status") == "success",
        "vendor resolved": lambda d, r: "not identified" not in str(r.get("vendor_concerns", "")),
    }
))

# 5. APPROVAL - with PR number
results.append(test(
    "Approval - PR-2026-0300 IT",
    "Route PR-2026-0300 for IT department, amount $75000",
    {
        "status=success": lambda d, r: d.get("status") == "success",
        "agent=approval": lambda d, r: "approval" in (d.get("agent_used") or "").lower(),
        "pr_number=PR-2026-0300": lambda d, r: r.get("pr_number") == "PR-2026-0300",
        "has approvers": lambda d, r: r.get("required_approvers") is not None or r.get("n_approvers") is not None or r.get("approval_chain") is not None,
    }
))

# 6. APPROVAL - auto-generate PR
results.append(test(
    "Approval - auto PR generation",
    "Route a new purchase request for Finance department, $120000 CAPEX",
    {
        "status=success": lambda d, r: d.get("status") == "success",
        "pr_number not Unknown": lambda d, r: r.get("pr_number", "Unknown") != "Unknown",
        "pr_number starts PR-": lambda d, r: str(r.get("pr_number", "")).startswith("PR-"),
    }
))

# 7. VENDOR - with category
results.append(test(
    "Vendor - Electronics",
    "Find the best vendor for electronics equipment under $50000",
    {
        "status=success": lambda d, r: d.get("status") == "success",
        "agent=vendor": lambda d, r: "vendor" in (d.get("agent_used") or "").lower(),
        "has recommendations": lambda d, r: (
            r.get("recommended_vendor") is not None or 
            r.get("top_vendors") is not None or
            r.get("vendors") is not None or
            r.get("recommendation") is not None
        ),
        "not empty/escalated": lambda d, r: r.get("status") != "escalated_to_human",
    }
))

# 8. VENDOR - Office supplies
results.append(test(
    "Vendor - Office Supplies",
    "Recommend a vendor for office supplies, budget $15000",
    {
        "status=success": lambda d, r: d.get("status") == "success",
        "has vendor data": lambda d, r: bool(r),
    }
))

# Summary
print(f"\n{'='*60}")
print(f"SUMMARY: {sum(results)}/{len(results)} tests passed")
print(f"{'='*60}")
if not all(results):
    print("FAILED tests need attention!")
    sys.exit(1)
else:
    print("All tests passed! ✅")
