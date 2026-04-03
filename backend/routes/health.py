"""
Health Check and Circuit Breaker Status Endpoints
"""
from fastapi import APIRouter, Query, HTTPException, Request, Header, Depends
from backend.services.circuit_breakers import get_circuit_status, reset_circuit_breakers
from backend.services.timeout_monitor import get_timeout_metrics, reset_timeout_metrics
from backend.services.rate_limiter import get_rate_limit_stats, reset_rate_limit_stats
from backend.services.db_pool import get_pool_stats, pool_health_check
import logging
import os
import hmac

from backend.services.rbac import require_auth, require_role

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_local_request(request: Request) -> bool:
    client_host = (request.client.host if request.client else "") or ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        client_host = forwarded_for.split(",")[0].strip()
    return client_host in {"127.0.0.1", "::1", "localhost"}


def _require_admin_reset_access(request: Request, x_admin_token: str | None):
    """Require a valid admin token for all reset operations."""
    configured_token = os.getenv("ADMIN_RESET_TOKEN") or os.getenv("ADMIN_API_TOKEN")
    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="Admin reset token is not configured. Set ADMIN_RESET_TOKEN or ADMIN_API_TOKEN.",
        )

    if not x_admin_token or not hmac.compare_digest(x_admin_token, configured_token):
        raise HTTPException(status_code=403, detail="Admin token is invalid or missing")


@router.get("/health")
async def health_check(current_user: dict = Depends(require_auth())):
    """
    Comprehensive health check endpoint.
    Returns status of all system components including circuit breakers.
    """
    circuit_status = get_circuit_status()
    pool_stats = get_pool_stats()
    pool_health = pool_health_check()

    overall_healthy = circuit_status["overall_healthy"] and pool_health.get("healthy", False)
    overall_status = "healthy" if overall_healthy else "degraded"
    
    return {
        "status": overall_status,
        "timestamp": None,  # Will be added by middleware
        "components": {
            "postgresql": {
                "status": "up" if circuit_status["postgres"]["healthy"] else "down",
                "circuit_state": circuit_status["postgres"]["state"],
                "fail_count": circuit_status["postgres"]["fail_counter"]
            },
            "odoo_xmlrpc": {
                "status": "up" if circuit_status["odoo"]["healthy"] else "down",
                "circuit_state": circuit_status["odoo"]["state"],
                "fail_count": circuit_status["odoo"]["fail_counter"]
            },
            "connection_pool": {
                "status": "up" if pool_health.get("healthy", False) else "down",
                "pool_initialized": pool_stats.get("pool_initialized", False),
                "active_connections": pool_stats.get("active_connections", 0),
                "idle_connections": pool_stats.get("idle_connections", 0),
                "utilization_percent": pool_stats.get("utilization_percent", 0),
                "error": pool_health.get("error")
            }
        },
        "circuit_breakers": {
            "enabled": True,
            "configuration": {
                "failure_threshold": 5,
                "recovery_timeout_seconds": 60
            }
        },
        "timeouts": get_timeout_metrics(),
        "rate_limits": get_rate_limit_stats(),
        "pool_health": pool_health,
        "connection_pool": pool_stats
    }


@router.get("/health/circuit-breakers")
async def circuit_breaker_status(current_user: dict = Depends(require_auth())):
    """
    Detailed circuit breaker status endpoint.
    Returns current state of all circuit breakers.
    """
    return get_circuit_status()


@router.post("/health/circuit-breakers/reset")
async def reset_circuit_breakers_endpoint(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    current_user: dict = Depends(require_role(["admin"])),
):
    """
    Admin endpoint to manually reset circuit breakers.
    Use with caution - should only be triggered by system administrators.
    """
    try:
        _require_admin_reset_access(request, x_admin_token)
        reset_circuit_breakers()
        logger.info("[ADMIN] Circuit breakers manually reset")
        return {
            "success": True,
            "message": "All circuit breakers have been reset to closed state"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ADMIN] Failed to reset circuit breakers: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/health/timeouts")
async def timeout_metrics(current_user: dict = Depends(require_auth())):
    """
    Timeout monitoring endpoint.
    Returns detailed timeout metrics for all tracked operations.
    """
    return get_timeout_metrics()


@router.post("/health/timeouts/reset")
async def reset_timeout_metrics_endpoint(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    current_user: dict = Depends(require_role(["admin"])),
):
    """
    Admin endpoint to reset timeout metrics.
    Use for testing or after system maintenance.
    """
    try:
        _require_admin_reset_access(request, x_admin_token)
        reset_timeout_metrics()
        logger.info("[ADMIN] Timeout metrics reset")
        return {
            "success": True,
            "message": "Timeout metrics have been reset"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ADMIN] Failed to reset timeout metrics: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/health/rate-limits")
async def rate_limit_metrics(user_id: str = Query(None, description="Optional user ID to get specific user stats"), current_user: dict = Depends(require_auth())):
    """
    Rate limiting monitoring endpoint.
    Returns current rate limit statistics globally or for a specific user.
    """
    return get_rate_limit_stats(user_id)


@router.post("/health/rate-limits/reset")
async def reset_rate_limit_metrics_endpoint(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    current_user: dict = Depends(require_role(["admin"])),
):
    """
    Admin endpoint to reset rate limit statistics.
    Use for testing or after system maintenance.
    """
    try:
        _require_admin_reset_access(request, x_admin_token)
        reset_rate_limit_stats()
        logger.info("[ADMIN] Rate limit statistics reset")
        return {
            "success": True,
            "message": "Rate limit statistics have been reset"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ADMIN] Failed to reset rate limit statistics: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/health/connection-pool")
async def connection_pool_status(current_user: dict = Depends(require_auth())):
    """
    Connection pool monitoring endpoint (FIX #5).
    Returns detailed connection pool statistics and health status.
    """
    try:
        stats = get_pool_stats()
        health = pool_health_check()
        
        return {
            "health": health,
            "statistics": stats,
            "recommendations": {
                "pool_exhausted": stats.get("utilization_percent", 0) > 90,
                "increase_maxconn": stats.get("utilization_percent", 0) > 80,
                "connection_leaks": stats.get("total_acquired", 0) != stats.get("total_returned", 0)
            }
        }
    except Exception as e:
        logger.error(f"Failed to get pool status: {e}")
        return {
            "health": {"healthy": False, "error": str(e)},
            "statistics": {},
            "recommendations": {}
        }
