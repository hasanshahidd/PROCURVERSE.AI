"""
SessionService — single-writer primitive for Layer 1 (execution sessions).

This module is the ONLY place in the codebase that is allowed to INSERT or
UPDATE any of the session orchestration tables:

    execution_sessions
    session_events
    session_gates
    session_snapshots

Call sites:
- backend/routes/agentic.py::execute_agentic_request_stream   → SessionService.create(caller="query_router")
- backend/routes/agentic.py::/api/agentic/p2p/resume          → SessionService.create(caller="legacy_proxy") [migration-only]
- backend/agents/orchestrator.py::_execute_full_p2p           → SessionService.append_event / open_gate / set_phase
- backend/agents/orchestrator.py::_resume_p2p_workflow        → SessionService.resolve_gate / append_event
- backend/routes/sessions.py                                  → read-only gets, list, SSE replay

Hard rules enforced here (see plan R1-R20):
- R3:  set_phase() validates against ALLOWED_TRANSITIONS. Illegal jumps raise
       IllegalTransitionError.
- R4:  create() computes a request_fingerprint and returns the existing
       session_id on duplicate submissions (idempotency).
- R9:  create() accepts only an allowlisted set of caller tokens.
- R13: resolve_gate() requires a gate_resolution_id; duplicate submissions
       return the prior decision without re-applying.
- R14: append_event() / set_phase() are pure low-level primitives — they
       never decide "what runs next". That is the orchestrator's job.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants — state machine, access control, session kinds
# ─────────────────────────────────────────────────────────────────────────────

# R9: Only these callers may invoke create(). Any other value raises.
ALLOWED_CALLERS: frozenset = frozenset({
    "query_router",   # backend/routes/agentic.py::execute_agentic_request_stream
    "legacy_proxy",   # backend/routes/agentic.py::/api/agentic/p2p/resume (migration only)
    "admin",          # admin tooling / ops scripts
    "test",           # unit tests (allowed in all environments; tests never touch prod DB)
})

# R3: Allowed phase transitions. Terminal states (completed/failed/cancelled)
# have no outgoing edges. Any attempt to move outside this map raises
# IllegalTransitionError.
ALLOWED_TRANSITIONS: Dict[str, frozenset] = {
    "starting":           frozenset({"compliance", "failed", "cancelled"}),
    "compliance":         frozenset({"budget", "failed", "cancelled"}),
    "budget":             frozenset({"vendor", "failed", "cancelled"}),
    "vendor":             frozenset({"vendor_selection", "failed", "cancelled"}),
    "vendor_selection":   frozenset({"pr_creation", "failed", "cancelled"}),
    "pr_creation":        frozenset({"approval", "failed", "cancelled"}),
    "approval":           frozenset({"approval_wait", "failed", "cancelled"}),
    "approval_wait":      frozenset({"po_creation", "failed", "cancelled"}),
    "po_creation":        frozenset({"delivery_tracking", "failed", "cancelled"}),
    "delivery_tracking":  frozenset({"grn", "failed", "cancelled"}),
    "grn":                frozenset({"grn_wait", "failed", "cancelled"}),
    "grn_wait":           frozenset({"quality_inspection", "failed", "cancelled"}),
    "quality_inspection": frozenset({"invoice_matching", "failed", "cancelled"}),
    "invoice_matching":   frozenset({"three_way_match", "failed", "cancelled"}),
    "three_way_match":    frozenset({"payment_readiness", "failed", "cancelled"}),
    "payment_readiness":  frozenset({"payment_execution", "failed", "cancelled"}),
    "payment_execution":  frozenset({"completed", "failed", "cancelled"}),
    # Terminal states
    "completed":          frozenset(),
    "failed":             frozenset(),
    "cancelled":          frozenset(),
}

# R4: the time bucket used when computing request_fingerprint.
# Requests within this window that share (user_id, canonicalized_summary)
# collapse to the same session (prevents double-click / network retry).
# Kept short so legitimate back-to-back P2P runs get their own sessions.
FINGERPRINT_BUCKET_SECONDS: int = 5  # 5 seconds (double-click guard only)

# Supported session kinds. P0 only supports p2p_full; extend here as new
# session-driven flows are added.
SESSION_KIND_P2P_FULL = "p2p_full"
SUPPORTED_KINDS: frozenset = frozenset({SESSION_KIND_P2P_FULL})


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class SessionServiceError(Exception):
    """Base class for all SessionService errors."""


class UnauthorizedSessionCreation(SessionServiceError):
    """Raised when create() is called with a caller not in ALLOWED_CALLERS."""


class IllegalTransitionError(SessionServiceError):
    """Raised when set_phase() attempts a transition not in ALLOWED_TRANSITIONS."""


class SessionNotFoundError(SessionServiceError):
    """Raised when a lookup by session_id finds no row."""


class GateNotFoundError(SessionServiceError):
    """Raised when a lookup or update by gate_id finds no row."""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _canonicalize(obj: Any) -> str:
    """
    Produce a stable string representation of an object for fingerprinting.
    Dicts are sorted by key so that logically-equal requests with different
    key orderings collapse to the same fingerprint.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_request_fingerprint(user_id: str, request_summary: Dict[str, Any],
                                timestamp: Optional[float] = None) -> str:
    """
    Compute the idempotency key for a session create request (R4).

    fingerprint = sha256( user_id || canonicalized_summary || time_bucket )

    Two calls to create() with the same user_id and logically-identical
    request_summary within the same FINGERPRINT_BUCKET_SECONDS window produce
    the same fingerprint and therefore collapse to the same session_id.
    """
    ts = timestamp if timestamp is not None else time.time()
    bucket = int(ts // FINGERPRINT_BUCKET_SECONDS)
    raw = f"{user_id}||{_canonicalize(request_summary)}||{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso(val: Any) -> Any:
    """Convert datetime/UUID values to JSON-friendly forms (recursive for dict/list)."""
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).isoformat() if val.tzinfo else val.isoformat()
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, dict):
        return {k: _iso(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_iso(v) for v in val]
    return val


def _normalize_session(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DB row fields into JSON-safe primitives."""
    if not row:
        return {}
    return {k: _iso(v) for k, v in row.items()}


# ─────────────────────────────────────────────────────────────────────────────
# SessionService — the single-writer primitive
# ─────────────────────────────────────────────────────────────────────────────

class SessionService:
    """
    Single-writer primitive for Layer 1 tables.

    All methods are classmethods because the service is stateless — it holds
    no in-process cache and opens a fresh DB connection per call via the
    adapter layer. This means multiple orchestrator workers can safely call
    into it from any thread or asyncio event loop without coordination.

    The design is deliberately thin:
      - each public method performs exactly one bounded DB operation
      - no business logic lives here (that belongs in the orchestrator)
      - exceptions are always raised — callers decide whether to swallow them
        (e.g. hybrid-mode emit() in orchestrator) or propagate (session mode).
    """

    # ── create ────────────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        kind: str,
        user_id: str,
        request_summary: Dict[str, Any],
        caller: str,
        workflow_run_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Create (or idempotently re-fetch) an execution session.

        Returns a dict with keys {session_id, created, session}.
          - created=True  → a new row was inserted
          - created=False → an existing row matched the request_fingerprint
            (double-click, retry, duplicate POST) and is being returned as-is

        Raises:
          UnauthorizedSessionCreation — caller not in ALLOWED_CALLERS (R9)
          ValueError                 — unknown session kind
          SessionServiceError        — underlying DB failure
        """
        if caller not in ALLOWED_CALLERS:
            raise UnauthorizedSessionCreation(
                f"SessionService.create() refused: caller={caller!r} not in ALLOWED_CALLERS"
            )
        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"Unsupported session kind: {kind!r}")
        if not user_id:
            raise ValueError("user_id is required for session creation")

        fingerprint = compute_request_fingerprint(
            user_id=user_id,
            request_summary=request_summary or {},
            timestamp=timestamp,
        )

        adapter = get_adapter()
        result = adapter.insert_execution_session({
            "session_kind": kind,
            "initiated_by_user_id": user_id,
            "request_fingerprint": fingerprint,
            "request_summary": request_summary or {},
            "workflow_run_id": workflow_run_id,
        })
        if not result.get("success"):
            raise SessionServiceError(
                f"Failed to create session: {result.get('error')}"
            )

        session_row = result.get("session") or {}
        session_id = str(session_row.get("session_id")) if session_row.get("session_id") else None
        created = bool(result.get("created"))

        logger.info(
            "[SessionService.create] caller=%s kind=%s user=%s session_id=%s created=%s",
            caller, kind, user_id, session_id, created,
        )

        return {
            "session_id": session_id,
            "created": created,
            "session": _normalize_session(session_row),
        }

    # ── read ──────────────────────────────────────────────────────────────

    @classmethod
    def get(cls, session_id: str) -> Dict[str, Any]:
        """
        Return the session row plus its open gates (status='pending').
        Raises SessionNotFoundError if the session does not exist.
        """
        adapter = get_adapter()
        row = adapter.get_execution_session(session_id)
        if not row:
            raise SessionNotFoundError(f"Session {session_id} not found")

        gates = adapter.list_session_gates(session_id=session_id, status="pending")
        return {
            **_normalize_session(row),
            "open_gates": [_normalize_session(g) for g in gates],
        }

    @classmethod
    def list(
        cls,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return filtered sessions ordered by created_at DESC."""
        adapter = get_adapter()
        rows = adapter.list_execution_sessions(
            user_id=user_id, status=status, kind=kind, limit=limit
        )
        return [_normalize_session(r) for r in rows]

    @classmethod
    def list_pending_gates(cls, gate_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all gates currently in status='pending', optionally filtered by type."""
        adapter = get_adapter()
        rows = adapter.list_session_gates(status="pending", gate_type=gate_type)
        return [_normalize_session(r) for r in rows]

    @classmethod
    def find_by_workflow_run(cls, workflow_run_id: str) -> Optional[Dict[str, Any]]:
        """
        Look up the session row attached to a workflow_run_id. Returns None
        if no session is attached. Used by the legacy p2p/resume proxy during
        the hybrid migration to translate workflow_run_id → session_id.
        """
        if not workflow_run_id:
            return None
        adapter = get_adapter()
        row = adapter.get_execution_session_by_workflow_run_id(workflow_run_id)
        if not row:
            return None
        gates = adapter.list_session_gates(session_id=row["session_id"], status="pending")
        return {
            **_normalize_session(row),
            "open_gates": [_normalize_session(g) for g in gates],
        }

    @classmethod
    def attach_workflow_run_id(cls, session_id: str, workflow_run_id: str) -> None:
        """
        Attach a workflow_run_id to an existing session. Called once from the
        orchestrator right after the underlying workflow_run is created.
        Hybrid-mode callers should wrap in try/except — a failure here must
        not break the pipeline.
        """
        if not session_id or not workflow_run_id:
            return
        adapter = get_adapter()
        result = adapter.update_execution_session_workflow_run_id(
            session_id=session_id, workflow_run_id=workflow_run_id
        )
        if not result.get("success"):
            raise SessionServiceError(
                f"attach_workflow_run_id failed: {result.get('error')}"
            )

    # ── append_event ──────────────────────────────────────────────────────

    @classmethod
    def append_event(
        cls,
        session_id: str,
        event_type: str,
        actor: str,
        payload: Optional[Dict[str, Any]] = None,
        caused_by_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Append an event to session_events under a single DB transaction that
        also bumps execution_sessions.last_event_sequence. Returns a dict with
        {event_id, sequence_number, created_at}.

        Raises SessionServiceError on DB failure. Callers in hybrid mode (the
        orchestrator during P1-P4) may catch-and-log; callers in session mode
        (P5+) must let the error propagate.
        """
        if not event_type:
            raise ValueError("event_type is required")
        if not actor:
            raise ValueError("actor is required")

        adapter = get_adapter()
        result = adapter.append_session_event(
            session_id=session_id,
            event_type=event_type,
            actor=actor,
            payload=payload or {},
            caused_by_event_id=caused_by_event_id,
        )
        if not result.get("success"):
            raise SessionServiceError(
                f"append_session_event failed: {result.get('error')}"
            )

        logger.debug(
            "[SessionService.append_event] session=%s type=%s actor=%s seq=%s",
            session_id, event_type, actor, result.get("sequence_number"),
        )
        return {
            "event_id": result.get("event_id"),
            "sequence_number": result.get("sequence_number"),
            "created_at": result.get("created_at"),
        }

    # ── append_event_tx (HF-2 / R12 transactional outbox) ──────────────────

    @classmethod
    def append_event_tx(
        cls,
        conn,
        session_id: str,
        event_type: str,
        actor: str,
        payload: Optional[Dict[str, Any]] = None,
        caused_by_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transactional variant of append_event — writes to session_event_outbox
        using the caller's connection. Does NOT commit, does NOT open a new
        connection, does NOT fire pg_notify directly. Publication is handled
        by the outbox pump (see backend/jobs/outbox_pump.py).

        Use this variant whenever a session event must commit atomically with
        an ERP write (R12). Typical usage inside an async handler:

            async with adapter.transaction() as conn:
                adapter.create_purchase_order_from_pr_tx(conn, po_data)
                SessionService.append_event_tx(
                    conn, session_id,
                    event_type="phase_completed",
                    actor="orchestrator",
                    payload={"phase": "po_creation", "ref": {"po_number": ...}},
                )
            # Commit happens at the end of the `async with` block. If either
            # the ERP write or the outbox insert raises, both roll back.

        Returns {outbox_id, sequence_number, created_at} on success.
        Raises SessionServiceError on failure — caller's transaction will
        roll back naturally when the exception propagates out.
        """
        if not event_type:
            raise ValueError("event_type is required")
        if not actor:
            raise ValueError("actor is required")
        if conn is None:
            raise ValueError("conn is required for append_event_tx")

        adapter = get_adapter()
        result = adapter.append_session_event_outbox_tx(
            conn=conn,
            session_id=session_id,
            event_type=event_type,
            actor=actor,
            payload=payload or {},
            caused_by_event_id=caused_by_event_id,
        )
        if not result.get("success"):
            raise SessionServiceError(
                f"append_session_event_outbox_tx failed: {result.get('error')}"
            )

        logger.debug(
            "[SessionService.append_event_tx] session=%s type=%s actor=%s seq=%s",
            session_id, event_type, actor, result.get("sequence_number"),
        )
        return {
            "outbox_id": result.get("outbox_id"),
            "sequence_number": result.get("sequence_number"),
            "created_at": result.get("created_at"),
        }

    @classmethod
    def list_events(
        cls,
        session_id: str,
        since_sequence: int = 0,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Return session_events ordered by sequence_number ASC (after `since_sequence`)."""
        adapter = get_adapter()
        rows = adapter.list_session_events(
            session_id=session_id,
            since_sequence=since_sequence,
            limit=limit,
        )
        return [_normalize_session(r) for r in rows]

    # ── gates ─────────────────────────────────────────────────────────────

    @classmethod
    def open_gate(
        cls,
        session_id: str,
        gate_type: str,
        gate_ref: Dict[str, Any],
        decision_context: Optional[Dict[str, Any]] = None,
        required_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Open a human gate. Writes a session_gates row only — the caller
        (orchestrator) is responsible for emitting a 'gate_opened' event and
        transitioning the session status to 'paused_human' via set_phase().

        decision_context is the auditable snapshot of why this gate exists
        (scoring, rejected options, policy version). It is written once and
        never updated.
        """
        if not gate_type:
            raise ValueError("gate_type is required")

        adapter = get_adapter()
        result = adapter.insert_session_gate({
            "session_id": session_id,
            "gate_type": gate_type,
            "gate_ref": gate_ref or {},
            "decision_context": decision_context or {},
            "required_role": required_role,
        })
        if not result.get("success"):
            raise SessionServiceError(
                f"insert_session_gate failed: {result.get('error')}"
            )
        gate = result.get("gate") or {}
        logger.info(
            "[SessionService.open_gate] session=%s type=%s gate_id=%s",
            session_id, gate_type, gate.get("gate_id"),
        )
        return _normalize_session(gate)

    @classmethod
    def get_gate(cls, gate_id: str) -> Dict[str, Any]:
        """Return a single gate row. Raises GateNotFoundError if missing."""
        adapter = get_adapter()
        row = adapter.get_session_gate(gate_id)
        if not row:
            raise GateNotFoundError(f"Gate {gate_id} not found")
        return _normalize_session(row)

    @classmethod
    def resolve_gate(
        cls,
        gate_id: str,
        decision: Dict[str, Any],
        resolved_by: str,
        gate_resolution_id: str,
    ) -> Dict[str, Any]:
        """
        Resolve a gate idempotently (R13).

        gate_resolution_id is a client-generated UUID that deduplicates
        retried resume submissions. A duplicate submission with the same
        gate_resolution_id returns the prior decision without re-applying.

        Returns a dict with keys {gate, idempotent_replay}.
        """
        if not gate_resolution_id:
            raise ValueError("gate_resolution_id is required (R13 idempotency)")
        if not resolved_by:
            raise ValueError("resolved_by is required")

        adapter = get_adapter()
        result = adapter.resolve_session_gate(
            gate_id=gate_id,
            decision=decision or {},
            resolved_by=resolved_by,
            gate_resolution_id=gate_resolution_id,
        )
        if not result.get("success"):
            err = result.get("error", "unknown")
            if err == "gate_not_found_or_already_resolved":
                raise GateNotFoundError(
                    f"Gate {gate_id} not found or already resolved with a different resolution_id"
                )
            raise SessionServiceError(f"resolve_session_gate failed: {err}")
        gate = result.get("gate") or {}
        logger.info(
            "[SessionService.resolve_gate] gate_id=%s resolved_by=%s idempotent_replay=%s",
            gate_id, resolved_by, result.get("idempotent_replay"),
        )
        return {
            "gate": _normalize_session(gate),
            "idempotent_replay": bool(result.get("idempotent_replay")),
        }

    # ── set_phase ─────────────────────────────────────────────────────────

    @classmethod
    def set_phase(
        cls,
        session_id: str,
        new_phase: str,
        new_status: str,
    ) -> Dict[str, Any]:
        """
        Transition the session's current_phase / current_status.

        Enforces the R3 ALLOWED_TRANSITIONS map: if new_phase is not an
        allowed successor of the current phase, raises IllegalTransitionError.

        Uses optimistic concurrency on the version column: if the row has been
        updated between our read and our write, retries up to 3 times. After
        that, raises SessionServiceError.
        """
        adapter = get_adapter()

        for attempt in range(3):
            current = adapter.get_execution_session(session_id)
            if not current:
                raise SessionNotFoundError(f"Session {session_id} not found")

            current_phase = current.get("current_phase")
            expected_version = current.get("version")

            allowed = ALLOWED_TRANSITIONS.get(current_phase, frozenset())
            if new_phase != current_phase and new_phase not in allowed:
                raise IllegalTransitionError(
                    f"Illegal transition {current_phase!r} -> {new_phase!r}. "
                    f"Allowed from {current_phase!r}: {sorted(allowed)}"
                )

            result = adapter.update_execution_session_phase(
                session_id=session_id,
                new_phase=new_phase,
                new_status=new_status,
                expected_version=expected_version,
            )
            if result.get("success"):
                logger.info(
                    "[SessionService.set_phase] session=%s %s -> %s (status=%s)",
                    session_id, current_phase, new_phase, new_status,
                )
                return _normalize_session(result.get("session") or {})

            if result.get("error") == "version_conflict_or_not_found":
                # Retry on optimistic-concurrency conflict
                continue
            raise SessionServiceError(f"set_phase failed: {result.get('error')}")

        raise SessionServiceError(
            f"set_phase: version conflict on session {session_id} after 3 retries"
        )

    # ── HF-4 / R8 / R19 snapshot primitives ──────────────────────────────

    @classmethod
    def write_snapshot_tx(
        cls,
        conn,
        session_id: str,
        at_sequence_number: int,
    ) -> Dict[str, Any]:
        """
        Write a session_snapshots row inside the caller's transaction (R19).

        This is the transactional variant used by the event-write path and
        the outbox pump. The snapshot is written alongside its triggering
        event so a crash between the two is impossible. ON CONFLICT makes
        duplicate calls for the same (session_id, sequence_number)
        idempotent.

        Returns {success, snapshot_id, content_hash, duplicate}.
        Caller is responsible for wrapping the call in a SAVEPOINT if a
        snapshot failure should not abort the parent transaction — events
        are authoritative, snapshots are derived.
        """
        if conn is None:
            raise ValueError("conn is required for write_snapshot_tx")
        adapter = get_adapter()
        return adapter.write_session_snapshot_tx(
            conn=conn,
            session_id=session_id,
            at_sequence_number=int(at_sequence_number),
        )

    @classmethod
    def get_latest_snapshot(
        cls,
        session_id: str,
        at_or_before_seq: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Return the latest snapshot for a session, optionally bounded by seq.
        Used by the SSE replay endpoint to skip replay of events 0..N when
        a snapshot exists at N. Returns {} if no snapshot is available.
        """
        adapter = get_adapter()
        row = adapter.get_latest_snapshot(
            session_id=session_id,
            at_or_before_seq=at_or_before_seq,
        )
        return _normalize_session(row) if row else {}

    @classmethod
    def verify_snapshot_hash(
        cls,
        session_id: str,
        at_sequence_number: int,
        expected_hash: str,
    ) -> bool:
        """R19: recompute hash from events and compare to stored hash."""
        if not expected_hash:
            return False
        adapter = get_adapter()
        return bool(adapter.verify_snapshot_hash(
            session_id=session_id,
            at_sequence_number=int(at_sequence_number),
            expected_hash=expected_hash,
        ))
