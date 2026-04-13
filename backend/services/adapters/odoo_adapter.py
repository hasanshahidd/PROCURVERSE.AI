"""
OdooAdapter — reads from live Odoo ERP via XML-RPC,
              OR from ERP-specific PostgreSQL tables when Odoo is not configured.

Activated by:  DATA_SOURCE=odoo  in .env
Field mapping: uses table_registry (odoo_model + odoo_key_field columns)

Demo mode: When ODOO_URL is not set, queries odoo_partners, odoo_products,
           odoo_purchase_orders, odoo_invoices, odoo_warehouses, etc.
           in PostgreSQL (seeded from CSV test data).
Live mode: set ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD in .env
"""

import os
import logging
from decimal import Decimal
from backend.services.adapters.base_adapter import IDataSourceAdapter

logger = logging.getLogger(__name__)

_SUFFIX = 'odoo'

# Map old logical table names to new CSV-based table names
_ODOO_TABLE_MAP = {
    'vendors':                'odoo_partners',
    'items':                  'odoo_products',
    'po_headers':             'odoo_purchase_orders',
    'invoices':               'odoo_invoices',
    'grn_headers':            'odoo_warehouses',
    'spend':                  'odoo_sale_orders',
    'cost_centers':           'odoo_companies',
    'purchase_requisitions':  'odoo_purchase_orders',
    'approved_supplier_list': 'odoo_partners',
    'contracts':              'odoo_partners',
    'exchange_rates':         'odoo_currencies',
    'warehouses':             'odoo_warehouses',
    'payment_terms':          'odoo_payment_terms',
    'taxes':                  'odoo_taxes',
    'employees':              'odoo_employees',
    'gl_accounts':            'odoo_chart_of_accounts',
    'ap_aging':               'odoo_invoices',
    'payment_proposals':      'odoo_invoices',
    'budget':                 'odoo_companies',
    'vendor_performance':     'odoo_partners',
    'inventory':              'odoo_locations',
    'rfq_headers':            'odoo_purchase_orders',
    'vendor_quotes':          'odoo_purchase_orders',
}


def _query(table_base: str, where: str = '', params: tuple = (), limit: int = 500) -> list:
    """Query an Odoo-specific PostgreSQL table, returning list of dicts."""
    from backend.services.nmi_data_service import get_conn
    from psycopg2.extras import RealDictCursor
    # Use new CSV table mapping, fallback to old pattern
    table = _ODOO_TABLE_MAP.get(table_base, f'{table_base}_{_SUFFIX}')
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
        logger.warning("[OdooAdapter] _query %s failed: %s", table, e)
        return []
    finally:
        if conn:
            conn.close()


def _norm_vendor(r: dict) -> dict:
    return {
        'vendor_id': str(r.get('id', '')),
        'vendor_name': r.get('name', ''),
        'email': r.get('email', ''),
        'phone': r.get('phone', ''),
        'country': r.get('country_id', ''),
        'city': r.get('city', ''),
        'status': 'Active' if r.get('active', True) else 'Blocked',
        'payment_terms': r.get('property_supplier_payment_term_id', ''),
        'credit_limit': None,
        'vat': r.get('vat', ''),
        'currency': r.get('currency_id', 'USD'),
    }


def _norm_item(r: dict) -> dict:
    return {
        'id': r.get('id', ''),
        'name': r.get('name', ''),
        'description': r.get('description_purchase', r.get('name', '')),
        'item_code': r.get('default_code', ''),
        'uom': r.get('uom_id', ''),
        'unit_cost': r.get('standard_price', 0),
        'category': r.get('categ_id', ''),
    }


def _norm_po(r: dict) -> dict:
    return {
        'id': r.get('id', ''),
        'po_number': r.get('name', ''),
        'vendor_id': r.get('partner_id', ''),
        'vendor_name': r.get('partner_id', ''),
        'total_amount': r.get('amount_total', 0),
        'po_grand_total': r.get('amount_total', 0),
        'currency': r.get('currency_id', 'USD'),
        'status': r.get('state', ''),
        'po_status': r.get('state', ''),
        'po_date': str(r.get('date_order', '')),
        'buyer': r.get('user_id', ''),
    }


def _norm_invoice(r: dict) -> dict:
    return {
        'id': r.get('id', ''),
        'invoice_number': r.get('name', ''),
        'invoice_no': r.get('name', ''),
        'vendor_id': r.get('partner_id', ''),
        'vendor_name': r.get('partner_id', ''),
        'total_amount': r.get('amount_total', 0),
        'invoice_total': r.get('amount_total', 0),
        'currency': r.get('currency_id', 'USD'),
        'status': r.get('payment_state', r.get('state', '')),
        'ap_status': r.get('payment_state', r.get('state', '')),
        'invoice_date': str(r.get('invoice_date', '')),
        'po_reference': r.get('invoice_origin', ''),
        'amount_residual': r.get('amount_residual', 0),
    }


def _norm_grn(r: dict) -> dict:
    return {
        'id': r.get('id', ''),
        'grn_number': r.get('name', ''),
        'po_reference': r.get('origin', ''),
        'vendor_name': r.get('partner_id', ''),
        'grn_date': str(r.get('scheduled_date', r.get('date_done', ''))),
        'grn_status': r.get('state', ''),
    }


def _norm_spend(r: dict) -> dict:
    return {
        'id': r.get('id', ''),
        'vendor_name': r.get('partner_id', ''),
        'total_amount_usd': r.get('amount_total', 0),
        'period': str(r.get('date_approve', ''))[:7],
        'cost_center': r.get('x_department', ''),
        'currency': r.get('currency_id', 'USD'),
    }

# Odoo field name mappings (PostgreSQL column → Odoo field)
# Source of truth: table_registry.odoo_model / odoo_key_field
FIELD_MAP = {
    # Vendors  (res.partner)
    "vendor_id":       "id",
    "vendor_name":     "name",
    "active":          "active",
    "vendor_rating":   "supplier_rank",
    "payment_terms":   "property_supplier_payment_term_id",
    "country":         "country_id",

    # Purchase Orders  (purchase.order)
    "po_number":       "name",
    "po_date":         "date_order",
    "po_grand_total":  "amount_total",
    "po_status":       "state",
    "vendor_name":     "partner_id",
    "buyer":           "user_id",

    # PO Lines  (purchase.order.line)
    "item_description":"name",
    "qty_ordered":     "product_qty",
    "unit_price":      "price_unit",
    "line_total":      "price_subtotal",

    # Invoices  (account.move)
    "invoice_no":      "name",
    "invoice_date":    "invoice_date",
    "invoice_total":   "amount_total",
    "ap_status":       "payment_state",
    "po_reference":    "invoice_origin",

    # GRN  (stock.picking)
    "grn_number":      "name",
    "grn_date":        "scheduled_date",
    "po_reference":    "origin",
    "grn_status":      "state",

    # Items  (product.product)
    "item_code":       "default_code",
    "item_description":"name",
    "reorder_point":   "reordering_rule_minimum_qty",

    # Budget  (crossovered.budget.lines)
    "cost_center":     "analytic_account_id",
    "fy_budget":       "planned_amount",
    "fy_actual":       "practical_amount",
}


class OdooAdapter(IDataSourceAdapter):
    """
    Reads from live Odoo 17 via XML-RPC.
    Falls back to Odoo-specific PostgreSQL tables when ODOO_URL is not set.
    All methods map Odoo fields back to the same column names that
    PostgreSQLAdapter returns — agents see no difference.
    """

    def __init__(self):
        self.url      = os.environ.get("ODOO_URL")
        self.db       = os.environ.get("ODOO_DB")
        self.user     = os.environ.get("ODOO_USER")
        self.password = os.environ.get("ODOO_PASSWORD")
        self._uid     = None
        self._models  = None
        self.name     = 'Odoo'

    @property
    def _use_demo(self) -> bool:
        """True when in demo mode OR live Odoo is not configured."""
        data_source = os.environ.get("DATA_SOURCE", "").lower()
        if data_source.startswith("demo_"):
            return True  # demo mode = always use PostgreSQL tables
        return not self.url

    def source_name(self) -> str:
        if self._use_demo:
            return "Odoo (PostgreSQL demo tables)"
        return f"Odoo ({self.db or 'not configured'})"

    def _connect(self):
        """Authenticate once and cache uid + models proxy."""
        if self._uid:
            return
        import xmlrpc.client
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._uid = common.authenticate(self.db, self.user, self.password, {})
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        logger.info("OdooAdapter connected: uid=%s db=%s", self._uid, self.db)

    def _search_read(self, model: str, domain: list, fields: list, limit: int = 200) -> list:
        self._connect()
        return self._models.execute_kw(
            self.db, self._uid, self.password,
            model, 'search_read', [domain],
            {'fields': fields, 'limit': limit}
        )

    # ── Master Data ────────────────────────────────────────────────────────────

    def get_vendors(self, active_only: bool = True, limit: int = 200) -> list:
        if self._use_demo:
            where = "active::text IN ('True','true','TRUE','1','t')" if active_only else ''
            return [_norm_vendor(r) for r in _query('vendors', where=where, limit=limit)]
        domain = [('supplier_rank', '>', 0)]
        if active_only:
            domain.append(('active', '=', True))
        try:
            rows = self._search_read('res.partner', domain,
                ['id','name','active','country_id','property_supplier_payment_term_id','supplier_rank'], limit)
            return [{'vendor_id': r['id'], 'vendor_name': r['name'],
                     'active': r['active'], 'vendor_rating': r['supplier_rank'],
                     'country': r['country_id'][1] if r.get('country_id') else None} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_vendors failed: %s", e)
            return []

    def get_items(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'default_code = %s'
                params = (item_code,)
            return [_norm_item(r) for r in _query('items', where=where, params=params)]
        domain = [('purchase_ok', '=', True)]
        if item_code:
            domain.append(('default_code', '=', item_code))
        try:
            rows = self._search_read('product.product', domain,
                ['id','name','default_code','categ_id','standard_price','uom_id'], 200)
            return [{'item_code': r.get('default_code'), 'item_description': r['name'],
                     'category': r['categ_id'][1] if r.get('categ_id') else None,
                     'std_unit_cost': r.get('standard_price')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_items failed: %s", e)
            return []

    def get_cost_centers(self) -> list:
        if self._use_demo:
            rows = _query('cost_centers')
            return [{'cost_center_code': r.get('id', ''),
                     'cost_center_name': r.get('name', '')} for r in rows]
        try:
            rows = self._search_read('account.analytic.account', [], ['id','name','code'], 200)
            return [{'cost_center_code': r.get('code'), 'cost_center_name': r['name']} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_cost_centers failed: %s", e)
            return []

    def get_exchange_rates(self) -> list:
        if self._use_demo:
            rows = _query('exchange_rates')
            return [{'currency_code': r.get('name', ''),
                     'rate': r.get('rate', 0),
                     'rate_date': None} for r in rows]
        try:
            rows = self._search_read('res.currency.rate', [], ['id','currency_id','company_rate','name'], 100)
            return [{'currency_code': r['currency_id'][1] if r.get('currency_id') else None,
                     'rate': r.get('company_rate'), 'rate_date': r.get('name')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_exchange_rates failed: %s", e)
            return []

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'state = %s'
                params = (status,)
            rows = _query('purchase_requisitions', where=where, params=params, limit=limit)
            return [{'pr_number': r.get('name', ''),
                     'status': r.get('state', ''),
                     'vendor_id': str(r.get('partner_id', '')),
                     'requested_by': None} for r in rows]
        domain = []
        if status:
            domain.append(('state', '=', status))
        try:
            rows = self._search_read('purchase.requisition', domain,
                ['id','name','state','date_end','user_id','line_ids'], limit)
            return [{'pr_number': r['name'], 'status': r['state'],
                     'requested_by': r['user_id'][1] if r.get('user_id') else None} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_purchase_requisitions failed: %s", e)
            return []

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        if self._use_demo:
            rows = _query('approved_supplier_list', where="supplier_rank ~ '^[0-9]+$' AND supplier_rank::int > 0")
            return [{'vendor_id': str(r.get('id', '')),
                     'vendor_name': r.get('name', ''),
                     'email': r.get('email', ''),
                     'approval_status': 'Approved'} for r in rows]
        domain = []
        if item_code:
            domain.append(('product_tmpl_id.default_code', '=', item_code))
        try:
            rows = self._search_read('product.supplierinfo', domain,
                ['id','partner_id','product_tmpl_id','price','delay','min_qty'], 200)
            return [{'vendor_id': str(r['partner_id'][0]), 'vendor_name': r['partner_id'][1],
                     'item_code': None, 'lead_time_days': r.get('delay'),
                     'min_order_qty': r.get('min_qty'), 'approval_status': 'Approved'} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_approved_suppliers failed: %s", e)
            return []

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'state = %s'
                params = (status,)
            rows = _query('rfq_headers', where=where, params=params, limit=limit)
            return [{'rfq_number': r.get('name', ''),
                     'status': r.get('state', ''),
                     'vendor_name': r.get('partner_id', ''),
                     'amount_total': r.get('amount_total', 0)} for r in rows]
        domain = [('state', 'in', ['draft', 'sent'])]
        try:
            rows = self._search_read('purchase.order', domain,
                ['id','name','partner_id','date_order','state','amount_total'], limit)
            return [{'rfq_number': r['name'], 'vendor_name': r['partner_id'][1] if r.get('partner_id') else None,
                     'rfq_date': r.get('date_order'), 'status': r['state'],
                     'amount_total': r.get('amount_total')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_rfq_headers failed: %s", e)
            return []

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_name:
                where = 'name ILIKE %s'
                params = (f'%{item_name}%',)
            rows = _query('vendor_quotes', where=where, params=params, limit=limit)
            return [{'rfq_reference': r.get('name', ''),
                     'vendor_id': str(r.get('partner_id', '')),
                     'total_quote_value': r.get('amount_total', 0),
                     'status': r.get('state', '')} for r in rows]
        domain = [('order_id.state', 'in', ['draft', 'sent'])]
        if item_name:
            domain.append(('name', 'ilike', item_name))
        try:
            rows = self._search_read('purchase.order.line', domain,
                ['id','order_id','partner_id','product_id','product_qty','price_unit','price_subtotal'], limit)
            return [{'rfq_reference': r['order_id'][1] if r.get('order_id') else None,
                     'item_description': r['product_id'][1] if r.get('product_id') else None,
                     'qty_quoted': r.get('product_qty'), 'unit_price': r.get('price_unit'),
                     'total_quote_value': r.get('price_subtotal')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_vendor_quotes failed: %s", e)
            return []

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where = 'id = %s'
                params = (int(vendor_id),)
            rows = _query('contracts', where=where, params=params, limit=limit)
            return [{'contract_number': r.get('ref', ''),
                     'vendor_name': r.get('name', ''),
                     'email': r.get('email', ''),
                     'status': 'Active' if r.get('active', True) else 'Inactive'} for r in rows]
        domain = [('state', '=', 'open')]
        if vendor_id:
            domain.append(('partner_id', '=', int(vendor_id)))
        try:
            rows = self._search_read('purchase.requisition', domain,
                ['id','name','partner_id','date_start','date_end','state'], limit)
            return [{'contract_no': r['name'], 'vendor_name': r['partner_id'][1] if r.get('partner_id') else None,
                     'contract_start_date': r.get('date_start'), 'contract_end_date': r.get('date_end'),
                     'status': r['state']} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_contracts failed: %s", e)
            return []

    # ── Purchase Orders ────────────────────────────────────────────────────────

    def get_purchase_orders(self, status: str = None, limit: int = 100) -> list:
        if self._use_demo:
            where, params = '', ()
            if status:
                where = 'state = %s'
                params = (status,)
            return [_norm_po(r) for r in _query('po_headers', where=where, params=params, limit=limit)]
        domain = [('state', 'in', ['purchase', 'done'])]
        if status:
            domain = [('state', '=', status)]
        try:
            rows = self._search_read('purchase.order', domain,
                ['id','name','partner_id','date_order','amount_total','state','user_id'], limit)
            return [{'po_number': r['name'],
                     'vendor_name': r['partner_id'][1] if r.get('partner_id') else None,
                     'po_date': r.get('date_order'), 'po_grand_total': r.get('amount_total'),
                     'po_status': r['state'], 'buyer': r['user_id'][1] if r.get('user_id') else None} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_purchase_orders failed: %s", e)
            return []

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_grn_headers(self, grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if po_number:
                where = 'origin = %s'
                params = (po_number,)
            elif grn_number:
                where = 'name = %s'
                params = (grn_number,)
            return [_norm_grn(r) for r in _query('grn_headers', where=where, params=params, limit=limit)]
        domain = [('picking_type_code', '=', 'incoming'), ('state', '=', 'done')]
        if po_number:
            domain.append(('origin', '=', po_number))
        try:
            rows = self._search_read('stock.picking', domain,
                ['id','name','origin','partner_id','scheduled_date','state'], limit)
            return [{'grn_number': r['name'], 'po_reference': r.get('origin'),
                     'vendor_name': r['partner_id'][1] if r.get('partner_id') else None,
                     'grn_date': r.get('scheduled_date'), 'grn_status': r['state']} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_grn_headers failed: %s", e)
            return []

    # ── Accounts Payable ──────────────────────────────────────────────────────

    def get_vendor_invoices(self, invoice_no: str = None, limit: int = 50) -> list:
        if self._use_demo:
            where, params = '', ()
            if invoice_no:
                where = 'name = %s'
                params = (invoice_no,)
            return [_norm_invoice(r) for r in _query('invoices', where=where, params=params, limit=limit)]
        domain = [('move_type', '=', 'in_invoice')]
        if invoice_no:
            domain.append(('name', '=', invoice_no))
        try:
            rows = self._search_read('account.move', domain,
                ['id','name','invoice_date','partner_id','amount_total','payment_state','invoice_origin'], limit)
            return [{'invoice_no': r['name'], 'invoice_date': r.get('invoice_date'),
                     'vendor_name': r['partner_id'][1] if r.get('partner_id') else None,
                     'invoice_total': r.get('amount_total'), 'ap_status': r.get('payment_state'),
                     'po_reference': r.get('invoice_origin')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_vendor_invoices failed: %s", e)
            return []

    def get_ap_aging(self) -> list:
        if self._use_demo:
            rows = _query('ap_aging', where="state != 'posted'")
            return [{'invoice_number': r.get('name', ''),
                     'vendor_id': str(r.get('partner_id', '')),
                     'amount': r.get('amount_total', 0),
                     'due_date': str(r.get('invoice_date_due', '')),
                     'status': r.get('state', '')} for r in rows]
        try:
            rows = self._search_read('account.move', [('move_type','=','in_invoice'),('payment_state','!=','paid')],
                ['id','name','partner_id','amount_residual','invoice_date_due'], 500)
            return [{'vendor_name': r['partner_id'][1] if r.get('partner_id') else None,
                     'outstanding_amount': r.get('amount_residual'),
                     'due_date': r.get('invoice_date_due')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_ap_aging failed: %s", e)
            return []

    def get_payment_proposals(self, limit: int = 50) -> list:
        if self._use_demo:
            rows = _query('payment_proposals', limit=limit)
            return [{'invoice_number': r.get('name', ''),
                     'vendor_id': str(r.get('partner_id', '')),
                     'amount': r.get('amount_total', 0),
                     'due_date': str(r.get('invoice_date_due', '')),
                     'status': r.get('state', '')} for r in rows]
        try:
            rows = self._search_read('account.payment', [('payment_type','=','outbound'),('state','=','draft')],
                ['id','name','partner_id','amount','date'], limit)
            return [{'proposal_id': r['name'], 'vendor_name': r['partner_id'][1] if r.get('partner_id') else None,
                     'amount': r.get('amount'), 'payment_date': r.get('date')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_payment_proposals failed: %s", e)
            return []

    # ── Finance ───────────────────────────────────────────────────────────────

    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if cost_center:
                where = 'name = %s'
                params = (cost_center,)
            rows = _query('budget', where=where, params=params)
            return [{'cost_center': r.get('name', ''),
                     'currency': r.get('currency_id', ''),
                     'country': r.get('country_id', '')} for r in rows]
        domain = []
        if cost_center:
            domain.append(('analytic_account_id.code', '=', cost_center))
        try:
            rows = self._search_read('crossovered.budget.lines', domain,
                ['id','analytic_account_id','general_budget_id','planned_amount','practical_amount','percentage'], 500)
            return [{'cost_center': r['analytic_account_id'][1] if r.get('analytic_account_id') else None,
                     'gl_account': r['general_budget_id'][1] if r.get('general_budget_id') else None,
                     'fy_budget': r.get('planned_amount'), 'fy_actual': r.get('practical_amount'),
                     'utilization_pct': r.get('percentage')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_budget_vs_actuals failed: %s", e)
            return []

    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        if self._use_demo:
            return [_norm_spend(r) for r in _query('spend', limit=limit)]
        domain = [('state', 'in', ['purchase', 'done'])]
        try:
            rows = self._search_read('purchase.order', domain,
                ['id','partner_id','amount_total','date_approve','x_department'], limit)
            return [{'vendor_name': r['partner_id'][1] if r.get('partner_id') else None,
                     'total_amount_usd': r.get('amount_total'),
                     'period': str(r.get('date_approve', ''))[:7],
                     'cost_center': r.get('x_department')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_spend_analytics failed: %s", e)
            return []

    def get_vendor_performance(self, vendor_id: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if vendor_id:
                where = 'id = %s'
                params = (int(vendor_id),)
            rows = _query('vendor_performance', where=where, params=params)
            return [_norm_vendor(r) for r in rows]
        domain = [('supplier_rank', '>', 0)]
        if vendor_id:
            domain.append(('id', '=', int(vendor_id)))
        try:
            rows = self._search_read('res.partner', domain,
                ['id','name','supplier_rank','purchase_order_count'], 100)
            return [{'vendor_id': str(r['id']), 'vendor_name': r['name'],
                     'overall_score': r.get('supplier_rank'),
                     'total_pos': r.get('purchase_order_count')} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_vendor_performance failed: %s", e)
            return []

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_status(self, item_code: str = None) -> list:
        if self._use_demo:
            where, params = '', ()
            if item_code:
                where = 'name ILIKE %s'
                params = (f'%{item_code}%',)
            rows = _query('inventory', where=where, params=params)
            return [{'location': r.get('name', ''),
                     'complete_name': r.get('complete_name', ''),
                     'usage': r.get('usage', ''),
                     'active': r.get('active', True)} for r in rows]
        domain = [('location_id.usage', '=', 'internal')]
        if item_code:
            domain.append(('product_id.default_code', '=', item_code))
        try:
            rows = self._search_read('stock.quant', domain,
                ['id','product_id','quantity','reserved_quantity','location_id'], 500)
            return [{'item_code': r['product_id'][1] if r.get('product_id') else None,
                     'item_description': r['product_id'][1] if r.get('product_id') else None,
                     'total_received': r.get('quantity', 0),
                     'reorder_point': 0,   # fetch from reordering rules separately
                     'active': True} for r in rows]
        except Exception as e:
            logger.error("OdooAdapter.get_inventory_status failed: %s", e)
            return []

    # ── System ────────────────────────────────────────────────────────────────

    def get_table_registry(self) -> list:
        # Table registry lives in PostgreSQL regardless of ERP source
        from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter().get_table_registry()
