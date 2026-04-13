"""
OCR & Document Processing Routes — Sprint D
=============================================
Full OCR chain: upload → extract text → detect type → extract fields →
optionally capture invoice into ERP.

Also: email inbox scanning — trigger the EmailInboxAgent to poll IMAP,
download attachments, run OCR, and auto-capture invoices.

Endpoints:
  POST /api/ocr/process          — Upload a document, get structured extraction
  POST /api/ocr/extract-text     — Raw text extraction only (no field parsing)
  POST /api/ocr/invoice-capture  — Upload invoice, extract + persist to ERP
  POST /api/ocr/email-scan       — Trigger email inbox scan for invoices
  GET  /api/ocr/status           — OCR provider + email inbox config status
"""

import base64
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.services.rbac import require_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ocr", tags=["ocr"])

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "docx", "doc"}


def _ext(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1].lower() if "." in filename else "")


# ── POST /api/ocr/process — Full OCR chain ──────────────────────────────────

@router.post("/process")
async def ocr_process_document(
    file: UploadFile = File(...),
    doc_type: str = Form("auto"),
    current_user: dict = Depends(require_auth()),
):
    """
    Full OCR pipeline: extract text → detect document type → extract fields.

    Accepts: PDF, PNG, JPG, TIFF, BMP, DOCX
    Returns: raw_text, doc_type_detected, confidence, fields[], source
    """
    filename = file.filename or "document"
    ext = _ext(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: .{ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    try:
        file_bytes = await file.read()
        if len(file_bytes) == 0:
            raise HTTPException(400, "Empty file uploaded")
        if len(file_bytes) > 20 * 1024 * 1024:  # 20MB limit
            raise HTTPException(400, "File too large (max 20MB)")

        from backend.services.ocr_service import process_document
        result = process_document(
            file_bytes=file_bytes,
            filename=filename,
            doc_type=doc_type if doc_type != "auto" else "auto",
        )

        # Compute a summary of extracted fields for quick display
        extracted = [f for f in result.get("fields", []) if f.get("status") == "extracted"]
        missing = [f for f in result.get("fields", []) if f.get("status") == "missing"]

        return {
            "success": True,
            "filename": filename,
            "file_size": len(file_bytes),
            "source": result.get("source", "unknown"),
            "doc_type_detected": result.get("doc_type_detected", "unknown"),
            "confidence": result.get("confidence", 0),
            "raw_text": result.get("raw_text", ""),
            "raw_text_length": len(result.get("raw_text", "")),
            "fields": result.get("fields", []),
            "summary": {
                "extracted_count": len(extracted),
                "missing_count": len(missing),
                "extracted_fields": {f["name"]: f["value"] for f in extracted},
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[OCR] process_document failed: %s", e)
        raise HTTPException(500, f"OCR processing failed: {str(e)}")


# ── POST /api/ocr/extract-text — Raw text extraction only ───────────────────

@router.post("/extract-text")
async def ocr_extract_text(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_auth()),
):
    """Extract raw text from a document without field parsing."""
    filename = file.filename or "document"
    ext = _ext(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: .{ext}")

    try:
        file_bytes = await file.read()
        if len(file_bytes) == 0:
            raise HTTPException(400, "Empty file uploaded")

        from backend.services.ocr_service import (
            extract_text_from_pdf,
            extract_text_from_image,
            extract_text_from_docx,
        )

        if ext == "pdf":
            text = extract_text_from_pdf(file_bytes)
            source = "pdf"
        elif ext in ("png", "jpg", "jpeg", "tiff", "tif", "bmp"):
            text = extract_text_from_image(file_bytes)
            source = "image"
        elif ext in ("docx", "doc"):
            text = extract_text_from_docx(file_bytes)
            source = "docx"
        else:
            text = file_bytes.decode("utf-8", errors="replace")
            source = "text"

        return {
            "success": True,
            "filename": filename,
            "source": source,
            "raw_text": text,
            "char_count": len(text),
            "line_count": len(text.splitlines()),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[OCR] extract_text failed: %s", e)
        raise HTTPException(500, f"Text extraction failed: {str(e)}")


# ── POST /api/ocr/invoice-capture — OCR + persist to ERP ────────────────────

@router.post("/invoice-capture")
async def ocr_invoice_capture(
    file: UploadFile = File(...),
    po_number: str = Form(""),
    vendor_name: str = Form(""),
    current_user: dict = Depends(require_auth()),
):
    """
    Full invoice capture chain:
    1. Extract text via OCR
    2. Detect document type (should be invoice)
    3. Extract structured fields (invoice_number, vendor, amount, dates, etc.)
    4. Run through InvoiceCaptureAgent for duplicate detection + ERP persistence
    5. Return captured invoice record

    Optional form fields:
      po_number   — link to an existing PO for 3-way matching
      vendor_name — hint for vendor matching
    """
    filename = file.filename or "document"
    ext = _ext(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: .{ext}")

    try:
        file_bytes = await file.read()
        if len(file_bytes) == 0:
            raise HTTPException(400, "Empty file uploaded")

        # Step 1-3: OCR extraction
        from backend.services.ocr_service import process_document
        ocr_result = process_document(file_bytes=file_bytes, filename=filename, doc_type="invoice")

        # Build field dict from extraction
        extracted_fields = {}
        for f in ocr_result.get("fields", []):
            if f.get("status") == "extracted" and f.get("value"):
                extracted_fields[f["name"]] = f["value"]

        # Overlay user-supplied hints
        if po_number:
            extracted_fields["po_reference"] = po_number
        if vendor_name:
            extracted_fields["vendor_name"] = vendor_name

        # Step 4: Invoice Capture Agent
        file_content_b64 = base64.b64encode(file_bytes).decode("utf-8")
        from backend.agents.orchestrator import initialize_orchestrator_with_agents
        orch = initialize_orchestrator_with_agents()

        capture_result = {}
        if "invoice_capture" in orch.specialized_agents:
            agent = orch.specialized_agents["invoice_capture"]
            capture_result = await agent.execute({
                "raw_content": ocr_result.get("raw_text", ""),
                "source_channel": "upload",
                "file_content_b64": file_content_b64,
                "filename": filename,
                "extracted_fields": extracted_fields,
                "po_reference": po_number,
                "vendor_hint": vendor_name,
            })

        # Build response
        capture_inner = capture_result.get("result", {}) if isinstance(capture_result.get("result"), dict) else {}
        return {
            "success": True,
            "filename": filename,
            "ocr": {
                "doc_type": ocr_result.get("doc_type_detected"),
                "confidence": ocr_result.get("confidence"),
                "raw_text_length": len(ocr_result.get("raw_text", "")),
                "fields": ocr_result.get("fields", []),
            },
            "capture": {
                "invoice_number": extracted_fields.get("invoice_number") or capture_inner.get("invoice_number"),
                "vendor_name": extracted_fields.get("vendor_name") or capture_inner.get("vendor_name"),
                "total_amount": extracted_fields.get("total_amount") or capture_inner.get("total_amount"),
                "invoice_date": extracted_fields.get("invoice_date") or capture_inner.get("invoice_date"),
                "po_reference": extracted_fields.get("po_reference") or capture_inner.get("po_reference"),
                "currency": extracted_fields.get("currency") or capture_inner.get("currency"),
                "due_date": extracted_fields.get("due_date") or capture_inner.get("due_date"),
                "duplicate_detected": capture_inner.get("duplicate_detected", False),
                "status": capture_inner.get("status", "captured"),
                "confidence": capture_inner.get("confidence", ocr_result.get("confidence", 0)),
            },
            "summary": {
                "fields_extracted": len([f for f in ocr_result.get("fields", []) if f.get("status") == "extracted"]),
                "fields_missing": len([f for f in ocr_result.get("fields", []) if f.get("status") == "missing"]),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[OCR] invoice_capture failed: %s", e)
        raise HTTPException(500, f"Invoice capture failed: {str(e)}")


# ── POST /api/ocr/email-scan — Trigger email inbox scan ─────────────────────

@router.post("/email-scan")
async def ocr_email_scan(
    current_user: dict = Depends(require_auth()),
):
    """
    Trigger the EmailInboxAgent to:
    1. Connect to IMAP mailbox
    2. Fetch unread emails with attachments
    3. Run OCR on each attachment
    4. Auto-capture invoices into the ERP
    5. Mark processed emails as read

    Requires IMAP_USER and IMAP_PASSWORD in .env for real emails.
    Falls back to demo data when IMAP is not configured.
    """
    import os
    imap_user = os.environ.get("IMAP_USER", "")
    imap_configured = bool(imap_user)

    try:
        from backend.agents.orchestrator import initialize_orchestrator_with_agents
        orch = initialize_orchestrator_with_agents()

        if "email_inbox" not in orch.specialized_agents:
            raise HTTPException(500, "EmailInboxAgent not registered")

        agent = orch.specialized_agents["email_inbox"]
        result = await agent.execute({
            "action": "scan_inbox",
            "max_emails": 20,
        })

        inner = result.get("result", {}) if isinstance(result.get("result"), dict) else {}
        return {
            "success": True,
            "mode": "live" if imap_configured else "demo",
            "imap_user": imap_user if imap_configured else "(not configured — using demo data)",
            "emails_scanned": inner.get("emails_scanned", inner.get("total_emails", 0)),
            "invoices_found": inner.get("invoices_found", inner.get("invoices_captured", 0)),
            "attachments_processed": inner.get("attachments_processed", 0),
            "errors": inner.get("errors", []),
            "captured_invoices": inner.get("captured_invoices", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[OCR] email_scan failed: %s", e)
        raise HTTPException(500, f"Email inbox scan failed: {str(e)}")


# ── GET /api/ocr/status — Config status ─────────────────────────────────────

@router.get("/status")
async def ocr_status(current_user: dict = Depends(require_auth())):
    """Return OCR and email config status for the admin/settings page."""
    import os

    ocr_provider = os.environ.get("OCR_PROVIDER", "regex")
    email_provider = os.environ.get("EMAIL_PROVIDER", "mock")
    email_enabled = os.environ.get("EMAIL_ENABLED", "false").lower() == "true"
    imap_configured = bool(os.environ.get("IMAP_USER", ""))
    smtp_configured = bool(os.environ.get("SMTP_USER", "") or os.environ.get("SMTP_HOST", ""))

    return {
        "ocr": {
            "provider": ocr_provider,
            "providers_available": ["regex", "mindee", "textract"],
            "mindee_configured": bool(os.environ.get("MINDEE_API_KEY")),
            "textract_configured": bool(os.environ.get("AWS_ACCESS_KEY_ID")),
        },
        "email": {
            "provider": email_provider,
            "enabled": email_enabled,
            "smtp_configured": smtp_configured,
            "smtp_host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
            "smtp_from": os.environ.get("SMTP_FROM", ""),
            "sendgrid_configured": bool(os.environ.get("SENDGRID_API_KEY")),
        },
        "inbox": {
            "imap_configured": imap_configured,
            "imap_host": os.environ.get("IMAP_HOST", "imap.gmail.com"),
            "imap_user": os.environ.get("IMAP_USER", "(not set)"),
        },
    }
