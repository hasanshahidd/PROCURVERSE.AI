"""
Test Suite: Risk Assessment Agent with Odoo Write Integration
Week 1 Day 3-4: Verify risk assessment storage and CRITICAL risk blocking

Tests 4 risk scenarios:
1. LOW risk → Approve with normal process
2. MEDIUM risk → Require manager review
3. HIGH risk → Require director approval + mitigation plan
4. CRITICAL risk → Block PO creation + immediate escalation
"""

import asyncio
import sys
import os
import json
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

load_dotenv()  # CRITICAL: Load environment before importing agents

from backend.agents.risk_assessment import RiskAssessmentAgent
from backend.services.odoo_client import get_odoo_client
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")


def print_test_header(test_name: str):
    """Print formatted test header"""
    print("\n" + "="*80)
    print(f"TEST: {test_name}")
    print("="*80)


def print_result(passed: bool, message: str):
    """Print test result"""
    symbol = "✅" if passed else "❌"
    status = "PASS" if passed else "FAIL"
    print(f"{symbol} {status}: {message}")


def verify_database_storage(pr_number: str) -> dict:
    """Verify risk assessment was stored in database"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT id, pr_number, total_risk_score, risk_level, 
                   blocked_po_creation, vendor_name, budget_amount,
                   assessed_at
            FROM po_risk_assessments
            WHERE pr_number = %s
            ORDER BY assessed_at DESC
            LIMIT 1
        """, (pr_number,))
        
        result = cur.fetchone()
        return dict(result) if result else None
    
    finally:
        cur.close()
        conn.close()


async def test_low_risk_scenario():
    """
    Test 1: LOW RISK SCENARIO
    - Small purchase ($5,000)
    - Known vendor (TechSupply)
    - Normal urgency
    - Expected: Approve with low risk, NO PO blocking
    """
    print_test_header("LOW RISK SCENARIO ($5K, Known Vendor)")
    
    agent = RiskAssessmentAgent()
    
    pr_data = {
        "pr_number": f"PR-TEST-LOW-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "vendor_name": "TechSupply",
        "vendor_id": 14,  # Assuming TechSupply has ID 14
        "supplier_category": "Electronics",
        "budget": 5000,
        "total_amount": 5000,
        "department": "IT",
        "priority_level": "Medium",
        "quantity": 10,
        "description": "Standard office laptops - routine purchase",
        "requester_name": "John Doe"
    }
    
    print(f"\n📋 PR Data:")
    print(f"   PR Number: {pr_data['pr_number']}")
    print(f"   Vendor: {pr_data['vendor_name']}")
    print(f"   Budget: ${pr_data['budget']:,}")
    print(f"   Department: {pr_data['department']}")
    
    # Execute risk assessment
    print("\n🔍 Running risk assessment...")
    result = await agent.execute({
        "request": "Assess procurement risks for low-value routine purchase",
        "pr_data": pr_data
    })
    
    print(f"\n📊 Risk Assessment Results:")
    print(f"   Risk Score: {result.get('risk_score', 0):.1f}/100")
    print(f"   Risk Level: {result.get('risk_level', 'UNKNOWN')}")
    print(f"   Can Proceed: {result.get('can_proceed', False)}")
    print(f"   PO Blocked: {result.get('blocked_po_creation', False)}")
    print(f"   Requires Human Review: {result.get('requires_human_review', False)}")
    
    # Verify database storage
    print("\n💾 Verifying database storage...")
    db_record = verify_database_storage(pr_data['pr_number'])
    
    # Assertions
    tests_passed = []
    
    # Check risk level is LOW
    is_low_risk = result.get('risk_level') == 'LOW'
    print_result(is_low_risk, f"Risk level is LOW (Got: {result.get('risk_level')})")
    tests_passed.append(is_low_risk)
    
    # Check PO not blocked
    not_blocked = not result.get('blocked_po_creation', True)
    print_result(not_blocked, f"PO creation NOT blocked")
    tests_passed.append(not_blocked)
    
    # Check can proceed
    can_proceed = result.get('can_proceed', False)
    print_result(can_proceed, "Can proceed with normal approval")
    tests_passed.append(can_proceed)
    
    # Check database storage
    db_stored = db_record is not None
    print_result(db_stored, f"Risk assessment stored in database (ID: {db_record['id'] if db_record else 'N/A'})")
    tests_passed.append(db_stored)
    
    if db_record:
        print(f"\n   Database Record:")
        print(f"   - Risk Score: {db_record['total_risk_score']}")
        print(f"   - Risk Level: {db_record['risk_level']}")
        print(f"   - Blocked: {db_record['blocked_po_creation']}")
    
    all_passed = all(tests_passed)
    print(f"\n{'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}: {sum(tests_passed)}/{len(tests_passed)}")
    
    return all_passed


async def test_medium_risk_scenario():
    """
    Test 2: MEDIUM RISK SCENARIO
    - Moderate purchase ($30,000)
    - High urgency
    - Expected: Medium risk, require manager review, NO PO blocking
    """
    print_test_header("MEDIUM RISK SCENARIO ($30K, High Urgency)")
    
    agent = RiskAssessmentAgent()
    
    pr_data = {
        "pr_number": f"PR-TEST-MEDIUM-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "vendor_name": "Office Depot",
        "vendor_id": 15,
        "supplier_category": "Office Supplies",
        "budget": 30000,
        "total_amount": 30000,
        "department": "Operations",
        "priority_level": "High",
        "quantity": 100,
        "description": "Bulk office furniture order with tight deadline",
        "requester_name": "Jane Smith"
    }
    
    print(f"\n📋 PR Data:")
    print(f"   PR Number: {pr_data['pr_number']}")
    print(f"   Vendor: {pr_data['vendor_name']}")
    print(f"   Budget: ${pr_data['budget']:,}")
    print(f"   Urgency: {pr_data['priority_level']}")
    
    print("\n🔍 Running risk assessment...")
    result = await agent.execute({
        "request": "Assess procurement risks for urgent moderate-value purchase",
        "pr_data": pr_data
    })
    
    print(f"\n📊 Risk Assessment Results:")
    print(f"   Risk Score: {result.get('risk_score', 0):.1f}/100")
    print(f"   Risk Level: {result.get('risk_level', 'UNKNOWN')}")
    print(f"   Can Proceed: {result.get('can_proceed', False)}")
    print(f"   PO Blocked: {result.get('blocked_po_creation', False)}")
    print(f"   Requires Human Review: {result.get('requires_human_review', False)}")
    
    db_record = verify_database_storage(pr_data['pr_number'])
    
    tests_passed = []
    
    # Check risk level is MEDIUM
    is_medium_risk = result.get('risk_level') == 'MEDIUM'
    print_result(is_medium_risk, f"Risk level is MEDIUM (Got: {result.get('risk_level')})")
    tests_passed.append(is_medium_risk)
    
    # Check PO not blocked
    not_blocked = not result.get('blocked_po_creation', True)
    print_result(not_blocked, "PO creation NOT blocked (manager review only)")
    tests_passed.append(not_blocked)
    
    # Check database storage
    db_stored = db_record is not None
    print_result(db_stored, f"Risk assessment stored in database")
    tests_passed.append(db_stored)
    
    all_passed = all(tests_passed)
    print(f"\n{'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}: {sum(tests_passed)}/{len(tests_passed)}")
    
    return all_passed


async def test_high_risk_scenario():
    """
    Test 3: HIGH RISK SCENARIO
    - Large purchase ($75,000)
    - Unclear vendor reliability
    - High urgency
    - Expected: High risk, require director approval + mitigation plan, NO PO blocking
    """
    print_test_header("HIGH RISK SCENARIO ($75K, Uncertain Vendor)")
    
    agent = RiskAssessmentAgent()
    
    pr_data = {
        "pr_number": f"PR-TEST-HIGH-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "vendor_name": "Unknown Supplier Corp",
        "supplier_category": "Industrial Equipment",
        "budget": 75000,
        "total_amount": 75000,
        "department": "Operations",
        "priority_level": "High",
        "quantity": 5,
        "description": "Specialized machinery from new vendor with urgent deadline",
        "requester_name": "Mike Manager"
    }
    
    print(f"\n📋 PR Data:")
    print(f"   PR Number: {pr_data['pr_number']}")
    print(f"   Vendor: {pr_data['vendor_name']}")
    print(f"   Budget: ${pr_data['budget']:,}")
    print(f"   Category: {pr_data['supplier_category']}")
    
    print("\n🔍 Running risk assessment...")
    result = await agent.execute({
        "request": "Assess procurement risks for large urgent purchase from new vendor",
        "pr_data": pr_data
    })
    
    print(f"\n📊 Risk Assessment Results:")
    print(f"   Risk Score: {result.get('risk_score', 0):.1f}/100")
    print(f"   Risk Level: {result.get('risk_level', 'UNKNOWN')}")
    print(f"   Can Proceed: {result.get('can_proceed', False)}")
    print(f"   PO Blocked: {result.get('blocked_po_creation', False)}")
    print(f"   Mitigations: {len(result.get('mitigations', []))}")
    
    if result.get('mitigations'):
        print(f"\n   Top 3 Mitigations:")
        for i, mitigation in enumerate(result.get('mitigations', [])[:3], 1):
            print(f"   {i}. {mitigation}")
    
    db_record = verify_database_storage(pr_data['pr_number'])
    
    tests_passed = []
    
    # Check risk level is HIGH
    is_high_risk = result.get('risk_level') == 'HIGH'
    print_result(is_high_risk, f"Risk level is HIGH (Got: {result.get('risk_level')})")
    tests_passed.append(is_high_risk)
    
    # Check PO not blocked (HIGH allows proceeding with approval)
    not_blocked = not result.get('blocked_po_creation', True)
    print_result(not_blocked, "PO creation NOT blocked (director approval required)")
    tests_passed.append(not_blocked)
    
    # Check mitigations provided
    has_mitigations = len(result.get('mitigations', [])) > 0
    print_result(has_mitigations, f"Mitigation plan provided ({len(result.get('mitigations', []))} recommendations)")
    tests_passed.append(has_mitigations)
    
    # Check database storage
    db_stored = db_record is not None
    print_result(db_stored, "Risk assessment stored in database")
    tests_passed.append(db_stored)
    
    all_passed = all(tests_passed)
    print(f"\n{'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}: {sum(tests_passed)}/{len(tests_passed)}")
    
    return all_passed


async def test_critical_risk_scenario():
    """
    Test 4: CRITICAL RISK SCENARIO
    - Very large purchase ($250,000)
    - Unknown vendor
    - High urgency
    - High budget utilization
    - Expected: CRITICAL risk, PO BLOCKED, immediate escalation
    """
    print_test_header("CRITICAL RISK SCENARIO ($250K, Unknown Vendor, High Urgency)")
    
    agent = RiskAssessmentAgent()
    
    pr_data = {
        "pr_number": f"PR-TEST-CRITICAL-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "vendor_name": "Unverified Mega Corp",
        "supplier_category": "Industrial Equipment",
        "budget": 250000,
        "total_amount": 250000,
        "department": "Operations",
        "priority_level": "URGENT",
        "quantity": 1,
        "description": "Single-source critical equipment from unvetted vendor with immediate need",
        "requester_name": "Urgent User"
    }
    
    print(f"\n📋 PR Data:")
    print(f"   PR Number: {pr_data['pr_number']}")
    print(f"   Vendor: {pr_data['vendor_name']} (UNVERIFIED)")
    print(f"   Budget: ${pr_data['budget']:,}")
    print(f"   Urgency: {pr_data['priority_level']}")
    print(f"   Single Source: Yes (Quantity: 1)")
    
    print("\n🔍 Running risk assessment...")
    result = await agent.execute({
        "request": "Assess procurement risks for urgent high-value purchase from unknown vendor",
        "pr_data": pr_data
    })
    
    print(f"\n📊 Risk Assessment Results:")
    print(f"   Risk Score: {result.get('risk_score', 0):.1f}/100")
    print(f"   Risk Level: {result.get('risk_level', 'UNKNOWN')}")
    print(f"   Can Proceed: {result.get('can_proceed', False)}")
    print(f"   🚫 PO BLOCKED: {result.get('blocked_po_creation', False)}")
    print(f"   Human Review Required: {result.get('requires_human_review', False)}")
    
    if result.get('mitigations'):
        print(f"\n   Recommended Mitigations:")
        for i, mitigation in enumerate(result.get('mitigations', [])[:5], 1):
            print(f"   {i}. {mitigation}")
    
    db_record = verify_database_storage(pr_data['pr_number'])
    
    tests_passed = []
    
    # Check risk level is CRITICAL
    is_critical_risk = result.get('risk_level') == 'CRITICAL'
    print_result(is_critical_risk, f"Risk level is CRITICAL (Got: {result.get('risk_level')})")
    tests_passed.append(is_critical_risk)
    
    # Check PO IS blocked (THIS IS THE KEY TEST!)
    po_blocked = result.get('blocked_po_creation', False)
    print_result(po_blocked, "🚫 PO CREATION BLOCKED (Critical risk protection)")
    tests_passed.append(po_blocked)
    
    # Check human review required
    human_review = result.get('requires_human_review', False)
    print_result(human_review, "Human review REQUIRED")
    tests_passed.append(human_review)
    
    # Check cannot proceed automatically
    cannot_proceed = not result.get('can_proceed', True)
    print_result(cannot_proceed, "Cannot proceed automatically")
    tests_passed.append(cannot_proceed)
    
    # Check database storage with blocked flag
    db_stored = db_record is not None
    print_result(db_stored, "Risk assessment stored in database")
    tests_passed.append(db_stored)
    
    if db_record:
        blocked_in_db = db_record.get('blocked_po_creation', False)
        print_result(blocked_in_db, f"Blocked flag persisted in database: {blocked_in_db}")
        tests_passed.append(blocked_in_db)
        
        print(f"\n   Database Record:")
        print(f"   - Risk Score: {db_record['total_risk_score']}")
        print(f"   - Risk Level: {db_record['risk_level']}")
        print(f"   - 🚫 BLOCKED: {db_record['blocked_po_creation']}")
    
    all_passed = all(tests_passed)
    print(f"\n{'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}: {sum(tests_passed)}/{len(tests_passed)}")
    
    return all_passed


async def run_all_tests():
    """Run comprehensive test suite"""
    print("\n" + "="*80)
    print("RISK ASSESSMENT AGENT - COMPREHENSIVE TEST SUITE")
    print("Week 1 Day 3-4: Risk Storage + CRITICAL Risk Blocking")
    print("="*80)
    
    # Verify Odoo connection
    print("\n🔍 Verifying Odoo connection...")
    try:
        odoo = get_odoo_client()
        vendors = odoo.get_vendors(limit=5)
        print(f"   ✅ Odoo connected: {len(vendors)} vendors found")
    except Exception as e:
        print(f"   ❌ Odoo connection failed: {e}")
        return
    
    # Verify database table exists
    print("\n🔍 Verifying po_risk_assessments table...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM po_risk_assessments")
        count = cur.fetchone()[0]
        print(f"   ✅ Table exists with {count} existing records")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"   ❌ Table verification failed: {e}")
        return
    
    # Run all tests
    results = []
    
    print("\n" + "▶"*40)
    print("STARTING TESTS")
    print("▶"*40)
    
    results.append(("LOW RISK", await test_low_risk_scenario()))
    results.append(("MEDIUM RISK", await test_medium_risk_scenario()))
    results.append(("HIGH RISK", await test_high_risk_scenario()))
    results.append(("CRITICAL RISK", await test_critical_risk_scenario()))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUITE SUMMARY")
    print("="*80)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    total_passed = sum(1 for _, passed in results if passed)
    total_tests = len(results)
    
    print("\n" + "="*80)
    if total_passed == total_tests:
        print(f"🎉 SUCCESS: ALL {total_tests} TESTS PASSED!")
        print("\n✅ Risk Assessment Agent Integration Complete:")
        print("   - Risk scores calculated accurately")
        print("   - Risk assessments stored in database")
        print("   - CRITICAL risks block PO creation")
        print("   - All risk levels handled correctly")
    else:
        print(f"⚠️ PARTIAL SUCCESS: {total_passed}/{total_tests} tests passed")
        print("\n❌ Failed tests need investigation")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
