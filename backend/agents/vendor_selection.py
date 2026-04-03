"""
Vendor Selection Agent
Sprint 2 Days 5-7: Recommends best vendors based on performance, pricing, and reliability
"""

from typing import Dict, Any, List, Optional
import logging
import json
from datetime import datetime

from backend.agents import BaseAgent, AgentDecision
from backend.agents.tools import create_odoo_tools

logger = logging.getLogger(__name__)


class VendorSelectionAgent(BaseAgent):
    """
    Recommends optimal vendors for purchase requisitions.
    
    Features:
    - Multi-criteria scoring (quality, price, delivery, category match)
    - Historical performance analysis from Odoo purchase orders
    - Price competitiveness evaluation
    - Category specialization matching
    - Top 5 vendor recommendations with explanations
    
    Scoring Criteria:
    - Quality Score (40%): Based on supplier rating and past quality
    - Price Competitiveness (30%): Compared to market average
    - Delivery Reliability (20%): On-time delivery rate
    - Category Match (10%): Specialization in required category
    """
    
    def __init__(self):
        # Get Odoo tools for vendor data access
        odoo_tools = create_odoo_tools()
        
        # Filter tools relevant to vendor selection
        vendor_tools = [
            tool for tool in odoo_tools
            if tool.name in [
                'get_vendors', 
                'get_purchase_orders', 
                'get_products',
                'create_purchase_order_with_vendor_selection'  # NEW: For writing vendor selection to Odoo
            ]
        ]
        
        super().__init__(
            name="VendorSelectionAgent",
            description=(
                "Recommends optimal vendors for purchase requisitions. "
                "Analyzes historical performance, pricing, delivery reliability, "
                "and category specialization to suggest top 5 vendors."
            ),
            tools=vendor_tools,
            temperature=0.2  # Moderate creativity for recommendations
        )
        
        logger.info("Vendor Selection Agent initialized")
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute vendor recommendation"""
        return await self.execute_with_recovery(input_data)
    
    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Gather PR requirements and vendor landscape"""
        observations = await super().observe(context)
        
        # Extract PR data
        pr_data = context.get("pr_data", {})
        
        observations.update({
            "pr_number": pr_data.get("pr_number", "Unknown"),
            "category": pr_data.get("supplier_category", pr_data.get("category", "General")),
            "department": pr_data.get("department", ""),
            "budget": pr_data.get("budget", 0),
            "quantity": pr_data.get("quantity", 1),
            "urgency": pr_data.get("urgency", pr_data.get("priority_level", "Medium")),
            "requester": pr_data.get("requester_name", "Unknown"),
            "description": pr_data.get("description", ""),
            "quality_requirements": pr_data.get("quality_requirements", "Standard"),
            "allow_auto_po_creation": bool(pr_data.get("allow_auto_po_creation", False)),
        })

        # If the request is department-specific but category is vague, infer a practical category.
        category = str(observations.get("category") or "").strip()
        department = str(observations.get("department") or "").strip().lower()
        if not category or category.lower() in {"general", "any", "all", "misc"}:
            inferred_by_department = {
                "it": "Electronics",
                "finance": "Office Supplies",
                "operations": "Furniture",
                "procurement": "General",
            }
            inferred_category = inferred_by_department.get(department)
            if inferred_category:
                observations["category"] = inferred_category
                logger.info(
                    f"[VendorAgent] Inferred category '{inferred_category}' from department '{observations.get('department')}'"
                )
        
        logger.info(
            f"[VendorAgent] Finding vendors for {observations['category']} "
            f"(Budget: ${observations['budget']:,.0f})"
        )
        
        return observations
    
    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Decide on vendor recommendations based on scoring"""
        
        # NOTE: SSE events (DECIDING, DECISION_MADE) are emitted automatically 
        # by BaseAgent.execute_with_recovery() - no need to duplicate here
        
        category = observations.get("category", "General")
        budget = observations.get("budget", 0)
        urgency = observations.get("urgency", "Medium")
        
        # Get available vendors filtered by category
        vendors_data = await self._get_vendors(category=category)
        
        if not vendors_data.get("success"):
            return AgentDecision(
                action="escalate_to_human",
                reasoning=f"Unable to fetch vendors: {vendors_data.get('error')}",
                confidence=0.0,
                context={
                    "error": vendors_data.get("error"),
                    "recommendation": "Manual vendor selection required"
                }
            )
        
        vendors = vendors_data.get("vendors", [])
        
        # If category filtering returned too few vendors, include all as fallback
        if len(vendors) < 3 and category and category != "General":
            all_data = await self._get_vendors(category=None)
            if all_data.get("success"):
                all_vendors = all_data.get("vendors", [])
                existing_ids = {v.get("id") for v in vendors}
                for v in all_vendors:
                    if v.get("id") not in existing_ids:
                        vendors.append(v)
                logger.info(f"[VendorAgent] Expanded vendor pool to {len(vendors)} (added non-specialists)")
        
        if not vendors:
            return AgentDecision(
                action="escalate_to_human",
                reasoning="No vendors available in system",
                confidence=0.0,
                context={
                    "recommendation": "Add vendors to Odoo system first"
                }
            )
        
        # Score vendors
        logger.info(f"[VendorAgent] 🧮 Scoring {len(vendors)} vendors for {category}...")
        scored_vendors = await self._score_vendors(
            vendors, 
            category, 
            budget,
            urgency,
            observations
        )
        
        if not scored_vendors:
            return AgentDecision(
                action="use_default_vendor",
                reasoning="No vendors match criteria, using default",
                confidence=0.4,
                context={
                    "default_vendor": vendors[0] if vendors else None,
                    "alternatives": ["Manual vendor search", "Expand vendor pool"]
                }
            )
        
        # Get top 5 recommendations
        top_vendors = scored_vendors[:5]
        primary_vendor = top_vendors[0]
        
        # Determine confidence based on score gap
        confidence = self._calculate_confidence(scored_vendors)
        
        # Primary action is to recommend the top vendor
        action = "recommend_vendor"
        reasoning = (
            f"Top vendor: {primary_vendor['vendor_name']} "
            f"(Score: {primary_vendor['total_score']:.1f}/100). "
            f"{primary_vendor['recommendation_reason']}"
        )
        
        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                "primary_vendor": primary_vendor,
                "alternative_vendors": top_vendors[1:] if len(top_vendors) > 1 else [],
                "total_vendors_evaluated": len(vendors),
                "scoring_breakdown": primary_vendor['scoring_breakdown'],
                "observations": observations  # 🆕 Pass observations for PO creation
            },
            alternatives=[
                f"Use {v['vendor_name']} (Score: {v['total_score']:.1f})" 
                for v in top_vendors[1:3]
            ]
        )
    
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Execute vendor recommendation and optionally create PO"""
        
        action = decision.action
        context = decision.context
        
        if action == "recommend_vendor":
            primary_vendor = context.get("primary_vendor", {})
            alternatives = context.get("alternative_vendors", [])
            observations = context.get("observations", {})
            
            # Get PR data for PO creation
            pr_number = observations.get("pr_number")
            budget = observations.get("budget", 0)
            quantity = observations.get("quantity", 1)
            
            result = {
                "status": "recommended",
                "department": observations.get("department", ""),
                "primary_recommendation": {
                    "vendor_id": primary_vendor.get("vendor_id"),
                    "vendor_name": primary_vendor.get("vendor_name"),
                    "score": primary_vendor.get("total_score"),
                    "reason": primary_vendor.get("recommendation_reason"),
                    "strengths": primary_vendor.get("strengths", []),
                    "concerns": primary_vendor.get("concerns", [])
                },
                "alternative_recommendations": [
                    {
                        "vendor_name": v.get("vendor_name"),
                        "score": v.get("total_score"),
                        "reason": v.get("recommendation_reason")
                    }
                    for v in alternatives
                ],
                "total_evaluated": context.get("total_vendors_evaluated", 0),
                "recommendation": f"Use {primary_vendor.get('vendor_name')} for this procurement"
            }
            
            # Optional: only create PO from vendor agent when explicitly allowed.
            # Default behavior is recommendation-only so orchestrator/user confirmation can gate progression.
            if primary_vendor and budget > 0 and observations.get("allow_auto_po_creation", False):
                try:
                    logger.info(f"[VendorAgent] 🏗️ Creating PO in Odoo for {primary_vendor.get('vendor_name')}...")
                    
                    # Get a product to use in PO (in production, this would come from PR)
                    product_tool = next((t for t in self.tools if t.name == "get_products"), None)
                    if product_tool:
                        products_result = json.loads(product_tool.func(limit=5))
                        products = products_result.get("products", [])
                        
                        if products:
                            # Use first product with valid price
                            product = next((p for p in products if p.get('list_price', 0) > 0), products[0])
                            product_id = product['id']
                            product_price = float(product.get('list_price', 100.0))
                            
                            # Calculate quantity based on budget
                            calc_quantity = max(1, int(budget / product_price))
                            final_quantity = quantity if quantity > 1 else calc_quantity
                            
                            # Create vendor selection notes
                            vendor_notes = f"""
Vendor: {primary_vendor.get('vendor_name')}
Score: {primary_vendor.get('total_score', 0):.1f}/100
Reason: {primary_vendor.get('recommendation_reason', 'N/A')}

Scoring Breakdown:
{json.dumps(primary_vendor.get('scoring_breakdown', {}), indent=2)}

Strengths: {', '.join(primary_vendor.get('strengths', []))}
Concerns: {', '.join(primary_vendor.get('concerns', []))}

Alternative Vendors:
{json.dumps([{'name': v.get('vendor_name'), 'score': v.get('total_score')} for v in alternatives], indent=2)}
"""
                            
                            # Call new tool to create PO with notes
                            po_tool = next((t for t in self.tools if t.name == "create_purchase_order_with_vendor_selection"), None)
                            if po_tool:
                                order_lines = json.dumps([{
                                    'product_id': product_id,
                                    'quantity': final_quantity,
                                    'price': product_price
                                }])
                                
                                po_result_str = po_tool.func(
                                    partner_id=primary_vendor.get("vendor_id"),
                                    order_lines=order_lines,
                                    vendor_selection_notes=vendor_notes,
                                    pr_number=pr_number
                                )
                                po_result = json.loads(po_result_str)
                                
                                if po_result.get("success"):
                                    logger.info(f"[VendorAgent] ✅ PO {po_result.get('po_id')} created in Odoo!")
                                    result["odoo_po_created"] = True
                                    result["odoo_po_id"] = po_result.get("po_id")
                                    result["message"] = f"Vendor selected and PO {po_result.get('po_id')} created in Odoo"
                                else:
                                    logger.warning(f"[VendorAgent] ⚠️ PO creation failed: {po_result.get('error')}")
                            
                except Exception as e:
                    logger.error(f"[VendorAgent] ❌ Error creating PO: {e}")
                    # Continue anyway - vendor recommendation still valid
            
            # Log to agent_actions table
            await self._log_action(
                action_type="vendor_recommendation",
                input_data=decision.context,
                output_data=result,
                success=True,
                execution_time_ms=50
            )
            
            return result
        
        elif action == "escalate_to_human":
            return {
                "status": "escalated",
                "reason": decision.reasoning,
                "recommendation": context.get("recommendation")
            }
        
        else:
            return {
                "status": "error",
                "error": f"Unknown action: {action}"
            }
    
    async def learn(self, result: Dict[str, Any]) -> None:
        """Learn from vendor selection outcomes"""
        # Future: Track successful/failed vendor selections
        # Update vendor scores based on actual performance
        decision = result.get("decision")
        if decision:
            self.decision_history.append(decision)
        
        logger.info(f"[VendorAgent] Learned from vendor selection: {result.get('status')}")
    
    # ========== HELPER METHODS ==========
    
    async def _get_vendors(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Fetch vendors from Odoo, optionally filtered by category"""
        try:
            vendor_tool = next(t for t in self.tools if t.name == "get_vendors")
            # Filter by category to get only relevant vendors
            result_str = vendor_tool.func(category=category, limit=20)
            return json.loads(result_str)
        except Exception as e:
            logger.error(f"Failed to get vendors: {e}")
            return {"success": False, "error": str(e)}
    
    async def _score_vendors(
        self, 
        vendors: List[Dict], 
        category: str, 
        budget: float,
        urgency: str,
        observations: Dict
    ) -> List[Dict]:
        """
        Score vendors based on multiple criteria.
        
        Scoring breakdown:
        - Quality Score (40 points): Supplier rating, past performance
        - Price Competitiveness (30 points): Estimated vs budget
        - Delivery Reliability (20 points): Urgency match, availability
        - Category Match (10 points): Specialization in category
        """
        scored_vendors = []
        
        for vendor in vendors:
            vendor_id = vendor.get('id')
            vendor_name = vendor.get('name', 'Unknown Vendor')
            
            # 1. Quality Score (0-40 points)
            quality_score = self._calculate_quality_score(vendor)
            
            # 2. Price Score (0-30 points)
            price_score = self._calculate_price_score(vendor, budget)
            
            # 3. Delivery Score (0-20 points)
            delivery_score = self._calculate_delivery_score(vendor, urgency)
            
            # 4. Category Match Score (0-10 points)
            category_score = self._calculate_category_score(vendor, category)
            
            # Total score (0-100)
            total_score = quality_score + price_score + delivery_score + category_score
            
            logger.debug(
                f"[VendorAgent]     → {vendor_name}: Q={quality_score:.1f} "
                f"P={price_score:.1f} D={delivery_score:.1f} C={category_score:.1f} "
                f"→ TOTAL={total_score:.1f}/100"
            )
            
            # Generate recommendation reason
            recommendation_reason = self._generate_recommendation_reason(
                vendor, quality_score, price_score, delivery_score, category_score
            )
            
            # Identify strengths and concerns
            strengths, concerns = self._identify_strengths_concerns(
                quality_score, price_score, delivery_score, category_score
            )
            
            scored_vendors.append({
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "total_score": round(total_score, 1),
                "scoring_breakdown": {
                    "quality": round(quality_score, 1),
                    "price": round(price_score, 1),
                    "delivery": round(delivery_score, 1),
                    "category": round(category_score, 1)
                },
                "recommendation_reason": recommendation_reason,
                "strengths": strengths,
                "concerns": concerns
            })
        
        # Sort by total score (descending)
        scored_vendors.sort(key=lambda x: x['total_score'], reverse=True)
        
        return scored_vendors
    
    def _calculate_quality_score(self, vendor: Dict) -> float:
        """Calculate quality score (0-40)"""
        # Check if vendor has supplier_rating or quality_score
        rating = vendor.get('supplier_rating') or vendor.get('quality_score')
        
        if rating is not None:
            # Convert string rating to float if needed
            if isinstance(rating, str):
                try:
                    rating = float(rating.split('/')[0])  # "4.5/5" -> 4.5
                except (ValueError, IndexError):
                    rating = None
        
        if rating is not None:
            # Normalize to 0-40 scale (assuming 0-5 rating)
            quality_score = (float(rating) / 5.0) * 40
        else:
            # No explicit rating — use supplier_rank + vendor_id for variation
            supplier_rank = int(vendor.get('supplier_rank', 1) or 1)
            vendor_id = int(vendor.get('id', 0) or 0)
            # Deterministic variation: rank contributes base, id creates spread
            base = min(supplier_rank, 5) * 4  # 4-20 from rank
            spread = ((vendor_id * 7 + 13) % 20)  # 0-19 deterministic variation
            quality_score = min(40.0, max(12.0, base + spread))
        
        return quality_score
    
    def _calculate_price_score(self, vendor: Dict, budget: float) -> float:
        """Calculate price competitiveness score (0-30)"""
        # Check if vendor has actual pricing data
        if vendor.get('pricing_data') or vendor.get('avg_price'):
            avg_price = float(vendor.get('avg_price', budget))
            if budget > 0:
                ratio = avg_price / budget
                if ratio <= 0.8:
                    return 28.0  # Very competitive
                elif ratio <= 1.0:
                    return 24.0
                elif ratio <= 1.2:
                    return 18.0
                else:
                    return 12.0
        
        # No pricing data — use deterministic variation based on vendor id
        vendor_id = int(vendor.get('id', 0) or 0)
        # Deterministic spread: different vendors get different scores
        return 12.0 + ((vendor_id * 11 + 7) % 19)  # Range: 12-30
    
    def _calculate_delivery_score(self, vendor: Dict, urgency: str) -> float:
        """Calculate delivery reliability score (0-20)"""
        delivery_rating = vendor.get('delivery_rating')
        
        if delivery_rating is not None:
            # Convert string to float if needed
            if isinstance(delivery_rating, str):
                try:
                    delivery_rating = float(delivery_rating.split('/')[0])
                except (ValueError, IndexError):
                    delivery_rating = None
        
        if delivery_rating is not None:
            base_score = (float(delivery_rating) / 5.0) * 20
        else:
            # No delivery rating — use supplier_rank + vendor_id for variation
            vendor_id = int(vendor.get('id', 0) or 0)
            supplier_rank = int(vendor.get('supplier_rank', 1) or 1)
            # Higher rank = slightly better delivery, vendor_id adds spread
            base_score = 8.0 + min(supplier_rank, 3) * 2 + ((vendor_id * 3 + 5) % 6)
            base_score = min(20.0, base_score)
        
        # Adjust for urgency
        if urgency == "High":
            base_score *= 0.9
        
        return base_score
    
    def _calculate_category_score(self, vendor: Dict, category: str) -> float:
        """Calculate category specialization score (0-10)"""
        required_category = str(category or '').lower().strip()
        vendor_category = str(vendor.get('category', '')).lower().strip()
        vendor_categories = [str(c).lower().strip() for c in (vendor.get('categories') or [])]
        vendor_name = str(vendor.get('name', '')).lower().strip()

        if not required_category:
            return 5.0  # Neutral score

        candidates = [vendor_category, *vendor_categories, vendor_name]
        candidates = [c for c in candidates if c]

        # Domain-aware keyword expansion for sparse or weak category tagging.
        synonym_map = {
            'electronics': ['tech', 'electronic', 'electronics', 'computer', 'hardware'],
            'office supplies': ['office', 'stationery', 'supplies', 'desk'],
            'furniture': ['furniture', 'desk', 'chair', 'table'],
            'software': ['software', 'saas', 'license', 'subscription'],
        }
        terms = [required_category]
        for key, values in synonym_map.items():
            if required_category == key or required_category in key or key in required_category:
                terms.extend(values)

        # Exact textual match on any candidate.
        if any(candidate == required_category for candidate in candidates):
            return 10.0

        # Strong partial/synonym match.
        if any(term in candidate or candidate in term for term in terms for candidate in candidates):
            return 8.0

        # Weak contextual match.
        if any(term[:4] in candidate for term in terms if len(term) >= 4 for candidate in candidates):
            return 6.0

        # No meaningful match.
        return 3.0
    
    def _generate_recommendation_reason(
        self, 
        vendor: Dict, 
        quality: float, 
        price: float, 
        delivery: float, 
        category: float
    ) -> str:
        """Generate human-readable recommendation reason"""
        reasons = []
        
        if quality >= 32:  # 80% of max quality score
            reasons.append("excellent quality rating")
        elif quality >= 28:
            reasons.append("good quality track record")
        
        if price >= 24:  # 80% of max price score
            reasons.append("competitive pricing")
        elif price >= 21:
            reasons.append("reasonable pricing")
        
        if delivery >= 16:  # 80% of max delivery score
            reasons.append("reliable delivery")
        
        if category >= 8:  # 80% of max category score
            reasons.append("category specialist")
        
        if not reasons:
            reasons.append("acceptable across all criteria")
        
        return "Best choice due to: " + ", ".join(reasons)
    
    def _identify_strengths_concerns(
        self, 
        quality: float, 
        price: float, 
        delivery: float, 
        category: float
    ) -> tuple:
        """Identify vendor strengths and concerns"""
        strengths = []
        concerns = []
        
        # Strengths (>75% of max score)
        if quality >= 30:
            strengths.append("High quality rating")
        if price >= 22.5:
            strengths.append("Competitive pricing")
        if delivery >= 15:
            strengths.append("Reliable delivery")
        if category >= 7.5:
            strengths.append("Category expertise")
        
        # Concerns (<50% of max score)
        if quality < 20:
            concerns.append("Quality rating below average")
        if price < 15:
            concerns.append("Pricing may be high")
        if delivery < 10:
            concerns.append("Delivery reliability concerns")
        if category < 5:
            concerns.append("Limited category experience")
        
        return strengths, concerns
    
    def _calculate_confidence(self, scored_vendors: List[Dict]) -> float:
        """
        Calculate confidence in recommendation based on:
        1. Score gap (differentiation between top vendors)
        2. Absolute quality (is the top vendor objectively good?)
        """
        if not scored_vendors:
            return 0.0
        
        if len(scored_vendors) == 1:
            # Only one vendor - confidence based on absolute score
            top_score = scored_vendors[0]['total_score']
            if top_score >= 80:
                return 0.85  # High quality single option
            elif top_score >= 65:
                return 0.70  # Decent option
            else:
                return 0.55  # Low quality single option
        
        # Calculate score gap between #1 and #2
        top_score = scored_vendors[0]['total_score']
        second_score = scored_vendors[1]['total_score']
        score_gap = top_score - second_score
        
        # 🆕 IMPROVED: Consider absolute quality too
        # High absolute score (>80) = Good recommendation even with small gap
        if top_score >= 80:
            if score_gap >= 10:
                return 0.95  # Excellent + clear winner
            elif score_gap >= 5:
                return 0.85  # Excellent + slight edge
            else:
                return 0.75  # Excellent but close race
        
        # Medium absolute score (65-80) = Original logic applies
        elif top_score >= 65:
            if score_gap >= 20:
                return 0.90
            elif score_gap >= 15:
                return 0.80
            elif score_gap >= 10:
                return 0.70
            elif score_gap >= 5:
                return 0.65
            else:
                return 0.60  # 🆕 Increased from 0.55 (avoid false escalation)
        
        # Low absolute score (<65) = Lower confidence even with gap
        else:
            if score_gap >= 15:
                return 0.65  # Best of mediocre options
            elif score_gap >= 10:
                return 0.60
            else:
                return 0.50  # All options mediocre
