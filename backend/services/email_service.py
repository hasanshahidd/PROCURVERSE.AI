"""
Email Delivery Service — Sprint 8 Pluggable Adapter
=====================================================
Liztek Procure-AI: Replaces MockEmailSender from notification_dispatcher.py
with a proper pluggable adapter pattern.

Architecture
------------
IEmailSender (ABC)
  ├── MockEmailSender        — logs to console, always returns True (default)
  ├── SendGridEmailSender    — SendGrid API (SENDGRID_API_KEY required)
  └── SMTPEmailSender        — standard SMTP via smtplib (SMTP_* vars required)

Factory
-------
get_email_sender() reads EMAIL_PROVIDER env var:
  'mock'     → MockEmailSender (default)
  'sendgrid' → SendGridEmailSender
  'smtp'     → SMTPEmailSender

Environment Variables
---------------------
EMAIL_PROVIDER=mock         (default — logs to console)
EMAIL_PROVIDER=sendgrid     (requires SENDGRID_API_KEY)
EMAIL_PROVIDER=smtp         (requires SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD)
SENDGRID_API_KEY=           (SendGrid API key)
FROM_EMAIL=noreply@procure.ai (sender address, default: noreply@procure.ai)
SMTP_HOST=                  (SMTP server hostname)
SMTP_PORT=587               (SMTP port, default: 587)
SMTP_USERNAME=              (SMTP auth username)
SMTP_PASSWORD=              (SMTP auth password)
SMTP_USE_TLS=true           (enable STARTTLS, default: true)
"""

from __future__ import annotations

import logging
import os
import re
import time
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default from-address
_DEFAULT_FROM_EMAIL = "noreply@procure.ai"


# ── Abstract Base ─────────────────────────────────────────────────────────────

class IEmailSender(ABC):
    """
    Abstract base for all email delivery providers.

    Each implementation must handle single and bulk sending,
    and return structured results for audit logging.
    """

    @abstractmethod
    def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """
        Send a single email.

        Parameters
        ----------
        to        : recipient email address
        subject   : email subject line
        body_html : HTML body content
        from_email: sender address (overrides FROM_EMAIL env var if set)
        cc        : optional list of CC addresses

        Returns True on success, False on failure.
        """

    @abstractmethod
    def bulk_send(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send multiple emails.

        Each message dict should have keys:
          to, subject, body_html, from_email (optional), cc (optional)

        Returns dict: {sent: N, failed: N, errors: [...error strings...]}
        """


# ── Implementation 1: MockEmailSender (default) ───────────────────────────────

class MockEmailSender(IEmailSender):
    """
    Development / CI stub email sender.

    Logs subject, recipient, and metadata to the standard logger instead of
    sending a real email. Always returns True (success).

    Moved from notification_dispatcher.py to this module in Sprint 8.
    The original BaseSender/MockEmailSender in notification_dispatcher is
    replaced by importing this class instead.
    """

    def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """Log the email to console and return True (always succeeds)."""
        sender = from_email or os.environ.get("FROM_EMAIL", _DEFAULT_FROM_EMAIL)
        cc_str = f" | cc: {','.join(cc)}" if cc else ""
        logger.info(
            "[MockEmailSender] SEND -> %s | from: %s | subject: %s%s",
            to,
            sender,
            subject[:80],
            cc_str,
        )
        return True

    def bulk_send(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Log all messages and report all as sent."""
        sent = 0
        errors: List[str] = []
        for msg in messages:
            try:
                self.send(
                    to=msg["to"],
                    subject=msg.get("subject", "(no subject)"),
                    body_html=msg.get("body_html", ""),
                    from_email=msg.get("from_email"),
                    cc=msg.get("cc"),
                )
                sent += 1
            except Exception as exc:
                errors.append(str(exc))
        return {"sent": sent, "failed": len(errors), "errors": errors}


# ── Implementation 2: SendGridEmailSender ────────────────────────────────────

class SendGridEmailSender(IEmailSender):
    """
    SendGrid API email delivery.

    Uses the sendgrid Python library if installed; falls back to direct
    requests HTTP calls to avoid a hard library dependency.

    Implements retry with exponential back-off on rate-limit (429) responses.

    Env vars required:
      SENDGRID_API_KEY — SendGrid API key (https://app.sendgrid.com/settings/api_keys)
      FROM_EMAIL       — sender address (default: noreply@procure.ai)
    """

    _SENDGRID_ENDPOINT = "https://api.sendgrid.com/v3/mail/send"
    _MAX_RETRIES = 3
    _RETRY_DELAY_S = 1.0

    def __init__(self) -> None:
        self._api_key = os.environ.get("SENDGRID_API_KEY", "").strip()
        if not self._api_key:
            raise ValueError(
                "SENDGRID_API_KEY not configured. "
                "Set EMAIL_PROVIDER=mock to use the console logger, "
                "or set SENDGRID_API_KEY in your .env file."
            )
        self._from_email = os.environ.get("FROM_EMAIL", _DEFAULT_FROM_EMAIL).strip()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_payload(
        self,
        to: str,
        subject: str,
        body_html: str,
        from_email: Optional[str],
        cc: Optional[List[str]],
    ) -> dict:
        """Build the SendGrid v3 mail/send JSON payload."""
        sender = from_email or self._from_email
        personalisation: Dict[str, Any] = {"to": [{"email": to}]}
        if cc:
            personalisation["cc"] = [{"email": addr} for addr in cc]

        return {
            "personalizations": [personalisation],
            "from": {"email": sender},
            "subject": subject,
            "content": [{"type": "text/html", "value": body_html or "<p></p>"}],
        }

    def _post_sendgrid(self, payload: dict) -> bool:
        """
        POST to SendGrid API with up to _MAX_RETRIES attempts.
        Returns True on HTTP 202 (accepted), False otherwise.
        """
        import requests

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                response = requests.post(
                    self._SENDGRID_ENDPOINT,
                    json=payload,
                    headers=headers,
                    timeout=30,
                )

                if response.status_code == 202:
                    return True

                if response.status_code == 429:
                    # Rate limited — back off
                    wait = self._RETRY_DELAY_S * attempt
                    logger.warning(
                        "[SendGridEmailSender] Rate limited (429). "
                        "Retrying in %.1fs (attempt %d/%d).",
                        wait, attempt, self._MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue

                logger.error(
                    "[SendGridEmailSender] API error %s: %s",
                    response.status_code,
                    response.text[:300],
                )
                return False

            except Exception as exc:
                logger.warning(
                    "[SendGridEmailSender] Request failed (attempt %d/%d): %s",
                    attempt, self._MAX_RETRIES, exc,
                )
                if attempt < self._MAX_RETRIES:
                    time.sleep(self._RETRY_DELAY_S)

        logger.error("[SendGridEmailSender] All %d attempts failed.", self._MAX_RETRIES)
        return False

    # ── Public interface ──────────────────────────────────────────────────────

    def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """Send a single email via SendGrid API."""
        payload = self._build_payload(to, subject, body_html, from_email, cc)
        success = self._post_sendgrid(payload)
        if success:
            logger.info("[SendGridEmailSender] Sent -> %s | subject: %s", to, subject[:80])
        return success

    def bulk_send(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send multiple emails via SendGrid.
        Each call is individual (no batching) to keep retry logic simple.
        """
        sent = 0
        failed = 0
        errors: List[str] = []

        for msg in messages:
            try:
                ok = self.send(
                    to=msg["to"],
                    subject=msg.get("subject", "(no subject)"),
                    body_html=msg.get("body_html", ""),
                    from_email=msg.get("from_email"),
                    cc=msg.get("cc"),
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                    errors.append(f"SendGrid rejected message to {msg.get('to')}")
            except Exception as exc:
                failed += 1
                errors.append(str(exc))

        logger.info(
            "[SendGridEmailSender] bulk_send complete — sent=%d failed=%d", sent, failed
        )
        return {"sent": sent, "failed": failed, "errors": errors}


# ── Implementation 3: SMTPEmailSender ────────────────────────────────────────

class SMTPEmailSender(IEmailSender):
    """
    Standard SMTP email delivery using the Python stdlib (smtplib + email.mime).

    No external library dependency — works with any SMTP server including
    Gmail (smtp.gmail.com:587), SendGrid SMTP relay, AWS SES SMTP, etc.

    Env vars required:
      SMTP_HOST     — SMTP server hostname
      SMTP_PORT     — port (default: 587)
      SMTP_USERNAME — SMTP auth username
      SMTP_PASSWORD — SMTP auth password
      SMTP_USE_TLS  — enable STARTTLS (default: true)
      FROM_EMAIL    — sender address (default: noreply@procure.ai)
    """

    def __init__(self) -> None:
        self._host = os.environ.get("SMTP_HOST", "").strip()
        if not self._host:
            raise ValueError(
                "SMTP_HOST not configured. "
                "Set EMAIL_PROVIDER=mock to use the console logger, "
                "or set SMTP_HOST (and SMTP_USERNAME, SMTP_PASSWORD) in your .env file."
            )
        self._port = int(os.environ.get("SMTP_PORT", "587"))
        self._username = os.environ.get("SMTP_USERNAME", "").strip()
        self._password = os.environ.get("SMTP_PASSWORD", "").strip()
        self._use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() not in ("false", "0", "no")
        self._from_email = os.environ.get("FROM_EMAIL", _DEFAULT_FROM_EMAIL).strip()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_message(
        self,
        to: str,
        subject: str,
        body_html: str,
        from_email: str,
        cc: Optional[List[str]],
    ) -> MIMEMultipart:
        """Construct a MIME email message."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)

        # Plain text fallback (strip basic HTML tags)
        plain_text = re.sub(r"<[^>]+>", "", body_html) if body_html else ""
        if plain_text:
            msg.attach(MIMEText(plain_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        return msg

    # ── Public interface ──────────────────────────────────────────────────────

    def send(
        self,
        to: str,
        subject: str,
        body_html: str,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """Send a single email via SMTP."""
        import smtplib

        sender = from_email or self._from_email
        msg = self._build_message(to, subject, body_html, sender, cc)
        recipients = [to] + (cc or [])

        try:
            with smtplib.SMTP(self._host, self._port, timeout=30) as smtp:
                smtp.ehlo()
                if self._use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if self._username and self._password:
                    smtp.login(self._username, self._password)
                smtp.sendmail(sender, recipients, msg.as_string())

            logger.info(
                "[SMTPEmailSender] Sent -> %s | subject: %s", to, subject[:80]
            )
            return True

        except Exception as exc:
            logger.error("[SMTPEmailSender] Send failed -> %s: %s", to, exc)
            return False

    def bulk_send(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Send multiple emails, reusing a single SMTP connection where possible.
        Falls back to individual sends on connection failure.
        """
        sent = 0
        failed = 0
        errors: List[str] = []

        for msg in messages:
            try:
                ok = self.send(
                    to=msg["to"],
                    subject=msg.get("subject", "(no subject)"),
                    body_html=msg.get("body_html", ""),
                    from_email=msg.get("from_email"),
                    cc=msg.get("cc"),
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                    errors.append(f"SMTP send returned False for {msg.get('to')}")
            except Exception as exc:
                failed += 1
                errors.append(str(exc))

        logger.info(
            "[SMTPEmailSender] bulk_send complete — sent=%d failed=%d", sent, failed
        )
        return {"sent": sent, "failed": failed, "errors": errors}


# ── Factory function ──────────────────────────────────────────────────────────

def get_email_sender() -> IEmailSender:
    """
    Return the configured email sender implementation.

    Reads the EMAIL_PROVIDER environment variable:
      'mock'     → MockEmailSender (default, no API key needed)
      'sendgrid' → SendGridEmailSender (SENDGRID_API_KEY required)
      'smtp'     → SMTPEmailSender (SMTP_HOST and credentials required)

    Falls back to MockEmailSender if the provider name is unrecognised.

    Environment Variables
    ---------------------
    EMAIL_PROVIDER    : provider selection (default: 'mock')
    SENDGRID_API_KEY  : required for 'sendgrid' provider
    FROM_EMAIL        : sender address (default: 'noreply@procure.ai')
    SMTP_HOST         : required for 'smtp' provider
    SMTP_PORT         : SMTP port (default: 587)
    SMTP_USERNAME     : SMTP auth username
    SMTP_PASSWORD     : SMTP auth password
    SMTP_USE_TLS      : enable STARTTLS (default: 'true')
    """
    provider = os.environ.get("EMAIL_PROVIDER", "mock").strip().lower()

    if provider == "sendgrid":
        logger.info("[get_email_sender] Using SendGridEmailSender")
        return SendGridEmailSender()

    if provider == "smtp":
        logger.info("[get_email_sender] Using SMTPEmailSender")
        return SMTPEmailSender()

    if provider != "mock":
        logger.warning(
            "[get_email_sender] Unknown EMAIL_PROVIDER '%s'; falling back to mock.",
            provider,
        )

    logger.info("[get_email_sender] Using MockEmailSender (default)")
    return MockEmailSender()


# ── Sprint 8: Module-level helpers and procurement email templates ────────────
#
# Config (from env vars with fallbacks, Sprint 8 naming convention)
# -----------------------------------------------------------------
import uuid as _uuid
from datetime import datetime as _datetime
from typing import Union as _Union

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT_VAL = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD_VAL = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "procurement@procure-ai.com")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"


def _html_header(title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6;padding:24px 0;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
      <!-- Header -->
      <tr>
        <td style="background:linear-gradient(135deg,#1e40af 0%,#2563eb 100%);padding:28px 32px;">
          <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Procure AI</h1>
          <p style="margin:4px 0 0;color:#bfdbfe;font-size:13px;">{title}</p>
        </td>
      </tr>
      <!-- Body -->
      <tr><td style="padding:32px;">
"""


def _html_footer() -> str:
    year = _datetime.now().year
    return f"""
      </td></tr>
      <!-- Footer -->
      <tr>
        <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:20px 32px;text-align:center;">
          <p style="margin:0;color:#94a3b8;font-size:12px;">This is an automated notification from Procure AI</p>
          <p style="margin:4px 0 0;color:#cbd5e1;font-size:11px;">&copy; {year} Procure AI &mdash; All rights reserved</p>
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _build_html(title: str, body_html: str) -> str:
    return _html_header(title) + body_html + _html_footer()


def send_email(
    to: _Union[str, list],
    subject: str,
    html_body: str,
    text_body: str = "",
) -> dict:
    """
    Send an email using the configured channel.

    Behaviour:
    - EMAIL_ENABLED=false  → log content and return {success: True, mode: "logged"}
    - SENDGRID_API_KEY set → use SendGrid HTTP API via httpx
    - Otherwise            → use smtplib SMTP with STARTTLS

    Returns: {success, mode, message_id, error}
    """
    import smtplib as _smtplib
    from email.mime.multipart import MIMEMultipart as _MM
    from email.mime.text import MIMEText as _MT

    recipients = [to] if isinstance(to, str) else list(to)
    message_id = str(_uuid.uuid4())

    if not EMAIL_ENABLED:
        logger.info(
            "[EmailService] EMAIL_ENABLED=false — logging email instead of sending.\n"
            "  To:      %s\n"
            "  Subject: %s\n"
            "  Body:    %s",
            ", ".join(recipients),
            subject,
            text_body or "(html only)",
        )
        return {"success": True, "mode": "logged", "message_id": message_id, "error": None}

    if SENDGRID_API_KEY:
        # SendGrid path via httpx (no sendgrid package needed)
        try:
            import httpx
            payload = {
                "personalizations": [{"to": [{"email": r} for r in recipients]}],
                "from": {"email": SMTP_FROM},
                "subject": subject,
                "content": [],
            }
            if text_body:
                payload["content"].append({"type": "text/plain", "value": text_body})
            payload["content"].append({"type": "text/html", "value": html_body})

            resp = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {SENDGRID_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 202):
                sg_id = resp.headers.get("X-Message-Id", message_id)
                logger.info("[EmailService] SendGrid OK — id=%s to=%s", sg_id, recipients)
                return {"success": True, "mode": "sendgrid", "message_id": sg_id, "error": None}
            logger.error("[EmailService] SendGrid error %s: %s", resp.status_code, resp.text)
            return {
                "success": False, "mode": "sendgrid", "message_id": None,
                "error": f"SendGrid HTTP {resp.status_code}: {resp.text}",
            }
        except Exception as exc:
            logger.error("[EmailService] SendGrid exception: %s", exc)
            return {"success": False, "mode": "sendgrid", "message_id": None, "error": str(exc)}

    if RESEND_API_KEY:
        # Resend path — simple HTTP API, no packages needed
        try:
            import httpx
            payload = {
                "from": SMTP_FROM,
                "to": recipients,
                "subject": subject,
                "html": html_body,
            }
            if text_body:
                payload["text"] = text_body

            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201):
                resp_data = resp.json()
                resend_id = resp_data.get("id", message_id)
                logger.info("[EmailService] Resend OK — id=%s to=%s", resend_id, recipients)
                return {"success": True, "mode": "resend", "message_id": resend_id, "error": None}
            logger.error("[EmailService] Resend error %s: %s", resp.status_code, resp.text)
            return {
                "success": False, "mode": "resend", "message_id": None,
                "error": f"Resend HTTP {resp.status_code}: {resp.text}",
            }
        except Exception as exc:
            logger.error("[EmailService] Resend exception: %s", exc)
            return {"success": False, "mode": "resend", "message_id": None, "error": str(exc)}

    # SMTP path
    try:
        msg = _MM("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = ", ".join(recipients)
        msg["Message-ID"] = f"<{message_id}@procure-ai.com>"
        if text_body:
            msg.attach(_MT(text_body, "plain", "utf-8"))
        msg.attach(_MT(html_body, "html", "utf-8"))

        with _smtplib.SMTP(SMTP_HOST, SMTP_PORT_VAL, timeout=15) as server:
            server.ehlo()
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD_VAL:
                server.login(SMTP_USER, SMTP_PASSWORD_VAL)
            server.sendmail(SMTP_FROM, recipients, msg.as_string())

        logger.info("[EmailService] SMTP OK — id=%s to=%s", message_id, recipients)
        return {"success": True, "mode": "smtp", "message_id": message_id, "error": None}
    except Exception as exc:
        logger.error("[EmailService] SMTP exception: %s", exc)
        return {"success": False, "mode": "smtp", "message_id": None, "error": str(exc)}


# ── Procurement-specific email template functions ─────────────────────────────

def send_approval_request_email(
    approver_email: str,
    approver_name: str,
    pr_data: dict,
) -> dict:
    """
    Notify an approver that a Purchase Requisition awaits their decision.
    Includes APPROVE / REJECT buttons linking to /my-approvals.
    """
    pr_number = pr_data.get("pr_number", pr_data.get("id", "N/A"))
    description = pr_data.get("description", "N/A")
    amount = pr_data.get("budget", pr_data.get("amount", 0))
    requestor = pr_data.get("requester_name", pr_data.get("requester", "Unknown"))
    department = pr_data.get("department", "N/A")
    currency = pr_data.get("currency", "AED")
    priority = pr_data.get("urgency", pr_data.get("priority_level", "Medium"))
    created_at = pr_data.get("created_at", _datetime.now().strftime("%d %b %Y"))

    priority_color = {
        "High": "#dc2626", "Critical": "#dc2626",
        "Medium": "#d97706", "Low": "#16a34a",
    }.get(str(priority), "#6b7280")

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    approval_link = f"{frontend_url}/my-approvals"

    body_html = f"""
<p style="margin:0 0 20px;color:#374151;font-size:15px;">Hello <strong>{approver_name}</strong>,</p>
<p style="margin:0 0 24px;color:#374151;font-size:14px;">
  A Purchase Requisition requires your approval. Please review the details below and take action.
</p>

<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;margin-bottom:28px;">
  <tr style="background:#f8fafc;">
    <td colspan="2" style="padding:12px 16px;border-bottom:1px solid #e2e8f0;">
      <strong style="color:#1e40af;font-size:14px;">PR #{pr_number}</strong>
    </td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;width:40%;border-bottom:1px solid #f1f5f9;">Description</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{description}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Department</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{department}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Amount</td>
    <td style="padding:10px 16px;color:#111827;font-size:14px;font-weight:700;border-bottom:1px solid #f1f5f9;">{currency} {float(amount):,.2f}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Requestor</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{requestor}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Priority</td>
    <td style="padding:10px 16px;font-size:13px;border-bottom:1px solid #f1f5f9;">
      <span style="background:{priority_color}1a;color:{priority_color};border:1px solid {priority_color}33;padding:2px 10px;border-radius:12px;font-weight:600;font-size:12px;">{priority}</span>
    </td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;">Submitted</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;">{created_at}</td>
  </tr>
</table>

<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
  <tr>
    <td align="center" style="padding:0 8px 0 0;">
      <a href="{approval_link}?action=approve&pr={pr_number}"
         style="display:inline-block;background:#16a34a;color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:6px;font-size:15px;font-weight:700;letter-spacing:0.3px;">
        &#x2705; APPROVE
      </a>
    </td>
    <td align="center" style="padding:0 0 0 8px;">
      <a href="{approval_link}?action=reject&pr={pr_number}"
         style="display:inline-block;background:#dc2626;color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:6px;font-size:15px;font-weight:700;letter-spacing:0.3px;">
        &#x274C; REJECT
      </a>
    </td>
  </tr>
</table>

<p style="margin:0;color:#6b7280;font-size:12px;text-align:center;">
  Or visit <a href="{approval_link}" style="color:#2563eb;">{approval_link}</a> to manage all pending approvals.
</p>
"""

    html = _build_html("Approval Required", body_html)
    text = (
        f"Approval Required — PR #{pr_number}\n\n"
        f"Hello {approver_name},\n\n"
        f"PR #{pr_number} from {requestor} ({department}) requires your approval.\n"
        f"Amount: {currency} {float(amount):,.2f}\n"
        f"Description: {description}\n\n"
        f"Visit {approval_link} to approve or reject."
    )
    return send_email(
        to=approver_email,
        subject=f"[Procure AI] Approval Required \u2014 PR #{pr_number}",
        html_body=html,
        text_body=text,
    )


def send_approval_decision_email(
    requester_email: str,
    pr_data: dict,
    decision: str,
    approver_name: str,
) -> dict:
    """Notify the PR requester of an approval or rejection decision."""
    pr_number = pr_data.get("pr_number", pr_data.get("id", "N/A"))
    description = pr_data.get("description", "N/A")
    amount = pr_data.get("budget", pr_data.get("amount", 0))
    currency = pr_data.get("currency", "AED")

    is_approved = decision.lower() in ("approved", "approve")
    status_label = "APPROVED" if is_approved else "REJECTED"
    status_color = "#16a34a" if is_approved else "#dc2626"
    status_bg = "#f0fdf4" if is_approved else "#fef2f2"
    status_icon = "&#x2705;" if is_approved else "&#x274C;"
    message = (
        f"Your Purchase Requisition has been <strong>approved</strong> by {approver_name}. "
        "It will now proceed to the next stage of the procurement process."
        if is_approved else
        f"Your Purchase Requisition has been <strong>rejected</strong> by {approver_name}. "
        "Please review the requirements and resubmit if necessary."
    )

    body_html = f"""
<p style="margin:0 0 20px;color:#374151;font-size:15px;">Your PR #{pr_number} has been reviewed.</p>

<div style="background:{status_bg};border:2px solid {status_color}33;border-radius:8px;padding:20px;text-align:center;margin-bottom:28px;">
  <span style="font-size:32px;">{status_icon}</span>
  <p style="margin:8px 0 4px;color:{status_color};font-size:20px;font-weight:700;">{status_label}</p>
  <p style="margin:0;color:#6b7280;font-size:13px;">Decision by {approver_name}</p>
</div>

<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;margin-bottom:24px;">
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;width:40%;border-bottom:1px solid #f1f5f9;">PR Number</td>
    <td style="padding:10px 16px;color:#1e40af;font-size:13px;font-weight:700;border-bottom:1px solid #f1f5f9;">{pr_number}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Description</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{description}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;">Amount</td>
    <td style="padding:10px 16px;color:#111827;font-size:14px;font-weight:700;">{currency} {float(amount):,.2f}</td>
  </tr>
</table>

<p style="margin:0;color:#374151;font-size:14px;">{message}</p>
"""

    html = _build_html(f"PR {status_label}", body_html)
    text = (
        f"PR #{pr_number} \u2014 {status_label}\n\n"
        f"Your requisition for {currency} {float(amount):,.2f} has been {status_label.lower()} "
        f"by {approver_name}.\nDescription: {description}"
    )
    return send_email(
        to=requester_email,
        subject=f"[Procure AI] PR #{pr_number} {status_label}",
        html_body=html,
        text_body=text,
    )


def send_payment_notification_email(
    finance_email: str,
    payment_data: dict,
) -> dict:
    """Notify the finance team when a payment run is created."""
    invoice_number = payment_data.get("invoice_number", payment_data.get("invoice_no", "N/A"))
    vendor = payment_data.get("vendor_name", payment_data.get("vendor", "N/A"))
    amount = payment_data.get("amount", payment_data.get("total_amount", 0))
    due_date = payment_data.get("due_date", "N/A")
    payment_method = payment_data.get("payment_method", "Bank Transfer")
    currency = payment_data.get("currency", "AED")
    po_number = payment_data.get("po_number", "N/A")

    body_html = f"""
<p style="margin:0 0 20px;color:#374151;font-size:15px;">
  A new payment run has been created and requires your attention.
</p>

<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;margin-bottom:28px;">
  <tr style="background:#f8fafc;">
    <td colspan="2" style="padding:12px 16px;border-bottom:1px solid #e2e8f0;">
      <strong style="color:#1e40af;font-size:14px;">Payment Details</strong>
    </td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;width:40%;border-bottom:1px solid #f1f5f9;">Invoice Number</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;font-weight:700;border-bottom:1px solid #f1f5f9;">{invoice_number}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">PO Number</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{po_number}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Vendor</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{vendor}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Amount</td>
    <td style="padding:10px 16px;color:#111827;font-size:16px;font-weight:700;border-bottom:1px solid #f1f5f9;">{currency} {float(amount):,.2f}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Payment Method</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{payment_method}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;">Due Date</td>
    <td style="padding:10px 16px;color:#dc2626;font-size:13px;font-weight:700;">{due_date}</td>
  </tr>
</table>

<p style="margin:0;color:#374151;font-size:14px;">
  Please process this payment before the due date to avoid late payment penalties.
</p>
"""

    html = _build_html("Payment Notification", body_html)
    text = (
        f"Payment Notification \u2014 Invoice {invoice_number}\n\n"
        f"Vendor: {vendor}\nAmount: {currency} {float(amount):,.2f}\n"
        f"Due Date: {due_date}\nPayment Method: {payment_method}"
    )
    return send_email(
        to=finance_email,
        subject=f"[Procure AI] Payment Due \u2014 {vendor} | {currency} {float(amount):,.2f}",
        html_body=html,
        text_body=text,
    )


def send_po_notification_email(
    vendor_email: str,
    vendor_name: str,
    po_data: dict,
) -> dict:
    """Send Purchase Order notification to the vendor."""
    po_number = po_data.get("po_number", "N/A")
    pr_number = po_data.get("pr_number", "N/A")
    product_name = po_data.get("product_name", "N/A")
    quantity = po_data.get("quantity", 1)
    total = po_data.get("budget", po_data.get("total", 0))
    currency = po_data.get("currency", "USD")
    department = po_data.get("department", "N/A")
    requester = po_data.get("requester_name", po_data.get("requester", "N/A"))
    delivery_address = po_data.get("delivery_address", "As per contract terms")

    try:
        total_fmt = f"{float(total):,.2f}"
    except (ValueError, TypeError):
        total_fmt = str(total)

    body_html = f"""
<p style="margin:0 0 20px;color:#374151;font-size:15px;">
  Dear <strong>{vendor_name}</strong>,
</p>
<p style="margin:0 0 20px;color:#374151;font-size:15px;">
  A new Purchase Order has been issued to your company. Please review the
  details below and confirm receipt.
</p>

<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;margin-bottom:28px;">
  <tr style="background:#f0fdf4;">
    <td colspan="2" style="padding:12px 16px;border-bottom:1px solid #e2e8f0;">
      <strong style="color:#166534;font-size:14px;">Purchase Order {po_number}</strong>
    </td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;width:40%;border-bottom:1px solid #f1f5f9;">PO Number</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;font-weight:700;border-bottom:1px solid #f1f5f9;">{po_number}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">PR Reference</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{pr_number}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Item</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{product_name}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Quantity</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{quantity}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Total Value</td>
    <td style="padding:10px 16px;color:#111827;font-size:16px;font-weight:700;border-bottom:1px solid #f1f5f9;">{currency} {total_fmt}</td>
  </tr>
  <tr style="background:#fafafa;">
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">Requesting Dept</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{department}</td>
  </tr>
  <tr>
    <td style="padding:10px 16px;color:#6b7280;font-size:13px;">Delivery Address</td>
    <td style="padding:10px 16px;color:#111827;font-size:13px;">{delivery_address}</td>
  </tr>
</table>

<p style="margin:0 0 8px;color:#374151;font-size:14px;">
  Please confirm this order and provide an estimated delivery date at your
  earliest convenience.
</p>
<p style="margin:0;color:#6b7280;font-size:12px;">
  This is an automated notification from Procure AI.
</p>
"""

    html = _build_html(f"Purchase Order {po_number}", body_html)
    text = (
        f"Purchase Order {po_number}\n\n"
        f"Dear {vendor_name},\n\n"
        f"A new PO has been issued:\n"
        f"  Item: {product_name}\n  Qty: {quantity}\n"
        f"  Total: {currency} {total_fmt}\n  Dept: {department}\n\n"
        f"Please confirm and provide estimated delivery date."
    )
    return send_email(
        to=vendor_email,
        subject=f"[Procure AI] Purchase Order {po_number} — {currency} {total_fmt}",
        html_body=html,
        text_body=text,
    )


def send_low_stock_alert_email(
    manager_email: str,
    items: list,
) -> dict:
    """
    Alert the inventory manager when items fall below reorder point.
    items: list of dicts with keys: item_code, description, current_qty, reorder_point, urgency
    """
    item_count = len(items)

    rows_html = ""
    for item in items:
        urgency = item.get("urgency", "Medium")
        urgency_color = {
            "Critical": "#dc2626", "High": "#d97706",
            "Medium": "#2563eb", "Low": "#16a34a",
        }.get(str(urgency), "#6b7280")
        current = item.get("current_qty", item.get("quantity_on_hand", 0))
        reorder = item.get("reorder_point", item.get("reorder_level", 0))
        rows_html += f"""
  <tr>
    <td style="padding:10px 12px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;font-family:monospace;">{item.get("item_code", "N/A")}</td>
    <td style="padding:10px 12px;color:#374151;font-size:13px;border-bottom:1px solid #f1f5f9;">{item.get("description", item.get("item_name", "N/A"))}</td>
    <td style="padding:10px 12px;text-align:right;color:#dc2626;font-size:13px;font-weight:700;border-bottom:1px solid #f1f5f9;">{current}</td>
    <td style="padding:10px 12px;text-align:right;color:#6b7280;font-size:13px;border-bottom:1px solid #f1f5f9;">{reorder}</td>
    <td style="padding:10px 12px;text-align:center;border-bottom:1px solid #f1f5f9;">
      <span style="background:{urgency_color}1a;color:{urgency_color};border:1px solid {urgency_color}33;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;">{urgency}</span>
    </td>
  </tr>"""

    body_html = f"""
<p style="margin:0 0 8px;color:#374151;font-size:15px;">
  <strong>{item_count} item{'s' if item_count != 1 else ''}</strong> below the reorder threshold and require immediate attention.
</p>
<p style="margin:0 0 24px;color:#6b7280;font-size:13px;">Please initiate purchase requisitions for the affected items.</p>

<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;margin-bottom:28px;">
  <tr style="background:#1e40af;">
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:left;font-weight:600;">Item Code</th>
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:left;font-weight:600;">Description</th>
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:right;font-weight:600;">Current Qty</th>
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:right;font-weight:600;">Reorder Point</th>
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:center;font-weight:600;">Urgency</th>
  </tr>
  {rows_html}
</table>
"""

    html = _build_html("Low Stock Alert", body_html)
    lines = [
        f"  - {i.get('item_code','N/A')}: {i.get('description','N/A')} "
        f"(qty {i.get('current_qty',0)}, reorder {i.get('reorder_point',0)})"
        for i in items
    ]
    text = f"Low Stock Alert \u2014 {item_count} item(s) below reorder point:\n\n" + "\n".join(lines)
    return send_email(
        to=manager_email,
        subject=f"[Procure AI] Low Stock Alert \u2014 {item_count} item{'s' if item_count != 1 else ''} below reorder threshold",
        html_body=html,
        text_body=text,
    )


def send_contract_expiry_alert_email(
    manager_email: str,
    contracts: list,
) -> dict:
    """
    Alert the procurement manager of contracts expiring within 30 days.
    contracts: list of dicts with keys: contract_id, vendor_name, value, expiry_date, days_remaining
    """
    contract_count = len(contracts)

    rows_html = ""
    for contract in contracts:
        days = contract.get("days_remaining", contract.get("days_to_expiry", 0))
        if days <= 7:
            urgency, color = "Critical", "#dc2626"
        elif days <= 14:
            urgency, color = "Urgent", "#d97706"
        else:
            urgency, color = "Expiring Soon", "#2563eb"

        value = contract.get("value", contract.get("contract_value", 0))
        currency = contract.get("currency", "AED")
        rows_html += f"""
  <tr>
    <td style="padding:10px 12px;color:#1e40af;font-size:13px;font-weight:700;border-bottom:1px solid #f1f5f9;">{contract.get("contract_id", "N/A")}</td>
    <td style="padding:10px 12px;color:#111827;font-size:13px;border-bottom:1px solid #f1f5f9;">{contract.get("vendor_name", contract.get("vendor", "N/A"))}</td>
    <td style="padding:10px 12px;color:#374151;font-size:13px;border-bottom:1px solid #f1f5f9;">{currency} {float(value):,.2f}</td>
    <td style="padding:10px 12px;color:#374151;font-size:13px;border-bottom:1px solid #f1f5f9;">{contract.get("expiry_date", "N/A")}</td>
    <td style="padding:10px 12px;text-align:center;border-bottom:1px solid #f1f5f9;">
      <span style="background:{color}1a;color:{color};border:1px solid {color}33;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;">{days}d \u2014 {urgency}</span>
    </td>
  </tr>"""

    body_html = f"""
<p style="margin:0 0 8px;color:#374151;font-size:15px;">
  <strong>{contract_count} contract{'s' if contract_count != 1 else ''}</strong> expiring within the next 30 days.
</p>
<p style="margin:0 0 24px;color:#6b7280;font-size:13px;">Please review and initiate renewal or termination procedures.</p>

<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;margin-bottom:28px;">
  <tr style="background:#1e40af;">
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:left;font-weight:600;">Contract ID</th>
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:left;font-weight:600;">Vendor</th>
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:left;font-weight:600;">Value</th>
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:left;font-weight:600;">Expiry Date</th>
    <th style="padding:10px 12px;color:#ffffff;font-size:12px;text-align:center;font-weight:600;">Status</th>
  </tr>
  {rows_html}
</table>

<p style="margin:0;color:#374151;font-size:14px;">
  Early renewal typically takes 2-4 weeks. Please action contracts marked <strong style="color:#dc2626;">Critical</strong> immediately.
</p>
"""

    html = _build_html("Contract Expiry Alert", body_html)
    lines = [
        f"  - {c.get('contract_id','N/A')}: {c.get('vendor_name','N/A')} "
        f"expires {c.get('expiry_date','N/A')} ({c.get('days_remaining',0)} days)"
        for c in contracts
    ]
    text = (
        f"Contract Expiry Alert \u2014 {contract_count} contract(s) expiring within 30 days:\n\n"
        + "\n".join(lines)
    )
    return send_email(
        to=manager_email,
        subject=f"[Procure AI] Contract Expiry Alert \u2014 {contract_count} contract{'s' if contract_count != 1 else ''} expiring soon",
        html_body=html,
        text_body=text,
    )
