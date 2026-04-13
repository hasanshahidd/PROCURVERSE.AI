"""Dump all SSE events from streaming endpoint."""
import requests
import json

url = "http://localhost:5000/api/agentic/execute/stream"
r = requests.post(url, json={"request": "Check budget for Operations department CAPEX, 50000"}, stream=True, timeout=30)
for line in r.iter_lines():
    if line:
        txt = line.decode("utf-8")
        if txt.startswith("data: "):
            d = json.loads(txt[6:])
            etype = d.get("type", "")
            print(f"[{etype}] ", end="")
            if etype == "complete":
                print(json.dumps(d, indent=2)[:3000])
            elif etype == "error":
                print(d.get("message"))
            else:
                # Brief summary for other events
                keys = list(d.keys())
                print(keys)
