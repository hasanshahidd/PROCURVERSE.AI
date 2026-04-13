import httpx, json
r = httpx.get("http://localhost:5000/api/odoo/vendors", timeout=10)
data = r.json()
vendors = data.get("vendors", data.get("data", []))
for v in vendors[:20]:
    vid = v.get("id")
    vname = v.get("name")
    print(f"  ID={vid}, Name={vname}")
print(f"\nTotal: {len(vendors)}")
