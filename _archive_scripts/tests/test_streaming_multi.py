"""Test multi-intent streaming endpoint."""
import requests, json

r = requests.post(
    "http://localhost:5000/api/agentic/execute/stream",
    json={
        "request": "Check budget for IT 75000 CAPEX and assess vendor risk for TechFlow and route for approval",
        "pr_data": {"department": "IT", "budget": 75000, "budget_category": "CAPEX", "vendor_name": "TechFlow"},
    },
    stream=True,
    headers={"Accept": "text/event-stream"},
)

events = []
for line in r.iter_lines(decode_unicode=True):
    if line and line.startswith("data:"):
        try:
            event = json.loads(line[5:].strip())
            etype = event.get("type", "?")
            events.append(etype)
            if etype == "complete":
                d = event.get("data", {})
                r2 = d.get("result", {})
                # Check if multi-intent
                if "intent_count" in r2 or "results" in r2:
                    print("MULTI-INTENT DETECTED!")
                    print(f"  intent_count: {r2.get('intent_count')}")
                    results = r2.get("results", [])
                    for i, res in enumerate(results):
                        pr = res.get("primary_result", res)
                        agent = pr.get("agent", "?")
                        dec = pr.get("decision", {})
                        act = dec.get("action", "?")[:50]
                        conf = dec.get("confidence", "?")
                        print(f"  [{i+1}] agent={agent}, action={act}, confidence={conf}")
                else:
                    # check nested result
                    inner = r2.get("result", {})
                    if "intent_count" in inner or "results" in inner:
                        print("MULTI-INTENT DETECTED (nested)!")
                        results = inner.get("results", [])
                        print(f"  intent_count: {inner.get('intent_count')}")
                        for i, res in enumerate(results):
                            pr = res.get("primary_result", res)
                            agent = pr.get("agent", "?")
                            dec = pr.get("decision", {})
                            act = dec.get("action", "?")[:50]
                            conf = dec.get("confidence", "?")
                            print(f"  [{i+1}] agent={agent}, action={act}, confidence={conf}")
                    else:
                        agent_top = r2.get("agent", "?")
                        print(f"SINGLE RESULT: agent={agent_top}")
                        pr = inner.get("primary_result", {})
                        if pr:
                            print(f"  primary_result.agent={pr.get('agent', '?')}")
                break
        except Exception as e:
            print(f"Parse error: {e}")

print(f"\nTotal events: {len(events)}")
print(f"Event types: {events}")
