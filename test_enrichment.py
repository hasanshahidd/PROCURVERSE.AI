"""Test pr_data enrichment from NL queries."""
import asyncio, json, httpx

async def test():
    async with httpx.AsyncClient(timeout=30) as client:
        # Test 1: Budget with department extraction
        print("=== TEST 1: Budget + Operations dept ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Check if Operations department has budget for a 15000 OPEX purchase"
        })
        data = r.json()
        result = data.get("result", {})
        pr = result.get("primary_result", result)
        inner = pr.get("result", {}) if isinstance(pr, dict) else {}
        bd = inner.get("budget_details", {})
        agent = data.get("agent", "?")
        print(f"  Agent: {agent}")
        print(f"  Department: {bd.get('department', inner.get('department', 'NOT_FOUND'))}")
        print(f"  Status: {inner.get('status', data.get('status'))}")
        print(f"  Amount: {bd.get('requested_amount')}")
        print()

        # Test 2: Approval with PR number extraction
        print("=== TEST 2: Approval + PR number ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Route PR-2026-0200 for approval, IT department, $12,000 purchase"
        })
        data = r.json()
        result = data.get("result", {})
        pr2 = result.get("primary_result", result)
        inner2 = pr2.get("result", {}) if isinstance(pr2, dict) else {}
        agent2 = data.get("agent", "?")
        print(f"  Agent: {agent2}")
        print(f"  PR Number: {inner2.get('pr_number', 'NOT_FOUND')}")
        print(f"  Workflow created: {inner2.get('workflow_created', 'NOT_FOUND')}")
        print(f"  Approvers: {len(inner2.get('assigned_approvers', []))}")
        print()

        # Test 3: Risk with vendor name
        print("=== TEST 3: Risk with vendor name (Office Depot LLC) ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Evaluate risk for buying $2000 of paper from Office Depot LLC for Operations department"
        })
        data = r.json()
        result = data.get("result", {})
        pr3 = result.get("primary_result", result)
        inner3 = pr3.get("result", {}) if isinstance(pr3, dict) else {}
        dims = inner3.get("risk_dimensions", {})
        vendor_concerns = dims.get("vendor_risk", {}).get("concerns", [])
        agent3 = data.get("agent", "?")
        print(f"  Agent: {agent3}")
        print(f"  Overall score: {inner3.get('overall_score')}")
        print(f"  Vendor concerns: {vendor_concerns}")
        print()

        # Test 4: Vendor with category extraction
        print("=== TEST 4: Vendor + electronics category ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Compare vendors for purchasing $50,000 of electronics equipment"
        })
        data = r.json()
        result = data.get("result", {})
        pr4 = result.get("primary_result", result)
        inner4 = pr4.get("result", {}) if isinstance(pr4, dict) else {}
        rec = inner4.get("recommendation", {})
        agent4 = data.get("agent", "?")
        print(f"  Agent: {agent4}")
        print(f"  Top vendor: {rec.get('vendor_name', 'NOT_FOUND')}")
        print(f"  Score: {rec.get('total_score', 'NOT_FOUND')}")
        print(f"  Category used: {inner4.get('evaluation_criteria', {}).get('category', 'NOT_FOUND')}")

asyncio.run(test())
