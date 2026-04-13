"""
Database Connection Pool Service
Manages PostgreSQL connection pool with health checks and monitoring
"""

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import os
import logging
import time
from typing import Optional, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Global connection pool instance
_connection_pool: Optional[pool.ThreadedConnectionPool] = None
_pool_stats = {
    "total_connections": 0,
    "active_connections": 0,
    "idle_connections": 0,
    "total_acquired": 0,
    "total_returned": 0,
    "failures": 0,
    "last_health_check": None,
    "pool_initialized": False
}


class DatabaseConnectionPool:
    """
    Database connection pool manager with health checks and monitoring.
    
    Features:
    - ThreadedConnectionPool for concurrent access
    - Configurable min/max connections
    - Health checks with automatic recovery
    - Connection statistics tracking
    - Connection timeout and retry logic
    """
    
    def __init__(
        self,
        database_url: str,
        minconn: int = 5,
        maxconn: int = 20,
        connection_timeout: int = 30
    ):
        """
        Initialize connection pool.
        
        Args:
            database_url: PostgreSQL connection string
            minconn: Minimum connections to maintain (default: 5)
            maxconn: Maximum connections allowed (default: 20)
            connection_timeout: Timeout for acquiring connection in seconds (default: 30)
        """
        self.database_url = database_url
        self.minconn = minconn
        self.maxconn = maxconn
        self.connection_timeout = connection_timeout
        self.pool: Optional[pool.ThreadedConnectionPool] = None
        
        # Initialize pool
        self._initialize_pool()
    
    def _initialize_pool(self) -> None:
        """Initialize the connection pool with error handling."""
        global _pool_stats
        
        try:
            self.pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=self.minconn,
                maxconn=self.maxconn,
                dsn=self.database_url,
                connect_timeout=self.connection_timeout
            )
            
            _pool_stats["pool_initialized"] = True
            _pool_stats["total_connections"] = self.minconn
            _pool_stats["idle_connections"] = self.minconn
            
            logger.info(
                f"Database connection pool initialized: "
                f"min={self.minconn}, max={self.maxconn}, timeout={self.connection_timeout}s"
            )
            
        except Exception as e:
            _pool_stats["pool_initialized"] = False
            _pool_stats["failures"] += 1
            logger.error(f"Failed to initialize connection pool: {e}")
            raise
    
    def get_connection(self) -> psycopg2.extensions.connection:
        """
        Get a connection from the pool with retry logic.
        
        Returns:
            Database connection from pool
            
        Raises:
            Exception if unable to acquire connection after retries
        """
        global _pool_stats
        
        if not self.pool:
            logger.error("Connection pool not initialized")
            _pool_stats["failures"] += 1
            raise Exception("Connection pool not initialized")
        
        max_retries = 3
        retry_delay = 1  # seconds
        
        logger.info(f"[POOL GET] Acquiring connection - Current active: {_pool_stats['active_connections']}, idle: {_pool_stats['idle_connections']}")
        
        for attempt in range(max_retries):
            try:
                conn = self.pool.getconn()
                
                # Update statistics
                _pool_stats["total_acquired"] += 1
                _pool_stats["active_connections"] += 1
                _pool_stats["idle_connections"] = max(0, _pool_stats["idle_connections"] - 1)
                
                logger.info(
                    f"[POOL GET SUCCESS] Connection acquired on attempt {attempt + 1} - "
                    f"Active: {_pool_stats['active_connections']}, Idle: {_pool_stats['idle_connections']}, "
                    f"Total acquired: {_pool_stats['total_acquired']}"
                )
                
                return conn
                
            except pool.PoolError as e:
                _pool_stats["failures"] += 1
                
                if attempt < max_retries - 1:
                    logger.warning(
                        f"️ [POOL GET RETRY] Failed attempt {attempt + 1}/{max_retries}: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(f"[POOL GET FAILED] All {max_retries} attempts failed: {e}")
                    raise
            
            except Exception as e:
                _pool_stats["failures"] += 1
                logger.error(f"[POOL GET ERROR] Unexpected error: {e}")
                raise
    
    def return_connection(self, conn: psycopg2.extensions.connection) -> None:
        """
        Return a connection to the pool.
        
        Args:
            conn: Database connection to return
        """
        global _pool_stats
        
        if not self.pool:
            logger.warning("[POOL RETURN] Connection pool not initialized, closing connection directly")
            if conn:
                conn.close()
            return
        
        try:
            self.pool.putconn(conn)
            
            # Update statistics
            _pool_stats["total_returned"] += 1
            _pool_stats["active_connections"] = max(0, _pool_stats["active_connections"] - 1)
            _pool_stats["idle_connections"] += 1
            
            logger.info(
                f"[POOL RETURN SUCCESS] Connection returned - "
                f"Active: {_pool_stats['active_connections']}, Idle: {_pool_stats['idle_connections']}, "
                f"Total returned: {_pool_stats['total_returned']}"
            )
            
        except Exception as e:
            _pool_stats["failures"] += 1
            logger.error(f"[POOL RETURN ERROR] Failed to return connection to pool: {e}")
            # Fallback: close connection
            if conn:
                try:
                    conn.close()
                except:
                    pass
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on connection pool.
        
        Returns:
            Dictionary with health status and metrics
        """
        global _pool_stats
        
        health_status = {
            "healthy": False,
            "pool_initialized": _pool_stats["pool_initialized"],
            "timestamp": time.time(),
            "error": None
        }
        
        if not self.pool:
            health_status["error"] = "Connection pool not initialized"
            logger.warning("[Health Check] Pool not initialized")
            return health_status
        
        try:
            # Test connection acquisition and return
            test_conn = self.pool.getconn()
            
            # Execute simple query
            cursor = test_conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            
            # Return connection
            self.pool.putconn(test_conn)
            
            # Update health status
            health_status["healthy"] = True
            _pool_stats["last_health_check"] = time.time()
            
            logger.info("[Health Check] Connection pool healthy")
            
        except Exception as e:
            health_status["error"] = str(e)
            _pool_stats["failures"] += 1
            logger.error(f"[Health Check] Connection pool unhealthy: {e}")
        
        return health_status
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get current pool statistics.
        
        Returns:
            Dictionary with pool statistics
        """
        global _pool_stats
        
        stats = {
            **_pool_stats,
            "config": {
                "minconn": self.minconn,
                "maxconn": self.maxconn,
                "connection_timeout": self.connection_timeout
            },
            "utilization_percent": (
                (_pool_stats["active_connections"] / self.maxconn * 100)
                if self.maxconn > 0 else 0
            )
        }
        
        return stats
    
    def close_all_connections(self) -> None:
        """Close all connections in the pool."""
        global _pool_stats
        
        if self.pool:
            try:
                self.pool.closeall()
                logger.info("All database connections closed")
                
                # Reset statistics
                _pool_stats["active_connections"] = 0
                _pool_stats["idle_connections"] = 0
                _pool_stats["pool_initialized"] = False
                
            except Exception as e:
                logger.error(f"Error closing connections: {e}")
    
    @contextmanager
    def get_cursor(self, dict_cursor: bool = True):
        """
        Context manager for getting a cursor with automatic connection management.
        
        Args:
            dict_cursor: If True, use RealDictCursor for dictionary results
            
        Yields:
            Database cursor
            
        Example:
            with pool.get_cursor() as cur:
                cur.execute("SELECT * FROM approval_chains")
                results = cur.fetchall()
        """
        conn = None
        cursor = None
        
        try:
            conn = self.get_connection()
            cursor_factory = RealDictCursor if dict_cursor else None
            cursor = conn.cursor(cursor_factory=cursor_factory)
            yield cursor
            conn.commit()
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                self.return_connection(conn)


# Global pool instance and helper functions
def init_pool(
    database_url: Optional[str] = None,
    minconn: int = 5,
    maxconn: int = 20,
    connection_timeout: int = 30
) -> DatabaseConnectionPool:
    """
    Initialize the global connection pool.
    
    Args:
        database_url: PostgreSQL connection string (uses DATABASE_URL env if None)
        minconn: Minimum connections (default: 5)
        maxconn: Maximum connections (default: 20)
        connection_timeout: Timeout in seconds (default: 30)
        
    Returns:
        DatabaseConnectionPool instance
    """
    global _connection_pool
    
    if _connection_pool is not None:
        logger.info("Connection pool already initialized")
        return _connection_pool
    
    db_url = database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not provided and not in environment")
    
    _connection_pool = DatabaseConnectionPool(
        database_url=db_url,
        minconn=minconn,
        maxconn=maxconn,
        connection_timeout=connection_timeout
    )
    
    return _connection_pool


def get_pool() -> DatabaseConnectionPool:
    """
    Get the global connection pool instance.
    
    Returns:
        DatabaseConnectionPool instance
        
    Raises:
        Exception if pool not initialized
    """
    global _connection_pool
    
    if _connection_pool is None:
        raise Exception("Connection pool not initialized. Call init_pool() first.")
    
    return _connection_pool


def get_db_connection() -> psycopg2.extensions.connection:
    """
    Get a database connection from the pool.
    
    Returns:
        Database connection
    """
    pool = get_pool()
    return pool.get_connection()


def return_db_connection(conn: psycopg2.extensions.connection) -> None:
    """
    Return a database connection to the pool.
    
    Args:
        conn: Database connection to return
    """
    pool = get_pool()
    pool.return_connection(conn)


def get_pool_stats() -> Dict[str, Any]:
    """
    Get current pool statistics.
    
    Returns:
        Dictionary with pool statistics
    """
    try:
        pool = get_pool()
        return pool.get_stats()
    except Exception as e:
        logger.error(f"Error getting pool stats: {e}")
        return {
            "error": str(e),
            "pool_initialized": False
        }


def pool_health_check() -> Dict[str, Any]:
    """
    Perform health check on the connection pool.
    
    Returns:
        Dictionary with health status
    """
    try:
        pool = get_pool()
        return pool.health_check()
    except Exception as e:
        logger.error(f"Error checking pool health: {e}")
        return {
            "healthy": False,
            "error": str(e),
            "timestamp": time.time()
        }


@contextmanager
def get_cursor(dict_cursor: bool = True):
    """
    Context manager for getting a cursor with automatic connection management.
    
    Args:
        dict_cursor: If True, use RealDictCursor for dictionary results
        
    Yields:
        Database cursor
        
    Example:
        from backend.services.db_pool import get_cursor
        
        with get_cursor() as cur:
            cur.execute("SELECT * FROM approval_chains WHERE department = %s", (dept,))
            results = cur.fetchall()
    """
    pool = get_pool()
    with pool.get_cursor(dict_cursor=dict_cursor) as cursor:
        yield cursor


def close_pool() -> None:
    """Close all connections in the pool."""
    global _connection_pool
    
    if _connection_pool:
        _connection_pool.close_all_connections()
        _connection_pool = None
