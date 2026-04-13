"""
Exception Resolution Service — Dev Spec 2.0, G-05
====================================================
Manages the exception_queue lifecycle: creation, assignment, resolution,
escalation, SLA-breach detection, and reporting.

Table: exception_queue  (created by devspec2_gap_tables migration)
Columns:
    id, exception_id, exception_type, severity, source_document_type,
    source_document_id, workflow_run_id, description, ai_context,
    ai_recommendation, assigned_to, sla_deadline, sla_breached,
    resolution_action, resolution_notes, resolved_by, resolved_at,
    status, escalation_level, created_at, updated_at

Statuses: open -> assigned -> in_progress -> escalated -> resolved -> closed

Usage:
    from backend.services.exception_resolution_service import get_exception_service
    svc = get_exception_service()
    exc = svc.create_exception({...})
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SLA_HOURS: Dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 24,
    "MEDIUM": 48,
    "LOW": 72,
}

AI_CONTEXT_TEMPLATES: Dict[str, str] = {
    "three_way_match_failure": "PO/GRN/Invoice mismatch detected. Check quantity/price variances.",
    "price_variance": "PO price differs from contract price beyond tolerance.",
    "duplicate_invoice": "Potential duplicate invoice detected by dedup engine.",
    "budget_exceeded": "PR/PO amount exceeds department budget allocation.",
    "quality_failure": "QC inspection failed. Goods do not meet specifications.",
    "delivery_delay": "Delivery overdue by >5 business days.",
    "vendor_hold": "Vendor account is on hold. Payment blocked.",
    "approval_timeout": "Approval request has exceeded SLA without response.",
    "grn_discrepancy": "Received quantity differs from PO quantity.",
    "fx_exposure": "FX exposure exceeds $50K threshold.",
}

# Escalation routing table: maps escalation_level to a role/queue.
# Level 0 = initial assignee, level 1 = supervisor, level 2 = manager, etc.
ESCALATION_ROUTING: Dict[int, str] = {
    1: "supervisor",
    2: "procurement_manager",
    3: "finance_director",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_conn() -> psycopg2.extensions.connection:
    """Open a fresh psycopg2 connection to the procure-AI PostgreSQL database."""
    db_url = DATABASE_URL or os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(db_url)


def _generate_exception_id() -> str:
    """Create a short, human-friendly exception ID such as EXC-A3F1B902."""
    return f"EXC-{uuid.uuid4().hex[:8].upper()}"


def _calculate_sla_deadline(severity: str, created_at: Optional[datetime] = None) -> datetime:
    """Return UTC deadline timestamp based on severity."""
    base = created_at or datetime.now(timezone.utc)
    hours = SLA_HOURS.get(severity.upper(), SLA_HOURS["MEDIUM"])
    return base + timedelta(hours=hours)


def _build_ai_context(exception_type: str, extra: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Build a JSONB-compatible AI context dict.

    Merges the template recommendation with any extra data the caller
    provides (e.g. variance amounts, document IDs).
    """
    template = AI_CONTEXT_TEMPLATES.get(exception_type, "Exception requires manual review.")
    ctx: Dict[str, Any] = {
        "recommendation": template,
        "exception_type": exception_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        ctx.update(extra)
    return ctx


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a RealDictRow — coerce Decimal to float, datetimes to ISO."""
    cleaned: Dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            cleaned[k] = float(v)
        elif isinstance(v, datetime):
            cleaned[k] = v.isoformat()
        else:
            cleaned[k] = v
    return cleaned


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class ExceptionResolutionService:
    """
    Full lifecycle management for procurement exceptions (G-05).

    All public methods acquire their own connection, commit on success,
    rollback on failure, and close the connection in a finally block.
    """

    # ------------------------------------------------------------------
    # create_exception
    # ------------------------------------------------------------------
    def create_exception(self, exception_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert a new exception into exception_queue.

        Required keys in exception_data:
            exception_type : str   — one of AI_CONTEXT_TEMPLATES keys (or custom)
            description    : str   — human-readable summary

        Optional keys:
            severity             : str  — CRITICAL | HIGH | MEDIUM | LOW (default MEDIUM)
            source_document_type : str  — e.g. 'purchase_order', 'invoice'
            source_document_id   : str  — e.g. 'PO-0042'
            workflow_run_id      : str  — pipeline/workflow correlation id
            assigned_to          : str  — user email or role
            ai_context_extra     : dict — extra data merged into ai_context
        """
        exception_id = _generate_exception_id()
        exception_type = exception_data.get("exception_type", "unknown")
        severity = exception_data.get("severity", "MEDIUM").upper()
        if severity not in SLA_HOURS:
            severity = "MEDIUM"

        now = datetime.now(timezone.utc)
        sla_deadline = _calculate_sla_deadline(severity, now)
        ai_context = _build_ai_context(
            exception_type,
            exception_data.get("ai_context_extra"),
        )
        ai_recommendation = AI_CONTEXT_TEMPLATES.get(
            exception_type, "Manual review required."
        )

        assigned_to = exception_data.get("assigned_to")
        status = "assigned" if assigned_to else "open"

        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO exception_queue (
                        exception_id, exception_type, severity,
                        source_document_type, source_document_id,
                        workflow_run_id, description,
                        ai_context, ai_recommendation,
                        assigned_to, sla_deadline, sla_breached,
                        resolution_action, resolution_notes,
                        resolved_by, resolved_at,
                        status, escalation_level,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, FALSE,
                        NULL, NULL,
                        NULL, NULL,
                        %s, 0,
                        %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        exception_id,
                        exception_type,
                        severity,
                        exception_data.get("source_document_type"),
                        exception_data.get("source_document_id"),
                        exception_data.get("workflow_run_id"),
                        exception_data.get("description", ""),
                        json.dumps(ai_context),
                        ai_recommendation,
                        assigned_to,
                        sla_deadline,
                        status,
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
            conn.commit()

            logger.info(
                f"[ExceptionService] Created {exception_id} "
                f"type={exception_type} severity={severity} sla={sla_deadline.isoformat()}"
            )
            return _row_to_dict(dict(row))

        except Exception as exc:
            if conn:
                conn.rollback()
            logger.error(f"[ExceptionService] create_exception failed: {exc}")
            raise
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # assign_exception
    # ------------------------------------------------------------------
    def assign_exception(
        self, exception_id: str, assignee: str
    ) -> Dict[str, Any]:
        """
        Assign (or reassign) an exception to a user/role.

        Sets status to 'assigned' and records the assignee.
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE exception_queue
                    SET assigned_to = %s,
                        status     = CASE
                                       WHEN status IN ('open', 'assigned') THEN 'assigned'
                                       ELSE status
                                     END,
                        updated_at = NOW()
                    WHERE exception_id = %s
                    RETURNING *
                    """,
                    (assignee, exception_id),
                )
                row = cur.fetchone()
            conn.commit()

            if not row:
                logger.warning(
                    f"[ExceptionService] assign_exception: {exception_id} not found"
                )
                return {"error": f"Exception {exception_id} not found"}

            logger.info(
                f"[ExceptionService] Assigned {exception_id} -> {assignee}"
            )
            return _row_to_dict(dict(row))

        except Exception as exc:
            if conn:
                conn.rollback()
            logger.error(f"[ExceptionService] assign_exception failed: {exc}")
            raise
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # resolve_exception
    # ------------------------------------------------------------------
    def resolve_exception(
        self,
        exception_id: str,
        resolution_action: str,
        notes: str = "",
        resolved_by: str = "",
    ) -> Dict[str, Any]:
        """
        Mark an exception as resolved.

        Args:
            exception_id:       Target exception.
            resolution_action:  Action taken (e.g. 'approved_override', 'rejected',
                                'adjusted_qty', 'waived', 'credited').
            notes:              Free-text resolution notes.
            resolved_by:        Who resolved it (email or username).
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE exception_queue
                    SET status            = 'resolved',
                        resolution_action = %s,
                        resolution_notes  = %s,
                        resolved_by       = %s,
                        resolved_at       = NOW(),
                        updated_at        = NOW()
                    WHERE exception_id = %s
                      AND status NOT IN ('resolved', 'closed')
                    RETURNING *
                    """,
                    (resolution_action, notes, resolved_by, exception_id),
                )
                row = cur.fetchone()
            conn.commit()

            if not row:
                logger.warning(
                    f"[ExceptionService] resolve_exception: "
                    f"{exception_id} not found or already resolved"
                )
                return {
                    "error": (
                        f"Exception {exception_id} not found or already resolved/closed"
                    )
                }

            logger.info(
                f"[ExceptionService] Resolved {exception_id} "
                f"action={resolution_action} by={resolved_by}"
            )
            return _row_to_dict(dict(row))

        except Exception as exc:
            if conn:
                conn.rollback()
            logger.error(f"[ExceptionService] resolve_exception failed: {exc}")
            raise
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # escalate_exception
    # ------------------------------------------------------------------
    def escalate_exception(
        self, exception_id: str, reason: str
    ) -> Dict[str, Any]:
        """
        Escalate an exception: bump escalation_level, set status to
        'escalated', and reassign to the next-level handler based on
        ESCALATION_ROUTING.

        Args:
            exception_id: Target exception.
            reason:       Why the exception is being escalated.
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Fetch current state
                cur.execute(
                    """
                    SELECT exception_id, escalation_level, ai_context, severity
                    FROM exception_queue
                    WHERE exception_id = %s
                      AND status NOT IN ('resolved', 'closed')
                    """,
                    (exception_id,),
                )
                current = cur.fetchone()

                if not current:
                    logger.warning(
                        f"[ExceptionService] escalate_exception: "
                        f"{exception_id} not found or already resolved"
                    )
                    return {
                        "error": (
                            f"Exception {exception_id} not found or "
                            "already resolved/closed"
                        )
                    }

                new_level = (current["escalation_level"] or 0) + 1
                new_assignee = ESCALATION_ROUTING.get(
                    new_level, f"escalation_level_{new_level}"
                )

                # Append escalation history to ai_context
                ai_ctx = current["ai_context"] or {}
                if isinstance(ai_ctx, str):
                    ai_ctx = json.loads(ai_ctx)
                escalation_history = ai_ctx.get("escalation_history", [])
                escalation_history.append(
                    {
                        "level": new_level,
                        "reason": reason,
                        "reassigned_to": new_assignee,
                        "escalated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                ai_ctx["escalation_history"] = escalation_history

                cur.execute(
                    """
                    UPDATE exception_queue
                    SET escalation_level = %s,
                        status           = 'escalated',
                        assigned_to      = %s,
                        ai_context       = %s,
                        updated_at       = NOW()
                    WHERE exception_id = %s
                    RETURNING *
                    """,
                    (
                        new_level,
                        new_assignee,
                        json.dumps(ai_ctx),
                        exception_id,
                    ),
                )
                row = cur.fetchone()
            conn.commit()

            logger.info(
                f"[ExceptionService] Escalated {exception_id} "
                f"to level {new_level} -> {new_assignee} reason={reason}"
            )
            return _row_to_dict(dict(row))

        except Exception as exc:
            if conn:
                conn.rollback()
            logger.error(f"[ExceptionService] escalate_exception failed: {exc}")
            raise
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # check_sla_breaches
    # ------------------------------------------------------------------
    def check_sla_breaches(self) -> List[Dict[str, Any]]:
        """
        Find all open/assigned/in_progress/escalated exceptions whose
        sla_deadline has passed and mark them as sla_breached=TRUE.

        Returns the list of newly breached exceptions.
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE exception_queue
                    SET sla_breached = TRUE,
                        updated_at  = NOW()
                    WHERE sla_deadline < NOW()
                      AND sla_breached = FALSE
                      AND status NOT IN ('resolved', 'closed')
                    RETURNING *
                    """
                )
                rows = cur.fetchall()
            conn.commit()

            breached = [_row_to_dict(dict(r)) for r in rows]
            if breached:
                logger.warning(
                    f"[ExceptionService] SLA breaches detected: "
                    f"{len(breached)} exception(s)"
                )
            else:
                logger.info("[ExceptionService] SLA check: no new breaches")

            return breached

        except Exception as exc:
            if conn:
                conn.rollback()
            logger.error(f"[ExceptionService] check_sla_breaches failed: {exc}")
            raise
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # get_open_exceptions
    # ------------------------------------------------------------------
    def get_open_exceptions(
        self,
        severity: Optional[str] = None,
        assigned_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List open (non-resolved, non-closed) exceptions with optional filters.

        Args:
            severity:    Filter by severity level (CRITICAL / HIGH / MEDIUM / LOW).
            assigned_to: Filter by assignee (email or role).
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                clauses: List[str] = [
                    "status NOT IN ('resolved', 'closed')"
                ]
                params: List[Any] = []

                if severity:
                    clauses.append("severity = %s")
                    params.append(severity.upper())

                if assigned_to:
                    clauses.append("assigned_to = %s")
                    params.append(assigned_to)

                where = " AND ".join(clauses)

                cur.execute(
                    f"""
                    SELECT *
                    FROM exception_queue
                    WHERE {where}
                    ORDER BY
                        CASE severity
                            WHEN 'CRITICAL' THEN 1
                            WHEN 'HIGH'     THEN 2
                            WHEN 'MEDIUM'   THEN 3
                            WHEN 'LOW'      THEN 4
                            ELSE 5
                        END,
                        sla_deadline ASC NULLS LAST
                    """,
                    params,
                )
                rows = cur.fetchall()

            return [_row_to_dict(dict(r)) for r in rows]

        except Exception as exc:
            logger.error(f"[ExceptionService] get_open_exceptions failed: {exc}")
            raise
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # get_exception_stats
    # ------------------------------------------------------------------
    def get_exception_stats(self) -> Dict[str, Any]:
        """
        Return summary statistics about the exception queue.

        Includes:
            total_open, total_breached, by_severity, by_status,
            avg_resolution_hours, oldest_open_exception
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Total open (non-resolved/closed)
                cur.execute(
                    """
                    SELECT COUNT(*) AS total_open
                    FROM exception_queue
                    WHERE status NOT IN ('resolved', 'closed')
                    """
                )
                total_open = cur.fetchone()["total_open"]

                # Total SLA-breached (still open)
                cur.execute(
                    """
                    SELECT COUNT(*) AS total_breached
                    FROM exception_queue
                    WHERE sla_breached = TRUE
                      AND status NOT IN ('resolved', 'closed')
                    """
                )
                total_breached = cur.fetchone()["total_breached"]

                # Breakdown by severity (open only)
                cur.execute(
                    """
                    SELECT severity, COUNT(*) AS count
                    FROM exception_queue
                    WHERE status NOT IN ('resolved', 'closed')
                    GROUP BY severity
                    ORDER BY
                        CASE severity
                            WHEN 'CRITICAL' THEN 1
                            WHEN 'HIGH'     THEN 2
                            WHEN 'MEDIUM'   THEN 3
                            WHEN 'LOW'      THEN 4
                            ELSE 5
                        END
                    """
                )
                by_severity = {
                    row["severity"]: row["count"] for row in cur.fetchall()
                }

                # Breakdown by status (all)
                cur.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM exception_queue
                    GROUP BY status
                    ORDER BY count DESC
                    """
                )
                by_status = {
                    row["status"]: row["count"] for row in cur.fetchall()
                }

                # Average resolution time (resolved exceptions only)
                cur.execute(
                    """
                    SELECT
                        AVG(
                            EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600
                        ) AS avg_hours
                    FROM exception_queue
                    WHERE status IN ('resolved', 'closed')
                      AND resolved_at IS NOT NULL
                    """
                )
                avg_row = cur.fetchone()
                avg_resolution_hours = (
                    round(float(avg_row["avg_hours"]), 2)
                    if avg_row and avg_row["avg_hours"] is not None
                    else None
                )

                # Oldest open exception
                cur.execute(
                    """
                    SELECT exception_id, exception_type, severity,
                           created_at, sla_deadline, sla_breached
                    FROM exception_queue
                    WHERE status NOT IN ('resolved', 'closed')
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                )
                oldest_row = cur.fetchone()
                oldest_open = _row_to_dict(dict(oldest_row)) if oldest_row else None

                # Total resolved count
                cur.execute(
                    """
                    SELECT COUNT(*) AS total_resolved
                    FROM exception_queue
                    WHERE status IN ('resolved', 'closed')
                    """
                )
                total_resolved = cur.fetchone()["total_resolved"]

            stats = {
                "total_open": total_open,
                "total_resolved": total_resolved,
                "total_breached": total_breached,
                "by_severity": by_severity,
                "by_status": by_status,
                "avg_resolution_hours": avg_resolution_hours,
                "oldest_open_exception": oldest_open,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

            logger.info(
                f"[ExceptionService] Stats: open={total_open} "
                f"breached={total_breached} avg_resolution={avg_resolution_hours}h"
            )
            return stats

        except Exception as exc:
            logger.error(f"[ExceptionService] get_exception_stats failed: {exc}")
            raise
        finally:
            if conn:
                conn.close()


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_service_instance: Optional[ExceptionResolutionService] = None


def get_exception_service() -> ExceptionResolutionService:
    """
    Return a module-level singleton of ExceptionResolutionService.

    Usage:
        from backend.services.exception_resolution_service import get_exception_service
        svc = get_exception_service()
        svc.create_exception({...})
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = ExceptionResolutionService()
        logger.info("[ExceptionService] Singleton instance created")
    return _service_instance
