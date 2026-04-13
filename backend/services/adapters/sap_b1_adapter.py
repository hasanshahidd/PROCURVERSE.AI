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

_SUFFIX = 'sap'

# Map logical table names to actual CSV-imported table names in PostgreSQL
# SAP B1 uses the SAME underlying PostgreSQL tables as SAP S/4HANA
_TABLE_REMAP = {
    'vendors_sap':               'sap_vendor_general',
    'po_headers_sap':            'sap_purchase_orders',
    'items_sap':                 'sap_material_general',
    'invoices_sap':              'sap_invoice_headers',
    'grn_headers_sap':           'sap_purchase_orders',
    'spend_sap':                 'sap_purchase_orders',
    'cost_centers_sap':          'sap_cost_centers',
    'exchange_rates_sap':        'sap_company_codes',
    'purchase_requisitions_sap': 'sap_purchase_orders',
    'approved_suppliers_sap':    'sap_vendor_general',
    'rfq_headers_sap':           'sap_purchase_orders',
    'vendor_quotes_sap':         'sap_vendor_purchasing',
    'contracts_sap':             'sap_purchase_orders',
    'ap_aging_sap':              'sap_invoice_headers',
    'payment_proposals_sap':     'sap_invoice_headers',
    'budget_sap':                'sap_cost_centers',
    'vendor_performance_sap':    'sap_vendor_general',
    'inventory_sap':             'sap_material_storage',
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
        logger.warning("[SAPB1Adapter] _query %s failed: %s", table, e)
        return []
    finally:
        if conn:
            conn.close()


def _norm_vendor(r: dict) -> dict:
    # Try ERP-native columns first, then fall back to CSV column names
    name = r.get('cardname') or r.get('name1') or r.get('name') or r.get('vendor_name') or str(r.get('lifnr', ''))
    vid = r.get('cardcode') or r.get('lifnr') or r.get('vendor_id') or r.get('_row_id', '')
    return {
        'vendor_id': str(vid),
        'vendor_name': name or '',
        'name': name or '',
        'email': r.get('e_mail') or r.get('email') or r.get('smtp_addr') or '',
        'phone': r.get('phone1') or r.get('telf1') or r.get('phone') or '',
        'country': r.get('country') or r.get('land1', ''),
        'city': r.get('city') or r.get('ort01', ''),
        'status': 'Active' if r.get('valid', 'Y') == 'Y' else ('Blocked' if str(r.get('sperr', '') or '').strip() else 'Active'),
        'payment_terms': str(r.get('paytermgrpcode') or r.get('zterm', '')),
        'credit_limit': r.get('creditlimit', None),
        'currency': r.get('currency') or r.get('waers', 'USD'),
    }


def _norm_item(r: dict) -> dict:
    code = r.get('itemcode') or r.get('matnr', '')
    name = r.get('itemname') or r.get('maktx') or code
    return {
        'id': code,
        'name': name,
        'description': name,
        'item_code': code,
        'uom': r.get('invntryuom') or r.get('meins', ''),
        'unit_cost': r.get('lastpurprc') or r.get('netpr', 0),
        'category': str(r.get('itmsgrpcod') or r.get('matkl', '')),
    }


def _norm_po(r: dict) -> dict:
    po_id = r.get('docnum') or r.get('ebeln', '')
    return {
        'id': str(po_id),
        'po_number': str(po_id),
        'vendor_id': r.get('cardcode') or r.get('lifnr', ''),
        'vendor_name': r.get('cardname') or r.get('lifnr', ''),
        'total_amount': r.get('doctotal') or r.get('netwr', 0),
        'po_grand_total': r.get('doctotal') or r.get('netwr', 0),
        'currency': r.get('doccurrency') or r.get('waers', 'USD'),
        'status': r.get('status') or r.get('statu') or ('Open' if r.get('docstatus', 'O') == 'O' else 'Closed'),
        'po_status': r.get('status') or r.get('statu') or ('Open' if r.get('docstatus', 'O') == 'O' else 'Closed'),
        'po_date': str(r.get('docdate') or r.get('bedat', '')),
    }


def _norm_invoice(r: dict) -> dict:
    inv_id = r.get('docnum') or r.get('belnr', '')
    return {
        'id': str(inv_id),
        'invoice_number': str(inv_id),
        'invoice_no': str(inv_id),
        'vendor_id': r.get('cardcode') or r.get('lifnr', ''),
        'vendor_name': r.get('cardname') or r.get('lifnr', ''),
        'total_amount': r.get('doctotal') or r.get('wrbtr', 0),
        'invoice_total': r.get('doctotal') or r.get('wrbtr', 0),
        'currency': r.get('doccurrency') or r.get('waers', 'USD'),
        'status': r.get('status') or ('Open' if r.get('docstatus', 'O') == 'O' else 'Closed'),
        'ap_status': r.get('status') or ('Open' if r.get('docstatus', 'O') == 'O' else 'Closed'),
        'invoice_date': str(r.get('docdate') or r.get('bldat', '')),
        'po_reference': r.get('baseref') or r.get('ebeln', ''),
    }


def _norm_grn(r: dict) -> dict:
    grn_id = r.get('docnum') or r.get('mblnr') or r.get('ebeln', '')
    return {
        'id': str(grn_id),
        'grn_number': str(grn_id),
        'po_reference': r.get('baseref') or r.get('ebeln', ''),
        'vendor_name': r.get('cardname') or r.get('lifnr', ''),
        'grn_date': str(r.get('docdate') or r.get('budat', '')),
        'grn_status': 'Closed' if r.get('docstatus', 'C') == 'C' else 'done',
    }


def _norm_spend(r: dict) -> dict:
    return {
        'id': str(r.get('docnum') or r.get('ebeln', '')),
        'vendor_name': r.get('cardname') or r.get('lifnr', ''),
        'total_amount_usd': r.get('doctotal') or r.get('netwr', 0),
        'period': str(r.get('docdate') or r.get('bedat', ''))[:7],
        'cost_center': r.get('ocrcode') or r.get('kostl', ''),
        'currency': r.get('doccurrency') or r.get('waers', 'USD'),
    }


def _norm_cost_center(r: dict) -> dict:
    return {
        'cost_center_code': r.get('kostl', ''),
        'cost_center_name': r.get('ltext', ''),
        'controlling_area': r.get('kokrs', ''),
        'valid_from': str(r.get('datab', '')),
        'valid_to': str(r.get('datbi', '')),
        'category': r.get('kosar', ''),
        'responsible': r.get('verak', ''),
        'currency': r.get('waers', 'USD'),
    }


def _norm_exchange_rate(r: dict) -> dict:
    return {
        'currency_code': r.get('waers', ''),
        'company_code': r.get('bukrs', ''),
        'rate': 1.0,
        'rate_date': '',
    }


def _norm_pr(r: dict) -> dict:
    return {
        'pr_number': str(r.get('ebeln', '')),
        'item_code': '',
        'qty_required': r.get('netwr', 0),
        'status': r.get('status') or r.get('statu', ''),
        'vendor_id': r.get('lifnr', ''),
        'po_date': str(r.get('bedat', '')),
        'currency': r.get('waers', 'USD'),
    }


def _norm_approved_supplier(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('lifnr', '')),
        'vendor_name': r.get('name1', ''),
        'country': r.get('land1', ''),
        'city': r.get('ort01', ''),
        'email': r.get('email', ''),
        'phone': r.get('telf1', ''),
        'status': 'Approved',
    }


def _norm_rfq(r: dict) -> dict:
    return {
        'rfq_number': str(r.get('ebeln', '')),
        'vendor_id': r.get('lifnr', ''),
        'rfq_date': str(r.get('bedat', '')),
        'total_amount': r.get('netwr', 0),
        'currency': r.get('waers', 'USD'),
        'status': r.get('status') or r.get('statu', ''),
    }


def _norm_vendor_quote(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('lifnr', '')),
        'org': r.get('ekorg', ''),
        'currency': r.get('waers', 'USD'),
        'incoterm': r.get('inco1', ''),
        'payment_terms': r.get('zterm', ''),
    }


def _norm_contract(r: dict) -> dict:
    return {
        'contract_number': str(r.get('ebeln', '')),
        'vendor_id': r.get('lifnr', ''),
        'start_date': str(r.get('bedat', '')),
        'total_amount': r.get('netwr', 0),
        'currency': r.get('waers', 'USD'),
        'status': r.get('status') or r.get('statu', ''),
    }


def _norm_ap_aging(r: dict) -> dict:
    return {
        'invoice_number': r.get('belnr', ''),
        'vendor_id': r.get('lifnr', ''),
        'invoice_date': str(r.get('bldat', '')),
        'due_date': str(r.get('budat', '')),
        'amount': r.get('wrbtr', 0),
        'currency': r.get('waers', 'USD'),
        'status': r.get('status', ''),
        'company_code': r.get('bukrs', ''),
    }


def _norm_payment_proposal(r: dict) -> dict:
    return {
        'invoice_number': r.get('belnr', ''),
        'vendor_id': r.get('lifnr', ''),
        'amount': r.get('wrbtr', 0),
        'currency': r.get('waers', 'USD'),
        'due_date': str(r.get('budat', '')),
        'company_code': r.get('bukrs', ''),
        'status': r.get('status', ''),
    }


def _norm_budget(r: dict) -> dict:
    return {
        'cost_center': r.get('kostl', ''),
        'cost_center_name': r.get('ltext', ''),
        'controlling_area': r.get('kokrs', ''),
        'fy_budget': 0,
        'fy_actual': 0,
        'currency': r.get('waers', 'USD'),
    }


def _norm_vendor_perf(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('lifnr', '')),
        'vendor_name': r.get('name1', ''),
        'country': r.get('land1', ''),
        'email': r.get('email', ''),
        'phone': r.get('telf1', ''),
        'on_time_rate': None,
        'quality_score': None,
        'status': 'Active',
    }


def _norm_inventory(r: dict) -> dict:
    return {
        'item_code': r.get('matnr', ''),
        'plant': r.get('werks', ''),
        'storage_location': r.get('lgort', ''),
        'total_received': r.get('labst', 0),
        'reorder_point': 0,
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
            where = ''  # CSV data may not have SAP B1-specific filter columns
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
            return [_norm_cost_center(r) for r in _query('cost_centers')]
        try:
            rows = self._get("ProfitCenters")
            return [{"cost_center_code": r.get("CenterCode"), "cost_center_name": r.get("CenterName")}
                    for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_cost_centers failed: %s", e)
            return []

    def get_exchange_rates(self) -> list:
        if self._use_demo:
            return [_norm_exchange_rate(r) for r in _query('exchange_rates')]
        logger.info("[SAPB1Adapter] get_exchange_rates: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_exchange_rates()

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'status = %s'
                params = (status,)
            return [_norm_pr(r) for r in _query('purchase_requisitions', where=where, params=params, limit=limit)]
        logger.info("[SAPB1Adapter] get_purchase_requisitions: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_purchase_requisitions(status=status, limit=limit)

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            return [_norm_approved_supplier(r) for r in _query('approved_suppliers')]
        logger.info("[SAPB1Adapter] get_approved_suppliers: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_approved_suppliers(item_code=item_code, category=category)

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'status = %s'
                params = (status,)
            return [_norm_rfq(r) for r in _query('rfq_headers', where=where, params=params, limit=limit)]
        try:
            rows = self._get("PurchaseQuotations", {"$top": limit})
            return [self._map_po_header(r) for r in rows]
        except Exception as e:
            logger.error("SAPB1Adapter.get_rfq_headers failed: %s", e)
            return []

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return [_norm_vendor_quote(r) for r in _query('vendor_quotes', limit=limit)]
        logger.info("[SAPB1Adapter] get_vendor_quotes: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_vendor_quotes(item_name=item_name, limit=limit)

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where = 'lifnr = %s'
                params = (vendor_id,)
            return [_norm_contract(r) for r in _query('contracts', where=where, params=params, limit=limit)]
        logger.info("[SAPB1Adapter] get_contracts: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_contracts(vendor_id=vendor_id, limit=limit)

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
            return [_norm_ap_aging(r) for r in _query('ap_aging')]
        logger.info("[SAPB1Adapter] get_ap_aging: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_ap_aging()

    def get_payment_proposals(self, limit: int = 50) -> list:
        if self._use_demo:
            return [_norm_payment_proposal(r) for r in _query('payment_proposals', limit=limit)]
        logger.info("[SAPB1Adapter] get_payment_proposals: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_payment_proposals(limit=limit)

    # ── Finance ───────────────────────────────────────────────────────────────

    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if cost_center:
                where = 'kostl = %s'
                params = (cost_center,)
            return [_norm_budget(r) for r in _query('budget', where=where, params=params)]
        logger.info("[SAPB1Adapter] get_budget_vs_actuals: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_budget_vs_actuals(cost_center=cost_center)

    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        if self._use_demo:
            return [_norm_spend(r) for r in _query('spend', limit=limit)]
        return self.get_purchase_orders(limit=limit)

    def get_vendor_performance(self, vendor_id: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where = 'lifnr = %s'
                params = (vendor_id,)
            return [_norm_vendor_perf(r) for r in _query('vendor_performance', where=where, params=params)]
        logger.info("[SAPB1Adapter] get_vendor_performance: Service Layer not implemented, using PostgreSQL fallback")
        return self._pg().get_vendor_performance(vendor_id=vendor_id)

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_status(self, item_code: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'matnr = %s'
                params = (item_code,)
            return [_norm_inventory(r) for r in _query('inventory', where=where, params=params)]
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
