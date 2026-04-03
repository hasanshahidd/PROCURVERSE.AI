"""
PaymentCalculationAgent — Step 8 of the 9-agent Invoice-to-Payment Pipeline
============================================================================
Liztek P2P Flow: Exact Payment Amount Determination

Calculates the precise amount to pay: full or partial (Q6), with optional
early-payment discount and FX conversion.

Payment type rules (Q6)
------------------------
FULL    — GRN delivered qty >= invoiced qty  (or GRN qty >= PO qty)
           pay the full invoice amount
PARTIAL — GRN delivered qty < invoiced qty
           pay (grn_qty / invoice_qty) × invoice_amount for received goods only

Early payment discount
-----------------------
Extracted from contracts: discount_days and discount_pct (e.g. 2/10 Net 30).
If today falls within the discount window, the discount is applied to the
net payable amount.

FX conversion
-------------
If invoice currency != base currency (AED default), the exchange_rates table
is consulted to convert to AED for the payment run.

Adapter methods used (ZERO hardcoded SQL):
  adapter.get_vendor_invoices()    → invoice amount, due date, currency
  adapter.get_purchase_orders()    → PO + po_lines (ordered qty, invoiced qty)
  adapter.get_grn_headers()        → GRN headers linked to PO
  adapter.get_exchange_rates()     → FX rates
  adapter.get_contracts()          → early payment discount terms
  adapter.create_payment_run()     → update / create payment_runs record
  adapter.log_notification()       → payment_scheduled
  adapter.get_email_template()     → email template lookup
  adapter.get_users_by_role()      → finance / ap_specialist users
  adapter.log_agent_action()       → agent_actions audit
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
import os
from datetime import date, datetime

from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.adapters.factory import get_adapter
from backend.services.fx_service import get_fx_service

logger = logging.getLogger(__name__)

_BASE_CURRENCY = os.environ.get("FX_BASE_CURRENCY", "AED").upper()


def _adapter():
    return get_adapter()


class PaymentCalculationAgent(BaseAgent):
    """
    Calculates the exact net payable amount for an authorised invoice.

    Pipeline position: follows PaymentReadinessAgent, precedes PaymentApprovalAgent.

    Key logic
    ---------
    1. Determine total GRN quantity delivered.
    2. Compare to invoiced quantity → full or partial payment.
    3. Apply early-payment discount if within discount window.
    4. Convert to base currency (AED) if required.
    5. Update the payment_runs record created by PaymentReadinessAgent.
    """

    def __init__(self):
        super().__init__(
            name="PaymentCalculationAgent",
            description=(
                "Calculates the exact net payable amount (full or partial) for "
                "an invoice authorised by PaymentReadinessAgent. Applies early "
                "payment discounts and FX conversion where applicable."
            ),
            temperature=0.0,
        )

    # ── OBSERVE ───────────────────────────────────────────────────────────────

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch invoice, PO, GRN, exchange-rate, and contract data.

        Expected input_data keys
        ------------------------
        invoice_number      : str — invoice being processed
        vendor_id           : str — vendor identifier
        po_reference        : str — PO number (resolved from invoice if absent)
        payment_run_number  : str — run number created by PaymentReadinessAgent
        """
        self.status = AgentStatus.OBSERVING

        invoice_number     = (
            input_data.get("invoice_number")
            or input_data.get("invoice_no")
        )
        vendor_id          = input_data.get("vendor_id", "")
        po_reference       = input_data.get("po_reference", "")
        payment_run_number = input_data.get("payment_run_number", "")

        logger.info(
            "[PaymentCalculationAgent] OBSERVE — invoice: %s, run: %s",
            invoice_number, payment_run_number,
        )

        observations: Dict[str, Any] = {
            "invoice_input":       input_data,
            "invoice_number":      invoice_number,
            "vendor_id":           vendor_id,
            "po_reference":        po_reference,
            "payment_run_number":  payment_run_number,
            "invoice_rows":        [],
            "po_rows":             [],
            "grn_rows":            [],
            "exchange_rates":      [],
            "contracts":           [],
            # Seed from input payload as fallback (for synthetic/new invoices not yet in ERP)
            "invoice_amount":      _safe_float(input_data.get("invoice_amount", 0)),
            "invoice_qty":         0.0,
            "invoice_currency":    input_data.get("currency", _BASE_CURRENCY),
            "invoice_due_date":    input_data.get("due_date"),
        }

        try:
            # 1. Invoice data — ERP lookup (overrides input-seed if found)
            if invoice_number:
                invoice_rows = _adapter().get_vendor_invoices(
                    invoice_no=invoice_number, limit=1
                )
                observations["invoice_rows"] = invoice_rows

                if invoice_rows:
                    first_inv = invoice_rows[0]

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
                        or _BASE_CURRENCY
                    )
                    observations["invoice_due_date"] = (
                        first_inv.get("invoice_date_due")
                        or first_inv.get("zfbdt")
                        or first_inv.get("due_date")
                    )
                    # Invoice quantity (sum of line quantities if available)
                    observations["invoice_qty"] = _safe_float(
                        first_inv.get("qty_invoiced")
                        or first_inv.get("product_qty")
                        or 0
                    )

            # 2. PO rows
            if po_reference:
                all_pos = _adapter().get_purchase_orders(limit=500)
                po_rows = [
                    p for p in all_pos
                    if str(p.get("po_number", "")) == str(po_reference)
                ]
                observations["po_rows"] = po_rows

            # 3. GRN headers (linked via PO number per the 3-way match chain)
            if po_reference:
                grn_rows = _adapter().get_grn_headers(
                    po_number=po_reference, limit=50
                )
                observations["grn_rows"] = grn_rows

            # 4. Exchange rates — Sprint 8: use pluggable FX service
            # FX_PROVIDER env var selects the provider (default: 'static').
            # The fx_service is stored on observations for use in decide().
            observations["_fx_service"] = get_fx_service()
            # Also keep exchange_rates list for backward compat with _get_fx_rate()
            try:
                exchange_rates = _adapter().get_exchange_rates()
            except Exception:
                exchange_rates = []
            observations["exchange_rates"] = exchange_rates

            # 5. Contracts — early payment discount
            if vendor_id:
                contracts = _adapter().get_contracts(
                    vendor_id=vendor_id, limit=5
                )
                observations["contracts"] = contracts

        except Exception as exc:
            logger.error("[PaymentCalculationAgent] OBSERVE error: %s", exc)
            observations["observe_error"] = str(exc)

        return observations

    # ── DECIDE ────────────────────────────────────────────────────────────────

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Determine payment_type (full/partial), apply discount, convert FX.
        """
        self.status = AgentStatus.THINKING

        invoice_number   = observations.get("invoice_number", "UNKNOWN")
        invoice_amount   = observations.get("invoice_amount", 0.0)
        invoice_qty      = observations.get("invoice_qty", 0.0)
        invoice_currency = observations.get("invoice_currency", _BASE_CURRENCY)
        grn_rows         = observations.get("grn_rows", [])
        po_rows          = observations.get("po_rows", [])
        contracts        = observations.get("contracts", [])
        exchange_rates   = observations.get("exchange_rates", [])
        due_date_raw     = observations.get("invoice_due_date")

        # ── Step 1: Aggregate GRN quantities ─────────────────────────────────
        grn_qty  = _sum_grn_qty(grn_rows)
        po_qty   = _sum_po_qty(po_rows)

        # Fallback: if invoice_qty is not on the invoice row, use po_qty
        if invoice_qty <= 0:
            invoice_qty = po_qty

        logger.info(
            "[PaymentCalculationAgent] Qtys — GRN: %.2f, Invoice: %.2f, PO: %.2f",
            grn_qty, invoice_qty, po_qty,
        )

        # ── Step 2: Full vs Partial ───────────────────────────────────────────
        if invoice_qty <= 0 or grn_qty >= invoice_qty or grn_qty >= po_qty:
            payment_type = "full"
            grn_amount   = invoice_amount
            confidence   = 0.95
        else:
            payment_type = "partial"
            ratio        = grn_qty / invoice_qty if invoice_qty > 0 else 1.0
            grn_amount   = round(ratio * invoice_amount, 2)
            confidence   = 0.85

        # ── Step 3: Early payment discount ───────────────────────────────────
        discount_applied = 0.0
        discount_pct     = 0.0
        discount_note    = ""

        due_date = _parse_date(due_date_raw)
        today    = date.today()

        if contracts:
            contract = contracts[0]
            raw_discount_pct  = _safe_float(
                contract.get("discount_pct")
                or contract.get("early_payment_discount_pct")
                or 0
            )
            raw_discount_days = int(
                _safe_float(
                    contract.get("discount_days")
                    or contract.get("early_payment_days")
                    or 0
                )
            )

            if raw_discount_pct > 0 and raw_discount_days > 0 and due_date:
                # Discount window: due_date - payment_term_days + discount_days
                # Simplified: if today is within raw_discount_days of invoice creation
                # Use due_date as upper bound; if payment is soon, discount applies
                days_until_due = (due_date - today).days
                if days_until_due >= (raw_discount_days - 10):  # within window
                    discount_pct     = raw_discount_pct / 100.0
                    discount_applied = round(grn_amount * discount_pct, 2)
                    discount_note    = (
                        f"Early payment discount {raw_discount_pct}% applied "
                        f"(within {raw_discount_days}-day window)."
                    )
                    logger.info(
                        "[PaymentCalculationAgent] Discount applied: %.2f",
                        discount_applied,
                    )

        net_payable_original = round(grn_amount - discount_applied, 2)

        # ── Step 3b: Tax calculation (Sprint 10) ─────────────────────────────
        # Non-breaking: if tax service fails, skip tax and log a warning.
        tax_amount = 0.0
        tax_rate = 0.0
        tax_name = ""
        tax_details = ""
        try:
            from backend.services.tax_service import calculate_tax
            # Determine country from invoice currency as a heuristic
            _currency_to_country = {
                "AED": "AE", "SAR": "SA", "BHD": "BH", "OMR": "OM",
                "GBP": "GB", "EUR": "DE", "USD": "US", "CAD": "CA",
                "INR": "IN", "SGD": "SG", "JPY": "JP",
            }
            tax_country = _currency_to_country.get(
                invoice_currency.upper(), "AE"
            )
            tax_result = calculate_tax(
                amount=net_payable_original,
                country_code=tax_country,
            )
            tax_amount = tax_result.get("tax_amount", 0.0)
            tax_rate = tax_result.get("tax_rate", 0.0)
            tax_name = tax_result.get("tax_name", "")
            tax_details = tax_result.get("details", "")
            if tax_amount > 0:
                net_payable_original = round(net_payable_original + tax_amount, 2)
                logger.info(
                    "[PaymentCalculationAgent] Tax applied: %s %.2f (%s)",
                    tax_name, tax_amount, tax_details,
                )
        except Exception as tax_exc:
            logger.warning(
                "[PaymentCalculationAgent] Tax calculation skipped: %s", tax_exc
            )

        # ── Step 4: FX conversion ─────────────────────────────────────────────
        # Sprint 8: Use pluggable IFXService for currency conversion.
        # Prefers the fx_service stored in observations during OBSERVE.
        # Falls back to the legacy _get_fx_rate() using exchange_rates rows if needed.
        fx_rate    = 1.0
        net_payable_aed = net_payable_original

        if invoice_currency.upper() != _BASE_CURRENCY:
            fx_svc = observations.get("_fx_service")
            if fx_svc is not None:
                try:
                    fx_rate = fx_svc.get_rate(invoice_currency, _BASE_CURRENCY)
                    net_payable_aed = fx_svc.convert(
                        net_payable_original, invoice_currency, _BASE_CURRENCY
                    )
                    logger.info(
                        "[PaymentCalculationAgent] FX %s→%s rate=%.6f (via %s)",
                        invoice_currency, _BASE_CURRENCY, fx_rate,
                        type(fx_svc).__name__,
                    )
                except Exception as exc:
                    logger.warning(
                        "[PaymentCalculationAgent] FX service failed (%s); "
                        "falling back to legacy exchange_rates: %s",
                        type(exc).__name__, exc,
                    )
                    fx_rate = _get_fx_rate(invoice_currency, exchange_rates)
                    net_payable_aed = round(net_payable_original * fx_rate, 2)
            else:
                # No fx_service in observations — use legacy helper
                fx_rate = _get_fx_rate(invoice_currency, exchange_rates)
                net_payable_aed = round(net_payable_original * fx_rate, 2)

        context_update = {
            "payment_type":          payment_type,
            "grn_qty":               grn_qty,
            "invoice_qty":           invoice_qty,
            "po_qty":                po_qty,
            "grn_amount":            grn_amount,
            "invoice_amount":        invoice_amount,
            "discount_applied":      discount_applied,
            "discount_pct":          discount_pct * 100,
            "discount_note":         discount_note,
            "tax_amount":            tax_amount,
            "tax_rate":              tax_rate,
            "tax_name":              tax_name,
            "tax_details":           tax_details,
            "net_payable":           net_payable_original,
            "net_payable_aed":       net_payable_aed,
            "fx_rate":               fx_rate,
            "invoice_currency":      invoice_currency,
            "base_currency":         _BASE_CURRENCY,
        }

        reasoning = (
            f"Invoice {invoice_number}: {payment_type.upper()} payment. "
            f"GRN qty {grn_qty:.0f} / Invoice qty {invoice_qty:.0f}. "
            f"GRN amount {grn_amount:,.2f}, discount {discount_applied:,.2f}, "
            + (f"tax {tax_amount:,.2f} ({tax_name}), " if tax_amount > 0 else "")
            + f"net payable {net_payable_original:,.2f} {invoice_currency}"
            + (f" = {net_payable_aed:,.2f} {_BASE_CURRENCY}" if fx_rate != 1.0 else "")
            + f". {discount_note}"
        )

        return AgentDecision(
            action="calculate_payment",
            reasoning=reasoning,
            confidence=confidence,
            context={**observations, **context_update},
            alternatives=["request_po_confirmation", "request_grn_confirmation"],
        )

    # ── ACT ───────────────────────────────────────────────────────────────────

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Update the payment_runs record with calculated amounts."""
        self.status = AgentStatus.ACTING

        ctx                  = decision.context
        invoice_number       = ctx.get("invoice_number", "UNKNOWN")
        payment_run_number   = ctx.get("payment_run_number", "")
        payment_type         = ctx.get("payment_type", "full")
        invoice_amount       = ctx.get("invoice_amount", 0.0)
        grn_amount           = ctx.get("grn_amount", invoice_amount)
        discount_applied     = ctx.get("discount_applied", 0.0)
        discount_pct         = ctx.get("discount_pct", 0.0)
        discount_note        = ctx.get("discount_note", "")
        tax_amount           = ctx.get("tax_amount", 0.0)
        tax_rate             = ctx.get("tax_rate", 0.0)
        tax_name             = ctx.get("tax_name", "")
        net_payable          = ctx.get("net_payable", grn_amount)
        net_payable_aed      = ctx.get("net_payable_aed", net_payable)
        invoice_currency     = ctx.get("invoice_currency", _BASE_CURRENCY)
        fx_rate              = ctx.get("fx_rate", 1.0)
        vendor_id            = ctx.get("vendor_id", "")
        today_str            = date.today().isoformat()

        # Build / update the payment run
        if not payment_run_number:
            payment_run_number = f"PR-{invoice_number}-{today_str}"

        payment_run_rec = _adapter().create_payment_run({
            "payment_run_number": payment_run_number,
            "run_date":           today_str,
            "total_amount":       net_payable_aed,
            "currency":           _BASE_CURRENCY,
            "status":             "processing",        # amounts calculated; awaiting approval
            "bank_account":       "",
            "payment_method":     "bank_transfer",
            "agent_name":         self.name,
            # Extended fields stored in the run for downstream reference
            "invoice_amount":     invoice_amount,
            "grn_amount":         grn_amount,
            "discount_applied":   discount_applied,
            "discount_pct":       discount_pct,
            "net_payable_orig":   net_payable,
            "invoice_currency":   invoice_currency,
            "fx_rate":            fx_rate,
            "payment_type":       payment_type,
        })

        payment_run_id = (
            payment_run_rec.get("id")
            or payment_run_rec.get("payment_run_number")
            or payment_run_number
        )

        # Notification — payment scheduled
        _send_notification(
            _adapter(),
            event_type="payment_scheduled",
            context_vars={
                "invoice_number":   invoice_number,
                "payment_run":      payment_run_number,
                "payment_type":     payment_type,
                "invoice_amount":   f"{invoice_amount:,.2f} {invoice_currency}",
                "grn_amount":       f"{grn_amount:,.2f} {invoice_currency}",
                "discount":         f"{discount_applied:,.2f}" if discount_applied else "none",
                "net_payable":      f"{net_payable:,.2f} {invoice_currency}",
                "net_payable_aed":  f"{net_payable_aed:,.2f} {_BASE_CURRENCY}",
            },
            agent_name=self.name,
        )

        result: Dict[str, Any] = {
            "agent":               self.name,
            "action":              "calculate_payment",
            "invoice_number":      invoice_number,
            "payment_run_number":  payment_run_number,
            "payment_run_id":      payment_run_id,
            "payment_type":        payment_type,
            "invoice_amount":      invoice_amount,
            "grn_amount":          grn_amount,
            "discount_applied":    discount_applied,
            "discount_pct":        discount_pct,
            "discount_note":       discount_note,
            "tax_amount":          tax_amount,
            "tax_rate":            tax_rate,
            "tax_name":            tax_name,
            "net_payable":         net_payable,
            "net_payable_aed":     net_payable_aed,
            "invoice_currency":    invoice_currency,
            "base_currency":       _BASE_CURRENCY,
            "fx_rate":             fx_rate,
            "next_agent":          "PaymentApprovalAgent",
            "success":             True,
        }

        logger.info(
            "[PaymentCalculationAgent] CALCULATED: %s | %s | net %.2f %s",
            invoice_number, payment_type.upper(), net_payable, invoice_currency,
        )

        # ── Audit log ─────────────────────────────────────────────────────────
        _adapter().log_agent_action(
            self.name,
            "payment_calculation"[:50],
            {
                "invoice_number":    invoice_number,
                "invoice_amount":    invoice_amount,
                "vendor_id":         vendor_id,
            },
            {
                "payment_type":      payment_type,
                "net_payable":       net_payable,
                "net_payable_aed":   net_payable_aed,
                "discount_applied":  discount_applied,
                "fx_rate":           fx_rate,
                "payment_run":       payment_run_number,
            },
            True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        res = learn_context.get("result", {})
        logger.info(
            "[PaymentCalculationAgent] LEARN — type: %s, net: %.2f",
            res.get("payment_type", "unknown"),
            res.get("net_payable", 0.0),
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(
            "[PaymentCalculationAgent] START — invoice: %s",
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
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _sum_grn_qty(grn_rows: List[dict]) -> float:
    """
    Sum delivered/received quantities across all GRN rows.
    Checks multiple field names to handle different ERP adapters.
    """
    total = 0.0
    for row in grn_rows:
        total += _safe_float(
            row.get("quantity_done")
            or row.get("qty_done")
            or row.get("received_qty")
            or row.get("grn_qty")
            or row.get("product_uom_qty")
            or 0
        )
    return total


def _sum_po_qty(po_rows: List[dict]) -> float:
    """Sum ordered quantities across all PO rows."""
    total = 0.0
    for row in po_rows:
        total += _safe_float(
            row.get("product_qty")
            or row.get("po_qty")
            or row.get("ordered_qty")
            or row.get("quantity")
            or 0
        )
    return total


def _get_fx_rate(from_currency: str, exchange_rates: List[dict]) -> float:
    """
    Return the exchange rate from from_currency to AED.
    Returns 1.0 if the rate is not found (no conversion).
    """
    from_upper = from_currency.upper()
    for rate_row in exchange_rates:
        source = (rate_row.get("from_currency") or rate_row.get("currency") or "").upper()
        target = (rate_row.get("to_currency") or rate_row.get("base_currency") or "AED").upper()
        if source == from_upper and target == _BASE_CURRENCY:
            return _safe_float(rate_row.get("rate") or rate_row.get("exchange_rate") or 1)
    logger.warning(
        "[PaymentCalculationAgent] FX rate not found for %s → %s. Using 1.0.",
        from_currency, _BASE_CURRENCY,
    )
    return 1.0


def _send_notification(
    adapter,
    event_type: str,
    context_vars: dict,
    agent_name: str,
) -> None:
    """Log notification_log rows for the payment_scheduled event."""
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

        role  = template.get("recipients_role", "finance")
        users = adapter.get_users_by_role(role)[:5]

        for user in users:
            adapter.log_notification({
                "event_type":      event_type,
                "document_type":   "PAYMENT",
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
            "[PaymentCalculationAgent] Notification logging failed: %s", exc
        )


# ── Convenience entry point ───────────────────────────────────────────────────

async def calculate_payment(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for the pipeline orchestrator."""
    agent = PaymentCalculationAgent()
    return await agent.execute(invoice_data)
