"""
NotificationDispatcher — Sprint 8
===================================
Polls notification_log WHERE status='pending', dispatches via pluggable sender,
marks as 'sent' or 'failed'.

Sprint 8 changes
----------------
- MockEmailSender has been moved to backend.services.email_service
- NotificationDispatcher now imports get_email_sender() from email_service
- EMAIL_PROVIDER env var selects the delivery provider:
    'mock'     → MockEmailSender (default — logs to console)
    'sendgrid' → SendGridEmailSender (SENDGRID_API_KEY required)
    'smtp'     → SMTPEmailSender (SMTP_* vars required)
- NotificationDispatcher.__init__(sender=None) falls back to get_email_sender()
  when no sender is explicitly provided, enabling backward compatibility

Can run as:
  python -m backend.services.notification_dispatcher        (single sweep)
  python -m backend.services.notification_dispatcher --loop (continuous, 30s interval)

Architecture
------------
NotificationDispatcher
  │
  ├── IEmailSender (from email_service)
  │     ├── MockEmailSender      — logs to console (default)
  │     ├── SendGridEmailSender  — SendGrid API
  │     └── SMTPEmailSender      — standard SMTP
  │
  └── dispatch_pending(limit)  — single sweep: fetch → send → mark sent/failed
      run_loop(interval)       — repeating sweep at `interval` seconds

Database access
---------------
The base IDataSourceAdapter does not expose get_pending_notifications().
This service therefore queries notification_log directly via
nmi_data_service.get_conn() (the same psycopg2 connection used by other
service-layer modules).  This is the ONLY module allowed to call get_conn()
directly; agents still go through adapters.

notification_log schema (expected):
  id              SERIAL PRIMARY KEY
  event_type      VARCHAR
  document_type   VARCHAR
  document_id     VARCHAR
  recipient_email VARCHAR
  recipient_role  VARCHAR
  subject         TEXT
  body            TEXT
  status          VARCHAR  -- 'pending' | 'sent' | 'failed'
  agent_name      VARCHAR
  created_at      TIMESTAMP DEFAULT NOW()
  sent_at         TIMESTAMP
  error_message   TEXT
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from backend.services.nmi_data_service import get_conn
from backend.services.email_service import IEmailSender, MockEmailSender, get_email_sender

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legacy BaseSender shim — backward compatibility for Sprint 7 code that
# may subclass BaseSender directly.  New code should subclass IEmailSender
# from backend.services.email_service instead.
# ---------------------------------------------------------------------------

class BaseSender:
    """
    Sprint 7 abstract base for email senders.

    Retained for backward compatibility.  New implementations should
    subclass IEmailSender from backend.services.email_service.

    Sprint 8: NotificationDispatcher now accepts both BaseSender subclasses
    (legacy) and IEmailSender implementations (new).
    """

    def send(
        self,
        recipient_email: str,
        subject: str,
        body: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send one email. Returns True on success, False on failure."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class NotificationDispatcher:
    """
    Polls notification_log for rows with status='pending' and dispatches
    each one through the configured sender.

    Usage
    -----
    dispatcher = NotificationDispatcher()            # uses MockEmailSender
    result     = dispatcher.dispatch_pending()       # single sweep
    dispatcher.run_loop(interval_seconds=30)         # continuous loop

    Custom sender:
    dispatcher = NotificationDispatcher(sender=MyRealSender())
    """

    def __init__(self, sender=None):
        """
        Initialise with an optional sender.

        Parameters
        ----------
        sender : IEmailSender | BaseSender | None
            Email sender implementation.  If None, get_email_sender() is called
            to select the implementation based on the EMAIL_PROVIDER env var
            (default: MockEmailSender).

            Accepts both:
              - IEmailSender subclasses (Sprint 8 email_service.py)
              - BaseSender subclasses (Sprint 7 legacy, backward compat)
        """
        if sender is None:
            self.sender = get_email_sender()
        else:
            self.sender = sender

        logger.info(
            "[NotificationDispatcher] Initialised with sender: %s",
            type(self.sender).__name__,
        )

    # ── Single sweep ──────────────────────────────────────────────────────────

    def dispatch_pending(self, limit: int = 50) -> Dict[str, Any]:
        """
        Fetch up to `limit` pending notifications, dispatch each, and update
        their status in notification_log.

        Returns
        -------
        dict with keys: total, sent, failed, skipped, duration_ms
        """
        start_ms = int(time.time() * 1000)

        rows = _fetch_pending_notifications(limit=limit)
        total   = len(rows)
        sent    = 0
        failed  = 0
        skipped = 0

        if not rows:
            logger.debug("[NotificationDispatcher] No pending notifications found.")
            return {
                "total":       0,
                "sent":        0,
                "failed":      0,
                "skipped":     0,
                "duration_ms": int(time.time() * 1000) - start_ms,
            }

        logger.info(
            "[NotificationDispatcher] Processing %d pending notification(s).", total
        )

        for row in rows:
            notif_id       = row["id"]
            recipient      = row.get("recipient_email", "")
            subject        = row.get("subject") or f"[{row.get('event_type', 'notification')}]"
            body           = row.get("body") or ""
            metadata       = {
                "event_type":    row.get("event_type", ""),
                "document_type": row.get("document_type", ""),
                "document_id":   row.get("document_id", ""),
                "agent_name":    row.get("agent_name", ""),
            }

            if not recipient:
                logger.warning(
                    "[NotificationDispatcher] Skipping id=%s — no recipient email.",
                    notif_id,
                )
                _mark_notification(
                    notif_id=notif_id,
                    status="failed",
                    error_message="No recipient email address",
                )
                failed += 1
                continue

            try:
                # Sprint 8: Support both IEmailSender (to/subject/body_html/cc)
                # and legacy BaseSender (recipient_email/subject/body/metadata).
                if isinstance(self.sender, IEmailSender):
                    success = self.sender.send(
                        to=recipient,
                        subject=subject,
                        body_html=body,
                    )
                else:
                    # Legacy BaseSender interface
                    success = self.sender.send(
                        recipient_email=recipient,
                        subject=subject,
                        body=body,
                        metadata=metadata,
                    )
            except Exception as exc:
                logger.error(
                    "[NotificationDispatcher] Sender raised for id=%s: %s",
                    notif_id, exc,
                )
                _mark_notification(
                    notif_id=notif_id,
                    status="failed",
                    error_message=str(exc)[:500],
                )
                failed += 1
                continue

            if success:
                _mark_notification(notif_id=notif_id, status="sent")
                sent += 1
                logger.debug(
                    "[NotificationDispatcher] Sent id=%s → %s", notif_id, recipient
                )
            else:
                _mark_notification(
                    notif_id=notif_id,
                    status="failed",
                    error_message="Sender returned False",
                )
                failed += 1
                logger.warning(
                    "[NotificationDispatcher] Sender returned False for id=%s",
                    notif_id,
                )

        duration_ms = int(time.time() * 1000) - start_ms
        summary = {
            "total":       total,
            "sent":        sent,
            "failed":      failed,
            "skipped":     skipped,
            "duration_ms": duration_ms,
        }
        logger.info(
            "[NotificationDispatcher] Sweep done — sent=%d failed=%d skipped=%d (%dms)",
            sent, failed, skipped, duration_ms,
        )
        return summary

    # ── Continuous loop ───────────────────────────────────────────────────────

    def run_loop(self, interval_seconds: int = 30) -> None:
        """
        Continuously dispatch pending notifications, sleeping `interval_seconds`
        between sweeps.

        Runs until interrupted (KeyboardInterrupt / SIGTERM).
        Suitable for running in a background thread or as a standalone process.
        """
        logger.info(
            "[NotificationDispatcher] Starting continuous loop (interval=%ds).",
            interval_seconds,
        )
        try:
            while True:
                try:
                    result = self.dispatch_pending()
                    if result["total"] > 0:
                        logger.info(
                            "[NotificationDispatcher] Loop result: %s", result
                        )
                except Exception as exc:
                    logger.error(
                        "[NotificationDispatcher] Error during sweep: %s", exc
                    )

                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("[NotificationDispatcher] Loop stopped by KeyboardInterrupt.")


# ---------------------------------------------------------------------------
# Private DB helpers  (direct psycopg2 — allowed for service-layer only)
# ---------------------------------------------------------------------------


def _fetch_pending_notifications(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Query notification_log for rows where status='pending'.
    Uses SELECT … FOR UPDATE SKIP LOCKED to allow concurrent workers
    without double-dispatch.

    Returns a list of dicts (RealDictCursor rows converted to plain dicts).
    """
    sql = """
        SELECT
            id,
            event_type,
            document_type,
            document_id,
            recipient_email,
            recipient_role,
            subject,
            body,
            status,
            agent_name,
            created_at
        FROM notification_log
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT %s
        FOR UPDATE SKIP LOCKED
    """
    conn = None
    try:
        conn = get_conn()
        conn.autocommit = False          # explicit transaction for FOR UPDATE
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (limit,))
            rows = [dict(row) for row in cur.fetchall()]
        # Don't commit here — each row will be updated individually
        # by _mark_notification() which opens its own connection.
        conn.rollback()                  # release the FOR UPDATE locks
        return rows
    except Exception as exc:
        logger.error("[NotificationDispatcher] _fetch_pending_notifications: %s", exc)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _mark_notification(
    notif_id: int,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """
    Update a single notification_log row with the dispatch outcome.

    status : 'sent' | 'failed'
    """
    if status == "sent":
        sql = """
            UPDATE notification_log
            SET    status   = 'sent',
                   sent_at  = %s
            WHERE  id       = %s
        """
        params = (datetime.utcnow(), notif_id)
    else:
        sql = """
            UPDATE notification_log
            SET    status        = 'failed',
                   error_message = %s,
                   sent_at       = %s
            WHERE  id            = %s
        """
        params = (error_message or "unknown error", datetime.utcnow(), notif_id)

    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception as exc:
        logger.error(
            "[NotificationDispatcher] _mark_notification(id=%s, status=%s): %s",
            notif_id, status, exc,
        )
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


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "NotificationDispatcher — Sprint 7 Liztek P2P Pipeline\n"
            "Polls notification_log for pending rows and dispatches via email sender."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously (every --interval seconds). Default: single sweep.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Seconds between sweeps when --loop is active (default: 30).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum notifications to process per sweep (default: 50).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Sprint 8: sender selected by EMAIL_PROVIDER env var (default: MockEmailSender)
    dispatcher = NotificationDispatcher()   # get_email_sender() called internally

    if args.loop:
        logger.info(
            "Starting NotificationDispatcher loop (interval=%ds, limit=%d)",
            args.interval, args.limit,
        )
        dispatcher.run_loop(interval_seconds=args.interval)
    else:
        logger.info(
            "Running single NotificationDispatcher sweep (limit=%d)", args.limit
        )
        result = dispatcher.dispatch_pending(limit=args.limit)
        print(f"Dispatch complete: {result}")
