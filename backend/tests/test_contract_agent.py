"""
Contract Monitoring Agent Tests
Sprint 4: Comprehensive test suite for contract expiration and renewal monitoring
"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from backend.agents.contract_monitoring import ContractMonitoringAgent


async def test_expired_contract():
    """Test 1: Expired contract (emergency scenario)"""
    print("\n" + "="*80)
    print("TEST 1: Expired Contract")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    # Contract expired 5 days ago
    end_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    
    context = {
        "request": "Monitor expired contract",
        "contract_data": {
            "contract_id": "C-2025-001",
            "contract_number": "CNT-IT-2025-001",
            "vendor_name": "TechSupplier Inc",
            "vendor_id": 15,
            "start_date": "2025-01-01",
            "end_date": end_date,
            "contract_value": 100000,
            "spent_amount": 85000,
            "department": "IT",
            "contract_type": "Software Licensing",
            "auto_renew": False,
            "description": "Enterprise software licenses"
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAgent: {result['agent']}")
    print(f"Status: {result['status']}")
    print(f"Action: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Alert Level: {result['result']['alert_level']}")
    print(f"Days Until Expiration: {result['result']['days_until_expiration']}")
    print(f"Spend: {result['result']['spend_percentage']}%")
    print(f"\nReasoning: {result['decision']['reasoning']}")
    print(f"\nRecommended Actions:")
    for action in result['result']['recommended_actions']:
        print(f"   - {action}")
    
    assert result['status'] == 'success', "Should complete successfully"
    assert result['result']['action'] == 'emergency_procurement', "Should trigger emergency procurement"
    assert result['result']['priority'] == 'CRITICAL', "Should be critical priority"
    assert result['result']['alert_level'] == 'CRITICAL', "Should be critical alert"
    
    print("\nTEST 1 PASSED: Expired contract properly escalated to emergency")


async def test_critical_7_days():
    """Test 2: Critical expiration (7 days remaining)"""
    print("\n" + "="*80)
    print("TEST 2: Critical Expiration (7 Days)")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    # Contract expires in 5 days (critical threshold)
    end_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    
    context = {
        "request": "Monitor contract expiring soon",
        "contract_data": {
            "contract_id": "C-2026-002",
            "contract_number": "CNT-FIN-2026-002",
            "vendor_name": "Financial Services Corp",
            "start_date": "2026-01-01",
            "end_date": end_date,
            "contract_value": 250000,
            "spent_amount": 180000,
            "department": "Finance",
            "contract_type": "Consulting Services",
            "auto_renew": False
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAgent: {result['agent']}")
    print(f"Action: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Alert Level: {result['result']['alert_level']}")
    print(f"Days Until Expiration: {result['result']['days_until_expiration']}")
    print(f"Expiration Status: {result['result']['expiration_status']}")
    print(f"\nReasoning: {result['decision']['reasoning']}")
    
    assert result['result']['action'] == 'urgent_renewal', "Should trigger urgent renewal"
    assert result['result']['priority'] == 'HIGH', "Should be high priority"
    assert result['result']['expiration_status'] == 'critical', "Should be critical status"
    
    print("\nTEST 2 PASSED: Critical expiration triggers urgent renewal")


async def test_urgent_30_days():
    """Test 3: Urgent expiration (30 days remaining)"""
    print("\n" + "="*80)
    print("TEST 3: Urgent Expiration (30 Days)")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    # Contract expires in 25 days (urgent threshold)
    end_date = (datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d")
    
    context = {
        "request": "Monitor contract nearing expiration",
        "contract_data": {
            "contract_number": "CNT-OPS-2026-003",
            "vendor_name": "Operations Partner LLC",
            "end_date": end_date,
            "contract_value": 150000,
            "spent_amount": 120000,
            "department": "Operations",
            "contract_type": "Maintenance Agreement"
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAction: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Days Until Expiration: {result['result']['days_until_expiration']}")
    print(f"Reasoning: {result['decision']['reasoning']}")
    
    assert result['result']['action'] == 'expedite_renewal', "Should expedite renewal"
    assert result['result']['priority'] == 'HIGH', "Should be high priority"
    assert result['result']['expiration_status'] == 'urgent', "Should be urgent status"
    
    print("\nTEST 3 PASSED: Urgent expiration triggers expedited renewal")


async def test_action_required_60_days_auto_renew():
    """Test 4: Action required (60 days) with auto-renewal"""
    print("\n" + "="*80)
    print("TEST 4: Action Required (60 Days) - Auto Renewal")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    # Contract expires in 55 days with auto-renewal
    end_date = (datetime.now() + timedelta(days=55)).strftime("%Y-%m-%d")
    
    context = {
        "request": "Verify auto-renewal contract",
        "contract_data": {
            "contract_number": "CNT-IT-2026-004",
            "vendor_name": "Cloud Services Provider",
            "end_date": end_date,
            "contract_value": 300000,
            "spent_amount": 220000,
            "department": "IT",
            "auto_renew": True,  # Auto-renewal enabled
            "contract_type": "Cloud Infrastructure"
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAction: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Days Until Expiration: {result['result']['days_until_expiration']}")
    print(f"Auto-Renew: Yes")
    print(f"Reasoning: {result['decision']['reasoning']}")
    
    assert result['result']['action'] == 'verify_auto_renewal', "Should verify auto-renewal"
    assert 'auto-renewal' in result['decision']['reasoning'].lower(), "Should mention auto-renewal"
    
    print("\nTEST 4 PASSED: Auto-renewal contract triggers verification")


async def test_action_required_60_days_no_auto_renew():
    """Test 5: Action required (60 days) without auto-renewal"""
    print("\n" + "="*80)
    print("TEST 5: Action Required (60 Days) - No Auto Renewal")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    # Contract expires in 50 days, no auto-renewal
    end_date = (datetime.now() + timedelta(days=50)).strftime("%Y-%m-%d")
    
    context = {
        "request": "Monitor contract needing renewal",
        "contract_data": {
            "contract_number": "CNT-PROC-2026-005",
            "vendor_name": "Procurement Solutions Inc",
            "end_date": end_date,
            "contract_value": 180000,
            "spent_amount": 95000,
            "department": "Procurement",
            "auto_renew": False,
            "contract_type": "Professional Services"
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAction: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Days Until Expiration: {result['result']['days_until_expiration']}")
    print(f"Reasoning: {result['decision']['reasoning']}")
    
    assert result['result']['action'] == 'initiate_renewal', "Should initiate renewal process"
    assert result['result']['priority'] == 'MEDIUM', "Should be medium priority"
    
    print("\nTEST 5 PASSED: 60-day warning initiates renewal process")


async def test_early_warning_90_days():
    """Test 6: Early warning (90 days remaining)"""
    print("\n" + "="*80)
    print("TEST 6: Early Warning (90 Days)")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    # Contract expires in 85 days (early warning)
    end_date = (datetime.now() + timedelta(days=85)).strftime("%Y-%m-%d")
    
    context = {
        "request": "Monitor contract for early planning",
        "contract_data": {
            "contract_number": "CNT-EXEC-2026-006",
            "vendor_name": "Executive Consulting Group",
            "end_date": end_date,
            "contract_value": 500000,
            "spent_amount": 200000,
            "department": "Executive",
            "contract_type": "Strategic Consulting"
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAction: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Days Until Expiration: {result['result']['days_until_expiration']}")
    print(f"Alert Level: {result['result']['alert_level']}")
    print(f"Reasoning: {result['decision']['reasoning']}")
    
    assert result['result']['action'] == 'plan_renewal', "Should plan renewal"
    assert result['result']['priority'] == 'LOW', "Should be low priority"
    assert result['result']['expiration_status'] == 'early_warning', "Should be early warning"
    
    print("\nTEST 6 PASSED: Early warning triggers renewal planning")


async def test_active_contract():
    """Test 7: Active contract (150+ days remaining)"""
    print("\n" + "="*80)
    print("TEST 7: Active Contract (150 Days)")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    # Contract expires in 180 days (active)
    end_date = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")
    
    context = {
        "request": "Monitor active contract",
        "contract_data": {
            "contract_number": "CNT-HR-2026-007",
            "vendor_name": "HR Solutions Provider",
            "end_date": end_date,
            "contract_value": 120000,
            "spent_amount": 30000,
            "department": "HR",
            "contract_type": "HR Software License"
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAction: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Days Until Expiration: {result['result']['days_until_expiration']}")
    print(f"Spend: {result['result']['spend_percentage']}%")
    print(f"Reasoning: {result['decision']['reasoning']}")
    
    assert result['result']['action'] == 'monitor_ongoing', "Should continue monitoring"
    assert result['result']['priority'] == 'LOW', "Should be low priority"
    assert result['result']['expiration_status'] == 'active', "Should be active"
    
    print("\nTEST 7 PASSED: Active contract continues routine monitoring")


async def test_high_spend_warning():
    """Test 8: Contract approaching spend limit (96% spent)"""
    print("\n" + "="*80)
    print("TEST 8: High Spend Warning (96% of Contract Value)")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    # Contract with 6 months remaining but 96% spent
    end_date = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")
    
    context = {
        "request": "Monitor contract with high spend",
        "contract_data": {
            "contract_number": "CNT-IT-2026-008",
            "vendor_name": "IT Infrastructure Corp",
            "end_date": end_date,
            "contract_value": 400000,
            "spent_amount": 384000,  # 96% spent
            "department": "IT",
            "contract_type": "Infrastructure Services"
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAction: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Days Until Expiration: {result['result']['days_until_expiration']}")
    print(f"Spend: {result['result']['spend_percentage']}%")
    print(f"Alert Level: {result['result']['alert_level']}")
    print(f"Reasoning: {result['decision']['reasoning']}")
    
    assert result['result']['action'] == 'review_overspend_risk', "Should review overspend risk"
    assert result['result']['spend_percentage'] == 96.0, "Should show 96% spend"
    assert '96.0%' in result['decision']['reasoning'], "Should mention high spend percentage"
    assert result['result']['alert_level'] == 'HIGH', "Should be high alert due to spend"
    
    print("\nTEST 8 PASSED: High spend triggers overspend risk review")


async def test_missing_end_date():
    """Test 9: Contract with missing end date"""
    print("\n" + "="*80)
    print("TEST 9: Missing End Date")
    print("="*80)
    
    agent = ContractMonitoringAgent()
    
    context = {
        "request": "Monitor contract with incomplete data",
        "contract_data": {
            "contract_number": "CNT-MISC-2026-009",
            "vendor_name": "Miscellaneous Vendor",
            "end_date": None,  # Missing end date
            "contract_value": 75000,
            "spent_amount": 25000,
            "department": "Procurement"
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAction: {result['result']['action']}")
    print(f"Priority: {result['result']['priority']}")
    print(f"Expiration Status: {result['result']['expiration_status']}")
    print(f"Reasoning: {result['decision']['reasoning']}")
    
    assert result['result']['action'] == 'update_contract_data', "Should update contract data"
    assert result['result']['expiration_status'] == 'no_end_date', "Should flag missing date"
    
    print("\nTEST 9 PASSED: Missing data triggers update action")


async def run_all_tests():
    """Run all contract monitoring agent tests"""
    print("\n" + "="*80)
    print("CONTRACT MONITORING AGENT - COMPREHENSIVE TEST SUITE")
    print("Sprint 4: Testing all expiration scenarios and contract monitoring")
    print("="*80)
    
    tests = [
        test_expired_contract,
        test_critical_7_days,
        test_urgent_30_days,
        test_action_required_60_days_auto_renew,
        test_action_required_60_days_no_auto_renew,
        test_early_warning_90_days,
        test_active_contract,
        test_high_spend_warning,
        test_missing_end_date
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            await test_func()
            passed += 1
        except AssertionError as e:
            print(f"\nTEST FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\nTEST ERROR: {e}")
            failed += 1
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Total Tests: {len(tests)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {(passed/len(tests)*100):.1f}%")
    
    if failed == 0:
        print("\nALL TESTS PASSED! ContractMonitoringAgent is fully operational.")
    else:
        print(f"\n️ {failed} test(s) failed. Review failures above.")
    
    print("="*80)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
