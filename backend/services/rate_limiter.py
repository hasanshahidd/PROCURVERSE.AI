"""
Rate Limiting Service
Prevents API abuse and controls OpenAI costs using token bucket algorithm
"""
import os
import time
import logging
from typing import Dict, Optional, Any
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)

# ── Sprint E fix (2026-04-11) ───────────────────────────────────────────────
# The SessionPage UI polls several endpoints every few seconds
# (/api/sessions/<id>, /events, /gates/pending, /config/data-source,
# /agentic/pending-approvals/count, /agentic/approval-chains). Combined with
# background ticks from other pages this trivially blows past 60/min and
# renders the whole app unusable behind a wall of 429s.
#
# The new defaults are deliberately generous for a dev/demo build. A
# production deployment can tighten them back with the RATE_LIMIT_*
# env-vars. Setting RATE_LIMIT_DISABLED=true short-circuits the check
# entirely for local testing.
# ───────────────────────────────────────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


RATE_LIMIT_DISABLED = os.environ.get("RATE_LIMIT_DISABLED", "false").lower() in (
    "1", "true", "yes", "on",
)

# Rate limit configuration
RATE_LIMITS = {
    "default": {
        "requests_per_minute": _env_int("RATE_LIMIT_DEFAULT_PER_MINUTE", 600),
        "requests_per_hour":   _env_int("RATE_LIMIT_DEFAULT_PER_HOUR", 10000),
        "requests_per_day":    _env_int("RATE_LIMIT_DEFAULT_PER_DAY", 50000),
    },
    "agentic": {
        "requests_per_minute": _env_int("RATE_LIMIT_AGENTIC_PER_MINUTE", 600),
        "requests_per_hour":   _env_int("RATE_LIMIT_AGENTIC_PER_HOUR", 10000),
        "requests_per_day":    _env_int("RATE_LIMIT_AGENTIC_PER_DAY", 50000),
    },
    "chat": {
        "requests_per_minute": _env_int("RATE_LIMIT_CHAT_PER_MINUTE", 300),
        "requests_per_hour":   _env_int("RATE_LIMIT_CHAT_PER_HOUR", 5000),
        "requests_per_day":    _env_int("RATE_LIMIT_CHAT_PER_DAY", 20000),
    },
    # Polling endpoints (session reads, gate list, config). These are pure
    # reads and the frontend legitimately hits them multiple times per second.
    "polling": {
        "requests_per_minute": _env_int("RATE_LIMIT_POLLING_PER_MINUTE", 2000),
        "requests_per_hour":   _env_int("RATE_LIMIT_POLLING_PER_HOUR", 60000),
        "requests_per_day":    _env_int("RATE_LIMIT_POLLING_PER_DAY", 500000),
    },
}

# Global rate limit tracking
rate_limit_storage = {
    "requests": defaultdict(lambda: {"minute": [], "hour": [], "day": []}),
    "violations": defaultdict(int),
    "total_requests": 0,
    "total_violations": 0
}

storage_lock = Lock()


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded"""
    def __init__(self, limit_type: str, limit_value: int, retry_after: int):
        self.limit_type = limit_type
        self.limit_value = limit_value
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded: {limit_value} {limit_type}. "
            f"Please retry after {retry_after} seconds."
        )


def _cleanup_old_requests(user_requests: Dict, current_time: float):
    """Remove expired timestamps from tracking"""
    # Keep requests from last 1 minute
    user_requests["minute"] = [
        ts for ts in user_requests["minute"] 
        if current_time - ts < 60
    ]
    # Keep requests from last 1 hour
    user_requests["hour"] = [
        ts for ts in user_requests["hour"] 
        if current_time - ts < 3600
    ]
    # Keep requests from last 1 day
    user_requests["day"] = [
        ts for ts in user_requests["day"] 
        if current_time - ts < 86400
    ]


def check_rate_limit(
    user_id: str,
    endpoint_type: str = "default"
) -> Optional[RateLimitExceeded]:
    """
    Check if user has exceeded rate limits.

    Args:
        user_id: Unique identifier for user (IP, session ID, etc.)
        endpoint_type: Type of endpoint ("default", "agentic", "chat", "polling")

    Returns:
        RateLimitExceeded exception if limit exceeded, None otherwise
    """
    # Sprint E fix: complete bypass for local / dev when env-var flips on.
    if RATE_LIMIT_DISABLED:
        return None

    current_time = time.time()
    limits = RATE_LIMITS.get(endpoint_type, RATE_LIMITS["default"])
    
    with storage_lock:
        user_requests = rate_limit_storage["requests"][user_id]
        
        # Cleanup old requests
        _cleanup_old_requests(user_requests, current_time)
        
        # Check minute limit
        if len(user_requests["minute"]) >= limits["requests_per_minute"]:
            oldest_request = min(user_requests["minute"])
            retry_after = int(60 - (current_time - oldest_request)) + 1
            rate_limit_storage["violations"][user_id] += 1
            rate_limit_storage["total_violations"] += 1
            
            logger.warning(
                f"[RATE LIMIT] User {user_id} exceeded minute limit "
                f"({limits['requests_per_minute']}/min) on {endpoint_type}"
            )
            
            return RateLimitExceeded("requests/minute", limits["requests_per_minute"], retry_after)
        
        # Check hour limit
        if len(user_requests["hour"]) >= limits["requests_per_hour"]:
            oldest_request = min(user_requests["hour"])
            retry_after = int(3600 - (current_time - oldest_request)) + 1
            rate_limit_storage["violations"][user_id] += 1
            rate_limit_storage["total_violations"] += 1
            
            logger.warning(
                f"[RATE LIMIT] User {user_id} exceeded hour limit "
                f"({limits['requests_per_hour']}/hour) on {endpoint_type}"
            )
            
            return RateLimitExceeded("requests/hour", limits["requests_per_hour"], retry_after)
        
        # Check day limit
        if len(user_requests["day"]) >= limits["requests_per_day"]:
            oldest_request = min(user_requests["day"])
            retry_after = int(86400 - (current_time - oldest_request)) + 1
            rate_limit_storage["violations"][user_id] += 1
            rate_limit_storage["total_violations"] += 1
            
            logger.warning(
                f"[RATE LIMIT] User {user_id} exceeded day limit "
                f"({limits['requests_per_day']}/day) on {endpoint_type}"
            )
            
            return RateLimitExceeded("requests/day", limits["requests_per_day"], retry_after)
        
        # All checks passed - record request
        user_requests["minute"].append(current_time)
        user_requests["hour"].append(current_time)
        user_requests["day"].append(current_time)
        rate_limit_storage["total_requests"] += 1
        
        return None


def get_rate_limit_stats(user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get current rate limit statistics.
    
    Args:
        user_id: Optional user ID to get specific user stats
    
    Returns:
        Dictionary with rate limit statistics
    """
    current_time = time.time()
    
    with storage_lock:
        if user_id:
            # Get stats for specific user
            user_requests = rate_limit_storage["requests"][user_id]
            _cleanup_old_requests(user_requests, current_time)
            
            return {
                "user_id": user_id,
                "current_usage": {
                    "last_minute": len(user_requests["minute"]),
                    "last_hour": len(user_requests["hour"]),
                    "last_day": len(user_requests["day"])
                },
                "limits": RATE_LIMITS["default"],
                "violations": rate_limit_storage["violations"][user_id],
                "remaining": {
                    "minute": RATE_LIMITS["default"]["requests_per_minute"] - len(user_requests["minute"]),
                    "hour": RATE_LIMITS["default"]["requests_per_hour"] - len(user_requests["hour"]),
                    "day": RATE_LIMITS["default"]["requests_per_day"] - len(user_requests["day"])
                }
            }
        else:
            # Get global stats
            total_users = len(rate_limit_storage["requests"])
            users_with_violations = len([
                user for user, violations in rate_limit_storage["violations"].items()
                if violations > 0
            ])
            
            # Calculate current active users (made request in last minute)
            active_users = 0
            for user_requests in rate_limit_storage["requests"].values():
                if user_requests["minute"] and (current_time - min(user_requests["minute"]) < 60):
                    active_users += 1
            
            return {
                "total_requests": rate_limit_storage["total_requests"],
                "total_violations": rate_limit_storage["total_violations"],
                "violation_rate": f"{(rate_limit_storage['total_violations'] / max(rate_limit_storage['total_requests'], 1)) * 100:.2f}%",
                "total_users": total_users,
                "active_users_last_minute": active_users,
                "users_with_violations": users_with_violations,
                "rate_limits": RATE_LIMITS
            }


def reset_rate_limit_stats():
    """Reset all rate limit statistics (admin only)"""
    global rate_limit_storage
    with storage_lock:
        rate_limit_storage = {
            "requests": defaultdict(lambda: {"minute": [], "hour": [], "day": []}),
            "violations": defaultdict(int),
            "total_requests": 0,
            "total_violations": 0
        }
    logger.info("[RATE LIMIT] Statistics reset")


def get_user_identifier(request) -> str:
    """
    Extract unique user identifier from request.
    Priority: Session ID > User header > IP address
    
    Args:
        request: FastAPI Request object
    
    Returns:
        User identifier string
    """
    # Try to get from headers first
    user_id = request.headers.get("X-User-ID")
    if user_id:
        return user_id
    
    # Try to get session ID from cookies
    session_id = request.cookies.get("session_id")
    if session_id:
        return f"session:{session_id}"
    
    # Fall back to IP address (less reliable with proxies)
    client_ip = request.client.host if request.client else "unknown"
    
    # Check for proxy headers
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    return f"ip:{client_ip}"
