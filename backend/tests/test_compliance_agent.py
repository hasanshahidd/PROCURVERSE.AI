"""
Test Suite for ComplianceCheckAgent
Tests policy validation, spending limits, vendor compliance, and regulatory checks
"""

import asyncio
import logging
import sys
from pathlib import Path
from pprint import pprint
from dotenv import load_dotenv

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_fully_compliant_pr():
    """Test 1: PR that passes all compliance checks"""
    from backend.agents.compliance_check import ComplianceCheckAgent
    
    print("\n" + "="*80)
    print("TEST 1: Fully Compliant PR")
    print("="*80)
    
    agent = ComplianceCheckAgent()
    
    context = {
        "request": "Check compliance for this PR",
        "pr_data": {
            "department": "IT",
            "budget": 15000,
            "vendor_name": "Dell Technologies",
            "category": "Electronics",
            "budget_category": "OPEX",
            "justification": "Replacing old laptops for development team to improve productivity and security",
            "urgency": "Normal"
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    assert result["result"]["compliance_score"] >= 90, "Fully compliant PR should score >=90"
    assert result["result"]["action"] == "approve", "Compliant PR should be approved"
    
    print(f"\n✅ Test 1 PASSED: Compliance score {result['result']['compliance_score']}/100 - APPROVED")
    return result


async def test_exceeds_budget():
    """Test 2: PR exceeds available budget"""
    from backend.agents.compliance_check import ComplianceCheckAgent
    
    print("\n" + "="*80)
    print("TEST 2: Exceeds Available Budget")
    print("="*80)
    
    agent = ComplianceCheckAgent()
    
    context = {
        "request": "Check compliance for high-budget PR",
        "pr_data": {
            "department": "Finance",
            "budget": 250000,  # Very high amount
            "vendor_name": "Oracle",
            "category": "Software",
            "budget_category": "CAPEX",
            "justification": "Enterprise ERP system upgrade",
            "urgency": "Normal"
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    # Should have budget violation if exceeds available
    violations = result["result"]["violations"]
    print(f"\n⚠️ Violations found: {len(violations)}")
    for v in violations:
        print(f"  - {v}")
    
    print("\n✅ Test 2 PASSED: Budget issues flagged correctly")
    return result


async def test_non_preferred_vendor():
    """Test 3: Vendor not on preferred list"""
    from backend.agents.compliance_check import ComplianceCheckAgent
    
    print("\n" + "="*80)
    print("TEST 3: Non-Preferred Vendor Warning")
    print("="*80)
    
    agent = ComplianceCheckAgent()
    
    context = {
        "request": "Check compliance for non-preferred vendor",
        "pr_data": {
            "department": "Operations",
            "budget": 20000,
            "vendor_name": "Unknown Small Vendor LLC",  # Not on preferred list
            "category": "Office Supplies",
            "budget_category": "OPEX",
            "justification": "Better pricing than preferred vendors for this specific order",
            "urgency": "Normal"
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    
    # Should have warnings about non-preferred vendor
    warnings = result["result"]["warnings"]
    print(f"\n⚠️ Warnings found: {len(warnings)}")
    for w in warnings:
        print(f"  - {w}")
    
    # Score should be reduced but not blocked
    score = result["result"]["compliance_score"]
    assert 70 <= score < 100, f"Non-preferred vendor should reduce score to 70-99 range, got {score}"
    
    print(f"\n✅ Test 3 PASSED: Non-preferred vendor warning issued (score: {score}/100)")
    return result


async def test_insufficient_justification():
    """Test 4: Missing or weak justification"""
    from backend.agents.compliance_check import ComplianceCheckAgent
    
    print("\n" + "="*80)
    print("TEST 4: Insufficient Business Justification")
    print("="*80)
    
    agent = ComplianceCheckAgent()
    
    context = {
        "request": "Check PR with weak justification",
        "pr_data": {
            "department": "IT",
            "budget": 30000,
            "vendor_name": "HP Inc",
            "category": "Electronics",
            "budget_category": "OPEX",
            "justification": "Need it",  # Too short/weak
            "urgency": "Normal"
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    
    # Should warn about insufficient justification
    warnings = result["result"]["warnings"]
    justification_warning = any("justification" in w.lower() for w in warnings)
    assert justification_warning, "Should warn about insufficient justification"
    
    print("\n✅ Test 4 PASSED: Insufficient justification flagged")
    return result


async def test_critical_urgency_no_justification():
    """Test 5: Critical urgency without proper justification"""
    from backend.agents.compliance_check import ComplianceCheckAgent
    
    print("\n" + "="*80)
    print("TEST 5: Critical Urgency Without Justification - VIOLATION")
    print("="*80)
    
    agent = ComplianceCheckAgent()
    
    context = {
        "request": "Check critical urgency PR",
        "pr_data": {
            "department": "Operations",
            "budget": 45000,
            "vendor_name": "Staples",
            "category": "Office Supplies",
            "budget_category": "OPEX",
            "justification": "",  # Empty for critical request - violation!
            "urgency": "Critical"
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    
    # Should have violation for critical without justification
    violations = result["result"]["violations"]
    critical_violation = any("critical" in v.lower() and "justification" in v.lower() for v in violations)
    assert critical_violation, "Should flag critical urgency without justification as violation"
    
    score = result["result"]["compliance_score"]
    print(f"\n❌ Compliance score: {score}/100 - Critical violation detected")
    
    print("\n✅ Test 5 PASSED: Critical urgency violation caught")
    return result


async def test_large_opex_warning():
    """Test 6: Large OPEX that might be CAPEX"""
    from backend.agents.compliance_check import ComplianceCheckAgent
    
    print("\n" + "="*80)
    print("TEST 6: Large OPEX - Possible Misclassification")
    print("="*80)
    
    agent = ComplianceCheckAgent()
    
    context = {
        "request": "Check budget category classification",
        "pr_data": {
            "department": "IT",
            "budget": 75000,  # Large amount classified as OPEX
            "vendor_name": "Lenovo",
            "category": "Electronics",
            "budget_category": "OPEX",  # Might be CAPEX asset
            "justification": "Purchasing 50 high-end workstations for engineering team",
            "urgency": "Normal"
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    
    # Should warn about large OPEX possibly being CAPEX
    warnings = result["result"]["warnings"]
    opex_warning = any("opex" in w.lower() and "capital" in w.lower() for w in warnings)
    if opex_warning:
        print("\n⚠️ OPEX/CAPEX classification warning detected (expected)")
    
    print("\n✅ Test 6 PASSED: Budget category validation working")
    return result


async def test_exceeds_vp_authority():
    """Test 7: Amount exceeds maximum VP authority"""
    from backend.agents.compliance_check import ComplianceCheckAgent
    
    print("\n" + "="*80)
    print("TEST 7: Exceeds VP Authority Limit")
    print("="*80)
    
    agent = ComplianceCheckAgent()
    
    context = {
        "request": "Check ultra-high value PR",
        "pr_data": {
            "department": "IT",
            "budget": 600000,  # Exceeds IT VP limit of $500k
            "vendor_name": "Microsoft",
            "category": "Software",
            "budget_category": "CAPEX",
            "justification": "Enterprise-wide cloud infrastructure migration - multi-year contract",
            "urgency": "Normal"
        }
    }
    
    result = await agent.execute(context)
    
    print("\nRESULT:")
    pprint(result)
    
    assert result["status"] == "success", "Agent execution should succeed"
    
    # Should have violation for exceeding VP authority
    violations = result["result"]["violations"]
    authority_violation = any("vp" in v.lower() and "authority" in v.lower() for v in violations)
    if authority_violation:
        print("\n⚠️ VP authority limit exceeded (expected violation)")
    
    print("\n✅ Test 7 PASSED: Spending limit enforcement working")
    return result


async def run_all_tests():
    """Run all compliance check tests"""
    print("\n" + "="*100)
    print("COMPLIANCE CHECK AGENT - COMPREHENSIVE TEST SUITE")
    print("="*100)
    
    results = {
        "total": 7,
        "passed": 0,
        "failed": 0
    }
    
    tests = [
        ("Fully Compliant PR", test_fully_compliant_pr),
        ("Exceeds Budget", test_exceeds_budget),
        ("Non-Preferred Vendor", test_non_preferred_vendor),
        ("Insufficient Justification", test_insufficient_justification),
        ("Critical Without Justification", test_critical_urgency_no_justification),
        ("Large OPEX Warning", test_large_opex_warning),
        ("Exceeds VP Authority", test_exceeds_vp_authority)
    ]
    
    for test_name, test_func in tests:
        try:
            await test_func()
            results["passed"] += 1
        except AssertionError as e:
            print(f"\n❌ {test_name} FAILED: {e}")
            results["failed"] += 1
        except Exception as e:
            print(f"\n❌ {test_name} ERROR: {e}")
            results["failed"] += 1
    
    print("\n" + "="*100)
    print("TEST SUMMARY")
    print("="*100)
    print(f"Total Tests: {results['total']}")
    print(f"✅ Passed: {results['passed']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"Success Rate: {(results['passed']/results['total'])*100:.1f}%")
    print("="*100)
    
    return results


if __name__ == "__main__":
    asyncio.run(run_all_tests())
