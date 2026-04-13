"""
ERP Integration API Routes (formerly Odoo-only)
Exposes procurement data from ANY configured ERP adapter for AI agent access.

Switch backend:  DATA_SOURCE=postgresql | odoo | sap | erpnext | dynamics | oracle | sap_b1
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import logging

from backend.services.adapters.factory import get_adapter
from backend.services.rbac import require_auth

logger = logging.getLogger(__name__)

# Keep the /api/odoo prefix for backward-compatibility with existing frontend calls.
# New integrations should use /api/erp (aliased in main.py if desired).
router = APIRouter(prefix="/api/odoo", tags=["erp"])


# ========== REQUEST/RESPONSE MODELS ==========

class ERPConnectionStatus(BaseModel):
    connected: bool
    source: str
    message: str


class PurchaseOrderCreate(BaseModel):
    vendor_name: str
    product_name: str
    quantity: float = 1
    unit_price: float = 0
    department: Optional[str] = None
    currency: str = "USD"


class PurchaseOrderAction(BaseModel):
    po_id: int
    action: str  # "approve" or "cancel"


# ========== HELPERS ==========

def _adapter():
    """Shorthand — returns the active ERP adapter singleton."""
    return get_adapter()


def _is_connected() -> bool:
    """Best-effort connectivity check via adapter."""
    try:
        # Quick probe: try fetching 1 vendor
        _adapter().get_vendors(active_only=True, limit=1)
        return True
    except Exception:
        return False


# ========== CONNECTION STATUS ==========

@router.get("/status", response_model=ERPConnectionStatus)
async def get_erp_status(current_user: dict = Depends(require_auth())):
    """Check ERP connection status (works with any adapter)."""
    adapter = _adapter()
    connected = _is_connected()

    return ERPConnectionStatus(
        connected=connected,
        source=adapter.source_name(),
        message=f"Connected to {adapter.source_name()}" if connected
                else f"{adapter.source_name()} — connection failed, check credentials",
    )


# ========== PURCHASE ORDERS ==========

@router.get("/purchase-orders")
async def get_purchase_orders(
    limit: int = Query(100, le=1000),
    state: Optional[str] = Query(None, description="Filter by status: draft, confirmed, approved, done, cancel"),
    current_user: dict = Depends(require_auth()),
):
    """
    Get purchase orders from the active ERP adapter.

    Status values depend on the ERP but common ones are:
    draft, confirmed/purchase, approved, done, cancel
    """
    adapter = _adapter()

    try:
        orders = adapter.get_purchase_orders(status=state, limit=limit)
        return {
            "success": True,
            "source": adapter.source_name(),
            "count": len(orders),
            "data": orders,
        }
    except Exception as e:
        logger.error("Error fetching purchase orders from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-orders/{po_name}")
async def get_purchase_order(po_name: str, current_user: dict = Depends(require_auth())):
    """Get a specific purchase order by name/number (e.g., PO00001)."""
    adapter = _adapter()

    try:
        # Adapter returns a list — filter to the specific PO
        orders = adapter.get_purchase_orders(status=None, limit=500)
        order = next(
            (o for o in orders
             if str(o.get("name") or o.get("po_number") or o.get("order_number", "")) == str(po_name)),
            None,
        )
        if not order:
            raise HTTPException(status_code=404, detail=f"Purchase order {po_name} not found")

        return {"success": True, "source": adapter.source_name(), "data": order}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching PO %s from %s: %s", po_name, adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/purchase-orders")
async def create_purchase_order(order: PurchaseOrderCreate, current_user: dict = Depends(require_auth())):
    """Create a new purchase order via the active ERP adapter."""
    adapter = _adapter()

    try:
        total_amount = order.quantity * order.unit_price
        result = adapter.create_purchase_order_from_pr({
            "vendor_name": order.vendor_name,
            "product_name": order.product_name,
            "quantity": order.quantity,
            "unit_price": order.unit_price,
            "total_amount": total_amount,
            "department": order.department or "General",
            "currency": order.currency,
            "pr_number": "MANUAL",
        })
        return {
            "success": result.get("success", True),
            "source": adapter.source_name(),
            "message": "Purchase order created",
            "po_number": result.get("po_number"),
            "po_id": result.get("po_id"),
        }
    except Exception as e:
        logger.error("Error creating PO via %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/purchase-orders/action")
async def execute_purchase_order_action(
    action_request: PurchaseOrderAction,
    current_user: dict = Depends(require_auth()),
):
    """
    Execute an action on a purchase order (approve / cancel).

    For adapters that support direct PO workflow actions, the call is
    forwarded to the ERP. Otherwise a local status update is performed.
    """
    adapter = _adapter()

    try:
        if action_request.action == "approve":
            # Use adapter's approval workflow if available
            result = adapter.update_approval_status(
                approval_id=action_request.po_id,
                status="approved",
                notes=f"Approved via API ({adapter.source_name()})",
            )
            message = "Purchase order approved"
        elif action_request.action == "cancel":
            result = adapter.update_approval_status(
                approval_id=action_request.po_id,
                status="cancelled",
                notes=f"Cancelled via API ({adapter.source_name()})",
            )
            message = "Purchase order cancelled"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid action: {action_request.action}")

        return {"success": True, "source": adapter.source_name(), "message": message, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error executing PO action via %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


# ========== PRODUCTS / ITEMS ==========

@router.get("/products")
async def get_products(
    limit: int = Query(100, le=1000),
    search: Optional[str] = Query(None, description="Search items by name or code"),
    current_user: dict = Depends(require_auth()),
):
    """Get products/items from the active ERP adapter."""
    adapter = _adapter()

    try:
        items = adapter.get_items(item_code=search, category=None)
        # Apply limit (adapter may not honour it)
        items = items[:limit]
        return {
            "success": True,
            "source": adapter.source_name(),
            "count": len(items),
            "data": items,
        }
    except Exception as e:
        logger.error("Error fetching products from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


# ========== VENDORS ==========

@router.get("/vendors")
async def get_vendors(
    limit: int = Query(100, le=1000),
    current_user: dict = Depends(require_auth()),
):
    """Get vendor/supplier list from the active ERP adapter."""
    adapter = _adapter()

    try:
        vendors = adapter.get_vendors(active_only=True, limit=limit)
        return {
            "success": True,
            "source": adapter.source_name(),
            "count": len(vendors),
            "data": vendors,
        }
    except Exception as e:
        logger.error("Error fetching vendors from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


# ========== ANALYTICS FOR AI AGENT ==========

@router.get("/analytics/pending-approvals")
async def get_pending_approvals(current_user: dict = Depends(require_auth())):
    """Get all purchase orders/PRs pending approval — for AI agent monitoring."""
    adapter = _adapter()

    try:
        pending = adapter.get_pending_approvals(status="pending")
        return {
            "success": True,
            "source": adapter.source_name(),
            "count": len(pending),
            "data": pending,
            "alert": len(pending) > 10,
        }
    except Exception as e:
        logger.error("Error fetching pending approvals from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/high-value-orders")
async def get_high_value_orders(
    threshold: float = Query(50000, description="Minimum order value"),
    current_user: dict = Depends(require_auth()),
):
    """Get high-value purchase orders — for risk monitoring."""
    adapter = _adapter()

    try:
        all_orders = adapter.get_purchase_orders(status=None, limit=500)
        high_value = [
            o for o in all_orders
            if float(o.get("amount_total") or o.get("total_amount") or o.get("net_amount") or 0) >= threshold
        ]
        total_value = sum(
            float(o.get("amount_total") or o.get("total_amount") or o.get("net_amount") or 0)
            for o in high_value
        )
        return {
            "success": True,
            "source": adapter.source_name(),
            "count": len(high_value),
            "total_value": round(total_value, 2),
            "data": high_value,
        }
    except Exception as e:
        logger.error("Error fetching high-value orders from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


# ========== ADDITIONAL ERP DATA ==========

@router.get("/purchase-requisitions")
async def get_purchase_requisitions(
    limit: int = Query(100, le=1000),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(require_auth()),
):
    """Get purchase requisitions from the active ERP adapter."""
    adapter = _adapter()
    try:
        prs = adapter.get_purchase_requisitions(status=status, limit=limit)
        return {"success": True, "source": adapter.source_name(), "count": len(prs), "data": prs}
    except Exception as e:
        logger.error("Error fetching PRs from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/grn")
async def get_grn_headers(
    grn_number: Optional[str] = Query(None),
    po_number: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    current_user: dict = Depends(require_auth()),
):
    """Get Goods Receipt Notes from the active ERP adapter."""
    adapter = _adapter()
    try:
        grns = adapter.get_grn_headers(grn_number=grn_number, po_number=po_number, limit=limit)
        return {"success": True, "source": adapter.source_name(), "count": len(grns), "data": grns}
    except Exception as e:
        logger.error("Error fetching GRNs from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/invoices")
async def get_vendor_invoices(
    invoice_no: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    current_user: dict = Depends(require_auth()),
):
    """Get vendor invoices from the active ERP adapter."""
    adapter = _adapter()
    try:
        invoices = adapter.get_vendor_invoices(invoice_no=invoice_no, limit=limit)
        return {"success": True, "source": adapter.source_name(), "count": len(invoices), "data": invoices}
    except Exception as e:
        logger.error("Error fetching invoices from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vendor-performance")
async def get_vendor_performance(
    vendor_id: Optional[str] = Query(None),
    current_user: dict = Depends(require_auth()),
):
    """Get vendor performance/KPI data from the active ERP adapter."""
    adapter = _adapter()
    try:
        perf = adapter.get_vendor_performance(vendor_id=vendor_id)
        return {"success": True, "source": adapter.source_name(), "count": len(perf), "data": perf}
    except Exception as e:
        logger.error("Error fetching vendor performance from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/budget")
async def get_budget_vs_actuals(
    cost_center: Optional[str] = Query(None),
    current_user: dict = Depends(require_auth()),
):
    """Get budget vs actuals from the active ERP adapter."""
    adapter = _adapter()
    try:
        budget = adapter.get_budget_vs_actuals(cost_center=cost_center)
        return {"success": True, "source": adapter.source_name(), "count": len(budget), "data": budget}
    except Exception as e:
        logger.error("Error fetching budget data from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inventory")
async def get_inventory_status(
    item_code: Optional[str] = Query(None),
    current_user: dict = Depends(require_auth()),
):
    """Get inventory / stock levels from the active ERP adapter."""
    adapter = _adapter()
    try:
        inv = adapter.get_inventory_status(item_code=item_code)
        return {"success": True, "source": adapter.source_name(), "count": len(inv), "data": inv}
    except Exception as e:
        logger.error("Error fetching inventory from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spend-analytics")
async def get_spend_analytics(
    period: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
    current_user: dict = Depends(require_auth()),
):
    """Get spend analytics from the active ERP adapter."""
    adapter = _adapter()
    try:
        spend = adapter.get_spend_analytics(period=period, limit=limit)
        return {"success": True, "source": adapter.source_name(), "count": len(spend), "data": spend}
    except Exception as e:
        logger.error("Error fetching spend analytics from %s: %s", adapter.source_name(), e)
        raise HTTPException(status_code=500, detail=str(e))


# ========== GENERIC SEARCH (legacy — graceful fallback for non-Odoo) ==========

@router.post("/search")
async def search_erp(
    model: str = Query(..., description="Model/entity name (e.g., 'purchase.order', 'vendors')"),
    limit: int = Query(100, le=1000),
    current_user: dict = Depends(require_auth()),
):
    """
    Generic search endpoint. For Odoo adapters this maps to search_read;
    for other adapters it uses adapter methods with best-effort mapping.
    """
    adapter = _adapter()
    source = adapter.source_name()

    # Map common model names to adapter methods
    model_lower = model.lower().replace(".", "_").replace(" ", "_")
    try:
        if model_lower in ("purchase_order", "purchase_orders", "po"):
            data = adapter.get_purchase_orders(status=None, limit=limit)
        elif model_lower in ("product", "products", "product_product", "items"):
            data = adapter.get_items()
        elif model_lower in ("vendor", "vendors", "res_partner", "supplier", "suppliers"):
            data = adapter.get_vendors(limit=limit)
        elif model_lower in ("purchase_requisition", "purchase_requisitions", "pr"):
            data = adapter.get_purchase_requisitions(limit=limit)
        elif model_lower in ("grn", "goods_receipt", "stock_picking"):
            data = adapter.get_grn_headers(limit=limit)
        elif model_lower in ("invoice", "invoices", "account_move", "vendor_invoices"):
            data = adapter.get_vendor_invoices(limit=limit)
        elif model_lower in ("budget", "budget_vs_actuals"):
            data = adapter.get_budget_vs_actuals()
        elif model_lower in ("inventory", "stock"):
            data = adapter.get_inventory_status()
        else:
            return {
                "success": False,
                "source": source,
                "message": f"Model '{model}' not mapped for {source}. "
                           f"Available: purchase_order, product, vendor, purchase_requisition, grn, invoice, budget, inventory",
            }

        return {
            "success": True,
            "source": source,
            "model": model,
            "count": len(data),
            "data": data[:limit],
        }
    except Exception as e:
        logger.error("Error searching %s in %s: %s", model, source, e)
        raise HTTPException(status_code=500, detail=str(e))
