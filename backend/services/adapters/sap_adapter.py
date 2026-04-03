"""
SAPAdapter — reads from SAP S/4HANA via OData / RFC / BAPI,
             OR from ERP-specific PostgreSQL tables when SAP is not configured.

Activated by:  DATA_SOURCE=sap  or  DATA_SOURCE=sap_s4  in .env

Demo mode: When SAP_HOST is not set, queries vendors_sap_s4, po_headers_sap_s4,
           items_sap_s4, invoices_sap_s4, grn_headers_sap_s4, spend_sap_s4 tables.
Live mode: set SAP_HOST, SAP_CLIENT, SAP_USER, SAP_PASSWORD, SAP_SYSNR in .env
"""

import os
import logging
from decimal import Decimal
from backend.services.adapters.base_adapter import IDataSourceAdapter

logger = logging.getLogger(__name__)

_SUFFIX = 'sap_s4'


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
        logger.warning("[SAPAdapter] _query %s failed: %s", table, e)
        return []
    finally:
        if conn:
            conn.close()


def _norm_vendor(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('lifnr', '')),
        'vendor_name': r.get('name1', ''),
        'email': r.get('smtp_addr', ''),
        'phone': r.get('telf1', ''),
        'country': r.get('land1', ''),
        'city': r.get('ort01', ''),
        'status': 'Blocked' if r.get('sperr', ' ').strip() else 'Active',
        'payment_terms': r.get('zterm', ''),
        'credit_limit': None,
        'currency': r.get('waers', 'USD'),
    }


def _norm_item(r: dict) -> dict:
    return {
        'id': r.get('matnr', ''),
        'name': r.get('maktx', ''),
        'description': r.get('maktx', ''),
        'item_code': r.get('matnr', ''),
        'uom': r.get('meins', ''),
        'unit_cost': r.get('netpr', 0),
        'category': r.get('matkl', ''),
    }


def _norm_po(r: dict) -> dict:
    return {
        'id': r.get('ebeln', ''),
        'po_number': str(r.get('ebeln', '')),
        'vendor_id': r.get('lifnr', ''),
        'vendor_name': r.get('lifnr', ''),
        'total_amount': r.get('netwr', 0),
        'po_grand_total': r.get('netwr', 0),
        'currency': r.get('waers', 'USD'),
        'status': r.get('statu', ''),
        'po_status': r.get('statu', ''),
        'po_date': str(r.get('bedat', '')),
        'buyer': r.get('ekgrp', ''),
    }


def _norm_invoice(r: dict) -> dict:
    return {
        'id': r.get('belnr', ''),
        'invoice_number': r.get('belnr', ''),
        'invoice_no': r.get('belnr', ''),
        'vendor_id': r.get('lifnr', ''),
        'vendor_name': r.get('lifnr', ''),
        'total_amount': r.get('wrbtr', 0),
        'invoice_total': r.get('wrbtr', 0),
        'currency': r.get('waers', 'USD'),
        'status': r.get('shkzg', ''),
        'ap_status': r.get('shkzg', ''),
        'invoice_date': str(r.get('bldat', '')),
        'po_reference': r.get('ebeln', ''),
    }


def _norm_grn(r: dict) -> dict:
    return {
        'id': r.get('mblnr', ''),
        'grn_number': r.get('mblnr', ''),
        'po_reference': r.get('ebeln', ''),
        'vendor_name': r.get('lifnr', ''),
        'grn_date': str(r.get('budat', '')),
        'grn_status': 'done',
    }


def _norm_spend(r: dict) -> dict:
    return {
        'id': r.get('ebeln', ''),
        'vendor_name': r.get('lifnr', ''),
        'total_amount_usd': r.get('netwr', 0),
        'period': str(r.get('bedat', ''))[:7],
        'cost_center': r.get('kostl', ''),
        'currency': r.get('waers', 'USD'),
    }


class SAPAdapter(IDataSourceAdapter):
    """
    Reads from SAP S/4HANA.
    Uses pyrfc (SAP RFC connector) or OData REST API depending on configuration.
    All methods return dicts with the same column names as PostgreSQLAdapter.
    """

    def __init__(self):
        self.host     = os.environ.get("SAP_HOST")
        self.client   = os.environ.get("SAP_CLIENT", "100")
        self.user     = os.environ.get("SAP_USER")
        self.password = os.environ.get("SAP_PASSWORD")
        self.sysnr    = os.environ.get("SAP_SYSNR", "00")
        self._conn    = None
        self.name     = 'SAP S/4HANA'

    @property
    def _use_demo(self) -> bool:
        return not self.host

    def source_name(self) -> str:
        if self._use_demo:
            return "SAP S/4HANA (PostgreSQL demo tables)"
        return f"SAP S/4HANA ({self.host or 'not configured'})"

    def _connect(self):
        if self._conn:
            return
        try:
            import pyrfc
            self._conn = pyrfc.Connection(
                ashost=self.host, sysnr=self.sysnr,
                client=self.client, user=self.user, passwd=self.password
            )
            logger.info("SAPAdapter connected: %s", self.host)
        except Exception as e:
            logger.error("SAPAdapter connection failed: %s", e)
            raise

    def _call_bapi(self, bapi: str, **kwargs) -> dict:
        self._connect()
        return self._conn.call(bapi, **kwargs)

    # ── Helper: normalize SAP field names to our column names ─────────────────

    @staticmethod
    def _map_vendor(lfa1: dict) -> dict:
        return {
            'vendor_id':    lfa1.get('LIFNR'),
            'vendor_name':  lfa1.get('NAME1'),
            'country':      lfa1.get('LAND1'),
            'city':         lfa1.get('ORT01'),
            'active':       True,
        }

    @staticmethod
    def _map_po_header(ekko: dict) -> dict:
        return {
            'po_number':      ekko.get('EBELN'),
            'po_date':        ekko.get('BEDAT'),
            'vendor_id':      ekko.get('LIFNR'),
            'po_grand_total': ekko.get('NETWR'),
            'currency':       ekko.get('WAERS'),
            'po_status':      ekko.get('STATU'),
            'buyer':          ekko.get('EKGRP'),
        }

    @staticmethod
    def _map_po_line(ekpo: dict) -> dict:
        return {
            'po_number':        ekpo.get('EBELN'),
            'line_no':          ekpo.get('EBELP'),
            'item_code':        ekpo.get('MATNR'),
            'item_description': ekpo.get('TXZ01'),
            'qty_ordered':      ekpo.get('MENGE'),
            'uom':              ekpo.get('MEINS'),
            'line_unit_price':  ekpo.get('NETPR'),
            'line_total':       ekpo.get('NETWR'),
        }

    @staticmethod
    def _map_grn_header(mkpf: dict) -> dict:
        return {
            'grn_number': mkpf.get('MBLNR'),
            'grn_date':   mkpf.get('BUDAT'),
            'grn_status': 'done',
        }

    @staticmethod
    def _map_invoice(rbkpv: dict) -> dict:
        return {
            'invoice_no':    rbkpv.get('BELNR'),
            'invoice_date':  rbkpv.get('BLDAT'),
            'vendor_id':     rbkpv.get('LIFNR'),
            'invoice_total': rbkpv.get('RMWWR'),
            'currency':      rbkpv.get('WAERS'),
            'ap_status':     rbkpv.get('XBLNR'),
        }

    # ── Master Data ────────────────────────────────────────────────────────────

    def get_vendors(self, active_only: bool = True, limit: int = 200) -> list:
        if self._use_demo:
            where = "sperr = ' ' AND loevm = ' '" if active_only else ''
            return [_norm_vendor(r) for r in _query('vendors', where=where, limit=limit)]
        try:
            result = self._call_bapi('BAPI_VENDOR_GETLIST',
                VENDORSELECTION=[{'SIGN': 'I', 'OPTION': 'CP', 'LOWER_LIMIT': '*'}])
            vendors = result.get('VENDORLIST', [])
            return [self._map_vendor(v) for v in vendors[:limit]]
        except Exception as e:
            logger.error("SAPAdapter.get_vendors failed: %s", e)
            return []

    def get_items(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'matnr = %s'
                params = (item_code,)
            return [_norm_item(r) for r in _query('items', where=where, params=params)]
        try:
            matnr = item_code or '*'
            result = self._call_bapi('BAPI_MATERIAL_GETLIST',
                MATNRSELECTION=[{'SIGN': 'I', 'OPTION': 'CP', 'MATNR_LOW': matnr}])
            return [{'item_code': r.get('MATERIAL'), 'item_description': r.get('MATL_DESC'),
                     'category': r.get('MATL_TYPE')} for r in result.get('MATNRLIST', [])]
        except Exception as e:
            logger.error("SAPAdapter.get_items failed: %s", e)
            return []

    def get_cost_centers(self) -> list:
        if self._use_demo:
            return self._pg().get_cost_centers()
        try:
            result = self._call_bapi('BAPI_COSTCENTER_GETLIST1')
            return [{'cost_center_code': r.get('COSTCENTER'), 'cost_center_name': r.get('NAME')}
                    for r in result.get('COSTCENTERLIST', [])]
        except Exception as e:
            logger.error("SAPAdapter.get_cost_centers failed: %s", e)
            return []

    def get_exchange_rates(self) -> list:
        if self._use_demo:
            return self._pg().get_exchange_rates()
        try:
            result = self._call_bapi('BAPI_EXCHANGERATE_GETDETAIL')
            return [{'currency_code': r.get('FCURR'), 'rate': r.get('UKURS'), 'rate_date': r.get('GDATU')}
                    for r in result.get('EXCHANGERATELIST', [])]
        except Exception as e:
            logger.error("SAPAdapter.get_exchange_rates failed: %s", e)
            return []

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            return self._pg().get_purchase_requisitions(status=status, limit=limit)
        try:
            result = self._call_bapi('BAPI_REQUISITION_GETLIST')
            items = result.get('REQUISITIONLIST', [])
            return [{'pr_number': r.get('PREQ_NO'), 'item_code': r.get('MATERIAL'),
                     'qty_required': r.get('QUANTITY'), 'status': r.get('PREQ_STATUS')}
                    for r in items[:limit]]
        except Exception as e:
            logger.error("SAPAdapter.get_purchase_requisitions failed: %s", e)
            return []

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            return self._pg().get_approved_suppliers(item_code=item_code, category=category)
        return []  # SAP: fetch from EINE/EINA info records

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_rfq_headers(status=status, limit=limit)
        return self.get_purchase_orders(status='AN', limit=limit)

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_vendor_quotes(item_name=item_name, limit=limit)
        return []  # SAP: fetch from EKPO with document type AN

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_contracts(vendor_id=vendor_id, limit=limit)
        return self.get_purchase_orders(status='K', limit=limit)

    # ── Purchase Orders ────────────────────────────────────────────────────────

    def get_purchase_orders(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'statu = %s'
                params = (status,)
            return [_norm_po(r) for r in _query('po_headers', where=where, params=params, limit=limit)]
        try:
            result = self._call_bapi('BAPI_PO_GETITEMS',
                PURCHASEORDER='*', ITEMS=[], ITEMSELECTIONPARAM=[])
            headers = result.get('PO_HEADER_LIST', [])
            return [self._map_po_header(h) for h in headers[:limit]]
        except Exception as e:
            logger.error("SAPAdapter.get_purchase_orders failed: %s", e)
            return []

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_grn_headers(self, grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if po_number:
                where = 'ebeln = %s'
                params = (po_number,)
            elif grn_number:
                where = 'mblnr = %s'
                params = (grn_number,)
            return [_norm_grn(r) for r in _query('grn_headers', where=where, params=params, limit=limit)]
        try:
            result = self._call_bapi('BAPI_GOODSMVT_GETDETAIL',
                GOODSMVT_HEADER={'REF_DOC_NO': po_number or ''})
            return [self._map_grn_header(r) for r in result.get('GOODSMVT_ITEMS', [])[:limit]]
        except Exception as e:
            logger.error("SAPAdapter.get_grn_headers failed: %s", e)
            return []

    # ── Accounts Payable ──────────────────────────────────────────────────────

    def get_vendor_invoices(self, invoice_no: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if invoice_no:
                where = 'belnr = %s'
                params = (invoice_no,)
            return [_norm_invoice(r) for r in _query('invoices', where=where, params=params, limit=limit)]
        try:
            result = self._call_bapi('BAPI_INCOMINGINVOICE_GETLIST')
            invoices = result.get('INVOICELIST', [])
            return [self._map_invoice(r) for r in invoices[:limit]]
        except Exception as e:
            logger.error("SAPAdapter.get_vendor_invoices failed: %s", e)
            return []

    def get_ap_aging(self) -> list:
        if self._use_demo:
            return self._pg().get_ap_aging()
        return []  # SAP: fetch from FBL1N / BSIK

    def get_payment_proposals(self, limit: int = 50) -> list:
        if self._use_demo:
            return self._pg().get_payment_proposals(limit=limit)
        return []  # SAP: fetch from REGUH (F110 payment run)

    # ── Finance ───────────────────────────────────────────────────────────────

    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        if self._use_demo:
            return self._pg().get_budget_vs_actuals(cost_center=cost_center)
        try:
            result = self._call_bapi('BAPI_COSTCENTER_GETACTUALS1',
                COSTCENTER=cost_center or '', CONTROLLINGAREA='1000',
                FISCAL_YEAR='2025', PERIOD_FROM='001', PERIOD_TO='012')
            return [{'cost_center': r.get('COSTCENTER'), 'fy_actual': r.get('TOTAL_ACTUAL'),
                     'fy_budget': r.get('TOTAL_BUDGET')} for r in result.get('ACTUALDATALIST', [])]
        except Exception as e:
            logger.error("SAPAdapter.get_budget_vs_actuals failed: %s", e)
            return []

    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        if self._use_demo:
            return [_norm_spend(r) for r in _query('spend', limit=limit)]
        return self.get_purchase_orders(limit=limit)

    def get_vendor_performance(self, vendor_id: str = None) -> list:
        if self._use_demo:
            return self._pg().get_vendor_performance(vendor_id=vendor_id)
        return []  # SAP: fetch from LIS / vendor evaluation (ME61)

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_status(self, item_code: str = None) -> list:
        if self._use_demo:
            return self._pg().get_inventory_status(item_code=item_code)
        try:
            result = self._call_bapi('BAPI_MATERIAL_STOCK_REQ_LIST',
                MATERIAL=item_code or '', PLANT='1000')
            return [{'item_code': r.get('MATERIAL'), 'total_received': r.get('MMSTA'),
                     'reorder_point': r.get('MINBE')} for r in result.get('STOCKREQLIST', [])]
        except Exception as e:
            logger.error("SAPAdapter.get_inventory_status failed: %s", e)
            return []

    # ── System ────────────────────────────────────────────────────────────────

    def get_table_registry(self) -> list:
        from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter().get_table_registry()
