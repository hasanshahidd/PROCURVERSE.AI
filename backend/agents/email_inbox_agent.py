"""
EmailInboxAgent — Sprint 9
==========================
Monitors an email inbox (IMAP) for incoming invoices and procurement documents.
Auto-extracts invoice data and feeds it into the invoice pipeline.

Workflows covered: WF-05 (Invoice Capture via Email)

How it works:
1. Connect to IMAP mailbox (Gmail/Office365/any IMAP)
2. Poll for unread emails with attachments (PDF, images)
3. Download attachments
4. Run OCR extraction (calls ocr_service)
5. Detect if it's an invoice/PO/delivery note
6. Auto-create an invoice capture entry
7. Trigger the invoice pipeline
8. Mark email as read, move to "Processed" folder
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from backend.agents import AgentDecision, AgentStatus, BaseAgent
from backend.services.email_inbox_service import (
    connect_imap,
    disconnect,
    get_unread_emails,
    is_procurement_email,
    mark_as_read,
    move_to_folder,
)

logger = logging.getLogger(__name__)

# ── IMAP config from environment ──────────────────────────────────────────────
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
IMAP_FOLDER = os.getenv("IMAP_FOLDER", "INBOX")
IMAP_PROCESSED_FOLDER = os.getenv("IMAP_PROCESSED_FOLDER", "Processed")

# ── Demo data (used when IMAP is not configured) ──────────────────────────────
DEMO_EMAILS: List[Dict[str, Any]] = [
    {
        "email_id": "demo_001",
        "subject": "Invoice INV-2026-0892 from TechCorp FZE",
        "sender": "billing@techcorp-fze.com",
        "date": "2026-04-02",
        "attachments": ["Invoice_INV-2026-0892.pdf"],
        "body_text": "Please find attached Invoice INV-2026-0892 for AED 48,500.00 "
                     "referencing PO-2024-0341. Payment due within 30 days.",
        "demo_extraction": {
            "invoice_number": "INV-2026-0892",
            "vendor": "TechCorp FZE",
            "amount": 48500.0,
            "currency": "AED",
            "po_reference": "PO-2024-0341",
            "date": "2026-04-01",
        },
    },
    {
        "email_id": "demo_002",
        "subject": "Invoice #2026-1047 - Gulf Supplies LLC",
        "sender": "accounts@gulf-supplies.ae",
        "date": "2026-04-02",
        "attachments": ["GS_Invoice_2026-1047.pdf"],
        "body_text": "Dear Procurement Team, attached is our invoice #2026-1047 "
                     "for office supplies delivered on 2026-03-30. "
                     "Total amount: AED 12,750.00. PO Reference: PO-2024-0388.",
        "demo_extraction": {
            "invoice_number": "2026-1047",
            "vendor": "Gulf Supplies LLC",
            "amount": 12750.0,
            "currency": "AED",
            "po_reference": "PO-2024-0388",
            "date": "2026-04-02",
        },
    },
    {
        "email_id": "demo_003",
        "subject": "Payment Receipt - Maintenance Services Feb 2026",
        "sender": "finance@rapidmaint.com",
        "date": "2026-04-01",
        "attachments": ["Rapid_Maintenance_Receipt_Feb2026.pdf"],
        "body_text": "Please find attached the receipt for maintenance services "
                     "provided in February 2026. Amount: AED 9,200.00. "
                     "Invoice: RM-2026-0233.",
        "demo_extraction": {
            "invoice_number": "RM-2026-0233",
            "vendor": "Rapid Maintenance Services",
            "amount": 9200.0,
            "currency": "AED",
            "po_reference": None,
            "date": "2026-04-01",
        },
    },
]

# Keywords that indicate an invoice email
_INVOICE_SUBJECT_KEYWORDS = {
    "invoice",
    "inv",
    "bill",
    "payment",
    "receipt",
    "proforma",
    "statement",
    "remittance",
}


class EmailInboxAgent(BaseAgent):
    """
    Sprint 9 — Email Inbox Agent.

    Polls an IMAP mailbox for incoming procurement emails, runs OCR on
    attachments, and feeds detected invoices into the invoice pipeline.
    Falls back to demo mode when IMAP credentials are not configured.
    """

    def __init__(self) -> None:
        super().__init__(
            name="EmailInboxAgent",
            description=(
                "Monitors an IMAP email inbox for incoming invoices and procurement "
                "documents, performs OCR extraction, and auto-creates invoice capture "
                "entries to feed the invoice pipeline."
            ),
            temperature=0.1,
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Connect to IMAP and retrieve unread emails.

        Returns a list of email_items with attachment metadata.
        Falls back to demo data when IMAP is not configured.
        """
        self.status = AgentStatus.OBSERVING
        max_emails = input_data.get("max_emails", 20)
        folder = input_data.get("folder", IMAP_FOLDER)

        # ── Demo mode ─────────────────────────────────────────────────────────
        if not IMAP_USER:
            logger.warning(
                "[EmailInboxAgent] IMAP_USER not set — returning demo email data."
            )
            return {
                "mode": "demo",
                "folder": folder,
                "email_items": DEMO_EMAILS,
                "total_unread": len(DEMO_EMAILS),
                "input_data": input_data,
            }

        # ── Live IMAP ─────────────────────────────────────────────────────────
        conn = connect_imap()
        if conn is None:
            logger.warning(
                "[EmailInboxAgent] IMAP connection failed — falling back to demo mode."
            )
            return {
                "mode": "demo",
                "folder": folder,
                "email_items": DEMO_EMAILS,
                "total_unread": len(DEMO_EMAILS),
                "input_data": input_data,
                "connection_error": True,
            }

        try:
            raw_emails = get_unread_emails(conn, folder=folder, max_count=max_emails)
        finally:
            disconnect(conn)

        # Convert to email_item format
        email_items: List[Dict[str, Any]] = []
        for em in raw_emails:
            attachment_names = [a["filename"] for a in em.get("attachments", [])]
            email_items.append(
                {
                    "email_id": em["id"],
                    "subject": em["subject"],
                    "sender": em["sender"],
                    "date": em["date"],
                    "attachments": attachment_names,
                    "body_text": em.get("body_text", ""),
                    "_raw_attachments": em.get("attachments", []),
                }
            )

        logger.info(
            "[EmailInboxAgent] OBSERVE: found %d unread emails in %s",
            len(email_items),
            folder,
        )

        return {
            "mode": "live",
            "folder": folder,
            "email_items": email_items,
            "total_unread": len(email_items),
            "input_data": input_data,
        }

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Filter emails likely to contain invoices.

        Scores each email by likelihood and returns action 'process_invoices'
        if any match, or 'no_invoices' if none pass the threshold.
        """
        self.status = AgentStatus.THINKING
        email_items = observations.get("email_items", [])
        mode = observations.get("mode", "live")

        invoice_candidates: List[Dict[str, Any]] = []

        for em in email_items:
            subject_lower = (em.get("subject") or "").lower()
            body_lower = (em.get("body_text") or "").lower()

            # Score by keyword presence in subject
            subject_score = sum(
                0.25 for kw in _INVOICE_SUBJECT_KEYWORDS if kw in subject_lower
            )

            # Use service classifier on combined text
            is_proc, svc_confidence = is_procurement_email(
                em.get("subject", ""), em.get("body_text", "")
            )

            # Demo emails get their pre-computed extraction
            if mode == "demo" and em.get("demo_extraction"):
                score = 0.95
            else:
                score = min(subject_score + svc_confidence * 0.5, 1.0)

            if score >= 0.4 or (mode == "demo" and em.get("demo_extraction")):
                invoice_candidates.append({**em, "invoice_score": round(score, 2)})

        if invoice_candidates:
            action = "process_invoices"
            reasoning = (
                f"Found {len(invoice_candidates)} likely invoice email(s) "
                f"out of {len(email_items)} unread. Processing."
            )
            confidence = 0.90
        else:
            action = "no_invoices"
            reasoning = (
                f"No invoice-related emails detected among {len(email_items)} unread."
            )
            confidence = 0.95

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "invoice_candidates": invoice_candidates,
            },
            alternatives=["manual_review"],
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        Process each invoice email:
        1. Download / access attachment bytes
        2. Run OCR extraction
        3. Create invoice capture record
        4. Mark email as read and move to Processed folder
        """
        self.status = AgentStatus.ACTING
        action = decision.action
        ctx = decision.context
        mode = ctx.get("mode", "live")
        auto_process = ctx.get("input_data", {}).get("auto_process", True)

        result: Dict[str, Any] = {
            "success": True,
            "agent": self.name,
            "action": action,
            "mode": mode,
            "processed_count": 0,
            "invoices_captured": [],
            "errors": [],
        }

        if action == "no_invoices":
            result["message"] = "No invoice emails found — nothing to process."
            return result

        if not auto_process:
            candidates = ctx.get("invoice_candidates", [])
            result["message"] = (
                f"Auto-process disabled. {len(candidates)} candidate(s) identified."
            )
            result["invoice_candidates"] = candidates
            return result

        invoice_candidates = ctx.get("invoice_candidates", [])
        conn = None if mode == "demo" else connect_imap()

        try:
            for em in invoice_candidates:
                email_id = em.get("email_id", "")
                subject = em.get("subject", "")
                sender = em.get("sender", "")

                try:
                    # ── Step 1: Get extracted fields ──────────────────────────
                    if mode == "demo" and em.get("demo_extraction"):
                        extracted = em["demo_extraction"]
                    else:
                        extracted = self._ocr_attachments(em)

                    # ── Step 2: Validate and create capture record ─────────────
                    has_amount = bool(
                        extracted.get("amount") or extracted.get("total_amount")
                    )
                    has_invoice_no = bool(
                        extracted.get("invoice_number") or extracted.get("invoice_no")
                    )

                    capture_record: Dict[str, Any] = {
                        "source_channel": "email",
                        "document_ref": subject,
                        "sender": sender,
                        "email_id": email_id,
                        "extracted_fields": extracted,
                        "captured_at": datetime.utcnow().isoformat(),
                        "capture_status": "captured" if (has_amount or has_invoice_no) else "needs_review",
                    }

                    # ── Step 3: Log to agent_actions ──────────────────────────
                    await self._log_action(
                        action_type="email_invoice_captured",
                        input_data={
                            "email_id": email_id,
                            "subject": subject,
                            "sender": sender,
                        },
                        output_data=capture_record,
                        success=True,
                    )

                    result["invoices_captured"].append(capture_record)
                    result["processed_count"] += 1

                    # ── Step 4: Mark as read and move (live only) ─────────────
                    if conn and email_id:
                        mark_as_read(conn, email_id)
                        move_to_folder(conn, email_id, IMAP_PROCESSED_FOLDER)

                    logger.info(
                        "[EmailInboxAgent] Captured invoice from email_id=%s subject='%s'",
                        email_id,
                        subject,
                    )

                except Exception as exc:
                    err_msg = f"Error processing email_id={email_id}: {exc}"
                    logger.error("[EmailInboxAgent] %s", err_msg)
                    result["errors"].append(err_msg)

        finally:
            if conn:
                disconnect(conn)

        result["message"] = (
            f"Processed {result['processed_count']} email(s). "
            f"Captured {len(result['invoices_captured'])} invoice(s). "
            f"Errors: {len(result['errors'])}."
        )
        return result

    # ── LEARN ─────────────────────────────────────────────────────────────────

    async def learn(self, result: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        logger.info(
            "[EmailInboxAgent] Learning — processed_count=%s",
            result.get("result", {}).get("processed_count", 0),
        )

    # ── EXECUTE ───────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _ocr_attachments(self, em: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run OCR on the first attachment of an email.

        Tries the pluggable OCR service; falls back to an empty dict on failure.
        """
        raw_attachments = em.get("_raw_attachments", [])
        for att in raw_attachments:
            filename: str = att.get("filename", "")
            file_bytes: bytes = att.get("bytes") or b""
            if not file_bytes:
                continue
            # Only process document-type attachments
            if not any(
                filename.lower().endswith(ext)
                for ext in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp")
            ):
                continue
            try:
                from backend.services.ocr_service import get_ocr_service

                # Decode bytes as text for regex OCR; binary providers handle
                # file_bytes directly via their own implementations.
                raw_text = file_bytes.decode("utf-8", errors="replace")
                return get_ocr_service().extract_invoice(raw_text)
            except Exception as exc:
                logger.warning(
                    "[EmailInboxAgent] OCR failed for %s: %s", filename, exc
                )
        return {}
