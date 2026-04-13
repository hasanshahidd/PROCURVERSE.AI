"""Debug: dump raw responses."""
import asyncio, json, httpx

async def test():
    async with httpx.AsyncClient(timeout=30) as client:
        # Risk with vendor name
        print("=== Risk with Office Depot LLC ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Evaluate risk for buying $2000 of paper from Office Depot LLC for Operations"
        })
        data = r.json()
        # Walk full tree
        result = data.get("result", {})
        pr = result.get("primary_result", {})
        inner = pr.get("result", {})
        breakdown = inner.get("breakdown", {})
        print(f"  inner.risk_level = {inner.get('risk_level')}")
        print(f"  inner.risk_score = {inner.get('risk_score')}")
        print(f"  breakdown keys = {list(breakdown.keys())}")
        vr = breakdown.get("vendor_risk", {})
        print(f"  vendor_risk.score = {vr.get('score')}")
        print(f"  vendor_risk.concerns = {vr.get('concerns')}")
        print()

        # Vendor
        print("=== Vendor for electronics ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Find best vendor for electronics equipment, budget 50000"
        })
        data = r.json()
        result = data.get("result", {})
        pr = result.get("primary_result", {})
        inner = pr.get("result", {})
        print(f"  inner keys = {list(inner.keys()) if isinstance(inner, dict) else type(inner)}")
        # Maybe the result is nested differently
        if not inner and isinstance(pr, dict):
            print(f"  pr keys = {list(pr.keys())}")
            print(f"  pr status = {pr.get('status')}")
            # Check if vendor result is at top level
            for k in ['recommendation', 'vendors', 'scored_vendors', 'vendor_scores']:
                if k in pr:
                    print(f"  pr.{k} = {json.dumps(pr[k])[:200]}")
        # Also check data.result directly
        for k in ['recommendation', 'vendors', 'scored_vendors']:
            if k in result:
                print(f"  result.{k} = {json.dumps(result[k])[:200]}")
        
        # Just dump the primary_result
        print(f"  primary_result (trimmed) = {json.dumps(pr)[:500]}")

asyncio.run(test())
