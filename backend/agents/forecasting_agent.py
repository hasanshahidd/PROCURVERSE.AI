"""
ForecastingAgent — WF-19
=========================
Demand Forecasting & Procurement Planning.

Workflows covered
-----------------
WF-19  Demand Forecasting & Procurement Planning
       Analyses historical spend and inventory data to produce a rolling
       3-month demand forecast per category, recommends a PO schedule,
       and flags categories where forecast exceeds available budget.

Business value
--------------
- Eliminates reactive, last-minute purchasing
- Surfaces budget pressure before it becomes a crisis
- Gives procurement teams a data-driven PO schedule
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from backend.agents import AgentDecision, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)

# Minimum months of data required for a high-confidence forecast
_MIN_MONTHS_HIGH_CONFIDENCE = 3
_MIN_MONTHS_MEDIUM_CONFIDENCE = 1


class ForecastingAgent(BaseAgent):
    """
    Produces demand forecasts using a 3-month rolling average of spend data.

    Observe  → Load spend records (get_spend_analytics), inventory status
               (get_inventory_status), and open POs (get_purchase_orders).
    Decide   → Group spend by category and month; compute 3-month rolling
               average; flag where forecast > budget.
    Act      → Return forecast_report: predicted_spend per category,
               recommended_po_schedule, budget_alignment, confidence.
    Learn    → Log category count and flagged-budget items.
    """

    def __init__(self) -> None:
        super().__init__(
            name="ForecastingAgent",
            description=(
                "Forecasts procurement demand by category using 3-month rolling "
                "averages of spend data. Flags budget overruns and recommends a "
                "PO schedule for the next period."
            ),
            temperature=0.1,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.status = AgentStatus.OBSERVING

        spend_data: List[Dict[str, Any]] = []
        inventory_data: List[Dict[str, Any]] = []
        open_pos: List[Dict[str, Any]] = []
        budget_data: List[Dict[str, Any]] = []

        try:
            from backend.services.adapters.factory import get_adapter
            adapter = get_adapter()

            spend_data = adapter.get_spend_analytics(limit=500)
            inventory_data = adapter.get_inventory_status()
            open_pos = adapter.get_purchase_orders(limit=200)

            # Budget vs actuals for budget alignment check
            try:
                budget_data = adapter.get_budget_vs_actuals()
            except Exception as budget_exc:
                logger.warning("[ForecastingAgent] Budget data unavailable: %s", budget_exc)

        except Exception as exc:
            logger.warning("[ForecastingAgent] Adapter query failed: %s", exc)

        logger.info(
            "[ForecastingAgent] Loaded spend=%d  inventory=%d  pos=%d  budget=%d",
            len(spend_data), len(inventory_data), len(open_pos), len(budget_data),
        )

        return {
            "spend_data": spend_data,
            "inventory_data": inventory_data,
            "open_pos": open_pos,
            "budget_data": budget_data,
            "forecast_period": context.get("forecast_period", "next_month"),
            "input_context": context,
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        self.status = AgentStatus.THINKING

        spend_data: List[Dict[str, Any]] = observations.get("spend_data", [])
        budget_data: List[Dict[str, Any]] = observations.get("budget_data", [])
        open_pos: List[Dict[str, Any]] = observations.get("open_pos", [])

        if not spend_data:
            return AgentDecision(
                action="insufficient_data",
                reasoning="No spend analytics data available — cannot generate forecast.",
                confidence=0.9,
                context=observations,
            )

        # ── Step 1: bucket spend by (category, YYYY-MM) ───────────────────────
        category_monthly: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

        for row in spend_data:
            category = (
                row.get("category")
                or row.get("product_category")
                or row.get("expense_category")
                or "Uncategorised"
            )
            amount = float(
                row.get("total_amount")
                or row.get("amount")
                or row.get("spend_amount")
                or row.get("net_amount")
                or 0
            )
            raw_date = row.get("period") or row.get("invoice_date") or row.get("date")
            month_key = self._to_month_key(raw_date)
            category_monthly[str(category)][month_key] += amount

        # ── Step 2: build budget lookup (category → budget) ───────────────────
        budget_lookup: Dict[str, float] = {}
        for b in budget_data:
            cat = str(
                b.get("budget_category") or b.get("category") or b.get("gl_account") or ""
            )
            bgt = float(b.get("budget_amount") or b.get("total_budget") or 0)
            if cat:
                budget_lookup[cat] = budget_lookup.get(cat, 0) + bgt

        # ── Step 3: build open-PO commitment lookup (category → committed) ────
        committed_lookup: Dict[str, float] = defaultdict(float)
        for po in open_pos:
            cat = str(po.get("category") or po.get("product_category") or "Uncategorised")
            val = float(po.get("po_grand_total") or po.get("amount_total") or 0)
            committed_lookup[cat] += val

        # ── Step 4: compute 3-month rolling average per category ──────────────
        forecasts: List[Dict[str, Any]] = []
        budget_flagged: List[str] = []

        for category, monthly_totals in category_monthly.items():
            sorted_months = sorted(monthly_totals.keys())
            last_3 = sorted_months[-3:]  # up to 3 most-recent months
            month_count = len(last_3)
            rolling_avg = (
                sum(monthly_totals[m] for m in last_3) / month_count
                if month_count > 0 else 0.0
            )

            # Confidence based on data volume
            if month_count >= _MIN_MONTHS_HIGH_CONFIDENCE:
                confidence_label = "high"
                confidence_score = 0.90
            elif month_count >= _MIN_MONTHS_MEDIUM_CONFIDENCE:
                confidence_label = "medium"
                confidence_score = 0.70
            else:
                confidence_label = "low"
                confidence_score = 0.50

            budget = budget_lookup.get(category, 0.0)
            committed = committed_lookup.get(category, 0.0)
            budget_remaining = budget - committed
            over_budget = budget > 0 and rolling_avg > budget_remaining

            if over_budget:
                budget_flagged.append(category)

            # Recommended PO schedule: if forecast exceeds committed open POs
            # suggest raising a new PO for the gap
            po_gap = max(rolling_avg - committed, 0.0)
            recommended_action = (
                f"Raise PO for ~{po_gap:,.0f} by next month"
                if po_gap > 0
                else "Existing open POs cover forecast"
            )

            forecasts.append({
                "category": category,
                "months_of_data": month_count,
                "rolling_3m_average": round(rolling_avg, 2),
                "predicted_next_period_spend": round(rolling_avg, 2),
                "open_po_committed": round(committed, 2),
                "budget_remaining": round(budget_remaining, 2),
                "over_budget_flag": over_budget,
                "confidence": confidence_label,
                "confidence_score": confidence_score,
                "recommended_po_action": recommended_action,
            })

        # Sort: flagged first, then by predicted spend desc
        forecasts.sort(key=lambda x: (-int(x["over_budget_flag"]), -x["predicted_next_period_spend"]))

        reasoning = (
            f"Generated forecast for {len(forecasts)} categories from "
            f"{len(spend_data)} spend records. "
            f"Budget over-run flagged for {len(budget_flagged)} categories: "
            f"{', '.join(budget_flagged[:5])}{'...' if len(budget_flagged) > 5 else ''}."
        )

        return AgentDecision(
            action="generate_forecast_report",
            reasoning=reasoning,
            confidence=0.88,
            context={
                **observations,
                "forecasts": forecasts,
                "budget_flagged": budget_flagged,
            },
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        self.status = AgentStatus.ACTING

        ctx = decision.context
        forecasts: List[Dict[str, Any]] = ctx.get("forecasts", [])
        budget_flagged: List[str] = ctx.get("budget_flagged", [])

        total_predicted = sum(f.get("predicted_next_period_spend", 0) for f in forecasts)

        result: Dict[str, Any] = {
            "success": True,
            "agent": self.name,
            "action": decision.action,
            "forecast_period": ctx.get("forecast_period", "next_month"),
            "categories_analysed": len(forecasts),
            "total_predicted_spend": round(total_predicted, 2),
            "budget_alignment": (
                "OVER_BUDGET" if budget_flagged else "WITHIN_BUDGET"
            ),
            "budget_flagged_categories": budget_flagged,
            "forecast_report": forecasts,
            "recommended_po_schedule": [
                {
                    "category": f["category"],
                    "action": f["recommended_po_action"],
                    "predicted_spend": f["predicted_next_period_spend"],
                }
                for f in forecasts
                if "Raise PO" in f.get("recommended_po_action", "")
            ],
            "timestamp": datetime.now().isoformat(),
        }

        if budget_flagged:
            result["message"] = (
                f"Forecast complete. {len(budget_flagged)} category(ies) exceed remaining budget: "
                f"{', '.join(budget_flagged[:3])}{'...' if len(budget_flagged) > 3 else ''}."
            )
        else:
            result["message"] = (
                f"Forecast complete for {len(forecasts)} categories. "
                "All categories within budget."
            )

        await self._log_action(
            action_type="demand_forecast_generated",
            input_data=ctx.get("input_context", {}),
            output_data=result,
            success=True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        result = learn_context.get("result", {})
        logger.info(
            "[ForecastingAgent] Learned: categories=%d  budget_flags=%d  total_predicted=%.2f",
            result.get("categories_analysed", 0),
            len(result.get("budget_flagged_categories", [])),
            result.get("total_predicted_spend", 0),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_month_key(raw: Any) -> str:
        """Convert any date-like value to a 'YYYY-MM' string for grouping."""
        if raw is None:
            return "unknown"
        s = str(raw)[:10]  # take first 10 chars — covers ISO date strings
        try:
            d = datetime.fromisoformat(s)
            return d.strftime("%Y-%m")
        except (ValueError, TypeError):
            # If it already looks like YYYY-MM return it directly
            if len(s) == 7 and s[4] == "-":
                return s
            return "unknown"


# ── Standalone entry point ─────────────────────────────────────────────────────

async def forecast_demand(params: Dict[str, Any]) -> Dict[str, Any]:
    """Standalone async function — call from orchestrator or API route."""
    agent = ForecastingAgent()
    return await agent.execute(params)
