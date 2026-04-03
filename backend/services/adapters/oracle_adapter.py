"""
OracleAdapter — reads from Oracle Fusion Cloud via REST API (FBDI / REST),
                OR from ERP-specific PostgreSQL tables when Oracle is not configured.

Activated by:  DATA_SOURCE=oracle  in .env

Demo mode: When ORACLE_URL is not set, queries vendors_oracle, po_headers_oracle,
           items_oracle, invoices_oracle, grn_headers_oracle, spend_oracle tables.
Live mode: set ORACLE_URL, ORACLE_USER, ORACLE_PASSWORD in .env
"""

import os
import logging
import base64
from decimal import Decimal
from backend.services.adapters.base_adapter import IDataSourceAdapter

logger = logging.getLogger(__name__)

_REST_VERSION = "11.13.18.05"
_SUFFIX = 'oracle'


def _query(table_base: str, where: str = '', params: tuple = (), limit: int = 500) -> list:
    from backend.services.nmi_data_service import get_conn
    from psycopg2.extras import RealDictCursor
    table = f'{table_base}_{_SUFFIX}'
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
        logger.warning("[OracleAdapter] _query %s failed: %s", table, e)
        return []
    finally:
        if conn:
            conn.close()


def _norm_vendor(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('suppliernumber', '')),
        'vendor_name': r.get('suppliername', ''),
        'email': r.get('email', ''),
        'phone': r.get('phone', ''),
        'country': r.get('countryoforigin', ''),
        'city': r.get('city', ''),
        'status': 'Active' if r.get('enabledflag', 'Y') == 'Y' else 'Disabled',
        'payment_terms': r.get('paymentterms', ''),
        'credit_limit': None,
        'currency': r.get('defaultcurrency', 'USD'),
    }


def _norm_item(r: dict) -> dict:
    return {
        'id': r.get('itemnumber', ''),
        'name': r.get('itemdescription', ''),
        'description': r.get('itemdescription', ''),
        'item_code': r.get('itemnumber', ''),
        'uom': r.get('uomcode', ''),
        'unit_cost': r.get('listprice', 0),
        'category': r.get('category', ''),
    }


def _norm_po(r: dict) -> dict:
    return {
        'id': r.get('ponumber', ''),
        'po_number': str(r.get('ponumber', '')),
        'vendor_id': r.get('suppliernumber', ''),
        'vendor_name': r.get('suppliername', ''),
        'total_amount': r.get('amount', 0),
        'po_grand_total': r.get('amount', 0),
        'currency': r.get('currencycode', 'USD'),
        'status': r.get('status', ''),
        'po_status': r.get('status', ''),
        'po_date': str(r.get('orderdate', '')),
        'buyer': r.get('buyername', ''),
    }


def _norm_invoice(r: dict) -> dict:
    return {
        'id': r.get('invoicenumber', ''),
        'invoice_number': r.get('invoicenumber', ''),
        'invoice_no': r.get('invoicenumber', ''),
        'vendor_id': r.get('suppliernumber', ''),
        'vendor_name': r.get('suppliername', ''),
        'total_amount': r.get('invoiceamount', 0),
        'invoice_total': r.get('invoiceamount', 0),
        'currency': r.get('currencycode', 'USD'),
        'status': r.get('paymentstatus', ''),
        'ap_status': r.get('paymentstatus', ''),
        'invoice_date': str(r.get('invoicedate', '')),
        'po_reference': r.get('ponumber', ''),
    }


def _norm_grn(r: dict) -> dict:
    return {
        'id': r.get('receiptnumber', ''),
        'grn_number': r.get('receiptnumber', ''),
        'po_reference': r.get('ponumber', ''),
        'vendor_name': r.get('suppliername', ''),
        'grn_date': str(r.get('receiptdate', '')),
        'grn_status': r.get('receiptstatus', 'DELIVERED'),
    }


def _norm_spend(r: dict) -> dict:
    return {
        'id': r.get('ponumber', ''),
        'vendor_name': r.get('suppliername', ''),
        'total_amount_usd': r.get('amount', 0),
        'period': str(r.get('orderdate', ''))[:7],
        'cost_center': r.get('costcenter', ''),
        'currency': r.get('currencycode', 'USD'),
    }


class OracleAdapter(IDataSourceAdapter):
    """
    Reads from Oracle Fusion Cloud via REST API.
    Returns dicts with the same neutral column names as PostgreSQLAdapter.
    """

    def __init__(self):
        self.base_url = os.environ.get("ORACLE_URL")   # e.g. https://org.fa.us2.oraclecloud.com
        self.user     = os.environ.get("ORACLE_USER")
        self.password = os.environ.get("ORACLE_PASSWORD")
        self.name     = 'Oracle'

    @property
    def _use_demo(self) -> bool:
        return not self.base_url

    def source_name(self) -> str:
        if self._use_demo:
            return "Oracle Fusion Cloud (PostgreSQL demo tables)"
        return f"Oracle Fusion Cloud ({self.base_url or 'not configured'})"

    def _auth_header(self) -> str:
        creds = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        return f"Basic {creds}"

    def _get(self, path: str, params: dict = None) -> list:
        try:
            import requests
            r = requests.get(
                f"{self.base_url}/fscmRestApi/resources/{_REST_VERSION}/{path}",
                headers={"Authorization": self._auth_header(), "Accept": "application/json"},
                params=params or {}, timeout=20
            )
            r.raise_for_status()
            data = r.json()
            return data.get("items", data.get("value", []))
        except Exception as e:
            logger.error("OracleAdapter GET %s failed: %s", path, e)
            return []

    # ── Field mappers ──────────────────────────────────────────────────────────

    @staticmethod
    def _map_vendor(s: dict) -> dict:
        return {
            "vendor_id":   s.get("SupplierNumber"),
            "vendor_name": s.get("Supplier"),
            "country":     s.get("CountryOfOriginCode"),
            "city":        None,
            "active":      s.get("StatusCode") == "A",
        }

    @staticmethod
    def _map_po_header(po: dict) -> dict:
        return {
            "po_number":      po.get("PONumber"),
            "po_date":        po.get("OrderedDate"),
            "vendor_id":      po.get("SupplierId"),
            "po_grand_total": po.get("Amount"),
            "currency":       po.get("CurrencyCode"),
            "po_status":      po.get("Status"),
            "buyer":          po.get("BuyerEmail"),
        }

    @staticmethod
    def _map_invoice(inv: dict) -> dict:
        return {
            "invoice_no":    inv.get("InvoiceNumber"),
            "invoice_date":  inv.get("InvoiceDate"),
            "vendor_id":     inv.get("SupplierNumber"),
            "invoice_total": inv.get("InvoiceAmount"),
            "currency":      inv.get("InvoiceCurrencyCode"),
            "ap_status":     inv.get("InvoiceStatus"),
        }

    # ── Master Data ────────────────────────────────────────────────────────────

    def get_vendors(self, active_only: bool = True, limit: int = 200) -> list:
        if self._use_demo:
            where = "enabledflag = 'Y'" if active_only else ''
            return [_norm_vendor(r) for r in _query('vendors', where=where, limit=limit)]
        try:
            rows = self._get("suppliers", {"limit": limit})
            if active_only:
                rows = [r for r in rows if r.get("StatusCode") == "A"]
            return [self._map_vendor(r) for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_vendors failed: %s", e)
            return []

    def get_items(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'itemnumber = %s'
                params = (item_code,)
            return [_norm_item(r) for r in _query('items', where=where, params=params)]
        try:
            rows = self._get("items", {"limit": 200})
            return [{"item_code": r.get("ItemNumber"), "item_description": r.get("Description"),
                     "category": r.get("ItemClass")} for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_items failed: %s", e)
            return []

    def get_cost_centers(self) -> list:
        if self._use_demo:
            return self._pg().get_cost_centers()
        return []

    def get_exchange_rates(self) -> list:
        if self._use_demo:
            return self._pg().get_exchange_rates()
        return []

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            return self._pg().get_purchase_requisitions(status=status, limit=limit)
        try:
            rows = self._get("purchaseRequisitions", {"limit": limit})
            return [{"pr_number": r.get("RequisitionNumber"), "status": r.get("Status")} for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_purchase_requisitions failed: %s", e)
            return []

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            return self._pg().get_approved_suppliers(item_code=item_code, category=category)
        return []

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_rfq_headers(status=status, limit=limit)
        try:
            rows = self._get("negotiationHeaders", {"limit": limit})
            return [{"rfq_number": r.get("NegotiationNumber"), "status": r.get("Status")} for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_rfq_headers failed: %s", e)
            return []

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_vendor_quotes(item_name=item_name, limit=limit)
        return []

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_contracts(vendor_id=vendor_id, limit=limit)
        try:
            rows = self._get("purchasingContracts", {"limit": limit})
            return [{"contract_number": r.get("ContractNumber"), "vendor_id": r.get("SupplierNumber"),
                     "status": r.get("Status")} for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_contracts failed: %s", e)
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
            rows = self._get("purchaseOrders", {"limit": limit})
            return [self._map_po_header(r) for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_purchase_orders failed: %s", e)
            return []

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_grn_headers(self, grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if po_number:
                where = 'ponumber = %s'
                params = (po_number,)
            return [_norm_grn(r) for r in _query('grn_headers', where=where, params=params, limit=limit)]
        try:
            rows = self._get("receivingReceiptsTransactions", {"limit": limit})
            return [{"grn_number": r.get("ReceiptNumber"), "grn_date": r.get("ReceiptDate"),
                     "grn_status": "done"} for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_grn_headers failed: %s", e)
            return []

    # ── Accounts Payable ──────────────────────────────────────────────────────

    def get_vendor_invoices(self, invoice_no: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if invoice_no:
                where = 'invoicenumber = %s'
                params = (invoice_no,)
            return [_norm_invoice(r) for r in _query('invoices', where=where, params=params, limit=limit)]
        try:
            rows = self._get("invoices", {"limit": limit})
            return [self._map_invoice(r) for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_vendor_invoices failed: %s", e)
            return []

    def get_ap_aging(self) -> list:
        if self._use_demo:
            return self._pg().get_ap_aging()
        return []

    def get_payment_proposals(self, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_payment_proposals(limit=limit)
        return []

    # ── Finance ───────────────────────────────────────────────────────────────

    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        if self._use_demo:
            return self._pg().get_budget_vs_actuals(cost_center=cost_center)
        return []

    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        if self._use_demo:
            return [_norm_spend(r) for r in _query('spend', limit=limit)]
        return self.get_purchase_orders(limit=limit)

    def get_vendor_performance(self, vendor_id: str = None) -> list:
        if self._use_demo:
            return self._pg().get_vendor_performance(vendor_id=vendor_id)
        return []

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_status(self, item_code: str = None) -> list:
        if self._use_demo:
            return self._pg().get_inventory_status(item_code=item_code)
        try:
            rows = self._get("inventoryBalances", {"limit": 200})
            return [{"item_code": r.get("ItemNumber"), "total_received": r.get("OnHandQuantity"),
                     "reorder_point": r.get("MinimumOrderQuantity")} for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_inventory_status failed: %s", e)
            return []

    # ── System ────────────────────────────────────────────────────────────────

    def get_table_registry(self) -> list:
        from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter().get_table_registry()
