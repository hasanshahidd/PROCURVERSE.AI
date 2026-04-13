"""
Import Routes — File Upload & Data Import API
===============================================
POST /api/import/upload         — Upload single CSV/Excel file, auto-create table, import data
POST /api/import/upload-batch   — Upload multiple files at once
POST /api/import/preview        — Preview schema (dry-run) without importing
GET  /api/import/tables         — List all imported ERP tables
GET  /api/import/table/{name}   — Get table schema + sample data
DELETE /api/import/table/{name} — Drop an imported table
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import JSONResponse

from backend.services.file_import_service import (
    import_data, import_batch, read_file, generate_schema,
    sanitize_table_name,
)

log = logging.getLogger(__name__)
router = APIRouter()

DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

# Tables that must never be deleted via the import API
PROTECTED_PREFIXES = set()  # ERP tables are safe to manage
PROTECTED_TABLES = {
    'users', 'approval_chains', 'budget_tracking', 'agent_actions',
    'agent_decisions', 'pending_approvals', 'pr_approval_workflows',
    'pr_approval_steps', 'po_risk_assessments', 'approval_rules',
    'email_templates', 'notification_log', 'table_registry',
    'chat_messages', 'procurement_records',
}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    table_name: Optional[str] = Form(None),
    mode: str = Form("replace"),
    sheet_name: Optional[str] = Form(None),
):
    """Upload a single CSV or Excel file. Auto-creates table and imports data.

    Args:
        file: The CSV/Excel file to upload
        table_name: Override table name (default: derived from filename)
        mode: 'replace' (drop & recreate), 'append' (add to existing), 'skip_existing'
        sheet_name: For Excel files, specify which sheet to import
    """
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ('csv', 'xlsx', 'xls', 'xlsm', 'tsv'):
        raise HTTPException(400, f"Unsupported file type: .{ext}. Supported: .csv, .xlsx, .xls, .tsv")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(400, "File is empty")

    # 50 MB limit
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(400, "File too large. Maximum 50 MB.")

    log.info(f"Uploading {file.filename} ({len(file_bytes):,} bytes), mode={mode}")

    result = import_data(
        db_url=DB_URL,
        file_bytes=file_bytes,
        filename=file.filename,
        table_name=table_name,
        sheet_name=sheet_name,
        mode=mode,
    )

    if not result.get('success'):
        return JSONResponse(status_code=400, content=result)

    return result


@router.post("/upload-batch")
async def upload_batch(
    files: list[UploadFile] = File(...),
    mode: str = Form("replace"),
):
    """Upload multiple CSV/Excel files at once. Each file becomes its own table."""
    if not files:
        raise HTTPException(400, "No files provided")

    file_list = []
    for f in files:
        if not f.filename:
            continue
        data = await f.read()
        if data:
            file_list.append((data, f.filename))

    if not file_list:
        raise HTTPException(400, "No valid files provided")

    log.info(f"Batch upload: {len(file_list)} files, mode={mode}")

    result = import_batch(
        db_url=DB_URL,
        files=file_list,
        mode=mode,
    )

    status = 200 if result['success'] else 207  # 207 Multi-Status if partial
    return JSONResponse(status_code=status, content=result)


@router.post("/preview")
async def preview_schema(
    file: UploadFile = File(...),
    table_name: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
):
    """Preview the schema that would be generated from a file, without importing.
    Returns column names, inferred types, DDL, and row count.
    """
    if not file.filename:
        raise HTTPException(400, "No file provided")

    file_bytes = await file.read()
    result = import_data(
        db_url=DB_URL,
        file_bytes=file_bytes,
        filename=file.filename,
        table_name=table_name,
        sheet_name=sheet_name,
        dry_run=True,
    )
    return result


@router.get("/tables")
async def list_imported_tables(
    erp: Optional[str] = Query(None, description="Filter by ERP prefix: odoo, sap, d365, oracle, erpnext"),
):
    """List all ERP data tables with row counts."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    try:
        # Get all ERP table names
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        all_tables = [r[0] for r in cur.fetchall()]

        # Filter to ERP prefixes
        erp_prefixes = ['odoo_', 'sap_', 'd365_', 'oracle_', 'erpnext_', 'imported_']
        if erp:
            erp_prefixes = [erp.lower().replace(' ', '_') + '_']

        erp_tables = [t for t in all_tables if any(t.startswith(p) for p in erp_prefixes)]

        tables = []
        for tname in erp_tables:
            # Get column count
            cur.execute("SELECT count(*) FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public'", (tname,))
            col_count = cur.fetchone()[0]

            # Get row count
            try:
                cur.execute(f'SELECT count(*) FROM "{tname}"')
                row_count = cur.fetchone()[0]
            except Exception:
                conn.rollback()
                row_count = 0

            # Determine ERP label
            erp_name = 'unknown'
            for prefix, label in [('odoo_', 'Odoo'), ('sap_', 'SAP'), ('d365_', 'Dynamics365'),
                                   ('oracle_', 'Oracle'), ('erpnext_', 'ERPNext'), ('imported_', 'Imported')]:
                if tname.startswith(prefix):
                    erp_name = label
                    break

            tables.append({
                'table_name': tname,
                'erp': erp_name,
                'columns': col_count,
                'rows': row_count,
            })

        return {
            'total': len(tables),
            'tables': tables,
        }
    finally:
        cur.close()
        conn.close()


@router.get("/table/{table_name}")
async def get_table_details(
    table_name: str,
    limit: int = Query(20, ge=1, le=500),
):
    """Get table schema and sample data rows."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    tbl = sanitize_table_name(table_name)
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    try:
        # Check table exists
        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)", (tbl,))
        if not cur.fetchone()[0]:
            raise HTTPException(404, f"Table '{tbl}' not found")

        # Get columns
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (tbl,))
        columns = [{'name': r[0], 'type': r[1], 'nullable': r[2]} for r in cur.fetchall()]

        # Get row count
        cur.execute(f"SELECT count(*) FROM {tbl}")
        total_rows = cur.fetchone()[0]

        # Get sample data
        cur2 = conn.cursor(cursor_factory=RealDictCursor)
        cur2.execute(f"SELECT * FROM {tbl} LIMIT %s", (limit,))
        sample_data = cur2.fetchall()
        cur2.close()

        # Convert any non-serializable types
        for row in sample_data:
            for k, v in row.items():
                if isinstance(v, (Decimal,)):
                    row[k] = float(v)
                elif hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()

        return {
            'table_name': tbl,
            'columns': columns,
            'total_rows': total_rows,
            'sample_data': sample_data,
            'sample_limit': limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        cur.close()
        conn.close()


@router.delete("/table/{table_name}")
async def delete_table(table_name: str):
    """Drop an imported ERP data table. Protected system tables cannot be deleted."""
    import psycopg2

    tbl = sanitize_table_name(table_name)

    if tbl in PROTECTED_TABLES:
        raise HTTPException(403, f"Table '{tbl}' is a protected system table and cannot be deleted")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    try:
        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)", (tbl,))
        if not cur.fetchone()[0]:
            raise HTTPException(404, f"Table '{tbl}' not found")

        cur.execute(f"DROP TABLE {tbl} CASCADE")
        conn.commit()

        return {'success': True, 'message': f"Table '{tbl}' deleted", 'table_name': tbl}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close()
        conn.close()


# Need this for Decimal serialization
from decimal import Decimal
