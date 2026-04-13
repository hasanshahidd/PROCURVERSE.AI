"""
Drift Reconciliation Job (P1.5 / HF-5 / R18)

Compares the authoritative session_events state (Layer 1) against the legacy
workflow_runs state (Layer 2) for every active session and records any
divergence in session_drift_reports. Read-only on both sides — never mutates
either Layer 1 or Layer 2 tables.

This job is the core measurement behind the P5 gate criterion:

    "zero unresolved drift for 14 consecutive days"

Safe to run every 15 minutes (hybrid) or daily (P5+). Idempotent: re-running
the job before a drift is resolved inserts a fresh row (the newest row is the
current state; older rows are history).

Consumers:
- backend/main.py — registers an asyncio task calling run_drift_reconciliation
  on a 15-minute interval during P1.5.
- GET /admin/drift — lists unresolved reports for operator triage.
- PATCH /admin/drift/:id — marks a report resolved with an explanatory note.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.adapters.factory import get_adapter
from backend.services.session_service import SessionService

logger = logging.getLogger(__name__)

# Statuses considered "in flight" — we only reconcile these. Terminal sessions
# (completed/failed/cancelled) are frozen and cannot drift any more.
ACTIVE_STATUSES = ("running", "paused_human")

# Phase groups map legacy workflow_runs.status values to the session phases
# they roughly correspond to. Used for coarse cross-layer comparison.
# The legacy engine has fewer states than the session state machine, so this
# mapping deliberately coarse — we're flagging major divergence, not every
# sub-phase difference.
LEGACY_TO_SESSION_GROUP = {
    "running":   {"compliance", "budget", "vendor", "vendor_selection",
                  "pr_creation", "approval", "approval_wait",
                  "po_creation", "delivery_tracking", "grn", "grn_wait",
                  "quality_inspection", "invoice_matching", "three_way_match",
                  "payment_readiness", "payment_execution"},
    "completed": {"completed"},
    "failed":    {"failed"},
    "cancelled": {"cancelled"},
    "paused":    {"paused_human", "vendor_selection", "approval_wait", "grn_wait"},
}


def _fold_session_state(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produce the minimal canonical view of a session for cross-layer compare.
    Only fields that matter for drift detection — phase, status, open gate
    type, event count. Business references (po_number, pr_number, etc.) are
    intentionally excluded; drift is about workflow position, not payload.
    """
    open_gates = session.get("open_gates") or []
    open_gate_types = sorted([g.get("gate_type") for g in open_gates if g.get("gate_type")])
    return {
        "session_id": session.get("session_id"),
        "current_phase": session.get("current_phase"),
        "current_status": session.get("current_status"),
        "open_gate_types": open_gate_types,
        "last_event_sequence": session.get("last_event_sequence"),
        "workflow_run_id": session.get("workflow_run_id"),
    }


def _fold_legacy_state(workflow_run_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the legacy workflow_runs row and reduce it to the canonical compare
    shape. Returns None if the workflow_run row does not exist.
    """
    try:
        from backend.services.workflow_engine import get_workflow_status
        wf_result = get_workflow_status(workflow_run_id)
    except Exception as exc:
        logger.warning("drift: legacy get_workflow_status failed for %s: %s",
                       workflow_run_id, exc)
        return None

    if not wf_result or not wf_result.get("success"):
        return None

    wf = wf_result.get("workflow") or {}
    return {
        "workflow_run_id": workflow_run_id,
        "status": wf.get("status"),
        "total_tasks": wf.get("total_tasks"),
        "completed_tasks": wf.get("completed_tasks"),
        "failed_tasks": wf.get("failed_tasks"),
        "pr_number": wf.get("pr_number"),
        "po_number": wf.get("po_number"),
    }


def _states_differ(session_state: Dict[str, Any],
                   legacy_state: Dict[str, Any]) -> bool:
    """
    Return True if the session and legacy views disagree about workflow state.

    Rules (intentionally coarse to avoid noise during hybrid mode):
      1. If legacy status is 'completed' but session phase is not terminal →
         drift. The legacy engine thinks we're done; we don't.
      2. If legacy status is 'failed' but session status is still 'running' or
         'paused_human' → drift. Legacy says broken; session says fine.
      3. If session phase is 'completed' but legacy status is 'running' →
         drift. Session says done; legacy still working.
      4. If both agree on "roughly running" or "roughly paused", no drift.
    """
    legacy_status = (legacy_state or {}).get("status")
    session_phase = (session_state or {}).get("current_phase")
    session_status = (session_state or {}).get("current_status")

    if not legacy_status:
        # No legacy row at all — treat as drift only if session claims there
        # should be one (workflow_run_id is set). The caller already skips
        # sessions without workflow_run_id so reaching here means missing row.
        return True

    # Rule 1: legacy finished, session still running
    if legacy_status == "completed" and session_phase not in (
        "completed", "failed", "cancelled"
    ):
        return True

    # Rule 2: legacy failed, session still progressing
    if legacy_status == "failed" and session_status in ("running", "paused_human"):
        return True

    # Rule 3: session finished, legacy still running
    if session_phase == "completed" and legacy_status == "running":
        return True

    # Rule 4: coarse group match — treat as agreement
    allowed_phases = LEGACY_TO_SESSION_GROUP.get(legacy_status)
    if allowed_phases is None:
        # Unknown legacy status — log but don't flag as drift
        logger.debug("drift: unknown legacy status %s, skipping", legacy_status)
        return False

    return session_phase not in allowed_phases


def _insert_drift_report(
    adapter,
    session_id: str,
    session_state: Dict[str, Any],
    legacy_state: Dict[str, Any],
) -> bool:
    """
    INSERT a new row into session_drift_reports. Uses a direct adapter connection
    so we don't pull in SessionService (which is write-locked to Layer 1 only).
    Returns True on success.
    """
    try:
        from backend.services.nmi_data_service import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO session_drift_reports
                        (session_id, session_state, legacy_state)
                    VALUES (%s, %s::jsonb, %s::jsonb)
                    """,
                    (session_id, json.dumps(session_state), json.dumps(legacy_state)),
                )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as exc:
        logger.error("drift: insert_drift_report failed for %s: %s", session_id, exc)
        return False


def _session_already_has_unresolved_report(
    session_id: str,
    session_state: Dict[str, Any],
    legacy_state: Dict[str, Any],
) -> bool:
    """
    Suppress duplicate drift reports: if the session already has an unresolved
    report with identical session_state + legacy_state, we don't insert a new
    one. This keeps the admin dashboard readable across hundreds of 15-minute
    runs of the job.
    """
    try:
        from backend.services.nmi_data_service import get_conn
        from psycopg2.extras import RealDictCursor
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT session_state, legacy_state
                    FROM session_drift_reports
                    WHERE session_id = %s AND resolution IS NULL
                    ORDER BY detected_at DESC
                    LIMIT 1
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                prior_session = row.get("session_state") or {}
                prior_legacy = row.get("legacy_state") or {}
                # Compare only the fields that matter for drift identity
                return (
                    prior_session.get("current_phase") == session_state.get("current_phase")
                    and prior_session.get("current_status") == session_state.get("current_status")
                    and prior_legacy.get("status") == legacy_state.get("status")
                )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("drift: dedupe check failed for %s: %s", session_id, exc)
        return False


async def run_drift_reconciliation() -> Dict[str, Any]:
    """
    Idempotent entry point — safe to run every 15 minutes.

    Returns:
        {
            "checked": int,           # sessions inspected
            "drift_count": int,       # drift observed this run
            "new_reports": int,       # reports inserted (after dedupe)
            "skipped_no_workflow": int,
            "errors": int,
            "finished_at": str (iso8601 utc),
        }
    """
    started = datetime.now(timezone.utc)
    adapter = get_adapter()

    summary = {
        "checked": 0,
        "drift_count": 0,
        "new_reports": 0,
        "skipped_no_workflow": 0,
        "errors": 0,
        "finished_at": None,
    }

    # Collect active sessions across both "in flight" statuses. The adapter's
    # list method takes a single status string, so we call it once per status.
    active_sessions: List[Dict[str, Any]] = []
    for status in ACTIVE_STATUSES:
        try:
            rows = SessionService.list(status=status, limit=500)
            active_sessions.extend(rows)
        except Exception as exc:
            logger.error("drift: list sessions failed for status=%s: %s", status, exc)
            summary["errors"] += 1

    logger.info("drift: reconciliation starting, %d active sessions", len(active_sessions))

    for sess_row in active_sessions:
        session_id = sess_row.get("session_id")
        workflow_run_id = sess_row.get("workflow_run_id")

        # Skip sessions with no legacy twin — nothing to compare against
        if not workflow_run_id:
            summary["skipped_no_workflow"] += 1
            continue

        summary["checked"] += 1

        try:
            # Re-fetch with open_gates so the fold sees the latest gate state
            full_session = SessionService.get(session_id)
        except Exception as exc:
            logger.warning("drift: SessionService.get failed for %s: %s", session_id, exc)
            summary["errors"] += 1
            continue

        session_state = _fold_session_state(full_session)
        legacy_state = _fold_legacy_state(workflow_run_id)

        if legacy_state is None:
            # Missing legacy row — record as drift (session claims a twin that doesn't exist)
            legacy_state = {"status": None, "workflow_run_id": workflow_run_id,
                            "reason": "legacy_workflow_not_found"}
            drift = True
        else:
            drift = _states_differ(session_state, legacy_state)

        if not drift:
            continue

        summary["drift_count"] += 1

        # Dedupe before insert
        if _session_already_has_unresolved_report(session_id, session_state, legacy_state):
            logger.debug("drift: duplicate suppressed for session=%s", session_id)
            continue

        if _insert_drift_report(adapter, session_id, session_state, legacy_state):
            summary["new_reports"] += 1
            logger.warning(
                "drift: NEW REPORT session=%s session_phase=%s legacy_status=%s",
                session_id, session_state.get("current_phase"), legacy_state.get("status"),
            )

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    logger.info(
        "drift: reconciliation done in %dms — checked=%d drift=%d new=%d skipped=%d errors=%d",
        duration_ms,
        summary["checked"],
        summary["drift_count"],
        summary["new_reports"],
        summary["skipped_no_workflow"],
        summary["errors"],
    )
    return summary


async def drift_reconciliation_loop(interval_seconds: int = 900) -> None:
    """
    Long-running loop that calls run_drift_reconciliation on a fixed interval.
    Default 900s (15 minutes) matches the P1.5 plan target.

    Exceptions from a single run are logged and swallowed — the loop continues.
    Cancel via asyncio.Task.cancel() during shutdown.
    """
    logger.info("drift: reconciliation loop starting, interval=%ds", interval_seconds)
    while True:
        try:
            await run_drift_reconciliation()
        except asyncio.CancelledError:
            logger.info("drift: reconciliation loop cancelled, exiting")
            raise
        except Exception as exc:
            logger.exception("drift: reconciliation run failed, will retry: %s", exc)
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("drift: reconciliation loop cancelled during sleep, exiting")
            raise


if __name__ == "__main__":
    # Manual smoke test: python -m backend.jobs.drift_reconciliation
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = asyncio.run(run_drift_reconciliation())
    print(json.dumps(result, indent=2, default=str))
