"""
Hybrid Query Service
Routes conversational queries to the active ERP adapter.

All data access goes through the adapter layer (ERP-neutral).
No direct Odoo/SQL calls — the factory determines which backend to use
based on the DATA_SOURCE environment variable.
"""

from typing import List, Dict, Any, Optional
from backend.services.adapters.factory import get_adapter
import logging

logger = logging.getLogger(__name__)

def _adapter():
    return get_adapter()


def query_odoo_data(query_type: str, filters: Dict[str, Any] = None) -> List[Dict]:
    """
    Query ERP data via the adapter layer (ERP-agnostic).

    Routes to whichever adapter is active (demo_odoo → PostgreSQL, odoo → XML-RPC, etc.)
    Falls back to Odoo XML-RPC only when adapter doesn't have the method.

    Args:
        query_type: 'purchase_orders', 'vendors', 'products', 'invoices', etc.
        filters: Optional filters like {'state': 'draft', 'limit': 10}
    """
    adapter = _adapter()
    filters = filters or {}
    limit = filters.get('limit', 100)

    try:
        if query_type == 'purchase_orders':
            return adapter.get_purchase_orders(status=filters.get('state'), limit=limit)

        elif query_type == 'vendors':
            return adapter.get_vendors(limit=limit)

        elif query_type == 'products' or query_type == 'items':
            return adapter.get_items(item_code=filters.get('search'))

        elif query_type == 'invoices':
            return adapter.get_vendor_invoices(invoice_no=filters.get('invoice_no'), limit=limit)

        elif query_type == 'contracts':
            return adapter.get_contracts(vendor_id=filters.get('vendor_id'), limit=limit)

        elif query_type == 'grn' or query_type == 'goods_receipt':
            return adapter.get_grn_headers(po_number=filters.get('po_number'), limit=limit)

        elif query_type == 'budget':
            return adapter.get_budget_vs_actuals(cost_center=filters.get('cost_center'))

        elif query_type == 'spend' or query_type == 'spend_analytics':
            return adapter.get_spend_analytics(period=filters.get('period'), limit=limit)

        elif query_type == 'vendor_performance':
            return adapter.get_vendor_performance(vendor_id=filters.get('vendor_id'))

        elif query_type == 'approved_suppliers':
            return adapter.get_approved_suppliers(item_code=filters.get('item_code'))

        elif query_type == 'cost_centers':
            return adapter.get_cost_centers()

        elif query_type == 'exchange_rates':
            return adapter.get_exchange_rates()

        else:
            logger.warning("query_odoo_data: unknown query_type '%s', returning empty", query_type)
            return []

    except Exception as e:
        logger.error("query_odoo_data(%s) via adapter [%s] failed: %s",
                     query_type, adapter.source_name(), e)
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
