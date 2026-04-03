"""
QuoteComparisonAgent — WF-04
=============================
Compares vendor quotes for an RFQ and recommends the best supplier.

Workflows covered
-----------------
WF-04  Quote Comparison & Vendor Selection (multi-vendor competitive sourcing)

Business value
--------------
- Automates multi-vendor bid analysis
- Scores quotes on price, delivery, quality and compliance
- Flags non-compliant or incomplete quotes
- Writes recommended_vendor back to vendor_quotes table
- Saves 4–8 hours of manual bid tabulation per RFQ
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.agents import AgentDecision, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)


class QuoteComparisonAgent(BaseAgent):
    """
    Fetches all quotes for an RFQ, scores them on multiple dimensions, and
    recommends the best vendor.

    Scoring (0–100)
    ---------------
    - Price competitiveness  40 pts  (lowest quote = 40; proportional for others)
    - Delivery lead time     25 pts  (shortest = 25)
    - Vendor track record    25 pts  (from vendor_performance table)
    - Compliance / validity  10 pts  (quote not expired + state = sent/confirmed)
    """

    WEIGHT_PRICE    = 0.40
    WEIGHT_DELIVERY = 0.25
    WEIGHT_TRACK    = 0.25
    WEIGHT_COMPLY   = 0.10

    def __init__(self) -> None:
        super().__init__(
            name="QuoteComparisonAgent",
            description=(
                "Compares vendor quotes for an RFQ and recommends the best supplier "
                "using a weighted scoring model (price, delivery, track record, compliance)."
            ),
            temperature=0.1,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return await self.execute_with_recovery(input_data)

    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.status = AgentStatus.OBSERVING

        rfq_number = context.get("rfq_number") or context.get("rfq_id", "")
        category   = context.get("category", "")

        quotes: List[Dict[str, Any]]   = []
        rfq_header: Dict[str, Any]     = {}
        vendor_perf: Dict[str, Any]    = {}   # vendor_id → performance dict

        try:
            from backend.services.adapters.factory import get_adapter
            adapter = get_adapter()

            # Load all quotes for this RFQ
            all_quotes = adapter.get_vendor_quotes(limit=200)
            if rfq_number:
                quotes = [
                    q for q in all_quotes
                    if str(q.get("rfq_id") or q.get("name") or "") == str(rfq_number)
                    or str(q.get("name") or "").startswith(str(rfq_number))
                ]
            else:
                quotes = all_quotes

            # Load RFQ header
            rfqs = adapter.get_rfq_headers(limit=100)
            rfq_header = next(
                (r for r in rfqs if str(r.get("name") or "") == str(rfq_number)),
                {},
            )

            # Load vendor performance for scoring
            raw_vp = adapter.get_vendor_performance()
            for vp in raw_vp:
                vid = str(vp.get("vendor_id") or vp.get("partner_id") or "")
                if vid:
                    vendor_perf[vid] = vp

        except Exception as exc:
            logger.warning("[QuoteComparisonAgent] Adapter query failed: %s", exc)

        logger.info(
            "[QuoteComparisonAgent] RFQ=%s  quotes=%d  vendors_with_perf=%d",
            rfq_number, len(quotes), len(vendor_perf),
        )

        return {
            "rfq_number":    rfq_number,
            "category":      category,
            "quotes":        quotes,
            "rfq_header":    rfq_header,
            "vendor_perf":   vendor_perf,
            "evaluated_at":  datetime.now().isoformat(),
            "input_context": context,
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        self.status = AgentStatus.THINKING

        quotes     = observations.get("quotes", [])
        vendor_perf = observations.get("vendor_perf", {})
        rfq_number = observations.get("rfq_number", "")

        if not quotes:
            return AgentDecision(
                action="no_quotes",
                reasoning=f"No quotes found for RFQ {rfq_number!r}. Cannot compare.",
                confidence=0.95,
                context=observations,
            )

        scored = self._score_quotes(quotes, vendor_perf)
        if not scored:
            return AgentDecision(
                action="all_quotes_invalid",
                reasoning="All quotes are expired or in an invalid state.",
                confidence=0.90,
                context=observations,
            )

        best    = scored[0]
        runners = scored[1:4]

        gap = best["total_score"] - (runners[0]["total_score"] if runners else 0)
        confidence = 0.95 if gap >= 10 else 0.80 if gap >= 5 else 0.70

        reasoning = (
            f"Best quote: {best['vendor_name']} — "
            f"score {best['total_score']:.1f}/100 "
            f"(price={best['price_score']:.0f}, delivery={best['delivery_score']:.0f}, "
            f"track={best['track_score']:.0f}, comply={best['comply_score']:.0f}). "
            f"Price: {best['currency']} {best['amount_total']:,.2f}. "
            f"Score gap vs runner-up: {gap:.1f} pts."
        )

        return AgentDecision(
            action="recommend_vendor",
            reasoning=reasoning,
            confidence=confidence,
            context={
                **observations,
                "best_quote":     best,
                "runner_up":      runners,
                "all_scored":     scored,
            },
        )

    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        self.status = AgentStatus.ACTING

        action = decision.action
        ctx    = decision.context

        if action == "no_quotes":
            return {
                "success": True,
                "action":  action,
                "status":  "no_quotes",
                "message": decision.reasoning,
            }

        if action == "all_quotes_invalid":
            return {
                "success": True,
                "action":  action,
                "status":  "invalid",
                "message": decision.reasoning,
            }

        best_quote = ctx.get("best_quote", {})
        runner_up  = ctx.get("runner_up", [])
        all_scored = ctx.get("all_scored", [])

        # Mark recommended=true in DB for best quote (best-effort)
        await self._mark_recommended(best_quote.get("id"), ctx.get("rfq_number", ""))

        result = {
            "success":            True,
            "agent":              self.name,
            "action":             action,
            "rfq_number":         ctx.get("rfq_number", ""),
            "status":             "recommended",
            "recommended_vendor": {
                "vendor_id":   best_quote.get("vendor_id") or best_quote.get("partner_id"),
                "vendor_name": best_quote.get("vendor_name", ""),
                "quote_id":    best_quote.get("id"),
                "amount":      best_quote.get("amount_total", 0),
                "currency":    best_quote.get("currency", "AED"),
                "score":       best_quote.get("total_score", 0),
                "breakdown": {
                    "price":    best_quote.get("price_score", 0),
                    "delivery": best_quote.get("delivery_score", 0),
                    "track":    best_quote.get("track_score", 0),
                    "comply":   best_quote.get("comply_score", 0),
                },
            },
            "runner_up": [
                {
                    "vendor_name": q.get("vendor_name", ""),
                    "amount":      q.get("amount_total", 0),
                    "score":       q.get("total_score", 0),
                }
                for q in runner_up
            ],
            "total_quotes_evaluated": len(all_scored),
            "evaluated_at":           ctx.get("evaluated_at"),
        }

        await self._log_action(
            action_type=f"quote_comparison_{action}",
            input_data=ctx.get("input_context", {}),
            output_data=result,
            success=True,
        )

        return result

    async def learn(self, learn_context: Dict[str, Any]) -> None:
        self.status = AgentStatus.LEARNING
        result = learn_context.get("result", {})
        logger.info(
            "[QuoteComparisonAgent] Learned: RFQ=%s  recommended=%s  score=%.1f",
            result.get("rfq_number", "?"),
            result.get("recommended_vendor", {}).get("vendor_name", "?"),
            result.get("recommended_vendor", {}).get("score", 0),
        )

    # ── Scoring ────────────────────────────────────────────────────────────────

    def _score_quotes(
        self,
        quotes: List[Dict[str, Any]],
        vendor_perf: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Score and rank all valid quotes."""
        today = datetime.now().date()

        # Filter: keep only quotes that are not expired and not cancelled
        valid = []
        for q in quotes:
            state = str(q.get("state") or "").lower()
            if state in ("cancel", "cancelled", "refused"):
                continue
            validity_raw = q.get("validity_date")
            if validity_raw:
                try:
                    vdate = (
                        validity_raw
                        if hasattr(validity_raw, "date")
                        else datetime.strptime(str(validity_raw)[:10], "%Y-%m-%d").date()
                    )
                    if vdate < today:
                        continue
                except Exception:
                    pass
            valid.append(q)

        if not valid:
            return []

        # Normalise amounts
        amounts = [float(q.get("amount_total") or 0) for q in valid]
        min_amt = min(a for a in amounts if a > 0) if any(a > 0 for a in amounts) else 1.0

        scored = []
        for q in valid:
            amt      = float(q.get("amount_total") or 0)
            vendor_id = str(q.get("partner_id") or q.get("vendor_id") or "")

            # 1. Price score (0–40): cheapest gets 40
            price_score = (min_amt / amt * 40) if amt > 0 else 20.0

            # 2. Delivery score (0–25): no lead time data → 15 (neutral)
            delivery_score = 15.0  # TODO: parse lead_time from quote notes when available

            # 3. Track record (0–25): from vendor_performance table
            vp = vendor_perf.get(vendor_id, {})
            on_time_pct = float(vp.get("on_time_delivery_rate") or vp.get("delivery_rate") or 70)
            track_score = on_time_pct / 100 * 25

            # 4. Compliance / validity (0–10)
            state = str(q.get("state") or "").lower()
            if state in ("confirmed", "purchase", "sent"):
                comply_score = 10.0
            elif state in ("draft", "quotation"):
                comply_score = 7.0
            else:
                comply_score = 5.0

            total = price_score + delivery_score + track_score + comply_score

            scored.append({
                **q,
                "vendor_name":    q.get("vendor_name", f"Vendor-{vendor_id}"),
                "currency":       q.get("currency_id") or "AED",
                "price_score":    round(price_score, 2),
                "delivery_score": round(delivery_score, 2),
                "track_score":    round(track_score, 2),
                "comply_score":   round(comply_score, 2),
                "total_score":    round(total, 2),
            })

        scored.sort(key=lambda x: x["total_score"], reverse=True)
        return scored

    async def _mark_recommended(self, quote_id: Optional[int], rfq_number: str) -> None:
        """Set recommended=true on the winning quote row."""
        if not quote_id:
            return
        try:
            from backend.services.adapters.factory import get_adapter
            from backend.services.nmi_data_service import get_conn

            adapter = get_adapter()
            suffix  = adapter._get_erp_suffix()
            table   = f"vendor_quotes_{suffix}"

            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    # Clear existing recommended flags for this RFQ
                    cur.execute(
                        f"UPDATE {table} SET recommended = FALSE WHERE rfq_id = %s",
                        (rfq_number,),
                    )
                    cur.execute(
                        f"UPDATE {table} SET recommended = TRUE  WHERE id = %s",
                        (quote_id,),
                    )
                    conn.commit()
                logger.info("[QuoteComparisonAgent] Marked quote %s as recommended.", quote_id)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("[QuoteComparisonAgent] Could not mark recommended quote: %s", exc)


async def compare_quotes(params: Dict[str, Any]) -> Dict[str, Any]:
    agent = QuoteComparisonAgent()
    return await agent.execute(params)
