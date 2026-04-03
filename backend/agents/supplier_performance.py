"""
Supplier Performance Agent
Sprint 5: Monitors and evaluates supplier performance over time

Features:
- Delivery performance tracking (on-time delivery rate)
- Quality metrics monitoring (defect rates, returns)
- Communication and responsiveness evaluation
- Pricing trend analysis
- Performance scoring and improvement recommendations
- Supplier risk identification
"""

from typing import Dict, Any, List, Optional
import logging
import json
from datetime import datetime, timedelta

from backend.agents import BaseAgent, AgentDecision
from backend.agents.tools import create_odoo_tools, create_database_tools

logger = logging.getLogger(__name__)


class SupplierPerformanceAgent(BaseAgent):
    """
    Monitors and evaluates supplier performance across multiple dimensions.
    
    Performance Dimensions:
    - Delivery (40%): On-time delivery rate, lead time accuracy
    - Quality (30%): Defect rate, return rate, compliance
    - Price (15%): Price stability, competitiveness
    - Communication (15%): Responsiveness, issue resolution
    
    Performance Levels:
    - Excellent: 90-100 (top tier supplier)
    - Good: 75-89 (reliable supplier)
    - Fair: 60-74 (moderate concerns)
    - Poor: 40-59 (significant issues)
    - Critical: 0-39 (immediate action required)
    """
    
    def __init__(self):
        # Get both Odoo and database tools
        odoo_tools = create_odoo_tools()
        db_tools = create_database_tools()
        
        # Combine relevant tools for supplier performance
        performance_tools = [
            tool for tool in odoo_tools + db_tools
            if tool.name in [
                'get_vendors', 'get_purchase_orders', 'get_products',
                'check_budget_availability', 'get_department_budget_status'
            ]
        ]
        
        super().__init__(
            name="SupplierPerformanceAgent",
            description=(
                "Monitors and evaluates supplier performance across delivery, quality, "
                "price, and communication dimensions. Provides performance scores (0-100) "
                "and improvement recommendations."
            ),
            tools=performance_tools,
            temperature=0.2  # Low temperature for consistent evaluation
        )
        
        logger.info("Supplier Performance Agent initialized")
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute supplier performance evaluation"""
        return await self.execute_with_recovery(input_data)
    
    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Gather supplier performance data"""
        observations = await super().observe(context)
        
        # Extract supplier data
        supplier_data = context.get("supplier_data", context.get("pr_data", {}))
        
        observations.update({
            "supplier_id": supplier_data.get("supplier_id", supplier_data.get("vendor_id")),
            "supplier_name": supplier_data.get("supplier_name", supplier_data.get("vendor_name", "Unknown")),
            "category": supplier_data.get("category", "General"),
            "evaluation_period_days": supplier_data.get("evaluation_period_days", 90),
            
            # Delivery metrics
            "total_orders": supplier_data.get("total_orders", 0),
            "on_time_deliveries": supplier_data.get("on_time_deliveries", 0),
            "late_deliveries": supplier_data.get("late_deliveries", 0),
            "average_delay_days": supplier_data.get("average_delay_days", 0),
            
            # Quality metrics
            "total_items_received": supplier_data.get("total_items_received", 0),
            "defective_items": supplier_data.get("defective_items", 0),
            "returns": supplier_data.get("returns", 0),
            "quality_complaints": supplier_data.get("quality_complaints", 0),
            
            # Price metrics
            "price_increases": supplier_data.get("price_increases", 0),
            "price_decreases": supplier_data.get("price_decreases", 0),
            "price_stability_score": supplier_data.get("price_stability_score", 85),  # 0-100
            "competitiveness_score": supplier_data.get("competitiveness_score", 75),  # 0-100
            
            # Communication metrics
            "response_time_hours": supplier_data.get("response_time_hours", 24),
            "issues_resolved": supplier_data.get("issues_resolved", 0),
            "issues_unresolved": supplier_data.get("issues_unresolved", 0),
            "communication_rating": supplier_data.get("communication_rating", 4.0),  # 1-5
        })

        # Assess whether user provided real performance metrics vs relying on defaults.
        metric_keys = [
            "total_orders",
            "on_time_deliveries",
            "late_deliveries",
            "average_delay_days",
            "total_items_received",
            "defective_items",
            "returns",
            "quality_complaints",
            "price_increases",
            "price_decreases",
            "price_stability_score",
            "competitiveness_score",
            "response_time_hours",
            "issues_resolved",
            "issues_unresolved",
            "communication_rating",
        ]
        provided_metric_count = sum(1 for key in metric_keys if key in supplier_data)

        # Validate supplier existence against Odoo vendor list when supplier name is provided.
        supplier_name = str(observations.get("supplier_name") or "").strip()
        vendor_exists = None
        matched_vendor = None
        vendor_lookup_error = None

        if supplier_name:
            try:
                vendors_tool = next((tool for tool in self.tools if tool.name == "get_vendors"), None)
                if vendors_tool:
                    vendors_raw = vendors_tool.func(None, 200)
                    vendors_data = json.loads(vendors_raw)
                    vendors = vendors_data.get("vendors", []) if vendors_data.get("success") else []

                    supplier_name_l = supplier_name.lower()
                    exact = next(
                        (v for v in vendors if str(v.get("name", "")).strip().lower() == supplier_name_l),
                        None,
                    )
                    fuzzy = next(
                        (v for v in vendors if supplier_name_l in str(v.get("name", "")).strip().lower()),
                        None,
                    )

                    matched_vendor = exact or fuzzy
                    vendor_exists = matched_vendor is not None
                else:
                    vendor_lookup_error = "get_vendors tool unavailable"
            except Exception as e:
                vendor_lookup_error = str(e)

        observations.update({
            "provided_metric_count": provided_metric_count,
            "vendor_exists": vendor_exists,
            "matched_vendor": matched_vendor,
            "vendor_lookup_error": vendor_lookup_error,
        })

        # Data quality flags used by decision phase.
        observations["is_estimated_from_defaults"] = provided_metric_count == 0
        observations["insufficient_evidence"] = (
            observations["is_estimated_from_defaults"]
            and (vendor_exists is False or supplier_name.lower() in ["", "unknown"])
        )
        
        # Calculate performance scores
        delivery_score = self._calculate_delivery_score(observations)
        quality_score = self._calculate_quality_score(observations)
        price_score = self._calculate_price_score(observations)
        communication_score = self._calculate_communication_score(observations)
        
        # Weighted overall score
        overall_score = (
            delivery_score * 0.40 +
            quality_score * 0.30 +
            price_score * 0.15 +
            communication_score * 0.15
        )
        
        observations.update({
            "delivery_score": round(delivery_score, 2),
            "quality_score": round(quality_score, 2),
            "price_score": round(price_score, 2),
            "communication_score": round(communication_score, 2),
            "overall_score": round(overall_score, 2),
            "performance_level": self._get_performance_level(overall_score)
        })
        
        logger.info(
            f"[SupplierAgent] Evaluating {observations['supplier_name']} - "
            f"Overall Score: {observations['overall_score']}/100 ({observations['performance_level']})"
        )
        
        return observations
    
    def _calculate_delivery_score(self, obs: Dict[str, Any]) -> float:
        """Calculate delivery performance score (0-100)"""
        total_orders = obs.get("total_orders", 0)
        if total_orders == 0:
            return 70  # Default for new suppliers
        
        on_time = obs.get("on_time_deliveries", 0)
        late = obs.get("late_deliveries", 0)
        avg_delay = obs.get("average_delay_days", 0)
        
        # On-time delivery rate (0-100)
        on_time_rate = (on_time / total_orders) * 100 if total_orders > 0 else 0
        
        # Penalty for delays
        delay_penalty = min(avg_delay * 2, 30)  # Max 30 point penalty
        
        score = on_time_rate - delay_penalty
        return max(0, min(100, score))
    
    def _calculate_quality_score(self, obs: Dict[str, Any]) -> float:
        """Calculate quality performance score (0-100)"""
        total_items = obs.get("total_items_received", 0)
        if total_items == 0:
            return 75  # Default for new suppliers
        
        defects = obs.get("defective_items", 0)
        returns = obs.get("returns", 0)
        complaints = obs.get("quality_complaints", 0)
        
        # Defect rate (lower is better)
        defect_rate = (defects / total_items) * 100 if total_items > 0 else 0
        return_rate = (returns / total_items) * 100 if total_items > 0 else 0
        
        # Start at 100, deduct for issues
        score = 100
        score -= defect_rate * 5  # 5 points per 1% defect rate
        score -= return_rate * 3  # 3 points per 1% return rate
        score -= complaints * 2   # 2 points per complaint
        
        return max(0, min(100, score))
    
    def _calculate_price_score(self, obs: Dict[str, Any]) -> float:
        """Calculate price performance score (0-100)"""
        stability = obs.get("price_stability_score", 85)
        competitiveness = obs.get("competitiveness_score", 75)
        
        # Weighted average
        score = (stability * 0.6) + (competitiveness * 0.4)
        return max(0, min(100, score))
    
    def _calculate_communication_score(self, obs: Dict[str, Any]) -> float:
        """Calculate communication performance score (0-100)"""
        response_hours = obs.get("response_time_hours", 24)
        resolved = obs.get("issues_resolved", 0)
        unresolved = obs.get("issues_unresolved", 0)
        rating = obs.get("communication_rating", 4.0)
        
        # Response time score (24h = 80, 12h = 90, 6h = 95, 1h = 100)
        if response_hours <= 1:
            response_score = 100
        elif response_hours <= 6:
            response_score = 95
        elif response_hours <= 12:
            response_score = 90
        elif response_hours <= 24:
            response_score = 80
        elif response_hours <= 48:
            response_score = 70
        else:
            response_score = 60
        
        # Issue resolution rate
        total_issues = resolved + unresolved
        resolution_rate = (resolved / total_issues) * 100 if total_issues > 0 else 90
        
        # Communication rating (1-5 scale to 0-100)
        rating_score = (rating / 5) * 100
        
        # Weighted average
        score = (response_score * 0.3) + (resolution_rate * 0.4) + (rating_score * 0.3)
        return max(0, min(100, score))
    
    def _get_performance_level(self, score: float) -> str:
        """Determine performance level based on overall score"""
        if score >= 90:
            return "excellent"
        elif score >= 75:
            return "good"
        elif score >= 60:
            return "fair"
        elif score >= 40:
            return "poor"
        else:
            return "critical"
    
    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Decide on supplier actions based on performance data"""
        
        overall_score = observations.get("overall_score", 0)
        performance_level = observations.get("performance_level", "unknown")
        supplier_name = observations.get("supplier_name", "Unknown")
        
        delivery_score = observations.get("delivery_score", 0)
        quality_score = observations.get("quality_score", 0)
        price_score = observations.get("price_score", 0)
        communication_score = observations.get("communication_score", 0)
        provided_metric_count = observations.get("provided_metric_count", 0)
        vendor_exists = observations.get("vendor_exists")
        supplier_name = observations.get("supplier_name", "Unknown")

        # Guardrail: avoid strong supplier recommendations when evidence is missing.
        if observations.get("insufficient_evidence"):
            action = "evaluate_supplier_data"
            reasoning = (
                f"INSUFFICIENT DATA: Unable to verify supplier '{supplier_name}' with real quarterly metrics. "
                f"Current score is a baseline estimate from defaults and should not drive supplier decisions. "
                f"Please provide delivery/quality/price/communication metrics or confirm a valid vendor record."
            )
            confidence = 0.78
            alternatives = ["collect_quarterly_metrics", "verify_vendor_master_data", "run_trial_evaluation"]

            recommendations = self._generate_recommendations(observations)
            return AgentDecision(
                action=action,
                reasoning=reasoning,
                confidence=confidence,
                context={
                    **observations,
                    "recommendations": recommendations,
                    "data_quality": {
                        "vendor_exists": vendor_exists,
                        "provided_metric_count": provided_metric_count,
                        "is_estimated": True,
                    },
                },
                alternatives=alternatives,
            )
        
        # Decision logic based on performance level
        if performance_level == "critical":
            action = "immediate_review_required"
            reasoning = (
                f"CRITICAL: {supplier_name} scored {overall_score}/100. "
                f"Immediate review required. Consider supplier replacement. "
                f"Breakdown: Delivery {delivery_score}, Quality {quality_score}, "
                f"Price {price_score}, Communication {communication_score}."
            )
            confidence = 0.95
            alternatives = ["supplier_replacement", "performance_improvement_plan", "reduce_order_volume"]
        
        elif performance_level == "poor":
            action = "performance_improvement_plan"
            reasoning = (
                f"POOR PERFORMANCE: {supplier_name} scored {overall_score}/100. "
                f"Requires performance improvement plan. "
                f"Key issues: "
            )
            
            # Identify lowest scoring dimension
            scores = {
                "Delivery": delivery_score,
                "Quality": quality_score,
                "Price": price_score,
                "Communication": communication_score
            }
            lowest = min(scores.items(), key=lambda x: x[1])
            reasoning += f"{lowest[0]} ({lowest[1]}/100) needs immediate attention."
            
            confidence = 0.85
            alternatives = ["supplier_probation", "reduce_orders", "performance_review_meeting"]
        
        elif performance_level == "fair":
            action = "monitor_and_improve"
            reasoning = (
                f"FAIR PERFORMANCE: {supplier_name} scored {overall_score}/100. "
                f"Monitor closely and implement improvements. "
                f"Scores: Delivery {delivery_score}, Quality {quality_score}, "
                f"Price {price_score}, Communication {communication_score}."
            )
            confidence = 0.75
            alternatives = ["continue_monitoring", "performance_coaching", "quarterly_review"]
        
        elif performance_level == "good":
            action = "maintain_relationship"
            reasoning = (
                f"GOOD PERFORMANCE: {supplier_name} scored {overall_score}/100. "
                f"Reliable supplier. Maintain relationship and encourage excellence. "
                f"Scores: Delivery {delivery_score}, Quality {quality_score}, "
                f"Price {price_score}, Communication {communication_score}."
            )
            confidence = 0.80
            alternatives = ["continue_current_approach", "explore_expansion", "annual_review"]
        
        elif performance_level == "excellent":
            action = "strategic_partnership"
            reasoning = (
                f"EXCELLENT PERFORMANCE: {supplier_name} scored {overall_score}/100. "
                f"Top-tier supplier. Consider strategic partnership opportunities. "
                f"Scores: Delivery {delivery_score}, Quality {quality_score}, "
                f"Price {price_score}, Communication {communication_score}."
            )
            confidence = 0.90
            alternatives = ["preferred_supplier_status", "volume_increase", "long_term_contract"]
        
        else:
            action = "evaluate_supplier_data"
            reasoning = (
                f"Insufficient data to evaluate {supplier_name}. "
                f"Collect performance metrics for comprehensive assessment."
            )
            confidence = 0.60
            alternatives = ["data_collection", "trial_period", "initial_evaluation"]
        
        # Add specific recommendations based on weak areas
        recommendations = self._generate_recommendations(observations)
        
        decision = AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={**observations, "recommendations": recommendations},
            alternatives=alternatives
        )
        
        logger.info(
            f"[SupplierAgent] Decision: {action} "
            f"(Score: {overall_score}/100, Level: {performance_level})"
        )
        
        return decision
    
    def _generate_recommendations(self, obs: Dict[str, Any]) -> List[str]:
        """Generate specific improvement recommendations"""
        recommendations = []
        
        delivery_score = obs.get("delivery_score", 0)
        quality_score = obs.get("quality_score", 0)
        price_score = obs.get("price_score", 0)
        communication_score = obs.get("communication_score", 0)
        
        # Delivery recommendations
        if delivery_score < 70:
            on_time_rate = (obs.get("on_time_deliveries", 0) / obs.get("total_orders", 1)) * 100
            recommendations.append(f"Improve on-time delivery rate (currently {on_time_rate:.1f}%)")
            if obs.get("average_delay_days", 0) > 3:
                recommendations.append(f"Address delivery delays (avg {obs['average_delay_days']} days)")
        
        # Quality recommendations
        if quality_score < 70:
            defect_rate = (obs.get("defective_items", 0) / obs.get("total_items_received", 1)) * 100
            if defect_rate > 2:
                recommendations.append(f"Reduce defect rate (currently {defect_rate:.1f}%)")
            if obs.get("returns", 0) > 5:
                recommendations.append(f"Address quality issues causing returns ({obs['returns']} returns)")
        
        # Price recommendations
        if price_score < 70:
            recommendations.append("Review pricing competitiveness and stability")
            if obs.get("price_increases", 0) > 3:
                recommendations.append("Negotiate price stability agreement")
        
        # Communication recommendations
        if communication_score < 70:
            if obs.get("response_time_hours", 0) > 24:
                recommendations.append(f"Improve response time (currently {obs['response_time_hours']}h)")
            resolution_rate = (obs.get("issues_resolved", 0) / 
                             (obs.get("issues_resolved", 0) + obs.get("issues_unresolved", 1))) * 100
            if resolution_rate < 80:
                recommendations.append(f"Improve issue resolution rate (currently {resolution_rate:.1f}%)")
        
        return recommendations if recommendations else ["Continue current performance"]
    
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Execute supplier performance actions"""
        action = decision.action
        context = decision.context
        
        result = {
            "agent": self.name,
            "action": action,
            "supplier_name": context.get("supplier_name", "Unknown"),
            "overall_score": context.get("overall_score", 0),
            "performance_level": context.get("performance_level", "unknown"),
            "delivery_score": context.get("delivery_score", 0),
            "quality_score": context.get("quality_score", 0),
            "price_score": context.get("price_score", 0),
            "communication_score": context.get("communication_score", 0),
            "timestamp": datetime.now().isoformat()
        }
        
        # Action-specific execution
        if action == "immediate_review_required":
            result.update({
                "urgency": "CRITICAL",
                "recommended_actions": [
                    "Schedule emergency supplier review meeting",
                    "Assess risk to ongoing operations",
                    "Identify alternative suppliers immediately",
                    "Consider terminating relationship",
                    "Escalate to procurement director",
                    "Implement contingency plan"
                ],
                "next_steps": [
                    "Emergency meeting within 48 hours",
                    "Risk assessment report",
                    "Supplier replacement plan"
                ],
                "recommendations": context.get("recommendations", [])
            })
        
        elif action == "performance_improvement_plan":
            result.update({
                "urgency": "HIGH",
                "recommended_actions": [
                    "Develop 90-day performance improvement plan",
                    "Set measurable improvement targets",
                    "Schedule bi-weekly progress reviews",
                    "Document performance issues formally",
                    "Implement probationary period if no improvement",
                    "Prepare backup supplier options"
                ],
                "next_steps": [
                    "Draft improvement plan",
                    "Supplier meeting to review issues",
                    "Set clear deadlines and metrics"
                ],
                "recommendations": context.get("recommendations", [])
            })
        
        elif action == "monitor_and_improve":
            result.update({
                "urgency": "MEDIUM",
                "recommended_actions": [
                    "Increase monitoring frequency to weekly",
                    "Provide constructive feedback to supplier",
                    "Identify specific improvement areas",
                    "Consider supplier training or support",
                    "Set quarterly improvement goals",
                    "Track progress on key metrics"
                ],
                "next_steps": [
                    "Performance feedback session",
                    "Weekly metric tracking",
                    "30-day progress review"
                ],
                "recommendations": context.get("recommendations", [])
            })
        
        elif action == "maintain_relationship":
            result.update({
                "urgency": "LOW",
                "recommended_actions": [
                    "Continue standard monitoring",
                    "Provide positive feedback on performance",
                    "Explore opportunities for collaboration",
                    "Consider increasing order volume",
                    "Maintain open communication channels",
                    "Annual performance review"
                ],
                "next_steps": [
                    "Quarterly check-in meetings",
                    "Continue current approach",
                    "Monitor for any changes"
                ],
                "recommendations": context.get("recommendations", [])
            })
        
        elif action == "strategic_partnership":
            result.update({
                "urgency": "LOW",
                "recommended_actions": [
                    "Propose preferred supplier status",
                    "Negotiate long-term contract with benefits",
                    "Explore volume commitment opportunities",
                    "Collaborate on process improvements",
                    "Share forecasts for better planning",
                    "Consider joint innovation initiatives"
                ],
                "next_steps": [
                    "Strategic partnership proposal",
                    "Long-term contract negotiation",
                    "Volume commitment discussion"
                ],
                "recommendations": ["Excellent performance - leverage for strategic advantage"]
            })
        
        elif action == "evaluate_supplier_data":
            result.update({
                "urgency": "MEDIUM",
                "recommended_actions": [
                    "Implement performance tracking systems",
                    "Collect delivery and quality metrics",
                    "Document all supplier interactions",
                    "Establish baseline performance expectations",
                    "Schedule initial evaluation after trial period"
                ],
                "next_steps": [
                    "Set up tracking systems",
                    "Define KPIs",
                    "Trial period evaluation"
                ],
                "recommendations": ["Insufficient data - establish metrics"]
            })
        
        else:
            result.update({
                "urgency": "LOW",
                "recommended_actions": [f"Action: {action}"],
                "next_steps": ["Standard processing"],
                "recommendations": context.get("recommendations", [])
            })
        
        # Add risk assessment
        result["risk_level"] = self._assess_supplier_risk(context)
        
        # Log action
        await self._log_action(
            action_type=action,
            input_data=context,
            output_data=result,
            success=True
        )
        
        logger.info(
            f"[SupplierAgent] Action '{action}' completed - "
            f"Score: {result['overall_score']}/100, Urgency: {result.get('urgency', 'N/A')}"
        )
        
        return result
    
    def _assess_supplier_risk(self, context: Dict[str, Any]) -> str:
        """Assess risk level based on performance"""
        overall_score = context.get("overall_score", 0)
        
        if overall_score < 40:
            return "HIGH"
        elif overall_score < 60:
            return "MEDIUM"
        elif overall_score < 75:
            return "LOW"
        else:
            return "MINIMAL"
    
    async def learn(self, result: Dict[str, Any]) -> None:
        """Learn from supplier performance evaluations"""
        await super().learn(result)
        
        action = result.get("action", "unknown")
        performance_level = result.get("performance_level", "unknown")
        overall_score = result.get("overall_score", 0)
        
        logger.info(
            f"[SupplierAgent] Learned from {action}: "
            f"Level={performance_level}, Score={overall_score}/100"
        )
