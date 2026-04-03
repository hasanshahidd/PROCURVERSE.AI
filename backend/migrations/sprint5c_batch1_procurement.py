"""
Sprint 5C Batch 1 — Purchase Requisitions, RFQ Headers, Vendor Quotes, Contracts
6 ERPs × 4 modules = 24 tables
"""
import os, sys
os.chdir("E:/procure AI/Procure-AI"); sys.path.insert(0, ".")
import psycopg2
from psycopg2.extras import execute_values
conn = psycopg2.connect("postgresql://postgres:YourStr0ng!Pass@localhost:5433/odoo_procurement_demo")
cur = conn.cursor()

ERPS = ['odoo','sap_s4','sap_b1','dynamics','oracle','erpnext']

# ── SCHEMAS ───────────────────────────────────────────────────────────────────

schemas = {}

# purchase_requisitions
schemas['purchase_requisitions_odoo'] = """
CREATE TABLE IF NOT EXISTS purchase_requisitions_odoo (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(64),          -- PR/2025/00001
    user_id         VARCHAR(100),         -- requester name
    date_order      DATE,
    date_approve    DATE,
    partner_id      INTEGER,              -- FK vendors_odoo.id (optional)
    product_id      VARCHAR(50),          -- item internal reference
    product_qty     NUMERIC(15,4),
    product_uom     VARCHAR(10),
    price_unit      NUMERIC(15,2),
    currency_id     VARCHAR(5),
    estimated_cost  NUMERIC(15,2),
    state           VARCHAR(20),          -- draft/to approve/purchase/done/cancel
    origin          VARCHAR(50),          -- source document
    notes           TEXT,
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['purchase_requisitions_sap_s4'] = """
CREATE TABLE IF NOT EXISTS purchase_requisitions_sap_s4 (
    BANFN   VARCHAR(10) PRIMARY KEY,   -- requisition number
    BNFPO   VARCHAR(5),                -- item number
    MATNR   VARCHAR(18),               -- material
    TXZ01   VARCHAR(40),               -- short text
    MENGE   NUMERIC(15,3),             -- quantity
    MEINS   VARCHAR(3),                -- unit
    PREIS   NUMERIC(15,2),             -- valuation price
    WAERS   VARCHAR(5),                -- currency
    AFNAM   VARCHAR(12),               -- requisitioner
    KOSTL   VARCHAR(10),               -- cost center
    ERDAT   DATE,                      -- creation date
    BADAT   DATE,                      -- requirement date
    ESTKZ   VARCHAR(1),                -- item category
    FRGZU   VARCHAR(2),                -- release status
    BSART   VARCHAR(4),                -- doc type (NB=standard)
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['purchase_requisitions_sap_b1'] = """
CREATE TABLE IF NOT EXISTS purchase_requisitions_sap_b1 (
    DocNum      INTEGER PRIMARY KEY,
    DocDate     DATE,
    ReqDate     DATE,
    CardCode    VARCHAR(15),           -- vendor (optional)
    ItemCode    VARCHAR(20),
    Dscription  VARCHAR(100),
    Quantity    NUMERIC(15,3),
    UomCode     VARCHAR(8),
    Price       NUMERIC(15,2),
    Currency    VARCHAR(3),
    LineTotal   NUMERIC(15,2),
    OcrCode     VARCHAR(50),           -- cost center
    ReqUser     VARCHAR(50),
    DocStatus   VARCHAR(1),            -- O=open, C=closed
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['purchase_requisitions_dynamics'] = """
CREATE TABLE IF NOT EXISTS purchase_requisitions_dynamics (
    RequisitionNumber   VARCHAR(20) PRIMARY KEY,
    RequisitionName     VARCHAR(200),
    RequesterEmail      VARCHAR(100),
    Department          VARCHAR(100),
    ItemNumber          VARCHAR(20),
    ProductName         VARCHAR(200),
    Quantity            NUMERIC(15,3),
    UnitCost            NUMERIC(15,2),
    CurrencyCode        VARCHAR(3),
    TotalCost           NUMERIC(15,2),
    Status              VARCHAR(20),   -- Draft/InReview/Approved/Rejected
    RequestDate         DATE,
    RequiredDate        DATE,
    CostCenter          VARCHAR(50),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['purchase_requisitions_oracle'] = """
CREATE TABLE IF NOT EXISTS purchase_requisitions_oracle (
    RequisitionNumber   VARCHAR(20) PRIMARY KEY,
    RequisitionType     VARCHAR(30),
    RequesterPersonNumber VARCHAR(30),
    ItemNumber          VARCHAR(40),
    ItemDescription     VARCHAR(240),
    Quantity            NUMERIC(15,3),
    UomCode             VARCHAR(3),
    UnitPrice           NUMERIC(15,2),
    CurrencyCode        VARCHAR(15),
    LineAmount          NUMERIC(15,2),
    Status              VARCHAR(30),
    CreationDate        DATE,
    NeedByDate          DATE,
    CostCenter          VARCHAR(50),
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['purchase_requisitions_erpnext'] = """
CREATE TABLE IF NOT EXISTS purchase_requisitions_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- MAT-MR-2025-00001
    title               VARCHAR(140),
    material_request_type VARCHAR(50),             -- Purchase
    transaction_date    DATE,
    schedule_date       DATE,
    requested_by        VARCHAR(140),
    department          VARCHAR(140),
    item_code           VARCHAR(140),
    item_name           VARCHAR(140),
    qty                 NUMERIC(15,3),
    stock_uom           VARCHAR(140),
    rate                NUMERIC(15,2),
    amount              NUMERIC(15,2),
    cost_center         VARCHAR(140),
    status              VARCHAR(50),               -- Draft/Submitted/Transferred
    company             VARCHAR(140),
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

# rfq_headers
schemas['rfq_headers_odoo'] = """
CREATE TABLE IF NOT EXISTS rfq_headers_odoo (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(64),          -- RFQ/2025/00001
    partner_id      INTEGER,              -- FK vendors_odoo.id
    date_order      DATE,
    validity_date   DATE,
    currency_id     VARCHAR(5),
    amount_untaxed  NUMERIC(15,2),
    amount_tax      NUMERIC(15,2),
    amount_total    NUMERIC(15,2),
    state           VARCHAR(20),          -- draft/sent/purchase/cancel
    origin          VARCHAR(50),          -- PR reference
    notes           TEXT,
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['rfq_headers_sap_s4'] = """
CREATE TABLE IF NOT EXISTS rfq_headers_sap_s4 (
    EBELN   VARCHAR(10) PRIMARY KEY,   -- quotation number (BSART=AN)
    BSART   VARCHAR(4) DEFAULT 'AN',   -- doc type: AN=quotation
    LIFNR   VARCHAR(10),               -- vendor
    BEDAT   DATE,                      -- doc date
    KDATB   DATE,                      -- validity start
    ANGDT   DATE,                      -- validity end
    EKORG   VARCHAR(4),                -- purchasing org
    EKGRP   VARCHAR(3),                -- purchasing group
    NETWR   NUMERIC(15,2),             -- net value
    WAERS   VARCHAR(5),                -- currency
    STATUS  VARCHAR(2),                -- quotation status
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['rfq_headers_sap_b1'] = """
CREATE TABLE IF NOT EXISTS rfq_headers_sap_b1 (
    DocNum      INTEGER PRIMARY KEY,
    DocDate     DATE,
    DocDueDate  DATE,
    CardCode    VARCHAR(15),
    CardName    VARCHAR(100),
    DocTotal    NUMERIC(15,2),
    DocCurrency VARCHAR(3),
    DocStatus   VARCHAR(1),            -- O/C
    Comments    VARCHAR(254),
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['rfq_headers_dynamics'] = """
CREATE TABLE IF NOT EXISTS rfq_headers_dynamics (
    RFQCaseNumber       VARCHAR(20) PRIMARY KEY,
    Title               VARCHAR(200),
    PurchaseType        VARCHAR(20),
    VendorAccountNumber VARCHAR(20),
    VendorName          VARCHAR(200),
    ExpiryDate          DATE,
    RequestDate         DATE,
    TotalAmount         NUMERIC(15,2),
    CurrencyCode        VARCHAR(3),
    Status              VARCHAR(20),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['rfq_headers_oracle'] = """
CREATE TABLE IF NOT EXISTS rfq_headers_oracle (
    NegotiationNumber   VARCHAR(20) PRIMARY KEY,
    NegotiationType     VARCHAR(30),
    SupplierNumber      VARCHAR(20),
    SupplierName        VARCHAR(360),
    OpenDate            DATE,
    CloseDate           DATE,
    TotalAmount         NUMERIC(15,2),
    CurrencyCode        VARCHAR(15),
    Status              VARCHAR(30),
    BuyerName           VARCHAR(240),
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['rfq_headers_erpnext'] = """
CREATE TABLE IF NOT EXISTS rfq_headers_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- PUR-RFQ-2025-00001
    transaction_date    DATE,
    valid_till          DATE,
    supplier            VARCHAR(140),
    supplier_name       VARCHAR(140),
    grand_total         NUMERIC(15,2),
    currency            VARCHAR(10),
    status              VARCHAR(50),
    message_for_supplier TEXT,
    company             VARCHAR(140),
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

# vendor_quotes
schemas['vendor_quotes_odoo'] = """
CREATE TABLE IF NOT EXISTS vendor_quotes_odoo (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(64),          -- PO/2025/00001 (state=sent)
    partner_id      INTEGER,              -- FK vendors_odoo.id
    rfq_id          VARCHAR(64),          -- reference to rfq_headers_odoo.name
    date_order      DATE,
    validity_date   DATE,
    currency_id     VARCHAR(5),
    amount_untaxed  NUMERIC(15,2),
    amount_tax      NUMERIC(15,2),
    amount_total    NUMERIC(15,2),
    state           VARCHAR(20),          -- sent/purchase/cancel
    recommended     BOOLEAN DEFAULT FALSE,
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['vendor_quotes_sap_s4'] = """
CREATE TABLE IF NOT EXISTS vendor_quotes_sap_s4 (
    ANGPF   VARCHAR(10) PRIMARY KEY,   -- quotation number
    EBELN   VARCHAR(10),               -- RFQ reference
    LIFNR   VARCHAR(10),               -- vendor
    ANGDT   DATE,                      -- quote date
    BNDDT   DATE,                      -- validity end
    NETWR   NUMERIC(15,2),             -- net value
    WAERS   VARCHAR(5),                -- currency
    PREIS   NUMERIC(15,2),             -- unit price
    MENGE   NUMERIC(15,3),             -- quantity
    EKORG   VARCHAR(4),                -- purchasing org
    SELKZ   VARCHAR(1),                -- selected flag
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['vendor_quotes_sap_b1'] = """
CREATE TABLE IF NOT EXISTS vendor_quotes_sap_b1 (
    DocNum      INTEGER PRIMARY KEY,
    DocDate     DATE,
    ValidUntil  DATE,
    CardCode    VARCHAR(15),
    CardName    VARCHAR(100),
    BaseRef     VARCHAR(100),          -- RFQ reference
    DocTotal    NUMERIC(15,2),
    DocCurrency VARCHAR(3),
    DocStatus   VARCHAR(1),
    Recommended VARCHAR(1),            -- Y/N
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['vendor_quotes_dynamics'] = """
CREATE TABLE IF NOT EXISTS vendor_quotes_dynamics (
    ReplyJournalNumber  VARCHAR(20) PRIMARY KEY,
    RFQCaseNumber       VARCHAR(20),
    VendorAccountNumber VARCHAR(20),
    VendorName          VARCHAR(200),
    ReplyDate           DATE,
    ExpiryDate          DATE,
    TotalAmount         NUMERIC(15,2),
    CurrencyCode        VARCHAR(3),
    IsLowest            VARCHAR(5),
    Status              VARCHAR(20),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['vendor_quotes_oracle'] = """
CREATE TABLE IF NOT EXISTS vendor_quotes_oracle (
    ResponseNumber      VARCHAR(20) PRIMARY KEY,
    NegotiationNumber   VARCHAR(20),
    SupplierNumber      VARCHAR(20),
    SupplierName        VARCHAR(360),
    ResponseDate        DATE,
    ExpirationDate      DATE,
    QuoteAmount         NUMERIC(15,2),
    CurrencyCode        VARCHAR(15),
    IsRecommended       VARCHAR(1),
    Status              VARCHAR(30),
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['vendor_quotes_erpnext'] = """
CREATE TABLE IF NOT EXISTS vendor_quotes_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- PUR-SQT-2025-00001
    rfq_reference       VARCHAR(140),
    supplier            VARCHAR(140),
    supplier_name       VARCHAR(140),
    transaction_date    DATE,
    valid_till          DATE,
    grand_total         NUMERIC(15,2),
    currency            VARCHAR(10),
    status              VARCHAR(50),
    is_recommended      INTEGER DEFAULT 0,
    company             VARCHAR(140),
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

# contracts
schemas['contracts_odoo'] = """
CREATE TABLE IF NOT EXISTS contracts_odoo (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(64),          -- BPO/2025/00001
    partner_id      INTEGER,              -- FK vendors_odoo.id
    date_order      DATE,
    date_approve    DATE,
    date_planned    DATE,                 -- contract end date
    currency_id     VARCHAR(5),
    amount_untaxed  NUMERIC(15,2),
    amount_total    NUMERIC(15,2),
    is_blanket_order BOOLEAN DEFAULT TRUE,
    state           VARCHAR(20),
    payment_term_id VARCHAR(50),
    notes           TEXT,
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['contracts_sap_s4'] = """
CREATE TABLE IF NOT EXISTS contracts_sap_s4 (
    EBELN   VARCHAR(10) PRIMARY KEY,   -- contract number
    BSART   VARCHAR(4),                -- LP=value contract, MK=qty contract
    LIFNR   VARCHAR(10),               -- vendor
    BEDAT   DATE,                      -- doc date
    KDATB   DATE,                      -- validity start
    KDATE   DATE,                      -- validity end
    EKORG   VARCHAR(4),
    EKGRP   VARCHAR(3),
    NETWR   NUMERIC(15,2),             -- target value
    WAERS   VARCHAR(5),
    KTWRT   NUMERIC(15,2),             -- contract target qty value
    STATUS  VARCHAR(2),
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['contracts_sap_b1'] = """
CREATE TABLE IF NOT EXISTS contracts_sap_b1 (
    AgreementNo     INTEGER PRIMARY KEY,
    CardCode        VARCHAR(15),
    CardName        VARCHAR(100),
    StartDate       DATE,
    EndDate         DATE,
    AgreementType   VARCHAR(20),       -- General/Specific
    TotalAmount     NUMERIC(15,2),
    Currency        VARCHAR(3),
    Status          VARCHAR(20),       -- Active/Expired/Cancelled
    Description     VARCHAR(254),
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['contracts_dynamics'] = """
CREATE TABLE IF NOT EXISTS contracts_dynamics (
    AgreementNumber     VARCHAR(20) PRIMARY KEY,
    AgreementClassification VARCHAR(20),   -- Blanket/Commitment
    VendorAccountNumber VARCHAR(20),
    VendorName          VARCHAR(200),
    EffectiveDate       DATE,
    ExpirationDate      DATE,
    CommitmentAmount    NUMERIC(15,2),
    CurrencyCode        VARCHAR(3),
    Status              VARCHAR(20),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['contracts_oracle'] = """
CREATE TABLE IF NOT EXISTS contracts_oracle (
    ContractNumber      VARCHAR(20) PRIMARY KEY,
    ContractType        VARCHAR(30),
    SupplierNumber      VARCHAR(20),
    SupplierName        VARCHAR(360),
    StartDate           DATE,
    EndDate             DATE,
    ContractAmount      NUMERIC(15,2),
    CurrencyCode        VARCHAR(15),
    Status              VARCHAR(30),
    BuyerName           VARCHAR(240),
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['contracts_erpnext'] = """
CREATE TABLE IF NOT EXISTS contracts_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- PUR-CON-2025-00001
    supplier            VARCHAR(140),
    supplier_name       VARCHAR(140),
    start_date          DATE,
    end_date            DATE,
    contract_value      NUMERIC(15,2),
    currency            VARCHAR(10),
    status              VARCHAR(50),
    contract_type       VARCHAR(50),
    company             VARCHAR(140),
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

# Create all tables
print("Creating procurement tables...")
for tbl, ddl in schemas.items():
    cur.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
    cur.execute(ddl)
    print(f"  + {tbl}")
conn.commit()

# ── SEED DATA ─────────────────────────────────────────────────────────────────

ITEMS = ['ITEM-001','ITEM-002','ITEM-003','ITEM-004','ITEM-005',
         'ITEM-006','ITEM-007','ITEM-008','ITEM-009','ITEM-010']
ITEM_DESC = ['Steel Sheet Metal 3mm HR','Aluminum Billets 6061-T6',
             'Industrial Bearing SKF 6205','Hydraulic Fitting 1/2 NPT',
             'Electronic Control PCB v2.1','Rubber Gasket 50mm OD',
             'Industrial Solvent n-Hexane','Corrugated Packaging Box',
             'Safety Helmet EN397 Yellow','Carbide Cutting Insert CNMG']
REQUESTERS = ['Ahmed Khan','Sara Malik','John Carter','Priya Sharma','Omar Farooq',
              'Lisa Chen','Carlos Ruiz','Anna Weber','Raj Patel','Mei Lin']
DEPTS = ['Engineering','Procurement','Operations','Finance','Maintenance',
         'Quality','Logistics','HR','IT','Production']

VND_ODOO     = list(range(13, 23))
VND_SAP_S4   = [f'000010{i:04d}' for i in range(1, 11)]
VND_SAP_B1   = ['V-GTS001','V-ESA002','V-AIC003','V-EOS004','V-PSR005',
                'V-SCL006','V-TMS007','V-FLL008','V-NCA009','V-DOP010']
VND_DYN      = [f'V-{i:05d}' for i in range(1, 11)]
VND_ORA      = [f'SUP-{i:05d}' for i in range(1, 11)]
VND_ERP      = [f'SUP-{i:05d}' for i in range(1, 11)]

print("\nSeeding purchase_requisitions...")

# Odoo
cur.execute("DELETE FROM purchase_requisitions_odoo")
execute_values(cur, """
    INSERT INTO purchase_requisitions_odoo
    (name,user_id,date_order,date_approve,product_id,product_qty,
     product_uom,price_unit,currency_id,estimated_cost,state,origin)
    VALUES %s
""", [
    (f'PR/2025/{str(i+1).zfill(5)}', REQUESTERS[i%10], f'2025-0{(i%6)+1}-{(i%20)+1:02d}',
     f'2025-0{(i%6)+2}-01' if i < 8 else None,
     ITEMS[i%10], float((i+1)*50), 'PCS', float((i+1)*10),
     'USD', float((i+1)*500),
     'purchase' if i < 8 else 'draft',
     f'DEPT-{DEPTS[i%10]}')
    for i in range(10)
])
print("  ✓ purchase_requisitions_odoo (10)")

# SAP S/4
cur.execute("DELETE FROM purchase_requisitions_sap_s4")
execute_values(cur, """
    INSERT INTO purchase_requisitions_sap_s4
    (BANFN,BNFPO,MATNR,TXZ01,MENGE,MEINS,PREIS,WAERS,
     AFNAM,KOSTL,ERDAT,BADAT,ESTKZ,FRGZU,BSART)
    VALUES %s
""", [
    (f'10{str(i+1).zfill(8)}','00010',f'MAT-1000{i+1}', ITEM_DESC[i%10][:40],
     float((i+1)*50), 'PCS', float((i+1)*10), 'USD',
     REQUESTERS[i%10][:12], f'KOST00{i%5+1}',
     f'2025-0{(i%6)+1}-{(i%20)+1:02d}',
     f'2025-0{(i%6)+2}-15',
     ' ', '00' if i < 8 else 'ZZ', 'NB')
    for i in range(10)
])
print("  ✓ purchase_requisitions_sap_s4 (10)")

# SAP B1
cur.execute("DELETE FROM purchase_requisitions_sap_b1")
execute_values(cur, """
    INSERT INTO purchase_requisitions_sap_b1
    (DocNum,DocDate,ReqDate,ItemCode,Dscription,Quantity,
     UomCode,Price,Currency,LineTotal,OcrCode,ReqUser,DocStatus)
    VALUES %s
""", [
    (50001+i, f'2025-0{(i%6)+1}-{(i%20)+1:02d}',
     f'2025-0{(i%6)+2}-15',
     f'I-ITEM{str(i%10+1).zfill(3)}', ITEM_DESC[i%10][:100],
     float((i+1)*50), 'PCS', float((i+1)*10), 'USD',
     float((i+1)*500), f'CC-{i%5+1:03d}', REQUESTERS[i%10][:50],
     'O' if i >= 8 else 'C')
    for i in range(10)
])
print("  ✓ purchase_requisitions_sap_b1 (10)")

# Dynamics
cur.execute("DELETE FROM purchase_requisitions_dynamics")
execute_values(cur, """
    INSERT INTO purchase_requisitions_dynamics
    (RequisitionNumber,RequisitionName,RequesterEmail,Department,
     ItemNumber,ProductName,Quantity,UnitCost,CurrencyCode,
     TotalCost,Status,RequestDate,RequiredDate,CostCenter)
    VALUES %s
""", [
    (f'REQ-{str(i+1).zfill(6)}', f'{DEPTS[i%10]} Purchase Request',
     f'{REQUESTERS[i%10].replace(" ",".")[:50].lower()}@company.com',
     DEPTS[i%10], f'I-{str(i%10+1).zfill(3)}', ITEM_DESC[i%10][:100],
     float((i+1)*50), float((i+1)*10), 'USD', float((i+1)*500),
     'Approved' if i < 8 else 'Draft',
     f'2025-0{(i%6)+1}-{(i%20)+1:02d}',
     f'2025-0{(i%6)+2}-15', f'CC-{i%5+1:03d}')
    for i in range(10)
])
print("  ✓ purchase_requisitions_dynamics (10)")

# Oracle
cur.execute("DELETE FROM purchase_requisitions_oracle")
execute_values(cur, """
    INSERT INTO purchase_requisitions_oracle
    (RequisitionNumber,RequisitionType,RequesterPersonNumber,
     ItemNumber,ItemDescription,Quantity,UomCode,UnitPrice,
     CurrencyCode,LineAmount,Status,CreationDate,NeedByDate,CostCenter)
    VALUES %s
""", [
    (f'REQ-{str(i+1).zfill(7)}', 'Purchase',
     f'EMP-{str(i%10+1).zfill(5)}',
     f'IT-{str(i%10+1).zfill(5)}', ITEM_DESC[i%10][:240],
     float((i+1)*50), 'EA', float((i+1)*10), 'USD',
     float((i+1)*500),
     'APPROVED' if i < 8 else 'INCOMPLETE',
     f'2025-0{(i%6)+1}-{(i%20)+1:02d}',
     f'2025-0{(i%6)+2}-15', f'CC-{i%5+1:03d}')
    for i in range(10)
])
print("  ✓ purchase_requisitions_oracle (10)")

# ERPNext
cur.execute("DELETE FROM purchase_requisitions_erpnext")
execute_values(cur, """
    INSERT INTO purchase_requisitions_erpnext
    (name,title,material_request_type,transaction_date,
     schedule_date,requested_by,department,item_code,item_name,
     qty,stock_uom,rate,amount,cost_center,status,company)
    VALUES %s
""", [
    (f'MAT-MR-2025-{str(i+1).zfill(5)}',
     f'{DEPTS[i%10]} - {ITEM_DESC[i%10][:50]}',
     'Purchase',
     f'2025-0{(i%6)+1}-{(i%20)+1:02d}',
     f'2025-0{(i%6)+2}-15',
     REQUESTERS[i%10][:140], DEPTS[i%10][:140],
     f'ITEM-{str(i%10+1).zfill(3)}', ITEM_DESC[i%10][:140],
     float((i+1)*50), 'Nos',
     float((i+1)*10), float((i+1)*500),
     f'CC-{i%5+1:03d} - Dept', 'Submitted' if i < 8 else 'Draft',
     'Procure-AI Demo Company')
    for i in range(10)
])
print("  ✓ purchase_requisitions_erpnext (10)")

conn.commit()
print("\nSeeding rfq_headers...")

# Odoo
cur.execute("DELETE FROM rfq_headers_odoo")
execute_values(cur, """
    INSERT INTO rfq_headers_odoo
    (name,partner_id,date_order,validity_date,currency_id,
     amount_untaxed,amount_tax,amount_total,state,origin)
    VALUES %s
""", [
    (f'RFQ/2025/{str(i+1).zfill(5)}', VND_ODOO[i%10],
     f'2025-0{(i%6)+1}-{(i%20)+5:02d}',
     f'2025-0{(i%6)+2}-28',
     'USD', float((i+1)*1000), float((i+1)*150),
     float((i+1)*1150),
     'sent' if i < 7 else 'draft',
     f'PR/2025/{str(i+1).zfill(5)}')
    for i in range(8)
])
print("  ✓ rfq_headers_odoo (8)")

# SAP S/4
cur.execute("DELETE FROM rfq_headers_sap_s4")
execute_values(cur, """
    INSERT INTO rfq_headers_sap_s4
    (EBELN,BSART,LIFNR,BEDAT,KDATB,ANGDT,EKORG,EKGRP,NETWR,WAERS,STATUS)
    VALUES %s
""", [
    (f'6{str(i+1).zfill(9)}', 'AN',
     VND_SAP_S4[i%10],
     f'2025-0{(i%6)+1}-{(i%20)+5:02d}',
     f'2025-0{(i%6)+1}-{(i%20)+5:02d}',
     f'2025-0{(i%6)+2}-28',
     'ORG1', 'GRP', float((i+1)*1000), 'USD', 'B')
    for i in range(8)
])
print("  ✓ rfq_headers_sap_s4 (8)")

# SAP B1
cur.execute("DELETE FROM rfq_headers_sap_b1")
execute_values(cur, """
    INSERT INTO rfq_headers_sap_b1
    (DocNum,DocDate,DocDueDate,CardCode,CardName,DocTotal,DocCurrency,DocStatus)
    VALUES %s
""", [
    (60001+i, f'2025-0{(i%6)+1}-{(i%20)+5:02d}',
     f'2025-0{(i%6)+2}-28',
     VND_SAP_B1[i%10], f'Vendor {i+1}',
     float((i+1)*1000), 'USD', 'O' if i >= 6 else 'C')
    for i in range(8)
])
print("  ✓ rfq_headers_sap_b1 (8)")

# Dynamics
cur.execute("DELETE FROM rfq_headers_dynamics")
execute_values(cur, """
    INSERT INTO rfq_headers_dynamics
    (RFQCaseNumber,Title,PurchaseType,VendorAccountNumber,
     VendorName,ExpiryDate,RequestDate,TotalAmount,CurrencyCode,Status)
    VALUES %s
""", [
    (f'RFQ-{str(i+1).zfill(6)}', f'Request for Quote {i+1}',
     'Purchase', VND_DYN[i%10], f'Vendor {i+1}',
     f'2025-0{(i%6)+2}-28',
     f'2025-0{(i%6)+1}-{(i%20)+5:02d}',
     float((i+1)*1000), 'USD',
     'Sent' if i < 7 else 'Created')
    for i in range(8)
])
print("  ✓ rfq_headers_dynamics (8)")

# Oracle
cur.execute("DELETE FROM rfq_headers_oracle")
execute_values(cur, """
    INSERT INTO rfq_headers_oracle
    (NegotiationNumber,NegotiationType,SupplierNumber,SupplierName,
     OpenDate,CloseDate,TotalAmount,CurrencyCode,Status,BuyerName)
    VALUES %s
""", [
    (f'NEG-{str(i+1).zfill(6)}', 'RFQ',
     VND_ORA[i%10], f'Supplier {i+1}',
     f'2025-0{(i%6)+1}-{(i%20)+5:02d}',
     f'2025-0{(i%6)+2}-28',
     float((i+1)*1000), 'USD',
     'Active' if i < 7 else 'Draft',
     'Ahmed Khan')
    for i in range(8)
])
print("  ✓ rfq_headers_oracle (8)")

# ERPNext
cur.execute("DELETE FROM rfq_headers_erpnext")
execute_values(cur, """
    INSERT INTO rfq_headers_erpnext
    (name,transaction_date,valid_till,supplier,supplier_name,
     grand_total,currency,status,company)
    VALUES %s
""", [
    (f'PUR-RFQ-2025-{str(i+1).zfill(5)}',
     f'2025-0{(i%6)+1}-{(i%20)+5:02d}',
     f'2025-0{(i%6)+2}-28',
     VND_ERP[i%10], f'Supplier {i+1}',
     float((i+1)*1000), 'USD',
     'Submitted' if i < 7 else 'Draft',
     'Procure-AI Demo Company')
    for i in range(8)
])
print("  ✓ rfq_headers_erpnext (8)")

conn.commit()
print("\nSeeding vendor_quotes...")

execute_values(cur, """INSERT INTO vendor_quotes_odoo
    (name,partner_id,rfq_id,date_order,validity_date,currency_id,
     amount_untaxed,amount_tax,amount_total,state,recommended)
    VALUES %s""", [
    (f'QUOT/2025/{str(i+1).zfill(5)}', VND_ODOO[i%10],
     f'RFQ/2025/{str(i+1).zfill(5)}',
     f'2025-0{(i%6)+1}-{(i%20)+8:02d}',
     f'2025-0{(i%6)+2}-28', 'USD',
     float((i+1)*950), float((i+1)*142),
     float((i+1)*1092),
     'purchase' if i < 5 else 'sent', i < 3)
    for i in range(8)
])
print("  ✓ vendor_quotes_odoo (8)")

execute_values(cur, """INSERT INTO vendor_quotes_sap_s4
    (ANGPF,EBELN,LIFNR,ANGDT,BNDDT,NETWR,WAERS,PREIS,MENGE,EKORG,SELKZ)
    VALUES %s""", [
    (f'7{str(i+1).zfill(9)}', f'6{str(i+1).zfill(9)}',
     VND_SAP_S4[i%10],
     f'2025-0{(i%6)+1}-{(i%20)+8:02d}',
     f'2025-0{(i%6)+2}-28',
     float((i+1)*950), 'USD',
     float((i+1)*9.5), float((i+1)*100), 'ORG1',
     'X' if i < 3 else ' ')
    for i in range(8)
])
print("  ✓ vendor_quotes_sap_s4 (8)")

execute_values(cur, """INSERT INTO vendor_quotes_sap_b1
    (DocNum,DocDate,ValidUntil,CardCode,CardName,BaseRef,
     DocTotal,DocCurrency,DocStatus,Recommended)
    VALUES %s""", [
    (70001+i, f'2025-0{(i%6)+1}-{(i%20)+8:02d}',
     f'2025-0{(i%6)+2}-28',
     VND_SAP_B1[i%10], f'Vendor {i+1}',
     str(60001+i), float((i+1)*1092), 'USD',
     'O' if i >= 5 else 'C', 'Y' if i < 3 else 'N')
    for i in range(8)
])
print("  ✓ vendor_quotes_sap_b1 (8)")

execute_values(cur, """INSERT INTO vendor_quotes_dynamics
    (ReplyJournalNumber,RFQCaseNumber,VendorAccountNumber,VendorName,
     ReplyDate,ExpiryDate,TotalAmount,CurrencyCode,IsLowest,Status)
    VALUES %s""", [
    (f'REPLY-{str(i+1).zfill(6)}', f'RFQ-{str(i+1).zfill(6)}',
     VND_DYN[i%10], f'Vendor {i+1}',
     f'2025-0{(i%6)+1}-{(i%20)+8:02d}',
     f'2025-0{(i%6)+2}-28',
     float((i+1)*1092), 'USD',
     'true' if i < 3 else 'false',
     'Accepted' if i < 5 else 'Submitted')
    for i in range(8)
])
print("  ✓ vendor_quotes_dynamics (8)")

execute_values(cur, """INSERT INTO vendor_quotes_oracle
    (ResponseNumber,NegotiationNumber,SupplierNumber,SupplierName,
     ResponseDate,ExpirationDate,QuoteAmount,CurrencyCode,IsRecommended,Status)
    VALUES %s""", [
    (f'RESP-{str(i+1).zfill(6)}', f'NEG-{str(i+1).zfill(6)}',
     VND_ORA[i%10], f'Supplier {i+1}',
     f'2025-0{(i%6)+1}-{(i%20)+8:02d}',
     f'2025-0{(i%6)+2}-28',
     float((i+1)*1092), 'USD',
     'Y' if i < 3 else 'N',
     'ACTIVE' if i < 5 else 'DRAFT')
    for i in range(8)
])
print("  ✓ vendor_quotes_oracle (8)")

execute_values(cur, """INSERT INTO vendor_quotes_erpnext
    (name,rfq_reference,supplier,supplier_name,transaction_date,
     valid_till,grand_total,currency,status,is_recommended,company)
    VALUES %s""", [
    (f'PUR-SQT-2025-{str(i+1).zfill(5)}',
     f'PUR-RFQ-2025-{str(i+1).zfill(5)}',
     VND_ERP[i%10], f'Supplier {i+1}',
     f'2025-0{(i%6)+1}-{(i%20)+8:02d}',
     f'2025-0{(i%6)+2}-28',
     float((i+1)*1092), 'USD',
     'Submitted' if i < 5 else 'Draft',
     1 if i < 3 else 0,
     'Procure-AI Demo Company')
    for i in range(8)
])
print("  ✓ vendor_quotes_erpnext (8)")

conn.commit()
print("\nSeeding contracts...")

execute_values(cur, """INSERT INTO contracts_odoo
    (name,partner_id,date_order,date_approve,date_planned,currency_id,
     amount_untaxed,amount_total,is_blanket_order,state,payment_term_id)
    VALUES %s""", [
    (f'BPO/2025/{str(i+1).zfill(5)}', VND_ODOO[i%10],
     f'2025-0{(i%3)+1}-01', f'2025-0{(i%3)+1}-05',
     f'2026-0{(i%3)+1}-01', 'USD',
     float((i+1)*50000), float((i+1)*57500),
     True, 'purchase' if i < 4 else 'draft',
     'Net 30')
    for i in range(6)
])
print("  ✓ contracts_odoo (6)")

execute_values(cur, """INSERT INTO contracts_sap_s4
    (EBELN,BSART,LIFNR,BEDAT,KDATB,KDATE,EKORG,EKGRP,NETWR,WAERS,STATUS)
    VALUES %s""", [
    (f'55000{str(i+1).zfill(5)}', 'LP',
     VND_SAP_S4[i%10],
     f'2025-0{(i%3)+1}-01',
     f'2025-0{(i%3)+1}-01',
     f'2026-0{(i%3)+1}-01',
     'ORG1', 'GRP', float((i+1)*50000), 'USD',
     'A' if i < 4 else 'I')
    for i in range(6)
])
print("  ✓ contracts_sap_s4 (6)")

execute_values(cur, """INSERT INTO contracts_sap_b1
    (AgreementNo,CardCode,CardName,StartDate,EndDate,
     AgreementType,TotalAmount,Currency,Status,Description)
    VALUES %s""", [
    (80001+i, VND_SAP_B1[i%10], f'Vendor {i+1}',
     f'2025-0{(i%3)+1}-01', f'2026-0{(i%3)+1}-01',
     'General', float((i+1)*50000), 'USD',
     'Active' if i < 4 else 'Expired',
     f'Annual supply contract {i+1}')
    for i in range(6)
])
print("  ✓ contracts_sap_b1 (6)")

execute_values(cur, """INSERT INTO contracts_dynamics
    (AgreementNumber,AgreementClassification,VendorAccountNumber,VendorName,
     EffectiveDate,ExpirationDate,CommitmentAmount,CurrencyCode,Status)
    VALUES %s""", [
    (f'AGMT-{str(i+1).zfill(6)}', 'Blanket',
     VND_DYN[i%10], f'Vendor {i+1}',
     f'2025-0{(i%3)+1}-01', f'2026-0{(i%3)+1}-01',
     float((i+1)*50000), 'USD',
     'Effective' if i < 4 else 'Expired')
    for i in range(6)
])
print("  ✓ contracts_dynamics (6)")

execute_values(cur, """INSERT INTO contracts_oracle
    (ContractNumber,ContractType,SupplierNumber,SupplierName,
     StartDate,EndDate,ContractAmount,CurrencyCode,Status,BuyerName)
    VALUES %s""", [
    (f'CON-{str(i+1).zfill(6)}', 'Blanket Purchase Agreement',
     VND_ORA[i%10], f'Supplier {i+1}',
     f'2025-0{(i%3)+1}-01', f'2026-0{(i%3)+1}-01',
     float((i+1)*50000), 'USD',
     'ACTIVE' if i < 4 else 'EXPIRED', 'Ahmed Khan')
    for i in range(6)
])
print("  ✓ contracts_oracle (6)")

execute_values(cur, """INSERT INTO contracts_erpnext
    (name,supplier,supplier_name,start_date,end_date,
     contract_value,currency,status,contract_type,company)
    VALUES %s""", [
    (f'PUR-CON-2025-{str(i+1).zfill(5)}',
     VND_ERP[i%10], f'Supplier {i+1}',
     f'2025-0{(i%3)+1}-01', f'2026-0{(i%3)+1}-01',
     float((i+1)*50000), 'USD',
     'Active' if i < 4 else 'Expired',
     'Annual Contract', 'Procure-AI Demo Company')
    for i in range(6)
])
print("  ✓ contracts_erpnext (6)")

conn.commit()

# Update table_registry
cur.execute("DELETE FROM table_registry WHERE erp_source IS NOT NULL AND table_name LIKE 'purchase_requisitions%'")
cur.execute("DELETE FROM table_registry WHERE erp_source IS NOT NULL AND table_name LIKE 'rfq_headers%'")
cur.execute("DELETE FROM table_registry WHERE erp_source IS NOT NULL AND table_name LIKE 'vendor_quotes%'")
cur.execute("DELETE FROM table_registry WHERE erp_source IS NOT NULL AND table_name LIKE 'contracts%'")

new_registry = []
for mod, module_name, module_code, odoo_model, sap_obj, desc in [
    ('purchase_requisitions','Procurement','PRC','purchase.order','EBAN','Purchase Requisitions'),
    ('rfq_headers','Procurement','PRC','purchase.order','EKKO/AN','RFQ Headers'),
    ('vendor_quotes','Procurement','PRC','purchase.order','EKKO/AN','Vendor Quotes'),
    ('contracts','Procurement','PRC','purchase.order','EKKO/LP','Contracts / Blanket POs'),
]:
    for erp in ERPS:
        tbl = f'{mod}_{erp}'
        new_registry.append((tbl, module_name, module_code, 'transaction', desc, odoo_model, sap_obj, erp, tbl))

execute_values(cur, """
    INSERT INTO table_registry
        (table_name, module, module_code, table_type, description, odoo_model, sap_object, erp_source, erp_table_name)
    VALUES %s ON CONFLICT (table_name) DO NOTHING
""", new_registry)
conn.commit()

print(f"\n{'='*60}")
print("BATCH 1 COMPLETE — 24 tables created and seeded")
print(f"{'='*60}")
cur.close(); conn.close()
