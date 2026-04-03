"""
PaymentApprovalAgent — Step 9 (Final) of the 9-agent Invoice-to-Payment Pipeline
==================================================================================
Liztek P2P Flow: Payment-Level Approval Gate

Implements Q4: payment approval is a SEPARATE step from invoice approval.
It uses document_type='PAYMENT' rules with different approvers (finance /
treasury) and different thresholds.

Decision logic
--------------
1. Fetch matching approval_rules where document_type='PAYMENT' and the
   net_payable amount falls within [amount_min, amount_max].
2. No matching rule → AUTO-APPROVE (internal payment, below any threshold).
3. Rule found and no active holds → create pending_approvals record, route to
   the approver identified in approval_rules.approver_role.
4. Rule found for auto-approver (approver_role = 'auto') → auto-approve inline.

Notification
------------
Approver email is pulled from approval_rules.approver_email (UAT-002 data).
Fallback: look up users by approver_role via get_users_by_role().

Adapter methods used (ZERO hardcoded SQL):
  adapter.get_approval_rules()     → PAYMENT rules for the amount
  adapter.get_users_by_role()      → approver contact details
  adapter.get_pending_approvals()  → check if already approved
  adapter.get_active_holds()       → confirm no holds remain
  adapter.create_pending_approval() → create approval record
  adapter.update_approval_status() → mark auto-approved
  adapter.log_notification()       → payment_approved / payment_pending_approval
  adapter.get_email_template()     → email template lookup
  adapter.log_agent_action()       → agent_actions audit
"""

from typing import Dict, Any, List, Optional
import logging
from datetime import date

from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)


def _adapter():
    return get_adapter()


class PaymentApprovalAgent(BaseAgent):
    """
    Final agent in the Invoice-to-Payment pipeline.

    Responsibilities
    ----------------
    - Apply PAYMENT-level approval rules (separate from INVOICE rules, Q4).
    - Auto-approve when no rule applies or approver_role is 'auto'.
    - Route to finance/treasury approver when a rule is triggered.
    - Ensure no active holds block the payment at this final stage.
    - This agent is the END of the pipeline — next_agent is always None.
    """

    def __init__(self):
        super().__init__(
            name="PaymentApprovalAgent",
            description=(
                "Final payment approval gate in the Liztek P2P pipeline. "
                "Applies PAYMENT-document-type approval rules with finance/treasury "
                "approvers. Auto-approves when no threshold rule is matched."
            ),
            temperature=0.0,
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch payment approval rules, existing approvals, and active holds.

        Expected input_data keys
        ------------------------
        invoice_number      : str   — invoice identifier
        net_payable         : float — net amount to pay (from PaymentCalculationAgent)
        net_payable_aed     : float — AED-equivalent net amount (may equal net_payable)
        vendor_id           : str   — vendor identifier
        payment_run_number  : str   — payment run reference
        payment_type        : str   — 'full' or 'partial'
        """
        self.status = AgentStatus.OBSERVING

        invoice_number     = (
            input_data.get("invoice_number")
            or input_data.get("invoice_no")
        )
        net_payable        = _safe_float(
            input_data.get("net_payable")
            or input_data.get("net_payable_aed")
            or 0
        )
        vendor_id          = input_data.get("vendor_id", "")
        payment_run_number = input_data.get("payment_run_number", "")
        payment_type       = input_data.get("payment_type", "full")

        logger.info(
            "[PaymentApprovalAgent] OBSERVE — invoice: %s, amount: %.2f",
            invoice_number, net_payable,
        )

        observations: Dict[str, Any] = {
            "invoice_input":       input_data,
            "invoice_number":      invoice_number,
            "net_payable":         net_payable,
            "vendor_id":           vendor_id,
            "payment_run_number":  payment_run_number,
            "payment_type":        payment_type,
            "approval_rules":      [],
            "existing_approvals":  [],
            "active_holds":        [],
            "approver_users":      [],
        }

        try:
            # 1. PAYMENT approval rules for this amount
            approval_rules = _adapter().get_approval_rules(
                document_type="PAYMENT", amount=net_payable
            )
            observations["approval_rules"] = approval_rules

            # 2. Check for an existing approved record (idempotency)
            all_approved = _adapter().get_pending_approvals(
                status="approved", document_type="PAYMENT"
            )
            observations["existing_approvals"] = [
                pa for pa in all_approved
                if str(pa.get("pr_number", "")) == str(invoice_number)
            ]

            # 3. Active holds — final safety check
            active_holds = _adapter().get_active_holds(invoice_number)
            observations["active_holds"] = active_holds

            # 4. Approver user lookup (for email routing)
            if approval_rules:
                approver_role = (
                    approval_rules[0].get("approver_role")
                    or "finance"
                )
                if approver_role and approver_role.lower() != "auto":
                    approver_users = _adapter().get_users_by_role(approver_role)
                    observations["approver_users"] = approver_users
                    observations["approver_role"] = approver_role
                else:
                    observations["approver_role"] = approver_role
            else:
                observations["approver_role"] = "auto"

        except Exception as exc:
            logger.error("[PaymentApprovalAgent] OBSERVE error: %s", exc)
            observations["observe_error"] = str(exc)

        return observations

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Determine approval action based on rules, existing approvals, and holds.
        """
        self.status = AgentStatus.THINKING

        invoice_number     = observations.get("invoice_number", "UNKNOWN")
        net_payable        = observations.get("net_payable", 0.0)
        approval_rules     = observations.get("approval_rules", [])
        existing_approvals = observations.get("existing_approvals", [])
        active_holds       = observations.get("active_holds", [])
        approver_role      = observations.get("approver_role", "auto")

        # ── Already approved (idempotency check) ──────────────────────────────
        if existing_approvals:
            existing = existing_approvals[0]
            return AgentDecision(
                action="already_approved",
                reasoning=(
                    f"Payment for invoice {invoice_number} already has an approved "
                    f"record (id: {existing.get('id', 'N/A')}). No duplicate needed."
                ),
                confidence=1.0,
                context={**observations, "existing_approval": existing},
                alternatives=[],
            )

        # ── Active holds — cannot approve ────────────────────────────────────
        if active_holds:
            hold_reasons = [h.get("hold_reason", "unknown") for h in active_holds]
            return AgentDecision(
                action="blocked_by_holds",
                reasoning=(
                    f"Invoice {invoice_number} has {len(active_holds)} active hold(s): "
                    f"{', '.join(hold_reasons)}. Payment approval blocked."
                ),
                confidence=0.95,
                context=observations,
                alternatives=["escalate_to_finance"],
            )

        # ── No matching rule → auto-approve ───────────────────────────────────
        if not approval_rules:
            return AgentDecision(
                action="auto_approve",
                reasoning=(
                    f"No PAYMENT approval rule found for amount {net_payable:,.2f}. "
                    "Invoice is below all thresholds — auto-approving."
                ),
                confidence=0.95,
                context=observations,
                alternatives=["route_for_payment_approval"],
            )

        # ── Rule with approver_role='auto' ────────────────────────────────────
        if approver_role.lower() == "auto":
            rule = approval_rules[0]
            return AgentDecision(
                action="auto_approve",
                reasoning=(
                    f"Approval rule {rule.get('id', 'N/A')} has approver_role='auto'. "
                    f"Amount {net_payable:,.2f} within [{rule.get('amount_min',0)}, "
                    f"{rule.get('amount_max','∞')}]. Auto-approving."
                ),
                confidence=0.95,
                context=observations,
                alternatives=["route_for_payment_approval"],
            )

        # ── Route for human approval ───────────────────────────────────────────
        rule = approval_rules[0]
        approver_name  = (
            rule.get("approver_name")
            or approver_role
        )
        approver_email = rule.get("approver_email", "")
        sla_hours      = rule.get("sla_hours", 24)

        return AgentDecision(
            action="route_for_payment_approval",
            reasoning=(
                f"PAYMENT rule matched for amount {net_payable:,.2f} "
                f"(rule id: {rule.get('id', 'N/A')}, level: {rule.get('approval_level', 'N/A')}). "
                f"Routing to {approver_name} ({approver_role}). SLA: {sla_hours}h."
            ),
            confidence=0.85,
            context={
                **observations,
                "matched_rule":    rule,
                "approver_name":   approver_name,
                "approver_email":  approver_email,
                "sla_hours":       sla_hours,
            },
            alternatives=["auto_approve", "escalate_to_finance"],
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        Execute the approval action: auto-approve or create pending approval record.
        """
        self.status = AgentStatus.ACTING

        action             = decision.action
        ctx                = decision.context
        invoice_number     = ctx.get("invoice_number", "UNKNOWN")
        net_payable        = ctx.get("net_payable", 0.0)
        vendor_id          = ctx.get("vendor_id", "")
        payment_run_number = ctx.get("payment_run_number", "")
        payment_type       = ctx.get("payment_type", "full")
        approver_role      = ctx.get("approver_role", "auto")
        today_str          = date.today().isoformat()

        approval_id:    Optional[int]  = None
        approver_name:  str            = "Auto"
        approver_email: str            = ""

        result: Dict[str, Any] = {
            "agent":              self.name,
            "action":             action,
            "invoice_number":     invoice_number,
            "net_payable":        net_payable,
            "payment_run_number": payment_run_number,
            "payment_type":       payment_type,
            "next_agent":         None,  # END OF PIPELINE
            "success":            True,
        }

        # ── ALREADY APPROVED ─────────────────────────────────────────────────
        if action == "already_approved":
            existing = ctx.get("existing_approval", {})
            result.update({
                "status":       "approved",
                "approval_id":  existing.get("id"),
                "approver_name": existing.get("approver_name", "previous"),
                "message": (
                    f"Payment for invoice {invoice_number} was already approved. "
                    "No action taken."
                ),
            })
            logger.info(
                "[PaymentApprovalAgent] ALREADY APPROVED: %s", invoice_number
            )

        # ── BLOCKED BY HOLDS ─────────────────────────────────────────────────
        elif action == "blocked_by_holds":
            active_holds = ctx.get("active_holds", [])
            result.update({
                "status":    "blocked",
                "holds":     len(active_holds),
                "success":   False,
                "message": (
                    f"Payment for invoice {invoice_number} blocked by "
                    f"{len(active_holds)} active hold(s)."
                ),
            })
            logger.warning(
                "[PaymentApprovalAgent] BLOCKED: %s has %d hold(s)",
                invoice_number, len(active_holds),
            )

        # ── AUTO APPROVE ─────────────────────────────────────────────────────
        elif action == "auto_approve":
            # Create + immediately approve the pending_approvals record
            approval_rec = _adapter().create_pending_approval({
                "pr_number":        invoice_number,
                "decision_type":    "PAYMENT",
                "agent_decision":   f"Auto-approved by {self.name}",
                "confidence_score": decision.confidence,
                "status":           "approved",
                "approver_name":    self.name,
                "approver_role":    "auto",
                "amount":           net_payable,
            })

            approval_id = (
                approval_rec.get("id")
                or approval_rec.get("approval_id")
            )

            # Belt-and-suspenders: explicitly set status=approved
            if approval_id:
                try:
                    _adapter().update_approval_status(
                        int(approval_id),
                        "approved",
                        f"Auto-approved by {self.name} — no threshold rule matched.",
                    )
                except Exception as exc:
                    logger.warning(
                        "[PaymentApprovalAgent] update_approval_status failed: %s", exc
                    )

            result.update({
                "status":         "approved",
                "approval_id":    approval_id,
                "approver_name":  self.name,
                "approver_role":  "auto",
                "message": (
                    f"Payment for invoice {invoice_number} auto-approved. "
                    f"Net payable: {net_payable:,.2f}. "
                    f"Payment run: {payment_run_number}."
                ),
            })

            _send_notification(
                _adapter(),
                event_type="payment_approved",
                context_vars={
                    "invoice_number":   invoice_number,
                    "payment_run":      payment_run_number,
                    "net_payable":      f"{net_payable:,.2f}",
                    "approved_by":      self.name,
                    "payment_type":     payment_type,
                },
                approver_email=approver_email,
                role="finance",
                agent_name=self.name,
            )

            logger.info(
                "[PaymentApprovalAgent] AUTO-APPROVED: %s | %.2f",
                invoice_number, net_payable,
            )

        # ── ROUTE FOR HUMAN APPROVAL ──────────────────────────────────────────
        else:  # route_for_payment_approval
            matched_rule   = ctx.get("matched_rule", {})
            approver_name  = ctx.get("approver_name", approver_role)
            approver_email = ctx.get("approver_email", "")
            sla_hours      = ctx.get("sla_hours", 24)

            approval_rec = _adapter().create_pending_approval({
                "pr_number":        invoice_number,
                "decision_type":    "PAYMENT",
                "agent_decision":   decision.reasoning,
                "confidence_score": decision.confidence,
                "status":           "pending",
                "approver_name":    approver_name,
                "approver_role":    approver_role,
                "approver_email":   approver_email,
                "amount":           net_payable,
                "sla_hours":        sla_hours,
            })

            approval_id = (
                approval_rec.get("id")
                or approval_rec.get("approval_id")
            )

            result.update({
                "status":         "pending_approval",
                "approval_id":    approval_id,
                "approver_name":  approver_name,
                "approver_role":  approver_role,
                "approver_email": approver_email,
                "sla_hours":      sla_hours,
                "message": (
                    f"Payment for invoice {invoice_number} requires approval by "
                    f"{approver_name} ({approver_role}). "
                    f"Net payable: {net_payable:,.2f}. SLA: {sla_hours}h."
                ),
            })

            _send_notification(
                _adapter(),
                event_type="payment_pending_approval",
                context_vars={
                    "invoice_number":   invoice_number,
                    "payment_run":      payment_run_number,
                    "net_payable":      f"{net_payable:,.2f}",
                    "approver_name":    approver_name,
                    "approver_role":    approver_role,
                    "sla_hours":        str(sla_hours),
                    "payment_type":     payment_type,
                },
                approver_email=approver_email,
                role=approver_role,
                agent_name=self.name,
            )

            logger.info(
                "[PaymentApprovalAgent] ROUTED TO APPROVER: %s → %s (%s)",
                invoice_number, approver_name, approver_role,
            )

        # ── Audit log ─────────────────────────────────────────────────────────
        _adapter().log_agent_action(
            self.name,
            f"payment_approval_{action}"[:50],
            {
                "invoice_number":    invoice_number,
                "net_payable":       net_payable,
                "vendor_id":         vendor_id,
                "payment_run":       payment_run_number,
            },
            {
                "action":         action,
                "status":         result.get("status"),
                "approval_id":    approval_id,
                "approver_name":  result.get("approver_name"),
            },
            result["success"],
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        res = learn_context.get("result", {})
        logger.info(
            "[PaymentApprovalAgent] LEARN — action: %s, status: %s",
            res.get("action", "unknown"),
            res.get("status", "unknown"),
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(
            "[PaymentApprovalAgent] START — invoice: %s, amount: %.2f",
            input_data.get("invoice_number"),
            _safe_float(input_data.get("net_payable") or 0),
        )
        return await self.execute_with_recovery(input_data)


# ── Private helpers ───────────────────────────────────────────────────────────

def _safe_float(val) -> float:
    try:
        return float(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _send_notification(
    adapter,
    event_type: str,
    context_vars: dict,
    approver_email: str,
    role: str,
    agent_name: str,
) -> None:
    """
    Log notification_log rows.

    Strategy:
    1. Look up the email template for event_type.
    2. Send to the named approver_email (from approval_rules) if available.
    3. Also send to all users with the given role (CC pattern).
    """
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

        resolved_role = template.get("recipients_role", role)

        # Build recipient list: named approver + role members
        recipients: List[Dict[str, str]] = []
        if approver_email:
            recipients.append({"email": approver_email, "role": resolved_role})

        role_users = adapter.get_users_by_role(resolved_role)[:3]
        for u in role_users:
            email = u.get("email", "")
            if email and email != approver_email:
                recipients.append({"email": email, "role": resolved_role})

        # Deduplicate and log
        seen: set = set()
        for rec in recipients:
            email = rec["email"]
            if email in seen:
                continue
            seen.add(email)
            adapter.log_notification({
                "event_type":      event_type,
                "document_type":   "PAYMENT",
                "document_id":     context_vars.get("invoice_number", ""),
                "recipient_email": email,
                "recipient_role":  rec["role"],
                "subject":         subject,
                "body":            body,
                "status":          "pending",
                "agent_name":      agent_name,
            })

    except Exception as exc:
        logger.warning(
            "[PaymentApprovalAgent] Notification logging failed: %s", exc
        )


# Type alias for use in _send_notification
from typing import List


# ── Convenience entry point ───────────────────────────────────────────────────

async def approve_payment(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for the pipeline orchestrator."""
    agent = PaymentApprovalAgent()
    return await agent.execute(invoice_data)
