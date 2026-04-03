"""
DocumentProcessingAgent — WF-01 / WF-05
=========================================
Document Parsing & Data Extraction.

Workflows covered
-----------------
WF-01  Automated Document Ingestion & Classification
       Accepts raw text content from any procurement document, detects the
       document type, and extracts structured fields via regex.
WF-05  PO / Invoice / Contract / RFQ Data Entry Automation
       Populates downstream procurement workflows with extracted structured data
       so human re-keying is eliminated.

Business value
--------------
- Eliminates manual data entry for POs, invoices, contracts, and RFQs
- Standardised field extraction enables downstream 3-way matching
- Confidence scoring surfaces uncertain extractions for human review
- Validation warnings prevent bad data from entering the system
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.agents import AgentDecision, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)

# ── Regex library ─────────────────────────────────────────────────────────────

# --- PO patterns ---
_RE_PO_NUMBER     = re.compile(r'\bP\.?O\.?\s*[#:\-]?\s*([A-Z0-9\-/]{3,20})\b', re.I)
_RE_PO_VENDOR     = re.compile(r'(?:vendor|supplier|to)\s*[:\-]?\s*([A-Za-z0-9 &,.\'-]{3,60})', re.I)
_RE_PO_TOTAL      = re.compile(r'(?:total|grand\s+total|order\s+total|amount)\s*[:\-]?\s*([A-Z]{0,3}\s*[\$€£]?\s*[\d,]+\.?\d{0,2})', re.I)
_RE_PO_CURRENCY   = re.compile(r'\b(USD|EUR|GBP|AED|SAR|INR|CAD|AUD)\b', re.I)
_RE_PAYMENT_TERMS = re.compile(r'(?:payment\s+terms?|terms?)\s*[:\-]?\s*(net\s*\d+|[0-9]+/[0-9]+\s*net\s*[0-9]+|\d+\s*days?)', re.I)

# --- Invoice patterns ---
_RE_INV_NUMBER    = re.compile(r'\bINV[-#\s]?([A-Z0-9\-/]{3,20})\b', re.I)
_RE_INV_DATE      = re.compile(r'(?:invoice\s+date|date)\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})', re.I)
_RE_INV_DUE       = re.compile(r'(?:due\s+date|payment\s+due)\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})', re.I)
_RE_INV_AMOUNT    = re.compile(r'(?:total|amount\s+due|balance\s+due|invoice\s+total)\s*[:\-]?\s*([\$€£]?\s*[\d,]+\.?\d{0,2})', re.I)
_RE_PO_REF        = re.compile(r'(?:PO\s+ref(?:erence)?|purchase\s+order)\s*[:\-]?\s*([A-Z0-9\-/]{3,20})', re.I)

# --- Contract patterns ---
_RE_CONTRACT_ID   = re.compile(r'(?:contract\s+(?:no|number|id|ref))\s*[:\-]?\s*([A-Z0-9\-/]{3,20})', re.I)
_RE_CONTRACT_START= re.compile(r'(?:start\s+date|commencement\s+date|effective\s+date)\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})', re.I)
_RE_CONTRACT_END  = re.compile(r'(?:end\s+date|expiry\s+date|termination\s+date)\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})', re.I)
_RE_CONTRACT_VAL  = re.compile(r'(?:contract\s+value|total\s+value|agreement\s+value)\s*[:\-]?\s*([\$€£]?\s*[\d,]+\.?\d{0,2})', re.I)

# --- RFQ patterns ---
_RE_RFQ_NUMBER    = re.compile(r'\bRFQ[-#\s]?([A-Z0-9\-/]{3,20})\b', re.I)
_RE_RFQ_DEADLINE  = re.compile(r'(?:submission\s+deadline|response\s+by|deadline|due\s+by)\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})', re.I)

# --- Type-detection keywords (score-based) ---
_DOC_KEYWORDS: Dict[str, List[str]] = {
    "invoice": ["invoice", "inv #", "tax invoice", "amount due", "payment due", "remit"],
    "purchase_order": ["purchase order", "p.o.", "po number", "ordered by", "order total", "ship to"],
    "contract": ["contract", "agreement", "terms and conditions", "obligations", "governing law", "indemnification"],
    "rfq": ["request for quotation", "rfq", "request for quote", "quotation request", "vendor list", "submit quote"],
}


class DocumentProcessingAgent(BaseAgent):
    """
    Parses raw procurement document text and extracts structured fields.

    Observe  → Accept raw_content string from context; detect document type by
               keyword scoring.
    Decide   → Route to the appropriate extractor (PO / Invoice / Contract / RFQ).
               Compute confidence and validation_warnings.
    Act      → Return extracted_fields, document_type, confidence, warnings.
    Learn    → Log document type detected and field extraction success rate.
    """

    def __init__(self) -> None:
        super().__init__(
            name="DocumentProcessingAgent",
            description=(
                "Parses and extracts structured fields from procurement documents "
                "(PO, Invoice, Contract, RFQ) using regex-based field detection."
            ),
            temperature=0.1,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.status = AgentStatus.OBSERVING

        raw_content: str = str(context.get("raw_content") or context.get("document_text") or "")
        document_type_hint: str = str(context.get("document_type") or "")

        # ── Sprint 8: Real OCR path ───────────────────────────────────────────
        # If file_content_b64 and filename are present, run real OCR extraction.
        ocr_result: Optional[Dict[str, Any]] = None
        file_content_b64: str = str(context.get("file_content_b64") or "")
        filename: str = str(context.get("filename") or "")

        if file_content_b64 and filename:
            try:
                from backend.services.ocr_service import process_document as ocr_process_document
                file_bytes = base64.b64decode(file_content_b64)
                doc_type_hint = document_type_hint or "auto"
                ocr_result = ocr_process_document(file_bytes, filename, doc_type_hint)
                raw_content = ocr_result.get("raw_text", "") or raw_content
                logger.info(
                    "[DocumentProcessingAgent] OCR completed: source=%s type=%s confidence=%.2f",
                    ocr_result.get("source"), ocr_result.get("doc_type_detected"),
                    ocr_result.get("confidence", 0),
                )
            except Exception as exc:
                logger.warning(
                    "[DocumentProcessingAgent] OCR processing failed (%s); "
                    "falling back to text-based extraction.", exc,
                )

        if not raw_content.strip():
            logger.warning("[DocumentProcessingAgent] No document content provided.")

        # Auto-detect document type unless caller supplied a hint
        if ocr_result and ocr_result.get("doc_type_detected") and not document_type_hint:
            final_type = ocr_result["doc_type_detected"]
            type_confidence = ocr_result.get("confidence", 0.7)
        else:
            detected_type, type_confidence = self._detect_document_type(raw_content)
            if document_type_hint:
                final_type = document_type_hint.lower()
                type_confidence = 1.0  # caller is certain
            else:
                final_type = detected_type

        logger.info(
            "[DocumentProcessingAgent] Content length=%d  detected_type=%s  confidence=%.2f",
            len(raw_content), final_type, type_confidence,
        )

        return {
            "raw_content": raw_content,
            "document_type": final_type,
            "type_detection_confidence": type_confidence,
            "input_context": context,
            "ocr_result": ocr_result,  # None if not available
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        self.status = AgentStatus.THINKING

        raw_content: str = observations.get("raw_content", "")
        document_type: str = observations.get("document_type", "unknown")

        if not raw_content.strip():
            return AgentDecision(
                action="no_content",
                reasoning="No document content provided — cannot extract fields.",
                confidence=0.95,
                context=observations,
            )

        # Dispatch to the correct extractor
        extractors = {
            "purchase_order": self._extract_po,
            "invoice": self._extract_invoice,
            "contract": self._extract_contract,
            "rfq": self._extract_rfq,
        }

        extractor = extractors.get(document_type)
        if extractor is None:
            return AgentDecision(
                action="unknown_document_type",
                reasoning=f"Document type '{document_type}' is not supported.",
                confidence=0.6,
                context={**observations, "extracted_fields": {}, "validation_warnings": []},
            )

        extracted_fields, validation_warnings = extractor(raw_content)

        # Confidence: type detection confidence × field completeness
        required_fields = self._required_fields(document_type)
        filled = sum(1 for f in required_fields if extracted_fields.get(f))
        field_pct = filled / len(required_fields) if required_fields else 1.0
        confidence = round(observations.get("type_detection_confidence", 0.8) * field_pct, 2)
        confidence = max(confidence, 0.3)

        reasoning = (
            f"Extracted {filled}/{len(required_fields)} required fields for "
            f"document_type='{document_type}'. "
            f"Warnings: {len(validation_warnings)}."
        )

        return AgentDecision(
            action="extract_document_fields",
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "extracted_fields": extracted_fields,
                "validation_warnings": validation_warnings,
                "fields_filled": filled,
                "fields_required": len(required_fields),
            },
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        self.status = AgentStatus.ACTING

        ctx = decision.context
        action = decision.action
        ocr_result = ctx.get("ocr_result")  # populated by Sprint 8 OCR path

        # ── Build OCR-sourced fields list (Sprint 8) ──────────────────────────
        # If OCR was run, include the richer structured fields list from the
        # ocr_service alongside the classic regex extracted_fields dict.
        ocr_fields: List[Dict[str, Any]] = []
        if ocr_result and isinstance(ocr_result.get("fields"), list):
            ocr_fields = ocr_result["fields"]

        result: Dict[str, Any] = {
            "success": True,
            "agent": self.name,
            "action": action,
            "document_type": ctx.get("document_type", "unknown"),
            "confidence": decision.confidence,
            "extracted_fields": ctx.get("extracted_fields", {}),
            "validation_warnings": ctx.get("validation_warnings", []),
            "fields_filled": ctx.get("fields_filled", 0),
            "fields_required": ctx.get("fields_required", 0),
            "timestamp": datetime.now().isoformat(),
        }

        # Attach OCR-specific fields if available
        if ocr_result:
            result["ocr_source"] = ocr_result.get("source", "unknown")
            result["ocr_fields"] = ocr_fields
            result["ocr_raw_text_length"] = len(ocr_result.get("raw_text", ""))

        if action in ("no_content", "unknown_document_type"):
            result["success"] = False
            result["message"] = decision.reasoning
        else:
            warnings = ctx.get("validation_warnings", [])
            filled = ctx.get("fields_filled", 0)
            required = ctx.get("fields_required", 1)
            ocr_note = (
                f" OCR source: {ocr_result.get('source')}." if ocr_result else ""
            )
            result["message"] = (
                f"Extracted {filled}/{required} fields from "
                f"'{ctx.get('document_type')}' document."
                f"{ocr_note} "
                f"{'⚠ ' + str(len(warnings)) + ' warning(s).' if warnings else 'No warnings.'}"
            )

        await self._log_action(
            action_type="document_processing",
            input_data={
                "document_type": ctx.get("document_type"),
                "content_length": len(ctx.get("raw_content", "")),
                "ocr_used": ocr_result is not None,
            },
            output_data=result,
            success=result["success"],
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        result = learn_context.get("result", {})
        logger.info(
            "[DocumentProcessingAgent] Learned: type=%s  fields=%d/%d  warnings=%d",
            result.get("document_type", "?"),
            result.get("fields_filled", 0),
            result.get("fields_required", 0),
            len(result.get("validation_warnings", [])),
        )

    # ── Extractors ─────────────────────────────────────────────────────────────

    def _extract_po(self, text: str) -> Tuple[Dict[str, Any], List[str]]:
        fields: Dict[str, Any] = {}
        warnings: List[str] = []

        fields["po_number"]      = self._first_match(_RE_PO_NUMBER, text)
        fields["vendor"]         = self._first_match(_RE_PO_VENDOR, text)
        fields["total"]          = self._parse_amount(self._first_match(_RE_PO_TOTAL, text))
        fields["currency"]       = (self._first_match(_RE_PO_CURRENCY, text) or "USD").upper()
        fields["payment_terms"]  = self._first_match(_RE_PAYMENT_TERMS, text)
        fields["line_items"]     = self._extract_line_items(text)

        if not fields["po_number"]:
            warnings.append("Could not extract PO number.")
        if not fields["vendor"]:
            warnings.append("Could not extract vendor name.")
        if not fields["total"]:
            warnings.append("Could not extract PO total amount.")

        return fields, warnings

    def _extract_invoice(self, text: str) -> Tuple[Dict[str, Any], List[str]]:
        fields: Dict[str, Any] = {}
        warnings: List[str] = []

        fields["invoice_number"] = self._first_match(_RE_INV_NUMBER, text)
        fields["date"]           = self._first_match(_RE_INV_DATE, text)
        fields["due_date"]       = self._first_match(_RE_INV_DUE, text)
        fields["vendor"]         = self._first_match(_RE_PO_VENDOR, text)
        fields["amount"]         = self._parse_amount(self._first_match(_RE_INV_AMOUNT, text))
        fields["currency"]       = (self._first_match(_RE_PO_CURRENCY, text) or "USD").upper()
        fields["po_reference"]   = self._first_match(_RE_PO_REF, text)

        if not fields["invoice_number"]:
            warnings.append("Could not extract invoice number.")
        if not fields["amount"]:
            warnings.append("Could not extract invoice amount.")
        if not fields["due_date"]:
            warnings.append("Due date not found — payment terms may need manual check.")

        return fields, warnings

    def _extract_contract(self, text: str) -> Tuple[Dict[str, Any], List[str]]:
        fields: Dict[str, Any] = {}
        warnings: List[str] = []

        fields["contract_id"]    = self._first_match(_RE_CONTRACT_ID, text)
        fields["vendor"]         = self._first_match(_RE_PO_VENDOR, text)
        fields["start_date"]     = self._first_match(_RE_CONTRACT_START, text)
        fields["end_date"]       = self._first_match(_RE_CONTRACT_END, text)
        fields["value"]          = self._parse_amount(self._first_match(_RE_CONTRACT_VAL, text))
        fields["currency"]       = (self._first_match(_RE_PO_CURRENCY, text) or "USD").upper()
        fields["payment_terms"]  = self._first_match(_RE_PAYMENT_TERMS, text)

        if not fields["contract_id"]:
            warnings.append("Could not extract contract ID/number.")
        if not fields["start_date"] or not fields["end_date"]:
            warnings.append("Contract start or end date missing.")
        if not fields["value"]:
            warnings.append("Contract value not found.")

        return fields, warnings

    def _extract_rfq(self, text: str) -> Tuple[Dict[str, Any], List[str]]:
        fields: Dict[str, Any] = {}
        warnings: List[str] = []

        fields["rfq_number"]     = self._first_match(_RE_RFQ_NUMBER, text)
        fields["deadline"]       = self._first_match(_RE_RFQ_DEADLINE, text)
        fields["items"]          = self._extract_line_items(text)
        fields["vendor_list"]    = self._extract_vendor_list(text)

        if not fields["rfq_number"]:
            warnings.append("Could not extract RFQ number.")
        if not fields["deadline"]:
            warnings.append("Submission deadline not found.")
        if not fields["items"]:
            warnings.append("No line items detected in RFQ.")

        return fields, warnings

    # ── Detection ─────────────────────────────────────────────────────────────

    def _detect_document_type(self, text: str) -> Tuple[str, float]:
        """Score text against keyword sets and return (type, confidence)."""
        lower = text.lower()
        scores: Dict[str, int] = {}
        for doc_type, keywords in _DOC_KEYWORDS.items():
            scores[doc_type] = sum(1 for kw in keywords if kw in lower)

        if not any(scores.values()):
            return "unknown", 0.4

        best_type = max(scores, key=lambda t: scores[t])
        total_hits = sum(scores.values())
        confidence = round(scores[best_type] / total_hits, 2) if total_hits > 0 else 0.4
        # Clamp confidence: single keyword match = medium confidence
        confidence = max(min(confidence, 0.97), 0.5)
        return best_type, confidence

    # ── Field helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _first_match(pattern: re.Pattern, text: str) -> Optional[str]:
        m = pattern.search(text)
        return m.group(1).strip() if m else None

    @staticmethod
    def _parse_amount(raw: Optional[str]) -> Optional[float]:
        if not raw:
            return None
        cleaned = re.sub(r'[^0-9.]', '', raw.replace(',', ''))
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    @staticmethod
    def _extract_line_items(text: str) -> List[Dict[str, Any]]:
        """
        Heuristic line-item extraction: look for lines with qty and price patterns.
        Returns up to 20 items.
        """
        line_pattern = re.compile(
            r'(?P<desc>[A-Za-z][A-Za-z0-9 \-/]{2,40})\s+'
            r'(?P<qty>\d+(?:\.\d+)?)\s+'
            r'(?P<unit_price>[\$€£]?\s*[\d,]+\.?\d{0,2})\s*'
            r'(?P<total>[\$€£]?\s*[\d,]+\.?\d{0,2})?',
            re.M,
        )
        items = []
        for m in line_pattern.finditer(text):
            items.append({
                "description": m.group("desc").strip(),
                "quantity": float(m.group("qty")),
                "unit_price": m.group("unit_price").strip(),
                "line_total": m.group("total").strip() if m.group("total") else None,
            })
            if len(items) >= 20:
                break
        return items

    @staticmethod
    def _extract_vendor_list(text: str) -> List[str]:
        """Extract vendor names listed after bullet points or numbered items."""
        pattern = re.compile(r'(?:^\s*[\-\*\d\.]+\s+)([A-Z][A-Za-z0-9 &,.\'-]{3,50})', re.M)
        return [m.group(1).strip() for m in pattern.finditer(text)][:10]

    @staticmethod
    def _required_fields(doc_type: str) -> List[str]:
        return {
            "purchase_order": ["po_number", "vendor", "total", "currency"],
            "invoice": ["invoice_number", "date", "amount", "vendor"],
            "contract": ["contract_id", "vendor", "start_date", "end_date"],
            "rfq": ["rfq_number", "deadline"],
        }.get(doc_type, [])


# ── Standalone entry point ─────────────────────────────────────────────────────

async def process_document(params: Dict[str, Any]) -> Dict[str, Any]:
    """Standalone async function — call from orchestrator or API route."""
    agent = DocumentProcessingAgent()
    return await agent.execute(params)
