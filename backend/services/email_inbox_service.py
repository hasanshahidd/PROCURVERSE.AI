"""
Email Inbox Service — Sprint 9
IMAP client for polling procurement email inbox.

Handles connecting to an IMAP server, fetching unread emails,
downloading attachments, and moving/marking emails.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

# ── IMAP config from environment ──────────────────────────────────────────────
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")


# ── Connection ────────────────────────────────────────────────────────────────

def connect_imap() -> Optional[imaplib.IMAP4_SSL]:
    """
    Connect and authenticate to the configured IMAP server.

    Returns an authenticated IMAP4_SSL connection, or None when credentials
    are not configured or authentication fails.
    """
    if not IMAP_USER or not IMAP_PASSWORD:
        logger.warning(
            "[EmailInboxService] IMAP_USER or IMAP_PASSWORD not set — "
            "running in demo mode."
        )
        return None

    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        conn.login(IMAP_USER, IMAP_PASSWORD)
        logger.info(
            "[EmailInboxService] Connected to %s as %s", IMAP_HOST, IMAP_USER
        )
        return conn
    except imaplib.IMAP4.error as exc:
        logger.error("[EmailInboxService] IMAP login failed: %s", exc)
        return None
    except Exception as exc:
        logger.error("[EmailInboxService] IMAP connection error: %s", exc)
        return None


# ── Fetch emails ──────────────────────────────────────────────────────────────

def get_unread_emails(
    conn: imaplib.IMAP4_SSL,
    folder: str = "INBOX",
    max_count: int = 20,
) -> list[dict]:
    """
    Fetch unread emails from *folder* and return a list of email dicts.

    Each dict contains:
      id            — IMAP message UID (bytes-decoded string)
      subject       — decoded subject line
      sender        — From header value
      date          — Date header value
      body_text     — plain-text body (may be empty)
      attachments   — list of {filename, content_type, bytes}
    """
    results: list[dict] = []

    try:
        conn.select(folder, readonly=False)
        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            logger.warning(
                "[EmailInboxService] Could not search folder %s: %s", folder, status
            )
            return results

        uid_list = data[0].split()
        if not uid_list:
            logger.info("[EmailInboxService] No unread emails in %s", folder)
            return results

        # Process most-recent first, up to max_count
        uid_list = uid_list[-max_count:]

        for uid_bytes in reversed(uid_list):
            try:
                uid_str = uid_bytes.decode()
                status, msg_data = conn.fetch(uid_bytes, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_header_value(msg.get("Subject", "(no subject)"))
                sender = msg.get("From", "")
                date = msg.get("Date", "")
                body_text = ""
                attachments: list[dict] = []

                for part in msg.walk():
                    ctype = part.get_content_type()
                    disposition = str(part.get("Content-Disposition", ""))

                    if ctype == "text/plain" and "attachment" not in disposition:
                        try:
                            body_text += part.get_payload(decode=True).decode(
                                part.get_content_charset("utf-8"), errors="replace"
                            )
                        except Exception:
                            pass

                    elif "attachment" in disposition or part.get_filename():
                        filename = _decode_header_value(
                            part.get_filename() or "attachment"
                        )
                        try:
                            file_bytes = part.get_payload(decode=True)
                        except Exception:
                            file_bytes = b""
                        attachments.append(
                            {
                                "filename": filename,
                                "content_type": ctype,
                                "bytes": file_bytes,
                            }
                        )

                results.append(
                    {
                        "id": uid_str,
                        "subject": subject,
                        "sender": sender,
                        "date": date,
                        "body_text": body_text,
                        "attachments": attachments,
                    }
                )

            except Exception as exc:
                logger.warning(
                    "[EmailInboxService] Error parsing email uid=%s: %s",
                    uid_bytes,
                    exc,
                )

    except Exception as exc:
        logger.error("[EmailInboxService] get_unread_emails error: %s", exc)

    return results


# ── Mark as read ──────────────────────────────────────────────────────────────

def mark_as_read(conn: imaplib.IMAP4_SSL, email_id: str) -> bool:
    """
    Add the \\Seen flag to a message identified by *email_id*.

    Returns True on success, False on failure.
    """
    try:
        status, _ = conn.store(email_id.encode(), "+FLAGS", "\\Seen")
        return status == "OK"
    except Exception as exc:
        logger.warning("[EmailInboxService] mark_as_read(%s) error: %s", email_id, exc)
        return False


# ── Move to folder ────────────────────────────────────────────────────────────

def move_to_folder(
    conn: imaplib.IMAP4_SSL, email_id: str, folder: str
) -> bool:
    """
    Copy *email_id* to *folder* then delete from the current mailbox.

    Returns True on success, False on any failure.
    """
    try:
        # Ensure target folder exists (best-effort create)
        conn.create(folder)
    except Exception:
        pass  # Folder may already exist

    try:
        status, _ = conn.copy(email_id.encode(), folder)
        if status != "OK":
            logger.warning(
                "[EmailInboxService] Could not copy %s to %s", email_id, folder
            )
            return False
        # Mark original for deletion
        conn.store(email_id.encode(), "+FLAGS", "\\Deleted")
        conn.expunge()
        return True
    except Exception as exc:
        logger.warning(
            "[EmailInboxService] move_to_folder(%s -> %s) error: %s",
            email_id,
            folder,
            exc,
        )
        return False


# ── Disconnect ────────────────────────────────────────────────────────────────

def disconnect(conn: imaplib.IMAP4_SSL) -> None:
    """Logout and close the IMAP connection gracefully."""
    try:
        conn.close()
    except Exception:
        pass
    try:
        conn.logout()
    except Exception:
        pass


# ── Procurement classifier ────────────────────────────────────────────────────

_PROCUREMENT_KEYWORDS = {
    "invoice",
    "inv",
    "bill",
    "payment",
    "receipt",
    "purchase order",
    "po ",
    "delivery note",
    "grn",
    "quotation",
    "rfq",
    "proforma",
    "statement",
    "remittance",
}

_HIGH_CONFIDENCE_WORDS = {"invoice", "bill", "receipt", "purchase order", "proforma"}


def is_procurement_email(subject: str, body: str) -> tuple[bool, float]:
    """
    Heuristic classifier: decide if an email is procurement-related.

    Returns (is_procurement: bool, confidence: float 0..1).
    """
    combined = (subject + " " + body).lower()

    hit_count = sum(1 for kw in _PROCUREMENT_KEYWORDS if kw in combined)
    high_count = sum(1 for kw in _HIGH_CONFIDENCE_WORDS if kw in combined)

    if hit_count == 0:
        return False, 0.0

    # Weight high-confidence keywords more heavily
    confidence = min(0.5 + high_count * 0.2 + (hit_count - high_count) * 0.05, 1.0)
    return confidence >= 0.5, round(confidence, 2)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _decode_header_value(raw: str) -> str:
    """Decode an RFC 2047-encoded email header value to a plain string."""
    try:
        parts = decode_header(raw)
        decoded_parts = []
        for part_bytes, charset in parts:
            if isinstance(part_bytes, bytes):
                decoded_parts.append(
                    part_bytes.decode(charset or "utf-8", errors="replace")
                )
            else:
                decoded_parts.append(str(part_bytes))
        return "".join(decoded_parts)
    except Exception:
        return str(raw)
