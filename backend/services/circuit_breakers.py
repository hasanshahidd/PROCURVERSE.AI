"""
Circuit Breaker Service for Database and External API Calls

Prevents cascade failures by opening circuit after threshold failures.
Implements graceful degradation with fallback data.
"""

import pybreaker
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Circuit Breaker Configuration
FAILURE_THRESHOLD = 5  # Open circuit after 5 consecutive failures
RECOVERY_TIMEOUT = 60  # Try to recover after 60 seconds
EXPECTED_EXCEPTION = Exception  # Catch all exceptions


class CircuitBreakerListener(pybreaker.CircuitBreakerListener):
    """
    Custom listener to log circuit breaker state changes.
    """
    
    def state_change(self, cb, old_state, new_state):
        """Log state transitions."""
        logger.warning(f"[CIRCUIT BREAKER] {cb.name} state changed: {old_state.name} -> {new_state.name}")
    
    def failure(self, cb, exc):
        """Log failures."""
        logger.error(f"[CIRCUIT BREAKER] {cb.name} failure: {exc}")
    
    def success(self, cb):
        """Log successful calls."""
        logger.debug(f"[CIRCUIT BREAKER] {cb.name} success")


# Create Circuit Breakers with listener
listener = CircuitBreakerListener()

# PostgreSQL Circuit Breaker
postgres_breaker = pybreaker.CircuitBreaker(
    fail_max=FAILURE_THRESHOLD,
    reset_timeout=RECOVERY_TIMEOUT,
    exclude=[],  # No exceptions to exclude
    listeners=[listener],
    name="PostgreSQL_DB"
)

# Odoo XML-RPC Circuit Breaker
odoo_breaker = pybreaker.CircuitBreaker(
    fail_max=FAILURE_THRESHOLD,
    reset_timeout=RECOVERY_TIMEOUT,
    exclude=[],
    listeners=[listener],
    name="Odoo_XMLRPC"
)


# Fallback Data for Graceful Degradation
FALLBACK_DATA = {
    "approval_chains": [
        {
            "department": "IT",
            "approval_level": 1,
            "approver_name": "Manager (System Offline)",
            "budget_threshold": 50000,
            "message": "️ System unavailable - showing cached approval chain"
        }
    ],
    "budget_status": {
        "department": "Unknown",
        "allocated_budget": 0,
        "spent_budget": 0,
        "available_budget": 0,
        "message": "️ Database unavailable - budget data unavailable"
    },
    "vendors": [
        {
            "id": 0,
            "name": "System Offline",
            "message": "️ Cannot retrieve vendors - Odoo unavailable"
        }
    ],
    "purchase_orders": [
        {
            "id": 0,
            "name": "System Offline",
            "message": "️ Cannot retrieve purchase orders - Odoo unavailable"
        }
    ],
    "products": [
        {
            "id": 0,
            "name": "System Offline",
            "message": "️ Cannot retrieve products - Odoo unavailable"
        }
    ]
}


def get_fallback_data(data_type: str) -> Any:
    """
    Return fallback data when circuit is open.
    
    Args:
        data_type: Type of data to return ("approval_chains", "budget_status", etc.)
    
    Returns:
        Fallback data with warning message
    """
    fallback = FALLBACK_DATA.get(data_type, {"message": "️ System unavailable"})
    logger.warning(f"[CIRCUIT BREAKER] Returning fallback data for {data_type}")
    return fallback


def get_circuit_status() -> Dict[str, Any]:
    """
    Get current status of all circuit breakers.
    
    Returns:
        Dictionary with circuit breaker states
    """
    return {
        "postgres": {
            "state": str(postgres_breaker.current_state),
            "fail_counter": postgres_breaker.fail_counter,
            "healthy": str(postgres_breaker.current_state) == "closed"
        },
        "odoo": {
            "state": str(odoo_breaker.current_state),
            "fail_counter": odoo_breaker.fail_counter,
            "healthy": str(odoo_breaker.current_state) == "closed"
        },
        "overall_healthy": (
            str(postgres_breaker.current_state) == "closed" and 
            str(odoo_breaker.current_state) == "closed"
        )
    }


def reset_circuit_breakers():
    """
    Manually reset all circuit breakers.
    Use with caution - only for admin override.
    """
    postgres_breaker.close()
    odoo_breaker.close()
    logger.info("[CIRCUIT BREAKER] All circuit breakers manually reset")
