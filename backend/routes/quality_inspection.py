"""
Quality Inspection Routes
==========================
GET  /api/qc/templates          — List QC templates
POST /api/qc/inspect            — Run inspection on a GRN
GET  /api/qc/results            — List inspection results
GET  /api/qc/results/{grn}      — Get results for a GRN
"""

import os, logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import json

log = logging.getLogger(__name__)
router = APIRouter()
DB_URL = os.environ.get('DATABASE_URL')


class InspectionRequest(BaseModel):
    grn_number: str
    po_number: str = ''
    template_id: int
    item_name: str = ''
    inspector: str = 'system'
    checklist_results: list = []  # [{item, passed: bool, notes}]


@router.get("/templates")
async def list_templates():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT id, template_name, category, pass_threshold, is_active, checklist_items FROM qc_templates WHERE is_active = TRUE ORDER BY id")
        rows = cur.fetchall()
        for r in rows:
            if isinstance(r.get('checklist_items'), str):
                r['checklist_items'] = json.loads(r['checklist_items'])
            if isinstance(r.get('pass_threshold'), __import__('decimal').Decimal):
                r['pass_threshold'] = float(r['pass_threshold'])
        return {'templates': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.post("/inspect")
async def run_inspection(body: InspectionRequest):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get template
        cur.execute("SELECT * FROM qc_templates WHERE id = %s", (body.template_id,))
        template = cur.fetchone()
        if not template:
            raise HTTPException(404, "QC template not found")

        checklist = template['checklist_items']
        if isinstance(checklist, str):
            checklist = json.loads(checklist)
        threshold = float(template['pass_threshold'])

        # Calculate score from results
        total_weight = sum(item.get('weight', 10) for item in checklist)
        earned_weight = 0
        result_details = []

        for i, template_item in enumerate(checklist):
            user_result = body.checklist_results[i] if i < len(body.checklist_results) else {}
            passed = user_result.get('passed', True)
            notes = user_result.get('notes', '')
            weight = template_item.get('weight', 10)
            if passed:
                earned_weight += weight
            result_details.append({
                'item': template_item.get('item', ''),
                'weight': weight,
                'passed': passed,
                'notes': notes,
            })

        score = round((earned_weight / max(total_weight, 1)) * 100, 1)
        pass_fail = 'pass' if score >= threshold else 'fail'
        hold_goods = pass_fail == 'fail'
        trigger_rtv = score < 50  # Auto-trigger RTV if score very low

        cur.execute("""
            INSERT INTO qc_results (grn_number, po_number, template_id, item_name, inspector, checklist_results, total_score, pass_fail, hold_goods, trigger_rtv)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (body.grn_number, body.po_number, body.template_id, body.item_name, body.inspector,
              json.dumps(result_details), score, pass_fail, hold_goods, trigger_rtv))
        result_id = cur.fetchone()['id']
        conn.commit()

        # Notification
        try:
            from backend.services.adapters.factory import get_adapter
            get_adapter().log_notification({
                'event_type': 'qc_completed',
                'document_type': 'QC',
                'document_id': body.grn_number,
                'recipient_role': 'procurement',
                'subject': 'QC %s: %s (score %.0f%%)' % (pass_fail.upper(), body.grn_number, score),
                'body_preview': 'Template: %s, Score: %.1f%%, Threshold: %.0f%%' % (template['template_name'], score, threshold),
                'status': 'pending',
                'agent_name': 'QCSystem',
            })
        except Exception:
            pass

        return {
            'success': True,
            'result_id': result_id,
            'grn_number': body.grn_number,
            'score': score,
            'threshold': threshold,
            'pass_fail': pass_fail,
            'hold_goods': hold_goods,
            'trigger_rtv': trigger_rtv,
            'details': result_details,
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        cur.close(); conn.close()


@router.get("/results")
async def list_results(pass_fail: Optional[str] = Query(None), limit: int = Query(50)):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        if pass_fail:
            cur.execute("SELECT * FROM qc_results WHERE pass_fail = %s ORDER BY created_at DESC LIMIT %s", (pass_fail, limit))
        else:
            cur.execute("SELECT * FROM qc_results ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'total': len(rows), 'results': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()


@router.get("/results/{grn_number}")
async def get_grn_results(grn_number: str):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM qc_results WHERE grn_number = %s ORDER BY created_at DESC", (grn_number,))
        rows = cur.fetchall()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
        return {'grn_number': grn_number, 'results': [dict(r) for r in rows]}
    finally:
        cur.close(); conn.close()
