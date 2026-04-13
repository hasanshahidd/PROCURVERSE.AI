"""
Simple check for Odoo PO creation
"""
import requests
import json

BASE_URL = "http://localhost:5000/api/odoo"

print("🔍 Fetching purchase orders from Odoo...")
response = requests.get(f"{BASE_URL}/purchase-orders?limit=10")

if response.status_code == 200:
    data = response.json()
    print(f"\n📦 Response structure:")
    print(json.dumps(data, indent=2, default=str))
    
    if 'data' in data:
        orders = data['data']
        print(f"\n✅ Found {len(orders)} purchase orders")
        
        if orders:
            print(f"\n📋 Most recent PO:")
            latest = orders[0]
            print(f"   ID: {latest.get('id')}")
            print(f"   Name: {latest.get('name')}")
            print(f"   State: {latest.get('state')}")
            print(f"   Amount: ${latest.get('amount_total', 0):,.2f}")
            
            partner = latest.get('partner_id')
            if isinstance(partner, list) and len(partner) > 1:
                print(f"   Vendor: {partner[1]}")
else:
    print(f"❌ Error: {response.status_code}")
    print(response.text)
