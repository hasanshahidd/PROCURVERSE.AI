"""
Unit tests for SessionService — Layer 1 single-writer primitive.

Covers the P0 service surface end-to-end with the adapter layer mocked out,
so no database is required. These tests validate the hard rules enforced by
the service:

  R3  — set_phase() rejects transitions not in ALLOWED_TRANSITIONS
  R4  — create() is idempotent via request_fingerprint
  R9  — create() rejects unknown callers
  R13 — resolve_gate() is idempotent via gate_resolution_id
  ... plus the smaller guards (empty args, missing rows, version conflicts).

Run:
  python -m pytest backend/tests/test_session_service.py -v
or
  python backend/tests/test_session_service.py
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Make backend imports work when this file is run directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.services.session_service import (  # noqa: E402
    ALLOWED_CALLERS,
    ALLOWED_TRANSITIONS,
    FINGERPRINT_BUCKET_SECONDS,
    SESSION_KIND_P2P_FULL,
    GateNotFoundError,
    IllegalTransitionError,
    SessionNotFoundError,
    SessionService,
    SessionServiceError,
    UnauthorizedSessionCreation,
    compute_request_fingerprint,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────

ADAPTER_PATCH_TARGET = "backend.services.session_service.get_adapter"


def _make_session_row(**overrides: Any) -> Dict[str, Any]:
    """A minimal execution_sessions row, JSON-safe."""
    row: Dict[str, Any] = {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "session_kind": SESSION_KIND_P2P_FULL,
        "initiated_by_user_id": "user-42",
        "request_fingerprint": "abc123",
        "current_phase": "starting",
        "current_status": "running",
        "workflow_run_id": None,
        "request_summary": {"request": "Procure 20 servers"},
        "last_event_sequence": 0,
        "snapshot_version": 0,
        "version": 1,
        "created_at": "2026-04-10T10:00:00+00:00",
        "updated_at": "2026-04-10T10:00:00+00:00",
        "completed_at": None,
    }
    row.update(overrides)
    return row


def _make_gate_row(**overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "gate_id": "gate-1111",
        "session_id": "11111111-1111-1111-1111-111111111111",
        "gate_type": "vendor_selection",
        "gate_ref": {"vendor_ids": ["v1", "v2"]},
        "decision_context": {"scoring": [], "rejected_options": []},
        "required_role": "requester",
        "status": "pending",
        "decision": None,
        "gate_resolution_id": None,
        "resolved_by": None,
        "resolved_at": None,
        "created_at": "2026-04-10T10:05:00+00:00",
    }
    row.update(overrides)
    return row


class _FakeAdapter:
    """
    Hand-rolled fake of the adapter interface for session tables.
    Simpler than MagicMock when we need stateful behaviour (e.g. list_session_gates
    reflecting the last insert_session_gate).
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.gates: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []

    # ── bookkeeping ───────────────────────────────────────────────────────
    def _log(self, name: str, **kwargs: Any) -> None:
        self.calls.append({"method": name, **kwargs})

    # ── sessions ──────────────────────────────────────────────────────────
    def insert_execution_session(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self._log("insert_execution_session", data=data)
        fp = data.get("request_fingerprint")
        for s in self.sessions.values():
            if s.get("request_fingerprint") == fp:
                return {"success": True, "created": False, "session": s}
        row = _make_session_row(
            session_id=f"sess-{len(self.sessions) + 1}",
            session_kind=data.get("session_kind"),
            initiated_by_user_id=data.get("initiated_by_user_id"),
            request_fingerprint=fp,
            request_summary=data.get("request_summary"),
            workflow_run_id=data.get("workflow_run_id"),
        )
        self.sessions[row["session_id"]] = row
        return {"success": True, "created": True, "session": row}

    def get_execution_session(self, session_id: str) -> Dict[str, Any]:
        self._log("get_execution_session", session_id=session_id)
        return self.sessions.get(session_id, {})

    def list_execution_sessions(self, user_id: Optional[str] = None,
                                status: Optional[str] = None,
                                kind: Optional[str] = None,
                                limit: int = 50) -> List[Dict[str, Any]]:
        self._log("list_execution_sessions", user_id=user_id, status=status,
                  kind=kind, limit=limit)
        out = list(self.sessions.values())
        if user_id:
            out = [r for r in out if r.get("initiated_by_user_id") == user_id]
        if status:
            out = [r for r in out if r.get("current_status") == status]
        if kind:
            out = [r for r in out if r.get("session_kind") == kind]
        return out[:limit]

    def update_execution_session_phase(self, session_id: str, new_phase: str,
                                       new_status: str,
                                       expected_version: int) -> Dict[str, Any]:
        self._log("update_execution_session_phase", session_id=session_id,
                  new_phase=new_phase, new_status=new_status,
                  expected_version=expected_version)
        row = self.sessions.get(session_id)
        if not row:
            return {"success": False, "error": "version_conflict_or_not_found"}
        if row.get("version") != expected_version:
            return {"success": False, "error": "version_conflict_or_not_found"}
        row["current_phase"] = new_phase
        row["current_status"] = new_status
        row["version"] = (row.get("version") or 0) + 1
        return {"success": True, "session": row}

    # ── events ────────────────────────────────────────────────────────────
    def append_session_event(self, session_id: str, event_type: str,
                             actor: str, payload: Dict[str, Any],
                             caused_by_event_id: Optional[str] = None) -> Dict[str, Any]:
        self._log("append_session_event", session_id=session_id,
                  event_type=event_type, actor=actor, payload=payload)
        sess = self.sessions.get(session_id)
        if not sess:
            return {"success": False, "error": "session_not_found"}
        next_seq = int(sess.get("last_event_sequence") or 0) + 1
        sess["last_event_sequence"] = next_seq
        event = {
            "event_id": f"evt-{len(self.events) + 1}",
            "session_id": session_id,
            "sequence_number": next_seq,
            "event_type": event_type,
            "actor": actor,
            "payload": payload,
            "caused_by_event_id": caused_by_event_id,
            "created_at": "2026-04-10T10:10:00+00:00",
        }
        self.events.append(event)
        return {
            "success": True,
            "event_id": event["event_id"],
            "sequence_number": next_seq,
            "created_at": event["created_at"],
        }

    def list_session_events(self, session_id: str, since_sequence: int = 0,
                            limit: int = 1000) -> List[Dict[str, Any]]:
        self._log("list_session_events", session_id=session_id,
                  since_sequence=since_sequence, limit=limit)
        out = [e for e in self.events
               if e["session_id"] == session_id
               and e["sequence_number"] > since_sequence]
        return sorted(out, key=lambda e: e["sequence_number"])[:limit]

    # ── gates ─────────────────────────────────────────────────────────────
    def insert_session_gate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self._log("insert_session_gate", data=data)
        gate = _make_gate_row(
            gate_id=f"gate-{len(self.gates) + 1}",
            session_id=data.get("session_id"),
            gate_type=data.get("gate_type"),
            gate_ref=data.get("gate_ref"),
            decision_context=data.get("decision_context"),
            required_role=data.get("required_role"),
        )
        self.gates[gate["gate_id"]] = gate
        return {"success": True, "gate": gate}

    def get_session_gate(self, gate_id: str) -> Dict[str, Any]:
        self._log("get_session_gate", gate_id=gate_id)
        return self.gates.get(gate_id, {})

    def list_session_gates(self, session_id: Optional[str] = None,
                           status: Optional[str] = None,
                           gate_type: Optional[str] = None) -> List[Dict[str, Any]]:
        self._log("list_session_gates", session_id=session_id,
                  status=status, gate_type=gate_type)
        out = list(self.gates.values())
        if session_id:
            out = [g for g in out if g.get("session_id") == session_id]
        if status:
            out = [g for g in out if g.get("status") == status]
        if gate_type:
            out = [g for g in out if g.get("gate_type") == gate_type]
        return out

    def resolve_session_gate(self, gate_id: str, decision: Dict[str, Any],
                             resolved_by: str,
                             gate_resolution_id: str) -> Dict[str, Any]:
        self._log("resolve_session_gate", gate_id=gate_id, decision=decision,
                  resolved_by=resolved_by, gate_resolution_id=gate_resolution_id)
        gate = self.gates.get(gate_id)
        if not gate:
            return {"success": False, "error": "gate_not_found_or_already_resolved"}
        # R13: idempotent replay
        if (gate.get("status") == "resolved"
                and gate.get("gate_resolution_id") == gate_resolution_id):
            return {"success": True, "gate": gate, "idempotent_replay": True}
        if gate.get("status") == "resolved":
            return {"success": False, "error": "gate_not_found_or_already_resolved"}
        gate["status"] = "resolved"
        gate["decision"] = decision
        gate["resolved_by"] = resolved_by
        gate["gate_resolution_id"] = gate_resolution_id
        gate["resolved_at"] = "2026-04-10T10:30:00+00:00"
        return {"success": True, "gate": gate, "idempotent_replay": False}


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFingerprintAndConstants(unittest.TestCase):
    """Pure-function sanity checks — no adapter involved."""

    def test_fingerprint_is_deterministic_within_bucket(self):
        t0 = 1_700_000_000.0
        fp1 = compute_request_fingerprint("user-1", {"a": 1, "b": 2}, timestamp=t0)
        fp2 = compute_request_fingerprint("user-1", {"b": 2, "a": 1}, timestamp=t0)
        self.assertEqual(fp1, fp2, "key order in dict must not affect fingerprint")

    def test_fingerprint_changes_across_buckets(self):
        t0 = 1_700_000_000.0
        t1 = t0 + FINGERPRINT_BUCKET_SECONDS + 1
        fp1 = compute_request_fingerprint("user-1", {"x": 1}, timestamp=t0)
        fp2 = compute_request_fingerprint("user-1", {"x": 1}, timestamp=t1)
        self.assertNotEqual(fp1, fp2, "crossing a bucket boundary must produce a new fingerprint")

    def test_fingerprint_differs_by_user(self):
        t0 = 1_700_000_000.0
        fp1 = compute_request_fingerprint("user-1", {"x": 1}, timestamp=t0)
        fp2 = compute_request_fingerprint("user-2", {"x": 1}, timestamp=t0)
        self.assertNotEqual(fp1, fp2)

    def test_fingerprint_differs_by_payload(self):
        t0 = 1_700_000_000.0
        fp1 = compute_request_fingerprint("user-1", {"x": 1}, timestamp=t0)
        fp2 = compute_request_fingerprint("user-1", {"x": 2}, timestamp=t0)
        self.assertNotEqual(fp1, fp2)

    def test_allowed_callers_is_frozen(self):
        self.assertIn("query_router", ALLOWED_CALLERS)
        self.assertIn("test", ALLOWED_CALLERS)
        self.assertNotIn("agent", ALLOWED_CALLERS)
        with self.assertRaises(AttributeError):
            ALLOWED_CALLERS.add("agent")  # type: ignore[attr-defined]

    def test_allowed_transitions_every_phase_has_entry(self):
        """
        Every phase that appears as an allowed successor must also appear as a
        key in ALLOWED_TRANSITIONS. This catches typos like 'complience' or
        transitions to undeclared phases.
        """
        all_successors = set()
        for allowed in ALLOWED_TRANSITIONS.values():
            all_successors.update(allowed)
        missing = all_successors - set(ALLOWED_TRANSITIONS.keys())
        self.assertFalse(
            missing,
            f"ALLOWED_TRANSITIONS has successor(s) with no entry: {missing}",
        )

    def test_terminal_states_are_dead_ends(self):
        for terminal in ("completed", "failed", "cancelled"):
            self.assertEqual(
                ALLOWED_TRANSITIONS[terminal],
                frozenset(),
                f"{terminal!r} must have no outgoing transitions",
            )


class TestSessionServiceCreate(unittest.TestCase):
    """R4 + R9: idempotent creation with allowlisted callers."""

    def setUp(self):
        self.adapter = _FakeAdapter()
        self.patcher = patch(ADAPTER_PATCH_TARGET, return_value=self.adapter)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_create_rejects_unknown_caller(self):
        with self.assertRaises(UnauthorizedSessionCreation):
            SessionService.create(
                kind=SESSION_KIND_P2P_FULL,
                user_id="user-1",
                request_summary={"request": "x"},
                caller="agent",  # not in ALLOWED_CALLERS
            )

    def test_create_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            SessionService.create(
                kind="compliance_only",  # not supported in P0
                user_id="user-1",
                request_summary={"request": "x"},
                caller="test",
            )

    def test_create_rejects_empty_user_id(self):
        with self.assertRaises(ValueError):
            SessionService.create(
                kind=SESSION_KIND_P2P_FULL,
                user_id="",
                request_summary={"request": "x"},
                caller="test",
            )

    def test_create_inserts_new_session(self):
        result = SessionService.create(
            kind=SESSION_KIND_P2P_FULL,
            user_id="user-1",
            request_summary={"request": "Procure 20 servers"},
            caller="test",
            timestamp=1_700_000_000.0,
        )
        self.assertTrue(result["created"])
        self.assertIsNotNone(result["session_id"])
        self.assertEqual(
            result["session"]["initiated_by_user_id"], "user-1",
        )
        # The adapter must have been called with a fingerprint
        inserts = [c for c in self.adapter.calls if c["method"] == "insert_execution_session"]
        self.assertEqual(len(inserts), 1)
        self.assertTrue(inserts[0]["data"]["request_fingerprint"])

    def test_create_is_idempotent_within_bucket(self):
        """Two creates with identical inputs at the same timestamp collapse to one session."""
        t0 = 1_700_000_000.0
        first = SessionService.create(
            kind=SESSION_KIND_P2P_FULL,
            user_id="user-1",
            request_summary={"request": "Procure 20 servers"},
            caller="test",
            timestamp=t0,
        )
        second = SessionService.create(
            kind=SESSION_KIND_P2P_FULL,
            user_id="user-1",
            request_summary={"request": "Procure 20 servers"},
            caller="test",
            timestamp=t0,
        )
        self.assertTrue(first["created"])
        self.assertFalse(second["created"], "duplicate must return created=False")
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(len(self.adapter.sessions), 1)

    def test_create_different_payloads_yield_different_sessions(self):
        t0 = 1_700_000_000.0
        r1 = SessionService.create(
            kind=SESSION_KIND_P2P_FULL,
            user_id="user-1",
            request_summary={"request": "A"},
            caller="test",
            timestamp=t0,
        )
        r2 = SessionService.create(
            kind=SESSION_KIND_P2P_FULL,
            user_id="user-1",
            request_summary={"request": "B"},
            caller="test",
            timestamp=t0,
        )
        self.assertNotEqual(r1["session_id"], r2["session_id"])

    def test_create_raises_on_adapter_failure(self):
        with patch.object(self.adapter, "insert_execution_session",
                          return_value={"success": False, "error": "db_down"}):
            with self.assertRaises(SessionServiceError):
                SessionService.create(
                    kind=SESSION_KIND_P2P_FULL,
                    user_id="user-1",
                    request_summary={"request": "x"},
                    caller="test",
                )


class TestSessionServiceGetAndList(unittest.TestCase):

    def setUp(self):
        self.adapter = _FakeAdapter()
        self.patcher = patch(ADAPTER_PATCH_TARGET, return_value=self.adapter)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _seed_session(self, **overrides: Any) -> str:
        row = _make_session_row(**overrides)
        self.adapter.sessions[row["session_id"]] = row
        return row["session_id"]

    def test_get_returns_session_with_open_gates(self):
        sid = self._seed_session(session_id="sess-42")
        self.adapter.gates["g1"] = _make_gate_row(gate_id="g1", session_id=sid, status="pending")
        self.adapter.gates["g2"] = _make_gate_row(gate_id="g2", session_id=sid, status="resolved")

        result = SessionService.get(sid)

        self.assertEqual(result["session_id"], sid)
        self.assertIn("open_gates", result)
        self.assertEqual(len(result["open_gates"]), 1)
        self.assertEqual(result["open_gates"][0]["gate_id"], "g1")

    def test_get_raises_when_missing(self):
        with self.assertRaises(SessionNotFoundError):
            SessionService.get("does-not-exist")

    def test_list_passes_filters_through(self):
        self._seed_session(session_id="s-a", initiated_by_user_id="u1", current_status="running")
        self._seed_session(session_id="s-b", initiated_by_user_id="u1", current_status="completed")
        self._seed_session(session_id="s-c", initiated_by_user_id="u2", current_status="running")

        out = SessionService.list(user_id="u1", status="running")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["session_id"], "s-a")

    def test_list_pending_gates_filters_by_type(self):
        self._seed_session()
        self.adapter.gates["g1"] = _make_gate_row(gate_id="g1", gate_type="vendor_selection", status="pending")
        self.adapter.gates["g2"] = _make_gate_row(gate_id="g2", gate_type="approval", status="pending")

        vendor_gates = SessionService.list_pending_gates(gate_type="vendor_selection")
        self.assertEqual(len(vendor_gates), 1)
        self.assertEqual(vendor_gates[0]["gate_id"], "g1")


class TestSessionServiceAppendEvent(unittest.TestCase):

    def setUp(self):
        self.adapter = _FakeAdapter()
        self.patcher = patch(ADAPTER_PATCH_TARGET, return_value=self.adapter)
        self.patcher.start()
        # Seed one session
        self.sid = "sess-evt-1"
        self.adapter.sessions[self.sid] = _make_session_row(session_id=self.sid)

    def tearDown(self):
        self.patcher.stop()

    def test_append_event_returns_sequence_and_id(self):
        result = SessionService.append_event(
            session_id=self.sid,
            event_type="phase_started",
            actor="orchestrator",
            payload={"phase": "compliance"},
        )
        self.assertIn("event_id", result)
        self.assertEqual(result["sequence_number"], 1)

    def test_append_event_sequence_is_monotonic(self):
        r1 = SessionService.append_event(self.sid, "phase_started", "orchestrator", {"phase": "compliance"})
        r2 = SessionService.append_event(self.sid, "phase_completed", "orchestrator", {"phase": "compliance"})
        r3 = SessionService.append_event(self.sid, "phase_started", "orchestrator", {"phase": "budget"})
        self.assertEqual([r1["sequence_number"], r2["sequence_number"], r3["sequence_number"]],
                         [1, 2, 3])

    def test_append_event_rejects_empty_type(self):
        with self.assertRaises(ValueError):
            SessionService.append_event(self.sid, "", "orchestrator", {})

    def test_append_event_rejects_empty_actor(self):
        with self.assertRaises(ValueError):
            SessionService.append_event(self.sid, "phase_started", "", {})

    def test_append_event_raises_on_adapter_failure(self):
        with patch.object(self.adapter, "append_session_event",
                          return_value={"success": False, "error": "db_down"}):
            with self.assertRaises(SessionServiceError):
                SessionService.append_event(self.sid, "phase_started", "orchestrator", {})

    def test_list_events_returns_only_after_since(self):
        SessionService.append_event(self.sid, "phase_started", "orchestrator", {"phase": "compliance"})
        SessionService.append_event(self.sid, "phase_completed", "orchestrator", {"phase": "compliance"})
        SessionService.append_event(self.sid, "phase_started", "orchestrator", {"phase": "budget"})

        all_events = SessionService.list_events(self.sid, since_sequence=0)
        self.assertEqual(len(all_events), 3)

        tail = SessionService.list_events(self.sid, since_sequence=2)
        self.assertEqual(len(tail), 1)
        self.assertEqual(tail[0]["sequence_number"], 3)


class TestSessionServiceGates(unittest.TestCase):

    def setUp(self):
        self.adapter = _FakeAdapter()
        self.patcher = patch(ADAPTER_PATCH_TARGET, return_value=self.adapter)
        self.patcher.start()
        self.sid = "sess-gate-1"
        self.adapter.sessions[self.sid] = _make_session_row(session_id=self.sid)

    def tearDown(self):
        self.patcher.stop()

    def test_open_gate_persists_decision_context_snapshot(self):
        ctx = {
            "scoring_snapshot": [{"vendor_id": "v1", "score": 87}],
            "rejected_options": [{"vendor_id": "v9", "reason": "past_due"}],
            "policy_version": "v2.3",
        }
        gate = SessionService.open_gate(
            session_id=self.sid,
            gate_type="vendor_selection",
            gate_ref={"vendor_ids": ["v1", "v2"]},
            decision_context=ctx,
            required_role="requester",
        )
        self.assertEqual(gate["gate_type"], "vendor_selection")
        self.assertEqual(gate["decision_context"], ctx)
        self.assertEqual(gate["status"], "pending")

    def test_open_gate_rejects_empty_type(self):
        with self.assertRaises(ValueError):
            SessionService.open_gate(
                session_id=self.sid,
                gate_type="",
                gate_ref={},
            )

    def test_get_gate_raises_on_missing(self):
        with self.assertRaises(GateNotFoundError):
            SessionService.get_gate("nope")

    def test_resolve_gate_requires_resolution_id(self):
        gate = SessionService.open_gate(self.sid, "vendor_selection", {})
        with self.assertRaises(ValueError):
            SessionService.resolve_gate(
                gate_id=gate["gate_id"],
                decision={"action": "approve"},
                resolved_by="user-1",
                gate_resolution_id="",
            )

    def test_resolve_gate_requires_resolved_by(self):
        gate = SessionService.open_gate(self.sid, "vendor_selection", {})
        with self.assertRaises(ValueError):
            SessionService.resolve_gate(
                gate_id=gate["gate_id"],
                decision={"action": "approve"},
                resolved_by="",
                gate_resolution_id="res-1",
            )

    def test_resolve_gate_idempotent_replay(self):
        """R13: submitting the same gate_resolution_id twice returns the prior decision."""
        gate = SessionService.open_gate(self.sid, "vendor_selection", {})
        res_id = "res-deterministic-1"
        first = SessionService.resolve_gate(
            gate_id=gate["gate_id"],
            decision={"action": "approve", "vendor_id": "v1"},
            resolved_by="user-1",
            gate_resolution_id=res_id,
        )
        second = SessionService.resolve_gate(
            gate_id=gate["gate_id"],
            decision={"action": "approve", "vendor_id": "v1"},
            resolved_by="user-1",
            gate_resolution_id=res_id,
        )
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["gate"]["gate_id"], second["gate"]["gate_id"])

    def test_resolve_gate_raises_on_missing(self):
        with self.assertRaises(GateNotFoundError):
            SessionService.resolve_gate(
                gate_id="nope",
                decision={"action": "approve"},
                resolved_by="user-1",
                gate_resolution_id="res-1",
            )


class TestSessionServiceSetPhase(unittest.TestCase):
    """R3: ALLOWED_TRANSITIONS enforcement + optimistic concurrency."""

    def setUp(self):
        self.adapter = _FakeAdapter()
        self.patcher = patch(ADAPTER_PATCH_TARGET, return_value=self.adapter)
        self.patcher.start()
        self.sid = "sess-phase-1"
        self.adapter.sessions[self.sid] = _make_session_row(
            session_id=self.sid,
            current_phase="starting",
            current_status="running",
            version=1,
        )

    def tearDown(self):
        self.patcher.stop()

    def test_valid_transition_starting_to_compliance(self):
        updated = SessionService.set_phase(self.sid, "compliance", "running")
        self.assertEqual(updated["current_phase"], "compliance")
        self.assertEqual(updated["current_status"], "running")
        self.assertEqual(updated["version"], 2)

    def test_illegal_transition_raises(self):
        # Cannot leap from 'starting' straight to 'payment_execution'
        with self.assertRaises(IllegalTransitionError):
            SessionService.set_phase(self.sid, "payment_execution", "running")

    def test_terminal_state_is_locked(self):
        self.adapter.sessions[self.sid]["current_phase"] = "completed"
        with self.assertRaises(IllegalTransitionError):
            SessionService.set_phase(self.sid, "starting", "running")

    def test_same_phase_is_allowed_noop(self):
        """Transitioning to the same phase is always allowed (status-only update)."""
        updated = SessionService.set_phase(self.sid, "starting", "paused_human")
        self.assertEqual(updated["current_phase"], "starting")
        self.assertEqual(updated["current_status"], "paused_human")

    def test_raises_when_session_missing(self):
        with self.assertRaises(SessionNotFoundError):
            SessionService.set_phase("nope", "compliance", "running")

    def test_retries_on_version_conflict_and_eventually_succeeds(self):
        """
        Simulate: attempt 1 returns version_conflict, attempt 2 succeeds.
        The service should retry transparently up to 3 times.
        """
        real_update = self.adapter.update_execution_session_phase
        call_counter = {"n": 0}

        def flaky_update(**kwargs: Any) -> Dict[str, Any]:
            call_counter["n"] += 1
            if call_counter["n"] == 1:
                return {"success": False, "error": "version_conflict_or_not_found"}
            return real_update(**kwargs)

        with patch.object(self.adapter, "update_execution_session_phase",
                          side_effect=flaky_update):
            updated = SessionService.set_phase(self.sid, "compliance", "running")
        self.assertEqual(updated["current_phase"], "compliance")
        self.assertEqual(call_counter["n"], 2)

    def test_raises_after_three_version_conflict_retries(self):
        with patch.object(self.adapter, "update_execution_session_phase",
                          return_value={"success": False,
                                        "error": "version_conflict_or_not_found"}):
            with self.assertRaises(SessionServiceError):
                SessionService.set_phase(self.sid, "compliance", "running")

    def test_raises_on_other_adapter_errors(self):
        with patch.object(self.adapter, "update_execution_session_phase",
                          return_value={"success": False, "error": "db_down"}):
            with self.assertRaises(SessionServiceError):
                SessionService.set_phase(self.sid, "compliance", "running")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
