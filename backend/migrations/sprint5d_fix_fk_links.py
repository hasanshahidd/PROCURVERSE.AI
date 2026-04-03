"""
sprint5d_fix_fk_links.py
========================
Fix all cross-table FK mismatches discovered during integrity check.

Issues fixed:
  1. Odoo po_lines.order_id       — VARCHAR 'PO00001' → INTEGER id (real Odoo FK)
  2. Odoo invoice_lines.move_id   — VARCHAR 'BILL/...' → INTEGER id (real Odoo FK)
  3. Odoo grn_lines.picking_id    — VARCHAR 'WH/IN/...' → INTEGER id (real Odoo FK)
  4. Oracle po_lines.ponumber     — 'US-000001' → 'US-10001' (matches po_headers)
  5. Oracle invoice_lines.ponumber— 'US-000001' → 'US-10001' (matches invoices)
  6. Oracle invoice_lines.invoicenumber — 'INV-00001' → actual header number
  7. Dynamics invoice_lines.vendorinvoicenumber — 'GTS-INV-2025-000101' → 'GTS-INV-2025-0101'
"""

import os, logging
import psycopg2

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

DB = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres:YourStr0ng!Pass@localhost:5433/odoo_procurement_demo'
)


def run():
    conn = psycopg2.connect(DB)
    cur = conn.cursor()

    # ── 1. Odoo po_lines.order_id: VARCHAR name → INTEGER id ─────────────────
    log.info("Fixing Odoo po_lines.order_id VARCHAR → INTEGER...")
    cur.execute("ALTER TABLE po_lines_odoo ADD COLUMN order_id_int INTEGER")
    cur.execute("""
        UPDATE po_lines_odoo l
        SET order_id_int = (
            SELECT h.id FROM po_headers_odoo h WHERE h.name = l.order_id
        )
    """)
    cur.execute("ALTER TABLE po_lines_odoo DROP COLUMN order_id")
    cur.execute("ALTER TABLE po_lines_odoo RENAME COLUMN order_id_int TO order_id")
    conn.commit()

    # Verify
    cur.execute("""
        SELECT COUNT(*) FROM po_lines_odoo l
        WHERE NOT EXISTS (SELECT 1 FROM po_headers_odoo h WHERE h.id = l.order_id)
    """)
    n = cur.fetchone()[0]
    log.info(f"  po_lines_odoo broken after fix: {n}")

    # ── 2. Odoo invoice_lines.move_id: VARCHAR name → INTEGER id ─────────────
    log.info("Fixing Odoo invoice_lines.move_id VARCHAR → INTEGER...")
    cur.execute("ALTER TABLE invoice_lines_odoo ADD COLUMN move_id_int INTEGER")
    cur.execute("""
        UPDATE invoice_lines_odoo l
        SET move_id_int = (
            SELECT i.id FROM invoices_odoo i WHERE i.name = l.move_id
        )
    """)
    cur.execute("ALTER TABLE invoice_lines_odoo DROP COLUMN move_id")
    cur.execute("ALTER TABLE invoice_lines_odoo RENAME COLUMN move_id_int TO move_id")
    conn.commit()

    cur.execute("""
        SELECT COUNT(*) FROM invoice_lines_odoo l
        WHERE NOT EXISTS (SELECT 1 FROM invoices_odoo i WHERE i.id = l.move_id)
    """)
    n = cur.fetchone()[0]
    log.info(f"  invoice_lines_odoo broken after fix: {n}")

    # ── 3. Odoo grn_lines.picking_id: VARCHAR name → INTEGER id ──────────────
    log.info("Fixing Odoo grn_lines.picking_id VARCHAR → INTEGER...")
    cur.execute("ALTER TABLE grn_lines_odoo ADD COLUMN picking_id_int INTEGER")
    cur.execute("""
        UPDATE grn_lines_odoo l
        SET picking_id_int = (
            SELECT g.id FROM grn_headers_odoo g WHERE g.name = l.picking_id
        )
    """)
    cur.execute("ALTER TABLE grn_lines_odoo DROP COLUMN picking_id")
    cur.execute("ALTER TABLE grn_lines_odoo RENAME COLUMN picking_id_int TO picking_id")
    conn.commit()

    cur.execute("""
        SELECT COUNT(*) FROM grn_lines_odoo l
        WHERE NOT EXISTS (SELECT 1 FROM grn_headers_odoo g WHERE g.id = l.picking_id)
    """)
    n = cur.fetchone()[0]
    log.info(f"  grn_lines_odoo broken after fix: {n}")

    # ── 4. Oracle po_lines.ponumber: 'US-000001' → 'US-10001' ────────────────
    log.info("Fixing Oracle po_lines.ponumber format...")
    cur.execute("""
        UPDATE po_lines_oracle
        SET ponumber = 'US-' || (
            CAST(LTRIM(SUBSTRING(ponumber FROM 4), '0') AS INTEGER) + 10000
        )::text
        WHERE ponumber LIKE 'US-0%'
    """)
    conn.commit()

    cur.execute("""
        SELECT COUNT(*) FROM po_lines_oracle l
        WHERE NOT EXISTS (SELECT 1 FROM po_headers_oracle h WHERE h.ponumber = l.ponumber)
    """)
    n = cur.fetchone()[0]
    log.info(f"  po_lines_oracle broken after fix: {n}")

    # ── 5. Oracle invoice_lines.ponumber: 'US-000001' → 'US-10001' ───────────
    log.info("Fixing Oracle invoice_lines.ponumber format...")
    cur.execute("""
        UPDATE invoice_lines_oracle
        SET ponumber = 'US-' || (
            CAST(LTRIM(SUBSTRING(ponumber FROM 4), '0') AS INTEGER) + 10000
        )::text
        WHERE ponumber LIKE 'US-0%'
    """)
    conn.commit()

    # ── 6. Oracle invoice_lines.invoicenumber: 'INV-00001' → actual header ───
    log.info("Fixing Oracle invoice_lines.invoicenumber...")
    # Join via ponumber: lines now have correct US-10001 ponumber that matches
    # invoices_oracle.ponumber, so we can look up the invoice number
    cur.execute("""
        UPDATE invoice_lines_oracle il
        SET invoicenumber = (
            SELECT i.invoicenumber FROM invoices_oracle i
            WHERE i.ponumber = il.ponumber
        )
        WHERE invoicenumber LIKE 'INV-%'
    """)
    conn.commit()

    cur.execute("""
        SELECT COUNT(*) FROM invoice_lines_oracle l
        WHERE NOT EXISTS (SELECT 1 FROM invoices_oracle i WHERE i.invoicenumber = l.invoicenumber)
    """)
    n = cur.fetchone()[0]
    log.info(f"  invoice_lines_oracle broken after fix: {n}")

    # ── 7. Dynamics invoice_lines.vendorinvoicenumber format fix ─────────────
    # 'GTS-INV-2025-000101' → match by RIGHT(..., 4) to get correct header number
    log.info("Fixing Dynamics invoice_lines.vendorinvoicenumber format...")
    cur.execute("""
        UPDATE invoice_lines_dynamics il
        SET vendorinvoicenumber = (
            SELECT i.vendorinvoicenumber FROM invoices_dynamics i
            WHERE RIGHT(i.vendorinvoicenumber, 4) = RIGHT(il.vendorinvoicenumber, 4)
        )
        WHERE vendorinvoicenumber LIKE '%-0000%' OR vendorinvoicenumber LIKE '%-001%'
    """)
    conn.commit()

    cur.execute("""
        SELECT COUNT(*) FROM invoice_lines_dynamics l
        WHERE NOT EXISTS (
            SELECT 1 FROM invoices_dynamics i WHERE i.vendorinvoicenumber = l.vendorinvoicenumber
        )
    """)
    n = cur.fetchone()[0]
    log.info(f"  invoice_lines_dynamics broken after fix: {n}")

    # ── Final verification sweep ──────────────────────────────────────────────
    log.info("\n=== FINAL VERIFICATION ===")
    checks = [
        ("Odoo PO lines", "po_lines_odoo l", "po_headers_odoo h", "h.id = l.order_id"),
        ("Odoo Inv lines", "invoice_lines_odoo l", "invoices_odoo i", "i.id = l.move_id"),
        ("Odoo GRN lines", "grn_lines_odoo l", "grn_headers_odoo g", "g.id = l.picking_id"),
        ("Oracle PO lines", "po_lines_oracle l", "po_headers_oracle h", "h.ponumber = l.ponumber"),
        ("Oracle Inv lines", "invoice_lines_oracle l", "invoices_oracle i", "i.invoicenumber = l.invoicenumber"),
        ("Dynamics Inv lines", "invoice_lines_dynamics l", "invoices_dynamics i",
         "i.vendorinvoicenumber = l.vendorinvoicenumber"),
    ]
    all_ok = True
    for label, from_tbl, join_tbl, condition in checks:
        cur.execute(f"""
            SELECT COUNT(*) FROM {from_tbl}
            WHERE NOT EXISTS (SELECT 1 FROM {join_tbl} WHERE {condition})
        """)
        n = cur.fetchone()[0]
        status = "OK" if n == 0 else f"BROKEN ({n} rows)"
        if n: all_ok = False
        log.info(f"  {label:30} {status}")

    if all_ok:
        log.info("\nAll FK links are now consistent across all 6 ERPs!")
    else:
        log.warning("\nSome issues remain — check output above.")

    cur.close()
    conn.close()


if __name__ == '__main__':
    run()
