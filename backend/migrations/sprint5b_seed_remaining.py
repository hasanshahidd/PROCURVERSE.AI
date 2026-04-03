"""
Sprint 5B — Seed remaining 4 empty ERP modules
================================================
Fills: items, po_lines, grn_headers, spend
For all 6 ERPs: odoo, sap_s4, sap_b1, dynamics, oracle, erpnext
Each module: 10 items / 20 po_lines / 8 grn_headers / 12 spend rows × 6 ERPs
"""

import os, sys
os.chdir("E:/procure AI/Procure-AI")
sys.path.insert(0, ".")

import psycopg2
from psycopg2.extras import execute_values
conn = psycopg2.connect("postgresql://postgres:YourStr0ng!Pass@localhost:5433/odoo_procurement_demo")
cur  = conn.cursor()

# ─────────────────────────────────────────────────────────────────────────────
# Reference data (same 10 items, 10 POs, 12 vendors across all ERPs)
# ─────────────────────────────────────────────────────────────────────────────

# SAP B1: ItmsGrpCod is an integer — map categories to group codes
SAP_B1_GROUP = {
    'Metals': 101, 'Bearings': 102, 'Hydraulics': 103,
    'Electronics': 104, 'Seals': 105, 'Chemicals': 106,
    'Packaging': 107, 'Safety': 108, 'Tooling': 109,
}
ITEMS = [
    # (odoo_ref, sap_ref, b1_ref, d365_ref, oracle_ref, erpnext_ref,
    #  description, category, sap_class, uom, price_usd, min_qty, lead_days, reorder, safety)
    ('ITEM-001','MAT-10001','I-ITEM001','I-001','IT-00001','ITEM-001',
     'Steel Sheet Metal 3mm HR',      'Metals',      'ROH','KG',   2.50,  500, 14, 2000,  500),
    ('ITEM-002','MAT-10002','I-ITEM002','I-002','IT-00002','ITEM-002',
     'Aluminum Billets 6061-T6',      'Metals',      'ROH','KG',   2.85, 1000,  7, 5000, 1000),
    ('ITEM-003','MAT-10003','I-ITEM003','I-003','IT-00003','ITEM-003',
     'Industrial Bearing SKF 6205',   'Bearings',    'HAWA','PCS', 12.50,  200, 21,  500,  100),
    ('ITEM-004','MAT-10004','I-ITEM004','I-004','IT-00004','ITEM-004',
     'Hydraulic Fitting 1/2 NPT',     'Hydraulics',  'HAWA','PCS',  8.75,  100, 14,  300,  100),
    ('ITEM-005','MAT-10005','I-ITEM005','I-005','IT-00005','ITEM-005',
     'Electronic Control PCB v2.1',   'Electronics', 'HAWA','PCS',245.00,   20, 21,  100,   30),
    ('ITEM-006','MAT-10006','I-ITEM006','I-006','IT-00006','ITEM-006',
     'Rubber Gasket 50mm OD',         'Seals',       'HAWA','PCS',  3.20,  200, 14, 1000,  300),
    ('ITEM-007','MAT-10007','I-ITEM007','I-007','IT-00007','ITEM-007',
     'Industrial Solvent n-Hexane',   'Chemicals',   'HIBE','LTR',  3.20, 1000,  7, 5000, 1000),
    ('ITEM-008','MAT-10008','I-ITEM008','I-008','IT-00008','ITEM-008',
     'Corrugated Packaging Box 40x30','Packaging',   'VERP','PCS',  1.10, 2000,  5,10000, 2000),
    ('ITEM-009','MAT-10009','I-ITEM009','I-009','IT-00009','ITEM-009',
     'Safety Helmet EN397 Yellow',    'Safety',      'HAWA','PCS', 22.50,   50, 14,  200,   50),
    ('ITEM-010','MAT-10010','I-ITEM010','I-010','IT-00010','ITEM-010',
     'Carbide Cutting Insert CNMG',   'Tooling',     'HAWA','PCS', 18.75,   50, 14,  200,   50),
]

# PO numbers per ERP (from vendors seeding reference)
PO_ODOO     = ['PO00001','PO00002','PO00003','PO00004','PO00005','PO00006','PO00007','PO00008','PO00009','PO00010']
PO_SAP_S4   = ['4500000001','4500000002','4500000003','4500000004','4500000005','4500000006','4500000007','4500000008','4500000009','4500000010']
PO_SAP_B1   = [10001,10002,10003,10004,10005,10006,10007,10008,10009,10010]
PO_DYNAMICS = ['PO-000001','PO-000002','PO-000003','PO-000004','PO-000005','PO-000006','PO-000007','PO-000008','PO-000009','PO-000010']
PO_ORACLE   = ['US-000001','US-000002','US-000003','US-000004','US-000005','US-000006','US-000007','US-000008','US-000009','US-000010']
PO_ERPNEXT  = ['PUR-ORD-2025-00001','PUR-ORD-2025-00002','PUR-ORD-2025-00003','PUR-ORD-2025-00004','PUR-ORD-2025-00005',
               'PUR-ORD-2025-00006','PUR-ORD-2025-00007','PUR-ORD-2025-00008','PUR-ORD-2025-00009','PUR-ORD-2025-00010']

# Vendor IDs per ERP (first 10 vendors, matching PO vendors)
VND_ODOO     = [13,14,15,16,17,18,19,20,21,22]   # integer IDs from vendors_odoo
VND_SAP_S4   = ['0000100001','0000100002','0000100003','0000100004','0000100005','0000100006','0000100007','0000100008','0000100009','0000100010']
VND_SAP_B1   = ['V-GTS001','V-ESA002','V-AIC003','V-EOS004','V-PSR005','V-SCL006','V-TMS007','V-FLL008','V-NCA009','V-DOP010']
VND_DYNAMICS = ['V-00001','V-00002','V-00003','V-00004','V-00005','V-00006','V-00007','V-00008','V-00009','V-00010']
VND_ORACLE   = ['SUP-00001','SUP-00002','SUP-00003','SUP-00004','SUP-00005','SUP-00006','SUP-00007','SUP-00008','SUP-00009','SUP-00010']
VND_ERPNEXT  = ['SUP-00001','SUP-00002','SUP-00003','SUP-00004','SUP-00005','SUP-00006','SUP-00007','SUP-00008','SUP-00009','SUP-00010']

VENDOR_NAMES = [
    'Global Tech Supplies LLC','Euro Steel AG','Apex Industrial Components','EuroStar Office Supplies',
    'Pak Steel & Raw Materials','Sigma Chemicals Ltd','TechMed Solutions','FastLog Logistics',
    'Nordic Components AB','Delta Office Products',
]

# Items linked to POs (2 items per PO = 20 lines)
PO_LINES_MAP = [
    # (po_idx, item_idx, qty, unit_price)
    (0, 0, 500.0,  2.50),   # PO1 → Steel Sheet Metal
    (0, 2, 200.0, 12.50),   # PO1 → Industrial Bearing
    (1, 1,1000.0,  2.85),   # PO2 → Aluminum Billets
    (1, 0, 800.0,  2.50),   # PO2 → Steel Sheet Metal
    (2, 3, 100.0,  8.75),   # PO3 → Hydraulic Fitting
    (2, 5, 200.0,  3.20),   # PO3 → Rubber Gasket
    (3, 7,2000.0,  1.10),   # PO4 → Packaging Box
    (3, 8,  50.0, 22.50),   # PO4 → Safety Helmet
    (4, 0, 600.0,  2.50),   # PO5 → Steel Sheet Metal
    (4, 1, 500.0,  2.85),   # PO5 → Aluminum Billets
    (5, 6,1000.0,  3.20),   # PO6 → Solvent
    (5, 5, 500.0,  3.20),   # PO6 → Gasket
    (6, 4,  20.0,245.00),   # PO7 → PCB
    (6, 9,  50.0, 18.75),   # PO7 → Cutting Insert
    (7, 0, 400.0,  2.50),   # PO8 → Steel Sheet Metal
    (7, 2, 100.0, 12.50),   # PO8 → Bearing
    (8, 7,1000.0,  1.10),   # PO9 → Packaging Box
    (8, 8, 100.0, 22.50),   # PO9 → Safety Helmet
    (9, 3, 200.0,  8.75),   # PO10 → Hydraulic Fitting
    (9, 5, 300.0,  3.20),   # PO10 → Gasket
]

PO_DATES = ['2025-01-15','2025-01-25','2025-02-03','2025-02-08','2025-02-15',
            '2025-02-22','2025-03-05','2025-03-15','2025-03-20','2025-04-02']

# GRN dates (8 of 10 POs received)
GRN_DATA = [  # (po_idx, grn_date, vendor_idx)
    (0,'2025-01-28',0), (1,'2025-02-05',1), (2,'2025-02-18',2),
    (3,'2025-02-25',3), (4,'2025-03-05',4), (5,'2025-03-12',5),
    (7,'2025-04-01',7), (8,'2025-04-05',8),   # PO6,PO9 still open
]

# Spend: 12 rows per ERP (monthly aggregated, 6 months × 2 cost centers)
SPEND_DATA = [
    # (month, cost_center, item_category, amount_usd, vendor_idx)
    ('2025-01','CC-001','Metals',        285000.00, 0),
    ('2025-01','CC-002','Electronics',    94300.00, 6),
    ('2025-02','CC-001','Hydraulics',     36225.00, 2),
    ('2025-02','CC-002','Packaging',      13800.00, 3),
    ('2025-03','CC-001','Chemicals',      77050.00, 5),
    ('2025-03','CC-002','Safety',        109250.00, 6),
    ('2025-04','CC-001','Metals',        178250.00, 4),
    ('2025-04','CC-002','Tooling',        20700.00, 7),
    ('2025-05','CC-001','Electronics',   138000.00, 8),
    ('2025-05','CC-002','Packaging',      25300.00, 9),
    ('2025-06','CC-001','Bearings',       51750.00, 0),
    ('2025-06','CC-002','Hydraulics',     36225.00, 2),
]

print("Seeding items...")

# ── items_odoo ────────────────────────────────────────────────────────────────
cur.execute("DELETE FROM items_odoo")
execute_values(cur, """
    INSERT INTO items_odoo (name, default_code, categ_id, type, uom_id, uom_po_id,
        standard_price, purchase_ok, active, description_purchase)
    VALUES %s
""", [
    (it[6], it[0], it[7], 'product', it[9], it[9],
     it[10], True, True, f"Purchase description for {it[6]}")
    for it in ITEMS
])
print("  ✓ items_odoo (10 rows)")

# ── items_sap_s4 ──────────────────────────────────────────────────────────────
cur.execute("DELETE FROM items_sap_s4")
execute_values(cur, """
    INSERT INTO items_sap_s4 (MATNR, MAKTX, MEINS, MTART, MATKL, WERKS,
        NETPR, PEINH, WAERS, BSTMI, MINBE, EISBE, WEBAZ, MMSTA)
    VALUES %s
""", [
    (it[1], it[6][:40], it[9], it[8], it[7][:9], '1000',
     it[10], 1, 'USD', it[11], it[13], it[14], it[12], 'Z1')
    for it in ITEMS
])
print("  ✓ items_sap_s4 (10 rows)")

# ── items_sap_b1 ──────────────────────────────────────────────────────────────
cur.execute("DELETE FROM items_sap_b1")
execute_values(cur, """
    INSERT INTO items_sap_b1 (ItemCode, ItemName, ItemType, ItmsGrpCod, InvntryUom,
        PurPackUn, LastPurPrc, Currency, MinLevel, ReorderPnt, LeadTime,
        MinOrderQty, Taxable, InvntItem, PrchseItem, FrozenFor)
    VALUES %s
""", [
    (it[2], it[6][:100], 'I', SAP_B1_GROUP.get(it[7], 100), it[9],
     it[9], it[10], 'USD', it[14], it[13], it[12],
     it[11], 'Y', 'Y', 'Y', 'N')
    for it in ITEMS
])
print("  ✓ items_sap_b1 (10 rows)")

# ── items_dynamics ────────────────────────────────────────────────────────────
cur.execute("DELETE FROM items_dynamics")
execute_values(cur, """
    INSERT INTO items_dynamics (ItemNumber, ProductName, SearchName, ItemGroup,
        StorageDimensionGroup, TrackingDimensionGroup, UnitOfMeasure, PurchaseUom,
        PurchasePrice, CostingMethod, TaxItemGroup, ReorderPoint, SafetyStock,
        MinOrderQty, LeadTimeInDays, Blocked)
    VALUES %s
""", [
    (it[3], it[6][:100], it[3][:60], it[7][:10],
     'SiteWH', 'None', it[9][:10], it[9][:10],
     it[10], 'FIFO', 'FULL', it[13], it[14],
     it[11], it[12], 'No')
    for it in ITEMS
])
print("  ✓ items_dynamics (10 rows)")

# ── items_oracle ──────────────────────────────────────────────────────────────
cur.execute("DELETE FROM items_oracle")
execute_values(cur, """
    INSERT INTO items_oracle (ItemNumber, ItemDescription, ItemType, Category,
        UomCode, PurchasingUom, ListPrice, CurrencyCode, ReorderPoint,
        SafetyStockQuantity, MinOrderQuantity, FixedLeadTime, BuyerName, EnabledFlag)
    VALUES %s
""", [
    (it[4], it[6][:240], 'Purchased', it[7],
     it[9], it[9], it[10], 'USD', it[13],
     it[14], it[11], it[12], 'Ahmed Khan', 'Y')
    for it in ITEMS
])
print("  ✓ items_oracle (10 rows)")

# ── items_erpnext ─────────────────────────────────────────────────────────────
cur.execute("DELETE FROM items_erpnext")
execute_values(cur, """
    INSERT INTO items_erpnext (name, item_name, item_group, description,
        stock_uom, purchase_uom, standard_rate, valuation_rate,
        is_purchase_item, is_stock_item, disabled,
        min_order_qty, safety_stock, reorder_level, lead_time_days)
    VALUES %s
""", [
    (it[5], it[6][:140], it[7], it[6],
     it[9], it[9], it[10], it[10],
     1, 1, 0,
     it[11], it[14], it[13], it[12])
    for it in ITEMS
])
print("  ✓ items_erpnext (10 rows)")

conn.commit()
print()
print("Seeding po_lines...")

# ── po_lines_odoo ─────────────────────────────────────────────────────────────
cur.execute("DELETE FROM po_lines_odoo")
execute_values(cur, """
    INSERT INTO po_lines_odoo (order_id, product_id, name, product_qty, product_uom,
        price_unit, price_subtotal, price_tax, price_total,
        date_planned, qty_received, qty_invoiced)
    VALUES %s
""", [
    (PO_ODOO[pi], ITEMS[ii][0], ITEMS[ii][6], qty, ITEMS[ii][9],
     price, round(qty*price,2), round(qty*price*0.15,2), round(qty*price*1.15,2),
     '2025-02-15', qty if pi < 6 else 0, qty if pi < 4 else 0)
    for pi, ii, qty, price in PO_LINES_MAP
])
print("  ✓ po_lines_odoo (20 rows)")

# ── po_lines_sap_s4 ───────────────────────────────────────────────────────────
cur.execute("DELETE FROM po_lines_sap_s4")
execute_values(cur, """
    INSERT INTO po_lines_sap_s4 (EBELN, EBELP, MATNR, TXZ01, WERKS, LGORT,
        MENGE, MEINS, NETPR, PEINH, NETWR, MWSKZ, EINDT, WEMNG, REMNG)
    VALUES %s
""", [
    (PO_SAP_S4[pi], str(idx%2+10).zfill(5),
     ITEMS[ii][1], ITEMS[ii][6][:40], '1000', '0001',
     qty, ITEMS[ii][9], price, 1, round(qty*price,2),
     'V0', '2025-02-15', qty if pi < 6 else 0, qty if pi < 4 else 0)
    for idx, (pi, ii, qty, price) in enumerate(PO_LINES_MAP)
])
print("  ✓ po_lines_sap_s4 (20 rows)")

# ── po_lines_sap_b1 ───────────────────────────────────────────────────────────
cur.execute("DELETE FROM po_lines_sap_b1")
execute_values(cur, """
    INSERT INTO po_lines_sap_b1 (DocNum, LineNum, ItemCode, Dscription, Quantity,
        InvQty, UomCode, Price, LineTotal, TaxCode, WhsCode,
        ShipDate, OpenQty, LineStatus)
    VALUES %s
""", [
    (PO_SAP_B1[pi], idx%2,
     ITEMS[ii][2], ITEMS[ii][6][:100], qty,
     qty, ITEMS[ii][9], price, round(qty*price,2),
     'VAT', 'WH01', '2025-02-15',
     0 if pi < 6 else qty, 'C' if pi < 4 else 'O')
    for idx, (pi, ii, qty, price) in enumerate(PO_LINES_MAP)
])
print("  ✓ po_lines_sap_b1 (20 rows)")

# ── po_lines_dynamics ─────────────────────────────────────────────────────────
cur.execute("DELETE FROM po_lines_dynamics")
execute_values(cur, """
    INSERT INTO po_lines_dynamics (PurchaseOrderNumber, LineNumber, ItemNumber,
        ProductName, Quantity, Unit, UnitPrice, LineAmount, TaxGroup,
        Site, Warehouse, DeliveryDate, ReceivedQuantity, InvoicedQuantity)
    VALUES %s
""", [
    (PO_DYNAMICS[pi], idx%2+1,
     ITEMS[ii][3], ITEMS[ii][6][:100], qty,
     ITEMS[ii][9], price, round(qty*price,2), 'FULL',
     'SITE1', 'WH01', '2025-02-15',
     qty if pi < 6 else 0, qty if pi < 4 else 0)
    for idx, (pi, ii, qty, price) in enumerate(PO_LINES_MAP)
])
print("  ✓ po_lines_dynamics (20 rows)")

# ── po_lines_oracle ───────────────────────────────────────────────────────────
cur.execute("DELETE FROM po_lines_oracle")
execute_values(cur, """
    INSERT INTO po_lines_oracle (PONumber, LineNumber, ItemNumber, ItemDescription,
        CategoryCode, Quantity, UomCode, UnitPrice, LineAmount, TaxCode,
        NeedByDate, QuantityReceived, QuantityBilled, LineStatus)
    VALUES %s
""", [
    (PO_ORACLE[pi], idx%2+1,
     ITEMS[ii][4], ITEMS[ii][6][:240], ITEMS[ii][7],
     qty, ITEMS[ii][9], price, round(qty*price,2), 'STANDARD',
     '2025-02-15',
     qty if pi < 6 else 0, qty if pi < 4 else 0,
     'CLOSED' if pi < 4 else 'OPEN')
    for idx, (pi, ii, qty, price) in enumerate(PO_LINES_MAP)
])
print("  ✓ po_lines_oracle (20 rows)")

# ── po_lines_erpnext ──────────────────────────────────────────────────────────
cur.execute("DELETE FROM po_lines_erpnext")
execute_values(cur, """
    INSERT INTO po_lines_erpnext (name, parent, idx, item_code, item_name,
        description, qty, stock_uom, uom, conversion_factor,
        rate, amount, received_qty, billed_qty, warehouse, schedule_date)
    VALUES %s
""", [
    (f"{PO_ERPNEXT[pi]}-{idx%2+1}", PO_ERPNEXT[pi], idx%2+1,
     ITEMS[ii][5], ITEMS[ii][6][:140], ITEMS[ii][6],
     qty, ITEMS[ii][9], ITEMS[ii][9], 1.0,
     price, round(qty*price,2),
     qty if pi < 6 else 0, qty if pi < 4 else 0,
     'Stores - Company', '2025-02-15')
    for idx, (pi, ii, qty, price) in enumerate(PO_LINES_MAP)
])
print("  ✓ po_lines_erpnext (20 rows)")

conn.commit()
print()
print("Seeding grn_headers...")

GRN_ODOO_NAMES   = [f'WH/IN/2025/{str(i+1).zfill(5)}' for i in range(8)]
GRN_SAP_DOCS     = [str(5000000001+i) for i in range(8)]
GRN_SAP_B1_DOCS  = list(range(30001, 30009))
GRN_DYN_NUMS     = [f'PR-{str(i+1).zfill(6)}' for i in range(8)]
GRN_ORACLE_NUMS  = [f'REC-{str(i+1).zfill(5)}' for i in range(8)]
GRN_ERPNEXT_NUMS = [f'MAT-PRE-2025-{str(i+1).zfill(5)}' for i in range(8)]

# ── grn_headers_odoo ──────────────────────────────────────────────────────────
cur.execute("DELETE FROM grn_headers_odoo")
execute_values(cur, """
    INSERT INTO grn_headers_odoo (name, partner_id, origin, scheduled_date,
        date_done, picking_type_id, location_id, location_dest_id, state, note)
    VALUES %s
""", [
    (GRN_ODOO_NAMES[i], str(VND_ODOO[pi]),
     PO_ODOO[pi], PO_DATES[pi], gdate,
     'Purchase Orders', 'Vendors', 'WH/Stock', 'done',
     f'GRN for {PO_ODOO[pi]}')
    for i, (pi, gdate, vi) in enumerate(GRN_DATA)
])
print("  ✓ grn_headers_odoo (8 rows)")

# ── grn_headers_sap_s4 ────────────────────────────────────────────────────────
cur.execute("DELETE FROM grn_headers_sap_s4")
execute_values(cur, """
    INSERT INTO grn_headers_sap_s4 (MBLNR, MJAHR, BUDAT, BLDAT, XBLNR,
        BKTXT, LIFNR, EBELN, WERKS, LGORT, BWART, USNAM)
    VALUES %s
""", [
    (GRN_SAP_DOCS[i], '2025', gdate, gdate,
     f'DN-{str(i+1).zfill(6)}',
     f'GR for {PO_SAP_S4[pi]}', VND_SAP_S4[pi],
     PO_SAP_S4[pi], '1000', '0001', '101', 'PROCSVC')
    for i, (pi, gdate, vi) in enumerate(GRN_DATA)
])
print("  ✓ grn_headers_sap_s4 (8 rows)")

# ── grn_headers_sap_b1 ────────────────────────────────────────────────────────
cur.execute("DELETE FROM grn_headers_sap_b1")
execute_values(cur, """
    INSERT INTO grn_headers_sap_b1 (DocNum, DocDate, DocDueDate, CardCode,
        CardName, NumAtCard, BaseRef, DocTotal, DocCurrency, Comments, DocStatus, Confirmed)
    VALUES %s
""", [
    (GRN_SAP_B1_DOCS[i], gdate, gdate,
     VND_SAP_B1[pi], VENDOR_NAMES[pi],
     f'DN-{str(i+1).zfill(6)}', str(PO_SAP_B1[pi]),
     round(PO_LINES_MAP[pi*2][2]*PO_LINES_MAP[pi*2][3] + PO_LINES_MAP[pi*2+1][2]*PO_LINES_MAP[pi*2+1][3], 2)
     if pi*2+1 < len(PO_LINES_MAP) else 0.00,
     'USD', f'GR for PO {PO_SAP_B1[pi]}', 'C', 'Y')
    for i, (pi, gdate, vi) in enumerate(GRN_DATA)
])
print("  ✓ grn_headers_sap_b1 (8 rows)")

# ── grn_headers_dynamics ──────────────────────────────────────────────────────
cur.execute("DELETE FROM grn_headers_dynamics")
execute_values(cur, """
    INSERT INTO grn_headers_dynamics (ProductReceiptNumber, PurchaseOrderNumber,
        VendorAccountNumber, VendorName, ReceiptDate, Site, Warehouse,
        DeliveryNote, Status, PostingDate, Description)
    VALUES %s
""", [
    (GRN_DYN_NUMS[i], PO_DYNAMICS[pi],
     VND_DYNAMICS[pi], VENDOR_NAMES[pi], gdate,
     'SITE1', 'WH01',
     f'DN-{str(i+1).zfill(6)}', 'Posted', gdate,
     f'Product receipt for {PO_DYNAMICS[pi]}')
    for i, (pi, gdate, vi) in enumerate(GRN_DATA)
])
print("  ✓ grn_headers_dynamics (8 rows)")

# ── grn_headers_oracle ────────────────────────────────────────────────────────
cur.execute("DELETE FROM grn_headers_oracle")
execute_values(cur, """
    INSERT INTO grn_headers_oracle (ReceiptNumber, PONumber, SupplierNumber,
        SupplierName, ReceiptDate, ReceivedBy, ShipmentNumber,
        WaybillNumber, OrganizationCode, ReceiptStatus, TransactionType)
    VALUES %s
""", [
    (GRN_ORACLE_NUMS[i], PO_ORACLE[pi],
     VND_ORACLE[pi], VENDOR_NAMES[pi], gdate,
     'WAREHOUSE', f'SHIP-{str(i+1).zfill(5)}',
     f'AWB-{str(i+1).zfill(8)}', 'M1', 'CLOSED', 'RECEIVE')
    for i, (pi, gdate, vi) in enumerate(GRN_DATA)
])
print("  ✓ grn_headers_oracle (8 rows)")

# ── grn_headers_erpnext ───────────────────────────────────────────────────────
cur.execute("DELETE FROM grn_headers_erpnext")
execute_values(cur, """
    INSERT INTO grn_headers_erpnext (name, supplier, supplier_name,
        posting_date, posting_time, purchase_order,
        set_warehouse, status, bill_no, bill_date, company, remarks)
    VALUES %s
""", [
    (GRN_ERPNEXT_NUMS[i], VND_ERPNEXT[pi], VENDOR_NAMES[pi],
     gdate, '09:00:00', PO_ERPNEXT[pi],
     'Stores - Company', 'Submitted',
     f'DN-{str(i+1).zfill(6)}', gdate,
     'Procure-AI Demo Company', f'GRN for {PO_ERPNEXT[pi]}')
    for i, (pi, gdate, vi) in enumerate(GRN_DATA)
])
print("  ✓ grn_headers_erpnext (8 rows)")

conn.commit()
print()
print("Seeding spend...")

# Helper: spend PO numbers
def spnd_po(erp_list, idx): return erp_list[idx % len(erp_list)]

# ── spend_odoo ────────────────────────────────────────────────────────────────
cur.execute("DELETE FROM spend_odoo")
execute_values(cur, """
    INSERT INTO spend_odoo (name, partner_id, date_approve, amount_total,
        currency_id, x_department, x_budget_category, state, company_id)
    VALUES %s
""", [
    (f'PO00{(i+1):03d}', str(VND_ODOO[vi % len(VND_ODOO)]),
     f'{mo}-01', amount, 'USD',
     cc, cat, 'purchase', 1)
    for i, (mo, cc, cat, amount, vi) in enumerate(SPEND_DATA)
])
print("  ✓ spend_odoo (12 rows)")

# ── spend_sap_s4 ──────────────────────────────────────────────────────────────
cur.execute("DELETE FROM spend_sap_s4")
execute_values(cur, """
    INSERT INTO spend_sap_s4 (EBELN, BUKRS, LIFNR, EKORG,
        BEDAT, NETWR, WAERS, KOSTL, SAKTO, MATKL, MATNR, BSART)
    VALUES %s
""", [
    (f'45000SP{str(i+1).zfill(3)}', '1000',
     VND_SAP_S4[vi % len(VND_SAP_S4)], 'ORG1',
     f'{mo}-01', amount, 'USD',
     cc.replace('CC-','KOST'), '400000', cat[:9], f'MAT-1000{i+1}', 'NB')
    for i, (mo, cc, cat, amount, vi) in enumerate(SPEND_DATA)
])
print("  ✓ spend_sap_s4 (12 rows)")

# ── spend_sap_b1 ──────────────────────────────────────────────────────────────
cur.execute("DELETE FROM spend_sap_b1")
execute_values(cur, """
    INSERT INTO spend_sap_b1 (DocNum, CardCode, CardName, DocDate,
        DocTotal, DocCurrency, OcrCode, Project, ItmsGrpCod, DocStatus)
    VALUES %s
""", [
    (40001+i,
     VND_SAP_B1[vi % len(VND_SAP_B1)], VENDOR_NAMES[vi % len(VENDOR_NAMES)],
     f'{mo}-01', amount, 'USD',
     cc, 'MAIN', SAP_B1_GROUP.get(cat, 100), 'C')
    for i, (mo, cc, cat, amount, vi) in enumerate(SPEND_DATA)
])
print("  ✓ spend_sap_b1 (12 rows)")

# ── spend_dynamics ────────────────────────────────────────────────────────────
cur.execute("DELETE FROM spend_dynamics")
execute_values(cur, """
    INSERT INTO spend_dynamics (PurchaseOrderNumber, VendorAccountNumber, VendorName,
        OrderDate, TotalAmount, CurrencyCode, Department, BusinessUnit,
        LegalEntity, ItemGroup, Status)
    VALUES %s
""", [
    (f'PO-SP{str(i+1).zfill(5)}',
     VND_DYNAMICS[vi % len(VND_DYNAMICS)], VENDOR_NAMES[vi % len(VENDOR_NAMES)],
     f'{mo}-01', amount, 'USD',
     cc, 'BU-CORP', 'USMF', cat[:10], 'Invoiced')
    for i, (mo, cc, cat, amount, vi) in enumerate(SPEND_DATA)
])
print("  ✓ spend_dynamics (12 rows)")

# ── spend_oracle ──────────────────────────────────────────────────────────────
cur.execute("DELETE FROM spend_oracle")
execute_values(cur, """
    INSERT INTO spend_oracle (PONumber, SupplierNumber, SupplierName,
        OrderDate, Amount, CurrencyCode, Category, OperatingUnit, CostCenter, Status)
    VALUES %s
""", [
    (f'US-SP{str(i+1).zfill(5)}',
     VND_ORACLE[vi % len(VND_ORACLE)], VENDOR_NAMES[vi % len(VENDOR_NAMES)],
     f'{mo}-01', amount, 'USD', cat,
     'US-OPERATIONS', cc, 'CLOSED')
    for i, (mo, cc, cat, amount, vi) in enumerate(SPEND_DATA)
])
print("  ✓ spend_oracle (12 rows)")

# ── spend_erpnext ─────────────────────────────────────────────────────────────
cur.execute("DELETE FROM spend_erpnext")
execute_values(cur, """
    INSERT INTO spend_erpnext (name, supplier, supplier_name,
        transaction_date, grand_total, currency,
        cost_center, project, company, status)
    VALUES %s
""", [
    (f'PUR-ORD-SP-{str(i+1).zfill(5)}',
     VND_ERPNEXT[vi % len(VND_ERPNEXT)], VENDOR_NAMES[vi % len(VENDOR_NAMES)],
     f'{mo}-01', amount, 'USD',
     cc, 'Main Project', 'Procure-AI Demo Company', 'Submitted')
    for i, (mo, cc, cat, amount, vi) in enumerate(SPEND_DATA)
])
print("  ✓ spend_erpnext (12 rows)")

conn.commit()

# ── Final audit ───────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("SPRINT 5B SEED COMPLETE — Final row counts")
print("=" * 70)
modules = ['vendors','items','po_headers','po_lines','grn_headers','invoices','spend']
erps    = ['odoo','sap_s4','sap_b1','dynamics','oracle','erpnext']
print(f"{'Module':<18}", end='')
for e in erps:
    print(f"{e:<12}", end='')
print()
print('-'*90)
for mod in modules:
    print(f"{mod:<18}", end='')
    for erp in erps:
        cur.execute(f"SELECT COUNT(*) FROM {mod}_{erp}")
        n = cur.fetchone()[0]
        print(f"{n:<12}", end='')
    print()
cur.close()
conn.close()
