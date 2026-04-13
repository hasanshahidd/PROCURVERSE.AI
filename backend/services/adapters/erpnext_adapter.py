"""
ERPNextAdapter — reads from ERPNext / Frappe via REST API,
                 OR from ERP-specific PostgreSQL tables when ERPNext is not configured.

Activated by:  DATA_SOURCE=erpnext  in .env

Demo mode: When ERPNEXT_URL is not set, queries vendors_erpnext, po_headers_erpnext,
           items_erpnext, invoices_erpnext, grn_headers_erpnext tables.
Live mode: set ERPNEXT_URL, ERPNEXT_API_KEY, ERPNEXT_API_SECRET in .env
"""

import os
import logging
from decimal import Decimal
from backend.services.adapters.base_adapter import IDataSourceAdapter

logger = logging.getLogger(__name__)

_SUFFIX = 'erpnext'

_TABLE_REMAP = {
    'vendors_erpnext':              'erpnext_suppliers',
    'po_headers_erpnext':           'erpnext_purchase_orders',
    'items_erpnext':                'erpnext_items',
    'invoices_erpnext':             'erpnext_payment_entries',
    'grn_headers_erpnext':          'erpnext_purchase_orders',
    'spend_erpnext':                'erpnext_purchase_orders',
    'cost_centers_erpnext':         'erpnext_cost_centers',
    'exchange_rates_erpnext':       'erpnext_payment_terms',
    'purchase_requisitions_erpnext':'erpnext_purchase_orders',
    'approved_suppliers_erpnext':   'erpnext_suppliers',
    'rfq_headers_erpnext':          'erpnext_purchase_orders',
    'vendor_quotes_erpnext':        'erpnext_item_prices',
    'contracts_erpnext':            'erpnext_purchase_orders',
    'ap_aging_erpnext':             'erpnext_payment_entries',
    'payment_proposals_erpnext':    'erpnext_payment_entries',
    'budget_erpnext':               'erpnext_companies',
    'vendor_performance_erpnext':   'erpnext_suppliers',
    'inventory_erpnext':            'erpnext_warehouses',
    'gl_accounts_erpnext':          'erpnext_gl_accounts',
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
        logger.warning("[ERPNextAdapter] _query %s failed: %s", table, e)
        return []
    finally:
        if conn:
            conn.close()


def _norm_vendor(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('name', '')),
        'vendor_name': r.get('supplier_name', ''),
        'email': r.get('email_id', ''),
        'phone': r.get('mobile_no', ''),
        'country': r.get('country', ''),
        'city': '',
        'status': 'Active' if r.get('disabled', 0) == 0 else 'Disabled',
        'payment_terms': r.get('payment_terms', ''),
        'credit_limit': None,
        'currency': r.get('default_currency', 'USD'),
    }


def _norm_item(r: dict) -> dict:
    return {
        'id': r.get('name', ''),
        'name': r.get('item_name', ''),
        'description': r.get('description', r.get('item_name', '')),
        'item_code': r.get('name', ''),
        'uom': r.get('stock_uom', ''),
        'unit_cost': r.get('standard_rate', 0),
        'category': r.get('item_group', ''),
    }


def _norm_po(r: dict) -> dict:
    return {
        'id': r.get('name', ''),
        'po_number': str(r.get('name', '')),
        'vendor_id': r.get('supplier', ''),
        'vendor_name': r.get('supplier_name', r.get('supplier', '')),
        'total_amount': r.get('grand_total', 0),
        'po_grand_total': r.get('grand_total', 0),
        'currency': r.get('currency', 'USD'),
        'status': r.get('status', ''),
        'po_status': r.get('status', ''),
        'po_date': str(r.get('transaction_date', '')),
    }


def _norm_invoice(r: dict) -> dict:
    return {
        'id': r.get('name', ''),
        'invoice_number': r.get('name', ''),
        'invoice_no': r.get('name', ''),
        'vendor_id': r.get('supplier', ''),
        'vendor_name': r.get('supplier_name', r.get('supplier', '')),
        'total_amount': r.get('grand_total', 0),
        'invoice_total': r.get('grand_total', 0),
        'currency': r.get('currency', 'USD'),
        'status': r.get('status', ''),
        'ap_status': r.get('status', ''),
        'invoice_date': str(r.get('posting_date', '')),
        'po_reference': r.get('purchase_order', ''),
        'outstanding_amount': r.get('outstanding_amount', 0),
    }


def _norm_grn(r: dict) -> dict:
    return {
        'id': r.get('name', ''),
        'grn_number': r.get('name', ''),
        'po_reference': r.get('purchase_order', ''),
        'vendor_name': r.get('supplier_name', r.get('supplier', '')),
        'grn_date': str(r.get('posting_date', '')),
        'grn_status': r.get('status', 'Submitted'),
    }


class ERPNextAdapter(IDataSourceAdapter):
    """
    Reads from ERPNext via Frappe REST API.
    Returns dicts with the same neutral column names as PostgreSQLAdapter.
    """

    def __init__(self):
        self.base_url   = os.environ.get("ERPNEXT_URL")         # e.g. https://erp.company.com
        self.api_key    = os.environ.get("ERPNEXT_API_KEY")
        self.api_secret = os.environ.get("ERPNEXT_API_SECRET")
        self.name       = 'ERPNext'

    @property
    def _use_demo(self) -> bool:
        return not self.base_url

    def source_name(self) -> str:
        if self._use_demo:
            return "ERPNext (PostgreSQL demo tables)"
        return f"ERPNext ({self.base_url or 'not configured'})"

    def _auth_header(self) -> dict:
        return {"Authorization": f"token {self.api_key}:{self.api_secret}",
                "Accept": "application/json"}

    def _get_list(self, doctype: str, fields: list = None, filters: list = None,
                  limit: int = 100) -> list:
        try:
            import requests, json
            params = {
                "doctype": doctype,
                "fields": json.dumps(fields or ["name"]),
                "limit_page_length": limit,
            }
            if filters:
                params["filters"] = json.dumps(filters)
            r = requests.get(
                f"{self.base_url}/api/resource/{doctype}",
                headers=self._auth_header(), params=params, timeout=20
            )
            r.raise_for_status()
            return r.json().get("data", [])
        except Exception as e:
            logger.error("ERPNextAdapter GET %s failed: %s", doctype, e)
            return []

    # ── Field mappers ──────────────────────────────────────────────────────────

    @staticmethod
    def _map_vendor(s: dict) -> dict:
        return {
            "vendor_id":   s.get("name"),
            "vendor_name": s.get("supplier_name"),
            "country":     s.get("country"),
            "city":        s.get("city"),
            "active":      s.get("disabled") != 1,
        }

    @staticmethod
    def _map_po_header(po: dict) -> dict:
        return {
            "po_number":      po.get("name"),
            "po_date":        po.get("transaction_date"),
            "vendor_id":      po.get("supplier"),
            "po_grand_total": po.get("grand_total"),
            "currency":       po.get("currency"),
            "po_status":      po.get("status"),
            "buyer":          po.get("owner"),
        }

    @staticmethod
    def _map_invoice(inv: dict) -> dict:
        return {
            "invoice_no":    inv.get("name"),
            "invoice_date":  inv.get("posting_date"),
            "vendor_id":     inv.get("supplier"),
            "invoice_total": inv.get("grand_total"),
            "currency":      inv.get("currency"),
            "ap_status":     inv.get("status"),
        }

    # ── Master Data ────────────────────────────────────────────────────────────

    def get_vendors(self, active_only: bool = True, limit: int = 200) -> list:
        if self._use_demo:
            where = ''  # CSV data may not have disabled column
            return [_norm_vendor(r) for r in _query('vendors', where=where, limit=limit)]
        try:
            filters = [["disabled", "=", 0]] if active_only else []
            fields = ["name", "supplier_name", "country", "city", "disabled"]
            rows = self._get_list("Supplier", fields=fields, filters=filters, limit=limit)
            return [self._map_vendor(r) for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_vendors failed: %s", e)
            return []

    def get_items(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'name = %s'
                params = (item_code,)
            return [_norm_item(r) for r in _query('items', where=where, params=params)]
        try:
            fields = ["item_code", "item_name", "item_group"]
            rows = self._get_list("Item", fields=fields, limit=200)
            return [{"item_code": r.get("item_code"), "item_description": r.get("item_name"),
                     "category": r.get("item_group")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_items failed: %s", e)
            return []

    def get_cost_centers(self) -> list:
        if self._use_demo:
            rows = _query('cost_centers')
            return [{'cost_center_code': r.get('name', ''), 'cost_center_name': r.get('cost_center_name', '')} for r in rows]
        try:
            fields = ["name", "cost_center_name", "parent_cost_center"]
            rows = self._get_list("Cost Center", fields=fields, limit=100)
            return [{"cost_center_code": r.get("name"), "cost_center_name": r.get("cost_center_name")}
                    for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_cost_centers failed: %s", e)
            return []

    def get_exchange_rates(self) -> list:
        if self._use_demo:
            rows = _query('exchange_rates')
            return [{'currency_code': r.get('payment_term_name', ''), 'rate': 1.0} for r in rows]
        try:
            fields = ["from_currency", "to_currency", "exchange_rate", "date"]
            rows = self._get_list("Currency Exchange", fields=fields, limit=50)
            return [{"currency_code": r.get("from_currency"), "rate": r.get("exchange_rate"),
                     "rate_date": r.get("date")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_exchange_rates failed: %s", e)
            return []

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where, params = 'status = %s', (status,)
            rows = _query('purchase_requisitions', where=where, params=params, limit=limit)
            return [{'pr_number': r.get('name', ''), 'status': r.get('status', '')} for r in rows]
        try:
            filters = [["status", "=", status]] if status else []
            fields = ["name", "status", "transaction_date"]
            rows = self._get_list("Material Request", fields=fields, filters=filters, limit=limit)
            return [{"pr_number": r.get("name"), "status": r.get("status")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_purchase_requisitions failed: %s", e)
            return []

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            rows = _query('approved_suppliers')
            return [{'vendor_id': str(r.get('supplier_name', '')), 'vendor_name': r.get('supplier_name', ''),
                     'approval_status': 'Approved'} for r in rows]
        try:
            fields = ["name", "supplier", "item_code", "is_default"]
            rows = self._get_list("Item Default", fields=fields, limit=200)
            return [{"supplier_id": r.get("supplier"), "item_code": r.get("item_code"),
                     "is_default": r.get("is_default")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_approved_suppliers failed: %s", e)
            return []

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where, params = 'status = %s', (status,)
            rows = _query('rfq_headers', where=where, params=params, limit=limit)
            return [{'rfq_number': r.get('name', ''), 'status': r.get('status', '')} for r in rows]
        try:
            fields = ["name", "status", "transaction_date", "supplier"]
            rows = self._get_list("Request for Quotation", fields=fields, limit=limit)
            return [{"rfq_number": r.get("name"), "status": r.get("status"),
                     "vendor_id": r.get("supplier")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_rfq_headers failed: %s", e)
            return []

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        if self._use_demo:
            rows = _query('vendor_quotes', limit=limit)
            return [{'quote_id': str(r.get('_row_id', '')), 'vendor_id': r.get('supplier', ''),
                     'total_price': r.get('price_list_rate', 0)} for r in rows]
        try:
            fields = ["name", "supplier", "grand_total", "currency", "valid_till"]
            rows = self._get_list("Supplier Quotation", fields=fields, limit=limit)
            return [{"quote_id": r.get("name"), "vendor_id": r.get("supplier"),
                     "total_price": r.get("grand_total"), "currency": r.get("currency")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_vendor_quotes failed: %s", e)
            return []

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where, params = 'supplier = %s', (vendor_id,)
            rows = _query('contracts', where=where, params=params, limit=limit)
            return [{'contract_id': r.get('name', ''), 'vendor_id': r.get('supplier', ''),
                     'status': r.get('status', '')} for r in rows]
        try:
            fields = ["name", "supplier", "start_date", "end_date", "grand_total", "status"]
            filters = [["supplier", "=", vendor_id]] if vendor_id else []
            rows = self._get_list("Blanket Order", fields=fields, filters=filters, limit=limit)
            return [{"contract_id": r.get("name"), "vendor_id": r.get("supplier"),
                     "start_date": r.get("start_date"), "end_date": r.get("end_date"),
                     "value": r.get("grand_total"), "status": r.get("status")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_contracts failed: %s", e)
            return []

    # ── Purchase Orders ────────────────────────────────────────────────────────

    def get_purchase_orders(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'status = %s'
                params = (status,)
            return [_norm_po(r) for r in _query('po_headers', where=where, params=params, limit=limit)]
        try:
            filters = [["status", "=", status]] if status else []
            fields = ["name", "transaction_date", "supplier", "grand_total", "currency",
                      "status", "owner"]
            rows = self._get_list("Purchase Order", fields=fields, filters=filters, limit=limit)
            return [self._map_po_header(r) for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_purchase_orders failed: %s", e)
            return []

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_grn_headers(self, grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if po_number:
                where = 'purchase_order = %s'
                params = (po_number,)
            elif grn_number:
                where = 'name = %s'
                params = (grn_number,)
            return [_norm_grn(r) for r in _query('grn_headers', where=where, params=params, limit=limit)]
        try:
            fields = ["name", "posting_date", "supplier", "status", "purchase_order"]
            rows = self._get_list("Purchase Receipt", fields=fields, limit=limit)
            return [{"grn_number": r.get("name"), "grn_date": r.get("posting_date"),
                     "grn_status": r.get("status"), "po_number": r.get("purchase_order")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_grn_headers failed: %s", e)
            return []

    # ── Accounts Payable ──────────────────────────────────────────────────────

    def get_vendor_invoices(self, invoice_no: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if invoice_no:
                where = 'name = %s'
                params = (invoice_no,)
            return [_norm_invoice(r) for r in _query('invoices', where=where, params=params, limit=limit)]
        try:
            filters = [["name", "=", invoice_no]] if invoice_no else []
            fields = ["name", "posting_date", "supplier", "grand_total", "currency", "status"]
            rows = self._get_list("Purchase Invoice", fields=fields, filters=filters, limit=limit)
            return [self._map_invoice(r) for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_vendor_invoices failed: %s", e)
            return []

    def get_ap_aging(self) -> list:
        if self._use_demo:
            rows = _query('ap_aging')
            return [{'invoice_no': r.get('name', ''), 'vendor_id': r.get('party', ''),
                     'amount': r.get('paid_amount', 0), 'outstanding': r.get('paid_amount', 0)} for r in rows]
        try:
            fields = ["name", "supplier", "grand_total", "outstanding_amount", "due_date", "status"]
            rows = self._get_list("Purchase Invoice", fields=fields,
                                  filters=[["outstanding_amount", ">", 0]], limit=200)
            return [{"invoice_no": r.get("name"), "vendor_id": r.get("supplier"),
                     "amount": r.get("grand_total"), "outstanding": r.get("outstanding_amount"),
                     "due_date": r.get("due_date")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_ap_aging failed: %s", e)
            return []

    def get_payment_proposals(self, limit: int = 50) -> list:
        if self._use_demo:
            rows = _query('payment_proposals', limit=limit)
            return [{'payment_id': r.get('name', ''), 'vendor_id': r.get('party', ''),
                     'amount': r.get('paid_amount', 0), 'type': r.get('payment_type', '')} for r in rows]
        try:
            fields = ["name", "supplier", "paid_amount", "payment_type", "posting_date"]
            rows = self._get_list("Payment Entry", fields=fields, limit=limit)
            return [{"payment_id": r.get("name"), "vendor_id": r.get("supplier"),
                     "amount": r.get("paid_amount"), "type": r.get("payment_type")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_payment_proposals failed: %s", e)
            return []

    # ── Finance ───────────────────────────────────────────────────────────────

    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        if self._use_demo:
            rows = _query('budget')
            return [{'cost_center': r.get('company_name', ''), 'fy_budget': r.get('default_currency', ''),
                     'fy_actual': 0} for r in rows]
        try:
            fields = ["account", "cost_center", "budget_amount", "actual_amount"]
            rows = self._get_list("Budget", fields=fields, limit=100)
            return [{"cost_center": r.get("cost_center"), "fy_budget": r.get("budget_amount"),
                     "fy_actual": r.get("actual_amount")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_budget_vs_actuals failed: %s", e)
            return []

    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        if self._use_demo:
            return self.get_purchase_orders(limit=limit)
        return self.get_purchase_orders(limit=limit)

    def get_vendor_performance(self, vendor_id: str = None) -> list:
        if self._use_demo:
            rows = _query('vendor_performance')
            return [{'vendor_id': r.get('supplier_name', ''), 'vendor_name': r.get('supplier_name', ''),
                     'score': 75, 'quality': 80, 'delivery': 70} for r in rows]
        try:
            fields = ["name", "supplier", "total_score", "quality_rating", "delivery_rating"]
            filters = [["supplier", "=", vendor_id]] if vendor_id else []
            rows = self._get_list("Supplier Scorecard", fields=fields, filters=filters, limit=100)
            return [{"vendor_id": r.get("supplier"), "score": r.get("total_score"),
                     "quality": r.get("quality_rating"), "delivery": r.get("delivery_rating")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_vendor_performance failed: %s", e)
            return []

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_status(self, item_code: str = None) -> list:
        if self._use_demo:
            rows = _query('inventory')
            return [{'item_code': r.get('name', ''), 'warehouse': r.get('warehouse_name', ''),
                     'total_received': 0, 'reorder_point': 0} for r in rows]
        try:
            filters = [["item_code", "=", item_code]] if item_code else []
            fields = ["item_code", "actual_qty", "reorder_level", "warehouse"]
            rows = self._get_list("Bin", fields=fields, filters=filters, limit=200)
            return [{"item_code": r.get("item_code"), "total_received": r.get("actual_qty"),
                     "reorder_point": r.get("reorder_level")} for r in rows]
        except Exception as e:
            logger.error("ERPNextAdapter.get_inventory_status failed: %s", e)
            return []

    # ── System ────────────────────────────────────────────────────────────────

    def get_table_registry(self) -> list:
        from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter().get_table_registry()
