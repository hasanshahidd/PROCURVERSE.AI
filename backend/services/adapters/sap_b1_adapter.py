"""
SAPB1Adapter — reads from SAP Business One via Service Layer REST API,
               OR from ERP-specific PostgreSQL tables when SAP B1 is not configured.

Activated by:  DATA_SOURCE=sap_b1  in .env

Demo mode: When SAP_B1_URL is not set, queries vendors_sap_b1, po_headers_sap_b1,
           items_sap_b1, invoices_sap_b1, grn_headers_sap_b1, spend_sap_b1 tables.
Live mode: set SAP_B1_URL, SAP_B1_COMPANY, SAP_B1_USER, SAP_B1_PASSWORD in .env
"""

import os
import logging
from decimal import Decimal
from backend.services.adapters.base_adapter import IDataSourceAdapter

logger = logging.getLogger(__name__)

_SUFFIX = 'sap_b1'


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
        logger.warning("[SAPB1Adapter] _query %s failed: %s", table, e)
        return []
    finally:
        if conn:
            conn.close()


def _norm_vendor(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('cardcode', '')),
        'vendor_name': r.get('cardname', ''),
        'email': r.get('e_mail', ''),
        'phone': r.get('phone1', ''),
        'country': r.get('country', ''),
        'city': r.get('city', ''),
        'status': 'Active' if r.get('valid', 'Y') == 'Y' else 'Blocked',
        'payment_terms': str(r.get('paytermgrpcode', '')),
        'credit_limit': r.get('creditlimit', None),
        'currency': r.get('currency', 'USD'),
    }


def _norm_item(r: dict) -> dict:
    return {
        'id': r.get('itemcode', ''),
        'name': r.get('itemname', ''),
        'description': r.get('itemname', ''),
        'item_code': r.get('itemcode', ''),
        'uom': r.get('invntryuom', ''),
        'unit_cost': r.get('lastpurprc', 0),
        'category': str(r.get('itmsgrpcod', '')),
    }


def _norm_po(r: dict) -> dict:
    return {
        'id': str(r.get('docnum', '')),
        'po_number': str(r.get('docnum', '')),
        'vendor_id': r.get('cardcode', ''),
        'vendor_name': r.get('cardname', ''),
        'total_amount': r.get('doctotal', 0),
        'po_grand_total': r.get('doctotal', 0),
        'currency': r.get('doccurrency', 'USD'),
        'status': 'Open' if r.get('docstatus', 'O') == 'O' else 'Closed',
        'po_status': 'Open' if r.get('docstatus', 'O') == 'O' else 'Closed',
        'po_date': str(r.get('docdate', '')),
    }


def _norm_invoice(r: dict) -> dict:
    return {
        'id': str(r.get('docnum', '')),
        'invoice_number': str(r.get('docnum', '')),
        'invoice_no': str(r.get('docnum', '')),
        'vendor_id': r.get('cardcode', ''),
        'vendor_name': r.get('cardname', ''),
        'total_amount': r.get('doctotal', 0),
        'invoice_total': r.get('doctotal', 0),
        'currency': r.get('doccurrency', 'USD'),
        'status': 'Open' if r.get('docstatus', 'O') == 'O' else 'Closed',
        'ap_status': 'Open' if r.get('docstatus', 'O') == 'O' else 'Closed',
        'invoice_date': str(r.get('docdate', '')),
        'po_reference': r.get('baseref', ''),
    }


def _norm_grn(r: dict) -> dict:
    return {
        'id': str(r.get('docnum', '')),
        'grn_number': str(r.get('docnum', '')),
        'po_reference': r.get('baseref', ''),
        'vendor_name': r.get('cardname', ''),
        'grn_date': str(r.get('docdate', '')),
        'grn_status': 'Closed' if r.get('docstatus', 'C') == 'C' else 'Open',
    }


def _norm_spend(r: dict) -> dict:
    return {
        'id': str(r.get('docnum', '')),
        'vendor_name': r.get('cardname', ''),
        'total_amount_usd': r.get('doctotal', 0),
        'period': str(r.get('docdate', ''))[:7],
        'cost_center': r.get('ocrcode', ''),
        'currency': r.get('doccurrency', 'USD'),
    }


class SAPB1Adapter(IDataSourceAdapter):
    """
    Reads from SAP Business One via Service Layer REST API.
    Returns dicts with the same neutral column names as PostgreSQLAdapter.
    """

    def __init__(self):
        self.base_url = os.environ.get("SAP_B1_URL")           # e.g. https://b1-host:50000/b1s/v1
        self.company  = os.environ.get("SAP_B1_COMPANY", "SBODemoUS")
        self.user     = os.environ.get("SAP_B1_USER")
        self.password = os.environ.get("SAP_B1_PASSWORD")
        self._session_id = None
        self.name     = 'SAP B1'

    @property
    def _use_demo(self) -> bool:
        return not self.base_url

    def source_name(self) -> str:
        if self._use_demo:
            return "SAP Business One (PostgreSQL demo tables)"
        return f"SAP Business One ({self.base_url or 'not configured'})"

    def _login(self):
        if self._session_id:
            return
        try:
            import requests
            r = requests.post(
                f"{self.base_url}/Login",
                json={"CompanyDB": self.company, "UserName": self.user, "Password": self.password},
                verify=False, timeout=10
            )
            r.raise_for_status()
            self._session_id = r.json().get("SessionId")
        except Exception as e:
            logger.error("SAPB1Adapter login failed: %s", e)
            raise

    def _get(self, endpoint: str, params: dict = None) -> list:
        self._login()
        try:
            import requests
            r = requests.get(
                f"{self.base_url}/{endpoint}",
                headers={"Cookie": f"B1SESSION={self._session_id}"},
                params=params or {},
                verify=False, timeout=15
            )
            r.raise_for_status()
            return r.json().get("value", [])
        except Exception as e:
            logger.error("SAPB1Adapter GET %s failed: %s", endpoint, e)
            return []

    # ── Field mappers ──────────────────────────────────────────────────────────

    @staticmethod
    def _map_vendor(bp: dict) -> dict:
        return {
            "vendor_id":   bp.get("CardCode"),
            "vendor_name": bp.get("CardName"),
            "country":     bp.get("Country"),
            "city":        bp.get("City"),
            "active":      bp.get("Valid") == "tYES",
        }

    @staticmethod
    def _map_po_header(doc: dict) -> dict:
        return {
            "po_number":      str(doc.get("DocNum")),
            "po_date":        doc.get("DocDate"),
            "vendor_id":      doc.get("CardCode"),
            "po_grand_total": doc.get("DocTotal"),
            "currency":       doc.get("DocCurrency"),
            "po_status":      doc.get("DocumentStatus"),
        }

    @staticmethod
    def _map_invoice(doc: dict) -> dict:
        return {
            "invoice_no":    str(doc.get("DocNum")),
            "invoice_date":  doc.get("DocDate"),
            "vendor_id":     doc.get("CardCode"),
            "invoice_total": doc.get("DocTotal"),
            "currency":      doc.get("DocCurrency"),
            "ap_status":     doc.get("DocumentStatus"),
        }

    # ── Master Data ────────────────────────────────────────────────────────────

    def get_vendors(self, active_only: bool = True, limit: int = 200) -> list:
        if self._use_demo:
            where = "valid = 'Y'" if active_only else ''
            return [_norm_vendor(r) for r in _query('vendors', where=where, limit=limit)]
        try:
            q = "$filter=CardType eq 'S'"
            if active_only:
                q += " and Valid eq 'tYES'"
            rows = self._get("BusinessPartners", {"$filter": q.replace("$filter=", ""), "$top": limit})
            return [self._map_vendor(r) for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_vendors failed: %s", e)
            return []

    def get_items(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'itemcode = %s'
                params = (item_code,)
            return [_norm_item(r) for r in _query('items', where=where, params=params)]
        try:
            rows = self._get("Items", {"$top": 200})
            return [{"item_code": r.get("ItemCode"), "item_description": r.get("ItemName"),
                     "category": r.get("ItemsGroupCode")} for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_items failed: %s", e)
            return []

    def get_cost_centers(self) -> list:
        if self._use_demo:
            return self._pg().get_cost_centers()
        try:
            rows = self._get("ProfitCenters")
            return [{"cost_center_code": r.get("CenterCode"), "cost_center_name": r.get("CenterName")}
                    for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_cost_centers failed: %s", e)
            return []

    def get_exchange_rates(self) -> list:
        if self._use_demo:
            return self._pg().get_exchange_rates()
        return []

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            return self._pg().get_purchase_requisitions(status=status, limit=limit)
        return []  # SAP B1: PurchaseQuotations or custom UDO

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            return self._pg().get_approved_suppliers(item_code=item_code, category=category)
        return []

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_rfq_headers(status=status, limit=limit)
        try:
            rows = self._get("PurchaseQuotations", {"$top": limit})
            return [self._map_po_header(r) for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_rfq_headers failed: %s", e)
            return []

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_vendor_quotes(item_name=item_name, limit=limit)
        return []

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_contracts(vendor_id=vendor_id, limit=limit)
        return []

    # ── Purchase Orders ────────────────────────────────────────────────────────

    def get_purchase_orders(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'docstatus = %s'
                params = (status,)
            return [_norm_po(r) for r in _query('po_headers', where=where, params=params, limit=limit)]
        try:
            rows = self._get("PurchaseOrders", {"$top": limit})
            return [self._map_po_header(r) for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_purchase_orders failed: %s", e)
            return []

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_grn_headers(self, grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if po_number:
                where = 'baseref = %s'
                params = (po_number,)
            return [_norm_grn(r) for r in _query('grn_headers', where=where, params=params, limit=limit)]
        try:
            rows = self._get("GoodsReceiptPO", {"$top": limit})
            return [{"grn_number": str(r.get("DocNum")), "grn_date": r.get("DocDate"),
                     "grn_status": "done"} for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_grn_headers failed: %s", e)
            return []

    # ── Accounts Payable ──────────────────────────────────────────────────────

    def get_vendor_invoices(self, invoice_no: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if invoice_no:
                where = 'docnum = %s'
                params = (invoice_no,)
            return [_norm_invoice(r) for r in _query('invoices', where=where, params=params, limit=limit)]
        try:
            rows = self._get("PurchaseInvoices", {"$top": limit})
            return [self._map_invoice(r) for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_vendor_invoices failed: %s", e)
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
            params = {"$top": 200}
            if item_code:
                params["$filter"] = f"ItemCode eq '{item_code}'"
            rows = self._get("Items", params)
            return [{"item_code": r.get("ItemCode"), "total_received": r.get("QuantityOnStock"),
                     "reorder_point": r.get("MinInventory")} for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_inventory_status failed: %s", e)
            return []

    # ── System ────────────────────────────────────────────────────────────────

    def get_table_registry(self) -> list:
        from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter().get_table_registry()
