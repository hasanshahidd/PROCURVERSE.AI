"""
Sprint 11 — ERP Test Data Import from CSV Files
=================================================
Reads all CSV files from erp_test_data/ folder, auto-generates PostgreSQL
tables based on CSV headers + inferred types, and imports all rows.

This REPLACES the old simplified Sprint 5 ERP demo tables with richer,
more realistic ERP-native data (93 files × 100 rows = 9,300 rows).

Old system tables (agent_actions, approval_chains, etc.) are NOT touched.

Usage:
    python -m backend.migrations.sprint11_erp_csv_import [--csv-dir PATH] [--dry-run]
"""

import os
import sys
import csv
import re
import logging
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# ── Setup ────────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
log = logging.getLogger(__name__)

DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable is required. Set it in .env")

# Default CSV directory (can be overridden via --csv-dir)
DEFAULT_CSV_DIR = os.environ.get(
    'ERP_TEST_DATA_DIR',
    str(Path(__file__).resolve().parents[2] / 'erp_test_data')
)

# Tables we must NEVER drop (system tables from Sprints 1-8)
PROTECTED_TABLES = {
    # Sprint 1 NMI base tables
    'vendors', 'items', 'chart_of_accounts', 'cost_centers', 'employees',
    'exchange_rates', 'uom_master', 'tax_codes', 'payment_terms', 'warehouses',
    'companies', 'buyers', 'purchase_requisitions', 'approved_supplier_list',
    'vendor_evaluations', 'rfq_headers', 'vendor_quotes', 'quote_comparisons',
    'contracts', 'po_headers', 'po_line_items', 'po_amendments', 'po_approval_log',
    'blanket_pos', 'grn_headers', 'grn_line_items', 'qc_inspection_log',
    'returns_to_vendor', 'vendor_invoices', 'invoice_line_items',
    'three_way_match_log', 'invoice_exceptions', 'invoice_approval_log',
    'payment_proposals', 'payment_runs', 'payment_holds',
    'early_payment_discounts', 'ap_aging', 'spend_analytics',
    'budget_vs_actuals', 'vendor_performance', 'duplicate_invoice_log',
    'audit_trail', 'workflow_approval_matrix', 'integration_transaction_log',
    'data_ingestion_log',
    # Agent system tables
    'approval_chains', 'budget_tracking', 'agent_actions', 'agent_decisions',
    'pending_approvals', 'pr_approval_workflows', 'pr_approval_steps',
    'po_risk_assessments', 'approval_rules',
    # Sprint 6 pipeline tables
    'users', 'email_templates', 'notification_log', 'ocr_ingestion_log',
    'discrepancy_log', 'invoice_holds', 'payment_run_lines',
    # Sprint 5 registry
    'table_registry',
    # Chat
    'chat_messages', 'procurement_records',
}

# ERP folder → prefix mapping for table naming
ERP_PREFIXES = {
    'Odoo': 'odoo',
    'SAP': 'sap',
    'Dynamics365': 'd365',
    'Oracle': 'oracle',
    'ERPNext': 'erpnext',
}


def infer_pg_type(values: list[str]) -> str:
    """Infer PostgreSQL column type from ALL values (not just clean ones).

    Uses TEXT for any column with mixed/dirty data (INVALID_*, N/A in numeric cols).
    This ensures test data with intentional errors can always be imported.
    """
    # Look at ALL values to detect dirty data
    all_vals = [v.strip() for v in values if v.strip()]
    clean = [v for v in all_vals if v.upper() not in ('NULL', 'N/A', '', 'NONE', 'TBD', 'UNKNOWN')]
    if not clean:
        return 'TEXT'

    # If any value starts with INVALID_, TEMP, ERROR, XXX → always TEXT
    dirty_prefixes = ('INVALID', 'TEMP', 'ERROR', 'XXX', 'TBD', 'UNKNOWN', 'N/A')
    has_dirty = any(v.upper().startswith(dirty_prefixes) for v in all_vals)

    # Check integer — must be ALL values, not just first 30
    int_count = 0
    for v in clean:
        try:
            int(v)
            int_count += 1
        except ValueError:
            break
    if not has_dirty and int_count == len(clean) and int_count > 0:
        max_val = max(abs(int(v)) for v in clean)
        if max_val > 2_147_483_647:
            return 'BIGINT'
        return 'INTEGER'

    # Check decimal/float — must be ALL values
    decimal_count = 0
    for v in clean:
        try:
            Decimal(v.replace(',', ''))
            decimal_count += 1
        except (InvalidOperation, ValueError):
            break
    if not has_dirty and decimal_count == len(clean) and decimal_count > 0:
        return 'NUMERIC(18,4)'

    # Check date patterns — 90%+ threshold on ALL clean values
    date_patterns = [
        r'^\d{4}-\d{2}-\d{2}',  # 2025-01-15 or 2025-01-15T...
        r'^\d{2}/\d{2}/\d{4}',  # 01/15/2025
    ]
    if not has_dirty and len(clean) > 2:
        date_count = sum(1 for v in clean if any(re.match(p, v) for p in date_patterns))
        if date_count >= len(clean) * 0.9:
            if any('T' in v or ' ' in v.strip() for v in clean[:10]):
                return 'TIMESTAMP'
            return 'DATE'

    # Default to TEXT — safest for mixed/dirty ERP data
    return 'TEXT'


def sanitize_column_name(col: str) -> str:
    """Convert CSV header to valid PostgreSQL column name."""
    col = col.strip().strip('\ufeff')  # Remove BOM
    col = re.sub(r'[^a-zA-Z0-9_]', '_', col)
    col = re.sub(r'_+', '_', col).strip('_').lower()
    if col and col[0].isdigit():
        col = 'c_' + col
    # Avoid reserved words
    reserved = {'order', 'group', 'user', 'table', 'select', 'where', 'from', 'index', 'key', 'check', 'default', 'column', 'row', 'level', 'type', 'comment'}
    if col in reserved:
        col = col + '_val'
    return col or 'unnamed_col'


def csv_to_table_name(csv_filename: str) -> str:
    """Convert CSV filename to PostgreSQL table name."""
    name = Path(csv_filename).stem.lower()
    name = re.sub(r'[^a-z0-9_]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    # Prefix with 'erp_' if name starts with digit
    if name[0].isdigit():
        name = 'erp_' + name
    return name


def read_csv_file(filepath: str) -> tuple[list[str], list[list[str]]]:
    """Read CSV file, return (headers, rows)."""
    rows = []
    headers = []
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            rows.append(row)
    return headers, rows


def generate_create_table(table_name: str, headers: list[str], rows: list[list[str]]) -> str:
    """Generate CREATE TABLE DDL from CSV headers and sample data."""
    columns = []
    for i, raw_header in enumerate(headers):
        col_name = sanitize_column_name(raw_header)
        # Gather ALL values for this column (not just sample) to detect dirty data
        sample_values = [row[i] for row in rows if i < len(row)]
        pg_type = infer_pg_type(sample_values)
        columns.append(f'    {col_name} {pg_type}')

    cols_sql = ',\n'.join(columns)
    return f'CREATE TABLE IF NOT EXISTS {table_name} (\n    _row_id SERIAL PRIMARY KEY,\n{cols_sql}\n);'


def import_csv_to_table(cur, table_name: str, headers: list[str], rows: list[list[str]], col_names: list[str]):
    """Import CSV rows into an existing table using bulk insert."""
    if not rows:
        return 0

    cols_joined = ', '.join(col_names)
    template = '(' + ', '.join(['%s'] * len(col_names)) + ')'

    # Clean values: empty strings → None, strip whitespace
    cleaned_rows = []
    for row in rows:
        cleaned = []
        for i, val in enumerate(row):
            if i >= len(col_names):
                break
            val = val.strip() if val else ''
            if val == '' or val.upper() in ('NULL', 'NONE'):
                cleaned.append(None)
            else:
                cleaned.append(val)
        # Pad if row is shorter than headers
        while len(cleaned) < len(col_names):
            cleaned.append(None)
        cleaned_rows.append(tuple(cleaned))

    execute_values(
        cur,
        f'INSERT INTO {table_name} ({cols_joined}) VALUES %s',
        cleaned_rows,
        template=template,
        page_size=500
    )
    return len(cleaned_rows)


def discover_csv_files(csv_dir: str) -> dict[str, list[Path]]:
    """Discover CSV files organized by ERP folder."""
    result = {}
    csv_path = Path(csv_dir)

    # Handle nested erp_test_data/erp_test_data structure
    if (csv_path / 'erp_test_data').is_dir():
        csv_path = csv_path / 'erp_test_data'

    for erp_folder, prefix in ERP_PREFIXES.items():
        erp_path = csv_path / erp_folder
        if erp_path.is_dir():
            files = sorted(erp_path.glob('*.csv'))
            if files:
                result[erp_folder] = files

    return result


def run(csv_dir: str = None, dry_run: bool = False):
    """Main migration: discover CSVs, create tables, import data."""
    csv_dir = csv_dir or DEFAULT_CSV_DIR
    log.info(f"CSV source directory: {csv_dir}")
    log.info(f"Database: {DB_URL.split('@')[1] if '@' in DB_URL else DB_URL}")
    log.info(f"Dry run: {dry_run}")

    # Discover files
    erp_files = discover_csv_files(csv_dir)
    total_files = sum(len(files) for files in erp_files.values())
    log.info(f"Found {total_files} CSV files across {len(erp_files)} ERPs")

    if not erp_files:
        log.error(f"No CSV files found in {csv_dir}. Check the path.")
        return

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    created_tables = []
    skipped_tables = []
    imported_rows = 0
    errors = []

    try:
        for erp_name, files in erp_files.items():
            log.info(f"\n{'='*60}")
            log.info(f"Processing {erp_name}: {len(files)} files")
            log.info(f"{'='*60}")

            for csv_file in files:
                table_name = csv_to_table_name(csv_file.name)

                # Safety check: never touch protected tables
                if table_name in PROTECTED_TABLES:
                    log.warning(f"  SKIP {table_name} — protected system table")
                    skipped_tables.append(table_name)
                    continue

                try:
                    headers, rows = read_csv_file(str(csv_file))
                    col_names = [sanitize_column_name(h) for h in headers]

                    # Generate DDL
                    ddl = generate_create_table(table_name, headers, rows)

                    if dry_run:
                        log.info(f"  [DRY RUN] Would create {table_name} ({len(col_names)} cols, {len(rows)} rows)")
                        log.info(f"  DDL:\n{ddl}\n")
                        created_tables.append(table_name)
                        continue

                    # Drop old table if exists (only ERP data tables, never protected)
                    cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")

                    # Create table
                    cur.execute(ddl)
                    log.info(f"  CREATED {table_name} ({len(col_names)} cols)")

                    # Import data
                    count = import_csv_to_table(cur, table_name, headers, rows, col_names)
                    imported_rows += count
                    conn.commit()  # Commit each table individually
                    log.info(f"  IMPORTED {count} rows into {table_name}")

                    created_tables.append(table_name)

                except Exception as e:
                    errors.append((table_name, str(e)))
                    log.error(f"  ERROR {table_name}: {e}")
                    conn.rollback()
                    # Reconnect after error
                    conn = psycopg2.connect(DB_URL)
                    cur = conn.cursor()

        if not dry_run:
            # Update table_registry with new tables
            log.info(f"\nUpdating table_registry...")
            for table_name in created_tables:
                # Determine ERP from table prefix
                erp = 'unknown'
                for prefix_name, prefix in [('Odoo', 'odoo_'), ('SAP', 'sap_'), ('Dynamics365', 'd365_'), ('Oracle', 'oracle_'), ('ERPNext', 'erpnext_')]:
                    if table_name.startswith(prefix):
                        erp = prefix_name
                        break

                # Determine module from table name
                module = table_name.replace('odoo_', '').replace('sap_', '').replace('d365_', '').replace('oracle_', '').replace('erpnext_', '')

                try:
                    cur.execute("""
                        INSERT INTO table_registry (table_name, erp_system, module, row_count, created_at)
                        VALUES (%s, %s, %s, 100, NOW())
                        ON CONFLICT (table_name) DO UPDATE SET
                            erp_system = EXCLUDED.erp_system,
                            module = EXCLUDED.module,
                            row_count = 100,
                            created_at = NOW()
                    """, (table_name, erp, module))
                except Exception as e:
                    # table_registry might not have these exact columns — skip silently
                    log.debug(f"  Registry update skipped for {table_name}: {e}")
                    conn.rollback()
                    conn = psycopg2.connect(DB_URL)
                    cur = conn.cursor()

            conn.commit()

        # Summary
        log.info(f"\n{'='*60}")
        log.info(f"MIGRATION COMPLETE")
        log.info(f"{'='*60}")
        log.info(f"Tables created:  {len(created_tables)}")
        log.info(f"Tables skipped:  {len(skipped_tables)}")
        log.info(f"Rows imported:   {imported_rows}")
        log.info(f"Errors:          {len(errors)}")
        if errors:
            for tbl, err in errors:
                log.error(f"  {tbl}: {err}")

    finally:
        cur.close()
        conn.close()

    return {
        'tables_created': created_tables,
        'tables_skipped': skipped_tables,
        'rows_imported': imported_rows,
        'errors': errors,
    }


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Import ERP test data from CSV files')
    parser.add_argument('--csv-dir', default=DEFAULT_CSV_DIR, help='Path to erp_test_data folder')
    parser.add_argument('--dry-run', action='store_true', help='Print DDL without executing')
    args = parser.parse_args()
    run(csv_dir=args.csv_dir, dry_run=args.dry_run)
