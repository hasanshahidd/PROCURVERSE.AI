"""
Odoo XML-RPC API Client
Connects to local Odoo instance for procurement data access
"""
import xmlrpc.client
import os
from typing import List, Dict, Any, Optional
import logging
import socket
from backend.services.circuit_breakers import odoo_breaker, get_fallback_data

logger = logging.getLogger(__name__)


class TimeoutTransport(xmlrpc.client.Transport):
    """
    Custom XML-RPC transport with configurable timeout.
    Prevents hanging connections when Odoo server is slow or unresponsive.
    """
    def __init__(self, timeout=10, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = timeout
        logger.info(f"[ODOO TRANSPORT] Initialized with {timeout}s timeout")
    
    def make_connection(self, host):
        conn = super().make_connection(host)
        if hasattr(conn, 'timeout'):
            conn.timeout = self.timeout
        return conn

class OdooClient:
    """
    Client for interacting with Odoo via XML-RPC API
    Supports reading and writing procurement-related data
    """
    
    def __init__(self):
        # Odoo connection settings
        self.url = os.getenv("ODOO_URL", "http://localhost:8069")
        self.db = os.getenv("ODOO_DB", "odoo_procurement_demo")
        self.username = os.getenv("ODOO_USERNAME", "admin")
        self.password = os.getenv("ODOO_PASSWORD", "admin")
        
        # Create transport with 10-second timeout
        transport = TimeoutTransport(timeout=10)
        
        # XML-RPC endpoints with custom transport
        self.common = xmlrpc.client.ServerProxy(
            f'{self.url}/xmlrpc/2/common',
            transport=transport
        )
        self.models = xmlrpc.client.ServerProxy(
            f'{self.url}/xmlrpc/2/object',
            transport=transport
        )
        
        # Authentication
        self.uid = None
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Odoo and get user ID"""
        try:
            self.uid = self.common.authenticate(
                self.db, 
                self.username, 
                self.password, 
                {}
            )
            if self.uid:
                logger.info(f"✅ Connected to Odoo: {self.url} | Database: {self.db} | User ID: {self.uid}")
            else:
                logger.error("❌ Odoo authentication failed - check credentials")
        except Exception as e:
            logger.error(f"❌ Odoo connection error: {str(e)}")
            self.uid = None
    
    def is_connected(self) -> bool:
        """Check if connected to Odoo"""
        return self.uid is not None
    
    def execute_kw(self, model: str, method: str, args: List, kwargs: Dict = None) -> Any:
        """
        Execute Odoo model method (with circuit breaker)
        
        Args:
            model: Odoo model name (e.g., 'purchase.order')
            method: Method to call (e.g., 'search_read')
            args: Positional arguments
            kwargs: Keyword arguments
        """
        if not self.is_connected():
            raise Exception("Not connected to Odoo - check credentials")
        
        if kwargs is None:
            kwargs = {}
        
        @odoo_breaker
        def _execute():
            return self.models.execute_kw(
                self.db,
                self.uid,
                self.password,
                model,
                method,
                args,
                kwargs
            )
        
        try:
            return _execute()
        except Exception as e:
            logger.error(f"[CIRCUIT BREAKER] Odoo XML-RPC call failed: {e}")
            # Return empty list for search operations, None for others
            if method in ['search_read', 'search']:
                return []
            return None
    
    # ========== PURCHASE ORDERS ==========
    
    def get_purchase_orders(self, limit: int = 100, domain: List = None) -> List[Dict]:
        """
        Get purchase orders from Odoo
        
        Args:
            limit: Maximum number of records
            domain: Odoo domain filter (e.g., [('state', '=', 'draft')])
        
        Returns:
            List of purchase order dictionaries
        """
        if domain is None:
            domain = []
        
        try:
            orders = self.execute_kw(
                'purchase.order',
                'search_read',
                [domain],
                {
                    'fields': [
                        'name', 'partner_id', 'date_order', 'amount_total',
                        'state', 'currency_id', 'user_id', 'create_date',
                        'write_date', 'date_approve', 'origin'
                    ],
                    'limit': limit
                }
            )
            logger.info(f"📦 Retrieved {len(orders)} purchase orders from Odoo")
            return orders
        except Exception as e:
            logger.error(f"Error fetching purchase orders: {str(e)}")
            return []
    
    def get_purchase_order_by_name(self, po_name: str) -> Optional[Dict]:
        """Get specific purchase order by name (e.g., 'PO00001')"""
        orders = self.get_purchase_orders(limit=1, domain=[('name', '=', po_name)])
        return orders[0] if orders else None
    
    def create_purchase_order(
        self,
        partner_id: int,
        order_lines: List[Dict],
        origin: str = None,
        notes: str = None,
    ) -> int:
        """
        Create new purchase order in Odoo
        
        Args:
            partner_id: Supplier/vendor ID
            order_lines: List of order line dicts with product_id, quantity, price
        
        Returns:
            ID of created purchase order
        """
        order_data = {
            'partner_id': partner_id,
            'order_line': [
                (0, 0, {
                    'product_id': line['product_id'],
                    'product_qty': line['quantity'],
                    'price_unit': line['price'],
                    **({'name': line.get('name')} if line.get('name') else {})
                }) for line in order_lines
            ]
        }

        if origin:
            order_data['origin'] = origin
        if notes:
            try:
                po_fields = self.execute_kw('purchase.order', 'fields_get', [], {'attributes': ['string']}) or {}
                if 'note' in po_fields:
                    order_data['note'] = notes
                elif 'notes' in po_fields:
                    order_data['notes'] = notes
                else:
                    logger.warning("Purchase order note field not available on this Odoo model; skipping notes")
            except Exception as field_check_error:
                logger.warning(f"Could not resolve PO note field; skipping notes: {field_check_error}")
        
        po_id = self.execute_kw('purchase.order', 'create', [order_data])
        logger.info(f"✅ Created purchase order: ID {po_id}")
        return po_id
    
    # ========== PURCHASE REQUISITIONS ==========
    
    def get_purchase_requisitions(self, limit: int = 100, domain: List = None) -> List[Dict]:
        """Get purchase requisitions (requires purchase_requisition module)"""
        if domain is None:
            domain = []
        
        try:
            requisitions = self.execute_kw(
                'purchase.requisition',
                'search_read',
                [domain],
                {
                    'fields': [
                        'name', 'user_id', 'date_end', 'state',
                        'ordering_date', 'origin'
                    ],
                    'limit': limit
                }
            )
            return requisitions
        except Exception as e:
            logger.warning(f"Purchase requisition module may not be installed: {str(e)}")
            return []
    
    # ========== PRODUCTS ==========
    
    def get_products(self, limit: int = 100, search_term: str = None) -> List[Dict]:
        """Get products from Odoo"""
        domain = []
        if search_term:
            domain = [('name', 'ilike', search_term)]
        
        products = self.execute_kw(
            'product.product',
            'search_read',
            [domain],
            {
                'fields': ['name', 'default_code', 'list_price', 'standard_price', 'categ_id'],
                'limit': limit
            }
        )
        return products
    
    # ========== VENDORS/PARTNERS ==========
    
    def get_vendors(self, limit: int = 100) -> List[Dict]:
        """Get vendor/supplier list"""
        vendors = self.execute_kw(
            'res.partner',
            'search_read',
            [[('supplier_rank', '>', 0)]],  # Only suppliers
            {
                'fields': ['name', 'email', 'phone', 'country_id', 'supplier_rank', 'category_id'],
                'limit': limit
            }
        )

        # Resolve many2many category IDs to category names.
        category_ids = set()
        for vendor in vendors:
            raw_ids = vendor.get('category_id') or []
            if isinstance(raw_ids, list):
                for cid in raw_ids:
                    if isinstance(cid, int):
                        category_ids.add(cid)

        category_name_map = {}
        if category_ids:
            try:
                category_rows = self.execute_kw(
                    'res.partner.category',
                    'search_read',
                    [[('id', 'in', list(category_ids))]],
                    {'fields': ['id', 'name'], 'limit': len(category_ids)}
                )
                category_name_map = {
                    row.get('id'): row.get('name', '')
                    for row in category_rows
                    if row.get('id')
                }
            except Exception as e:
                logger.warning(f"Unable to resolve vendor category names: {str(e)}")

        for vendor in vendors:
            raw_ids = vendor.get('category_id') or []
            names = []
            if isinstance(raw_ids, list):
                names = [category_name_map.get(cid) for cid in raw_ids if category_name_map.get(cid)]

            vendor['categories'] = names
            vendor['category'] = names[0] if names else 'General'
        
        return vendors
    
    # ========== APPROVAL WORKFLOWS (For Agentic Flows) ==========
    
    def approve_purchase_order(self, po_id: int) -> bool:
        """Approve a purchase order (trigger 'button_confirm' action)"""
        try:
            self.execute_kw('purchase.order', 'button_confirm', [[po_id]])
            logger.info(f"✅ Approved purchase order: ID {po_id}")
            return True
        except Exception as e:
            logger.error(f"Error approving PO {po_id}: {str(e)}")
            return False
    
    def cancel_purchase_order(self, po_id: int) -> bool:
        """Cancel a purchase order"""
        try:
            self.execute_kw('purchase.order', 'button_cancel', [[po_id]])
            logger.info(f"❌ Cancelled purchase order: ID {po_id}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling PO {po_id}: {str(e)}")
            return False
    
    # ========== SEARCH & QUERY METHODS ==========
    
    def search_records(self, model: str, domain: List, limit: int = 100) -> List[int]:
        """Generic search - returns list of record IDs"""
        return self.execute_kw(model, 'search', [domain], {'limit': limit})
    
    def read_records(self, model: str, ids: List[int], fields: List[str]) -> List[Dict]:
        """Read specific records by ID"""
        return self.execute_kw(model, 'read', [ids], {'fields': fields})
    
    def search_count(self, model: str, domain: List) -> int:
        """Count records matching domain"""
        return self.execute_kw(model, 'search_count', [domain])
    
    # ========== ANALYTICS & INSIGHTS (For AI Agent) ==========
    
    def get_pending_approvals(self) -> List[Dict]:
        """Get all purchase orders waiting for approval"""
        return self.get_purchase_orders(
            domain=[('state', 'in', ['draft', 'sent'])],
            limit=1000
        )
    
    def get_overdue_orders(self) -> List[Dict]:
        """Get overdue purchase orders"""
        # This would need custom logic based on date_planned field
        return self.get_purchase_orders(
            domain=[('state', '=', 'purchase')],  # Confirmed orders
            limit=1000
        )
    
    def get_high_value_orders(self, threshold: float = 50000) -> List[Dict]:
        """Get high-value purchase orders above threshold"""
        return self.get_purchase_orders(
            domain=[('amount_total', '>=', threshold)],
            limit=1000
        )


# Singleton instance
_odoo_client = None

def get_odoo_client() -> OdooClient:
    """Get or create Odoo client singleton"""
    global _odoo_client
    if _odoo_client is None:
        _odoo_client = OdooClient()
    return _odoo_client
