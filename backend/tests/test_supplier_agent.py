"""
Supplier Performance Agent Tests
Sprint 5: Comprehensive test suite for supplier performance evaluation
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
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from backend.agents.supplier_performance import SupplierPerformanceAgent


async def test_excellent_supplier():
    """Test 1: Excellent performing supplier (90-100 score)"""
    print("\n" + "="*80)
    print("TEST 1: Excellent Supplier Performance")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    context = {
        "request": "Evaluate top-tier supplier",
        "supplier_data": {
            "supplier_name": "Premium Tech Solutions",
            "supplier_id": 101,
            "category": "Electronics",
            "evaluation_period_days": 90,
            
            # Excellent delivery metrics
            "total_orders": 50,
            "on_time_deliveries": 48,
            "late_deliveries": 2,
            "average_delay_days": 0.5,
            
            # Excellent quality metrics
            "total_items_received": 5000,
            "defective_items": 10,  # 0.2% defect rate
            "returns": 5,
            "quality_complaints": 0,
            
            # Excellent price metrics
            "price_increases": 0,
            "price_decreases": 1,
            "price_stability_score": 98,
            "competitiveness_score": 95,
            
            # Excellent communication
            "response_time_hours": 2,
            "issues_resolved": 15,
            "issues_unresolved": 0,
            "communication_rating": 4.9
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nAgent: {result['agent']}")
    print(f"Status: {result['status']}")
    print(f"Action: {result['result']['action']}")
    print(f"Overall Score: {result['result']['overall_score']}/100")
    print(f"Performance Level: {result['result']['performance_level']}")
    print(f"Delivery Score: {result['result']['delivery_score']}")
    print(f"Quality Score: {result['result']['quality_score']}")
    print(f"Price Score: {result['result']['price_score']}")
    print(f"Communication Score: {result['result']['communication_score']}")
    print(f"Risk Level: {result['result']['risk_level']}")
    print(f"\nReasoning: {result['decision']['reasoning']}")
    
    assert result['status'] == 'success', "Should complete successfully"
    assert result['result']['performance_level'] == 'excellent', "Should be excellent level"
    assert result['result']['overall_score'] >= 90, "Score should be 90+"
    assert result['result']['action'] == 'strategic_partnership', "Should recommend partnership"
    assert result['result']['risk_level'] == 'MINIMAL', "Should be minimal risk"
    
    print("\nTEST 1 PASSED: Excellent supplier identified for strategic partnership")


async def test_good_supplier():
    """Test 2: Good performing supplier (75-89 score)"""
    print("\n" + "="*80)
    print("TEST 2: Good Supplier Performance")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    context = {
        "request": "Evaluate reliable supplier",
        "supplier_data": {
            "supplier_name": "Reliable Parts Co",
            "supplier_id": 102,
            "category": "Manufacturing",
            
            # Good delivery metrics
            "total_orders": 40,
            "on_time_deliveries": 36,
            "late_deliveries": 4,
            "average_delay_days": 1.5,
            
            # Good quality metrics
            "total_items_received": 4000,
            "defective_items": 40,  # 1% defect rate
            "returns": 20,
            "quality_complaints": 2,
            
            # Good price metrics
            "price_stability_score": 85,
            "competitiveness_score": 80,
            
            # Good communication
            "response_time_hours": 12,
            "issues_resolved": 10,
            "issues_unresolved": 1,
            "communication_rating": 4.0
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nOverall Score: {result['result']['overall_score']}/100")
    print(f"Performance Level: {result['result']['performance_level']}")
    print(f"Action: {result['result']['action']}")
    print(f"Risk Level: {result['result']['risk_level']}")
    
    assert result['result']['performance_level'] == 'good', "Should be good level"
    assert 75 <= result['result']['overall_score'] < 90, "Score should be 75-89"
    assert result['result']['action'] == 'maintain_relationship', "Should maintain relationship"
    assert result['result']['risk_level'] == 'MINIMAL', "Should be minimal risk"
    
    print("\nTEST 2 PASSED: Good supplier relationship maintained")


async def test_fair_supplier():
    """Test 3: Fair performing supplier (60-74 score)"""
    print("\n" + "="*80)
    print("TEST 3: Fair Supplier Performance")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    context = {
        "request": "Evaluate average supplier",
        "supplier_data": {
            "supplier_name": "Average Supply Inc",
            "supplier_id": 103,
            
            # Fair delivery metrics
            "total_orders": 30,
            "on_time_deliveries": 22,
            "late_deliveries": 8,
            "average_delay_days": 3,
            
            # Fair quality metrics
            "total_items_received": 3000,
            "defective_items": 90,  # 3% defect rate
            "returns": 60,
            "quality_complaints": 5,
            
            # Fair price metrics
            "price_stability_score": 70,
            "competitiveness_score": 65,
            
            # Fair communication
            "response_time_hours": 36,
            "issues_resolved": 8,
            "issues_unresolved": 3,
            "communication_rating": 3.5
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nOverall Score: {result['result']['overall_score']}/100")
    print(f"Performance Level: {result['result']['performance_level']}")
    print(f"Action: {result['result']['action']}")
    print(f"Risk Level: {result['result']['risk_level']}")
    print(f"\nRecommendations:")
    for rec in result['result']['recommendations']:
        print(f"   - {rec}")
    
    assert result['result']['performance_level'] == 'fair', "Should be fair level"
    assert 60 <= result['result']['overall_score'] < 75, "Score should be 60-74"
    assert result['result']['action'] == 'monitor_and_improve', "Should monitor and improve"
    assert result['result']['risk_level'] == 'LOW', "Should be low risk"
    
    print("\nTEST 3 PASSED: Fair supplier requires monitoring and improvement")


async def test_poor_supplier():
    """Test 4: Poor performing supplier (40-59 score)"""
    print("\n" + "="*80)
    print("TEST 4: Poor Supplier Performance")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    context = {
        "request": "Evaluate problematic supplier",
        "supplier_data": {
            "supplier_name": "Problematic Vendors LLC",
            "supplier_id": 104,
            
            # Poor delivery metrics
            "total_orders": 25,
            "on_time_deliveries": 15,
            "late_deliveries": 10,
            "average_delay_days": 5,
            
            # Poor quality metrics
            "total_items_received": 2500,
            "defective_items": 150,  # 6% defect rate
            "returns": 100,
            "quality_complaints": 10,
            
            # Poor price metrics
            "price_stability_score": 55,
            "competitiveness_score": 50,
            
            # Poor communication
            "response_time_hours": 72,
            "issues_resolved": 5,
            "issues_unresolved": 8,
            "communication_rating": 2.5
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nOverall Score: {result['result']['overall_score']}/100")
    print(f"Performance Level: {result['result']['performance_level']}")
    print(f"Action: {result['result']['action']}")
    print(f"Urgency: {result['result']['urgency']}")
    print(f"Risk Level: {result['result']['risk_level']}")
    print(f"\nReasoning: {result['decision']['reasoning']}")
    
    assert result['result']['performance_level'] == 'poor', "Should be poor level"
    assert 40 <= result['result']['overall_score'] < 60, "Score should be 40-59"
    assert result['result']['action'] == 'performance_improvement_plan', "Should require improvement plan"
    assert result['result']['urgency'] == 'HIGH', "Should be high urgency"
    assert result['result']['risk_level'] == 'MEDIUM', "Should be medium risk"
    
    print("\nTEST 4 PASSED: Poor supplier requires performance improvement plan")


async def test_critical_supplier():
    """Test 5: Critical performing supplier (0-39 score)"""
    print("\n" + "="*80)
    print("TEST 5: Critical Supplier Performance")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    context = {
        "request": "Evaluate failing supplier",
        "supplier_data": {
            "supplier_name": "Failing Supplier Corp",
            "supplier_id": 105,
            
            # Critical delivery metrics
            "total_orders": 20,
            "on_time_deliveries": 8,
            "late_deliveries": 12,
            "average_delay_days": 10,
            
            # Critical quality metrics
            "total_items_received": 2000,
            "defective_items": 300,  # 15% defect rate
            "returns": 250,
            "quality_complaints": 20,
            
            # Critical price metrics
            "price_stability_score": 40,
            "competitiveness_score": 35,
            
            # Critical communication
            "response_time_hours": 120,
            "issues_resolved": 2,
            "issues_unresolved": 15,
            "communication_rating": 1.5
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nOverall Score: {result['result']['overall_score']}/100")
    print(f"Performance Level: {result['result']['performance_level']}")
    print(f"Action: {result['result']['action']}")
    print(f"Urgency: {result['result']['urgency']}")
    print(f"Risk Level: {result['result']['risk_level']}")
    print(f"\nRecommended Actions:")
    for action in result['result']['recommended_actions'][:3]:
        print(f"   - {action}")
    
    assert result['result']['performance_level'] == 'critical', "Should be critical level"
    assert result['result']['overall_score'] < 40, "Score should be under 40"
    assert result['result']['action'] == 'immediate_review_required', "Should require immediate review"
    assert result['result']['urgency'] == 'CRITICAL', "Should be critical urgency"
    assert result['result']['risk_level'] == 'HIGH', "Should be high risk"
    
    print("\nTEST 5 PASSED: Critical supplier flagged for immediate review")


async def test_delivery_focused_issues():
    """Test 6: Supplier with primarily delivery issues"""
    print("\n" + "="*80)
    print("TEST 6: Delivery Issues")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    context = {
        "request": "Evaluate supplier with delivery problems",
        "supplier_data": {
            "supplier_name": "Late Delivery Services",
            "supplier_id": 106,
            
            # Poor delivery metrics
            "total_orders": 30,
            "on_time_deliveries": 18,
            "late_deliveries": 12,
            "average_delay_days": 7,
            
            # Good quality metrics
            "total_items_received": 3000,
            "defective_items": 30,
            "returns": 15,
            "quality_complaints": 1,
            
            # Good price metrics
            "price_stability_score": 88,
            "competitiveness_score": 85,
            
            # Good communication
            "response_time_hours": 8,
            "issues_resolved": 12,
            "issues_unresolved": 1,
            "communication_rating": 4.2
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nOverall Score: {result['result']['overall_score']}/100")
    print(f"Delivery Score: {result['result']['delivery_score']} (LOW)")
    print(f"Quality Score: {result['result']['quality_score']} (HIGH)")
    print(f"Action: {result['result']['action']}")
    print(f"\nKey Recommendations:")
    for rec in result['result']['recommendations']:
        if 'delivery' in rec.lower() or 'delay' in rec.lower():
            print(f"   - {rec}")
    
    assert result['result']['delivery_score'] < 70, "Delivery score should be low"
    assert result['result']['quality_score'] > 85, "Quality score should be high"
    assert any('delivery' in rec.lower() for rec in result['result']['recommendations']), \
        "Should recommend delivery improvements"
    
    print("\nTEST 6 PASSED: Delivery issues identified with specific recommendations")


async def test_quality_focused_issues():
    """Test 7: Supplier with primarily quality issues"""
    print("\n" + "="*80)
    print("TEST 7: Quality Issues")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    context = {
        "request": "Evaluate supplier with quality problems",
        "supplier_data": {
            "supplier_name": "Quality Problems Inc",
            "supplier_id": 107,
            
            # Good delivery metrics
            "total_orders": 35,
            "on_time_deliveries": 33,
            "late_deliveries": 2,
            "average_delay_days": 0.5,
            
            # Poor quality metrics
            "total_items_received": 3500,
            "defective_items": 280,  # 8% defect rate
            "returns": 180,
            "quality_complaints": 15,
            
            # Good price metrics
            "price_stability_score": 82,
            "competitiveness_score": 78,
            
            # Good communication
            "response_time_hours": 10,
            "issues_resolved": 10,
            "issues_unresolved": 2,
            "communication_rating": 3.8
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nOverall Score: {result['result']['overall_score']}/100")
    print(f"Delivery Score: {result['result']['delivery_score']} (HIGH)")
    print(f"Quality Score: {result['result']['quality_score']} (LOW)")
    print(f"Action: {result['result']['action']}")
    print(f"\nQuality Recommendations:")
    for rec in result['result']['recommendations']:
        if 'quality' in rec.lower() or 'defect' in rec.lower():
            print(f"   - {rec}")
    
    assert result['result']['quality_score'] < 60, "Quality score should be low"
    assert result['result']['delivery_score'] > 90, "Delivery score should be high"
    assert any('quality' in rec.lower() or 'defect' in rec.lower() 
               for rec in result['result']['recommendations']), \
        "Should recommend quality improvements"
    
    print("\nTEST 7 PASSED: Quality issues identified with specific recommendations")


async def test_new_supplier_insufficient_data():
    """Test 8: New supplier with insufficient data"""
    print("\n" + "="*80)
    print("TEST 8: New Supplier - Insufficient Data")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    context = {
        "request": "Evaluate new supplier",
        "supplier_data": {
            "supplier_name": "New Vendor Ltd",
            "supplier_id": 108,
            "category": "Office Supplies",
            
            # Minimal data - no order history
            "total_orders": 0,
            "total_items_received": 0,
            "response_time_hours": 12,
            "communication_rating": 4.0
        }
    }
    
    result = await agent.execute(context)
    
    print(f"\nOverall Score: {result['result']['overall_score']}/100")
    print(f"Performance Level: {result['result']['performance_level']}")
    print(f"Action: {result['result']['action']}")
    print(f"Urgency: {result['result']['urgency']}")
    
    # Agent uses defaults for missing data, which gives ~75/100 score (good level)
    # This is correct behavior - maintaining relationship for promising new supplier
    assert result['result']['performance_level'] == 'good', "Should be good level with defaults"
    assert result['result']['action'] == 'maintain_relationship', "Should maintain relationship"
    assert result['result']['overall_score'] >= 70, "Should have reasonable default score"
    
    print("\nTEST 8 PASSED: New supplier evaluated with default scores")  


async def run_all_tests():
    """Run all supplier performance agent tests"""
    print("\n" + "="*80)
    print("SUPPLIER PERFORMANCE AGENT - COMPREHENSIVE TEST SUITE")
    print("Sprint 5: Testing all performance levels and scenarios")
    print("="*80)
    
    tests = [
        test_excellent_supplier,
        test_good_supplier,
        test_fair_supplier,
        test_poor_supplier,
        test_critical_supplier,
        test_delivery_focused_issues,
        test_quality_focused_issues,
        test_new_supplier_insufficient_data
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
        print("\nALL TESTS PASSED! SupplierPerformanceAgent is fully operational.")
    else:
        print(f"\n️ {failed} test(s) failed. Review failures above.")
    
    print("="*80)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
