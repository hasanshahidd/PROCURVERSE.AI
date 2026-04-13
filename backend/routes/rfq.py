"""
RFQ Routes — Request for Quotation Management
===============================================
POST /api/rfq/create              — Create RFQ from PR
POST /api/rfq/{id}/add-line       — Add item line to RFQ
POST /api/rfq/{id}/send           — Send RFQ to vendors (status → sent)
POST /api/rfq/{id}/quote          — Vendor submits a quote
GET  /api/rfq/{id}/compare        — Compare all quotes for an RFQ
POST /api/rfq/{id}/award          — Award to winning vendor → creates PO
GET  /api/rfq/list                — List all RFQs
GET  /api/rfq/{id}                — Get RFQ details with lines + quotes
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)
router = APIRouter()

DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    raise RuntimeError("DATABASE_URL required")


def _conn():
    return psycopg2.connect(DB_URL)


# ── Request Models ───────────────────────────────────────────────────────────

class CreateRFQRequest(BaseModel):
    title: str
    pr_number: Optional[str] = None
    department: str = ''
    requester: str = ''
    description: str = ''
    submission_deadline_days: int = 14
    items: list = []  # list of {item_name, quantity, unit_of_measure, estimated_price, specifications}


class AddLineRequest(BaseModel):
    item_name: str
    quantity: float = 1
    unit_of_measure: str = 'EA'
    estimated_price: float = 0
    specifications: str = ''
    description: str = ''


class SubmitQuoteRequest(BaseModel):
    vendor_id: str
    vendor_name: str
    items: list = []  # list of {item_name, unit_price, lead_time_days, total_price}


class AwardRequest(BaseModel):
    vendor_id: str
    vendor_name: str
    notes: str = ''


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/create")
async def create_rfq(body: CreateRFQRequest):
    """Create a new RFQ, optionally linked to a PR."""
    conn = _conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        rfq_number = "RFQ-%s" % datetime.now().strftime("%Y%m%d%H%M%S")
        deadline = (datetime.now() + timedelta(days=body.submission_deadline_days)).strftime('%Y-%m-%d')

        cur.execute("""
            INSERT INTO rfq_headers (rfq_number, pr_number, title, description, department, requester, status, submission_deadline)
            VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s)
            RETURNING id, rfq_number
        """, (rfq_number, body.pr_number, body.title, body.description, body.department, body.requester, deadline))
        row = cur.fetchone()
        rfq_id = row['id']

        # Add item lines
        lines_added = 0
        for item in body.items:
            cur.execute("""
                INSERT INTO rfq_lines (rfq_id, item_name, description, quantity, unit_of_measure, estimated_price, specifications)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (rfq_id, item.get('item_name', ''), item.get('description', ''),
                  item.get('quantity', 1), item.get('unit_of_measure', 'EA'),
                  item.get('estimated_price', 0), item.get('specifications', '')))
            lines_added += 1

        conn.commit()

        # Log notification
        try:
            from backend.services.adapters.factory import get_adapter
            get_adapter().log_notification({
                'event_type': 'rfq_created',
                'document_type': 'RFQ',
                'document_id': rfq_number,
                'recipient_role': 'procurement',
                'subject': 'New RFQ: %s' % body.title,
                'body_preview': 'RFQ %s created with %d items' % (rfq_number, lines_added),
                'status': 'pending',
                'agent_name': 'RFQSystem',
            })
        except Exception:
            pass

        return {
            'success': True,
            'rfq_id': rfq_id,
            'rfq_number': rfq_number,
            'lines_added': lines_added,
            'status': 'draft',
            'deadline': deadline,
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.post("/{rfq_id}/add-line")
async def add_rfq_line(rfq_id: int, body: AddLineRequest):
    """Add an item line to an existing RFQ."""
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT status FROM rfq_headers WHERE id = %s", (rfq_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "RFQ not found")
        if row[0] not in ('draft', 'sent'):
            raise HTTPException(400, "Cannot add lines to RFQ in status: %s" % row[0])

        cur.execute("""
            INSERT INTO rfq_lines (rfq_id, item_name, description, quantity, unit_of_measure, estimated_price, specifications)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (rfq_id, body.item_name, body.description, body.quantity, body.unit_of_measure, body.estimated_price, body.specifications))
        conn.commit()
        return {'success': True, 'line_id': cur.fetchone()[0]}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.post("/{rfq_id}/send")
async def send_rfq(rfq_id: int):
    """Mark RFQ as sent to vendors."""
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE rfq_headers SET status = 'sent', updated_at = NOW() WHERE id = %s AND status = 'draft' RETURNING rfq_number", (rfq_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(400, "RFQ not found or not in draft status")
        conn.commit()

        # Notification
        try:
            from backend.services.adapters.factory import get_adapter
            get_adapter().log_notification({
                'event_type': 'rfq_sent',
                'document_type': 'RFQ',
                'document_id': row[0],
                'recipient_role': 'procurement',
                'subject': 'RFQ %s sent to vendors' % row[0],
                'status': 'pending',
                'agent_name': 'RFQSystem',
            })
        except Exception:
            pass

        return {'success': True, 'rfq_number': row[0], 'status': 'sent'}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.post("/{rfq_id}/quote")
async def submit_quote(rfq_id: int, body: SubmitQuoteRequest):
    """Vendor submits a quote for an RFQ."""
    conn = _conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT rfq_number, status FROM rfq_headers WHERE id = %s", (rfq_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "RFQ not found")
        if row[1] not in ('sent', 'evaluation'):
            raise HTTPException(400, "RFQ not accepting quotes (status: %s)" % row[1])

        quotes_added = 0
        for item in body.items:
            cur.execute("""
                INSERT INTO vendor_quotes (rfq_id, vendor_id, vendor_name, item_name, unit_price, lead_time_days, total_price, currency, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'USD', 'submitted')
            """, (rfq_id, body.vendor_id, body.vendor_name,
                  item.get('item_name', ''), item.get('unit_price', 0),
                  item.get('lead_time_days', 14), item.get('total_price', 0)))
            quotes_added += 1

        # Update quote count
        cur.execute("UPDATE rfq_headers SET quotes_received = quotes_received + 1, status = 'evaluation', updated_at = NOW() WHERE id = %s", (rfq_id,))
        conn.commit()
        return {'success': True, 'quotes_added': quotes_added, 'vendor': body.vendor_name}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.get("/{rfq_id}/compare")
async def compare_quotes(rfq_id: int):
    """Compare all vendor quotes for an RFQ with scoring."""
    conn = _conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get RFQ
        cur.execute("SELECT * FROM rfq_headers WHERE id = %s", (rfq_id,))
        rfq = cur.fetchone()
        if not rfq:
            raise HTTPException(404, "RFQ not found")

        # Get all quotes
        cur.execute("SELECT * FROM vendor_quotes WHERE rfq_id = %s ORDER BY unit_price ASC", (rfq_id,))
        quotes = cur.fetchall()

        if not quotes:
            return {'rfq': dict(rfq), 'quotes': [], 'recommendation': None}

        # Score each quote (price 40%, lead time 30%, vendor 30%)
        min_price = min(float(q['unit_price'] or 1) for q in quotes)
        min_lead = min(int(q['lead_time_days'] or 1) for q in quotes)

        scored = []
        for q in quotes:
            price_score = (min_price / max(float(q['unit_price'] or 1), 0.01)) * 40
            lead_score = (min_lead / max(int(q['lead_time_days'] or 1), 1)) * 30
            vendor_score = 30  # Base score (could be enhanced with vendor performance data)
            total_score = round(price_score + lead_score + vendor_score, 1)
            scored.append({
                'quote_id': q['id'],
                'vendor_id': q['vendor_id'],
                'vendor_name': q['vendor_name'],
                'item_name': q['item_name'],
                'unit_price': float(q['unit_price'] or 0),
                'lead_time_days': int(q['lead_time_days'] or 0),
                'total_price': float(q['total_price'] or 0),
                'price_score': round(price_score, 1),
                'lead_score': round(lead_score, 1),
                'vendor_score': vendor_score,
                'total_score': total_score,
                'recommended': False,
            })

        # Mark top scorer
        scored.sort(key=lambda x: x['total_score'], reverse=True)
        if scored:
            scored[0]['recommended'] = True

        # Serialize rfq
        rfq_dict = dict(rfq)
        for k, v in rfq_dict.items():
            if hasattr(v, 'isoformat'):
                rfq_dict[k] = v.isoformat()

        return {
            'rfq': rfq_dict,
            'quotes': scored,
            'recommendation': {
                'vendor_id': scored[0]['vendor_id'],
                'vendor_name': scored[0]['vendor_name'],
                'score': scored[0]['total_score'],
                'unit_price': scored[0]['unit_price'],
            } if scored else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.post("/{rfq_id}/award")
async def award_rfq(rfq_id: int, body: AwardRequest):
    """Award RFQ to winning vendor. Optionally creates PO."""
    conn = _conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM rfq_headers WHERE id = %s", (rfq_id,))
        rfq = cur.fetchone()
        if not rfq:
            raise HTTPException(404, "RFQ not found")

        # Mark winner
        cur.execute("""
            UPDATE rfq_headers
            SET status = 'awarded', winning_vendor_id = %s, winning_vendor_name = %s, updated_at = NOW()
            WHERE id = %s
        """, (body.vendor_id, body.vendor_name, rfq_id))

        # Mark winning quotes
        cur.execute("""
            UPDATE vendor_quotes SET recommended = TRUE
            WHERE rfq_id = %s AND vendor_id = %s
        """, (rfq_id, body.vendor_id))

        # Create PO from winning quote
        cur.execute("""
            SELECT SUM(total_price) as total, SUM(unit_price * 1) as avg_price
            FROM vendor_quotes WHERE rfq_id = %s AND vendor_id = %s
        """, (rfq_id, body.vendor_id))
        totals = cur.fetchone()

        conn.commit()

        # Create PO via adapter
        po_result = {'success': False}
        try:
            from backend.services.adapters.factory import get_adapter
            adapter = get_adapter()
            po_result = adapter.create_purchase_order_from_pr({
                'pr_number': rfq['pr_number'] or rfq['rfq_number'],
                'vendor_name': body.vendor_name,
                'product_name': rfq['title'],
                'quantity': 1,
                'unit_price': float(totals['total'] or 0) if totals else 0,
                'total_amount': float(totals['total'] or 0) if totals else 0,
                'department': rfq['department'],
                'currency': 'USD',
            })

            # Notification
            adapter.log_notification({
                'event_type': 'rfq_awarded',
                'document_type': 'RFQ',
                'document_id': rfq['rfq_number'],
                'recipient_role': 'procurement',
                'subject': 'RFQ %s awarded to %s' % (rfq['rfq_number'], body.vendor_name),
                'body_preview': 'PO created: %s' % po_result.get('po_number', '?'),
                'status': 'pending',
                'agent_name': 'RFQSystem',
            })
        except Exception as e:
            log.warning("PO creation from RFQ award failed: %s", e)

        return {
            'success': True,
            'rfq_number': rfq['rfq_number'],
            'awarded_to': body.vendor_name,
            'status': 'awarded',
            'po_created': po_result.get('success', False),
            'po_number': po_result.get('po_number'),
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.get("/list")
async def list_rfqs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List all RFQs."""
    conn = _conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if status:
            cur.execute("SELECT * FROM rfq_headers WHERE status = %s ORDER BY created_at DESC LIMIT %s", (status, limit))
        else:
            cur.execute("SELECT * FROM rfq_headers ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'):
                    r[k] = v.isoformat()
        return {'total': len(rows), 'rfqs': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.get("/{rfq_id}")
async def get_rfq_detail(rfq_id: int):
    """Get RFQ with lines and quotes."""
    conn = _conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM rfq_headers WHERE id = %s", (rfq_id,))
        rfq = cur.fetchone()
        if not rfq:
            raise HTTPException(404, "RFQ not found")

        cur.execute("SELECT * FROM rfq_lines WHERE rfq_id = %s ORDER BY id", (rfq_id,))
        lines = cur.fetchall()

        cur.execute("SELECT * FROM vendor_quotes WHERE rfq_id = %s ORDER BY unit_price", (rfq_id,))
        quotes = cur.fetchall()

        # Serialize
        for obj in [rfq] + lines + quotes:
            for k, v in obj.items():
                if hasattr(v, 'isoformat'):
                    obj[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal):
                    obj[k] = float(v)

        return {
            'rfq': dict(rfq),
            'lines': [dict(l) for l in lines],
            'quotes': [dict(q) for q in quotes],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()
