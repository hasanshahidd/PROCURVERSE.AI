"""
sprint6_invoice_pipeline_tables.py
====================================
Creates all system tables required for the 9-agent invoice-to-payment pipeline.

New tables:
  1. users                — internal users (approvers, finance, procurement, AP)
  2. email_templates      — per-event email subject+body templates
  3. notification_log     — every email/push sent (who, what, when, status)
  4. ocr_ingestion_log    — raw OCR output per document (PO / Invoice)
  5. discrepancy_log      — 3-way match discrepancies (qty/price/missing PO)
  6. invoice_holds        — holds placed on invoices (reason, resolver, resolved_at)
  7. payment_runs         — payment batch records (payment_run_id, total, status)

All tables live in PostgreSQL regardless of which ERP adapter is active.
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

    # ── 1. users ──────────────────────────────────────────────────────────────
    log.info("Creating table: users")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              SERIAL PRIMARY KEY,
            username        VARCHAR(100) UNIQUE NOT NULL,
            full_name       VARCHAR(200) NOT NULL,
            email           VARCHAR(200) UNIQUE NOT NULL,
            role            VARCHAR(50)  NOT NULL
                CHECK (role IN ('admin','procurement','finance','ap_specialist',
                                'approver','supplier','viewer')),
            department      VARCHAR(100),
            manager_email   VARCHAR(200),
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()

    # Seed a handful of default system users
    cur.execute("""
        INSERT INTO users (username, full_name, email, role, department, manager_email)
        VALUES
          ('sys_admin',       'System Administrator',  'admin@procure.ai',          'admin',        'IT',           NULL),
          ('ap_manager',      'AP Manager',            'ap.manager@procure.ai',     'approver',     'Accounts Payable', 'admin@procure.ai'),
          ('finance_head',    'Finance Head',          'finance@procure.ai',        'finance',      'Finance',      'admin@procure.ai'),
          ('proc_manager',    'Procurement Manager',   'procurement@procure.ai',    'procurement',  'Procurement',  'admin@procure.ai'),
          ('ap_specialist1',  'AP Specialist 1',       'ap1@procure.ai',            'ap_specialist','Accounts Payable','ap.manager@procure.ai'),
          ('ap_specialist2',  'AP Specialist 2',       'ap2@procure.ai',            'ap_specialist','Accounts Payable','ap.manager@procure.ai')
        ON CONFLICT (username) DO NOTHING
    """)
    conn.commit()
    log.info("  users seeded with 6 default users")

    # ── 2. email_templates ────────────────────────────────────────────────────
    log.info("Creating table: email_templates")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_templates (
            id              SERIAL PRIMARY KEY,
            event_type      VARCHAR(100) UNIQUE NOT NULL,
            subject         TEXT NOT NULL,
            body_html       TEXT NOT NULL,
            recipients_role VARCHAR(50),   -- default role to notify
            cc_role         VARCHAR(50),
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()

    # Seed templates for all 9 pipeline steps
    templates = [
        ('po_received',             'PO Received – {po_number}',
         '<p>A new Purchase Order <strong>{po_number}</strong> has been received from <strong>{vendor}</strong> and is queued for registration.</p>',
         'procurement', None),

        ('po_registered',           'PO Registered – {po_number}',
         '<p>PO <strong>{po_number}</strong> has been successfully registered in the ERP system.</p>',
         'procurement', 'finance'),

        ('po_discrepancy',          'PO Discrepancy Found – {po_number}',
         '<p>Discrepancy found during PO registration for <strong>{po_number}</strong>.<br>Issue: {discrepancy_detail}<br>Please review and take action.</p>',
         'procurement', 'ap_specialist'),

        ('invoice_received',        'Invoice Received – {invoice_number}',
         '<p>Invoice <strong>{invoice_number}</strong> from <strong>{vendor}</strong> has been captured and is pending matching.</p>',
         'ap_specialist', None),

        ('invoice_routed',          'Invoice Routed for Review – {invoice_number}',
         '<p>Invoice <strong>{invoice_number}</strong> (Amount: {currency} {amount}) has been routed to <strong>{department}</strong> for review.</p>',
         'ap_specialist', 'finance'),

        ('invoice_matched',         'Invoice Matched – {invoice_number}',
         '<p>3-way match <strong>PASSED</strong> for invoice <strong>{invoice_number}</strong>.<br>PO: {po_number} | GRN: {grn_number} | Amount: {amount}</p>',
         'ap_specialist', 'finance'),

        ('invoice_discrepancy',     'Invoice Discrepancy – {invoice_number}',
         '<p>Discrepancy detected on invoice <strong>{invoice_number}</strong>.<br>Type: {discrepancy_type}<br>Detail: {discrepancy_detail}<br>Action required.</p>',
         'ap_specialist', 'procurement'),

        ('discrepancy_supplier_notify', 'Action Required: Invoice {invoice_number} Discrepancy',
         '<p>Dear Supplier,<br>We have identified a discrepancy on Invoice <strong>{invoice_number}</strong>.<br>Issue: {discrepancy_detail}<br>Please provide clarification within 3 business days.</p>',
         'supplier', None),

        ('discrepancy_escalated',   'ESCALATED: Discrepancy on {invoice_number}',
         '<p>Invoice <strong>{invoice_number}</strong> discrepancy has been escalated after {days} days without resolution.<br>Please prioritise.</p>',
         'approver', 'finance'),

        ('payment_ready',           'Payment Ready – {invoice_number}',
         '<p>Invoice <strong>{invoice_number}</strong> has passed all checks and is <strong>Payment Ready</strong>.<br>Amount: {currency} {amount} | Due: {due_date}</p>',
         'finance', 'ap_specialist'),

        ('payment_approved',        'Payment Approved – {invoice_number}',
         '<p>Payment of <strong>{currency} {amount}</strong> for invoice <strong>{invoice_number}</strong> has been approved and payment instructions sent to treasury.</p>',
         'finance', 'ap_specialist'),

        ('payment_rejected',        'Payment Rejected – {invoice_number}',
         '<p>Payment for invoice <strong>{invoice_number}</strong> has been <strong>rejected</strong>.<br>Reason: {reason}</p>',
         'ap_specialist', 'procurement'),

        ('budget_exceeded',         'Budget Limit Exceeded – {department}',
         '<p>Budget for department <strong>{department} / {category}</strong> is at {utilization}% utilisation.<br>Requested: {requested} | Available: {available}</p>',
         'finance', 'approver'),

        ('approval_requested',      'Approval Required – {document_type} {document_id}',
         '<p>Your approval is required for <strong>{document_type} {document_id}</strong>.<br>Amount: {currency} {amount}<br>Submitted by: {submitter}</p>',
         'approver', None),

        ('approval_completed',      'Approved – {document_type} {document_id}',
         '<p><strong>{document_type} {document_id}</strong> has been approved by <strong>{approver}</strong>.</p>',
         'procurement', 'finance'),

        ('invoice_hold_placed',     'Invoice Hold Placed – {invoice_number}',
         '<p>A hold has been placed on invoice <strong>{invoice_number}</strong>.<br>Reason: {reason}</p>',
         'ap_specialist', 'finance'),

        ('invoice_hold_released',   'Invoice Hold Released – {invoice_number}',
         '<p>The hold on invoice <strong>{invoice_number}</strong> has been released by <strong>{resolver}</strong>.</p>',
         'ap_specialist', 'finance'),

        ('ocr_extraction_complete', 'OCR Complete – Document {document_ref}',
         '<p>OCR extraction completed for document <strong>{document_ref}</strong>.<br>Confidence: {confidence}%</p>',
         'ap_specialist', None),

        ('risk_flagged',            'Risk Alert – {document_type} {document_id}',
         '<p>Risk assessment flagged <strong>{document_type} {document_id}</strong> as HIGH risk.<br>Factors: {risk_factors}</p>',
         'approver', 'finance'),
    ]

    cur.executemany("""
        INSERT INTO email_templates (event_type, subject, body_html, recipients_role, cc_role)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (event_type) DO NOTHING
    """, templates)
    conn.commit()
    log.info(f"  email_templates seeded with {len(templates)} templates")

    # ── 3. notification_log ───────────────────────────────────────────────────
    log.info("Creating table: notification_log")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id              SERIAL PRIMARY KEY,
            event_type      VARCHAR(100) NOT NULL,
            document_type   VARCHAR(50),          -- 'PO', 'INVOICE', 'GRN', 'PR'
            document_id     VARCHAR(100),          -- PO number / Invoice number / etc.
            recipient_email VARCHAR(200) NOT NULL,
            recipient_role  VARCHAR(50),
            cc_email        VARCHAR(200),
            subject         TEXT,
            body_preview    TEXT,                  -- first 500 chars of body
            status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','sent','failed','bounced')),
            sent_at         TIMESTAMPTZ,
            error_message   TEXT,
            agent_name      VARCHAR(100),
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notif_document ON notification_log(document_type, document_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notif_status   ON notification_log(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notif_event    ON notification_log(event_type)")
    conn.commit()

    # ── 4. ocr_ingestion_log ──────────────────────────────────────────────────
    log.info("Creating table: ocr_ingestion_log")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ocr_ingestion_log (
            id                  SERIAL PRIMARY KEY,
            document_ref        VARCHAR(200),          -- file name / email subject
            document_type       VARCHAR(50)             -- 'PO', 'INVOICE', 'GRN'
                CHECK (document_type IN ('PO','INVOICE','GRN','UNKNOWN')),
            source_channel      VARCHAR(50)             -- 'email','portal','edi','api','scan'
                CHECK (source_channel IN ('email','portal','edi','api','scan','unknown')),
            sender              VARCHAR(200),
            received_at         TIMESTAMPTZ DEFAULT NOW(),
            ocr_raw_text        TEXT,
            extracted_fields    JSONB,                 -- {vendor, date, amount, line_items, ...}
            confidence_score    NUMERIC(5,2),          -- 0-100
            needs_review        BOOLEAN DEFAULT FALSE,
            reviewed_by         VARCHAR(100),
            reviewed_at         TIMESTAMPTZ,
            linked_po_number    VARCHAR(100),
            linked_invoice_no   VARCHAR(100),
            agent_name          VARCHAR(100),
            created_at          TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ocr_doc_type   ON ocr_ingestion_log(document_type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ocr_channel    ON ocr_ingestion_log(source_channel)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ocr_review     ON ocr_ingestion_log(needs_review) WHERE needs_review = TRUE")
    conn.commit()

    # ── 5. discrepancy_log ────────────────────────────────────────────────────
    log.info("Creating table: discrepancy_log")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS discrepancy_log (
            id                  SERIAL PRIMARY KEY,
            invoice_number      VARCHAR(100) NOT NULL,
            po_number           VARCHAR(100),
            grn_number          VARCHAR(100),
            discrepancy_type    VARCHAR(50) NOT NULL
                CHECK (discrepancy_type IN (
                    'qty_mismatch','price_variance','missing_po',
                    'missing_grn','duplicate_invoice','vendor_mismatch',
                    'currency_mismatch','other'
                )),
            po_value            NUMERIC(15,2),
            invoice_value       NUMERIC(15,2),
            grn_value           NUMERIC(15,2),
            variance_amount     NUMERIC(15,2),
            variance_pct        NUMERIC(7,2),
            description         TEXT,
            status              VARCHAR(30) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','notified_supplier','notified_procurement',
                                  'escalated','resolved','waived')),
            resolution_notes    TEXT,
            resolved_by         VARCHAR(100),
            resolved_at         TIMESTAMPTZ,
            escalation_count    INTEGER DEFAULT 0,
            last_escalated_at   TIMESTAMPTZ,
            agent_name          VARCHAR(100),
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_disc_invoice    ON discrepancy_log(invoice_number)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_disc_status     ON discrepancy_log(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_disc_type       ON discrepancy_log(discrepancy_type)")
    conn.commit()

    # ── 6. invoice_holds ──────────────────────────────────────────────────────
    log.info("Creating table: invoice_holds")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoice_holds (
            id              SERIAL PRIMARY KEY,
            invoice_number  VARCHAR(100) NOT NULL,
            po_number       VARCHAR(100),
            hold_reason     VARCHAR(100) NOT NULL
                CHECK (hold_reason IN (
                    'pending_grn','price_variance','qty_mismatch',
                    'missing_po','duplicate_suspected','budget_exceeded',
                    'approval_pending','supplier_query','manual_hold','other'
                )),
            hold_notes      TEXT,
            placed_by       VARCHAR(100) NOT NULL DEFAULT 'system',
            placed_at       TIMESTAMPTZ DEFAULT NOW(),
            resolved_by     VARCHAR(100),
            resolved_at     TIMESTAMPTZ,
            status          VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','released','auto_released')),
            agent_name      VARCHAR(100)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_holds_invoice   ON invoice_holds(invoice_number)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_holds_status    ON invoice_holds(status) WHERE status = 'active'")
    conn.commit()

    # ── 7. payment_runs ───────────────────────────────────────────────────────
    log.info("Creating table: payment_runs")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_runs (
            id                  SERIAL PRIMARY KEY,
            payment_run_id      VARCHAR(50) UNIQUE NOT NULL,
            run_date            DATE NOT NULL DEFAULT CURRENT_DATE,
            currency            VARCHAR(10) DEFAULT 'USD',
            total_amount        NUMERIC(18,2) DEFAULT 0,
            invoice_count       INTEGER DEFAULT 0,
            status              VARCHAR(30) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','approved','processing',
                                  'completed','failed','cancelled')),
            payment_method      VARCHAR(50),          -- 'ACH','WIRE','CHECK','EFT'
            bank_account_ref    VARCHAR(100),
            approved_by         VARCHAR(100),
            approved_at         TIMESTAMPTZ,
            processed_at        TIMESTAMPTZ,
            erp_payment_ref     VARCHAR(200),         -- ERP-side payment document ID
            notes               TEXT,
            agent_name          VARCHAR(100),
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pay_run_status  ON payment_runs(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pay_run_date    ON payment_runs(run_date)")
    conn.commit()

    # ── 8. payment_run_lines ─────────────────────────────────────────────────
    log.info("Creating table: payment_run_lines")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_run_lines (
            id                  SERIAL PRIMARY KEY,
            payment_run_id      VARCHAR(50) NOT NULL
                REFERENCES payment_runs(payment_run_id),
            invoice_number      VARCHAR(100) NOT NULL,
            vendor_id           VARCHAR(100),
            vendor_name         VARCHAR(200),
            invoice_amount      NUMERIC(15,2),
            payment_amount      NUMERIC(15,2),
            payment_type        VARCHAR(20) NOT NULL DEFAULT 'full'
                CHECK (payment_type IN ('full','partial','percentage')),
            payment_pct         NUMERIC(5,2),          -- for milestone/percentage payments
            due_date            DATE,
            payment_terms       VARCHAR(50),
            status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','paid','failed','cancelled')),
            erp_payment_ref     VARCHAR(200),
            created_at          TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payline_run     ON payment_run_lines(payment_run_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payline_invoice ON payment_run_lines(invoice_number)")
    conn.commit()

    # ── Final summary ──────────────────────────────────────────────────────────
    tables = ['users','email_templates','notification_log','ocr_ingestion_log',
              'discrepancy_log','invoice_holds','payment_runs','payment_run_lines']
    log.info("\n=== Sprint 6 Migration Complete ===")
    for tbl in tables:
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        n = cur.fetchone()[0]
        log.info(f"  {tbl:30} {n:>4} rows")

    cur.close()
    conn.close()


if __name__ == '__main__':
    run()
