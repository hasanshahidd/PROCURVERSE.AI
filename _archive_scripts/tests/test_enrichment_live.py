"""Test enrichment via live API calls."""
import asyncio, json, httpx

async def test():
    async with httpx.AsyncClient(timeout=30) as client:
        queries = {
            "Budget + Ops": "Check if Operations department has budget for a $15,000 OPEX purchase",
            "Risk + vendor": "Evaluate risk for buying $2000 of paper from Office Depot LLC for Operations",
            "Approval + PR": "Route PR-2026-0200 for approval, IT department, $12,000 purchase",
            "Vendor + electronics": "Find best vendor for electronics equipment, budget 50000",
        }

        for label, q in queries.items():
            print(f"=== {label} ===")
            r = await client.post("http://localhost:5000/api/agentic/execute", json={"request": q})
            data = r.json()

            # Walk response tree
            top_agent = data.get("agent", "?")
            top_decision = data.get("decision", {})
            result = data.get("result", {})
            pr = result.get("primary_result", {})
            pr_agent = pr.get("agent", "?")
            pr_decision = pr.get("decision", {})
            inner = pr.get("result", {})

            print(f"  top.agent={top_agent}  pr.agent={pr_agent}")

            if isinstance(inner, dict):
                # Budget
                if inner.get("budget_verified") is not None:
                    print(f"  department={inner.get('department', 'MISSING')}")
                    print(f"  status={inner.get('status')}")
                    bu = inner.get("budget_update", {})
                    print(f"  available={bu.get('new_available_budget')}")
                # Risk
                elif inner.get("risk_score") is not None:
                    bd = inner.get("breakdown", {})
                    vr = bd.get("vendor_risk", {})
                    print(f"  risk_level={inner.get('risk_level')}")
                    print(f"  score={inner.get('risk_score')}")
                    print(f"  vendor_concerns={vr.get('concerns', [])}")
                    print(f"  dept={inner.get('department', 'MISSING')}")
                # Approval
                elif inner.get("assigned_approvers") is not None:
                    print(f"  pr_number={inner.get('pr_number', 'MISSING')}")
                    print(f"  n_approvers={len(inner.get('assigned_approvers', []))}")
                    print(f"  workflow={inner.get('workflow_created', {})}")
                # Vendor
                elif inner.get("recommendation") is not None:
                    rec = inner.get("recommendation", {})
                    print(f"  top_vendor={rec.get('vendor_name', 'MISSING')}")
                    print(f"  score={rec.get('total_score', 'MISSING')}")
                else:
                    print(f"  keys={list(inner.keys())[:10]}")
            else:
                print(f"  inner type={type(inner)}, pr keys={list(pr.keys())[:10]}")
            print()

asyncio.run(test())
