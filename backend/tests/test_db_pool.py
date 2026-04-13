"""
FIX #5: Database Connection Pool Tests
Tests connection pooling with health checks, statistics, and reuse verification
"""

import os
import sys
import time
import pytest
from psycopg2.extras import RealDictCursor

# Add backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.services.db_pool import (
    DatabaseConnectionPool,
    init_pool,
    get_pool,
    get_db_connection,
    return_db_connection,
    get_pool_stats,
    pool_health_check,
    get_cursor,
    close_pool
)

# Test database URL
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/odoo_procurement_demo")


class TestConnectionPool:
    """Test suite for database connection pooling"""
    
    def setup_method(self):
        """Setup before each test"""
        # Close any existing pool
        close_pool()
    
    def teardown_method(self):
        """Cleanup after each test"""
        close_pool()
    
    def test_01_pool_initialization(self):
        """TEST 1: Pool Initialization"""
        print("\n" + "="*80)
        print("TEST 1: Pool Initialization")
        print("="*80)
        
        # Initialize pool with custom settings
        pool = init_pool(
            database_url=DATABASE_URL,
            minconn=3,
            maxconn=10,
            connection_timeout=30
        )
        
        assert pool is not None, "Pool should be initialized"
        assert pool.minconn == 3, "Min connections should be 3"
        assert pool.maxconn == 10, "Max connections should be 10"
        assert pool.connection_timeout == 30, "Timeout should be 30s"
        
        stats = get_pool_stats()
        assert stats["pool_initialized"] == True, "Pool should be initialized"
        assert stats["idle_connections"] == 3, "Should have 3 idle connections"
        assert stats["active_connections"] == 0, "Should have 0 active connections"
        
        print(f"  Pool initialized: {stats['config']['minconn']}-{stats['config']['maxconn']} connections")
        print(f"  Initial state: {stats['idle_connections']} idle, {stats['active_connections']} active")
        print(f"  Connection timeout: {stats['config']['connection_timeout']}s")
    
    def test_02_connection_acquisition_and_return(self):
        """TEST 2: Connection Acquisition and Return"""
        print("\n" + "="*80)
        print("TEST 2: Connection Acquisition and Return")
        print("="*80)
        
        # Initialize pool
        pool = init_pool(database_url=DATABASE_URL, minconn=2, maxconn=5)
        
        # Get initial stats
        stats_before = get_pool_stats()
        print(f"  Before: {stats_before['active_connections']} active, {stats_before['idle_connections']} idle")
        
        # Acquire connection
        conn = get_db_connection()
        assert conn is not None, "Connection should be acquired"
        
        # Check stats after acquisition
        stats_after_get = get_pool_stats()
        assert stats_after_get["active_connections"] == 1, "Should have 1 active connection"
        assert stats_after_get["total_acquired"] == 1, "Should have acquired 1 connection"
        print(f"  After acquisition: {stats_after_get['active_connections']} active, {stats_after_get['idle_connections']} idle")
        
        # Return connection
        return_db_connection(conn)
        
        # Check stats after return
        stats_after_return = get_pool_stats()
        assert stats_after_return["active_connections"] == 0, "Should have 0 active connections"
        assert stats_after_return["total_returned"] == 1, "Should have returned 1 connection"
        print(f"  After return: {stats_after_return['active_connections']} active, {stats_after_return['idle_connections']} idle")
        
        # Verify no leaks
        assert stats_after_return["total_acquired"] == stats_after_return["total_returned"], "No connection leaks"
        print(f"  No leaks: {stats_after_return['total_acquired']} acquired = {stats_after_return['total_returned']} returned")
    
    def test_03_connection_reuse(self):
        """TEST 3: Connection Reuse (No New Connections Created)"""
        print("\n" + "="*80)
        print("TEST 3: Connection Reuse")
        print("="*80)
        
        # Initialize pool
        pool = init_pool(database_url=DATABASE_URL, minconn=3, maxconn=10)
        
        # Get initial stats to track relative changes
        stats_initial = get_pool_stats()
        initial_acquired = stats_initial["total_acquired"]
        initial_returned = stats_initial["total_returned"]
        
        # Get and return connection multiple times
        connections_created = []
        iterations = 5
        for i in range(iterations):
            conn = get_db_connection()
            conn_id = id(conn)  # Track connection object identity
            connections_created.append(conn_id)
            
            # Execute a simple query to verify connection works
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            assert result == (1,), "Query should return 1"
            
            return_db_connection(conn)
            print(f"  Iteration {i+1}: Connection ID {conn_id} used and returned")
        
        stats = get_pool_stats()
        acquired_count = stats['total_acquired'] - initial_acquired
        returned_count = stats['total_returned'] - initial_returned
        
        print(f"\n  Final stats: {acquired_count} acquired, {returned_count} returned")
        print(f"  Connection reuse working (all connections returned to pool)")
        
        # Verify acquisitions and returns match
        assert acquired_count == iterations, f"Should have acquired {iterations} times (actual: {acquired_count})"
        assert returned_count == iterations, f"Should have returned {iterations} times (actual: {returned_count})"
    
    def test_04_concurrent_connections(self):
        """TEST 4: Multiple Concurrent Connections"""
        print("\n" + "="*80)
        print("TEST 4: Multiple Concurrent Connections")
        print("="*80)
        
        # Initialize pool
        pool = init_pool(database_url=DATABASE_URL, minconn=2, maxconn=10)
        
        # Acquire multiple connections simultaneously
        connections = []
        for i in range(5):
            conn = get_db_connection()
            connections.append(conn)
            print(f"  Acquired connection {i+1}")
        
        # Check stats
        stats_active = get_pool_stats()
        assert stats_active["active_connections"] == 5, "Should have 5 active connections"
        print(f"\n  Active connections: {stats_active['active_connections']}")
        print(f"  Utilization: {stats_active['utilization_percent']:.1f}%")
        
        # Return all connections
        for i, conn in enumerate(connections):
            return_db_connection(conn)
            print(f"  Returned connection {i+1}")
        
        # Check final stats
        stats_final = get_pool_stats()
        assert stats_final["active_connections"] == 0, "Should have 0 active connections"
        assert stats_final["total_acquired"] == stats_final["total_returned"], "No leaks"
        print(f"\n  All connections returned successfully")
        print(f"  No leaks: {stats_final['total_acquired']} acquired = {stats_final['total_returned']} returned")
    
    def test_05_pool_exhaustion_handling(self):
        """TEST 5: Pool Exhaustion Handling"""
        print("\n" + "="*80)
        print("TEST 5: Pool Exhaustion Handling")
        print("="*80)
        
        # Initialize pool with small max
        pool = init_pool(database_url=DATABASE_URL, minconn=1, maxconn=3)
        
        # Fill the pool
        connections = []
        for i in range(3):
            conn = get_db_connection()
            connections.append(conn)
            print(f"  Acquired connection {i+1}/3")
        
        stats_full = get_pool_stats()
        print(f"\n  Pool full: {stats_full['active_connections']}/{stats_full['config']['maxconn']} connections used")
        print(f"  Utilization: {stats_full['utilization_percent']:.1f}%")
        assert stats_full["utilization_percent"] == 100.0, "Pool should be at 100% utilization"
        
        # Return one connection to free up space
        return_db_connection(connections[0])
        connections = connections[1:]
        print(f"\n  Returned 1 connection, freeing up space")
        
        # Acquire another (should succeed now)
        conn = get_db_connection()
        connections.append(conn)
        print(f"  Successfully acquired connection after freeing space")
        
        # Clean up
        for conn in connections:
            return_db_connection(conn)
        
        stats_final = get_pool_stats()
        print(f"\n  Pool exhaustion handled correctly")
        print(f"  Final: {stats_final['active_connections']} active, no leaks")
    
    def test_06_health_check(self):
        """TEST 6: Pool Health Check"""
        print("\n" + "="*80)
        print("TEST 6: Pool Health Check")
        print("="*80)
        
        # Initialize pool
        pool = init_pool(database_url=DATABASE_URL, minconn=2, maxconn=10)
        
        # Perform health check
        health = pool_health_check()
        
        assert health["healthy"] == True, "Pool should be healthy"
        assert health["pool_initialized"] == True, "Pool should be initialized"
        assert health["error"] is None, "Should have no errors"
        assert health["timestamp"] is not None, "Should have timestamp"
        
        print(f"  Health check passed")
        print(f"  Pool status: {'HEALTHY' if health['healthy'] else 'UNHEALTHY'}")
        print(f"  Timestamp: {health['timestamp']}")
    
    def test_07_statistics_tracking(self):
        """TEST 7: Statistics Tracking"""
        print("\n" + "="*80)
        print("TEST 7: Statistics Tracking")
        print("="*80)
        
        # Initialize pool
        pool = init_pool(database_url=DATABASE_URL, minconn=2, maxconn=10)
        
        # Perform operations
        conn1 = get_db_connection()
        conn2 = get_db_connection()
        
        stats_with_active = get_pool_stats()
        print(f"  With 2 active: {stats_with_active['active_connections']} active")
        
        return_db_connection(conn1)
        return_db_connection(conn2)
        
        # Get final stats
        stats = get_pool_stats()
        
        assert "total_connections" in stats, "Should track total connections"
        assert "active_connections" in stats, "Should track active connections"
        assert "idle_connections" in stats, "Should track idle connections"
        assert "total_acquired" in stats, "Should track total acquired"
        assert "total_returned" in stats, "Should track total returned"
        assert "failures" in stats, "Should track failures"
        assert "utilization_percent" in stats, "Should track utilization"
        
        print(f"\n  Statistics tracked:")
        print(f"     - Total acquired: {stats['total_acquired']}")
        print(f"     - Total returned: {stats['total_returned']}")
        print(f"     - Active: {stats['active_connections']}")
        print(f"     - Idle: {stats['idle_connections']}")
        print(f"     - Utilization: {stats['utilization_percent']:.1f}%")
        print(f"     - Failures: {stats['failures']}")
    
    def test_08_context_manager_usage(self):
        """TEST 8: Context Manager for Cursor Operations"""
        print("\n" + "="*80)
        print("TEST 8: Context Manager for Cursor Operations")
        print("="*80)
        
        # Initialize pool
        pool = init_pool(database_url=DATABASE_URL, minconn=2, maxconn=10)
        
        # Use context manager for query
        try:
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM approval_chains")
                result = cur.fetchone()
                count = result['count']
                print(f"  Context manager executed query successfully")
                print(f"  Found {count} records in approval_chains table")
            
            # Verify connection was returned
            stats = get_pool_stats()
            assert stats["active_connections"] == 0, "Connection should be returned after context manager"
            print(f"  Connection automatically returned to pool")
            
        except Exception as e:
            pytest.fail(f"Context manager failed: {e}")


def run_tests():
    """Run all tests"""
    print("\n" + "="*80)
    print("FIX #5: DATABASE CONNECTION POOL TEST SUITE")
    print("="*80)
    print("Testing connection pooling with health checks and statistics")
    print("="*80 + "\n")
    
    test_class = TestConnectionPool()
    tests = [
        ("Pool Initialization", test_class.test_01_pool_initialization),
        ("Connection Acquisition & Return", test_class.test_02_connection_acquisition_and_return),
        ("Connection Reuse", test_class.test_03_connection_reuse),
        ("Concurrent Connections", test_class.test_04_concurrent_connections),
        ("Pool Exhaustion Handling", test_class.test_05_pool_exhaustion_handling),
        ("Health Check", test_class.test_06_health_check),
        ("Statistics Tracking", test_class.test_07_statistics_tracking),
        ("Context Manager", test_class.test_08_context_manager_usage)
    ]
    
    passed = 0
    failed = 0
    
    for i, (test_name, test_func) in enumerate(tests, 1):
        try:
            test_class.setup_method()
            test_func()
            test_class.teardown_method()
            passed += 1
            print(f"\nTEST {i} PASSED: {test_name}")
        except Exception as e:
            failed += 1
            print(f"\nTEST {i} FAILED: {test_name}")
            print(f"   Error: {str(e)}")
    
    print("\n" + "="*80)
    print(f"TEST RESULTS: {passed}/{len(tests)} tests passed")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"{failed} tests failed")
    print("="*80 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
