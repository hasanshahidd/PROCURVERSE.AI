"""Quick test for risk vendor resolution."""
import asyncio, json, httpx

async def test():
    async with httpx.AsyncClient(timeout=30) as client:
        print("=== Risk with Office Depot LLC ===")
        r = await client.post("http://localhost:5000/api/agentic/execute", json={
            "request": "Assess risk for a $2000 purchase from Office Depot LLC for Operations department"
        })
        data = r.json()
        result = data.get("result", {})
        pr = result.get("primary_result", {})
        inner = pr.get("result", {})
        bd = inner.get("breakdown", {})
        vr = bd.get("vendor_risk", {})
        print(f"  risk_level={inner.get('risk_level')}")
        print(f"  vendor_concerns={vr.get('concerns', [])}")
        print(f"  risk_score={inner.get('risk_score')}")

asyncio.run(test())
