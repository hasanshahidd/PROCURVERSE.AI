"""
Budget Verification Agent
Sprint 2 implementation: Verifies budget availability before PR approval
"""

from typing import Dict, Any
import logging
import json

try:
    from langchain_core.tools import Tool
except ImportError:
    try:
        from langchain.tools import Tool
    except ImportError:
        Tool = None  # graceful fallback — agent still runs without LangChain Tool class

from backend.agents import BaseAgent, AgentDecision
from backend.agents.tools import create_database_tools

logger = logging.getLogger(__name__)


class BudgetVerificationAgent(BaseAgent):
    """
    Verifies budget availability before PR approval.
    
    Features:
    - Real-time budget calculation (allocated - spent - committed)
    - Threshold alerts (80%, 90%, 95%)
    - Automatic budget blocking if insufficient
    - Updates committed budget after approval
    """
    
    def __init__(self):
        # Get database tools
        db_tools = create_database_tools()
        
        # Filter tools relevant to budget verification
        budget_tools = [
            tool for tool in db_tools
            if tool.name in [
                'check_budget_availability',
                'update_committed_budget',
                'get_department_budget_status'
            ]
        ]
        
        super().__init__(
            name="BudgetVerificationAgent",
            description=(
                "Verifies budget availability for purchase requisitions. "
                "Checks allocated, spent, and committed budgets. "
                "Sends alerts when thresholds are exceeded (80%, 90%, 95%)."
            ),
            tools=budget_tools,
            temperature=0.1  # Low temperature for financial decisions
        )
        
        logger.info("Budget Verification Agent initialized")
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute budget verification"""
        return await self.execute_with_recovery(input_data)
    
    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Gather PR details and current budget status"""
        observations = await super().observe(context)
        
        # Extract PR data
        pr_data = context.get("pr_data", {})
        
        budget_requested = pr_data.get("budget", 0) or 0
        observations.update({
            "pr_number": pr_data.get("pr_number"),
            "department": pr_data.get("department"),
            "budget_requested": budget_requested,
            "budget_category": pr_data.get("budget_category", "OPEX"),
            "priority": pr_data.get("priority_level", "Medium"),
            "requester": pr_data.get("requester_name", "Unknown"),
            "is_status_check": (budget_requested == 0),
        })
        
        logger.info(
            f"[BudgetAgent] Verifying {observations['budget_requested']} "
            f"for {observations['department']}"
        )
        
        return observations
    
    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Decide if budget is sufficient and what action to take"""
        
        department = observations.get("department")
        budget_category = observations.get("budget_category")
        amount = observations.get("budget_requested", 0)
        is_status_check = observations.get("is_status_check", False)

        # Pure status inquiry (no amount specified) → fetch full breakdown, skip commit
        if is_status_check:
            logger.info(f"[BudgetAgent] 📊 Status-only query for {department} — using get_department_budget_status")
            status_data = await self._get_department_status(department)
            return AgentDecision(
                action="report_status",
                reasoning=f"Reporting current budget status for {department}.",
                confidence=0.95,
                context={**observations, "status_data": status_data},
                alternatives=[]
            )

        # Check budget availability using tool
        logger.info(f"[BudgetAgent] 💰 Checking budget: {department}/{budget_category} for ${amount:,.2f}")
        budget_check_result = await self._check_budget(
            department,
            budget_category,
            amount
        )
        logger.info(f"[BudgetAgent] 📊 Budget check result: {budget_check_result.get('sufficient')} (Current: ${budget_check_result.get('current_budget', 0):,.2f}, After: {budget_check_result.get('utilization_after_approval', 0):.1f}%)")
        
        if budget_check_result["success"]:
            is_sufficient = budget_check_result.get("sufficient", False)
            utilization = budget_check_result.get("utilization_after_approval", 0)
            
            if is_sufficient:
                # Budget available
                logger.debug(f"[BudgetAgent] ✅ Budget sufficient, analyzing utilization: {utilization:.1f}%")
                if utilization >= 95:
                    action = "approve_with_critical_alert"
                    confidence = 0.7
                    reasoning = (
                        f"Budget available but utilization will reach {utilization}%. "
                        "Critical threshold exceeded."
                    )
                    logger.warning(f"[BudgetAgent] 🚨 CRITICAL: Utilization will be {utilization:.1f}%")
                elif utilization >= 90:
                    action = "approve_with_high_alert"
                    confidence = 0.8
                    reasoning = (
                        f"Budget available but utilization will reach {utilization}%. "
                        "High threshold exceeded."
                    )
                elif utilization >= 80:
                    action = "approve_with_warning"
                    confidence = 0.9
                    reasoning = (
                        f"Budget available. Utilization will be {utilization}%. "
                        "Warning threshold exceeded."
                    )
                else:
                    action = "approve"
                    confidence = 0.95
                    reasoning = f"Budget available. Utilization: {utilization}%."
                    logger.info(f"[BudgetAgent] ✅ Approved: Utilization OK at {utilization:.1f}%")
                
                alternatives = ["update_committed_budget"]
            else:
                # Insufficient budget
                action = "reject_insufficient_budget"
                confidence = 0.95
                reasoning = (
                    f"Insufficient budget. Available: "
                    f"{budget_check_result.get('available_budget', 0)}, "
                    f"Requested: {amount}, "
                    f"Shortfall: {budget_check_result.get('shortfall', 0)}"
                )
                alternatives = ["escalate_to_cfo", "request_budget_increase"]
        else:
            # Error checking budget
            action = "error_budget_check"
            confidence = 0.3
            reasoning = f"Failed to check budget: {budget_check_result.get('error')}"
            alternatives = ["retry_budget_check", "manual_verification"]
        
        decision = AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context=observations,
            alternatives=alternatives
        )
        
        logger.info(
            f"[BudgetAgent] Decision: {action} (confidence: {confidence:.2f})"
        )
        
        return decision
    
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Execute the budget verification decision"""
        
        action = decision.action
        context = decision.context
        
        department = context.get("department")
        budget_category = context.get("budget_category")
        amount = context.get("budget_requested", 0)
        input_context = context.get("input_context", {})
        # Default to False: only commit budget when the PR workflow explicitly requests it.
        # Standalone "check budget" queries must NEVER mutate committed_budget.
        reserve_budget = bool(input_context.get("reserve_budget", False))
        
        if action.startswith("approve"):
            update_result = None
            if reserve_budget:
                # Reserve budget only when workflow explicitly requests commitment.
                update_result = await self._update_committed_budget(
                    department,
                    budget_category,
                    amount
                )
            
            return {
                "status": "approved",
                "budget_verified": True,
                "department": department,
                "action": action,
                "reasoning": decision.reasoning,
                "budget_update": update_result,
                "budget_reserved": reserve_budget,
                "alert_level": self._get_alert_level(action)
            }
        
        elif action == "reject_insufficient_budget":
            return {
                "status": "rejected",
                "budget_verified": False,
                "department": department,
                "reason": decision.reasoning,
                "alternatives": decision.alternatives
            }
        
        elif action == "report_status":
            status_data = context.get("status_data", {})
            return {
                "status": "budget_status",
                "budget_verified": True,
                "department": department,
                "budget_status_report": status_data,
                "reasoning": decision.reasoning,
            }

        elif action == "error_budget_check":
            return {
                "status": "error",
                "budget_verified": False,
                "error": decision.reasoning,
                "requires_manual_review": True
            }
        
        else:
            return {
                "status": "unknown_action",
                "action": action,
                "message": "Unhandled action type"
            }
    
    async def _check_budget(
        self,
        department: str,
        budget_category: str,
        amount: float
    ) -> Dict[str, Any]:
        """Helper to check budget availability"""
        try:
            # Find the budget check tool
            budget_tool = next(
                (t for t in self.tools if t.name == "check_budget_availability"),
                None
            )
            
            if not budget_tool:
                return {"success": False, "error": "Budget check tool not found"}
            
            # Call the tool
            result_json = budget_tool.func(department, budget_category, amount)
            result = json.loads(result_json)
            
            return result
        except Exception as e:
            logger.error(f"Budget check failed: {e}")
            return {"success": False, "error": str(e)}

    async def _get_department_status(self, department: str) -> Dict[str, Any]:
        """Helper to fetch full budget status for all categories in a department"""
        try:
            status_tool = next(
                (t for t in self.tools if t.name == "get_department_budget_status"),
                None
            )
            if not status_tool:
                return {"success": False, "error": "Budget status tool not found"}
            result_json = status_tool.func(department)
            return json.loads(result_json)
        except Exception as e:
            logger.error(f"Budget status fetch failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def _update_committed_budget(
        self,
        department: str,
        budget_category: str,
        amount: float
    ) -> Dict[str, Any]:
        """Helper to update committed budget"""
        try:
            # Find the update tool
            update_tool = next(
                (t for t in self.tools if t.name == "update_committed_budget"),
                None
            )
            
            if not update_tool:
                return {"success": False, "error": "Update tool not found"}
            
            # Call the tool
            result_json = update_tool.func(department, budget_category, amount)
            result = json.loads(result_json)
            
            return result
        except Exception as e:
            logger.error(f"Budget update failed: {e}")
            return {"success": False, "error": str(e)}
    
    def _get_alert_level(self, action: str) -> str:
        """Determine alert level from action"""
        if "critical" in action:
            return "critical"
        elif "high" in action:
            return "high"
        elif "warning" in action:
            return "warning"
        else:
            return "none"
