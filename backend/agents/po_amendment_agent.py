"""
PO Amendment Agent — Handles PO modifications via chat.
Triggers on: "change PO", "amend PO", "update delivery date", "modify order"
"""
import os, json, logging, re, asyncio
from datetime import datetime
from typing import Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.agents import BaseAgent

logger = logging.getLogger(__name__)
DB_URL = os.environ.get('DATABASE_URL')


class POAmendmentAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="POAmendmentAgent", description="Modifies PO quantity, price, dates", temperature=0.1)

    async def _execute_action(self, decision) -> Dict[str, Any]:
        """Required by BaseAgent. Delegates to execute()."""
        return await self.execute(decision.context if hasattr(decision, 'context') else {})

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        request = input_data.get('request', '')
        request_lower = request.lower()

        if any(kw in request_lower for kw in ['list amend', 'show amend', 'amendment history']):
            return await asyncio.to_thread(self._list_amendments, input_data)

        # Extract PO number
        po_match = re.search(r'PO[-\s]?(\d{4}[-/]?\d+|\w+[-]\d+)', request, re.IGNORECASE)
        po_number = po_match.group(0).strip() if po_match else input_data.get('pr_data', {}).get('po_number', '')

        # Determine amendment type
        if any(kw in request_lower for kw in ['quantity', 'qty', 'units', 'pieces']):
            amendment_type = 'quantity_change'
        elif any(kw in request_lower for kw in ['price', 'cost', 'rate']):
            amendment_type = 'price_change'
        elif any(kw in request_lower for kw in ['date', 'delivery', 'deadline', 'schedule']):
            amendment_type = 'date_change'
        else:
            amendment_type = 'general_change'

        # Extract values
        numbers = re.findall(r'\d+\.?\d*', request)
        old_value = numbers[0] if len(numbers) > 0 else ''
        new_value = numbers[1] if len(numbers) > 1 else numbers[0] if numbers else ''
        amount_impact = float(new_value) - float(old_value) if old_value and new_value else 0

        return await asyncio.to_thread(
            self._create_amendment, po_number, amendment_type, request, old_value, new_value, amount_impact
        )

    def _create_amendment(self, po_number, amendment_type, request, old_value, new_value, amount_impact):
        """Synchronous DB work — runs in thread pool to avoid blocking the event loop."""
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            amendment_number = "AMD-%s" % datetime.now().strftime("%Y%m%d%H%M%S")
            requires_approval = abs(amount_impact) > 5000

            cur.execute("""
                INSERT INTO po_amendments (amendment_number, po_number, amendment_type, reason, old_value, new_value, amount_impact, status, requested_by, requires_re_approval)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Chat User', %s) RETURNING id
            """, (amendment_number, po_number, amendment_type, request[:200],
                  str(old_value), str(new_value), amount_impact,
                  'pending_approval' if requires_approval else 'approved', requires_approval))
            conn.commit()

            # Notify
            cur.execute("INSERT INTO notification_log (event_type, document_type, document_id, recipient_role, subject, status, agent_name) VALUES ('po_amendment', 'AMENDMENT', %s, 'procurement', %s, 'pending', 'POAmendmentAgent')",
                       (amendment_number, 'PO Amendment: %s on %s' % (amendment_type, po_number)))
            cur.execute("INSERT INTO agent_actions (agent_name, action_type, input_data, output_data, success) VALUES ('POAmendmentAgent', 'create_amendment', %s, %s, TRUE)",
                       (json.dumps({'po_number': po_number}), json.dumps({'amendment_number': amendment_number})))
            conn.commit()

            return {
                'status': 'success',
                'action': 'amendment_created',
                'amendment_number': amendment_number,
                'po_number': po_number,
                'amendment_type': amendment_type,
                'old_value': old_value,
                'new_value': new_value,
                'requires_approval': requires_approval,
                'message': 'Amendment %s created for %s (%s: %s -> %s).%s' % (
                    amendment_number, po_number, amendment_type.replace('_', ' '),
                    old_value, new_value,
                    ' Requires re-approval (impact > $5K).' if requires_approval else ' Auto-approved.'
                ),
                'next_suggestions': ['Show amendment history for %s' % po_number],
            }
        except Exception as e:
            conn.rollback()
            return {'status': 'error', 'error': str(e), 'message': 'Operation failed: ' + str(e)[:100]}
        finally:
            cur.close(); conn.close()

    def _list_amendments(self, input_data):
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT amendment_number, po_number, amendment_type, old_value, new_value, amount_impact, status FROM po_amendments ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            for r in rows:
                if isinstance(r.get('amount_impact'), __import__('decimal').Decimal):
                    r['amount_impact'] = float(r['amount_impact'])
            return {'status': 'success', 'action': 'amendment_list', 'amendments': [dict(r) for r in rows], 'message': '%d amendments found.' % len(rows)}
        finally:
            cur.close(); conn.close()
