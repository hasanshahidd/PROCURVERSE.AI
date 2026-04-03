"""
PostgreSQLAdapter — reads from PostgreSQL demo database.

DATA_SOURCE routing:
  postgresql  → neutral NMI tables (vendors, items, purchase_orders ...)
  odoo        → ERP-specific tables (vendors_odoo, po_headers_odoo ...)
  sap / sap_s4→ ERP-specific tables (vendors_sap_s4, po_headers_sap_s4 ...)
  sap_b1      → vendors_sap_b1, po_headers_sap_b1 ...
  dynamics    → vendors_dynamics, po_headers_dynamics ...
  oracle      → vendors_oracle, po_headers_oracle ...
  erpnext     → vendors_erpnext, po_headers_erpnext ...

When real ERP is connected → swap to OdooAdapter/SAPAdapter/etc. in factory.
PostgreSQLAdapter stays dormant. Zero agent code changes needed.
"""

import os, logging
from backend.services.adapters.base_adapter import IDataSourceAdapter
from backend.services import nmi_data_service as _db

logger = logging.getLogger(__name__)

# Map DATA_SOURCE value → ERP table suffix
_ERP_SUFFIX = {
    'odoo':     'odoo',
    'sap':      'sap_s4',
    'sap_s4':   'sap_s4',
    'sap_b1':   'sap_b1',
    'dynamics': 'dynamics',
    'oracle':   'oracle',
    'erpnext':  'erpnext',
}

# Neutral column → ERP-specific column name for key fields
_VENDOR_ID_COL = {
    'odoo':     'id',
    'sap_s4':   'lifnr',
    'sap_b1':   'cardcode',
    'dynamics': 'vendoraccount',
    'oracle':   'suppliernumber',
    'erpnext':  'name',
}
_VENDOR_NAME_COL = {
    'odoo':     'name',
    'sap_s4':   'name1',
    'sap_b1':   'cardname',
    'dynamics': 'organizationname',
    'oracle':   'supplier',
    'erpnext':  'supplier_name',
}
_PO_NUMBER_COL = {
    'odoo':     'name',
    'sap_s4':   'ebeln',
    'sap_b1':   'docnum',
    'dynamics': 'purchaseordernumber',
    'oracle':   'ponumber',
    'erpnext':  'name',
}


def _get_erp_suffix() -> str:
    src = os.environ.get('DATA_SOURCE', 'postgresql').lower()
    # Strip demo_ prefix so demo_odoo → odoo suffix, demo_sap_s4 → sap_s4 suffix, etc.
    if src.startswith('demo_'):
        src = src[5:]
    return _ERP_SUFFIX.get(src, '')


def _query_erp_table(table_base: str, where: str = '', params: tuple = (),
                     limit: int = 200) -> list:
    """Query an ERP-specific table (e.g. vendors_odoo) returning raw dicts."""
    from backend.services.nmi_data_service import get_conn, _rows
    from psycopg2.extras import RealDictCursor
    suffix = _get_erp_suffix()
    table = f'{table_base}_{suffix}'
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
        logger.error("_query_erp_table %s failed: %s", table, e)
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
                where = "WHERE active = TRUE" if active_only else ""
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
        return _db.get_nmi_vendor_quotes(limit=limit)

    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        return _db.get_nmi_vendor_quotes(item_name=item_name, limit=limit)

    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        suffix = _get_erp_suffix()
        if suffix:
            # Route to ERP-specific contracts table
            # Odoo: partner_id; SAP S4: lifnr; Oracle: suppliernumber; others: vendor_id
            vendor_col_map = {
                'odoo':     'partner_id',
                'sap_s4':   'lifnr',
                'sap_b1':   'vendor_code',
                'dynamics': 'vendoraccount',
                'oracle':   'suppliernumber',
                'erpnext':  'party',
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
                'sap_s4':   'ebeln',
                'sap_b1':   'baseref',
                'dynamics': 'purchaseordernumber',
                'oracle':   'ponumber',
                'erpnext':  'purchase_order',
            }
            grn_col_map = {
                'odoo':  'name',
                'sap_s4': 'mblnr',
                'sap_b1': 'docnum',
                'dynamics': 'receiptid',
                'oracle': 'receiptnum',
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
            # ERP invoice number column by source
            inv_col_map = {
                'odoo':     'name',
                'sap_s4':   'belnr',
                'sap_b1':   'docnum',
                'dynamics': 'invoicenumber',
                'oracle':   'invoicenumber',
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
                'odoo':     'partner_id',   # vendor_performance_odoo uses partner_id
                'sap_s4':   'lifnr',
                'sap_b1':   'cardcode',
                'dynamics': 'vendoraccount',
                'oracle':   'suppliernumber',
                'erpnext':  'vendor',
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

    def get_approval_rules(self, document_type: str = None, amount: float = None) -> list:
        from backend.services.nmi_data_service import get_conn, _rows
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if document_type and amount is not None:
                    cur.execute("""
                        SELECT * FROM approval_rules
                        WHERE (%s IS NULL OR LOWER(document_type)=LOWER(%s))
                          AND amount_min <= %s AND amount_max >= %s
                          AND status = 'active'
                        ORDER BY amount_min
                    """, (document_type, document_type, amount, amount))
                elif document_type:
                    cur.execute("""
                        SELECT * FROM approval_rules
                        WHERE LOWER(document_type)=LOWER(%s) AND status='active'
                        ORDER BY amount_min
                    """, (document_type,))
                else:
                    cur.execute("SELECT * FROM approval_rules WHERE status='active' ORDER BY document_type, amount_min")
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
                    ORDER BY id DESC
                """, (status, status))
                return _rows(cur)
        except Exception as e:
            logger.error("get_pending_approvals failed: %s", e)
            return []
        finally:
            if conn: conn.close()

    def create_pending_approval(self, data: dict) -> dict:
        import json as _json
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            # agent_decision column is JSONB — must receive valid JSON.
            # Agents may pass a plain string (reasoning text); wrap it in a dict.
            raw_decision = data.get('agent_decision')
            if isinstance(raw_decision, str):
                agent_decision_json = _json.dumps({"reasoning": raw_decision})
            elif raw_decision is None:
                agent_decision_json = _json.dumps({})
            else:
                agent_decision_json = _json.dumps(raw_decision)

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO pending_approvals
                      (pr_number, decision_type, agent_decision, confidence_score, status)
                    VALUES (%s,%s,%s::jsonb,%s,%s)
                    RETURNING *
                """, (data.get('pr_number'), data.get('decision_type'),
                      agent_decision_json, data.get('confidence_score', 0),
                      data.get('status', 'pending')))
                conn.commit()
                row = cur.fetchone()
                return dict(row) if row else {}
        except Exception as e:
            logger.error("create_pending_approval failed: %s", e)
            if conn: conn.rollback()
            return {}
        finally:
            if conn: conn.close()

    def update_approval_status(self, approval_id: int, status: str, notes: str = '') -> dict:
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE pending_approvals SET status=%s
                    WHERE id=%s RETURNING *
                """, (status, approval_id))
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

    # ── Write operations ──────────────────────────────────────────────────────

    def create_purchase_requisition(self, data: dict) -> dict:
        """
        Insert an auto-generated PR into the ERP-specific purchase_requisitions table.
        Called by InventoryCheckAgent when it detects low-stock items.

        Accepted keys in `data`:
            pr_number, description, quantity, requester, department,
            status, priority, notes
        """
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        import json as _json

        suffix = self._get_erp_suffix()  # e.g. 'odoo'
        table = f"purchase_requisitions_{suffix}"
        pr_number = data.get("pr_number") or f"PR-AUTO-{int(__import__('time').time())}"
        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {table}
                        (name, user_id, product_qty, state, origin, notes, erp_source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (
                        pr_number,
                        data.get("requester", "InventoryCheckAgent"),
                        float(data.get("quantity", 1)),
                        data.get("status", "draft"),
                        data.get("department", "Inventory"),
                        data.get("notes", ""),
                        suffix,
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
