"""
Sprint 5C Batch 2 — Approved Supplier List, Invoice Lines, GRN Lines,
                     Budget vs Actuals, Vendor Performance
6 ERPs × 5 modules = 30 tables
"""
import os, sys
from pathlib import Path
os.chdir(str(Path(__file__).resolve().parents[2])); sys.path.insert(0, ".")
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/odoo_procurement_demo"))
cur  = conn.cursor()

ERPS = ['odoo','sap_s4','sap_b1','dynamics','oracle','erpnext']
VND_ODOO  = list(range(13, 23))
VND_SAP   = [f'000010{i:04d}' for i in range(1, 11)]
VND_B1    = ['V-GTS001','V-ESA002','V-AIC003','V-EOS004','V-PSR005',
             'V-SCL006','V-TMS007','V-FLL008','V-NCA009','V-DOP010']
VND_DYN   = [f'V-{i:05d}' for i in range(1, 11)]
VND_ORA   = [f'SUP-{i:05d}' for i in range(1, 11)]
VND_ERP   = [f'SUP-{i:05d}' for i in range(1, 11)]
ITEMS_ODOO   = [f'ITEM-{i:03d}' for i in range(1,11)]
ITEMS_SAP    = [f'MAT-1000{i}' for i in range(1,11)]
ITEMS_B1     = [f'I-ITEM{i:03d}' for i in range(1,11)]
ITEMS_DYN    = [f'I-{i:03d}' for i in range(1,11)]
ITEMS_ORA    = [f'IT-{i:05d}' for i in range(1,11)]
ITEMS_ERP    = [f'ITEM-{i:03d}' for i in range(1,11)]
ITEM_DESC    = ['Steel Sheet Metal','Aluminum Billets','Industrial Bearing',
                'Hydraulic Fitting','Electronic PCB','Rubber Gasket',
                'Industrial Solvent','Packaging Box','Safety Helmet','Cutting Insert']
INV_ODOO  = [f'BILL/2025/{i:05d}' for i in range(1,11)]
INV_SAP   = [f'51000000{i:02d}' for i in range(1,11)]
INV_B1    = list(range(20001, 20011))
INV_DYN   = [f'GTS-INV-2025-{i:04d}01' for i in range(1,11)]
INV_ORA   = [f'INV-{i:05d}' for i in range(1,11)]
INV_ERP   = [f'ACC-PINV-2025-{i:05d}' for i in range(1,11)]
GRN_ODOO  = [f'WH/IN/2025/{i:05d}' for i in range(1,9)]
GRN_SAP   = [f'50000000{i:02d}' for i in range(1,9)]
GRN_B1    = list(range(30001, 30009))
GRN_DYN   = [f'PR-{i:06d}' for i in range(1,9)]
GRN_ORA   = [f'REC-{i:05d}' for i in range(1,9)]
GRN_ERP   = [f'MAT-PRE-2025-{i:05d}' for i in range(1,9)]
COST_CENTERS = ['CC-001','CC-002','CC-003','CC-004','CC-005']
VEND_NAMES   = ['Global Tech Supplies LLC','Euro Steel AG','Apex Industrial Components',
                'EuroStar Office Supplies','Pak Steel & Raw Materials',
                'Sigma Chemicals Ltd','TechMed Solutions','FastLog Logistics',
                'Nordic Components AB','Delta Office Products']

schemas = {}

# ── approved_supplier_list ────────────────────────────────────────────────────
schemas['approved_supplier_list_odoo'] = """
CREATE TABLE IF NOT EXISTS approved_supplier_list_odoo (
    id              SERIAL PRIMARY KEY,
    product_id      VARCHAR(50),          -- item internal reference
    partner_id      INTEGER,              -- FK vendors_odoo.id
    min_qty         NUMERIC(15,3),
    price           NUMERIC(15,2),
    currency_id     VARCHAR(5),
    delay           INTEGER,              -- lead time days
    sequence        INTEGER DEFAULT 1,    -- preferred rank
    date_start      DATE,
    date_end        DATE,
    name            VARCHAR(100),
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['approved_supplier_list_sap_s4'] = """
CREATE TABLE IF NOT EXISTS approved_supplier_list_sap_s4 (
    INFNR   VARCHAR(10) PRIMARY KEY,   -- info record number
    MATNR   VARCHAR(18),               -- material
    LIFNR   VARCHAR(10),               -- vendor
    EKORG   VARCHAR(4),                -- purchasing org
    WERKS   VARCHAR(4),                -- plant
    PREIS   NUMERIC(15,2),             -- net price
    PEINH   NUMERIC(9,0) DEFAULT 1,    -- price unit
    WAERS   VARCHAR(5),
    MINBM   NUMERIC(15,3),             -- minimum order qty
    WEBAZ   INTEGER,                   -- GR processing time (lead days)
    DATAB   DATE,                      -- valid from
    DATBI   DATE,                      -- valid to
    ESOKZ   VARCHAR(1) DEFAULT '0',    -- info record type
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['approved_supplier_list_sap_b1'] = """
CREATE TABLE IF NOT EXISTS approved_supplier_list_sap_b1 (
    LineId      SERIAL PRIMARY KEY,
    ItemCode    VARCHAR(20),
    CardCode    VARCHAR(15),
    CardName    VARCHAR(100),
    Priority    INTEGER,               -- preferred rank
    MinOrderQty NUMERIC(15,3),
    Price       NUMERIC(15,2),
    Currency    VARCHAR(3),
    LeadTime    INTEGER,
    ValidFrom   DATE,
    ValidTo     DATE,
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['approved_supplier_list_dynamics'] = """
CREATE TABLE IF NOT EXISTS approved_supplier_list_dynamics (
    LineId              SERIAL PRIMARY KEY,
    ItemNumber          VARCHAR(20),
    VendorAccountNumber VARCHAR(20),
    VendorName          VARCHAR(200),
    PreferredRank       INTEGER,
    MinOrderQty         NUMERIC(15,3),
    UnitPrice           NUMERIC(15,2),
    CurrencyCode        VARCHAR(3),
    DeliveryLeadDays    INTEGER,
    ValidFrom           DATE,
    ValidTo             DATE,
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['approved_supplier_list_oracle'] = """
CREATE TABLE IF NOT EXISTS approved_supplier_list_oracle (
    LineId              SERIAL PRIMARY KEY,
    ItemNumber          VARCHAR(40),
    SupplierNumber      VARCHAR(20),
    SupplierName        VARCHAR(360),
    PreferredRank       INTEGER,
    MinOrderQuantity    NUMERIC(15,3),
    UnitPrice           NUMERIC(15,2),
    CurrencyCode        VARCHAR(15),
    FixedLeadTime       INTEGER,
    EnabledFlag         VARCHAR(1) DEFAULT 'Y',
    StartDate           DATE,
    EndDate             DATE,
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['approved_supplier_list_erpnext'] = """
CREATE TABLE IF NOT EXISTS approved_supplier_list_erpnext (
    name            VARCHAR(140) PRIMARY KEY,
    parent          VARCHAR(140),          -- item_code
    supplier        VARCHAR(140),
    supplier_name   VARCHAR(140),
    supplier_part_no VARCHAR(140),
    lead_time_days  INTEGER,
    min_qty         NUMERIC(15,3),
    price           NUMERIC(15,2),
    currency        VARCHAR(10),
    valid_from      DATE,
    valid_to        DATE,
    erp_source      VARCHAR(20) DEFAULT 'erpnext'
)"""

# ── invoice_lines ─────────────────────────────────────────────────────────────
schemas['invoice_lines_odoo'] = """
CREATE TABLE IF NOT EXISTS invoice_lines_odoo (
    id              SERIAL PRIMARY KEY,
    move_id         VARCHAR(64),          -- FK invoices_odoo.name
    sequence        INTEGER,
    product_id      VARCHAR(50),
    name            VARCHAR(200),
    quantity        NUMERIC(15,4),
    product_uom_id  VARCHAR(10),
    price_unit      NUMERIC(15,2),
    discount        NUMERIC(5,2) DEFAULT 0,
    price_subtotal  NUMERIC(15,2),
    price_tax       NUMERIC(15,2),
    price_total     NUMERIC(15,2),
    account_id      VARCHAR(20),
    analytic_account_id VARCHAR(50),
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['invoice_lines_sap_s4'] = """
CREATE TABLE IF NOT EXISTS invoice_lines_sap_s4 (
    BELNR   VARCHAR(10),               -- invoice document
    BUZEI   VARCHAR(3),                -- line item
    GJAHR   VARCHAR(4),
    MATNR   VARCHAR(18),
    TXZ01   VARCHAR(40),
    MENGE   NUMERIC(15,3),
    MEINS   VARCHAR(3),
    WRBTR   NUMERIC(15,2),             -- amount
    MWSKZ   VARCHAR(2),                -- tax code
    EBELN   VARCHAR(10),               -- PO reference
    EBELP   VARCHAR(5),                -- PO line
    SAKTO   VARCHAR(10),               -- GL account
    KOSTL   VARCHAR(10),               -- cost center
    PRIMARY KEY (BELNR, BUZEI),
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['invoice_lines_sap_b1'] = """
CREATE TABLE IF NOT EXISTS invoice_lines_sap_b1 (
    DocNum      INTEGER,
    LineNum     INTEGER,
    ItemCode    VARCHAR(20),
    Dscription  VARCHAR(100),
    Quantity    NUMERIC(15,3),
    UomCode     VARCHAR(8),
    Price       NUMERIC(15,2),
    DiscPrcnt   NUMERIC(5,2) DEFAULT 0,
    LineTotal   NUMERIC(15,2),
    TaxCode     VARCHAR(8),
    WhsCode     VARCHAR(8),
    BaseRef     VARCHAR(20),           -- PO reference
    OcrCode     VARCHAR(50),
    PRIMARY KEY (DocNum, LineNum),
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['invoice_lines_dynamics'] = """
CREATE TABLE IF NOT EXISTS invoice_lines_dynamics (
    VendorInvoiceNumber VARCHAR(50),
    LineNumber          INTEGER,
    ItemNumber          VARCHAR(20),
    ProductName         VARCHAR(200),
    Quantity            NUMERIC(15,3),
    Unit                VARCHAR(10),
    UnitPrice           NUMERIC(15,2),
    DiscountPercent     NUMERIC(5,2) DEFAULT 0,
    LineAmount          NUMERIC(15,2),
    TaxGroup            VARCHAR(20),
    PurchaseOrderNumber VARCHAR(20),
    CostCenter          VARCHAR(50),
    PRIMARY KEY (VendorInvoiceNumber, LineNumber),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['invoice_lines_oracle'] = """
CREATE TABLE IF NOT EXISTS invoice_lines_oracle (
    InvoiceNumber   VARCHAR(50),
    LineNumber      INTEGER,
    ItemNumber      VARCHAR(40),
    Description     VARCHAR(240),
    Quantity        NUMERIC(15,3),
    UomCode         VARCHAR(3),
    UnitPrice       NUMERIC(15,2),
    LineAmount      NUMERIC(15,2),
    TaxCode         VARCHAR(30),
    PONumber        VARCHAR(20),
    CostCenter      VARCHAR(50),
    AccountCode     VARCHAR(50),
    PRIMARY KEY (InvoiceNumber, LineNumber),
    erp_source      VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['invoice_lines_erpnext'] = """
CREATE TABLE IF NOT EXISTS invoice_lines_erpnext (
    name            VARCHAR(140),
    parent          VARCHAR(140),          -- invoice name
    idx             INTEGER,
    item_code       VARCHAR(140),
    item_name       VARCHAR(140),
    qty             NUMERIC(15,3),
    uom             VARCHAR(140),
    rate            NUMERIC(15,2),
    discount_percentage NUMERIC(5,2) DEFAULT 0,
    amount          NUMERIC(15,2),
    purchase_order  VARCHAR(140),
    cost_center     VARCHAR(140),
    expense_account VARCHAR(140),
    PRIMARY KEY (name, parent),
    erp_source      VARCHAR(20) DEFAULT 'erpnext'
)"""

# ── grn_lines ─────────────────────────────────────────────────────────────────
schemas['grn_lines_odoo'] = """
CREATE TABLE IF NOT EXISTS grn_lines_odoo (
    id              SERIAL PRIMARY KEY,
    picking_id      VARCHAR(64),          -- FK grn_headers_odoo.name
    product_id      VARCHAR(50),
    description_picking VARCHAR(200),
    product_uom_qty NUMERIC(15,4),        -- demand qty
    quantity_done   NUMERIC(15,4),        -- actual received
    product_uom     VARCHAR(10),
    location_id     VARCHAR(50),
    location_dest_id VARCHAR(50),
    lot_id          VARCHAR(50),
    state           VARCHAR(20),
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['grn_lines_sap_s4'] = """
CREATE TABLE IF NOT EXISTS grn_lines_sap_s4 (
    MBLNR   VARCHAR(10),               -- mat. document
    ZEILE   VARCHAR(4),                -- item
    MJAHR   VARCHAR(4),
    MATNR   VARCHAR(18),
    TXZ01   VARCHAR(40),
    MENGE   NUMERIC(15,3),
    MEINS   VARCHAR(3),
    WRBTR   NUMERIC(15,2),
    EBELN   VARCHAR(10),               -- PO
    EBELP   VARCHAR(5),                -- PO line
    WERKS   VARCHAR(4),
    LGORT   VARCHAR(4),
    CHARG   VARCHAR(10),               -- batch
    BWART   VARCHAR(3) DEFAULT '101',  -- movement type
    PRIMARY KEY (MBLNR, ZEILE),
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['grn_lines_sap_b1'] = """
CREATE TABLE IF NOT EXISTS grn_lines_sap_b1 (
    DocNum      INTEGER,
    LineNum     INTEGER,
    ItemCode    VARCHAR(20),
    Dscription  VARCHAR(100),
    Quantity    NUMERIC(15,3),
    UomCode     VARCHAR(8),
    UnitPrice   NUMERIC(15,2),
    LineTotal   NUMERIC(15,2),
    WhsCode     VARCHAR(8),
    BatchNum    VARCHAR(20),
    BaseRef     VARCHAR(20),           -- PO reference
    OpenQty     NUMERIC(15,3),
    PRIMARY KEY (DocNum, LineNum),
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['grn_lines_dynamics'] = """
CREATE TABLE IF NOT EXISTS grn_lines_dynamics (
    ProductReceiptNumber VARCHAR(20),
    LineNumber          INTEGER,
    ItemNumber          VARCHAR(20),
    ProductName         VARCHAR(200),
    ReceivedQuantity    NUMERIC(15,3),
    Unit                VARCHAR(10),
    CostPrice           NUMERIC(15,2),
    LineAmount          NUMERIC(15,2),
    Site                VARCHAR(10),
    Warehouse           VARCHAR(10),
    BatchId             VARCHAR(50),
    PurchaseOrderNumber VARCHAR(20),
    PRIMARY KEY (ProductReceiptNumber, LineNumber),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['grn_lines_oracle'] = """
CREATE TABLE IF NOT EXISTS grn_lines_oracle (
    ReceiptNumber   VARCHAR(20),
    LineNumber      INTEGER,
    ItemNumber      VARCHAR(40),
    Description     VARCHAR(240),
    QuantityReceived NUMERIC(15,3),
    UomCode         VARCHAR(3),
    UnitPrice       NUMERIC(15,2),
    LineAmount      NUMERIC(15,2),
    SubInventory    VARCHAR(10),
    LotNumber       VARCHAR(30),
    PONumber        VARCHAR(20),
    POLineNumber    INTEGER,
    PRIMARY KEY (ReceiptNumber, LineNumber),
    erp_source      VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['grn_lines_erpnext'] = """
CREATE TABLE IF NOT EXISTS grn_lines_erpnext (
    name            VARCHAR(140),
    parent          VARCHAR(140),          -- receipt name
    idx             INTEGER,
    item_code       VARCHAR(140),
    item_name       VARCHAR(140),
    qty             NUMERIC(15,3),
    received_qty    NUMERIC(15,3),
    uom             VARCHAR(140),
    rate            NUMERIC(15,2),
    amount          NUMERIC(15,2),
    warehouse       VARCHAR(140),
    batch_no        VARCHAR(140),
    purchase_order  VARCHAR(140),
    PRIMARY KEY (name, parent),
    erp_source      VARCHAR(20) DEFAULT 'erpnext'
)"""

# ── budget_vs_actuals ─────────────────────────────────────────────────────────
schemas['budget_vs_actuals_odoo'] = """
CREATE TABLE IF NOT EXISTS budget_vs_actuals_odoo (
    id              SERIAL PRIMARY KEY,
    crossovered_budget_id INTEGER,
    analytic_account_id VARCHAR(50),   -- cost center
    general_budget_id VARCHAR(20),     -- GL account
    date_from       DATE,
    date_to         DATE,
    planned_amount  NUMERIC(15,2),
    practical_amount NUMERIC(15,2),
    theoritical_amount NUMERIC(15,2),
    percentage      NUMERIC(8,2),
    currency_id     VARCHAR(5),
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['budget_vs_actuals_sap_s4'] = """
CREATE TABLE IF NOT EXISTS budget_vs_actuals_sap_s4 (
    KOKRS   VARCHAR(4),                -- controlling area
    KOSTL   VARCHAR(10),               -- cost center
    GJAHR   VARCHAR(4),                -- fiscal year
    PERIO   VARCHAR(3),                -- period
    KSTAR   VARCHAR(10),               -- cost element
    WRTTP_04 NUMERIC(15,2),            -- plan (version 0)
    WRTTP_11 NUMERIC(15,2),            -- actual
    WAERS   VARCHAR(5),
    PRIMARY KEY (KOKRS, KOSTL, GJAHR, PERIO, KSTAR),
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['budget_vs_actuals_sap_b1'] = """
CREATE TABLE IF NOT EXISTS budget_vs_actuals_sap_b1 (
    LineId          SERIAL PRIMARY KEY,
    OcrCode         VARCHAR(50),       -- cost center
    AcctCode        VARCHAR(20),       -- GL account
    FromDate        DATE,
    ToDate          DATE,
    BudgetAmount    NUMERIC(15,2),
    ActualAmount    NUMERIC(15,2),
    Variance        NUMERIC(15,2),
    Currency        VARCHAR(3),
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['budget_vs_actuals_dynamics'] = """
CREATE TABLE IF NOT EXISTS budget_vs_actuals_dynamics (
    LineId              SERIAL PRIMARY KEY,
    BudgetPlanNumber    VARCHAR(20),
    CostCenter          VARCHAR(50),
    MainAccount         VARCHAR(20),
    FiscalYear          VARCHAR(4),
    Period              VARCHAR(3),
    BudgetAmount        NUMERIC(15,2),
    ActualAmount        NUMERIC(15,2),
    EncumbranceAmount   NUMERIC(15,2),
    RemainingBudget     NUMERIC(15,2),
    CurrencyCode        VARCHAR(3),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['budget_vs_actuals_oracle'] = """
CREATE TABLE IF NOT EXISTS budget_vs_actuals_oracle (
    LineId          SERIAL PRIMARY KEY,
    LedgerName      VARCHAR(30),
    CostCenter      VARCHAR(50),
    AccountCode     VARCHAR(50),
    PeriodName      VARCHAR(15),
    CurrencyCode    VARCHAR(15),
    BudgetAmount    NUMERIC(15,2),
    ActualAmount    NUMERIC(15,2),
    EncumbranceAmount NUMERIC(15,2),
    AvailableBudget NUMERIC(15,2),
    erp_source      VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['budget_vs_actuals_erpnext'] = """
CREATE TABLE IF NOT EXISTS budget_vs_actuals_erpnext (
    name            VARCHAR(140),
    cost_center     VARCHAR(140),
    account         VARCHAR(140),
    fiscal_year     VARCHAR(10),
    monthly_budget  NUMERIC(15,2),
    actual_amount   NUMERIC(15,2),
    variance        NUMERIC(15,2),
    company         VARCHAR(140),
    PRIMARY KEY (name, cost_center, account),
    erp_source      VARCHAR(20) DEFAULT 'erpnext'
)"""

# ── vendor_performance ────────────────────────────────────────────────────────
schemas['vendor_performance_odoo'] = """
CREATE TABLE IF NOT EXISTS vendor_performance_odoo (
    id              SERIAL PRIMARY KEY,
    partner_id      INTEGER,              -- FK vendors_odoo.id
    review_period   VARCHAR(20),
    total_pos       INTEGER,
    total_spend     NUMERIC(15,2),
    currency_id     VARCHAR(5),
    otd_rate        NUMERIC(5,2),         -- on-time delivery %
    quality_rate    NUMERIC(5,2),
    invoice_accuracy NUMERIC(5,2),
    price_compliance NUMERIC(5,2),
    overall_score   NUMERIC(5,2),
    rating          VARCHAR(2),           -- A/B/C
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['vendor_performance_sap_s4'] = """
CREATE TABLE IF NOT EXISTS vendor_performance_sap_s4 (
    LIFNR       VARCHAR(10),
    GJAHR       VARCHAR(4),
    EKORG       VARCHAR(4),
    TOTAL_POS   INTEGER,
    TOTAL_SPEND NUMERIC(15,2),
    WAERS       VARCHAR(5),
    OTIF_PCTG   NUMERIC(5,2),
    QUAL_PCTG   NUMERIC(5,2),
    PRICE_VAR   NUMERIC(5,2),
    OVERALL_SCORE NUMERIC(5,2),
    RATING      VARCHAR(2),
    PRIMARY KEY (LIFNR, GJAHR, EKORG),
    erp_source  VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['vendor_performance_sap_b1'] = """
CREATE TABLE IF NOT EXISTS vendor_performance_sap_b1 (
    LineId      SERIAL PRIMARY KEY,
    CardCode    VARCHAR(15),
    CardName    VARCHAR(100),
    Period      VARCHAR(20),
    TotalPOs    INTEGER,
    TotalSpend  NUMERIC(15,2),
    Currency    VARCHAR(3),
    OTDRate     NUMERIC(5,2),
    QualityRate NUMERIC(5,2),
    InvoiceAccuracy NUMERIC(5,2),
    OverallScore NUMERIC(5,2),
    Rating      VARCHAR(2),
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['vendor_performance_dynamics'] = """
CREATE TABLE IF NOT EXISTS vendor_performance_dynamics (
    LineId              SERIAL PRIMARY KEY,
    VendorAccountNumber VARCHAR(20),
    VendorName          VARCHAR(200),
    Period              VARCHAR(20),
    TotalPOs            INTEGER,
    TotalSpend          NUMERIC(15,2),
    CurrencyCode        VARCHAR(3),
    OTDScore            NUMERIC(5,2),
    QualityScore        NUMERIC(5,2),
    InvoiceAccuracy     NUMERIC(5,2),
    OverallScore        NUMERIC(5,2),
    Rating              VARCHAR(2),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['vendor_performance_oracle'] = """
CREATE TABLE IF NOT EXISTS vendor_performance_oracle (
    LineId          SERIAL PRIMARY KEY,
    SupplierNumber  VARCHAR(20),
    SupplierName    VARCHAR(360),
    Period          VARCHAR(20),
    TotalPOs        INTEGER,
    TotalSpend      NUMERIC(15,2),
    CurrencyCode    VARCHAR(15),
    OTIFScore       NUMERIC(5,2),
    QualityScore    NUMERIC(5,2),
    InvoiceAccuracy NUMERIC(5,2),
    OverallScore    NUMERIC(5,2),
    Rating          VARCHAR(2),
    erp_source      VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['vendor_performance_erpnext'] = """
CREATE TABLE IF NOT EXISTS vendor_performance_erpnext (
    name            VARCHAR(140),
    supplier        VARCHAR(140),
    supplier_name   VARCHAR(140),
    period          VARCHAR(20),
    total_pos       INTEGER,
    total_spend     NUMERIC(15,2),
    currency        VARCHAR(10),
    otd_score       NUMERIC(5,2),
    quality_score   NUMERIC(5,2),
    invoice_accuracy NUMERIC(5,2),
    overall_score   NUMERIC(5,2),
    rating          VARCHAR(2),
    company         VARCHAR(140),
    PRIMARY KEY (name, supplier),
    erp_source      VARCHAR(20) DEFAULT 'erpnext'
)"""

# Create all tables
print("Creating AP/Lines/Budget tables...")
for tbl, ddl in schemas.items():
    cur.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
    cur.execute(ddl)
    print(f"  + {tbl}")
conn.commit()

# ── SEED DATA ─────────────────────────────────────────────────────────────────
print("\nSeeding approved_supplier_list...")

asl_rows = [(i%10, i//10) for i in range(21)]  # (item_idx, vendor_idx)

execute_values(cur, """INSERT INTO approved_supplier_list_odoo
    (product_id,partner_id,min_qty,price,currency_id,delay,sequence,date_start,date_end)
    VALUES %s""", [
    (ITEMS_ODOO[ii], VND_ODOO[vi%10], float((ii+1)*50), float((ii+1)*10+vi),
     'USD', 14+vi*2, vi%3+1, '2025-01-01', '2026-12-31')
    for ii, vi in asl_rows
])
print("  approved_supplier_list_odoo (21)")

execute_values(cur, """INSERT INTO approved_supplier_list_sap_s4
    (INFNR,MATNR,LIFNR,EKORG,WERKS,PREIS,WAERS,MINBM,WEBAZ,DATAB,DATBI)
    VALUES %s""", [
    (f'53{str(ii*10+vi).zfill(8)}', ITEMS_SAP[ii], VND_SAP[vi%10],
     'ORG1', '1000', float((ii+1)*10+vi), 'USD',
     float((ii+1)*50), 14+vi*2, '2025-01-01', '2026-12-31')
    for ii, vi in asl_rows
])
print("  approved_supplier_list_sap_s4 (21)")

execute_values(cur, """INSERT INTO approved_supplier_list_sap_b1
    (ItemCode,CardCode,CardName,Priority,MinOrderQty,Price,Currency,LeadTime,ValidFrom,ValidTo)
    VALUES %s""", [
    (ITEMS_B1[ii], VND_B1[vi%10], VEND_NAMES[vi%10],
     vi%3+1, float((ii+1)*50), float((ii+1)*10+vi),
     'USD', 14+vi*2, '2025-01-01', '2026-12-31')
    for ii, vi in asl_rows
])
print("  approved_supplier_list_sap_b1 (21)")

execute_values(cur, """INSERT INTO approved_supplier_list_dynamics
    (ItemNumber,VendorAccountNumber,VendorName,PreferredRank,
     MinOrderQty,UnitPrice,CurrencyCode,DeliveryLeadDays,ValidFrom,ValidTo)
    VALUES %s""", [
    (ITEMS_DYN[ii], VND_DYN[vi%10], VEND_NAMES[vi%10],
     vi%3+1, float((ii+1)*50), float((ii+1)*10+vi),
     'USD', 14+vi*2, '2025-01-01', '2026-12-31')
    for ii, vi in asl_rows
])
print("  approved_supplier_list_dynamics (21)")

execute_values(cur, """INSERT INTO approved_supplier_list_oracle
    (ItemNumber,SupplierNumber,SupplierName,PreferredRank,MinOrderQuantity,
     UnitPrice,CurrencyCode,FixedLeadTime,StartDate,EndDate)
    VALUES %s""", [
    (ITEMS_ORA[ii], VND_ORA[vi%10], VEND_NAMES[vi%10],
     vi%3+1, float((ii+1)*50), float((ii+1)*10+vi),
     'USD', 14+vi*2, '2025-01-01', '2026-12-31')
    for ii, vi in asl_rows
])
print("  approved_supplier_list_oracle (21)")

execute_values(cur, """INSERT INTO approved_supplier_list_erpnext
    (name,parent,supplier,supplier_name,lead_time_days,min_qty,price,currency,valid_from,valid_to)
    VALUES %s""", [
    (f'ASL-{ITEMS_ERP[ii]}-{vi:02d}', ITEMS_ERP[ii],
     VND_ERP[vi%10], VEND_NAMES[vi%10],
     14+vi*2, float((ii+1)*50), float((ii+1)*10+vi),
     'USD', '2025-01-01', '2026-12-31')
    for ii, vi in asl_rows
])
print("  approved_supplier_list_erpnext (21)")
conn.commit()

print("\nSeeding invoice_lines...")
# 2 lines per invoice × 10 invoices = 20 lines
inv_lines = [
    (0,1, ITEMS_ODOO[0], 500.0, 2.50),  (0,2, ITEMS_ODOO[2], 200.0,12.50),
    (1,1, ITEMS_ODOO[1],1000.0, 2.85),  (1,2, ITEMS_ODOO[0], 800.0, 2.50),
    (2,1, ITEMS_ODOO[3], 100.0, 8.75),  (2,2, ITEMS_ODOO[5], 200.0, 3.20),
    (3,1, ITEMS_ODOO[7],2000.0, 1.10),  (3,2, ITEMS_ODOO[8],  50.0,22.50),
    (4,1, ITEMS_ODOO[0], 600.0, 2.50),  (4,2, ITEMS_ODOO[1], 500.0, 2.85),
    (5,1, ITEMS_ODOO[6],1000.0, 3.20),  (5,2, ITEMS_ODOO[5], 500.0, 3.20),
    (6,1, ITEMS_ODOO[4],  20.0,245.0),  (6,2, ITEMS_ODOO[9],  50.0,18.75),
    (7,1, ITEMS_ODOO[0], 400.0, 2.50),  (7,2, ITEMS_ODOO[2], 100.0,12.50),
    (8,1, ITEMS_ODOO[7],1000.0, 1.10),  (8,2, ITEMS_ODOO[8], 100.0,22.50),
    (9,1, ITEMS_ODOO[3], 200.0, 8.75),  (9,2, ITEMS_ODOO[5], 300.0, 3.20),
]

execute_values(cur, """INSERT INTO invoice_lines_odoo
    (move_id,sequence,product_id,name,quantity,product_uom_id,
     price_unit,price_subtotal,price_tax,price_total,account_id)
    VALUES %s""", [
    (INV_ODOO[ii], seq, item, ITEM_DESC[ITEMS_ODOO.index(item)],
     qty, 'PCS', price,
     round(qty*price,2), round(qty*price*0.15,2), round(qty*price*1.15,2), '400000')
    for ii, seq, item, qty, price in inv_lines
])
print("  invoice_lines_odoo (20)")

execute_values(cur, """INSERT INTO invoice_lines_sap_s4
    (BELNR,BUZEI,GJAHR,MATNR,TXZ01,MENGE,MEINS,WRBTR,MWSKZ,EBELN,SAKTO)
    VALUES %s""", [
    (INV_SAP[ii], str(seq).zfill(3), '2025',
     ITEMS_SAP[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:40],
     qty, 'PCS', round(qty*price,2), 'V0', f'45000000{ii+1:02d}', '400000')
    for ii, seq, item, qty, price in inv_lines
])
print("  invoice_lines_sap_s4 (20)")

execute_values(cur, """INSERT INTO invoice_lines_sap_b1
    (DocNum,LineNum,ItemCode,Dscription,Quantity,UomCode,Price,LineTotal,TaxCode,WhsCode)
    VALUES %s""", [
    (INV_B1[ii], seq,
     ITEMS_B1[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:100],
     qty, 'PCS', price, round(qty*price,2), 'VAT', 'WH01')
    for ii, seq, item, qty, price in inv_lines
])
print("  invoice_lines_sap_b1 (20)")

execute_values(cur, """INSERT INTO invoice_lines_dynamics
    (VendorInvoiceNumber,LineNumber,ItemNumber,ProductName,
     Quantity,Unit,UnitPrice,LineAmount,TaxGroup,PurchaseOrderNumber)
    VALUES %s""", [
    (INV_DYN[ii], seq,
     ITEMS_DYN[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:100],
     qty, 'PCS', price, round(qty*price,2), 'FULL',
     f'PO-{str(ii+1).zfill(6)}')
    for ii, seq, item, qty, price in inv_lines
])
print("  invoice_lines_dynamics (20)")

execute_values(cur, """INSERT INTO invoice_lines_oracle
    (InvoiceNumber,LineNumber,ItemNumber,Description,
     Quantity,UomCode,UnitPrice,LineAmount,PONumber)
    VALUES %s""", [
    (INV_ORA[ii], seq,
     ITEMS_ORA[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:240],
     qty, 'EA', price, round(qty*price,2), f'US-{str(ii+1).zfill(6)}')
    for ii, seq, item, qty, price in inv_lines
])
print("  invoice_lines_oracle (20)")

execute_values(cur, """INSERT INTO invoice_lines_erpnext
    (name,parent,idx,item_code,item_name,qty,uom,rate,amount,purchase_order)
    VALUES %s""", [
    (f'{INV_ERP[ii]}-{seq}', INV_ERP[ii], seq,
     ITEMS_ERP[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:140],
     qty, 'Nos', price, round(qty*price,2),
     f'PUR-ORD-2025-{str(ii+1).zfill(5)}')
    for ii, seq, item, qty, price in inv_lines
])
print("  invoice_lines_erpnext (20)")
conn.commit()

print("\nSeeding grn_lines...")
grn_lines = [
    (0,1,ITEMS_ODOO[0],500.0, 2.50),(0,2,ITEMS_ODOO[2],200.0,12.50),
    (1,1,ITEMS_ODOO[1],1000.0,2.85),(1,2,ITEMS_ODOO[0],800.0, 2.50),
    (2,1,ITEMS_ODOO[3],100.0, 8.75),(2,2,ITEMS_ODOO[5],200.0, 3.20),
    (3,1,ITEMS_ODOO[7],2000.0,1.10),(3,2,ITEMS_ODOO[8], 50.0,22.50),
    (4,1,ITEMS_ODOO[0],600.0, 2.50),(4,2,ITEMS_ODOO[1],500.0, 2.85),
    (5,1,ITEMS_ODOO[6],1000.0,3.20),(5,2,ITEMS_ODOO[5],500.0, 3.20),
    (6,1,ITEMS_ODOO[4], 20.0,245.0),(6,2,ITEMS_ODOO[9], 50.0,18.75),
    (7,1,ITEMS_ODOO[0],400.0, 2.50),(7,2,ITEMS_ODOO[2],100.0,12.50),
]

execute_values(cur, """INSERT INTO grn_lines_odoo
    (picking_id,product_id,description_picking,product_uom_qty,
     quantity_done,product_uom,state)
    VALUES %s""", [
    (GRN_ODOO[gi], item, ITEM_DESC[ITEMS_ODOO.index(item)],
     qty, qty, 'PCS', 'done')
    for gi, seq, item, qty, price in grn_lines
])
print("  grn_lines_odoo (16)")

execute_values(cur, """INSERT INTO grn_lines_sap_s4
    (MBLNR,ZEILE,MJAHR,MATNR,TXZ01,MENGE,MEINS,WRBTR,EBELN,WERKS,LGORT)
    VALUES %s""", [
    (GRN_SAP[gi], str(seq).zfill(4), '2025',
     ITEMS_SAP[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:40],
     qty, 'PCS', round(qty*price,2),
     f'45000000{gi+1:02d}', '1000', '0001')
    for gi, seq, item, qty, price in grn_lines
])
print("  grn_lines_sap_s4 (16)")

execute_values(cur, """INSERT INTO grn_lines_sap_b1
    (DocNum,LineNum,ItemCode,Dscription,Quantity,UomCode,
     UnitPrice,LineTotal,WhsCode,OpenQty)
    VALUES %s""", [
    (GRN_B1[gi], seq,
     ITEMS_B1[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:100],
     qty, 'PCS', price, round(qty*price,2), 'WH01', 0)
    for gi, seq, item, qty, price in grn_lines
])
print("  grn_lines_sap_b1 (16)")

execute_values(cur, """INSERT INTO grn_lines_dynamics
    (ProductReceiptNumber,LineNumber,ItemNumber,ProductName,
     ReceivedQuantity,Unit,CostPrice,LineAmount,Site,Warehouse,PurchaseOrderNumber)
    VALUES %s""", [
    (GRN_DYN[gi], seq,
     ITEMS_DYN[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:100],
     qty, 'PCS', price, round(qty*price,2),
     'SITE1', 'WH01', f'PO-{str(gi+1).zfill(6)}')
    for gi, seq, item, qty, price in grn_lines
])
print("  grn_lines_dynamics (16)")

execute_values(cur, """INSERT INTO grn_lines_oracle
    (ReceiptNumber,LineNumber,ItemNumber,Description,
     QuantityReceived,UomCode,UnitPrice,LineAmount,SubInventory,PONumber)
    VALUES %s""", [
    (GRN_ORA[gi], seq,
     ITEMS_ORA[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:240],
     qty, 'EA', price, round(qty*price,2), 'STORES',
     f'US-{str(gi+1).zfill(6)}')
    for gi, seq, item, qty, price in grn_lines
])
print("  grn_lines_oracle (16)")

execute_values(cur, """INSERT INTO grn_lines_erpnext
    (name,parent,idx,item_code,item_name,qty,received_qty,
     uom,rate,amount,warehouse,purchase_order)
    VALUES %s""", [
    (f'{GRN_ERP[gi]}-{seq}', GRN_ERP[gi], seq,
     ITEMS_ERP[ITEMS_ODOO.index(item)], ITEM_DESC[ITEMS_ODOO.index(item)][:140],
     qty, qty, 'Nos', price, round(qty*price,2),
     'Stores - Company', f'PUR-ORD-2025-{str(gi+1).zfill(5)}')
    for gi, seq, item, qty, price in grn_lines
])
print("  grn_lines_erpnext (16)")
conn.commit()

print("\nSeeding budget_vs_actuals...")
BVA = [
    ('CC-001','400100','Metals',  200000,185000),('CC-001','400200','Electronics',150000,162000),
    ('CC-002','400100','Hydraulics',80000, 75000),('CC-002','400300','Packaging',  60000, 58000),
    ('CC-003','400400','Chemicals',120000,130000),('CC-003','400200','Safety',      40000, 38000),
    ('CC-004','400100','Metals',  180000,175000),('CC-004','400500','Tooling',      30000, 28500),
    ('CC-005','400200','Electronics',90000,95000),('CC-005','400300','Packaging',   45000, 44000),
    ('CC-001','400600','Services',  50000, 52000),('CC-002','400600','Services',    35000, 33000),
]

execute_values(cur, """INSERT INTO budget_vs_actuals_odoo
    (analytic_account_id,general_budget_id,date_from,date_to,
     planned_amount,practical_amount,currency_id)
    VALUES %s""", [
    (cc, gl, '2025-01-01','2025-12-31', bud, act, 'USD')
    for cc, gl, cat, bud, act in BVA
])
print("  budget_vs_actuals_odoo (12)")

execute_values(cur, """INSERT INTO budget_vs_actuals_sap_s4
    (KOKRS,KOSTL,GJAHR,PERIO,KSTAR,WRTTP_04,WRTTP_11,WAERS)
    VALUES %s""", [
    ('1000', cc.replace('CC-','KOST'), '2025','001', gl,
     bud/12, act/12, 'USD')
    for cc, gl, cat, bud, act in BVA
])
print("  budget_vs_actuals_sap_s4 (12)")

execute_values(cur, """INSERT INTO budget_vs_actuals_sap_b1
    (OcrCode,AcctCode,FromDate,ToDate,BudgetAmount,ActualAmount,Variance,Currency)
    VALUES %s""", [
    (cc, gl, '2025-01-01','2025-12-31', bud, act, bud-act, 'USD')
    for cc, gl, cat, bud, act in BVA
])
print("  budget_vs_actuals_sap_b1 (12)")

execute_values(cur, """INSERT INTO budget_vs_actuals_dynamics
    (BudgetPlanNumber,CostCenter,MainAccount,FiscalYear,Period,
     BudgetAmount,ActualAmount,EncumbranceAmount,RemainingBudget,CurrencyCode)
    VALUES %s""", [
    (f'BP-2025-{i+1:03d}', cc, gl, '2025','P01',
     bud, act, 0, bud-act, 'USD')
    for i,(cc, gl, cat, bud, act) in enumerate(BVA)
])
print("  budget_vs_actuals_dynamics (12)")

execute_values(cur, """INSERT INTO budget_vs_actuals_oracle
    (LedgerName,CostCenter,AccountCode,PeriodName,CurrencyCode,
     BudgetAmount,ActualAmount,EncumbranceAmount,AvailableBudget)
    VALUES %s""", [
    ('Primary Ledger', cc, gl, 'JAN-25','USD',
     bud, act, 0, bud-act)
    for cc, gl, cat, bud, act in BVA
])
print("  budget_vs_actuals_oracle (12)")

execute_values(cur, """INSERT INTO budget_vs_actuals_erpnext
    (name,cost_center,account,fiscal_year,monthly_budget,actual_amount,variance,company)
    VALUES %s""", [
    (f'BVA-2025-{i+1:03d}', f'{cc} - Company', f'{gl} - Company',
     '2025', bud/12, act/12, (bud-act)/12, 'Procure-AI Demo Company')
    for i,(cc, gl, cat, bud, act) in enumerate(BVA)
])
print("  budget_vs_actuals_erpnext (12)")
conn.commit()

print("\nSeeding vendor_performance...")
VP = [
    (0, '2025-H1', 45, 285000, 94.5, 98.2, 99.1, 95.0, 96.7, 'A'),
    (1, '2025-H1', 38, 240000, 91.0, 95.5, 97.8, 93.0, 94.3, 'A'),
    (2, '2025-H1', 22, 130000, 88.5, 97.0, 98.5, 91.0, 93.8, 'A'),
    (3, '2025-H1', 18,  95000, 85.0, 93.0, 96.0, 88.0, 90.5, 'B'),
    (4, '2025-H1', 30, 178000, 92.0, 96.5, 98.0, 94.0, 95.1, 'A'),
    (5, '2025-H1', 25, 115000, 87.5, 94.5, 97.5, 90.0, 92.4, 'B'),
    (6, '2025-H1', 20, 109000, 89.0, 95.0, 97.0, 92.0, 93.3, 'A'),
    (7, '2025-H1', 15,  75000, 82.0, 91.0, 95.5, 86.0, 88.6, 'B'),
    (8, '2025-H1', 28, 138000, 90.5, 96.0, 98.2, 93.5, 94.6, 'A'),
    (9, '2025-H1', 12,  62000, 80.0, 89.0, 94.0, 84.0, 86.8, 'C'),
    (0, '2025-H2', 48, 310000, 95.5, 98.5, 99.3, 96.0, 97.3, 'A'),
    (1, '2025-H2', 40, 260000, 92.0, 96.0, 98.0, 94.0, 95.0, 'A'),
]

execute_values(cur, """INSERT INTO vendor_performance_odoo
    (partner_id,review_period,total_pos,total_spend,currency_id,
     otd_rate,quality_rate,invoice_accuracy,price_compliance,overall_score,rating)
    VALUES %s""", [
    (VND_ODOO[vi], period, pos, spend, 'USD',
     otd, qual, inv_acc, price_c, overall, rating)
    for vi,period,pos,spend,otd,qual,inv_acc,price_c,overall,rating in VP
])
print("  vendor_performance_odoo (12)")

execute_values(cur, """INSERT INTO vendor_performance_sap_s4
    (LIFNR,GJAHR,EKORG,TOTAL_POS,TOTAL_SPEND,WAERS,
     OTIF_PCTG,QUAL_PCTG,PRICE_VAR,OVERALL_SCORE,RATING)
    VALUES %s""", [
    (VND_SAP[vi], period.replace('2025-','25'), 'ORG1', pos, spend, 'USD',
     otd, qual, price_c, overall, rating)
    for vi,period,pos,spend,otd,qual,inv_acc,price_c,overall,rating in VP
])
print("  vendor_performance_sap_s4 (12)")

execute_values(cur, """INSERT INTO vendor_performance_sap_b1
    (CardCode,CardName,Period,TotalPOs,TotalSpend,Currency,
     OTDRate,QualityRate,InvoiceAccuracy,OverallScore,Rating)
    VALUES %s""", [
    (VND_B1[vi], VEND_NAMES[vi], period, pos, spend, 'USD',
     otd, qual, inv_acc, overall, rating)
    for vi,period,pos,spend,otd,qual,inv_acc,price_c,overall,rating in VP
])
print("  vendor_performance_sap_b1 (12)")

execute_values(cur, """INSERT INTO vendor_performance_dynamics
    (VendorAccountNumber,VendorName,Period,TotalPOs,TotalSpend,CurrencyCode,
     OTDScore,QualityScore,InvoiceAccuracy,OverallScore,Rating)
    VALUES %s""", [
    (VND_DYN[vi], VEND_NAMES[vi], period, pos, spend, 'USD',
     otd, qual, inv_acc, overall, rating)
    for vi,period,pos,spend,otd,qual,inv_acc,price_c,overall,rating in VP
])
print("  vendor_performance_dynamics (12)")

execute_values(cur, """INSERT INTO vendor_performance_oracle
    (SupplierNumber,SupplierName,Period,TotalPOs,TotalSpend,CurrencyCode,
     OTIFScore,QualityScore,InvoiceAccuracy,OverallScore,Rating)
    VALUES %s""", [
    (VND_ORA[vi], VEND_NAMES[vi], period, pos, spend, 'USD',
     otd, qual, inv_acc, overall, rating)
    for vi,period,pos,spend,otd,qual,inv_acc,price_c,overall,rating in VP
])
print("  vendor_performance_oracle (12)")

execute_values(cur, """INSERT INTO vendor_performance_erpnext
    (name,supplier,supplier_name,period,total_pos,total_spend,currency,
     otd_score,quality_score,invoice_accuracy,overall_score,rating,company)
    VALUES %s""", [
    (f'VP-{VND_ERP[vi]}-{period}', VND_ERP[vi], VEND_NAMES[vi],
     period, pos, spend, 'USD',
     otd, qual, inv_acc, overall, rating,
     'Procure-AI Demo Company')
    for vi,period,pos,spend,otd,qual,inv_acc,price_c,overall,rating in VP
])
print("  vendor_performance_erpnext (12)")
conn.commit()

# Update table_registry
for mod, module_name, module_code, table_type, odoo_model, sap_obj, desc in [
    ('approved_supplier_list','Procurement','PRC','master','product.supplierinfo','EINE','Approved Supplier List'),
    ('invoice_lines','Accounts Payable','AP','transaction','account.move.line','RSEG','Invoice Line Items'),
    ('grn_lines','Warehouse','WMS','transaction','stock.move','MSEG','GRN Line Items'),
    ('budget_vs_actuals','Finance','FIN','report','account.budget.line','BPGE','Budget vs Actuals'),
    ('vendor_performance','Procurement','PRC','report','res.partner','LIKP','Vendor Performance'),
]:
    for erp in ERPS:
        tbl = f'{mod}_{erp}'
        cur.execute("""INSERT INTO table_registry
            (table_name,module,module_code,table_type,description,odoo_model,sap_object,erp_source,erp_table_name)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (table_name) DO NOTHING""",
            (tbl, module_name, module_code, table_type, desc, odoo_model, sap_obj, erp, tbl))
conn.commit()

print(f"\n{'='*60}")
print("BATCH 2 COMPLETE — 30 tables created and seeded")
print(f"{'='*60}")
cur.close(); conn.close()
