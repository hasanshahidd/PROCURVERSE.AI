"""
Pipeline Orchestrator — Sprint 8
==================================
Liztek Procure-AI: Chains all 9 agents in the Invoice-to-Payment pipeline.

Architecture
------------
InvoicePipelineOrchestrator
  ├── run_po_intake()             → POIntakeAgent
  ├── run_po_registration()       → PORegistrationAgent
  ├── run_invoice_capture()       → InvoiceCaptureAgent
  ├── run_invoice_routing()       → InvoiceRoutingAgent
  ├── run_invoice_matching()      → InvoiceMatchingAgent  (via invoice_matching module)
  ├── run_discrepancy_resolution()→ DiscrepancyResolutionAgent
  ├── run_payment_readiness()     → PaymentReadinessAgent
  ├── run_payment_calculation()   → PaymentCalculationAgent
  ├── run_payment_approval()      → PaymentApprovalAgent
  └── run_full_pipeline()         → chains all 9 steps with timing + error recovery

Usage
-----
    from backend.services.pipeline_orchestrator import InvoicePipelineOrchestrator

    orchestrator = InvoicePipelineOrchestrator()

    # Run full pipeline
    result = await orchestrator.run_full_pipeline(
        po_document={"document_ref": "PO-2025-001", "raw_content": "..."},
        invoice_document={"document_ref": "INV-2025-001", "raw_content": "..."},
    )

    # Run individual steps
    po_result = await orchestrator.run_po_intake({"document_ref": "PO-001"})

    # Dry run (skips DB writes — agents still execute logic but not persist)
    result = await orchestrator.run_full_pipeline(
        po_document=..., invoice_document=..., dry_run=True
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Context merge helper (module-level, used by convenience sub-pipelines) ────

def _merge_result_into(context: dict, result: dict) -> None:
    """Merge an agent result dict into a shared pipeline context.

    BaseAgent.execute_with_recovery() returns:
      {"status": "success", "agent": "...", "decision": {...}, "result": {<payload>}}

    We merge BOTH the wrapper-level fields (minus the nested "result" key) AND the
    inner "result" payload so that downstream steps can read invoice_number,
    payment_run_number, extracted_fields, etc. directly from context.
    Inner (payload) fields win over wrapper fields on key collision (e.g. "status").
    """
    context.update(
        {k: v for k, v in result.items() if v is not None and k != "result"}
    )
    inner = result.get("result")
    if isinstance(inner, dict):
        context.update({k: v for k, v in inner.items() if v is not None})


# ── Step result helper ────────────────────────────────────────────────────────

def _step_result(
    step: str,
    agent_name: str,
    result: dict,
    elapsed_ms: int,
    error: Optional[str] = None,
) -> dict:
    """Build a standardised per-step result entry.

    BaseAgent.execute_with_recovery() wraps the real payload in a 'result' key.
    Check the inner dict's 'success' flag first, then fall back to outer level.
    """
    if error:
        success = False
    elif result.get("status") == "error":
        success = False
    else:
        inner = result.get("result")
        if isinstance(inner, dict):
            success = inner.get("success", True)
        else:
            success = result.get("success", True)

    return {
        "step":       step,
        "agent":      agent_name,
        "elapsed_ms": elapsed_ms,
        "success":    success,
        "result":     result,
        "error":      error,
    }


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


# ── Orchestrator ──────────────────────────────────────────────────────────────

class InvoicePipelineOrchestrator:
    """
    Orchestrates the 9-agent Liztek Invoice-to-Payment pipeline.

    Each step's output is merged into the shared context dict, which is
    passed as input to the next step. This allows downstream agents to
    pick up PO numbers, invoice numbers, vendor IDs, etc. without callers
    having to manually wire them.

    On failure in any step, the orchestrator captures the error in the
    step result and returns a partial pipeline result with
    pipeline_success=False and the step that failed.

    Parameters
    ----------
    dry_run : bool (set per-call via run_full_pipeline)
        When True, adds dry_run=True to every agent's input_data.
        Agents that respect this flag will skip database writes.
    """

    # ── Individual step runners ───────────────────────────────────────────────

    async def run_po_intake(self, document_data: Dict[str, Any]) -> dict:
        """
        Step 1 — POIntakeAgent.

        Input keys (required):
          document_ref    — filename / email subject / EDI ref
          source_channel  — 'email'|'portal'|'edi'|'api'|'scan'
          raw_content     — raw OCR / document text

        Returns the agent's execute() result dict.
        """
        from backend.agents.po_intake_agent import POIntakeAgent
        agent = POIntakeAgent()
        return await agent.execute(document_data)

    async def run_po_registration(self, po_data: Dict[str, Any]) -> dict:
        """
        Step 2 — PORegistrationAgent.

        Input keys (from po_intake result + any additions):
          extracted_fields  — dict from OCR step (po_number, vendor, etc.)
          vendor_record     — matched vendor dict (optional)
          document_ref      — original document reference
        """
        from backend.agents.po_registration_agent import PORegistrationAgent
        agent = PORegistrationAgent()
        return await agent.execute(po_data)

    async def run_invoice_capture(self, invoice_data: Dict[str, Any]) -> dict:
        """
        Step 3 — InvoiceCaptureAgent.

        Input keys:
          document_ref    — filename / email subject
          source_channel  — 'email'|'portal'|'edi'|'api'|'scan'
          raw_content     — raw OCR / document text
          receipt_date    — ISO date string (optional; defaults to today)
        """
        from backend.agents.invoice_capture_agent import InvoiceCaptureAgent
        agent = InvoiceCaptureAgent()
        return await agent.execute(invoice_data)

    async def run_invoice_routing(self, routing_data: Dict[str, Any]) -> dict:
        """
        Step 4 — InvoiceRoutingAgent.

        Input keys (from invoice_capture result):
          invoice_number    — captured invoice number
          vendor_id         — vendor identifier
          extracted_fields  — invoice field dict
        """
        from backend.agents.invoice_routing_agent import InvoiceRoutingAgent
        agent = InvoiceRoutingAgent()
        return await agent.execute(routing_data)

    async def run_invoice_matching(self, match_data: Dict[str, Any]) -> dict:
        """
        Step 5 — InvoiceMatchingAgent (3-way match: PO / GRN / Invoice).

        Input keys:
          invoice_number   — invoice to match
          po_reference     — purchase order reference
          vendor_id        — vendor identifier
        """
        from backend.agents.invoice_matching import InvoiceMatchingAgent
        agent = InvoiceMatchingAgent()
        return await agent.execute(match_data)

    async def run_discrepancy_resolution(self, disc_data: Dict[str, Any]) -> dict:
        """
        Step 6 — DiscrepancyResolutionAgent.

        Input keys:
          invoice_number  — invoice with potential discrepancies
          match_result    — result dict from invoice_matching step
          po_reference    — purchase order reference
        """
        from backend.agents.discrepancy_resolution_agent import DiscrepancyResolutionAgent
        agent = DiscrepancyResolutionAgent()
        return await agent.execute(disc_data)

    async def run_payment_readiness(self, readiness_data: Dict[str, Any]) -> dict:
        """
        Step 7 — PaymentReadinessAgent.

        Input keys:
          invoice_number  — invoice being checked
          vendor_id       — vendor identifier
          po_reference    — purchase order reference (optional)

        Checks 7 conditions: match_passed, no_active_holds, budget_available,
        not_overdue, payment_terms_match, vendor_not_sanctioned, approved.
        """
        from backend.agents.payment_readiness_agent import PaymentReadinessAgent
        agent = PaymentReadinessAgent()
        return await agent.execute(readiness_data)

    async def run_payment_calculation(self, calc_data: Dict[str, Any]) -> dict:
        """
        Step 8 — PaymentCalculationAgent.

        Input keys:
          invoice_number      — invoice to calculate payment for
          vendor_id           — vendor identifier
          payment_run_number  — from payment_readiness step
          po_reference        — purchase order reference

        Determines full/partial payment, applies early-payment discount,
        and performs FX conversion to AED.
        """
        from backend.agents.payment_calculation_agent import PaymentCalculationAgent
        agent = PaymentCalculationAgent()
        return await agent.execute(calc_data)

    async def run_payment_approval(self, approval_data: Dict[str, Any]) -> dict:
        """
        Step 9 — PaymentApprovalAgent.

        Input keys:
          invoice_number      — invoice awaiting final approval
          payment_run_number  — from payment_calculation step
          net_payable_aed     — final net payable amount in AED
          vendor_id           — vendor identifier
        """
        from backend.agents.payment_approval_agent import PaymentApprovalAgent
        agent = PaymentApprovalAgent()
        return await agent.execute(approval_data)

    # ── Full pipeline ─────────────────────────────────────────────────────────

    async def run_full_pipeline(
        self,
        po_document: Dict[str, Any],
        invoice_document: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Run the complete 9-agent PO → Invoice → Payment pipeline.

        Parameters
        ----------
        po_document       : dict — PO input (document_ref, source_channel, raw_content, ...)
        invoice_document  : dict — Invoice input (document_ref, source_channel, raw_content, ...)
        dry_run           : bool — if True, passes dry_run=True to all agents

        Returns
        -------
        dict with keys:
          pipeline_success  : bool — True if all steps succeeded
          total_elapsed_ms  : int  — total wall-clock time in milliseconds
          failed_step       : str | None — name of first failed step (or None)
          steps             : list[dict] — per-step results with timing
          context           : dict — accumulated pipeline context (all fields merged)
          summary           : dict — high-level summary for caller display
        """
        pipeline_start = _now_ms()
        steps: List[dict] = []
        context: Dict[str, Any] = {}
        failed_step: Optional[str] = None

        def _merge(result: dict) -> None:
            """Merge agent result into shared context (delegates to module-level helper)."""
            _merge_result_into(context, result)

        def _is_agent_failed(result: dict) -> bool:
            """Return True when the agent reported a hard failure that should halt the pipeline."""
            # Outer wrapper failure (exception path)
            if result.get("status") == "error":
                return True
            # Inner result failure flag
            inner = result.get("result")
            if isinstance(inner, dict):
                return inner.get("success") is False
            # Legacy flat format (agents not using execute_with_recovery)
            return result.get("success") is False

        def _inject_dry_run(data: dict) -> dict:
            if dry_run:
                return {**data, "dry_run": True}
            return data

        # ── Step 1: PO Intake ─────────────────────────────────────────────────
        step_name = "1_po_intake"
        step_start = _now_ms()
        try:
            step_input = _inject_dry_run({**po_document})
            result = await self.run_po_intake(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "POIntakeAgent", result, elapsed))
            _merge(result)

            if _is_agent_failed(result):
                failed_step = step_name
                logger.warning("[Pipeline] Step %s failed — stopping.", step_name)
                return _build_pipeline_result(steps, context, failed_step, pipeline_start)

            logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "POIntakeAgent", {}, elapsed, str(exc)))
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Step 2: PO Registration ───────────────────────────────────────────
        step_name = "2_po_registration"
        step_start = _now_ms()
        try:
            step_input = _inject_dry_run({
                **po_document,
                **context,
                "extracted_fields": context.get("extracted_fields", {}),
                "vendor_record":    context.get("vendor_record"),
            })
            result = await self.run_po_registration(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "PORegistrationAgent", result, elapsed))
            _merge(result)
            logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "PORegistrationAgent", {}, elapsed, str(exc)))
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Step 3: Invoice Capture ───────────────────────────────────────────
        step_name = "3_invoice_capture"
        step_start = _now_ms()
        try:
            step_input = _inject_dry_run({**invoice_document})
            result = await self.run_invoice_capture(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "InvoiceCaptureAgent", result, elapsed))
            _merge(result)

            if _is_agent_failed(result):
                failed_step = step_name
                logger.warning("[Pipeline] %s failed — stopping.", step_name)
                return _build_pipeline_result(steps, context, failed_step, pipeline_start)

            logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "InvoiceCaptureAgent", {}, elapsed, str(exc)))
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Step 4: Invoice Routing ───────────────────────────────────────────
        step_name = "4_invoice_routing"
        step_start = _now_ms()
        try:
            inv_fields = context.get("extracted_fields", {})
            step_input = _inject_dry_run({
                "invoice_number":  context.get("invoice_number") or inv_fields.get("invoice_number"),
                "vendor_id":       context.get("vendor_id", ""),
                "extracted_fields": inv_fields,
                "linked_po":       context.get("linked_po"),
                "receipt_date":    context.get("receipt_date"),
                "document_ref":    context.get("document_ref"),
                "source_channel":  context.get("source_channel"),
                "confidence":      context.get("confidence", 0.0),
            })
            result = await self.run_invoice_routing(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "InvoiceRoutingAgent", result, elapsed))
            _merge(result)
            logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "InvoiceRoutingAgent", {}, elapsed, str(exc)))
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Step 5: Invoice Matching ──────────────────────────────────────────
        step_name = "5_invoice_matching"
        step_start = _now_ms()
        try:
            inv_fields = context.get("extracted_fields", {})
            step_input = _inject_dry_run({
                "invoice_number": (
                    context.get("invoice_number")
                    or inv_fields.get("invoice_number")
                ),
                "po_reference":   (
                    context.get("po_reference")
                    or context.get("po_number")
                    or inv_fields.get("po_number")
                ),
                "vendor_id":      context.get("vendor_id", ""),
                "extracted_fields": inv_fields,
            })
            result = await self.run_invoice_matching(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "InvoiceMatchingAgent", result, elapsed))
            _merge(result)
            logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "InvoiceMatchingAgent", {}, elapsed, str(exc)))
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Step 6: Discrepancy Resolution ────────────────────────────────────
        step_name = "6_discrepancy_resolution"
        step_start = _now_ms()
        try:
            step_input = _inject_dry_run({
                "invoice_number": context.get("invoice_number"),
                "po_reference":   context.get("po_reference") or context.get("po_number"),
                "vendor_id":      context.get("vendor_id", ""),
                "match_result":   context,  # pass full context as match_result for agent
            })
            result = await self.run_discrepancy_resolution(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "DiscrepancyResolutionAgent", result, elapsed))
            _merge(result)
            logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(
                _step_result(step_name, "DiscrepancyResolutionAgent", {}, elapsed, str(exc))
            )
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Step 7: Payment Readiness ─────────────────────────────────────────
        step_name = "7_payment_readiness"
        step_start = _now_ms()
        try:
            step_input = _inject_dry_run({
                "invoice_number": context.get("invoice_number"),
                "vendor_id":      context.get("vendor_id", ""),
                "po_reference":   context.get("po_reference") or context.get("po_number"),
            })
            result = await self.run_payment_readiness(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "PaymentReadinessAgent", result, elapsed))
            _merge(result)

            # After _merge the inner fields are promoted into context.
            # Check the inner result for hold/on_hold status.
            _inner7 = result.get("result") or result
            if _inner7.get("status") == "on_hold":
                # Holds placed — pipeline continues (payment will be blocked downstream)
                logger.warning(
                    "[Pipeline] %s placed holds: %s",
                    step_name,
                    _inner7.get("failed_conditions") or context.get("failed_conditions"),
                )
            else:
                logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(
                _step_result(step_name, "PaymentReadinessAgent", {}, elapsed, str(exc))
            )
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Step 8: Payment Calculation ───────────────────────────────────────
        step_name = "8_payment_calculation"
        step_start = _now_ms()
        try:
            # invoice_amount may live in extracted_fields.total_amount when the
            # caller hasn't passed it explicitly and the invoice is not in DB.
            _inv_fields = context.get("extracted_fields") or {}
            _inv_amount = (
                context.get("invoice_amount")
                or _inv_fields.get("total_amount")
                or _inv_fields.get("invoice_amount")
                or 0
            )
            step_input = _inject_dry_run({
                "invoice_number":     context.get("invoice_number"),
                "vendor_id":          context.get("vendor_id", ""),
                "po_reference":       context.get("po_reference") or context.get("po_number"),
                "payment_run_number": context.get("payment_run_number"),
                "invoice_amount":     _inv_amount,
                "currency":           context.get("invoice_currency", "AED"),
                "due_date":           context.get("invoice_due_date"),
            })
            result = await self.run_payment_calculation(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "PaymentCalculationAgent", result, elapsed))
            _merge(result)
            logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(
                _step_result(step_name, "PaymentCalculationAgent", {}, elapsed, str(exc))
            )
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Step 9: Payment Approval ──────────────────────────────────────────
        step_name = "9_payment_approval"
        step_start = _now_ms()
        try:
            step_input = _inject_dry_run({
                "invoice_number":     context.get("invoice_number"),
                "payment_run_number": context.get("payment_run_number"),
                "net_payable_aed":    context.get("net_payable_aed", 0),
                "vendor_id":          context.get("vendor_id", ""),
                "po_reference":       context.get("po_reference") or context.get("po_number"),
                "payment_type":       context.get("payment_type", "full"),
                "invoice_currency":   context.get("invoice_currency", "AED"),
                "fx_rate":            context.get("fx_rate", 1.0),
            })
            result = await self.run_payment_approval(step_input)
            elapsed = _now_ms() - step_start
            steps.append(_step_result(step_name, "PaymentApprovalAgent", result, elapsed))
            _merge(result)
            logger.info("[Pipeline] %s OK (%dms)", step_name, elapsed)

        except Exception as exc:
            elapsed = _now_ms() - step_start
            steps.append(
                _step_result(step_name, "PaymentApprovalAgent", {}, elapsed, str(exc))
            )
            failed_step = step_name
            logger.error("[Pipeline] %s raised: %s", step_name, exc)
            return _build_pipeline_result(steps, context, failed_step, pipeline_start)

        # ── Pipeline complete ─────────────────────────────────────────────────
        return _build_pipeline_result(steps, context, failed_step, pipeline_start)

    # ── Convenience runners for partial pipelines ─────────────────────────────

    async def run_po_pipeline(
        self,
        po_document: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Run only the PO sub-pipeline (steps 1–2).
        Useful for testing PO intake and registration in isolation.
        """
        pipeline_start = _now_ms()
        steps: List[dict] = []
        context: Dict[str, Any] = {}
        failed_step: Optional[str] = None

        for step_name, agent_name, coro_fn in [
            ("1_po_intake",        "POIntakeAgent",        self.run_po_intake),
            ("2_po_registration",  "PORegistrationAgent",  self.run_po_registration),
        ]:
            step_start = _now_ms()
            try:
                step_input = {**po_document, **context}
                if dry_run:
                    step_input["dry_run"] = True
                result = await coro_fn(step_input)
                elapsed = _now_ms() - step_start
                steps.append(_step_result(step_name, agent_name, result, elapsed))
                _merge_result_into(context, result)
            except Exception as exc:
                elapsed = _now_ms() - step_start
                steps.append(_step_result(step_name, agent_name, {}, elapsed, str(exc)))
                failed_step = step_name
                break

        return _build_pipeline_result(steps, context, failed_step, pipeline_start)

    async def run_invoice_pipeline(
        self,
        invoice_document: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Run only the invoice sub-pipeline (steps 3–6).
        Requires a po_reference or po_number in invoice_document if PO linking is needed.
        """
        pipeline_start = _now_ms()
        steps: List[dict] = []
        context: Dict[str, Any] = {}
        failed_step: Optional[str] = None

        for step_name, agent_name, coro_fn in [
            ("3_invoice_capture",         "InvoiceCaptureAgent",        self.run_invoice_capture),
            ("4_invoice_routing",         "InvoiceRoutingAgent",         self.run_invoice_routing),
            ("5_invoice_matching",        "InvoiceMatchingAgent",        self.run_invoice_matching),
            ("6_discrepancy_resolution",  "DiscrepancyResolutionAgent",  self.run_discrepancy_resolution),
        ]:
            step_start = _now_ms()
            try:
                step_input = {**invoice_document, **context}
                if dry_run:
                    step_input["dry_run"] = True
                result = await coro_fn(step_input)
                elapsed = _now_ms() - step_start
                steps.append(_step_result(step_name, agent_name, result, elapsed))
                _merge_result_into(context, result)
            except Exception as exc:
                elapsed = _now_ms() - step_start
                steps.append(_step_result(step_name, agent_name, {}, elapsed, str(exc)))
                failed_step = step_name
                break

        return _build_pipeline_result(steps, context, failed_step, pipeline_start)

    async def run_payment_pipeline(
        self,
        payment_data: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Run only the payment sub-pipeline (steps 7–9).
        Requires invoice_number and optionally po_reference, vendor_id.
        """
        pipeline_start = _now_ms()
        steps: List[dict] = []
        context: Dict[str, Any] = {}
        failed_step: Optional[str] = None

        for step_name, agent_name, coro_fn in [
            ("7_payment_readiness",   "PaymentReadinessAgent",   self.run_payment_readiness),
            ("8_payment_calculation", "PaymentCalculationAgent", self.run_payment_calculation),
            ("9_payment_approval",    "PaymentApprovalAgent",    self.run_payment_approval),
        ]:
            step_start = _now_ms()
            try:
                step_input = {**payment_data, **context}
                if dry_run:
                    step_input["dry_run"] = True
                result = await coro_fn(step_input)
                elapsed = _now_ms() - step_start
                steps.append(_step_result(step_name, agent_name, result, elapsed))
                _merge_result_into(context, result)
            except Exception as exc:
                elapsed = _now_ms() - step_start
                steps.append(_step_result(step_name, agent_name, {}, elapsed, str(exc)))
                failed_step = step_name
                break

        return _build_pipeline_result(steps, context, failed_step, pipeline_start)


# ── Pipeline result builder ───────────────────────────────────────────────────

def _build_pipeline_result(
    steps: List[dict],
    context: Dict[str, Any],
    failed_step: Optional[str],
    pipeline_start_ms: int,
) -> Dict[str, Any]:
    """Build the final pipeline result dict."""
    total_elapsed = _now_ms() - pipeline_start_ms
    pipeline_success = failed_step is None

    # Build high-level summary
    summary: Dict[str, Any] = {
        "steps_run":        len(steps),
        "steps_succeeded":  sum(1 for s in steps if s["success"]),
        "steps_failed":     sum(1 for s in steps if not s["success"]),
        "total_elapsed_ms": total_elapsed,
    }

    # Extract key business fields for summary
    if context.get("invoice_number"):
        summary["invoice_number"] = context["invoice_number"]
    if context.get("payment_run_number"):
        summary["payment_run_number"] = context["payment_run_number"]
    if context.get("net_payable_aed") is not None:
        summary["net_payable_aed"] = context["net_payable_aed"]
    if context.get("payment_type"):
        summary["payment_type"] = context["payment_type"]
    if context.get("invoice_currency"):
        summary["invoice_currency"] = context["invoice_currency"]

    logger.info(
        "[Pipeline] Complete — success=%s, steps=%d/%d, elapsed=%dms, failed_step=%s",
        pipeline_success,
        summary["steps_succeeded"],
        summary["steps_run"],
        total_elapsed,
        failed_step or "none",
    )

    return {
        "pipeline_success":  pipeline_success,
        "total_elapsed_ms":  total_elapsed,
        "failed_step":       failed_step,
        "steps":             steps,
        "context":           context,
        "summary":           summary,
    }


# ── Convenience entry points ──────────────────────────────────────────────────

async def run_full_pipeline(
    po_document: Dict[str, Any],
    invoice_document: Dict[str, Any],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Module-level convenience function for running the full 9-agent pipeline."""
    orchestrator = InvoicePipelineOrchestrator()
    return await orchestrator.run_full_pipeline(
        po_document=po_document,
        invoice_document=invoice_document,
        dry_run=dry_run,
    )
