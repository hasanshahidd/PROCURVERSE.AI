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

_TABLE_REMAP = {
    'vendors_oracle':              'oracle_suppliers',
    'po_headers_oracle':           'oracle_purchase_orders',
    'items_oracle':                'oracle_items',
    'invoices_oracle':             'oracle_invoices',
    'grn_headers_oracle':          'oracle_purchase_orders',
    'spend_oracle':                'oracle_purchase_orders',
    'cost_centers_oracle':         'oracle_cost_centers',
    'exchange_rates_oracle':       'oracle_currencies',
    'purchase_requisitions_oracle':'oracle_purchase_orders',
    'approved_suppliers_oracle':   'oracle_suppliers',
    'rfq_headers_oracle':          'oracle_purchase_orders',
    'vendor_quotes_oracle':        'oracle_supplier_contacts',
    'contracts_oracle':            'oracle_purchase_orders',
    'ap_aging_oracle':             'oracle_invoices',
    'payment_proposals_oracle':    'oracle_invoices',
    'budget_oracle':               'oracle_business_units',
    'vendor_performance_oracle':   'oracle_suppliers',
    'inventory_oracle':            'oracle_items',
    'gl_accounts_oracle':          'oracle_gl_accounts',
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
            # Sprint D / Oracle-focus (2026-04-11): explicit trace so every live
            # Oracle read is visible in backend logs during P2P runs. Tagged with
            # [ADAPTER-CALL] so it can be grep'd out of noisy logs.
            logger.info(
                "[ADAPTER-CALL] OracleAdapter _query table=%s where=%s params=%s -> %d rows",
                table, where or "-", params or "-", len(rows),
            )
            return [{k: float(v) if isinstance(v, Decimal) else v
                     for k, v in dict(r).items()} for r in rows]
    except Exception as e:
        logger.warning("[OracleAdapter] _query %s failed: %s", table, e)
        return []
    finally:
        if conn:
            conn.close()


def _norm_vendor(r: dict) -> dict:
    # Sprint D / Oracle-focus fix (2026-04-11): real oracle_suppliers schema uses
    # snake_case (vendor_name, vendor_number, enabled_flag, country_code). Keep
    # camelCase fallbacks for REST responses but do not silently drop data.
    name = (r.get('vendor_name') or r.get('suppliername') or r.get('supplier_name')
            or r.get('name') or '')
    # oracle_suppliers uses vendor_id='SUP100001' as the business key and
    # vendor_number='10001' as the internal sequence — keep vendor_id first.
    vid = (r.get('vendor_id') or r.get('suppliernumber') or r.get('supplier_number')
           or r.get('vendor_number') or r.get('_row_id', ''))
    return {
        'vendor_id': str(vid),
        'vendor_name': name,
        'name': name,
        'email': r.get('email') or r.get('email_address') or '',
        'phone': r.get('phone') or r.get('phone_number') or '',
        'country': r.get('country_code') or r.get('countryoforigin') or '',
        'city': r.get('city', ''),
        # Accept Y or missing as Active; anything else (N / INVALID_* / None) → Disabled.
        'status': 'Active' if (r.get('enabled_flag') or r.get('enabledflag') or 'Y') == 'Y' else 'Disabled',
        'payment_terms': r.get('pay_group_lookup_code') or r.get('paymentterms') or '',
        'credit_limit': None,
        'currency': r.get('payment_currency_code') or r.get('defaultcurrency') or 'USD',
    }


def _norm_item(r: dict) -> dict:
    # oracle_items columns: item_number, description, unit_of_measure, unit_cost, ...
    code = r.get('item_number') or r.get('itemnumber') or ''
    desc = r.get('description') or r.get('itemdescription') or ''
    return {
        'id': code,
        'name': desc,
        'description': desc,
        'item_code': code,
        'uom': r.get('unit_of_measure') or r.get('uomcode') or '',
        'unit_cost': r.get('unit_cost') or r.get('listprice') or 0,
        'category': r.get('item_type') or r.get('category') or '',
    }


def _norm_po(r: dict) -> dict:
    # oracle_purchase_orders columns: po_number, vendor_id, amount, status,
    # currency_code, creation_date, approved_date, ...
    po_no = r.get('po_number') or r.get('ponumber') or ''
    return {
        'id': po_no,
        'po_number': str(po_no),
        'vendor_id': r.get('vendor_id') or r.get('suppliernumber') or '',
        'vendor_name': r.get('vendor_name') or r.get('suppliername') or '',
        'total_amount': r.get('amount', 0),
        'po_grand_total': r.get('amount', 0),
        'currency': r.get('currency_code') or r.get('currencycode') or 'USD',
        'status': r.get('status', ''),
        'po_status': r.get('status', ''),
        'po_date': str(r.get('creation_date') or r.get('orderdate') or ''),
        'buyer': r.get('buyer') or r.get('buyername') or '',
    }


def _norm_invoice(r: dict) -> dict:
    # oracle_invoices columns: invoice_number, vendor_id, invoice_amount,
    # currency_code, status, invoice_date, ...
    inv_no = r.get('invoice_number') or r.get('invoicenumber') or ''
    return {
        'id': inv_no,
        'invoice_number': inv_no,
        'invoice_no': inv_no,
        'vendor_id': r.get('vendor_id') or r.get('suppliernumber') or '',
        'vendor_name': r.get('vendor_name') or r.get('suppliername') or '',
        'total_amount': r.get('invoice_amount') or r.get('invoiceamount') or 0,
        'invoice_total': r.get('invoice_amount') or r.get('invoiceamount') or 0,
        'currency': r.get('currency_code') or r.get('currencycode') or 'USD',
        'status': r.get('status') or r.get('paymentstatus') or '',
        'ap_status': r.get('status') or r.get('paymentstatus') or '',
        'invoice_date': str(r.get('invoice_date') or r.get('invoicedate') or ''),
        'po_reference': r.get('po_number') or r.get('ponumber') or '',
    }


def _norm_grn(r: dict) -> dict:
    # GRN headers are served from oracle_purchase_orders in the demo remap.
    return {
        'id': r.get('receipt_number') or r.get('receiptnumber') or r.get('po_number') or '',
        'grn_number': r.get('receipt_number') or r.get('receiptnumber') or r.get('po_number') or '',
        'po_reference': r.get('po_number') or r.get('ponumber') or '',
        'vendor_name': r.get('vendor_name') or r.get('suppliername') or '',
        'grn_date': str(r.get('receipt_date') or r.get('creation_date') or r.get('receiptdate') or ''),
        'grn_status': r.get('receipt_status') or r.get('receiptstatus') or 'DELIVERED',
    }


def _norm_spend(r: dict) -> dict:
    # Spend rows are derived from oracle_purchase_orders in the demo remap.
    return {
        'id': r.get('po_number') or r.get('ponumber') or '',
        'vendor_name': r.get('vendor_name') or r.get('suppliername') or '',
        'total_amount_usd': r.get('amount', 0),
        'period': str(r.get('creation_date') or r.get('orderdate') or '')[:7],
        'cost_center': r.get('cost_center') or r.get('costcenter') or '',
        'currency': r.get('currency_code') or r.get('currencycode') or 'USD',
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
        # Sprint D / Oracle-focus (2026-04-11): explicit startup trace so the
        # console shows which adapter the running backend is bound to. Tagged
        # [ADAPTER-BOOT] for easy grep.
        mode = "DEMO (PostgreSQL oracle_* tables)" if not self.base_url else f"LIVE ({self.base_url})"
        logger.info("[ADAPTER-BOOT] OracleAdapter activated: mode=%s", mode)

    @property
    def _use_demo(self) -> bool:
        return not self.base_url

    def source_name(self) -> str:
        if self._use_demo:
            return "Oracle Fusion Cloud (PostgreSQL demo tables)"
        return f"Oracle Fusion Cloud ({self.base_url or 'not configured'})"

    def _pg(self):
        """Lazy PostgreSQL fallback adapter.

        Used by methods that don't yet read from oracle_* tables (e.g.
        cost centers, exchange rates, vendor performance). Those calls are
        still served from the demo DB but through the generic PG tables.
        Logged distinctly so operators can tell PG-fallback from native
        oracle_* reads.
        """
        from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
        if not hasattr(self, '_pg_adapter'):
            self._pg_adapter = PostgreSQLAdapter()
            logger.info(
                "[ADAPTER-BOOT] OracleAdapter: PG fallback adapter created "
                "(cost_centers / exchange_rates / vendor_performance / etc. "
                "will read from generic PG tables until Oracle-specific tables land)"
            )
        return self._pg_adapter

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
            where = ''  # CSV data uses enabled_flag not enabledflag
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
            return [{'cost_center_code': r.get('cost_center_code', ''),
                     'cost_center_name': r.get('cost_center_name', ''),
                     'department': r.get('department', ''),
                     'manager': r.get('manager_name', '')}
                    for r in _query('cost_centers')]
        logger.info("[OracleAdapter] get_cost_centers: REST API not implemented, using PostgreSQL fallback")
        return self._pg().get_cost_centers()

    def get_exchange_rates(self) -> list:
        if self._use_demo:
            return [{'currency_code': r.get('currency_code', ''),
                     'currency_name': r.get('name', ''),
                     'rate': r.get('precision', 1.0)}
                    for r in _query('exchange_rates') if r.get('enabled_flag', 'Y') == 'Y']
        logger.info("[OracleAdapter] get_exchange_rates: REST API not implemented, using PostgreSQL fallback")
        return self._pg().get_exchange_rates()

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = "status = %s"
                params = (status,)
            rows = _query('purchase_requisitions', where=where, params=params, limit=limit)
            return [{'pr_number': r.get('po_number', ''), 'status': r.get('status', ''),
                     'vendor_id': r.get('vendor_id', ''), 'total_amount': r.get('amount', 0),
                     'currency': r.get('currency_code', 'USD'),
                     'creation_date': str(r.get('creation_date', ''))}
                    for r in rows]
        try:
            rows = self._get("purchaseRequisitions", {"limit": limit})
            return [{"pr_number": r.get("RequisitionNumber"), "status": r.get("Status")} for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_purchase_requisitions failed: %s", e)
            return []

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            rows = _query('approved_suppliers')
            return [{'vendor_id': r.get('vendor_id', ''), 'vendor_name': r.get('vendor_name', ''),
                     'email': r.get('email', ''), 'status': 'Active'
                     if r.get('enabled_flag', 'Y') == 'Y' else 'Disabled'}
                    for r in rows if r.get('enabled_flag', 'Y') == 'Y']
        logger.info("[OracleAdapter] get_approved_suppliers: REST API not implemented, using PostgreSQL fallback")
        return self._pg().get_approved_suppliers(item_code=item_code, category=category)

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = "status = %s"
                params = (status,)
            rows = _query('rfq_headers', where=where, params=params, limit=limit)
            return [{'rfq_number': r.get('po_number', ''), 'status': r.get('status', ''),
                     'vendor_id': r.get('vendor_id', ''), 'amount': r.get('amount', 0)}
                    for r in rows]
        try:
            rows = self._get("negotiationHeaders", {"limit": limit})
            return [{"rfq_number": r.get("NegotiationNumber"), "status": r.get("Status")} for r in rows]
        except Exception as e:
            logger.error("OracleAdapter.get_rfq_headers failed: %s", e)
            return []

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        if self._use_demo:
            rows = _query('vendor_quotes', limit=limit)
            return [{'vendor_id': r.get('vendor_id', ''), 'vendor_name': str(r.get('first_name', '')),
                     'contact_email': r.get('email_address', ''), 'phone': r.get('phone', '')}
                    for r in rows]
        logger.info("[OracleAdapter] get_vendor_quotes: REST API not implemented, using PostgreSQL fallback")
        return self._pg().get_vendor_quotes(item_name=item_name, limit=limit)

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where = "vendor_id = %s"
                params = (vendor_id,)
            rows = _query('contracts', where=where, params=params, limit=limit)
            return [{'contract_number': r.get('po_number', ''), 'vendor_id': r.get('vendor_id', ''),
                     'status': r.get('status', ''), 'amount': r.get('amount', 0),
                     'currency': r.get('currency_code', 'USD')}
                    for r in rows]
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
            rows = _query('ap_aging')
            return [{'invoice_number': r.get('invoice_number', ''), 'vendor_id': r.get('vendor_id', ''),
                     'invoice_date': str(r.get('invoice_date', '')),
                     'invoice_amount': r.get('invoice_amount', 0),
                     'currency': r.get('currency_code', 'USD'),
                     'status': r.get('payment_status', r.get('status', ''))}
                    for r in rows]
        logger.info("[OracleAdapter] get_ap_aging: REST API not implemented, using PostgreSQL fallback")
        return self._pg().get_ap_aging()

    def get_payment_proposals(self, limit: int = 50) -> list:
        if self._use_demo:
            rows = _query('payment_proposals', limit=limit)
            return [{'invoice_number': r.get('invoice_number', ''), 'vendor_id': r.get('vendor_id', ''),
                     'amount': r.get('invoice_amount', 0), 'currency': r.get('currency_code', 'USD'),
                     'due_date': str(r.get('due_date', r.get('invoice_date', '')))}
                    for r in rows]
        logger.info("[OracleAdapter] get_payment_proposals: REST API not implemented, using PostgreSQL fallback")
        return self._pg().get_payment_proposals(limit=limit)

    # ── Finance ───────────────────────────────────────────────────────────────

    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if cost_center:
                where = "short_code = %s"
                params = (cost_center,)
            rows = _query('budget', where=where, params=params)
            return [{'cost_center': r.get('short_code', r.get('business_unit_name', '')),
                     'budget_name': r.get('business_unit_name', ''),
                     'currency': r.get('default_currency', 'USD'),
                     'status': r.get('status', '')}
                    for r in rows]
        logger.info("[OracleAdapter] get_budget_vs_actuals: REST API not implemented, using PostgreSQL fallback")
        return self._pg().get_budget_vs_actuals(cost_center=cost_center)

    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        if self._use_demo:
            return [_norm_spend(r) for r in _query('spend', limit=limit)]
        return self.get_purchase_orders(limit=limit)

    def get_vendor_performance(self, vendor_id: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where = "vendor_id = %s"
                params = (vendor_id,)
            rows = _query('vendor_performance', where=where, params=params)
            return [_norm_vendor(r) for r in rows]
        logger.info("[OracleAdapter] get_vendor_performance: REST API not implemented, using PostgreSQL fallback")
        return self._pg().get_vendor_performance(vendor_id=vendor_id)

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_status(self, item_code: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = "item_number = %s"
                params = (item_code,)
            rows = _query('inventory', where=where, params=params)
            return [{'item_code': r.get('item_number', ''), 'description': r.get('description', ''),
                     'unit_cost': r.get('unit_cost', 0), 'uom': r.get('unit_of_measure', '')}
                    for r in rows]
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
