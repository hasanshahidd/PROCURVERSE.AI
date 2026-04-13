"""
RTV Routes — Return to Vendor
===============================
POST /api/rtv/create          — Create return from GRN
GET  /api/rtv/list            — List all returns
GET  /api/rtv/{id}            — Get return details
POST /api/rtv/{id}/approve    — Approve return
POST /api/rtv/{id}/ship       — Mark as shipped back to vendor
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


class CreateRTVRequest(BaseModel):
    grn_number: str = ''
    po_number: str = ''
    vendor_id: str = ''
    vendor_name: str = ''
    return_reason: str = 'quality_failure'
    return_type: str = 'quality_failure'  # quality_failure, wrong_item, damaged, excess
    initiated_by: str = 'system'
    items: list = []  # [{item_name, return_qty, unit_price, reason_code, condition, inspection_notes}]


@router.post("/create")
async def create_rtv(body: CreateRTVRequest):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        rtv_number = "RTV-%s" % datetime.now().strftime("%Y%m%d%H%M%S")
        total_qty = sum(float(i.get('return_qty', 0)) for i in body.items)
        total_value = sum(float(i.get('return_qty', 0)) * float(i.get('unit_price', 0)) for i in body.items)

        cur.execute("""
            INSERT INTO rtv_headers (rtv_number, grn_number, po_number, vendor_id, vendor_name, return_reason, return_type, total_return_qty, total_return_value, credit_expected, status, initiated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'initiated', %s)
            RETURNING id, rtv_number
        """, (rtv_number, body.grn_number, body.po_number, body.vendor_id, body.vendor_name,
              body.return_reason, body.return_type, total_qty, total_value, total_value, body.initiated_by))
        header = cur.fetchone()
        rtv_id = header['id']

        for item in body.items:
            cur.execute("""
                INSERT INTO rtv_lines (rtv_id, item_name, return_qty, unit_price, return_value, reason_code, condition, inspection_notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (rtv_id, item.get('item_name', ''), item.get('return_qty', 0), item.get('unit_price', 0),
                  float(item.get('return_qty', 0)) * float(item.get('unit_price', 0)),
                  item.get('reason_code', 'quality'), item.get('condition', 'damaged'), item.get('inspection_notes', '')))

        conn.commit()

        try:
            from backend.services.adapters.factory import get_adapter
            get_adapter().log_notification({
                'event_type': 'rtv_created',
                'document_type': 'RTV',
                'document_id': rtv_number,
                'recipient_role': 'procurement',
                'subject': 'Return to Vendor: %s' % body.vendor_name,
                'body_preview': '%d items, credit expected: $%.2f' % (len(body.items), total_value),
                'status': 'pending',
                'agent_name': 'RTVSystem',
            })
        except Exception:
            pass

        return {'success': True, 'rtv_number': rtv_number, 'rtv_id': rtv_id, 'total_qty': total_qty, 'credit_expected': total_value}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.get("/list")
async def list_rtvs(status: Optional[str] = Query(None), limit: int = Query(50)):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if status:
            cur.execute("SELECT * FROM rtv_headers WHERE status = %s ORDER BY created_at DESC LIMIT %s", (status, limit))
        else:
            cur.execute("SELECT * FROM rtv_headers ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'total': len(rows), 'returns': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.get("/{rtv_id}")
async def get_rtv(rtv_id: int):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM rtv_headers WHERE id = %s", (rtv_id,))
        header = cur.fetchone()
        if not header:
            raise HTTPException(404, "RTV not found")
        cur.execute("SELECT * FROM rtv_lines WHERE rtv_id = %s", (rtv_id,))
        lines = cur.fetchall()
        for obj in [header] + lines:
            for k, v in obj.items():
                if hasattr(v, 'isoformat'): obj[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): obj[k] = float(v)
        return {'header': dict(header), 'lines': [dict(l) for l in lines]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.post("/{rtv_id}/approve")
async def approve_rtv(rtv_id: int):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE rtv_headers SET status = 'approved' WHERE id = %s AND status = 'initiated' RETURNING rtv_number", (rtv_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "RTV not found or not in initiated status")
        conn.commit()
        return {'success': True, 'rtv_number': row[0], 'status': 'approved'}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.post("/{rtv_id}/ship")
async def ship_rtv(rtv_id: int):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE rtv_headers SET status = 'shipped', shipped_date = CURRENT_DATE WHERE id = %s AND status = 'approved' RETURNING rtv_number", (rtv_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "RTV not found or not approved")
        conn.commit()
        return {'success': True, 'rtv_number': row[0], 'status': 'shipped'}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()
