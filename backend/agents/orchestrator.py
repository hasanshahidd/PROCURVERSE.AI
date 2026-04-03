"""
Orchestrator Agent - Master Router for Agentic Procurement System
Routes requests to specialized agents using intelligent classification
"""

from typing import Dict, Any, List, Optional
import logging
import json
import re
from datetime import datetime
import os

from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI

from backend.agents import BaseAgent, AgentStatus, AgentDecision
from backend.agents.tools import get_all_tools
from backend.services.llm_routing_guide import build_module_selection_instructions
from backend.services.odoo_client import get_odoo_client
# psycopg2 is NOT imported at module level — use the shared db_pool or adapter pattern instead.
# Any DB operations in OrchestratorAgent should go through BaseAgent._log_action or get_adapter().

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """
    Master orchestrator that routes requests to specialized agents.
    
    Uses LLM-based classification to determine which agent(s) should handle
    a request. Can invoke multiple agents if needed and aggregate results.
    
    Key Features:
    - Intelligent request classification
    - Multi-agent coordination
    - Result aggregation
    - Error recovery with agent fallback
    """
    
    def __init__(self):
        # Get all available tools so orchestrator can use them in workflows
        all_tools = get_all_tools()
        
        super().__init__(
            name="Orchestrator",
            description=(
                "Master agent that analyzes requests and routes them to "
                "specialized procurement agents. Coordinates multi-agent "
                "workflows and aggregates results."
            ),
            tools=all_tools,  # Pass tools for PR/PO creation workflows
            temperature=0.1  # Low temperature for consistent routing
        )
        
        # Registry of specialized agents (will be initialized later)
        self.specialized_agents: Dict[str, BaseAgent] = {}
        
        logger.info("Orchestrator Agent initialized")
    
    def register_agent(self, agent_type: str, agent: BaseAgent) -> None:
        """
        Register a specialized agent with the orchestrator.
        
        Args:
            agent_type: Type identifier (e.g., 'approval_routing', 'budget')
            agent: The agent instance
        """
        logger.info(f"[REGISTER] Registering agent type '{agent_type}' with name '{agent.name}'")
        logger.info(f"[REGISTER] Before registration: {list(self.specialized_agents.keys())}")
        
        self.specialized_agents[agent_type] = agent
        
        logger.info(f"[REGISTER] After registration: {list(self.specialized_agents.keys())}")
        logger.info(f"[REGISTER] ✅ Registered agent: {agent_type} ({agent.name})")
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute request using full orchestration cycle"""
        return await self.execute_with_recovery(input_data)
    
    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze the request to understand what needs to be done.
        """
        observations = await super().observe(context)
        
        # Extract key information from request
        request = context.get("request", "")
        pr_data = context.get("pr_data", {})
        query_type = context.get("query_type", "")  # From classifier!
        
        # Add orchestrator-specific observations
        logger.info(f"[OBSERVE] Orchestrator ID: {id(self)}")
        logger.info(f"[OBSERVE] specialized_agents: {self.specialized_agents}")
        logger.info(f"[OBSERVE] specialized_agents keys: {list(self.specialized_agents.keys())}")
        logger.info(f"[OBSERVE] 🎯 Query type from classifier: '{query_type}'")
        
        observations.update({
            "request_type": self._classify_request_type(query_type),
            "query_type": query_type,  # Pass through classifier result!
            "pr_budget": pr_data.get("budget", 0),
            "pr_department": pr_data.get("department", ""),
            "available_agents": list(self.specialized_agents.keys()),
            "timestamp": datetime.now().isoformat()
        })
        
        logger.info(
            f"[Orchestrator] Observed request type: "
            f"{observations['request_type']}"
        )
        
        return observations
    
    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Decide which agent(s) should handle this request.
        """
        request_type = observations.get("request_type", "unknown")
        query_type = observations.get("query_type", "")
        
        print("\n" + "="*80)
        print("[ORCHESTRATOR ROUTING]")
        print("="*80)
        print(f"📝 Request: {observations.get('request', 'unknown')}")
        print(f"🏷️  Request Type: {request_type}")
        print(f"🎯 Query Type (from classifier): '{query_type}'")
        print(f"💰 Budget: ${observations.get('pr_budget', 0):,}")
        print(f"🏢 Department: {observations.get('pr_department', 'unknown')}")
        print(f"🤖 Available Agents: {observations.get('available_agents', [])}")
        print("="*80)

        # FAST-PATH: When the classifier already resolved a specific agent type,
        # skip the LLM routing call to avoid the LLM re-interpreting the request
        # (e.g., "buy servers" → pr_creation) when the classifier explicitly said BUDGET/RISK/APPROVAL.
        _DIRECT_ROUTE_MAP = {
            "BUDGET": "budget_verification",
            "BUDGET_TRACKING": "budget_verification",
            "BUDGET_CHECK": "budget_verification",
            "APPROVAL": "approval_routing",
            "APPROVAL_CHAINS": "approval_routing",
            "APPROVAL_ROUTING": "approval_routing",
            "VENDOR": "vendor_selection",
            "VENDOR_SELECTION": "vendor_selection",
            "VENDORS": "vendor_selection",
            "RISK": "risk_assessment",
            "RISK_ASSESSMENT": "risk_assessment",
            "CONTRACT": "contract_monitoring",
            "CONTRACT_MONITORING": "contract_monitoring",
            "PERFORMANCE": "supplier_performance",
            "SUPPLIER_PERFORMANCE": "supplier_performance",
            "PRICE": "price_analysis",
            "PRICE_ANALYSIS": "price_analysis",
            "COMPLIANCE": "compliance_check",
            "COMPLIANCE_CHECK": "compliance_check",
            "INVOICE": "invoice_matching",
            "INVOICE_MATCHING": "invoice_matching",
            "SPEND": "spend_analytics",
            "SPEND_ANALYTICS": "spend_analytics",
            "INVENTORY": "inventory_check",
            "INVENTORY_CHECK": "inventory_check",
            "CREATE": "pr_creation",
            "PR_CREATION": "pr_creation",
            "PO_CREATE": "po_creation",
            "PO_CREATION": "po_creation",
        }
        qt_upper = (query_type or "").strip().upper()
        direct_agent = _DIRECT_ROUTE_MAP.get(qt_upper)
        if direct_agent and (direct_agent in self.specialized_agents or direct_agent in ("pr_creation", "po_creation")):
            print(f"[ORCHESTRATOR] ⚡ FAST-PATH: query_type={qt_upper} → {direct_agent} (skipping LLM)")
            return AgentDecision(
                action=json.dumps({"primary": direct_agent, "secondary": [], "sequence": "sequential"}),
                reasoning=f"Direct routing from classifier query_type={qt_upper}",
                confidence=0.95,
                context=observations,
                alternatives=[],
            )
        
        module_instructions = build_module_selection_instructions()

        # Build classification prompt with query_type as input signal, not rigid forcing.
        classification_prompt = f"""You are a procurement orchestration AI. Route requests based on business value.

REQUEST: "{observations.get('request', 'unknown')}"
CONTEXT: Department={observations.get('pr_department', 'unknown')}, Budget=${observations.get('pr_budget', 0)}
    AVAILABLE AGENTS: {observations.get('available_agents', [])}

    CLASSIFIER INPUT: query_type="{query_type}"
    Use classifier output as a strong signal, but resolve ambiguity by intent and expected outcome.

    {module_instructions}

    Task:
    1. Choose the best primary agent for the user goal.
    2. Optionally choose secondary agents only if genuinely needed.
    3. Do not route by keyword-only rules; route by requested outcome.
    4. Keep reasoning concise and business-focused.

    Confidence guidance:
    - strong and explicit intent: 0.9+
    - clear but slightly ambiguous: 0.75-0.89
    - ambiguous: 0.6-0.74

Return JSON (valid format):
{{
    "primary_agent": "agent_name",
    "secondary_agents": [],
    "reasoning": "CLASSIFIER: query_type='{query_type}'. User needs [VALUE], routing to [agent] because [intelligent reason based on principles above].",
    "sequence": "sequential",
    "confidence": 0.95
}}
"""
        
        response = await self.llm.ainvoke(classification_prompt)
        raw_content = (response.content or "").strip()
        logger.info(f"[Orchestrator] Raw routing response: {raw_content[:1000]}")
        
        # Parse LLM response
        try:
            parse_content = raw_content

            # Handle markdown code fences and mixed text responses
            if parse_content.startswith("```"):
                parse_content = re.sub(r"^```(?:json)?\\s*", "", parse_content)
                parse_content = re.sub(r"\\s*```$", "", parse_content)

            # If still not pure JSON, extract first JSON object block
            if not parse_content.startswith("{"):
                start = parse_content.find("{")
                end = parse_content.rfind("}")
                if start != -1 and end != -1 and end > start:
                    parse_content = parse_content[start:end + 1]

            routing_decision = json.loads(parse_content)
            
            primary_agent = routing_decision.get("primary_agent")
            secondary_agents =routing_decision.get("secondary_agents", [])
            confidence = float(routing_decision.get("confidence", 0.7))
            reasoning = routing_decision.get("reasoning", "")
            
            # Build action plan
            action = {
                "primary": primary_agent,
                "secondary": secondary_agents,
                "sequence": routing_decision.get("sequence", "sequential")
            }
            
            decision = AgentDecision(
                action=json.dumps(action),
                reasoning=reasoning,
                confidence=confidence,
                context=observations,
                alternatives=[
                    json.dumps({"primary": alt, "secondary": []}) 
                    for alt in secondary_agents
                ]
            )
            
            print("\n" + "="*80)
            print("[ROUTING DECISION]")
            print("="*80)
            print(f"✅ Primary Agent: {primary_agent}")
            print(f"📋 Secondary Agents: {secondary_agents}")
            print(f"🎯 Confidence: {confidence:.2%}")
            print(f"💭 Reasoning: {reasoning[:200]}...")
            print("="*80 + "\n")
            
            logger.info(
                f"[Orchestrator] Routing to {primary_agent} "
                f"(confidence: {confidence:.2f})"
            )
            
            return decision
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse routing decision: {e}")
            
            # Fallback to basic classification
            primary_agent = self._fallback_routing(request_type)
            
            return AgentDecision(
                action=json.dumps({"primary": primary_agent, "secondary": []}),
                reasoning="Fallback routing based on request type",
                confidence=0.5,
                context=observations,
                alternatives=[]
            )
    
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        Execute the routing decision by invoking appropriate agents.
        Handles special workflows like PR/PO creation.
        """
        action = json.loads(decision.action)
        primary_agent_type = action["primary"]
        secondary_agent_types = action.get("secondary", [])
        sequence = action.get("sequence", "sequential")
        
        results = {
            "primary_result": None,
            "secondary_results": [],
            "agents_invoked": [],
            "total_execution_time_ms": 0
        }
        
        # Handle PR/PO creation workflows (not separate agents, but orchestrated workflows)
        if primary_agent_type == "pr_creation":
            return await self._create_pr_workflow(decision.context)
        elif primary_agent_type == "po_creation":
            return await self._create_po_workflow(decision.context)
        
        # Check if primary agent exists
        if primary_agent_type not in self.specialized_agents:
            raise ValueError(
                f"Agent type '{primary_agent_type}' not registered. "
                f"Available: {list(self.specialized_agents.keys())}"
            )
        
        # Execute primary agent with original request context
        execution_context = decision.context.get("input_context", decision.context)

        async def emit_agent_selected(agent_type_key: str, confidence_score: float, reasoning_text: str) -> None:
            stream = execution_context.get("event_stream")
            if not stream:
                return
            from backend.services.agent_event_stream import AgentEventType
            selected = self.specialized_agents.get(agent_type_key)
            if not selected:
                return
            await stream.emit(AgentEventType.AGENT_SELECTED, {
                "agent": selected.name,
                "agent_type": agent_type_key,
                "confidence": confidence_score,
                "reasoning": reasoning_text,
                "message": f"Routing to {selected.name} for specialized processing"
            })

        # Execute primary agent
        primary_agent = self.specialized_agents[primary_agent_type]
        logger.info(f"[Orchestrator] Invoking primary agent: {primary_agent.name}")
        
        # Emit primary selection event
        await emit_agent_selected(primary_agent_type, decision.confidence, decision.reasoning)

        primary_result = await primary_agent.execute(execution_context)
        results["primary_result"] = primary_result
        results["agents_invoked"].append(primary_agent_type)
        
        # Execute secondary agents if needed
        if secondary_agent_types:
            if sequence == "parallel":
                # Execute in parallel (simplified - sequential for now)
                logger.info("[Orchestrator] Executing secondary agents in parallel")
                for agent_type in secondary_agent_types:
                    if agent_type in self.specialized_agents:
                        await emit_agent_selected(
                            agent_type,
                            decision.confidence,
                            f"Secondary parallel execution: {agent_type}"
                        )
                        agent = self.specialized_agents[agent_type]
                        result = await agent.execute(execution_context)
                        results["secondary_results"].append({
                            "agent_type": agent_type,
                            "result": result
                        })
                        results["agents_invoked"].append(agent_type)
            else:
                # Execute sequentially (pass output of previous as input to next)
                logger.info("[Orchestrator] Executing secondary agents sequentially")
                current_context = {**execution_context, "primary_result": primary_result}
                
                for agent_type in secondary_agent_types:
                    if agent_type in self.specialized_agents:
                        await emit_agent_selected(
                            agent_type,
                            decision.confidence,
                            f"Secondary sequential execution: {agent_type}"
                        )
                        agent = self.specialized_agents[agent_type]
                        result = await agent.execute(current_context)
                        results["secondary_results"].append({
                            "agent_type": agent_type,
                            "result": result
                        })
                        results["agents_invoked"].append(agent_type)
                        
                        # Update context for next agent
                        current_context = {**current_context, "previous_result": result}
        
        logger.info(
            f"[Orchestrator] Completed execution using "
            f"{len(results['agents_invoked'])} agent(s)"
        )
        
        return results
    
    def _classify_request_type(self, query_type: str) -> str:
        """
        Normalize classifier query_type to a fallback routing category.
        """
        normalized = (query_type or "").strip().upper()
        type_map = {
            "APPROVAL": "approval",
            "BUDGET": "budget",
            "VENDOR": "vendor",
            "CREATE": "pr_creation",
            "PO_CREATE": "po_creation",
            "RISK": "risk",
            "PRICE": "price",
            "CONTRACT": "contract",
            "COMPLIANCE": "compliance",
            "INVOICE": "invoice",
            "SPEND": "spend",
            "INVENTORY": "inventory",
            "PERFORMANCE": "performance",
        }
        return type_map.get(normalized, "unknown")
    
    def _fallback_routing(self, request_type: str) -> str:
        """
        Fallback routing when LLM classification fails.
        """
        routing_map = {
            "approval": "approval_routing",
            "budget": "budget_verification",
            "vendor": "vendor_selection",
            "pr_creation": "pr_creation",
            "po_creation": "po_creation",
            "risk": "risk_assessment",
            "price": "price_analysis",
            "contract": "contract_monitoring",
            "compliance": "compliance_check",
            "invoice": "invoice_matching",
            "spend": "spend_analytics",
            "inventory": "inventory_check",
            "performance": "supplier_performance",
            "unknown": "approval_routing"  # Default
        }
        
        return routing_map.get(request_type, "approval_routing")

    def _extract_vendor_options(self, vendor_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract top vendor options from VendorSelectionAgent output for UI confirmation."""
        payload = (vendor_result or {}).get("result", {}) if isinstance(vendor_result, dict) else {}
        options: List[Dict[str, Any]] = []

        primary = payload.get("primary_recommendation") if isinstance(payload, dict) else None
        if isinstance(primary, dict) and primary.get("vendor_name"):
            options.append({
                "vendor_name": str(primary.get("vendor_name")),
                "score": primary.get("score"),
                "reason": primary.get("reason"),
            })

        alternatives = payload.get("alternative_recommendations") if isinstance(payload, dict) else None
        if isinstance(alternatives, list):
            for alt in alternatives:
                if not isinstance(alt, dict) or not alt.get("vendor_name"):
                    continue
                options.append({
                    "vendor_name": str(alt.get("vendor_name")),
                    "score": alt.get("score"),
                    "reason": alt.get("reason"),
                })

        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in options:
            key = str(item.get("vendor_name", "")).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        return deduped[:5]
    
    async def _create_pr_workflow(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        PR Creation Workflow:
        1. Run compliance check
        2. Run budget verification
        3. Run price analysis (if vendor/price provided)
        4. If all pass, create structured PR object
        """
        logger.info("="*80)
        logger.info("[Orchestrator] 🚀 Starting PR creation workflow...")
        logger.info("="*80)
        
        workflow_results = {
            "workflow_type": "pr_creation",
            "agents_invoked": [],
            "validations": {},
            "pr_object": None,
            "status": "in_progress"
        }
        
        try:
            # Extract original input context (not orchestrator's wrapped context)
            input_context = context.get("input_context", context)
            pr_data = input_context.get("pr_data", {})

            # Normalize common free-text PR fields once so downstream agents/tools
            # (compliance, budget, approval routing) operate on canonical values.
            raw_department = (pr_data.get("department") or "").strip()
            dept_key = raw_department.lower()
            if dept_key.endswith(" department"):
                dept_key = dept_key[:-11].strip()
            elif dept_key.endswith(" dept"):
                dept_key = dept_key[:-5].strip()

            dept_map = {
                "it": "IT",
                "information technology": "IT",
                "finance": "Finance",
                "operations": "Operations",
                "operation": "Operations",
                "procurement": "Procurement",
                "purchasing": "Procurement",
            }
            normalized_department = dept_map.get(dept_key, raw_department)

            normalized_budget_category = (pr_data.get("budget_category") or "OPEX").strip().upper()
            if normalized_budget_category not in {"CAPEX", "OPEX"}:
                normalized_budget_category = "OPEX"

            if normalized_department:
                pr_data["department"] = normalized_department
            pr_data["budget_category"] = normalized_budget_category
            input_context["pr_data"] = pr_data

            # ── Early guard: budget is required to run the PR creation workflow ──
            raw_budget = pr_data.get("budget") or pr_data.get("total_amount") or 0
            try:
                raw_budget = float(raw_budget)
            except (TypeError, ValueError):
                raw_budget = 0.0

            if raw_budget <= 0:
                dept_label = normalized_department or "the requested"
                budget_cat = normalized_budget_category or "OPEX"
                logger.info(
                    f"[Orchestrator] 💬 Budget not provided for PR creation — prompting user"
                )
                return {
                    "workflow_type": "pr_creation",
                    "status": "needs_clarification",
                    "clarification_question": (
                        f"💰 To create a PR for the **{dept_label}** department, "
                        f"I need the **budget amount**.\n\n"
                        f"Please re-send your request with the amount, for example:\n\n"
                        f"> *Create PR for {dept_label} department, $25,000 {budget_cat}*"
                    ),
                    "missing_fields": ["budget"],
                    "agents_invoked": [],
                    "validations": {},
                    "pr_object": None,
                }

            logger.info(f"[Orchestrator] 📋 PR Data Received:")
            logger.info(f"[Orchestrator]   - Department: {pr_data.get('department', 'N/A')}")
            logger.info(f"[Orchestrator]   - Budget: ${pr_data.get('budget', 0):,.2f}")
            logger.info(f"[Orchestrator]   - Vendor: {pr_data.get('vendor_name', 'N/A')}")
            logger.info(f"[Orchestrator]   - Product: {pr_data.get('product_name', 'N/A')}")
            logger.info(f"[Orchestrator]   - Quantity: {pr_data.get('quantity', 0)}")
            logger.info(f"[Orchestrator]   - Requester: {pr_data.get('requester_name', 'Unknown')}")
            
            # Step 1: Compliance Check
            if "compliance_check" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] 📝 STEP 1: Running compliance check...")
                compliance_agent = self.specialized_agents["compliance_check"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": compliance_agent.name,
                        "agent_type": "compliance_check",
                        "confidence": 0.95,
                        "reasoning": "PR workflow validation step 1",
                        "message": f"Workflow invoking {compliance_agent.name}"
                    })
                compliance_result = await compliance_agent.execute(input_context)
                compliance_action = (
                    compliance_result.get("action")
                    or compliance_result.get("result", {}).get("action")
                )
                
                logger.info(f"[Orchestrator] ✓ Compliance check completed")
                logger.info(f"[Orchestrator]   - Status: {compliance_result.get('status')}")
                logger.info(f"[Orchestrator]   - Action: {compliance_action}")
                logger.info(f"[Orchestrator]   - Agent: {compliance_result.get('agent')}")
                
                workflow_results["validations"]["compliance"] = compliance_result
                workflow_results["agents_invoked"].append("compliance_check")
                
                # Block only on hard reject; warnings/corrections continue with notes
                if compliance_action == "reject":
                    logger.warning(f"[Orchestrator] ⚠️ Compliance check REJECTED - blocking workflow")
                    workflow_results["status"] = "failed"
                    workflow_results["failure_reason"] = "Compliance check rejected"
                    return workflow_results
                elif compliance_action == "require_correction":
                    logger.info(f"[Orchestrator] ⚠️ Compliance has corrections needed - continuing with warnings")
                    workflow_results["compliance_warnings"] = True
                else:
                    logger.info(f"[Orchestrator] ✅ Compliance check PASSED - continuing workflow")
            else:
                logger.warning("[Orchestrator] ⚠️ ComplianceCheckAgent not registered - skipping")
            
            # Step 2: Budget Verification
            if "budget_verification" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] 💰 STEP 2: Running budget verification...")
                budget_agent = self.specialized_agents["budget_verification"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": budget_agent.name,
                        "agent_type": "budget_verification",
                        "confidence": 0.9,
                        "reasoning": "PR workflow validation step 2",
                        "message": f"Workflow invoking {budget_agent.name}"
                    })
                budget_context = {**input_context, "reserve_budget": False}
                budget_result = await budget_agent.execute(budget_context)
                budget_action = (
                    budget_result.get("action")
                    or budget_result.get("result", {}).get("action")
                )
                
                logger.info(f"[Orchestrator] ✓ Budget verification completed")
                logger.info(f"[Orchestrator]   - Status: {budget_result.get('status')}")
                logger.info(f"[Orchestrator]   - Action: {budget_action}")
                logger.info(f"[Orchestrator]   - Budget Verified: {budget_result.get('result', {}).get('budget_verified', False)}")
                
                workflow_results["validations"]["budget"] = budget_result
                workflow_results["agents_invoked"].append("budget_verification")
                
                # Block if budget is insufficient, agent explicitly rejects, or agent errored.
                # BudgetVerificationAgent returns "reject_insufficient_budget" for hard failures.
                budget_agent_errored = budget_result.get("status") == "error"
                budget_result_inner = budget_result.get("result") if isinstance(budget_result.get("result"), dict) else {}
                budget_status = str(budget_result_inner.get("status", "")).lower()
                budget_verified = budget_result_inner.get("budget_verified")
                if (
                    budget_agent_errored
                    or budget_action in {"block", "reject", "reject_insufficient_budget"}
                    or budget_status in {"rejected", "error"}
                    or budget_verified is False
                ):
                    logger.error(f"[Orchestrator] ❌ Budget verification FAILED - insufficient funds")
                    workflow_results["status"] = "failed"
                    workflow_results["failure_reason"] = "Insufficient budget"
                    return workflow_results
                else:
                    logger.info(f"[Orchestrator] ✅ Budget verification PASSED - funds available")
            else:
                logger.warning("[Orchestrator] ⚠️ BudgetVerificationAgent not registered - skipping")
            
            # Step 3: Price Analysis (if price data available)
            if pr_data.get("quoted_price") and "price_analysis" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] 💵 STEP 3: Running price analysis...")
                price_agent = self.specialized_agents["price_analysis"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": price_agent.name,
                        "agent_type": "price_analysis",
                        "confidence": 0.85,
                        "reasoning": "PR workflow validation step 3",
                        "message": f"Workflow invoking {price_agent.name}"
                    })
                price_result = await price_agent.execute(input_context)
                
                logger.info(f"[Orchestrator] ✓ Price analysis completed")
                logger.info(f"[Orchestrator]   - Status: {price_result.get('status')}")
                
                workflow_results["validations"]["price"] = price_result
                workflow_results["agents_invoked"].append("price_analysis")
            else:
                logger.info("[Orchestrator] ℹ️ No quoted price provided - skipping price analysis")

            # Step 3.5: Mandatory vendor shortlist + user confirmation
            if "vendor_selection" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] 🏪 STEP 3.5: Building top 5 vendor shortlist...")
                vendor_agent = self.specialized_agents["vendor_selection"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": vendor_agent.name,
                        "agent_type": "vendor_selection",
                        "confidence": 0.9,
                        "reasoning": "PR workflow vendor shortlist",
                        "message": f"Workflow invoking {vendor_agent.name}"
                    })

                vendor_result = await vendor_agent.execute(input_context)
                workflow_results["validations"]["vendor"] = vendor_result
                workflow_results["agents_invoked"].append("vendor_selection")
                top_vendor_options = self._extract_vendor_options(vendor_result)
                workflow_results["top_vendor_options"] = top_vendor_options

                vendor_confirmed = bool(pr_data.get("vendor_confirmed"))
                selected_vendor = str(pr_data.get("selected_vendor_name") or pr_data.get("vendor_name") or "").strip()
                if selected_vendor:
                    selected_vendor = selected_vendor.split(". Continue", 1)[0].strip()
                    selected_vendor = selected_vendor.split("\n", 1)[0].strip()

                if not vendor_confirmed:
                    logger.info("[Orchestrator] ⏸️ Waiting for vendor confirmation before PR creation")
                    workflow_results["status"] = "awaiting_vendor_confirmation"
                    workflow_results["awaiting_vendor_confirmation"] = True
                    workflow_results["message"] = "Please review the top 5 vendors and confirm one to continue PR creation."
                    workflow_results["workflow_context"] = {
                        "pr_data": dict(pr_data),
                        "department": pr_data.get("department", ""),
                        "budget": pr_data.get("budget", 0),
                        "budget_category": pr_data.get("budget_category", "OPEX"),
                        "category": pr_data.get("category", ""),
                        "product_name": pr_data.get("product_name", ""),
                        "quantity": pr_data.get("quantity", 1),
                        "requester_name": pr_data.get("requester_name", "")
                    }
                    return workflow_results

                if selected_vendor:
                    pr_data["vendor_name"] = selected_vendor
                    if top_vendor_options:
                        selected_lower = selected_vendor.lower()
                        ranked_names = [str(v.get("vendor_name", "")).strip() for v in top_vendor_options if v.get("vendor_name")]
                        ranked_lowers = [n.lower() for n in ranked_names]
                        top_name = ranked_names[0] if ranked_names else ""

                        advisory: Optional[str] = None
                        if selected_lower not in ranked_lowers:
                            advisory = (
                                f"Selected vendor '{selected_vendor}' is outside the recommended shortlist. "
                                f"Top recommendation is '{top_name or 'N/A'}'."
                            )
                        elif top_name and selected_lower != top_name.lower():
                            advisory = (
                                f"Selected vendor '{selected_vendor}' is not the top recommended option "
                                f"('{top_name}')."
                            )

                        if advisory:
                            workflow_results.setdefault("warnings", [])
                            if advisory not in workflow_results["warnings"]:
                                workflow_results["warnings"].append(advisory)
                            workflow_results["vendor_selection_note"] = advisory
                            logger.info(f"[Orchestrator] ⚠️ {advisory}")
                elif top_vendor_options:
                    pr_data["vendor_name"] = top_vendor_options[0].get("vendor_name", "")
                input_context["pr_data"] = pr_data
                logger.info(f"[Orchestrator] ✅ Vendor confirmed for PR workflow: {pr_data.get('vendor_name', 'N/A')}")
            else:
                logger.warning("[Orchestrator] ⚠️ VendorSelectionAgent not registered - skipping shortlist gate")
            
            # Step 4: All validations passed - create PR object
            logger.info("-"*80)
            logger.info("[Orchestrator] 📦 STEP 4: Creating PR object...")
            pr_number = f"PR-2026-{datetime.now().strftime('%m%d%H%M%S')}"  # Added seconds for uniqueness
            
            pr_object = {
                "pr_number": pr_number,
                "department": pr_data.get("department", ""),
                "requester_name": pr_data.get("requester_name", ""),
                "product_name": pr_data.get("product_name", ""),
                "quantity": pr_data.get("quantity", 1),
                "budget": pr_data.get("budget", 0),
                "budget_category": pr_data.get("budget_category", "OPEX"),
                "vendor_name": pr_data.get("vendor_name", ""),
                "category": pr_data.get("category", ""),
                "justification": pr_data.get("justification", ""),
                "urgency": pr_data.get("urgency", "Normal"),
                "status": "pending_approval",
                "created_at": datetime.now().isoformat(),
                "validations_passed": len(workflow_results["validations"])
            }
            
            workflow_results["pr_object"] = pr_object
            logger.info(f"[Orchestrator] ✓ PR object created: {pr_number}")
            
            # Step 5: Create workflow and approval steps via ApprovalRoutingAgent
            # IMPORTANT: Let ApprovalRoutingAgent handle PR workflow creation to ensure approval steps are created
            logger.info("-"*80)
            logger.info("[Orchestrator] 👥 STEP 5: Creating approval workflow...")
            
            if "approval_routing" in self.specialized_agents:
                logger.info("[Orchestrator] 📋 Calling ApprovalRoutingAgent...")
                approval_agent = self.specialized_agents["approval_routing"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": approval_agent.name,
                        "agent_type": "approval_routing",
                        "confidence": 0.9,
                        "reasoning": "PR workflow approval orchestration",
                        "message": f"Workflow invoking {approval_agent.name}"
                    })
                
                total_amount = pr_data.get("budget", 0) or (pr_data.get("quoted_price", 0) * pr_data.get("quantity", 1))
                
                logger.info(f"[Orchestrator] 📨 Sending to ApprovalAgent:")
                logger.info(f"[Orchestrator]   - PR Number: {pr_number}")
                logger.info(f"[Orchestrator]   - Department: {pr_data.get('department', 'IT')}")
                logger.info(f"[Orchestrator]   - Total Amount: ${total_amount:,.2f}")
                logger.info(f"[Orchestrator]   - Requester: {pr_data.get('requester_name', 'Unknown')}")
                
                # Build context for approval routing
                approval_context = {
                    "request": f"Route approval for PR {pr_number}",
                    "pr_data": {
                        **pr_data,
                        "pr_number": pr_number,
                        "department": pr_data.get("department", "IT"),
                        "budget": total_amount,
                        "requester_name": pr_data.get("requester_name", "Unknown")
                    }
                }
                
                logger.info(f"[Orchestrator] 🔄 Executing ApprovalRoutingAgent...")
                approval_result = await approval_agent.execute(approval_context)
                
                logger.info(f"[Orchestrator] ✓ ApprovalRoutingAgent execution completed")
                logger.info(f"[Orchestrator]   - Status: {approval_result.get('status')}")
                logger.info(f"[Orchestrator]   - Agent: {approval_result.get('agent')}")
                logger.info(f"[Orchestrator]   - Action: {approval_result.get('action')}")
                
                # Extract nested result
                approval_inner_result = approval_result.get("result", {})
                logger.info(f"[Orchestrator]   - Inner Result Success: {approval_inner_result.get('success')}")
                logger.info(f"[Orchestrator]   - Inner Result Status: {approval_inner_result.get('status')}")
                logger.info(f"[Orchestrator]   - Workflow ID: {approval_inner_result.get('workflow_id', 'N/A')}")
                logger.info(f"[Orchestrator]   - Message: {approval_inner_result.get('message', 'N/A')}")
                
                workflow_results["validations"]["approval_routing"] = approval_result
                workflow_results["agents_invoked"].append("approval_routing")
                
                # Check if workflow was created successfully
                if approval_result.get("status") == "success" and approval_inner_result.get("success"):
                    workflow_results["workflow_id"] = pr_number
                    workflow_results["status"] = "success"
                    logger.info(f"[Orchestrator] ✅✅✅ PR CREATION COMPLETE: {pr_number}")
                    logger.info(f"[Orchestrator] ✅ Workflow and approval steps created successfully")
                    logger.info(f"[Orchestrator] ✅ Approvers assigned: {len(approval_inner_result.get('assigned_approvers', []))} level(s)")
                else:
                    logger.error(f"[Orchestrator] ❌ Approval workflow creation FAILED")
                    logger.error(f"[Orchestrator] ❌ Approval result: {approval_result}")
                    logger.warning(f"[Orchestrator] ⚠️ PR created but approval workflow failed: {pr_number}")
                    workflow_results["status"] = "success_no_workflow"
            else:
                logger.error("[Orchestrator] ❌ ApprovalRoutingAgent not available!")
                logger.warning("[Orchestrator] ⚠️ PR created without approval workflow")
                workflow_results["status"] = "success_no_workflow"

            # Step 6: Non-blocking risk snapshot for user visibility
            if "risk_assessment" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] ⚠️ STEP 6: Running post-create risk snapshot...")
                risk_agent = self.specialized_agents["risk_assessment"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": risk_agent.name,
                        "agent_type": "risk_assessment",
                        "confidence": 0.85,
                        "reasoning": "PR workflow post-create visibility step",
                        "message": f"Workflow invoking {risk_agent.name}"
                    })

                risk_context = {
                    **input_context,
                    "pr_data": {
                        **pr_data,
                        "pr_number": pr_number,
                    }
                }

                try:
                    risk_result = await risk_agent.execute(risk_context)
                    workflow_results["validations"]["risk"] = risk_result
                    workflow_results["agents_invoked"].append("risk_assessment")
                    risk_inner = risk_result.get("result", {}) if isinstance(risk_result, dict) else {}
                    logger.info(
                        "[Orchestrator] ✓ Risk snapshot captured: "
                        f"{risk_inner.get('risk_level', 'UNKNOWN')} "
                        f"({risk_inner.get('risk_score', 'N/A')}/100)"
                    )
                except Exception as risk_error:
                    logger.warning(f"[Orchestrator] ⚠️ Risk snapshot failed (non-blocking): {risk_error}")
            else:
                logger.info("[Orchestrator] ℹ️ RiskAssessmentAgent not registered - skipping post-create risk snapshot")
            
            logger.info("="*80)
            logger.info(f"[Orchestrator] 🏁 PR Workflow Completed: {workflow_results['status']}")
            logger.info(f"[Orchestrator] 🏁 Agents Invoked: {workflow_results['agents_invoked']}")
            logger.info("="*80)
            
        except Exception as e:
            logger.error("="*80)
            logger.error(f"[Orchestrator] ❌❌❌ PR WORKFLOW EXCEPTION")
            logger.error(f"[Orchestrator] ❌ Error: {str(e)}")
            logger.error(f"[Orchestrator] ❌ Type: {type(e).__name__}")
            import traceback
            logger.error(f"[Orchestrator] ❌ Traceback: {traceback.format_exc()}")
            logger.error("="*80)
            workflow_results["status"] = "error"
            workflow_results["error"] = str(e)
        
        return workflow_results
    
    async def _create_po_workflow(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        PO Creation Workflow:
        1. Run vendor selection (if vendor not specified)
        2. Run risk assessment
        3. Run approval routing
        4. If all pass, create PO in Odoo via create_purchase_order tool
        """
        logger.info("[Orchestrator] Starting PO creation workflow...")
        
        workflow_results = {
            "workflow_type": "po_creation",
            "agents_invoked": [],
            "validations": {},
            "po_object": None,
            "status": "in_progress"
        }
        
        try:
            # Extract original input context (not orchestrator's wrapped context)
            input_context = context.get("input_context", context)
            pr_data = input_context.get("pr_data", {})
            
            # Step 1: Mandatory Vendor Selection + Confirmation Gate
            if "vendor_selection" in self.specialized_agents:
                logger.info("[Orchestrator] Running vendor selection for top 5 shortlist...")
                vendor_agent = self.specialized_agents["vendor_selection"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": vendor_agent.name,
                        "agent_type": "vendor_selection",
                        "confidence": 0.9,
                        "reasoning": "PO workflow vendor validation",
                        "message": f"Workflow invoking {vendor_agent.name}"
                    })
                vendor_result = await vendor_agent.execute(input_context)
                workflow_results["validations"]["vendor"] = vendor_result
                workflow_results["agents_invoked"].append("vendor_selection")

                top_vendor_options = self._extract_vendor_options(vendor_result)
                workflow_results["top_vendor_options"] = top_vendor_options

                vendor_confirmed = bool(pr_data.get("vendor_confirmed"))
                selected_vendor = str(pr_data.get("selected_vendor_name") or pr_data.get("vendor_name") or "").strip()
                if selected_vendor:
                    selected_vendor = selected_vendor.split(". Continue", 1)[0].strip()
                    selected_vendor = selected_vendor.split("\n", 1)[0].strip()

                if not vendor_confirmed:
                    workflow_results["status"] = "awaiting_vendor_confirmation"
                    workflow_results["awaiting_vendor_confirmation"] = True
                    workflow_results["message"] = "Please review the top 5 vendors and confirm one to continue PO creation."
                    workflow_results["workflow_context"] = {
                        "pr_data": dict(pr_data),
                        "department": pr_data.get("department", ""),
                        "budget": pr_data.get("budget", 0),
                        "budget_category": pr_data.get("budget_category", "OPEX"),
                        "category": pr_data.get("category", ""),
                        "product_name": pr_data.get("product_name", ""),
                        "quantity": pr_data.get("quantity", 1),
                        "requester_name": pr_data.get("requester_name", "")
                    }
                    logger.info("[Orchestrator] ⏸️ Waiting for user vendor confirmation before PO creation")
                    return workflow_results

                if selected_vendor:
                    pr_data["vendor_name"] = selected_vendor
                    if top_vendor_options:
                        selected_lower = selected_vendor.lower()
                        ranked_names = [str(v.get("vendor_name", "")).strip() for v in top_vendor_options if v.get("vendor_name")]
                        ranked_lowers = [n.lower() for n in ranked_names]
                        top_name = ranked_names[0] if ranked_names else ""

                        advisory: Optional[str] = None
                        if selected_lower not in ranked_lowers:
                            advisory = (
                                f"Selected vendor '{selected_vendor}' is outside the recommended shortlist. "
                                f"Top recommendation is '{top_name or 'N/A'}'."
                            )
                        elif top_name and selected_lower != top_name.lower():
                            advisory = (
                                f"Selected vendor '{selected_vendor}' is not the top recommended option "
                                f"('{top_name}')."
                            )

                        if advisory:
                            workflow_results.setdefault("warnings", [])
                            if advisory not in workflow_results["warnings"]:
                                workflow_results["warnings"].append(advisory)
                            workflow_results["vendor_selection_note"] = advisory
                            logger.info(f"[Orchestrator] ⚠️ {advisory}")
                elif top_vendor_options:
                    pr_data["vendor_name"] = top_vendor_options[0].get("vendor_name", "")

                input_context["pr_data"] = pr_data
                logger.info(f"[Orchestrator] ✅ Vendor confirmed for PO workflow: {pr_data.get('vendor_name', 'N/A')}")
            else:
                logger.warning("[Orchestrator] ⚠️ VendorSelectionAgent unavailable, proceeding without shortlist gate")
            
            # Step 2: Risk Assessment
            if "risk_assessment" in self.specialized_agents:
                logger.info("[Orchestrator] Running risk assessment...")
                risk_agent = self.specialized_agents["risk_assessment"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": risk_agent.name,
                        "agent_type": "risk_assessment",
                        "confidence": 0.9,
                        "reasoning": "PO workflow risk validation",
                        "message": f"Workflow invoking {risk_agent.name}"
                    })
                risk_result = await risk_agent.execute(input_context)
                workflow_results["validations"]["risk"] = risk_result
                workflow_results["agents_invoked"].append("risk_assessment")
                
                # Block if risk is critical
                if risk_result.get("risk_level") == "CRITICAL":
                    workflow_results["status"] = "failed"
                    workflow_results["failure_reason"] = "Critical risk level"
                    return workflow_results
            
            # Step 3: Approval Routing
            if "approval_routing" in self.specialized_agents:
                logger.info("[Orchestrator] Running approval routing...")
                approval_agent = self.specialized_agents["approval_routing"]
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": approval_agent.name,
                        "agent_type": "approval_routing",
                        "confidence": 0.9,
                        "reasoning": "PO workflow approval routing",
                        "message": f"Workflow invoking {approval_agent.name}"
                    })
                approval_result = await approval_agent.execute(input_context)
                workflow_results["validations"]["approval"] = approval_result
                workflow_results["agents_invoked"].append("approval_routing")
            
            # Step 4: All validations passed - create PO in Odoo via tool
            po_number = f"PO-2026-{datetime.now().strftime('%m%d%H%M%S')}"  # Added seconds for uniqueness
            quantity_for_po = int(pr_data.get("quantity", 1) or 1)
            total_for_po = float(pr_data.get("budget", 0) or 0)
            quoted_for_po = float(pr_data.get("quoted_price", 0) or 0)
            unit_price_for_po = quoted_for_po if quoted_for_po > 0 else (total_for_po / quantity_for_po if quantity_for_po > 0 else total_for_po)

            po_object = {
                "po_number": po_number,
                "pr_number": pr_data.get("pr_number", ""),
                "vendor_name": pr_data.get("vendor_name", ""),
                "department": pr_data.get("department", ""),
                "product_name": pr_data.get("product_name", ""),
                "quantity": quantity_for_po,
                "unit_price": unit_price_for_po,
                "total_amount": total_for_po,
                "status": "draft",
                "created_at": datetime.now().isoformat(),
                "validations_passed": len(workflow_results["validations"]),
                "approval_chain": workflow_results["validations"].get("approval", {}).get("approval_chain", [])
            }
            
            workflow_results["po_object"] = po_object
            
            # Actually create PO in Odoo using resolved vendor/product IDs.
            try:
                odoo = get_odoo_client()

                vendor_name = str(pr_data.get("vendor_name") or "").strip()
                product_name = str(pr_data.get("product_name") or "").strip()
                quantity = int(pr_data.get("quantity", 1) or 1)
                raw_total = float(pr_data.get("budget", 0) or 0)
                quoted_price = float(pr_data.get("quoted_price", 0) or 0)
                unit_price = quoted_price if quoted_price > 0 else (raw_total / quantity if quantity > 0 else raw_total)

                # Resolve vendor partner_id by name.
                partner_id = None
                if vendor_name:
                    vendors = odoo.execute_kw(
                        'res.partner',
                        'search_read',
                        [[('name', 'ilike', vendor_name)]],
                        {'fields': ['id', 'name'], 'limit': 1}
                    ) or []
                    if vendors:
                        partner_id = vendors[0].get('id')

                if not partner_id:
                    raise ValueError(f"Could not resolve vendor in Odoo for name='{vendor_name}'")

                # Resolve product_id by product name; fallback to a safe purchasable product.
                product_id = None
                if product_name:
                    products = odoo.get_products(limit=20, search_term=product_name) or []
                    if products:
                        product_id = products[0].get('id')

                if not product_id:
                    fallback_products = odoo.get_products(limit=1) or []
                    if fallback_products:
                        product_id = fallback_products[0].get('id')

                if not product_id:
                    raise ValueError("Could not resolve product in Odoo")

                notes = (
                    f"Department: {pr_data.get('department', '')}\n"
                    f"Budget Category: {pr_data.get('budget_category', '')}\n"
                    f"Business Justification: {pr_data.get('justification', '')}"
                )

                odoo_po_id = odoo.create_purchase_order(
                    partner_id=partner_id,
                    order_lines=[{
                        "product_id": product_id,
                        "quantity": quantity,
                        "price": unit_price,
                        "name": product_name or "Requested Item",
                    }],
                    origin=(pr_data.get("pr_number") or None),
                    notes=notes,
                )

                workflow_results["odoo_po_id"] = odoo_po_id
                workflow_results["status"] = "success"
                logger.info(f"[Orchestrator] ✅ PO created in Odoo: {po_number} (Odoo ID: {odoo_po_id})")
                    
            except Exception as odoo_error:
                logger.error(f"[Orchestrator] Failed to create PO in Odoo: {odoo_error}")
                workflow_results["status"] = "success_odoo_failed"
                workflow_results["odoo_error"] = str(odoo_error)
                logger.warning(f"[Orchestrator] ⚠️ PO object created but Odoo write failed: {po_number}")
            
        except Exception as e:
            logger.error(f"[Orchestrator] PO workflow failed: {e}")
            workflow_results["status"] = "error"
            workflow_results["error"] = str(e)
        
        return workflow_results
    
    async def get_system_status(self) -> Dict[str, Any]:
        """
        Get status of all registered agents.
        """
        status = {
            "orchestrator": {
                "name": self.name,
                "status": self.status.value,
                "registered_agents": len(self.specialized_agents)
            },
            "agents": {}
        }
        
        for agent_type, agent in self.specialized_agents.items():
            status["agents"][agent_type] = {
                "name": agent.name,
                "status": agent.status.value,
                "decision_history_count": len(agent.decision_history)
            }
        
        return status


# Global orchestrator instance (singleton)
_orchestrator_instance: Optional[OrchestratorAgent] = None


def get_orchestrator() -> OrchestratorAgent:
    """Get global orchestrator instance"""
    global _orchestrator_instance
    
    if _orchestrator_instance is None:
        _orchestrator_instance = OrchestratorAgent()
        logger.info("Created new Orchestrator instance")
    
    return _orchestrator_instance


def initialize_orchestrator_with_agents() -> OrchestratorAgent:
    """
    Initialize orchestrator and register all specialized agents.
    This will be called during application startup.
    """
    logger.info("[INIT] Starting initialize_orchestrator_with_agents()")
    
    orchestrator = get_orchestrator()
    logger.info(f"[INIT] Got orchestrator instance: {id(orchestrator)}")
    logger.info(f"[INIT] Current specialized_agents: {orchestrator.specialized_agents}")
    logger.info(f"[INIT] specialized_agents is dict: {isinstance(orchestrator.specialized_agents, dict)}")
    logger.info(f"[INIT] specialized_agents length: {len(orchestrator.specialized_agents)}")
    logger.info(f"[INIT] specialized_agents keys: {list(orchestrator.specialized_agents.keys())}")
    
    # Only register if not already registered
    if not orchestrator.specialized_agents:
        logger.info("[INIT] No agents registered yet, registering now...")
        from backend.agents.budget_verification import BudgetVerificationAgent
        from backend.agents.approval_routing import ApprovalRoutingAgent
        from backend.agents.vendor_selection import VendorSelectionAgent
        from backend.agents.risk_assessment import RiskAssessmentAgent
        
        logger.info("[INIT] Creating BudgetVerificationAgent...")
        budget_agent = BudgetVerificationAgent()
        logger.info(f"[INIT] Created BudgetVerificationAgent: {budget_agent.name}")
        
        logger.info("[INIT] Creating ApprovalRoutingAgent...")
        approval_agent = ApprovalRoutingAgent()
        logger.info(f"[INIT] Created ApprovalRoutingAgent: {approval_agent.name}")
        
        logger.info("[INIT] Creating VendorSelectionAgent...")
        vendor_agent = VendorSelectionAgent()
        logger.info(f"[INIT] Created VendorSelectionAgent: {vendor_agent.name}")
        
        logger.info("[INIT] Creating RiskAssessmentAgent...")
        risk_agent = RiskAssessmentAgent()
        logger.info(f"[INIT] Created RiskAssessmentAgent: {risk_agent.name}")
        
        logger.info("[INIT] Creating ContractMonitoringAgent...")
        from backend.agents.contract_monitoring import ContractMonitoringAgent
        contract_agent = ContractMonitoringAgent()
        logger.info(f"[INIT] Created ContractMonitoringAgent: {contract_agent.name}")
        
        logger.info("[INIT] Creating SupplierPerformanceAgent...")
        from backend.agents.supplier_performance import SupplierPerformanceAgent
        supplier_perf_agent = SupplierPerformanceAgent()
        logger.info(f"[INIT] Created SupplierPerformanceAgent: {supplier_perf_agent.name}")
        
        logger.info("[INIT] Creating PriceAnalysisAgent...")
        from backend.agents.price_analysis import PriceAnalysisAgent
        price_agent = PriceAnalysisAgent()
        logger.info(f"[INIT] Created PriceAnalysisAgent: {price_agent.name}")
        
        logger.info("[INIT] Creating ComplianceCheckAgent...")
        from backend.agents.compliance_check import ComplianceCheckAgent
        compliance_agent = ComplianceCheckAgent()
        logger.info(f"[INIT] Created ComplianceCheckAgent: {compliance_agent.name}")
        
        logger.info("[INIT] Creating InvoiceMatchingAgent...")
        from backend.agents.invoice_matching import InvoiceMatchingAgent
        invoice_agent = InvoiceMatchingAgent()
        logger.info(f"[INIT] Created InvoiceMatchingAgent: {invoice_agent.name}")
        
        logger.info("[INIT] Creating SpendAnalyticsAgent...")
        from backend.agents.spend_analytics import SpendAnalyticsAgent
        spend_agent = SpendAnalyticsAgent()
        logger.info(f"[INIT] Created SpendAnalyticsAgent: {spend_agent.name}")
        
        logger.info("[INIT] Creating InventoryCheckAgent...")
        from backend.agents.inventory_check import InventoryCheckAgent
        inventory_agent = InventoryCheckAgent()
        logger.info(f"[INIT] Created InventoryCheckAgent: {inventory_agent.name}")
        
        logger.info("[INIT] Registering budget_verification agent...")
        orchestrator.register_agent("budget_verification", budget_agent)
        logger.info(f"[INIT] After budget registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering approval_routing agent...")
        orchestrator.register_agent("approval_routing", approval_agent)
        logger.info(f"[INIT] After approval registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering vendor_selection agent...")
        orchestrator.register_agent("vendor_selection", vendor_agent)
        logger.info(f"[INIT] After vendor registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering risk_assessment agent...")
        orchestrator.register_agent("risk_assessment", risk_agent)
        logger.info(f"[INIT] After risk registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering contract_monitoring agent...")
        orchestrator.register_agent("contract_monitoring", contract_agent)
        logger.info(f"[INIT] After contract registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering supplier_performance agent...")
        orchestrator.register_agent("supplier_performance", supplier_perf_agent)
        logger.info(f"[INIT] After supplier performance registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering price_analysis agent...")
        orchestrator.register_agent("price_analysis", price_agent)
        logger.info(f"[INIT] After price analysis registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering compliance_check agent...")
        orchestrator.register_agent("compliance_check", compliance_agent)
        logger.info(f"[INIT] After compliance check registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering invoice_matching agent...")
        orchestrator.register_agent("invoice_matching", invoice_agent)
        logger.info(f"[INIT] After invoice matching registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering spend_analytics agent...")
        orchestrator.register_agent("spend_analytics", spend_agent)
        logger.info(f"[INIT] After spend analytics registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info("[INIT] Registering inventory_check agent...")
        orchestrator.register_agent("inventory_check", inventory_agent)
        logger.info(f"[INIT] After inventory check registration: {list(orchestrator.specialized_agents.keys())}")
        
        logger.info(
            f"[INIT] ✅ Orchestrator initialized with "
            f"{len(orchestrator.specialized_agents)} agent(s): "
            f"{list(orchestrator.specialized_agents.keys())}"
        )
    else:
        logger.info(f"[INIT] Agents already registered: {list(orchestrator.specialized_agents.keys())}")
    
    logger.info(f"[INIT] Returning orchestrator with {len(orchestrator.specialized_agents)} agents")
    return orchestrator
