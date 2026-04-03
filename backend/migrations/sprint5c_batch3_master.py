"""
Sprint 5C Batch 3 — Cost Centers, Payment Terms, Exchange Rates, Warehouses
6 ERPs × 4 modules = 24 tables
"""
import os, sys
os.chdir("E:/procure AI/Procure-AI"); sys.path.insert(0, ".")
import psycopg2
from psycopg2.extras import execute_values
conn = psycopg2.connect("postgresql://postgres:YourStr0ng!Pass@localhost:5433/odoo_procurement_demo")
cur  = conn.cursor()
ERPS = ['odoo','sap_s4','sap_b1','dynamics','oracle','erpnext']

schemas = {}

# ── cost_centers ──────────────────────────────────────────────────────────────
schemas['cost_centers_odoo'] = """
CREATE TABLE IF NOT EXISTS cost_centers_odoo (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200),         -- Analytic account name
    code        VARCHAR(64),          -- CC-001
    group_id    VARCHAR(100),
    company_id  VARCHAR(100) DEFAULT 'Procure-AI Demo',
    partner_id  VARCHAR(100),
    active      BOOLEAN DEFAULT TRUE,
    erp_source  VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['cost_centers_sap_s4'] = """
CREATE TABLE IF NOT EXISTS cost_centers_sap_s4 (
    KOSTL   VARCHAR(10) PRIMARY KEY,   -- cost center
    KOKRS   VARCHAR(4) DEFAULT '1000', -- controlling area
    KTEXT   VARCHAR(40),               -- name
    LTEXT   VARCHAR(60),               -- long text
    VERAK   VARCHAR(12),               -- person responsible
    GSBER   VARCHAR(4),                -- business area
    KOSAR   VARCHAR(2),                -- cost center type
    DATAB   DATE,                      -- valid from
    DATBI   DATE,                      -- valid to
    BUKRS   VARCHAR(4),                -- company code
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['cost_centers_sap_b1'] = """
CREATE TABLE IF NOT EXISTS cost_centers_sap_b1 (
    CenterCode  VARCHAR(8) PRIMARY KEY,
    CenterName  VARCHAR(30),
    InCharge    VARCHAR(50),
    Locked      VARCHAR(1) DEFAULT 'N',
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['cost_centers_dynamics'] = """
CREATE TABLE IF NOT EXISTS cost_centers_dynamics (
    DimensionValueCode  VARCHAR(10) PRIMARY KEY,
    Name                VARCHAR(60),
    DimensionCode       VARCHAR(10) DEFAULT 'CostCenter',
    IsActive            VARCHAR(5) DEFAULT 'true',
    Description         VARCHAR(200),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['cost_centers_oracle'] = """
CREATE TABLE IF NOT EXISTS cost_centers_oracle (
    Segment3        VARCHAR(25) PRIMARY KEY,    -- cost center segment
    Description     VARCHAR(240),
    ParentValue     VARCHAR(25),
    EnabledFlag     VARCHAR(1) DEFAULT 'Y',
    StartDateActive DATE,
    EndDateActive   DATE,
    erp_source      VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['cost_centers_erpnext'] = """
CREATE TABLE IF NOT EXISTS cost_centers_erpnext (
    name                VARCHAR(140) PRIMARY KEY,
    cost_center_name    VARCHAR(140),
    parent_cost_center  VARCHAR(140),
    company             VARCHAR(140),
    is_group            INTEGER DEFAULT 0,
    disabled            INTEGER DEFAULT 0,
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

# ── payment_terms ─────────────────────────────────────────────────────────────
schemas['payment_terms_odoo'] = """
CREATE TABLE IF NOT EXISTS payment_terms_odoo (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(64),          -- Net 30, Net 60, etc.
    note        TEXT,
    line_days   INTEGER,              -- net days
    line_value  NUMERIC(5,2),         -- 1.0 = 100%
    discount_days INTEGER,
    discount_pct NUMERIC(5,2),
    active      BOOLEAN DEFAULT TRUE,
    erp_source  VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['payment_terms_sap_s4'] = """
CREATE TABLE IF NOT EXISTS payment_terms_sap_s4 (
    ZTERM   VARCHAR(4) PRIMARY KEY,   -- payment term key
    ZTEXT   VARCHAR(30),              -- description
    ZBT01   NUMERIC(3,0),             -- discount 1 days
    ZBP01   NUMERIC(5,3),             -- discount 1 pct
    ZBT02   NUMERIC(3,0),             -- discount 2 days
    ZBP02   NUMERIC(5,3),             -- discount 2 pct
    ZBD3T   NUMERIC(3,0),             -- net days
    MANDT   VARCHAR(3) DEFAULT '100',
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['payment_terms_sap_b1'] = """
CREATE TABLE IF NOT EXISTS payment_terms_sap_b1 (
    GroupNum        INTEGER PRIMARY KEY,
    PayTermsGrpName VARCHAR(30),
    PymntAdpt       VARCHAR(1),        -- payment adaptor
    NumberOfPymnt   INTEGER DEFAULT 1,
    OpenIncomingPay VARCHAR(1) DEFAULT 'Y',
    OpenOutgoingPay VARCHAR(1) DEFAULT 'Y',
    DiscountCode    VARCHAR(8),
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['payment_terms_dynamics'] = """
CREATE TABLE IF NOT EXISTS payment_terms_dynamics (
    TermsCode               VARCHAR(10) PRIMARY KEY,
    Description             VARCHAR(50),
    DaysInPaymentPeriod     INTEGER,
    CashDiscountPercent     NUMERIC(5,2),
    CashDiscountDays        INTEGER,
    PaymentMethod           VARCHAR(10),
    erp_source              VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['payment_terms_oracle'] = """
CREATE TABLE IF NOT EXISTS payment_terms_oracle (
    TermsName       VARCHAR(50) PRIMARY KEY,
    Description     VARCHAR(240),
    DueDays         INTEGER,
    DiscountPercent NUMERIC(5,2),
    DiscountDays    INTEGER,
    CutoffDay       INTEGER,
    erp_source      VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['payment_terms_erpnext'] = """
CREATE TABLE IF NOT EXISTS payment_terms_erpnext (
    name                VARCHAR(140) PRIMARY KEY,
    payment_terms_name  VARCHAR(140),
    due_date_based_on   VARCHAR(50),
    payment_days        INTEGER,
    discount_percentage NUMERIC(5,2) DEFAULT 0,
    discount_validity_based_on VARCHAR(50),
    discount_validity  INTEGER DEFAULT 0,
    description         TEXT,
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

# ── exchange_rates ────────────────────────────────────────────────────────────
schemas['exchange_rates_odoo'] = """
CREATE TABLE IF NOT EXISTS exchange_rates_odoo (
    id          SERIAL PRIMARY KEY,
    currency_id VARCHAR(5),           -- from currency
    company_id  VARCHAR(100),
    name        DATE,                 -- rate date
    rate        NUMERIC(18,6),        -- 1 / exchange_rate
    erp_source  VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['exchange_rates_sap_s4'] = """
CREATE TABLE IF NOT EXISTS exchange_rates_sap_s4 (
    KURST   VARCHAR(4) DEFAULT 'M',   -- rate type: M=avg, B=buy, G=sell
    FCURR   VARCHAR(5),               -- from currency
    TCURR   VARCHAR(5) DEFAULT 'USD', -- to currency
    GDATU   DATE,                     -- valid from date
    UKURS   NUMERIC(18,6),            -- exchange rate
    FFACT   NUMERIC(9,0) DEFAULT 1,
    TFACT   NUMERIC(9,0) DEFAULT 1,
    PRIMARY KEY (KURST, FCURR, TCURR, GDATU),
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['exchange_rates_sap_b1'] = """
CREATE TABLE IF NOT EXISTS exchange_rates_sap_b1 (
    Currency    VARCHAR(3),
    RateDate    DATE,
    Rate        NUMERIC(18,6),
    RateType    VARCHAR(10) DEFAULT 'LAST',
    PRIMARY KEY (Currency, RateDate),
    erp_source  VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['exchange_rates_dynamics'] = """
CREATE TABLE IF NOT EXISTS exchange_rates_dynamics (
    CurrencyCode        VARCHAR(3),
    ExchangeRateType    VARCHAR(10) DEFAULT 'Default',
    StartDate           DATE,
    ExchangeRate        NUMERIC(18,6),
    PRIMARY KEY (CurrencyCode, ExchangeRateType, StartDate),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['exchange_rates_oracle'] = """
CREATE TABLE IF NOT EXISTS exchange_rates_oracle (
    FromCurrency    VARCHAR(15),
    ToCurrency      VARCHAR(15),
    ConversionType  VARCHAR(30) DEFAULT 'Corporate',
    ConversionDate  DATE,
    ConversionRate  NUMERIC(18,6),
    PRIMARY KEY (FromCurrency, ToCurrency, ConversionType, ConversionDate),
    erp_source      VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['exchange_rates_erpnext'] = """
CREATE TABLE IF NOT EXISTS exchange_rates_erpnext (
    name            VARCHAR(140),
    from_currency   VARCHAR(3),
    to_currency     VARCHAR(3),
    exchange_rate   NUMERIC(18,6),
    date            DATE,
    for_buying      INTEGER DEFAULT 1,
    for_selling     INTEGER DEFAULT 1,
    PRIMARY KEY (from_currency, to_currency, date),
    erp_source      VARCHAR(20) DEFAULT 'erpnext'
)"""

# ── warehouses ────────────────────────────────────────────────────────────────
schemas['warehouses_odoo'] = """
CREATE TABLE IF NOT EXISTS warehouses_odoo (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(128),
    code            VARCHAR(5),       -- short code e.g. WH
    company_id      VARCHAR(100),
    lot_stock_id    VARCHAR(50),      -- stock location
    wh_input_stock_loc_id  VARCHAR(50),
    wh_output_stock_loc_id VARCHAR(50),
    active          BOOLEAN DEFAULT TRUE,
    erp_source      VARCHAR(20) DEFAULT 'odoo'
)"""
schemas['warehouses_sap_s4'] = """
CREATE TABLE IF NOT EXISTS warehouses_sap_s4 (
    WERKS   VARCHAR(4) PRIMARY KEY,   -- plant
    NAME1   VARCHAR(30),
    ORT01   VARCHAR(25),              -- city
    LAND1   VARCHAR(3),               -- country
    PSTLZ   VARCHAR(10),              -- postal code
    EKORG   VARCHAR(4),               -- purchasing org
    BUKRS   VARCHAR(4),               -- company code
    LGORT   VARCHAR(4),               -- storage location (default)
    LGOBE   VARCHAR(16),              -- storage location desc
    erp_source VARCHAR(20) DEFAULT 'sap_s4'
)"""
schemas['warehouses_sap_b1'] = """
CREATE TABLE IF NOT EXISTS warehouses_sap_b1 (
    WarehouseCode   VARCHAR(8) PRIMARY KEY,
    WarehouseName   VARCHAR(100),
    Street          VARCHAR(100),
    City            VARCHAR(50),
    Country         VARCHAR(3),
    Inactive        VARCHAR(1) DEFAULT 'N',
    erp_source      VARCHAR(20) DEFAULT 'sap_b1'
)"""
schemas['warehouses_dynamics'] = """
CREATE TABLE IF NOT EXISTS warehouses_dynamics (
    WarehouseId         VARCHAR(10) PRIMARY KEY,
    Name                VARCHAR(60),
    SiteId              VARCHAR(10),
    ManualReorderingEnabled VARCHAR(5) DEFAULT 'true',
    City                VARCHAR(50),
    Country             VARCHAR(10),
    erp_source          VARCHAR(20) DEFAULT 'dynamics'
)"""
schemas['warehouses_oracle'] = """
CREATE TABLE IF NOT EXISTS warehouses_oracle (
    OrganizationCode    VARCHAR(3) PRIMARY KEY,
    OrganizationName    VARCHAR(240),
    OrganizationType    VARCHAR(30),
    LocationCode        VARCHAR(20),
    City                VARCHAR(60),
    Country             VARCHAR(60),
    EnabledFlag         VARCHAR(1) DEFAULT 'Y',
    erp_source          VARCHAR(20) DEFAULT 'oracle'
)"""
schemas['warehouses_erpnext'] = """
CREATE TABLE IF NOT EXISTS warehouses_erpnext (
    name                VARCHAR(140) PRIMARY KEY,
    warehouse_name      VARCHAR(140),
    parent_warehouse    VARCHAR(140),
    company             VARCHAR(140),
    city                VARCHAR(140),
    country             VARCHAR(140),
    is_group            INTEGER DEFAULT 0,
    disabled            INTEGER DEFAULT 0,
    erp_source          VARCHAR(20) DEFAULT 'erpnext'
)"""

print("Creating master data tables...")
for tbl, ddl in schemas.items():
    cur.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE")
    cur.execute(ddl)
    print(f"  + {tbl}")
conn.commit()

# ── SEED DATA ─────────────────────────────────────────────────────────────────
CC = [
    ('CC-001','Engineering',   'ENG','Ahmed Khan'),
    ('CC-002','Procurement',   'PRC','Sara Malik'),
    ('CC-003','Operations',    'OPS','John Carter'),
    ('CC-004','Finance',       'FIN','Priya Sharma'),
    ('CC-005','Maintenance',   'MNT','Omar Farooq'),
    ('CC-006','Quality',       'QA', 'Lisa Chen'),
    ('CC-007','Logistics',     'LOG','Carlos Ruiz'),
    ('CC-008','HR',            'HR', 'Anna Weber'),
    ('CC-009','IT',            'IT', 'Raj Patel'),
    ('CC-010','Production',    'PRD','Mei Lin'),
]

print("\nSeeding cost_centers...")
execute_values(cur, """INSERT INTO cost_centers_odoo
    (name,code,company_id,active) VALUES %s""", [
    (f'{dept} Department', cc, 'Procure-AI Demo', True)
    for cc, dept, code, mgr in CC
])
print("  ✓ cost_centers_odoo (10)")

execute_values(cur, """INSERT INTO cost_centers_sap_s4
    (KOSTL,KTEXT,LTEXT,VERAK,GSBER,KOSAR,DATAB,DATBI,BUKRS) VALUES %s""", [
    (cc.replace('-',''), f'{dept[:40]}', f'{dept} Cost Center',
     mgr[:12], 'BA01', 'E', '2020-01-01', '9999-12-31', '1000')
    for cc, dept, code, mgr in CC
])
print("  ✓ cost_centers_sap_s4 (10)")

execute_values(cur, """INSERT INTO cost_centers_sap_b1
    (CenterCode,CenterName,InCharge) VALUES %s""", [
    (cc.replace('-',''), f'{dept[:30]}', mgr[:50])
    for cc, dept, code, mgr in CC
])
print("  ✓ cost_centers_sap_b1 (10)")

execute_values(cur, """INSERT INTO cost_centers_dynamics
    (DimensionValueCode,Name,Description) VALUES %s""", [
    (cc.replace('-',''), f'{dept} Department', f'Cost center for {dept}')
    for cc, dept, code, mgr in CC
])
print("  ✓ cost_centers_dynamics (10)")

execute_values(cur, """INSERT INTO cost_centers_oracle
    (Segment3,Description,StartDateActive) VALUES %s""", [
    (cc.replace('-',''), f'{dept} Department', '2020-01-01')
    for cc, dept, code, mgr in CC
])
print("  ✓ cost_centers_oracle (10)")

execute_values(cur, """INSERT INTO cost_centers_erpnext
    (name,cost_center_name,company,is_group,disabled) VALUES %s""", [
    (f'{cc} - Procure-AI Demo Company', f'{dept} Department',
     'Procure-AI Demo Company', 0, 0)
    for cc, dept, code, mgr in CC
])
print("  ✓ cost_centers_erpnext (10)")
conn.commit()

PT = [
    ('Net 30',  'NT30', 30, 0.0,  0,  1),
    ('Net 45',  'NT45', 45, 0.0,  0,  2),
    ('Net 60',  'NT60', 60, 0.0,  0,  3),
    ('Net 90',  'NT90', 90, 0.0,  0,  4),
    ('2/10 Net 30','2N30',30,2.0,10,  5),
    ('1/15 Net 45','1N45',45,1.0,15,  6),
    ('Immediate', 'IMMD', 0, 0.0,  0,  7),
    ('Net 15',  'NT15', 15, 0.0,  0,  8),
    ('30 EOM',  'EOM3', 30, 0.0,  0,  9),
    ('Prepay',  'PREP',  0, 0.0,  0, 10),
]

print("\nSeeding payment_terms...")
execute_values(cur, """INSERT INTO payment_terms_odoo
    (name,note,line_days,line_value,discount_days,discount_pct) VALUES %s""", [
    (name, f'Payment within {days} days', days, 1.0, dddays, ddpct)
    for name,code,days,ddpct,dddays,seq in PT
])
print("  ✓ payment_terms_odoo (10)")

execute_values(cur, """INSERT INTO payment_terms_sap_s4
    (ZTERM,ZTEXT,ZBT01,ZBP01,ZBD3T) VALUES %s""", [
    (code, name[:30], dddays, ddpct, days)
    for name,code,days,ddpct,dddays,seq in PT
])
print("  ✓ payment_terms_sap_s4 (10)")

execute_values(cur, """INSERT INTO payment_terms_sap_b1
    (GroupNum,PayTermsGrpName,PymntAdpt,NumberOfPymnt,DiscountCode) VALUES %s""", [
    (seq, name[:30], 'B', 1, code if ddpct > 0 else None)
    for name,code,days,ddpct,dddays,seq in PT
])
print("  ✓ payment_terms_sap_b1 (10)")

execute_values(cur, """INSERT INTO payment_terms_dynamics
    (TermsCode,Description,DaysInPaymentPeriod,CashDiscountPercent,CashDiscountDays)
    VALUES %s""", [
    (code, name[:50], days, ddpct, dddays)
    for name,code,days,ddpct,dddays,seq in PT
])
print("  ✓ payment_terms_dynamics (10)")

execute_values(cur, """INSERT INTO payment_terms_oracle
    (TermsName,Description,DueDays,DiscountPercent,DiscountDays) VALUES %s""", [
    (name[:50], name[:240], days, ddpct, dddays)
    for name,code,days,ddpct,dddays,seq in PT
])
print("  ✓ payment_terms_oracle (10)")

execute_values(cur, """INSERT INTO payment_terms_erpnext
    (name,payment_terms_name,due_date_based_on,payment_days,discount_percentage)
    VALUES %s""", [
    (name[:140], name[:140], 'Day(s) after invoice date', days, ddpct)
    for name,code,days,ddpct,dddays,seq in PT
])
print("  ✓ payment_terms_erpnext (10)")
conn.commit()

CURRENCIES = [
    ('EUR','USD','2025-01-01',1.092000),('GBP','USD','2025-01-01',1.268000),
    ('PKR','USD','2025-01-01',0.003580),('SAR','USD','2025-01-01',0.266700),
    ('CHF','USD','2025-01-01',1.115000),('SGD','USD','2025-01-01',0.744000),
    ('SEK','USD','2025-01-01',0.095800),('CAD','USD','2025-01-01',0.742000),
    ('AED','USD','2025-01-01',0.272300),('JPY','USD','2025-01-01',0.006680),
    ('EUR','USD','2025-04-01',1.081000),('GBP','USD','2025-04-01',1.255000),
]

print("\nSeeding exchange_rates...")
execute_values(cur, """INSERT INTO exchange_rates_odoo
    (currency_id,company_id,name,rate) VALUES %s""", [
    (fc, 'Procure-AI Demo', dt, round(1/rate, 6))
    for fc,tc,dt,rate in CURRENCIES
])
print("  ✓ exchange_rates_odoo (12)")

execute_values(cur, """INSERT INTO exchange_rates_sap_s4
    (KURST,FCURR,TCURR,GDATU,UKURS) VALUES %s""", [
    ('M', fc, tc, dt, rate)
    for fc,tc,dt,rate in CURRENCIES
])
print("  ✓ exchange_rates_sap_s4 (12)")

execute_values(cur, """INSERT INTO exchange_rates_sap_b1
    (Currency,RateDate,Rate,RateType) VALUES %s""", [
    (fc, dt, rate, 'LAST')
    for fc,tc,dt,rate in CURRENCIES
])
print("  ✓ exchange_rates_sap_b1 (12)")

execute_values(cur, """INSERT INTO exchange_rates_dynamics
    (CurrencyCode,ExchangeRateType,StartDate,ExchangeRate) VALUES %s""", [
    (fc, 'Default', dt, rate)
    for fc,tc,dt,rate in CURRENCIES
])
print("  ✓ exchange_rates_dynamics (12)")

execute_values(cur, """INSERT INTO exchange_rates_oracle
    (FromCurrency,ToCurrency,ConversionType,ConversionDate,ConversionRate)
    VALUES %s""", [
    (fc, tc, 'Corporate', dt, rate)
    for fc,tc,dt,rate in CURRENCIES
])
print("  ✓ exchange_rates_oracle (12)")

execute_values(cur, """INSERT INTO exchange_rates_erpnext
    (name,from_currency,to_currency,exchange_rate,date) VALUES %s""", [
    (f'{fc}-{tc}-{dt}', fc, tc, rate, dt)
    for fc,tc,dt,rate in CURRENCIES
])
print("  ✓ exchange_rates_erpnext (12)")
conn.commit()

WH = [
    ('WH',  'Main Warehouse',    'Karachi','PKR','P100','1000','MN'),
    ('WH2', 'Raw Materials',     'Lahore', 'PKR','P200','1000','RM'),
    ('WH3', 'Finished Goods',    'Karachi','PKR','P300','1000','FG'),
    ('WH4', 'Transit Warehouse', 'Dubai',  'AED','P400','1000','TR'),
    ('WH5', 'Cold Storage',      'Karachi','PKR','P500','1000','CS'),
    ('WH6', 'Hazmat Store',      'Karachi','PKR','P600','1000','HZ'),
    ('WH7', 'Spare Parts',       'Lahore', 'PKR','P700','1000','SP'),
]

print("\nSeeding warehouses...")
execute_values(cur, """INSERT INTO warehouses_odoo
    (name,code,company_id,active) VALUES %s""", [
    (f'{name} - {city}', code, 'Procure-AI Demo', True)
    for code,name,city,curr,sapcode,bukrs,lgort in WH
])
print("  ✓ warehouses_odoo (7)")

execute_values(cur, """INSERT INTO warehouses_sap_s4
    (WERKS,NAME1,ORT01,LAND1,EKORG,BUKRS,LGORT,LGOBE) VALUES %s""", [
    (sapcode, name[:30], city, 'PK' if curr=='PKR' else 'AE',
     'ORG1', bukrs, lgort, f'{name[:10]} Loc')
    for code,name,city,curr,sapcode,bukrs,lgort in WH
])
print("  ✓ warehouses_sap_s4 (7)")

execute_values(cur, """INSERT INTO warehouses_sap_b1
    (WarehouseCode,WarehouseName,City,Country,Inactive) VALUES %s""", [
    (code, name[:100], city,
     'PK' if curr=='PKR' else 'AE', 'N')
    for code,name,city,curr,sapcode,bukrs,lgort in WH
])
print("  ✓ warehouses_sap_b1 (7)")

execute_values(cur, """INSERT INTO warehouses_dynamics
    (WarehouseId,Name,SiteId,City,Country) VALUES %s""", [
    (code, name[:60], 'SITE1', city,
     'PK' if curr=='PKR' else 'AE')
    for code,name,city,curr,sapcode,bukrs,lgort in WH
])
print("  ✓ warehouses_dynamics (7)")

execute_values(cur, """INSERT INTO warehouses_oracle
    (OrganizationCode,OrganizationName,OrganizationType,City,Country)
    VALUES %s""", [
    (sapcode[:3], name[:240], 'Inventory', city,
     'Pakistan' if curr=='PKR' else 'UAE')
    for code,name,city,curr,sapcode,bukrs,lgort in WH
])
print("  ✓ warehouses_oracle (7)")

execute_values(cur, """INSERT INTO warehouses_erpnext
    (name,warehouse_name,company,city,country,is_group,disabled)
    VALUES %s""", [
    (f'{name} - Procure-AI Demo Company', name,
     'Procure-AI Demo Company', city,
     'Pakistan' if curr=='PKR' else 'UAE', 0, 0)
    for code,name,city,curr,sapcode,bukrs,lgort in WH
])
print("  ✓ warehouses_erpnext (7)")
conn.commit()

# Update table_registry
for mod, module_name, module_code, table_type, odoo_model, sap_obj in [
    ('cost_centers',   'Finance','FIN','master','account.analytic.account','CSKS'),
    ('payment_terms',  'Finance','FIN','master','account.payment.term',    'T052'),
    ('exchange_rates', 'Finance','FIN','master','res.currency.rate',       'TCURR'),
    ('warehouses',     'Warehouse','WMS','master','stock.warehouse',       'T001W'),
]:
    for erp in ERPS:
        tbl = f'{mod}_{erp}'
        cur.execute("""INSERT INTO table_registry
            (table_name,module,module_code,table_type,odoo_model,sap_object,erp_source,erp_table_name)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (table_name) DO NOTHING""",
            (tbl, module_name, module_code, table_type, odoo_model, sap_obj, erp, tbl))
conn.commit()

print(f"\n{'='*60}")
print("BATCH 3 COMPLETE — 24 tables created and seeded")
print(f"{'='*60}")
cur.close(); conn.close()
