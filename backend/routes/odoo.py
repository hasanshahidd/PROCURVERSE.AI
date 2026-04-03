"""
Odoo Integration API Routes
Exposes Odoo procurement data for AI agent access
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import logging

from backend.services.odoo_client import get_odoo_client
from backend.services.rbac import require_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/odoo", tags=["odoo"])


# ========== REQUEST/RESPONSE MODELS ==========

class OdooConnectionStatus(BaseModel):
    connected: bool
    url: str
    database: str
    user_id: Optional[int]
    message: str


class PurchaseOrderCreate(BaseModel):
    partner_id: int
    order_lines: List[Dict[str, Any]]


class PurchaseOrderAction(BaseModel):
    po_id: int
    action: str  # "approve" or "cancel"


# ========== CONNECTION STATUS ==========

@router.get("/status", response_model=OdooConnectionStatus)
async def get_odoo_status(current_user: dict = Depends(require_auth())):
    """Check Odoo connection status"""
    client = get_odoo_client()
    
    return OdooConnectionStatus(
        connected=client.is_connected(),
        url=client.url,
        database=client.db,
        user_id=client.uid,
        message="Connected to Odoo" if client.is_connected() else "Not connected - check credentials"
    )


# ========== PURCHASE ORDERS ==========

@router.get("/purchase-orders")
async def get_purchase_orders(
    limit: int = Query(100, le=1000),
    state: Optional[str] = Query(None, description="Filter by state: draft, sent, purchase, done, cancel"),
    current_user: dict = Depends(require_auth()),
):
    """
    Get purchase orders from Odoo
    
    States:
    - draft: Quotation
    - sent: RFQ Sent
    - purchase: Purchase Order (confirmed)
    - done: Done
    - cancel: Cancelled
    """
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    domain = []
    if state:
        domain.append(('state', '=', state))
    
    try:
        orders = client.get_purchase_orders(limit=limit, domain=domain)
        return {
            "success": True,
            "count": len(orders),
            "data": orders
        }
    except Exception as e:
        logger.error(f"Error fetching purchase orders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-orders/{po_name}")
async def get_purchase_order(po_name: str, current_user: dict = Depends(require_auth())):
    """Get specific purchase order by name (e.g., PO00001)"""
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    order = client.get_purchase_order_by_name(po_name)
    
    if not order:
        raise HTTPException(status_code=404, detail=f"Purchase order {po_name} not found")
    
    return {
        "success": True,
        "data": order
    }


@router.post("/purchase-orders")
async def create_purchase_order(order: PurchaseOrderCreate, current_user: dict = Depends(require_auth())):
    """Create new purchase order in Odoo"""
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    try:
        po_id = client.create_purchase_order(
            partner_id=order.partner_id,
            order_lines=order.order_lines
        )
        return {
            "success": True,
            "message": f"Purchase order created",
            "po_id": po_id
        }
    except Exception as e:
        logger.error(f"Error creating purchase order: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/purchase-orders/action")
async def execute_purchase_order_action(action_request: PurchaseOrderAction, current_user: dict = Depends(require_auth())):
    """
    Execute action on purchase order
    
    Actions:
    - approve: Confirm the purchase order
    - cancel: Cancel the purchase order
    """
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    if action_request.action == "approve":
        success = client.approve_purchase_order(action_request.po_id)
        message = "Purchase order approved" if success else "Failed to approve"
    elif action_request.action == "cancel":
        success = client.cancel_purchase_order(action_request.po_id)
        message = "Purchase order cancelled" if success else "Failed to cancel"
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action_request.action}")
    
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {
        "success": True,
        "message": message
    }


# ========== PRODUCTS ==========

@router.get("/products")
async def get_products(
    limit: int = Query(100, le=1000),
    search: Optional[str] = Query(None, description="Search products by name"),
    current_user: dict = Depends(require_auth()),
):
    """Get products from Odoo"""
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    try:
        products = client.get_products(limit=limit, search_term=search)
        return {
            "success": True,
            "count": len(products),
            "data": products
        }
    except Exception as e:
        logger.error(f"Error fetching products: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== VENDORS ==========

@router.get("/vendors")
async def get_vendors(limit: int = Query(100, le=1000), current_user: dict = Depends(require_auth())):
    """Get vendor/supplier list from Odoo"""
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    try:
        vendors = client.get_vendors(limit=limit)
        return {
            "success": True,
            "count": len(vendors),
            "data": vendors
        }
    except Exception as e:
        logger.error(f"Error fetching vendors: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== ANALYTICS FOR AI AGENT ==========

@router.get("/analytics/pending-approvals")
async def get_pending_approvals(current_user: dict = Depends(require_auth())):
    """Get all purchase orders pending approval - for AI agent monitoring"""
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    try:
        pending = client.get_pending_approvals()
        return {
            "success": True,
            "count": len(pending),
            "data": pending,
            "alert": len(pending) > 10  # Alert if >10 pending
        }
    except Exception as e:
        logger.error(f"Error fetching pending approvals: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/high-value-orders")
async def get_high_value_orders(threshold: float = Query(50000, description="Minimum order value"), current_user: dict = Depends(require_auth())):
    """Get high-value purchase orders - for risk monitoring"""
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    try:
        high_value = client.get_high_value_orders(threshold=threshold)
        return {
            "success": True,
            "count": len(high_value),
            "total_value": sum(order.get('amount_total', 0) for order in high_value),
            "data": high_value
        }
    except Exception as e:
        logger.error(f"Error fetching high-value orders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== GENERIC SEARCH ==========

@router.post("/search")
async def search_odoo_model(
    model: str = Query(..., description="Odoo model name (e.g., 'purchase.order')"),
    domain: List = Query([], description="Odoo domain filter"),
    limit: int = Query(100, le=1000),
    current_user: dict = Depends(require_auth()),
):
    """
    Generic search across any Odoo model
    
    Example domain: [['state', '=', 'draft'], ['amount_total', '>', 1000]]
    """
    client = get_odoo_client()
    
    if not client.is_connected():
        raise HTTPException(status_code=503, detail="Odoo connection not available")
    
    try:
        ids = client.search_records(model, domain, limit)
        count = client.search_count(model, domain)
        
        return {
            "success": True,
            "model": model,
            "count": count,
            "ids": ids,
            "message": f"Found {count} records"
        }
    except Exception as e:
        logger.error(f"Error searching {model}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
