"""
Supplier Performance Agent Structure Verification
Sprint 5: Verify agent structure without running LLM calls
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

# Add backend to path
backend_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_path))

from backend.agents.supplier_performance import SupplierPerformanceAgent


def verify_class_structure():
    """Verify SupplierPerformanceAgent has required structure"""
    print("\n" + "="*80)
    print("STRUCTURE VERIFICATION: SupplierPerformanceAgent")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    # Check base attributes
    print("\n✓ Checking base attributes...")
    assert hasattr(agent, 'name'), "Missing 'name' attribute"
    assert agent.name == "SupplierPerformanceAgent", f"Wrong name: {agent.name}"
    print(f"  - Agent name: {agent.name}")
    required_methods = [
        'observe', 'decide', '_execute_action', 'learn',
        '_calculate_delivery_score', '_calculate_quality_score',
        '_calculate_price_score', '_calculate_communication_score',
        '_get_performance_level', '_generate_recommendations', '_assess_supplier_risk'
    ]
    
    for method_name in required_methods:
        assert hasattr(agent, method_name), f"Missing method: {method_name}"
        print(f"  - {method_name}: ✓")
    
    # Check performance levels
    print("\n✓ Checking performance level definitions...")
    levels = {
        'excellent': (90, 100),
        'good': (75, 89),
        'fair': (60, 74),
        'poor': (40, 59),
        'critical': (0, 39)
    }
    
    for level, (min_score, max_score) in levels.items():
        print(f"  - {level.upper()}: {min_score}-{max_score} points")
    
    print("\n✅ ALL STRUCTURE CHECKS PASSED")
    print("="*80)


def verify_scoring_logic():
    """Verify scoring calculation logic"""
    print("\n" + "="*80)
    print("SCORING LOGIC VERIFICATION")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    # Test delivery scoring
    print("\n✓ Testing delivery score calculation...")
    delivery_data = {
        'total_orders': 100,
        'on_time_deliveries': 95,
        'late_deliveries': 5,
        'average_delay_days': 1
    }
    delivery_score = agent._calculate_delivery_score(delivery_data)
    assert 0 <= delivery_score <= 100, "Delivery score out of range"
    assert delivery_score >= 90, "Should score high for 95% on-time"
    print(f"  - 95% on-time delivery → Score: {delivery_score}/100")
    
    # Test quality scoring
    print("\n✓ Testing quality score calculation...")
    quality_data = {
        'total_items_received': 1000,
        'defective_items': 10,
        'returns': 5,
        'quality_complaints': 1
    }
    quality_score = agent._calculate_quality_score(quality_data)
    assert 0 <= quality_score <= 100, "Quality score out of range"
    assert quality_score >= 85, "Should score high for 1% defect rate"
    print(f"  - 1% defect rate → Score: {quality_score}/100")
    
    # Test price scoring
    print("\n✓ Testing price score calculation...")
    price_data = {
        'price_stability_score': 85,
        'competitiveness_score': 80
    }
    price_score = agent._calculate_price_score(price_data)
    assert 0 <= price_score <= 100, "Price score out of range"
    print(f"  - Stability: 85, Competitiveness: 80 → Score: {price_score}/100")
    
    # Test communication scoring
    print("\n✓ Testing communication score calculation...")
    comm_data = {
        'response_time_hours': 12,
        'issues_resolved': 10,
        'issues_unresolved': 2,
        'communication_rating': 4.0
    }
    comm_score = agent._calculate_communication_score(comm_data)
    assert 0 <= comm_score <= 100, "Communication score out of range"
    print(f"  - Response: 12hrs, Rating: 4.0 → Score: {comm_score}/100")
    
    print("\n✅ ALL SCORING LOGIC CHECKS PASSED")
    print("="*80)


def verify_performance_levels():
    """Verify performance level determination"""
    print("\n" + "="*80)
    print("PERFORMANCE LEVEL VERIFICATION")
    print("="*80)
    
    agent = SupplierPerformanceAgent()
    
    test_cases = [
        (95, 'excellent'),
        (85, 'good'),
        (70, 'fair'),
        (50, 'poor'),
        (30, 'critical')
    ]
    
    print("\n✓ Testing performance level mapping...")
    for score, expected_level in test_cases:
        level = agent._get_performance_level(score)
        assert level == expected_level, f"Score {score} should be {expected_level}, got {level}"
        print(f"  - Score {score}/100 → {level.upper()} ✓")
    
    print("\n✅ ALL PERFORMANCE LEVEL CHECKS PASSED")
    print("="*80)


def run_all_verifications():
    """Run all structure verifications"""
    print("\n" + "="*80)
    print("SUPPLIER PERFORMANCE AGENT - STRUCTURE VERIFICATION")
    print("Sprint 5: Verifying agent structure without LLM calls")
    print("="*80)
    
    verifications = [
        ("Class Structure", verify_class_structure),
        ("Scoring Logic", verify_scoring_logic),
        ("Performance Levels", verify_performance_levels)
    ]
    
    passed = 0
    failed = 0
    
    for name, verify_func in verifications:
        try:
            verify_func()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ VERIFICATION FAILED ({name}): {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ VERIFICATION ERROR ({name}): {e}")
            failed += 1
    
    print("\n" + "="*80)
    print("VERIFICATION SUMMARY")
    print("="*80)
    print(f"Total Verifications: {len(verifications)}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"Success Rate: {(passed/len(verifications)*100):.1f}%")
    
    if failed == 0:
        print("\n🎉 ALL VERIFICATIONS PASSED!")
        print("SupplierPerformanceAgent structure is correct.")
        print("\nNext step: Run test_supplier_agent.py for full LLM-based tests.")
    else:
        print(f"\n⚠️ {failed} verification(s) failed.")
    
    print("="*80)


if __name__ == "__main__":
    run_all_verifications()
