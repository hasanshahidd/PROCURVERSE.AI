"""Debug: dump full response shapes."""
import asyncio, json, httpx

async def test():
    async with httpx.AsyncClient(timeout=30) as client:
        # Test 1: Budget
        print("=== TEST 1: Budget ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Check if Operations department has budget for a 15000 OPEX purchase"
        })
        data = r.json()
        # Walk the full result tree
        result = data.get("result", {})
        pr = result.get("primary_result", {})
        inner = pr.get("result", {})
        print(f"  data.agent = {data.get('agent')}")
        print(f"  pr.agent = {pr.get('agent')}")
        print(f"  inner keys = {list(inner.keys()) if isinstance(inner, dict) else type(inner)}")
        print(f"  inner.department = {inner.get('department', 'MISSING')}")
        print(f"  inner.budget_details = {json.dumps(inner.get('budget_details', {}))[:300]}")
        print()

        # Test 3: Risk
        print("=== TEST 3: Risk ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Evaluate risk for buying $2000 of paper from Office Depot LLC for Operations"
        })
        data = r.json()
        result = data.get("result", {})
        pr = result.get("primary_result", {})
        inner = pr.get("result", {})
        print(f"  inner keys = {list(inner.keys()) if isinstance(inner, dict) else type(inner)}")
        dims = inner.get("risk_dimensions", {})
        print(f"  vendor_risk = {json.dumps(dims.get('vendor_risk', {}))[:300]}")
        print()

        # Test 4: Vendor
        print("=== TEST 4: Vendor ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Find best vendor for electronics equipment, budget 50000"
        })
        data = r.json()
        result = data.get("result", {})
        pr = result.get("primary_result", {})
        inner = pr.get("result", {})
        print(f"  inner keys = {list(inner.keys()) if isinstance(inner, dict) else type(inner)}")
        rec = inner.get("recommendation", {})
        print(f"  recommendation = {json.dumps(rec)[:300]}")
        print(f"  evaluation_criteria = {json.dumps(inner.get('evaluation_criteria', {}))[:200]}")

asyncio.run(test())
