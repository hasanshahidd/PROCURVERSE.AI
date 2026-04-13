"""
PostgreSQLAdapter — reads from PostgreSQL demo database.

DATA_SOURCE routing (Sprint 11 — updated for new CSV table names):
  postgresql  → neutral NMI tables (legacy fallback)
  demo_odoo   → odoo_* tables (odoo_partners, odoo_products, odoo_purchase_orders ...)
  demo_sap    → sap_* tables (sap_vendor_general, sap_material_general, sap_purchase_orders ...)
  demo_dynamics → d365_* tables (d365_vendors, d365_products, d365_purchase_orders ...)
  demo_oracle → oracle_* tables (oracle_suppliers, oracle_items, oracle_purchase_orders ...)
  demo_erpnext → erpnext_* tables (erpnext_suppliers, erpnext_items, erpnext_purchase_orders ...)

When real ERP is connected → swap to OdooAdapter/SAPAdapter/etc. in factory.
PostgreSQLAdapter stays dormant. Zero agent code changes needed.
"""

import os, logging
from backend.services.adapters.base_adapter import IDataSourceAdapter
from backend.services import nmi_data_service as _db

logger = logging.getLogger(__name__)

# Map DATA_SOURCE value → ERP key (after stripping demo_ prefix)
_ERP_SUFFIX = {
    'odoo':     'odoo',
    'sap':      'sap',
    'sap_s4':   'sap',
    'sap_b1':   'sap',
    'dynamics': 'd365',
    'oracle':   'oracle',
    'erpnext':  'erpnext',
}

# ── NEW CSV TABLE MAPPING ─────────────────────────────────────────────────────
# Maps (adapter_method_key, erp) → actual table name in PostgreSQL
# This is the SINGLE source of truth for table routing.
_TABLE_MAP = {
    # ── Vendors / Partners / Suppliers ──
    ('vendors', 'odoo'):     'odoo_partners',
    ('vendors', 'sap'):      'sap_vendor_general',
    ('vendors', 'd365'):     'd365_vendors',
    ('vendors', 'oracle'):   'oracle_suppliers',
    ('vendors', 'erpnext'):  'erpnext_suppliers',

    # ── Items / Products / Materials ──
    ('items', 'odoo'):       'odoo_products',
    ('items', 'sap'):        'sap_material_general',
    ('items', 'd365'):       'd365_products',
    ('items', 'oracle'):     'oracle_items',
    ('items', 'erpnext'):    'erpnext_items',

    # ── Purchase Orders ──
    ('po_headers', 'odoo'):  'odoo_purchase_orders',
    ('po_headers', 'sap'):   'sap_purchase_orders',
    ('po_headers', 'd365'):  'd365_purchase_orders',
    ('po_headers', 'oracle'):'oracle_purchase_orders',
    ('po_headers', 'erpnext'):'erpnext_purchase_orders',

    # ── Invoices ──
    ('invoices', 'odoo'):    'odoo_invoices',
    ('invoices', 'sap'):     'sap_invoice_headers',
    ('invoices', 'd365'):    'd365_journal_entries',
    ('invoices', 'oracle'):  'oracle_invoices',
    ('invoices', 'erpnext'): 'erpnext_payment_entries',

    # ── Chart of Accounts / GL ──
    ('gl_accounts', 'odoo'): 'odoo_chart_of_accounts',
    ('gl_accounts', 'sap'):  'sap_gl_accounts',
    ('gl_accounts', 'd365'): 'd365_gl_accounts',
    ('gl_accounts', 'oracle'):'oracle_gl_accounts',
    ('gl_accounts', 'erpnext'):'erpnext_gl_accounts',

    # ── Cost Centers ──
    ('cost_centers', 'odoo'): 'odoo_companies',
    ('cost_centers', 'sap'):  'sap_cost_centers',
    ('cost_centers', 'd365'): 'd365_dimensions',
    ('cost_centers', 'oracle'):'oracle_cost_centers',
    ('cost_centers', 'erpnext'):'erpnext_cost_centers',

    # ── Warehouses / Locations ──
    ('warehouses', 'odoo'):   'odoo_warehouses',
    ('warehouses', 'sap'):    'sap_plant_data',
    ('warehouses', 'd365'):   'd365_warehouses',
    ('warehouses', 'oracle'): 'oracle_business_units',
    ('warehouses', 'erpnext'):'erpnext_warehouses',

    # ── Payment Terms ──
    ('payment_terms', 'odoo'):   'odoo_payment_terms',
    ('payment_terms', 'sap'):    'sap_payment_terms',
    ('payment_terms', 'd365'):   'd365_payment_terms',
    ('payment_terms', 'oracle'): 'oracle_payment_terms',
    ('payment_terms', 'erpnext'):'erpnext_payment_terms',

    # ── Employees ──
    ('employees', 'odoo'):   'odoo_employees',
    ('employees', 'sap'):    'sap_vendor_purchasing',
    ('employees', 'd365'):   'd365_employees',
    ('employees', 'oracle'): 'oracle_supplier_contacts',
    ('employees', 'erpnext'):'erpnext_employees',

    # ── Currencies ──
    ('currencies', 'odoo'):  'odoo_currencies',
    ('currencies', 'sap'):   'sap_company_codes',
    ('currencies', 'd365'):  'd365_legal_entities',
    ('currencies', 'oracle'):'oracle_currencies',
    ('currencies', 'erpnext'):'erpnext_companies',

    # ── Taxes ──
    ('taxes', 'odoo'):       'odoo_taxes',
    ('taxes', 'sap'):        'sap_gl_accounts',
    ('taxes', 'd365'):       'd365_tax_groups',
    ('taxes', 'oracle'):     'oracle_item_categories',
    ('taxes', 'erpnext'):    'erpnext_item_groups',

    # ── Sales Orders ──
    ('sales_orders', 'odoo'):   'odoo_sale_orders',
    ('sales_orders', 'sap'):    'sap_sales_orders',
    ('sales_orders', 'd365'):   'd365_sales_orders',
    ('sales_orders', 'oracle'): 'oracle_sales_orders',
    ('sales_orders', 'erpnext'):'erpnext_sales_orders',

    # ── Vendor Performance (map to vendors since no separate perf table) ──
    ('vendor_performance', 'odoo'):    'odoo_partners',
    ('vendor_performance', 'sap'):     'sap_vendor_general',
    ('vendor_performance', 'd365'):    'd365_vendors',
    ('vendor_performance', 'oracle'):  'oracle_suppliers',
    ('vendor_performance', 'erpnext'): 'erpnext_suppliers',

    # ── Approved Supplier List (map to vendors) ──
    ('approved_supplier_list', 'odoo'):    'odoo_partners',
    ('approved_supplier_list', 'sap'):     'sap_vendor_purchasing',
    ('approved_supplier_list', 'd365'):    'd365_vendors',
    ('approved_supplier_list', 'oracle'):  'oracle_suppliers',
    ('approved_supplier_list', 'erpnext'): 'erpnext_suppliers',

    # ── Contracts ──
    ('contracts', 'odoo'):    'odoo_purchase_orders',
    ('contracts', 'sap'):     'sap_purchase_orders',
    ('contracts', 'd365'):    'd365_purchase_orders',
    ('contracts', 'oracle'):  'oracle_purchase_orders',
    ('contracts', 'erpnext'): 'erpnext_purchase_orders',

    # ── Spend Analytics ──
    ('spend', 'odoo'):    'odoo_purchase_orders',
    ('spend', 'sap'):     'sap_purchase_orders',
    ('spend', 'd365'):    'd365_purchase_orders',
    ('spend', 'oracle'):  'oracle_purchase_orders',
    ('spend', 'erpnext'): 'erpnext_purchase_orders',

    # ── Budget vs Actuals ──
    ('budget_vs_actuals', 'odoo'):    'odoo_purchase_orders',
    ('budget_vs_actuals', 'sap'):     'sap_purchase_orders',
    ('budget_vs_actuals', 'd365'):    'd365_purchase_orders',
    ('budget_vs_actuals', 'oracle'):  'oracle_purchase_orders',
    ('budget_vs_actuals', 'erpnext'): 'erpnext_purchase_orders',

    # ── GRN Headers ──
    ('grn_headers', 'odoo'):    'odoo_warehouses',
    ('grn_headers', 'sap'):     'sap_plant_data',
    ('grn_headers', 'd365'):    'd365_warehouses',
    ('grn_headers', 'oracle'):  'oracle_business_units',
    ('grn_headers', 'erpnext'): 'erpnext_warehouses',

    # ── Customers ──
    ('customers', 'odoo'):   'odoo_partners',
    ('customers', 'sap'):    'sap_customer_general',
    ('customers', 'd365'):   'd365_customers',
    ('customers', 'oracle'): 'oracle_customers',
    ('customers', 'erpnext'):'erpnext_customers',

    # ── Vendor Bank Accounts ──
    ('vendor_banks', 'odoo'):   'odoo_partner_banks',
    ('vendor_banks', 'sap'):    'sap_vendor_bank',
    ('vendor_banks', 'd365'):   'd365_vendor_bank_accounts',
    ('vendor_banks', 'oracle'): 'oracle_supplier_bank_accounts',
    ('vendor_banks', 'erpnext'):'erpnext_addresses',

    # ── Product Categories ──
    ('product_categories', 'odoo'):   'odoo_product_categories',
    ('product_categories', 'sap'):    'sap_material_valuation',
    ('product_categories', 'd365'):   'd365_product_variants',
    ('product_categories', 'oracle'): 'oracle_item_categories',
    ('product_categories', 'erpnext'):'erpnext_item_groups',
}

# Neutral column → ERP-specific column name for key fields
_VENDOR_ID_COL = {
    'odoo':     'id',
    'sap':      'lifnr',
    'd365':     'vendaccount',
    'oracle':   'vendor_id',
    'erpnext':  'name',
}
_VENDOR_NAME_COL = {
    'odoo':     'name',
    'sap':      'name1',
    'd365':     'vendname',
    'oracle':   'vendor_name',
    'erpnext':  'supplier_name',
}
_PO_NUMBER_COL = {
    'odoo':     'name',
    'sap':      'ebeln',
    'd365':     'purchid',
    'oracle':   'po_number',
    'erpnext':  'name',
}
_INVOICE_NUMBER_COL = {
    'odoo':     'name',
    'sap':      'belnr',
    'd365':     'journalid',
    'oracle':   'invoice_number',
    'erpnext':  'name',
}


def _get_erp_suffix() -> str:
    """Get the ERP key from DATA_SOURCE env var."""
    src = os.environ.get('DATA_SOURCE', 'postgresql').lower()
    if src.startswith('demo_'):
        src = src[5:]
    return _ERP_SUFFIX.get(src, '')


def _resolve_table(table_base: str) -> str:
    """Resolve a logical table name to the actual PostgreSQL table.

    Uses _TABLE_MAP to find the CSV-based table (e.g., 'vendors' + 'odoo' → 'odoo_partners').
    Falls back to the old naming pattern if no mapping exists.
    """
    suffix = _get_erp_suffix()
    if not suffix:
        return table_base  # neutral table name as-is

    # Try new CSV table mapping first
    mapped = _TABLE_MAP.get((table_base, suffix))
    if mapped:
        return mapped

    # Fallback: old naming convention (table_base + _ + suffix)
    return f'{table_base}_{suffix}'


def _query_erp_table(table_base: str, where: str = '', params: tuple = (),
                     limit: int = 200) -> list:
    """Query an ERP-specific table, resolving via _TABLE_MAP.

    Example: _query_erp_table('vendors') with DATA_SOURCE=demo_odoo
             → resolves to odoo_partners → SELECT * FROM odoo_partners LIMIT 200
    """
    from backend.services.nmi_data_service import get_conn, _rows
    from psycopg2.extras import RealDictCursor
    table = _resolve_table(table_base)
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f'SELECT * FROM {table}'
            if where:
                sql += f' WHERE {where}'
            sql += f' LIMIT {limit}'
            cur.execute(sql, params)
            return _rows(cur)
    except Exception as e:
        logger.error("_query_erp_table %s (base=%s) failed: %s", table, table_base, e)
        return []
    finally:
        if conn:
            conn.close()


def _normalize_vendor(row: dict, suffix: str) -> dict:
    """Remap ERP-native vendor fields to neutral column names."""
    if not row:
        return row
    id_col   = _VENDOR_ID_COL.get(suffix, 'id')
    name_col = _VENDOR_NAME_COL.get(suffix, 'name')
    return {
        'vendor_id':   str(row.get(id_col, '')),
        'vendor_name': row.get(name_col, ''),
        'country':     row.get('country', row.get('land1', '')),
        'city':        row.get('city', row.get('ort01', '')),
        'active':      row.get('active', row.get('valid', True)),
        **{k: v for k, v in row.items()
           if k not in (id_col, name_col, 'erp_source')},
    }


def _normalize_payment_terms(raw: str) -> str:
    """
    Normalise payment-term strings to 'Net NN' / '2/10 Net 30' format.
    Covers Odoo ('30 Net', '60 Net', '2/10 Net 30') and SAP ('Z030', 'Z060').
    """
    if not raw:
        return raw
    s = str(raw).strip()
    import re as _re
    # Already correct e.g. 'Net 30', '2/10 Net 30'
    if _re.match(r'^\d+/\d+\s+Net\s+\d+$', s, _re.I) or _re.match(r'^Net\s+\d+$', s, _re.I):
        return s
    # Odoo reversed: '30 Net' → 'Net 30', '60 Net' → 'Net 60'
    m = _re.match(r'^(\d+)\s+Net$', s, _re.I)
    if m:
        return f"Net {m.group(1)}"
    # SAP Z-term codes: 'Z030' → 'Net 30', 'Z060' → 'Net 60'
    m = _re.match(r'^Z0*(\d+)$', s, _re.I)
    if m:
        return f"Net {int(m.group(1))}"
    # Fallback — return as-is
    return s


def _normalize_po(row: dict, suffix: str) -> dict:
    """Remap ERP-native PO fields to neutral column names."""
    if not row:
        return row
    po_col = _PO_NUMBER_COL.get(suffix, 'name')
    raw_terms = row.get('payment_term_id', row.get('zterm', row.get('payterms', '')))
    return {
        'po_number':      str(row.get(po_col, '')),
        'po_grand_total': row.get('amount_total', row.get('netwr', row.get('doctotal',
                          row.get('totalamount', row.get('grand_total', 0))))),
        'po_status':      row.get('state', row.get('status', row.get('docstatus', ''))),
        'payment_terms':  _normalize_payment_terms(str(raw_terms)) if raw_terms else '',
        **{k: v for k, v in row.items()
           if k not in (po_col, 'erp_source')},
    }


# ────────────────────────────────────────────────────────────────────────────
# HF-4 / R8 / R19 — Session snapshot helpers
#
# Snapshots bound SSE replay cost on long-running sessions. They are written
# in the SAME transaction as their triggering event so a crash between the
# event INSERT and the snapshot INSERT is impossible, and they carry a
# SHA-256 content_hash for corruption detection on replay.
#
# Trigger rule: write a snapshot at every phase_completed event OR every N
# events, whichever comes first. Phase boundaries are the most useful replay
# checkpoints because they are also the transactional-outbox commit points.
# ────────────────────────────────────────────────────────────────────────────

SNAPSHOT_EVERY_N_EVENTS = 100


def _should_snapshot(event_type: str, sequence_number: int) -> bool:
    """Return True iff an event should trigger a snapshot write."""
    if event_type == "phase_completed":
        return True
    if sequence_number > 0 and sequence_number % SNAPSHOT_EVERY_N_EVENTS == 0:
        return True
    return False


def _canonical_state_hash(state: dict) -> str:
    """SHA-256 over a canonical JSON serialization of the folded state (R19)."""
    import hashlib
    import json as _json
    canonical = _json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fold_session_state_from_cur(cur, session_id: str, up_to_seq: int) -> dict:
    """
    Fold session_events 0..up_to_seq into a deterministic state dict using
    the caller's cursor. This is deliberately cursor-based (not a new conn)
    so that events inserted in the SAME transaction — including the event
    that triggered the snapshot — are visible to the fold.

    The fold output is the single source of truth the SSE client would
    reconstruct by replaying events. The content_hash is taken over this
    exact dict, so any divergence between write-time and read-time fold
    logic will be caught on verify_snapshot_hash.
    """
    cur.execute(
        """
        SELECT session_id, session_kind, current_phase, current_status,
               current_checkpoint, last_event_sequence, snapshot_version,
               created_at, updated_at, completed_at
        FROM execution_sessions
        WHERE session_id = %s
        """,
        (session_id,),
    )
    master = cur.fetchone()
    if not master:
        return {}

    cur.execute(
        """
        SELECT sequence_number, event_type, actor, payload, created_at
        FROM session_events
        WHERE session_id = %s AND sequence_number <= %s
        ORDER BY sequence_number ASC
        """,
        (session_id, int(up_to_seq)),
    )
    events = cur.fetchall()

    completed_phases: list = []
    failed_phases: list = []
    phase_payloads: dict = {}   # phase_name → payload from phase_completed
    open_gates: dict = {}
    resolved_gates: list = []
    last_event_type = None
    last_event_at = None

    for ev in events:
        etype = ev["event_type"]
        payload = ev.get("payload") or {}
        last_event_type = etype
        last_event_at = ev.get("created_at")

        if etype == "phase_completed":
            phase = (payload or {}).get("phase")
            if phase and phase not in completed_phases:
                completed_phases.append(phase)
            if phase:
                phase_payloads[phase] = payload
        elif etype == "phase_failed":
            phase = (payload or {}).get("phase")
            if phase and phase not in failed_phases:
                failed_phases.append(phase)
        elif etype == "gate_opened":
            gid = (payload or {}).get("gate_id")
            if gid:
                open_gates[gid] = {
                    "gate_type": (payload or {}).get("gate_type"),
                    "gate_ref": (payload or {}).get("gate_ref", {}),
                    "decision_context": (payload or {}).get("decision_context", {}),
                    "required_role": (payload or {}).get("required_role"),
                    "opened_at_sequence": int(ev["sequence_number"]),
                }
        elif etype == "gate_resolved":
            gid = (payload or {}).get("gate_id")
            if gid and gid in open_gates:
                resolved_gates.append({
                    "gate_id": gid,
                    "gate_type": open_gates[gid].get("gate_type"),
                    "resolved_at_sequence": int(ev["sequence_number"]),
                })
                open_gates.pop(gid, None)

    return {
        "session_id": str(master["session_id"]),
        "session_kind": master["session_kind"],
        "current_phase": master["current_phase"],
        "current_status": master["current_status"],
        "current_checkpoint": master.get("current_checkpoint"),
        "at_sequence_number": int(up_to_seq),
        "completed_phases": completed_phases,
        "failed_phases": failed_phases,
        "phase_payloads": phase_payloads,
        "open_gates": {
            gid: {
                "gate_id": gid,
                "gate_type": gdata.get("gate_type"),
                "gate_ref": gdata.get("gate_ref", {}),
                "decision_context": gdata.get("decision_context", {}),
                "required_role": gdata.get("required_role"),
            }
            for gid, gdata in open_gates.items()
        },
        "resolved_gates": [g["gate_id"] for g in resolved_gates],
        "last_event_type": last_event_type,
        "last_event_at": last_event_at,
        "events_count": len(events),
    }


class PostgreSQLAdapter(IDataSourceAdapter):
    """
    Routes to neutral NMI tables OR ERP-specific tables based on DATA_SOURCE.
    Normalizes ERP-native field names to neutral names before returning to agents.
    """

    def source_name(self) -> str:
        suffix = _get_erp_suffix()
        if suffix:
            return f"PostgreSQL — {suffix.upper()} demo tables"
        return "PostgreSQL (NMI neutral tables)"

    # ── Master Data ────────────────────────────────────────────────────────────

    def get_vendors(self, active_only: bool = True, limit: int = 200) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            rows = _query_erp_table('vendors', limit=limit)
            return [_normalize_vendor(r, suffix) for r in rows]
        # neutral path
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        from decimal import Decimal
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                where = "WHERE active::text IN ('True','true','TRUE','1','t')" if active_only else ""
                cur.execute(f"SELECT * FROM vendors {where} ORDER BY vendor_id LIMIT %s", (limit,))
                return [{k: float(v) if isinstance(v, Decimal) else v for k, v in r.items()} for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_vendors failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()

    def get_items(self, item_code: str = None, category: str = None) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            where = "itemcode = %s OR item_code = %s OR itemnumber = %s OR name = %s" if item_code else ''
            params = (item_code,)*4 if item_code else ()
            return _query_erp_table('items', where=where, params=params, limit=200)
        return _db.get_nmi_inventory_status(item_code=item_code)

    def get_cost_centers(self) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            return _query_erp_table('cost_centers', limit=200)
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM cost_centers ORDER BY cost_center_code")
                return _rows(cur)
        except Exception as e:
            logger.error("get_cost_centers failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()

    def get_exchange_rates(self) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM exchange_rates ORDER BY currency_code")
                return _rows(cur)
        except Exception as e:
            logger.error("get_exchange_rates failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()

    # ── Procurement ────────────────────────────────────────────────────────────

    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM purchase_requisitions WHERE (%s IS NULL OR status ILIKE %s) ORDER BY pr_date DESC LIMIT %s",
                    (status, status, limit)
                )
                return _rows(cur)
        except Exception as e:
            logger.error("get_purchase_requisitions failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()

    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            # ERP-specific approved_supplier_list table
            where, params = '', ()
            if item_code:
                where = "product_id = %s OR item_code = %s OR itemnumber = %s"
                params = (item_code, item_code, item_code)
            rows = _query_erp_table('approved_supplier_list', where=where, params=params, limit=500)
            # Normalise to neutral fields
            result = []
            for r in rows:
                result.append({
                    'vendor_id':   str(r.get('partner_id', r.get('vendor_id', r.get('lifnr', '')))),
                    'vendor_name': r.get('vendor_name', r.get('name', '')),
                    'supplier_id': str(r.get('partner_id', r.get('vendor_id', r.get('lifnr', '')))),
                    **r,
                })
            return result
        return _db.get_nmi_approved_suppliers(item_code=item_code, item_category=category)

    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        """Get RFQ headers from the rfq_headers system table."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if status:
                    cur.execute("SELECT * FROM rfq_headers WHERE status ILIKE %s ORDER BY created_at DESC LIMIT %s", (status, limit))
                else:
                    cur.execute("SELECT * FROM rfq_headers ORDER BY created_at DESC LIMIT %s", (limit,))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_rfq_headers failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        """Get vendor quotes from the vendor_quotes system table."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if item_name:
                    cur.execute(
                        "SELECT * FROM vendor_quotes WHERE item_name ILIKE %s ORDER BY unit_price LIMIT %s",
                        (f"%{item_name}%", limit)
                    )
                else:
                    cur.execute("SELECT * FROM vendor_quotes ORDER BY created_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
                return [{k: float(v) if isinstance(v, __import__('decimal').Decimal) else v for k, v in dict(r).items()} for r in rows]
        except Exception as e:
            logger.error("get_vendor_quotes failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            vendor_col_map = {
                'odoo':     'partner_id',
                'sap':      'lifnr',
                'd365':     'vendaccount',
                'oracle':   'vendor_id',
                'erpnext':  'supplier',
            }
            vcol = vendor_col_map.get(suffix, 'vendor_id')
            where  = f"{vcol} = %s OR {vcol}::text = %s" if vendor_id else ''
            params = (vendor_id, str(vendor_id)) if vendor_id else ()
            rows = _query_erp_table('contracts', where=where, params=params, limit=limit)
            # Add neutral fields
            for r in rows:
                if 'contract_value' not in r:
                    r['contract_value'] = r.get('amount_total', r.get('netwr', r.get('totalvalue', 0)))
                if 'is_blanket_order' not in r:
                    bsart = r.get('bsart', '')  # SAP contract type
                    r['is_blanket_order'] = bsart in ('MK', 'WK') or bool(r.get('is_blanket_order', False))
                if 'payment_terms' not in r:
                    r['payment_terms'] = _normalize_payment_terms(
                        str(r.get('payment_term_id', r.get('zterm', r.get('payterms', '')))))
            return rows
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM contracts WHERE (%s IS NULL OR vendor_id ILIKE %s) ORDER BY contract_start_date DESC LIMIT %s",
                    (vendor_id, vendor_id, limit)
                )
                return _rows(cur)
        except Exception as e:
            logger.error("get_contracts failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()

    # ── Purchase Orders ────────────────────────────────────────────────────────

    def get_purchase_orders(self, status: str = None, limit: int = 100) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            rows = _query_erp_table('po_headers', limit=limit)
            return [_normalize_po(r, suffix) for r in rows]
        return _db.get_nmi_purchase_orders(status=status, limit=limit)

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_grn_headers(self, grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            # GRN link to PO: Odoo uses 'origin'; SAP uses EBELN; Oracle uses PONUMBER
            po_col_map = {
                'odoo':     'origin',
                'sap':      'ebeln',
                'd365':     'purchaseordernumber',
                'oracle':   'ponumber',
                'erpnext':  'purchase_order',
            }
            grn_col_map = {
                'odoo':    'name',
                'sap':     'mblnr',
                'd365':    'receiptid',
                'oracle':  'receiptnum',
                'erpnext': 'name',
            }
            conditions, params = [], []
            if po_number:
                pcol = po_col_map.get(suffix, 'origin')
                conditions.append(f"{pcol} = %s OR {pcol} ILIKE %s")
                params.extend([po_number, po_number])
            if grn_number:
                gcol = grn_col_map.get(suffix, 'name')
                conditions.append(f"{gcol} = %s")
                params.append(grn_number)
            where  = ' AND '.join(conditions) if conditions else ''
            return _query_erp_table('grn_headers', where=where, params=tuple(params), limit=limit)
        return _db.get_nmi_grn_details(grn_number=grn_number, po_number=po_number, limit=limit)

    # ── Accounts Payable ──────────────────────────────────────────────────────

    def get_vendor_invoices(self, invoice_no: str = None, limit: int = 50) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            inv_col_map = {
                'odoo':     'name',
                'sap':      'belnr',
                'd365':     'journalid',
                'oracle':   'invoice_number',
                'erpnext':  'name',
            }
            icol = inv_col_map.get(suffix, 'name')
            if invoice_no:
                where  = f"{icol} = %s OR {icol} ILIKE %s"
                params = (invoice_no, invoice_no)
            else:
                where, params = '', ()
            return _query_erp_table('invoices', where=where, params=params, limit=limit)
        return _db.get_nmi_invoice_details(invoice_no=invoice_no, limit=limit)

    def get_ap_aging(self) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM ap_aging ORDER BY vendor_id")
                return _rows(cur)
        except Exception as e:
            logger.error("get_ap_aging failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()

    def get_payment_proposals(self, limit: int = 50) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM payment_proposals ORDER BY proposal_date DESC LIMIT %s", (limit,))
                return _rows(cur)
        except Exception as e:
            logger.error("get_payment_proposals failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()

    # ── Finance ───────────────────────────────────────────────────────────────

    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            return _query_erp_table('budget_vs_actuals', limit=200)
        return _db.get_nmi_budget_vs_actuals(cost_center=cost_center)

    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            return _query_erp_table('spend', limit=limit)
        return _db.get_nmi_spend_analytics(period=period, limit=limit)

    def get_vendor_performance(self, vendor_id: str = None) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            # ERP-specific vendor_id column names in vendor_performance_* tables
            _vp_id_col = {
                'odoo':     'id',
                'sap':      'lifnr',
                'd365':     'vendaccount',
                'oracle':   'vendor_id',
                'erpnext':  'name',
            }
            vcol = _vp_id_col.get(suffix, 'vendor_id')
            if vendor_id:
                # Cast both sides to TEXT for cross-type comparison
                # (e.g. Odoo partner_id is INTEGER, but vendor_id arg is a string)
                where  = f"(CAST({vcol} AS TEXT) = %s)"
                params = (str(vendor_id),)
            else:
                where, params = '', ()
            return _query_erp_table('vendor_performance', where=where, params=params)
        # Neutral fallback
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM vendor_performance WHERE (%s IS NULL OR vendor_id ILIKE %s) ORDER BY vendor_id",
                    (vendor_id, vendor_id)
                )
                return _rows(cur)
        except Exception as e:
            logger.error("get_vendor_performance failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_status(self, item_code: str = None) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            return _query_erp_table('items', limit=200)
        return _db.get_nmi_inventory_status(item_code=item_code)

    # ── Operational / System tables ───────────────────────────────────────────

    def get_approval_rules(self, document_type: str = None, amount: float = None, department: str = None) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                clauses = ["status = 'active'"]
                params = []
                if document_type:
                    clauses.append("LOWER(document_type) = LOWER(%s)")
                    params.append(document_type)
                if amount is not None:
                    clauses.append("amount_min <= %s AND amount_max >= %s")
                    params.extend([amount, amount])
                if department:
                    clauses.append("(department IS NULL OR LOWER(department) = LOWER(%s))")
                    params.append(department)
                where = " AND ".join(clauses)
                cur.execute(f"SELECT * FROM approval_rules WHERE {where} ORDER BY approval_level, amount_min", params)
                return _rows(cur)
        except Exception as e:
            logger.error("get_approval_rules failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def get_pending_approvals(self, status: str = None, document_type: str = None) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM pending_approvals
                    WHERE (%s IS NULL OR status ILIKE %s)
                    ORDER BY approval_id DESC
                """, (status, status))
                return _rows(cur)
        except Exception as e:
            logger.error("get_pending_approvals failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def create_pending_approval(self, data: dict) -> dict:
        """Create a pending approval record.

        Translates agent data keys (pr_number, decision_type, agent_decision)
        to the actual table columns (approval_id, request_type, request_data,
        recommendation, reasoning).
        """
        import json as _json, uuid as _uuid
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor

        # Generate unique approval ID
        approval_id = _uuid.uuid4().hex[:12]

        # Map agent_name
        agent_name = data.get('agent_name', 'UnknownAgent')

        # Map decision_type → request_type
        request_type = data.get('decision_type', data.get('request_type', 'GENERAL'))

        # Build request_data JSONB from extra fields agents pass
        request_data = {}
        for key in ('pr_number', 'invoice_number', 'po_number', 'amount',
                     'approver_name', 'approver_role', 'approver_email',
                     'sla_hours', 'payment_type', 'vendor_id', 'department'):
            if data.get(key) is not None:
                request_data[key] = data[key]
        request_data_json = _json.dumps(request_data)

        # Map agent_decision → recommendation (JSONB) + reasoning (TEXT)
        raw_decision = data.get('agent_decision')
        if isinstance(raw_decision, str):
            recommendation_json = _json.dumps({"reasoning": raw_decision})
            reasoning_text = raw_decision
        elif isinstance(raw_decision, dict):
            recommendation_json = _json.dumps(raw_decision)
            reasoning_text = raw_decision.get('reasoning', _json.dumps(raw_decision))
        elif raw_decision is None:
            recommendation_json = _json.dumps({})
            reasoning_text = 'No reasoning provided'
        else:
            recommendation_json = _json.dumps(raw_decision)
            reasoning_text = str(raw_decision)

        # Clamp confidence_score (table CHECK constraint)
        confidence = min(float(data.get('confidence_score', 0)), 0.59)

        status = data.get('status', 'pending')

        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO pending_approvals
                      (approval_id, agent_name, request_type, request_data,
                       recommendation, confidence_score, reasoning, status)
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                    RETURNING *
                """, (approval_id, agent_name, request_type, request_data_json,
                      recommendation_json, confidence, reasoning_text, status))
                conn.commit()
                row = cur.fetchone()
                result = dict(row) if row else {}
                # Also add pr_number alias so agents can read it back
                if request_data.get('pr_number'):
                    result['pr_number'] = request_data['pr_number']
                return result
        except Exception as e:
            logger.error("create_pending_approval failed: %s", e)
            if conn: conn.rollback()
            return {}
        finally:
            if conn: conn.close()

    def update_approval_status(self, approval_id, status: str, notes: str = '') -> dict:
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE pending_approvals
                    SET status = %s, reviewed_at = NOW(), review_notes = %s
                    WHERE approval_id = %s
                    RETURNING *
                """, (status, notes, str(approval_id)))
                conn.commit()
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("update_approval_status failed: %s", e)
            if conn: conn.rollback()
            return {}
        finally:
            if conn: conn.close()

    def get_budget_tracking(self, department: str = None, category: str = None) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM budget_tracking
                    WHERE (%s IS NULL OR LOWER(TRIM(department))=LOWER(TRIM(%s)))
                      AND (%s IS NULL OR UPPER(TRIM(budget_category))=UPPER(TRIM(%s)))
                      AND fiscal_year = 2026
                    ORDER BY department, budget_category
                """, (department, department, category, category))
                return _rows(cur)
        except Exception as e:
            logger.error("get_budget_tracking failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def commit_budget(self, department: str, category: str, amount: float) -> dict:
        """Atomically reserve budget using row-level lock (SERIALIZABLE isolation)."""
        import psycopg2.extensions as ext
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            conn.set_isolation_level(ext.ISOLATION_LEVEL_SERIALIZABLE)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT available_budget, committed_budget
                    FROM budget_tracking
                    WHERE LOWER(TRIM(department))=LOWER(TRIM(%s))
                      AND UPPER(TRIM(budget_category))=UPPER(TRIM(%s))
                      AND fiscal_year=2026
                    FOR UPDATE
                """, (department, category))
                row = cur.fetchone()
                if not row:
                    return {'success': False, 'error': f'No budget for {department}/{category}'}
                if float(row['available_budget']) < amount:
                    conn.rollback()
                    return {'success': False, 'error': 'Insufficient budget',
                            'available': float(row['available_budget'])}
                cur.execute("""
                    UPDATE budget_tracking
                    SET committed_budget = committed_budget + %s, last_updated = NOW()
                    WHERE LOWER(TRIM(department))=LOWER(TRIM(%s))
                      AND UPPER(TRIM(budget_category))=UPPER(TRIM(%s))
                      AND fiscal_year=2026
                    RETURNING available_budget, committed_budget
                """, (amount, department, category))
                result = cur.fetchone()
                conn.commit()
                return {'success': True,
                        'available_budget': float(result['available_budget']),
                        'committed_budget': float(result['committed_budget'])}
        except Exception as e:
            logger.error("commit_budget failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def release_committed_budget(self, department: str, category: str, amount: float) -> dict:
        """Release previously committed budget (on PO cancel, PO reduce, or payment completion)."""
        import psycopg2.extensions as ext
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            conn.set_isolation_level(ext.ISOLATION_LEVEL_SERIALIZABLE)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE budget_tracking
                    SET committed_budget = GREATEST(committed_budget - %s, 0),
                        last_updated = NOW()
                    WHERE LOWER(TRIM(department))=LOWER(TRIM(%s))
                      AND UPPER(TRIM(budget_category))=UPPER(TRIM(%s))
                      AND fiscal_year=2026
                    RETURNING available_budget, committed_budget
                """, (amount, department, category))
                result = cur.fetchone()
                conn.commit()
                if result:
                    return {'success': True, 'released': amount,
                            'available_budget': float(result['available_budget']),
                            'committed_budget': float(result['committed_budget'])}
                return {'success': False, 'error': 'Budget row not found'}
        except Exception as e:
            logger.error("release_committed_budget failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def lock_fx_rate(self, document_type: str, document_number: str, from_currency: str, to_currency: str = 'AED') -> dict:
        """Lock FX rate at PO/invoice creation time for consistent payment calculation."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get current spot rate
                cur.execute("SELECT rate_to_aed FROM exchange_rates WHERE currency_code = %s", (from_currency,))
                rate_row = cur.fetchone()
                spot_rate = float(rate_row['rate_to_aed']) if rate_row else 1.0

                cur.execute("""
                    INSERT INTO fx_locked_rates (document_type, document_number, from_currency, to_currency, locked_rate, spot_rate)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (document_type, document_number) DO UPDATE SET locked_rate = EXCLUDED.locked_rate, spot_rate = EXCLUDED.spot_rate
                    RETURNING id, locked_rate
                """, (document_type, document_number, from_currency, to_currency, spot_rate, spot_rate))
                result = cur.fetchone()
                conn.commit()
                return {'success': True, 'locked_rate': float(result['locked_rate']), 'from': from_currency, 'to': to_currency}
        except Exception as e:
            logger.error("lock_fx_rate failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def get_locked_fx_rate(self, document_type: str, document_number: str) -> float:
        """Get previously locked FX rate for a document. Returns 0 if not locked."""
        from backend.services.nmi_data_service import get_conn
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT locked_rate FROM fx_locked_rates WHERE document_type = %s AND document_number = %s", (document_type, document_number))
                row = cur.fetchone()
                return float(row[0]) if row else 0.0
        except Exception:
            return 0.0
        finally:
            if conn: conn.close()

    def create_accrual(self, grn_number: str, po_number: str, vendor_name: str, amount: float, currency: str = 'USD') -> dict:
        """Create GRNi accrual when goods received but not yet invoiced."""
        from backend.services.nmi_data_service import get_conn
        from datetime import datetime
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                ref = "ACC-%s" % datetime.now().strftime("%Y%m%d%H%M%S")
                period = datetime.now().strftime("%Y-%m")
                cur.execute("""
                    INSERT INTO accruals (accrual_ref, grn_number, po_number, vendor_name, accrual_amount, currency, period, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'open')
                    ON CONFLICT (accrual_ref) DO NOTHING
                    RETURNING id
                """, (ref, grn_number, po_number, vendor_name, amount, currency, period))
                conn.commit()
                return {'success': True, 'accrual_ref': ref, 'amount': amount}
        except Exception as e:
            logger.error("create_accrual failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def reverse_accrual(self, grn_number: str, invoice_number: str) -> dict:
        """Reverse a GRNi accrual when the invoice arrives."""
        from backend.services.nmi_data_service import get_conn
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE accruals SET status = 'reversed', invoice_number = %s, reversed_at = NOW()
                    WHERE grn_number = %s AND status = 'open'
                    RETURNING accrual_ref
                """, (invoice_number, grn_number))
                rows = cur.fetchall()
                conn.commit()
                return {'success': True, 'reversed': len(rows)}
        except Exception as e:
            logger.error("reverse_accrual failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def create_debit_note(self, rtv_number: str, vendor_name: str, po_number: str, amount: float, reason: str = '') -> dict:
        """Auto-generate debit note when RTV is shipped."""
        from backend.services.nmi_data_service import get_conn
        from datetime import datetime
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                dn_number = "DN-%s" % datetime.now().strftime("%Y%m%d%H%M%S")
                cur.execute("""
                    INSERT INTO debit_notes (debit_note_number, rtv_number, vendor_name, po_number, amount, reason, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'issued')
                    RETURNING id
                """, (dn_number, rtv_number, vendor_name, po_number, amount, reason))
                conn.commit()
                return {'success': True, 'debit_note_number': dn_number, 'amount': amount}
        except Exception as e:
            logger.error("create_debit_note failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def store_risk_assessment(self, data: dict) -> dict:
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO po_risk_assessments (
                        odoo_po_id, pr_number,
                        total_risk_score, vendor_risk_score, financial_risk_score,
                        compliance_risk_score, operational_risk_score,
                        risk_level, risk_breakdown, mitigation_recommendations,
                        concerns_identified, recommended_action, decision_confidence,
                        blocked_po_creation, vendor_name, vendor_id,
                        budget_amount, department, category, urgency
                    ) VALUES (
                        %(odoo_po_id)s, %(pr_number)s,
                        %(total_risk_score)s, %(vendor_risk_score)s, %(financial_risk_score)s,
                        %(compliance_risk_score)s, %(operational_risk_score)s,
                        %(risk_level)s, %(risk_breakdown)s, %(mitigation_recommendations)s,
                        %(concerns_identified)s, %(recommended_action)s, %(decision_confidence)s,
                        %(blocked_po_creation)s, %(vendor_name)s, %(vendor_id)s,
                        %(budget_amount)s, %(department)s, %(category)s, %(urgency)s
                    ) RETURNING id, assessed_at
                """, {
                    **{k: data.get(k) for k in [
                        'odoo_po_id','pr_number','total_risk_score','vendor_risk_score',
                        'financial_risk_score','compliance_risk_score','operational_risk_score',
                        'risk_level','recommended_action','decision_confidence',
                        'blocked_po_creation','vendor_name','vendor_id',
                        'budget_amount','department','category','urgency']},
                    'risk_breakdown': _json.dumps(data.get('risk_breakdown', {})),
                    'mitigation_recommendations': _json.dumps(data.get('mitigation_recommendations', [])),
                    'concerns_identified': _json.dumps(data.get('concerns_identified', {})),
                })
                conn.commit()
                row = cur.fetchone()
                return {'success': True, 'id': row['id'],
                        'assessed_at': row['assessed_at'].isoformat()}
        except Exception as e:
            logger.error("store_risk_assessment failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def log_agent_action(self, agent_name: str, action_type: str,
                         input_data: dict, output_data: dict, success: bool) -> None:
        from backend.services.nmi_data_service import get_conn
        import json as _json
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO agent_actions
                      (agent_name, action_type, input_data, output_data, success)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)
                """, (agent_name, action_type,
                      _json.dumps(input_data), _json.dumps(output_data), success))
                conn.commit()
        except Exception as e:
            logger.error("log_agent_action failed: %s", e)
            if conn: conn.rollback()
        finally:
            if conn: conn.close()

    # ── Sprint-6 Pipeline Methods ──────────────────────────────────────────────

    def log_notification(self, data: dict) -> dict:
        """Insert a row into notification_log."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO notification_log
                      (event_type, document_type, document_id,
                       recipient_email, recipient_role, cc_email,
                       subject, body_preview, status, agent_name)
                    VALUES (%(event_type)s, %(document_type)s, %(document_id)s,
                            %(recipient_email)s, %(recipient_role)s, %(cc_email)s,
                            %(subject)s, %(body_preview)s,
                            %(status)s, %(agent_name)s)
                    RETURNING id, created_at
                """, {
                    'event_type':     data.get('event_type', 'unknown'),
                    'document_type':  data.get('document_type'),
                    'document_id':    data.get('document_id'),
                    'recipient_email': data.get('recipient_email', ''),
                    'recipient_role': data.get('recipient_role'),
                    'cc_email':       data.get('cc_email'),
                    'subject':        data.get('subject', '')[:500],
                    'body_preview':   (data.get('body', '') or '')[:500],
                    'status':         data.get('status', 'pending'),
                    'agent_name':     data.get('agent_name'),
                })
                conn.commit()
                row = cur.fetchone()
                return {'success': True, 'id': row['id'],
                        'created_at': row['created_at'].isoformat()}
        except Exception as e:
            logger.error("log_notification failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def mark_notification_sent(self, notification_id: int) -> None:
        """Mark a notification_log row as sent."""
        from backend.services.nmi_data_service import get_conn
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE notification_log
                    SET status='sent', sent_at=NOW()
                    WHERE id=%s
                """, (notification_id,))
                conn.commit()
        except Exception as e:
            logger.error("mark_notification_sent failed: %s", e)
            if conn: conn.rollback()
        finally:
            if conn: conn.close()

    def log_ocr_ingestion(self, data: dict) -> dict:
        """Insert OCR extraction result into ocr_ingestion_log."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO ocr_ingestion_log
                      (document_ref, document_type, source_channel, sender,
                       ocr_raw_text, extracted_fields, confidence_score,
                       needs_review, linked_po_number, linked_invoice_no, agent_name)
                    VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
                    RETURNING id, created_at
                """, (
                    data.get('document_ref'),
                    data.get('document_type', 'UNKNOWN'),
                    data.get('source_channel', 'unknown'),
                    data.get('sender'),
                    data.get('ocr_raw_text'),
                    _json.dumps(data.get('extracted_fields', {})),
                    data.get('confidence_score'),
                    data.get('needs_review', False),
                    data.get('linked_po_number'),
                    data.get('linked_invoice_no'),
                    data.get('agent_name'),
                ))
                conn.commit()
                row = cur.fetchone()
                return {'success': True, 'id': row['id'],
                        'created_at': row['created_at'].isoformat()}
        except Exception as e:
            logger.error("log_ocr_ingestion failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def log_discrepancy(self, data: dict) -> dict:
        """Insert a discrepancy_log record."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO discrepancy_log
                      (invoice_number, po_number, grn_number, discrepancy_type,
                       po_value, invoice_value, grn_value,
                       variance_amount, variance_pct, description,
                       status, agent_name)
                    VALUES (%(invoice_number)s,%(po_number)s,%(grn_number)s,
                            %(discrepancy_type)s,%(po_value)s,%(invoice_value)s,
                            %(grn_value)s,%(variance_amount)s,%(variance_pct)s,
                            %(description)s,%(status)s,%(agent_name)s)
                    RETURNING id, created_at
                """, {
                    'invoice_number':   data.get('invoice_number', ''),
                    'po_number':        data.get('po_number'),
                    'grn_number':       data.get('grn_number'),
                    'discrepancy_type': data.get('discrepancy_type', 'other'),
                    'po_value':         data.get('po_value'),
                    'invoice_value':    data.get('invoice_value'),
                    'grn_value':        data.get('grn_value'),
                    'variance_amount':  data.get('variance_amount'),
                    'variance_pct':     data.get('variance_pct'),
                    'description':      data.get('description'),
                    'status':           data.get('status', 'open'),
                    'agent_name':       data.get('agent_name'),
                })
                conn.commit()
                row = cur.fetchone()
                return {'success': True, 'id': row['id']}
        except Exception as e:
            logger.error("log_discrepancy failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def get_discrepancies(self, invoice_number: str = None,
                          status: str = None, limit: int = 50) -> list:
        """Return discrepancy_log rows."""
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM discrepancy_log
                    WHERE (%s IS NULL OR invoice_number=%s)
                      AND (%s IS NULL OR status=%s)
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (invoice_number, invoice_number, status, status, limit))
                return _rows(cur)
        except Exception as e:
            logger.error("get_discrepancies failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def resolve_discrepancy(self, discrepancy_id: int,
                             resolution_notes: str, resolved_by: str) -> dict:
        """Mark a discrepancy as resolved."""
        from backend.services.nmi_data_service import get_conn
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE discrepancy_log
                    SET status='resolved', resolution_notes=%s,
                        resolved_by=%s, resolved_at=NOW(), updated_at=NOW()
                    WHERE id=%s
                """, (resolution_notes, resolved_by, discrepancy_id))
                conn.commit()
            return {'success': True}
        except Exception as e:
            logger.error("resolve_discrepancy failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def place_invoice_hold(self, data: dict) -> dict:
        """Insert an invoice_holds record."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO invoice_holds
                      (invoice_number, po_number, hold_reason, hold_notes,
                       placed_by, agent_name)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    RETURNING id, placed_at
                """, (
                    data.get('invoice_number', ''),
                    data.get('po_number'),
                    data.get('hold_reason', 'other'),
                    data.get('hold_notes'),
                    data.get('placed_by', 'system'),
                    data.get('agent_name'),
                ))
                conn.commit()
                row = cur.fetchone()
                return {'success': True, 'id': row['id'],
                        'placed_at': row['placed_at'].isoformat()}
        except Exception as e:
            logger.error("place_invoice_hold failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def release_invoice_hold(self, invoice_number: str, resolved_by: str) -> dict:
        """Release all active holds on an invoice."""
        from backend.services.nmi_data_service import get_conn
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE invoice_holds
                    SET status='released', resolved_by=%s, resolved_at=NOW()
                    WHERE invoice_number=%s AND status='active'
                """, (resolved_by, invoice_number))
                conn.commit()
            return {'success': True}
        except Exception as e:
            logger.error("release_invoice_hold failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def get_active_holds(self, invoice_number: str = None) -> list:
        """Return active invoice holds."""
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM invoice_holds
                    WHERE status='active'
                      AND (%s IS NULL OR invoice_number=%s)
                    ORDER BY placed_at DESC
                """, (invoice_number, invoice_number))
                return _rows(cur)
        except Exception as e:
            logger.error("get_active_holds failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def create_payment_run(self, data: dict) -> dict:
        """Create (or update) a payment_runs record.

        Accepts either ``payment_run_id`` or ``payment_run_number`` as the
        business-key (agents use the latter; schema calls it the former).
        Uses ON CONFLICT DO UPDATE so that downstream pipeline steps (e.g.
        PaymentCalculationAgent) can safely call this again with the same run
        number to update the amount/status without causing a duplicate-key error.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            run_id_used = data.get('payment_run_id') or data.get('payment_run_number')
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO payment_runs
                      (payment_run_id, run_date, currency, total_amount,
                       invoice_count, status, payment_method, agent_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (payment_run_id) DO UPDATE SET
                      total_amount   = EXCLUDED.total_amount,
                      status         = EXCLUDED.status,
                      currency       = EXCLUDED.currency,
                      agent_name     = EXCLUDED.agent_name,
                      updated_at     = NOW()
                    RETURNING id, created_at
                """, (
                    run_id_used,
                    data.get('run_date'),
                    data.get('currency', 'AED'),
                    data.get('total_amount', 0),
                    data.get('invoice_count', 0),
                    data.get('status', 'draft'),
                    data.get('payment_method'),
                    data.get('agent_name'),
                ))
                conn.commit()
                row = cur.fetchone()
                return {
                    'success': True,
                    'id': row['id'] if row else None,
                    'payment_run_number': run_id_used,
                    'payment_run_id': run_id_used,
                }
        except Exception as e:
            logger.error("create_payment_run failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def get_email_template(self, event_type: str) -> dict:
        """Return email_templates row for a given event_type."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM email_templates
                    WHERE event_type=%s AND is_active=TRUE
                """, (event_type,))
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("get_email_template failed: %s", e)
            return {}
        finally:
            if conn: conn.close()

    def get_users_by_role(self, role: str) -> list:
        """Return active users matching a role."""
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM users
                    WHERE role=%s AND is_active=TRUE
                    ORDER BY full_name
                """, (role,))
                return _rows(cur)
        except Exception as e:
            logger.error("get_users_by_role failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    # ── UAT-003: Approval Workflow (replaces hardcoded psycopg2 in agent) ─────

    def get_approval_workflow(self, pr_number: str) -> dict:
        """Return an existing approval workflow by PR number, or {} if not found."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM pr_approval_workflows WHERE pr_number = %s",
                    (pr_number,)
                )
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("get_approval_workflow failed: %s", e)
            return {}
        finally:
            if conn: conn.close()

    def create_approval_workflow(self, data: dict) -> dict:
        """
        Insert a row into pr_approval_workflows.
        Returns {'success': True, 'workflow_id': <pr_number>} on success.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO pr_approval_workflows
                      (pr_number, department, total_amount, requester_name,
                       request_data, current_approval_level, workflow_status,
                       created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, NOW(), NOW())
                    ON CONFLICT (pr_number) DO NOTHING
                    RETURNING pr_number
                """, (
                    data.get('pr_number'),
                    data.get('department'),
                    data.get('total_amount', 0),
                    data.get('requester_name', ''),
                    _json.dumps(data.get('request_data', {})),
                    data.get('current_approval_level', 1),
                    data.get('workflow_status', 'in_progress'),
                ))
                conn.commit()
                row = cur.fetchone()
                if row:
                    return {'success': True, 'workflow_id': row['pr_number']}
                # ON CONFLICT → already existed
                return {'success': True, 'workflow_id': data.get('pr_number'),
                        'message': 'Workflow already existed'}
        except Exception as e:
            logger.error("create_approval_workflow failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def create_approval_step(self, data: dict) -> dict:
        """Insert a row into pr_approval_steps."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO pr_approval_steps
                      (pr_number, approval_level, approver_name, approver_email, status)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    data.get('pr_number'),
                    data.get('approval_level'),
                    data.get('approver_name'),
                    data.get('approver_email'),
                    data.get('status', 'pending'),
                ))
                conn.commit()
                row = cur.fetchone()
                return {'success': True, 'id': row['id']}
        except Exception as e:
            logger.error("create_approval_step failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    # ── Layer 1: Execution Session Orchestration (P0) ─────────────────────────
    # CRUD for execution_sessions / session_events / session_gates / session_snapshots.
    # Called ONLY from backend/services/session_service.py (single-writer rule).
    # Never called directly from agents, routes, or tools.

    def insert_execution_session(self, data: dict) -> dict:
        """
        Insert a new execution_sessions row. Idempotent via request_fingerprint —
        ON CONFLICT (request_fingerprint) returns the existing row rather than
        creating a duplicate. This is the R4 guarantee.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO execution_sessions
                      (session_kind, initiated_by_user_id, request_fingerprint,
                       request_summary, workflow_run_id)
                    VALUES (%s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (request_fingerprint) DO NOTHING
                    RETURNING *
                """, (
                    data.get('session_kind'),
                    data.get('initiated_by_user_id'),
                    data.get('request_fingerprint'),
                    _json.dumps(data.get('request_summary') or {}),
                    data.get('workflow_run_id'),
                ))
                row = cur.fetchone()
                if row:
                    conn.commit()
                    return {'success': True, 'session': dict(row), 'created': True}
                # Conflict: fetch the existing row for idempotent return
                cur.execute(
                    "SELECT * FROM execution_sessions WHERE request_fingerprint = %s",
                    (data.get('request_fingerprint'),)
                )
                existing = cur.fetchone()
                return {'success': True, 'session': dict(existing) if existing else {},
                        'created': False}
        except Exception as e:
            logger.error("insert_execution_session failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def get_execution_session(self, session_id: str) -> dict:
        """Return an execution_sessions row by session_id, or {} if not found."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM execution_sessions WHERE session_id = %s",
                    (session_id,)
                )
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("get_execution_session failed: %s", e)
            return {}
        finally:
            if conn: conn.close()

    def get_execution_session_by_fingerprint(self, request_fingerprint: str) -> dict:
        """Return an execution_sessions row by request_fingerprint, or {}."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM execution_sessions WHERE request_fingerprint = %s",
                    (request_fingerprint,)
                )
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("get_execution_session_by_fingerprint failed: %s", e)
            return {}
        finally:
            if conn: conn.close()

    def get_execution_session_by_workflow_run_id(self, workflow_run_id: str) -> dict:
        """
        Return the most recent execution_sessions row attached to a workflow_run_id.
        Used by the legacy /api/agentic/p2p/resume proxy to locate the session
        for a workflow that was created before session_id was surfaced to callers.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM execution_sessions "
                    "WHERE workflow_run_id = %s "
                    "ORDER BY created_at DESC LIMIT 1",
                    (workflow_run_id,)
                )
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("get_execution_session_by_workflow_run_id failed: %s", e)
            return {}
        finally:
            if conn: conn.close()

    def update_execution_session_workflow_run_id(self, session_id: str, workflow_run_id: str) -> dict:
        """
        Attach a workflow_run_id to an existing execution_sessions row.
        Called once, right after the underlying workflow_run is created, so
        the legacy p2p/resume proxy can later look up the session by workflow_run_id.
        """
        from backend.services.nmi_data_service import get_conn
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE execution_sessions "
                    "SET workflow_run_id = %s, updated_at = NOW() "
                    "WHERE session_id = %s",
                    (workflow_run_id, session_id)
                )
                conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error("update_execution_session_workflow_run_id failed: %s", e)
            if conn:
                try: conn.rollback()
                except Exception: pass
            return {"success": False, "error": str(e)}
        finally:
            if conn: conn.close()

    def list_execution_sessions(self, user_id: str = None, status: str = None,
                                kind: str = None, limit: int = 50) -> list:
        """Return filtered execution_sessions ordered by created_at DESC."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                clauses, params = [], []
                if user_id:
                    clauses.append("initiated_by_user_id = %s")
                    params.append(user_id)
                if status:
                    clauses.append("current_status = %s")
                    params.append(status)
                if kind:
                    clauses.append("session_kind = %s")
                    params.append(kind)
                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                params.append(int(limit))
                cur.execute(
                    f"SELECT * FROM execution_sessions {where} "
                    f"ORDER BY created_at DESC LIMIT %s",
                    tuple(params)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("list_execution_sessions failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def update_execution_session_phase(self, session_id: str, new_phase: str,
                                       new_status: str, expected_version: int) -> dict:
        """
        Atomically update current_phase/current_status using optimistic concurrency.
        The row is updated only if its current version matches expected_version;
        this prevents two concurrent writers from interleaving transitions.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE execution_sessions
                    SET current_phase = %s,
                        current_status = %s,
                        version = version + 1,
                        updated_at = NOW(),
                        completed_at = CASE
                            WHEN %s IN ('completed','failed','cancelled') THEN NOW()
                            ELSE completed_at
                        END
                    WHERE session_id = %s AND version = %s
                    RETURNING *
                """, (new_phase, new_status, new_status, session_id, expected_version))
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return {'success': False,
                            'error': 'version_conflict_or_not_found'}
                conn.commit()
                return {'success': True, 'session': dict(row)}
        except Exception as e:
            logger.error("update_execution_session_phase failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def append_session_event(self, session_id: str, event_type: str, actor: str,
                             payload: dict, caused_by_event_id: str = None) -> dict:
        """
        Append an event to session_events under ONE transaction that also
        bumps execution_sessions.last_event_sequence. Guarantees:
          - monotonic per-session sequence numbers (no gaps)
          - no event visible to listeners until the row is committed
          - NOTIFY fires automatically via the AFTER INSERT trigger
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json
        conn = None
        try:
            conn = get_conn()
            conn.autocommit = False
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1) Atomically increment last_event_sequence and read the new value
                cur.execute("""
                    UPDATE execution_sessions
                    SET last_event_sequence = last_event_sequence + 1,
                        updated_at = NOW()
                    WHERE session_id = %s
                    RETURNING last_event_sequence
                """, (session_id,))
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return {'success': False, 'error': 'session_not_found'}
                next_seq = row['last_event_sequence']

                # 2) Insert the event with the freshly allocated sequence_number
                cur.execute("""
                    INSERT INTO session_events
                      (session_id, sequence_number, event_type, actor,
                       payload, caused_by_event_id)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING event_id, sequence_number, created_at
                """, (
                    session_id, next_seq, event_type, actor,
                    _json.dumps(payload or {}),
                    caused_by_event_id,
                ))
                ev = cur.fetchone()

                # 3) HF-4 / R8 / R19 — optional snapshot write. SAVEPOINT-guarded
                # so a snapshot failure is logged but does NOT abort the event
                # write. Events are authoritative; snapshots are derived data
                # that can be rebuilt by a replay at any time.
                if _should_snapshot(event_type, int(ev['sequence_number'])):
                    try:
                        cur.execute("SAVEPOINT snap_sp")
                        state = _fold_session_state_from_cur(
                            cur, session_id, int(ev['sequence_number'])
                        )
                        if state:
                            content_hash = _canonical_state_hash(state)
                            cur.execute("""
                                INSERT INTO session_snapshots
                                  (session_id, at_sequence_number, state, content_hash)
                                VALUES (%s, %s, %s::jsonb, %s)
                                ON CONFLICT (session_id, at_sequence_number) DO NOTHING
                            """, (
                                session_id, int(ev['sequence_number']),
                                _json.dumps(state, default=str), content_hash,
                            ))
                            cur.execute("""
                                UPDATE execution_sessions
                                SET snapshot_version = snapshot_version + 1
                                WHERE session_id = %s
                            """, (session_id,))
                        cur.execute("RELEASE SAVEPOINT snap_sp")
                    except Exception as _snap_err:
                        logger.warning(
                            "session_snapshot write failed at seq=%s (non-fatal): %s",
                            ev['sequence_number'], _snap_err,
                        )
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT snap_sp")
                            cur.execute("RELEASE SAVEPOINT snap_sp")
                        except Exception:
                            pass

                conn.commit()
                return {
                    'success': True,
                    'event_id': str(ev['event_id']),
                    'sequence_number': ev['sequence_number'],
                    'created_at': ev['created_at'].isoformat() if ev.get('created_at') else None,
                }
        except Exception as e:
            logger.error("append_session_event failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn:
                try:
                    conn.autocommit = True
                except Exception:
                    pass
                conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    # HF-2 / R12 — Transactional outbox support
    # ─────────────────────────────────────────────────────────────────────────

    def begin_tx(self):
        """
        Return a fresh psycopg2 connection with autocommit=False. Caller is
        responsible for conn.commit() / conn.rollback() / conn.close().

        Intended for use with SessionService.append_event_tx and any ERP
        write that must commit atomically with an event emission (R12).

        Most callers should prefer the `transaction()` async context manager
        on this adapter, which wraps this primitive with commit/rollback/close.
        """
        from backend.services.nmi_data_service import get_conn
        conn = get_conn()
        conn.autocommit = False
        return conn

    def transaction(self):
        """
        Async context manager yielding a psycopg2 connection with
        autocommit=False. Commits on clean exit, rolls back on exception,
        always closes.

        Usage:
            async with adapter.transaction() as conn:
                adapter.create_purchase_order_from_pr_tx(conn, data)
                SessionService.append_event_tx(conn, session_id, ...)
            # commit + close happened here
        """
        import contextlib

        @contextlib.asynccontextmanager
        async def _cm():
            conn = self.begin_tx()
            try:
                yield conn
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                try:
                    conn.autocommit = True
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        return _cm()

    def append_session_event_outbox_tx(self, conn, session_id: str,
                                        event_type: str, actor: str,
                                        payload: dict,
                                        caused_by_event_id: str = None) -> dict:
        """
        Outbox variant of append_session_event. Uses the caller's connection
        (does NOT open a new one, does NOT commit). Writes to session_event_outbox
        only — the outbox pump is responsible for moving the row to session_events
        and firing NOTIFY.

        Guarantees:
          - Same-transaction semantics with whatever the caller is doing
            (ERP write + event append commit together or roll back together).
          - Monotonic per-session sequence numbers via UPDATE ... RETURNING.
          - No event visible to SSE listeners until the pump publishes it.

        Returns {success, outbox_id, sequence_number} or {success: False, error}.
        """
        from psycopg2.extras import RealDictCursor
        import json as _json
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1) Atomically increment last_event_sequence and read the new value
                cur.execute("""
                    UPDATE execution_sessions
                    SET last_event_sequence = last_event_sequence + 1,
                        updated_at = NOW()
                    WHERE session_id = %s
                    RETURNING last_event_sequence
                """, (session_id,))
                row = cur.fetchone()
                if not row:
                    return {'success': False, 'error': 'session_not_found'}
                next_seq = row['last_event_sequence']

                # 2) Insert into outbox using the same sequence number
                cur.execute("""
                    INSERT INTO session_event_outbox
                      (session_id, sequence_number, event_type, actor,
                       payload, caused_by_event_id)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING outbox_id, sequence_number, created_at
                """, (
                    session_id, next_seq, event_type, actor,
                    _json.dumps(payload or {}),
                    caused_by_event_id,
                ))
                ev = cur.fetchone()
                return {
                    'success': True,
                    'outbox_id': str(ev['outbox_id']),
                    'sequence_number': ev['sequence_number'],
                    'created_at': ev['created_at'].isoformat() if ev.get('created_at') else None,
                }
        except Exception as e:
            logger.error("append_session_event_outbox_tx failed: %s", e)
            # Do NOT rollback here — that's the caller's responsibility since
            # they may have other work in this transaction that must also roll back.
            return {'success': False, 'error': str(e)}

    def pump_outbox_once(self, batch_size: int = 100) -> dict:
        """
        Outbox pump: publish a batch of uncommitted outbox rows to session_events.

        Uses SELECT ... FOR UPDATE SKIP LOCKED so multiple pump workers (if we
        ever run more than one) do not conflict. Each row is inserted into
        session_events (which fires NOTIFY via the trigger) and then marked
        committed. Both writes happen in the same transaction — if either
        fails, neither side moves forward.

        Returns {success, published, stuck_count} for observability.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json

        published = 0
        conn = None
        try:
            conn = get_conn()
            conn.autocommit = False
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Select next batch of uncommitted rows, locked so another
                # pump iteration can't grab them simultaneously.
                cur.execute("""
                    SELECT outbox_id, session_id, sequence_number, event_type,
                           actor, payload, caused_by_event_id
                    FROM session_event_outbox
                    WHERE committed_at IS NULL
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                """, (int(batch_size),))
                rows = cur.fetchall()

                for row in rows:
                    # Insert into session_events using the SAME sequence_number
                    # that append_session_event_outbox_tx already allocated.
                    # The NOTIFY trigger on session_events fires here, making
                    # the event visible to SSE listeners.
                    try:
                        cur.execute("""
                            INSERT INTO session_events
                              (session_id, sequence_number, event_type, actor,
                               payload, caused_by_event_id)
                            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                            ON CONFLICT (session_id, sequence_number) DO NOTHING
                        """, (
                            row['session_id'],
                            row['sequence_number'],
                            row['event_type'],
                            row['actor'],
                            _json.dumps(row['payload'] or {}),
                            row['caused_by_event_id'],
                        ))
                        cur.execute("""
                            UPDATE session_event_outbox
                            SET committed_at = NOW()
                            WHERE outbox_id = %s
                        """, (row['outbox_id'],))

                        # HF-4 / R8 / R19 — snapshot write, SAVEPOINT-guarded.
                        # The pump publishes events that were durably written
                        # to the outbox before a crash, so snapshotting them
                        # here gives the same atomicity guarantee as the
                        # non-tx append path above. A snapshot failure is
                        # logged but does NOT abort the outbox publish.
                        if _should_snapshot(row['event_type'], int(row['sequence_number'])):
                            try:
                                cur.execute("SAVEPOINT snap_sp")
                                state = _fold_session_state_from_cur(
                                    cur, str(row['session_id']),
                                    int(row['sequence_number']),
                                )
                                if state:
                                    content_hash = _canonical_state_hash(state)
                                    cur.execute("""
                                        INSERT INTO session_snapshots
                                          (session_id, at_sequence_number, state, content_hash)
                                        VALUES (%s, %s, %s::jsonb, %s)
                                        ON CONFLICT (session_id, at_sequence_number) DO NOTHING
                                    """, (
                                        row['session_id'],
                                        int(row['sequence_number']),
                                        _json.dumps(state, default=str),
                                        content_hash,
                                    ))
                                    cur.execute("""
                                        UPDATE execution_sessions
                                        SET snapshot_version = snapshot_version + 1
                                        WHERE session_id = %s
                                    """, (row['session_id'],))
                                cur.execute("RELEASE SAVEPOINT snap_sp")
                            except Exception as _snap_err:
                                logger.warning(
                                    "pump_outbox_once: snapshot write failed "
                                    "at seq=%s (non-fatal): %s",
                                    row.get('sequence_number'), _snap_err,
                                )
                                try:
                                    cur.execute("ROLLBACK TO SAVEPOINT snap_sp")
                                    cur.execute("RELEASE SAVEPOINT snap_sp")
                                except Exception:
                                    pass

                        published += 1
                    except Exception as row_exc:
                        logger.error("pump_outbox_once: row %s publish failed: %s",
                                     row.get('outbox_id'), row_exc)
                        # Continue with other rows — the failed one stays
                        # uncommitted and will be retried next iteration.
                        conn.rollback()
                        conn.autocommit = False
                        continue

                conn.commit()

                # Observability: count rows stuck longer than 60s (R12 health signal)
                cur.execute("""
                    SELECT COUNT(*) AS stuck FROM session_event_outbox
                    WHERE committed_at IS NULL
                      AND created_at < NOW() - INTERVAL '60 seconds'
                """)
                stuck_row = cur.fetchone()
                stuck_count = stuck_row['stuck'] if stuck_row else 0

            return {'success': True, 'published': published, 'stuck_count': stuck_count}
        except Exception as e:
            logger.error("pump_outbox_once failed: %s", e)
            if conn:
                try: conn.rollback()
                except Exception: pass
            return {'success': False, 'published': published, 'error': str(e)}
        finally:
            if conn:
                try:
                    conn.autocommit = True
                except Exception:
                    pass
                conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    # HF-4 / R8 / R19 — Session snapshots for bounded SSE replay cost
    # ─────────────────────────────────────────────────────────────────────────

    def write_session_snapshot_tx(self, conn, session_id: str,
                                   at_sequence_number: int) -> dict:
        """
        Write a session_snapshots row using the caller's connection.

        R19: the snapshot is written in the SAME transaction as the triggering
        event so a crash between the event INSERT and the snapshot INSERT is
        impossible. ON CONFLICT DO NOTHING makes duplicate calls for the same
        sequence_number idempotent (safe under retries).

        The snapshot stores the folded state up to at_sequence_number plus a
        SHA-256 content_hash for corruption detection on replay.

        Returns {success, snapshot_id, at_sequence_number, content_hash, duplicate}.
        """
        from psycopg2.extras import RealDictCursor
        import json as _json
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                state = _fold_session_state_from_cur(cur, session_id, at_sequence_number)
                if not state:
                    return {"success": False, "error": "session_not_found"}
                content_hash = _canonical_state_hash(state)
                cur.execute("""
                    INSERT INTO session_snapshots
                      (session_id, at_sequence_number, state, content_hash)
                    VALUES (%s, %s, %s::jsonb, %s)
                    ON CONFLICT (session_id, at_sequence_number) DO NOTHING
                    RETURNING snapshot_id
                """, (
                    session_id, int(at_sequence_number),
                    _json.dumps(state, default=str), content_hash,
                ))
                row = cur.fetchone()
                if row:
                    cur.execute("""
                        UPDATE execution_sessions
                        SET snapshot_version = snapshot_version + 1
                        WHERE session_id = %s
                    """, (session_id,))
                return {
                    "success": True,
                    "snapshot_id": str(row["snapshot_id"]) if row else None,
                    "at_sequence_number": int(at_sequence_number),
                    "content_hash": content_hash,
                    "duplicate": row is None,
                }
        except Exception as e:
            logger.error("write_session_snapshot_tx failed: %s", e)
            return {"success": False, "error": str(e)}

    def get_latest_snapshot(self, session_id: str,
                             at_or_before_seq: int = None) -> dict:
        """
        Return the latest session_snapshots row for a session, optionally
        filtered to snapshots taken at or before a specific sequence number.

        Used by the SSE replay endpoint to skip replay of events 0..N when
        a snapshot exists at N. Returns {} if no snapshot exists.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if at_or_before_seq is None:
                    cur.execute("""
                        SELECT snapshot_id, session_id, at_sequence_number,
                               state, content_hash, created_at
                        FROM session_snapshots
                        WHERE session_id = %s
                        ORDER BY at_sequence_number DESC
                        LIMIT 1
                    """, (session_id,))
                else:
                    cur.execute("""
                        SELECT snapshot_id, session_id, at_sequence_number,
                               state, content_hash, created_at
                        FROM session_snapshots
                        WHERE session_id = %s AND at_sequence_number <= %s
                        ORDER BY at_sequence_number DESC
                        LIMIT 1
                    """, (session_id, int(at_or_before_seq)))
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("get_latest_snapshot failed: %s", e)
            return {}
        finally:
            if conn: conn.close()

    def verify_snapshot_hash(self, session_id: str,
                              at_sequence_number: int,
                              expected_hash: str) -> bool:
        """
        Recompute the snapshot's content_hash from session_events and compare
        to the stored hash. Used by the SSE endpoint to detect silent snapshot
        corruption (R19) before serving a snapshot to a client.

        Returns True iff the recomputed hash matches the expected hash.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                state = _fold_session_state_from_cur(cur, session_id, at_sequence_number)
                if not state:
                    return False
                return _canonical_state_hash(state) == expected_hash
        except Exception as e:
            logger.error("verify_snapshot_hash failed: %s", e)
            return False
        finally:
            if conn: conn.close()

    def list_session_events(self, session_id: str, since_sequence: int = 0,
                            limit: int = 1000) -> list:
        """Return session_events ordered by sequence_number ASC."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT event_id, session_id, sequence_number, event_type,
                           actor, payload, caused_by_event_id, created_at
                    FROM session_events
                    WHERE session_id = %s AND sequence_number > %s
                    ORDER BY sequence_number ASC
                    LIMIT %s
                """, (session_id, int(since_sequence), int(limit)))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("list_session_events failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def insert_session_gate(self, data: dict) -> dict:
        """Insert a session_gates row. Returns the full created row."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO session_gates
                      (session_id, gate_type, gate_ref, decision_context, required_role)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)
                    RETURNING *
                """, (
                    data.get('session_id'),
                    data.get('gate_type'),
                    _json.dumps(data.get('gate_ref') or {}),
                    _json.dumps(data.get('decision_context') or {}),
                    data.get('required_role'),
                ))
                row = cur.fetchone()
                conn.commit()
                return {'success': True, 'gate': dict(row)}
        except Exception as e:
            logger.error("insert_session_gate failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def get_session_gate(self, gate_id: str) -> dict:
        """Return a session_gates row by gate_id, or {}."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM session_gates WHERE gate_id = %s",
                    (gate_id,)
                )
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("get_session_gate failed: %s", e)
            return {}
        finally:
            if conn: conn.close()

    def list_session_gates(self, session_id: str = None, status: str = None,
                           gate_type: str = None) -> list:
        """Return filtered session_gates ordered by created_at DESC."""
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                clauses, params = [], []
                if session_id:
                    clauses.append("session_id = %s")
                    params.append(session_id)
                if status:
                    clauses.append("status = %s")
                    params.append(status)
                if gate_type:
                    clauses.append("gate_type = %s")
                    params.append(gate_type)
                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                cur.execute(
                    f"SELECT * FROM session_gates {where} "
                    f"ORDER BY created_at DESC",
                    tuple(params)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("list_session_gates failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def resolve_session_gate(self, gate_id: str, decision: dict,
                             resolved_by: str, gate_resolution_id: str) -> dict:
        """
        Resolve a gate idempotently via gate_resolution_id (R13).
        If this (gate_id, gate_resolution_id) pair has already been applied,
        return the prior stored decision without modifying state.
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Idempotency check: same gate_id + gate_resolution_id → return prior row
                cur.execute("""
                    SELECT * FROM session_gates
                    WHERE gate_id = %s AND gate_resolution_id = %s
                """, (gate_id, gate_resolution_id))
                existing = cur.fetchone()
                if existing:
                    return {'success': True, 'gate': dict(existing),
                            'idempotent_replay': True}

                # Fresh resolution: only resolve if still pending
                cur.execute("""
                    UPDATE session_gates
                    SET status = 'resolved',
                        decision = %s::jsonb,
                        resolved_by = %s,
                        resolved_at = NOW(),
                        gate_resolution_id = %s
                    WHERE gate_id = %s AND status = 'pending'
                    RETURNING *
                """, (
                    _json.dumps(decision or {}),
                    resolved_by,
                    gate_resolution_id,
                    gate_id,
                ))
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    return {'success': False,
                            'error': 'gate_not_found_or_already_resolved'}
                conn.commit()
                return {'success': True, 'gate': dict(row),
                        'idempotent_replay': False}
        except Exception as e:
            logger.error("resolve_session_gate failed: %s", e)
            if conn: conn.rollback()
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    # ── Write operations ──────────────────────────────────────────────────────

    def create_purchase_order_from_pr(self, data: dict) -> dict:
        """Create a PO in the ERP-specific PO table from an approved PR.

        Resolves the correct table via _TABLE_MAP (e.g., demo_odoo → odoo_purchase_orders).
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        from datetime import datetime
        import time as _time

        table = _resolve_table('po_headers')  # e.g., odoo_purchase_orders
        po_number = f"PO-{datetime.now().strftime('%Y-%m%d%H%M%S')}"
        pr_number = data.get('pr_number', '')
        vendor = data.get('vendor_name', 'Unknown Vendor')
        product = data.get('product_name', '')
        quantity = float(data.get('quantity', 0) or 0)
        unit_price = float(data.get('unit_price', 0) or 0)
        total = float(data.get('total_amount', 0) or 0)
        if total == 0 and quantity > 0 and unit_price > 0:
            total = quantity * unit_price
        currency = data.get('currency', 'USD')
        department = data.get('department', '')

        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get column names from the target table
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = %s AND table_schema = 'public'
                    AND column_name != '_row_id'
                    ORDER BY ordinal_position LIMIT 5
                """, (table,))
                cols = [r['column_name'] for r in cur.fetchall()]

                # Build INSERT dynamically based on available columns
                # Most ERP PO tables have: id/name, partner_id/vendor, amount, state/status, date
                suffix = _get_erp_suffix()

                if suffix == 'odoo':
                    cur.execute(f"""
                        INSERT INTO {table} (name, partner_id, currency_id, date_order,
                            amount_total, state, product_id, product_qty)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (po_number, vendor, currency, datetime.now().strftime('%Y-%m-%d'),
                          total, 'purchase', product, quantity))
                elif suffix == 'sap':
                    # SAP uses numeric PO numbers (EBELN is INTEGER)
                    sap_po_num = int(_time.time()) % 1000000000
                    po_number = str(sap_po_num)
                    cur.execute(f"""
                        INSERT INTO {table} (ebeln, lifnr, bedat, waers, netwr, werks, matnr, menge, meins, netpr)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (sap_po_num, vendor, datetime.now().strftime('%Y-%m-%d'),
                          currency, total, department, product, quantity, 'EA', unit_price))
                elif suffix == 'd365':
                    cur.execute(f"""
                        INSERT INTO {table} (purchid, vendaccount, purchstatus, currencycode,
                            orderdate, purchamount, itemid, purchqty)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (po_number, vendor, 'Confirmed', currency,
                          datetime.now().strftime('%Y-%m-%d'), total, product, quantity))
                elif suffix == 'oracle':
                    cur.execute(f"""
                        INSERT INTO {table} (po_number, vendor_id, currency_code, creation_date,
                            approved_date, amount, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (po_number, vendor, currency, datetime.now().strftime('%Y-%m-%d'),
                          datetime.now().strftime('%Y-%m-%d'), total, 'APPROVED'))
                elif suffix == 'erpnext':
                    cur.execute(f"""
                        INSERT INTO {table} (name, supplier, transaction_date, currency,
                            grand_total, status, item_code, qty)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (po_number, vendor, datetime.now().strftime('%Y-%m-%d'),
                          currency, total, 'Submitted', product, quantity))
                else:
                    # Generic fallback
                    cur.execute(f"""
                        INSERT INTO {table} (name, partner_id, amount_total, state)
                        VALUES (%s, %s, %s, %s)
                    """, (po_number, vendor, total, 'confirmed'))

                conn.commit()
                logger.info("PO created via adapter: %s in table %s (from PR %s)",
                           po_number, table, pr_number)
                return {
                    'success': True,
                    'po_number': po_number,
                    'po_id': po_number,
                    'table': table,
                    'pr_number': pr_number,
                }
        except Exception as e:
            logger.error("create_purchase_order_from_pr failed: %s", e)
            if conn:
                try: conn.rollback()
                except: pass
            return {'success': False, 'error': str(e)}
        finally:
            if conn: conn.close()

    def create_purchase_order_from_pr_tx(self, conn, data: dict) -> dict:
        """
        Transactional variant of create_purchase_order_from_pr (R12).

        Uses the caller's connection, does NOT commit, does NOT close. Intended
        to be called inside `async with adapter.transaction() as conn:` so the
        PO insert commits atomically with a SessionService.append_event_tx call
        on the same connection.

        Returns {success, po_number, po_id, table, pr_number} or {success: False, error}.
        Caller is responsible for rolling back the enclosing transaction on failure.
        """
        from psycopg2.extras import RealDictCursor
        from datetime import datetime
        import time as _time

        table = _resolve_table('po_headers')
        po_number = f"PO-{datetime.now().strftime('%Y-%m%d%H%M%S')}"
        pr_number = data.get('pr_number', '')
        vendor = data.get('vendor_name', 'Unknown Vendor')
        product = data.get('product_name', '')
        quantity = float(data.get('quantity', 0) or 0)
        unit_price = float(data.get('unit_price', 0) or 0)
        total = float(data.get('total_amount', 0) or 0)
        if total == 0 and quantity > 0 and unit_price > 0:
            total = quantity * unit_price
        currency = data.get('currency', 'USD')
        department = data.get('department', '')

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                suffix = _get_erp_suffix()

                if suffix == 'odoo':
                    cur.execute(f"""
                        INSERT INTO {table} (name, partner_id, currency_id, date_order,
                            amount_total, state, product_id, product_qty)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (po_number, vendor, currency, datetime.now().strftime('%Y-%m-%d'),
                          total, 'purchase', product, quantity))
                elif suffix == 'sap':
                    sap_po_num = int(_time.time()) % 1000000000
                    po_number = str(sap_po_num)
                    cur.execute(f"""
                        INSERT INTO {table} (ebeln, lifnr, bedat, waers, netwr, werks, matnr, menge, meins, netpr)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (sap_po_num, vendor, datetime.now().strftime('%Y-%m-%d'),
                          currency, total, department, product, quantity, 'EA', unit_price))
                elif suffix == 'd365':
                    cur.execute(f"""
                        INSERT INTO {table} (purchid, vendaccount, purchstatus, currencycode,
                            orderdate, purchamount, itemid, purchqty)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (po_number, vendor, 'Confirmed', currency,
                          datetime.now().strftime('%Y-%m-%d'), total, product, quantity))
                elif suffix == 'oracle':
                    cur.execute(f"""
                        INSERT INTO {table} (po_number, vendor_id, currency_code, creation_date,
                            approved_date, amount, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (po_number, vendor, currency, datetime.now().strftime('%Y-%m-%d'),
                          datetime.now().strftime('%Y-%m-%d'), total, 'APPROVED'))
                elif suffix == 'erpnext':
                    cur.execute(f"""
                        INSERT INTO {table} (name, supplier, transaction_date, currency,
                            grand_total, status, item_code, qty)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (po_number, vendor, datetime.now().strftime('%Y-%m-%d'),
                          currency, total, 'Submitted', product, quantity))
                else:
                    cur.execute(f"""
                        INSERT INTO {table} (name, partner_id, amount_total, state)
                        VALUES (%s, %s, %s, %s)
                    """, (po_number, vendor, total, 'confirmed'))

                logger.info(
                    "PO created via adapter (tx): %s in table %s (from PR %s)",
                    po_number, table, pr_number,
                )
                return {
                    'success': True,
                    'po_number': po_number,
                    'po_id': po_number,
                    'table': table,
                    'pr_number': pr_number,
                }
        except Exception as e:
            logger.error("create_purchase_order_from_pr_tx failed: %s", e)
            # Do NOT rollback here — the caller owns the transaction.
            return {'success': False, 'error': str(e)}

    def create_purchase_requisition(self, data: dict) -> dict:
        """
        Insert a PR into the procurement_records system table.
        Called by Orchestrator during PR creation workflow and InventoryCheckAgent for auto-reorder.

        Accepted keys in `data`:
            name (pr_number), user_id (requester), product_qty, state, origin (department),
            notes, erp_source
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json

        table = "procurement_records"  # System table — always in PostgreSQL
        pr_number = data.get("name") or data.get("pr_number") or f"PR-AUTO-{int(__import__('time').time())}"
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {table}
                        (pr_number, description, department, requester, amount, status, priority, budget_code)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        pr_number,
                        data.get("notes", data.get("product_name", "")),
                        data.get("origin", data.get("department", "")),
                        data.get("user_id", data.get("requester", "System")),
                        float(data.get("product_qty", 0) or 0),
                        data.get("state", data.get("status", "draft")),
                        data.get("priority", "medium"),
                        data.get("budget_code", data.get("budget_category", "")),
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return {"success": True, "pr_number": pr_number, "id": row["id"] if row else None}
        except Exception as e:
            logger.error("create_purchase_requisition failed: %s", e)
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return {"success": False, "error": str(e)}
        finally:
            if conn:
                conn.close()

    # ── System ────────────────────────────────────────────────────────────────

    def get_table_registry(self) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM table_registry ORDER BY module_code, table_name")
                return _rows(cur)
        except Exception as e:
            logger.error("get_table_registry failed: %s", e)
            return []
        finally:
            if conn:
                conn.close()
