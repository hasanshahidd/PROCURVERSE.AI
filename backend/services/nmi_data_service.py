"""
NMI Data Service — queries NMI PostgreSQL tables seeded from 58 Excel files.
Used by Phase-3 agents as the primary data source when Odoo is not connected.
"""
import os
import logging
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn() -> psycopg2.extensions.connection:
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL)


def _rows(cur) -> list:
    """Convert cursor results, coercing Decimal → float for JSON compatibility."""
    result = []
    for row in cur.fetchall():
        r = {}
        for k, v in row.items():
            r[k] = float(v) if isinstance(v, Decimal) else v
        result.append(r)
    return result


# ─────────────────────────────────────────────────────────────
#  Vendor Quotes & RFQ
# ─────────────────────────────────────────────────────────────

def get_nmi_vendor_quotes(item_name: str = None, limit: int = 50) -> list:
    """vendor_quotes LEFT JOIN rfq_headers for price comparison."""
    sql = """
        SELECT
            vq.quote_id, vq.rfq_reference, vq.vendor_id, vq.vendor_name,
            vq.item_code, vq.qty_quoted, vq.unit_price, vq.currency,
            vq.total_quote_value, vq.lead_time_days, vq.validity_days,
            vq.payment_terms, vq.delivery_terms, vq.tax_rate,
            vq.total_incl_tax, vq.technical_compliance, vq.recommended,
            rh.rfq_number, rh.rfq_date, rh.item_description,
            rh.qty_required, rh.target_price, rh.status AS rfq_status
        FROM vendor_quotes vq
        LEFT JOIN rfq_headers rh ON vq.rfq_reference = rh.rfq_number
        WHERE (%s IS NULL OR vq.item_code ILIKE '%%' || %s || '%%'
               OR rh.item_description ILIKE '%%' || %s || '%%')
        ORDER BY vq.unit_price ASC
        LIMIT %s
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (item_name, item_name, item_name, limit))
            return _rows(cur)
    except Exception as exc:
        logger.error("get_nmi_vendor_quotes failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Purchase Orders
# ─────────────────────────────────────────────────────────────

def get_nmi_purchase_orders(status: str = None, limit: int = 100) -> list:
    """po_headers LEFT JOIN po_line_items."""
    sql = """
        SELECT
            ph.po_number, ph.po_date, ph.pr_reference, ph.vendor_id,
            ph.vendor_name, ph.buyer, ph.payment_terms, ph.currency,
            ph.delivery_address, ph.requested_delivery, ph.promised_delivery,
            ph.po_subtotal, ph.tax_amount, ph.po_grand_total,
            ph.approval_status, ph.approved_by, ph.approval_date,
            ph.po_status, ph.exception_flag, ph.notes,
            pli.line_id, pli.line_no, pli.item_code, pli.item_description,
            pli.qty_ordered, pli.uom, pli.unit_price AS line_unit_price,
            pli.discount_pct, pli.net_unit_price, pli.line_total,
            pli.tax_code, pli.tax_amount AS line_tax, pli.line_total_incl_tax,
            pli.gl_account, pli.cost_center, pli.status AS line_status
        FROM po_headers ph
        LEFT JOIN po_line_items pli ON ph.po_number = pli.po_number
        WHERE (%s IS NULL OR ph.po_status ILIKE %s)
        ORDER BY ph.po_date DESC
        LIMIT %s
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (status, status, limit))
            return _rows(cur)
    except Exception as exc:
        logger.error("get_nmi_purchase_orders failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Spend Analytics
# ─────────────────────────────────────────────────────────────

def get_nmi_spend_analytics(period: str = None, limit: int = 200) -> list:
    """spend_analytics — multi-dimensional spend data."""
    sql = """
        SELECT *
        FROM spend_analytics
        WHERE (%s IS NULL OR period ILIKE %s)
        ORDER BY period DESC, total_amount_usd DESC
        LIMIT %s
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (period, period, limit))
            return _rows(cur)
    except Exception as exc:
        logger.error("get_nmi_spend_analytics failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Budget vs Actuals
# ─────────────────────────────────────────────────────────────

def get_nmi_budget_vs_actuals(cost_center: str = None) -> list:
    """budget_vs_actuals — Q1-Q4 + FY budget/actual/variance."""
    sql = """
        SELECT *
        FROM budget_vs_actuals
        WHERE (%s IS NULL OR cost_center ILIKE %s OR cost_center_name ILIKE '%%' || %s || '%%')
        ORDER BY cost_center, gl_account
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (cost_center, cost_center, cost_center))
            return _rows(cur)
    except Exception as exc:
        logger.error("get_nmi_budget_vs_actuals failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Invoices (3-way match)
# ─────────────────────────────────────────────────────────────

def get_nmi_invoice_details(invoice_no: str = None, limit: int = 50) -> list:
    """vendor_invoices LEFT JOIN invoice_line_items + three_way_match_log."""
    sql = """
        SELECT
            vi.invoice_no, vi.vendor_invoice_no, vi.invoice_date,
            vi.po_reference, vi.grn_reference, vi.vendor_id, vi.vendor_name,
            vi.invoice_type, vi.subtotal, vi.tax_amount, vi.invoice_total,
            vi.currency, vi.payment_terms, vi.due_date,
            vi.gl_account, vi.cost_center,
            vi.ap_status, vi.three_way_match_status,
            vi.approved_by, vi.exception_flag, vi.notes,
            ili.inv_line_id, ili.line_no, ili.item_code, ili.item_description,
            ili.qty_invoiced, ili.uom, ili.unit_price AS inv_unit_price,
            ili.discount_pct, ili.net_price, ili.line_subtotal,
            ili.tax_code, ili.tax_amt, ili.line_total AS inv_line_total,
            twm.match_id, twm.po_number AS twm_po, twm.grn_number AS twm_grn,
            twm.po_qty, twm.grn_qty, twm.inv_qty,
            twm.po_price, twm.inv_price,
            twm.qty_match, twm.price_match, twm.value_match,
            twm.match_result, twm.exception_type, twm.action_required
        FROM vendor_invoices vi
        LEFT JOIN invoice_line_items ili ON vi.invoice_no = ili.invoice_no
        LEFT JOIN three_way_match_log twm ON vi.invoice_no = twm.invoice_number
        WHERE (%s IS NULL OR vi.invoice_no ILIKE %s)
        ORDER BY vi.invoice_date DESC
        LIMIT %s
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (invoice_no, invoice_no, limit))
            return _rows(cur)
    except Exception as exc:
        logger.error("get_nmi_invoice_details failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Goods Receipt Notes
# ─────────────────────────────────────────────────────────────

def get_nmi_grn_details(grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
    """grn_headers LEFT JOIN grn_line_items."""
    sql = """
        SELECT
            gh.grn_number, gh.grn_date, gh.po_reference, gh.vendor_id,
            gh.vendor_name, gh.received_by, gh.warehouse,
            gh.delivery_note_no, gh.carrier, gh.packages_received,
            gh.total_weight_kg, gh.grn_status, gh.qc_status,
            gh.exception_flag, gh.notes,
            gli.grn_line_id, gli.po_number, gli.item_code, gli.item_description,
            gli.po_qty, gli.received_qty, gli.variance_qty, gli.uom,
            gli.unit_cost, gli.currency, gli.line_value,
            gli.lot_batch_no, gli.qc_status AS line_qc_status
        FROM grn_headers gh
        LEFT JOIN grn_line_items gli ON gh.grn_number = gli.grn_number
        WHERE
            (%s IS NULL OR gh.grn_number ILIKE %s)
            AND (%s IS NULL OR gh.po_reference ILIKE %s OR gli.po_number ILIKE %s)
        ORDER BY gh.grn_date DESC
        LIMIT %s
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (grn_number, grn_number, po_number, po_number, po_number, limit))
            return _rows(cur)
    except Exception as exc:
        logger.error("get_nmi_grn_details failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Inventory / Items
# ─────────────────────────────────────────────────────────────

def get_nmi_inventory_status(item_code: str = None) -> list:
    """items LEFT JOIN grn_line_items — received qty vs reorder point."""
    sql = """
        SELECT
            i.item_code, i.item_description, i.item_type, i.category,
            i.sub_category, i.uom, i.std_unit_cost, i.currency,
            i.min_order_qty, i.lead_time_days, i.reorder_point,
            i.safety_stock, i.gl_account, i.active,
            COALESCE(SUM(gli.received_qty), 0)  AS total_received,
            MAX(gh.grn_date)                     AS last_receipt_date
        FROM items i
        LEFT JOIN grn_line_items gli ON i.item_code = gli.item_code
        LEFT JOIN grn_headers gh ON gli.grn_number = gh.grn_number
        WHERE (%s IS NULL OR i.item_code ILIKE %s OR i.item_description ILIKE '%%' || %s || '%%')
        GROUP BY
            i.item_code, i.item_description, i.item_type, i.category,
            i.sub_category, i.uom, i.std_unit_cost, i.currency,
            i.min_order_qty, i.lead_time_days, i.reorder_point,
            i.safety_stock, i.gl_account, i.active
        ORDER BY i.item_code
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (item_code, item_code, item_code))
            return _rows(cur)
    except Exception as exc:
        logger.error("get_nmi_inventory_status failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Approved Suppliers
# ─────────────────────────────────────────────────────────────

def get_nmi_approved_suppliers(item_code: str = None, item_category: str = None) -> list:
    """approved_supplier_list LEFT JOIN vendors."""
    sql = """
        SELECT
            asl.asl_id, asl.vendor_id, asl.vendor_name, asl.item_code,
            asl.item_category, asl.approval_status, asl.preferred_rank,
            asl.approved_by, asl.approval_date, asl.expiry_date,
            asl.annual_spend_cap_usd, asl.ytd_spend_usd,
            asl.qualification_basis, asl.quality_cert,
            asl.last_audit_date, asl.notes,
            v.short_name, v.category AS vendor_category,
            v.country, v.currency AS vendor_currency,
            v.payment_terms AS vendor_payment_terms,
            v.lead_time_days AS vendor_lead_time,
            v.min_order_qty AS vendor_min_qty,
            v.contact_person, v.email, v.phone,
            v.vendor_rating, v.hold_status, v.active AS vendor_active
        FROM approved_supplier_list asl
        LEFT JOIN vendors v ON asl.vendor_id = v.vendor_id
        WHERE
            (%s IS NULL OR asl.item_code ILIKE %s)
            AND (%s IS NULL OR asl.item_category ILIKE '%%' || %s || '%%')
        ORDER BY asl.item_code, asl.preferred_rank
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (item_code, item_code, item_category, item_category))
            return _rows(cur)
    except Exception as exc:
        logger.error("get_nmi_approved_suppliers failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Compliance Data
# ─────────────────────────────────────────────────────────────

def get_nmi_compliance_data(department: str = None) -> dict:
    """Workflow approval matrix + budget vs actuals for compliance checks."""
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM workflow_approval_matrix
                WHERE (%s IS NULL OR process ILIKE '%%' || %s || '%%')
                ORDER BY process, threshold_min
                """,
                (department, department),
            )
            workflow_matrix = _rows(cur)

            cur.execute(
                """
                SELECT *
                FROM budget_vs_actuals
                WHERE (%s IS NULL OR cost_center ILIKE %s
                       OR cost_center_name ILIKE '%%' || %s || '%%')
                ORDER BY cost_center, gl_account
                """,
                (department, department, department),
            )
            budget_status = _rows(cur)

        return {"workflow_matrix": workflow_matrix, "budget_status": budget_status}
    except Exception as exc:
        logger.error("get_nmi_compliance_data failed: %s", exc)
        return {"workflow_matrix": [], "budget_status": []}
    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────
#  Summary Statistics
# ─────────────────────────────────────────────────────────────

def get_nmi_summary_stats() -> dict:
    """High-level counts and spend totals for the system status view."""
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM po_headers")
            total_pos = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM vendors WHERE active = TRUE")
            total_vendors = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM vendor_invoices")
            total_invoices = cur.fetchone()["n"]

            cur.execute(
                """
                SELECT COALESCE(SUM(po_grand_total), 0) AS ytd
                FROM po_headers
                WHERE EXTRACT(YEAR FROM po_date) = EXTRACT(YEAR FROM CURRENT_DATE)
                """
            )
            spend_ytd = cur.fetchone()["ytd"]

            cur.execute(
                "SELECT COUNT(*) AS n FROM po_headers WHERE po_status ILIKE '%OPEN%' OR po_status ILIKE '%PENDING%'"
            )
            pending_pos = cur.fetchone()["n"]

            cur.execute(
                "SELECT COUNT(*) AS n FROM vendor_invoices WHERE ap_status ILIKE '%PENDING%'"
            )
            pending_invoices = cur.fetchone()["n"]

        return {
            "total_pos": total_pos,
            "total_vendors": total_vendors,
            "total_invoices": total_invoices,
            "spend_ytd": float(spend_ytd) if spend_ytd else 0.0,
            "pending_pos": pending_pos,
            "pending_invoices": pending_invoices,
        }
    except Exception as exc:
        logger.error("get_nmi_summary_stats failed: %s", exc)
        return {
            "total_pos": 0, "total_vendors": 0, "total_invoices": 0,
            "spend_ytd": 0.0, "pending_pos": 0, "pending_invoices": 0,
        }
    finally:
        if conn:
            conn.close()
