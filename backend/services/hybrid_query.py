"""
Hybrid Query Service
Routes conversational queries to appropriate data sources:
- Adapter layer for all ERP / P2P data (ERP-neutral, adapter-routed)
- Odoo API (legacy path, only used when DATA_SOURCE=odoo adapter is live)

All direct SQL removed. Use adapter methods exclusively.
"""

import os
from typing import List, Dict, Any, Optional
from backend.services.odoo_client import get_odoo_client
from backend.services.adapters.factory import get_adapter
import logging

logger = logging.getLogger(__name__)

def _adapter():
    return get_adapter()


def query_odoo_data(query_type: str, filters: Dict[str, Any] = None) -> List[Dict]:
    """
    Query Odoo data via API
    
    Args:
        query_type: 'purchase_orders', 'vendors', 'products'
        filters: Optional filters like {'state': 'draft', 'limit': 10}
    """
    odoo = get_odoo_client()
    filters = filters or {}
    
    # Map common terms to Odoo states
    STATE_MAPPING = {
        'pending': 'draft',
        'waiting': 'draft',
        'new': 'draft',
        'approved': 'purchase',
        'confirmed': 'purchase',
        'completed': 'done',
        'finished': 'done',
        'cancelled': 'cancel',
        'rejected': 'cancel',
    }
    
    if query_type == 'purchase_orders':
        domain = []
        if 'state' in filters:
            state = filters['state'].lower()
            # Map to Odoo state if needed
            odoo_state = STATE_MAPPING.get(state, state)
            domain.append(('state', '=', odoo_state))
        if 'amount_min' in filters and filters.get('amount_min') is not None:
            try:
                domain.append(('amount_total', '>', float(filters.get('amount_min'))))
            except (TypeError, ValueError):
                pass
        if 'amount_max' in filters and filters.get('amount_max') is not None:
            try:
                domain.append(('amount_total', '<', float(filters.get('amount_max'))))
            except (TypeError, ValueError):
                pass
        return odoo.get_purchase_orders(
            limit=filters.get('limit', 100),
            domain=domain if domain else None
        )
    
    elif query_type == 'vendors':
        return odoo.get_vendors(limit=filters.get('limit', 100))
    
    elif query_type == 'products':
        search = filters.get('search', '')
        return odoo.get_products(limit=filters.get('limit', 100), search_term=search)
    
    else:
        return []


def query_approval_chains(department: Optional[str] = None,
                           amount: Optional[float] = None) -> List[Dict]:
    """Get approval rules via adapter (replaces direct approval_chains SQL)."""
    try:
        return _adapter().get_approval_rules(document_type='PR', amount=amount)
    except Exception as e:
        logger.error("query_approval_chains failed: %s", e)
        return []


def query_budget_status(department: Optional[str] = None,
                         fiscal_year: int = 2026) -> List[Dict]:
    """Get budget tracking data via adapter."""
    try:
        rows = _adapter().get_budget_tracking(department=department)
        # Enrich with percentage columns
        result = []
        for b in rows:
            alloc = float(b.get('allocated_budget') or 1)
            spent = float(b.get('spent_budget') or 0)
            committed = float(b.get('committed_budget') or 0)
            available = float(b.get('available_budget') or 0)
            result.append({
                **b,
                'spent_percent': round(spent / alloc * 100, 2),
                'committed_percent': round(committed / alloc * 100, 2),
                'available_percent': round(available / alloc * 100, 2),
            })
        return result
    except Exception as e:
        logger.error("query_budget_status failed: %s", e)
        return []


def query_agent_actions(agent_name: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """Get agent action log via adapter."""
    try:
        rows = _adapter().get_pending_approvals()   # closest available system table
        # agent_actions is a system table — read directly via adapter log method
        # For full history, use get_pending_approvals as proxy or extend adapter
        return rows[:limit]
    except Exception as e:
        logger.error("query_agent_actions failed: %s", e)
        return []


def query_agent_decisions(agent_name: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """Get pending approval decisions via adapter."""
    try:
        rows = _adapter().get_pending_approvals()
        if agent_name:
            rows = [r for r in rows if str(r.get('agent_decision', '')).startswith(agent_name)]
        return rows[:limit]
    except Exception as e:
        logger.error("query_agent_decisions failed: %s", e)
        return []


def get_system_stats() -> Dict[str, Any]:
    """Get system statistics via adapter — no direct SQL."""
    try:
        vendors  = _adapter().get_vendors(limit=1000)
        pos      = _adapter().get_purchase_orders(limit=1000)
        budgets  = _adapter().get_budget_tracking()
        approvals = _adapter().get_pending_approvals()
        rules    = _adapter().get_approval_rules()

        total_alloc = sum(float(b.get('allocated_budget') or 0) for b in budgets)
        total_spent = sum(float(b.get('spent_budget') or 0) for b in budgets)
        total_committed = sum(float(b.get('committed_budget') or 0) for b in budgets)
        total_available = sum(float(b.get('available_budget') or 0) for b in budgets)

        return {
            "data_source": _adapter().source_name(),
            "erp_data": {
                "vendors": len(vendors),
                "purchase_orders": len(pos),
            },
            "system_tables": {
                "approval_rules": len(rules),
                "budget_tracking": len(budgets),
                "pending_approvals": len(approvals),
            },
            "budget_summary": {
                "total_allocated": total_alloc,
                "total_spent": total_spent,
                "total_committed": total_committed,
                "total_available": total_available,
            }
        }
    except Exception as e:
        logger.error("get_system_stats failed: %s", e)
        return {"error": str(e)}
