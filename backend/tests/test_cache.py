"""
Test Suite for Redis Caching Layer (FIX #4)
Tests cache operations, TTL, decorators, and statistics

Run: python backend/tests/test_cache.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import time
import json
from backend.services.cache import (
    get_cache, 
    cached, 
    cache_key, 
    invalidate_cache,
    TTL_1_MINUTE,
    TTL_5_MINUTES
)


def test_cache_initialization():
    """TEST 1: Cache service initialization"""
    print("\n" + "="*60)
    print("  TEST 1: CACHE INITIALIZATION")
    print("="*60)
    
    cache = get_cache()
    
    print(f"✓ Cache instance created")
    print(f"✓ Cache enabled: {cache.enabled}")
    
    if cache.enabled:
        print(f"✓ Cache client: {type(cache.client).__name__}")
    
    assert cache is not None, "Cache service should be initialized"
    print("\n✅ TEST 1 PASSED: Cache initialized successfully\n")
    return True


def test_basic_cache_operations():
    """TEST 2: Basic get/set/delete operations"""
    print("="*60)
    print("  TEST 2: BASIC CACHE OPERATIONS")
    print("="*60)
    
    cache = get_cache()
    
    if not cache.enabled:
        print("⏭️  SKIPPED: Cache not enabled (install fakeredis or redis)")
        return True
    
    # Test SET
    test_key = "test:basic"
    test_value = "test_value_123"
    success = cache.set(test_key, test_value, 60)
    assert success, "Cache set should succeed"
    print(f"✓ SET operation: {test_key} = {test_value}")
    
    # Test GET
    retrieved = cache.get(test_key)
    assert retrieved == test_value, f"Expected '{test_value}', got '{retrieved}'"
    print(f"✓ GET operation: Retrieved '{retrieved}'")
    
    # Test DELETE
    cache.delete(test_key)
    deleted_value = cache.get(test_key)
    assert deleted_value is None, "Value should be None after delete"
    print(f"✓ DELETE operation: Key removed")
    
    print("\n✅ TEST 2 PASSED: Basic operations working\n")
    return True


def test_ttl_expiration():
    """TEST 3: TTL-based cache expiration"""
    print("="*60)
    print("  TEST 3: TTL EXPIRATION")
    print("="*60)
    
    cache = get_cache()
    
    if not cache.enabled:
        print("⏭️  SKIPPED: Cache not enabled")
        return True
    
    # Set with 2-second TTL
    test_key = "test:ttl"
    test_value = "expires_soon"
    cache.set(test_key, test_value, 2)
    print(f"✓ SET with TTL=2s: {test_key}")
    
    # Immediate retrieval should work
    value = cache.get(test_key)
    assert value == test_value, "Value should exist immediately after set"
    print(f"✓ Immediate GET: '{value}' (still cached)")
    
    # Wait for expiration
    print("  Waiting 3 seconds for TTL expiration...")
    time.sleep(3)
    
    # Should be expired
    expired_value = cache.get(test_key)
    assert expired_value is None, "Value should be None after TTL expiration"
    print(f"✓ After 3s: Value expired (None)")
    
    print("\n✅ TEST 3 PASSED: TTL expiration working\n")
    return True


def test_cache_decorator():
    """TEST 4: @cached decorator functionality"""
    print("="*60)
    print("  TEST 4: CACHE DECORATOR")
    print("="*60)
    
    cache = get_cache()
    
    if not cache.enabled:
        print("⏭️  SKIPPED: Cache not enabled")
        return True
    
    # Clear any existing cache
    invalidate_cache("test:*")
    
    # Reset stats
    cache.reset_stats()
    
    # Function with caching decorator
    call_count = 0
    
    @cached(ttl_seconds=60, key_prefix="test:decorated")
    def expensive_function(x, y):
        nonlocal call_count
        call_count += 1
        # Simulate expensive computation
        return {"result": x + y, "call_number": call_count}
    
    # First call - cache miss
    result1 = expensive_function(5, 3)
    print(f"✓ First call: {result1} (cache miss, function executed)")
    assert call_count == 1, "Function should be called once"
    assert result1["result"] == 8, "Result should be correct"
    
    # Second call - cache hit
    result2 = expensive_function(5, 3)
    print(f"✓ Second call: {result2} (cache hit, function NOT executed)")
    assert call_count == 1, "Function should NOT be called again (cached)"
    assert result2["result"] == 8, "Cached result should match"
    
    # Different arguments - cache miss
    result3 = expensive_function(10, 20)
    print(f"✓ Different args: {result3} (cache miss, function executed)")
    assert call_count == 2, "Function should be called with new arguments"
    assert result3["result"] == 30, "Result should be correct for new args"
    
    # Check cache stats
    stats = cache.get_stats()
    print(f"\n✓ Cache statistics:")
    print(f"  - Hits: {stats['hits']}")
    print(f"  - Misses: {stats['misses']}")
    print(f"  - Hit rate: {stats['hit_rate']}%")
    
    assert stats['hits'] >= 1, "Should have at least 1 cache hit"
    assert stats['misses'] >= 2, "Should have at least 2 cache misses"
    
    print("\n✅ TEST 4 PASSED: Decorator caching working\n")
    return True


def test_cache_key_generation():
    """TEST 5: Cache key generation with different arguments"""
    print("="*60)
    print("  TEST 5: CACHE KEY GENERATION")
    print("="*60)
    
    # Test with different argument combinations
    key1 = cache_key("vendors", limit=10, category="Electronics")
    key2 = cache_key("vendors", limit=10, category="Electronics")
    key3 = cache_key("vendors", limit=20, category="Electronics")
    key4 = cache_key("vendors", category="Electronics", limit=10)  # Different order
    
    print(f"✓ Key 1: {key1}")
    print(f"✓ Key 2: {key2}")
    print(f"✓ Key 3: {key3}")
    print(f"✓ Key 4: {key4}")
    
    # Same args should produce same key
    assert key1 == key2, "Same arguments should produce same key"
    print(f"✓ Same args → same key: {key1 == key2}")
    
    # Different args should produce different key
    assert key1 != key3, "Different arguments should produce different key"
    print(f"✓ Different args → different key: {key1 != key3}")
    
    # Order of kwargs shouldn't matter
    assert key1 == key4, "Argument order should NOT affect key"
    print(f"✓ Arg order independent: {key1 == key4}")
    
    print("\n✅ TEST 5 PASSED: Cache key generation working\n")
    return True


def test_cache_statistics():
    """TEST 6: Cache statistics tracking"""
    print("="*60)
    print("  TEST 6: CACHE STATISTICS")
    print("="*60)
    
    cache = get_cache()
    
    if not cache.enabled:
        print("⏭️  SKIPPED: Cache not enabled")
        return True
    
    # Reset stats
    cache.reset_stats()
    print("✓ Statistics reset")
    
    # Generate some cache activity
    cache.set("stat_test_1", "value1", 60)
    cache.set("stat_test_2", "value2", 60)
    
    # Cache hits
    cache.get("stat_test_1")  # HIT
    cache.get("stat_test_1")  # HIT
    cache.get("stat_test_2")  # HIT
    
    # Cache misses
    cache.get("stat_test_nonexistent")  # MISS
    cache.get("stat_test_another_miss")  # MISS
    
    # Get stats
    stats = cache.get_stats()
    
    print(f"\n✓ Cache Statistics:")
    print(f"  - Enabled: {stats['enabled']}")
    print(f"  - Total Hits: {stats['hits']}")
    print(f"  - Total Misses: {stats['misses']}")
    print(f"  - Total Requests: {stats['total_requests']}")
    print(f"  - Hit Rate: {stats['hit_rate']}%")
    
    assert stats['hits'] == 3, f"Expected 3 hits, got {stats['hits']}"
    assert stats['misses'] == 2, f"Expected 2 misses, got {stats['misses']}"
    assert stats['hit_rate'] == 60.0, f"Expected 60% hit rate, got {stats['hit_rate']}%"
    
    print("\n✅ TEST 6 PASSED: Statistics tracking accurate\n")
    return True


def test_pattern_invalidation():
    """TEST 7: Pattern-based cache invalidation"""
    print("="*60)
    print("  TEST 7: PATTERN INVALIDATION")
    print("="*60)
    
    cache = get_cache()
    
    if not cache.enabled:
        print("⏭️  SKIPPED: Cache not enabled")
        return True
    
    # Set multiple keys with pattern
    cache.set("vendors:category1", "data1", 60)
    cache.set("vendors:category2", "data2", 60)
    cache.set("products:search1", "data3", 60)
    cache.set("products:search2", "data4", 60)
    
    print("✓ Set 4 cache entries (2 vendors, 2 products)")
    
    # Verify they exist
    assert cache.get("vendors:category1") is not None
    assert cache.get("products:search1") is not None
    print("✓ All entries exist")
    
    # Invalidate vendors pattern
    deleted = invalidate_cache("vendors:*")
    print(f"✓ Invalidated 'vendors:*' pattern ({deleted} keys)")
    
    # Vendors should be gone
    assert cache.get("vendors:category1") is None, "Vendor cache should be cleared"
    assert cache.get("vendors:category2") is None, "Vendor cache should be cleared"
    print("✓ Vendor caches cleared")
    
    # Products should still exist
    assert cache.get("products:search1") is not None, "Product cache should remain"
    assert cache.get("products:search2") is not None, "Product cache should remain"
    print("✓ Product caches still exist")
    
    # Clean up
    invalidate_cache("products:*")
    
    print("\n✅ TEST 7 PASSED: Pattern invalidation working\n")
    return True


def main():
    """Run all cache tests"""
    print("\n" + "🧪"*30)
    print("  CACHE SYSTEM TESTING - FIX #4")
    print("  Backend: Redis/Fakeredis Caching Layer")
    print("🧪"*30 + "\n")
    
    tests = [
        ("Cache Initialization", test_cache_initialization),
        ("Basic Operations", test_basic_cache_operations),
        ("TTL Expiration", test_ttl_expiration),
        ("Cache Decorator", test_cache_decorator),
        ("Key Generation", test_cache_key_generation),
        ("Statistics Tracking", test_cache_statistics),
        ("Pattern Invalidation", test_pattern_invalidation),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n❌ TEST FAILED: {name}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("  TEST SUMMARY")
    print("="*60)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {name}")
    
    print(f"\n{'='*60}")
    print(f"  Results: {passed_count}/{total_count} tests passed ({passed_count*100//total_count}%)")
    print(f"{'='*60}\n")
    
    if passed_count == total_count:
        print("🎉 ALL CACHE TESTS PASSED!")
        return 0
    else:
        print(f"⚠️  {total_count - passed_count} test(s) failed")
        return 1


if __name__ == "__main__":
    exit(main())
