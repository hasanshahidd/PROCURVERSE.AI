"""
Sessions Routes — Layer 1 Execution Session Orchestration API

Six endpoints, thin wrappers around SessionService. No business logic here.

  GET  /api/sessions                     — list user's sessions (filtered)
  GET  /api/sessions/{session_id}        — master row + open gates
  GET  /api/sessions/{session_id}/events — SSE: replay + live (LISTEN/NOTIFY)
  POST /api/sessions/{session_id}/resume — resolve a gate (R13 idempotent)
  POST /api/sessions/{session_id}/cancel — cancel mid-run
  GET  /api/sessions/gates/pending       — pending gates for sidebar badges

The SSE endpoint is the backbone of the session-driven frontend (Layer 3).
It streams events directly from session_events (DB = sole source of truth)
by replaying past events and then subscribing to pg_notify on the channel
"session_<session_id>". If LISTEN/NOTIFY is unavailable, it falls back to
polling the DB every 500ms.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.services.rbac import require_auth
from backend.services.session_service import (
    GateNotFoundError,
    IllegalTransitionError,
    SessionNotFoundError,
    SessionService,
    SessionServiceError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class ResumeRequest(BaseModel):
    """
    Body for POST /api/sessions/{session_id}/resume.

    gate_resolution_id is required (R13): the client must generate a stable
    UUID per user action. Retrying the same click with the same
    gate_resolution_id is safe — the server returns the prior decision
    without re-applying.
    """
    gate_id: str = Field(..., description="The session_gates.gate_id being resolved")
    gate_resolution_id: str = Field(..., description="Client-generated UUID for idempotency (R13)")
    action: str = Field(..., description="The decision action, e.g. 'approve', 'reject', 'confirm_received'")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Action-specific data")


class CancelRequest(BaseModel):
    reason: str = Field("user_cancelled", description="Reason for cancellation")


class AdvanceToGrnRequest(BaseModel):
    """
    Body for POST /api/sessions/{session_id}/advance-to-grn (HF-1).

    Called by GoodsReceiptPage when the user clicks "Confirm goods arrived".
    This is the ONLY place where phase_completed(delivery_tracking) is emitted
    and the grn gate is opened — preventing the pre-HF-1 <1ms compression bug.

    advance_request_id is required for R13-style idempotency: repeated clicks
    with the same id return the existing gate_id rather than opening a second.
    """
    advance_request_id: str = Field(..., description="Client-generated UUID for idempotency")
    po_number: Optional[str] = Field(None, description="PO number on the delivery (for the event payload)")
    pr_number: Optional[str] = Field(None, description="PR number that produced this PO")
    vendor_name: Optional[str] = Field(None, description="Vendor name for display")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _user_id_of(current_user: Dict[str, Any]) -> str:
    """Extract a stable user identifier from the auth dict."""
    return (
        current_user.get("sub")
        or current_user.get("email")
        or current_user.get("name")
        or "anonymous"
    )


def _sse_format(event_name: str, data: Dict[str, Any]) -> str:
    """Format a dict as an SSE event frame."""
    payload = json.dumps(data, default=str)
    return f"event: {event_name}\ndata: {payload}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# HF-6 — Background resume wrapper
# ─────────────────────────────────────────────────────────────────────────────

async def _run_orchestrator_resume(resume_context: Dict[str, Any]) -> None:
    """
    HF-6 background wrapper around orchestrator._resume_p2p_workflow.

    Runs AFTER the /resume HTTP response is sent so the user's click
    feels instant. Delegates ALL work to the orchestrator, which in
    turn drives the 24 specialized agents (observe → decide → act →
    learn) via self.specialized_agents. This wrapper does NOT decide
    phase ordering, NOT touch pr_data, NOT call agents directly.

    Events emitted by the orchestrator flow through
    SessionService.append_event → session_events → LISTEN/NOTIFY → SSE,
    so the frontend sees phase_started / phase_completed / gate_opened
    live in the reducer.

    Exception safety only: if the orchestrator raises, emit a
    session_failed event so the UI doesn't silently hang waiting for
    the next gate that will never open.
    """
    session_id = resume_context.get("session_id")
    action = resume_context.get("action")
    sid_short = (session_id or "?")[:8] if session_id else "?"
    try:
        logger.info("[bg-resume] session=%s START action=%s", sid_short, action)
        # Import here to avoid circular imports at module load time
        from backend.agents.orchestrator import initialize_orchestrator_with_agents
        orch = initialize_orchestrator_with_agents()
        result = await orch._resume_p2p_workflow(resume_context)
        logger.info(
            "[bg-resume] session=%s DONE status=%s",
            sid_short,
            (result or {}).get("status") if isinstance(result, dict) else "?",
        )
    except Exception as exc:
        logger.exception(
            "[bg-resume] session=%s FAILED action=%s err=%s",
            sid_short, action, exc,
        )
        # Best-effort: emit session_failed so the UI shows a terminal
        # error state instead of hanging indefinitely. If even this
        # fails, we've already logged the exception stack trace above.
        try:
            SessionService.append_event(
                session_id=session_id,
                event_type="session_failed",
                actor="orchestrator",
                payload={
                    "error": str(exc),
                    "phase": "resume",
                    "action": action,
                },
            )
        except Exception as _emit_exc:
            logger.warning(
                "[bg-resume] session=%s failed to emit session_failed: %s",
                sid_short, _emit_exc,
            )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sessions
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def list_sessions(
    status: Optional[str] = Query(None, description="Filter by current_status"),
    kind: Optional[str] = Query(None, description="Filter by session_kind"),
    gate: Optional[str] = Query(None, description="Filter by open gate_type (returns sessions with a pending gate of this type)"),
    limit: int = Query(50, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """List sessions for the current user, with optional filters."""
    user_id = _user_id_of(current_user)

    if gate:
        # "sessions with an open gate of type X" — project via the gates list
        gates = SessionService.list_pending_gates(gate_type=gate)
        session_ids = list({g.get("session_id") for g in gates if g.get("session_id")})
        sessions: List[Dict[str, Any]] = []
        for sid in session_ids:
            try:
                sessions.append(SessionService.get(sid))
            except SessionNotFoundError:
                continue
        # Return all sessions (admin-visible); the frontend filters by current user if needed.
        return {"sessions": sessions, "total": len(sessions)}

    rows = SessionService.list(user_id=user_id, status=status, kind=kind, limit=limit)
    return {"sessions": rows, "total": len(rows)}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sessions/gates/pending
# (defined BEFORE /{session_id} so path matching doesn't misroute "gates")
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/gates/pending")
async def list_pending_gates(
    gate_type: Optional[str] = Query(None, description="Filter by gate_type"),
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """Return all currently-pending gates (for sidebar badges)."""
    gates = SessionService.list_pending_gates(gate_type=gate_type)
    return {"gates": gates, "total": len(gates)}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sessions/{session_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{session_id}")
async def get_session(
    session_id: str,
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """Return the session master row plus all currently-open gates."""
    try:
        return SessionService.get(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/sessions/{session_id}/events  (SSE)
# ─────────────────────────────────────────────────────────────────────────────

async def _stream_session_events(
    session_id: str,
    since_sequence: int,
    request: Request,
) -> AsyncGenerator[str, None]:
    """
    SSE generator: replay + live-tail for one session's event log.

    Phase 1 (replay): flush every event with sequence_number > since_sequence
                      ordered ASC, straight from the DB. This is the DB=truth
                      guarantee — no in-memory bus can diverge.

    Phase 2 (live):   LISTEN on 'session_<session_id>'. On each notification
                      re-fetch events since the last applied sequence and
                      stream them. If LISTEN/NOTIFY is unavailable, fall back
                      to polling every 500ms.

    The client may reconnect with ?since=<last_known_sequence> after any
    disconnect and the replay phase will bring it back in sync exactly.
    """
    # ── Phase 1: replay ───────────────────────────────────────────────
    last_sequence = since_sequence
    sid_short = session_id[:8] if session_id else "?"
    logger.info("[SSE-STREAM] OPEN session=%s since=%s", sid_short, since_sequence)

    # HF-4 / R8 / R19 — snapshot fast-forward.
    # If a snapshot exists ahead of the client's `since`, verify its hash
    # and stream a single `snapshot_replay` frame so the client reducer can
    # jump directly to that state instead of replaying every event from 0.
    # On a hash mismatch we log and fall through to full replay — the event
    # log is authoritative; a bad snapshot is a performance issue, not a
    # correctness issue.
    try:
        snapshot = await asyncio.to_thread(
            SessionService.get_latest_snapshot, session_id, None
        )
    except Exception as exc:
        logger.warning("[SSE-STREAM] snapshot lookup failed session=%s err=%s", sid_short, exc)
        snapshot = {}

    if snapshot:
        snap_seq = int(snapshot.get("at_sequence_number") or 0)
        snap_hash = snapshot.get("content_hash") or ""
        if snap_seq > last_sequence and snap_hash:
            try:
                hash_ok = await asyncio.to_thread(
                    SessionService.verify_snapshot_hash,
                    session_id, snap_seq, snap_hash,
                )
            except Exception as exc:
                logger.error(
                    "snapshot verify failed for session %s at seq=%s: %s",
                    session_id, snap_seq, exc,
                )
                hash_ok = False

            if hash_ok:
                yield _sse_format("snapshot_replay", {
                    "session_id": session_id,
                    "at_sequence_number": snap_seq,
                    "state": snapshot.get("state") or {},
                    "content_hash": snap_hash,
                })
                last_sequence = snap_seq
            else:
                logger.error(
                    "SNAPSHOT_HASH_MISMATCH session=%s seq=%s — falling back to full replay",
                    session_id, snap_seq,
                )

    try:
        events = await asyncio.to_thread(
            SessionService.list_events, session_id, last_sequence, 10_000
        )
    except Exception as exc:
        logger.error("[SSE-STREAM] replay FAILED session=%s err=%s", sid_short, exc)
        yield _sse_format("error", {"error": f"replay_failed: {exc}"})
        return

    logger.info(
        "[SSE-STREAM] REPLAY session=%s from_seq=%s count=%s",
        sid_short, last_sequence, len(events),
    )

    # Emit a synthetic marker so the frontend knows replay is starting
    yield _sse_format("replay_start", {
        "session_id": session_id,
        "since": last_sequence,
        "count": len(events),
    })
    for ev in events:
        yield _sse_format("session_event", ev)
        last_sequence = max(last_sequence, int(ev.get("sequence_number") or 0))
    yield _sse_format("replay_end", {"last_sequence": last_sequence})
    logger.info("[SSE-STREAM] REPLAY-END session=%s last_seq=%s", sid_short, last_sequence)

    # ── Phase 2: live tail ────────────────────────────────────────────
    # Try PostgreSQL LISTEN/NOTIFY on a dedicated connection.
    # Fall back to polling if it's not available.
    use_listen = os.getenv("SESSION_SSE_MODE", "listen").lower() == "listen"
    listen_conn = None
    if use_listen:
        try:
            listen_conn = await asyncio.to_thread(_open_listen_connection, session_id)
            logger.info("[SSE-STREAM] LISTEN connected session=%s channel=session_%s", sid_short, sid_short)
        except Exception as exc:
            logger.warning(
                "[SSE-STREAM] LISTEN unavailable session=%s err=%s — falling back to polling",
                sid_short, exc,
            )
            listen_conn = None
    else:
        logger.info("[SSE-STREAM] LISTEN disabled by env session=%s — polling mode", sid_short)

    tick = 0
    try:
        while True:
            if await request.is_disconnected():
                logger.info("[SSE-STREAM] client disconnected session=%s", sid_short)
                return

            got_notify = False
            if listen_conn is not None:
                # Non-blocking poll for notifications
                got_notify = await asyncio.to_thread(
                    _drain_notifications, listen_conn
                )
                if got_notify:
                    logger.debug("[SSE-STREAM] NOTIFY drained session=%s", sid_short)

            if got_notify or listen_conn is None:
                # Re-fetch any new events and stream them
                new_events = await asyncio.to_thread(
                    SessionService.list_events, session_id, last_sequence, 1000
                )
                if new_events:
                    logger.info(
                        "[SSE-STREAM] FLUSH session=%s count=%s seqs=%s..%s",
                        sid_short, len(new_events),
                        new_events[0].get("sequence_number"),
                        new_events[-1].get("sequence_number"),
                    )
                for ev in new_events:
                    yield _sse_format("session_event", ev)
                    last_sequence = max(last_sequence, int(ev.get("sequence_number") or 0))

                # Terminate stream if the session reached a terminal state
                try:
                    current = SessionService.get(session_id)
                    if current.get("current_status") in ("completed", "failed", "cancelled"):
                        logger.info(
                            "[SSE-STREAM] TERMINAL session=%s status=%s last_seq=%s — closing",
                            sid_short, current.get("current_status"), last_sequence,
                        )
                        yield _sse_format("stream_end", {
                            "status": current.get("current_status"),
                            "last_sequence": last_sequence,
                        })
                        return
                except SessionNotFoundError:
                    logger.warning("[SSE-STREAM] session vanished session=%s — closing", sid_short)
                    return

            # Keep-alive + polling interval
            await asyncio.sleep(0.5)
            tick += 1
            if tick % 60 == 0:  # ~30s
                logger.debug("[SSE-STREAM] still alive session=%s last_seq=%s tick=%s", sid_short, last_sequence, tick)
            # Send keepalive comment to avoid proxies closing idle connections
            yield ": keepalive\n\n"
    finally:
        logger.info("[SSE-STREAM] CLOSE session=%s last_seq=%s ticks=%s", sid_short, last_sequence, tick)
        if listen_conn is not None:
            try:
                await asyncio.to_thread(listen_conn.close)
            except Exception:
                pass


def _open_listen_connection(session_id: str):
    """
    Open a dedicated psycopg2 connection in autocommit mode and issue
    LISTEN session_<session_id>. Returns the connection (caller closes).
    """
    import psycopg2
    import psycopg2.extensions

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(dsn)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cur:
        # Channel names with hyphens (UUIDs) must be quoted
        cur.execute(f'LISTEN "session_{session_id}";')
    return conn


def _drain_notifications(conn) -> bool:
    """
    Poll the connection for buffered NOTIFY messages.
    Returns True if one or more notifications were consumed.
    """
    conn.poll()
    got_any = False
    while conn.notifies:
        conn.notifies.pop(0)
        got_any = True
    return got_any


@router.get("/{session_id}/events")
async def stream_session_events(
    session_id: str,
    request: Request,
    since: int = Query(0, ge=0, description="Stream events with sequence_number greater than this"),
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> StreamingResponse:
    """
    SSE endpoint: ordered replay from `since` followed by a live tail.

    Clients reconnect with ?since=<last_sequence_number> after any blip.
    The hook is idempotent because each frame carries its sequence_number.
    """
    # Validate the session exists (fail fast with 404 before starting stream)
    try:
        SessionService.get(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return StreamingResponse(
        _stream_session_events(session_id, since, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering if present
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/sessions/{session_id}/resume
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{session_id}/resume")
async def resume_session(
    session_id: str,
    body: ResumeRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """
    Resolve an open gate on a session. R13 idempotent via gate_resolution_id.

    On a fresh resolution (not an idempotent replay) this route ALSO
    spawns `orchestrator._resume_p2p_workflow` as a FastAPI
    BackgroundTask (HF-6). The orchestrator continues the P2P flow
    through the 24 specialized agents via its `specialized_agents`
    dispatch, emitting phase_started / phase_completed / gate_opened
    events via SessionService.append_event. The frontend picks up
    those events live via the SSE subscription on
    /api/sessions/{session_id}/events, so the HTTP response here
    stays fast and only carries the gate-resolution acknowledgment.
    """
    user_id = _user_id_of(current_user)
    logger.info(
        "[resume_session] session=%s gate_id=%s action=%s grid=%s payload_keys=%s user=%s",
        (session_id or "?")[:8],
        body.gate_id,
        body.action,
        (body.gate_resolution_id or "?")[:8],
        list((body.payload or {}).keys()),
        user_id,
    )

    # Validate the session first
    try:
        SessionService.get(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Resolve the gate (idempotent via gate_resolution_id)
    try:
        result = SessionService.resolve_gate(
            gate_id=body.gate_id,
            decision={"action": body.action, "payload": body.payload},
            resolved_by=user_id,
            gate_resolution_id=body.gate_resolution_id,
        )
    except GateNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SessionServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # If this was a fresh resolution (not a replay), append a gate_resolved
    # event AND spawn the orchestrator to continue past the gate.
    if not result.get("idempotent_replay"):
        try:
            SessionService.append_event(
                session_id=session_id,
                event_type="gate_resolved",
                actor=user_id,
                payload={
                    "gate_id": body.gate_id,
                    "action": body.action,
                    "gate_resolution_id": body.gate_resolution_id,
                },
            )
        except SessionServiceError as exc:
            logger.warning("append_event after resolve_gate failed: %s", exc)

        # HF-6: Re-enter the orchestrator to continue the P2P flow past
        # this gate. The orchestrator drives the 24 specialized agents
        # via self.specialized_agents — no phase ordering, no pr_data
        # construction, no agent selection lives here. This route
        # handler only hands off control.
        try:
            session_row = SessionService.get(session_id)
            wf_id = session_row.get("workflow_run_id")
            if not wf_id:
                logger.warning(
                    "[resume_session] session=%s has no workflow_run_id — "
                    "cannot hand off to orchestrator (gate was still resolved)",
                    (session_id or "?")[:8],
                )
            else:
                resume_context = {
                    "workflow_run_id": wf_id,
                    "session_id": session_id,
                    "gate_id": body.gate_id,
                    "gate_resolution_id": body.gate_resolution_id,
                    "action": body.action,
                    "human_input": body.payload or {},
                    "user_id": user_id,
                }
                background_tasks.add_task(
                    _run_orchestrator_resume, resume_context
                )
                logger.info(
                    "[resume_session] session=%s queued orchestrator "
                    "resume wf=%s action=%s",
                    (session_id or "?")[:8],
                    (wf_id or "?")[:8],
                    body.action,
                )
        except Exception as _spawn_exc:
            # Do NOT fail the HTTP request. The gate is already resolved
            # in the DB; if the spawn fails the user will see a stuck
            # session, which surfaces as a separate (louder) signal.
            logger.error(
                "[resume_session] session=%s FAILED to queue orchestrator "
                "resume: %s",
                (session_id or "?")[:8], _spawn_exc,
            )

    return {
        "success": True,
        "gate": result.get("gate"),
        "idempotent_replay": result.get("idempotent_replay"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/sessions/{session_id}/cancel
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{session_id}/cancel")
async def cancel_session(
    session_id: str,
    body: CancelRequest,
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """Cancel a running session. Appends a session_cancelled event."""
    user_id = _user_id_of(current_user)

    try:
        session = SessionService.get(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if session.get("current_status") in ("completed", "failed", "cancelled"):
        return {
            "success": True,
            "already_terminal": True,
            "current_status": session.get("current_status"),
        }

    try:
        SessionService.append_event(
            session_id=session_id,
            event_type="session_cancelled",
            actor=user_id,
            payload={"reason": body.reason},
        )
        updated = SessionService.set_phase(
            session_id=session_id,
            new_phase="cancelled",
            new_status="cancelled",
        )
    except IllegalTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SessionServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "session": updated}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/sessions/{session_id}/advance-to-grn  (HF-1)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{session_id}/advance-to-grn")
async def advance_to_grn(
    session_id: str,
    body: AdvanceToGrnRequest,
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """
    Move a session from delivery_tracking(running) → grn(running) → grn_wait(paused_human)
    and open the grn gate. Called by GoodsReceiptPage when the user confirms
    that goods have physically arrived.

    HF-1: this is the ONLY place the orchestrator emits phase_completed for
    delivery_tracking and the ONLY place the grn gate is opened. The previous
    implementation compressed all of these into a <1ms burst right after
    po_creation, which made the event log lie about real-world timing.

    Idempotency: callers pass a stable advance_request_id per click. If the
    session is already past delivery_tracking (e.g. already in grn_wait or
    further) the endpoint returns the existing gate without re-emitting events.
    """
    user_id = _user_id_of(current_user)

    # Load the session master row
    try:
        sess = SessionService.get(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    current_phase = sess.get("current_phase")
    current_status = sess.get("current_status")

    # Idempotent replay: already advanced past delivery_tracking
    if current_phase != "delivery_tracking":
        existing_grn_gate = next(
            (
                g for g in (sess.get("open_gates") or [])
                if g.get("gate_type") == "grn" and g.get("status") == "pending"
            ),
            None,
        )
        return {
            "success": True,
            "idempotent_replay": True,
            "current_phase": current_phase,
            "current_status": current_status,
            "gate": existing_grn_gate,
        }

    # Gate-ref: ids only, no business values
    gate_ref: Dict[str, Any] = {}
    if body.po_number:
        gate_ref["po_number"] = body.po_number
    if body.pr_number:
        gate_ref["pr_number"] = body.pr_number
    if body.vendor_name:
        gate_ref["vendor_name"] = body.vendor_name

    decision_context: Dict[str, Any] = {
        "triggered_by": "user_confirmation",
        "advance_request_id": body.advance_request_id,
        "confirmed_by": user_id,
    }

    try:
        # phase_completed(delivery_tracking) — HONEST: emitted only when the user
        # actually confirmed delivery arrived, not in a <1ms burst.
        SessionService.append_event(
            session_id=session_id,
            event_type="phase_completed",
            actor=f"user:{user_id}",
            payload={
                "phase": "delivery_tracking",
                "ref": gate_ref,
                "advance_request_id": body.advance_request_id,
            },
        )
        SessionService.set_phase(session_id, new_phase="grn", new_status="running")
        SessionService.append_event(
            session_id=session_id,
            event_type="phase_started",
            actor="orchestrator",
            payload={"phase": "grn", "ref": gate_ref},
        )
        gate_row = SessionService.open_gate(
            session_id=session_id,
            gate_type="grn",
            gate_ref=gate_ref,
            decision_context=decision_context,
            required_role="warehouse",
        )
        gate_id = gate_row.get("gate_id")
        SessionService.append_event(
            session_id=session_id,
            event_type="gate_opened",
            actor="orchestrator",
            payload={
                "gate_id": gate_id,
                "gate_type": "grn",
                "po_number": body.po_number,
            },
        )
        SessionService.set_phase(session_id, new_phase="grn_wait", new_status="paused_human")
    except IllegalTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SessionServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "success": True,
        "idempotent_replay": False,
        "gate_id": gate_id,
        "current_phase": "grn_wait",
        "current_status": "paused_human",
    }
