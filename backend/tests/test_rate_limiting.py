"""
FIX #3: Rate Limiting Test Suite
Tests token bucket algorithm, middleware, and monitoring endpoints
"""
import time
from backend.services.rate_limiter import (
    check_rate_limit,
    get_rate_limit_stats,
    reset_rate_limit_stats,
    RateLimitExceeded,
    RATE_LIMITS
)


def test_1_normal_requests_under_limit():
    """Test that normal requests under limit are allowed"""
    print("\n=== TEST 1: Normal Requests Under Limit ===")
    
    # Reset stats
    reset_rate_limit_stats()
    
    user_id = "test_user_1"
    
    # Make 5 requests (well under 60/min limit)
    success_count = 0
    for i in range(5):
        result = check_rate_limit(user_id, "default")
        if result is None:  # No exception means success
            success_count += 1
        print(f"  Request {i+1}: {'✅ Allowed' if result is None else '❌ Denied'}")
    
    print(f"\n✅ Test 1 PASSED: {success_count}/5 requests allowed")
    assert success_count == 5, f"Expected all 5 requests to succeed, got {success_count}"


def test_2_exceed_minute_limit():
    """Test that exceeding minute limit triggers rate limiting"""
    print("\n=== TEST 2: Exceed Minute Limit ===")
    
    reset_rate_limit_stats()
    
    user_id = "test_user_2"
    endpoint_type = "default"  # 60 requests per minute
    
    allowed_count = 0
    denied_count = 0
    
    # Try to make 65 requests (should deny after 60)
    for i in range(65):
        result = check_rate_limit(user_id, endpoint_type)
        if result is None:
            allowed_count += 1
        elif isinstance(result, RateLimitExceeded):
            denied_count += 1
            if denied_count == 1:  # First denial
                print(f"  First denial at request {i+1}")
                print(f"  Retry after: {result.retry_after} seconds")
                print(f"  Limit type: {result.limit_type}")
                assert result.retry_after <= 61, "Retry after should be <= 61 seconds for minute limit (60s + 1s safety margin)"
    
    print(f"  Allowed: {allowed_count}, Denied: {denied_count}")
    print(f"\n✅ Test 2 PASSED: Rate limit enforced at 60 requests/minute")
    assert allowed_count == 60, f"Expected 60 requests allowed, got {allowed_count}"
    assert denied_count == 5, f"Expected 5 requests denied, got {denied_count}"


def test_3_different_endpoint_types():
    """Test that different endpoints have different limits"""
    print("\n=== TEST 3: Different Endpoint Types ===")
    
    reset_rate_limit_stats()
    
    user_id = "test_user_3"
    
    # Test agentic endpoint (20/min limit)
    agentic_allowed = 0
    for _ in range(25):
        result = check_rate_limit(user_id, "agentic")
        if result is None:
            agentic_allowed += 1
        elif isinstance(result, RateLimitExceeded):
            break
    
    print(f"  Agentic endpoint: {agentic_allowed} requests allowed (limit: 20/min)")
    assert agentic_allowed == 20, f"Expected 20 agentic requests, got {agentic_allowed}"
    
    # Reset for chat test
    reset_rate_limit_stats()
    
    # Test chat endpoint (30/min limit)
    chat_allowed = 0
    for _ in range(35):
        result = check_rate_limit(user_id, "chat")
        if result is None:
            chat_allowed += 1
        elif isinstance(result, RateLimitExceeded):
            break
    
    print(f"  Chat endpoint: {chat_allowed} requests allowed (limit: 30/min)")
    assert chat_allowed == 30, f"Expected 30 chat requests, got {chat_allowed}"
    
    # Reset for default test
    reset_rate_limit_stats()
    
    # Test default endpoint (60/min limit)
    default_allowed = 0
    for _ in range(65):
        result = check_rate_limit(user_id, "default")
        if result is None:
            default_allowed += 1
        elif isinstance(result, RateLimitExceeded):
            break
    
    print(f"  Default endpoint: {default_allowed} requests allowed (limit: 60/min)")
    assert default_allowed == 60, f"Expected 60 default requests, got {default_allowed}"
    
    print(f"\n✅ Test 3 PASSED: Different endpoints enforce different limits")


def test_4_user_identification():
    """Test that different users have separate rate limits"""
    print("\n=== TEST 4: User Identification ===")
    
    reset_rate_limit_stats()
    
    # User 1 makes 60 requests
    user1_id = "test_user_4a"
    user1_allowed = 0
    for _ in range(60):
        result = check_rate_limit(user1_id, "default")
        if result is None:
            user1_allowed += 1
        elif isinstance(result, RateLimitExceeded):
            break
    
    print(f"  User 1: {user1_allowed} requests allowed")
    
    # User 2 should still have full quota
    user2_id = "test_user_4b"
    user2_allowed = 0
    for _ in range(60):
        result = check_rate_limit(user2_id, "default")
        if result is None:
            user2_allowed += 1
        elif isinstance(result, RateLimitExceeded):
            break
    
    print(f"  User 2: {user2_allowed} requests allowed")
    
    print(f"\n✅ Test 4 PASSED: Users have separate rate limit buckets")
    assert user1_allowed == 60, f"User 1 should get 60 requests, got {user1_allowed}"
    assert user2_allowed == 60, f"User 2 should get 60 requests, got {user2_allowed}"


def test_5_stats_tracking():
    """Test that stats are tracked correctly"""
    print("\n=== TEST 5: Stats Tracking ===")
    
    reset_rate_limit_stats()
    
    user_id = "test_user_5"
    
    # Make 50 requests
    for _ in range(50):
        result = check_rate_limit(user_id, "default")
        # Continue regardless of result
    
    # Get stats
    stats = get_rate_limit_stats()
    
    print(f"  Total requests: {stats['total_requests']}")
    print(f"  Total users: {stats['total_users']}")
    print(f"  Total violations: {stats['total_violations']}")
    
    assert stats['total_requests'] == 50, f"Expected 50 requests, got {stats['total_requests']}"
    assert stats['total_users'] >= 1, f"Expected at least 1 user, got {stats['total_users']}"
    
    # Get user-specific stats
    user_stats = get_rate_limit_stats(user_id)
    print(f"  User {user_id} minute usage: {user_stats['current_usage']['last_minute']}")
    
    assert user_stats['current_usage']['last_minute'] == 50, \
        f"Expected 50 requests in last minute, got {user_stats['current_usage']['last_minute']}"
    
    print(f"\n✅ Test 5 PASSED: Stats tracked correctly")


def test_6_stats_reset():
    """Test that stats reset works"""
    print("\n=== TEST 6: Stats Reset ===")
    
    reset_rate_limit_stats()
    
    user_id = "test_user_6"
    
    # Make some requests
    for _ in range(30):
        result = check_rate_limit(user_id, "default")
        # Continue regardless of result
    
    stats_before = get_rate_limit_stats()
    print(f"  Before reset: {stats_before['total_requests']} requests")
    
    # Reset
    reset_rate_limit_stats()
    
    stats_after = get_rate_limit_stats()
    print(f"  After reset: {stats_after['total_requests']} requests")
    
    assert stats_after['total_requests'] == 0, f"Expected 0 requests after reset, got {stats_after['total_requests']}"
    assert stats_after['total_users'] == 0, f"Expected 0 users after reset, got {stats_after['total_users']}"
    
    print(f"\n✅ Test 6 PASSED: Stats reset successfully")


def test_7_rate_limit_configuration():
    """Test that rate limit configuration is correct"""
    print("\n=== TEST 7: Rate Limit Configuration ===")
    
    # Check that limits are configured correctly
    print(f"  Default limits: {RATE_LIMITS['default']}")
    print(f"  Agentic limits: {RATE_LIMITS['agentic']}")
    print(f"  Chat limits: {RATE_LIMITS['chat']}")
    
    # Verify default limits
    assert RATE_LIMITS['default']['requests_per_minute'] == 60, \
        f"Expected default 60/min, got {RATE_LIMITS['default']['requests_per_minute']}"
    assert RATE_LIMITS['default']['requests_per_hour'] == 1000, \
        f"Expected default 1000/hour, got {RATE_LIMITS['default']['requests_per_hour']}"
    assert RATE_LIMITS['default']['requests_per_day'] == 10000, \
        f"Expected default 10000/day, got {RATE_LIMITS['default']['requests_per_day']}"
    
    # Verify agentic limits (more restrictive)
    assert RATE_LIMITS['agentic']['requests_per_minute'] == 20, \
        f"Expected agentic 20/min, got {RATE_LIMITS['agentic']['requests_per_minute']}"
    assert RATE_LIMITS['agentic']['requests_per_hour'] == 300, \
        f"Expected agentic 300/hour, got {RATE_LIMITS['agentic']['requests_per_hour']}"
    assert RATE_LIMITS['agentic']['requests_per_day'] == 2000, \
        f"Expected agentic 2000/day, got {RATE_LIMITS['agentic']['requests_per_day']}"
    
    # Verify chat limits (moderate)
    assert RATE_LIMITS['chat']['requests_per_minute'] == 30, \
        f"Expected chat 30/min, got {RATE_LIMITS['chat']['requests_per_minute']}"
    assert RATE_LIMITS['chat']['requests_per_hour'] == 500, \
        f"Expected chat 500/hour, got {RATE_LIMITS['chat']['requests_per_hour']}"
    assert RATE_LIMITS['chat']['requests_per_day'] == 5000, \
        f"Expected chat 5000/day, got {RATE_LIMITS['chat']['requests_per_day']}"
    
    print(f"\n✅ Test 7 PASSED: Rate limit configuration is correct")


def run_all_tests():
    """Run all rate limiting tests"""
    print("\n" + "="*60)
    print("FIX #3: RATE LIMITING TEST SUITE")
    print("="*60)
    
    tests = [
        test_1_normal_requests_under_limit,
        test_2_exceed_minute_limit,
        test_3_different_endpoint_types,
        test_4_user_identification,
        test_5_stats_tracking,
        test_6_stats_reset,
        test_7_rate_limit_configuration
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ TEST FAILED: {test_func.__name__}")
            print(f"   Error: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ TEST ERROR: {test_func.__name__}")
            print(f"   Error: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("="*60)
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! FIX #3 Rate Limiting is working correctly.")
        return True
    else:
        print(f"\n⚠️  {failed} test(s) failed. Review the output above.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
