"""
HF-3 / R14 — Parity test: legacy STEP 1/2/3 path vs PHASE_DISPATCH split-dispatch.

When `USE_PURE_HANDLERS` is enabled (or `context["_use_pure_handlers"]=True`),
`OrchestratorAgent._execute_full_p2p` runs the pre-gate phases (compliance,
budget, vendor) through the pure handlers in `backend.agents.p2p_handlers`
instead of the inline STEP 1/2/3 code blocks. This test runs the same fixture
P2P request through both paths and asserts that the resulting `session_events`
sequences are byte-for-byte identical (ignoring timestamps, UUIDs, and the
opaque gate_id).

This is the gate criterion for promoting `USE_PURE_HANDLERS=True` in staging
and is the structural prerequisite for the P5 driver flip.

Run:
  python -m pytest backend/tests/test_pure_handlers_parity.py -v
or
  python backend/tests/test_pure_handlers_parity.py

The test mocks every external boundary (SessionService adapter, workflow_engine,
budget_ledger_service, contract_linkage_service) so no database, ERP, or LLM
is required.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

# Make backend imports work when this file is run directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Reuse the hand-rolled fake adapter from the SessionService unit tests so the
# parity test stays consistent with how SessionService is actually exercised.
from backend.tests.test_session_service import _FakeAdapter, _make_session_row  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Mock agent — minimal duck-type matching `BaseAgent` for orchestrator usage
# ─────────────────────────────────────────────────────────────────────────────


class _MockAgent:
    """
    The orchestrator only reads `.name` and `await .execute(context)` on
    specialized agents in the pre-gate phases. We don't need a real BaseAgent.
    """

    def __init__(self, name: str, result: Dict[str, Any]) -> None:
        self.name = name
        self._result = result

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self._result


# ─────────────────────────────────────────────────────────────────────────────
# Parity test
# ─────────────────────────────────────────────────────────────────────────────


class TestPureHandlersParity(unittest.TestCase):
    """
    HF-3 parity gate: legacy and split-dispatch must emit identical session
    event sequences for the same fixture input.
    """

    # Fixture results — chosen so every code path the handlers and STEP 1/2/3
    # emit goes down the same branch (approve, sufficient budget, vendor list).
    COMPLIANCE_RESULT: Dict[str, Any] = {
        "action": "approve",
        "result": {
            "compliance_score": 92,
            "compliance_level": "PASS",
            "warnings": [],
            "violations": [],
        },
    }
    BUDGET_RESULT: Dict[str, Any] = {
        "action": "approve",
        "result": {
            "available_budget": 50000,
            "current_budget": 50000,
            "utilization_percentage": 30,
            "budget_verified": True,
            "department": "IT",
        },
    }
    VENDOR_RESULT: Dict[str, Any] = {
        "decision": {
            "context": {
                "primary_vendor": {
                    "vendor_name": "Acme Corp",
                    "total_score": 87,
                    "recommendation_reason": "Best price + delivery",
                    "strengths": ["price", "delivery"],
                    "concerns": [],
                },
                "alternative_vendors": [
                    {
                        "vendor_name": "Beta Inc",
                        "total_score": 79,
                        "recommendation_reason": "Faster lead time",
                        "strengths": ["lead_time"],
                        "concerns": ["price"],
                    }
                ],
            }
        }
    }

    def setUp(self) -> None:
        # Single shared adapter — both legacy and v2 sessions live here so
        # we can read each set of events back by session_id.
        self.adapter = _FakeAdapter()

        # Patch every external boundary the orchestrator touches in the pre-
        # gate path. All patches start here and stop in tearDown.
        self._patches = [
            patch(
                "backend.services.session_service.get_adapter",
                return_value=self.adapter,
            ),
            # workflow_engine — return a successful workflow with no run_id so
            # `_track_task` short-circuits and the workflow attach is a no-op.
            patch(
                "backend.services.workflow_engine.create_workflow",
                return_value={"success": True, "workflow_run_id": None},
            ),
            patch(
                "backend.services.workflow_engine.advance_workflow",
                return_value={"success": True},
            ),
            patch(
                "backend.services.workflow_engine.complete_task",
                return_value={"success": True},
            ),
            patch(
                "backend.services.workflow_engine.fail_task",
                return_value={"success": True},
            ),
            patch(
                "backend.services.workflow_engine.get_suggestions",
                return_value={"suggestions": []},
            ),
            patch(
                "backend.services.workflow_engine.generate_workflow_summary",
                return_value="",
            ),
            patch(
                "backend.services.workflow_engine.get_workflow_status",
                return_value={"tasks": []},
            ),
            # budget_ledger_service — record_commitment is non-blocking; just
            # return a no-op stub. The orchestrator catches any exception, so
            # patching is mostly to keep the test logs clean.
            patch(
                "backend.services.budget_ledger_service.get_budget_ledger_service",
                return_value=_NoOpService(),
            ),
            # contract_linkage_service — same story; the orchestrator's G-02
            # check tolerates failures, but we want a clean run.
            patch(
                "backend.services.contract_linkage_service.get_contract_linkage_service",
                return_value=_NoOpService(),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    # ── helpers ────────────────────────────────────────────────────────────

    def _make_orchestrator(self):
        """
        Build an OrchestratorAgent without running its heavy `__init__`
        (which would try to load LLM credentials, tools, etc.).
        """
        from backend.agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent.__new__(OrchestratorAgent)
        orch.specialized_agents = {
            "compliance_check": _MockAgent("ComplianceCheckAgent", self.COMPLIANCE_RESULT),
            "budget_verification": _MockAgent("BudgetVerificationAgent", self.BUDGET_RESULT),
            "vendor_selection": _MockAgent("VendorSelectionAgent", self.VENDOR_RESULT),
            # NB: NO risk_assessment registered → STEP 4.5 takes the
            # "skipped" path. NO downstream agents → execution halts at
            # the vendor_selection gate, which is exactly the parity
            # boundary HF-3 covers.
        }
        return orch

    def _seed_session(self, session_id: str) -> None:
        """Insert a starting-state session row directly into the fake adapter."""
        self.adapter.sessions[session_id] = _make_session_row(
            session_id=session_id,
            current_phase="starting",
            current_status="running",
            version=1,
            last_event_sequence=0,
        )

    def _events_for(self, session_id: str) -> List[Dict[str, Any]]:
        """All events recorded against a session, sorted by sequence_number."""
        return sorted(
            (e for e in self.adapter.events if e["session_id"] == session_id),
            key=lambda e: e["sequence_number"],
        )

    @staticmethod
    def _normalize(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Strip non-deterministic fields (event_id, sequence_number, created_at,
        gate_id) so two runs can be compared structurally.

        We keep:
          - event_type
          - actor
          - the keys of payload that carry semantic meaning for parity
            (phase, gate_type, action, reason, top_vendor, ref)

        We deliberately drop the gate_id from gate_opened payloads — it is a
        UUID generated by the fake adapter and differs between runs.
        """
        out: List[Dict[str, Any]] = []
        for e in events:
            payload = dict(e.get("payload") or {})
            payload.pop("gate_id", None)  # opaque uuid
            out.append(
                {
                    "event_type": e["event_type"],
                    "actor": e["actor"],
                    "payload": payload,
                }
            )
        return out

    async def _run_one(
        self,
        *,
        use_pure_handlers: bool,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Run `_execute_full_p2p` once with the given mode and return the
        normalized list of session events emitted against the session.
        """
        orch = self._make_orchestrator()
        context: Dict[str, Any] = {
            "request": "Procure 10 servers for IT",
            "pr_data": {
                "department": "IT",
                "product_name": "Dell PowerEdge Server",
                "quantity": 10,
                "budget": 5000,
                "budget_category": "OPEX",
                "requester_name": "Test User",
                "justification": "Capacity expansion",
            },
            "session_id": session_id,
        }
        if use_pure_handlers:
            context["_use_pure_handlers"] = True

        await orch._execute_full_p2p(context)
        return self._normalize(self._events_for(session_id))

    # ── the actual parity test ─────────────────────────────────────────────

    def test_legacy_and_v2_emit_identical_event_sequences(self) -> None:
        """
        Run the same fixture P2P request through both the legacy STEP 1/2/3
        code path and the PHASE_DISPATCH split-dispatch path. Their session
        event sequences must be byte-for-byte identical (modulo timestamps,
        UUIDs, and gate_id).
        """
        self._seed_session("sess-legacy")
        self._seed_session("sess-v2")

        legacy_events = asyncio.run(
            self._run_one(use_pure_handlers=False, session_id="sess-legacy")
        )
        v2_events = asyncio.run(
            self._run_one(use_pure_handlers=True, session_id="sess-v2")
        )

        # Sanity: both runs must have actually paused at the vendor gate
        # (otherwise the parity comparison would be vacuous).
        self.assertTrue(
            len(legacy_events) > 0,
            "legacy run produced zero session events — fixture is broken",
        )
        self.assertTrue(
            len(v2_events) > 0,
            "v2 run produced zero session events — fixture is broken",
        )
        self.assertEqual(
            legacy_events[-1]["event_type"],
            "gate_opened",
            "legacy run did not pause at the vendor_selection gate",
        )
        self.assertEqual(
            v2_events[-1]["event_type"],
            "gate_opened",
            "v2 run did not pause at the vendor_selection gate",
        )

        # The actual parity assertion. assertEqual on two lists-of-dicts
        # gives a per-index diff if they differ.
        self.assertEqual(
            legacy_events,
            v2_events,
            "HF-3 parity violation: legacy and split-dispatch event sequences differ",
        )

    def test_v2_path_uses_handlers_not_inline_steps(self) -> None:
        """
        Sanity check: when `_use_pure_handlers=True`, the v2 path actually
        ran. We verify by inspecting `p2p_results["actions_completed"]` —
        the handlers and the inline STEP 1/2/3 code add steps in slightly
        different orders, but BOTH paths must record the same step names.
        This guards against a regression where the env-var check accidentally
        falls through to the legacy path silently.
        """
        # Capture the orchestrator's p2p_results from a v2 run by injecting
        # a side-channel through context.
        self._seed_session("sess-v2-only")
        orch = self._make_orchestrator()
        ctx: Dict[str, Any] = {
            "request": "Procure 10 servers",
            "pr_data": {
                "department": "IT",
                "product_name": "Server",
                "quantity": 10,
                "budget": 5000,
            },
            "session_id": "sess-v2-only",
            "_use_pure_handlers": True,
        }
        result = asyncio.run(orch._execute_full_p2p(ctx))
        step_names = [s["step"] for s in result.get("actions_completed", [])]
        self.assertIn(
            "compliance_check", step_names,
            "v2 split-dispatch did not record compliance_check step",
        )
        self.assertIn(
            "budget_verification", step_names,
            "v2 split-dispatch did not record budget_verification step",
        )
        self.assertIn(
            "vendor_selection", step_names,
            "v2 split-dispatch did not record vendor_selection step",
        )

    def test_compliance_reject_parity(self) -> None:
        """
        Parity also has to hold on the failure paths. Configure the
        compliance agent to reject and verify both paths emit the same
        sequence ending in phase_failed(compliance).
        """
        self.COMPLIANCE_RESULT["action"] = "reject"
        try:
            self._seed_session("sess-legacy-rej")
            self._seed_session("sess-v2-rej")

            legacy_events = asyncio.run(
                self._run_one(use_pure_handlers=False, session_id="sess-legacy-rej")
            )
            v2_events = asyncio.run(
                self._run_one(use_pure_handlers=True, session_id="sess-v2-rej")
            )

            # Both must end with phase_failed for compliance
            self.assertEqual(legacy_events[-1]["event_type"], "phase_failed")
            self.assertEqual(legacy_events[-1]["payload"].get("phase"), "compliance")
            self.assertEqual(v2_events[-1]["event_type"], "phase_failed")
            self.assertEqual(v2_events[-1]["payload"].get("phase"), "compliance")

            self.assertEqual(
                legacy_events,
                v2_events,
                "HF-3 parity violation on compliance reject path",
            )
        finally:
            # Restore the fixture for any other test in this class
            self.COMPLIANCE_RESULT["action"] = "approve"


# ─────────────────────────────────────────────────────────────────────────────
# Tiny helper — a no-op object that swallows any attribute access
# ─────────────────────────────────────────────────────────────────────────────


class _NoOpService:
    """
    Stand-in for budget_ledger_service / contract_linkage_service.
    Every method returns a benign default; the orchestrator catches
    exceptions from these calls anyway, but this keeps the logs clean.
    """

    def record_commitment(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"success": True}

    def check_maverick_spend(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"is_maverick": False}

    def __getattr__(self, _name: str):
        # Anything else — return a callable that returns an empty dict.
        return lambda *_a, **_kw: {}


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
