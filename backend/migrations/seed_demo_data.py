"""
Seed missing demo data for all agents.
Run: python -m backend.migrations.seed_demo_data
"""
import os
import psycopg2
from datetime import datetime

DB = os.environ.get('DATABASE_URL', 'postgresql://postgres:YourStr0ng!Pass@127.0.0.1:5433/odoo_procurement_demo')
conn = psycopg2.connect(DB)
cur = conn.cursor()


def seed_bank_statements():
    cur.execute('SELECT count(*) FROM bank_statements')
    if cur.fetchone()[0] > 0:
        print('  bank_statements: already has data, skipping')
        return
    stmts = []
    banks = ['HSBC', 'Standard Chartered', 'Meezan Bank', 'HBL', 'UBL']
    for i in range(1, 21):
        ref = f'PAY-REF-{2026000 + i}'
        amt = round(1000 + (i * 573.25) % 9000, 2)
        stmts.append((
            f'BS-{i:04d}',
            banks[i % len(banks)],
            f'ACC-{1000 + i}',
            datetime(2026, 4, max(1, i % 28 + 1)),
            datetime(2026, 4, max(1, (i % 28) + 2)),
            f'Payment to vendor #{i} for PO supplies',
            amt if i % 3 != 0 else 0,
            0 if i % 3 != 0 else amt,
            round(50000 + i * 1200, 2),
            ref, 'USD', False
        ))
    cur.executemany(
        """INSERT INTO bank_statements
           (statement_ref, bank_name, account_number, transaction_date,
            value_date, description, debit_amount, credit_amount,
            balance, reference, currency, matched)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
        stmts)
    print(f'  bank_statements: inserted {len(stmts)} rows')


def seed_payment_run_lines():
    cur.execute('SELECT count(*) FROM payment_run_lines')
    if cur.fetchone()[0] > 0:
        print('  payment_run_lines: already has data, skipping')
        return
    # Insert new payment_runs with realistic data, then link lines
    vendors = [
        ('TechSupply Co', 15000), ('Industrial Parts Inc', 8500),
        ('Office Depot LLC', 3200), ('Dell', 22000), ('Ready Mat', 4800),
    ]
    inserted = 0
    for v_name, amt in vendors:
        run_id = f'PR-{v_name[:4].upper()}-2026-04'
        cur.execute(
            """INSERT INTO payment_runs
               (payment_run_id, run_date, currency, total_amount, invoice_count,
                status, payment_method, agent_name)
               VALUES (%s, %s, 'USD', %s, 1, 'completed', 'bank_transfer', 'SeedScript')
               ON CONFLICT DO NOTHING RETURNING id""",
            (run_id, datetime(2026, 4, 8).date(), amt))
        row = cur.fetchone()
        if row:
            # FK references payment_run_id (VARCHAR), not id (INT)
            cur.execute(
                """INSERT INTO payment_run_lines
                   (payment_run_id, invoice_number, vendor_id, vendor_name,
                    invoice_amount, payment_amount, payment_type, payment_pct,
                    due_date, payment_terms, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'full', 100.0, %s, 'Net 30', 'paid')""",
                (run_id, f'INV-{v_name[:3].upper()}-001', f'V-{v_name[:3].upper()}',
                 v_name, amt, amt, datetime(2026, 4, 30).date()))
            inserted += 1
    print(f'  payment_runs + lines: inserted {inserted} pairs')


def ensure_nmi_tables():
    """Create NMI tables if they don't exist."""
    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='nmi_spend_analytics')")
    if not cur.fetchone()[0]:
        cur.execute("""CREATE TABLE nmi_spend_analytics (
            id SERIAL PRIMARY KEY,
            vendor_name VARCHAR(200), vendor_id VARCHAR(50),
            category VARCHAR(100), spend_category VARCHAR(100),
            cost_center VARCHAR(100), department VARCHAR(100),
            period VARCHAR(20), total_amount_usd NUMERIC(15,2) DEFAULT 0,
            transaction_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW()
        )""")
        print('  Created nmi_spend_analytics')

    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='nmi_items')")
    if not cur.fetchone()[0]:
        cur.execute("""CREATE TABLE nmi_items (
            id SERIAL PRIMARY KEY,
            item_code VARCHAR(50) UNIQUE, item_description VARCHAR(300),
            category VARCHAR(100), sub_category VARCHAR(100),
            total_received NUMERIC(10,2) DEFAULT 0,
            reorder_point NUMERIC(10,2) DEFAULT 50,
            safety_stock NUMERIC(10,2) DEFAULT 20,
            active BOOLEAN DEFAULT TRUE, item_type VARCHAR(50) DEFAULT 'stock',
            lead_time_days INTEGER DEFAULT 7, min_order_qty NUMERIC(10,2) DEFAULT 10,
            last_receipt_date DATE, created_at TIMESTAMP DEFAULT NOW()
        )""")
        print('  Created nmi_items')

    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='nmi_approved_suppliers')")
    if not cur.fetchone()[0]:
        cur.execute("""CREATE TABLE nmi_approved_suppliers (
            id SERIAL PRIMARY KEY,
            item_code VARCHAR(50), vendor_name VARCHAR(200),
            vendor_lead_time INTEGER DEFAULT 7,
            vendor_min_qty NUMERIC(10,2) DEFAULT 1,
            preferred_rank INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT NOW()
        )""")
        print('  Created nmi_approved_suppliers')


def seed_spend_analytics():
    cur.execute('SELECT count(*) FROM nmi_spend_analytics')
    if cur.fetchone()[0] > 0:
        print('  nmi_spend_analytics: already has data, skipping')
        return
    depts = ['IT', 'Finance', 'Operations', 'Procurement', 'HR']
    vendors = ['TechSupply Co', 'Industrial Parts Inc', 'Office Depot LLC', 'Dell', 'Ready Mat']
    cats = ['Electronics', 'Office Supplies', 'IT Hardware', 'Furniture', 'Software']
    rows = []
    for month in range(1, 5):
        for d_idx, dept in enumerate(depts):
            for v_idx in range(2):
                v = vendors[(d_idx + v_idx) % len(vendors)]
                c = cats[(d_idx + v_idx) % len(cats)]
                amt = round(5000 + (d_idx * 3000) + (month * 1500) + (v_idx * 2000), 2)
                rows.append((v, f'V-{d_idx+1}{v_idx+1}', c, c, dept, dept,
                             f'2026-{month:02d}', amt, 3 + v_idx * 2))
    cur.executemany(
        """INSERT INTO nmi_spend_analytics
           (vendor_name, vendor_id, category, spend_category, cost_center,
            department, period, total_amount_usd, transaction_count)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        rows)
    print(f'  nmi_spend_analytics: inserted {len(rows)} rows')


def seed_inventory():
    cur.execute('SELECT count(*) FROM nmi_items')
    if cur.fetchone()[0] > 0:
        print('  nmi_items: already has data, skipping')
        return
    items = [
        ('ITM-001', 'Dell Monitor 27"', 'Electronics', 'Monitors', 15, 20, 10, 7, 5),
        ('ITM-002', 'Mechanical Keyboard', 'Electronics', 'Peripherals', 45, 30, 15, 5, 10),
        ('ITM-003', 'Office Chair Ergonomic', 'Furniture', 'Seating', 8, 15, 5, 14, 3),
        ('ITM-004', 'A4 Paper Ream', 'Office Supplies', 'Paper', 200, 100, 50, 3, 20),
        ('ITM-005', 'Laptop Stand', 'Electronics', 'Accessories', 5, 10, 5, 7, 5),
        ('ITM-006', 'USB-C Hub', 'Electronics', 'Accessories', 3, 15, 8, 5, 10),
        ('ITM-007', 'Whiteboard Marker Set', 'Office Supplies', 'Writing', 150, 50, 25, 3, 30),
        ('ITM-008', 'Server Rack 42U', 'IT Hardware', 'Infrastructure', 2, 3, 1, 21, 1),
        ('ITM-009', 'CAT6 Cable 100m', 'IT Hardware', 'Networking', 12, 20, 10, 5, 5),
        ('ITM-010', 'Desk Lamp LED', 'Furniture', 'Lighting', 30, 25, 10, 7, 5),
    ]
    for code, desc, cat, sub, recv, reorder, safety, lead, moq in items:
        cur.execute(
            """INSERT INTO nmi_items
               (item_code, item_description, category, sub_category,
                total_received, reorder_point, safety_stock,
                lead_time_days, min_order_qty, last_receipt_date)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (code, desc, cat, sub, recv, reorder, safety, lead, moq,
             datetime(2026, 3, 15).date()))
    print(f'  nmi_items: inserted {len(items)} rows')

    # Approved suppliers
    cur.execute('SELECT count(*) FROM nmi_approved_suppliers')
    if cur.fetchone()[0] > 0:
        print('  nmi_approved_suppliers: already has data, skipping')
        return
    suppliers = [
        ('ITM-001', 'Dell', 5, 3, 1), ('ITM-001', 'TechSupply Co', 7, 5, 2),
        ('ITM-002', 'TechSupply Co', 5, 10, 1), ('ITM-003', 'Office Depot LLC', 10, 3, 1),
        ('ITM-005', 'Dell', 7, 5, 1), ('ITM-006', 'TechSupply Co', 5, 10, 1),
        ('ITM-008', 'Industrial Parts Inc', 21, 1, 1), ('ITM-009', 'TechSupply Co', 5, 5, 1),
    ]
    for code, vendor, lead, moq, rank in suppliers:
        cur.execute(
            """INSERT INTO nmi_approved_suppliers
               (item_code, vendor_name, vendor_lead_time, vendor_min_qty, preferred_rank)
               VALUES (%s,%s,%s,%s,%s)""",
            (code, vendor, lead, moq, rank))
    print(f'  nmi_approved_suppliers: inserted {len(suppliers)} rows')


def reset_budgets():
    """Reset committed budgets so all departments have reasonable available funds."""
    resets = [
        ('IT', 'CAPEX', 500000), ('IT', 'OPEX', 200000),
        ('Finance', 'CAPEX', 100000), ('Finance', 'OPEX', 50000),
        ('Operations', 'CAPEX', 500000), ('Operations', 'OPEX', 200000),
        ('Procurement', 'CAPEX', 100000), ('Procurement', 'OPEX', 50000),
    ]
    for dept, cat, committed in resets:
        cur.execute(
            'UPDATE budget_tracking SET committed_budget = %s WHERE department = %s AND budget_category = %s',
            (committed, dept, cat))
        if cur.rowcount > 0:
            print(f'  budget: {dept} {cat} committed -> ${committed:,}')


def fix_notification_log():
    """Make recipient_email nullable if it isn't already."""
    cur.execute("""
        SELECT is_nullable FROM information_schema.columns
        WHERE table_name = 'notification_log' AND column_name = 'recipient_email'
    """)
    row = cur.fetchone()
    if row and row[0] == 'NO':
        cur.execute('ALTER TABLE notification_log ALTER COLUMN recipient_email DROP NOT NULL')
        print('  notification_log: recipient_email made nullable')
    else:
        print('  notification_log: recipient_email already nullable')


def verify():
    print('\n=== VERIFICATION ===')
    tables = ['bank_statements', 'payment_run_lines', 'nmi_spend_analytics',
              'nmi_items', 'nmi_approved_suppliers', 'qc_templates', 'qc_results',
              'procurement_records', 'odoo_invoices', 'payment_runs']
    for t in tables:
        try:
            cur.execute(f'SELECT count(*) FROM {t}')
            print(f'  {t:35s} {cur.fetchone()[0]:5d} rows')
        except Exception:
            conn.rollback()
            print(f'  {t:35s} ERROR')

    print()
    cur.execute(
        'SELECT department, budget_category, available_budget FROM budget_tracking ORDER BY department, budget_category')
    for r in cur.fetchall():
        print(f'  Budget: {r[0]:15s} {r[1]:6s}  available = ${r[2]:>12,.2f}')


if __name__ == '__main__':
    print('=== SEEDING DEMO DATA ===')
    seed_bank_statements()
    seed_payment_run_lines()
    ensure_nmi_tables()
    seed_spend_analytics()
    seed_inventory()
    reset_budgets()
    fix_notification_log()
    conn.commit()
    verify()
    cur.close()
    conn.close()
    print('\nDone.')
