"""
Test Odoo PO Creation Integration
This will approve all steps of PR-2026-0002 to trigger PO creation
"""

import requests
import json
import time

BASE_URL = "http://localhost:5000/api/agentic"

def approve_pr_all_levels(pr_number):
    """Approve PR through all 3 levels"""
    
    print("=" * 80)
    print(f"🧪 TESTING ODOO PO CREATION FOR {pr_number}")
    print("=" * 80)
    
    # Get workflow details first
    response = requests.get(f"{BASE_URL}/approval-workflows")
    workflows = response.json()
    
    target_workflow = None
    for w in workflows['workflows']:
        if w['pr_number'] == pr_number:
            target_workflow = w
            break
    
    if not target_workflow:
        print(f"❌ Workflow {pr_number} not found")
        return
    
    print(f"\n📋 Workflow Details:")
    print(f"   PR: {target_workflow['pr_number']}")
    print(f"   Department: {target_workflow['department']}")
    print(f"   Amount: ${target_workflow['total_amount']:,.2f}")
    print(f"   Status: {target_workflow['workflow_status']}")
    print(f"   Current Level: {target_workflow['current_approval_level']}")
    
    # Approval chain
    approvers = [
        {"level": 1, "email": "mike.manager@company.com", "name": "Mike Manager"},
        {"level": 2, "email": "diana.director@company.com", "name": "Diana Director"},
        {"level": 3, "email": "victor.vp@company.com", "name": "Victor VP"}
    ]
    
    # Approve each level
    for approver in approvers:
        if approver['level'] >= target_workflow['current_approval_level']:
            print(f"\n{'='*80}")
            print(f"📝 Level {approver['level']}: {approver['name']} approving...")
            print(f"{'='*80}")
            
            response = requests.post(
                f"{BASE_URL}/approval-workflows/{pr_number}/approve",
                json={
                    "approver_email": approver['email'],
                    "notes": f"Approved at Level {approver['level']} for Odoo integration test"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Approval successful!")
                print(f"   Remaining steps: {result['remaining_steps']}")
                print(f"   Workflow complete: {result['completed']}")
                
                if result['completed']:
                    print(f"\n{'='*80}")
                    print(f"🎉 ALL APPROVALS COMPLETE!")
                    print(f"🚀 CHECK BACKEND LOGS FOR ODOO PO CREATION!")
                    print(f"{'='*80}")
                    print(f"\nExpected in logs:")
                    print(f"  - 🚀 TRIGGERING ODOO PO CREATION...")
                    print(f"  - 🏪 Using vendor: [vendor name]")
                    print(f"  - 📦 Product: [product name]")
                    print(f"  - ✅✅✅ PURCHASE ORDER CREATED IN ODOO!")
                    print(f"  - 🆔 Odoo PO ID: [ID]")
                    print(f"  - 🔗 PR {pr_number} → PO [ID]")
                
                time.sleep(1)  # Brief pause between approvals
            else:
                print(f"❌ Approval failed: {response.text}")
                break
    
    print(f"\n{'='*80}")
    print(f"✅ TEST COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    # Test with PR-2026-0002 (Finance, $120,000)
    approve_pr_all_levels("PR-2026-0002")
