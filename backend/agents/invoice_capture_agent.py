"""
InvoiceCaptureAgent — Step 3 of the 9-agent Invoice-to-Payment Pipeline
========================================================================
Liztek P2P Flow: Intelligent Intake Phase — Invoice Side

Sub-steps:
  1. Invoice Detection & Acquisition — monitor all inbound channels
  2. Initial Processing              — OCR + GenAI for field extraction
  3. Receipt Date Recording          — official receipt timestamp
  4. Secure Storage                  — OCR log + link to PO

Adapter methods used (ZERO hardcoded SQL):
  adapter.get_vendor_invoices()      → duplicate invoice check
  adapter.get_purchase_orders()      → link invoice to PO
  adapter.log_ocr_ingestion()        → ocr_ingestion_log
  adapter.log_notification()         → notification_log
  adapter.get_email_template()       → email_templates
  adapter.get_users_by_role()        → user lookup
  adapter.place_invoice_hold()       → invoice_holds (if duplicate detected)
  adapter.log_agent_action()         → agent_actions audit
"""

from typing import Dict, Any, Optional
import json
import logging
import re
from datetime import datetime, date

from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.adapters.factory import get_adapter
from backend.services.ocr_service import get_ocr_service

logger = logging.getLogger(__name__)

# Confidence thresholds
_HIGH_CONF   = 0.80
_MEDIUM_CONF = 0.55


def _adapter():
    return get_adapter()


class InvoiceCaptureAgent(BaseAgent):
    """
    Step 3 — Invoice Capture Agent.
    Captures invoices from all channels (email, AP portal, EDI, API),
    performs OCR + field extraction, deduplication check, and logs receipt.
    Hands validated invoice payload to InvoiceRoutingAgent.
    """

    def __init__(self):
        super().__init__(
            name="InvoiceCaptureAgent",
            description=(
                "Captures vendor invoices from all inbound channels, performs OCR "
                "and AI-powered field extraction, deduplication check, and records "
                "the official receipt date before routing for matching."
            ),
            temperature=0.1
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Collect channel metadata and run OCR extraction.
        input_data keys:
          document_ref      — filename / email subject
          source_channel    — 'email'|'portal'|'edi'|'api'|'scan'
          sender            — sender email or system
          raw_content       — raw OCR / document text
          extracted_fields  — (optional) pre-parsed dict
          receipt_date      — (optional) ISO date string; defaults to today
        """
        self.status = AgentStatus.OBSERVING
        logger.info("[InvoiceCaptureAgent] OBSERVE — channel: %s, ref: %s",
                    input_data.get('source_channel', 'unknown'),
                    input_data.get('document_ref', 'unknown'))

        obs = {
            'document_ref':     input_data.get('document_ref', 'UNKNOWN'),
            'source_channel':   input_data.get('source_channel', 'unknown'),
            'sender':           input_data.get('sender', ''),
            'raw_content':      input_data.get('raw_content', ''),
            'extracted_fields': input_data.get('extracted_fields', {}),
            'receipt_date':     input_data.get('receipt_date') or date.today().isoformat(),
            'duplicate_found':  False,
            'existing_invoice': None,
            'linked_po':        None,
        }

        # Run OCR extraction if not pre-supplied
        if not obs['extracted_fields']:
            obs['extracted_fields'] = _ocr_extract_invoice(obs['raw_content'])

        fields = obs['extracted_fields']

        try:
            # 1. Duplicate invoice check
            inv_no = fields.get('invoice_number') or fields.get('invoice_no')
            if inv_no:
                existing = _adapter().get_vendor_invoices(invoice_no=inv_no, limit=5)
                if existing:
                    obs['duplicate_found']  = True
                    obs['existing_invoice'] = existing[0]
                    logger.warning("[InvoiceCaptureAgent] Duplicate invoice: %s", inv_no)

            # 2. PO link lookup
            po_number = fields.get('po_number') or fields.get('po_ref')
            if po_number:
                pos = _adapter().get_purchase_orders(limit=500)
                for po in pos:
                    if str(po.get('po_number', '')) == str(po_number):
                        obs['linked_po'] = po
                        break

        except Exception as e:
            logger.error("[InvoiceCaptureAgent] OBSERVE error: %s", e)
            obs['observe_error'] = str(e)

        return obs

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Classify invoice, check for duplicates, calculate confidence."""
        self.status = AgentStatus.THINKING

        fields    = observations.get('extracted_fields', {})
        inv_no    = fields.get('invoice_number') or fields.get('invoice_no', 'UNKNOWN')
        doc_ref   = observations.get('document_ref', 'UNKNOWN')

        # ── Document type check ───────────────────────────────────────────────
        doc_type = _classify_invoice_doc(observations.get('raw_content', ''), fields)
        observations['document_type'] = doc_type

        if doc_type != 'INVOICE':
            return AgentDecision(
                action='reject_wrong_doc_type',
                reasoning=f"Document '{doc_ref}' classified as '{doc_type}', not an INVOICE.",
                confidence=0.92,
                context={**observations, 'confidence': 0.92},
                alternatives=['manual_review']
            )

        # ── Duplicate check ───────────────────────────────────────────────────
        if observations.get('duplicate_found'):
            return AgentDecision(
                action='reject_duplicate',
                reasoning=(
                    f"Invoice {inv_no} already exists in system. "
                    f"Possible duplicate — placing hold for review."
                ),
                confidence=0.95,
                context={**observations, 'confidence': 0.95},
                alternatives=['manual_review']
            )

        # ── Confidence scoring ────────────────────────────────────────────────
        confidence = _score_invoice_confidence(fields, bool(observations.get('linked_po')))
        observations['confidence'] = confidence

        if confidence >= _HIGH_CONF:
            action = 'capture_and_route'
        elif confidence >= _MEDIUM_CONF:
            action = 'capture_with_flags'
        else:
            action = 'queue_for_manual_review'

        reasoning = (
            f"Invoice {inv_no}: confidence {confidence*100:.0f}%. "
            f"PO linked: {'yes' if observations.get('linked_po') else 'no'}. "
            f"Fields: {list(fields.keys())}."
        )

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={**observations, 'confidence': confidence},
            alternatives=['queue_for_manual_review']
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Persist OCR record, send notifications, build routing payload."""
        self.status   = AgentStatus.ACTING
        ctx           = decision.context
        action        = decision.action
        fields        = ctx.get('extracted_fields', {})
        doc_ref       = ctx.get('document_ref', 'UNKNOWN')
        channel       = ctx.get('source_channel', 'unknown')
        confidence    = ctx.get('confidence', 0.0)
        receipt_date  = ctx.get('receipt_date', date.today().isoformat())
        inv_no        = fields.get('invoice_number') or fields.get('invoice_no', doc_ref)

        result = {
            'success':          True,
            'agent':            self.name,
            'action':           action,
            'document_ref':     doc_ref,
            'invoice_number':   inv_no,
            'receipt_date':     receipt_date,
            'confidence':       confidence,
            'extracted_fields': fields,
            'linked_po':        ctx.get('linked_po'),
        }

        # ── Duplicate → hold + reject ─────────────────────────────────────────
        if action == 'reject_duplicate':
            hold_result = _adapter().place_invoice_hold({
                'invoice_number': inv_no,
                'po_number':      fields.get('po_number'),
                'hold_reason':    'duplicate_suspected',
                'hold_notes':     f"Duplicate detected during capture. Ref: {doc_ref}",
                'placed_by':      self.name,
                'agent_name':     self.name,
            })
            result['success']    = False
            result['status']     = 'duplicate_hold'
            result['hold_id']    = hold_result.get('id')
            result['next_agent'] = None
            result['message']    = (
                f"Invoice {inv_no} flagged as duplicate — hold placed "
                f"(hold_id={hold_result.get('id')}). AP specialist review required."
            )
            _send_notification(_adapter(), 'invoice_hold_placed', {
                'invoice_number': inv_no,
                'reason':         'Duplicate invoice suspected',
            }, self.name)

        # ── Wrong doc type ────────────────────────────────────────────────────
        elif action == 'reject_wrong_doc_type':
            result['success']    = False
            result['status']     = 'rejected'
            result['next_agent'] = None
            result['message']    = (
                f"Document {doc_ref} is not an invoice "
                f"(type: {ctx.get('document_type', 'UNKNOWN')}). Rejected."
            )

        else:
            # ── Log OCR ingestion ─────────────────────────────────────────────
            ocr_result = _adapter().log_ocr_ingestion({
                'document_ref':     doc_ref,
                'document_type':    'INVOICE',
                'source_channel':   channel,
                'sender':           ctx.get('sender', ''),
                'ocr_raw_text':     ctx.get('raw_content', '')[:4000],
                'extracted_fields': {
                    **fields,
                    'receipt_date': receipt_date,
                },
                'confidence_score': round(confidence * 100, 2),
                'needs_review':     action == 'capture_with_flags',
                'linked_po_number': fields.get('po_number'),
                'linked_invoice_no': inv_no,
                'agent_name':       self.name,
            })
            result['ocr_log_id'] = ocr_result.get('id')

            if action == 'capture_and_route':
                result['status']     = 'captured'
                result['next_agent'] = 'InvoiceRoutingAgent'
                result['message'] = (
                    f"Invoice {inv_no} captured from {channel}. "
                    f"Receipt date: {receipt_date}. "
                    f"PO: {fields.get('po_number', 'TBD')}. "
                    f"Routing for matching."
                )
                _send_notification(_adapter(), 'invoice_received', {
                    'invoice_number': inv_no,
                    'vendor':         fields.get('vendor', 'Unknown'),
                    'amount':         fields.get('total_amount', '0'),
                    'currency':       fields.get('currency', 'USD'),
                }, self.name)

            else:  # capture_with_flags / manual_review
                result['status']     = 'captured_with_flags'
                result['next_agent'] = 'InvoiceRoutingAgent'
                result['flags']      = _build_invoice_flags(fields)
                result['message'] = (
                    f"Invoice {inv_no} captured with {len(result['flags'])} flag(s). "
                    f"Flags: {result['flags']}."
                )
                _send_notification(_adapter(), 'invoice_received', {
                    'invoice_number': inv_no,
                    'vendor':         fields.get('vendor', 'Unknown'),
                    'amount':         fields.get('total_amount', '0'),
                    'currency':       fields.get('currency', 'USD'),
                }, self.name)

        # Audit log
        _adapter().log_agent_action(
            self.name,
            f'invoice_capture_{action}'[:50],
            {'document_ref': doc_ref, 'channel': channel},
            {'action': action, 'invoice_number': inv_no,
             'ocr_log_id': result.get('ocr_log_id')},
            result['success']
        )

        return result

    async def learn(self, result: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        logger.info("[InvoiceCaptureAgent] Learning — action: %s",
                    result.get('result', {}).get('action'))

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)


# ── Helper Functions ──────────────────────────────────────────────────────────

def _ocr_extract_invoice(raw_text: str) -> dict:
    """
    Sprint 8: Thin wrapper that delegates invoice field extraction to the
    pluggable OCR service (get_ocr_service()).

    Provider selection via OCR_PROVIDER env var:
      'regex'    → RegexOCRService (default, no API key needed)
      'mindee'   → MindeeOCRService (MINDEE_API_KEY required)
      'textract' → AWSTextractService (AWS credentials required)

    Falls back to RegexOCRService if the configured provider fails, so
    this function always returns a dict (possibly empty) and never raises.
    """
    try:
        return get_ocr_service().extract_invoice(raw_text)
    except Exception as exc:
        logger.warning(
            "[InvoiceCaptureAgent] OCR service failed (%s); falling back to regex: %s",
            type(exc).__name__, exc,
        )
        # Inline regex fallback — identical to the pre-Sprint-8 implementation
        return _regex_extract_invoice(raw_text)


def _regex_extract_invoice(raw_text: str) -> dict:
    """
    Inline regex fallback for invoice field extraction.
    Used when the configured OCR service is unavailable.
    Mirrors the original _ocr_extract_invoice() implementation from Sprint 7.
    """
    text = raw_text or ''
    fields = {}

    # Invoice number
    inv_match = re.search(
        r'(?:invoice\s*(?:no|number|#|num)[:\s#]*)([\w\-/]+)',
        text, re.IGNORECASE
    )
    if inv_match:
        fields['invoice_number'] = inv_match.group(1).strip()

    # PO reference
    po_match = re.search(
        r'(?:po\s*(?:no|number|#|ref|reference)[:\s#]*)([\w\-/]+)',
        text, re.IGNORECASE
    )
    if po_match:
        fields['po_number'] = po_match.group(1).strip()

    # Vendor
    vendor_match = re.search(
        r'(?:vendor|supplier|billed?\s*by|from)[:\s]+([A-Za-z][^\n,]{2,50})',
        text, re.IGNORECASE
    )
    if vendor_match:
        fields['vendor'] = vendor_match.group(1).strip()

    # Invoice date
    date_match = re.search(
        r'(?:invoice\s*date|date)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})',
        text, re.IGNORECASE
    )
    if date_match:
        fields['invoice_date'] = date_match.group(1)

    # Due date
    due_match = re.search(
        r'(?:due\s*date|payment\s*due)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})',
        text, re.IGNORECASE
    )
    if due_match:
        fields['due_date'] = due_match.group(1)

    # Total amount
    total_match = re.search(
        r'(?:total\s*(?:amount|due|payable)|amount\s*due)[:\s]*(?:USD|EUR|GBP|AED)?\s*([\d,]+\.?\d*)',
        text, re.IGNORECASE
    )
    if total_match:
        fields['total_amount'] = total_match.group(1).replace(',', '')

    # Currency
    curr_match = re.search(r'\b(USD|EUR|GBP|AED|SAR|INR)\b', text)
    if curr_match:
        fields['currency'] = curr_match.group(1)

    # Payment terms (Net 30, Net 60, etc.)
    terms_match = re.search(r'\b(Net\s*\d+|Immediate|Due on receipt)\b', text, re.IGNORECASE)
    if terms_match:
        fields['payment_terms'] = terms_match.group(1)

    return fields


def _classify_invoice_doc(raw_text: str, fields: dict) -> str:
    """Classify whether document is an invoice."""
    text = (raw_text or '').upper()
    if any(k in text for k in ['TAX INVOICE', 'INVOICE', 'BILL TO', 'AMOUNT DUE']):
        return 'INVOICE'
    if any(k in text for k in ['PURCHASE ORDER', 'P.O.', 'ORDER NUMBER']):
        return 'PO'
    if any(k in text for k in ['GOODS RECEIPT', 'DELIVERY NOTE', 'PACKING SLIP']):
        return 'GRN'
    if fields.get('invoice_number'):
        return 'INVOICE'
    return 'UNKNOWN'


def _score_invoice_confidence(fields: dict, po_linked: bool) -> float:
    """Score invoice extraction quality."""
    weights = {
        'invoice_number': 0.30,
        'vendor':         0.20,
        'invoice_date':   0.15,
        'total_amount':   0.15,
        'po_number':      0.10,
        'currency':       0.05,
    }
    score = sum(weights[f] for f in weights if fields.get(f))
    if po_linked:
        score += 0.05
    return round(min(score, 1.0), 2)


def _build_invoice_flags(fields: dict) -> list:
    required = ['invoice_number', 'vendor', 'invoice_date', 'total_amount', 'po_number']
    return [f"missing_{f}" for f in required if not fields.get(f)]


def _send_notification(adapter, event_type: str, context_vars: dict, agent_name: str) -> None:
    try:
        template = adapter.get_email_template(event_type)
        if not template:
            return
        subject = template.get('subject', event_type)
        for k, v in context_vars.items():
            subject = subject.replace('{' + k + '}', str(v))
        role = template.get('recipients_role', 'ap_specialist')
        for user in adapter.get_users_by_role(role)[:3]:
            adapter.log_notification({
                'event_type':      event_type,
                'document_type':   'INVOICE',
                'document_id':     context_vars.get('invoice_number'),
                'recipient_email': user.get('email', ''),
                'recipient_role':  role,
                'subject':         subject,
                'body':            template.get('body_html', ''),
                'status':          'pending',
                'agent_name':      agent_name,
            })
    except Exception as e:
        logger.warning("[InvoiceCaptureAgent] Notification logging failed: %s", e)


# ── Convenience wrapper ───────────────────────────────────────────────────────

async def capture_invoice(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for pipeline orchestrator."""
    agent = InvoiceCaptureAgent()
    return await agent.execute(invoice_data)
