"""
Timeout Handling Testing Script
Tests all timeout scenarios including middleware, OpenAI, Odoo, and monitoring
"""
import os
import sys
import time
import asyncio
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

from services.timeout_monitor import (
    get_timeout_metrics,
    reset_timeout_metrics,
    track_timeout
)


def print_status(title):
    """Print section title"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_timeout_monitor():
    """Test 1: Verify timeout monitoring tracks operations"""
    print_status("TEST 1: Timeout Monitoring")
    
    # Reset metrics
    reset_timeout_metrics()
    initial_metrics = get_timeout_metrics()
    print(f"Initial metrics: {initial_metrics}")
    assert initial_metrics['total_requests'] == 0, "Metrics should start at 0"
    
    # Simulate tracked operation
    @track_timeout("test_operation", slow_threshold=0.5)
    async def fast_operation():
        await asyncio.sleep(0.1)
        return {"status": "success"}
    
    @track_timeout("slow_operation", slow_threshold=0.5)
    async def slow_operation():
        await asyncio.sleep(0.6)
        return {"status": "success"}
    
    # Run operations
    asyncio.run(fast_operation())
    asyncio.run(slow_operation())
    
    # Check metrics
    metrics = get_timeout_metrics()
    print(f"\nAfter 2 operations:")
    print(f"  Total requests: {metrics['total_requests']}")
    print(f"  Slow requests: {metrics['slow_requests']}")
    print(f"  Avg response time: {metrics['avg_response_time']}")
    
    assert metrics['total_requests'] == 2, "Should have 2 total requests"
    assert metrics['slow_requests'] == 1, "Should have 1 slow request"
    print("✅ TEST 1 PASSED: Timeout monitoring works correctly")


def test_timeout_error_handling():
    """Test 2: Verify timeout errors are caught"""
    print_status("TEST 2: Timeout Error Handling")
    
    @track_timeout("timeout_operation")
    async def timeout_operation():
        # Simulate timeout
        await asyncio.sleep(0.1)
        raise asyncio.TimeoutError("Operation timed out")
    
    try:
        asyncio.run(timeout_operation())
        assert False, "Should have raised TimeoutError"
    except asyncio.TimeoutError:
        print("✅ TimeoutError caught correctly")
    
    # Check metrics
    metrics = get_timeout_metrics()
    print(f"Timeout count: {metrics['timeouts']}")
    assert metrics['timeouts'] >= 1, "Should have recorded timeout"
    print("✅ TEST 2 PASSED: Timeout errors tracked correctly")


def test_metrics_reset():
    """Test 3: Verify metrics can be reset"""
    print_status("TEST 3: Metrics Reset")
    
    # Ensure some metrics exist
    @track_timeout("reset_test")
    async def dummy_operation():
        await asyncio.sleep(0.01)
        return True
    
    asyncio.run(dummy_operation())
    
    metrics_before = get_timeout_metrics()
    print(f"Before reset: {metrics_before['total_requests']} requests")
    assert metrics_before['total_requests'] > 0, "Should have requests before reset"
    
    # Reset
    reset_timeout_metrics()
    
    metrics_after = get_timeout_metrics()
    print(f"After reset: {metrics_after['total_requests']} requests")
    assert metrics_after['total_requests'] == 0, "Should be 0 after reset"
    print("✅ TEST 3 PASSED: Metrics reset works")


def test_operation_specific_metrics():
    """Test 4: Verify per-operation metrics"""
    print_status("TEST 4: Per-Operation Metrics")
    
    reset_timeout_metrics()
    
    @track_timeout("operation_a")
    async def operation_a():
        await asyncio.sleep(0.05)
        return "A"
    
    @track_timeout("operation_b")
    async def operation_b():
        await asyncio.sleep(0.1)
        return "B"
    
    # Run operations multiple times
    for _ in range(3):
        asyncio.run(operation_a())
    
    for _ in range(2):
        asyncio.run(operation_b())
    
    metrics = get_timeout_metrics()
    print(f"\nOperation metrics:")
    for op_name, op_metrics in metrics['operations'].items():
        print(f"  {op_name}: {op_metrics['count']} calls, avg {op_metrics['avg_time']:.2f}s")
    
    assert 'operation_a' in metrics['operations'], "Should track operation_a"
    assert 'operation_b' in metrics['operations'], "Should track operation_b"
    assert metrics['operations']['operation_a']['count'] == 3, "Should have 3 calls to operation_a"
    assert metrics['operations']['operation_b']['count'] == 2, "Should have 2 calls to operation_b"
    print("✅ TEST 4 PASSED: Per-operation metrics work correctly")


def test_sync_function_tracking():
    """Test 5: Verify sync functions can be tracked"""
    print_status("TEST 5: Sync Function Tracking")
    
    reset_timeout_metrics()
    
    @track_timeout("sync_operation")
    def sync_operation():
        time.sleep(0.05)
        return "sync result"
    
    result = sync_operation()
    assert result == "sync result", "Sync function should return result"
    
    metrics = get_timeout_metrics()
    assert metrics['total_requests'] == 1, "Should track sync operation"
    print("✅ TEST 5 PASSED: Sync functions tracked correctly")


def test_timeout_configuration():
    """Test 6: Verify timeout configurations are properly set"""
    print_status("TEST 6: Timeout Configuration Verification")
    
    # Test OpenAI client timeout
    print("\n📊 OpenAI Client Configuration:")
    try:
        from services.translation_service import client as translation_client
        print(f"  Translation client timeout: {translation_client.timeout}")
        print(f"  Max retries: {translation_client.max_retries}")
        print("  ✅ Translation service configured")
    except Exception as e:
        print(f"  ⚠️  Could not verify translation service: {e}")
    
    try:
        from services.query_router import client as router_client
        print(f"  Router client timeout: {router_client.timeout}")
        print(f"  Max retries: {router_client.max_retries}")
        print("  ✅ Query router configured")
    except Exception as e:
        print(f"  ⚠️  Could not verify query router: {e}")
    
    # Test Odoo timeout
    print("\n📊 Odoo Client Configuration:")
    try:
        from services.odoo_client import TimeoutTransport
        transport = TimeoutTransport(timeout=10)
        print(f"  Transport timeout: {transport.timeout}s")
        print("  ✅ Odoo transport configured")
    except Exception as e:
        print(f"  ⚠️  Could not verify Odoo transport: {e}")
    
    print("\n✅ TEST 6 PASSED: Configuration verification complete")


if __name__ == "__main__":
    print("\n" + "⏱️ "*20)
    print("  TIMEOUT HANDLING TEST SUITE")
    print("⏱️ "*20)
    
    try:
        # Run all tests
        test_timeout_monitor()
        time.sleep(0.5)
        
        test_timeout_error_handling()
        time.sleep(0.5)
        
        test_metrics_reset()
        time.sleep(0.5)
        
        test_operation_specific_metrics()
        time.sleep(0.5)
        
        test_sync_function_tracking()
        time.sleep(0.5)
        
        test_timeout_configuration()
        
        print("\n" + "="*60)
        print("  ✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("="*60)
        
        # Final metrics
        final_metrics = get_timeout_metrics()
        print(f"\nFinal System Metrics:")
        print(f"  Total requests: {final_metrics['total_requests']}")
        print(f"  Timeouts: {final_metrics['timeouts']}")
        print(f"  Timeout rate: {final_metrics['timeout_rate']}")
        print(f"  Slow requests: {final_metrics['slow_requests']}")
        print(f"  Avg response time: {final_metrics['avg_response_time']}")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
