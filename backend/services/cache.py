"""
Redis Caching Layer - FIX #4
Provides TTL-based caching for frequently accessed data

Features:
- Redis and fakeredis support (auto-detection)
- Decorator-based caching
- TTL-based expiration
- Cache statistics tracking
- Graceful fallback if Redis unavailable
"""

import os
import json
import hashlib
import functools
from typing import Any, Optional, Callable
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

# Try to import redis, fall back to fakeredis for development
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis-py not installed. Caching disabled.")

try:
    import fakeredis
    FAKEREDIS_AVAILABLE = True
except ImportError:
    FAKEREDIS_AVAILABLE = False


class CacheService:
    """Redis-based caching service with fallback support"""
    
    def __init__(self):
        self.client: Optional[Any] = None
        self.enabled = False
        self.cache_hits = 0
        self.cache_misses = 0
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Redis client with fallback to fakeredis"""
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        use_fakeredis = os.getenv("USE_FAKEREDIS", "true").lower() == "true"
        
        try:
            if use_fakeredis and FAKEREDIS_AVAILABLE:
                # Use fakeredis for development (no Redis server needed)
                self.client = fakeredis.FakeStrictRedis(decode_responses=True)
                self.enabled = True
                logger.info("✅ Cache initialized with fakeredis (development mode)")
            elif REDIS_AVAILABLE:
                # Use real Redis for production
                self.client = redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2
                )
                # Test connection
                self.client.ping()
                self.enabled = True
                logger.info(f"✅ Cache initialized with Redis: {redis_url}")
            else:
                logger.warning("⚠️  Redis not available. Caching disabled.")
                self.enabled = False
        except Exception as e:
            logger.error(f"❌ Failed to initialize cache: {e}")
            self.enabled = False
    
    def get(self, key: str) -> Optional[str]:
        """Get value from cache"""
        if not self.enabled or not self.client:
            return None
        
        try:
            value = self.client.get(key)
            if value:
                self.cache_hits += 1
                logger.debug(f"Cache HIT: {key}")
            else:
                self.cache_misses += 1
                logger.debug(f"Cache MISS: {key}")
            return value
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    def set(self, key: str, value: str, ttl_seconds: int = 300) -> bool:
        """Set value in cache with TTL"""
        if not self.enabled or not self.client:
            return False
        
        try:
            self.client.setex(key, ttl_seconds, value)
            logger.debug(f"Cache SET: {key} (TTL: {ttl_seconds}s)")
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.enabled or not self.client:
            return False
        
        try:
            self.client.delete(key)
            logger.debug(f"Cache DELETE: {key}")
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern (e.g., 'vendors:*')"""
        if not self.enabled or not self.client:
            return 0
        
        try:
            keys = self.client.keys(pattern)
            if keys:
                deleted = self.client.delete(*keys)
                logger.info(f"Cache cleared: {deleted} keys matching '{pattern}'")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return 0
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        if not self.enabled:
            return {
                "enabled": False,
                "hits": 0,
                "misses": 0,
                "hit_rate": 0.0
            }
        
        total = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total * 100) if total > 0 else 0.0
        
        return {
            "enabled": True,
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hit_rate": round(hit_rate, 2),
            "total_requests": total
        }
    
    def reset_stats(self):
        """Reset cache statistics"""
        self.cache_hits = 0
        self.cache_misses = 0
        logger.info("Cache statistics reset")


# Global cache instance
_cache_service = CacheService()


def get_cache() -> CacheService:
    """Get global cache service instance"""
    return _cache_service


def cache_key(prefix: str, *args, **kwargs) -> str:
    """
    Generate cache key from prefix and arguments
    Example: cache_key('vendors', limit=10) -> 'vendors:a1b2c3d4'
    """
    # Create deterministic hash from args and kwargs
    key_data = {
        "args": args,
        "kwargs": sorted(kwargs.items())  # Sort for consistent hashing
    }
    key_hash = hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()[:8]
    return f"{prefix}:{key_hash}"


def cached(ttl_seconds: int = 300, key_prefix: str = "default"):
    """
    Decorator to cache function results
    
    Args:
        ttl_seconds: Time-to-live in seconds (default: 5 minutes)
        key_prefix: Prefix for cache key (e.g., 'vendors', 'products')
    
    Example:
        @cached(ttl_seconds=600, key_prefix='odoo:vendors')
        def get_vendors():
            return expensive_database_query()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_cache()
            
            # If cache disabled, call function directly
            if not cache.enabled:
                return func(*args, **kwargs)
            
            # Generate cache key
            # Skip 'self' argument for class methods
            cache_args = args[1:] if args and hasattr(args[0], '__dict__') else args
            key = cache_key(f"{key_prefix}:{func.__name__}", *cache_args, **kwargs)
            
            # Try to get from cache
            cached_value = cache.get(key)
            if cached_value is not None:
                try:
                    return json.loads(cached_value)
                except json.JSONDecodeError:
                    # If not JSON, return as string
                    return cached_value
            
            # Cache miss - call function
            result = func(*args, **kwargs)
            
            # Store in cache
            try:
                cache_value = json.dumps(result) if not isinstance(result, str) else result
                cache.set(key, cache_value, ttl_seconds)
            except (TypeError, ValueError) as e:
                logger.warning(f"Failed to cache result for {func.__name__}: {e}")
            
            return result
        
        return wrapper
    return decorator


def invalidate_cache(pattern: str):
    """
    Invalidate cache entries matching pattern
    
    Example:
        invalidate_cache('vendors:*')  # Clear all vendor caches
        invalidate_cache('products:*')  # Clear all product caches
    """
    cache = get_cache()
    return cache.clear_pattern(pattern)


# Pre-defined TTL constants for common use cases
TTL_1_MINUTE = 60
TTL_5_MINUTES = 300
TTL_15_MINUTES = 900
TTL_1_HOUR = 3600
TTL_1_DAY = 86400


if __name__ == "__main__":
    # Quick test
    cache = get_cache()
    print(f"Cache enabled: {cache.enabled}")
    
    if cache.enabled:
        # Test basic operations
        cache.set("test_key", "test_value", 60)
        value = cache.get("test_key")
        print(f"Cached value: {value}")
        
        stats = cache.get_stats()
        print(f"Stats: {stats}")
