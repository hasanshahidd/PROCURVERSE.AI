"""
InvoiceRoutingAgent — Step 4 of the 9-agent Invoice-to-Payment Pipeline
========================================================================
Liztek P2P Flow: Invoice Intake & Queue Assignment

Routes ALL vendor invoices — PO-backed and non-PO — to the ap_specialist queue.
Business Rule Q1:D: every invoice, regardless of type or amount, is assigned to
the ap_specialist queue. Non-PO invoices are flagged but NOT rejected.

Sub-steps:
  1. Invoice Fetch       — get recent/specific invoices from adapter
  2. Hold Check          — check for existing active holds
  3. PO Linkage Check    — determine whether invoice has a PO reference
  4. Duplicate Detection — honour duplicate flag from InvoiceCaptureAgent
  5. Queue Assignment    — route to ap_specialist (always)
  6. Notification        — log notification_log for the ap_specialist team

Adapter methods used (ZERO hardcoded SQL):
  adapter.get_vendor_invoices()   → invoice data
  adapter.get_active_holds()      → active invoice holds
  adapter.log_notification()      → notification_log
  adapter.get_email_template()    → email subject/body
  adapter.get_users_by_role()     → ap_specialist users
  adapter.log_agent_action()      → agent_actions audit
"""

from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)


def _adapter():
    return get_adapter()


class InvoiceRoutingAgent(BaseAgent):
    """
    Agent responsible for routing all vendor invoices into the AP processing queue.

    Key behaviours
    --------------
    - Q1:D  : ALL invoices go to ap_specialist regardless of origin or type.
    - Q3:B  : Non-PO invoices also route to ap_specialist, flagged as 'non_po_invoice'.
    - Holds : Invoices with active holds are routed as 'hold_pending_resolution'.
    - Dups  : Invoices already flagged as duplicates by InvoiceCaptureAgent are rejected.

    Confidence scoring
    ------------------
    0.95 — PO-backed invoice routed normally
    0.80 — Non-PO invoice (more manual review expected)
    1.00 — Reject (duplicate) — high certainty, no routing needed
    0.90 — Hold pending resolution
    """

    def __init__(self):
        super().__init__(
            name="InvoiceRoutingAgent",
            description=(
                "Routes all vendor invoices (PO-backed and non-PO) to the "
                "ap_specialist queue. Handles duplicate rejection and hold "
                "detection before queue assignment."
            ),
            temperature=0.1,
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch invoice data and check for active holds.

        Inputs expected in input_data
        ------------------------------
        invoice_number  : specific invoice to process (optional — fetches batch if absent)
        is_duplicate    : bool set by InvoiceCaptureAgent upstream
        ocr_data        : dict from InvoiceCaptureAgent (confidence, extracted fields)
        vendor_id       : vendor identifier (may be absent for non-PO invoices)
        """
        self.status = AgentStatus.OBSERVING

        invoice_number = (
            input_data.get("invoice_number")
            or input_data.get("invoice_no")
        )
        logger.info("[InvoiceRoutingAgent] OBSERVE — invoice: %s", invoice_number)

        observations: Dict[str, Any] = {
            "invoice_input":   input_data,
            "invoice_rows":    [],
            "active_holds":    [],
            "is_duplicate":    input_data.get("is_duplicate", False),
            "ocr_data":        input_data.get("ocr_data", {}),
        }

        try:
            # 1. Fetch invoice(s)
            if invoice_number:
                invoice_rows = _adapter().get_vendor_invoices(
                    invoice_no=invoice_number, limit=1
                )
            else:
                invoice_rows = _adapter().get_vendor_invoices(limit=100)

            observations["invoice_rows"] = invoice_rows

            if invoice_rows:
                first_inv = invoice_rows[0]
                # Normalise invoice number across ERP schemas
                resolved_inv_no = (
                    first_inv.get("invoice_no")
                    or first_inv.get("name")
                    or first_inv.get("belnr")
                    or invoice_number
                    or "UNKNOWN"
                )
                observations["resolved_invoice_number"] = resolved_inv_no

                # 2. Check for active holds on this invoice
                active_holds = _adapter().get_active_holds(resolved_inv_no)
                observations["active_holds"] = active_holds

                # 3. Determine PO linkage
                po_reference = _extract_po_reference(first_inv)
                observations["po_reference"]   = po_reference
                observations["is_po_backed"]   = bool(po_reference)
                observations["vendor_id"]      = (
                    first_inv.get("vendor_id")
                    or first_inv.get("partner_id")
                    or first_inv.get("lifnr")
                    or input_data.get("vendor_id")
                )
                observations["invoice_amount"] = _safe_float(
                    first_inv.get("amount_total")
                    or first_inv.get("wrbtr")
                    or first_inv.get("invoice_total")
                    or 0
                )
                observations["currency"] = (
                    first_inv.get("currency")
                    or first_inv.get("currency_id")
                    or "AED"
                )
            else:
                logger.warning(
                    "[InvoiceRoutingAgent] No invoice found for: %s", invoice_number
                )
                observations["resolved_invoice_number"] = invoice_number or "UNKNOWN"
                observations["is_po_backed"] = False
                observations["po_reference"] = None
                observations["vendor_id"]    = input_data.get("vendor_id")
                observations["invoice_amount"] = 0.0
                observations["currency"]     = "AED"

        except Exception as exc:
            logger.error("[InvoiceRoutingAgent] OBSERVE error: %s", exc)
            observations["observe_error"] = str(exc)

        return observations

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Apply routing rules to determine action.

        Priority order
        --------------
        1. Duplicate flag  → reject_duplicate           (confidence 1.0)
        2. Active hold     → hold_pending_resolution     (confidence 0.90)
        3. PO-backed       → route_to_ap_specialist      (confidence 0.95)
        4. Non-PO          → route_to_ap_specialist      (confidence 0.80, flagged)
        """
        self.status = AgentStatus.THINKING

        is_duplicate    = observations.get("is_duplicate", False)
        active_holds    = observations.get("active_holds", [])
        is_po_backed    = observations.get("is_po_backed", False)
        invoice_number  = observations.get("resolved_invoice_number", "UNKNOWN")
        invoice_rows    = observations.get("invoice_rows", [])

        # ── Rule 1: Duplicate ─────────────────────────────────────────────────
        if is_duplicate:
            return AgentDecision(
                action="reject_duplicate",
                reasoning=(
                    f"Invoice {invoice_number} is flagged as a duplicate by "
                    "InvoiceCaptureAgent. Rejecting to prevent double payment."
                ),
                confidence=1.0,
                context=observations,
                alternatives=["route_to_ap_specialist"],
            )

        # ── Rule 2: Active hold ───────────────────────────────────────────────
        if active_holds:
            hold_reasons = [h.get("hold_reason", "unknown") for h in active_holds]
            return AgentDecision(
                action="hold_pending_resolution",
                reasoning=(
                    f"Invoice {invoice_number} has {len(active_holds)} active hold(s): "
                    f"{', '.join(hold_reasons)}. Cannot route until holds resolved."
                ),
                confidence=0.90,
                context=observations,
                alternatives=["route_to_ap_specialist"],
            )

        # ── Rule 3 & 4: Route to ap_specialist (Q1:D — ALL invoices) ─────────
        if is_po_backed:
            reasoning = (
                f"Invoice {invoice_number} is PO-backed (PO: "
                f"{observations.get('po_reference', 'N/A')}). "
                "Routing to ap_specialist queue per Q1:D policy."
            )
            confidence = 0.95
            flags = []
        else:
            reasoning = (
                f"Invoice {invoice_number} has no PO reference — classified as "
                "non-PO invoice. Routing to ap_specialist queue per Q3:B policy. "
                "Flagged for manual PO association or exception approval."
            )
            confidence = 0.80
            flags = ["non_po_invoice"]

        return AgentDecision(
            action="route_to_ap_specialist",
            reasoning=reasoning,
            confidence=confidence,
            context={**observations, "routing_flags": flags},
            alternatives=["escalate_to_manager", "hold_pending_resolution"],
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Execute the routing decision and log notifications."""
        self.status = AgentStatus.ACTING

        action          = decision.action
        ctx             = decision.context
        invoice_number  = ctx.get("resolved_invoice_number", "UNKNOWN")
        invoice_rows    = ctx.get("invoice_rows", [])
        is_po_backed    = ctx.get("is_po_backed", False)
        routing_flags   = ctx.get("routing_flags", [])
        active_holds    = ctx.get("active_holds", [])
        vendor_id       = ctx.get("vendor_id", "")
        invoice_amount  = ctx.get("invoice_amount", 0.0)
        currency        = ctx.get("currency", "AED")
        po_reference    = ctx.get("po_reference", "")

        result: Dict[str, Any] = {
            "agent":           self.name,
            "action":          action,
            "invoice_number":  invoice_number,
            "vendor_id":       vendor_id,
            "invoice_amount":  invoice_amount,
            "currency":        currency,
            "is_po_backed":    is_po_backed,
            "routing_flags":   routing_flags,
            "success":         True,
        }

        # ── REJECT_DUPLICATE ─────────────────────────────────────────────────
        if action == "reject_duplicate":
            logger.warning(
                "[InvoiceRoutingAgent] REJECT DUPLICATE: %s", invoice_number
            )
            result.update({
                "status":          "rejected_duplicate",
                "queue_assignment": None,
                "next_agent":      None,
                "message": (
                    f"Invoice {invoice_number} rejected — duplicate detected by "
                    "InvoiceCaptureAgent."
                ),
            })
            _send_notification(
                _adapter(),
                event_type="invoice_received",
                context_vars={
                    "invoice_number": invoice_number,
                    "status":         "rejected_duplicate",
                    "notes":          "Duplicate invoice — no action required",
                },
                agent_name=self.name,
            )

        # ── HOLD_PENDING_RESOLUTION ───────────────────────────────────────────
        elif action == "hold_pending_resolution":
            hold_count = len(active_holds)
            logger.info(
                "[InvoiceRoutingAgent] HOLD: %s (%d active hold(s))",
                invoice_number, hold_count,
            )
            result.update({
                "status":          "hold_pending_resolution",
                "queue_assignment": "ap_specialist",
                "next_agent":      "DiscrepancyResolutionAgent",
                "active_holds":    hold_count,
                "message": (
                    f"Invoice {invoice_number} has {hold_count} active hold(s). "
                    "Routed to ap_specialist for hold resolution."
                ),
            })
            _send_notification(
                _adapter(),
                event_type="invoice_received",
                context_vars={
                    "invoice_number": invoice_number,
                    "status":         "on_hold",
                    "notes":          f"{hold_count} active hold(s) — requires resolution",
                },
                agent_name=self.name,
            )

        # ── ROUTE_TO_AP_SPECIALIST (default path for all invoices) ────────────
        else:
            invoice_type = "Non-PO" if not is_po_backed else "PO-backed"
            logger.info(
                "[InvoiceRoutingAgent] ROUTING to ap_specialist: %s (%s)",
                invoice_number, invoice_type,
            )
            result.update({
                "status":           "routed_to_ap_specialist",
                "queue_assignment": "ap_specialist",
                "next_agent":       "InvoiceMatchingAgent",
                "invoice_type":     invoice_type,
                "po_reference":     po_reference or None,
                "message": (
                    f"Invoice {invoice_number} ({invoice_type}) routed to "
                    "ap_specialist queue for processing."
                ),
            })
            _send_notification(
                _adapter(),
                event_type="invoice_received",
                context_vars={
                    "invoice_number": invoice_number,
                    "vendor_id":      vendor_id or "N/A",
                    "amount":         f"{invoice_amount:,.2f} {currency}",
                    "invoice_type":   invoice_type,
                    "po_reference":   po_reference or "N/A",
                    "flags":          ", ".join(routing_flags) if routing_flags else "none",
                },
                agent_name=self.name,
            )

        # ── Audit log ─────────────────────────────────────────────────────────
        _adapter().log_agent_action(
            self.name,
            f"invoice_routing_{action}"[:50],
            {
                "invoice_number": invoice_number,
                "is_po_backed":   is_po_backed,
                "routing_flags":  routing_flags,
            },
            {
                "action": action,
                "status": result.get("status"),
                "queue":  result.get("queue_assignment"),
            },
            result["success"],
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        action = (
            learn_context.get("result", {}).get("action")
            or learn_context.get("result", {}).get("status", "unknown")
        )
        logger.info("[InvoiceRoutingAgent] LEARN — last action: %s", action)

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(
            "[InvoiceRoutingAgent] START — invoice: %s",
            input_data.get("invoice_number"),
        )
        return await self.execute_with_recovery(input_data)


# ── Private helpers ───────────────────────────────────────────────────────────

def _extract_po_reference(invoice_row: dict) -> Optional[str]:
    """
    Return the PO reference from an invoice row, checking all known ERP field names.
    Returns None if no PO reference is present (non-PO invoice).
    """
    candidates = [
        invoice_row.get("invoice_origin"),   # Odoo
        invoice_row.get("po_reference"),      # normalised field
        invoice_row.get("po_number"),         # alternative normalised
        invoice_row.get("ebeln"),             # SAP S/4
        invoice_row.get("ponumber"),          # SAP B1 / generic
        invoice_row.get("purchase_order"),    # ERP-neutral
    ]
    for c in candidates:
        if c and str(c).strip():
            return str(c).strip()
    return None


def _safe_float(val) -> float:
    try:
        return float(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _send_notification(
    adapter,
    event_type: str,
    context_vars: dict,
    agent_name: str,
) -> None:
    """
    Look up the email template for event_type, resolve recipient list from
    ap_specialist role, and log one notification_log row per recipient.
    """
    try:
        template = adapter.get_email_template(event_type)
        if not template:
            logger.debug(
                "[InvoiceRoutingAgent] No template for event_type=%s", event_type
            )
            return

        subject = template.get("subject", event_type)
        body    = template.get("body_html", "")

        for key, value in context_vars.items():
            placeholder = "{" + key + "}"
            subject = subject.replace(placeholder, str(value))
            body    = body.replace(placeholder, str(value))

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
            "[InvoiceRoutingAgent] Notification logging failed: %s", exc
        )


# ── Convenience entry point ───────────────────────────────────────────────────

async def route_invoice(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for the pipeline orchestrator."""
    agent = InvoiceRoutingAgent()
    return await agent.execute(invoice_data)
