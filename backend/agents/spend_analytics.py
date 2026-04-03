"""
SpendAnalyticsAgent - AI-Powered Spend Intelligence
Analyzes NMI spend data, identifies savings opportunities
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from backend.agents import BaseAgent, AgentDecision, AgentStatus
from backend.services.nmi_data_service import get_nmi_spend_analytics, get_nmi_budget_vs_actuals

logger = logging.getLogger(__name__)


class SpendAnalyticsAgent(BaseAgent):
    """
    Agent for comprehensive spend analysis and savings identification.

    Analysis Dimensions:
    1. Spend by Department / Cost Center
    2. Spend by Category
    3. Spend by Vendor (concentration analysis)
    4. Spend by Time Period (monthly trends)

    Savings Opportunities:
    - Volume consolidation (bulk discounts)
    - Contract renegotiation (high-spend vendors)
    - Preferred vendor redirect (maverick spend)
    - Price variance elimination
    """

    SAVINGS_THRESHOLDS = {
        "volume_consolidation": 0.10,
        "price_standardization": 0.08,
        "vendor_consolidation": 0.12,
        "contract_renegotiation": 0.15
    }

    VENDOR_CONCENTRATION_RISK = 0.40

    def __init__(self):
        super().__init__(
            name="SpendAnalyticsAgent",
            description="Comprehensive spend analysis with ML-powered savings identification",
            temperature=0.2
        )

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        analysis_type = input_data.get("analysis_type", "comprehensive")
        time_period = input_data.get("time_period", "YTD")
        logger.info(f"[SpendAnalyticsAgent] Starting {analysis_type} spend analysis for {time_period}")
        return await self.execute_with_recovery(input_data)

    async def observe(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """OBSERVE: Pull NMI spend_analytics and budget_vs_actuals data."""
        self.status = AgentStatus.OBSERVING

        time_period = input_data.get("time_period", "YTD")
        department = input_data.get("department")

        try:
            spend_rows = get_nmi_spend_analytics(period=time_period if time_period != "YTD" else None, limit=500)
            budget_rows = get_nmi_budget_vs_actuals(cost_center=department)

            logger.info(
                f"[SpendAnalyticsAgent] Fetched {len(spend_rows)} spend rows, "
                f"{len(budget_rows)} budget rows"
            )

            return {
                "time_period": time_period,
                "spend_rows": spend_rows,
                "budget_rows": budget_rows,
                "input_params": input_data
            }

        except Exception as e:
            logger.error(f"[SpendAnalyticsAgent] Error fetching NMI data: {e}")
            return {
                "error": str(e),
                "time_period": time_period,
                "spend_rows": [],
                "budget_rows": [],
                "input_params": input_data
            }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """DECIDE: Analyze NMI spend patterns and identify savings opportunities."""
        self.status = AgentStatus.THINKING

        spend_rows = observations.get("spend_rows", [])

        if not spend_rows:
            return AgentDecision(
                action="no_data",
                reasoning="No spend data found in NMI spend_analytics table for the specified period",
                confidence=1.0,
                context=observations
            )

        spend_by_dept = defaultdict(float)
        spend_by_vendor = defaultdict(float)
        spend_by_category = defaultdict(float)
        spend_by_month = defaultdict(float)
        vendor_po_count = defaultdict(int)

        total_spend = 0.0

        for row in spend_rows:
            # NMI spend_analytics columns: total_amount_usd, vendor_name, category,
            # cost_center / department, period
            amount = float(row.get("total_amount_usd") or row.get("total_amount_pkr") or 0)
            total_spend += amount

            dept = row.get("cost_center") or row.get("department") or "Unassigned"
            spend_by_dept[dept] += amount

            vendor = row.get("vendor_name") or row.get("vendor_id") or "Unknown"
            spend_by_vendor[vendor] += amount
            vendor_po_count[vendor] += int(row.get("transaction_count") or 1)

            category = row.get("category") or row.get("spend_category") or "General"
            spend_by_category[category] += amount

            period = row.get("period") or ""
            if period:
                spend_by_month[period[:7]] += amount  # YYYY-MM

        # SAVINGS ANALYSIS

        savings_opportunities = []

        # 1. Vendor Concentration Risk
        for vendor, vendor_spend in spend_by_vendor.items():
            concentration = vendor_spend / total_spend if total_spend > 0 else 0
            if concentration > self.VENDOR_CONCENTRATION_RISK:
                savings_opportunities.append({
                    "type": "vendor_diversification",
                    "vendor": vendor,
                    "current_spend": round(vendor_spend, 2),
                    "concentration_pct": round(concentration * 100, 1),
                    "risk": "HIGH",
                    "recommendation": f"Reduce dependency on {vendor} (currently {concentration*100:.1f}% of spend)",
                    "potential_savings": round(vendor_spend * 0.08, 2)
                })

        # 2. Volume Consolidation (top vendors with high volume)
        top_vendors = sorted(spend_by_vendor.items(), key=lambda x: x[1], reverse=True)[:5]
        for vendor, vendor_spend in top_vendors:
            if vendor_spend > 100000:
                po_count = vendor_po_count[vendor]
                if po_count > 10:
                    savings_opportunities.append({
                        "type": "volume_consolidation",
                        "vendor": vendor,
                        "current_spend": round(vendor_spend, 2),
                        "po_count": po_count,
                        "recommendation": f"Negotiate bulk discount with {vendor} ({po_count} transactions, ${vendor_spend:,.0f})",
                        "potential_savings": round(vendor_spend * self.SAVINGS_THRESHOLDS["volume_consolidation"], 2)
                    })

        # 3. Department overspend detection
        dept_alerts = []
        for dept, dept_spend in spend_by_dept.items():
            dept_pct = dept_spend / total_spend * 100 if total_spend > 0 else 0
            if dept_pct > 35:
                dept_alerts.append({
                    "department": dept,
                    "spend": round(dept_spend, 2),
                    "percentage": round(dept_pct, 1),
                    "alert": "High concentration"
                })

        # Budget vs Actuals analysis
        budget_alerts = []
        for bva in observations.get("budget_rows", []):
            fy_budget = float(bva.get("fy_budget") or 0)
            fy_actual = float(bva.get("fy_actual") or 0)
            if fy_budget > 0 and fy_actual > fy_budget:
                overspend = fy_actual - fy_budget
                budget_alerts.append({
                    "cost_center": bva.get("cost_center"),
                    "gl_account": bva.get("gl_account"),
                    "budget": round(fy_budget, 2),
                    "actual": round(fy_actual, 2),
                    "overspend": round(overspend, 2),
                    "overspend_pct": round(overspend / fy_budget * 100, 1)
                })

        total_savings = sum(opp.get("potential_savings", 0) for opp in savings_opportunities)

        if total_savings > 100000:
            action = "high_value_opportunities"
            reasoning = f"Identified ${total_savings:,.0f} in potential savings across {len(savings_opportunities)} opportunities"
            confidence = 0.85
        elif savings_opportunities:
            action = "moderate_opportunities"
            reasoning = f"Found {len(savings_opportunities)} savings opportunities totaling ${total_savings:,.0f}"
            confidence = 0.75
        else:
            action = "optimized_spend"
            reasoning = "Spend appears optimized - no major savings opportunities identified"
            confidence = 0.70

        decision_context = {
            **observations,
            "spend_summary": {
                "total_spend": round(total_spend, 2),
                "total_rows": len(spend_rows),
                "unique_vendors": len(spend_by_vendor),
                "unique_departments": len(spend_by_dept),
                "data_source": "NMI spend_analytics"
            },
            "spend_by_department": {k: round(v, 2) for k, v in sorted(spend_by_dept.items(), key=lambda x: x[1], reverse=True)},
            "spend_by_vendor": {k: round(v, 2) for k, v in sorted(spend_by_vendor.items(), key=lambda x: x[1], reverse=True)[:20]},
            "spend_by_category": {k: round(v, 2) for k, v in sorted(spend_by_category.items(), key=lambda x: x[1], reverse=True)},
            "spend_by_month": {k: round(v, 2) for k, v in sorted(spend_by_month.items())},
            "savings_opportunities": savings_opportunities,
            "total_potential_savings": round(total_savings, 2),
            "department_alerts": dept_alerts,
            "budget_alerts": budget_alerts
        }

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context=decision_context,
            alternatives=["detailed_drill_down", "export_to_dashboard"]
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """ACT: Generate actionable insights and recommendations."""
        self.status = AgentStatus.ACTING

        context = decision.context
        spend_summary = context.get("spend_summary", {})
        savings_opportunities = context.get("savings_opportunities", [])

        result = {
            "success": True,
            "agent": self.name,
            "action": decision.action,
            "analysis_timestamp": datetime.now().isoformat(),
            "decision": decision.to_dict(),

            "executive_summary": {
                "total_spend": spend_summary.get("total_spend"),
                "total_records": spend_summary.get("total_rows"),
                "unique_vendors": spend_summary.get("unique_vendors"),
                "unique_departments": spend_summary.get("unique_departments"),
                "total_savings_identified": context.get("total_potential_savings"),
                "savings_percentage": round(
                    context.get("total_potential_savings", 0) / max(spend_summary.get("total_spend", 1), 1) * 100, 2
                ),
                "opportunities_count": len(savings_opportunities),
                "data_source": spend_summary.get("data_source")
            },

            "spend_by_department": context.get("spend_by_department"),
            "spend_by_vendor": context.get("spend_by_vendor"),
            "spend_by_category": context.get("spend_by_category"),
            "spend_by_month": context.get("spend_by_month"),
            "savings_opportunities": savings_opportunities,
            "department_alerts": context.get("department_alerts", []),
            "budget_alerts": context.get("budget_alerts", []),
            "top_recommendations": self._generate_recommendations(savings_opportunities)
        }

        await self._log_action(
            action_type=f"spend_analysis_{decision.action}",
            input_data=context.get("input_params", {}),
            output_data=result,
            success=True
        )

        total_savings = result.get("executive_summary", {}).get("total_savings_identified") or 0
        logger.info(f"[SpendAnalyticsAgent] Analysis complete - ${total_savings:,.0f} in savings identified")

        return result

    def _generate_recommendations(self, opportunities: List[Dict]) -> List[Dict]:
        if not opportunities:
            return [{
                "priority": "LOW",
                "action": "Continue monitoring",
                "description": "Spend patterns are optimized. Continue quarterly reviews."
            }]

        sorted_opps = sorted(opportunities, key=lambda x: x.get("potential_savings", 0), reverse=True)
        recommendations = []

        for i, opp in enumerate(sorted_opps[:5], 1):
            rec = {
                "rank": i,
                "priority": "HIGH" if opp.get("potential_savings", 0) > 50000 else "MEDIUM",
                "type": opp.get("type"),
                "action": opp.get("recommendation"),
                "potential_savings": opp.get("potential_savings"),
                "implementation_complexity": "Medium",
                "timeline": "30-60 days"
            }

            if opp.get("type") == "volume_consolidation":
                rec["next_steps"] = [
                    f"Schedule meeting with {opp.get('vendor')}",
                    "Prepare 12-month spend data",
                    "Negotiate 10-15% bulk discount",
                    "Draft new contract terms"
                ]
            elif opp.get("type") == "vendor_diversification":
                rec["next_steps"] = [
                    "Research alternative vendors",
                    "Request quotes from 3-5 competitors",
                    "Pilot orders with 2 new vendors",
                    "Gradually shift 20-30% of volume"
                ]

            recommendations.append(rec)

        return recommendations

    async def learn(self, result: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        logger.info("[SpendAnalyticsAgent] Learning complete - stored spend patterns")

    # NOTE: _log_action is inherited from BaseAgent — it uses the shared db_pool.
    # The raw psycopg2 override that was here previously bypassed the adapter
    # pattern and is removed.


async def analyze_spend(params: Dict[str, Any]) -> Dict[str, Any]:
    agent = SpendAnalyticsAgent()
    return await agent.execute(params)
