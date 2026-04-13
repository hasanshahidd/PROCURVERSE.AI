"""
Dev Spec 2.0 — Gap Tables Migration
Creates 9 new tables and adds columns to 4 existing tables.
Gaps: G-01 through G-14

New tables:
  - vendor_kyc             (G-01: Vendor KYC & Onboarding)
  - contract_line_items    (G-02: Contract Linkage)
  - po_contract_link       (G-02: Contract Linkage on PO)
  - grn_returns            (G-03: Goods Returns & Debit Notes)
  - invoice_dedup_log      (G-04: Duplicate Invoice Detection)
  - exception_queue        (G-05: Exception Resolution Workflow)
  - vendor_communications  (G-06: Vendor Communication Loop)
  - budget_ledger          (G-08: Budget Commitment Reconciliation)
  - vendor_scorecard       (G-10: Vendor Performance Feedback)
  - accrual_entries        (G-12: Accruals)

Altered tables:
  - contracts              (G-02: add contract_type, auto_renew, price_escalation_pct, maverick_spend_flag)
  - po_headers             (G-09: add delivery_mode, total_received_qty, remaining_qty, delivery_complete)
  - grn_headers            (G-09: add grn_type, partial_seq, cumulative_qty)
  - vendor_invoices        (G-13: add fx_rate_locked, fx_rate_lock_date, fx_rate_expiry, base_currency_amount)

Usage:
    python backend/migrations/devspec2_gap_tables.py
    python backend/migrations/devspec2_gap_tables.py --drop  # drop and recreate
"""
import psycopg2
import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# ---------------------------------------------------------------------------
# DDL for brand-new tables
# ---------------------------------------------------------------------------
NEW_TABLES_DDL = """

-- ==========================================================================
-- G-01: Vendor KYC & Onboarding
-- ==========================================================================
CREATE TABLE IF NOT EXISTS vendor_kyc (
    id SERIAL PRIMARY KEY,
    vendor_id VARCHAR(20),
    kyc_status VARCHAR(30) DEFAULT 'pending'
        CHECK (kyc_status IN ('pending','in_progress','approved','rejected','expired')),
    sanction_check_passed BOOLEAN,
    sanction_check_date TIMESTAMP,
    sanction_source VARCHAR(100),
    sanction_matches JSONB DEFAULT '[]',
    tax_verified BOOLEAN DEFAULT FALSE,
    bank_verified BOOLEAN DEFAULT FALSE,
    insurance_verified BOOLEAN DEFAULT FALSE,
    insurance_expiry DATE,
    compliance_score DECIMAL(5,2),
    kyc_documents JSONB DEFAULT '[]',
    approved_by VARCHAR(255),
    approved_at TIMESTAMP,
    expiry_date DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vendor_kyc_vendor ON vendor_kyc(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_kyc_status ON vendor_kyc(kyc_status);

-- ==========================================================================
-- G-02: Contract Linkage — line items
-- ==========================================================================
CREATE TABLE IF NOT EXISTS contract_line_items (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER,
    item_code VARCHAR(50),
    item_description VARCHAR(500),
    contracted_price DECIMAL(15,4),
    currency VARCHAR(10) DEFAULT 'USD',
    min_qty DECIMAL(15,4),
    max_qty DECIMAL(15,4),
    uom VARCHAR(20),
    price_valid_from DATE,
    price_valid_to DATE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_contract_lines_contract ON contract_line_items(contract_id);
CREATE INDEX IF NOT EXISTS idx_contract_lines_item ON contract_line_items(item_code);

-- ==========================================================================
-- G-02: Contract Linkage — PO-to-contract link
-- ==========================================================================
CREATE TABLE IF NOT EXISTS po_contract_link (
    id SERIAL PRIMARY KEY,
    po_number VARCHAR(50),
    contract_id INTEGER,
    contract_number VARCHAR(50),
    line_item_id INTEGER,
    contracted_price DECIMAL(15,4),
    actual_price DECIMAL(15,4),
    price_variance_pct DECIMAL(5,2),
    variance_status VARCHAR(30)
        CHECK (variance_status IN ('within_tolerance','notify','blocked','override')),
    maverick_flag BOOLEAN DEFAULT FALSE,
    validated_by VARCHAR(100),
    validated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_po_contract_po ON po_contract_link(po_number);
CREATE INDEX IF NOT EXISTS idx_po_contract_contract ON po_contract_link(contract_id);

-- ==========================================================================
-- G-03: Goods Returns & Debit Notes
-- ==========================================================================
CREATE TABLE IF NOT EXISTS grn_returns (
    id SERIAL PRIMARY KEY,
    return_number VARCHAR(50) UNIQUE NOT NULL,
    grn_number VARCHAR(50),
    po_number VARCHAR(50),
    vendor_id VARCHAR(20),
    vendor_name VARCHAR(255),
    return_reason VARCHAR(100),
    return_type VARCHAR(50)
        CHECK (return_type IN ('full_return','partial_return','quality_reject','damaged','wrong_item','excess')),
    items JSONB DEFAULT '[]',
    total_return_qty DECIMAL(15,4),
    total_return_value DECIMAL(15,2),
    debit_note_number VARCHAR(50),
    debit_note_amount DECIMAL(15,2),
    debit_note_status VARCHAR(30) DEFAULT 'pending'
        CHECK (debit_note_status IN ('pending','issued','sent','acknowledged','credited','disputed')),
    credit_resolution VARCHAR(30)
        CHECK (credit_resolution IN ('credit_note','replacement','refund','write_off')),
    credit_amount DECIMAL(15,2),
    status VARCHAR(30) DEFAULT 'initiated'
        CHECK (status IN ('initiated','approved','shipped','received_by_vendor','resolved','cancelled')),
    initiated_by VARCHAR(255),
    approved_by VARCHAR(255),
    approved_at TIMESTAMP,
    resolved_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grn_returns_grn ON grn_returns(grn_number);
CREATE INDEX IF NOT EXISTS idx_grn_returns_po ON grn_returns(po_number);
CREATE INDEX IF NOT EXISTS idx_grn_returns_vendor ON grn_returns(vendor_id);
CREATE INDEX IF NOT EXISTS idx_grn_returns_status ON grn_returns(status);

-- ==========================================================================
-- G-04: Duplicate Invoice Detection
-- ==========================================================================
CREATE TABLE IF NOT EXISTS invoice_dedup_log (
    id SERIAL PRIMARY KEY,
    invoice_number VARCHAR(100),
    vendor_id VARCHAR(20),
    vendor_name VARCHAR(255),
    invoice_amount DECIMAL(15,2),
    invoice_date DATE,
    detection_method VARCHAR(30)
        CHECK (detection_method IN ('exact_hash','fuzzy_match','cross_channel','manual')),
    hash_sha256 VARCHAR(64),
    match_score DECIMAL(5,2),
    matched_invoice_id INTEGER,
    matched_invoice_number VARCHAR(100),
    similarity_details JSONB DEFAULT '{}',
    resolution VARCHAR(30) DEFAULT 'pending'
        CHECK (resolution IN ('pending','confirmed_duplicate','false_positive','merged','rejected')),
    resolved_by VARCHAR(255),
    resolved_at TIMESTAMP,
    auto_blocked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dedup_hash ON invoice_dedup_log(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_dedup_vendor ON invoice_dedup_log(vendor_id);
CREATE INDEX IF NOT EXISTS idx_dedup_resolution ON invoice_dedup_log(resolution);

-- ==========================================================================
-- G-05: Exception Resolution Workflow
-- ==========================================================================
CREATE TABLE IF NOT EXISTS exception_queue (
    id SERIAL PRIMARY KEY,
    exception_id VARCHAR(50) UNIQUE NOT NULL,
    exception_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) DEFAULT 'MEDIUM'
        CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    source_document_type VARCHAR(50),
    source_document_id VARCHAR(50),
    workflow_run_id VARCHAR(100),
    description TEXT,
    ai_context JSONB DEFAULT '{}',
    ai_recommendation TEXT,
    assigned_to VARCHAR(255),
    sla_deadline TIMESTAMP,
    sla_breached BOOLEAN DEFAULT FALSE,
    resolution_action VARCHAR(100),
    resolution_notes TEXT,
    resolved_by VARCHAR(255),
    resolved_at TIMESTAMP,
    status VARCHAR(30) DEFAULT 'open'
        CHECK (status IN ('open','assigned','in_progress','escalated','resolved','closed')),
    escalation_level INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_exception_status ON exception_queue(status);
CREATE INDEX IF NOT EXISTS idx_exception_severity ON exception_queue(severity);
CREATE INDEX IF NOT EXISTS idx_exception_sla ON exception_queue(sla_deadline);
CREATE INDEX IF NOT EXISTS idx_exception_assigned ON exception_queue(assigned_to);

-- ==========================================================================
-- G-06: Vendor Communication Loop
-- ==========================================================================
CREATE TABLE IF NOT EXISTS vendor_communications (
    id SERIAL PRIMARY KEY,
    vendor_id VARCHAR(20),
    vendor_name VARCHAR(255),
    communication_type VARCHAR(50) NOT NULL
        CHECK (communication_type IN (
            'po_acknowledgment','delivery_approaching','goods_received',
            'partial_accept','invoice_received','invoice_matched',
            'exception_raised','payment_sent','debit_note','general'
        )),
    document_type VARCHAR(50),
    document_id VARCHAR(50),
    channel VARCHAR(30) DEFAULT 'email'
        CHECK (channel IN ('email','portal','api','sms','webhook')),
    subject VARCHAR(500),
    body TEXT,
    template_id INTEGER,
    sent_at TIMESTAMP,
    delivered_at TIMESTAMP,
    read_at TIMESTAMP,
    response_received BOOLEAN DEFAULT FALSE,
    response_data JSONB,
    status VARCHAR(30) DEFAULT 'pending'
        CHECK (status IN ('pending','sent','delivered','read','responded','failed','bounced')),
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vendor_comm_vendor ON vendor_communications(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_comm_type ON vendor_communications(communication_type);
CREATE INDEX IF NOT EXISTS idx_vendor_comm_status ON vendor_communications(status);

-- ==========================================================================
-- G-08: Budget Commitment Reconciliation
-- ==========================================================================
CREATE TABLE IF NOT EXISTS budget_ledger (
    id SERIAL PRIMARY KEY,
    department VARCHAR(100) NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_period VARCHAR(20),
    entry_type VARCHAR(30) NOT NULL
        CHECK (entry_type IN ('allocation','commitment','release','actual','adjustment','transfer')),
    reference_type VARCHAR(50),
    reference_id VARCHAR(50),
    amount DECIMAL(15,2) NOT NULL,
    running_balance DECIMAL(15,2),
    description TEXT,
    posted_by VARCHAR(255),
    posted_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_budget_ledger_dept ON budget_ledger(department, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_budget_ledger_ref ON budget_ledger(reference_type, reference_id);
CREATE INDEX IF NOT EXISTS idx_budget_ledger_type ON budget_ledger(entry_type);

-- ==========================================================================
-- G-10: Vendor Performance Feedback
-- ==========================================================================
CREATE TABLE IF NOT EXISTS vendor_scorecard (
    id SERIAL PRIMARY KEY,
    vendor_id VARCHAR(20),
    vendor_name VARCHAR(255),
    evaluation_period VARCHAR(20),
    po_number VARCHAR(50),
    grn_number VARCHAR(50),
    delivery_accuracy_score DECIMAL(5,2),
    on_time_delivery_score DECIMAL(5,2),
    quality_score DECIMAL(5,2),
    invoice_accuracy_score DECIMAL(5,2),
    communication_score DECIMAL(5,2),
    overall_score DECIMAL(5,2),
    total_orders INTEGER DEFAULT 0,
    total_on_time INTEGER DEFAULT 0,
    total_quality_pass INTEGER DEFAULT 0,
    total_invoice_accurate INTEGER DEFAULT 0,
    rolling_12m_avg DECIMAL(5,2),
    feedback_notes TEXT,
    scored_by VARCHAR(100) DEFAULT 'system',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scorecard_vendor ON vendor_scorecard(vendor_id);
CREATE INDEX IF NOT EXISTS idx_scorecard_period ON vendor_scorecard(evaluation_period);
CREATE INDEX IF NOT EXISTS idx_scorecard_overall ON vendor_scorecard(overall_score);

-- ==========================================================================
-- G-12: Accruals
-- ==========================================================================
CREATE TABLE IF NOT EXISTS accrual_entries (
    id SERIAL PRIMARY KEY,
    accrual_type VARCHAR(30) NOT NULL
        CHECK (accrual_type IN ('grni','expense','reversal')),
    grn_number VARCHAR(50),
    po_number VARCHAR(50),
    vendor_id VARCHAR(20),
    vendor_name VARCHAR(255),
    gl_account VARCHAR(20),
    cost_center VARCHAR(20),
    amount DECIMAL(15,2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'USD',
    fiscal_period VARCHAR(20),
    fiscal_year INTEGER,
    reversal_of INTEGER,
    reversed BOOLEAN DEFAULT FALSE,
    reversed_at TIMESTAMP,
    posted_by VARCHAR(100) DEFAULT 'system',
    posted_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_accrual_grn ON accrual_entries(grn_number);
CREATE INDEX IF NOT EXISTS idx_accrual_period ON accrual_entries(fiscal_period, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_accrual_type ON accrual_entries(accrual_type);

"""

# ---------------------------------------------------------------------------
# DDL for altering existing tables
# ---------------------------------------------------------------------------
ALTER_EXISTING_DDL = """

-- ==========================================================================
-- G-02: contracts — additional columns
-- ==========================================================================
ALTER TABLE contracts ADD COLUMN IF NOT EXISTS contract_type VARCHAR(50);
ALTER TABLE contracts ADD COLUMN IF NOT EXISTS auto_renew BOOLEAN DEFAULT FALSE;
ALTER TABLE contracts ADD COLUMN IF NOT EXISTS price_escalation_pct DECIMAL(5,2);
ALTER TABLE contracts ADD COLUMN IF NOT EXISTS maverick_spend_flag BOOLEAN DEFAULT FALSE;

-- ==========================================================================
-- G-09: po_headers — partial delivery support
-- ==========================================================================
ALTER TABLE po_headers ADD COLUMN IF NOT EXISTS delivery_mode VARCHAR(20) DEFAULT 'single';
ALTER TABLE po_headers ADD COLUMN IF NOT EXISTS total_received_qty DECIMAL(15,4) DEFAULT 0;
ALTER TABLE po_headers ADD COLUMN IF NOT EXISTS remaining_qty DECIMAL(15,4);
ALTER TABLE po_headers ADD COLUMN IF NOT EXISTS delivery_complete BOOLEAN DEFAULT FALSE;

-- ==========================================================================
-- G-09: grn_headers — partial delivery support
-- ==========================================================================
ALTER TABLE grn_headers ADD COLUMN IF NOT EXISTS grn_type VARCHAR(20) DEFAULT 'full';
ALTER TABLE grn_headers ADD COLUMN IF NOT EXISTS partial_seq INTEGER DEFAULT 1;
ALTER TABLE grn_headers ADD COLUMN IF NOT EXISTS cumulative_qty DECIMAL(15,4);

-- ==========================================================================
-- G-13: vendor_invoices — FX controls
-- ==========================================================================
ALTER TABLE vendor_invoices ADD COLUMN IF NOT EXISTS fx_rate_locked DECIMAL(15,6);
ALTER TABLE vendor_invoices ADD COLUMN IF NOT EXISTS fx_rate_lock_date TIMESTAMP;
ALTER TABLE vendor_invoices ADD COLUMN IF NOT EXISTS fx_rate_expiry DATE;
ALTER TABLE vendor_invoices ADD COLUMN IF NOT EXISTS base_currency_amount DECIMAL(15,2);

"""

# ---------------------------------------------------------------------------
# Tables that this migration owns (used for --drop)
# ---------------------------------------------------------------------------
GAP_TABLES = [
    "vendor_kyc",
    "contract_line_items",
    "po_contract_link",
    "grn_returns",
    "invoice_dedup_log",
    "exception_queue",
    "vendor_communications",
    "budget_ledger",
    "vendor_scorecard",
    "accrual_entries",
]


def run(drop_first=False):
    """Execute the migration."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    try:
        # ------------------------------------------------------------------
        # Optional: drop new tables so they can be recreated cleanly
        # ------------------------------------------------------------------
        if drop_first:
            for table_name in GAP_TABLES:
                cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
            conn.commit()
            print(f"Dropped {len(GAP_TABLES)} gap tables")

        # ------------------------------------------------------------------
        # Create new tables + indexes
        # ------------------------------------------------------------------
        cur.execute(NEW_TABLES_DDL)
        conn.commit()
        print("Created new tables and indexes")

        # ------------------------------------------------------------------
        # Alter existing tables with new columns (each ALTER is independent)
        # ------------------------------------------------------------------
        alter_statements = [s.strip() for s in ALTER_EXISTING_DDL.split(";") if s.strip() and s.strip().upper().startswith("ALTER")]
        alter_ok = 0
        alter_skip = 0
        for stmt in alter_statements:
            try:
                cur.execute(stmt)
                conn.commit()
                alter_ok += 1
            except Exception as alter_err:
                conn.rollback()
                alter_skip += 1
                print(f"  SKIP: {str(alter_err).strip().splitlines()[0]}")
        print(f"Altered existing tables: {alter_ok} succeeded, {alter_skip} skipped (table may not exist)")

        # ------------------------------------------------------------------
        # Verification: confirm all new tables exist
        # ------------------------------------------------------------------
        placeholders = ",".join(["%s"] * len(GAP_TABLES))
        cur.execute(
            f"SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema = 'public' AND table_name IN ({placeholders})",
            GAP_TABLES,
        )
        found_tables = sorted([row[0] for row in cur.fetchall()])
        print(f"Verified {len(found_tables)}/{len(GAP_TABLES)} new tables: {found_tables}")

        if len(found_tables) < len(GAP_TABLES):
            missing = set(GAP_TABLES) - set(found_tables)
            print(f"WARNING: Missing tables: {missing}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Dev Spec 2.0 gap tables migration (G-01 through G-14)"
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop and recreate all gap tables (does NOT remove added columns from existing tables)",
    )
    args = parser.parse_args()
    run(drop_first=args.drop)
