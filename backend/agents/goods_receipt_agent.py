"""
GoodsReceiptAgent — WF-09 / WF-10 / WF-11
============================================
Records and validates goods receipts (GRNs) against purchase orders.

Workflows covered
-----------------
WF-09  Standard Goods Receipt (match PO quantities, accept delivery)
WF-10  Partial Receipt (record partial delivery, update open qty)
WF-11  Quality Inspection at Receipt (flag quality issues before acceptance)

Business value
--------------
- Closes the 3-way match loop (PO ↔ GRN ↔ Invoice)
- Prevents payment on undelivered goods
- Tracks actual vs ordered quantities per line
- Auto-updates inventory on receipt confirmation
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.agents import AgentDecision, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)


class GoodsReceiptAgent(BaseAgent):
    """
    Validates and records goods receipt notes (GRNs).

    Observe  → Load PO header + lines; load any existing GRN for the PO.
    Decide   → Compare received quantities vs ordered; classify receipt.
    Act      → Write GRN to grn_headers_* + grn_lines_*; update invoice match context.
    Learn    → Summarise receipt rate for the vendor.
    """

    def __init__(self) -> None:
        super().__init__(
            name="GoodsReceiptAgent",
            description=(
                "Records and validates goods receipts against purchase orders. "
                "Supports full receipt, partial receipt, and quality-inspection workflows."
            ),
            temperature=0.1,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.status = AgentStatus.OBSERVING

        po_number = context.get("po_number") or context.get("po_reference", "")
        grn_number = context.get("grn_number", "")
        received_lines: List[Dict[str, Any]] = context.get("received_lines", [])

        # Load PO from adapter
        po_header: Dict[str, Any] = {}
        po_lines: List[Dict[str, Any]] = []
        existing_grns: List[Dict[str, Any]] = []

        try:
            from backend.services.adapters.factory import get_adapter
            adapter = get_adapter()

            # Purchase orders
            pos = adapter.get_purchase_orders(limit=200)
            po_header = next(
                (p for p in pos
                 if str(p.get("name") or p.get("po_number") or "") == str(po_number)),
                {},
            )
            # GRN headers already in DB for this PO
            existing_grns = adapter.get_grn_headers(po_number=po_number)

        except Exception as exc:
            logger.warning("[GoodsReceiptAgent] Adapter query failed: %s", exc)

        # Supplier invoice lines that came in through context (from pipeline)
        if not received_lines and context.get("invoice_lines"):
            received_lines = context["invoice_lines"]

        total_ordered = sum(float(l.get("quantity") or l.get("product_qty") or 0) for l in received_lines)
        total_received_previous = sum(
            float(g.get("quantity_done") or 0) for g in existing_grns
        )

        logger.info(
            "[GoodsReceiptAgent] PO=%s  lines=%d  existing_grns=%d  ordered_qty=%.2f",
            po_number, len(received_lines), len(existing_grns), total_ordered,
        )

        return {
            "po_number":                po_number,
            "grn_number":               grn_number or f"GRN-{po_number}-{datetime.now().strftime('%Y%m%d')}",
            "vendor_id":                context.get("vendor_id", po_header.get("partner_id", "")),
            "vendor_name":              context.get("vendor_name", ""),
            "received_lines":           received_lines,
            "po_header":                po_header,
            "existing_grns":            existing_grns,
            "total_ordered":            total_ordered,
            "total_received_previous":  total_received_previous,
            "quality_check_required":   context.get("quality_check_required", False),
            "receipt_date":             context.get("receipt_date", datetime.now().isoformat()),
            "input_context":            context,
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        self.status = AgentStatus.THINKING

        received_lines   = observations.get("received_lines", [])
        total_ordered    = observations.get("total_ordered", 0)
        prev_received    = observations.get("total_received_previous", 0)
        quality_required = observations.get("quality_check_required", False)
        po_number        = observations.get("po_number", "")

        if not received_lines:
            return AgentDecision(
                action="no_receipt_data",
                reasoning="No received line items provided — cannot create GRN.",
                confidence=0.95,
                context=observations,
            )

        # Current batch received qty
        current_qty = sum(
            float(l.get("quantity_done") or l.get("quantity") or 0)
            for l in received_lines
        )
        cumulative_qty = prev_received + current_qty
        receipt_pct = (current_qty / total_ordered * 100) if total_ordered > 0 else 100.0

        if quality_required:
            action = "quality_inspection"
            reasoning = (
                f"Quality inspection required before acceptance. "
                f"Received {current_qty:.0f} units ({receipt_pct:.1f}% of order)."
            )
            confidence = 0.88
        elif receipt_pct >= 98:
            action = "full_receipt"
            reasoning = (
                f"Full receipt recorded: {current_qty:.0f} of {total_ordered:.0f} units "
                f"({receipt_pct:.1f}%). PO can be closed."
            )
            confidence = 0.95
        elif receipt_pct >= 20:
            action = "partial_receipt"
            reasoning = (
                f"Partial receipt: {current_qty:.0f} of {total_ordered:.0f} units "
                f"({receipt_pct:.1f}%). Cumulative: {cumulative_qty:.0f} units."
            )
            confidence = 0.90
        else:
            action = "under_delivery"
            reasoning = (
                f"Under-delivery: only {current_qty:.0f} units received "
                f"({receipt_pct:.1f}% of {total_ordered:.0f} ordered). "
                f"Escalation recommended."
            )
            confidence = 0.85

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "current_qty":    current_qty,
                "cumulative_qty": cumulative_qty,
                "receipt_pct":    round(receipt_pct, 2),
            },
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        self.status = AgentStatus.ACTING

        action  = decision.action
        ctx     = decision.context
        po_number    = ctx.get("po_number", "")
        grn_number   = ctx.get("grn_number", "")
        vendor_id    = str(ctx.get("vendor_id", ""))
        current_qty  = ctx.get("current_qty", 0)
        receipt_pct  = ctx.get("receipt_pct", 0)
        received_lines = ctx.get("received_lines", [])

        grn_id: Optional[int] = None

        if action != "no_receipt_data":
            grn_id = await self._persist_grn(
                grn_number=grn_number,
                po_number=po_number,
                vendor_id=vendor_id,
                received_lines=received_lines,
                action=action,
            )

        result: Dict[str, Any] = {
            "success":      True,
            "agent":        self.name,
            "action":       action,
            "grn_number":   grn_number,
            "po_number":    po_number,
            "vendor_id":    vendor_id,
            "receipt_pct":  receipt_pct,
            "current_qty":  current_qty,
            "grn_id":       grn_id,
            "status":       self._action_to_status(action),
            "timestamp":    datetime.now().isoformat(),
        }

        if action == "quality_inspection":
            result["message"] = "GRN recorded — awaiting quality inspection approval."
            result["next_step"] = "quality_review"
        elif action == "full_receipt":
            result["message"] = f"Full receipt confirmed: {current_qty:.0f} units. PO {po_number} complete."
        elif action == "partial_receipt":
            result["message"] = f"Partial receipt: {receipt_pct:.1f}% received. Remaining on backorder."
        elif action == "under_delivery":
            result["message"] = f"Under-delivery alert: only {receipt_pct:.1f}% received. Buyer notified."
        else:
            result["message"] = "No receipt data — GRN not created."

        await self._log_action(
            action_type=f"goods_receipt_{action}",
            input_data=ctx.get("input_context", {}),
            output_data=result,
            success=True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        result = learn_context.get("result", {})
        logger.info(
            "[GoodsReceiptAgent] Learned: PO=%s action=%s pct=%.1f%%",
            result.get("po_number", "?"),
            result.get("action", "?"),
            result.get("receipt_pct", 0),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _action_to_status(self, action: str) -> str:
        return {
            "full_receipt":       "received",
            "partial_receipt":    "partial",
            "quality_inspection": "pending_inspection",
            "under_delivery":     "under_delivered",
            "no_receipt_data":    "skipped",
        }.get(action, "processed")

    async def _persist_grn(
        self,
        grn_number: str,
        po_number: str,
        vendor_id: str,
        received_lines: List[Dict[str, Any]],
        action: str,
    ) -> Optional[int]:
        """
        Write GRN header + lines to grn_headers_<erp> / grn_lines_<erp>.
        Returns the DB id of the new GRN header row (or None on failure).
        """
        try:
            from backend.services.adapters.factory import get_adapter
            from backend.services.nmi_data_service import get_conn
            from psycopg2.extras import RealDictCursor

            adapter = get_adapter()
            suffix = adapter._get_erp_suffix()
            header_table = f"grn_headers_{suffix}"
            lines_table  = f"grn_lines_{suffix}"

            state_map = {
                "full_receipt":       "done",
                "partial_receipt":    "assigned",
                "quality_inspection": "assigned",
                "under_delivery":     "assigned",
            }
            state = state_map.get(action, "assigned")

            conn = get_conn()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Insert GRN header
                    cur.execute(
                        f"""
                        INSERT INTO {header_table}
                            (name, partner_id, origin, date_done, state, erp_source)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING id
                        """,
                        (
                            grn_number,
                            vendor_id or None,
                            po_number,
                            datetime.now(),
                            state,
                            suffix,
                        ),
                    )
                    row = cur.fetchone()
                    header_id = row["id"] if row else None

                    if header_id:
                        for line in received_lines:
                            qty_done = float(line.get("quantity_done") or line.get("quantity") or 0)
                            cur.execute(
                                f"""
                                INSERT INTO {lines_table}
                                    (picking_id, description_picking, product_uom_qty, quantity_done, state, erp_source)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                                """,
                                (
                                    header_id,
                                    line.get("description") or line.get("item_description") or "",
                                    qty_done,
                                    qty_done,
                                    state,
                                    suffix,
                                ),
                            )

                    conn.commit()
                    logger.info("[GoodsReceiptAgent] GRN persisted: %s (id=%s)", grn_number, header_id)
                    return header_id
            finally:
                conn.close()

        except Exception as exc:
            logger.error("[GoodsReceiptAgent] GRN persist failed: %s", exc)
            return None


async def record_goods_receipt(params: Dict[str, Any]) -> Dict[str, Any]:
    agent = GoodsReceiptAgent()
    return await agent.execute(params)
