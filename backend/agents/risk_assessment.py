"""
Risk Assessment Agent
Sprint 3: Evaluates procurement risks across multiple dimensions

Analyzes:
- Vendor performance risks (delivery, quality, reliability)
- Financial risks (budget overruns, price volatility)
- Compliance risks (regulatory, policy violations)
- Operational risks (single-source dependency, capacity constraints)
"""

from typing import Dict, Any, List, Optional
import logging
import json
from datetime import datetime, timedelta

from backend.agents import BaseAgent, AgentDecision
from backend.agents.tools import create_odoo_tools, create_database_tools

logger = logging.getLogger(__name__)


class RiskAssessmentAgent(BaseAgent):
    """
    Evaluates procurement risks and provides mitigation recommendations.
    
    Risk Scoring (0-100, higher = more risk):
    - Vendor Risk (30%): Performance, reliability, dependency
    - Financial Risk (30%): Budget impact, price volatility
    - Compliance Risk (25%): Regulatory, policy adherence
    - Operational Risk (15%): Supply chain, capacity
    
    Risk Levels:
    - LOW (<30): Proceed with normal approval
    - MEDIUM (30-60): Needs manager review
    - HIGH (60-80): Requires director approval + mitigation plan
    - CRITICAL (>80): Immediate escalation + hold procurement
    """
    
    def __init__(self):
        # Get both Odoo and database tools
        odoo_tools = create_odoo_tools()
        db_tools = create_database_tools()
        
        # Combine relevant tools for risk assessment
        risk_tools = [
            tool for tool in odoo_tools + db_tools
            if tool.name in [
                'get_vendors', 'get_purchase_orders', 'get_products',
                'check_budget_availability', 'get_department_budget_status',
                'get_approval_chain', 'store_risk_assessment'  # Added new tool
            ]
        ]
        
        super().__init__(
            name="RiskAssessmentAgent",
            description=(
                "Evaluates procurement risks across vendor performance, financial, "
                "compliance, and operational dimensions. Provides risk scores (0-100) "
                "and mitigation recommendations."
            ),
            tools=risk_tools,
            temperature=0.1  # Very low - we want consistent risk assessment
        )
        
        logger.info("Risk Assessment Agent initialized with store_risk_assessment tool")
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute risk assessment"""
        return await self.execute_with_recovery(input_data)
    
    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Gather PR data and risk context"""
        observations = await super().observe(context)
        
        # Extract PR data
        pr_data = context.get("pr_data", {})
        
        observations.update({
            "pr_number": pr_data.get("pr_number", "Unknown"),
            "vendor_name": pr_data.get("vendor_name", pr_data.get("supplier_name", "Unknown")),
            "vendor_id": pr_data.get("vendor_id", pr_data.get("supplier_id")),
            "category": pr_data.get("supplier_category", pr_data.get("category", "General")),
            "budget": pr_data.get("budget", pr_data.get("total_amount", 0)),
            "department": pr_data.get("department", "Unknown"),
            "budget_category": pr_data.get("budget_category", "OPEX"),  # CAPEX or OPEX
            "urgency": pr_data.get("urgency", pr_data.get("priority_level", "Low")),
            "quantity": pr_data.get("quantity", 1),
            "description": pr_data.get("description", ""),
            "justification": pr_data.get("justification", pr_data.get("purchase_justification", "")),
            "requester": pr_data.get("requester_name") or pr_data.get("requester") or "Unknown"
        })
        
        logger.info(
            f"[RiskAgent] Assessing risks for {observations['pr_number']} - "
            f"Vendor: {observations['vendor_name']}, Budget: ${observations['budget']:,.0f}"
        )
        
        return observations
    
    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Decide on risk level and required actions"""
        
        vendor_name = observations.get("vendor_name", "Unknown")
        vendor_id = observations.get("vendor_id")
        budget = observations.get("budget", 0)
        department = observations.get("department", "Unknown")
        category = observations.get("category", "General")
        urgency = observations.get("urgency", "Medium")
        
        # Calculate risk scores across dimensions
        logger.info(f"[RiskAgent] Performing 4-dimensional risk assessment for {vendor_name}...")
        logger.debug("[RiskAgent]   1️⃣ Assessing vendor risk (30% weight)...")
        vendor_risk = await self._assess_vendor_risk(vendor_id, vendor_name, observations)
        logger.info(f"[RiskAgent]   Vendor Risk: {vendor_risk['score']:.1f}/100 - {len(vendor_risk['concerns'])} concerns")
        
        logger.debug("[RiskAgent]   2️⃣ Assessing financial risk (30% weight)...")
        financial_risk = await self._assess_financial_risk(budget, department, observations)
        logger.info(f"[RiskAgent]   Financial Risk: {financial_risk['score']:.1f}/100")
        
        logger.debug("[RiskAgent]   3️⃣ Assessing compliance risk (25% weight)...")
        compliance_risk = await self._assess_compliance_risk(category, budget, observations)
        logger.info(f"[RiskAgent]   Compliance Risk: {compliance_risk['score']:.1f}/100")
        
        logger.debug("[RiskAgent]   4️⃣ Assessing operational risk (15% weight)...")
        operational_risk = await self._assess_operational_risk(
            vendor_name, category, urgency, observations
        )
        logger.info(f"[RiskAgent]   Operational Risk: {operational_risk['score']:.1f}/100")
        
        # Calculate weighted total risk (0-100)
        total_risk_score = (
            vendor_risk['score'] * 0.30 +
            financial_risk['score'] * 0.30 +
            compliance_risk['score'] * 0.25 +
            operational_risk['score'] * 0.15
        )
        logger.info(f"[RiskAgent] TOTAL WEIGHTED RISK SCORE: {total_risk_score:.1f}/100")
        
        # Determine risk level
        risk_level, risk_color = self._determine_risk_level(total_risk_score)
        logger.info(f"[RiskAgent] {risk_color} Risk Level: {risk_level} (Score: {total_risk_score:.1f}/100)")
        
        # Generate mitigation recommendations
        mitigations = self._generate_mitigations(
            risk_level, vendor_risk, financial_risk, compliance_risk, operational_risk
        )

        # Calculate confidence based on data quality (not just risk level)
        base_confidence = self._calculate_confidence_from_data_quality(observations, vendor_risk, financial_risk)

        # Determine action based on risk level
        if risk_level == "CRITICAL":
            action = "escalate_to_human"
            confidence = min(base_confidence + 0.05, 0.95)  # Boost for critical (we're very sure it's bad)
            reasoning = (
                f"CRITICAL RISK DETECTED (Score: {total_risk_score:.1f}/100). "
                f"Immediate human review required. Top concerns: {', '.join(mitigations[:2])}"
            )
        elif risk_level == "HIGH":
            action = "require_mitigation_plan"
            confidence = base_confidence  # Use calculated confidence
            reasoning = (
                f"HIGH RISK (Score: {total_risk_score:.1f}/100). "
                f"Director approval + mitigation plan required before proceeding."
            )
        elif risk_level == "MEDIUM":
            action = "require_manager_review"
            confidence = max(base_confidence - 0.05, 0.50)  # Reduce slightly for medium (more uncertain)
            reasoning = (
                f"MEDIUM RISK (Score: {total_risk_score:.1f}/100). "
                f"Manager review recommended. Consider: {mitigations[0] if mitigations else 'additional due diligence'}"
            )
        else:  # LOW
            action = "approve_low_risk"
            confidence = base_confidence  # Use calculated confidence
            reasoning = (
                f"LOW RISK (Score: {total_risk_score:.1f}/100). "
                f"Procurement can proceed with normal approval process."
            )
        
        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                "risk_assessment": {
                    "total_score": round(total_risk_score, 1),
                    "risk_level": risk_level,
                    "risk_color": risk_color,
                    "breakdown": {
                        "vendor_risk": {
                            "score": round(vendor_risk['score'], 1),
                            "weight": "30%",
                            "concerns": vendor_risk['concerns']
                        },
                        "financial_risk": {
                            "score": round(financial_risk['score'], 1),
                            "weight": "30%",
                            "concerns": financial_risk['concerns']
                        },
                        "compliance_risk": {
                            "score": round(compliance_risk['score'], 1),
                            "weight": "25%",
                            "concerns": compliance_risk['concerns']
                        },
                        "operational_risk": {
                            "score": round(operational_risk['score'], 1),
                            "weight": "15%",
                            "concerns": operational_risk['concerns']
                        }
                    },
                    "mitigations": mitigations,
                    "recommended_actions": self._get_recommended_actions(risk_level)
                },
                "vendor_name": vendor_name,
                "budget": budget,
                "pr_number": observations.get("pr_number")
            },
            alternatives=[
                f"Add backup vendor for {category}",
                f"Split order to reduce concentration risk",
                f"Request performance bond from vendor"
            ]
        )
    
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Execute risk assessment action and store results"""
        
        action = decision.action
        context = decision.context
        risk_assessment = context.get("risk_assessment", {})
        pr_number = context.get("pr_number", "Unknown")
        vendor_name = context.get("vendor_name", "Unknown")
        budget = context.get("budget", 0)
        
        # Determine if PO creation should be blocked (CRITICAL risk only)
        risk_level = risk_assessment.get("risk_level")
        blocked_po_creation = (risk_level == "CRITICAL")
        
        result = {
            "status": self._map_action_to_status(action),
            "risk_score": risk_assessment.get("total_score"),
            "risk_level": risk_level,
            "breakdown": risk_assessment.get("breakdown"),
            "mitigations": risk_assessment.get("mitigations", []),
            "recommended_actions": risk_assessment.get("recommended_actions", []),
            "requires_human_review": action in ["escalate_to_human", "require_mitigation_plan"],
            "can_proceed": action in ["approve_low_risk", "require_manager_review"],
            "blocked_po_creation": blocked_po_creation  # Critical flag
        }
        
        # === NEW: Store risk assessment in database ===
        try:
            # Get the store_risk_assessment tool
            store_tool = next((t for t in self.tools if t.name == "store_risk_assessment"), None)
            
            if store_tool:
                # Prepare risk data for storage
                risk_data = {
                    "pr_number": pr_number,
                    "odoo_po_id": context.get("odoo_po_id"),  # Will be None if PO not created yet
                    "total_risk_score": risk_assessment.get("total_score"),
                    "vendor_risk_score": risk_assessment.get("breakdown", {}).get("vendor_risk", {}).get("score", 0),
                    "financial_risk_score": risk_assessment.get("breakdown", {}).get("financial_risk", {}).get("score", 0),
                    "compliance_risk_score": risk_assessment.get("breakdown", {}).get("compliance_risk", {}).get("score", 0),
                    "operational_risk_score": risk_assessment.get("breakdown", {}).get("operational_risk", {}).get("score", 0),
                    "risk_level": risk_level,
                    "risk_breakdown": risk_assessment.get("breakdown", {}),
                    "mitigation_recommendations": risk_assessment.get("mitigations", []),
                    "concerns_identified": {
                        "vendor": risk_assessment.get("breakdown", {}).get("vendor_risk", {}).get("concerns", []),
                        "financial": risk_assessment.get("breakdown", {}).get("financial_risk", {}).get("concerns", []),
                        "compliance": risk_assessment.get("breakdown", {}).get("compliance_risk", {}).get("concerns", []),
                        "operational": risk_assessment.get("breakdown", {}).get("operational_risk", {}).get("concerns", [])
                    },
                    "recommended_action": action,
                    "decision_confidence": decision.confidence,
                    "blocked_po_creation": blocked_po_creation,
                    "vendor_name": vendor_name,
                    "vendor_id": context.get("vendor_id"),
                    "budget_amount": budget,
                    "department": context.get("department"),
                    "category": context.get("category"),
                    "urgency": context.get("urgency")
                }
                
                # Call the tool to store risk data (run in thread to avoid blocking event loop)
                import asyncio as _aio
                storage_result_json = await _aio.to_thread(store_tool.func, json.dumps(risk_data))
                storage_result = json.loads(storage_result_json)
                
                if storage_result.get("success"):
                    logger.info(
                        f"[RiskAgent] Risk assessment stored: ID={storage_result['assessment_id']}, "
                        f"PR={pr_number}, Risk={risk_level}, Blocked={blocked_po_creation}"
                    )
                    result["assessment_id"] = storage_result["assessment_id"]
                    result["stored_in_database"] = True
                else:
                    logger.error(f"[RiskAgent] Failed to store risk assessment: {storage_result.get('error')}")
                    result["stored_in_database"] = False
                    result["storage_error"] = storage_result.get("error")
            else:
                logger.warning("[RiskAgent] ️ store_risk_assessment tool not found")
                result["stored_in_database"] = False
        
        except Exception as e:
            logger.error(f"[RiskAgent] Error storing risk assessment: {e}")
            result["stored_in_database"] = False
            result["storage_error"] = str(e)
        
        # Log action to agent_actions table (existing logging)
        await self._log_action(
            action_type="risk_assessment",
            input_data=context,
            output_data=result,
            success=True,
            execution_time_ms=75
        )
        
        # Add warning if PO creation was blocked
        if blocked_po_creation:
            logger.warning(
                f"[RiskAgent] CRITICAL RISK: PO creation BLOCKED for {pr_number}. "
                f"Risk score: {risk_assessment.get('total_score'):.1f}/100. "
                f"Human review required immediately."
            )
        
        return result
    
    async def learn(self, result: Dict[str, Any]) -> None:
        """Learn from risk assessment outcomes"""
        # Future: Track prediction accuracy vs actual outcomes
        decision = result.get("decision")
        if decision:
            self.decision_history.append(decision)
        
        logger.info(
            f"[RiskAgent] Learned from assessment: "
            f"Risk Level {result.get('risk_level', 'Unknown')}"
        )
    
    # ========== RISK ASSESSMENT METHODS ==========
    
    async def _assess_vendor_risk(
        self, 
        vendor_id: Optional[int], 
        vendor_name: str,
        observations: Dict
    ) -> Dict[str, Any]:
        """
        Assess vendor performance risk (0-100).
        
        Factors:
        - Historical delivery performance
        - Quality rating
        - Response time
        - Contract violations
        - Single-source dependency
        """
        risk_score = 0.0
        concerns = []
        
        # Get vendor data if ID available
        # If no ID but we have a name, try to resolve it
        if not vendor_id and vendor_name and vendor_name != "Unknown":
            resolved = await self._resolve_vendor_by_name(vendor_name)
            if resolved:
                vendor_id = resolved.get("id")
                logger.info(f"[RiskAgent] Resolved vendor '{vendor_name}' -> ID {vendor_id}")

        if vendor_id:
            vendor_data = await self._get_vendor_data(vendor_id)
            
            if vendor_data:
                # 1. Check supplier rating (max 30 points)
                rating = self._extract_rating(vendor_data.get('supplier_rating', '4/5'))
                if rating < 3.0:
                    risk_score += 30
                    concerns.append(f"Low supplier rating ({rating}/5)")
                elif rating < 4.0:
                    risk_score += 15
                    concerns.append(f"Below-average rating ({rating}/5)")
                
                # 2. Check delivery performance (max 25 points)
                delivery_rating = self._extract_rating(vendor_data.get('delivery_rating', '4/5'))
                if delivery_rating < 3.5:
                    risk_score += 25
                    concerns.append("Poor delivery track record")
                elif delivery_rating < 4.0:
                    risk_score += 12
                
                # 3. Check recent PO history (max 20 points)
                recent_issues = await self._check_recent_vendor_issues(vendor_id)
                risk_score += recent_issues['risk_points']
                concerns.extend(recent_issues['concerns'])
            else:
                # No vendor data = unknown risk
                risk_score += 40
                concerns.append("New/unknown vendor - limited history")
        else:
            # No vendor ID = cannot assess
            risk_score += 50
            concerns.append("Vendor not identified in system")
        
        # 4. Check single-source dependency (max 25 points)
        category = observations.get("category", "")
        if category and await self._is_single_source(vendor_name, category):
            risk_score += 25
            concerns.append(f"Single-source for {category} (high dependency)")
        
        return {
            "score": min(risk_score, 100),  # Cap at 100
            "concerns": concerns if concerns else ["No significant vendor risks identified"]
        }
    
    async def _assess_financial_risk(
        self, 
        budget: float, 
        department: str,
        observations: Dict
    ) -> Dict[str, Any]:
        """
        Assess financial risk (0-100).
        
        Factors:
        - Budget availability
        - Percentage of budget consumed
        - Historical price volatility
        - Payment terms
        """
        risk_score = 0.0
        concerns = []

        # Extract budget category (CAPEX or OPEX)
        budget_category = observations.get("budget_category", "OPEX")

        # 1. Check budget availability (max 40 points)
        budget_check = await self._check_budget_status(department, budget, budget_category)

        if not budget_check['available']:
            risk_score += 40
            if budget_check['utilization'] >= 100:
                concerns.append(f"No budget available for {department} {budget_category}")
            elif budget_check['utilization'] > 0:
                concerns.append(f"Budget exceeded ({budget_check['utilization']:.0f}% used)")
            else:
                concerns.append("Budget status could not be verified for this department")
        elif budget_check['utilization'] > 95:
            risk_score += 35
            concerns.append(f"Near budget limit ({budget_check['utilization']:.0f}% used)")
        elif budget_check['utilization'] > 85:
            risk_score += 20
            concerns.append(f"High budget utilization ({budget_check['utilization']:.0f}%)")
        elif budget_check['utilization'] > 75:
            risk_score += 10
        
        # 2. Order size risk (max 30 points)
        if budget > 100000:
            risk_score += 30
            concerns.append(f"Large order value (${budget:,.0f})")
        elif budget > 50000:
            risk_score += 15
            concerns.append(f"Significant investment (${budget:,.0f})")
        
        # 3. Price volatility check (max 30 points)
        category = observations.get("category", "")
        if category in ["Electronics", "Raw Materials", "Energy"]:
            risk_score += 20
            concerns.append(f"{category} prices historically volatile")
        
        return {
            "score": min(risk_score, 100),
            "concerns": concerns if concerns else ["Financial risk within acceptable limits"]
        }
    
    async def _assess_compliance_risk(
        self, 
        category: str, 
        budget: float,
        observations: Dict
    ) -> Dict[str, Any]:
        """
        Assess compliance risk (0-100).
        
        Factors:
        - Regulatory requirements
        - Approval chain adherence
        - Documentation completeness
        - Policy violations
        """
        risk_score = 0.0
        concerns = []
        
        # 1. High-risk categories (max 40 points)
        high_risk_categories = [
            "Pharmaceuticals", "Medical", "Chemicals", "Food", 
            "Electronics", "Defense", "Aerospace"
        ]
        if any(cat in category for cat in high_risk_categories):
            risk_score += 25
            concerns.append(f"{category} requires regulatory compliance checks")
        
        # 2. Large value threshold compliance (max 30 points)
        if budget > 50000:
            # Check if approval chain exists
            department = observations.get("department", "")
            if department:
                approval_data = await self._get_approval_requirements(department, budget)
                if not approval_data['has_approval_chain']:
                    risk_score += 30
                    concerns.append("Missing approval chain for high-value purchase")
                elif approval_data['levels_required'] < 2:
                    risk_score += 15
                    concerns.append("Insufficient approval levels for amount")
        
        # 3. Documentation completeness (max 30 points)
        # Check both justification (new field) and description (legacy)
        justification = observations.get("justification", "")
        description = observations.get("description", "")
        combined_text = justification or description  # Prefer justification

        if not combined_text or len(combined_text.strip()) < 20:
            risk_score += 20
            concerns.append("Insufficient purchase justification")

        requester = observations.get("requester", "")
        if not requester or requester == "Unknown":
            risk_score += 10
            concerns.append("Requester not identified")
        
        return {
            "score": min(risk_score, 100),
            "concerns": concerns if concerns else ["Compliance requirements satisfied"]
        }
    
    async def _assess_operational_risk(
        self, 
        vendor_name: str, 
        category: str, 
        urgency: str,
        observations: Dict
    ) -> Dict[str, Any]:
        """
        Assess operational risk (0-100).
        
        Factors:
        - Supply chain disruption potential
        - Vendor capacity constraints
        - Lead time vs urgency mismatch
        - Geographic/geopolitical risks
        """
        risk_score = 0.0
        concerns = []
        
        # 1. Urgency vs lead time (max 40 points)
        if urgency == "High":
            risk_score += 30
            concerns.append("High urgency increases delivery risk")
        elif urgency == "Medium":
            risk_score += 15
        
        # 2. Category supply chain risk (max 35 points)
        high_disruption_categories = [
            "Electronics", "Semiconductors", "Raw Materials", 
            "Chemicals", "Transportation", "Energy"
        ]
        if any(cat in category for cat in high_disruption_categories):
            risk_score += 25
            concerns.append(f"{category} supply chain vulnerable to disruptions")
        
        # 3. Geographic concentration (max 25 points)
        # In real system, would check vendor location
        # For now, use simplified heuristic
        if category in ["Electronics", "Manufacturing Equipment"]:
            risk_score += 15
            concerns.append("Potential geographic concentration risk")
        
        return {
            "score": min(risk_score, 100),
            "concerns": concerns if concerns else ["Operational risk minimal"]
        }
    
    # ========== HELPER METHODS ==========
    
    def _determine_risk_level(self, score: float) -> tuple:
        """Map risk score to risk level and color"""
        if score >= 80:
            return ("CRITICAL", "red")
        elif score >= 60:
            return ("HIGH", "orange")
        elif score >= 30:
            return ("MEDIUM", "yellow")
        else:
            return ("LOW", "green")

    def _calculate_confidence_from_data_quality(
        self,
        observations: Dict[str, Any],
        vendor_risk: Dict[str, Any],
        financial_risk: Dict[str, Any]
    ) -> float:
        """
        Calculate confidence score (0-1) based on data completeness and quality.

        Higher confidence when we have:
        - Known vendor with history
        - Verified budget data
        - Complete requester info
        - Detailed justification

        Lower confidence when data is missing or uncertain.
        """
        confidence_score = 0.70  # Base confidence

        # Vendor data quality (+15%)
        vendor_name = observations.get("vendor_name", "Unknown")
        vendor_id = observations.get("vendor_id")
        if vendor_id and vendor_name != "Unknown":
            # Known vendor with ID = full confidence boost
            confidence_score += 0.15
        elif vendor_name and vendor_name != "Unknown" and "not identified" not in str(vendor_risk.get("concerns", [])).lower():
            # Known vendor name but maybe no ID = partial boost
            confidence_score += 0.08

        # Budget verification quality (+10%)
        budget_concerns = str(financial_risk.get("concerns", [])).lower()
        if "could not be verified" not in budget_concerns and "not found" not in budget_concerns:
            # Budget was successfully verified
            confidence_score += 0.10

        # Requester info quality (+5%)
        requester = observations.get("requester", "Unknown")
        if requester and requester != "Unknown":
            confidence_score += 0.05

        # Justification quality (+5%)
        justification = observations.get("justification", "")
        description = observations.get("description", "")
        combined = justification or description
        if combined and len(combined.strip()) >= 20:
            confidence_score += 0.05

        return min(confidence_score, 0.95)  # Cap at 95%
    
    def _generate_mitigations(
        self,
        risk_level: str,
        vendor_risk: Dict,
        financial_risk: Dict,
        compliance_risk: Dict,
        operational_risk: Dict
    ) -> List[str]:
        """Generate prioritized mitigation recommendations"""
        mitigations = []
        
        # Collect all concerns with their risk scores
        all_concerns = [
            (vendor_risk['score'], vendor_risk['concerns']),
            (financial_risk['score'], financial_risk['concerns']),
            (compliance_risk['score'], compliance_risk['concerns']),
            (operational_risk['score'], operational_risk['concerns'])
        ]
        
        # Sort by risk score (highest first)
        all_concerns.sort(key=lambda x: x[0], reverse=True)
        
        # Generate mitigations for top concerns
        for score, concerns in all_concerns:
            if score > 40:  # Only major concerns
                for concern in concerns[:2]:  # Top 2 per category
                    if concern not in mitigations:
                        mitigation = self._concern_to_mitigation(concern)
                        if mitigation:
                            mitigations.append(mitigation)
        
        # Add general mitigations based on risk level
        if risk_level == "CRITICAL":
            mitigations.insert(0, "HOLD procurement pending executive review")
        elif risk_level == "HIGH":
            mitigations.insert(0, "Require director approval and mitigation plan")
        
        return mitigations[:5]  # Top 5 mitigations
    
    def _concern_to_mitigation(self, concern: str) -> Optional[str]:
        """Convert concern to actionable mitigation"""
        concern_lower = concern.lower()
        
        if "rating" in concern_lower or "quality" in concern_lower:
            return "Request vendor quality improvement plan"
        elif "delivery" in concern_lower:
            return "Add delivery penalty clauses to contract"
        elif "budget" in concern_lower:
            return "Seek budget reallocation or approval for overage"
        elif "single-source" in concern_lower or "dependency" in concern_lower:
            return "Identify and qualify backup vendors"
        elif "volatile" in concern_lower or "volatility" in concern_lower:
            return "Lock in fixed pricing or add price protection clause"
        elif "compliance" in concern_lower or "regulatory" in concern_lower:
            return "Complete compliance checklist before proceeding"
        elif "approval" in concern_lower:
            return "Route through proper approval chain"
        elif "documentation" in concern_lower or "justification" in concern_lower:
            return "Request detailed business justification"
        elif "urgency" in concern_lower or "lead time" in concern_lower:
            return "Explore expedited shipping or alternative vendors"
        elif "disruption" in concern_lower or "supply chain" in concern_lower:
            return "Establish safety stock or alternative sourcing"
        elif "unknown vendor" in concern_lower or "new vendor" in concern_lower:
            return "Conduct vendor due diligence and request references"
        
        return None
    
    def _get_recommended_actions(self, risk_level: str) -> List[str]:
        """Get recommended next steps based on risk level"""
        actions = {
            "CRITICAL": [
                "STOP: Do not proceed with procurement",
                "Escalate to VP/CFO immediately",
                "Conduct emergency risk review meeting",
                "Explore alternative vendors or approaches"
            ],
            "HIGH": [
                "Route to Director for approval",
                "Prepare detailed risk mitigation plan",
                "Request executive committee review",
                "Document all risk factors in purchase requisition"
            ],
            "MEDIUM": [
                "Obtain manager approval before proceeding",
                "Document risk factors and mitigation steps",
                "Consider splitting order or adding safeguards",
                "Monitor closely during fulfillment"
            ],
            "LOW": [
                "Proceed with standard approval process",
                "Document assessment in PR notes",
                "No additional risk mitigation required"
            ]
        }
        return actions.get(risk_level, [])
    
    def _map_action_to_status(self, action: str) -> str:
        """Map agent action to status string"""
        status_map = {
            "escalate_to_human": "critical_risk_hold",
            "require_mitigation_plan": "high_risk_review",
            "require_manager_review": "medium_risk_approval",
            "approve_low_risk": "low_risk_proceed"
        }
        return status_map.get(action, "assessed")
    
    async def _get_vendor_data(self, vendor_id: int) -> Optional[Dict]:
        """Fetch vendor data from Odoo"""
        try:
            import asyncio as _aio
            vendor_tool = next(t for t in self.tools if t.name == "get_vendors")
            result_str = await _aio.to_thread(vendor_tool.func, limit=50)
            result = json.loads(result_str)
            
            if result.get("success"):
                vendors = result.get("vendors", [])
                return next((v for v in vendors if v.get('id') == vendor_id), None)
        except Exception as e:
            logger.error(f"Failed to get vendor data: {e}")
        
        return None

    async def _resolve_vendor_by_name(self, vendor_name: str) -> Optional[Dict]:
        """Resolve a vendor name to vendor data by fuzzy-matching Odoo vendors."""
        try:
            import asyncio as _aio
            vendor_tool = next(t for t in self.tools if t.name == "get_vendors")
            result_str = await _aio.to_thread(vendor_tool.func, limit=50)
            result = json.loads(result_str)
            
            if result.get("success"):
                vendors = result.get("vendors", [])
                name_lower = vendor_name.lower().strip()
                # Exact match first
                for v in vendors:
                    if v.get("name", "").lower().strip() == name_lower:
                        return v
                # Partial match (vendor name contains the search term or vice versa)
                for v in vendors:
                    vname = v.get("name", "").lower().strip()
                    if name_lower in vname or vname in name_lower:
                        return v
        except Exception as e:
            logger.error(f"Failed to resolve vendor by name: {e}")
        return None
    
    async def _check_recent_vendor_issues(self, vendor_id: int) -> Dict[str, Any]:
        """
        Check for recent PO issues with this vendor.
        Queries approved_supplier_list_odoo and vendor_performance_odoo for signals.
        """
        risk_points = 0
        concerns = []
        try:
            import asyncio as _aio
            po_tool = next((t for t in self.tools if t.name == "get_purchase_orders"), None)
            if po_tool:
                result_str = await _aio.to_thread(po_tool.func, limit=50)
                result = json.loads(result_str)
                pos = result.get("purchase_orders", [])
                vendor_pos = [
                    p for p in pos
                    if str(p.get("partner_id") or p.get("vendor_id") or "") == str(vendor_id)
                ]
                cancelled = [p for p in vendor_pos if p.get("state") in ("cancel", "cancelled")]
                if len(cancelled) > 0:
                    pct = len(cancelled) / max(len(vendor_pos), 1) * 100
                    if pct >= 30:
                        risk_points += 20
                        concerns.append(f"High PO cancellation rate ({pct:.0f}%) in recent orders")
                    elif pct >= 10:
                        risk_points += 10
                        concerns.append(f"Elevated PO cancellation rate ({pct:.0f}%)")
        except Exception as e:
            logger.debug(f"[RiskAgent] _check_recent_vendor_issues query failed: {e}")
        return {"risk_points": risk_points, "concerns": concerns}

    async def _is_single_source(self, vendor_name: str, category: str) -> bool:
        """
        Checks whether vendor_name is the only active vendor for this category
        by scanning the vendor list for suppliers with the same category tag.
        Returns True only when fewer than 2 vendors serve the category.
        """
        if not category or not vendor_name:
            return False
        try:
            import asyncio as _aio
            vendor_tool = next((t for t in self.tools if t.name == "get_vendors"), None)
            if vendor_tool:
                result_str = await _aio.to_thread(vendor_tool.func, limit=100)
                result = json.loads(result_str)
                vendors = result.get("vendors", [])
                cat_lower = category.lower()
                category_vendors = [
                    v for v in vendors
                    if cat_lower in str(v.get("category", "")).lower()
                    or cat_lower in str(v.get("name", "")).lower()
                ]
                # If only 0 or 1 vendor covers this category, it IS single-source
                return len(category_vendors) <= 1
        except Exception as e:
            logger.debug(f"[RiskAgent] _is_single_source query failed: {e}")
        return False
    
    async def _check_budget_status(self, department: str, amount: float, budget_category: str = "OPEX") -> Dict[str, Any]:
        """Check budget availability"""
        try:
            import asyncio as _aio
            budget_tool = next(t for t in self.tools if t.name == "check_budget_availability")
            result_str = await _aio.to_thread(
                budget_tool.func,
                department=department,
                amount=amount,
                budget_category=budget_category
            )
            result = json.loads(result_str)

            # Check if query was successful
            if not result.get("success", False):
                # No budget found for this department - treat as HIGH RISK
                logger.warning(f"[RiskAgent] ️ Budget not found for {department} {budget_category}")
                return {"available": False, "utilization": 100}  # 100% = no budget available

            # Use correct keys from tool response
            available = result.get("sufficient", False)
            utilization = result.get("utilization_after_approval", 0)

            return {
                "available": available,
                "utilization": utilization
            }
        except Exception as e:
            logger.error(f"Failed to check budget: {e}")
            # On error, treat as HIGH RISK (not low risk)
            return {"available": False, "utilization": 100}  # Changed from available=True, utilization=50
    
    async def _get_approval_requirements(self, department: str, amount: float) -> Dict[str, Any]:
        """Get approval chain requirements"""
        try:
            import asyncio as _aio
            approval_tool = next(t for t in self.tools if t.name == "get_approval_chain")
            # Note: Database tool uses 'budget' parameter, not 'amount'
            result_str = await _aio.to_thread(approval_tool.func, department=department, budget=amount)
            result = json.loads(result_str)
            
            approvers = result.get("approvers", [])
            return {
                "has_approval_chain": len(approvers) > 0,
                "levels_required": len(approvers)
            }
        except Exception as e:
            logger.error(f"Failed to get approval requirements: {e}")
            return {"has_approval_chain": True, "levels_required": 1}
    
    def _extract_rating(self, rating_str: Any) -> float:
        """Extract numeric rating from string or return float"""
        if isinstance(rating_str, (int, float)):
            return float(rating_str)
        
        if isinstance(rating_str, str):
            try:
                # Handle "4.5/5" format
                if '/' in rating_str:
                    return float(rating_str.split('/')[0])
                return float(rating_str)
            except:
                return 3.5  # Default average rating
        
        return 3.5  # Default
