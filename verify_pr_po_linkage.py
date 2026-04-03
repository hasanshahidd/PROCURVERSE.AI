"""
Verify PR → PO linkage is stored correctly
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
import requests

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

print("=" * 80)
print("🔗 VERIFYING PR → PO LINKAGE")
print("=" * 80)

# Check workflows with PO IDs
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor(cursor_factory=RealDictCursor)

cur.execute("""
    SELECT 
        pr_number,
        department,
        total_amount,
        workflow_status,
        odoo_po_id,
        created_at
    FROM pr_approval_workflows
    WHERE workflow_status = 'completed'
    ORDER BY created_at DESC
    LIMIT 5
""")

workflows = cur.fetchall()

print(f"\n📋 Found {len(workflows)} completed workflows:")
print("=" * 80)

for w in workflows:
    print(f"\n✅ {w['pr_number']}")
    print(f"   Department: {w['department']}")
    print(f"   Amount: ${w['total_amount']:,.2f}")
    print(f"   Status: {w['workflow_status']}")
    print(f"   Odoo PO ID: {w['odoo_po_id'] or 'Not linked'}")
    print(f"   Created: {w['created_at']}")
    
    # If PO exists, fetch it from Odoo
    if w['odoo_po_id']:
        try:
            response = requests.get(
                f"http://localhost:5000/api/odoo/purchase-orders",
                params={"limit": 100}
            )
            if response.status_code == 200:
                data = response.json()
                pos = data.get('data', [])
                po = next((p for p in pos if p['id'] == w['odoo_po_id']), None)
                if po:
                    print(f"   📦 PO Name: {po['name']}")
                    print(f"   📦 PO State: {po['state']}")
                    print(f"   📦 PO Amount: ${po['amount_total']:,.2f}")
                    vendor = po.get('partner_id')
                    if isinstance(vendor, list) and len(vendor) > 1:
                        print(f"   📦 Vendor: {vendor[1]}")
        except Exception as e:
            print(f"   ⚠️  Could not fetch PO from Odoo: {e}")

cur.close()
conn.close()

print("\n" + "=" * 80)
print("✅ LINKAGE VERIFICATION COMPLETE")
print("=" * 80)
