"""
Payment Reconciliation Routes
===============================
POST /api/reconciliation/upload-statement  — Upload bank statement CSV
POST /api/reconciliation/run               — Run auto-matching
GET  /api/reconciliation/results           — List reconciliation results
GET  /api/reconciliation/exceptions        — List unmatched/exceptions
POST /api/reconciliation/resolve/{id}      — Resolve an exception
"""

import os, logging, csv, io
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import json, uuid

log = logging.getLogger(__name__)
router = APIRouter()
DB_URL = os.environ.get('DATABASE_URL')


class ResolveRequest(BaseModel):
    resolved_by: str = 'system'
    notes: str = ''


@router.post("/upload-statement")
async def upload_statement(file: UploadFile = File(...)):
    """Upload a bank statement CSV. Expected columns: date, description, debit, credit, balance, reference."""
    content = await file.read()
    text = content.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text))

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        rows_added = 0
        statement_ref = "STMT-%s" % datetime.now().strftime("%Y%m%d%H%M%S")

        for row in reader:
            cur.execute("""
                INSERT INTO bank_statements (statement_ref, transaction_date, description, debit_amount, credit_amount, balance, reference, currency)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'USD')
            """, (
                statement_ref,
                row.get('date', row.get('transaction_date', datetime.now().strftime('%Y-%m-%d'))),
                row.get('description', row.get('narration', '')),
                float(row.get('debit', row.get('debit_amount', 0)) or 0),
                float(row.get('credit', row.get('credit_amount', 0)) or 0),
                float(row.get('balance', 0) or 0),
                row.get('reference', row.get('ref', '')),
            ))
            rows_added += 1

        conn.commit()
        return {'success': True, 'statement_ref': statement_ref, 'rows_imported': rows_added}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.post("/run")
async def run_reconciliation():
    """Auto-match bank statement entries to payment runs."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        run_id = "RECON-%s" % datetime.now().strftime("%Y%m%d%H%M%S")

        # Get unmatched bank entries
        cur.execute("SELECT * FROM bank_statements WHERE matched = FALSE ORDER BY transaction_date")
        bank_rows = cur.fetchall()

        # Get payment runs
        cur.execute("SELECT * FROM payment_runs ORDER BY run_date DESC")
        payments = cur.fetchall()

        matched = 0
        exceptions = 0

        for bank in bank_rows:
            amount = float(bank.get('debit_amount') or bank.get('credit_amount') or 0)
            reference = str(bank.get('reference', '')).strip()
            description = str(bank.get('description', '')).strip()
            best_match = None
            best_confidence = 0

            for pay in payments:
                pay_amount = float(pay.get('total_amount', 0))
                pay_id = str(pay.get('payment_run_id', ''))

                # Match by reference
                if reference and pay_id and reference in pay_id:
                    best_match = pay
                    best_confidence = 95
                    break

                # Match by amount (within 1%)
                if pay_amount > 0 and abs(amount - pay_amount) / pay_amount < 0.01:
                    if best_confidence < 80:
                        best_match = pay
                        best_confidence = 80

            if best_match and best_confidence >= 70:
                # Matched
                cur.execute("""
                    INSERT INTO reconciliation_results (reconciliation_run_id, bank_statement_id, payment_run_id, bank_amount, ledger_amount, variance, match_status, match_confidence, reconciled_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'matched', %s, NOW())
                """, (run_id, bank['id'], best_match.get('payment_run_id', ''),
                      amount, float(best_match.get('total_amount', 0)),
                      abs(amount - float(best_match.get('total_amount', 0))),
                      best_confidence))
                cur.execute("UPDATE bank_statements SET matched = TRUE, matched_to = %s WHERE id = %s",
                           (best_match.get('payment_run_id', ''), bank['id']))
                matched += 1
            else:
                # Exception
                cur.execute("""
                    INSERT INTO reconciliation_exceptions (reconciliation_run_id, exception_type, description, bank_amount, reference, status)
                    VALUES (%s, 'unmatched', %s, %s, %s, 'open')
                """, (run_id, description[:200], amount, reference))
                exceptions += 1

        conn.commit()
        return {
            'success': True,
            'reconciliation_run_id': run_id,
            'bank_entries_processed': len(bank_rows),
            'matched': matched,
            'exceptions': exceptions,
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.get("/results")
async def list_results(limit: int = Query(50)):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM reconciliation_results ORDER BY reconciled_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'total': len(rows), 'results': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.get("/exceptions")
async def list_exceptions(status: Optional[str] = Query(None), limit: int = Query(50)):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if status:
            cur.execute("SELECT * FROM reconciliation_exceptions WHERE status = %s ORDER BY created_at DESC LIMIT %s", (status, limit))
        else:
            cur.execute("SELECT * FROM reconciliation_exceptions ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'total': len(rows), 'exceptions': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.post("/resolve/{exception_id}")
async def resolve_exception(exception_id: int, body: ResolveRequest):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE reconciliation_exceptions SET status = 'resolved', resolved_by = %s, resolved_at = NOW() WHERE id = %s AND status = 'open' RETURNING id", (body.resolved_by, exception_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Exception not found or already resolved")
        conn.commit()
        return {'success': True, 'exception_id': exception_id, 'status': 'resolved'}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()
