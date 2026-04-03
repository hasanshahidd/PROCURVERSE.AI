"""
POIntakeAgent — Step 1 of the 9-agent Invoice-to-Payment Pipeline
================================================================
Liztek P2P Flow: Intelligent Intake Phase

Sub-steps:
  1. Channel Monitoring  — detect new PO documents across email/portal/EDI/API/scan
  2. Document Recognition — OCR extraction + document type classification
  3. Initial Data Capture — NLP metadata (sender, date, doc type, PO number)
  4. Storage & Handover  — persist OCR log, notify PORegistrationAgent

Adapter methods used (ZERO hardcoded SQL):
  adapter.log_ocr_ingestion()     → ocr_ingestion_log
  adapter.log_notification()      → notification_log
  adapter.get_email_template()    → email_templates
  adapter.get_vendors()           → vendor lookup / validation
  adapter.log_agent_action()      → agent_actions audit
"""

from typing import Dict, Any, Optional
import json
import logging
import re
from datetime import datetime

from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.adapters.factory import get_adapter
from backend.services.ocr_service import get_ocr_service

logger = logging.getLogger(__name__)

# ── Confidence thresholds ─────────────────────────────────────────────────────
_HIGH_CONF   = 0.85   # auto-proceed to registration
_MEDIUM_CONF = 0.60   # proceed with flags
_LOW_CONF    = 0.40   # queue for manual review


def _adapter():
    return get_adapter()


class POIntakeAgent(BaseAgent):
    """
    Step 1 — PO Intake Agent.
    Receives raw PO documents from any channel, runs OCR + NLP extraction,
    validates basic structure, and hands off to PORegistrationAgent.
    """

    def __init__(self):
        super().__init__(
            name="POIntakeAgent",
            description=(
                "Monitors all inbound channels for Purchase Order documents, "
                "performs OCR extraction and NLP metadata capture, then hands "
                "off structured PO data for ERP registration."
            ),
            temperature=0.1
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gather channel metadata, raw document text, and vendor context.
        input_data keys:
          document_ref    — filename / email subject / EDI ref
          source_channel  — 'email' | 'portal' | 'edi' | 'api' | 'scan'
          sender          — email address or system ID
          raw_content     — raw text / OCR text of the document
          extracted_fields— (optional) pre-parsed dict from upstream OCR service
        """
        self.status = AgentStatus.OBSERVING
        logger.info("[POIntakeAgent] OBSERVE — channel: %s, ref: %s",
                    input_data.get('source_channel', 'unknown'),
                    input_data.get('document_ref', 'unknown'))

        obs = {
            "document_ref":   input_data.get('document_ref', 'UNKNOWN'),
            "source_channel": input_data.get('source_channel', 'unknown'),
            "sender":         input_data.get('sender', ''),
            "raw_content":    input_data.get('raw_content', ''),
            "extracted_fields": input_data.get('extracted_fields', {}),
            "vendor_validated": False,
            "vendor_record":    None,
        }

        # Attempt vendor lookup from extracted_fields.vendor or sender domain
        vendor_hint = (obs["extracted_fields"].get('vendor') or
                       _extract_domain(obs["sender"]))
        if vendor_hint:
            try:
                vendors = _adapter().get_vendors(limit=500)
                matched = _find_vendor(vendors, vendor_hint)
                if matched:
                    obs["vendor_validated"] = True
                    obs["vendor_record"] = matched
                    logger.info("[POIntakeAgent] Vendor matched: %s", matched.get('vendor_name'))
            except Exception as e:
                logger.warning("[POIntakeAgent] Vendor lookup failed: %s", e)

        return obs

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Classify document and decide on OCR confidence + next action."""
        self.status = AgentStatus.THINKING

        raw      = observations.get('raw_content', '')
        fields   = observations.get('extracted_fields', {})
        doc_ref  = observations.get('document_ref', '')

        # ── NLP Extraction ──────────────────────────────────────────────────
        if not fields:
            fields = _nlp_extract(raw)
            observations['extracted_fields'] = fields

        # ── Confidence scoring ───────────────────────────────────────────────
        confidence = _score_confidence(fields, observations.get('vendor_validated', False))

        # ── Document type classification ─────────────────────────────────────
        doc_type = _classify_document(raw, fields)
        observations['document_type'] = doc_type

        if doc_type != 'PO':
            return AgentDecision(
                action='reject_wrong_doc_type',
                reasoning=f"Document classified as '{doc_type}', not a PO. Ref: {doc_ref}",
                confidence=0.95,
                context={**observations, 'confidence': confidence},
                alternatives=['manual_review']
            )

        if confidence >= _HIGH_CONF:
            action = 'proceed_to_registration'
        elif confidence >= _MEDIUM_CONF:
            action = 'proceed_with_flags'
        else:
            action = 'queue_for_manual_review'

        reasoning = (
            f"PO detected with {confidence*100:.0f}% confidence. "
            f"Vendor: {'matched' if observations.get('vendor_validated') else 'not found'}. "
            f"Fields extracted: {list(fields.keys())}."
        )

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={**observations, 'confidence': confidence, 'extracted_fields': fields},
            alternatives=['queue_for_manual_review']
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Persist OCR log, send notification, return handoff payload."""
        self.status = AgentStatus.ACTING
        ctx         = decision.context
        action      = decision.action
        fields      = ctx.get('extracted_fields', {})
        doc_ref     = ctx.get('document_ref', 'UNKNOWN')
        channel     = ctx.get('source_channel', 'unknown')
        doc_type    = ctx.get('document_type', 'UNKNOWN')
        confidence  = ctx.get('confidence', 0.0)

        # 1. Persist OCR ingestion log (always via adapter)
        ocr_result = _adapter().log_ocr_ingestion({
            'document_ref':     doc_ref,
            'document_type':    doc_type,
            'source_channel':   channel,
            'sender':           ctx.get('sender', ''),
            'ocr_raw_text':     ctx.get('raw_content', '')[:4000],
            'extracted_fields': fields,
            'confidence_score': round(confidence * 100, 2),
            'needs_review':     action in ('queue_for_manual_review', 'reject_wrong_doc_type'),
            'linked_po_number': fields.get('po_number'),
            'agent_name':       self.name,
        })

        result = {
            'success':       True,
            'agent':         self.name,
            'action':        action,
            'document_ref':  doc_ref,
            'document_type': doc_type,
            'ocr_log_id':    ocr_result.get('id'),
            'confidence':    confidence,
            'extracted_fields': fields,
            'vendor_validated': ctx.get('vendor_validated', False),
            'vendor_record':    ctx.get('vendor_record'),
        }

        # 2. Send notification based on action
        event_type = {
            'proceed_to_registration': 'po_received',
            'proceed_with_flags':      'po_received',
            'queue_for_manual_review': 'ocr_extraction_complete',
            'reject_wrong_doc_type':   'ocr_extraction_complete',
        }.get(action, 'po_received')

        _send_notification(_adapter(), event_type, {
            'document_ref':  doc_ref,
            'po_number':     fields.get('po_number', doc_ref),
            'vendor':        (ctx.get('vendor_record') or {}).get('vendor_name', 'Unknown'),
            'confidence':    round(confidence * 100, 1),
            'document_type': doc_type,
        }, self.name)

        # 3. Audit log
        _adapter().log_agent_action(
            self.name,
            f'po_intake_{action}'[:50],
            {'document_ref': doc_ref, 'channel': channel},
            {'action': action, 'confidence': confidence, 'ocr_log_id': ocr_result.get('id')},
            True
        )

        if action == 'proceed_to_registration':
            result['next_agent'] = 'PORegistrationAgent'
            result['message'] = (
                f"PO {fields.get('po_number', doc_ref)} received and ready for registration. "
                f"Confidence: {confidence*100:.0f}%"
            )
        elif action == 'proceed_with_flags':
            result['next_agent'] = 'PORegistrationAgent'
            result['flags'] = _build_flags(fields)
            result['message'] = (
                f"PO {fields.get('po_number', doc_ref)} proceeding with validation flags. "
                f"Review required: {result['flags']}"
            )
        elif action == 'queue_for_manual_review':
            result['next_agent'] = None
            result['message'] = (
                f"Low confidence ({confidence*100:.0f}%). "
                f"Document {doc_ref} queued for AP specialist review."
            )
        else:
            result['next_agent'] = None
            result['success'] = False
            result['message'] = f"Document {doc_ref} rejected — type: {doc_type}, not a PO."

        return result

    async def learn(self, result: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        logger.info("[POIntakeAgent] Learning — action: %s, confidence: %s",
                    result.get('result', {}).get('action'),
                    result.get('result', {}).get('confidence'))

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)


# ── Helper Functions ──────────────────────────────────────────────────────────

def _extract_domain(email: str) -> str:
    """Extract domain from email for vendor hint."""
    if '@' in (email or ''):
        domain = email.split('@')[-1].split('.')[0]
        return domain
    return ''


def _find_vendor(vendors: list, hint: str) -> Optional[dict]:
    """Case-insensitive vendor name search."""
    hint_lower = hint.lower()
    for v in vendors:
        name = (v.get('vendor_name') or '').lower()
        if hint_lower in name or name in hint_lower:
            return v
    return None


def _nlp_extract(raw_text: str) -> dict:
    """
    Sprint 8: Thin wrapper that delegates PO field extraction to the
    pluggable OCR service (get_ocr_service()).

    Provider selection via OCR_PROVIDER env var:
      'regex'    → RegexOCRService (default, no API key needed)
      'mindee'   → MindeeOCRService (MINDEE_API_KEY required)
      'textract' → AWSTextractService (AWS credentials required)

    Falls back to RegexOCRService if the configured provider fails, so
    this function always returns a dict (possibly empty) and never raises.
    """
    try:
        return get_ocr_service().extract_po(raw_text)
    except Exception as exc:
        logger.warning(
            "[POIntakeAgent] OCR service failed (%s); falling back to regex: %s",
            type(exc).__name__, exc,
        )
        # Inline regex fallback — identical to the pre-Sprint-8 implementation
        return _regex_extract_po(raw_text)


def _regex_extract_po(raw_text: str) -> dict:
    """
    Inline regex fallback for PO field extraction.
    Used when the configured OCR service is unavailable.
    Mirrors the original _nlp_extract() implementation from Sprint 7.
    """
    text = raw_text or ''
    fields = {}

    # PO number patterns: PO-1234, PO/2025/001, 4500012345
    po_match = re.search(
        r'\b(PO[-/]?\d{4,}|purchase order[:\s#]+(\S+))',
        text, re.IGNORECASE
    )
    if po_match:
        fields['po_number'] = (po_match.group(2) or po_match.group(1)).strip()

    # Vendor / supplier
    vendor_match = re.search(r'(?:vendor|supplier|from)[:\s]+([A-Za-z][^\n,]{2,50})',
                              text, re.IGNORECASE)
    if vendor_match:
        fields['vendor'] = vendor_match.group(1).strip()

    # Date
    date_match = re.search(
        r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b', text)
    if date_match:
        fields['po_date'] = date_match.group(1)

    # Total amount
    amount_match = re.search(
        r'(?:total|amount|grand total)[:\s]*(?:USD|EUR|GBP|AED)?\s*([\d,]+\.?\d*)',
        text, re.IGNORECASE)
    if amount_match:
        fields['total_amount'] = amount_match.group(1).replace(',', '')

    # Currency
    curr_match = re.search(r'\b(USD|EUR|GBP|AED|SAR|INR)\b', text)
    if curr_match:
        fields['currency'] = curr_match.group(1)

    # Line item count estimate
    line_count = len(re.findall(r'^\s*\d+[\s.)\-]+\S', text, re.MULTILINE))
    if line_count > 0:
        fields['estimated_line_count'] = line_count

    return fields


def _classify_document(raw_text: str, fields: dict) -> str:
    """Classify document type from content signals."""
    text = (raw_text or '').upper()
    if any(k in text for k in ['PURCHASE ORDER', 'P.O.', 'PO NUMBER', 'ORDER NUMBER']):
        return 'PO'
    if any(k in text for k in ['INVOICE', 'TAX INVOICE', 'BILL']):
        return 'INVOICE'
    if any(k in text for k in ['GOODS RECEIPT', 'GRN', 'DELIVERY NOTE', 'PACKING SLIP']):
        return 'GRN'
    if fields.get('po_number'):
        return 'PO'
    return 'UNKNOWN'


def _score_confidence(fields: dict, vendor_validated: bool) -> float:
    """Score 0.0–1.0 based on how many critical fields were found."""
    score = 0.0
    weights = {
        'po_number':    0.35,
        'vendor':       0.20,
        'po_date':      0.15,
        'total_amount': 0.15,
        'currency':     0.05,
    }
    for field, weight in weights.items():
        if fields.get(field):
            score += weight
    if vendor_validated:
        score += 0.10
    return min(round(score, 2), 1.0)


def _build_flags(fields: dict) -> list:
    """Return list of missing critical fields as validation flags."""
    required = ['po_number', 'vendor', 'po_date', 'total_amount']
    return [f for f in required if not fields.get(f)]


def _send_notification(adapter, event_type: str, context_vars: dict, agent_name: str) -> None:
    """Log a notification row (email sending happens in notification service)."""
    try:
        template = adapter.get_email_template(event_type)
        if not template:
            return
        subject = template.get('subject', event_type)
        for k, v in context_vars.items():
            subject = subject.replace('{' + k + '}', str(v))
        recipients = adapter.get_users_by_role(template.get('recipients_role', 'procurement'))
        for user in recipients[:3]:  # cap at 3 per event to avoid spam in demo
            adapter.log_notification({
                'event_type':     event_type,
                'document_type':  'PO',
                'document_id':    context_vars.get('po_number'),
                'recipient_email': user.get('email', ''),
                'recipient_role': template.get('recipients_role'),
                'subject':        subject,
                'body':           template.get('body_html', ''),
                'status':         'pending',
                'agent_name':     agent_name,
            })
    except Exception as e:
        logger.warning("[POIntakeAgent] Notification logging failed: %s", e)


# ── Convenience wrapper ───────────────────────────────────────────────────────

async def intake_po_document(document_data: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for pipeline orchestrator."""
    agent = POIntakeAgent()
    return await agent.execute(document_data)
