"""
Vendor Communication Service -- G-06 (Dev Spec 2.0)
====================================================
Implements the Vendor Communication Loop with 9 touchpoints
across the procure-to-pay lifecycle.

Touchpoints
-----------
1. po_acknowledgment     -- PO issued, acknowledgment requested
2. delivery_approaching  -- Delivery date approaching reminder
3. goods_received        -- GRN created, goods accepted
4. partial_accept        -- Partial acceptance with discrepancies
5. invoice_received      -- Invoice received and logged
6. invoice_matched       -- Invoice matched against PO/GRN
7. exception_raised      -- Exception raised requiring vendor action
8. payment_sent          -- Payment dispatched
9. debit_note            -- Debit note issued for returns/adjustments

Database
--------
All records stored in vendor_communications table (see devspec2_gap_tables.py).
Direct psycopg2 access via nmi_data_service.get_conn(), consistent with
other service-layer modules.

Email Delivery
--------------
Uses get_email_sender() from email_service (pluggable: Mock / SendGrid / SMTP).
Communications are recorded in DB first, then dispatched. A failure in delivery
updates the record status to 'failed' but never loses the communication record.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from backend.services.nmi_data_service import get_conn
from backend.services.email_service import get_email_sender

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Communication types -- the 9 touchpoints from Dev Spec 2.0 G-06
# ---------------------------------------------------------------------------

COMM_TYPES = [
    "po_acknowledgment",
    "delivery_approaching",
    "goods_received",
    "partial_accept",
    "invoice_received",
    "invoice_matched",
    "exception_raised",
    "payment_sent",
    "debit_note",
]

# ---------------------------------------------------------------------------
# Email templates -- subject/body per communication type
# ---------------------------------------------------------------------------

TEMPLATES: Dict[str, Dict[str, str]] = {
    "po_acknowledgment": {
        "subject": "Purchase Order {po_number} - Acknowledgment Required",
        "body": (
            "Dear {vendor_name},\n\n"
            "We have issued Purchase Order {po_number}. Please acknowledge receipt "
            "and confirm your ability to fulfil the order within the agreed terms.\n\n"
            "You can acknowledge via the supplier portal or by replying to this email.\n\n"
            "If you have any questions about the order specifications or delivery schedule, "
            "please contact our procurement team.\n\n"
            "Regards,\n"
            "Procurement Team"
        ),
    },
    "delivery_approaching": {
        "subject": "Reminder: Delivery Due for PO {po_number} on {expected_date}",
        "body": (
            "Dear {vendor_name},\n\n"
            "This is a friendly reminder that the delivery for Purchase Order {po_number} "
            "is expected on {expected_date}.\n\n"
            "Please ensure the shipment is on schedule. If there are any anticipated delays, "
            "kindly notify us at your earliest convenience so we can adjust our planning.\n\n"
            "Delivery details:\n"
            "  PO Number     : {po_number}\n"
            "  Expected Date : {expected_date}\n\n"
            "Regards,\n"
            "Procurement Team"
        ),
    },
    "goods_received": {
        "subject": "Goods Received - GRN {grn_number} for PO {po_number}",
        "body": (
            "Dear {vendor_name},\n\n"
            "We are pleased to confirm that the goods for Purchase Order {po_number} "
            "have been received and inspected.\n\n"
            "Goods Receipt Note: {grn_number}\n"
            "Related PO: {po_number}\n\n"
            "The invoice processing cycle will now commence. You will receive a "
            "separate notification once the invoice has been matched and approved "
            "for payment.\n\n"
            "Regards,\n"
            "Procurement Team"
        ),
    },
    "partial_accept": {
        "subject": "Partial Acceptance - GRN {grn_number} for PO {po_number}",
        "body": (
            "Dear {vendor_name},\n\n"
            "We have partially accepted the delivery for Purchase Order {po_number}.\n\n"
            "Goods Receipt Note: {grn_number}\n"
            "Related PO: {po_number}\n\n"
            "Discrepancies were found during the inspection. Please review the details "
            "in the supplier portal or contact our receiving department.\n\n"
            "A debit note or return request may follow for the rejected items.\n\n"
            "Regards,\n"
            "Procurement Team"
        ),
    },
    "invoice_received": {
        "subject": "Invoice {invoice_number} Received - Under Review",
        "body": (
            "Dear {vendor_name},\n\n"
            "We have received your invoice {invoice_number} and it is now under review.\n\n"
            "Our accounts payable team will match it against the corresponding purchase "
            "order and goods receipt. You will be notified of the outcome.\n\n"
            "Regards,\n"
            "Procurement Team"
        ),
    },
    "invoice_matched": {
        "subject": "Invoice {invoice_number} Matched - PO {po_number} ({match_status})",
        "body": (
            "Dear {vendor_name},\n\n"
            "Your invoice {invoice_number} has been matched against Purchase Order {po_number}.\n\n"
            "Match Result: {match_status}\n\n"
            "The invoice will now proceed to the payment approval workflow. You will "
            "receive a payment notification once the payment has been dispatched.\n\n"
            "If the match result indicates discrepancies, our AP team may reach out "
            "for clarification.\n\n"
            "Regards,\n"
            "Procurement Team"
        ),
    },
    "exception_raised": {
        "subject": "Action Required: Exception {exception_id} - {exception_type}",
        "body": (
            "Dear {vendor_name},\n\n"
            "An exception has been raised that requires your attention.\n\n"
            "Exception ID   : {exception_id}\n"
            "Exception Type : {exception_type}\n"
            "Description    : {description}\n\n"
            "Please review and respond at your earliest convenience via the "
            "supplier portal or by replying to this email.\n\n"
            "Timely resolution helps us maintain smooth operations for both parties.\n\n"
            "Regards,\n"
            "Procurement Team"
        ),
    },
    "payment_sent": {
        "subject": "Payment {payment_ref} Dispatched - {currency} {amount}",
        "body": (
            "Dear {vendor_name},\n\n"
            "We are pleased to inform you that a payment has been dispatched.\n\n"
            "Payment Reference : {payment_ref}\n"
            "Amount            : {currency} {amount}\n\n"
            "Please allow standard banking processing time for the funds to reflect "
            "in your account. If you do not receive the payment within the expected "
            "timeframe, please contact our finance team.\n\n"
            "Regards,\n"
            "Finance Team"
        ),
    },
    "debit_note": {
        "subject": "Debit Note Issued - Return {return_number}",
        "body": (
            "Dear {vendor_name},\n\n"
            "A debit note has been issued against your account.\n\n"
            "Return Reference : {return_number}\n"
            "Amount           : {amount}\n"
            "Reason           : {reason}\n\n"
            "This amount will be adjusted against your next payment or as otherwise "
            "agreed. Please review the details and contact our accounts payable team "
            "if you have any questions.\n\n"
            "Regards,\n"
            "Finance Team"
        ),
    },
}

# ---------------------------------------------------------------------------
# Vendor communication email config
# ---------------------------------------------------------------------------

VENDOR_EMAIL_DOMAIN = os.getenv("VENDOR_EMAIL_DOMAIN", "")
VENDOR_EMAIL_LOOKUP_ENABLED = os.getenv("VENDOR_EMAIL_LOOKUP", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class VendorCommunicationService:
    """
    Manages the full vendor communication lifecycle for the 9 touchpoints
    defined in Dev Spec 2.0 G-06.

    Responsibilities:
      - Create communication records in vendor_communications table
      - Render email templates with context variables
      - Dispatch via the configured email sender
      - Track delivery, read, and response status
    """

    def __init__(self):
        self._email_sender = None

    # ── Lazy-loaded email sender ─────────────────────────────────────────────

    @property
    def email_sender(self):
        """Lazy-init the email sender so import-time errors don't block the module."""
        if self._email_sender is None:
            self._email_sender = get_email_sender()
            logger.info(
                "[VendorComm] Email sender initialised: %s",
                type(self._email_sender).__name__,
            )
        return self._email_sender

    # ── Core send method ─────────────────────────────────────────────────────

    def send_communication(
        self,
        vendor_id: str,
        vendor_name: str,
        comm_type: str,
        document_type: str,
        document_id: str,
        subject: str,
        body: str,
        channel: str = "email",
    ) -> Dict[str, Any]:
        """
        Create a communication record and attempt delivery.

        Parameters
        ----------
        vendor_id     : Vendor identifier (e.g. 'V-001')
        vendor_name   : Display name of the vendor
        comm_type     : One of COMM_TYPES or 'general'
        document_type : Related document type (e.g. 'purchase_order', 'invoice')
        document_id   : Related document identifier (e.g. 'PO-2024-0100')
        subject       : Email/message subject line
        body          : Email/message body text
        channel       : Delivery channel ('email', 'portal', 'api', 'sms', 'webhook')

        Returns
        -------
        dict with keys: comm_id, status, error (if any)
        """
        conn = None
        comm_id = None
        result = {"comm_id": None, "status": "failed", "error": None}

        try:
            conn = get_conn()

            # 1. Insert communication record
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vendor_communications
                        (vendor_id, vendor_name, communication_type,
                         document_type, document_id, channel,
                         subject, body, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
                    RETURNING id
                    """,
                    (
                        vendor_id,
                        vendor_name,
                        comm_type,
                        document_type,
                        document_id,
                        channel,
                        subject,
                        body,
                    ),
                )
                row = cur.fetchone()
                comm_id = row[0] if row else None
            conn.commit()

            result["comm_id"] = comm_id

            if not comm_id:
                result["error"] = "Failed to insert communication record"
                return result

            logger.info(
                "[VendorComm] Created comm_id=%s type=%s vendor=%s doc=%s",
                comm_id,
                comm_type,
                vendor_id,
                document_id,
            )

            # 2. Attempt delivery
            if channel == "email":
                delivery_ok = self._deliver_email(vendor_id, subject, body)
            else:
                # portal / api / sms / webhook -- mark as sent (placeholder)
                delivery_ok = True
                logger.info(
                    "[VendorComm] Channel '%s' delivery stub for comm_id=%s",
                    channel,
                    comm_id,
                )

            # 3. Update record status based on delivery outcome
            if delivery_ok:
                self._update_status(conn, comm_id, "sent")
                result["status"] = "sent"
            else:
                self._increment_retry(conn, comm_id)
                self._update_status(conn, comm_id, "failed")
                result["status"] = "failed"
                result["error"] = "Delivery failed"

        except Exception as exc:
            logger.error("[VendorComm] send_communication error: %s", exc)
            result["error"] = str(exc)[:500]
            if conn and comm_id:
                try:
                    self._update_status(conn, comm_id, "failed")
                except Exception:
                    pass
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        return result

    # ── Template-based convenience methods ───────────────────────────────────

    def send_po_acknowledgment(
        self,
        po_number: str,
        vendor_name: str,
        vendor_id: str,
    ) -> Dict[str, Any]:
        """Send a PO acknowledgment request to the vendor."""
        tpl = TEMPLATES["po_acknowledgment"]
        subject = tpl["subject"].format(po_number=po_number)
        body = tpl["body"].format(vendor_name=vendor_name, po_number=po_number)

        return self.send_communication(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            comm_type="po_acknowledgment",
            document_type="purchase_order",
            document_id=po_number,
            subject=subject,
            body=body,
        )

    def send_delivery_reminder(
        self,
        po_number: str,
        vendor_name: str,
        vendor_id: str,
        expected_date: str,
    ) -> Dict[str, Any]:
        """Send a delivery-approaching reminder to the vendor."""
        tpl = TEMPLATES["delivery_approaching"]
        subject = tpl["subject"].format(
            po_number=po_number, expected_date=expected_date
        )
        body = tpl["body"].format(
            vendor_name=vendor_name,
            po_number=po_number,
            expected_date=expected_date,
        )

        return self.send_communication(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            comm_type="delivery_approaching",
            document_type="purchase_order",
            document_id=po_number,
            subject=subject,
            body=body,
        )

    def send_goods_received_notice(
        self,
        grn_number: str,
        vendor_name: str,
        vendor_id: str,
        po_number: str,
    ) -> Dict[str, Any]:
        """Notify the vendor that goods have been received and accepted."""
        tpl = TEMPLATES["goods_received"]
        subject = tpl["subject"].format(grn_number=grn_number, po_number=po_number)
        body = tpl["body"].format(
            vendor_name=vendor_name,
            grn_number=grn_number,
            po_number=po_number,
        )

        return self.send_communication(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            comm_type="goods_received",
            document_type="grn",
            document_id=grn_number,
            subject=subject,
            body=body,
        )

    def send_payment_notification(
        self,
        payment_ref: str,
        vendor_name: str,
        vendor_id: str,
        amount: float,
        currency: str = "AED",
    ) -> Dict[str, Any]:
        """Notify the vendor that payment has been dispatched."""
        formatted_amount = f"{amount:,.2f}"
        tpl = TEMPLATES["payment_sent"]
        subject = tpl["subject"].format(
            payment_ref=payment_ref,
            currency=currency,
            amount=formatted_amount,
        )
        body = tpl["body"].format(
            vendor_name=vendor_name,
            payment_ref=payment_ref,
            currency=currency,
            amount=formatted_amount,
        )

        return self.send_communication(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            comm_type="payment_sent",
            document_type="payment",
            document_id=payment_ref,
            subject=subject,
            body=body,
        )

    def send_debit_note(
        self,
        return_number: str,
        vendor_name: str,
        vendor_id: str,
        amount: float,
        reason: str,
    ) -> Dict[str, Any]:
        """Send a debit note communication for returns or adjustments."""
        formatted_amount = f"{amount:,.2f}"
        tpl = TEMPLATES["debit_note"]
        subject = tpl["subject"].format(return_number=return_number)
        body = tpl["body"].format(
            vendor_name=vendor_name,
            return_number=return_number,
            amount=formatted_amount,
            reason=reason,
        )

        return self.send_communication(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            comm_type="debit_note",
            document_type="grn_return",
            document_id=return_number,
            subject=subject,
            body=body,
        )

    def send_exception_notification(
        self,
        exception_id: str,
        vendor_name: str,
        vendor_id: str,
        exception_type: str,
        description: str,
    ) -> Dict[str, Any]:
        """Notify the vendor about a raised exception requiring their action."""
        tpl = TEMPLATES["exception_raised"]
        subject = tpl["subject"].format(
            exception_id=exception_id, exception_type=exception_type
        )
        body = tpl["body"].format(
            vendor_name=vendor_name,
            exception_id=exception_id,
            exception_type=exception_type,
            description=description,
        )

        return self.send_communication(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            comm_type="exception_raised",
            document_type="exception",
            document_id=exception_id,
            subject=subject,
            body=body,
        )

    def send_invoice_matched(
        self,
        invoice_number: str,
        vendor_name: str,
        vendor_id: str,
        po_number: str,
        match_status: str = "3-way match",
    ) -> Dict[str, Any]:
        """Notify the vendor that their invoice has been matched."""
        tpl = TEMPLATES["invoice_matched"]
        subject = tpl["subject"].format(
            invoice_number=invoice_number,
            po_number=po_number,
            match_status=match_status,
        )
        body = tpl["body"].format(
            vendor_name=vendor_name,
            invoice_number=invoice_number,
            po_number=po_number,
            match_status=match_status,
        )

        return self.send_communication(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            comm_type="invoice_matched",
            document_type="invoice",
            document_id=invoice_number,
            subject=subject,
            body=body,
        )

    # ── Query / status-update methods ────────────────────────────────────────

    def get_vendor_communications(
        self,
        vendor_id: Optional[str] = None,
        comm_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve communication records with optional filters.

        Parameters
        ----------
        vendor_id : Filter by vendor (optional)
        comm_type : Filter by communication_type (optional)
        limit     : Maximum rows to return (default 50)

        Returns
        -------
        List of communication dicts, most recent first.
        """
        conditions: List[str] = []
        params: List[Any] = []

        if vendor_id:
            conditions.append("vendor_id = %s")
            params.append(vendor_id)

        if comm_type:
            conditions.append("communication_type = %s")
            params.append(comm_type)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                id, vendor_id, vendor_name, communication_type,
                document_type, document_id, channel,
                subject, body, template_id,
                sent_at, delivered_at, read_at,
                response_received, response_data,
                status, retry_count, created_at
            FROM vendor_communications
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """
        params.append(limit)

        conn = None
        try:
            conn = get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error("[VendorComm] get_vendor_communications error: %s", exc)
            return []
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def mark_delivered(self, comm_id: int) -> bool:
        """
        Mark a communication as delivered (vendor confirmed receipt).

        Parameters
        ----------
        comm_id : The vendor_communications.id to update

        Returns
        -------
        True if updated, False on error.
        """
        conn = None
        try:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE vendor_communications
                    SET    status       = 'delivered',
                           delivered_at = %s
                    WHERE  id = %s
                      AND  status IN ('pending', 'sent')
                    """,
                    (datetime.now(timezone.utc), comm_id),
                )
                updated = cur.rowcount
            conn.commit()

            if updated:
                logger.info("[VendorComm] Marked comm_id=%s as delivered", comm_id)
                return True
            else:
                logger.warning(
                    "[VendorComm] mark_delivered: no qualifying row for comm_id=%s",
                    comm_id,
                )
                return False
        except Exception as exc:
            logger.error("[VendorComm] mark_delivered error: %s", exc)
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def mark_responded(
        self, comm_id: int, response_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Mark a communication as responded by the vendor.

        Parameters
        ----------
        comm_id       : The vendor_communications.id to update
        response_data : JSON-serialisable dict of vendor response details

        Returns
        -------
        True if updated, False on error.
        """
        import json as _json

        conn = None
        try:
            conn = get_conn()
            response_json = (
                _json.dumps(response_data) if response_data else _json.dumps({})
            )
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE vendor_communications
                    SET    status            = 'responded',
                           response_received = TRUE,
                           response_data     = %s::jsonb
                    WHERE  id = %s
                      AND  status IN ('pending', 'sent', 'delivered', 'read')
                    """,
                    (response_json, comm_id),
                )
                updated = cur.rowcount
            conn.commit()

            if updated:
                logger.info(
                    "[VendorComm] Marked comm_id=%s as responded", comm_id
                )
                return True
            else:
                logger.warning(
                    "[VendorComm] mark_responded: no qualifying row for comm_id=%s",
                    comm_id,
                )
                return False
        except Exception as exc:
            logger.error("[VendorComm] mark_responded error: %s", exc)
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ── Private helpers ──────────────────────────────────────────────────────

    def _deliver_email(
        self, vendor_id: str, subject: str, body: str
    ) -> bool:
        """
        Attempt to deliver an email to the vendor.

        Looks up vendor email from DB (vendor master) if VENDOR_EMAIL_LOOKUP
        is enabled; otherwise falls back to a constructed address or sends
        via the mock/configured sender.

        Returns True on success, False on failure.
        """
        recipient = self._resolve_vendor_email(vendor_id)

        if not recipient:
            logger.warning(
                "[VendorComm] No email address for vendor_id=%s, skipping delivery",
                vendor_id,
            )
            return False

        try:
            success = self.email_sender.send(
                to=recipient,
                subject=subject,
                body_html=body,
            )
            if success:
                logger.info(
                    "[VendorComm] Email sent to %s (vendor_id=%s)",
                    recipient,
                    vendor_id,
                )
            else:
                logger.warning(
                    "[VendorComm] Email sender returned False for vendor_id=%s",
                    vendor_id,
                )
            return success
        except Exception as exc:
            logger.error(
                "[VendorComm] Email delivery failed for vendor_id=%s: %s",
                vendor_id,
                exc,
            )
            return False

    def _resolve_vendor_email(self, vendor_id: str) -> Optional[str]:
        """
        Resolve vendor email address.

        Strategy:
          1. If VENDOR_EMAIL_LOOKUP is enabled, query vendors table
          2. Fall back to vendor_id@<VENDOR_EMAIL_DOMAIN> if domain is configured
          3. Return a placeholder for MockEmailSender

        Returns None if no email can be determined.
        """
        # 1. DB lookup
        if VENDOR_EMAIL_LOOKUP_ENABLED:
            conn = None
            try:
                conn = get_conn()
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT email
                        FROM vendors
                        WHERE id = %s OR vendor_id = %s
                        LIMIT 1
                        """,
                        (vendor_id, vendor_id),
                    )
                    row = cur.fetchone()
                    if row and row.get("email"):
                        return row["email"]
            except Exception as exc:
                logger.debug(
                    "[VendorComm] Vendor email lookup failed for %s: %s",
                    vendor_id,
                    exc,
                )
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        # 2. Constructed address from domain
        if VENDOR_EMAIL_DOMAIN:
            return f"{vendor_id}@{VENDOR_EMAIL_DOMAIN}"

        # 3. Placeholder for mock / dev environments
        return f"{vendor_id}@vendor.procure.ai"

    def _update_status(
        self,
        conn,
        comm_id: int,
        status: str,
    ) -> None:
        """Update the status of a communication record (reuses existing conn)."""
        try:
            sent_at_clause = ", sent_at = NOW()" if status == "sent" else ""
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE vendor_communications
                    SET    status = %s {sent_at_clause}
                    WHERE  id = %s
                    """,
                    (status, comm_id),
                )
            conn.commit()
        except Exception as exc:
            logger.error(
                "[VendorComm] _update_status(comm_id=%s, status=%s) error: %s",
                comm_id,
                status,
                exc,
            )
            try:
                conn.rollback()
            except Exception:
                pass

    def _increment_retry(self, conn, comm_id: int) -> None:
        """Increment the retry counter on a communication record."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE vendor_communications
                    SET    retry_count = retry_count + 1
                    WHERE  id = %s
                    """,
                    (comm_id,),
                )
            conn.commit()
        except Exception as exc:
            logger.error(
                "[VendorComm] _increment_retry(comm_id=%s) error: %s",
                comm_id,
                exc,
            )
            try:
                conn.rollback()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_vendor_comm_service: Optional[VendorCommunicationService] = None


def get_vendor_comm_service() -> VendorCommunicationService:
    """
    Return the module-level singleton VendorCommunicationService instance.

    Thread-safe for typical CPython (GIL protects the reference assignment).
    """
    global _vendor_comm_service
    if _vendor_comm_service is None:
        _vendor_comm_service = VendorCommunicationService()
        logger.info("[VendorComm] Singleton service created")
    return _vendor_comm_service
