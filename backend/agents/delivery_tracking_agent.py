"""
DeliveryTrackingAgent — WF-07
==============================
PO Delivery Tracking & Shipment Monitoring.

Workflows covered
-----------------
WF-07  PO Delivery Tracking & Shipment Monitoring
       Monitors open purchase orders against their GRN (goods receipt) status,
       calculates delivery health (on_track / delayed / critical / not_started),
       and raises alerts for overdue purchase orders.

Business value
--------------
- Proactive visibility into open PO delivery timelines
- Automatic delay alerting so buyers can chase vendors early
- Single dashboard view: ETA, % received, days overdue
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from backend.agents import AgentDecision, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)

# Days past expected delivery date that triggers each severity level
_DELAY_CRITICAL_DAYS = 14
_DELAY_WARNING_DAYS = 3


class DeliveryTrackingAgent(BaseAgent):
    """
    Tracks open PO delivery status by cross-referencing GRN headers.

    Observe  → Load open POs via adapter; load GRN headers per PO.
    Decide   → Classify each PO as not_started / in_transit / delivered /
               delayed / critical based on GRN presence and due-date maths.
    Act      → Return a tracking_report with per-PO status, ETA, days overdue,
               and a consolidated alerts list.
    Learn    → Log summary statistics (total POs, alert count).
    """

    def __init__(self) -> None:
        super().__init__(
            name="DeliveryTrackingAgent",
            description=(
                "Monitors open purchase orders for delivery status, calculates "
                "ETA / days overdue, and raises alerts for delayed or critical POs."
            ),
            temperature=0.1,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.status = AgentStatus.OBSERVING

        po_filter = context.get("po_number")   # optional: track a single PO
        limit = int(context.get("limit", 100))

        purchase_orders: List[Dict[str, Any]] = []
        grn_map: Dict[str, List[Dict[str, Any]]] = {}  # po_number → grn list

        try:
            from backend.services.adapters.factory import get_adapter
            adapter = get_adapter()

            purchase_orders = adapter.get_purchase_orders(limit=limit)

            # Optionally filter to a single PO
            if po_filter:
                purchase_orders = [
                    p for p in purchase_orders
                    if str(p.get("po_number") or p.get("name") or "") == str(po_filter)
                ]

            # Load GRN headers for every open PO
            for po in purchase_orders:
                po_num = str(po.get("po_number") or po.get("name") or "")
                if po_num:
                    grns = adapter.get_grn_headers(po_number=po_num, limit=20)
                    grn_map[po_num] = grns

        except Exception as exc:
            logger.warning("[DeliveryTrackingAgent] Adapter query failed: %s", exc)

        logger.info(
            "[DeliveryTrackingAgent] Loaded %d POs, %d with GRNs",
            len(purchase_orders),
            sum(1 for v in grn_map.values() if v),
        )

        return {
            "purchase_orders": purchase_orders,
            "grn_map": grn_map,
            "as_of_date": datetime.now().isoformat(),
            "input_context": context,
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        self.status = AgentStatus.THINKING

        purchase_orders = observations.get("purchase_orders", [])
        grn_map = observations.get("grn_map", {})
        today = date.today()

        if not purchase_orders:
            return AgentDecision(
                action="no_open_pos",
                reasoning="No open purchase orders found — nothing to track.",
                confidence=0.95,
                context=observations,
            )

        tracking_lines: List[Dict[str, Any]] = []
        alerts: List[Dict[str, Any]] = []
        critical_count = 0
        delayed_count = 0

        for po in purchase_orders:
            po_num = str(po.get("po_number") or po.get("name") or "")
            grns = grn_map.get(po_num, [])

            # Resolve expected delivery date from several possible field names
            raw_date = (
                po.get("date_planned")
                or po.get("delivery_date")
                or po.get("expected_date")
                or po.get("date_approve")
            )
            expected_date: Optional[date] = self._parse_date(raw_date)

            # Quantity-based receipt pct
            ordered_qty = float(
                po.get("product_qty") or po.get("qty_ordered") or po.get("po_grand_total") or 0
            )
            received_qty = sum(
                float(g.get("quantity_done") or g.get("qty_received") or 0)
                for g in grns
            )
            receipt_pct = (received_qty / ordered_qty * 100) if ordered_qty > 0 else 0.0

            # Days overdue (positive = late, negative = still within window)
            days_overdue = 0
            if expected_date:
                days_overdue = (today - expected_date).days

            # Classify delivery status
            if not grns:
                if expected_date and days_overdue > _DELAY_CRITICAL_DAYS:
                    status = "critical"
                    critical_count += 1
                elif expected_date and days_overdue > _DELAY_WARNING_DAYS:
                    status = "delayed"
                    delayed_count += 1
                else:
                    status = "not_started"
            elif receipt_pct >= 98:
                status = "delivered"
            else:
                if expected_date and days_overdue > _DELAY_CRITICAL_DAYS:
                    status = "critical"
                    critical_count += 1
                elif expected_date and days_overdue > _DELAY_WARNING_DAYS:
                    status = "delayed"
                    delayed_count += 1
                else:
                    status = "in_transit"

            line = {
                "po_number": po_num,
                "vendor": po.get("partner_id") or po.get("vendor_id") or po.get("vendor_name") or "",
                "expected_delivery_date": expected_date.isoformat() if expected_date else None,
                "days_overdue": max(days_overdue, 0) if status in ("delayed", "critical") else 0,
                "receipt_pct": round(receipt_pct, 1),
                "grn_count": len(grns),
                "delivery_status": status,
                "total_value": float(po.get("po_grand_total") or po.get("amount_total") or 0),
            }
            tracking_lines.append(line)

            if status in ("delayed", "critical"):
                alerts.append({
                    "po_number": po_num,
                    "severity": status,
                    "days_overdue": line["days_overdue"],
                    "message": (
                        f"PO {po_num} is {status.upper()}: "
                        f"{line['days_overdue']} days past expected delivery. "
                        f"Only {receipt_pct:.0f}% received."
                    ),
                })

        action = "generate_tracking_report"
        reasoning = (
            f"Analysed {len(purchase_orders)} POs. "
            f"Critical: {critical_count}, Delayed: {delayed_count}, "
            f"Alerts raised: {len(alerts)}."
        )
        confidence = 0.92 if purchase_orders else 0.5

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "tracking_lines": tracking_lines,
                "alerts": alerts,
                "critical_count": critical_count,
                "delayed_count": delayed_count,
            },
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        self.status = AgentStatus.ACTING

        ctx = decision.context
        tracking_lines: List[Dict[str, Any]] = ctx.get("tracking_lines", [])
        alerts: List[Dict[str, Any]] = ctx.get("alerts", [])

        # Summary counts
        status_counts: Dict[str, int] = {}
        for line in tracking_lines:
            s = line.get("delivery_status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        result: Dict[str, Any] = {
            "success": True,
            "agent": self.name,
            "action": decision.action,
            "as_of_date": ctx.get("as_of_date", datetime.now().isoformat()),
            "total_pos_tracked": len(tracking_lines),
            "status_summary": status_counts,
            "alerts": alerts,
            "tracking_report": tracking_lines,
            "timestamp": datetime.now().isoformat(),
        }

        if alerts:
            result["message"] = (
                f"{len(alerts)} delivery alert(s) raised — "
                f"{ctx.get('critical_count', 0)} critical, "
                f"{ctx.get('delayed_count', 0)} delayed."
            )
        else:
            result["message"] = (
                f"All {len(tracking_lines)} PO(s) are on track or delivered."
            )

        await self._log_action(
            action_type="delivery_tracking_report",
            input_data=ctx.get("input_context", {}),
            output_data=result,
            success=True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        result = learn_context.get("result", {})
        logger.info(
            "[DeliveryTrackingAgent] Learned: POs=%d  alerts=%d",
            result.get("total_pos_tracked", 0),
            len(result.get("alerts", [])),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_date(raw: Any) -> Optional[date]:
        """Parse a date string or datetime object into a date."""
        if raw is None:
            return None
        if isinstance(raw, date):
            return raw if not isinstance(raw, datetime) else raw.date()
        try:
            return datetime.fromisoformat(str(raw)[:10]).date()
        except (ValueError, TypeError):
            return None


# ── Standalone entry point ─────────────────────────────────────────────────────

async def track_delivery(params: Dict[str, Any]) -> Dict[str, Any]:
    """Standalone async function — call from orchestrator or API route."""
    agent = DeliveryTrackingAgent()
    return await agent.execute(params)
