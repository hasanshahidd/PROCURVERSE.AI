"""
Sprint 1 — NMI Full Schema Migration
Creates all 45 database tables from 58 NexaManufacturing Industries Excel files.
Run ONCE to set up the complete schema before data ingestion.

Tables created (grouped by domain):
  Master Data (12): vendors, items, chart_of_accounts, cost_centers, employees,
                    exchange_rates, uom_master, tax_codes, payment_terms,
                    warehouses, companies, buyers
  Procurement (7):  purchase_requisitions, approved_supplier_list,
                    vendor_evaluations, rfq_headers, vendor_quotes,
                    quote_comparisons, contracts
  Purchase Orders (5): po_headers, po_line_items, po_amendments,
                       po_approval_log, blanket_pos
  Goods Receipt (4): grn_headers, grn_line_items, qc_inspection_log,
                     returns_to_vendor
  Invoicing (6):   vendor_invoices, invoice_line_items, three_way_match_log,
                   invoice_exceptions, credit_debit_memos, invoice_approval_log
  Payments (7):    payment_proposals, payment_runs, bank_payment_files,
                   remittance_advice, payment_holds, early_payment_discounts,
                   ap_aging
  Analytics (4):   spend_analytics, budget_vs_actuals, vendor_performance,
                   duplicate_invoice_log

Usage:
    python backend/migrations/sprint1_nmi_schema.py
    python backend/migrations/sprint1_nmi_schema.py --drop  # drop and recreate
"""

import psycopg2
import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)


# ─────────────────────────────────────────────
#  DDL — All 45 tables
# ─────────────────────────────────────────────

MASTER_DATA_DDL = """
-- ══════════════════════════════════════════
--  MASTER DATA TABLES  (Files 01-12)
-- ══════════════════════════════════════════

-- File 01: Vendor Master
CREATE TABLE IF NOT EXISTS vendors (
    id                  SERIAL PRIMARY KEY,
    vendor_id           VARCHAR(20) UNIQUE NOT NULL,
    vendor_name         VARCHAR(255) NOT NULL,
    short_name          VARCHAR(50),
    category            VARCHAR(100),
    currency            VARCHAR(10) DEFAULT 'USD',
    country             VARCHAR(100),
    tax_id              VARCHAR(50),
    gst_vat_no          VARCHAR(50),
    address             TEXT,
    city                VARCHAR(100),
    postal_code         VARCHAR(20),
    phone               VARCHAR(50),
    email               VARCHAR(255),
    website             VARCHAR(255),
    payment_terms       VARCHAR(50),
    payment_method      VARCHAR(50),
    bank_name           VARCHAR(255),
    bank_account_no     VARCHAR(100),
    iban_swift          VARCHAR(50),
    credit_limit        DECIMAL(15,2),
    incoterms           VARCHAR(20),
    lead_time_days      INTEGER,
    min_order_qty       DECIMAL(15,4),
    contact_person      VARCHAR(255),
    vendor_rating       VARCHAR(10),
    hold_status         VARCHAR(20) DEFAULT 'Active',
    hold_reason         TEXT,
    approved_by         VARCHAR(255),
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vendors_category ON vendors(category);
CREATE INDEX IF NOT EXISTS idx_vendors_hold_status ON vendors(hold_status);
CREATE INDEX IF NOT EXISTS idx_vendors_country ON vendors(country);

-- File 02: Item / Product Master
CREATE TABLE IF NOT EXISTS items (
    id                  SERIAL PRIMARY KEY,
    item_code           VARCHAR(50) UNIQUE NOT NULL,
    item_description    VARCHAR(500) NOT NULL,
    item_type           VARCHAR(50),
    category            VARCHAR(100),
    sub_category        VARCHAR(100),
    uom                 VARCHAR(20),
    std_unit_cost       DECIMAL(15,4),
    currency            VARCHAR(10) DEFAULT 'USD',
    min_order_qty       DECIMAL(15,4),
    lead_time_days      INTEGER,
    reorder_point       DECIMAL(15,4),
    safety_stock        DECIMAL(15,4),
    gl_account          VARCHAR(20),
    cost_center         VARCHAR(20),
    tax_code            VARCHAR(20),
    hs_code             VARCHAR(20),
    weight_kg           DECIMAL(10,4),
    country_of_origin   VARCHAR(100),
    shelf_life_days     INTEGER,
    qc_required         BOOLEAN DEFAULT FALSE,
    hazardous           BOOLEAN DEFAULT FALSE,
    active              BOOLEAN DEFAULT TRUE,
    odoo_ref            VARCHAR(50),
    erp_ref_d365        VARCHAR(50),
    erp_ref_sap         VARCHAR(50),
    erp_ref_oracle      VARCHAR(50),
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_type ON items(item_type);

-- File 03: Chart of Accounts
CREATE TABLE IF NOT EXISTS chart_of_accounts (
    id              SERIAL PRIMARY KEY,
    account_code    VARCHAR(20) UNIQUE NOT NULL,
    account_name    VARCHAR(255) NOT NULL,
    account_type    VARCHAR(50),
    sub_type        VARCHAR(50),
    currency        VARCHAR(10) DEFAULT 'PKR',
    normal_balance  VARCHAR(10) CHECK (normal_balance IN ('Debit', 'Credit')),
    pl_bs           VARCHAR(5)  CHECK (pl_bs IN ('P&L', 'BS')),
    cost_center     VARCHAR(20),
    parent_account  VARCHAR(20),
    tax_applicable  BOOLEAN DEFAULT FALSE,
    description     TEXT,
    odoo_account    VARCHAR(20),
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- File 04: Cost Center / Department Master
CREATE TABLE IF NOT EXISTS cost_centers (
    id                      SERIAL PRIMARY KEY,
    cost_center_code        VARCHAR(20) UNIQUE NOT NULL,
    cost_center_name        VARCHAR(255) NOT NULL,
    department              VARCHAR(100),
    type                    VARCHAR(20) CHECK (type IN ('Direct', 'Indirect', 'Overhead')),
    location                VARCHAR(100),
    manager                 VARCHAR(255),
    budget_holder           VARCHAR(255),
    annual_budget_pkr       DECIMAL(18,2),
    annual_budget_usd       DECIMAL(15,2),
    currency                VARCHAR(10) DEFAULT 'PKR',
    company_code            VARCHAR(20),
    profit_center           VARCHAR(20),
    parent_cc               VARCHAR(20),
    gl_account_prefix       VARCHAR(30),
    active                  BOOLEAN DEFAULT TRUE,
    created_at              TIMESTAMP DEFAULT NOW()
);

-- File 05: Employee / User Master
CREATE TABLE IF NOT EXISTS employees (
    id                  SERIAL PRIMARY KEY,
    user_id             VARCHAR(20) UNIQUE NOT NULL,
    full_name           VARCHAR(255) NOT NULL,
    username            VARCHAR(100) UNIQUE,
    email               VARCHAR(255) UNIQUE NOT NULL,
    department          VARCHAR(100),
    job_title           VARCHAR(100),
    role                VARCHAR(50),
    approval_limit_pkr  DECIMAL(15,2),
    approval_limit_usd  DECIMAL(12,2),
    cost_center         VARCHAR(20),
    company_code        VARCHAR(20),
    location            VARCHAR(100),
    manager             VARCHAR(255),
    erp_access_level    VARCHAR(20),
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_employees_role ON employees(role);
CREATE INDEX IF NOT EXISTS idx_employees_dept ON employees(department);

-- File 06: Currency & Exchange Rates
CREATE TABLE IF NOT EXISTS exchange_rates (
    id              SERIAL PRIMARY KEY,
    period          VARCHAR(20),
    from_currency   VARCHAR(10) NOT NULL,
    to_currency     VARCHAR(10) NOT NULL DEFAULT 'PKR',
    exchange_rate   DECIMAL(15,6) NOT NULL,
    rate_type       VARCHAR(20),
    effective_date  DATE NOT NULL,
    expiry_date     DATE,
    source          VARCHAR(100),
    entered_by      VARCHAR(100),
    status          VARCHAR(20) DEFAULT 'Active',
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_exchange_rates_period ON exchange_rates(period);
CREATE INDEX IF NOT EXISTS idx_exchange_rates_currencies ON exchange_rates(from_currency, to_currency);

-- File 07: Unit of Measure Master
CREATE TABLE IF NOT EXISTS uom_master (
    id                  SERIAL PRIMARY KEY,
    uom_code            VARCHAR(20) UNIQUE NOT NULL,
    uom_name            VARCHAR(100) NOT NULL,
    uom_type            VARCHAR(50),
    base_uom            VARCHAR(20),
    conversion_factor   DECIMAL(15,6) DEFAULT 1.0,
    decimal_places      INTEGER DEFAULT 2,
    description         TEXT,
    odoo_uom            VARCHAR(50),
    active              BOOLEAN DEFAULT TRUE
);

-- File 08: Tax Code Master
CREATE TABLE IF NOT EXISTS tax_codes (
    id              SERIAL PRIMARY KEY,
    tax_code        VARCHAR(20) UNIQUE NOT NULL,
    tax_name        VARCHAR(255) NOT NULL,
    tax_type        VARCHAR(50),
    rate_pct        DECIMAL(7,4) NOT NULL,
    currency        VARCHAR(10),
    country         VARCHAR(100),
    applicable_to   VARCHAR(50),
    gl_account      VARCHAR(20),
    jurisdiction    VARCHAR(100),
    recoverable     BOOLEAN DEFAULT TRUE,
    exempt          BOOLEAN DEFAULT FALSE,
    description     TEXT,
    active          BOOLEAN DEFAULT TRUE
);

-- File 09: Payment Terms Master
CREATE TABLE IF NOT EXISTS payment_terms (
    id                      SERIAL PRIMARY KEY,
    term_code               VARCHAR(20) UNIQUE NOT NULL,
    term_description        VARCHAR(255) NOT NULL,
    net_days                INTEGER NOT NULL,
    discount_pct            DECIMAL(5,2) DEFAULT 0,
    discount_days           INTEGER DEFAULT 0,
    penalty_pct             DECIMAL(5,2) DEFAULT 0,
    penalty_grace_days      INTEGER DEFAULT 0,
    base_date               VARCHAR(50),
    currency                VARCHAR(10),
    applicable_to           VARCHAR(50),
    erp_code_odoo           VARCHAR(50),
    erp_code_d365           VARCHAR(50),
    erp_code_sap            VARCHAR(50),
    erp_code_oracle         VARCHAR(50),
    active                  BOOLEAN DEFAULT TRUE
);

-- File 10: Warehouse / Location Master
CREATE TABLE IF NOT EXISTS warehouses (
    id                  SERIAL PRIMARY KEY,
    warehouse_code      VARCHAR(20) UNIQUE NOT NULL,
    warehouse_name      VARCHAR(255) NOT NULL,
    type                VARCHAR(50),
    address             TEXT,
    city                VARCHAR(100),
    country             VARCHAR(100),
    manager             VARCHAR(255),
    capacity_sqm        DECIMAL(10,2),
    capacity_pallets    INTEGER,
    temp_controlled     BOOLEAN DEFAULT FALSE,
    hazmat_approved     BOOLEAN DEFAULT FALSE,
    operating_hours     VARCHAR(100),
    company_code        VARCHAR(20),
    odoo_wh_code        VARCHAR(50),
    erp_plant_sap       VARCHAR(50),
    erp_site_d365       VARCHAR(50),
    active              BOOLEAN DEFAULT TRUE
);

-- File 11: Company / Entity Master
CREATE TABLE IF NOT EXISTS companies (
    id                  SERIAL PRIMARY KEY,
    company_code        VARCHAR(20) UNIQUE NOT NULL,
    legal_name          VARCHAR(255) NOT NULL,
    short_name          VARCHAR(50),
    country             VARCHAR(100),
    currency            VARCHAR(10),
    tax_reg_no          VARCHAR(50),
    gst_vat_no          VARCHAR(50),
    registered_address  TEXT,
    city                VARCHAR(100),
    fiscal_year_start   VARCHAR(10),
    fiscal_year_end     VARCHAR(10),
    chart_of_accounts   VARCHAR(20),
    bank_account        VARCHAR(100),
    industry            VARCHAR(100),
    parent_company      VARCHAR(20),
    erp_company_code    VARCHAR(100),
    active              BOOLEAN DEFAULT TRUE
);

-- File 12: Buyer / Purchasing Agent Master
CREATE TABLE IF NOT EXISTS buyers (
    id                      SERIAL PRIMARY KEY,
    buyer_id                VARCHAR(20) UNIQUE NOT NULL,
    buyer_name              VARCHAR(255) NOT NULL,
    email                   VARCHAR(255),
    phone                   VARCHAR(50),
    category_responsibility VARCHAR(255),
    spend_limit_usd         DECIMAL(15,2),
    preferred_vendor_ids    TEXT,
    active_pos              INTEGER DEFAULT 0,
    languages               VARCHAR(100),
    location                VARCHAR(100),
    reporting_to            VARCHAR(255),
    active                  BOOLEAN DEFAULT TRUE,
    created_at              TIMESTAMP DEFAULT NOW()
);
"""

PROCUREMENT_DDL = """
-- ══════════════════════════════════════════
--  PROCUREMENT TABLES  (Files 13-19)
-- ══════════════════════════════════════════

-- File 13: Purchase Requisitions
CREATE TABLE IF NOT EXISTS purchase_requisitions (
    id                      SERIAL PRIMARY KEY,
    pr_number               VARCHAR(30) UNIQUE NOT NULL,
    pr_date                 DATE NOT NULL,
    requester               VARCHAR(255),
    department              VARCHAR(100),
    cost_center             VARCHAR(20),
    item_code               VARCHAR(50),
    item_description        VARCHAR(500),
    qty                     DECIMAL(15,4),
    uom                     VARCHAR(20),
    est_unit_price          DECIMAL(15,4),
    currency                VARCHAR(10) DEFAULT 'USD',
    est_total               DECIMAL(15,2),
    preferred_vendor        VARCHAR(20),
    vendor_name             VARCHAR(255),
    required_by_date        DATE,
    business_justification  TEXT,
    priority                VARCHAR(20) DEFAULT 'Normal'
                                CHECK (priority IN ('Urgent', 'High', 'Normal', 'Low')),
    budget_code             VARCHAR(50),
    budget_amount           DECIMAL(15,2),
    variance_to_budget      DECIMAL(15,2),
    approval_required       BOOLEAN DEFAULT TRUE,
    approval_status         VARCHAR(20) DEFAULT 'Draft'
                                CHECK (approval_status IN ('Draft','Pending','Approved','Rejected','Cancelled')),
    approved_by             VARCHAR(255),
    approval_date           DATE,
    exception_flag          BOOLEAN DEFAULT FALSE,
    notes                   TEXT,
    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pr_status ON purchase_requisitions(approval_status);
CREATE INDEX IF NOT EXISTS idx_pr_date ON purchase_requisitions(pr_date);
CREATE INDEX IF NOT EXISTS idx_pr_requester ON purchase_requisitions(requester);

-- File 14: Approved Supplier List
CREATE TABLE IF NOT EXISTS approved_supplier_list (
    id                      SERIAL PRIMARY KEY,
    asl_id                  VARCHAR(20) UNIQUE NOT NULL,
    vendor_id               VARCHAR(20) NOT NULL,
    vendor_name             VARCHAR(255),
    item_code               VARCHAR(50),
    item_category           VARCHAR(100),
    approval_status         VARCHAR(20) DEFAULT 'Approved',
    preferred_rank          INTEGER DEFAULT 1,
    approved_by             VARCHAR(255),
    approval_date           DATE,
    expiry_date             DATE,
    annual_spend_cap_usd    DECIMAL(15,2),
    ytd_spend_usd           DECIMAL(15,2),
    qualification_basis     TEXT,
    quality_cert            VARCHAR(255),
    last_audit_date         DATE,
    notes                   TEXT,
    created_at              TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_asl_vendor ON approved_supplier_list(vendor_id);
CREATE INDEX IF NOT EXISTS idx_asl_item ON approved_supplier_list(item_code);

-- File 15: Vendor Evaluation Scorecard
CREATE TABLE IF NOT EXISTS vendor_evaluations (
    id                          SERIAL PRIMARY KEY,
    scorecard_id                VARCHAR(20) UNIQUE NOT NULL,
    vendor_id                   VARCHAR(20) NOT NULL,
    vendor_name                 VARCHAR(255),
    evaluation_period           VARCHAR(50),
    evaluator                   VARCHAR(255),
    on_time_delivery_pct        DECIMAL(5,2),
    quality_score               DECIMAL(5,2),
    invoice_accuracy_pct        DECIMAL(5,2),
    responsiveness_score        DECIMAL(5,2),
    compliance_score            DECIMAL(5,2),
    price_competitiveness       DECIMAL(5,2),
    overall_score               DECIMAL(5,2),
    rating                      VARCHAR(5),
    issues_noted                TEXT,
    action_required             TEXT,
    next_review                 DATE,
    created_at                  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vendor_eval_vendor ON vendor_evaluations(vendor_id);

-- File 16: Request for Quotation (RFQ)
CREATE TABLE IF NOT EXISTS rfq_headers (
    id                  SERIAL PRIMARY KEY,
    rfq_number          VARCHAR(30) UNIQUE NOT NULL,
    rfq_date            DATE NOT NULL,
    pr_reference        VARCHAR(30),
    item_code           VARCHAR(50),
    item_description    VARCHAR(500),
    qty_required        DECIMAL(15,4),
    uom                 VARCHAR(20),
    target_price        DECIMAL(15,4),
    currency            VARCHAR(10) DEFAULT 'USD',
    vendors_invited     TEXT,
    no_of_vendors       INTEGER,
    rfq_deadline        DATE,
    submission_method   VARCHAR(50),
    buyer               VARCHAR(255),
    status              VARCHAR(20) DEFAULT 'Open'
                            CHECK (status IN ('Open','Closed','Cancelled','Awarded')),
    selected_vendor     VARCHAR(20),
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- File 17: Vendor Quotes / Bids
CREATE TABLE IF NOT EXISTS vendor_quotes (
    id                      SERIAL PRIMARY KEY,
    quote_id                VARCHAR(30) UNIQUE NOT NULL,
    rfq_reference           VARCHAR(30),
    vendor_id               VARCHAR(20) NOT NULL,
    vendor_name             VARCHAR(255),
    item_code               VARCHAR(50),
    qty_quoted              DECIMAL(15,4),
    unit_price              DECIMAL(15,4),
    currency                VARCHAR(10),
    total_quote_value       DECIMAL(15,2),
    lead_time_days          INTEGER,
    validity_days           INTEGER,
    payment_terms           VARCHAR(50),
    delivery_terms          VARCHAR(50),
    tax_rate                DECIMAL(5,2),
    total_incl_tax          DECIMAL(15,2),
    technical_compliance    VARCHAR(20),
    recommended             BOOLEAN DEFAULT FALSE,
    rejection_reason        TEXT,
    created_at              TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_quotes_rfq ON vendor_quotes(rfq_reference);
CREATE INDEX IF NOT EXISTS idx_quotes_vendor ON vendor_quotes(vendor_id);

-- File 18: Quote Comparison Sheet
CREATE TABLE IF NOT EXISTS quote_comparisons (
    id                      SERIAL PRIMARY KEY,
    comparison_id           VARCHAR(30) UNIQUE NOT NULL,
    rfq_reference           VARCHAR(30),
    item_code               VARCHAR(50),
    item_description        VARCHAR(500),
    qty                     DECIMAL(15,4),
    vendor1_id              VARCHAR(20),
    vendor1_price           DECIMAL(15,4),
    vendor1_total           DECIMAL(15,2),
    vendor2_id              VARCHAR(20),
    vendor2_price           DECIMAL(15,4),
    vendor2_total           DECIMAL(15,2),
    vendor3_id              VARCHAR(20),
    vendor3_price           DECIMAL(15,4),
    vendor3_total           DECIMAL(15,2),
    currency                VARCHAR(10),
    price_savings           DECIMAL(15,2),
    savings_pct             DECIMAL(7,4),
    recommended_vendor      VARCHAR(20),
    recommendation_basis    TEXT,
    approved_by             VARCHAR(255),
    approval_date           DATE,
    created_at              TIMESTAMP DEFAULT NOW()
);

-- File 19: Contracts Master
CREATE TABLE IF NOT EXISTS contracts (
    id                  SERIAL PRIMARY KEY,
    contract_no         VARCHAR(30) UNIQUE NOT NULL,
    vendor_id           VARCHAR(20) NOT NULL,
    vendor_name         VARCHAR(255),
    contract_type       VARCHAR(50),
    category            VARCHAR(100),
    start_date          DATE,
    end_date            DATE,
    contract_value      DECIMAL(15,2),
    currency            VARCHAR(10) DEFAULT 'USD',
    committed_spend     DECIMAL(15,2),
    ytd_spend           DECIMAL(15,2),
    balance             DECIMAL(15,2),
    payment_terms       VARCHAR(50),
    auto_renew          BOOLEAN DEFAULT FALSE,
    notice_period_days  INTEGER,
    key_sla             TEXT,
    contract_owner      VARCHAR(255),
    status              VARCHAR(20) DEFAULT 'Active'
                            CHECK (status IN ('Draft','Active','Expired','Terminated','Under Review')),
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_contracts_vendor ON contracts(vendor_id);
CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(status);
CREATE INDEX IF NOT EXISTS idx_contracts_end_date ON contracts(end_date);
"""

PURCHASE_ORDER_DDL = """
-- ══════════════════════════════════════════
--  PURCHASE ORDER TABLES  (Files 20-25)
-- ══════════════════════════════════════════

-- File 20: Purchase Order Headers
CREATE TABLE IF NOT EXISTS po_headers (
    id                  SERIAL PRIMARY KEY,
    po_number           VARCHAR(30) UNIQUE NOT NULL,
    po_date             DATE NOT NULL,
    pr_reference        VARCHAR(30),
    vendor_id           VARCHAR(20) NOT NULL,
    vendor_name         VARCHAR(255),
    buyer               VARCHAR(255),
    payment_terms       VARCHAR(50),
    currency            VARCHAR(10) DEFAULT 'USD',
    delivery_address    TEXT,
    requested_delivery  DATE,
    promised_delivery   DATE,
    po_subtotal         DECIMAL(15,2),
    tax_amount          DECIMAL(15,2),
    po_grand_total      DECIMAL(15,2),
    approval_status     VARCHAR(20) DEFAULT 'Pending'
                            CHECK (approval_status IN ('Draft','Pending','Approved','Rejected','Cancelled')),
    approved_by         VARCHAR(255),
    approval_date       DATE,
    po_status           VARCHAR(20) DEFAULT 'Open'
                            CHECK (po_status IN ('Open','Partially Received','Fully Received','Closed','Cancelled')),
    erp_doc_type        VARCHAR(50),
    exception_flag      BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    odoo_po_id          INTEGER,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_po_vendor ON po_headers(vendor_id);
CREATE INDEX IF NOT EXISTS idx_po_status ON po_headers(po_status);
CREATE INDEX IF NOT EXISTS idx_po_approval ON po_headers(approval_status);
CREATE INDEX IF NOT EXISTS idx_po_date ON po_headers(po_date);

-- File 21: PO Line Items
CREATE TABLE IF NOT EXISTS po_line_items (
    id                  SERIAL PRIMARY KEY,
    line_id             VARCHAR(30) UNIQUE,
    po_number           VARCHAR(30) NOT NULL,
    line_no             INTEGER NOT NULL,
    item_code           VARCHAR(50),
    item_description    VARCHAR(500),
    qty_ordered         DECIMAL(15,4),
    uom                 VARCHAR(20),
    unit_price          DECIMAL(15,4),
    currency            VARCHAR(10),
    discount_pct        DECIMAL(5,2) DEFAULT 0,
    net_unit_price      DECIMAL(15,4),
    line_total          DECIMAL(15,2),
    tax_code            VARCHAR(20),
    tax_amount          DECIMAL(15,2),
    line_total_incl_tax DECIMAL(15,2),
    gl_account          VARCHAR(20),
    cost_center         VARCHAR(20),
    delivery_address    TEXT,
    req_delivery_date   DATE,
    status              VARCHAR(20) DEFAULT 'Open',
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_po_lines_po ON po_line_items(po_number);

-- File 22: PO Amendments / Change Orders
CREATE TABLE IF NOT EXISTS po_amendments (
    id                  SERIAL PRIMARY KEY,
    amendment_id        VARCHAR(30) UNIQUE NOT NULL,
    po_number           VARCHAR(30) NOT NULL,
    amendment_date      DATE,
    change_type         VARCHAR(50),
    original_value      VARCHAR(500),
    amended_value       VARCHAR(500),
    currency            VARCHAR(10),
    delta               DECIMAL(15,2),
    reason_for_change   TEXT,
    requested_by        VARCHAR(255),
    approved_by         VARCHAR(255),
    approval_date       DATE,
    vendor_acknowledged BOOLEAN DEFAULT FALSE,
    status              VARCHAR(20) DEFAULT 'Pending',
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- File 24: PO Approval Workflow Log
CREATE TABLE IF NOT EXISTS po_approval_log (
    id                  SERIAL PRIMARY KEY,
    log_id              VARCHAR(30) UNIQUE,
    po_number           VARCHAR(30) NOT NULL,
    po_date             DATE,
    po_value            DECIMAL(15,2),
    currency            VARCHAR(10),
    step_no             INTEGER,
    approver_role       VARCHAR(100),
    approver_name       VARCHAR(255),
    action              VARCHAR(20) CHECK (action IN ('Approved','Rejected','Escalated','Delegated')),
    action_date         TIMESTAMP,
    time_taken_hrs      DECIMAL(7,2),
    sla_hours           DECIMAL(7,2),
    sla_met             BOOLEAN,
    comments            TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_po_approval_log_po ON po_approval_log(po_number);

-- File 23: Blanket Purchase Orders
CREATE TABLE IF NOT EXISTS blanket_pos (
    id                  SERIAL PRIMARY KEY,
    bpo_number          VARCHAR(30) UNIQUE NOT NULL,
    vendor_id           VARCHAR(20) NOT NULL,
    vendor_name         VARCHAR(255),
    category            VARCHAR(100),
    start_date          DATE,
    end_date            DATE,
    total_value         DECIMAL(15,2),
    currency            VARCHAR(10),
    released_value      DECIMAL(15,2),
    remaining_value     DECIMAL(15,2),
    release_count       INTEGER DEFAULT 0,
    status              VARCHAR(20) DEFAULT 'Active',
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);
"""

GOODS_RECEIPT_DDL = """
-- ══════════════════════════════════════════
--  GOODS RECEIPT TABLES  (Files 26-30)
-- ══════════════════════════════════════════

-- File 26: Goods Receipt Notes (GRN Headers)
CREATE TABLE IF NOT EXISTS grn_headers (
    id                  SERIAL PRIMARY KEY,
    grn_number          VARCHAR(30) UNIQUE NOT NULL,
    grn_date            DATE NOT NULL,
    po_reference        VARCHAR(30) NOT NULL,
    vendor_id           VARCHAR(20),
    vendor_name         VARCHAR(255),
    received_by         VARCHAR(255),
    warehouse           VARCHAR(20),
    delivery_note_no    VARCHAR(50),
    carrier             VARCHAR(100),
    airway_bill_bol     VARCHAR(100),
    packages_received   INTEGER,
    total_weight_kg     DECIMAL(10,3),
    grn_status          VARCHAR(20) DEFAULT 'Draft'
                            CHECK (grn_status IN ('Draft','Partial','Complete','Rejected')),
    qc_status           VARCHAR(20) DEFAULT 'Pending'
                            CHECK (qc_status IN ('Pending','Pass','Fail','Partial Pass')),
    exception_flag      BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grn_po ON grn_headers(po_reference);
CREATE INDEX IF NOT EXISTS idx_grn_status ON grn_headers(grn_status);
CREATE INDEX IF NOT EXISTS idx_grn_date ON grn_headers(grn_date);

-- File 27: GRN Line Items
CREATE TABLE IF NOT EXISTS grn_line_items (
    id                  SERIAL PRIMARY KEY,
    grn_line_id         VARCHAR(30) UNIQUE,
    grn_number          VARCHAR(30) NOT NULL,
    po_number           VARCHAR(30),
    item_code           VARCHAR(50),
    item_description    VARCHAR(500),
    po_qty              DECIMAL(15,4),
    received_qty        DECIMAL(15,4),
    variance_qty        DECIMAL(15,4),
    uom                 VARCHAR(20),
    unit_cost           DECIMAL(15,4),
    currency            VARCHAR(10),
    line_value          DECIMAL(15,2),
    lot_batch_no        VARCHAR(100),
    serial_numbers      TEXT,
    expiry_date         DATE,
    storage_location    VARCHAR(100),
    qc_status           VARCHAR(20) DEFAULT 'Pending',
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grn_lines_grn ON grn_line_items(grn_number);

-- File 28: Inspection / QC Log
CREATE TABLE IF NOT EXISTS qc_inspection_log (
    id                      SERIAL PRIMARY KEY,
    qc_log_id               VARCHAR(30) UNIQUE NOT NULL,
    grn_reference           VARCHAR(30) NOT NULL,
    inspection_date         DATE,
    item_code               VARCHAR(50),
    item_description        VARCHAR(500),
    inspector               VARCHAR(255),
    sample_size             INTEGER,
    accepted_qty            DECIMAL(15,4),
    rejected_qty            DECIMAL(15,4),
    rejection_reason        TEXT,
    qc_result               VARCHAR(20) CHECK (qc_result IN ('Pass','Fail','Conditional')),
    corrective_action       TEXT,
    re_inspection_required  BOOLEAN DEFAULT FALSE,
    certificate_ref         VARCHAR(100),
    notes                   TEXT,
    created_at              TIMESTAMP DEFAULT NOW()
);

-- File 29: Returns to Vendor
CREATE TABLE IF NOT EXISTS returns_to_vendor (
    id                  SERIAL PRIMARY KEY,
    rtv_id              VARCHAR(30) UNIQUE NOT NULL,
    grn_reference       VARCHAR(30),
    po_reference        VARCHAR(30),
    vendor_id           VARCHAR(20) NOT NULL,
    vendor_name         VARCHAR(255),
    return_date         DATE,
    item_code           VARCHAR(50),
    item_description    VARCHAR(500),
    return_qty          DECIMAL(15,4),
    uom                 VARCHAR(20),
    unit_cost           DECIMAL(15,4),
    currency            VARCHAR(10),
    return_value        DECIMAL(15,2),
    return_reason       TEXT,
    return_type         VARCHAR(30),
    credit_note_ref     VARCHAR(30),
    status              VARCHAR(20) DEFAULT 'Pending',
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);
"""

INVOICING_DDL = """
-- ══════════════════════════════════════════
--  INVOICE TABLES  (Files 31-37)
-- ══════════════════════════════════════════

-- File 32: Vendor Invoices (header)
CREATE TABLE IF NOT EXISTS vendor_invoices (
    id                  SERIAL PRIMARY KEY,
    invoice_no          VARCHAR(30) UNIQUE NOT NULL,
    vendor_invoice_no   VARCHAR(50),
    invoice_date        DATE NOT NULL,
    po_reference        VARCHAR(30),
    grn_reference       VARCHAR(30),
    vendor_id           VARCHAR(20) NOT NULL,
    vendor_name         VARCHAR(255),
    invoice_type        VARCHAR(30) DEFAULT 'Standard'
                            CHECK (invoice_type IN ('Standard','Credit Note','Debit Memo','Proforma','Recurring')),
    subtotal            DECIMAL(15,2),
    tax_amount          DECIMAL(15,2),
    invoice_total       DECIMAL(15,2) NOT NULL,
    currency            VARCHAR(10) DEFAULT 'USD',
    payment_terms       VARCHAR(50),
    due_date            DATE,
    gl_account          VARCHAR(20),
    cost_center         VARCHAR(20),
    ap_status           VARCHAR(20) DEFAULT 'Pending'
                            CHECK (ap_status IN ('Pending','Approved','On Hold','Paid','Cancelled','Disputed')),
    three_way_match_status VARCHAR(20) DEFAULT 'Pending'
                            CHECK (three_way_match_status IN ('Pending','Matched','Partial','Exception','Overridden')),
    approved_by         VARCHAR(255),
    exception_flag      BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_inv_vendor ON vendor_invoices(vendor_id);
CREATE INDEX IF NOT EXISTS idx_inv_status ON vendor_invoices(ap_status);
CREATE INDEX IF NOT EXISTS idx_inv_3wm ON vendor_invoices(three_way_match_status);
CREATE INDEX IF NOT EXISTS idx_inv_due ON vendor_invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_inv_po ON vendor_invoices(po_reference);

-- File 33: Invoice Line Items
CREATE TABLE IF NOT EXISTS invoice_line_items (
    id                  SERIAL PRIMARY KEY,
    inv_line_id         VARCHAR(30) UNIQUE,
    invoice_no          VARCHAR(30) NOT NULL,
    line_no             INTEGER,
    item_code           VARCHAR(50),
    item_description    VARCHAR(500),
    qty_invoiced        DECIMAL(15,4),
    uom                 VARCHAR(20),
    unit_price          DECIMAL(15,4),
    currency            VARCHAR(10),
    discount_pct        DECIMAL(5,2) DEFAULT 0,
    net_price           DECIMAL(15,4),
    line_subtotal       DECIMAL(15,2),
    tax_code            VARCHAR(20),
    tax_amt             DECIMAL(15,2),
    line_total          DECIMAL(15,2),
    gl_account          VARCHAR(20),
    cost_center         VARCHAR(20),
    exception           TEXT,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_inv_lines_inv ON invoice_line_items(invoice_no);

-- File 31: Three-Way Match Log
CREATE TABLE IF NOT EXISTS three_way_match_log (
    id                  SERIAL PRIMARY KEY,
    match_id            VARCHAR(30) UNIQUE NOT NULL,
    po_number           VARCHAR(30),
    grn_number          VARCHAR(30),
    invoice_number      VARCHAR(30),
    vendor              VARCHAR(255),
    item_code           VARCHAR(50),
    po_qty              DECIMAL(15,4),
    grn_qty             DECIMAL(15,4),
    inv_qty             DECIMAL(15,4),
    po_price            DECIMAL(15,4),
    inv_price           DECIMAL(15,4),
    currency            VARCHAR(10),
    po_total            DECIMAL(15,2),
    grn_value           DECIMAL(15,2),
    inv_total           DECIMAL(15,2),
    qty_match           BOOLEAN,
    price_match         BOOLEAN,
    value_match         BOOLEAN,
    match_result        VARCHAR(20) CHECK (match_result IN ('Matched','Partial','Exception','Overridden')),
    exception_type      VARCHAR(100),
    action_required     TEXT,
    resolved            BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_3wm_po ON three_way_match_log(po_number);
CREATE INDEX IF NOT EXISTS idx_3wm_inv ON three_way_match_log(invoice_number);
CREATE INDEX IF NOT EXISTS idx_3wm_result ON three_way_match_log(match_result);

-- File 35: Invoice Exceptions Log
CREATE TABLE IF NOT EXISTS invoice_exceptions (
    id                  SERIAL PRIMARY KEY,
    exception_id        VARCHAR(30) UNIQUE NOT NULL,
    invoice_no          VARCHAR(30),
    po_reference        VARCHAR(30),
    vendor              VARCHAR(255),
    exception_type      VARCHAR(100),
    exception_date      DATE,
    po_amount           DECIMAL(15,2),
    invoice_amount      DECIMAL(15,2),
    currency            VARCHAR(10),
    variance            DECIMAL(15,2),
    variance_pct        DECIMAL(7,4),
    detected_by         VARCHAR(255),
    detection_method    VARCHAR(50),
    assigned_to         VARCHAR(255),
    status              VARCHAR(20) DEFAULT 'Open',
    resolution          TEXT,
    resolved_date       DATE,
    impact              VARCHAR(20),
    created_at          TIMESTAMP DEFAULT NOW()
);

-- File 37: Invoice Approval Workflow Log
CREATE TABLE IF NOT EXISTS invoice_approval_log (
    id                  SERIAL PRIMARY KEY,
    log_id              VARCHAR(30) UNIQUE,
    invoice_no          VARCHAR(30) NOT NULL,
    step_no             INTEGER,
    approver_role       VARCHAR(100),
    approver_name       VARCHAR(255),
    action              VARCHAR(20),
    action_date         TIMESTAMP,
    time_taken_hrs      DECIMAL(7,2),
    sla_met             BOOLEAN,
    comments            TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);
"""

PAYMENT_DDL = """
-- ══════════════════════════════════════════
--  PAYMENT TABLES  (Files 39-46)
-- ══════════════════════════════════════════

-- File 39: Payment Proposals
CREATE TABLE IF NOT EXISTS payment_proposals (
    id                      SERIAL PRIMARY KEY,
    proposal_id             VARCHAR(30) UNIQUE NOT NULL,
    proposal_date           DATE,
    invoice_no              VARCHAR(30) NOT NULL,
    vendor_id               VARCHAR(20),
    vendor_name             VARCHAR(255),
    invoice_amount          DECIMAL(15,2),
    currency                VARCHAR(10),
    due_date                DATE,
    proposed_payment_date   DATE,
    early_pay_discount_pct  DECIMAL(5,2),
    discount_amount         DECIMAL(15,2),
    net_payment             DECIMAL(15,2),
    payment_method          VARCHAR(30),
    bank_account            VARCHAR(100),
    included_in_run         BOOLEAN DEFAULT FALSE,
    status                  VARCHAR(20) DEFAULT 'Proposed',
    notes                   TEXT,
    created_at              TIMESTAMP DEFAULT NOW()
);

-- File 40: Payment Runs
CREATE TABLE IF NOT EXISTS payment_runs (
    id                  SERIAL PRIMARY KEY,
    payment_run_id      VARCHAR(30) UNIQUE NOT NULL,
    run_date            DATE NOT NULL,
    run_type            VARCHAR(30),
    no_of_payments      INTEGER,
    total_amount_pkr    DECIMAL(18,2),
    currencies          VARCHAR(100),
    run_by              VARCHAR(255),
    approved_by         VARCHAR(255),
    bank_file_ref       VARCHAR(100),
    status              VARCHAR(20) DEFAULT 'Draft'
                            CHECK (status IN ('Draft','Approved','Submitted','Completed','Failed')),
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- File 44: Payment Exceptions / Holds
CREATE TABLE IF NOT EXISTS payment_holds (
    id                  SERIAL PRIMARY KEY,
    exception_id        VARCHAR(30) UNIQUE NOT NULL,
    invoice_no          VARCHAR(30) NOT NULL,
    po_reference        VARCHAR(30),
    vendor              VARCHAR(255),
    hold_reason         TEXT,
    hold_date           DATE,
    invoice_amount      DECIMAL(15,2),
    currency            VARCHAR(10),
    held_amount         DECIMAL(15,2),
    hold_owner          VARCHAR(255),
    status              VARCHAR(20) DEFAULT 'On Hold',
    resolution          TEXT,
    release_date        DATE,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- File 43: Early Payment Discounts Log
CREATE TABLE IF NOT EXISTS early_payment_discounts (
    id                  SERIAL PRIMARY KEY,
    discount_id         VARCHAR(30) UNIQUE,
    invoice_no          VARCHAR(30) NOT NULL,
    vendor_id           VARCHAR(20),
    invoice_amount      DECIMAL(15,2),
    currency            VARCHAR(10),
    discount_pct        DECIMAL(5,2),
    discount_amount     DECIMAL(15,2),
    discount_deadline   DATE,
    payment_date        DATE,
    captured            BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- File 46: AP Aging Report
CREATE TABLE IF NOT EXISTS ap_aging (
    id                  SERIAL PRIMARY KEY,
    vendor_id           VARCHAR(20) NOT NULL,
    vendor_name         VARCHAR(255),
    invoice_no          VARCHAR(30),
    invoice_date        DATE,
    due_date            DATE,
    invoice_amount      DECIMAL(15,2),
    currency            VARCHAR(10),
    current_balance     DECIMAL(15,2),
    bucket_0_30         DECIMAL(15,2) DEFAULT 0,
    bucket_31_60        DECIMAL(15,2) DEFAULT 0,
    bucket_61_90        DECIMAL(15,2) DEFAULT 0,
    bucket_91_plus      DECIMAL(15,2) DEFAULT 0,
    total_outstanding   DECIMAL(15,2),
    dpo_days            INTEGER,
    snapshot_date       DATE DEFAULT CURRENT_DATE,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ap_aging_vendor ON ap_aging(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ap_aging_snapshot ON ap_aging(snapshot_date);
"""

ANALYTICS_DDL = """
-- ══════════════════════════════════════════
--  ANALYTICS & REPORTING TABLES  (Files 47-53)
-- ══════════════════════════════════════════

-- File 47: Spend Analytics Dataset
CREATE TABLE IF NOT EXISTS spend_analytics (
    id                      SERIAL PRIMARY KEY,
    transaction_id          VARCHAR(30) UNIQUE NOT NULL,
    period                  VARCHAR(20),
    month                   VARCHAR(20),
    quarter                 VARCHAR(10),
    vendor_id               VARCHAR(20),
    vendor_name             VARCHAR(255),
    category                VARCHAR(100),
    sub_category            VARCHAR(100),
    item_code               VARCHAR(50),
    item_description        VARCHAR(500),
    qty                     DECIMAL(15,4),
    uom                     VARCHAR(20),
    unit_price              DECIMAL(15,4),
    currency                VARCHAR(10),
    total_amount_usd        DECIMAL(15,2),
    legal_entity            VARCHAR(20),
    cost_center             VARCHAR(20),
    gl_account              VARCHAR(20),
    po_number               VARCHAR(30),
    buyer                   VARCHAR(255),
    spend_classification    VARCHAR(50),
    created_at              TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_spend_period ON spend_analytics(period);
CREATE INDEX IF NOT EXISTS idx_spend_vendor ON spend_analytics(vendor_id);
CREATE INDEX IF NOT EXISTS idx_spend_category ON spend_analytics(category);
CREATE INDEX IF NOT EXISTS idx_spend_entity ON spend_analytics(legal_entity);

-- File 48: Budget vs Actuals
CREATE TABLE IF NOT EXISTS budget_vs_actuals (
    id                  SERIAL PRIMARY KEY,
    cost_center         VARCHAR(20) NOT NULL,
    cost_center_name    VARCHAR(255),
    gl_account          VARCHAR(20),
    gl_account_name     VARCHAR(255),
    category            VARCHAR(50),
    q1_budget           DECIMAL(15,2),
    q1_actual           DECIMAL(15,2),
    q1_variance         DECIMAL(15,2),
    q1_variance_pct     DECIMAL(7,2),
    q2_budget           DECIMAL(15,2),
    q2_actual           DECIMAL(15,2),
    q2_variance         DECIMAL(15,2),
    q2_variance_pct     DECIMAL(7,2),
    q3_budget           DECIMAL(15,2),
    q3_actual           DECIMAL(15,2),
    q3_variance         DECIMAL(15,2),
    q3_variance_pct     DECIMAL(7,2),
    q4_budget           DECIMAL(15,2),
    q4_actual           DECIMAL(15,2),
    q4_variance         DECIMAL(15,2),
    q4_variance_pct     DECIMAL(7,2),
    fy_budget           DECIMAL(15,2),
    fy_actual           DECIMAL(15,2),
    fy_variance         DECIMAL(15,2),
    fy_variance_pct     DECIMAL(7,2),
    status              VARCHAR(20),
    exception_flag      TEXT,
    fiscal_year         INTEGER DEFAULT 2025,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_budget_cc ON budget_vs_actuals(cost_center);

-- File 49: Vendor Performance Dashboard
CREATE TABLE IF NOT EXISTS vendor_performance (
    id                          SERIAL PRIMARY KEY,
    vendor_id                   VARCHAR(20) NOT NULL,
    vendor_name                 VARCHAR(255),
    category                    VARCHAR(100),
    total_pos                   INTEGER,
    total_spend_usd             DECIMAL(15,2),
    on_time_delivery_pct        DECIMAL(5,2),
    quality_pass_rate_pct       DECIMAL(5,2),
    invoice_accuracy_pct        DECIMAL(5,2),
    price_compliance_pct        DECIMAL(5,2),
    lead_time_days              DECIMAL(7,1),
    defect_rate_pct             DECIMAL(5,2),
    returns_count               INTEGER DEFAULT 0,
    disputes_count              INTEGER DEFAULT 0,
    overall_score               DECIMAL(5,2),
    rating                      VARCHAR(5),
    preferred                   BOOLEAN DEFAULT FALSE,
    comments                    TEXT,
    review_period               VARCHAR(50),
    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vend_perf_vendor ON vendor_performance(vendor_id);

-- File 52: Duplicate Invoice Detection Log
CREATE TABLE IF NOT EXISTS duplicate_invoice_log (
    id                  SERIAL PRIMARY KEY,
    detection_id        VARCHAR(30) UNIQUE NOT NULL,
    detection_date      DATE,
    invoice_1           VARCHAR(30),
    invoice_2           VARCHAR(30),
    vendor_id           VARCHAR(20),
    vendor_name         VARCHAR(255),
    amount_1            DECIMAL(15,2),
    amount_2            DECIMAL(15,2),
    currency            VARCHAR(10),
    match_criteria      VARCHAR(255),
    similarity_pct      VARCHAR(10),
    detection_method    VARCHAR(50),
    status              VARCHAR(50),
    action_taken        TEXT,
    reviewed_by         VARCHAR(255),
    resolution_date     DATE,
    savings_avoided_usd DECIMAL(15,2),
    exception_flag      VARCHAR(100),
    created_at          TIMESTAMP DEFAULT NOW()
);
"""

SYSTEM_DDL = """
-- ══════════════════════════════════════════
--  SYSTEM / CONFIG TABLES  (Files 53-58)
-- ══════════════════════════════════════════

-- File 53: Audit Trail / Change Log
CREATE TABLE IF NOT EXISTS audit_trail (
    id                  SERIAL PRIMARY KEY,
    log_id              VARCHAR(30) UNIQUE,
    timestamp           TIMESTAMP NOT NULL DEFAULT NOW(),
    user_id             VARCHAR(20),
    user_name           VARCHAR(255),
    role                VARCHAR(100),
    module              VARCHAR(100),
    transaction_id      VARCHAR(50),
    action              VARCHAR(20) CHECK (action IN ('CREATE','UPDATE','DELETE','APPROVE','REJECT','AMEND','BLOCK')),
    field_changed       VARCHAR(100),
    old_value           TEXT,
    new_value           TEXT,
    reason              TEXT,
    ip_address          VARCHAR(45),
    erp_system          VARCHAR(50),
    legal_entity        VARCHAR(20),
    change_category     VARCHAR(50),
    risk_flag           VARCHAR(20) DEFAULT 'Low'
                            CHECK (risk_flag IN ('Low','Medium','High','Critical'))
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_trail(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_module ON audit_trail(module);
CREATE INDEX IF NOT EXISTS idx_audit_txn ON audit_trail(transaction_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_trail(timestamp);

-- File 56: Workflow Approval Matrix
CREATE TABLE IF NOT EXISTS workflow_approval_matrix (
    id                  SERIAL PRIMARY KEY,
    workflow_id         VARCHAR(20) UNIQUE NOT NULL,
    process             VARCHAR(100),
    document_type       VARCHAR(20),
    threshold_min       DECIMAL(15,2),
    threshold_max       DECIMAL(15,2),
    currency            VARCHAR(10),
    l1_approver         VARCHAR(255),
    l1_role             VARCHAR(100),
    l1_limit            DECIMAL(15,2),
    l2_approver         VARCHAR(255),
    l2_role             VARCHAR(100),
    l2_limit            DECIMAL(15,2),
    l3_approver         VARCHAR(255),
    l3_role             VARCHAR(100),
    sla_hours           INTEGER,
    escalation_hours    INTEGER,
    auto_approve        BOOLEAN DEFAULT FALSE,
    conditions          TEXT,
    erp_workflow_name   VARCHAR(100),
    override_approver   VARCHAR(255),
    status              VARCHAR(20) DEFAULT 'ACTIVE',
    created_at          TIMESTAMP DEFAULT NOW()
);

-- File 58: Integration Transaction Log
CREATE TABLE IF NOT EXISTS integration_transaction_log (
    id                  SERIAL PRIMARY KEY,
    txn_id              VARCHAR(50) UNIQUE NOT NULL,
    timestamp           TIMESTAMP DEFAULT NOW(),
    source_system       VARCHAR(50),
    target_system       VARCHAR(50),
    operation           VARCHAR(50),
    entity_type         VARCHAR(50),
    entity_id           VARCHAR(100),
    status              VARCHAR(20) CHECK (status IN ('Success','Failed','Pending','Retry')),
    error_code          VARCHAR(20),
    error_message       TEXT,
    retry_count         INTEGER DEFAULT 0,
    payload_size_bytes  INTEGER,
    duration_ms         INTEGER,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_integ_log_ts ON integration_transaction_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_integ_log_status ON integration_transaction_log(status);
CREATE INDEX IF NOT EXISTS idx_integ_log_entity ON integration_transaction_log(entity_type, entity_id);

-- Data ingestion tracking table (tracks which Excel files have been loaded)
CREATE TABLE IF NOT EXISTS data_ingestion_log (
    id              SERIAL PRIMARY KEY,
    source_file     VARCHAR(255) NOT NULL,
    table_name      VARCHAR(100) NOT NULL,
    rows_loaded     INTEGER,
    rows_skipped    INTEGER,
    status          VARCHAR(20) DEFAULT 'Pending'
                        CHECK (status IN ('Pending','Running','Complete','Failed')),
    error_message   TEXT,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);
"""

# ─────────────────────────────────────────────
#  Migration runner
# ─────────────────────────────────────────────

ALL_DDL_BLOCKS = [
    ("Master Data (12 tables)",   MASTER_DATA_DDL),
    ("Procurement (7 tables)",    PROCUREMENT_DDL),
    ("Purchase Orders (5 tables)", PURCHASE_ORDER_DDL),
    ("Goods Receipt (4 tables)",  GOODS_RECEIPT_DDL),
    ("Invoicing (6 tables)",      INVOICING_DDL),
    ("Payments (5 tables)",       PAYMENT_DDL),
    ("Analytics (4 tables)",      ANALYTICS_DDL),
    ("System / Config (4 tables)", SYSTEM_DDL),
]


def run_migration(drop_first: bool = False):
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        if drop_first:
            print("DROP mode — removing existing NMI tables...")
            drop_tables = [
                "integration_transaction_log", "data_ingestion_log",
                "workflow_approval_matrix", "audit_trail",
                "duplicate_invoice_log", "vendor_performance",
                "budget_vs_actuals", "spend_analytics",
                "ap_aging", "early_payment_discounts", "payment_holds",
                "payment_runs", "payment_proposals",
                "invoice_approval_log", "invoice_exceptions",
                "three_way_match_log", "invoice_line_items", "vendor_invoices",
                "returns_to_vendor", "qc_inspection_log",
                "grn_line_items", "grn_headers",
                "blanket_pos", "po_approval_log", "po_amendments",
                "po_line_items", "po_headers",
                "contracts", "quote_comparisons", "vendor_quotes",
                "rfq_headers", "vendor_evaluations",
                "approved_supplier_list", "purchase_requisitions",
                "buyers", "warehouses", "companies",
                "payment_terms", "tax_codes", "uom_master",
                "exchange_rates", "employees", "cost_centers",
                "chart_of_accounts", "items", "vendors",
            ]
            for t in drop_tables:
                cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
                print(f"   Dropped: {t}")
            conn.commit()

        print("\nCreating NMI schema tables...\n")
        for group_name, ddl in ALL_DDL_BLOCKS:
            print(f"  ▶ {group_name}")
            cur.execute(ddl)
            conn.commit()
            print(f"    Done")

        # Final count
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                'vendors','items','chart_of_accounts','cost_centers','employees',
                'exchange_rates','uom_master','tax_codes','payment_terms',
                'warehouses','companies','buyers',
                'purchase_requisitions','approved_supplier_list','vendor_evaluations',
                'rfq_headers','vendor_quotes','quote_comparisons','contracts',
                'po_headers','po_line_items','po_amendments','po_approval_log','blanket_pos',
                'grn_headers','grn_line_items','qc_inspection_log','returns_to_vendor',
                'vendor_invoices','invoice_line_items','three_way_match_log',
                'invoice_exceptions','invoice_approval_log',
                'payment_proposals','payment_runs','payment_holds',
                'early_payment_discounts','ap_aging',
                'spend_analytics','budget_vs_actuals','vendor_performance',
                'duplicate_invoice_log',
                'audit_trail','workflow_approval_matrix',
                'integration_transaction_log','data_ingestion_log'
              );
        """)
        count = cur.fetchone()[0]
        print(f"\nSprint 1 schema migration complete — {count}/46 tables created.")

    except Exception as e:
        conn.rollback()
        print(f"\nMigration failed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sprint 1 NMI Schema Migration")
    parser.add_argument("--drop", action="store_true",
                        help="Drop and recreate all tables (destructive!)")
    args = parser.parse_args()

    if args.drop:
        confirm = input("This will DROP all NMI tables. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    run_migration(drop_first=args.drop)
