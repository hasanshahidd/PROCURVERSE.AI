"""
HF-3 / R14 — Pure phase handlers for the P2P workflow.

Each handler is an async callable of the form:

    async def handle_<phase>(orch, context, helpers) -> HandlerResult

Handlers are pure responders — they receive an immutable snapshot of the
session at entry (context["_sess_snapshot"]), execute exactly one logical
unit of work, and return a HandlerResult naming the next phase. They never
call each other and never re-read session state mid-execution.

Scope of this module (P1.5):
  - Only the PRE-GATE phases (compliance, budget, vendor) are extracted
    into pure handlers. These are the phases with zero ERP side-effects
    and no transactional outbox writes, so the refactor risk is minimal.
  - The full extraction of gate / PR / approval / PO / GRN / invoice /
    payment handlers happens incrementally in follow-up PRs, each gated
    on the parity test passing.
  - `_execute_full_p2p_v2` in orchestrator.py dispatches through
    PHASE_DISPATCH for the phases that have handlers and falls back to
    the legacy monolithic path for the rest. This "split dispatch"
    keeps the feature flag usable while the refactor is partial.

Per the plan, agents are NOT aware of sessions. Handlers wrap agent calls
with helpers.emit() and helpers.add_step() side-effects; agents see only
their normal `execute(context)` contract.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from backend.agents.handler_types import HandlerResult, HandlerHelpers

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Handler implementations
# ─────────────────────────────────────────────────────────────────────────────


async def handle_compliance(
    orch: Any,
    context: Dict[str, Any],
    helpers: HandlerHelpers,
) -> HandlerResult:
    """
    Phase 1: Compliance check.

    Returns:
      next_phase="budget"      on normal pass
      next_phase=None, status="paused_human"  on human review required
      next_phase=None, status="failed"        on compliance rejection
    """
    input_context = context.get("input_context", context)
    p2p_results = context.get("_p2p_results") or {}

    if "compliance_check" not in orch.specialized_agents:
        helpers.add_step("compliance_check", "skipped", "Agent not available")
        return HandlerResult(next_phase="budget", status="running")

    logger.info("[P2P-v2] STEP 1/15: Compliance check...")
    helpers.emit("phase_started", {"phase": "compliance"})

    # Sprint C (2026-04-11): agent_activity events bracket every agent call
    # so the Sprint D LiveActivityTicker can show "Now: ComplianceCheckAgent
    # is observing policy rules...". Closed vocabulary: observing / deciding
    # / acting / learning. Unknown event types pass through the useSession
    # reducer untouched (stored in events[] for Sprint D to fold).
    helpers.emit("agent_activity", {
        "agent": "ComplianceCheckAgent",
        "phase": "compliance",
        "lifecycle": "observing",
        "detail": "Gathering policy rules and request context",
    })
    try:
        comp_result = await orch._get_agent("compliance_check").execute(input_context)
    except Exception as exc:
        helpers.emit("phase_failed", {"phase": "compliance", "error": str(exc)})
        return HandlerResult(next_phase=None, status="failed", error=str(exc))
    helpers.emit("agent_activity", {
        "agent": "ComplianceCheckAgent",
        "phase": "compliance",
        "lifecycle": "acting",
        "detail": f"Decision: {comp_result.get('action') or comp_result.get('result', {}).get('action') or 'passed'}",
    })

    comp_action = comp_result.get("action") or comp_result.get("result", {}).get("action")
    p2p_results.setdefault("agents_invoked", []).append(
        orch._get_agent("compliance_check").name
    )
    p2p_results.setdefault("validations", {})["compliance"] = comp_result

    # Universal human-gate check
    check_fn = context.get("_check_human_gate")
    if check_fn and check_fn("compliance_check", comp_result, "ComplianceCheckAgent"):
        helpers.add_step(
            "compliance_check", "awaiting_input",
            "Human review needed", "ComplianceCheckAgent",
        )
        helpers.emit("phase_failed", {"phase": "compliance", "reason": "needs_human_review"})
        return HandlerResult(next_phase=None, status="paused_human")

    if comp_action == "reject":
        helpers.track_task("compliance_check", failed=True, error_msg="Compliance rejected")
        helpers.add_step(
            "compliance_check", "rejected",
            "Compliance check rejected this request", "ComplianceCheckAgent",
        )
        p2p_results["status"] = "failed"
        p2p_results["summary"] = "P2P workflow blocked: compliance check rejected."
        p2p_results["suggested_next_actions"] = [
            "Review compliance rules", "Modify request and retry"
        ]
        helpers.emit("phase_failed", {"phase": "compliance", "reason": "rejected"})
        return HandlerResult(next_phase=None, status="failed", error="rejected")

    helpers.track_task("compliance_check", {"action": comp_action, "passed": True})

    # Sprint C (2026-04-11): compute comp_inner BEFORE emit so the
    # phase_completed payload carries the same data the legacy add_step
    # used to hide in pipelineStore. SessionPage's PhaseDetailCard (Sprint
    # D) will render these; the GenericGatePanel already does via the
    # decision_context JSON drawer if this was a gate, but phase_completed
    # is the non-gate path so we enrich here directly.
    comp_inner = (
        comp_result.get("result", comp_result)
        if isinstance(comp_result.get("result"), dict)
        else comp_result
    )
    helpers.emit(
        "phase_completed",
        {
            "phase": "compliance",
            "action": comp_action,
            "compliance_score": comp_inner.get("compliance_score"),
            "compliance_level": comp_inner.get("compliance_level"),
            "warnings": comp_inner.get("warnings", []),
            "violations": comp_inner.get("violations", []),
            "policies_checked": comp_inner.get("policies_checked", []),
        },
    )

    comp_summary_parts = [f"Score: {comp_inner.get('compliance_score', 'N/A')}"]
    if comp_inner.get("warnings"):
        comp_summary_parts.append(f"{len(comp_inner['warnings'])} warning(s)")
    helpers.add_step(
        "compliance_check", "passed", " | ".join(comp_summary_parts),
        "ComplianceCheckAgent",
        data={
            "compliance_score": comp_inner.get("compliance_score"),
            "compliance_level": comp_inner.get("compliance_level"),
            "warnings": comp_inner.get("warnings", []),
            "violations": comp_inner.get("violations", []),
        },
    )
    return HandlerResult(next_phase="budget", status="running")


async def handle_budget(
    orch: Any,
    context: Dict[str, Any],
    helpers: HandlerHelpers,
) -> HandlerResult:
    """
    Phase 2: Budget verification.

    Returns:
      next_phase="vendor"   on sufficient budget
      next_phase=None, status="paused_human"  on human review required
      next_phase=None, status="failed"        on insufficient budget
    """
    input_context = context.get("input_context", context)
    pr_data = input_context.get("pr_data", {})
    p2p_results = context.get("_p2p_results") or {}

    if "budget_verification" not in orch.specialized_agents:
        helpers.add_step("budget_verification", "skipped", "Agent not available")
        return HandlerResult(next_phase="vendor", status="running")

    logger.info("[P2P-v2] STEP 2/15: Budget verification...")
    helpers.emit("phase_started", {"phase": "budget"})

    # Sprint C (2026-04-11): agent_activity bracket for LiveActivityTicker.
    helpers.emit("agent_activity", {
        "agent": "BudgetVerificationAgent",
        "phase": "budget",
        "lifecycle": "observing",
        "detail": f"Reading budget ledger for {pr_data.get('department', 'department')}",
    })
    budget_ctx = {**input_context, "reserve_budget": False}
    try:
        budget_result = await orch._get_agent("budget_verification").execute(budget_ctx)
    except Exception as exc:
        helpers.emit("phase_failed", {"phase": "budget", "error": str(exc)})
        return HandlerResult(next_phase=None, status="failed", error=str(exc))
    _budget_inner_peek = (
        budget_result.get("result", {})
        if isinstance(budget_result.get("result"), dict)
        else {}
    )
    helpers.emit("agent_activity", {
        "agent": "BudgetVerificationAgent",
        "phase": "budget",
        "lifecycle": "acting",
        "detail": f"Available: ${_budget_inner_peek.get('available_budget', 'n/a')}",
    })

    budget_action = (
        budget_result.get("action")
        or budget_result.get("result", {}).get("action")
    )
    budget_inner = (
        budget_result.get("result", {})
        if isinstance(budget_result.get("result"), dict)
        else {}
    )
    p2p_results.setdefault("agents_invoked", []).append(
        orch._get_agent("budget_verification").name
    )
    p2p_results.setdefault("validations", {})["budget"] = budget_result

    check_fn = context.get("_check_human_gate")
    if check_fn and check_fn("budget_verification", budget_result, "BudgetVerificationAgent"):
        helpers.add_step(
            "budget_verification", "awaiting_input",
            "Human review needed", "BudgetVerificationAgent",
        )
        helpers.emit("phase_failed", {"phase": "budget", "reason": "needs_human_review"})
        return HandlerResult(next_phase=None, status="paused_human")

    budget_failed = (
        budget_result.get("status") == "error"
        or budget_action in {"block", "reject", "reject_insufficient_budget"}
        or str(budget_inner.get("status", "")).lower() in {"rejected", "error"}
        or budget_inner.get("budget_verified") is False
    )
    if budget_failed:
        helpers.track_task("budget_verification", failed=True, error_msg="Insufficient budget")
        avail = budget_inner.get("available_budget", "N/A")
        helpers.add_step(
            "budget_verification", "rejected",
            f"Insufficient budget (available: ${avail})",
            "BudgetVerificationAgent",
        )
        p2p_results["status"] = "failed"
        p2p_results["summary"] = (
            f"P2P workflow blocked: insufficient budget. Available: ${avail}."
        )
        p2p_results["suggested_next_actions"] = [
            "Request budget increase", "Reduce order quantity"
        ]
        helpers.emit("phase_failed", {"phase": "budget", "reason": "insufficient_budget"})
        return HandlerResult(next_phase=None, status="failed", error="insufficient_budget")

    raw_avail = budget_inner.get(
        "available_budget", budget_inner.get("current_budget", "")
    )
    try:
        avail_str = (
            f"{float(str(raw_avail).replace(',', '')):,.0f}"
            if raw_avail and str(raw_avail).replace(",", "").replace(".", "").isdigit()
            else (raw_avail or "confirmed")
        )
    except (ValueError, TypeError):
        avail_str = str(raw_avail) if raw_avail else "confirmed"
    util = budget_inner.get(
        "utilization",
        budget_inner.get("utilization_percentage", budget_inner.get("utilization_after_approval", "")),
    )

    # Sprint C (2026-04-11): enrich phase_completed so SessionPage does not
    # need to re-fetch budget context from the ERP adapter. Fields mirror
    # BudgetVerificationAgent's result shape (total_budget, committed,
    # available, department, source_account). Missing fields are omitted
    # so the payload stays small and safe.
    helpers.emit(
        "phase_completed",
        {
            "phase": "budget",
            "available": budget_inner.get("available_budget"),
            "total_budget": budget_inner.get("total_budget"),
            "committed": budget_inner.get("committed"),
            "budget_remaining": budget_inner.get(
                "budget_remaining", budget_inner.get("available_budget")
            ),
            "utilization_pct": util,
            "department": budget_inner.get("department", pr_data.get("department", "")),
            "source_account": budget_inner.get("source_account"),
            "budget_verified": budget_inner.get("budget_verified"),
        },
    )
    helpers.track_task("budget_verification", {"budget_verified": True})
    helpers.add_step(
        "budget_verification", "approved",
        f"Budget verified — ${avail_str} available"
        + (f", {util}% utilized" if util else ""),
        "BudgetVerificationAgent",
        data={
            "available_budget": avail_str,
            "utilization": util,
            "department": budget_inner.get("department", pr_data.get("department", "")),
        },
    )

    # G-08: Record budget commitment in ledger (non-blocking)
    try:
        from backend.services.budget_ledger_service import get_budget_ledger_service
        _bl = get_budget_ledger_service()
        _bl.record_commitment(
            department=pr_data.get("department", "General"),
            fiscal_year=None,
            reference_type="PR",
            reference_id=f"P2P-{context.get('workflow_run_id') or 'UNKNOWN'}",
            amount=float(pr_data.get("budget") or pr_data.get("total_amount") or 0),
            description=f"P2P budget commitment for {pr_data.get('product_name', 'procurement')}",
        )
        logger.info("[P2P-v2] G-08: Budget commitment recorded in ledger")
    except Exception as _bl_err:
        logger.debug("[P2P-v2] G-08: Budget ledger (non-blocking): %s", _bl_err)

    return HandlerResult(next_phase="vendor", status="running")


async def handle_vendor(
    orch: Any,
    context: Dict[str, Any],
    helpers: HandlerHelpers,
) -> HandlerResult:
    """
    Phase 3: Vendor selection + ranking.

    This handler runs the vendor agent and stores the ranked options on
    the shared p2p_results dict. It does NOT open the vendor_selection
    gate — that happens in the dedicated handle_vendor_selection handler
    during the full extraction. For P1.5 the caller falls back to the
    legacy gate path after this handler returns.
    """
    input_context = context.get("input_context", context)
    p2p_results = context.get("_p2p_results") or {}

    if "vendor_selection" not in orch.specialized_agents:
        # Legacy parity: when the vendor agent is missing the pipeline logs
        # "skipped" for both vendor_selection AND vendor_confirmation, then
        # falls through to STEP 4.5 (risk assessment). Signal "handlers done,
        # fall through to legacy" via next_phase=None + status="running".
        helpers.add_step("vendor_selection", "skipped", "Agent not available")
        helpers.add_step("vendor_confirmation", "skipped", "No vendor selection")
        return HandlerResult(next_phase=None, status="running")

    logger.info("[P2P-v2] STEP 3/15: Vendor selection...")
    helpers.emit("phase_started", {"phase": "vendor"})

    # Sprint C (2026-04-11): agent_activity bracket for LiveActivityTicker.
    helpers.emit("agent_activity", {
        "agent": "VendorSelectionAgent",
        "phase": "vendor",
        "lifecycle": "observing",
        "detail": "Loading vendor master and past performance history",
    })
    try:
        vendor_result = await orch._get_agent("vendor_selection").execute(input_context)
    except Exception as exc:
        helpers.emit("phase_failed", {"phase": "vendor", "error": str(exc)})
        return HandlerResult(next_phase=None, status="failed", error=str(exc))
    helpers.emit("agent_activity", {
        "agent": "VendorSelectionAgent",
        "phase": "vendor",
        "lifecycle": "acting",
        "detail": "Scoring and ranking candidates on price + delivery + risk",
    })

    p2p_results.setdefault("agents_invoked", []).append(
        orch._get_agent("vendor_selection").name
    )
    p2p_results.setdefault("validations", {})["vendor"] = vendor_result
    helpers.track_task("vendor_selection", {"vendors_found": True})

    top_vendor_options = orch._extract_vendor_options(vendor_result)
    p2p_results["top_vendor_options"] = top_vendor_options
    top_vendor_name = (
        top_vendor_options[0].get("vendor_name", "") if top_vendor_options else ""
    )
    vendor_count = len(top_vendor_options)
    vendor_summary = (
        f"Top vendor: {top_vendor_name} ({vendor_count} options)"
        if top_vendor_name
        else f"{vendor_count} vendors shortlisted"
    )
    helpers.add_step(
        "vendor_selection",
        "completed",
        vendor_summary,
        "VendorSelectionAgent",
        data={
            "top_vendor": top_vendor_name,
            "vendor_count": vendor_count,
            "vendors": [
                {"name": v.get("vendor_name"), "score": v.get("total_score", v.get("score"))}
                for v in top_vendor_options[:5]
            ],
        },
    )
    # Sprint C (2026-04-11): include the vendors[] array on phase_completed
    # so VendorSelectionPanel has all the scoring context it needs directly
    # from the event stream. Keep payloads safe via .get() with defaults.
    vendors_rich = [
        {
            "vendor_id": v.get("vendor_id"),
            "vendor_name": v.get("vendor_name"),
            "total_score": v.get("total_score", v.get("score")),
            "price": v.get("price", v.get("unit_price")),
            "delivery_days": v.get("delivery_days"),
            "quality_score": v.get("quality_score"),
            "compliance_score": v.get("compliance_score"),
            "risk_score": v.get("risk_score"),
            "recommendation": v.get("recommendation"),
        }
        for v in top_vendor_options[:5]
    ]
    helpers.emit(
        "phase_completed",
        {
            "phase": "vendor",
            "ref": {"vendor_count": vendor_count},
            "top_vendor": top_vendor_name,
            "vendor_count": vendor_count,
            "vendors": vendors_rich,
        },
    )

    # P1.5: return to the dispatcher with next_phase="vendor_selection".
    # The split-dispatch branch in the orchestrator opens the vendor_selection
    # gate inline; the dedicated gate handler lands in a follow-up PR.
    return HandlerResult(next_phase="vendor_selection", status="running")


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch map
# ─────────────────────────────────────────────────────────────────────────────

# Only the phases whose handlers are implemented in this module appear here.
# The v2 dispatcher falls back to the legacy path for any phase not listed.
PHASE_DISPATCH: Dict[str, Any] = {
    "compliance": handle_compliance,
    "budget":     handle_budget,
    "vendor":     handle_vendor,
}
