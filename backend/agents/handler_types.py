"""
HF-3 / R14 — HandlerResult and the PhaseHandler protocol.

Pure handlers replace the monolithic `_execute_full_p2p` async function. Each
handler takes exactly three arguments:

    (orchestrator, context, helpers) -> HandlerResult

and returns a `HandlerResult` that names the next phase (or `None` if the
handler paused at a gate / reached a terminal state). The dispatch loop in
`orchestrator._execute_full_p2p_v2` is the ONLY code that decides what runs
next — handlers never call each other, never re-read state mid-execution,
and never assume what comes after them.

R14 invariants:
  - Handlers are stateless responders. They receive an immutable snapshot
    of the session at entry (in context["_sess_snapshot"]) and never call
    SessionService.get() mid-execution.
  - Handlers never call another handler directly. All cross-phase progress
    happens via HandlerResult.next_phase.
  - Handlers never import or read `ALLOWED_TRANSITIONS` — validation is
    the dispatch loop's job via SessionService.set_phase().
  - Agents remain pure functions. Handlers wrap agent calls with emit()
    side-effects; agents never know a session exists (R15).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Protocol


# ─────────────────────────────────────────────────────────────────────────────
# HandlerResult
# ─────────────────────────────────────────────────────────────────────────────

HandlerStatus = Literal["running", "paused_human", "failed", "completed"]


@dataclass(frozen=True)
class HandlerResult:
    """
    What a phase handler returns to the dispatch loop.

    Fields:
      next_phase: the phase to dispatch next. `None` means the handler has
        either paused at a gate (see `status="paused_human"`) or reached
        a terminal state (completed / failed).
      status: the session status to apply alongside the transition. For
        normal forward progress use "running". For a gate pause use
        "paused_human". For terminal states use "completed" or "failed".
      checkpoint: optional R17 checkpoint name. When set, the dispatch
        loop writes it to execution_sessions.current_checkpoint so that
        a retry from this phase resumes past the checkpoint instead of
        re-running the entire phase.
      error: optional human-readable error string when status == "failed".
    """

    next_phase: Optional[str]
    status: HandlerStatus
    checkpoint: Optional[str] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers bag — the narrow interface a handler gets from the orchestrator
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HandlerHelpers:
    """
    Bundle of closures the orchestrator hands to each handler so the handler
    can emit events, open/resolve gates, and log pipeline steps without
    importing SessionService itself.

    Every closure MUST be safe to call when session_id is None (legacy
    callers): the hybrid-mode emit wrapper in the orchestrator swallows
    Layer 1 failures so a session-layer bug cannot break the pipeline.
    """

    emit: Callable[[str, Dict[str, Any]], None]
    open_gate: Callable[..., Optional[str]]
    set_phase: Callable[[str, str], None]
    set_checkpoint: Callable[[str], None]
    add_step: Callable[..., None]
    track_task: Callable[..., Optional[str]]
    complete_task: Callable[..., None]


# ─────────────────────────────────────────────────────────────────────────────
# PhaseHandler protocol — the type every entry in PHASE_DISPATCH must match
# ─────────────────────────────────────────────────────────────────────────────


class PhaseHandler(Protocol):
    """
    Every entry in PHASE_DISPATCH must be an async callable with this
    exact signature. The dispatch loop calls it once per phase visit and
    uses the returned HandlerResult to decide the next step.
    """

    async def __call__(
        self,
        orch: Any,
        context: Dict[str, Any],
        helpers: HandlerHelpers,
    ) -> HandlerResult: ...
