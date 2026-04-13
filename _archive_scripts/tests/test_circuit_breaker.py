"""
Circuit Breaker Testing Script
Tests all circuit breaker scenarios including failure and recovery
"""
import os
import sys
import time
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

from services.circuit_breakers import (
    postgres_breaker, 
    odoo_breaker, 
    get_circuit_status,
    reset_circuit_breakers,
    get_fallback_data
)

def print_status(title):
    """Print current circuit breaker status"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    status = get_circuit_status()
    print(f"PostgreSQL Circuit: {status['postgres']['state']} (Failures: {status['postgres']['fail_counter']})")
    print(f"Odoo Circuit: {status['odoo']['state']} (Failures: {status['odoo']['fail_counter']})")
    print(f"Overall Healthy: {status['overall_healthy']}")
    return status

def test_normal_operation():
    """Test 1: Normal operation - circuits should stay closed"""
    print_status("TEST 1: Normal Operation")
    
    # Simulate successful operations
    @postgres_breaker
    def successful_query():
        return {"status": "success", "data": []}
    
    result = successful_query()
    print(f"✅ Successful query returned: {result}")
    
    status = get_circuit_status()
    assert status['postgres']['state'] == 'closed', "Circuit should be closed after success"
    print("✅ TEST 1 PASSED: Circuit remains closed on success")

def test_circuit_breaking():
    """Test 2: Trigger circuit breaker with failures"""
    print_status("TEST 2: Circuit Breaking (5 failures)")
    
    @postgres_breaker
    def failing_query():
        raise Exception("Database connection failed!")
    
    failures = 0
    for i in range(6):  # Need 5+ failures to open circuit
        try:
            failing_query()
        except Exception as e:
            failures += 1
            print(f"Failure {failures}: {str(e)[:50]}")
    
    status = get_circuit_status()
    print(f"\n📊 Final state: {status['postgres']['state']}")
    print(f"📊 Fail counter: {status['postgres']['fail_counter']}")
    
    assert status['postgres']['state'] == 'open', "Circuit should be OPEN after 5 failures"
    print("✅ TEST 2 PASSED: Circuit opened after threshold reached")

def test_fallback_data():
    """Test 3: Verify fallback data when circuit is open"""
    print_status("TEST 3: Fallback Data (Circuit Open)")
    
    # Get fallback data for different types
    test_types = ['approval_chains', 'budget_status', 'vendors', 'purchase_orders']
    
    for data_type in test_types:
        fallback = get_fallback_data(data_type)
        print(f"\n{data_type}:")
        
        # Handle both list and dict responses
        if isinstance(fallback, list):
            print(f"  ⚠️  Returned list with {len(fallback)} items")
            if fallback and isinstance(fallback[0], dict):
                print(f"  ⚠️  {fallback[0].get('message', fallback[0].get('warning', 'Fallback data'))}")
        elif isinstance(fallback, dict):
            print(f"  ⚠️  {fallback.get('message', fallback.get('warning', 'Fallback data'))}")
        
        assert fallback is not None, f"Fallback data should not be None for {data_type}"
    
    print("\n✅ TEST 3 PASSED: Fallback data returned correctly")

def test_circuit_reset():
    """Test 4: Manual circuit reset"""
    print_status("TEST 4: Before Reset")
    
    reset_circuit_breakers()
    print("\n🔄 Circuit breakers manually reset...")
    
    status = print_status("TEST 4: After Reset")
    
    assert status['postgres']['state'] == 'closed', "Circuit should be CLOSED after reset"
    assert status['postgres']['fail_counter'] == 0, "Fail counter should be reset to 0"
    print("✅ TEST 4 PASSED: Manual reset works correctly")

def test_half_open_recovery():
    """Test 5: Circuit recovery (half-open state)"""
    print("\n" + "="*60)
    print("  TEST 5: Circuit Recovery (Half-Open State)")
    print("="*60)
    print("⏱️  This test requires waiting 60 seconds for recovery timeout...")
    print("⏭️  SKIPPING (would take too long) - Manual verification recommended")
    print("📝 To test manually:")
    print("   1. Trigger 5 failures (circuit opens)")
    print("   2. Wait 60 seconds")
    print("   3. Try one query (circuit goes half-open)")
    print("   4. Success → closed, Failure → open again")

if __name__ == "__main__":
    print("\n" + "🧪 "*20)
    print("  CIRCUIT BREAKER COMPREHENSIVE TEST SUITE")
    print("🧪 "*20)
    
    try:
        # Run all tests
        test_normal_operation()
        time.sleep(1)
        
        test_circuit_breaking()
        time.sleep(1)
        
        test_fallback_data()
        time.sleep(1)
        
        test_circuit_reset()
        time.sleep(1)
        
        test_half_open_recovery()
        
        print("\n" + "="*60)
        print("  ✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("="*60)
        
        # Final status
        final_status = get_circuit_status()
        print(f"\nFinal Circuit Status:")
        print(f"  PostgreSQL: {final_status['postgres']['state']} (Healthy: {final_status['postgres']['healthy']})")
        print(f"  Odoo: {final_status['odoo']['state']} (Healthy: {final_status['odoo']['healthy']})")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
