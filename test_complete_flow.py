"""
Test COMPLETE flow: Create PR → Approve all levels → Verify PO linkage
"""

import requests
import time
import json

BASE_URL = "http://localhost:5000/api/agentic"

print("=" * 80)
print("🧪 TESTING COMPLETE PR → PO FLOW WITH LINKAGE")
print("=" * 80)

# Step 1: Create new PR via orchestrator
print("\n1️⃣  Creating new PR via orchestrator...")
response = requests.post(
    f"{BASE_URL}/execute",
    json={
        "request": "Create purchase requisition for IT department",
        "pr_data": {
            "department": "IT",
            "budget": 50000,
            "budget_category": "CAPEX",
            "requester": "Test User",
            "description": "Test PR for PO linkage verification"
        }
    }
)

if response.status_code == 200:
    result = response.json()
    print(f"✅ PR created: {json.dumps(result, indent=2)[:500]}")
    
    # Extract PR number from result
    pr_number = result.get('result', {}).get('pr_number')
    if not pr_number:
        # Try to extract from message
        message = str(result)
        if 'PR-' in message:
            import re
            match = re.search(r'PR-\d{4}-\d{10}', message)
            if match:
                pr_number = match.group(0)
    
    if pr_number:
        print(f"📋 PR Number: {pr_number}")
        
        # Step 2: Approve all 3 levels
        approvers = [
            {"email": "mike.manager@company.com", "name": "Mike Manager", "level": 1},
            {"email": "diana.director@company.com", "name": "Diana Director", "level": 2},
            {"email": "victor.vp@company.com", "name": "Victor VP", "level": 3}
        ]
        
        for approver in approvers:
            print(f"\n{approver['level']}️⃣  {approver['name']} approving...")
            time.sleep(1)
            
            response = requests.post(
                f"{BASE_URL}/approval-workflows/{pr_number}/approve",
                json={
                    "approver_email": approver['email'],
                    "notes": f"Approved at level {approver['level']} for linkage test"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ Approved! Remaining: {result['remaining_steps']}")
                
                if result['completed']:
                    print(f"\n🎉 WORKFLOW COMPLETE!")
                    if result.get('odoo_po_id'):
                        print(f"🔗 Odoo PO ID: {result['odoo_po_id']}")
                    else:
                        print(f"⚠️  No PO ID in response")
            else:
                print(f"   ❌ Error: {response.text}")
                break
        
        # Step 3: Verify linkage in database
        print(f"\n3️⃣  Verifying linkage in database...")
        time.sleep(2)
        
        import psycopg2
        from psycopg2.extras import RealDictCursor
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT pr_number, workflow_status, odoo_po_id 
            FROM pr_approval_workflows 
            WHERE pr_number = %s
        """, (pr_number,))
        
        workflow = cur.fetchone()
        if workflow:
            print(f"   PR: {workflow['pr_number']}")
            print(f"   Status: {workflow['workflow_status']}")
            print(f"   Odoo PO ID: {workflow['odoo_po_id']}")
            
            if workflow['odoo_po_id']:
                print(f"\n✅✅✅ SUCCESS! PR → PO LINKAGE WORKING!")
            else:
                print(f"\n❌ FAILED - PO ID not stored in database")
        
        cur.close()
        conn.close()
    else:
        print("❌ Could not extract PR number from response")
else:
    print(f"❌ Error creating PR: {response.text}")

print("\n" + "=" * 80)
print("✅ TEST COMPLETE")
print("=" * 80)
