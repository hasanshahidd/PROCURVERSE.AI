"""
Sprint 5 — ERP-Specific Tables Migration
Creates 7 core P2P tables × 6 ERPs = 42 tables in PostgreSQL.
Each table uses that ERP's real field names, ID formats, and terminology.

ERPs: odoo | sap_s4 | sap_b1 | dynamics | oracle | erpnext
Tables: vendors | items | po_headers | po_lines | grn_headers | invoices | spend
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

with open(os.path.join(os.path.dirname(__file__), '..', '..', '.env')) as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

import psycopg2
from psycopg2.extras import execute_values

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — CREATE ERP-SPECIFIC TABLE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

schemas = {}

# ── ODOO ─────────────────────────────────────────────────────────────────────
schemas['vendors_odoo'] = """
CREATE TABLE IF NOT EXISTS vendors_odoo (
    id                              SERIAL PRIMARY KEY,
    name                            VARCHAR(200),
    ref                             VARCHAR(50),       -- external vendor ref
    vat                             VARCHAR(50),       -- tax/VAT number
    company_type                    VARCHAR(20),       -- company / person
    street                          VARCHAR(200),
    city                            VARCHAR(100),
    country_id                      VARCHAR(50),
    phone                           VARCHAR(50),
    email                           VARCHAR(150),
    website                         VARCHAR(200),
    property_account_payable_id     VARCHAR(50),       -- GL payable account
    property_supplier_payment_term_id VARCHAR(50),
    supplier_rank                   INTEGER DEFAULT 1,
    active                          BOOLEAN DEFAULT TRUE,
    lang                            VARCHAR(10) DEFAULT 'en_US',
    currency_id                     VARCHAR(10) DEFAULT 'USD',
    erp_source                      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['items_odoo'] = """
CREATE TABLE IF NOT EXISTS items_odoo (
    id                              SERIAL PRIMARY KEY,
    name                            VARCHAR(300),
    default_code                    VARCHAR(100),      -- internal reference
    barcode                         VARCHAR(100),
    categ_id                        VARCHAR(100),      -- product category
    type                            VARCHAR(20),       -- product / consu / service
    uom_id                          VARCHAR(50),       -- unit of measure
    uom_po_id                       VARCHAR(50),       -- purchase UOM
    standard_price                  NUMERIC(14,4),
    purchase_ok                     BOOLEAN DEFAULT TRUE,
    active                          BOOLEAN DEFAULT TRUE,
    description_purchase            TEXT,
    taxes_id                        VARCHAR(50),
    property_account_expense_id     VARCHAR(50),
    erp_source                      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['po_headers_odoo'] = """
CREATE TABLE IF NOT EXISTS po_headers_odoo (
    id                              SERIAL PRIMARY KEY,
    name                            VARCHAR(50),       -- PO00001
    partner_id                      VARCHAR(200),      -- vendor name
    date_order                      DATE,
    date_approve                    DATE,
    date_planned                    DATE,
    user_id                         VARCHAR(100),      -- buyer
    company_id                      VARCHAR(100),
    currency_id                     VARCHAR(10),
    amount_untaxed                  NUMERIC(14,2),
    amount_tax                      NUMERIC(14,2),
    amount_total                    NUMERIC(14,2),
    state                           VARCHAR(20),       -- draft/sent/purchase/done/cancel
    notes                           TEXT,
    incoterm_id                     VARCHAR(20),
    payment_term_id                 VARCHAR(50),
    erp_source                      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['po_lines_odoo'] = """
CREATE TABLE IF NOT EXISTS po_lines_odoo (
    id                              SERIAL PRIMARY KEY,
    order_id                        VARCHAR(50),       -- PO name ref
    product_id                      VARCHAR(200),
    name                            TEXT,              -- line description
    product_qty                     NUMERIC(14,4),
    product_uom                     VARCHAR(50),
    price_unit                      NUMERIC(14,4),
    price_subtotal                  NUMERIC(14,2),
    price_tax                       NUMERIC(14,2),
    price_total                     NUMERIC(14,2),
    taxes_id                        VARCHAR(50),
    account_analytic_id             VARCHAR(100),
    date_planned                    DATE,
    qty_received                    NUMERIC(14,4) DEFAULT 0,
    qty_invoiced                    NUMERIC(14,4) DEFAULT 0,
    erp_source                      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['grn_headers_odoo'] = """
CREATE TABLE IF NOT EXISTS grn_headers_odoo (
    id                              SERIAL PRIMARY KEY,
    name                            VARCHAR(50),       -- WH/IN/00001
    partner_id                      VARCHAR(200),      -- vendor
    origin                          VARCHAR(100),      -- PO reference
    scheduled_date                  DATE,
    date_done                       DATE,
    picking_type_id                 VARCHAR(50),
    location_id                     VARCHAR(100),
    location_dest_id                VARCHAR(100),
    state                           VARCHAR(20),       -- done/ready/waiting
    note                            TEXT,
    erp_source                      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['invoices_odoo'] = """
CREATE TABLE IF NOT EXISTS invoices_odoo (
    id                              SERIAL PRIMARY KEY,
    name                            VARCHAR(50),       -- BILL/2025/00001
    move_type                       VARCHAR(20) DEFAULT 'in_invoice',
    partner_id                      VARCHAR(200),
    invoice_date                    DATE,
    invoice_date_due                DATE,
    ref                             VARCHAR(100),      -- vendor invoice number
    invoice_origin                  VARCHAR(100),      -- PO reference
    amount_untaxed                  NUMERIC(14,2),
    amount_tax                      NUMERIC(14,2),
    amount_total                    NUMERIC(14,2),
    amount_residual                 NUMERIC(14,2),
    currency_id                     VARCHAR(10),
    state                           VARCHAR(20),       -- draft/posted/cancel
    payment_state                   VARCHAR(30),       -- not_paid/in_payment/paid/partial
    journal_id                      VARCHAR(50),
    erp_source                      VARCHAR(20) DEFAULT 'odoo'
)"""

schemas['spend_odoo'] = """
CREATE TABLE IF NOT EXISTS spend_odoo (
    id                              SERIAL PRIMARY KEY,
    name                            VARCHAR(50),       -- PO name
    partner_id                      VARCHAR(200),      -- vendor
    date_approve                    DATE,
    amount_total                    NUMERIC(14,2),
    currency_id                     VARCHAR(10),
    x_department                    VARCHAR(100),
    x_budget_category               VARCHAR(50),
    state                           VARCHAR(20),
    company_id                      VARCHAR(100),
    erp_source                      VARCHAR(20) DEFAULT 'odoo'
)"""

# ── SAP S/4HANA ───────────────────────────────────────────────────────────────
schemas['vendors_sap_s4'] = """
CREATE TABLE IF NOT EXISTS vendors_sap_s4 (
    LIFNR       VARCHAR(10) PRIMARY KEY,   -- vendor account number
    NAME1       VARCHAR(35),               -- name 1
    NAME2       VARCHAR(35),               -- name 2
    LAND1       VARCHAR(3),                -- country key
    ORT01       VARCHAR(35),               -- city
    STRAS       VARCHAR(35),               -- street
    PSTLZ       VARCHAR(10),               -- postal code
    TELF1       VARCHAR(16),               -- phone
    SMTP_ADDR   VARCHAR(241),              -- email
    KTOKK       VARCHAR(4),                -- vendor account group
    AKONT       VARCHAR(10),               -- reconciliation account (LFB1)
    ZTERM       VARCHAR(4),                -- payment terms
    EKGRP       VARCHAR(3),                -- purchasing group
    WAERS       VARCHAR(5),                -- currency
    BUKRS       VARCHAR(4),                -- company code
    EKORG       VARCHAR(4),                -- purchasing organisation
    SPRAS       VARCHAR(1) DEFAULT 'E',    -- language
    SPERR       VARCHAR(1) DEFAULT ' ',    -- central block
    LOEVM       VARCHAR(1) DEFAULT ' ',    -- deletion flag
    erp_source  VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['items_sap_s4'] = """
CREATE TABLE IF NOT EXISTS items_sap_s4 (
    MATNR       VARCHAR(18) PRIMARY KEY,   -- material number
    MAKTX       VARCHAR(40),               -- material description
    MEINS       VARCHAR(3),                -- base unit of measure
    MTART       VARCHAR(4),                -- material type (ROH/HALB/FERT)
    MATKL       VARCHAR(9),                -- material group
    WERKS       VARCHAR(4),                -- plant
    NETPR       NUMERIC(14,4),             -- net price
    PEINH       NUMERIC(9,0) DEFAULT 1,    -- price unit
    WAERS       VARCHAR(5),                -- currency
    MFRNR       VARCHAR(10),               -- vendor number (preferred)
    BSTMI       NUMERIC(13,3),             -- minimum order qty
    MINBE       NUMERIC(13,3),             -- reorder point
    EISBE       NUMERIC(13,3),             -- safety stock
    WEBAZ       INTEGER,                   -- goods receipt processing time
    MMSTA       VARCHAR(2),                -- x-plant material status
    erp_source  VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['po_headers_sap_s4'] = """
CREATE TABLE IF NOT EXISTS po_headers_sap_s4 (
    EBELN       VARCHAR(10) PRIMARY KEY,   -- purchasing document number
    BUKRS       VARCHAR(4),                -- company code
    BSART       VARCHAR(4),                -- order type (NB/FO/UB)
    LIFNR       VARCHAR(10),               -- vendor
    EKORG       VARCHAR(4),                -- purchasing org
    EKGRP       VARCHAR(3),                -- purchasing group
    BEDAT       DATE,                      -- PO date
    KDATB       DATE,                      -- validity start
    KDATE       DATE,                      -- validity end
    WAERS       VARCHAR(5),                -- currency
    NETWR       NUMERIC(15,2),             -- net order value
    WKURS       NUMERIC(9,5),              -- exchange rate
    ZTERM       VARCHAR(4),                -- payment terms
    INCO1       VARCHAR(3),                -- incoterms 1
    INCO2       VARCHAR(28),               -- incoterms 2
    STATU       VARCHAR(1),                -- status
    erp_source  VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['po_lines_sap_s4'] = """
CREATE TABLE IF NOT EXISTS po_lines_sap_s4 (
    EBELN       VARCHAR(10),               -- PO number
    EBELP       VARCHAR(5),                -- line item number
    MATNR       VARCHAR(18),               -- material number
    TXZ01       VARCHAR(40),               -- short text
    WERKS       VARCHAR(4),                -- plant
    LGORT       VARCHAR(4),                -- storage location
    MENGE       NUMERIC(13,3),             -- PO quantity
    MEINS       VARCHAR(3),                -- UOM
    NETPR       NUMERIC(14,4),             -- net price
    PEINH       NUMERIC(9,0) DEFAULT 1,    -- price unit
    NETWR       NUMERIC(15,2),             -- net value
    MWSKZ       VARCHAR(2),                -- tax code
    EINDT       DATE,                      -- delivery date
    WEMNG       NUMERIC(13,3) DEFAULT 0,   -- qty delivered
    REMNG       NUMERIC(13,3) DEFAULT 0,   -- qty invoiced
    LOEKZ       VARCHAR(1) DEFAULT ' ',    -- deletion indicator
    erp_source  VARCHAR(20) DEFAULT 'sap_s4',
    PRIMARY KEY (EBELN, EBELP)
)"""

schemas['grn_headers_sap_s4'] = """
CREATE TABLE IF NOT EXISTS grn_headers_sap_s4 (
    MBLNR       VARCHAR(10) PRIMARY KEY,   -- material document number
    MJAHR       VARCHAR(4),                -- fiscal year
    BUDAT       DATE,                      -- posting date
    BLDAT       DATE,                      -- document date
    XBLNR       VARCHAR(20),               -- reference document
    BKTXT       VARCHAR(25),               -- header text
    LIFNR       VARCHAR(10),               -- vendor
    EBELN       VARCHAR(10),               -- PO reference
    WERKS       VARCHAR(4),                -- plant
    LGORT       VARCHAR(4),                -- storage location
    BWART       VARCHAR(3),                -- movement type (101=GR)
    USNAM       VARCHAR(12),               -- username
    erp_source  VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['invoices_sap_s4'] = """
CREATE TABLE IF NOT EXISTS invoices_sap_s4 (
    BELNR       VARCHAR(10) PRIMARY KEY,   -- document number (RBKPV)
    BUKRS       VARCHAR(4),                -- company code
    GJAHR       VARCHAR(4),                -- fiscal year
    BLART       VARCHAR(2),                -- document type (RE=vendor inv)
    BLDAT       DATE,                      -- document date
    BUDAT       DATE,                      -- posting date
    LIFNR       VARCHAR(10),               -- vendor
    XBLNR       VARCHAR(20),               -- vendor invoice reference
    WRBTR       NUMERIC(15,2),             -- amount in document currency
    DMBTR       NUMERIC(15,2),             -- amount in local currency
    WAERS       VARCHAR(5),                -- currency
    ZFBDT       DATE,                      -- baseline date for payment
    ZLSCH       VARCHAR(1),                -- payment method
    ZTERM       VARCHAR(4),                -- payment terms
    EBELN       VARCHAR(10),               -- PO reference
    MWSKZ       VARCHAR(2),                -- tax code
    SHKZG       VARCHAR(1) DEFAULT 'H',    -- debit/credit (H=credit)
    erp_source  VARCHAR(20) DEFAULT 'sap_s4'
)"""

schemas['spend_sap_s4'] = """
CREATE TABLE IF NOT EXISTS spend_sap_s4 (
    EBELN       VARCHAR(10),               -- PO number
    BUKRS       VARCHAR(4),                -- company code
    LIFNR       VARCHAR(10),               -- vendor
    EKORG       VARCHAR(4),                -- purchasing org
    BEDAT       DATE,                      -- PO date
    NETWR       NUMERIC(15,2),             -- net value
    WAERS       VARCHAR(5),                -- currency
    KOSTL       VARCHAR(10),               -- cost center
    SAKTO       VARCHAR(10),               -- GL account
    MATKL       VARCHAR(9),                -- material group
    MATNR       VARCHAR(18),               -- material
    BSART       VARCHAR(4),                -- doc type
    erp_source  VARCHAR(20) DEFAULT 'sap_s4',
    PRIMARY KEY (EBELN)
)"""

# ── SAP BUSINESS ONE ──────────────────────────────────────────────────────────
schemas['vendors_sap_b1'] = """
CREATE TABLE IF NOT EXISTS vendors_sap_b1 (
    CardCode        VARCHAR(15) PRIMARY KEY,   -- supplier code
    CardName        VARCHAR(100),              -- supplier name
    CardType        VARCHAR(1) DEFAULT 'S',    -- S=supplier
    GroupCode       INTEGER,                   -- supplier group
    CreditLimit     NUMERIC(19,6),
    Balance         NUMERIC(19,6) DEFAULT 0,
    PayTermsGrpCode INTEGER,                   -- payment terms
    PeyMethodCode   VARCHAR(15),               -- payment method
    VatLiable       VARCHAR(1) DEFAULT 'Y',
    Country         VARCHAR(3),
    City            VARCHAR(100),
    ZipCode         VARCHAR(20),
    Phone1          VARCHAR(20),
    E_Mail          VARCHAR(100),
    Currency        VARCHAR(3) DEFAULT 'USD',
    TaxCode         VARCHAR(8),
    OnHold          VARCHAR(1) DEFAULT 'N',
    Valid           VARCHAR(1) DEFAULT 'Y',
    Frozen          VARCHAR(1) DEFAULT 'N',
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['items_sap_b1'] = """
CREATE TABLE IF NOT EXISTS items_sap_b1 (
    ItemCode        VARCHAR(20) PRIMARY KEY,
    ItemName        VARCHAR(100),
    ItemType        VARCHAR(1) DEFAULT 'I',    -- I=items, S=service
    ItmsGrpCod      INTEGER,                   -- item group
    InvntryUom      VARCHAR(8),                -- inventory UOM
    PurPackUn       VARCHAR(8),                -- purchase UOM
    LastPurPrc      NUMERIC(19,6),             -- last purchase price
    Currency        VARCHAR(3) DEFAULT 'USD',
    MinLevel        NUMERIC(19,6),             -- minimum stock
    ReorderPnt      NUMERIC(19,6),             -- reorder point
    LeadTime        INTEGER,                   -- lead time (days)
    MinOrderQty     NUMERIC(19,6),
    Taxable         VARCHAR(1) DEFAULT 'Y',
    InvntItem       VARCHAR(1) DEFAULT 'Y',    -- inventory item flag
    PrchseItem      VARCHAR(1) DEFAULT 'Y',    -- purchase item flag
    frozenFor       VARCHAR(1) DEFAULT 'N',
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['po_headers_sap_b1'] = """
CREATE TABLE IF NOT EXISTS po_headers_sap_b1 (
    DocNum          INTEGER PRIMARY KEY,       -- document number
    DocType         VARCHAR(1) DEFAULT 'I',    -- I=items, S=service
    DocDate         DATE,                      -- posting date
    DocDueDate      DATE,                      -- delivery date
    CardCode        VARCHAR(15),               -- supplier code
    CardName        VARCHAR(100),              -- supplier name
    NumAtCard       VARCHAR(100),              -- vendor reference
    DocTotal        NUMERIC(19,6),             -- total amount
    VatSum          NUMERIC(19,6),             -- tax amount
    DiscSum         NUMERIC(19,6) DEFAULT 0,   -- discount
    DocCurrency     VARCHAR(3) DEFAULT 'USD',
    DocRate         NUMERIC(19,6) DEFAULT 1,   -- exchange rate
    Comments        VARCHAR(254),
    DocStatus       VARCHAR(1) DEFAULT 'O',    -- O=open, C=closed
    PayToCode       VARCHAR(15),               -- bill-to address
    ShipToCode      VARCHAR(15),               -- ship-to address
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['po_lines_sap_b1'] = """
CREATE TABLE IF NOT EXISTS po_lines_sap_b1 (
    DocNum          INTEGER,
    LineNum         INTEGER,
    ItemCode        VARCHAR(20),
    Dscription      VARCHAR(100),
    Quantity        NUMERIC(19,6),
    InvQty          NUMERIC(19,6),
    UomCode         VARCHAR(8),
    Price           NUMERIC(19,6),
    LineTotal       NUMERIC(19,6),
    TaxCode         VARCHAR(8),
    WhsCode         VARCHAR(8),                -- warehouse
    ShipDate        DATE,
    OpenQty         NUMERIC(19,6),
    InvQtySrvsd     NUMERIC(19,6) DEFAULT 0,
    LineStatus      VARCHAR(1) DEFAULT 'O',
    erp_source      VARCHAR(20) DEFAULT 'sap_b1',
    PRIMARY KEY (DocNum, LineNum)
)"""

schemas['grn_headers_sap_b1'] = """
CREATE TABLE IF NOT EXISTS grn_headers_sap_b1 (
    DocNum          INTEGER PRIMARY KEY,       -- OPDN doc number
    DocDate         DATE,
    DocDueDate      DATE,
    CardCode        VARCHAR(15),
    CardName        VARCHAR(100),
    NumAtCard       VARCHAR(100),              -- vendor delivery note
    BaseRef         VARCHAR(100),              -- PO reference
    DocTotal        NUMERIC(19,6),
    DocCurrency     VARCHAR(3) DEFAULT 'USD',
    Comments        VARCHAR(254),
    DocStatus       VARCHAR(1) DEFAULT 'C',    -- C=closed (posted)
    Confirmed       VARCHAR(1) DEFAULT 'Y',
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['invoices_sap_b1'] = """
CREATE TABLE IF NOT EXISTS invoices_sap_b1 (
    DocNum          INTEGER PRIMARY KEY,       -- OPCH doc number
    DocDate         DATE,                      -- invoice date
    DocDueDate      DATE,                      -- due date
    CardCode        VARCHAR(15),               -- supplier code
    CardName        VARCHAR(100),
    NumAtCard       VARCHAR(100),              -- vendor invoice number
    DocTotal        NUMERIC(19,6),
    VatSum          NUMERIC(19,6),
    DiscSum         NUMERIC(19,6) DEFAULT 0,
    DocCurrency     VARCHAR(3) DEFAULT 'USD',
    DocRate         NUMERIC(19,6) DEFAULT 1,
    BaseRef         VARCHAR(100),              -- PO/GRN ref
    Comments        VARCHAR(254),
    DocStatus       VARCHAR(1) DEFAULT 'O',    -- O=open, C=closed
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""

schemas['spend_sap_b1'] = """
CREATE TABLE IF NOT EXISTS spend_sap_b1 (
    DocNum          INTEGER PRIMARY KEY,
    CardCode        VARCHAR(15),
    CardName        VARCHAR(100),
    DocDate         DATE,
    DocTotal        NUMERIC(19,6),
    DocCurrency     VARCHAR(3),
    OcrCode         VARCHAR(8),                -- cost center (distribution rule)
    Project         VARCHAR(8),                -- project code
    ItmsGrpCod      INTEGER,                   -- item group
    DocStatus       VARCHAR(1),
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""

# ── MICROSOFT DYNAMICS 365 ────────────────────────────────────────────────────
schemas['vendors_dynamics'] = """
CREATE TABLE IF NOT EXISTS vendors_dynamics (
    VendorAccount       VARCHAR(20) PRIMARY KEY,   -- V-XXXXX format
    VendorName          VARCHAR(200),
    VendorGroup         VARCHAR(10),
    Currency            VARCHAR(3),
    CountryRegion       VARCHAR(3),
    City                VARCHAR(60),
    ZipCode             VARCHAR(10),
    Phone               VARCHAR(30),
    Email               VARCHAR(150),
    PaymentTerms        VARCHAR(10),
    PaymentMethod       VARCHAR(10),
    PostingProfile      VARCHAR(10),
    TaxGroup            VARCHAR(10),
    VATNumber           VARCHAR(30),
    BankAccount         VARCHAR(30),
    OnHold              VARCHAR(10) DEFAULT 'No',  -- No/All/Invoice/Payment
    OneTimeVendor       VARCHAR(5) DEFAULT 'No',
    ContactPerson       VARCHAR(100),
    BusinessUnit        VARCHAR(10),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['items_dynamics'] = """
CREATE TABLE IF NOT EXISTS items_dynamics (
    ItemNumber          VARCHAR(20) PRIMARY KEY,
    ProductName         VARCHAR(200),
    SearchName          VARCHAR(60),
    ItemGroup           VARCHAR(10),
    StorageDimensionGroup VARCHAR(10),
    TrackingDimensionGroup VARCHAR(10),
    UnitOfMeasure       VARCHAR(10),
    PurchaseUOM         VARCHAR(10),
    PurchasePrice       NUMERIC(19,6),
    CostingMethod       VARCHAR(10),
    TaxItemGroup        VARCHAR(10),
    ReorderPoint        NUMERIC(19,6),
    SafetyStock         NUMERIC(19,6),
    MinOrderQty         NUMERIC(19,6),
    LeadTimeInDays      INTEGER,
    Blocked             VARCHAR(5) DEFAULT 'No',
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['po_headers_dynamics'] = """
CREATE TABLE IF NOT EXISTS po_headers_dynamics (
    PurchaseOrderNumber VARCHAR(20) PRIMARY KEY,   -- PO-XXXXXX
    PurchaseOrderName   VARCHAR(200),
    VendorAccountNumber VARCHAR(20),
    VendorName          VARCHAR(200),
    OrderDate           DATE,
    DeliveryDate        DATE,
    CurrencyCode        VARCHAR(3),
    ExchangeRate        NUMERIC(19,6) DEFAULT 1,
    TotalAmount         NUMERIC(19,2),
    TaxAmount           NUMERIC(19,2),
    DiscountAmount      NUMERIC(19,2) DEFAULT 0,
    PaymentTerms        VARCHAR(10),
    DeliveryTerms       VARCHAR(10),
    PurchasingAgent     VARCHAR(100),
    CompanyAccount      VARCHAR(10),
    Status              VARCHAR(20),   -- Draft/Confirmed/Received/Invoiced/Closed
    LegalEntity         VARCHAR(10),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['po_lines_dynamics'] = """
CREATE TABLE IF NOT EXISTS po_lines_dynamics (
    PurchaseOrderNumber VARCHAR(20),
    LineNumber          INTEGER,
    ItemNumber          VARCHAR(20),
    ProductName         VARCHAR(200),
    Quantity            NUMERIC(19,6),
    Unit                VARCHAR(10),
    UnitPrice           NUMERIC(19,6),
    LineAmount          NUMERIC(19,2),
    TaxGroup            VARCHAR(10),
    Site                VARCHAR(10),
    Warehouse           VARCHAR(10),
    DeliveryDate        DATE,
    ReceivedQuantity    NUMERIC(19,6) DEFAULT 0,
    InvoicedQuantity    NUMERIC(19,6) DEFAULT 0,
    erp_source          VARCHAR(20) DEFAULT 'dynamics',
    PRIMARY KEY (PurchaseOrderNumber, LineNumber)
)"""

schemas['grn_headers_dynamics'] = """
CREATE TABLE IF NOT EXISTS grn_headers_dynamics (
    ProductReceiptNumber VARCHAR(20) PRIMARY KEY,
    PurchaseOrderNumber  VARCHAR(20),
    VendorAccountNumber  VARCHAR(20),
    VendorName           VARCHAR(200),
    ReceiptDate          DATE,
    Site                 VARCHAR(10),
    Warehouse            VARCHAR(10),
    DeliveryNote         VARCHAR(50),
    Status               VARCHAR(20) DEFAULT 'Received',
    PostingDate          DATE,
    Description          VARCHAR(200),
    erp_source           VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['invoices_dynamics'] = """
CREATE TABLE IF NOT EXISTS invoices_dynamics (
    VendorInvoiceNumber VARCHAR(50) PRIMARY KEY,
    InvoiceDescription  VARCHAR(200),
    VendorAccountNumber VARCHAR(20),
    VendorName          VARCHAR(200),
    InvoiceDate         DATE,
    DueDate             DATE,
    PurchaseOrderNumber VARCHAR(20),
    TotalAmount         NUMERIC(19,2),
    TaxAmount           NUMERIC(19,2),
    CurrencyCode        VARCHAR(3),
    PaymentTerms        VARCHAR(10),
    Status              VARCHAR(20),   -- Pending/Approved/Paid/OnHold
    PostingProfile      VARCHAR(10),
    ApprovedBy          VARCHAR(100),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

schemas['spend_dynamics'] = """
CREATE TABLE IF NOT EXISTS spend_dynamics (
    PurchaseOrderNumber VARCHAR(20) PRIMARY KEY,
    VendorAccountNumber VARCHAR(20),
    VendorName          VARCHAR(200),
    OrderDate           DATE,
    TotalAmount         NUMERIC(19,2),
    CurrencyCode        VARCHAR(3),
    Department          VARCHAR(100),
    BusinessUnit        VARCHAR(10),
    LegalEntity         VARCHAR(10),
    ItemGroup           VARCHAR(10),
    Status              VARCHAR(20),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""

# ── ORACLE FUSION ─────────────────────────────────────────────────────────────
schemas['vendors_oracle'] = """
CREATE TABLE IF NOT EXISTS vendors_oracle (
    SupplierNumber      VARCHAR(20) PRIMARY KEY,   -- SUP-XXXXX
    SupplierName        VARCHAR(360),
    SupplierType        VARCHAR(30),               -- SUPPLIER/EMPLOYEE
    TaxOrganizationType VARCHAR(30),               -- INDIVIDUAL/CORPORATION
    TaxRegistrationNumber VARCHAR(30),
    StandardIndustryCode VARCHAR(4),               -- SIC code
    OperatingUnit       VARCHAR(60),
    PaymentTerms        VARCHAR(30),
    PaymentMethod       VARCHAR(30),
    DefaultCurrency     VARCHAR(15),
    CountryOfOrigin     VARCHAR(2),
    City                VARCHAR(60),
    PostalCode          VARCHAR(20),
    Phone               VARCHAR(40),
    Email               VARCHAR(240),
    HoldFlag            VARCHAR(1) DEFAULT 'N',
    EnabledFlag         VARCHAR(1) DEFAULT 'Y',
    CreationDate        DATE,
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['items_oracle'] = """
CREATE TABLE IF NOT EXISTS items_oracle (
    ItemNumber          VARCHAR(40) PRIMARY KEY,
    ItemDescription     VARCHAR(240),
    ItemType            VARCHAR(30),               -- Standard/Kit/Option
    Category            VARCHAR(240),
    UOMCode             VARCHAR(3),
    PurchasingUOM       VARCHAR(3),
    ListPrice           NUMERIC(28,10),
    CurrencyCode        VARCHAR(15),
    ReorderPoint        NUMERIC(28,10),
    SafetyStockQuantity NUMERIC(28,10),
    MinOrderQuantity    NUMERIC(28,10),
    FixedLeadTime       INTEGER,
    BuyerName           VARCHAR(240),
    EnabledFlag         VARCHAR(1) DEFAULT 'Y',
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['po_headers_oracle'] = """
CREATE TABLE IF NOT EXISTS po_headers_oracle (
    PONumber            VARCHAR(20) PRIMARY KEY,   -- US-XXXXX
    POHeaderId          BIGINT,
    POType              VARCHAR(25),               -- STANDARD/BLANKET/CONTRACT
    SupplierNumber      VARCHAR(20),
    SupplierName        VARCHAR(360),
    SupplierSiteCode    VARCHAR(15),
    OrderDate           DATE,
    EffectiveDate       DATE,
    ExpirationDate      DATE,
    CurrencyCode        VARCHAR(15),
    Amount              NUMERIC(28,10),
    Status              VARCHAR(25),               -- OPEN/CLOSED/FINALLY CLOSED
    BuyerName           VARCHAR(240),
    OperatingUnit       VARCHAR(60),
    FreightTerms        VARCHAR(30),
    PaymentTerms        VARCHAR(30),
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['po_lines_oracle'] = """
CREATE TABLE IF NOT EXISTS po_lines_oracle (
    PONumber            VARCHAR(20),
    LineNumber          INTEGER,
    ItemNumber          VARCHAR(40),
    ItemDescription     VARCHAR(240),
    CategoryCode        VARCHAR(240),
    Quantity            NUMERIC(28,10),
    UOMCode             VARCHAR(3),
    UnitPrice           NUMERIC(28,10),
    LineAmount          NUMERIC(28,10),
    TaxCode             VARCHAR(30),
    NeedByDate          DATE,
    QuantityReceived    NUMERIC(28,10) DEFAULT 0,
    QuantityBilled      NUMERIC(28,10) DEFAULT 0,
    LineStatus          VARCHAR(25),
    erp_source          VARCHAR(20) DEFAULT 'oracle',
    PRIMARY KEY (PONumber, LineNumber)
)"""

schemas['grn_headers_oracle'] = """
CREATE TABLE IF NOT EXISTS grn_headers_oracle (
    ReceiptNumber       VARCHAR(20) PRIMARY KEY,
    PONumber            VARCHAR(20),
    SupplierNumber      VARCHAR(20),
    SupplierName        VARCHAR(360),
    ReceiptDate         DATE,
    ReceivedBy          VARCHAR(240),
    ShipmentNumber      VARCHAR(30),
    WaybillNumber       VARCHAR(30),
    OrganizationCode    VARCHAR(3),
    ReceiptStatus       VARCHAR(25) DEFAULT 'DELIVERED',
    TransactionType     VARCHAR(25) DEFAULT 'RECEIVE',
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['invoices_oracle'] = """
CREATE TABLE IF NOT EXISTS invoices_oracle (
    InvoiceNumber       VARCHAR(50) PRIMARY KEY,
    InvoiceId           BIGINT,
    InvoiceType         VARCHAR(25) DEFAULT 'STANDARD',
    SupplierNumber      VARCHAR(20),
    SupplierName        VARCHAR(360),
    SupplierSiteCode    VARCHAR(15),
    InvoiceDate         DATE,
    DueDate             DATE,
    PONumber            VARCHAR(20),
    InvoiceAmount       NUMERIC(28,10),
    TaxAmount           NUMERIC(28,10),
    CurrencyCode        VARCHAR(15),
    PaymentMethod       VARCHAR(30),
    PaymentStatus       VARCHAR(25),   -- UNPAID/PARTIAL/PAID
    Description         VARCHAR(240),
    OperatingUnit       VARCHAR(60),
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

schemas['spend_oracle'] = """
CREATE TABLE IF NOT EXISTS spend_oracle (
    PONumber            VARCHAR(20) PRIMARY KEY,
    SupplierNumber      VARCHAR(20),
    SupplierName        VARCHAR(360),
    OrderDate           DATE,
    Amount              NUMERIC(28,10),
    CurrencyCode        VARCHAR(15),
    Category            VARCHAR(240),
    OperatingUnit       VARCHAR(60),
    CostCenter          VARCHAR(60),
    Status              VARCHAR(25),
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""

# ── ERPNEXT ───────────────────────────────────────────────────────────────────
schemas['vendors_erpnext'] = """
CREATE TABLE IF NOT EXISTS vendors_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- SUP-00XXX
    supplier_name       VARCHAR(140),
    supplier_group      VARCHAR(140),
    supplier_type       VARCHAR(140),              -- Company/Individual
    country             VARCHAR(140),
    default_currency    VARCHAR(3) DEFAULT 'USD',
    payment_terms       VARCHAR(140),
    tax_id              VARCHAR(50),
    is_internal_supplier INTEGER DEFAULT 0,
    on_hold             INTEGER DEFAULT 0,
    hold_type           VARCHAR(140),
    disabled            INTEGER DEFAULT 0,
    mobile_no           VARCHAR(15),
    email_id            VARCHAR(140),
    website             VARCHAR(255),
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

schemas['items_erpnext'] = """
CREATE TABLE IF NOT EXISTS items_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- item code
    item_name           VARCHAR(255),
    item_group          VARCHAR(140),
    description         TEXT,
    stock_uom           VARCHAR(140) DEFAULT 'Nos',
    purchase_uom        VARCHAR(140),
    standard_rate       NUMERIC(21,9) DEFAULT 0,
    valuation_rate      NUMERIC(21,9) DEFAULT 0,
    is_purchase_item    INTEGER DEFAULT 1,
    is_stock_item       INTEGER DEFAULT 1,
    disabled            INTEGER DEFAULT 0,
    min_order_qty       NUMERIC(21,9) DEFAULT 0,
    safety_stock        NUMERIC(21,9) DEFAULT 0,
    reorder_level       NUMERIC(21,9) DEFAULT 0,
    lead_time_days      INTEGER DEFAULT 0,
    item_tax_template   VARCHAR(140),
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

schemas['po_headers_erpnext'] = """
CREATE TABLE IF NOT EXISTS po_headers_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- PUR-ORD-YYYY-XXXXX
    supplier            VARCHAR(140),
    supplier_name       VARCHAR(140),
    transaction_date    DATE,
    schedule_date       DATE,
    currency            VARCHAR(3) DEFAULT 'USD',
    exchange_rate       NUMERIC(9,4) DEFAULT 1,
    net_total           NUMERIC(21,9),
    total_taxes_and_charges NUMERIC(21,9),
    grand_total         NUMERIC(21,9),
    status              VARCHAR(140),  -- Draft/Submitted/Cancelled/Closed
    company             VARCHAR(140),
    buying_price_list   VARCHAR(140),
    payment_terms_template VARCHAR(140),
    set_warehouse       VARCHAR(140),
    amended_from        VARCHAR(140),
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

schemas['po_lines_erpnext'] = """
CREATE TABLE IF NOT EXISTS po_lines_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- row id
    parent              VARCHAR(140),              -- PO name
    idx                 INTEGER,                   -- line number
    item_code           VARCHAR(140),
    item_name           VARCHAR(255),
    description         TEXT,
    qty                 NUMERIC(21,9),
    stock_uom           VARCHAR(140),
    uom                 VARCHAR(140),
    conversion_factor   NUMERIC(9,4) DEFAULT 1,
    rate                NUMERIC(21,9),
    amount              NUMERIC(21,9),
    received_qty        NUMERIC(21,9) DEFAULT 0,
    billed_qty          NUMERIC(21,9) DEFAULT 0,
    warehouse           VARCHAR(140),
    schedule_date       DATE,
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

schemas['grn_headers_erpnext'] = """
CREATE TABLE IF NOT EXISTS grn_headers_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- MAT-PRE-YYYY-XXXXX
    supplier            VARCHAR(140),
    supplier_name       VARCHAR(140),
    posting_date        DATE,
    posting_time        VARCHAR(20),
    purchase_order      VARCHAR(140),
    set_warehouse       VARCHAR(140),
    status              VARCHAR(140) DEFAULT 'Submitted',
    bill_no             VARCHAR(140),
    bill_date           DATE,
    company             VARCHAR(140),
    remarks             TEXT,
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

schemas['invoices_erpnext'] = """
CREATE TABLE IF NOT EXISTS invoices_erpnext (
    name                VARCHAR(140) PRIMARY KEY,  -- ACC-PINV-YYYY-XXXXX
    supplier            VARCHAR(140),
    supplier_name       VARCHAR(140),
    posting_date        DATE,
    due_date            DATE,
    bill_no             VARCHAR(140),              -- vendor invoice number
    bill_date           DATE,
    currency            VARCHAR(3) DEFAULT 'USD',
    conversion_rate     NUMERIC(9,4) DEFAULT 1,
    net_total           NUMERIC(21,9),
    total_taxes_and_charges NUMERIC(21,9),
    grand_total         NUMERIC(21,9),
    outstanding_amount  NUMERIC(21,9),
    status              VARCHAR(140),  -- Draft/Submitted/Paid/Overdue
    company             VARCHAR(140),
    purchase_order      VARCHAR(140),
    remarks             TEXT,
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

schemas['spend_erpnext'] = """
CREATE TABLE IF NOT EXISTS spend_erpnext (
    name                VARCHAR(140) PRIMARY KEY,
    supplier            VARCHAR(140),
    supplier_name       VARCHAR(140),
    transaction_date    DATE,
    grand_total         NUMERIC(21,9),
    currency            VARCHAR(3),
    cost_center         VARCHAR(140),
    project             VARCHAR(140),
    company             VARCHAR(140),
    status              VARCHAR(140),
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTE ALL SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
print("Creating ERP-specific tables...")
for tbl, ddl in schemas.items():
    cur.execute(ddl)
    print(f"  ✓ {tbl}")
conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — SEED DEMO DATA
# ─────────────────────────────────────────────────────────────────────────────
print("\nSeeding demo data...")

# ── ODOO VENDORS ─────────────────────────────────────────────────────────────
cur.execute("DELETE FROM vendors_odoo")
execute_values(cur, """
    INSERT INTO vendors_odoo (name, ref, vat, company_type, street, city, country_id,
        phone, email, property_account_payable_id, property_supplier_payment_term_id,
        supplier_rank, active, currency_id)
    VALUES %s
""", [
    ('Global Tech Supplies LLC',   'VND-001', 'US-98765431',  'company', '123 Tech Blvd',       'San Jose',     'US', '+1-408-555-0101', 'gts@globaltech.com',      '21000', '30 Net',  1, True, 'USD'),
    ('Euro Steel AG',              'VND-002', 'DE-123456789', 'company', 'Stahlstrasse 44',      'Dusseldorf',   'DE', '+49-211-555-0202','info@eurosteel.de',        '21000', '60 Net',  1, True, 'EUR'),
    ('Apex Industrial Components', 'VND-003', 'US-55544433',  'company', '77 Factory Lane',      'Detroit',      'US', '+1-313-555-0303', 'sales@apexind.com',        '21000', '45 Net',  1, True, 'USD'),
    ('EuroStar Office Supplies',   'VND-004', 'GB-987654321', 'company', '10 Kings Road',        'London',       'GB', '+44-20-555-0404', 'orders@eurostar.co.uk',    '21000', '30 Net',  1, True, 'GBP'),
    ('Pak Steel & Raw Materials',  'VND-005', 'PK-112233445', 'company', 'Steel Mill Road 5',   'Karachi',      'PK', '+92-21-555-0505', 'info@paksteel.pk',         '21000', 'Immediate',1,True, 'PKR'),
    ('Sigma Chemicals Ltd',        'VND-006', 'CH-444555666', 'company', 'Chemieweg 12',         'Basel',        'CH', '+41-61-555-0606', 'sigma@chemltd.ch',         '21000', '30 Net',  1, True, 'CHF'),
    ('TechMed Solutions',          'VND-007', 'US-77788899',  'company', '500 Medical Park Dr',  'Boston',       'US', '+1-617-555-0707', 'orders@techmed.com',       '21000', '45 Net',  1, True, 'USD'),
    ('FastLog Logistics',          'VND-008', 'SG-888777666', 'company', '3 Harbour Front Ave',  'Singapore',    'SG', '+65-6555-0808',   'ops@fastlog.sg',           '21000', '15 Net',  1, True, 'SGD'),
    ('Nordic Components AB',       'VND-009', 'SE-999888777', 'company', 'Industrivägen 22',     'Gothenburg',   'SE', '+46-31-555-0909', 'sales@nordic-comp.se',     '21000', '60 Net',  1, True, 'SEK'),
    ('Delta Office Products',      'VND-010', 'CA-111222333', 'company', '88 Commerce St',       'Toronto',      'CA', '+1-416-555-1010', 'delta@officeproducts.ca',  '21000', '30 Net',  1, True, 'CAD'),
    ('Precision Tools Japan',      'VND-011', 'JP-555666777', 'company', '7-1 Minato Mirai',     'Yokohama',     'JP', '+81-45-555-1111', 'export@precisiontool.jp',  '21000', '60 Net',  1, True, 'JPY'),
    ('AusStar Mining Supplies',    'VND-012', 'AU-333444555', 'company', '45 Harbour Parade',    'Perth',        'AU', '+61-8-555-1212',  'orders@aussstar.com.au',   '21000', '30 Net',  1, True, 'AUD'),
])
print("  ✓ vendors_odoo (12 rows)")

# ── SAP S/4HANA VENDORS ───────────────────────────────────────────────────────
cur.execute("DELETE FROM vendors_sap_s4")
execute_values(cur, """
    INSERT INTO vendors_sap_s4 (LIFNR, NAME1, NAME2, LAND1, ORT01, STRAS, TELF1,
        SMTP_ADDR, KTOKK, AKONT, ZTERM, EKGRP, WAERS, BUKRS, EKORG)
    VALUES %s
""", [
    ('0000100001','Global Tech Supplies LLC',  'GTS',         'US','San Jose',    '123 Tech Blvd',        '+14085550101','gts@globaltech.com',      'KRED','160000','NT30','G10','USD','1000','1000'),
    ('0000100002','Euro Steel AG',             'ESA',         'DE','Dusseldorf',  'Stahlstrasse 44',      '+492115550202','info@eurosteel.de',       'KRED','160000','NT60','G20','EUR','1000','1000'),
    ('0000100003','Apex Industrial Components','Apex Ind',    'US','Detroit',     '77 Factory Lane',      '+13135550303','sales@apexind.com',       'KRED','160000','NT45','G10','USD','1000','1000'),
    ('0000100004','EuroStar Office Supplies',  'EuroStar',    'GB','London',      '10 Kings Road',        '+442055550404','orders@eurostar.co.uk',   'KRED','160000','NT30','G30','GBP','1000','1000'),
    ('0000100005','Pak Steel & Raw Materials', 'PakSteel',    'PK','Karachi',     'Steel Mill Road 5',    '+922155550505','info@paksteel.pk',        'KRED','160000','SOFO','G20','PKR','1000','1000'),
    ('0000100006','Sigma Chemicals Ltd',       'Sigma Chem',  'CH','Basel',       'Chemieweg 12',         '+41615550606','sigma@chemltd.ch',        'KRED','160000','NT30','G20','CHF','1000','1000'),
    ('0000100007','TechMed Solutions',         'TechMed',     'US','Boston',      '500 Medical Park Dr',  '+16175550707','orders@techmed.com',      'KRED','160000','NT45','G10','USD','1000','1000'),
    ('0000100008','FastLog Logistics',         'FastLog',     'SG','Singapore',   '3 Harbour Front Ave',  '+6565550808','ops@fastlog.sg',           'KRED','160000','NT15','G40','SGD','1000','1000'),
    ('0000100009','Nordic Components AB',      'Nordic Comp', 'SE','Gothenburg',  'Industrivägen 22',     '+46315550909','sales@nordic-comp.se',    'KRED','160000','NT60','G10','SEK','1000','1000'),
    ('0000100010','Delta Office Products',     'Delta Off',   'CA','Toronto',     '88 Commerce St',       '+14165551010','delta@officeproducts.ca', 'KRED','160000','NT30','G30','CAD','1000','1000'),
    ('0000100011','Precision Tools Japan',     'Precision',   'JP','Yokohama',    '7-1 Minato Mirai',     '+81455551111','export@precisiontool.jp', 'KRED','160000','NT60','G10','JPY','1000','1000'),
    ('0000100012','AusStar Mining Supplies',   'AusStar',     'AU','Perth',       '45 Harbour Parade',    '+6185551212','orders@aussstar.com.au',   'KRED','160000','NT30','G20','AUD','1000','1000'),
])
print("  ✓ vendors_sap_s4 (12 rows)")

# ── SAP B1 VENDORS ────────────────────────────────────────────────────────────
cur.execute("DELETE FROM vendors_sap_b1")
execute_values(cur, """
    INSERT INTO vendors_sap_b1 (CardCode, CardName, CardType, GroupCode, PayTermsGrpCode,
        PeyMethodCode, Country, City, Phone1, E_Mail, Currency, OnHold)
    VALUES %s
""", [
    ('V-GTS001', 'Global Tech Supplies LLC',   'S', 101, 3,  'T',  'US', 'San Jose',    '+14085550101','+1408555','USD','N'),
    ('V-ESA002', 'Euro Steel AG',              'S', 102, 6,  'T',  'DE', 'Dusseldorf',  '+492115550202','info@eurosteel.de','EUR','N'),
    ('V-AIC003', 'Apex Industrial Components', 'S', 102, 4,  'T',  'US', 'Detroit',     '+13135550303','sales@apexind.com','USD','N'),
    ('V-EOS004', 'EuroStar Office Supplies',   'S', 103, 3,  'C',  'GB', 'London',      '+442055550404','orders@eurostar.co.uk','GBP','N'),
    ('V-PSR005', 'Pak Steel & Raw Materials',  'S', 102, 1,  'B',  'PK', 'Karachi',     '+922155550505','info@paksteel.pk','USD','N'),
    ('V-SCL006', 'Sigma Chemicals Ltd',        'S', 104, 3,  'T',  'CH', 'Basel',       '+41615550606','sigma@chemltd.ch','CHF','N'),
    ('V-TMS007', 'TechMed Solutions',          'S', 101, 4,  'T',  'US', 'Boston',      '+16175550707','orders@techmed.com','USD','N'),
    ('V-FLL008', 'FastLog Logistics',          'S', 105, 2,  'T',  'SG', 'Singapore',   '+6565550808','ops@fastlog.sg','SGD','N'),
    ('V-NCA009', 'Nordic Components AB',       'S', 102, 6,  'T',  'SE', 'Gothenburg',  '+46315550909','sales@nordic-comp.se','SEK','N'),
    ('V-DOP010', 'Delta Office Products',      'S', 103, 3,  'C',  'CA', 'Toronto',     '+14165551010','delta@officeproducts.ca','CAD','N'),
    ('V-PTJ011', 'Precision Tools Japan',      'S', 102, 6,  'T',  'JP', 'Yokohama',    '+81455551111','export@precisiontool.jp','JPY','N'),
    ('V-AMS012', 'AusStar Mining Supplies',    'S', 102, 3,  'T',  'AU', 'Perth',       '+6185551212','orders@aussstar.com.au','AUD','N'),
])
print("  ✓ vendors_sap_b1 (12 rows)")

# ── MS DYNAMICS VENDORS ───────────────────────────────────────────────────────
cur.execute("DELETE FROM vendors_dynamics")
execute_values(cur, """
    INSERT INTO vendors_dynamics (VendorAccount, VendorName, VendorGroup, Currency,
        CountryRegion, City, Phone, Email, PaymentTerms, PaymentMethod, PostingProfile,
        TaxGroup, OnHold, BusinessUnit)
    VALUES %s
""", [
    ('V-00001','Global Tech Supplies LLC',   'TECH',  'USD','USA','San Jose',   '+14085550101','gts@globaltech.com',     'Net30','CHK','GEN','ITEM','No', 'BU001'),
    ('V-00002','Euro Steel AG',              'MANUF', 'EUR','DEU','Dusseldorf', '+492115550202','info@eurosteel.de',     'Net60','TRF','GEN','ITEM','No', 'BU002'),
    ('V-00003','Apex Industrial Components', 'MANUF', 'USD','USA','Detroit',    '+13135550303','sales@apexind.com',     'Net45','CHK','GEN','ITEM','No', 'BU001'),
    ('V-00004','EuroStar Office Supplies',   'OFFSUP','GBP','GBR','London',     '+442055550404','orders@eurostar.co.uk', 'Net30','CHK','GEN','ITEM','No', 'BU003'),
    ('V-00005','Pak Steel & Raw Materials',  'MANUF', 'USD','PAK','Karachi',    '+922155550505','info@paksteel.pk',     'Immed','TRF','GEN','ITEM','No', 'BU002'),
    ('V-00006','Sigma Chemicals Ltd',        'CHEM',  'CHF','CHE','Basel',      '+41615550606','sigma@chemltd.ch',      'Net30','TRF','GEN','ITEM','No', 'BU002'),
    ('V-00007','TechMed Solutions',          'MED',   'USD','USA','Boston',     '+16175550707','orders@techmed.com',    'Net45','CHK','GEN','ITEM','No', 'BU001'),
    ('V-00008','FastLog Logistics',          'LOGIS', 'SGD','SGP','Singapore',  '+6565550808','ops@fastlog.sg',         'Net15','TRF','GEN','SRVC','No', 'BU004'),
    ('V-00009','Nordic Components AB',       'MANUF', 'SEK','SWE','Gothenburg', '+46315550909','sales@nordic-comp.se', 'Net60','TRF','GEN','ITEM','No', 'BU002'),
    ('V-00010','Delta Office Products',      'OFFSUP','CAD','CAN','Toronto',    '+14165551010','delta@officeproducts.ca','Net30','CHK','GEN','ITEM','No','BU003'),
    ('V-00011','Precision Tools Japan',      'MANUF', 'JPY','JPN','Yokohama',   '+81455551111','export@precisiontool.jp','Net60','TRF','GEN','ITEM','No','BU002'),
    ('V-00012','AusStar Mining Supplies',    'MINING','AUD','AUS','Perth',      '+6185551212','orders@aussstar.com.au',  'Net30','TRF','GEN','ITEM','No','BU002'),
])
print("  ✓ vendors_dynamics (12 rows)")

# ── ORACLE FUSION VENDORS ─────────────────────────────────────────────────────
cur.execute("DELETE FROM vendors_oracle")
execute_values(cur, """
    INSERT INTO vendors_oracle (SupplierNumber, SupplierName, SupplierType, TaxOrganizationType,
        TaxRegistrationNumber, StandardIndustryCode, OperatingUnit, PaymentTerms,
        PaymentMethod, DefaultCurrency, CountryOfOrigin, City, Phone, Email, EnabledFlag)
    VALUES %s
""", [
    ('SUP-00001','Global Tech Supplies LLC',   'SUPPLIER','CORPORATION','US-98765431','5045','US OU', 'NET30','CHECK','USD','US','San Jose',    '+14085550101','gts@globaltech.com',     'Y'),
    ('SUP-00002','Euro Steel AG',              'SUPPLIER','CORPORATION','DE-123456789','3316','DE OU', 'NET60','WIRE', 'EUR','DE','Dusseldorf','+492115550202','info@eurosteel.de',       'Y'),
    ('SUP-00003','Apex Industrial Components', 'SUPPLIER','CORPORATION','US-55544433', '3490','US OU', 'NET45','CHECK','USD','US','Detroit',    '+13135550303','sales@apexind.com',       'Y'),
    ('SUP-00004','EuroStar Office Supplies',   'SUPPLIER','CORPORATION','GB-987654321','5112','GB OU', 'NET30','CHECK','GBP','GB','London',     '+442055550404','orders@eurostar.co.uk',   'Y'),
    ('SUP-00005','Pak Steel & Raw Materials',  'SUPPLIER','CORPORATION','PK-112233445','3316','PK OU', 'IMMEDIATE','WIRE','USD','PK','Karachi', '+922155550505','info@paksteel.pk',        'Y'),
    ('SUP-00006','Sigma Chemicals Ltd',        'SUPPLIER','CORPORATION','CH-444555666','2869','CH OU', 'NET30','WIRE', 'CHF','CH','Basel',      '+41615550606','sigma@chemltd.ch',         'Y'),
    ('SUP-00007','TechMed Solutions',          'SUPPLIER','CORPORATION','US-77788899', '5047','US OU', 'NET45','CHECK','USD','US','Boston',     '+16175550707','orders@techmed.com',       'Y'),
    ('SUP-00008','FastLog Logistics',          'SUPPLIER','CORPORATION','SG-888777666','4731','SG OU', 'NET15','WIRE', 'SGD','SG','Singapore',  '+6565550808','ops@fastlog.sg',            'Y'),
    ('SUP-00009','Nordic Components AB',       'SUPPLIER','CORPORATION','SE-999888777','3562','SE OU', 'NET60','WIRE', 'SEK','SE','Gothenburg', '+46315550909','sales@nordic-comp.se',     'Y'),
    ('SUP-00010','Delta Office Products',      'SUPPLIER','CORPORATION','CA-111222333','5112','CA OU', 'NET30','CHECK','CAD','CA','Toronto',    '+14165551010','delta@officeproducts.ca',   'Y'),
    ('SUP-00011','Precision Tools Japan',      'SUPPLIER','CORPORATION','JP-555666777','3460','JP OU', 'NET60','WIRE', 'JPY','JP','Yokohama',   '+81455551111','export@precisiontool.jp',   'Y'),
    ('SUP-00012','AusStar Mining Supplies',    'SUPPLIER','CORPORATION','AU-333444555','1040','AU OU', 'NET30','WIRE', 'AUD','AU','Perth',      '+6185551212','orders@aussstar.com.au',     'Y'),
])
print("  ✓ vendors_oracle (12 rows)")

# ── ERPNEXT VENDORS ───────────────────────────────────────────────────────────
cur.execute("DELETE FROM vendors_erpnext")
execute_values(cur, """
    INSERT INTO vendors_erpnext (name, supplier_name, supplier_group, supplier_type,
        country, default_currency, payment_terms, tax_id, on_hold, email_id, mobile_no)
    VALUES %s
""", [
    ('SUP-00001','Global Tech Supplies LLC',   'Technology',     'Company','United States','USD','Net 30', 'US-98765431',0,'gts@globaltech.com',    '+14085550101'),
    ('SUP-00002','Euro Steel AG',              'Raw Materials',  'Company','Germany',      'EUR','Net 60', 'DE-123456789',0,'info@eurosteel.de',     '+492115550202'),
    ('SUP-00003','Apex Industrial Components', 'Manufacturing',  'Company','United States','USD','Net 45', 'US-55544433', 0,'sales@apexind.com',     '+13135550303'),
    ('SUP-00004','EuroStar Office Supplies',   'Office Supplies','Company','United Kingdom','GBP','Net 30','GB-987654321',0,'orders@eurostar.co.uk', '+442055550404'),
    ('SUP-00005','Pak Steel & Raw Materials',  'Raw Materials',  'Company','Pakistan',     'PKR','Immediate','PK-112233445',0,'info@paksteel.pk',   '+922155550505'),
    ('SUP-00006','Sigma Chemicals Ltd',        'Chemicals',      'Company','Switzerland',  'CHF','Net 30', 'CH-444555666',0,'sigma@chemltd.ch',      '+41615550606'),
    ('SUP-00007','TechMed Solutions',          'Medical',        'Company','United States','USD','Net 45', 'US-77788899', 0,'orders@techmed.com',    '+16175550707'),
    ('SUP-00008','FastLog Logistics',          'Services',       'Company','Singapore',    'SGD','Net 15', 'SG-888777666',0,'ops@fastlog.sg',        '+6565550808'),
    ('SUP-00009','Nordic Components AB',       'Manufacturing',  'Company','Sweden',       'SEK','Net 60', 'SE-999888777',0,'sales@nordic-comp.se',  '+46315550909'),
    ('SUP-00010','Delta Office Products',      'Office Supplies','Company','Canada',       'CAD','Net 30', 'CA-111222333',0,'delta@officeproducts.ca','+14165551010'),
    ('SUP-00011','Precision Tools Japan',      'Manufacturing',  'Company','Japan',        'JPY','Net 60', 'JP-555666777',0,'export@precisiontool.jp','+81455551111'),
    ('SUP-00012','AusStar Mining Supplies',    'Raw Materials',  'Company','Australia',    'AUD','Net 30', 'AU-333444555',0,'orders@aussstar.com.au', '+6185551212'),
])
print("  ✓ vendors_erpnext (12 rows)")

# ── PO HEADERS — all 6 ERPs ───────────────────────────────────────────────────
cur.execute("DELETE FROM po_headers_odoo")
execute_values(cur, """
    INSERT INTO po_headers_odoo (name, partner_id, date_order, date_approve,
        currency_id, amount_untaxed, amount_tax, amount_total, state, payment_term_id)
    VALUES %s
""", [
    ('PO00001','Global Tech Supplies LLC',   '2025-01-10','2025-01-11','USD', 45000.00, 6750.00, 51750.00,'purchase','30 Net'),
    ('PO00002','Euro Steel AG',              '2025-01-15','2025-01-16','EUR', 82000.00,12300.00, 94300.00,'purchase','60 Net'),
    ('PO00003','Apex Industrial Components', '2025-01-20','2025-01-21','USD', 31500.00, 4725.00, 36225.00,'purchase','45 Net'),
    ('PO00004','EuroStar Office Supplies',   '2025-02-01','2025-02-02','GBP', 12000.00, 1800.00, 13800.00,'purchase','30 Net'),
    ('PO00005','Sigma Chemicals Ltd',        '2025-02-10','2025-02-11','CHF', 67000.00,10050.00, 77050.00,'purchase','30 Net'),
    ('PO00006','TechMed Solutions',          '2025-02-15','2025-02-16','USD', 95000.00,14250.00,109250.00,'purchase','45 Net'),
    ('PO00007','FastLog Logistics',          '2025-03-01','2025-03-02','SGD', 18000.00, 2700.00, 20700.00,'purchase','15 Net'),
    ('PO00008','Nordic Components AB',       '2025-03-10','2025-03-11','SEK',120000.00,18000.00,138000.00,'done',   '60 Net'),
    ('PO00009','Delta Office Products',      '2025-03-15','2025-03-16','CAD', 22000.00, 3300.00, 25300.00,'done',   '30 Net'),
    ('PO00010','Pak Steel & Raw Materials',  '2025-04-01','2025-04-02','USD',155000.00,23250.00,178250.00,'purchase','Immediate'),
])
print("  ✓ po_headers_odoo (10 rows)")

cur.execute("DELETE FROM po_headers_sap_s4")
execute_values(cur, """
    INSERT INTO po_headers_sap_s4 (EBELN, BUKRS, BSART, LIFNR, EKORG, EKGRP,
        BEDAT, WAERS, NETWR, ZTERM, INCO1, STATU)
    VALUES %s
""", [
    ('4500000001','1000','NB','0000100001','1000','G10','2025-01-10','USD', 45000.00,'NT30','FOB','A'),
    ('4500000002','1000','NB','0000100002','1000','G20','2025-01-15','EUR', 82000.00,'NT60','CIF','A'),
    ('4500000003','1000','NB','0000100003','1000','G10','2025-01-20','USD', 31500.00,'NT45','FOB','A'),
    ('4500000004','1000','NB','0000100004','1000','G30','2025-02-01','GBP', 12000.00,'NT30','DAP','A'),
    ('4500000005','1000','NB','0000100006','1000','G20','2025-02-10','CHF', 67000.00,'NT30','CIF','A'),
    ('4500000006','1000','NB','0000100007','1000','G10','2025-02-15','USD', 95000.00,'NT45','FOB','A'),
    ('4500000007','1000','NB','0000100008','1000','G40','2025-03-01','SGD', 18000.00,'NT15','EXW','A'),
    ('4500000008','1000','NB','0000100009','1000','G10','2025-03-10','SEK',120000.00,'NT60','DAP','L'),
    ('4500000009','1000','NB','0000100010','1000','G30','2025-03-15','CAD', 22000.00,'NT30','FOB','L'),
    ('4500000010','1000','NB','0000100005','1000','G20','2025-04-01','USD',155000.00,'SOFO','CFR','A'),
])
print("  ✓ po_headers_sap_s4 (10 rows)")

cur.execute("DELETE FROM po_headers_sap_b1")
execute_values(cur, """
    INSERT INTO po_headers_sap_b1 (DocNum, DocDate, DocDueDate, CardCode, CardName,
        NumAtCard, DocTotal, VatSum, DocCurrency, DocStatus)
    VALUES %s
""", [
    (10001,'2025-01-10','2025-02-10','V-GTS001','Global Tech Supplies LLC',  'GTS-PO-001', 51750.00, 6750.00,'USD','O'),
    (10002,'2025-01-15','2025-03-15','V-ESA002','Euro Steel AG',             'ESA-PO-002', 94300.00,12300.00,'EUR','O'),
    (10003,'2025-01-20','2025-03-05','V-AIC003','Apex Industrial Components','AIC-PO-003', 36225.00, 4725.00,'USD','O'),
    (10004,'2025-02-01','2025-03-01','V-EOS004','EuroStar Office Supplies',  'EOS-PO-004', 13800.00, 1800.00,'GBP','O'),
    (10005,'2025-02-10','2025-03-10','V-SCL006','Sigma Chemicals Ltd',       'SCL-PO-005', 77050.00,10050.00,'CHF','O'),
    (10006,'2025-02-15','2025-03-30','V-TMS007','TechMed Solutions',         'TMS-PO-006',109250.00,14250.00,'USD','O'),
    (10007,'2025-03-01','2025-03-16','V-FLL008','FastLog Logistics',         'FLL-PO-007', 20700.00, 2700.00,'SGD','C'),
    (10008,'2025-03-10','2025-05-08','V-NCA009','Nordic Components AB',      'NCA-PO-008',138000.00,18000.00,'SEK','C'),
    (10009,'2025-03-15','2025-04-14','V-DOP010','Delta Office Products',     'DOP-PO-009', 25300.00, 3300.00,'CAD','C'),
    (10010,'2025-04-01','2025-04-08','V-PSR005','Pak Steel & Raw Materials', 'PSR-PO-010',178250.00,23250.00,'USD','O'),
])
print("  ✓ po_headers_sap_b1 (10 rows)")

cur.execute("DELETE FROM po_headers_dynamics")
execute_values(cur, """
    INSERT INTO po_headers_dynamics (PurchaseOrderNumber, PurchaseOrderName,
        VendorAccountNumber, VendorName, OrderDate, DeliveryDate, CurrencyCode,
        TotalAmount, TaxAmount, PaymentTerms, PurchasingAgent, Status, LegalEntity)
    VALUES %s
""", [
    ('PO-000001','Technology Hardware Order',   'V-00001','Global Tech Supplies LLC',   '2025-01-10','2025-02-10','USD', 51750.00, 6750.00,'Net30','J.Smith',  'Confirmed','CORP'),
    ('PO-000002','Structural Steel Supply',     'V-00002','Euro Steel AG',              '2025-01-15','2025-03-15','EUR', 94300.00,12300.00,'Net60','M.Johnson','Confirmed','CORP'),
    ('PO-000003','Industrial Components Q1',    'V-00003','Apex Industrial Components', '2025-01-20','2025-03-05','USD', 36225.00, 4725.00,'Net45','K.Williams','Confirmed','CORP'),
    ('PO-000004','Office Supplies Restock',     'V-00004','EuroStar Office Supplies',   '2025-02-01','2025-03-01','GBP', 13800.00, 1800.00,'Net30','J.Smith',  'Confirmed','CORP'),
    ('PO-000005','Chemical Raw Materials',      'V-00006','Sigma Chemicals Ltd',        '2025-02-10','2025-03-10','CHF', 77050.00,10050.00,'Net30','M.Johnson','Confirmed','CORP'),
    ('PO-000006','Medical Equipment Procurement','V-00007','TechMed Solutions',         '2025-02-15','2025-03-30','USD',109250.00,14250.00,'Net45','K.Williams','Received', 'CORP'),
    ('PO-000007','Logistics Services Feb',      'V-00008','FastLog Logistics',          '2025-03-01','2025-03-16','SGD', 20700.00, 2700.00,'Net15','J.Smith',  'Invoiced', 'CORP'),
    ('PO-000008','Nordic Machine Components',   'V-00009','Nordic Components AB',       '2025-03-10','2025-05-08','SEK',138000.00,18000.00,'Net60','M.Johnson','Closed',   'CORP'),
    ('PO-000009','Canadian Office Products',    'V-00010','Delta Office Products',      '2025-03-15','2025-04-14','CAD', 25300.00, 3300.00,'Net30','K.Williams','Closed',   'CORP'),
    ('PO-000010','Steel Raw Material April',    'V-00005','Pak Steel & Raw Materials',  '2025-04-01','2025-04-08','USD',178250.00,23250.00,'Immediate','J.Smith','Confirmed','CORP'),
])
print("  ✓ po_headers_dynamics (10 rows)")

cur.execute("DELETE FROM po_headers_oracle")
execute_values(cur, """
    INSERT INTO po_headers_oracle (PONumber, POHeaderId, POType, SupplierNumber,
        SupplierName, SupplierSiteCode, OrderDate, CurrencyCode, Amount,
        Status, BuyerName, OperatingUnit, PaymentTerms)
    VALUES %s
""", [
    ('US-10001',1001,'STANDARD','SUP-00001','Global Tech Supplies LLC',   'US-MAIN','2025-01-10','USD', 51750.00,'OPEN',          'John Smith',   'US OU','NET30'),
    ('US-10002',1002,'STANDARD','SUP-00002','Euro Steel AG',              'DE-MAIN','2025-01-15','EUR', 94300.00,'OPEN',          'Mary Johnson', 'DE OU','NET60'),
    ('US-10003',1003,'STANDARD','SUP-00003','Apex Industrial Components', 'US-MAIN','2025-01-20','USD', 36225.00,'OPEN',          'Kate Williams','US OU','NET45'),
    ('US-10004',1004,'STANDARD','SUP-00004','EuroStar Office Supplies',   'GB-MAIN','2025-02-01','GBP', 13800.00,'OPEN',          'John Smith',   'GB OU','NET30'),
    ('US-10005',1005,'STANDARD','SUP-00006','Sigma Chemicals Ltd',        'CH-MAIN','2025-02-10','CHF', 77050.00,'OPEN',          'Mary Johnson', 'CH OU','NET30'),
    ('US-10006',1006,'STANDARD','SUP-00007','TechMed Solutions',          'US-MAIN','2025-02-15','USD',109250.00,'OPEN',          'Kate Williams','US OU','NET45'),
    ('US-10007',1007,'STANDARD','SUP-00008','FastLog Logistics',          'SG-MAIN','2025-03-01','SGD', 20700.00,'CLOSED',        'John Smith',   'SG OU','NET15'),
    ('US-10008',1008,'STANDARD','SUP-00009','Nordic Components AB',       'SE-MAIN','2025-03-10','SEK',138000.00,'FINALLY CLOSED','Mary Johnson', 'SE OU','NET60'),
    ('US-10009',1009,'STANDARD','SUP-00010','Delta Office Products',      'CA-MAIN','2025-03-15','CAD', 25300.00,'FINALLY CLOSED','Kate Williams','CA OU','NET30'),
    ('US-10010',1010,'STANDARD','SUP-00005','Pak Steel & Raw Materials',  'PK-MAIN','2025-04-01','USD',178250.00,'OPEN',          'John Smith',   'PK OU','IMMEDIATE'),
])
print("  ✓ po_headers_oracle (10 rows)")

cur.execute("DELETE FROM po_headers_erpnext")
execute_values(cur, """
    INSERT INTO po_headers_erpnext (name, supplier, supplier_name, transaction_date,
        schedule_date, currency, net_total, total_taxes_and_charges, grand_total,
        status, company, payment_terms_template)
    VALUES %s
""", [
    ('PUR-ORD-2025-00001','SUP-00001','Global Tech Supplies LLC',   '2025-01-10','2025-02-10','USD', 45000.00, 6750.00, 51750.00,'Submitted','NMI Industries','Net 30'),
    ('PUR-ORD-2025-00002','SUP-00002','Euro Steel AG',              '2025-01-15','2025-03-15','EUR', 82000.00,12300.00, 94300.00,'Submitted','NMI Industries','Net 60'),
    ('PUR-ORD-2025-00003','SUP-00003','Apex Industrial Components', '2025-01-20','2025-03-05','USD', 31500.00, 4725.00, 36225.00,'Submitted','NMI Industries','Net 45'),
    ('PUR-ORD-2025-00004','SUP-00004','EuroStar Office Supplies',   '2025-02-01','2025-03-01','GBP', 12000.00, 1800.00, 13800.00,'Submitted','NMI Industries','Net 30'),
    ('PUR-ORD-2025-00005','SUP-00006','Sigma Chemicals Ltd',        '2025-02-10','2025-03-10','CHF', 67000.00,10050.00, 77050.00,'Submitted','NMI Industries','Net 30'),
    ('PUR-ORD-2025-00006','SUP-00007','TechMed Solutions',          '2025-02-15','2025-03-30','USD', 95000.00,14250.00,109250.00,'Submitted','NMI Industries','Net 45'),
    ('PUR-ORD-2025-00007','SUP-00008','FastLog Logistics',          '2025-03-01','2025-03-16','SGD', 18000.00, 2700.00, 20700.00,'Closed',   'NMI Industries','Net 15'),
    ('PUR-ORD-2025-00008','SUP-00009','Nordic Components AB',       '2025-03-10','2025-05-08','SEK',120000.00,18000.00,138000.00,'Closed',   'NMI Industries','Net 60'),
    ('PUR-ORD-2025-00009','SUP-00010','Delta Office Products',      '2025-03-15','2025-04-14','CAD', 22000.00, 3300.00, 25300.00,'Closed',   'NMI Industries','Net 30'),
    ('PUR-ORD-2025-00010','SUP-00005','Pak Steel & Raw Materials',  '2025-04-01','2025-04-08','USD',155000.00,23250.00,178250.00,'Submitted','NMI Industries','Immediate'),
])
print("  ✓ po_headers_erpnext (10 rows)")

# ── INVOICES — all 6 ERPs ─────────────────────────────────────────────────────
cur.execute("DELETE FROM invoices_odoo")
execute_values(cur, """
    INSERT INTO invoices_odoo (name, partner_id, invoice_date, invoice_date_due,
        ref, invoice_origin, amount_untaxed, amount_tax, amount_total,
        amount_residual, currency_id, state, payment_state)
    VALUES %s
""", [
    ('BILL/2025/00001','Global Tech Supplies LLC',   '2025-01-20','2025-02-19','GTS-INV-2025-0101','PO00001', 45000.00, 6750.00, 51750.00, 51750.00,'USD','posted','not_paid'),
    ('BILL/2025/00002','Euro Steel AG',              '2025-01-28','2025-03-28','ESA-INV-2025-0201','PO00002', 82000.00,12300.00, 94300.00, 94300.00,'EUR','posted','not_paid'),
    ('BILL/2025/00003','Apex Industrial Components', '2025-02-05','2025-03-22','AIC-INV-2025-0301','PO00003', 31500.00, 4725.00, 36225.00,     0.00,'USD','posted','paid'),
    ('BILL/2025/00004','EuroStar Office Supplies',   '2025-02-10','2025-03-12','EOS-INV-2025-0401','PO00004', 12000.00, 1800.00, 13800.00,     0.00,'GBP','posted','paid'),
    ('BILL/2025/00005','Sigma Chemicals Ltd',        '2025-02-18','2025-03-20','SCL-INV-2025-0501','PO00005', 67000.00,10050.00, 77050.00, 77050.00,'CHF','posted','not_paid'),
    ('BILL/2025/00006','TechMed Solutions',          '2025-02-25','2025-04-11','TMS-INV-2025-0601','PO00006', 95000.00,14250.00,109250.00,109250.00,'USD','posted','not_paid'),
    ('BILL/2025/00007','FastLog Logistics',          '2025-03-08','2025-03-23','FLL-INV-2025-0701','PO00007', 18000.00, 2700.00, 20700.00,     0.00,'SGD','posted','paid'),
    ('BILL/2025/00008','Nordic Components AB',       '2025-03-18','2025-05-16','NCA-INV-2025-0801','PO00008',120000.00,18000.00,138000.00,     0.00,'SEK','posted','paid'),
    ('BILL/2025/00009','Delta Office Products',      '2025-03-22','2025-04-21','DOP-INV-2025-0901','PO00009', 22000.00, 3300.00, 25300.00, 25300.00,'CAD','posted','not_paid'),
    ('BILL/2025/00010','Pak Steel & Raw Materials',  '2025-04-05','2025-04-05','PSR-INV-2025-1001','PO00010',155000.00,23250.00,178250.00,178250.00,'USD','posted','not_paid'),
])
print("  ✓ invoices_odoo (10 rows)")

cur.execute("DELETE FROM invoices_sap_s4")
execute_values(cur, """
    INSERT INTO invoices_sap_s4 (BELNR, BUKRS, GJAHR, BLART, BLDAT, BUDAT,
        LIFNR, XBLNR, WRBTR, WAERS, ZFBDT, ZTERM, EBELN)
    VALUES %s
""", [
    ('5100000001','1000','2025','RE','2025-01-20','2025-01-21','0000100001','GTS-INV-2025-0101', 51750.00,'USD','2025-02-19','NT30','4500000001'),
    ('5100000002','1000','2025','RE','2025-01-28','2025-01-29','0000100002','ESA-INV-2025-0201', 94300.00,'EUR','2025-03-28','NT60','4500000002'),
    ('5100000003','1000','2025','RE','2025-02-05','2025-02-06','0000100003','AIC-INV-2025-0301', 36225.00,'USD','2025-03-22','NT45','4500000003'),
    ('5100000004','1000','2025','RE','2025-02-10','2025-02-11','0000100004','EOS-INV-2025-0401', 13800.00,'GBP','2025-03-12','NT30','4500000004'),
    ('5100000005','1000','2025','RE','2025-02-18','2025-02-19','0000100006','SCL-INV-2025-0501', 77050.00,'CHF','2025-03-20','NT30','4500000005'),
    ('5100000006','1000','2025','RE','2025-02-25','2025-02-26','0000100007','TMS-INV-2025-0601',109250.00,'USD','2025-04-11','NT45','4500000006'),
    ('5100000007','1000','2025','RE','2025-03-08','2025-03-09','0000100008','FLL-INV-2025-0701', 20700.00,'SGD','2025-03-23','NT15','4500000007'),
    ('5100000008','1000','2025','RE','2025-03-18','2025-03-19','0000100009','NCA-INV-2025-0801',138000.00,'SEK','2025-05-16','NT60','4500000008'),
    ('5100000009','1000','2025','RE','2025-03-22','2025-03-23','0000100010','DOP-INV-2025-0901', 25300.00,'CAD','2025-04-21','NT30','4500000009'),
    ('5100000010','1000','2025','RE','2025-04-05','2025-04-05','0000100005','PSR-INV-2025-1001',178250.00,'USD','2025-04-05','SOFO','4500000010'),
])
print("  ✓ invoices_sap_s4 (10 rows)")

cur.execute("DELETE FROM invoices_sap_b1")
execute_values(cur, """
    INSERT INTO invoices_sap_b1 (DocNum, DocDate, DocDueDate, CardCode, CardName,
        NumAtCard, DocTotal, VatSum, DocCurrency, BaseRef, DocStatus)
    VALUES %s
""", [
    (20001,'2025-01-20','2025-02-19','V-GTS001','Global Tech Supplies LLC',   'GTS-INV-2025-0101', 51750.00, 6750.00,'USD','10001','O'),
    (20002,'2025-01-28','2025-03-28','V-ESA002','Euro Steel AG',              'ESA-INV-2025-0201', 94300.00,12300.00,'EUR','10002','O'),
    (20003,'2025-02-05','2025-03-22','V-AIC003','Apex Industrial Components', 'AIC-INV-2025-0301', 36225.00, 4725.00,'USD','10003','C'),
    (20004,'2025-02-10','2025-03-12','V-EOS004','EuroStar Office Supplies',   'EOS-INV-2025-0401', 13800.00, 1800.00,'GBP','10004','C'),
    (20005,'2025-02-18','2025-03-20','V-SCL006','Sigma Chemicals Ltd',        'SCL-INV-2025-0501', 77050.00,10050.00,'CHF','10005','O'),
    (20006,'2025-02-25','2025-04-11','V-TMS007','TechMed Solutions',          'TMS-INV-2025-0601',109250.00,14250.00,'USD','10006','O'),
    (20007,'2025-03-08','2025-03-23','V-FLL008','FastLog Logistics',          'FLL-INV-2025-0701', 20700.00, 2700.00,'SGD','10007','C'),
    (20008,'2025-03-18','2025-05-16','V-NCA009','Nordic Components AB',       'NCA-INV-2025-0801',138000.00,18000.00,'SEK','10008','C'),
    (20009,'2025-03-22','2025-04-21','V-DOP010','Delta Office Products',      'DOP-INV-2025-0901', 25300.00, 3300.00,'CAD','10009','O'),
    (20010,'2025-04-05','2025-04-05','V-PSR005','Pak Steel & Raw Materials',  'PSR-INV-2025-1001',178250.00,23250.00,'USD','10010','O'),
])
print("  ✓ invoices_sap_b1 (10 rows)")

cur.execute("DELETE FROM invoices_dynamics")
execute_values(cur, """
    INSERT INTO invoices_dynamics (VendorInvoiceNumber, InvoiceDescription,
        VendorAccountNumber, VendorName, InvoiceDate, DueDate, PurchaseOrderNumber,
        TotalAmount, TaxAmount, CurrencyCode, PaymentTerms, Status)
    VALUES %s
""", [
    ('GTS-INV-2025-0101','Technology Hardware Invoice',   'V-00001','Global Tech Supplies LLC',   '2025-01-20','2025-02-19','PO-000001', 51750.00, 6750.00,'USD','Net30','Pending'),
    ('ESA-INV-2025-0201','Structural Steel Invoice',      'V-00002','Euro Steel AG',              '2025-01-28','2025-03-28','PO-000002', 94300.00,12300.00,'EUR','Net60','Pending'),
    ('AIC-INV-2025-0301','Industrial Components Invoice', 'V-00003','Apex Industrial Components', '2025-02-05','2025-03-22','PO-000003', 36225.00, 4725.00,'USD','Net45','Paid'),
    ('EOS-INV-2025-0401','Office Supplies Invoice',       'V-00004','EuroStar Office Supplies',   '2025-02-10','2025-03-12','PO-000004', 13800.00, 1800.00,'GBP','Net30','Paid'),
    ('SCL-INV-2025-0501','Chemical Materials Invoice',    'V-00006','Sigma Chemicals Ltd',        '2025-02-18','2025-03-20','PO-000005', 77050.00,10050.00,'CHF','Net30','Pending'),
    ('TMS-INV-2025-0601','Medical Equipment Invoice',     'V-00007','TechMed Solutions',          '2025-02-25','2025-04-11','PO-000006',109250.00,14250.00,'USD','Net45','Pending'),
    ('FLL-INV-2025-0701','Logistics Services Invoice',    'V-00008','FastLog Logistics',          '2025-03-08','2025-03-23','PO-000007', 20700.00, 2700.00,'SGD','Net15','Paid'),
    ('NCA-INV-2025-0801','Nordic Components Invoice',     'V-00009','Nordic Components AB',       '2025-03-18','2025-05-16','PO-000008',138000.00,18000.00,'SEK','Net60','Paid'),
    ('DOP-INV-2025-0901','Canadian Office Products Inv',  'V-00010','Delta Office Products',      '2025-03-22','2025-04-21','PO-000009', 25300.00, 3300.00,'CAD','Net30','Pending'),
    ('PSR-INV-2025-1001','Steel Raw Materials Invoice',   'V-00005','Pak Steel & Raw Materials',  '2025-04-05','2025-04-05','PO-000010',178250.00,23250.00,'USD','Immediate','Pending'),
])
print("  ✓ invoices_dynamics (10 rows)")

cur.execute("DELETE FROM invoices_oracle")
execute_values(cur, """
    INSERT INTO invoices_oracle (InvoiceNumber, InvoiceId, SupplierNumber, SupplierName,
        SupplierSiteCode, InvoiceDate, DueDate, PONumber, InvoiceAmount, TaxAmount,
        CurrencyCode, PaymentStatus, OperatingUnit)
    VALUES %s
""", [
    ('GTS-INV-2025-0101',2001,'SUP-00001','Global Tech Supplies LLC',   'US-MAIN','2025-01-20','2025-02-19','US-10001', 51750.00, 6750.00,'USD','UNPAID', 'US OU'),
    ('ESA-INV-2025-0201',2002,'SUP-00002','Euro Steel AG',              'DE-MAIN','2025-01-28','2025-03-28','US-10002', 94300.00,12300.00,'EUR','UNPAID', 'DE OU'),
    ('AIC-INV-2025-0301',2003,'SUP-00003','Apex Industrial Components', 'US-MAIN','2025-02-05','2025-03-22','US-10003', 36225.00, 4725.00,'USD','PAID',   'US OU'),
    ('EOS-INV-2025-0401',2004,'SUP-00004','EuroStar Office Supplies',   'GB-MAIN','2025-02-10','2025-03-12','US-10004', 13800.00, 1800.00,'GBP','PAID',   'GB OU'),
    ('SCL-INV-2025-0501',2005,'SUP-00006','Sigma Chemicals Ltd',        'CH-MAIN','2025-02-18','2025-03-20','US-10005', 77050.00,10050.00,'CHF','UNPAID', 'CH OU'),
    ('TMS-INV-2025-0601',2006,'SUP-00007','TechMed Solutions',          'US-MAIN','2025-02-25','2025-04-11','US-10006',109250.00,14250.00,'USD','UNPAID', 'US OU'),
    ('FLL-INV-2025-0701',2007,'SUP-00008','FastLog Logistics',          'SG-MAIN','2025-03-08','2025-03-23','US-10007', 20700.00, 2700.00,'SGD','PAID',   'SG OU'),
    ('NCA-INV-2025-0801',2008,'SUP-00009','Nordic Components AB',       'SE-MAIN','2025-03-18','2025-05-16','US-10008',138000.00,18000.00,'SEK','PAID',   'SE OU'),
    ('DOP-INV-2025-0901',2009,'SUP-00010','Delta Office Products',      'CA-MAIN','2025-03-22','2025-04-21','US-10009', 25300.00, 3300.00,'CAD','UNPAID', 'CA OU'),
    ('PSR-INV-2025-1001',2010,'SUP-00005','Pak Steel & Raw Materials',  'PK-MAIN','2025-04-05','2025-04-05','US-10010',178250.00,23250.00,'USD','UNPAID', 'PK OU'),
])
print("  ✓ invoices_oracle (10 rows)")

cur.execute("DELETE FROM invoices_erpnext")
execute_values(cur, """
    INSERT INTO invoices_erpnext (name, supplier, supplier_name, posting_date,
        due_date, bill_no, currency, net_total, total_taxes_and_charges,
        grand_total, outstanding_amount, status, company, purchase_order)
    VALUES %s
""", [
    ('ACC-PINV-2025-00001','SUP-00001','Global Tech Supplies LLC',   '2025-01-20','2025-02-19','GTS-INV-2025-0101','USD', 45000.00, 6750.00, 51750.00, 51750.00,'Unpaid',  'NMI Industries','PUR-ORD-2025-00001'),
    ('ACC-PINV-2025-00002','SUP-00002','Euro Steel AG',              '2025-01-28','2025-03-28','ESA-INV-2025-0201','EUR', 82000.00,12300.00, 94300.00, 94300.00,'Unpaid',  'NMI Industries','PUR-ORD-2025-00002'),
    ('ACC-PINV-2025-00003','SUP-00003','Apex Industrial Components', '2025-02-05','2025-03-22','AIC-INV-2025-0301','USD', 31500.00, 4725.00, 36225.00,     0.00,'Paid',    'NMI Industries','PUR-ORD-2025-00003'),
    ('ACC-PINV-2025-00004','SUP-00004','EuroStar Office Supplies',   '2025-02-10','2025-03-12','EOS-INV-2025-0401','GBP', 12000.00, 1800.00, 13800.00,     0.00,'Paid',    'NMI Industries','PUR-ORD-2025-00004'),
    ('ACC-PINV-2025-00005','SUP-00006','Sigma Chemicals Ltd',        '2025-02-18','2025-03-20','SCL-INV-2025-0501','CHF', 67000.00,10050.00, 77050.00, 77050.00,'Unpaid',  'NMI Industries','PUR-ORD-2025-00005'),
    ('ACC-PINV-2025-00006','SUP-00007','TechMed Solutions',          '2025-02-25','2025-04-11','TMS-INV-2025-0601','USD', 95000.00,14250.00,109250.00,109250.00,'Unpaid',  'NMI Industries','PUR-ORD-2025-00006'),
    ('ACC-PINV-2025-00007','SUP-00008','FastLog Logistics',          '2025-03-08','2025-03-23','FLL-INV-2025-0701','SGD', 18000.00, 2700.00, 20700.00,     0.00,'Paid',    'NMI Industries','PUR-ORD-2025-00007'),
    ('ACC-PINV-2025-00008','SUP-00009','Nordic Components AB',       '2025-03-18','2025-05-16','NCA-INV-2025-0801','SEK',120000.00,18000.00,138000.00,     0.00,'Paid',    'NMI Industries','PUR-ORD-2025-00008'),
    ('ACC-PINV-2025-00009','SUP-00010','Delta Office Products',      '2025-03-22','2025-04-21','DOP-INV-2025-0901','CAD', 22000.00, 3300.00, 25300.00, 25300.00,'Unpaid',  'NMI Industries','PUR-ORD-2025-00009'),
    ('ACC-PINV-2025-00010','SUP-00005','Pak Steel & Raw Materials',  '2025-04-05','2025-04-05','PSR-INV-2025-1001','USD',155000.00,23250.00,178250.00,178250.00,'Overdue', 'NMI Industries','PUR-ORD-2025-00010'),
])
print("  ✓ invoices_erpnext (10 rows)")

conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — UPDATE TABLE REGISTRY WITH ERP SOURCE
# ─────────────────────────────────────────────────────────────────────────────
print("\nUpdating table_registry...")

erp_registry_rows = []
erp_map = {
    'odoo':     ('Odoo ERP',          'odoo'),
    'sap_s4':   ('SAP S/4HANA',       'sap_s4'),
    'sap_b1':   ('SAP Business One',  'sap_b1'),
    'dynamics': ('MS Dynamics 365',   'dynamics'),
    'oracle':   ('Oracle Fusion',     'oracle'),
    'erpnext':  ('ERPNext',           'erpnext'),
}
table_meta = {
    'vendors':    ('Master Data',    'MDM', 'master',        'Vendor master'),
    'items':      ('Master Data',    'MDM', 'master',        'Item/product catalog'),
    'po_headers': ('Purchase Orders','P2P', 'transactional', 'Purchase order headers'),
    'po_lines':   ('Purchase Orders','P2P', 'transactional', 'Purchase order line items'),
    'grn_headers':('Warehouse',      'WMS', 'transactional', 'Goods receipt notes'),
    'invoices':   ('Accounts Payable','AP', 'transactional', 'Vendor invoices'),
    'spend':      ('Finance',        'FIN', 'transactional', 'Spend analytics'),
}
odoo_models = {
    'vendors':'res.partner','items':'product.product','po_headers':'purchase.order',
    'po_lines':'purchase.order.line','grn_headers':'stock.picking',
    'invoices':'account.move','spend':'purchase.order',
}
sap_objects = {
    'vendors':'LFA1','items':'MARA','po_headers':'EKKO','po_lines':'EKPO',
    'grn_headers':'MKPF','invoices':'RBKPV','spend':'EKKO',
}
netsuite_types = {
    'vendors':'vendor','items':'inventoryItem','po_headers':'purchaseOrder',
    'po_lines':'purchaseOrderItem','grn_headers':'itemReceipt',
    'invoices':'vendorBill','spend':'purchaseOrder',
}

for base_table, (module, mod_code, tbl_type, desc) in table_meta.items():
    for erp_code, (erp_label, erp_col) in erp_map.items():
        erp_table = f"{base_table}_{erp_code}"
        erp_registry_rows.append((
            erp_table, module, mod_code, tbl_type,
            f"{desc} — {erp_label} format",
            odoo_models.get(base_table), 'id',
            sap_objects.get(base_table), 'ID',
            netsuite_types.get(base_table), 'internalId',
            f"get_{base_table}",
            erp_col, erp_table
        ))

cur.execute("DELETE FROM table_registry WHERE erp_source != 'all'")
cur.executemany("""
    INSERT INTO table_registry
        (table_name, module, module_code, table_type, description,
         odoo_model, odoo_key_field, sap_object, sap_key_field,
         netsuite_type, netsuite_key_field, adapter_method,
         erp_source, erp_table_name)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
""", erp_registry_rows)
conn.commit()
print(f"  ✓ Added {len(erp_registry_rows)} ERP-specific rows to table_registry")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
cur.execute("SELECT COUNT(*) FROM table_registry")
total = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM table_registry WHERE erp_source != 'all'")
erp_specific = cur.fetchone()[0]
cur.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema='public' AND (
        table_name LIKE '%_odoo' OR table_name LIKE '%_sap_s4' OR
        table_name LIKE '%_sap_b1' OR table_name LIKE '%_dynamics' OR
        table_name LIKE '%_oracle' OR table_name LIKE '%_erpnext'
    ) ORDER BY table_name
""")
erp_tables = [r[0] for r in cur.fetchall()]

print(f"\n{'='*60}")
print(f"SPRINT 5 MIGRATION COMPLETE")
print(f"{'='*60}")
print(f"ERP-specific tables created : {len(erp_tables)}")
print(f"Table registry total rows   : {total} ({erp_specific} ERP-specific)")
print(f"\nTables by ERP:")
for erp in ['odoo','sap_s4','sap_b1','dynamics','oracle','erpnext']:
    count = sum(1 for t in erp_tables if t.endswith(f'_{erp}'))
    print(f"  {erp:12s}: {count} tables")

cur.close()
conn.close()
