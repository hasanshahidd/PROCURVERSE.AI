"""
Audit Routes — Export audit trail
===================================
GET /api/audit/export       — Export agent_actions as CSV
GET /api/audit/summary      — Audit summary stats
GET /api/audit/accruals     — Outstanding GRNi accruals
GET /api/audit/debit-notes  — Issued debit notes
"""
import os, logging, csv, io
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)
router = APIRouter()
DB_URL = os.environ.get('DATABASE_URL')


@router.get("/export")
async def export_audit(
    agent: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    """Export agent_actions as CSV."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if agent:
            cur.execute("SELECT agent_name, action_type, success, error_message, execution_time_ms, created_at FROM agent_actions WHERE agent_name ILIKE %s AND created_at > NOW() - INTERVAL '%s days' ORDER BY created_at DESC", (agent, days))
        else:
            cur.execute("SELECT agent_name, action_type, success, error_message, execution_time_ms, created_at FROM agent_actions WHERE created_at > NOW() - INTERVAL '%s days' ORDER BY created_at DESC LIMIT 5000" % days)
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['agent_name', 'action_type', 'success', 'error_message', 'execution_time_ms', 'created_at'])
        writer.writeheader()
        for r in rows:
            r['created_at'] = r['created_at'].isoformat() if r.get('created_at') else ''
            writer.writerow(r)

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_trail.csv"},
        )
    finally:
        cur.close(); conn.close()


@router.get("/summary")
async def audit_summary(days: int = Query(30)):
    """Audit summary — agent activity, success rates, timing."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT agent_name,
                   COUNT(*) as total_actions,
                   SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                   SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
                   ROUND(AVG(execution_time_ms)) as avg_time_ms
            FROM agent_actions
            WHERE created_at > NOW() - INTERVAL '%s days'
            GROUP BY agent_name
            ORDER BY total_actions DESC
        """ % days)
        agents = cur.fetchall()

        cur.execute("SELECT count(*) as total FROM agent_actions WHERE created_at > NOW() - INTERVAL '%s days'" % days)
        total = cur.fetchone()['total']

        for a in agents:
            for k, v in a.items():
                if isinstance(v, __import__('decimal').Decimal): a[k] = float(v)

        return {
            'total_actions': total,
            'period_days': days,
            'agents': [dict(a) for a in agents],
        }
    finally:
        cur.close(); conn.close()


@router.get("/accruals")
async def list_accruals(status: Optional[str] = Query(None)):
    """List outstanding GRNi accruals."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if status:
            cur.execute("SELECT * FROM accruals WHERE status = %s ORDER BY created_at DESC", (status,))
        else:
            cur.execute("SELECT * FROM accruals ORDER BY created_at DESC LIMIT 100")
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'total': len(rows), 'accruals': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.get("/debit-notes")
async def list_debit_notes(status: Optional[str] = Query(None)):
    """List issued debit notes."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if status:
            cur.execute("SELECT * FROM debit_notes WHERE status = %s ORDER BY created_at DESC", (status,))
        else:
            cur.execute("SELECT * FROM debit_notes ORDER BY created_at DESC LIMIT 100")
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'total': len(rows), 'debit_notes': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()
