"""
Phase 8 — Senior-Identified Gap Fixes
=======================================
Creates tables for:
  - debit_notes (Gap #3: Returns → vendor debit notes)
  - accruals (Gap #13: GRNi — goods received not invoiced)
  - fx_locked_rates (Gap #14: FX rate locking at PO creation)
"""
import os, logging, psycopg2
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    raise RuntimeError("DATABASE_URL required")


def run():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # 1. Debit Notes (Gap #3)
    log.info("Creating debit_notes table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS debit_notes (
            id              SERIAL PRIMARY KEY,
            debit_note_number VARCHAR(50) UNIQUE NOT NULL,
            rtv_number      VARCHAR(50),
            vendor_id       VARCHAR(50),
            vendor_name     VARCHAR(200),
            po_number       VARCHAR(50),
            invoice_number  VARCHAR(100),
            amount          NUMERIC(18,2),
            currency        VARCHAR(10) DEFAULT 'USD',
            reason          TEXT,
            status          VARCHAR(50) DEFAULT 'issued',
            issued_date     DATE DEFAULT CURRENT_DATE,
            settled_date    DATE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    log.info("  debit_notes created")

    # 2. Accruals / GRNi (Gap #13)
    log.info("Creating accruals table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accruals (
            id              SERIAL PRIMARY KEY,
            accrual_ref     VARCHAR(50) UNIQUE NOT NULL,
            grn_number      VARCHAR(50),
            po_number       VARCHAR(50),
            vendor_name     VARCHAR(200),
            accrual_amount  NUMERIC(18,2),
            currency        VARCHAR(10) DEFAULT 'USD',
            period          VARCHAR(20),
            accrual_type    VARCHAR(50) DEFAULT 'grni',
            status          VARCHAR(50) DEFAULT 'open',
            invoice_number  VARCHAR(100),
            reversed_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    log.info("  accruals created")

    # 3. FX Locked Rates (Gap #14)
    log.info("Creating fx_locked_rates table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fx_locked_rates (
            id              SERIAL PRIMARY KEY,
            document_type   VARCHAR(50) NOT NULL,
            document_number VARCHAR(50) NOT NULL,
            from_currency   VARCHAR(10) NOT NULL,
            to_currency     VARCHAR(10) NOT NULL DEFAULT 'AED',
            locked_rate     NUMERIC(18,6) NOT NULL,
            spot_rate       NUMERIC(18,6),
            locked_by       VARCHAR(200) DEFAULT 'system',
            locked_at       TIMESTAMPTZ DEFAULT NOW(),
            used_at         TIMESTAMPTZ,
            variance_pct    NUMERIC(8,4)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fx_locked_doc ON fx_locked_rates(document_type, document_number)")
    conn.commit()
    log.info("  fx_locked_rates created")

    # Verify
    log.info("\nVerification:")
    for t in ['debit_notes', 'accruals', 'fx_locked_rates']:
        cur.execute("SELECT count(*) FROM %s" % t)
        log.info("  %s: %d rows" % (t, cur.fetchone()[0]))

    cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
    log.info("  Total tables: %d" % cur.fetchone()[0])

    cur.close()
    conn.close()
    log.info("Phase 8 migration complete")


if __name__ == '__main__':
    run()
