"""
Phase 1 — Complete Data Seeding & Table Creation
=================================================
Creates all missing tables and seeds data for the complete P2P workflow.

Tables created:
  - rfq_headers, rfq_lines (RFQ workflow)
  - po_amendments, po_amendment_lines (PO changes)
  - rtv_headers, rtv_lines (Returns to vendor)
  - bank_statements, reconciliation_results, reconciliation_exceptions (Payment recon)
  - workflow_runs, workflow_tasks, workflow_events (Workflow engine)
  - qc_templates, qc_results (Quality inspection)

Data seeded:
  - vendor_quotes: expanded to 50 rows
  - ap_aging: expanded to 100 rows
  - rfq_headers: 10 sample RFQs
  - qc_templates: 5 inspection templates

Usage:
  python -m backend.migrations.phase1_complete_seed
"""

import os
import sys
import logging
import random
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")


def run():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 1: SEED vendor_quotes to 50 rows
    # ═══════════════════════════════════════════════════════════════════
    log.info("1A. Seeding vendor_quotes to 50 rows...")
    cur.execute("SELECT count(*) FROM vendor_quotes")
    existing = cur.fetchone()[0]
    needed = 50 - existing

    if needed > 0:
        vendors = [
            ('1', 'Lopez-Sweeney'), ('2', 'Smith Manufacturing'), ('3', 'Global Parts Inc'),
            ('4', 'TechParts Dubai'), ('5', 'Emirates Steel'), ('6', 'Precision Engineering'),
            ('7', 'Al-Falah Trading'), ('8', 'Pacific Components'), ('9', 'Euro Metals GmbH'),
            ('10', 'Tata Industrial'),
        ]
        items = [
            ('Steel Bearings', 10, 15), ('Hydraulic Pumps', 200, 350),
            ('Electronic Controllers', 80, 150), ('Safety Valves', 30, 60),
            ('Copper Wire Rolls', 40, 80), ('Industrial Filters', 15, 35),
            ('Gasket Sets', 5, 15), ('Motor Assemblies', 500, 900),
        ]
        quotes = []
        for i in range(needed):
            vid, vname = random.choice(vendors)
            item, price_low, price_high = random.choice(items)
            price = round(random.uniform(price_low, price_high), 2)
            qty = random.choice([50, 100, 200, 500, 1000])
            lead = random.choice([7, 14, 21, 30, 45, 60])
            rfq_id = random.randint(1, 10)
            validity = (datetime.now() + timedelta(days=random.randint(30, 90))).strftime('%Y-%m-%d')
            quotes.append((rfq_id, vid, vname, item, price, lead, round(price * qty, 2), 'USD', 'submitted', False, validity))

        execute_values(cur, """
            INSERT INTO vendor_quotes (rfq_id, vendor_id, vendor_name, item_name, unit_price, lead_time_days, total_price, currency, status, recommended, validity_date)
            VALUES %s
        """, quotes)
        log.info(f"  Added {needed} quotes (total: 50)")
    else:
        log.info(f"  Already has {existing} quotes, skipping")
    conn.commit()

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 2: SEED ap_aging to 100 rows
    # ═══════════════════════════════════════════════════════════════════
    log.info("1B. Seeding ap_aging to 100 rows...")
    cur.execute("SELECT count(*) FROM ap_aging")
    existing = cur.fetchone()[0]
    needed = 100 - existing

    if needed > 0:
        vendors = [
            ('1', 'Lopez-Sweeney'), ('2', 'Smith Manufacturing'), ('3', 'Global Parts'),
            ('4', 'TechParts Dubai'), ('5', 'Emirates Steel'), ('6', 'Precision Eng'),
            ('7', 'Al-Falah Trading'), ('8', 'Pacific Components'), ('9', 'Euro Metals'),
            ('10', 'Tata Industrial'), ('11', 'Gulf Logistics'), ('12', 'Karachi Steel'),
            ('13', 'Riyadh Supplies'), ('14', 'Doha Equipment'), ('15', 'Mumbai Parts'),
        ]
        buckets = [
            ('current', 0, 0), ('1-30', 1, 30), ('31-60', 31, 60),
            ('61-90', 61, 90), ('90+', 91, 180),
        ]
        aging_rows = []
        for i in range(needed):
            vid, vname = random.choice(vendors)
            bucket_name, days_min, days_max = random.choice(buckets)
            days_overdue = random.randint(days_min, days_max) if days_max > 0 else 0
            amount = round(random.uniform(1000, 75000), 2)
            paid = round(amount * random.choice([0, 0, 0, 0.25, 0.5, 0.75, 1.0]), 2)
            outstanding = round(amount - paid, 2)
            inv_date = (datetime.now() - timedelta(days=days_overdue + 30)).strftime('%Y-%m-%d')
            due_date = (datetime.now() - timedelta(days=days_overdue)).strftime('%Y-%m-%d')
            status = 'paid' if paid >= amount else ('overdue' if days_overdue > 0 else 'open')
            inv_num = f"INV-2026-{random.randint(100, 999)}"
            dept = random.choice(['Engineering', 'IT', 'Finance', 'Operations', 'Procurement', 'HR'])
            aging_rows.append((vid, vname, inv_num, inv_date, due_date, amount, paid, outstanding, days_overdue, bucket_name, 'USD', status))

        execute_values(cur, """
            INSERT INTO ap_aging (vendor_id, vendor_name, invoice_number, invoice_date, due_date, amount, paid_amount, outstanding, days_overdue, aging_bucket, currency, status)
            VALUES %s
        """, aging_rows)
        log.info(f"  Added {needed} aging rows (total: 100)")
    else:
        log.info(f"  Already has {existing} rows, skipping")
    conn.commit()

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 3: CREATE RFQ TABLES
    # ═══════════════════════════════════════════════════════════════════
    log.info("1C. Creating RFQ tables...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfq_headers (
            id              SERIAL PRIMARY KEY,
            rfq_number      VARCHAR(50) UNIQUE NOT NULL,
            pr_number       VARCHAR(50),
            title           VARCHAR(500),
            description     TEXT,
            department      VARCHAR(100),
            requester       VARCHAR(200),
            status          VARCHAR(50) DEFAULT 'draft',
            submission_deadline DATE,
            vendors_invited INTEGER DEFAULT 0,
            quotes_received INTEGER DEFAULT 0,
            winning_vendor_id VARCHAR(50),
            winning_vendor_name VARCHAR(200),
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfq_lines (
            id              SERIAL PRIMARY KEY,
            rfq_id          INTEGER REFERENCES rfq_headers(id),
            item_name       VARCHAR(200) NOT NULL,
            description     TEXT,
            quantity        NUMERIC(18,2),
            unit_of_measure VARCHAR(50) DEFAULT 'EA',
            estimated_price NUMERIC(18,2),
            specifications  TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Seed 10 sample RFQs
    cur.execute("SELECT count(*) FROM rfq_headers")
    if cur.fetchone()[0] == 0:
        rfq_data = [
            ('RFQ-2026-001', 'PR-2026-001', 'Steel Bearings Supply', 'Engineering', 'draft', 3, 0),
            ('RFQ-2026-002', 'PR-2026-002', 'Hydraulic Pump Procurement', 'Operations', 'sent', 5, 3),
            ('RFQ-2026-003', 'PR-2026-003', 'Electronic Controllers', 'IT', 'evaluation', 4, 4),
            ('RFQ-2026-004', 'PR-2026-004', 'Safety Equipment', 'HSE', 'awarded', 3, 3),
            ('RFQ-2026-005', 'PR-2026-005', 'Office Furniture', 'HR', 'closed', 2, 2),
            ('RFQ-2026-006', None, 'Copper Wire Bulk Order', 'Engineering', 'draft', 0, 0),
            ('RFQ-2026-007', 'PR-2026-007', 'Industrial Filters', 'Operations', 'sent', 4, 1),
            ('RFQ-2026-008', 'PR-2026-008', 'Motor Assembly Parts', 'Engineering', 'evaluation', 3, 3),
            ('RFQ-2026-009', None, 'IT Infrastructure Upgrade', 'IT', 'draft', 0, 0),
            ('RFQ-2026-010', 'PR-2026-010', 'Chemical Supplies', 'Operations', 'sent', 6, 2),
        ]
        execute_values(cur, """
            INSERT INTO rfq_headers (rfq_number, pr_number, title, department, status, vendors_invited, quotes_received)
            VALUES %s
        """, rfq_data)
        log.info("  Seeded 10 RFQs")
    conn.commit()

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 4: CREATE PO AMENDMENT TABLES
    # ═══════════════════════════════════════════════════════════════════
    log.info("1D. Creating PO amendment tables...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS po_amendments (
            id              SERIAL PRIMARY KEY,
            amendment_number VARCHAR(50) UNIQUE NOT NULL,
            po_number       VARCHAR(50) NOT NULL,
            amendment_type  VARCHAR(50) NOT NULL,
            reason          TEXT,
            old_value       TEXT,
            new_value       TEXT,
            amount_impact   NUMERIC(18,2) DEFAULT 0,
            status          VARCHAR(50) DEFAULT 'pending',
            requested_by    VARCHAR(200),
            approved_by     VARCHAR(200),
            requires_re_approval BOOLEAN DEFAULT FALSE,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            approved_at     TIMESTAMPTZ
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS po_amendment_lines (
            id              SERIAL PRIMARY KEY,
            amendment_id    INTEGER REFERENCES po_amendments(id),
            field_changed   VARCHAR(100),
            old_value       TEXT,
            new_value       TEXT,
            line_number     INTEGER
        )
    """)
    conn.commit()
    log.info("  Created po_amendments + po_amendment_lines")

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 5: CREATE RTV TABLES
    # ═══════════════════════════════════════════════════════════════════
    log.info("1E. Creating RTV (Return to Vendor) tables...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rtv_headers (
            id              SERIAL PRIMARY KEY,
            rtv_number      VARCHAR(50) UNIQUE NOT NULL,
            grn_number      VARCHAR(50),
            po_number       VARCHAR(50),
            vendor_id       VARCHAR(50),
            vendor_name     VARCHAR(200),
            return_reason   VARCHAR(200),
            return_type     VARCHAR(50) DEFAULT 'quality_failure',
            total_return_qty NUMERIC(18,2) DEFAULT 0,
            total_return_value NUMERIC(18,2) DEFAULT 0,
            credit_expected NUMERIC(18,2) DEFAULT 0,
            status          VARCHAR(50) DEFAULT 'initiated',
            initiated_by    VARCHAR(200),
            approved_by     VARCHAR(200),
            shipped_date    DATE,
            credit_received_date DATE,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rtv_lines (
            id              SERIAL PRIMARY KEY,
            rtv_id          INTEGER REFERENCES rtv_headers(id),
            item_name       VARCHAR(200),
            return_qty      NUMERIC(18,2),
            unit_price      NUMERIC(18,2),
            return_value    NUMERIC(18,2),
            reason_code     VARCHAR(50),
            condition       VARCHAR(50) DEFAULT 'damaged',
            inspection_notes TEXT
        )
    """)
    conn.commit()
    log.info("  Created rtv_headers + rtv_lines")

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 6: CREATE BANK RECONCILIATION TABLES
    # ═══════════════════════════════════════════════════════════════════
    log.info("1F. Creating reconciliation tables...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bank_statements (
            id              SERIAL PRIMARY KEY,
            statement_ref   VARCHAR(100),
            bank_name       VARCHAR(200),
            account_number  VARCHAR(50),
            transaction_date DATE,
            value_date      DATE,
            description     TEXT,
            debit_amount    NUMERIC(18,2) DEFAULT 0,
            credit_amount   NUMERIC(18,2) DEFAULT 0,
            balance         NUMERIC(18,2),
            reference       VARCHAR(200),
            currency        VARCHAR(10) DEFAULT 'USD',
            matched         BOOLEAN DEFAULT FALSE,
            matched_to      VARCHAR(100),
            uploaded_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_results (
            id              SERIAL PRIMARY KEY,
            reconciliation_run_id VARCHAR(50),
            bank_statement_id INTEGER REFERENCES bank_statements(id),
            payment_run_id  VARCHAR(50),
            invoice_number  VARCHAR(100),
            vendor_name     VARCHAR(200),
            bank_amount     NUMERIC(18,2),
            ledger_amount   NUMERIC(18,2),
            variance        NUMERIC(18,2) DEFAULT 0,
            match_status    VARCHAR(50) DEFAULT 'unmatched',
            match_confidence NUMERIC(5,2),
            reconciled_at   TIMESTAMPTZ,
            reconciled_by   VARCHAR(200)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_exceptions (
            id              SERIAL PRIMARY KEY,
            reconciliation_run_id VARCHAR(50),
            exception_type  VARCHAR(50),
            description     TEXT,
            bank_amount     NUMERIC(18,2),
            ledger_amount   NUMERIC(18,2),
            vendor_name     VARCHAR(200),
            reference       VARCHAR(200),
            status          VARCHAR(50) DEFAULT 'open',
            resolved_by     VARCHAR(200),
            resolved_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    log.info("  Created bank_statements + reconciliation_results + reconciliation_exceptions")

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 7: CREATE WORKFLOW ENGINE TABLES
    # ═══════════════════════════════════════════════════════════════════
    log.info("1G. Creating workflow engine tables...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id              SERIAL PRIMARY KEY,
            workflow_run_id VARCHAR(50) UNIQUE NOT NULL,
            workflow_type   VARCHAR(50) NOT NULL,
            trigger_source  VARCHAR(100),
            trigger_data    JSONB DEFAULT '{}',
            status          VARCHAR(50) DEFAULT 'pending',
            current_task_id VARCHAR(50),
            total_tasks     INTEGER DEFAULT 0,
            completed_tasks INTEGER DEFAULT 0,
            failed_tasks    INTEGER DEFAULT 0,
            pr_number       VARCHAR(50),
            po_number       VARCHAR(50),
            invoice_number  VARCHAR(100),
            started_at      TIMESTAMPTZ DEFAULT NOW(),
            completed_at    TIMESTAMPTZ,
            error_message   TEXT,
            created_by      VARCHAR(200) DEFAULT 'system'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS workflow_tasks (
            id              SERIAL PRIMARY KEY,
            task_id         VARCHAR(50) UNIQUE NOT NULL,
            workflow_run_id VARCHAR(50) REFERENCES workflow_runs(workflow_run_id),
            task_name       VARCHAR(100) NOT NULL,
            task_type       VARCHAR(50) NOT NULL,
            agent_name      VARCHAR(100),
            status          VARCHAR(50) DEFAULT 'pending',
            depends_on      VARCHAR(50)[],
            input_data      JSONB DEFAULT '{}',
            output_data     JSONB DEFAULT '{}',
            wait_type       VARCHAR(50),
            wait_reason     TEXT,
            retry_count     INTEGER DEFAULT 0,
            max_retries     INTEGER DEFAULT 3,
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            error_message   TEXT,
            execution_time_ms INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS workflow_events (
            id              SERIAL PRIMARY KEY,
            event_id        VARCHAR(50) UNIQUE NOT NULL,
            workflow_run_id VARCHAR(50),
            task_id         VARCHAR(50),
            event_type      VARCHAR(100) NOT NULL,
            event_data      JSONB DEFAULT '{}',
            source_agent    VARCHAR(100),
            triggered_tasks VARCHAR(50)[],
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Create indexes for performance
    cur.execute("CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_workflow_runs_type ON workflow_runs(workflow_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_workflow_tasks_run ON workflow_tasks(workflow_run_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_workflow_tasks_status ON workflow_tasks(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_workflow_events_run ON workflow_events(workflow_run_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_workflow_events_type ON workflow_events(event_type)")
    conn.commit()
    log.info("  Created workflow_runs + workflow_tasks + workflow_events (with indexes)")

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 8: CREATE QC INSPECTION TABLES
    # ═══════════════════════════════════════════════════════════════════
    log.info("1H. Creating quality inspection tables...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS qc_templates (
            id              SERIAL PRIMARY KEY,
            template_name   VARCHAR(200) NOT NULL,
            category        VARCHAR(100),
            checklist_items JSONB NOT NULL DEFAULT '[]',
            pass_threshold  NUMERIC(5,2) DEFAULT 80.00,
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS qc_results (
            id              SERIAL PRIMARY KEY,
            grn_number      VARCHAR(50),
            po_number       VARCHAR(50),
            template_id     INTEGER REFERENCES qc_templates(id),
            item_name       VARCHAR(200),
            inspector       VARCHAR(200),
            inspection_date DATE DEFAULT CURRENT_DATE,
            checklist_results JSONB DEFAULT '[]',
            total_score     NUMERIC(5,2),
            pass_fail       VARCHAR(10) DEFAULT 'pending',
            notes           TEXT,
            hold_goods      BOOLEAN DEFAULT FALSE,
            trigger_rtv     BOOLEAN DEFAULT FALSE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Seed QC templates
    cur.execute("SELECT count(*) FROM qc_templates")
    if cur.fetchone()[0] == 0:
        import json
        templates = [
            ('General Goods Inspection', 'General', json.dumps([
                {"item": "Package intact", "weight": 10},
                {"item": "Quantity matches PO", "weight": 20},
                {"item": "No visible damage", "weight": 20},
                {"item": "Correct item received", "weight": 25},
                {"item": "Labels and documentation present", "weight": 10},
                {"item": "Expiry date valid (if applicable)", "weight": 15},
            ]), 80.00),
            ('Raw Materials Inspection', 'Materials', json.dumps([
                {"item": "Material grade matches specification", "weight": 25},
                {"item": "Dimensions within tolerance", "weight": 20},
                {"item": "Surface finish acceptable", "weight": 15},
                {"item": "Weight/quantity verified", "weight": 20},
                {"item": "Test certificate provided", "weight": 20},
            ]), 85.00),
            ('Electronic Components', 'Electronics', json.dumps([
                {"item": "Part number matches PO", "weight": 20},
                {"item": "No visible damage to components", "weight": 15},
                {"item": "Packaging ESD compliant", "weight": 10},
                {"item": "Quantity count accurate", "weight": 20},
                {"item": "Datasheet/specs provided", "weight": 15},
                {"item": "Functional test (sample)", "weight": 20},
            ]), 80.00),
            ('Chemical/Hazmat Inspection', 'Chemicals', json.dumps([
                {"item": "SDS (Safety Data Sheet) present", "weight": 25},
                {"item": "Container sealed and undamaged", "weight": 20},
                {"item": "Labels match order", "weight": 15},
                {"item": "Storage requirements documented", "weight": 15},
                {"item": "Expiry date valid", "weight": 25},
            ]), 90.00),
            ('Service Delivery Verification', 'Services', json.dumps([
                {"item": "Scope of work completed", "weight": 30},
                {"item": "Quality meets standards", "weight": 25},
                {"item": "Deliverables received", "weight": 20},
                {"item": "Timeframe adherence", "weight": 15},
                {"item": "Sign-off documentation", "weight": 10},
            ]), 75.00),
        ]
        execute_values(cur, """
            INSERT INTO qc_templates (template_name, category, checklist_items, pass_threshold)
            VALUES %s
        """, templates)
        log.info("  Seeded 5 QC templates")
    conn.commit()

    # ═══════════════════════════════════════════════════════════════════
    # FINAL VERIFICATION
    # ═══════════════════════════════════════════════════════════════════
    log.info("\n" + "=" * 60)
    log.info("PHASE 1 VERIFICATION")
    log.info("=" * 60)

    all_tables = [
        'vendor_quotes', 'ap_aging', 'rfq_headers', 'rfq_lines',
        'po_amendments', 'po_amendment_lines', 'rtv_headers', 'rtv_lines',
        'bank_statements', 'reconciliation_results', 'reconciliation_exceptions',
        'workflow_runs', 'workflow_tasks', 'workflow_events',
        'qc_templates', 'qc_results',
    ]

    for t in all_tables:
        cur.execute(f"SELECT count(*) FROM {t}")
        rows = cur.fetchone()[0]
        status = "OK" if rows > 0 or t.endswith('_lines') or t in ('po_amendments', 'rtv_headers', 'bank_statements', 'reconciliation_results', 'reconciliation_exceptions', 'workflow_runs', 'workflow_tasks', 'workflow_events', 'qc_results') else "SEEDED"
        log.info(f"  {status:6s}  {t:35s}  {rows:>5} rows")

    # Total table count
    cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
    total = cur.fetchone()[0]
    log.info(f"\n  Total tables in database: {total}")

    cur.close()
    conn.close()
    log.info("\nPHASE 1 COMPLETE")


if __name__ == '__main__':
    run()
