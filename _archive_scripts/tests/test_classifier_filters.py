"""Test classifier filter extraction for vendor_name."""
import asyncio, json
from backend.services.query_router import classify_query_intent

async def test():
    queries = [
        "Evaluate risk for buying 2000 of paper from Office Depot LLC for Operations",
        "Route PR-2026-0200 for approval, IT department, $12,000 purchase",
        "Find best vendor for electronics equipment, budget 50000",
        "Check if Operations department has budget for a $15,000 OPEX purchase",
    ]
    for q in queries:
        result = await classify_query_intent(q)
        intents = result.get("intents", [])
        print(f"Query: {q[:60]}...")
        for i, intent in enumerate(intents):
            qt = intent.get("query_type", "?")
            ds = intent.get("data_source", "?")
            filters = intent.get("filters", {})
            print(f"  Intent {i}: type={qt}, source={ds}")
            print(f"    Filters: {json.dumps(filters)}")
        print()

asyncio.run(test())
