"""
Timeout Monitoring Service
Tracks request timeouts and slow operations across the system
"""
import time
import logging
from functools import wraps
from typing import Dict, Any, Callable
import asyncio

logger = logging.getLogger(__name__)

# Global timeout metrics
timeout_metrics = {
    "total_requests": 0,
    "timeouts": 0,
    "slow_requests": 0,  # Requests > 10 seconds
    "avg_response_time": 0.0,
    "max_response_time": 0.0,
    "operations": {}  # Per-operation metrics
}


def get_timeout_metrics() -> Dict[str, Any]:
    """
    Get current timeout metrics for monitoring
    
    Returns:
        Dictionary with timeout statistics
    """
    total = timeout_metrics["total_requests"]
    if total > 0:
        timeout_rate = (timeout_metrics["timeouts"] / total) * 100
        slow_rate = (timeout_metrics["slow_requests"] / total) * 100
    else:
        timeout_rate = 0.0
        slow_rate = 0.0
    
    return {
        "total_requests": total,
        "timeouts": timeout_metrics["timeouts"],
        "timeout_rate": f"{timeout_rate:.2f}%",
        "slow_requests": timeout_metrics["slow_requests"],
        "slow_request_rate": f"{slow_rate:.2f}%",
        "avg_response_time": f"{timeout_metrics['avg_response_time']:.2f}s",
        "max_response_time": f"{timeout_metrics['max_response_time']:.2f}s",
        "operations": timeout_metrics["operations"]
    }


def reset_timeout_metrics():
    """Reset all timeout metrics (for testing/admin)"""
    global timeout_metrics
    timeout_metrics = {
        "total_requests": 0,
        "timeouts": 0,
        "slow_requests": 0,
        "avg_response_time": 0.0,
        "max_response_time": 0.0,
        "operations": {}
    }
    logger.info("[TIMEOUT MONITOR] Metrics reset")


def track_timeout(operation_name: str, slow_threshold: float = 10.0):
    """
    Decorator to track operation timeouts and performance
    
    Args:
        operation_name: Name of operation being tracked
        slow_threshold: Seconds after which request is considered slow (default: 10s)
    
    Usage:
        @track_timeout("compliance_check")
        async def execute_compliance_check(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            timeout_metrics["total_requests"] += 1
            
            # Initialize operation metrics if needed
            if operation_name not in timeout_metrics["operations"]:
                timeout_metrics["operations"][operation_name] = {
                    "count": 0,
                    "timeouts": 0,
                    "slow": 0,
                    "avg_time": 0.0
                }
            
            op_metrics = timeout_metrics["operations"][operation_name]
            op_metrics["count"] += 1
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                
                # Update global metrics
                timeout_metrics["avg_response_time"] = (
                    (timeout_metrics["avg_response_time"] * (timeout_metrics["total_requests"] - 1) + duration)
                    / timeout_metrics["total_requests"]
                )
                
                if duration > timeout_metrics["max_response_time"]:
                    timeout_metrics["max_response_time"] = duration
                
                # Update operation metrics
                op_metrics["avg_time"] = (
                    (op_metrics["avg_time"] * (op_metrics["count"] - 1) + duration)
                    / op_metrics["count"]
                )
                
                # Check if slow
                if duration > slow_threshold:
                    timeout_metrics["slow_requests"] += 1
                    op_metrics["slow"] += 1
                    logger.warning(
                        f"[SLOW REQUEST] {operation_name} took {duration:.2f}s "
                        f"(threshold: {slow_threshold}s)"
                    )
                
                return result
                
            except asyncio.TimeoutError:
                duration = time.time() - start_time
                timeout_metrics["timeouts"] += 1
                op_metrics["timeouts"] += 1
                logger.error(
                    f"[TIMEOUT] {operation_name} exceeded limit after {duration:.2f}s"
                )
                raise
            
            except Exception as e:
                duration = time.time() - start_time
                logger.error(
                    f"[ERROR] {operation_name} failed after {duration:.2f}s: {str(e)}"
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            timeout_metrics["total_requests"] += 1
            
            # Initialize operation metrics if needed
            if operation_name not in timeout_metrics["operations"]:
                timeout_metrics["operations"][operation_name] = {
                    "count": 0,
                    "timeouts": 0,
                    "slow": 0,
                    "avg_time": 0.0
                }
            
            op_metrics = timeout_metrics["operations"][operation_name]
            op_metrics["count"] += 1
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                # Update global metrics
                timeout_metrics["avg_response_time"] = (
                    (timeout_metrics["avg_response_time"] * (timeout_metrics["total_requests"] - 1) + duration)
                    / timeout_metrics["total_requests"]
                )
                
                if duration > timeout_metrics["max_response_time"]:
                    timeout_metrics["max_response_time"] = duration
                
                # Update operation metrics
                op_metrics["avg_time"] = (
                    (op_metrics["avg_time"] * (op_metrics["count"] - 1) + duration)
                    / op_metrics["count"]
                )
                
                # Check if slow
                if duration > slow_threshold:
                    timeout_metrics["slow_requests"] += 1
                    op_metrics["slow"] += 1
                    logger.warning(
                        f"[SLOW REQUEST] {operation_name} took {duration:.2f}s "
                        f"(threshold: {slow_threshold}s)"
                    )
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                logger.error(
                    f"[ERROR] {operation_name} failed after {duration:.2f}s: {str(e)}"
                )
                raise
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator
