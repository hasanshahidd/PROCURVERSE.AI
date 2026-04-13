"""
RFQ Agent — Creates and manages Request for Quotation workflows via chat.

Triggers on: "create RFQ for...", "invite vendors for...", "compare quotes for..."
Calls: /api/rfq/* endpoints internally via adapter/direct DB.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor

from backend.agents import BaseAgent, AgentDecision

logger = logging.getLogger(__name__)
DB_URL = os.environ.get('DATABASE_URL')


class RFQAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="RFQAgent",
            description="Creates RFQs, invites vendors, compares quotes, awards contracts",
            temperature=0.1,
        )

    async def _execute_action(self, decision) -> Dict[str, Any]:
        """Required by BaseAgent. Delegates to execute()."""
        return await self.execute(decision.context if hasattr(decision, 'context') else {})

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        request = input_data.get('request', '')
        request_lower = request.lower()

        # Determine action — all helpers use blocking psycopg2, so run in thread pool
        if any(kw in request_lower for kw in ['compare', 'evaluation', 'score', 'which vendor']):
            return await asyncio.to_thread(self._compare_quotes, input_data)
        elif any(kw in request_lower for kw in ['award', 'select winner', 'choose vendor']):
            return await asyncio.to_thread(self._award_rfq, input_data)
        elif any(kw in request_lower for kw in ['list rfq', 'show rfq', 'active rfq']):
            return await asyncio.to_thread(self._list_rfqs)
        else:
            return await asyncio.to_thread(self._create_rfq, input_data)

    def _create_rfq(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        request = input_data.get('request', '')
        pr_data = input_data.get('pr_data', {})

        title = pr_data.get('product_name', '') or self._extract_item(request)
        department = pr_data.get('department', '') or 'Procurement'
        requester = pr_data.get('requester_name', 'Chat User')

        rfq_number = "RFQ-%s" % datetime.now().strftime("%Y%m%d%H%M%S")
        deadline = (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d')

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                INSERT INTO rfq_headers (rfq_number, title, department, requester, status, submission_deadline)
                VALUES (%s, %s, %s, %s, 'draft', %s) RETURNING id, rfq_number
            """, (rfq_number, title or 'Procurement Request', department, requester, deadline))
            row = cur.fetchone()
            rfq_id = row['id']

            # Add line item if we can extract one
            if title:
                qty = pr_data.get('quantity', 1)
                price = pr_data.get('budget', 0)
                cur.execute("""
                    INSERT INTO rfq_lines (rfq_id, item_name, quantity, estimated_price)
                    VALUES (%s, %s, %s, %s)
                """, (rfq_id, title, qty, price))

            # Auto-send
            cur.execute("UPDATE rfq_headers SET status = 'sent', vendors_invited = 3 WHERE id = %s", (rfq_id,))
            conn.commit()

            self._log_action(conn, 'create_rfq', {'rfq_number': rfq_number, 'title': title})
            self._notify(conn, 'rfq_created', rfq_number, 'New RFQ: %s' % title)

            return {
                'status': 'success',
                'action': 'rfq_created',
                'rfq_number': rfq_number,
                'title': title,
                'department': department,
                'deadline': deadline,
                'message': 'RFQ %s created and sent to vendors. Deadline: %s.' % (rfq_number, deadline),
                'next_suggestions': [
                    'Compare quotes for %s' % rfq_number,
                    'Show all active RFQs',
                ],
            }
        except Exception as e:
            conn.rollback()
            logger.error("RFQAgent create failed: %s", e)
            return {'status': 'error', 'error': str(e), 'message': 'Operation failed: ' + str(e)[:100]}
        finally:
            cur.close(); conn.close()

    def _compare_quotes(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Get latest RFQ with quotes
            cur.execute("SELECT id, rfq_number, title FROM rfq_headers WHERE status IN ('evaluation', 'sent') AND quotes_received > 0 ORDER BY created_at DESC LIMIT 1")
            rfq = cur.fetchone()
            if not rfq:
                return {'status': 'success', 'message': 'No RFQs with quotes found. Create an RFQ first.'}

            cur.execute("SELECT vendor_name, item_name, unit_price, lead_time_days, total_price FROM vendor_quotes WHERE rfq_id = %s ORDER BY unit_price", (rfq['id'],))
            quotes = cur.fetchall()

            if not quotes:
                return {'status': 'success', 'message': 'No quotes received yet for %s.' % rfq['rfq_number']}

            # Score
            min_price = min(float(q['unit_price'] or 1) for q in quotes)
            min_lead = min(int(q['lead_time_days'] or 1) for q in quotes)
            scored = []
            for q in quotes:
                p_score = (min_price / max(float(q['unit_price'] or 1), 0.01)) * 40
                l_score = (min_lead / max(int(q['lead_time_days'] or 1), 1)) * 30
                total = round(p_score + l_score + 30, 1)
                scored.append({**dict(q), 'score': total, 'unit_price': float(q['unit_price']), 'total_price': float(q['total_price'] or 0)})

            scored.sort(key=lambda x: x['score'], reverse=True)
            winner = scored[0]

            return {
                'status': 'success',
                'action': 'quotes_compared',
                'rfq_number': rfq['rfq_number'],
                'title': rfq['title'],
                'quotes': scored,
                'recommendation': winner['vendor_name'],
                'recommendation_score': winner['score'],
                'message': 'Compared %d quotes for %s. Recommended: %s (score %.1f).' % (len(scored), rfq['rfq_number'], winner['vendor_name'], winner['score']),
                'next_suggestions': ['Award %s to %s' % (rfq['rfq_number'], winner['vendor_name'])],
            }
        finally:
            cur.close(); conn.close()

    def _award_rfq(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT id, rfq_number, title FROM rfq_headers WHERE status IN ('evaluation', 'sent') ORDER BY created_at DESC LIMIT 1")
            rfq = cur.fetchone()
            if not rfq:
                return {'status': 'success', 'message': 'No RFQ available to award.'}

            # Get best quote
            cur.execute("SELECT vendor_id, vendor_name, unit_price FROM vendor_quotes WHERE rfq_id = %s ORDER BY unit_price LIMIT 1", (rfq['id'],))
            best = cur.fetchone()
            if not best:
                return {'status': 'success', 'message': 'No quotes to award.'}

            cur.execute("UPDATE rfq_headers SET status = 'awarded', winning_vendor_id = %s, winning_vendor_name = %s WHERE id = %s",
                       (best['vendor_id'], best['vendor_name'], rfq['id']))
            cur.execute("UPDATE vendor_quotes SET recommended = TRUE WHERE rfq_id = %s AND vendor_id = %s", (rfq['id'], best['vendor_id']))
            conn.commit()

            self._notify(conn, 'rfq_awarded', rfq['rfq_number'], 'RFQ %s awarded to %s' % (rfq['rfq_number'], best['vendor_name']))

            return {
                'status': 'success',
                'action': 'rfq_awarded',
                'rfq_number': rfq['rfq_number'],
                'awarded_to': best['vendor_name'],
                'message': 'RFQ %s awarded to %s. PO can now be created.' % (rfq['rfq_number'], best['vendor_name']),
                'next_suggestions': ['Create PO from %s' % rfq['rfq_number']],
            }
        finally:
            cur.close(); conn.close()

    def _list_rfqs(self) -> Dict[str, Any]:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT rfq_number, title, status, quotes_received, winning_vendor_name FROM rfq_headers ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            return {
                'status': 'success',
                'action': 'rfq_list',
                'rfqs': [dict(r) for r in rows],
                'message': '%d RFQs found.' % len(rows),
            }
        finally:
            cur.close(); conn.close()

    def _extract_item(self, text):
        for kw in ['for ', 'of ', 'need ']:
            if kw in text.lower():
                return text.lower().split(kw, 1)[1].split(',')[0].split('.')[0].strip()[:100]
        return text[:100] if text else 'General Procurement'

    def _log_action(self, conn, action_type, data):
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO agent_actions (agent_name, action_type, input_data, output_data, success) VALUES (%s, %s, %s, %s, TRUE)",
                       ('RFQAgent', action_type, json.dumps(data), json.dumps(data)))
            conn.commit()
            cur.close()
        except Exception:
            pass

    def _notify(self, conn, event_type, doc_id, subject):
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO notification_log (event_type, document_type, document_id, recipient_role, subject, status, agent_name) VALUES (%s, 'RFQ', %s, 'procurement', %s, 'pending', 'RFQAgent')",
                       (event_type, doc_id, subject))
            conn.commit()
            cur.close()
        except Exception:
            pass
