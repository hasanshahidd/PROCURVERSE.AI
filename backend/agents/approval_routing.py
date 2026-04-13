"""
Approval Routing Agent
Sprint 2 implementation: Routes purchase requisitions through multi-level approval chains

UAT-003 fix: _create_workflow_in_database() now uses the adapter interface exclusively.
  No hardcoded psycopg2, no inline ALTER TABLE DDL.
  Adapter methods used:
    adapter.get_approval_workflow()   → check for duplicate
    adapter.create_approval_workflow() → pr_approval_workflows row
    adapter.create_approval_step()     → pr_approval_steps rows
    adapter.log_agent_action()         → agent_actions audit
"""

from typing import Dict, Any, List
import logging
import json
from datetime import datetime

from backend.agents import BaseAgent, AgentDecision
from backend.agents.tools import create_approval_routing_tools
from backend.services import hybrid_query
from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)


class ApprovalRoutingAgent(BaseAgent):
    """
    Routes purchase requisitions through appropriate approval chains.
    
    Features:
    - Multi-level approval routing (Manager → Director → VP)
    - Department-specific approval chains
    - Amount-based escalation logic
    - Automatic approver assignment based on budget thresholds
    - Tracks approval status and escalates when needed
    """
    
    def __init__(self):
        # Get approval routing tools
        approval_tools = create_approval_routing_tools()
        
        super().__init__(
            name="ApprovalRoutingAgent",
            description=(
                "Routes purchase requisitions through multi-level approval chains. "
                "Assigns approvers based on department and amount thresholds. "
                "Handles escalation to higher approval levels when needed."
            ),
            tools=approval_tools,
            temperature=0.0  # Zero temperature for deterministic routing
        )
        
        logger.info("Approval Routing Agent initialized")
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute approval routing"""
        return await self.execute_with_recovery(input_data)
    
    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Gather PR details and approval requirements"""
        observations = await super().observe(context)
        
        # Extract PR data
        pr_data = context.get("pr_data", {})
        
        pr_number = pr_data.get("pr_number", "Unknown")
        # If no PR number exists, run routing as analysis-only.
        # Do not auto-generate synthetic PR ids because it implies a real workflow was created.
        has_real_pr = bool(pr_number and pr_number != "Unknown")
        if not has_real_pr:
            pr_number = None
            logger.info("[ApprovalAgent] No PR number provided - running approval routing in analysis-only mode")
        
        observations.update({
            "pr_number": pr_number,
            "analysis_only": not has_real_pr,
            "department": pr_data.get("department", "Unknown"),
            "amount": pr_data.get("budget", 0),
            "requester": pr_data.get("requester_name", "Chat User"),
            "raw_pr_data": pr_data,
            "priority": pr_data.get("urgency", pr_data.get("priority_level", "Medium")),
            "description": pr_data.get("description", "No description"),
            "current_status": pr_data.get("status", "pending")
        })
        
        logger.info(
            f"[ApprovalAgent] Routing PR {observations['pr_number'] or 'N/A (analysis-only)'} "
            f"from {observations['department']} (${observations['amount']:,.2f})"
        )
        
        return observations
    
    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """Decide approval routing and required levels"""
        
        department = observations.get("department")
        amount = observations.get("amount", 0)
        pr_number = observations.get("pr_number")
        
        # Get approval chain for this department and amount
        logger.info(f"[ApprovalAgent] Fetching approval chain: {department} @ ${amount:,.2f}")
        approval_chain = await self._get_approval_chain(department, amount)
        logger.info(f"[ApprovalAgent] Chain lookup result: {approval_chain.get('success')} - {len(approval_chain.get('approvers', []))} levels")
        
        if not approval_chain["success"]:
            # No approval chain configured - escalate to human
            return AgentDecision(
                action="escalate_to_human",
                reasoning=f"No approval chain configured for {department} department",
                confidence=0.0,
                context={
                    "error": approval_chain.get("error"),
                    "department": department,
                    "amount": amount,
                    "recommendation": "Configure approval chain in database"
                }
            )
        
        approvers = approval_chain.get("approvers", [])
        required_levels = len(approvers)
        
        # Determine routing action based on amount and approval levels
        if amount < 10000:
            # Low amount - single level approval
            action = "route_to_manager"
            confidence = 1.0
            reasoning = f"Amount ${amount:,.2f} requires manager approval only"
        elif amount < 50000:
            # Medium amount - manager + director
            action = "route_to_director"
            confidence = 0.95
            reasoning = f"Amount ${amount:,.2f} requires director approval (2 levels)"
        else:
            # High amount - all levels including VP
            action = "route_to_vp"
            confidence = 0.90
            reasoning = f"Amount ${amount:,.2f} requires VP approval (3 levels)"
        
        logger.info(f"[ApprovalAgent] Decision: {action} (confidence: {confidence})")
        
        return AgentDecision(
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            context={
                "pr_number": pr_number,
                "analysis_only": observations.get("analysis_only", False),
                "department": department,
                "amount": amount,
                "requester": observations.get("requester", "Chat User"),
                "raw_pr_data": observations.get("raw_pr_data", {}),
                "approvers": approvers,
                "required_levels": required_levels,
                "alternatives": [
                    {
                        "action": "auto_approve",
                        "condition": "If amount < $1000 and requester has authority"
                    },
                    {
                        "action": "reject",
                        "condition": "If department budget insufficient"
                    }
                ]
            }
        )
    
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Execute the approval routing action"""
        action = decision.action
        context = decision.context
        
        pr_number = context.get("pr_number")
        analysis_only = bool(context.get("analysis_only", False))
        department = context.get("department")
        amount = context.get("amount", 0)
        approvers = context.get("approvers", [])

        logger.info(
            f"[ApprovalAgent] Execute action={action} | analysis_only={analysis_only} | "
            f"pr_number={pr_number} | department={department} | amount={amount}"
        )
        
        if action == "escalate_to_human":
            return {
                "success": True,
                "status": "escalated",
                "message": decision.reasoning,
                "recommendation": context.get("recommendation")
            }
        
        # Route to appropriate approval level
        if action in ["route_to_manager", "route_to_director", "route_to_vp"]:
            # Find the first approver at required level
            level_map = {
                "route_to_manager": 1,
                "route_to_director": 2,
                "route_to_vp": 3
            }
            
            required_level = level_map[action]
            assigned_approvers = [
                a for a in approvers 
                if a.get("approval_level") <= required_level
            ]
            
            if not assigned_approvers:
                return {
                    "success": False,
                    "status": "error",
                    "message": f"No approvers found at required level {required_level}"
                }

            # Analysis-only mode: provide routing recommendation without creating DB workflow entries.
            if analysis_only:
                logger.info(
                    f"[ApprovalAgent] Analysis-only result: {len(assigned_approvers)} approver(s) required "
                    f"for department={department}, amount={amount}"
                )
                return {
                    "success": True,
                    "status": "completed",
                    "pr_number": None,
                    "action": action,
                    "assigned_approvers": assigned_approvers,
                    "required_level": required_level,
                    "workflow_id": None,
                    "analysis_only": True,
                    "message": f"Approval route analyzed: {len(assigned_approvers)} approver(s) required. No PR/workflow created."
                }
            
            # Create workflow in database
            workflow_created = await self._create_workflow_in_database(
                pr_number=pr_number,
                department=department,
                amount=amount,
                approvers=assigned_approvers,
                decision=decision
            )

            logger.info(
                f"[ApprovalAgent] Workflow creation result for {pr_number}: "
                f"success={workflow_created.get('success')} workflow_id={workflow_created.get('workflow_id')}"
            )
            
            if not workflow_created["success"]:
                logger.error(f"Failed to create workflow: {workflow_created.get('error')}")
                return {
                    "success": True,
                    "status": "completed",
                    "pr_number": pr_number,
                    "action": action,
                    "assigned_approvers": assigned_approvers,
                    "required_level": required_level,
                    "workflow_id": None,
                    "analysis_only": True,
                    "message": "Approval route analyzed, but workflow record was not created."
                }
            
            # Log action
            await self._log_action(
                action_type="approval_routing",
                input_data=context,
                output_data={
                    "pr_number": pr_number,
                    "assigned_approvers": assigned_approvers,
                    "approval_level": required_level,
                    "workflow_created": workflow_created["success"]
                },
                success=True,
                execution_time_ms=50
            )

            result = {
                "success": True,
                "status": "routed",
                "pr_number": pr_number,
                "action": action,
                "assigned_approvers": assigned_approvers,
                "required_level": required_level,
                "workflow_id": workflow_created.get("workflow_id"),
                "message": f"PR routed to {len(assigned_approvers)} approver(s)"
            }

            # Send Slack notification (fire-and-forget)
            try:
                from backend.services.slack_service import send_approval_request
                import asyncio
                asyncio.create_task(asyncio.to_thread(
                    send_approval_request,
                    {
                        "pr_number": result.get("pr_number", ""),
                        "description": context.get("raw_pr_data", {}).get("description", ""),
                        "budget": context.get("amount", 0),
                        "department": context.get("department", ""),
                        "requester": context.get("requester", ""),
                        "priority": context.get("raw_pr_data", {}).get(
                            "urgency",
                            context.get("raw_pr_data", {}).get("priority_level", "medium")
                        ),
                    }
                ))
            except Exception as slack_err:
                logger.warning(f"Slack notification failed (non-fatal): {slack_err}")

            # Fire-and-forget email notification
            try:
                from backend.services.email_service import send_approval_request_email
                import asyncio
                # Get approver email from the routing decision
                approver_email = decision.context.get("approver_email", "")
                if not approver_email and assigned_approvers:
                    approver_email = assigned_approvers[0].get("approver_email", "")
                if approver_email:
                    approver_name = (
                        decision.context.get("approver_name")
                        or (assigned_approvers[0].get("approver_name", "Approver") if assigned_approvers else "Approver")
                    )
                    asyncio.create_task(asyncio.to_thread(
                        send_approval_request_email,
                        approver_email,
                        approver_name,
                        {
                            "pr_number": pr_number,
                            "description": context.get("raw_pr_data", {}).get("description", ""),
                            "budget": amount,
                            "department": department,
                            "requester": context.get("requester", ""),
                            "priority": context.get("raw_pr_data", {}).get(
                                "urgency",
                                context.get("raw_pr_data", {}).get("priority_level", "medium")
                            ),
                        },
                    ))
            except Exception as e:
                logger.warning(f"Email notification failed (non-fatal): {e}")

            return result
        
        return {
            "success": False,
            "status": "unknown_action",
            "message": f"Unknown action: {action}"
        }
    
    async def _create_workflow_in_database(
        self,
        pr_number: str,
        department: str,
        amount: float,
        approvers: List[Dict[str, Any]],
        decision: AgentDecision
    ) -> Dict[str, Any]:
        """
        Create approval workflow record using adapter interface only.
        UAT-003: zero hardcoded psycopg2 / zero inline DDL.

        Adapter calls:
          get_approval_workflow()    → duplicate check
          create_approval_workflow() → header row
          create_approval_step()     → one row per approver level
        """
        try:
            adapter = get_adapter()
            logger.info("[ApprovalAgent] Creating workflow — PR: %s, dept: %s, amount: %.2f",
                        pr_number, department, amount)

            # ── Duplicate check ───────────────────────────────────────────────
            existing = adapter.get_approval_workflow(pr_number)
            if existing:
                logger.warning("[ApprovalAgent] Workflow for %s already exists — skipping.", pr_number)
                return {"success": True, "workflow_id": pr_number,
                        "message": "Workflow already exists"}

            # ── Build request payload ─────────────────────────────────────────
            raw_pr_data   = decision.context.get("raw_pr_data", {}) or {}
            requester_name = (
                decision.context.get("requester")
                or raw_pr_data.get("requester_name")
                or "Chat User"
            )
            request_payload = {
                "department":           department,
                "amount":               amount,
                "requester":            requester_name,
                "captured_at":          datetime.now().isoformat(),
                "approval_action":      decision.action,
                "confidence":           decision.confidence,
                "context": {
                    "raw_pr_data": raw_pr_data,
                },
            }

            # ── Create workflow header ────────────────────────────────────────
            wf_result = adapter.create_approval_workflow({
                "pr_number":              pr_number,
                "department":             department,
                "total_amount":           amount,
                "requester_name":         requester_name,
                "request_data":           request_payload,
                "current_approval_level": 1,
                "workflow_status":        "in_progress",
            })
            if not wf_result.get("success"):
                return {"success": False,
                        "error": wf_result.get("error", "Workflow insert failed")}
            logger.info("[ApprovalAgent] Workflow header created for %s", pr_number)

            # ── Create approval steps ─────────────────────────────────────────
            steps_created = 0
            for approver in approvers:
                step_result = adapter.create_approval_step({
                    "pr_number":      pr_number,
                    "approval_level": approver.get("approval_level"),
                    "approver_name":  approver.get("approver_name"),
                    "approver_email": approver.get("approver_email"),
                    "status":         "pending",
                })
                if step_result.get("success"):
                    steps_created += 1
                    logger.info("[ApprovalAgent] Step %d created — %s (%s)",
                                approver.get("approval_level"),
                                approver.get("approver_name"),
                                approver.get("approver_email"))
                else:
                    logger.warning("[ApprovalAgent] Step insert failed: %s",
                                   step_result.get("error"))

            # ── Audit log ────────────────────────────────────────────────────
            adapter.log_agent_action(
                "ApprovalRoutingAgent",
                "create_approval_workflow",
                {"pr_number": pr_number, "department": department, "amount": amount},
                {"workflow_id": pr_number, "steps_created": steps_created},
                True
            )

            logger.info("[ApprovalAgent] Workflow complete — %d steps for %s",
                        steps_created, pr_number)
            return {
                "success":       True,
                "workflow_id":   pr_number,
                "steps_created": steps_created,
                "message":       f"Workflow created with {steps_created} steps",
            }

        except Exception as e:
            logger.error("[ApprovalAgent] _create_workflow_in_database error: %s", e)
            return {"success": False, "error": str(e)}
    
    async def learn(self, result: Dict[str, Any]) -> None:
        """Learn from approval routing patterns"""
        await super().learn(result)
        
        # Future: Track approval times, rejection patterns, escalation frequency
        # Can be used to optimize routing logic
        
        logger.info(f"[ApprovalAgent] Learning from result: {result.get('status')}")
    
    async def _get_approval_chain(self, department: str, amount: float) -> Dict[str, Any]:
        """Get approval chain using the get_approval_chain tool"""
        try:
            # Find the tool
            tool = next(
                (t for t in self.tools if t.name == "get_approval_chain"),
                None
            )
            
            if not tool:
                return {
                    "success": False,
                    "error": "get_approval_chain tool not found"
                }
            
            # Call the tool in a thread to avoid blocking the asyncio event loop
            import asyncio
            result_json = await asyncio.to_thread(tool.func, department=department, amount=amount)
            result = json.loads(result_json)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting approval chain: {e}")
            return {
                "success": False,
                "error": str(e)
            }
