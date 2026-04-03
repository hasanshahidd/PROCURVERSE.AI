"""
DiscrepancyResolutionAgent — Step 6 of the 9-agent Invoice-to-Payment Pipeline
===============================================================================
Liztek P2P Flow: Discrepancy Triage & Resolution

Receives invoices that failed 3-way matching and decides whether discrepancies
can be auto-resolved or must be escalated for manual review.

Resolution rules (from UAT SME session)
----------------------------------------
quantity_mismatch
  • Blanket contract (is_blanket_order=True) → auto-resolve (Q2:C)
  • Standard PO, invoice ≤ GRN qty × unit_price + 2% tolerance → auto-resolve
  • Otherwise → manual review, keep hold

price_variance
  • Variance ≤ 5% → auto-resolve with note
  • Variance > 5% → manual review, notify ap_specialist

missing_grn
  • Always manual review (GRN must exist before payment)

Adapter methods used (ZERO hardcoded SQL):
  adapter.get_discrepancies()      → discrepancy_log rows
  adapter.get_active_holds()       → current holds
  adapter.get_contracts()          → blanket/standard contract check
  adapter.get_vendor_invoices()    → invoice refresh
  adapter.get_purchase_orders()    → PO data (unit prices)
  adapter.resolve_discrepancy()    → mark discrepancy resolved
  adapter.release_invoice_hold()   → remove hold after resolution
  adapter.log_notification()       → notify ap_specialist when manual needed
  adapter.get_email_template()     → email template lookup
  adapter.get_users_by_role()      → ap_specialist users
  adapter.log_agent_action()       → agent_actions audit
"""

from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)

# Tolerance constants
_PRICE_AUTO_RESOLVE_PCT  = 0.05   # 5% — auto-resolve below this
_QTY_INVOICE_TOLERANCE   = 0.02   # 2% — quantity/amount tolerance for standard POs


def _adapter():
    return get_adapter()


class DiscrepancyResolutionAgent(BaseAgent):
    """
    Agent that triages and resolves 3-way match discrepancies.

    Auto-resolution paths
    ---------------------
    1. Blanket contract + quantity mismatch        → auto-resolve
    2. Standard PO + invoice within 2% of GRN qty → auto-resolve
    3. Price variance ≤ 5%                         → auto-resolve
    4. All else                                    → manual review, hold remains

    Output
    ------
    Returns a summary of resolved vs pending discrepancies and routes
    either to PaymentReadinessAgent (all resolved) or stays in queue.
    """

    def __init__(self):
        super().__init__(
            name="DiscrepancyResolutionAgent",
            description=(
                "Triages 3-way match discrepancies from InvoiceMatchingAgent. "
                "Auto-resolves blanket-contract quantity mismatches and small "
                "price variances; escalates the rest for manual AP review."
            ),
            temperature=0.1,
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch open discrepancies, active holds, contract data, and refreshed
        invoice / PO rows for the given invoice.

        Expected input_data keys
        ------------------------
        invoice_number : str   — invoice being processed
        vendor_id      : str   — vendor identifier (for contract lookup)
        po_reference   : str   — associated PO number (optional)
        """
        self.status = AgentStatus.OBSERVING

        invoice_number = (
            input_data.get("invoice_number")
            or input_data.get("invoice_no")
        )
        vendor_id    = input_data.get("vendor_id", "")
        po_reference = input_data.get("po_reference", "")

        logger.info(
            "[DiscrepancyResolutionAgent] OBSERVE — invoice: %s, vendor: %s",
            invoice_number, vendor_id,
        )

        observations: Dict[str, Any] = {
            "invoice_input":   input_data,
            "invoice_number":  invoice_number,
            "vendor_id":       vendor_id,
            "po_reference":    po_reference,
            "discrepancies":   [],
            "active_holds":    [],
            "contracts":       [],
            "invoice_rows":    [],
            "po_rows":         [],
        }

        try:
            # 1. Open discrepancies for this invoice
            discrepancies = _adapter().get_discrepancies(
                invoice_number=invoice_number, status="open"
            )
            observations["discrepancies"] = discrepancies

            # 2. Active holds
            active_holds = _adapter().get_active_holds(invoice_number)
            observations["active_holds"] = active_holds

            # 3. Contracts — check for blanket order
            if vendor_id:
                contracts = _adapter().get_contracts(vendor_id=vendor_id, limit=10)
                observations["contracts"] = contracts

            # 4. Refresh invoice data
            if invoice_number:
                invoice_rows = _adapter().get_vendor_invoices(
                    invoice_no=invoice_number, limit=1
                )
                observations["invoice_rows"] = invoice_rows

                if invoice_rows:
                    first_inv = invoice_rows[0]
                    # Resolve vendor_id and PO from invoice if not provided
                    if not vendor_id:
                        vendor_id = (
                            first_inv.get("vendor_id")
                            or first_inv.get("partner_id")
                            or first_inv.get("lifnr")
                            or ""
                        )
                        observations["vendor_id"] = vendor_id
                        # Fetch contracts again now that we have vendor_id
                        if vendor_id:
                            observations["contracts"] = _adapter().get_contracts(
                                vendor_id=vendor_id, limit=10
                            )
                    if not po_reference:
                        po_reference = _extract_po_reference(first_inv)
                        observations["po_reference"] = po_reference

                    observations["invoice_amount"] = _safe_float(
                        first_inv.get("amount_total")
                        or first_inv.get("wrbtr")
                        or 0
                    )

            # 5. PO data (for unit price lookups)
            if po_reference:
                all_pos = _adapter().get_purchase_orders(limit=500)
                observations["po_rows"] = [
                    p for p in all_pos
                    if str(p.get("po_number", "")) == str(po_reference)
                ]

        except Exception as exc:
            logger.error("[DiscrepancyResolutionAgent] OBSERVE error: %s", exc)
            observations["observe_error"] = str(exc)

        return observations

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Evaluate each discrepancy and decide: auto-resolve or manual review.
        """
        self.status = AgentStatus.THINKING

        discrepancies  = observations.get("discrepancies", [])
        contracts      = observations.get("contracts", [])
        invoice_amount = observations.get("invoice_amount", 0.0)
        po_rows        = observations.get("po_rows", [])
        invoice_number = observations.get("invoice_number", "UNKNOWN")

        if not discrepancies:
            return AgentDecision(
                action="no_discrepancies",
                reasoning=(
                    f"No open discrepancies found for invoice {invoice_number}. "
                    "Invoice can proceed to payment readiness check."
                ),
                confidence=0.98,
                context=observations,
                alternatives=[],
            )

        # Determine blanket contract status
        is_blanket = any(c.get("is_blanket_order") for c in contracts)

        # Evaluate each discrepancy
        auto_resolve_list: List[Dict[str, Any]] = []
        manual_review_list: List[Dict[str, Any]] = []

        for disc in discrepancies:
            disc_type    = (disc.get("discrepancy_type") or "").lower()
            variance_pct = _safe_float(disc.get("variance_pct") or 0)
            disc_id      = disc.get("id") or disc.get("discrepancy_id")

            if disc_type == "quantity_mismatch":
                if is_blanket:
                    auto_resolve_list.append({
                        "discrepancy": disc,
                        "reason": (
                            "Blanket contract: partial GRN is acceptable (Q2:C). "
                            "Auto-resolved."
                        ),
                    })
                else:
                    # Standard PO — check if invoice amount ≈ GRN qty × unit_price
                    within_tolerance = _check_qty_within_tolerance(
                        disc, po_rows, invoice_amount
                    )
                    if within_tolerance:
                        auto_resolve_list.append({
                            "discrepancy": disc,
                            "reason": (
                                f"Standard PO: invoice amount within "
                                f"{_QTY_INVOICE_TOLERANCE*100:.0f}% of "
                                "GRN qty × unit_price. Auto-resolved."
                            ),
                        })
                    else:
                        manual_review_list.append({
                            "discrepancy": disc,
                            "reason": (
                                "Standard PO quantity mismatch exceeds tolerance. "
                                "Manual review required."
                            ),
                        })

            elif disc_type == "price_variance":
                if variance_pct <= _PRICE_AUTO_RESOLVE_PCT * 100:
                    auto_resolve_list.append({
                        "discrepancy": disc,
                        "reason": (
                            f"Price variance {variance_pct:.2f}% is within "
                            f"{_PRICE_AUTO_RESOLVE_PCT*100:.0f}% auto-resolve "
                            "threshold."
                        ),
                    })
                else:
                    manual_review_list.append({
                        "discrepancy": disc,
                        "reason": (
                            f"Price variance {variance_pct:.2f}% exceeds "
                            f"{_PRICE_AUTO_RESOLVE_PCT*100:.0f}% threshold. "
                            "Manual review required."
                        ),
                    })

            elif disc_type == "missing_grn":
                manual_review_list.append({
                    "discrepancy": disc,
                    "reason": (
                        "GRN is missing — payment cannot proceed without goods "
                        "receipt confirmation. Manual review required."
                    ),
                })

            else:
                # Unknown discrepancy type — err on side of caution
                manual_review_list.append({
                    "discrepancy": disc,
                    "reason": (
                        f"Unknown discrepancy type '{disc_type}'. "
                        "Defaulting to manual review."
                    ),
                })

        all_resolved = len(manual_review_list) == 0
        action       = "auto_resolve_all" if all_resolved else (
            "auto_resolve_partial" if auto_resolve_list else "flag_all_manual"
        )

        total = len(discrepancies)
        auto  = len(auto_resolve_list)
        manual = len(manual_review_list)

        reasoning = (
            f"Invoice {invoice_number}: {total} discrepancy(ies) — "
            f"{auto} auto-resolve, {manual} manual review. "
            f"Blanket contract: {is_blanket}."
        )
        confidence = 0.95 if all_resolved else (0.80 if auto_resolve_list else 0.70)

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "auto_resolve_list":  auto_resolve_list,
                "manual_review_list": manual_review_list,
                "is_blanket":         is_blanket,
            },
            alternatives=["escalate_to_manager", "place_payment_hold"],
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        Execute auto-resolutions, release associated holds, and notify for
        manual-review items.
        """
        self.status = AgentStatus.ACTING

        action             = decision.action
        ctx                = decision.context
        invoice_number     = ctx.get("invoice_number", "UNKNOWN")
        auto_resolve_list  = ctx.get("auto_resolve_list", [])
        manual_review_list = ctx.get("manual_review_list", [])
        active_holds       = ctx.get("active_holds", [])
        vendor_id          = ctx.get("vendor_id", "")

        resolved_ids: List[int] = []
        pending_ids:  List[int] = []

        # ── AUTO-RESOLVE items ────────────────────────────────────────────────
        for item in auto_resolve_list:
            disc    = item["discrepancy"]
            reason  = item["reason"]
            disc_id = disc.get("id") or disc.get("discrepancy_id")

            if disc_id is None:
                logger.warning(
                    "[DiscrepancyResolutionAgent] Cannot resolve — no id: %s", disc
                )
                continue

            try:
                _adapter().resolve_discrepancy(
                    discrepancy_id=int(disc_id),
                    resolution_notes=reason,
                    resolved_by=self.name,
                )
                resolved_ids.append(int(disc_id))
                logger.info(
                    "[DiscrepancyResolutionAgent] Resolved discrepancy %s: %s",
                    disc_id, reason[:80],
                )

                # Release hold if it was placed specifically for this discrepancy
                _release_matching_hold(active_holds, invoice_number, disc, self.name)

            except Exception as exc:
                logger.error(
                    "[DiscrepancyResolutionAgent] resolve_discrepancy(%s) failed: %s",
                    disc_id, exc,
                )
                pending_ids.append(int(disc_id) if disc_id else -1)

        # ── MANUAL REVIEW items — keep holds, notify ap_specialist ────────────
        for item in manual_review_list:
            disc    = item["discrepancy"]
            reason  = item["reason"]
            disc_id = disc.get("id") or disc.get("discrepancy_id")
            if disc_id is not None:
                pending_ids.append(int(disc_id))

            _send_notification(
                _adapter(),
                event_type="discrepancy_flagged",
                context_vars={
                    "invoice_number":    invoice_number,
                    "discrepancy_type":  disc.get("discrepancy_type", "unknown"),
                    "discrepancy_detail": reason[:200],
                    "vendor_id":         vendor_id or "N/A",
                },
                agent_name=self.name,
            )

        # ── Determine overall status & next agent ─────────────────────────────
        if not pending_ids:
            overall_status = "resolved"
            next_agent     = "PaymentReadinessAgent"
        elif resolved_ids:
            overall_status = "partially_resolved"
            next_agent     = "DiscrepancyResolutionAgent"  # re-queue
        else:
            overall_status = "pending_manual"
            next_agent     = None  # stays in ap_specialist queue

        result: Dict[str, Any] = {
            "agent":                    self.name,
            "action":                   action,
            "invoice_number":           invoice_number,
            "status":                   overall_status,
            "discrepancies_resolved":   len(resolved_ids),
            "discrepancies_pending":    len(pending_ids),
            "resolved_ids":             resolved_ids,
            "pending_ids":              pending_ids,
            "next_agent":               next_agent,
            "success":                  True,
        }

        # ── Audit log ─────────────────────────────────────────────────────────
        _adapter().log_agent_action(
            self.name,
            f"discrepancy_resolution_{action}"[:50],
            {
                "invoice_number":         invoice_number,
                "total_discrepancies":    len(auto_resolve_list) + len(manual_review_list),
                "vendor_id":              vendor_id,
            },
            {
                "resolved":   len(resolved_ids),
                "pending":    len(pending_ids),
                "status":     overall_status,
                "next_agent": next_agent,
            },
            True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        res = learn_context.get("result", {})
        logger.info(
            "[DiscrepancyResolutionAgent] LEARN — resolved: %s, pending: %s",
            res.get("discrepancies_resolved", 0),
            res.get("discrepancies_pending", 0),
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(
            "[DiscrepancyResolutionAgent] START — invoice: %s",
            input_data.get("invoice_number"),
        )
        return await self.execute_with_recovery(input_data)


# ── Private helpers ───────────────────────────────────────────────────────────

def _extract_po_reference(invoice_row: dict) -> Optional[str]:
    for field in ("invoice_origin", "po_reference", "po_number", "ebeln", "ponumber"):
        val = invoice_row.get(field)
        if val and str(val).strip():
            return str(val).strip()
    return None


def _safe_float(val) -> float:
    try:
        return float(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _check_qty_within_tolerance(
    disc: dict,
    po_rows: List[dict],
    invoice_amount: float,
) -> bool:
    """
    For standard PO quantity mismatches, check whether the invoice amount is
    within _QTY_INVOICE_TOLERANCE of (GRN qty × unit_price).

    Returns True if within tolerance (safe to auto-resolve).
    """
    grn_value = _safe_float(disc.get("grn_value") or 0)
    if grn_value <= 0 and po_rows:
        # Estimate: use po_rows unit cost × GRN received qty from disc
        grn_qty    = _safe_float(disc.get("grn_value") or disc.get("variance_amount") or 0)
        unit_price = _safe_float(
            next((p.get("unit_price") or p.get("unit_cost") or 0 for p in po_rows), 0)
        )
        grn_value  = grn_qty * unit_price

    if grn_value <= 0 or invoice_amount <= 0:
        return False

    variance = abs(invoice_amount - grn_value) / grn_value
    return variance <= _QTY_INVOICE_TOLERANCE


def _release_matching_hold(
    active_holds: List[dict],
    invoice_number: str,
    disc: dict,
    agent_name: str,
) -> None:
    """
    Release an active hold whose hold_reason matches the discrepancy type, if any.
    Silently ignores errors (non-critical path).
    """
    disc_type = (disc.get("discrepancy_type") or "").lower()
    type_hold_map = {
        "price_variance":   "price_variance",
        "quantity_mismatch": "quantity_mismatch",
        "missing_grn":      "pending_grn",
    }
    target_reason = type_hold_map.get(disc_type)
    if not target_reason:
        return

    matching = [
        h for h in active_holds
        if (h.get("hold_reason") or "").lower() == target_reason
    ]
    if matching:
        try:
            _adapter().release_invoice_hold(invoice_number, agent_name)
            logger.info(
                "[DiscrepancyResolutionAgent] Released hold '%s' on %s",
                target_reason, invoice_number,
            )
        except Exception as exc:
            logger.warning(
                "[DiscrepancyResolutionAgent] Could not release hold on %s: %s",
                invoice_number, exc,
            )


def _send_notification(
    adapter,
    event_type: str,
    context_vars: dict,
    agent_name: str,
) -> None:
    """Log a notification_log row for each ap_specialist user."""
    try:
        template = adapter.get_email_template(event_type)
        if not template:
            return

        subject = template.get("subject", event_type)
        body    = template.get("body_html", "")
        for k, v in context_vars.items():
            ph      = "{" + k + "}"
            subject = subject.replace(ph, str(v))
            body    = body.replace(ph, str(v))

        role  = template.get("recipients_role", "ap_specialist")
        users = adapter.get_users_by_role(role)[:5]

        for user in users:
            adapter.log_notification({
                "event_type":      event_type,
                "document_type":   "INVOICE",
                "document_id":     context_vars.get("invoice_number", ""),
                "recipient_email": user.get("email", ""),
                "recipient_role":  role,
                "subject":         subject,
                "body":            body,
                "status":          "pending",
                "agent_name":      agent_name,
            })

    except Exception as exc:
        logger.warning(
            "[DiscrepancyResolutionAgent] Notification logging failed: %s", exc
        )


# ── Convenience entry point ───────────────────────────────────────────────────

async def resolve_discrepancies(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for the pipeline orchestrator."""
    agent = DiscrepancyResolutionAgent()
    return await agent.execute(invoice_data)
