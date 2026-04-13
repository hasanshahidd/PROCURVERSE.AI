"""
Reconciliation Agent — Auto-matches bank statements to payments via chat.
Triggers on: "reconcile payments", "match bank entries", "check payment matching"
"""
import os, json, logging, asyncio
from typing import Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.agents import BaseAgent

logger = logging.getLogger(__name__)
DB_URL = os.environ.get('DATABASE_URL')


class ReconciliationAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="ReconciliationAgent", description="Matches bank statements to payments, finds exceptions", temperature=0.1)

    async def _execute_action(self, decision) -> Dict[str, Any]:
        """Required by BaseAgent. Delegates to execute()."""
        return await self.execute(decision.context if hasattr(decision, 'context') else {})

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        request = input_data.get('request', '').lower()

        if any(kw in request for kw in ['exception', 'unmatched', 'mismatch']):
            return await asyncio.to_thread(self._show_exceptions)
        if any(kw in request for kw in ['result', 'matched', 'status']):
            return await asyncio.to_thread(self._show_results)

        return await asyncio.to_thread(self._run_reconciliation)

    def _run_reconciliation(self) -> Dict[str, Any]:
        from datetime import datetime
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            run_id = "RECON-%s" % datetime.now().strftime("%Y%m%d%H%M%S")

            cur.execute("SELECT * FROM bank_statements WHERE matched = FALSE")
            bank_rows = cur.fetchall()

            cur.execute("SELECT * FROM payment_runs")
            payments = cur.fetchall()

            matched = 0
            exceptions = 0

            for bank in bank_rows:
                amount = float(bank.get('debit_amount') or bank.get('credit_amount') or 0)
                reference = str(bank.get('reference', '')).strip()
                best_match = None

                for pay in payments:
                    pay_amount = float(pay.get('total_amount', 0))
                    pay_id = str(pay.get('payment_run_id', ''))
                    if reference and pay_id and reference in pay_id:
                        best_match = pay; break
                    if pay_amount > 0 and abs(amount - pay_amount) / pay_amount < 0.01:
                        best_match = pay

                if best_match:
                    cur.execute("""INSERT INTO reconciliation_results (reconciliation_run_id, bank_statement_id, payment_run_id, bank_amount, ledger_amount, variance, match_status, match_confidence, reconciled_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'matched', 90, NOW())""",
                        (run_id, bank['id'], best_match.get('payment_run_id', ''), amount, float(best_match.get('total_amount', 0)), abs(amount - float(best_match.get('total_amount', 0)))))
                    cur.execute("UPDATE bank_statements SET matched = TRUE WHERE id = %s", (bank['id'],))
                    matched += 1
                else:
                    cur.execute("""INSERT INTO reconciliation_exceptions (reconciliation_run_id, exception_type, description, bank_amount, reference, status)
                        VALUES (%s, 'unmatched', %s, %s, %s, 'open')""",
                        (run_id, str(bank.get('description', ''))[:200], amount, reference))
                    exceptions += 1

            cur.execute("INSERT INTO agent_actions (agent_name, action_type, input_data, output_data, success) VALUES ('ReconciliationAgent', 'reconcile', %s, %s, TRUE)",
                       (json.dumps({'bank_entries': len(bank_rows)}), json.dumps({'matched': matched, 'exceptions': exceptions})))
            cur.execute("INSERT INTO notification_log (event_type, document_type, document_id, recipient_role, subject, status, agent_name) VALUES ('reconciliation_complete', 'RECON', %s, 'finance', %s, 'pending', 'ReconciliationAgent')",
                       (run_id, 'Reconciliation: %d matched, %d exceptions' % (matched, exceptions)))
            conn.commit()

            msg = 'Reconciliation complete.\nProcessed: %d bank entries\nMatched: %d\nExceptions: %d' % (len(bank_rows), matched, exceptions)
            if exceptions > 0:
                msg += '\n%d unmatched entries need manual review.' % exceptions
            elif len(bank_rows) == 0:
                msg = 'No unmatched bank entries to reconcile. Upload a bank statement first.'

            return {
                'status': 'success',
                'action': 'reconciliation_complete',
                'run_id': run_id,
                'processed': len(bank_rows),
                'matched': matched,
                'exceptions': exceptions,
                'message': msg,
                'next_suggestions': ['Show reconciliation exceptions'] if exceptions > 0 else [],
            }
        except Exception as e:
            conn.rollback()
            return {'status': 'error', 'error': str(e), 'message': 'Operation failed: ' + str(e)[:100]}
        finally:
            cur.close(); conn.close()

    def _show_results(self):
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT reconciliation_run_id, count(*) as matches, sum(bank_amount) as total FROM reconciliation_results GROUP BY reconciliation_run_id ORDER BY max(reconciled_at) DESC LIMIT 5")
            rows = cur.fetchall()
            for r in rows:
                for k, v in r.items():
                    if isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
            return {'status': 'success', 'action': 'recon_results', 'runs': [dict(r) for r in rows], 'message': '%d reconciliation runs found.' % len(rows)}
        finally:
            cur.close(); conn.close()

    def _show_exceptions(self):
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT exception_type, description, bank_amount, reference, status FROM reconciliation_exceptions WHERE status = 'open' ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            for r in rows:
                for k, v in r.items():
                    if isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
            return {'status': 'success', 'action': 'recon_exceptions', 'exceptions': [dict(r) for r in rows], 'message': '%d open exceptions.' % len(rows)}
        finally:
            cur.close(); conn.close()
