"""
DynamicsAdapter — reads from Microsoft Dynamics 365 Finance & Operations
                  via OData REST API (OAuth 2.0),
                  OR from ERP-specific PostgreSQL tables when D365 is not configured.

Activated by:  DATA_SOURCE=dynamics  in .env

Demo mode: When DYNAMICS_URL is not set, queries vendors_dynamics, po_headers_dynamics,
           items_dynamics, invoices_dynamics, grn_headers_dynamics, spend_dynamics tables.
Live mode: set DYNAMICS_URL, DYNAMICS_TENANT_ID, DYNAMICS_CLIENT_ID,
           DYNAMICS_CLIENT_SECRET, DYNAMICS_RESOURCE in .env
"""

import os
import logging
from decimal import Decimal
from backend.services.adapters.base_adapter import IDataSourceAdapter

logger = logging.getLogger(__name__)

_SUFFIX = 'dynamics'

_TABLE_REMAP = {
    'vendors_dynamics':              'd365_vendors',
    'po_headers_dynamics':           'd365_purchase_orders',
    'items_dynamics':                'd365_products',
    'invoices_dynamics':             'd365_journal_entries',
    'grn_headers_dynamics':          'd365_purchase_orders',
    'spend_dynamics':                'd365_purchase_orders',
    'cost_centers_dynamics':         'd365_dimensions',
    'exchange_rates_dynamics':       'd365_legal_entities',
    'purchase_requisitions_dynamics':'d365_purchase_orders',
    'approved_suppliers_dynamics':   'd365_vendors',
    'rfq_headers_dynamics':          'd365_purchase_orders',
    'vendor_quotes_dynamics':        'd365_item_prices',
    'contracts_dynamics':            'd365_purchase_orders',
    'ap_aging_dynamics':             'd365_journal_entries',
    'payment_proposals_dynamics':    'd365_journal_entries',
    'budget_dynamics':               'd365_dimensions',
    'vendor_performance_dynamics':   'd365_vendors',
    'inventory_dynamics':            'd365_warehouses',
}


def _query(table_base: str, where: str = '', params: tuple = (), limit: int = 500) -> list:
    from backend.services.nmi_data_service import get_conn
    from psycopg2.extras import RealDictCursor
    raw_table = f'{table_base}_{_SUFFIX}'
    table = _TABLE_REMAP.get(raw_table, raw_table)
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f'SELECT * FROM {table}'
            if where:
                sql += f' WHERE {where}'
            sql += f' LIMIT {limit}'
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [{k: float(v) if isinstance(v, Decimal) else v
                     for k, v in dict(r).items()} for r in rows]
    except Exception as e:
        logger.warning("[DynamicsAdapter] _query %s failed: %s", table, e)
        return []
    finally:
        if conn:
            conn.close()


def _norm_vendor(r: dict) -> dict:
    name = r.get('vendorname') or r.get('vendname') or r.get('name') or r.get('vendor_name') or ''
    vid = r.get('vendoraccount') or r.get('vendaccount') or r.get('vendor_id') or r.get('_row_id', '')
    return {
        'vendor_id': str(vid),
        'vendor_name': name,
        'name': name,
        'email': r.get('email') or r.get('primaryemail') or '',
        'phone': r.get('phone') or r.get('primaryphone') or '',
        'country': r.get('countryregion', ''),
        'city': r.get('city', ''),
        'status': 'Active' if r.get('onhold', 'No') == 'No' else 'On Hold',
        'payment_terms': r.get('paymentterms', ''),
        'credit_limit': None,
        'currency': r.get('currency', 'USD'),
    }


def _norm_item(r: dict) -> dict:
    return {
        'id': r.get('itemnumber', ''),
        'name': r.get('productname', ''),
        'description': r.get('productname', ''),
        'item_code': r.get('itemnumber', ''),
        'uom': r.get('unitofmeasure', ''),
        'unit_cost': r.get('purchaseprice', 0),
        'category': r.get('itemgroup', ''),
    }


def _norm_po(r: dict) -> dict:
    return {
        'id': r.get('purchaseordernumber', ''),
        'po_number': str(r.get('purchaseordernumber', '')),
        'vendor_id': r.get('vendoraccountnumber', ''),
        'vendor_name': r.get('vendorname', ''),
        'total_amount': r.get('totalamount', 0),
        'po_grand_total': r.get('totalamount', 0),
        'currency': r.get('currencycode', 'USD'),
        'status': r.get('status', ''),
        'po_status': r.get('status', ''),
        'po_date': str(r.get('orderdate', '')),
        'buyer': r.get('purchasingagent', ''),
    }


def _norm_invoice(r: dict) -> dict:
    return {
        'id': r.get('vendorinvoicenumber', ''),
        'invoice_number': r.get('vendorinvoicenumber', ''),
        'invoice_no': r.get('vendorinvoicenumber', ''),
        'vendor_id': r.get('vendoraccountnumber', ''),
        'vendor_name': r.get('vendorname', ''),
        'total_amount': r.get('totalamount', 0),
        'invoice_total': r.get('totalamount', 0),
        'currency': r.get('currencycode', 'USD'),
        'status': r.get('status', ''),
        'ap_status': r.get('status', ''),
        'invoice_date': str(r.get('invoicedate', '')),
        'po_reference': r.get('purchaseordernumber', ''),
    }


def _norm_grn(r: dict) -> dict:
    return {
        'id': r.get('productreceiptnumber', ''),
        'grn_number': r.get('productreceiptnumber', ''),
        'po_reference': r.get('purchaseordernumber', ''),
        'vendor_name': r.get('vendorname', ''),
        'grn_date': str(r.get('receiptdate', '')),
        'grn_status': r.get('status', 'Received'),
    }


def _norm_spend(r: dict) -> dict:
    return {
        'id': r.get('purchaseordernumber', ''),
        'vendor_name': r.get('vendorname', ''),
        'total_amount_usd': r.get('totalamount', 0),
        'period': str(r.get('orderdate', ''))[:7],
        'cost_center': r.get('department', ''),
        'currency': r.get('currencycode', 'USD'),
    }


def _norm_cost_center(r: dict) -> dict:
    return {
        'cost_center_code': r.get('dimensionvalue', ''),
        'cost_center_name': r.get('dimensionname', ''),
        'dimension_type': r.get('dimensiontype', ''),
        'is_active': r.get('isactive', True),
    }


def _norm_exchange_rate(r: dict) -> dict:
    return {
        'currency_code': r.get('currencycode', ''),
        'entity_name': r.get('name', ''),
        'country': r.get('countryregionid', ''),
        'vat_number': r.get('vatnum', ''),
    }


def _norm_pr(r: dict) -> dict:
    return {
        'pr_number': r.get('purchid', ''),
        'status': r.get('purchstatus', ''),
        'vendor_id': r.get('vendaccount', ''),
        'currency': r.get('currencycode', 'USD'),
        'order_date': str(r.get('orderdate', '')),
        'total_amount': r.get('totalamount', 0),
    }


def _norm_approved_supplier(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('vendaccount', '')),
        'vendor_name': r.get('vendname', ''),
        'email': r.get('email', ''),
        'phone': r.get('phone', ''),
        'country': r.get('countryregionid', ''),
        'currency': r.get('currency', 'USD'),
        'payment_terms': r.get('paymtermid', ''),
        'status': 'Approved',
    }


def _norm_rfq(r: dict) -> dict:
    return {
        'rfq_number': r.get('purchid', ''),
        'status': r.get('purchstatus', ''),
        'vendor_id': r.get('vendaccount', ''),
        'currency': r.get('currencycode', 'USD'),
        'order_date': str(r.get('orderdate', '')),
        'total_amount': r.get('totalamount', 0),
    }


def _norm_vendor_quote(r: dict) -> dict:
    return {
        'item_code': r.get('itemid', ''),
        'price_type': r.get('pricetype', ''),
        'currency': r.get('currencycode', 'USD'),
        'unit_price': r.get('price', 0),
    }


def _norm_contract(r: dict) -> dict:
    return {
        'contract_number': r.get('purchid', ''),
        'vendor_id': r.get('vendaccount', ''),
        'status': r.get('purchstatus', ''),
        'currency': r.get('currencycode', 'USD'),
        'start_date': str(r.get('orderdate', '')),
        'total_amount': r.get('totalamount', 0),
    }


def _norm_ap_aging(r: dict) -> dict:
    return {
        'journal_id': r.get('journalid', ''),
        'voucher': r.get('voucher', ''),
        'transaction_date': str(r.get('transdate', '')),
        'debit_amount': r.get('debitamount', 0),
        'credit_amount': r.get('creditamount', 0),
        'account_id': r.get('mainaccountid', ''),
        'journal_type': r.get('journaltype', ''),
    }


def _norm_payment_proposal(r: dict) -> dict:
    return {
        'journal_id': r.get('journalid', ''),
        'voucher': r.get('voucher', ''),
        'transaction_date': str(r.get('transdate', '')),
        'debit_amount': r.get('debitamount', 0),
        'credit_amount': r.get('creditamount', 0),
        'account_id': r.get('mainaccountid', ''),
        'journal_type': r.get('journaltype', ''),
    }


def _norm_budget(r: dict) -> dict:
    return {
        'cost_center': r.get('dimensionvalue', ''),
        'cost_center_name': r.get('dimensionname', ''),
        'dimension_type': r.get('dimensiontype', ''),
        'is_active': r.get('isactive', True),
    }


def _norm_vendor_perf(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('vendaccount', '')),
        'vendor_name': r.get('vendname', ''),
        'vendor_group': r.get('vendgroupid', ''),
        'email': r.get('email', ''),
        'phone': r.get('phone', ''),
        'country': r.get('countryregionid', ''),
        'currency': r.get('currency', 'USD'),
        'payment_terms': r.get('paymtermid', ''),
    }


def _norm_inventory(r: dict) -> dict:
    return {
        'warehouse_id': r.get('inventlocationid', ''),
        'warehouse_name': r.get('name', ''),
        'warehouse_type': r.get('type_val', ''),
        'is_active': r.get('isactive', True),
    }


class DynamicsAdapter(IDataSourceAdapter):
    """
    Reads from MS Dynamics 365 F&O via OData.
    Returns dicts with the same neutral column names as PostgreSQLAdapter.
    """

    def __init__(self):
        self.base_url     = os.environ.get("DYNAMICS_URL")          # e.g. https://org.operations.dynamics.com
        self.tenant_id    = os.environ.get("DYNAMICS_TENANT_ID")
        self.client_id    = os.environ.get("DYNAMICS_CLIENT_ID")
        self.client_secret= os.environ.get("DYNAMICS_CLIENT_SECRET")
        self.resource     = os.environ.get("DYNAMICS_RESOURCE", "https://org.operations.dynamics.com")
        self._token       = None
        self.name         = 'Dynamics 365'

    @property
    def _use_demo(self) -> bool:
        return not self.base_url

    def source_name(self) -> str:
        if self._use_demo:
            return "MS Dynamics 365 F&O (PostgreSQL demo tables)"
        return f"MS Dynamics 365 F&O ({self.base_url or 'not configured'})"

    def _get_token(self):
        if self._token:
            return self._token
        try:
            import requests
            r = requests.post(
                f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "resource": self.resource,
                }, timeout=15
            )
            r.raise_for_status()
            self._token = r.json()["access_token"]
            return self._token
        except Exception as e:
            logger.error("DynamicsAdapter token fetch failed: %s", e)
            raise

    def _get(self, entity: str, params: dict = None) -> list:
        try:
            import requests
            headers = {"Authorization": f"Bearer {self._get_token()}",
                       "Accept": "application/json"}
            r = requests.get(
                f"{self.base_url}/data/{entity}",
                headers=headers, params=params or {}, timeout=20
            )
            r.raise_for_status()
            return r.json().get("value", [])
        except Exception as e:
            logger.error("DynamicsAdapter GET %s failed: %s", entity, e)
            return []

    # ── Field mappers ──────────────────────────────────────────────────────────

    @staticmethod
    def _map_vendor(v: dict) -> dict:
        return {
            "vendor_id":   v.get("VendorAccountNumber"),
            "vendor_name": v.get("VendorOrganizationName"),
            "country":     v.get("AddressCountryRegionId"),
            "city":        v.get("AddressCity"),
            "active":      v.get("IsVendorBlocked") == "No",
        }

    @staticmethod
    def _map_po_header(po: dict) -> dict:
        return {
            "po_number":      po.get("PurchaseOrderNumber"),
            "po_date":        po.get("PurchaseOrderDate"),
            "vendor_id":      po.get("VendorAccountNumber"),
            "po_grand_total": po.get("TotalInvoiceAmount"),
            "currency":       po.get("CurrencyCode"),
            "po_status":      po.get("PurchaseOrderStatus"),
        }

    @staticmethod
    def _map_invoice(inv: dict) -> dict:
        return {
            "invoice_no":    inv.get("VendorInvoiceNumber"),
            "invoice_date":  inv.get("InvoiceDate"),
            "vendor_id":     inv.get("VendorAccountNumber"),
            "invoice_total": inv.get("TotalAmount"),
            "currency":      inv.get("CurrencyCode"),
            "ap_status":     inv.get("Status"),
        }

    # ── Master Data ────────────────────────────────────────────────────────────

    def get_vendors(self, active_only: bool = True, limit: int = 200) -> list:
        if self._use_demo:
            where = ''  # CSV data may not have onhold column
            return [_norm_vendor(r) for r in _query('vendors', where=where, limit=limit)]
        try:
            rows = self._get("VendVendorV2", {"$top": limit})
            if active_only:
                rows = [r for r in rows if r.get("IsVendorBlocked") == "No"]
            return [self._map_vendor(r) for r in rows]
        except Exception as e:
            logger.error("DynamicsAdapter.get_vendors failed: %s", e)
            return []

    def get_items(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'itemnumber = %s'
                params = (item_code,)
            return [_norm_item(r) for r in _query('items', where=where, params=params)]
        try:
            rows = self._get("ReleasedProductsV2", {"$top": 200})
            return [{"item_code": r.get("ItemNumber"), "item_description": r.get("ProductName"),
                     "category": r.get("ItemModelGroupId")} for r in rows]
        except Exception as e:
            logger.error("DynamicsAdapter.get_items failed: %s", e)
            return []

    def get_cost_centers(self) -> list:
        if self._use_demo:
            return [_norm_cost_center(r) for r in _query('cost_centers')]
        logger.info("[DynamicsAdapter] get_cost_centers: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_cost_centers()

    def get_exchange_rates(self) -> list:
        if self._use_demo:
            return [_norm_exchange_rate(r) for r in _query('exchange_rates')]
        logger.info("[DynamicsAdapter] get_exchange_rates: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_exchange_rates()

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'purchstatus = %s'
                params = (status,)
            return [_norm_pr(r) for r in _query('purchase_requisitions', where=where, params=params, limit=limit)]
        try:
            rows = self._get("PurchaseRequisitionHeaders", {"$top": limit})
            return [{"pr_number": r.get("PurchaseRequisitionNumber"),
                     "status": r.get("PurchaseRequisitionStatus")} for r in rows]
        except Exception as e:
            logger.error("DynamicsAdapter.get_purchase_requisitions failed: %s", e)
            return []

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'vendgroupid = %s'
                params = (item_code,)
            return [_norm_approved_supplier(r) for r in _query('approved_suppliers', where=where, params=params)]
        logger.info("[DynamicsAdapter] get_approved_suppliers: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_approved_suppliers(item_code=item_code, category=category)

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'purchstatus = %s'
                params = (status,)
            return [_norm_rfq(r) for r in _query('rfq_headers', where=where, params=params, limit=limit)]
        try:
            rows = self._get("PurchRFQCaseTable", {"$top": limit})
            return [{"rfq_number": r.get("RFQCaseNumber"), "status": r.get("Status")} for r in rows]
        except Exception as e:
            logger.error("DynamicsAdapter.get_rfq_headers failed: %s", e)
            return []

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_name:
                where = 'itemid = %s'
                params = (item_name,)
            return [_norm_vendor_quote(r) for r in _query('vendor_quotes', where=where, params=params, limit=limit)]
        logger.info("[DynamicsAdapter] get_vendor_quotes: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_vendor_quotes(item_name=item_name, limit=limit)

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where = 'vendaccount = %s'
                params = (vendor_id,)
            return [_norm_contract(r) for r in _query('contracts', where=where, params=params, limit=limit)]
        logger.info("[DynamicsAdapter] get_contracts: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_contracts(vendor_id=vendor_id, limit=limit)

    # ── Purchase Orders ────────────────────────────────────────────────────────

    def get_purchase_orders(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'status = %s'
                params = (status,)
            return [_norm_po(r) for r in _query('po_headers', where=where, params=params, limit=limit)]
        try:
            rows = self._get("PurchaseOrderHeadersV2", {"$top": limit})
            return [self._map_po_header(r) for r in rows]
        except Exception as e:
            logger.error("DynamicsAdapter.get_purchase_orders failed: %s", e)
            return []

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_grn_headers(self, grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if po_number:
                where = 'purchaseordernumber = %s'
                params = (po_number,)
            return [_norm_grn(r) for r in _query('grn_headers', where=where, params=params, limit=limit)]
        try:
            rows = self._get("VendPackingSlipJournalHeaders", {"$top": limit})
            return [{"grn_number": r.get("PackingSlipId"), "grn_date": r.get("DeliveryDate"),
                     "grn_status": "done"} for r in rows]
        except Exception as e:
            logger.error("DynamicsAdapter.get_grn_headers failed: %s", e)
            return []

    # ── Accounts Payable ──────────────────────────────────────────────────────

    def get_vendor_invoices(self, invoice_no: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if invoice_no:
                where = 'vendorinvoicenumber = %s'
                params = (invoice_no,)
            return [_norm_invoice(r) for r in _query('invoices', where=where, params=params, limit=limit)]
        try:
            rows = self._get("VendorInvoiceHeaders", {"$top": limit})
            return [self._map_invoice(r) for r in rows]
        except Exception as e:
            logger.error("DynamicsAdapter.get_vendor_invoices failed: %s", e)
            return []

    def get_ap_aging(self) -> list:
        if self._use_demo:
            return [_norm_ap_aging(r) for r in _query('ap_aging')]
        logger.info("[DynamicsAdapter] get_ap_aging: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_ap_aging()

    def get_payment_proposals(self, limit: int = 50) -> list:
        if self._use_demo:
            return [_norm_payment_proposal(r) for r in _query('payment_proposals', limit=limit)]
        logger.info("[DynamicsAdapter] get_payment_proposals: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_payment_proposals(limit=limit)

    # ── Finance ───────────────────────────────────────────────────────────────

    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if cost_center:
                where = 'dimensionvalue = %s'
                params = (cost_center,)
            return [_norm_budget(r) for r in _query('budget', where=where, params=params)]
        logger.info("[DynamicsAdapter] get_budget_vs_actuals: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_budget_vs_actuals(cost_center=cost_center)

    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        if self._use_demo:
            return [_norm_spend(r) for r in _query('spend', limit=limit)]
        return self.get_purchase_orders(limit=limit)

    def get_vendor_performance(self, vendor_id: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where = 'vendaccount = %s'
                params = (vendor_id,)
            return [_norm_vendor_perf(r) for r in _query('vendor_performance', where=where, params=params)]
        logger.info("[DynamicsAdapter] get_vendor_performance: OData not implemented, using PostgreSQL fallback")
        return self._pg().get_vendor_performance(vendor_id=vendor_id)

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_status(self, item_code: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'inventlocationid = %s'
                params = (item_code,)
            return [_norm_inventory(r) for r in _query('inventory', where=where, params=params)]
        try:
            rows = self._get("InventOnHandEntries", {"$top": 200})
            return [{"item_code": r.get("ItemNumber"), "total_received": r.get("AvailableOrderedQuantity"),
                     "reorder_point": r.get("ReorderPoint")} for r in rows]
        except Exception as e:
            logger.error("DynamicsAdapter.get_inventory_status failed: %s", e)
            return []

    # ── System ────────────────────────────────────────────────────────────────

    def get_table_registry(self) -> list:
        from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter().get_table_registry()
