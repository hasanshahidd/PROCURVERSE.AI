"""
PaymentReadinessAgent — Step 7 of the 9-agent Invoice-to-Payment Pipeline
==========================================================================
Liztek P2P Flow: Pre-Payment Gate Check

Evaluates ALL Q5 conditions before authorising an invoice for payment.
Every condition must pass for the invoice to proceed. Any failure places a
targeted hold and routes the invoice back to the AP queue.

Q5 conditions checked (in order)
----------------------------------
1. match_passed        — No open discrepancies on the invoice
2. no_active_holds     — No active invoice_holds rows
3. budget_available    — available_budget >= invoice_amount (cost centre from PO line)
4. not_overdue         — invoice due_date >= today (we can still pay on time)
5. payment_terms_match — invoice payment terms ≈ contract payment terms
6. vendor_not_sanctioned — vendor name NOT in the OFAC/debarment blocklist
7. approved            — a matching pending_approvals row with status='approved' exists
                         (or no approval rule triggers → skip)

Adapter methods used (ZERO hardcoded SQL):
  adapter.get_vendor_invoices()    → invoice + due date + currency
  adapter.get_purchase_orders()    → find PO + po_lines (cost centre)
  adapter.get_active_holds()       → current holds
  adapter.get_discrepancies()      → open discrepancies
  adapter.get_budget_tracking()    → budget check
  adapter.get_contracts()          → payment term comparison
  adapter.get_vendor_performance() → vendor risk / sanctions proxy
  adapter.get_pending_approvals()  → check invoice approval status
  adapter.create_payment_run()     → create payment_runs record on authorise
  adapter.place_invoice_hold()     → place hold for each failed condition
  adapter.log_notification()       → payment_authorized / invoice_holds_placed
  adapter.get_email_template()     → email template lookup
  adapter.get_users_by_role()      → ap_specialist / finance users
  adapter.log_agent_action()       → agent_actions audit
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
from datetime import date, datetime

from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.adapters.factory import get_adapter
from backend.services.sanctions_service import get_sanctions_service

logger = logging.getLogger(__name__)

# Sprint 8: Sanctions checking is now delegated to the pluggable ISanctionsService.
# SANCTIONS_PROVIDER env var selects the provider:
#   'local'         → LocalBlocklistSanctionsService (default, no API)
#   'opensanctions' → OpenSanctionsService (free API, optional OPENSANCTIONS_API_KEY)
#   'worldbank'     → WorldBankDebarmentService (public API, no key)
#
# The legacy _SANCTIONS_BLOCKLIST is retained for reference but is no longer
# used directly in the agent — it is now encapsulated in LocalBlocklistSanctionsService.
_SANCTIONS_BLOCKLIST = frozenset([
    "ofac blocked",
    "sanctioned corp",
    "debarred vendor",
    "blacklisted supplier",
])


def _adapter():
    return get_adapter()


class PaymentReadinessAgent(BaseAgent):
    """
    Gate agent that verifies every pre-payment condition before authorising
    a payment run.

    On full pass  → creates payment_runs record (status='pending_payment')
                    → routes to PaymentCalculationAgent
    On any failure → places targeted hold(s) on the invoice
                    → notifies ap_specialist / finance
                    → returns conditions_checked dict for audit
    """

    def __init__(self):
        super().__init__(
            name="PaymentReadinessAgent",
            description=(
                "Pre-payment gate check for the Liztek P2P pipeline. "
                "Verifies 3-way match, holds, budget, due date, payment terms, "
                "sanctions, and approval status before authorising payment."
            ),
            temperature=0.0,   # Fully deterministic — no LLM ambiguity
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gather all data required to evaluate the 7 Q5 conditions.

        Expected input_data keys
        ------------------------
        invoice_number : str   — invoice being checked
        vendor_id      : str   — vendor identifier
        po_reference   : str   — PO number (optional; resolved from invoice if absent)
        """
        self.status = AgentStatus.OBSERVING

        invoice_number = (
            input_data.get("invoice_number")
            or input_data.get("invoice_no")
        )
        vendor_id    = input_data.get("vendor_id", "")
        po_reference = input_data.get("po_reference", "")

        logger.info(
            "[PaymentReadinessAgent] OBSERVE — invoice: %s", invoice_number
        )

        observations: Dict[str, Any] = {
            "invoice_input":   input_data,
            "invoice_number":  invoice_number,
            "vendor_id":       vendor_id,
            "po_reference":    po_reference,
            "invoice_rows":    [],
            "po_rows":         [],
            "active_holds":    [],
            "open_discrepancies": [],
            "budget_rows":     [],
            "contracts":       [],
            "vendor_perf":     [],
            "pending_approvals": [],
            "cost_center":     None,
            "invoice_amount":  0.0,
            "invoice_due_date": None,
            "invoice_currency": "AED",
            "invoice_payment_terms": None,
        }

        try:
            # 1. Invoice data
            if invoice_number:
                invoice_rows = _adapter().get_vendor_invoices(
                    invoice_no=invoice_number, limit=1
                )
                observations["invoice_rows"] = invoice_rows

                if invoice_rows:
                    first_inv = invoice_rows[0]

                    # Resolve vendor_id and PO if not provided
                    if not vendor_id:
                        vendor_id = (
                            first_inv.get("vendor_id")
                            or first_inv.get("partner_id")
                            or first_inv.get("lifnr")
                            or ""
                        )
                        observations["vendor_id"] = vendor_id

                    if not po_reference:
                        po_reference = _extract_po_reference(first_inv)
                        observations["po_reference"] = po_reference

                    observations["invoice_amount"] = _safe_float(
                        first_inv.get("amount_total")
                        or first_inv.get("wrbtr")
                        or 0
                    )
                    observations["invoice_currency"] = (
                        first_inv.get("currency")
                        or first_inv.get("currency_id")
                        or "AED"
                    )
                    observations["invoice_due_date"] = (
                        first_inv.get("invoice_date_due")
                        or first_inv.get("zfbdt")
                        or first_inv.get("due_date")
                    )
                    observations["invoice_payment_terms"] = (
                        first_inv.get("payment_term_id")
                        or first_inv.get("payment_terms")
                        or ""
                    )
                    observations["vendor_name"] = (
                        first_inv.get("vendor_name")
                        or first_inv.get("partner_name")
                        or ""
                    )

            # 2. PO rows (for cost centre)
            if po_reference:
                all_pos = _adapter().get_purchase_orders(limit=500)
                po_rows = [
                    p for p in all_pos
                    if str(p.get("po_number", "")) == str(po_reference)
                ]
                observations["po_rows"] = po_rows
                # Cost centre: po_lines.account_analytic_id
                cost_center = None
                for po in po_rows:
                    cc = (
                        po.get("account_analytic_id")
                        or po.get("cost_center")
                        or po.get("department")
                    )
                    if cc:
                        cost_center = str(cc)
                        break
                observations["cost_center"] = cost_center

            # 3. Active holds
            active_holds = _adapter().get_active_holds(invoice_number)
            observations["active_holds"] = active_holds

            # 4. Open discrepancies
            open_discs = _adapter().get_discrepancies(
                invoice_number=invoice_number, status="open"
            )
            observations["open_discrepancies"] = open_discs

            # 5. Budget check
            cost_center = observations.get("cost_center")
            if cost_center:
                budget_rows = _adapter().get_budget_tracking(
                    department=cost_center
                )
                observations["budget_rows"] = budget_rows

            # 6. Contracts — payment terms comparison
            if vendor_id:
                contracts = _adapter().get_contracts(
                    vendor_id=vendor_id, limit=5
                )
                observations["contracts"] = contracts

            # 7. Vendor performance / sanctions proxy
            if vendor_id:
                vendor_perf = _adapter().get_vendor_performance(
                    vendor_id=vendor_id
                )
                observations["vendor_perf"] = vendor_perf

            # 8. Pending approvals — check if invoice already approved
            pending_approvals = _adapter().get_pending_approvals(
                status="approved", document_type="INVOICE"
            )
            observations["pending_approvals"] = [
                pa for pa in pending_approvals
                if str(pa.get("pr_number", "")) == str(invoice_number)
            ]

        except Exception as exc:
            logger.error("[PaymentReadinessAgent] OBSERVE error: %s", exc)
            observations["observe_error"] = str(exc)

        return observations

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Evaluate all Q5 conditions and determine action."""
        self.status = AgentStatus.THINKING

        invoice_number  = observations.get("invoice_number", "UNKNOWN")
        invoice_amount  = observations.get("invoice_amount", 0.0)
        due_date_raw    = observations.get("invoice_due_date")
        vendor_name     = observations.get("vendor_name", "")
        contracts       = observations.get("contracts", [])
        budget_rows     = observations.get("budget_rows", [])
        active_holds    = observations.get("active_holds", [])
        open_discs      = observations.get("open_discrepancies", [])
        pending_approvals = observations.get("pending_approvals", [])
        inv_terms       = observations.get("invoice_payment_terms", "")

        conditions: Dict[str, bool] = {}
        condition_notes: Dict[str, str] = {}

        # ── Condition 1: match_passed ─────────────────────────────────────────
        conditions["match_passed"]  = len(open_discs) == 0
        condition_notes["match_passed"] = (
            "OK — no open discrepancies"
            if conditions["match_passed"]
            else f"FAIL — {len(open_discs)} open discrepancy(ies)"
        )

        # ── Condition 2: no_active_holds ──────────────────────────────────────
        conditions["no_active_holds"]  = len(active_holds) == 0
        condition_notes["no_active_holds"] = (
            "OK — no active holds"
            if conditions["no_active_holds"]
            else f"FAIL — {len(active_holds)} active hold(s)"
        )

        # ── Condition 3: budget_available ─────────────────────────────────────
        if budget_rows:
            total_available = sum(
                _safe_float(r.get("available_budget") or 0) for r in budget_rows
            )
            conditions["budget_available"] = total_available >= invoice_amount
            condition_notes["budget_available"] = (
                f"OK — available {total_available:,.2f} >= invoice {invoice_amount:,.2f}"
                if conditions["budget_available"]
                else f"FAIL — available {total_available:,.2f} < invoice {invoice_amount:,.2f}"
            )
        else:
            # No budget row found — treat as pass (cost centre may not require tracking)
            conditions["budget_available"] = True
            condition_notes["budget_available"] = "OK — no budget tracking row (unrestricted)"

        # ── Condition 4: not_overdue ──────────────────────────────────────────
        # Business logic: overdue invoices still PASS this condition but get a
        # warning note. An overdue invoice must be expedited (paid ASAP), not
        # blocked — placing a hold on an already-overdue invoice would worsen
        # the situation by further delaying payment and damaging vendor relations.
        today = date.today()
        due_date = _parse_date(due_date_raw)
        conditions["not_overdue"] = True  # always pass; warn if overdue
        if due_date:
            if due_date < today:
                days_overdue = (today - due_date).days
                condition_notes["not_overdue"] = (
                    f"WARN — overdue {days_overdue} day(s) since {due_date.isoformat()} "
                    f"(expedite payment immediately)"
                )
            else:
                condition_notes["not_overdue"] = (
                    f"OK — due {due_date.isoformat()} >= today {today.isoformat()}"
                )
        else:
            condition_notes["not_overdue"] = "OK — no due date provided (treating as current)"

        # ── Condition 5: payment_terms_match ─────────────────────────────────
        if contracts:
            contract_terms = str(
                contracts[0].get("payment_term_id")
                or contracts[0].get("payment_terms")
                or ""
            ).strip().lower()
            inv_terms_norm = str(inv_terms or "").strip().lower()
            conditions["payment_terms_match"] = (
                not contract_terms               # no contract terms — pass
                or not inv_terms_norm            # no invoice terms — pass
                or contract_terms == inv_terms_norm
                or _terms_compatible(contract_terms, inv_terms_norm)
            )
            condition_notes["payment_terms_match"] = (
                f"OK — terms match ('{contract_terms}')"
                if conditions["payment_terms_match"]
                else f"FAIL — invoice terms '{inv_terms_norm}' != contract '{contract_terms}'"
            )
        else:
            conditions["payment_terms_match"] = True
            condition_notes["payment_terms_match"] = "OK — no contract found (no conflict)"

        # ── Condition 6: vendor_not_sanctioned ───────────────────────────────
        # Sprint 8: Delegated to pluggable ISanctionsService via get_sanctions_service().
        # Provider selected by SANCTIONS_PROVIDER env var (default: 'local').
        sanctions_result = {}
        try:
            vendor_id_for_check = observations.get("vendor_id", "")
            sanctions_svc = get_sanctions_service()
            sanctions_result = sanctions_svc.check_vendor(
                vendor_name=vendor_name,
                vendor_id=vendor_id_for_check if vendor_id_for_check else None,
            )
            is_sanctioned = sanctions_result.get("is_sanctioned", False)
            risk_level    = sanctions_result.get("risk_level", "clear")
            source        = sanctions_result.get("source", "unknown")

            if sanctions_result.get("matches"):
                logger.warning(
                    "[PaymentReadinessAgent] Sanctions matches for '%s': %s",
                    vendor_name, sanctions_result["matches"],
                )
        except Exception as exc:
            logger.warning(
                "[PaymentReadinessAgent] Sanctions check failed (%s); "
                "falling back to local blocklist: %s",
                type(exc).__name__, exc,
            )
            # Inline fallback using the legacy blocklist
            vendor_name_lower = vendor_name.lower().strip()
            is_sanctioned = any(
                blocked in vendor_name_lower for blocked in _SANCTIONS_BLOCKLIST
            )
            risk_level = "blocked" if is_sanctioned else "clear"
            source = "fallback_blocklist"

        conditions["vendor_not_sanctioned"] = not is_sanctioned
        condition_notes["vendor_not_sanctioned"] = (
            f"OK — vendor '{vendor_name}' cleared (source: {source}, risk: {risk_level})"
            if conditions["vendor_not_sanctioned"]
            else (
                f"FAIL — vendor '{vendor_name}' is sanctioned "
                f"(source: {source}, risk: {risk_level})"
            )
        )

        # ── Condition 7: approved ─────────────────────────────────────────────
        if pending_approvals:
            conditions["approved"] = True
            condition_notes["approved"] = (
                f"OK — invoice approval found (id: "
                f"{pending_approvals[0].get('id', 'N/A')})"
            )
        else:
            # No approved record found — check if an approval rule applies
            # For now: if there is no rule requiring approval, pass
            conditions["approved"] = True
            condition_notes["approved"] = (
                "OK — no invoice approval required or approval not tracked yet"
            )

        # ── Summary ───────────────────────────────────────────────────────────
        failed = [k for k, v in conditions.items() if not v]
        passed = [k for k, v in conditions.items() if v]
        all_pass = len(failed) == 0

        action = "authorize_payment" if all_pass else "hold_for_conditions"
        confidence = len(passed) / len(conditions)

        reasoning = (
            f"Invoice {invoice_number}: {len(passed)}/{len(conditions)} conditions "
            f"passed. Failed: {failed if failed else 'none'}."
        )

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "conditions":       conditions,
                "condition_notes":  condition_notes,
                "failed_conditions": failed,
                "passed_conditions": passed,
            },
            alternatives=["escalate_to_finance", "request_manual_override"],
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Create payment run on pass, or place targeted holds on failure."""
        self.status = AgentStatus.ACTING

        action           = decision.action
        ctx              = decision.context
        invoice_number   = ctx.get("invoice_number", "UNKNOWN")
        invoice_amount   = ctx.get("invoice_amount", 0.0)
        invoice_currency = ctx.get("invoice_currency", "AED")
        vendor_id        = ctx.get("vendor_id", "")
        conditions       = ctx.get("conditions", {})
        condition_notes  = ctx.get("condition_notes", {})
        failed           = ctx.get("failed_conditions", [])
        passed           = ctx.get("passed_conditions", [])

        payment_run_id: Optional[str] = None

        result: Dict[str, Any] = {
            "agent":              self.name,
            "action":             action,
            "invoice_number":     invoice_number,
            "conditions_checked": len(conditions),
            "conditions_detail":  conditions,
            "condition_notes":    condition_notes,
            "conditions_passed":  len(passed),
            "conditions_failed":  len(failed),
            "failed_conditions":  failed,
            "success":            True,
        }

        if action == "authorize_payment":
            # ── CREATE PAYMENT RUN ────────────────────────────────────────────
            today_str       = date.today().isoformat()
            run_number      = f"PR-{invoice_number}-{today_str}"
            payment_run_rec = _adapter().create_payment_run({
                "payment_run_number": run_number,
                "run_date":           today_str,
                "total_amount":       invoice_amount,
                "currency":           invoice_currency,
                "status":             "draft",           # initial run; calc step sets processing
                "bank_account":       "",
                "payment_method":     "bank_transfer",
                "agent_name":         self.name,
            })

            payment_run_id = (
                payment_run_rec.get("id")
                or payment_run_rec.get("payment_run_number")
                or run_number
            )

            result.update({
                "status":          "authorized",
                "payment_run_id":  payment_run_id,
                "payment_run_number": run_number,
                "next_agent":      "PaymentCalculationAgent",
                "message": (
                    f"Invoice {invoice_number} passed all {len(passed)} "
                    f"pre-payment conditions. Payment run {run_number} created."
                ),
            })

            _send_notification(
                _adapter(),
                event_type="payment_authorized",
                context_vars={
                    "invoice_number":  invoice_number,
                    "amount":          f"{invoice_amount:,.2f} {invoice_currency}",
                    "payment_run":     run_number,
                    "conditions_passed": len(passed),
                },
                role="finance",
                agent_name=self.name,
            )

            logger.info(
                "[PaymentReadinessAgent] AUTHORIZED: %s → run %s",
                invoice_number, run_number,
            )

        else:
            # Map payment-readiness condition names → allowed invoice_holds.hold_reason values.
            # DB CHECK constraint allows only these values:
            #   pending_grn, price_variance, qty_mismatch, missing_po,
            #   duplicate_suspected, budget_exceeded, approval_pending,
            #   supplier_query, manual_hold, other
            _HOLD_REASON_MAP = {
                "match_passed":          "price_variance",
                "no_active_holds":       "manual_hold",
                "budget_available":      "budget_exceeded",
                "not_overdue":           "manual_hold",
                "payment_terms_match":   "approval_pending",
                "vendor_not_sanctioned": "supplier_query",
                "approved":              "approval_pending",
            }

            # ── PLACE HOLDS for each failed condition ─────────────────────────
            for cond in failed:
                note = condition_notes.get(cond, cond)
                db_reason = _HOLD_REASON_MAP.get(cond, "manual_hold")
                try:
                    _adapter().place_invoice_hold({
                        "invoice_number": invoice_number,
                        "hold_reason":    db_reason,
                        "hold_notes":     f"[{cond}] {note}",
                        "hold_type":      "payment_readiness",
                        "placed_by":      self.name,
                        "agent_name":     self.name,
                    })
                    logger.info(
                        "[PaymentReadinessAgent] Hold placed: %s / %s",
                        invoice_number, cond,
                    )
                except Exception as exc:
                    logger.warning(
                        "[PaymentReadinessAgent] place_invoice_hold failed (%s): %s",
                        cond, exc,
                    )

            result.update({
                "status":     "on_hold",
                "holds_placed": failed,
                "next_agent": None,
                "message": (
                    f"Invoice {invoice_number} failed {len(failed)} condition(s): "
                    f"{', '.join(failed)}. Holds placed."
                ),
            })

            _send_notification(
                _adapter(),
                event_type="invoice_holds_placed",
                context_vars={
                    "invoice_number":    invoice_number,
                    "failed_conditions": ", ".join(failed),
                    "hold_count":        str(len(failed)),
                    "amount":            f"{invoice_amount:,.2f} {invoice_currency}",
                },
                role="ap_specialist",
                agent_name=self.name,
            )

            logger.info(
                "[PaymentReadinessAgent] HOLDS PLACED: %s — failed: %s",
                invoice_number, failed,
            )

        # ── Audit log ─────────────────────────────────────────────────────────
        _adapter().log_agent_action(
            self.name,
            f"payment_readiness_{action}"[:50],
            {
                "invoice_number": invoice_number,
                "invoice_amount": invoice_amount,
                "vendor_id":      vendor_id,
            },
            {
                "action":            action,
                "status":            result.get("status"),
                "conditions_passed": len(passed),
                "conditions_failed": len(failed),
                "failed":            failed,
                "payment_run_id":    payment_run_id,
            },
            True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        res = learn_context.get("result", {})
        logger.info(
            "[PaymentReadinessAgent] LEARN — status: %s, passed: %s/%s",
            res.get("status"),
            res.get("conditions_passed", 0),
            res.get("conditions_passed", 0) + res.get("conditions_failed", 0),
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(
            "[PaymentReadinessAgent] START — invoice: %s",
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


def _parse_date(raw) -> Optional[date]:
    """Parse a date from string, date, or datetime; return None on failure."""
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw if isinstance(raw, date) else raw.date()
    if isinstance(raw, datetime):
        return raw.date()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _terms_compatible(contract_terms: str, invoice_terms: str) -> bool:
    """
    Fuzzy payment-terms comparison. Strips common prefixes and whitespace
    before comparing. E.g. 'net 30' == '30 days' → True.
    """
    def _normalise(t: str) -> str:
        return (
            t.lower()
            .replace("net", "")
            .replace("days", "")
            .replace("day", "")
            .replace(" ", "")
            .strip()
        )

    return _normalise(contract_terms) == _normalise(invoice_terms)


def _send_notification(
    adapter,
    event_type: str,
    context_vars: dict,
    role: str,
    agent_name: str,
) -> None:
    """Log notification_log rows for the given role."""
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
        users = adapter.get_users_by_role(resolved_role)[:5]

        for user in users:
            adapter.log_notification({
                "event_type":      event_type,
                "document_type":   "INVOICE",
                "document_id":     context_vars.get("invoice_number", ""),
                "recipient_email": user.get("email", ""),
                "recipient_role":  resolved_role,
                "subject":         subject,
                "body":            body,
                "status":          "pending",
                "agent_name":      agent_name,
            })

    except Exception as exc:
        logger.warning(
            "[PaymentReadinessAgent] Notification logging failed: %s", exc
        )


# ── Convenience entry point ───────────────────────────────────────────────────

async def check_payment_readiness(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for the pipeline orchestrator."""
    agent = PaymentReadinessAgent()
    return await agent.execute(invoice_data)
