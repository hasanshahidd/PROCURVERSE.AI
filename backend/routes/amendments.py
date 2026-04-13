"""
PO Amendment Routes
====================
POST /api/amendments/create        — Create amendment for a PO
GET  /api/amendments/list          — List all amendments
GET  /api/amendments/{po_number}   — Get amendments for a specific PO
POST /api/amendments/{id}/approve  — Approve an amendment
"""

import os, logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)
router = APIRouter()
DB_URL = os.environ.get('DATABASE_URL')


class CreateAmendmentRequest(BaseModel):
    po_number: str
    amendment_type: str  # quantity_change, price_change, date_change, item_add, item_remove
    reason: str = ''
    old_value: str = ''
    new_value: str = ''
    amount_impact: float = 0
    requested_by: str = 'system'


@router.post("/create")
async def create_amendment(body: CreateAmendmentRequest):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        amendment_number = "AMD-%s" % datetime.now().strftime("%Y%m%d%H%M%S")
        requires_approval = abs(body.amount_impact) > 5000  # Re-approve if >$5K impact

        cur.execute("""
            INSERT INTO po_amendments (amendment_number, po_number, amendment_type, reason, old_value, new_value, amount_impact, status, requested_by, requires_re_approval)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, amendment_number
        """, (amendment_number, body.po_number, body.amendment_type, body.reason,
              body.old_value, body.new_value, body.amount_impact,
              'pending_approval' if requires_approval else 'approved',
              body.requested_by, requires_approval))
        row = cur.fetchone()
        conn.commit()

        # Notification
        try:
            from backend.services.adapters.factory import get_adapter
            get_adapter().log_notification({
                'event_type': 'po_amendment_created',
                'document_type': 'PO_AMENDMENT',
                'document_id': amendment_number,
                'recipient_role': 'procurement',
                'subject': 'PO Amendment: %s for %s' % (body.amendment_type, body.po_number),
                'body_preview': 'Change: %s -> %s (impact: $%.2f)' % (body.old_value, body.new_value, body.amount_impact),
                'status': 'pending',
                'agent_name': 'AmendmentSystem',
            })
        except Exception:
            pass

        return {
            'success': True,
            'amendment_number': row['amendment_number'],
            'requires_approval': requires_approval,
            'status': 'pending_approval' if requires_approval else 'approved',
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.get("/list")
async def list_amendments(po_number: Optional[str] = Query(None), limit: int = Query(50)):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if po_number:
            cur.execute("SELECT * FROM po_amendments WHERE po_number = %s ORDER BY created_at DESC LIMIT %s", (po_number, limit))
        else:
            cur.execute("SELECT * FROM po_amendments ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'total': len(rows), 'amendments': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.get("/{po_number}")
async def get_po_amendments(po_number: str):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM po_amendments WHERE po_number = %s ORDER BY created_at DESC", (po_number,))
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'po_number': po_number, 'amendments': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.post("/{amendment_id}/approve")
async def approve_amendment(amendment_id: int):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE po_amendments SET status = 'approved', approved_at = NOW() WHERE id = %s AND status = 'pending_approval' RETURNING amendment_number", (amendment_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Amendment not found or already processed")
        conn.commit()
        return {'success': True, 'amendment_number': row[0], 'status': 'approved'}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()
