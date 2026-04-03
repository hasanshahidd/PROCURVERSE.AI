"""
Contract Monitoring Agent
Sprint 4: Monitors contract expirations, renewals, and compliance

Features:
- Contract expiration tracking (30/60/90 day alerts)
- Renewal recommendations based on performance
- Contract compliance monitoring
- Spend analysis against contract terms
- Auto-triggers procurement for expiring contracts
"""

from typing import Dict, Any, List, Optional
import logging
import json
from datetime import datetime, timedelta

from backend.agents import BaseAgent, AgentDecision
from backend.agents.tools import create_odoo_tools, create_database_tools

logger = logging.getLogger(__name__)


class ContractMonitoringAgent(BaseAgent):
    """
    Monitors contracts for expiration, compliance, and renewal opportunities.
    
    Monitoring Dimensions:
    - Expiration Status: Days until contract expires
    - Spend vs Contract: Actual spend against contract limits
    - Compliance: Terms adherence, SLA compliance
    - Performance: Vendor performance under contract
    - Renewal Priority: Recommendations for renewal vs replacement
    
    Alert Thresholds:
    - 90 days: Early warning - start renewal planning
    - 60 days: Action required - initiate renewal process
    - 30 days: Urgent - expedite renewal or find replacement
    - 7 days: Critical - emergency procurement required
    """
    
    def __init__(self):
        # Get both Odoo and database tools
        odoo_tools = create_odoo_tools()
        db_tools = create_database_tools()
        
        # Combine relevant tools for contract monitoring
        contract_tools = [
            tool for tool in odoo_tools + db_tools
            if tool.name in [
                'get_vendors', 'get_purchase_orders', 'get_products',
                'check_budget_availability', 'get_department_budget_status'
            ]
        ]
        
        super().__init__(
            name="ContractMonitoringAgent",
            description=(
                "Monitors contracts for expiration, compliance, and renewal. "
                "Provides alerts at 90/60/30/7 day thresholds. "
                "Analyzes vendor performance and recommends renewal or replacement."
            ),
            tools=contract_tools,
            temperature=0.1  # Low temperature for consistent monitoring
        )
        
        logger.info("Contract Monitoring Agent initialized")
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute contract monitoring"""
        return await self.execute_with_recovery(input_data)
    
    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Gather contract data and monitoring context"""
        observations = await super().observe(context)
        
        # Extract contract data
        contract_data = context.get("contract_data", context.get("pr_data", {}))
        
        observations.update({
            "contract_id": contract_data.get("contract_id", "Unknown"),
            "contract_number": contract_data.get("contract_number", "Unknown"),
            "vendor_name": contract_data.get("vendor_name", contract_data.get("supplier_name", "Unknown")),
            "vendor_id": contract_data.get("vendor_id", contract_data.get("supplier_id")),
            "start_date": contract_data.get("start_date", contract_data.get("contract_start")),
            "end_date": contract_data.get("end_date", contract_data.get("contract_end")),
            "contract_value": contract_data.get("contract_value", contract_data.get("total_amount", 0)),
            "spent_amount": contract_data.get("spent_amount", 0),
            "department": contract_data.get("department", "Unknown"),
            "contract_type": contract_data.get("contract_type", "General"),
            "auto_renew": contract_data.get("auto_renew", False),
            "sla_terms": contract_data.get("sla_terms", {}),
            "description": contract_data.get("description", "")
        })
        
        # Calculate days until expiration
        if observations.get("end_date"):
            try:
                raw_end = observations["end_date"]
                if isinstance(raw_end, str):
                    # Try multiple date formats encountered in real ERP exports
                    _DATE_FORMATS = [
                        "%Y-%m-%d",
                        "%d/%m/%Y",
                        "%m/%d/%Y",
                        "%d-%m-%Y",
                        "%Y/%m/%d",
                        "%d %b %Y",
                        "%d %B %Y",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%dT%H:%M:%S.%f",
                    ]
                    end_date = None
                    for fmt in _DATE_FORMATS:
                        try:
                            end_date = datetime.strptime(raw_end.strip(), fmt)
                            break
                        except ValueError:
                            continue
                    if end_date is None:
                        raise ValueError(f"Unrecognised date format: {raw_end!r}")
                else:
                    end_date = raw_end

                today = datetime.now()
                days_remaining = (end_date - today).days
                observations["days_until_expiration"] = days_remaining
                observations["expiration_status"] = self._get_expiration_status(days_remaining)
            except Exception as e:
                logger.warning(f"[ContractAgent] Could not parse end_date: {e}")
                observations["days_until_expiration"] = None
                observations["expiration_status"] = "unknown"
        else:
            observations["days_until_expiration"] = None
            observations["expiration_status"] = "no_end_date"
        
        # Calculate spend percentage
        if observations["contract_value"] > 0:
            spend_pct = (observations["spent_amount"] / observations["contract_value"]) * 100
            observations["spend_percentage"] = round(spend_pct, 2)
        else:
            observations["spend_percentage"] = 0
        
        logger.info(
            f"[ContractAgent] Monitoring {observations['contract_number']} - "
            f"Vendor: {observations['vendor_name']}, "
            f"Expires in: {observations.get('days_until_expiration', 'N/A')} days, "
            f"Spend: {observations['spend_percentage']}%"
        )
        
        return observations
    
    def _get_expiration_status(self, days_remaining: int) -> str:
        """Determine expiration status based on days remaining"""
        if days_remaining <= 0:
            return "expired"
        elif days_remaining <= 7:
            return "critical"
        elif days_remaining <= 30:
            return "urgent"
        elif days_remaining <= 60:
            return "action_required"
        elif days_remaining <= 90:
            return "early_warning"
        else:
            return "active"
    
    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Decide on contract actions based on monitoring data"""
        
        expiration_status = observations.get("expiration_status", "unknown")
        days_remaining = observations.get("days_until_expiration")
        spend_pct = observations.get("spend_percentage", 0)
        auto_renew = observations.get("auto_renew", False)
        
        # Decision logic based on expiration status
        if expiration_status == "expired":
            action = "emergency_procurement"
            reasoning = (
                f"Contract {observations['contract_number']} has EXPIRED. "
                f"Immediate action required to avoid service disruption. "
                f"Recommend emergency procurement process."
            )
            confidence = 0.95
            alternatives = ["negotiate_extension", "find_alternative_vendor"]
        
        elif expiration_status == "critical":
            action = "urgent_renewal"
            reasoning = (
                f"Contract expires in {days_remaining} days (CRITICAL). "
                f"Insufficient time for normal procurement. "
                f"Recommend immediate renewal or emergency sourcing."
            )
            confidence = 0.90
            alternatives = ["emergency_extension", "expedited_rfp"]
        
        elif expiration_status == "urgent":
            action = "expedite_renewal"
            reasoning = (
                f"Contract expires in {days_remaining} days (URGENT). "
                f"Limited time for renewal process. "
                f"Recommend expedited renewal procedures."
            )
            confidence = 0.85
            alternatives = ["standard_renewal", "negotiate_extension"]
        
        elif expiration_status == "action_required":
            if auto_renew:
                action = "verify_auto_renewal"
                reasoning = (
                    f"Contract set for auto-renewal in {days_remaining} days. "
                    f"Verify terms are still favorable. "
                    f"Current spend: {spend_pct:.1f}% of contract value."
                )
                confidence = 0.80
            else:
                action = "initiate_renewal"
                reasoning = (
                    f"Contract expires in {days_remaining} days. "
                    f"Initiate renewal process now to avoid disruption. "
                    f"Current spend: {spend_pct:.1f}% of contract value."
                )
                confidence = 0.85
            alternatives = ["renegotiate_terms", "market_review", "extend_current"]
        
        elif expiration_status == "early_warning":
            action = "plan_renewal"
            reasoning = (
                f"Contract expires in {days_remaining} days. "
                f"Begin renewal planning and vendor performance review. "
                f"Current spend: {spend_pct:.1f}% of contract value."
            )
            confidence = 0.75
            alternatives = ["continue_monitoring", "market_scan", "performance_review"]
        
        elif expiration_status == "active":
            action = "monitor_ongoing"
            reasoning = (
                f"Contract active with {days_remaining} days remaining. "
                f"Continue monitoring spend and performance. "
                f"Current spend: {spend_pct:.1f}% of contract value."
            )
            confidence = 0.70
            alternatives = ["no_action", "quarterly_review"]
        
        else:  # unknown or no_end_date
            action = "update_contract_data"
            reasoning = (
                f"Contract {observations['contract_number']} missing critical data. "
                f"Update contract end date and terms in system."
            )
            confidence = 0.60
            alternatives = ["manual_review", "procurement_audit"]
        
        # Additional spend analysis
        if spend_pct > 95:
            reasoning += f" ⚠️ WARNING: Spend at {spend_pct:.1f}% - near contract limit!"
            confidence = max(confidence - 0.1, 0.5)
            if action == "monitor_ongoing":
                action = "review_overspend_risk"
        elif spend_pct < 20 and expiration_status in ["expired", "critical", "urgent"]:
            reasoning += f" Note: Low utilization ({spend_pct:.1f}%) - consider not renewing."
        
        decision = AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context=observations,
            alternatives=alternatives
        )
        
        logger.info(
            f"[ContractAgent] Decision: {action} "
            f"(Confidence: {confidence:.2f}, Status: {expiration_status})"
        )
        
        return decision
    
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Execute contract monitoring actions"""
        action = decision.action
        context = decision.context
        
        result = {
            "agent": self.name,
            "action": action,
            "contract_number": context.get("contract_number", "Unknown"),
            "vendor_name": context.get("vendor_name", "Unknown"),
            "expiration_status": context.get("expiration_status", "unknown"),
            "days_until_expiration": context.get("days_until_expiration"),
            "spend_percentage": context.get("spend_percentage", 0),
            "timestamp": datetime.now().isoformat()
        }
        
        # Action-specific execution
        if action == "emergency_procurement":
            result.update({
                "priority": "CRITICAL",
                "recommended_actions": [
                    "Activate emergency procurement procedures",
                    "Contact vendor for immediate extension",
                    "Notify department head of contract lapse",
                    "Identify alternative vendors immediately",
                    "Escalate to procurement director"
                ],
                "next_steps": [
                    "Emergency meeting with vendor",
                    "Prepare emergency PO",
                    "Execute contingency plan"
                ]
            })
        
        elif action == "urgent_renewal":
            result.update({
                "priority": "HIGH",
                "recommended_actions": [
                    "Contact vendor immediately for renewal",
                    "Expedite internal approval process",
                    "Prepare renewal documentation",
                    f"Target completion: within {context.get('days_until_expiration', 7)} days",
                    "Notify stakeholders of timeline"
                ],
                "next_steps": [
                    "Send renewal request to vendor",
                    "Fast-track approval routing",
                    "Prepare alternative options"
                ]
            })
        
        elif action == "expedite_renewal":
            result.update({
                "priority": "HIGH",
                "recommended_actions": [
                    "Initiate expedited renewal process",
                    "Request vendor proposal within 7 days",
                    "Conduct abbreviated performance review",
                    "Fast-track budget approval",
                    "Prepare contract documents"
                ],
                "next_steps": [
                    "Vendor outreach",
                    "Performance summary review",
                    "Route for approval"
                ]
            })
        
        elif action == "initiate_renewal":
            result.update({
                "priority": "MEDIUM",
                "recommended_actions": [
                    "Begin formal renewal process",
                    "Conduct vendor performance review",
                    "Compare market pricing",
                    "Engage stakeholders for requirements",
                    "Prepare RFP if needed"
                ],
                "next_steps": [
                    "Performance analysis",
                    "Market research",
                    "Stakeholder consultation"
                ]
            })
        
        elif action == "verify_auto_renewal":
            result.update({
                "priority": "MEDIUM",
                "recommended_actions": [
                    "Review auto-renewal terms",
                    "Verify pricing remains competitive",
                    "Check vendor performance metrics",
                    "Confirm budget availability",
                    "Notify stakeholders of pending renewal"
                ],
                "next_steps": [
                    "Terms review",
                    "Pricing comparison",
                    "Stakeholder notification"
                ]
            })
        
        elif action == "plan_renewal":
            result.update({
                "priority": "LOW",
                "recommended_actions": [
                    "Begin renewal planning activities",
                    "Schedule vendor performance review",
                    "Conduct market scan for alternatives",
                    "Gather stakeholder requirements",
                    "Review contract utilization"
                ],
                "next_steps": [
                    "Performance review meeting",
                    "Market analysis",
                    "Requirements gathering"
                ]
            })
        
        elif action == "monitor_ongoing":
            result.update({
                "priority": "LOW",
                "recommended_actions": [
                    "Continue routine monitoring",
                    "Track spend against contract value",
                    "Monitor vendor performance",
                    "Quarterly review scheduled"
                ],
                "next_steps": [
                    "No immediate action required",
                    "Continue monitoring"
                ]
            })
        
        elif action == "review_overspend_risk":
            result.update({
                "priority": "MEDIUM",
                "recommended_actions": [
                    f"Spend at {context['spend_percentage']:.1f}% of contract value",
                    "Review remaining contract capacity",
                    "Consider amendment if additional spend needed",
                    "Monitor orders to avoid overspend",
                    "Plan for contract expansion or new agreement"
                ],
                "next_steps": [
                    "Spend analysis",
                    "Contract amendment review",
                    "Budget planning"
                ]
            })
        
        elif action == "update_contract_data":
            result.update({
                "priority": "HIGH",
                "recommended_actions": [
                    "Update contract end date in system",
                    "Complete missing contract data fields",
                    "Verify contract terms with procurement",
                    "Upload contract documents",
                    "Ensure data accuracy for monitoring"
                ],
                "next_steps": [
                    "Data entry review",
                    "Document upload",
                    "Procurement verification"
                ]
            })
        
        else:
            result.update({
                "priority": "LOW",
                "recommended_actions": [
                    f"Action: {action}",
                    "Review contract status",
                    "Follow standard procedures"
                ],
                "next_steps": ["Standard processing"]
            })
        
        # Add alert level
        result["alert_level"] = self._get_alert_level(
            context.get("expiration_status", "unknown"),
            context.get("spend_percentage", 0)
        )
        
        # Log action
        await self._log_action(
            action_type=action,
            input_data=context,
            output_data=result,
            success=True
        )
        
        logger.info(
            f"[ContractAgent] Action '{action}' completed - "
            f"Priority: {result['priority']}, Alert: {result['alert_level']}"
        )
        
        return result
    
    def _get_alert_level(self, expiration_status: str, spend_pct: float) -> str:
        """Determine alert level based on status and spend"""
        if expiration_status == "expired":
            return "CRITICAL"
        elif expiration_status == "critical" or spend_pct > 100:
            return "URGENT"
        elif expiration_status == "urgent" or spend_pct > 95:
            return "HIGH"
        elif expiration_status == "action_required" or spend_pct > 90:
            return "MEDIUM"
        elif expiration_status == "early_warning":
            return "LOW"
        else:
            return "INFO"
    
    async def learn(self, result: Dict[str, Any]) -> None:
        """Learn from contract monitoring outcomes"""
        await super().learn(result)
        
        # Extract learning patterns
        action = result.get("action", "unknown")
        expiration_status = result.get("expiration_status", "unknown")
        spend_pct = result.get("spend_percentage", 0)
        
        logger.info(
            f"[ContractAgent] Learned from {action}: "
            f"Status={expiration_status}, Spend={spend_pct:.1f}%"
        )
