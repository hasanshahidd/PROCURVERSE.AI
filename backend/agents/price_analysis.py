"""
Price Analysis Agent
Phase 3: Analyzes vendor pricing and identifies cost-saving opportunities

Features:
- Compares vendor quotes to market average prices
- Flags abnormally high prices (>20% above average)
- Identifies single-source dependencies
- Recommends negotiation opportunities for large orders
- Tracks price trends and volatility
"""

from typing import Dict, Any, List
import logging
from datetime import datetime
from statistics import mean, stdev

from backend.agents import BaseAgent, AgentDecision
from backend.services.nmi_data_service import get_nmi_vendor_quotes, get_nmi_purchase_orders

logger = logging.getLogger(__name__)


class PriceAnalysisAgent(BaseAgent):
    """
    Analyzes vendor pricing for competitiveness and cost savings.

    Pricing Thresholds:
    - Excellent: <10% below market average
    - Competitive: ±10% of market average
    - High: 10-20% above average
    - Very High: >20% above average (immediate negotiation required)
    """

    def __init__(self):
        super().__init__(
            name="PriceAnalysisAgent",
            description=(
                "Analyzes vendor pricing for competitiveness. "
                "Compares quotes to market averages, identifies single-source risks, "
                "and recommends negotiation opportunities."
            ),
            tools=[],
            temperature=0.2
        )
        logger.info("PriceAnalysisAgent initialized (NMI data source)")

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Gather pricing data from NMI vendor_quotes and po_headers."""
        observations = await super().observe(context)

        pr_data = context.get("pr_data", {})
        product_name = pr_data.get("product_name", "")
        quoted_price = pr_data.get("quoted_price", 0)
        vendor_name = pr_data.get("vendor_name", "")
        quantity = pr_data.get("quantity", 1)
        category = pr_data.get("category", "")

        logger.info(
            f"[PriceAnalysisAgent] Analyzing price for {product_name}: "
            f"${quoted_price} from {vendor_name} (qty: {quantity})"
        )

        try:
            # Fetch quotes from NMI vendor_quotes table
            vendor_quotes = get_nmi_vendor_quotes(item_name=product_name or None, limit=100)

            # Fetch historical POs from NMI po_headers + po_line_items
            purchase_orders = get_nmi_purchase_orders(limit=200)

            # Market stats from vendor quotes (most accurate for price comparison)
            market_stats = self._calculate_market_stats_from_quotes(
                product_name, vendor_quotes, purchase_orders
            )

            vendor_diversity = self._analyze_vendor_diversity(product_name, purchase_orders, vendor_quotes)

            observations.update({
                "product_name": product_name,
                "quoted_price": quoted_price,
                "vendor_name": vendor_name,
                "quantity": quantity,
                "category": category,
                "market_avg_price": market_stats.get("avg_price", 0),
                "market_min_price": market_stats.get("min_price", 0),
                "market_max_price": market_stats.get("max_price", 0),
                "price_std_dev": market_stats.get("std_dev", 0),
                "historical_orders": market_stats.get("order_count", 0),
                "vendor_count": vendor_diversity.get("vendor_count", 0),
                "is_single_source": vendor_diversity.get("is_single_source", False),
                "primary_vendor": vendor_diversity.get("primary_vendor", ""),
                "timestamp": datetime.now().isoformat()
            })

        except Exception as e:
            logger.error(f"Error gathering NMI pricing data: {e}")
            observations.update({
                "error": str(e),
                "market_avg_price": 0,
                "vendor_count": 0
            })

        return observations

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Analyze pricing and determine recommendations."""
        quoted_price = observations.get("quoted_price", 0)
        market_avg = observations.get("market_avg_price", 0)
        vendor_count = observations.get("vendor_count", 0)
        is_single_source = observations.get("is_single_source", False)
        quantity = observations.get("quantity", 1)

        if market_avg > 0:
            price_variance = ((quoted_price - market_avg) / market_avg) * 100
        else:
            price_variance = 0

        # When no market data is available we cannot classify price competitiveness
        if market_avg <= 0:
            price_level = "insufficient_data"
            action = "approve_with_note"  # approve but note that data is missing
        elif price_variance < -10:
            price_level = "Excellent"
            action = "approve"
        elif price_variance <= 10:
            price_level = "Competitive"
            action = "approve"
        elif price_variance <= 20:
            price_level = "High"
            action = "negotiate" if quantity * quoted_price > 10000 else "approve_with_note"
        else:
            price_level = "Very High"
            action = "negotiate"

        reasoning_parts = [
            f"Quoted price: ${quoted_price:,.2f}",
            f"Market average: ${market_avg:,.2f}" if market_avg > 0 else "No market data available",
            f"Price variance: {price_variance:+.1f}%" if market_avg > 0 else "New product",
            f"Price level: {price_level}"
        ]

        if is_single_source:
            reasoning_parts.append("️ SINGLE-SOURCE DEPENDENCY DETECTED")
            reasoning_parts.append("Recommend identifying alternative vendors")

        if vendor_count == 0:
            reasoning_parts.append("No historical orders for this product")
        elif vendor_count == 1:
            reasoning_parts.append("Only 1 vendor used historically")
        else:
            reasoning_parts.append(f"{vendor_count} vendors available")

        total_value = quantity * quoted_price
        if action == "negotiate":
            potential_savings = total_value * (abs(price_variance) / 100)
            reasoning_parts.append(
                f"Negotiation opportunity: Potential savings ${potential_savings:,.2f}"
            )

        reasoning = " | ".join(reasoning_parts)

        confidence = 0.5
        if market_avg > 0:
            confidence += 0.3
        if vendor_count > 1:
            confidence += 0.2
        confidence = min(confidence, 0.95)

        alternatives = []
        if action == "negotiate":
            alternatives.append({
                "action": "seek_alternative_vendor",
                "description": "Find alternative vendors for competitive quotes"
            })
            if vendor_count > 1:
                alternatives.append({
                    "action": "request_bulk_discount",
                    "description": f"Request volume discount for {quantity} units"
                })

        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                "quoted_price": quoted_price,
                "market_avg_price": market_avg,
                "price_variance_pct": round(price_variance, 2),
                "price_level": price_level,
                "is_single_source": is_single_source,
                "vendor_count": vendor_count,
                "total_value": total_value,
                "alternatives": alternatives
            }
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        action = decision.action
        context = decision.context

        result = {
            "action": action,
            "status": "success",
            "decision": decision.model_dump() if hasattr(decision, 'model_dump') else decision.__dict__,
            "timestamp": datetime.now().isoformat()
        }

        await self._log_action(
            action_type=f"price_analysis_{action}",
            input_data=context,
            output_data=result,
            success=True
        )

        if action == "negotiate":
            result["message"] = (
                f"Price is {context['price_variance_pct']}% above market average. "
                f"Negotiation recommended for potential savings of "
                f"${context['total_value'] * (abs(context['price_variance_pct']) / 100):,.2f}"
            )
        elif action == "approve":
            result["message"] = (
                f"Price is competitive ({context['price_level']}). "
                f"Approved for procurement."
            )
        elif action == "approve_with_note":
            result["message"] = (
                f"Price is slightly high but acceptable. "
                f"Consider negotiation for larger orders."
            )

        if context.get("is_single_source"):
            result["warning"] = (
                "Single-source dependency detected. "
                "Recommend developing alternative supplier relationships."
            )

        return result

    def _calculate_market_stats_from_quotes(
        self,
        product_name: str,
        vendor_quotes: List[Dict[str, Any]],
        purchase_orders: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate market price stats from NMI vendor quotes and PO line items."""
        prices = []

        # Primary: use vendor quotes unit prices
        for q in vendor_quotes:
            price = q.get("unit_price")
            if price and float(price) > 0:
                prices.append(float(price))

        # Fallback: use PO line item prices if no quotes match
        if not prices:
            for po in purchase_orders:
                line_price = po.get("line_unit_price")
                if line_price and float(line_price) > 0:
                    # Filter by product name if provided
                    item_desc = (po.get("item_description") or "").lower()
                    item_code = (po.get("item_code") or "").lower()
                    if not product_name or (
                        product_name.lower() in item_desc or
                        product_name.lower() in item_code
                    ):
                        prices.append(float(line_price))

        if not prices:
            return {"avg_price": 0, "min_price": 0, "max_price": 0, "std_dev": 0, "order_count": 0}

        return {
            "avg_price": mean(prices),
            "min_price": min(prices),
            "max_price": max(prices),
            "std_dev": stdev(prices) if len(prices) > 1 else 0,
            "order_count": len(prices)
        }

    def _analyze_vendor_diversity(
        self,
        product_name: str,
        purchase_orders: List[Dict[str, Any]],
        vendor_quotes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze vendor diversity from NMI POs and quotes."""
        vendors: set = set()
        vendor_counts: Dict[str, int] = {}

        for po in purchase_orders:
            vendor = po.get("vendor_name", "")
            if vendor:
                vendors.add(vendor)
                vendor_counts[vendor] = vendor_counts.get(vendor, 0) + 1

        for q in vendor_quotes:
            vendor = q.get("vendor_name", "")
            if vendor:
                vendors.add(vendor)

        vendor_count = len(vendors)
        primary_vendor = max(vendor_counts, key=vendor_counts.get) if vendor_counts else ""

        return {
            "vendor_count": vendor_count,
            "is_single_source": vendor_count <= 1,
            "primary_vendor": primary_vendor,
            "all_vendors": list(vendors)
        }
