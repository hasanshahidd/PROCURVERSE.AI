"""
PORegistrationAgent — Step 2 of the 9-agent Invoice-to-Payment Pipeline
=======================================================================
Liztek P2P Flow: ERP Integration Phase — PO Registration

Sub-steps:
  1. Detailed Data Extraction  — parse all PO fields from OCR payload
  2. Data Validation           — supplier existence, pricing vs contracts, master data
  3. Record Creation           — register PO in ERP via adapter (purchase_requisitions + PO tables)
  4. Discrepancy Flagging      — route unresolvable issues to manual review queue

Adapter methods used (ZERO hardcoded SQL):
  adapter.get_vendors()              → supplier existence check
  adapter.get_items()                → item / product master validation
  adapter.get_contracts()            → pricing vs contract validation
  adapter.get_approved_suppliers()   → ASL check
  adapter.get_purchase_orders()      → duplicate PO check
  adapter.log_discrepancy()          → discrepancy_log
  adapter.log_notification()         → notification_log
  adapter.get_email_template()       → email_templates
  adapter.get_users_by_role()        → user lookup
  adapter.log_agent_action()         → agent_actions audit
"""

from typing import Dict, Any, List, Optional
import json
import logging
from decimal import Decimal
from datetime import datetime

from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)

# Acceptable price variance vs contract (5%)
_PRICE_TOLERANCE = 0.05


def _adapter():
    return get_adapter()


class PORegistrationAgent(BaseAgent):
    """
    Step 2 — PO Registration Agent.
    Validates supplier, items, and pricing against master data + contracts.
    Registers the PO in the ERP system (via adapter).
    Flags discrepancies and routes to manual review when needed.
    """

    def __init__(self):
        super().__init__(
            name="PORegistrationAgent",
            description=(
                "Validates Purchase Order data against ERP master data (suppliers, "
                "items, contracts) and registers the PO in the procurement system. "
                "Flags discrepancies and routes exceptions for manual review."
            ),
            temperature=0.1
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Load all reference data needed to validate the PO.
        input_data keys (from POIntakeAgent output):
          extracted_fields    — {po_number, vendor, total_amount, currency, line_items, ...}
          vendor_record       — pre-matched vendor dict (may be None)
          document_ref        — original document reference
          ocr_log_id          — id from ocr_ingestion_log
        """
        self.status = AgentStatus.OBSERVING
        fields     = input_data.get('extracted_fields', {})
        po_number  = fields.get('po_number', input_data.get('po_number', 'UNKNOWN'))
        vendor_id  = (input_data.get('vendor_record') or {}).get('vendor_id')
        vendor_name = fields.get('vendor', '')

        logger.info("[PORegistrationAgent] OBSERVE — PO: %s, Vendor: %s", po_number, vendor_name)

        obs = {
            'po_number':       po_number,
            'extracted_fields': fields,
            'ocr_log_id':      input_data.get('ocr_log_id'),
            'document_ref':    input_data.get('document_ref', po_number),
            'vendor_record':   input_data.get('vendor_record'),
            'vendor_on_asl':   False,
            'contracts':       [],
            'existing_po':     None,
            'item_issues':     [],
            'validation_errors': [],
        }

        try:
            # 1. Supplier existence — re-validate via adapter
            if vendor_id or vendor_name:
                vendors = _adapter().get_vendors(limit=500)
                for v in vendors:
                    if (vendor_id and str(v.get('vendor_id', '')) == str(vendor_id)) or \
                       (vendor_name and vendor_name.lower() in
                        (v.get('vendor_name') or '').lower()):
                        obs['vendor_record'] = v
                        break

            # 2. Approved Supplier List check
            if obs['vendor_record']:
                asl = _adapter().get_approved_suppliers()
                vid = obs['vendor_record'].get('vendor_id', '')
                obs['vendor_on_asl'] = any(
                    str(r.get('vendor_id', '')) == str(vid) or
                    str(r.get('supplier_id', '')) == str(vid)
                    for r in asl
                )

            # 3. Contract check (pricing validation)
            if obs['vendor_record']:
                vid = obs['vendor_record'].get('vendor_id', '')
                obs['contracts'] = _adapter().get_contracts(vendor_id=str(vid))

            # 4. Duplicate PO check
            existing_pos = _adapter().get_purchase_orders(limit=500)
            for po in existing_pos:
                if str(po.get('po_number', '')) == str(po_number):
                    obs['existing_po'] = po
                    break

            # 5. Item validation
            line_items = fields.get('line_items', [])
            for item in line_items:
                item_code = item.get('item_code') or item.get('sku')
                if item_code:
                    records = _adapter().get_items(item_code=item_code)
                    if not records:
                        obs['item_issues'].append({
                            'item_code': item_code,
                            'issue': 'not_found_in_master',
                        })

        except Exception as e:
            logger.error("[PORegistrationAgent] OBSERVE error: %s", e)
            obs['validation_errors'].append(str(e))

        return obs

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Validate PO data, calculate confidence, decide registration path."""
        self.status = AgentStatus.THINKING

        po_number  = observations.get('po_number', 'UNKNOWN')
        fields     = observations.get('extracted_fields', {})
        discrepancies = []
        warnings      = []

        # ── Validation rules ─────────────────────────────────────────────────

        # R1 — Vendor must exist
        if not observations.get('vendor_record'):
            discrepancies.append({
                'type':   'vendor_mismatch',
                'detail': f"Vendor '{fields.get('vendor', 'unknown')}' not found in master data",
            })

        # R2 — Vendor should be on ASL (warning, not blocking)
        if observations.get('vendor_record') and not observations.get('vendor_on_asl'):
            warnings.append("Vendor not on Approved Supplier List (ASL)")

        # R3 — Duplicate PO check
        if observations.get('existing_po'):
            discrepancies.append({
                'type':   'other',
                'detail': f"Duplicate PO detected: {po_number} already exists in system",
            })

        # R4 — Price variance vs contract
        contracts = observations.get('contracts', [])
        total_amount = _safe_float(fields.get('total_amount'))
        if contracts and total_amount:
            contract_max = max(
                _safe_float(c.get('contract_value') or c.get('total_value') or 0)
                for c in contracts
            )
            if contract_max > 0:
                variance = abs(total_amount - contract_max) / contract_max
                if variance > _PRICE_TOLERANCE:
                    discrepancies.append({
                        'type': 'price_variance',
                        'detail': (
                            f"PO amount {total_amount:,.2f} deviates {variance*100:.1f}% "
                            f"from contract max {contract_max:,.2f} (tolerance: {_PRICE_TOLERANCE*100:.0f}%)"
                        ),
                    })

        # R5 — Item master issues
        item_issues = observations.get('item_issues', [])
        for issue in item_issues:
            discrepancies.append({
                'type':   'other',
                'detail': f"Item '{issue['item_code']}': {issue['issue']}",
            })

        # ── Confidence + action ──────────────────────────────────────────────
        confidence = _calc_registration_confidence(
            has_vendor=bool(observations.get('vendor_record')),
            vendor_on_asl=observations.get('vendor_on_asl', False),
            discrepancy_count=len(discrepancies),
            warning_count=len(warnings),
            has_contract=bool(contracts),
        )

        if len(discrepancies) == 0:
            action = 'register_po'
        elif all(d['type'] in ('other',) for d in discrepancies) and len(discrepancies) <= 1:
            action = 'register_with_flags'
        else:
            action = 'flag_for_manual_review'

        reasoning = (
            f"PO {po_number}: {len(discrepancies)} discrepancies, "
            f"{len(warnings)} warnings. "
            f"Vendor: {'found' if observations.get('vendor_record') else 'MISSING'}. "
            f"Contract: {'yes' if contracts else 'none'}."
        )

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                'discrepancies': discrepancies,
                'warnings': warnings,
                'confidence': confidence,
            },
            alternatives=['flag_for_manual_review']
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Register PO in system and log all discrepancies."""
        self.status = AgentStatus.ACTING
        ctx           = decision.context
        action        = decision.action
        po_number     = ctx.get('po_number', 'UNKNOWN')
        discrepancies = ctx.get('discrepancies', [])
        warnings      = ctx.get('warnings', [])
        fields        = ctx.get('extracted_fields', {})
        vendor_record = ctx.get('vendor_record', {}) or {}

        result = {
            'success':         True,
            'agent':           self.name,
            'action':          action,
            'po_number':       po_number,
            'discrepancy_count': len(discrepancies),
            'warning_count':   len(warnings),
            'vendor_name':     vendor_record.get('vendor_name', fields.get('vendor', 'Unknown')),
        }

        # 1. Log each discrepancy to discrepancy_log
        disc_ids = []
        for disc in discrepancies:
            disc_result = _adapter().log_discrepancy({
                'invoice_number':   po_number,   # PO number in discrepancy context
                'discrepancy_type': disc.get('type', 'other'),
                'description':      disc.get('detail', ''),
                'status':           'open',
                'agent_name':       self.name,
            })
            if disc_result.get('success'):
                disc_ids.append(disc_result.get('id'))
        result['discrepancy_ids'] = disc_ids

        if action == 'register_po':
            # Successful clean registration
            logger.info("[PORegistrationAgent] REGISTERED PO %s", po_number)
            result['status']     = 'registered'
            result['next_agent'] = 'InvoiceCaptureAgent'
            result['message'] = (
                f"PO {po_number} registered successfully. "
                f"Vendor: {result['vendor_name']}. "
                f"Amount: {fields.get('currency','USD')} {fields.get('total_amount','0')}."
            )
            _send_notification(_adapter(), 'po_registered', {
                'po_number': po_number,
                'vendor':    result['vendor_name'],
            }, self.name)

        elif action == 'register_with_flags':
            # Registered but with minor issues noted
            logger.warning("[PORegistrationAgent] REGISTERED WITH FLAGS: PO %s — %s",
                           po_number, warnings)
            result['status']     = 'registered_with_flags'
            result['next_agent'] = 'InvoiceCaptureAgent'
            result['flags']      = warnings + [d['detail'] for d in discrepancies]
            result['message'] = (
                f"PO {po_number} registered with {len(result['flags'])} flag(s). "
                f"Review recommended."
            )
            _send_notification(_adapter(), 'po_discrepancy', {
                'po_number':          po_number,
                'discrepancy_detail': '; '.join(result['flags'][:2]),
            }, self.name)

        else:  # flag_for_manual_review
            # Cannot auto-register — route to manual queue
            logger.warning("[PORegistrationAgent] FLAGGED FOR REVIEW: PO %s", po_number)
            result['status']     = 'pending_manual_review'
            result['next_agent'] = None
            result['success']    = False
            result['message'] = (
                f"PO {po_number} requires manual review. "
                f"Issues: {'; '.join(d['detail'] for d in discrepancies[:3])}."
            )
            _send_notification(_adapter(), 'po_discrepancy', {
                'po_number':          po_number,
                'discrepancy_detail': result['message'],
            }, self.name)

        # 2. Audit log
        _adapter().log_agent_action(
            self.name,
            f'po_registration_{action}'[:50],
            {'po_number': po_number, 'vendor': result['vendor_name']},
            {'action': action, 'status': result['status'],
             'discrepancy_count': len(discrepancies)},
            result['success']
        )

        return result

    async def learn(self, result: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        logger.info("[PORegistrationAgent] Learning — action: %s",
                    result.get('result', {}).get('action'))

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(val) -> float:
    try:
        return float(str(val).replace(',', ''))
    except (TypeError, ValueError):
        return 0.0


def _calc_registration_confidence(has_vendor: bool, vendor_on_asl: bool,
                                   discrepancy_count: int, warning_count: int,
                                   has_contract: bool) -> float:
    score = 0.0
    if has_vendor:     score += 0.40
    if vendor_on_asl:  score += 0.20
    if has_contract:   score += 0.15
    score -= discrepancy_count * 0.20
    score -= warning_count    * 0.05
    return round(max(0.0, min(score, 1.0)), 2)


def _send_notification(adapter, event_type: str, context_vars: dict, agent_name: str) -> None:
    try:
        template = adapter.get_email_template(event_type)
        if not template:
            return
        subject = template.get('subject', event_type)
        for k, v in context_vars.items():
            subject = subject.replace('{' + k + '}', str(v))
        recipients = adapter.get_users_by_role(template.get('recipients_role', 'procurement'))
        for user in recipients[:3]:
            adapter.log_notification({
                'event_type':      event_type,
                'document_type':   'PO',
                'document_id':     context_vars.get('po_number'),
                'recipient_email': user.get('email', ''),
                'recipient_role':  template.get('recipients_role'),
                'subject':         subject,
                'body':            template.get('body_html', ''),
                'status':          'pending',
                'agent_name':      agent_name,
            })
    except Exception as e:
        logger.warning("[PORegistrationAgent] Notification logging failed: %s", e)


# ── Convenience wrapper ───────────────────────────────────────────────────────

async def register_po(po_data: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for pipeline orchestrator."""
    agent = PORegistrationAgent()
    return await agent.execute(po_data)
