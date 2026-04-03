"""
Check if Odoo PO was created for the approved PRs
"""

import requests

BASE_URL = "http://localhost:5000/api/odoo"

# Check Odoo connection
print("🔍 Checking Odoo connection...")
response = requests.get(f"{BASE_URL}/status")
status = response.json()
print(f"Odoo Status: {status}")

# Get recent purchase orders
print("\n🔍 Fetching recent purchase orders from Odoo...")
response = requests.get(f"{BASE_URL}/purchase-orders?limit=5")
if response.status_code == 200:
    data = response.json()
    
    # Check if response is a list or dict
    if isinstance(data, dict):
        orders = data.get('orders', data.get('data', []))
    else:
        orders = data
    
    print(f"\n📋 Found {len(orders)} recent purchase orders:")
    print("=" * 80)
    
    for order in orders:
        # Handle if order is a string (error case)
        if isinstance(order, str):
            print(f"\n⚠️ Unexpected string response: {order}")
            continue
            
        print(f"\n🆔 PO ID: {order.get('id')}")
        print(f"   Name: {order.get('name', 'N/A')}")
        
        # Handle partner_id which can be [id, name] or just id
        partner = order.get('partner_id', 'N/A')
        if isinstance(partner, list) and len(partner) > 1:
            print(f"   Partner: {partner[1]}")
        else:
            print(f"   Partner: {partner}")
            
        print(f"   State: {order.get('state', 'N/A')}")
        print(f"   Amount: ${order.get('amount_total', 0):,.2f}")
        print(f"   Date: {order.get('date_order', 'N/A')}")
else:
    print(f"❌ Error fetching POs: {response.text}")
