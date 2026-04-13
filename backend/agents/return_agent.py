"""
Return Agent -- Handles returns to vendor (RTV) via chat.
Triggers on: "return goods", "send back", "damaged items", "reject delivery",
              "debit note", "credit note"
Looks up real PO/GRN pricing from the active ERP adapter.

G-03 Enhancement (Dev Spec 2.0):
  - Writes to grn_returns gap table alongside rtv_headers
  - Auto-generates debit notes (DN-YYYYMMDDHHMMSS)
  - Calculates accepted_qty = received_qty - return_qty
  - Sends vendor communication (debit_note touchpoint) via VendorCommunicationService
  - Supports credit resolution workflow (credit_note, replacement, refund, write_off)
"""
import os, json, logging, re, asyncio
from datetime import datetime
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from backend.agents import BaseAgent
from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)
DB_URL = os.environ.get('DATABASE_URL')


class ReturnAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="ReturnAgent", description="Creates and manages returns to vendor", temperature=0.1)
        self._vendor_comm = None

    # -- Lazy-loaded vendor communication service -----------------------------
    @property
    def vendor_comm(self):
        """Lazy import to avoid circular imports and import-time DB hits."""
        if self._vendor_comm is None:
            from backend.services.vendor_communication_service import get_vendor_comm_service
            self._vendor_comm = get_vendor_comm_service()
        return self._vendor_comm

    async def _execute_action(self, decision) -> Dict[str, Any]:
        """Required by BaseAgent. Delegates to execute()."""
        return await self.execute(decision.context if hasattr(decision, 'context') else {})

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        request = input_data.get('request', '')
        request_lower = request.lower()

        if any(kw in request_lower for kw in ['list return', 'show return', 'active return', 'rtv list']):
            return await asyncio.to_thread(self._list_returns)

        # --- G-03: Debit note lookup / status --------------------------------
        if any(kw in request_lower for kw in ['debit note', 'show debit', 'list debit']):
            rtv_match = re.search(r'RTV[-\s]?(\d+)', request, re.IGNORECASE)
            dn_match = re.search(r'DN[-\s]?(\d+)', request, re.IGNORECASE)
            if rtv_match:
                rtv_number = 'RTV-%s' % rtv_match.group(1)
                return await asyncio.to_thread(self._get_return_with_debit_note, rtv_number)
            elif dn_match:
                dn_number = 'DN-%s' % dn_match.group(1)
                return await asyncio.to_thread(self._get_return_with_debit_note, None, dn_number)
            else:
                return await asyncio.to_thread(self._list_returns_with_debit_notes)

        # --- G-03: Credit resolution -----------------------------------------
        if any(kw in request_lower for kw in ['credit note', 'credit resolution', 'resolve return', 'resolve credit']):
            rtv_match = re.search(r'RTV[-\s]?(\d+)', request, re.IGNORECASE)
            dn_match = re.search(r'DN[-\s]?(\d+)', request, re.IGNORECASE)
            return_ref = None
            if rtv_match:
                return_ref = 'RTV-%s' % rtv_match.group(1)
            elif dn_match:
                return_ref = 'DN-%s' % dn_match.group(1)

            resolution_type = 'credit_note'  # default
            if 'replacement' in request_lower:
                resolution_type = 'replacement'
            elif 'refund' in request_lower:
                resolution_type = 'refund'
            elif 'write_off' in request_lower or 'write off' in request_lower:
                resolution_type = 'write_off'

            # Extract credit amount if mentioned
            amt_match = re.search(r'\$?\s*([\d,]+(?:\.\d{2})?)', request)
            credit_amount = float(amt_match.group(1).replace(',', '')) if amt_match else None

            return await asyncio.to_thread(
                self._handle_credit_resolution, return_ref, resolution_type, credit_amount
            )

        # Extract references
        grn_match = re.search(r'GRN[-\s]?(\w+[-]?\d+)', request, re.IGNORECASE)
        grn_number = grn_match.group(0).strip() if grn_match else ''
        po_match = re.search(r'PO[-\s]?(\w+[-]?\d+)', request, re.IGNORECASE)
        po_number = po_match.group(0).strip() if po_match else ''

        # Extract reason
        reason = 'quality_failure'
        if any(kw in request_lower for kw in ['damage', 'broken']): reason = 'damaged'
        elif any(kw in request_lower for kw in ['wrong', 'incorrect']): reason = 'wrong_item'
        elif any(kw in request_lower for kw in ['excess', 'too many', 'extra']): reason = 'excess'

        # Extract quantity
        qty_match = re.search(r'(\d+)\s*(unit|item|piece|widget|part|box)', request_lower)
        qty = int(qty_match.group(1)) if qty_match else 1

        # Extract item name
        item_name = self._extract_item(request)
        vendor_name = input_data.get('pr_data', {}).get('vendor_name', 'Unknown Vendor')

        return await asyncio.to_thread(
            self._create_return, grn_number, po_number, vendor_name, reason, qty, item_name, input_data
        )

    # =========================================================================
    #  _create_return  (enhanced for G-03)
    # =========================================================================
    def _create_return(self, grn_number, po_number, vendor_name, reason, qty, item_name, input_data):
        """Synchronous DB + adapter work -- runs in thread pool."""
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            rtv_number = "RTV-%s" % datetime.now().strftime("%Y%m%d%H%M%S")

            # Look up real unit price from PO/GRN data via the adapter
            unit_price = 0.0
            received_qty = 0
            try:
                adapter = get_adapter()
                if po_number:
                    pos = adapter.get_purchase_orders(status=None, limit=200)
                    po_rec = next((p for p in pos if str(p.get('name') or p.get('po_number', '')) == str(po_number)), {})
                    po_total = float(po_rec.get('amount_total') or po_rec.get('total_amount') or 0)
                    po_qty = float(po_rec.get('total_qty') or po_rec.get('qty_ordered') or qty or 1)
                    if po_total > 0 and po_qty > 0:
                        unit_price = round(po_total / po_qty, 2)
                if unit_price <= 0 and grn_number:
                    grns = adapter.get_grn_headers(grn_number=grn_number, limit=1)
                    grn_rec = grns[0] if grns else {}
                    grn_total = float(grn_rec.get('total_value') or grn_rec.get('amount') or 0)
                    grn_qty = float(grn_rec.get('total_qty') or grn_rec.get('qty_received') or qty or 1)
                    if grn_total > 0 and grn_qty > 0:
                        unit_price = round(grn_total / grn_qty, 2)
                    received_qty = int(grn_rec.get('total_qty') or grn_rec.get('qty_received') or 0)
            except Exception as price_err:
                logger.warning("[ReturnAgent] Price lookup failed: %s -- using budget estimate", price_err)

            if unit_price <= 0:
                # Final fallback: use budget from pr_data if available, else reasonable default
                budget = float(input_data.get('pr_data', {}).get('budget', 0))
                unit_price = round(budget / max(qty, 1), 2) if budget > 0 else 100.0
                logger.info("[ReturnAgent] Using estimated unit_price=%.2f (no PO/GRN price found)", unit_price)

            total_value = qty * unit_price

            # G-03: Calculate accepted_qty
            accepted_qty = max(received_qty - qty, 0) if received_qty > 0 else 0

            # --- Insert into rtv_headers (existing) --------------------------
            cur.execute("""
                INSERT INTO rtv_headers (rtv_number, grn_number, po_number, vendor_name, return_reason, return_type, total_return_qty, total_return_value, credit_expected, status, initiated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'initiated', 'Chat User') RETURNING id
            """, (rtv_number, grn_number, po_number, vendor_name, reason, reason, qty, total_value, total_value))
            rtv_id = cur.fetchone()['id']

            cur.execute("""
                INSERT INTO rtv_lines (rtv_id, item_name, return_qty, unit_price, return_value, reason_code, condition)
                VALUES (%s, %s, %s, %s, %s, %s, 'damaged')
            """, (rtv_id, item_name, qty, unit_price, total_value, reason))

            # --- G-03: Insert into grn_returns gap table ---------------------
            dn_number = self._generate_debit_note_number()
            vendor_id = input_data.get('pr_data', {}).get('vendor_id', '')
            return_type = self._map_reason_to_return_type(reason)

            items_json = json.dumps([{
                'item_name': item_name,
                'return_qty': qty,
                'unit_price': float(unit_price),
                'return_value': float(total_value),
                'reason_code': reason,
                'accepted_qty': accepted_qty,
            }])

            cur.execute("""
                INSERT INTO grn_returns
                    (return_number, grn_number, po_number, vendor_id, vendor_name,
                     return_reason, return_type, items, total_return_qty,
                     total_return_value, debit_note_number, debit_note_amount,
                     debit_note_status, status, initiated_by)
                VALUES (%s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb, %s,
                        %s, %s, %s,
                        'issued', 'initiated', 'Chat User')
                RETURNING id
            """, (rtv_number, grn_number, po_number, vendor_id, vendor_name,
                  reason, return_type, items_json, qty,
                  total_value, dn_number, total_value))
            grn_return_id = cur.fetchone()['id']

            # Log + notify
            cur.execute("INSERT INTO agent_actions (agent_name, action_type, input_data, output_data, success) VALUES ('ReturnAgent', 'create_rtv', %s, %s, TRUE)",
                       (json.dumps({'grn': grn_number}), json.dumps({'rtv_number': rtv_number, 'debit_note': dn_number})))
            cur.execute("INSERT INTO notification_log (event_type, document_type, document_id, recipient_role, subject, status, agent_name) VALUES ('rtv_created', 'RTV', %s, 'procurement', %s, 'pending', 'ReturnAgent')",
                       (rtv_number, 'Return initiated: %s (%s). Debit note: %s' % (rtv_number, reason, dn_number)))
            conn.commit()

            # --- G-03: Send debit note vendor communication ------------------
            comm_result = self._send_debit_note_communication(
                return_number=rtv_number,
                vendor_name=vendor_name,
                vendor_id=vendor_id,
                amount=total_value,
                reason=reason,
            )

            return {
                'status': 'success',
                'action': 'return_created',
                'rtv_number': rtv_number,
                'grn_number': grn_number,
                'reason': reason,
                'items_returned': qty,
                'accepted_qty': accepted_qty,
                'credit_expected': total_value,
                'debit_note_number': dn_number,
                'debit_note_status': 'issued',
                'vendor_notified': comm_result.get('status') == 'sent',
                'message': (
                    'Return %s created. %d %s being returned (%s). '
                    'Credit expected: $%s. Debit note %s issued%s.'
                ) % (
                    rtv_number, qty, item_name, reason.replace('_', ' '),
                    '{:,.2f}'.format(total_value), dn_number,
                    ' and vendor notified' if comm_result.get('status') == 'sent' else ''
                ),
                'next_suggestions': [
                    'Show active returns',
                    'Track return %s' % rtv_number,
                    'Show debit note %s' % dn_number,
                ],
            }
        except Exception as e:
            conn.rollback()
            return {'status': 'error', 'error': str(e), 'message': 'Operation failed: ' + str(e)[:100]}
        finally:
            cur.close(); conn.close()

    # =========================================================================
    #  G-03: _create_debit_note  (standalone debit note creation)
    # =========================================================================
    def _create_debit_note(self, grn_return_id: int, return_number: str,
                           vendor_name: str, vendor_id: str,
                           amount: float, reason: str) -> Dict[str, Any]:
        """
        Generate a debit note for an existing grn_returns record.

        - Generates a debit note number (DN-YYYYMMDDHHMMSS)
        - Updates the grn_returns record with debit note details
        - Sets debit_note_status to 'issued'
        - Calls vendor communication service to notify the vendor

        Parameters
        ----------
        grn_return_id : The grn_returns.id to update
        return_number : The RTV/return reference number
        vendor_name   : Vendor display name
        vendor_id     : Vendor identifier
        amount        : Debit note amount
        reason        : Return reason description

        Returns
        -------
        dict with debit_note_number, status, vendor_notified
        """
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            dn_number = self._generate_debit_note_number()

            cur.execute("""
                UPDATE grn_returns
                SET debit_note_number = %s,
                    debit_note_amount = %s,
                    debit_note_status = 'issued',
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
            """, (dn_number, amount, grn_return_id))
            updated = cur.fetchone()

            if not updated:
                return {
                    'status': 'error',
                    'error': 'grn_returns record not found',
                    'message': 'Could not find return record id=%d' % grn_return_id,
                }

            # Log the action
            cur.execute(
                "INSERT INTO agent_actions (agent_name, action_type, input_data, output_data, success) "
                "VALUES ('ReturnAgent', 'create_debit_note', %s, %s, TRUE)",
                (
                    json.dumps({'grn_return_id': grn_return_id, 'return_number': return_number}),
                    json.dumps({'debit_note_number': dn_number}),
                )
            )

            cur.execute(
                "INSERT INTO notification_log (event_type, document_type, document_id, "
                "recipient_role, subject, status, agent_name) "
                "VALUES ('debit_note_issued', 'debit_note', %s, 'procurement', %s, 'pending', 'ReturnAgent')",
                (dn_number, 'Debit note %s issued for return %s' % (dn_number, return_number))
            )

            conn.commit()

            # Send vendor communication
            comm_result = self._send_debit_note_communication(
                return_number=return_number,
                vendor_name=vendor_name,
                vendor_id=vendor_id,
                amount=amount,
                reason=reason,
            )

            return {
                'status': 'success',
                'debit_note_number': dn_number,
                'debit_note_amount': amount,
                'debit_note_status': 'issued',
                'vendor_notified': comm_result.get('status') == 'sent',
                'message': 'Debit note %s issued for $%s against return %s.' % (
                    dn_number, '{:,.2f}'.format(amount), return_number
                ),
            }
        except Exception as e:
            conn.rollback()
            return {'status': 'error', 'error': str(e), 'message': 'Debit note creation failed: ' + str(e)[:100]}
        finally:
            cur.close(); conn.close()

    # =========================================================================
    #  G-03: _handle_credit_resolution
    # =========================================================================
    def _handle_credit_resolution(self, return_ref: Optional[str],
                                  resolution_type: str,
                                  credit_amount: Optional[float] = None) -> Dict[str, Any]:
        """
        Update a grn_returns record with the credit resolution outcome.

        Parameters
        ----------
        return_ref      : RTV number or DN number to look up
        resolution_type : One of 'credit_note', 'replacement', 'refund', 'write_off'
        credit_amount   : Resolved credit amount (defaults to debit_note_amount if None)

        Returns
        -------
        dict with updated record details
        """
        valid_resolutions = ('credit_note', 'replacement', 'refund', 'write_off')
        if resolution_type not in valid_resolutions:
            return {
                'status': 'error',
                'error': 'invalid_resolution_type',
                'message': 'Resolution type must be one of: %s' % ', '.join(valid_resolutions),
            }

        if not return_ref:
            return {
                'status': 'error',
                'error': 'missing_reference',
                'message': 'Please provide an RTV or DN number to resolve (e.g. RTV-20260410120000).',
            }

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Look up by return_number or debit_note_number
            cur.execute("""
                SELECT id, return_number, debit_note_number, debit_note_amount,
                       total_return_value, vendor_name, status, credit_resolution
                FROM grn_returns
                WHERE return_number = %s OR debit_note_number = %s
                ORDER BY created_at DESC LIMIT 1
            """, (return_ref, return_ref))
            record = cur.fetchone()

            if not record:
                return {
                    'status': 'error',
                    'error': 'not_found',
                    'message': 'No return record found for reference: %s' % return_ref,
                }

            if record['credit_resolution']:
                return {
                    'status': 'error',
                    'error': 'already_resolved',
                    'message': 'Return %s already resolved as %s.' % (
                        record['return_number'], record['credit_resolution']
                    ),
                }

            # Default credit_amount to debit_note_amount or total_return_value
            if credit_amount is None:
                credit_amount = float(record['debit_note_amount'] or record['total_return_value'] or 0)

            cur.execute("""
                UPDATE grn_returns
                SET credit_resolution = %s,
                    credit_amount = %s,
                    status = 'resolved',
                    resolved_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, return_number, debit_note_number
            """, (resolution_type, credit_amount, record['id']))
            updated = cur.fetchone()

            # Log action
            cur.execute(
                "INSERT INTO agent_actions (agent_name, action_type, input_data, output_data, success) "
                "VALUES ('ReturnAgent', 'credit_resolution', %s, %s, TRUE)",
                (
                    json.dumps({'return_ref': return_ref, 'resolution_type': resolution_type}),
                    json.dumps({
                        'return_number': updated['return_number'],
                        'credit_resolution': resolution_type,
                        'credit_amount': float(credit_amount),
                    }),
                )
            )

            cur.execute(
                "INSERT INTO notification_log (event_type, document_type, document_id, "
                "recipient_role, subject, status, agent_name) "
                "VALUES ('credit_resolved', 'grn_return', %s, 'procurement', %s, 'pending', 'ReturnAgent')",
                (
                    updated['return_number'],
                    'Credit resolved: %s via %s ($%s)' % (
                        updated['return_number'], resolution_type, '{:,.2f}'.format(credit_amount)
                    ),
                )
            )

            conn.commit()

            return {
                'status': 'success',
                'action': 'credit_resolved',
                'return_number': updated['return_number'],
                'debit_note_number': updated['debit_note_number'],
                'resolution_type': resolution_type,
                'credit_amount': credit_amount,
                'message': 'Return %s resolved via %s. Credit amount: $%s.' % (
                    updated['return_number'],
                    resolution_type.replace('_', ' '),
                    '{:,.2f}'.format(credit_amount),
                ),
                'next_suggestions': [
                    'Show active returns',
                    'Show debit note %s' % (updated['debit_note_number'] or ''),
                ],
            }
        except Exception as e:
            conn.rollback()
            return {'status': 'error', 'error': str(e), 'message': 'Credit resolution failed: ' + str(e)[:100]}
        finally:
            cur.close(); conn.close()

    # =========================================================================
    #  G-03: _get_return_with_debit_note
    # =========================================================================
    def _get_return_with_debit_note(self, rtv_number: Optional[str] = None,
                                    dn_number: Optional[str] = None) -> Dict[str, Any]:
        """
        Return combined RTV + debit note data for a given return or debit note number.

        Parameters
        ----------
        rtv_number : RTV reference (e.g. 'RTV-20260410120000')
        dn_number  : Debit note reference (e.g. 'DN-20260410120000')

        Returns
        -------
        dict with merged rtv_headers + grn_returns data
        """
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Fetch from grn_returns
            if rtv_number:
                cur.execute("""
                    SELECT * FROM grn_returns WHERE return_number = %s LIMIT 1
                """, (rtv_number,))
            elif dn_number:
                cur.execute("""
                    SELECT * FROM grn_returns WHERE debit_note_number = %s LIMIT 1
                """, (dn_number,))
            else:
                return {
                    'status': 'error',
                    'error': 'missing_reference',
                    'message': 'Provide an RTV or DN number.',
                }

            grn_return = cur.fetchone()

            # Fetch from rtv_headers for the same return
            lookup_rtv = rtv_number or (grn_return['return_number'] if grn_return else None)
            rtv_record = None
            if lookup_rtv:
                cur.execute("""
                    SELECT rh.*, json_agg(rl.*) AS lines
                    FROM rtv_headers rh
                    LEFT JOIN rtv_lines rl ON rl.rtv_id = rh.id
                    WHERE rh.rtv_number = %s
                    GROUP BY rh.id
                    LIMIT 1
                """, (lookup_rtv,))
                rtv_record = cur.fetchone()

            if not grn_return and not rtv_record:
                ref = rtv_number or dn_number
                return {
                    'status': 'error',
                    'error': 'not_found',
                    'message': 'No return found for reference: %s' % ref,
                }

            # Serialise decimals
            result_data = {}
            for source, label in [(grn_return, 'grn_return'), (rtv_record, 'rtv')]:
                if source:
                    row = dict(source)
                    for k, v in row.items():
                        if isinstance(v, __import__('decimal').Decimal):
                            row[k] = float(v)
                        elif isinstance(v, datetime):
                            row[k] = v.isoformat()
                    result_data[label] = row

            return {
                'status': 'success',
                'action': 'return_detail',
                **result_data,
                'message': 'Return details for %s retrieved.' % (rtv_number or dn_number),
            }
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'message': 'Lookup failed: ' + str(e)[:100]}
        finally:
            cur.close(); conn.close()

    # =========================================================================
    #  Existing: _list_returns  (unchanged)
    # =========================================================================
    def _list_returns(self):
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT rtv_number, vendor_name, return_reason, total_return_qty, credit_expected, status FROM rtv_headers ORDER BY created_at DESC LIMIT 10")
            rows = cur.fetchall()
            for r in rows:
                for k, v in r.items():
                    if isinstance(v, __import__('decimal').Decimal): r[k] = float(v)
            return {'status': 'success', 'action': 'return_list', 'returns': [dict(r) for r in rows], 'message': '%d returns found.' % len(rows)}
        finally:
            cur.close(); conn.close()

    # =========================================================================
    #  G-03: _list_returns_with_debit_notes  (new -- used by "show debit notes")
    # =========================================================================
    def _list_returns_with_debit_notes(self):
        """List recent returns that have debit notes issued."""
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT return_number, grn_number, vendor_name, return_reason,
                       total_return_qty, total_return_value,
                       debit_note_number, debit_note_amount, debit_note_status,
                       credit_resolution, credit_amount, status
                FROM grn_returns
                WHERE debit_note_number IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 15
            """)
            rows = cur.fetchall()
            for r in rows:
                for k, v in r.items():
                    if isinstance(v, __import__('decimal').Decimal):
                        r[k] = float(v)
            return {
                'status': 'success',
                'action': 'debit_note_list',
                'returns': [dict(r) for r in rows],
                'message': '%d debit notes found.' % len(rows),
            }
        finally:
            cur.close(); conn.close()

    # =========================================================================
    #  Existing: _extract_item  (unchanged)
    # =========================================================================
    def _extract_item(self, text):
        for kw in ['return ', 'send back ', 'damaged ']:
            if kw in text.lower():
                part = text.lower().split(kw, 1)[1]
                return part.split(' from')[0].split(' to')[0].split(',')[0].strip()[:100]
        return 'Item'

    # =========================================================================
    #  G-03: Private helpers
    # =========================================================================
    @staticmethod
    def _generate_debit_note_number() -> str:
        """Generate a debit note number in format DN-YYYYMMDDHHMMSS."""
        return "DN-%s" % datetime.now().strftime("%Y%m%d%H%M%S")

    @staticmethod
    def _map_reason_to_return_type(reason: str) -> str:
        """Map a reason code to a grn_returns.return_type enum value."""
        mapping = {
            'damaged': 'damaged',
            'wrong_item': 'wrong_item',
            'excess': 'excess',
            'quality_failure': 'quality_reject',
        }
        return mapping.get(reason, 'partial_return')

    def _send_debit_note_communication(self, return_number: str, vendor_name: str,
                                       vendor_id: str, amount: float,
                                       reason: str) -> Dict[str, Any]:
        """
        Send vendor communication for a debit note via VendorCommunicationService.
        Non-fatal: logs and returns result but never raises.
        """
        try:
            result = self.vendor_comm.send_debit_note(
                return_number=return_number,
                vendor_name=vendor_name,
                vendor_id=vendor_id or 'UNKNOWN',
                amount=amount,
                reason=reason.replace('_', ' '),
            )
            logger.info(
                "[ReturnAgent] Debit note communication for %s: status=%s comm_id=%s",
                return_number, result.get('status'), result.get('comm_id'),
            )
            return result
        except Exception as comm_err:
            logger.warning(
                "[ReturnAgent] Vendor communication failed for %s: %s",
                return_number, comm_err,
            )
            return {'status': 'failed', 'error': str(comm_err)}
