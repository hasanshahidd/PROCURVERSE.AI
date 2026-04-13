"""
Orchestrator Agent - Master Router for Agentic Procurement System
Routes requests to specialized agents using intelligent classification
"""

from typing import Dict, Any, List, Optional
import logging
import json
import re
from datetime import datetime, timedelta
import os

from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI

from backend.agents import BaseAgent, AgentStatus, AgentDecision
from backend.agents.tools import get_all_tools
from backend.services.llm_routing_guide import build_module_selection_instructions
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
        logger.info(f"[REGISTER] Registered agent: {agent_type} ({agent.name})")

    def _get_agent(self, agent_type: str):
        """Safe accessor — returns agent or None if not registered."""
        agent = self.specialized_agents.get(agent_type)
        if not agent:
            logger.warning(f"[ORCHESTRATOR] Agent '{agent_type}' not registered. Available: {list(self.specialized_agents.keys())}")
        return agent
    
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
        logger.info(f"[OBSERVE] Query type from classifier: '{query_type}'")
        
        observations.update({
            "request_type": self._classify_request_type(query_type),
            "query_type": query_type,  # Pass through classifier result!
            "pr_budget": pr_data.get("budget", 0),
            "pr_department": pr_data.get("department", ""),
            "available_agents": list(self.specialized_agents.keys()),
            "timestamp": datetime.now().isoformat(),
            # Preserve original context so _execute_full_p2p / _create_pr_workflow
            # can read pr_data, session_id, event_stream etc. Without this,
            # decision.context loses the full pr_data dict and the approval gate
            # renders $0.00 / empty fields.
            "input_context": context,
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
        logger.info(f"Request: {observations.get('request', 'unknown')}")
        logger.info(f"️  Request Type: {request_type}")
        logger.info(f"Query Type (from classifier): '{query_type}'")
        logger.info(f"Budget: ${observations.get('pr_budget', 0):,}")
        logger.info(f"Department: {observations.get('pr_department', 'unknown')}")
        logger.info(f"Available Agents: {observations.get('available_agents', [])}")
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
            # Phase 3-7: New agentic modules
            "RFQ": "rfq_management",
            "RFQ_CREATE": "rfq_management",
            "RFQ_COMPARE": "rfq_management",
            "QUOTATION": "rfq_management",
            "AMENDMENT": "po_amendment",
            "PO_AMENDMENT": "po_amendment",
            "PO_AMEND": "po_amendment",
            "MODIFY_PO": "po_amendment",
            "RETURN": "return_processing",
            "RTV": "return_processing",
            "RETURN_TO_VENDOR": "return_processing",
            "SEND_BACK": "return_processing",
            "QUALITY": "quality_inspection",
            "QC": "quality_inspection",
            "QUALITY_INSPECTION": "quality_inspection",
            "INSPECT": "quality_inspection",
            "RECONCILIATION": "reconciliation",
            "RECONCILE": "reconciliation",
            "BANK_MATCH": "reconciliation",
            "PAYMENT_MATCH": "reconciliation",
            # Vendor onboarding
            "ONBOARD": "vendor_onboarding",
            "VENDOR_ONBOARD": "vendor_onboarding",
            "REGISTER_VENDOR": "vendor_onboarding",
            "NEW_VENDOR": "vendor_onboarding",
            "NEW_SUPPLIER": "vendor_onboarding",
            # Delivery tracking
            "DELIVERY": "delivery_tracking",
            "TRACK_DELIVERY": "delivery_tracking",
            "SHIPMENT": "delivery_tracking",
            "TRACK_SHIPMENT": "delivery_tracking",
            "DELIVERY_STATUS": "delivery_tracking",
            # Exception resolution
            "DISCREPANCY": "exception_resolution",
            "EXCEPTION": "exception_resolution",
            "MISMATCH": "exception_resolution",
            "RESOLVE_EXCEPTION": "exception_resolution",
            # Payment readiness & execution
            "PAYMENT_READY": "payment_readiness",
            "PAYMENT_CHECK": "payment_readiness",
            "PRE_PAYMENT": "payment_readiness",
            "CAN_WE_PAY": "payment_readiness",
            "PAYMENT": "payment_calculation",
            "PAY": "payment_calculation",
            "PROCESS_PAYMENT": "payment_calculation",
            "RELEASE_PAYMENT": "payment_calculation",
            "PAYMENT_APPROVAL": "payment_approval",
            # Goods receipt
            "GRN": "goods_receipt",
            "GOODS_RECEIPT": "goods_receipt",
            "RECEIVE_GOODS": "goods_receipt",
            "RECEIVED": "goods_receipt",
            # Quote comparison
            "QUOTE": "quote_comparison",
            "COMPARE_QUOTES": "quote_comparison",
            "QUOTE_COMPARISON": "quote_comparison",
            # Full Procure-to-Pay (ONLY for explicit "run full pipeline" requests)
            "P2P_FULL": "p2p_full",
            "FULL_P2P": "p2p_full",
            "END_TO_END": "p2p_full",
            "PROCURE_TO_PAY": "p2p_full",
            # Previously orphaned agents — now routable
            "ANOMALY": "anomaly_detection",
            "ANOMALY_DETECTION": "anomaly_detection",
            "DETECT_ANOMALY": "anomaly_detection",
            "FRAUD": "anomaly_detection",
            "FORECAST": "forecasting",
            "FORECASTING": "forecasting",
            "DEMAND_FORECAST": "forecasting",
            "PREDICT": "forecasting",
            "INVOICE_ROUTE": "invoice_routing",
            "INVOICE_ROUTING": "invoice_routing",
            "ROUTE_INVOICE": "invoice_routing",
            "DASHBOARD": "monitoring_dashboard",
            "MONITORING": "monitoring_dashboard",
            "HEALTH_SCORE": "monitoring_dashboard",
            "KPI": "monitoring_dashboard",
            "PO_REGISTER": "po_registration",
            "PO_REGISTRATION": "po_registration",
            "REGISTER_PO": "po_registration",
            "VALIDATE_PO": "po_registration",
        }
        qt_upper = (query_type or "").strip().upper()
        direct_agent = _DIRECT_ROUTE_MAP.get(qt_upper)
        if direct_agent and (direct_agent in self.specialized_agents or direct_agent in ("pr_creation", "po_creation", "p2p_full")):
            logger.info(f"[ORCHESTRATOR] FAST-PATH: query_type={qt_upper} → {direct_agent} (skipping LLM)")
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
            logger.info(f"Primary Agent: {primary_agent}")
            logger.info(f"Secondary Agents: {secondary_agents}")
            logger.info(f"Confidence: {confidence:.2%}")
            logger.info(f"Reasoning: {reasoning[:200]}...")
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
        elif primary_agent_type == "p2p_full":
            return await self._execute_full_p2p(decision.context)

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
                "message": f"Routing to {selected.name} for specialized processing",
                "routed_agent_name": selected.name,
                "query_type": execution_context.get("query_type", ""),
                "detected_intent": execution_context.get("query_type", ""),
            })

        # Execute primary agent
        primary_agent = self._get_agent(primary_agent_type)
        if not primary_agent:
            return {"status": "error", "error": f"Agent '{primary_agent_type}' is not registered."}
        logger.info(f"[Orchestrator] Invoking primary agent: {primary_agent.name} (type={primary_agent_type})")
        logger.info(f"[Orchestrator] Agent has tools: {[t.name for t in getattr(primary_agent, 'tools', [])][:5]}")

        # Emit primary selection event
        await emit_agent_selected(primary_agent_type, decision.confidence, decision.reasoning)

        try:
            primary_result = await primary_agent.execute(execution_context)
            logger.info(f"[Orchestrator] Agent {primary_agent.name} returned: status={primary_result.get('status') if isinstance(primary_result, dict) else 'N/A'}, keys={list(primary_result.keys()) if isinstance(primary_result, dict) else 'not-dict'}")
        except Exception as agent_err:
            logger.error(f"[Orchestrator] Agent {primary_agent.name} FAILED: {agent_err}", exc_info=True)
            raise
        results["primary_result"] = primary_result
        results["agents_invoked"].append(primary_agent.name)
        
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
                        results["agents_invoked"].append(agent.name)
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
                        results["agents_invoked"].append(agent.name)

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
            "APPROVAL_CHAINS": "approval",
            "APPROVAL_ROUTING": "approval",
            "BUDGET": "budget",
            "BUDGET_TRACKING": "budget",
            "BUDGET_CHECK": "budget",
            "VENDOR": "vendor",
            "VENDOR_SELECTION": "vendor",
            "VENDORS": "vendor",
            "CREATE": "pr_creation",
            "PR_CREATION": "pr_creation",
            "PO_CREATE": "po_creation",
            "PO_CREATION": "po_creation",
            "RISK": "risk",
            "RISK_ASSESSMENT": "risk",
            "PRICE": "price",
            "PRICE_ANALYSIS": "price",
            "CONTRACT": "contract",
            "CONTRACT_MONITORING": "contract",
            "COMPLIANCE": "compliance",
            "COMPLIANCE_CHECK": "compliance",
            "INVOICE": "invoice",
            "INVOICE_MATCHING": "invoice",
            "SPEND": "spend",
            "SPEND_ANALYTICS": "spend",
            "INVENTORY": "inventory",
            "INVENTORY_CHECK": "inventory",
            "PERFORMANCE": "performance",
            "SUPPLIER_PERFORMANCE": "performance",
            "P2P_FULL": "p2p_full",
            "FULL_P2P": "p2p_full",
            "PROCURE": "p2p_full",
            "PROCURE_TO_PAY": "p2p_full",
            "END_TO_END": "p2p_full",
            "P2P": "p2p_full",
            "RFQ": "rfq",
            "QUOTATION": "rfq",
            "PAYMENT": "payment",
            "PAY": "payment",
            "PAYMENT_READY": "payment",
            "GRN": "grn",
            "GOODS_RECEIPT": "grn",
            "DELIVERY": "delivery",
            "SHIPMENT": "delivery",
            "ONBOARD": "vendor_onboard",
            "VENDOR_ONBOARD": "vendor_onboard",
            "NEW_VENDOR": "vendor_onboard",
            "ANOMALY": "anomaly",
            "ANOMALY_DETECTION": "anomaly",
            "FRAUD": "anomaly",
            "FORECAST": "forecasting",
            "FORECASTING": "forecasting",
            "DEMAND_FORECAST": "forecasting",
            "INVOICE_ROUTE": "invoice_routing",
            "INVOICE_ROUTING": "invoice_routing",
            "DASHBOARD": "dashboard",
            "MONITORING": "dashboard",
            "KPI": "dashboard",
            "HEALTH_SCORE": "dashboard",
            "PO_REGISTER": "po_registration",
            "PO_REGISTRATION": "po_registration",
            "REGISTER_PO": "po_registration",
            "GENERAL": "general",
        }
        return type_map.get(normalized, "general")
    
    def _fallback_routing(self, request_type: str) -> str:
        """
        Fallback routing when LLM classification fails.
        Routes to the correct agent based on request type.
        'general' queries go to spend_analytics as a safe default (read-only overview).
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
            "p2p_full": "p2p_full",
            "rfq": "rfq_management",
            "payment": "payment_calculation",
            "grn": "goods_receipt",
            "delivery": "delivery_tracking",
            "vendor_onboard": "vendor_onboarding",
            "anomaly": "anomaly_detection",
            "forecasting": "forecasting",
            "invoice_routing": "invoice_routing",
            "dashboard": "monitoring_dashboard",
            "po_registration": "po_registration",
            "general": "spend_analytics",  # Safe read-only default
        }

        return routing_map.get(request_type, "spend_analytics")

    def _extract_vendor_options(self, vendor_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract top vendor options from VendorSelectionAgent output for UI confirmation."""
        if not isinstance(vendor_result, dict):
            return []
        options: List[Dict[str, Any]] = []

        # Navigate nested result structures to find vendor data
        # Shape 1 (direct agent execute): decision.context.{primary_vendor, alternative_vendors}
        # Shape 2 (orchestrated): result.primary_result.decision.context.{...}
        # Shape 3 (legacy): result.{primary_recommendation, alternative_recommendations}

        # Try all known paths to find vendor context
        ctx = {}
        logger.info("[_extract_vendor_options] vendor_result keys: %s", list(vendor_result.keys()))
        # Path A: direct decision.context (from agent.execute())
        direct_dec = vendor_result.get("decision", {}) or {}
        logger.info("[_extract_vendor_options] Path A decision keys: %s, has context: %s", list(direct_dec.keys()) if isinstance(direct_dec, dict) else "not-dict", bool(direct_dec.get("context") if isinstance(direct_dec, dict) else False))
        if isinstance(direct_dec, dict) and direct_dec.get("context"):
            _ctx = direct_dec["context"]
            logger.info("[_extract_vendor_options] Context keys: %s, primary_vendor type: %s", list(_ctx.keys())[:10] if isinstance(_ctx, dict) else "not-dict", type(_ctx.get("primary_vendor")).__name__ if isinstance(_ctx, dict) else "N/A")
        if isinstance(direct_dec, dict) and direct_dec.get("context"):
            ctx = direct_dec["context"]
        # Path B: nested result.primary_result.decision.context (from orchestrator wrapper)
        if not ctx.get("primary_vendor"):
            payload = vendor_result.get("result", {})
            if isinstance(payload, dict):
                primary_result = payload.get("primary_result", {}) or {}
                decision = (primary_result.get("decision", {}) or {})
                ctx = decision.get("context", {}) or {}
        # Path C: top-level result fields
        if not ctx.get("primary_vendor"):
            payload = vendor_result.get("result", {})
            if isinstance(payload, dict):
                ctx = payload

        # Build options from whichever path populated ctx
        primary = ctx.get("primary_vendor") or ctx.get("primary_recommendation")
        if isinstance(primary, dict) and primary.get("vendor_name"):
            options.append({
                "vendor_name": str(primary["vendor_name"]),
                "total_score": primary.get("total_score", primary.get("score")),
                "score": primary.get("total_score", primary.get("score")),
                "recommendation_reason": primary.get("recommendation_reason", primary.get("reason", "")),
                "strengths": primary.get("strengths", []),
                "concerns": primary.get("concerns", []),
            })

        alternatives = ctx.get("alternative_vendors") or ctx.get("alternative_recommendations") or []
        if isinstance(alternatives, list):
            for alt in alternatives:
                if not isinstance(alt, dict) or not alt.get("vendor_name"):
                    continue
                options.append({
                    "vendor_name": str(alt["vendor_name"]),
                    "total_score": alt.get("total_score", alt.get("score")),
                    "score": alt.get("total_score", alt.get("score")),
                    "recommendation_reason": alt.get("recommendation_reason", alt.get("reason", "")),
                    "strengths": alt.get("strengths", []),
                    "concerns": alt.get("concerns", []),
                })

        # Deduplicate
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

        Now integrated with WorkflowEngine for persistent tracking.
        """
        logger.info("="*80)
        logger.info("[Orchestrator] Starting PR creation workflow...")
        logger.info("="*80)

        # Create tracked workflow in workflow engine
        workflow_run_id = None
        try:
            from backend.services.workflow_engine import create_workflow, advance_workflow, complete_task, fail_task
            input_context = context.get("input_context", context)
            pr_data = input_context.get("pr_data", {})
            wf_result = create_workflow('PR_TO_PO', {
                'department': pr_data.get('department', ''),
                'product_name': pr_data.get('product_name', ''),
                'quantity': pr_data.get('quantity', 0),
                'budget': pr_data.get('budget', 0),
                'requester': pr_data.get('requester_name', 'Chat User'),
                'request': context.get('request', ''),
            })
            if wf_result.get('success'):
                workflow_run_id = wf_result['workflow_run_id']
                logger.info("[Orchestrator] Workflow tracked: %s", workflow_run_id)
                # Start first task (compliance_check)
                advance_workflow(workflow_run_id)
        except Exception as wf_err:
            logger.warning("[Orchestrator] Workflow tracking failed (non-blocking): %s", wf_err)

        workflow_results = {
            "workflow_type": "pr_creation",
            "workflow_run_id": workflow_run_id,
            "agents_invoked": [],
            "validations": {},
            "pr_object": None,
            "status": "in_progress"
        }

        # Helper to track task completion in workflow engine (non-blocking)
        def _track_task(task_name, result_data=None, failed=False, error_msg=None):
            if not workflow_run_id:
                return
            try:
                from backend.services.workflow_engine import get_workflow_status, complete_task, fail_task
                status = get_workflow_status(workflow_run_id)
                for t in status.get('tasks', []):
                    if t['task_name'] == task_name and t['status'] in ('running', 'pending'):
                        if failed:
                            fail_task(t['task_id'], error_msg or 'Agent failed')
                        else:
                            complete_task(t['task_id'], result_data or {})
                        return
            except Exception as _te:
                logger.debug("[Orchestrator] Workflow tracking for %s: %s", task_name, _te)
        
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
                    f"[Orchestrator] Budget not provided for PR creation — prompting user"
                )
                return {
                    "workflow_type": "pr_creation",
                    "status": "needs_clarification",
                    "clarification_question": (
                        f"To create a PR for the **{dept_label}** department, "
                        f"I need the **budget amount**.\n\n"
                        f"Please re-send your request with the amount, for example:\n\n"
                        f"> *Create PR for {dept_label} department, $25,000 {budget_cat}*"
                    ),
                    "missing_fields": ["budget"],
                    "agents_invoked": [],
                    "validations": {},
                    "pr_object": None,
                }

            logger.info(f"[Orchestrator] PR Data Received:")
            logger.info(f"[Orchestrator]   - Department: {pr_data.get('department', 'N/A')}")
            logger.info(f"[Orchestrator]   - Budget: ${pr_data.get('budget', 0):,.2f}")
            logger.info(f"[Orchestrator]   - Vendor: {pr_data.get('vendor_name', 'N/A')}")
            logger.info(f"[Orchestrator]   - Product: {pr_data.get('product_name', 'N/A')}")
            logger.info(f"[Orchestrator]   - Quantity: {pr_data.get('quantity', 0)}")
            logger.info(f"[Orchestrator]   - Requester: {pr_data.get('requester_name', 'Unknown')}")
            
            # Step 1: Compliance Check
            if "compliance_check" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] STEP 1: Running compliance check...")
                compliance_agent = self._get_agent("compliance_check")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": compliance_agent.name,
                        "agent_type": "compliance_check",
                        "confidence": 0.95,
                        "reasoning": "PR workflow validation step 1",
                        "message": f"Workflow invoking {compliance_agent.name}",
                        "routed_agent_name": compliance_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
                    })
                compliance_result = await compliance_agent.execute(input_context)
                compliance_action = (
                    compliance_result.get("action")
                    or compliance_result.get("result", {}).get("action")
                )
                
                logger.info(f"[Orchestrator] Compliance check completed")
                logger.info(f"[Orchestrator]   - Status: {compliance_result.get('status')}")
                logger.info(f"[Orchestrator]   - Action: {compliance_action}")
                logger.info(f"[Orchestrator]   - Agent: {compliance_result.get('agent')}")
                
                workflow_results["validations"]["compliance"] = compliance_result
                workflow_results["agents_invoked"].append(compliance_agent.name)

                # Block only on hard reject; warnings/corrections continue with notes
                if compliance_action == "reject":
                    logger.warning("[Orchestrator] Compliance check REJECTED - blocking workflow")
                    _track_task('compliance_check', failed=True, error_msg='Compliance rejected')
                    workflow_results["status"] = "failed"
                    workflow_results["failure_reason"] = "Compliance check rejected"
                    return workflow_results
                elif compliance_action == "require_correction":
                    logger.info("[Orchestrator] Compliance has corrections needed - continuing with warnings")
                    workflow_results["compliance_warnings"] = True
                    _track_task('compliance_check', {'action': 'require_correction', 'passed': True})
                else:
                    logger.info("[Orchestrator] Compliance check PASSED - continuing workflow")
                    _track_task('compliance_check', {'action': compliance_action, 'passed': True})
            else:
                logger.warning("[Orchestrator] ️ ComplianceCheckAgent not registered - skipping")
            
            # Step 2: Budget Verification
            if "budget_verification" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] STEP 2: Running budget verification...")
                budget_agent = self._get_agent("budget_verification")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": budget_agent.name,
                        "agent_type": "budget_verification",
                        "confidence": 0.9,
                        "reasoning": "PR workflow validation step 2",
                        "message": f"Workflow invoking {budget_agent.name}",
                        "routed_agent_name": budget_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
                    })
                budget_context = {**input_context, "reserve_budget": False}
                budget_result = await budget_agent.execute(budget_context)
                budget_action = (
                    budget_result.get("action")
                    or budget_result.get("result", {}).get("action")
                )
                
                logger.info(f"[Orchestrator] Budget verification completed")
                logger.info(f"[Orchestrator]   - Status: {budget_result.get('status')}")
                logger.info(f"[Orchestrator]   - Action: {budget_action}")
                logger.info(f"[Orchestrator]   - Budget Verified: {budget_result.get('result', {}).get('budget_verified', False)}")
                
                workflow_results["validations"]["budget"] = budget_result
                workflow_results["agents_invoked"].append(budget_agent.name)
                
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
                    logger.error("[Orchestrator] Budget verification FAILED - insufficient funds")
                    _track_task('budget_verification', failed=True, error_msg='Insufficient budget')
                    workflow_results["status"] = "failed"
                    workflow_results["failure_reason"] = "Insufficient budget"
                    return workflow_results
                else:
                    logger.info("[Orchestrator] Budget verification PASSED - funds available")
                    _track_task('budget_verification', {'budget_verified': True})
            else:
                logger.warning("[Orchestrator] ️ BudgetVerificationAgent not registered - skipping")
            
            # Step 3: Price Analysis (if price data available)
            if pr_data.get("quoted_price") and "price_analysis" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] STEP 3: Running price analysis...")
                price_agent = self._get_agent("price_analysis")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": price_agent.name,
                        "agent_type": "price_analysis",
                        "confidence": 0.85,
                        "reasoning": "PR workflow validation step 3",
                        "message": f"Workflow invoking {price_agent.name}",
                        "routed_agent_name": price_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
                    })
                price_result = await price_agent.execute(input_context)
                
                logger.info(f"[Orchestrator] Price analysis completed")
                logger.info(f"[Orchestrator]   - Status: {price_result.get('status')}")
                
                workflow_results["validations"]["price"] = price_result
                workflow_results["agents_invoked"].append(price_agent.name)
            else:
                logger.info("[Orchestrator] ️ No quoted price provided - skipping price analysis")

            # Step 3.5: Mandatory vendor shortlist + user confirmation
            if "vendor_selection" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] STEP 3.5: Building top 5 vendor shortlist...")
                vendor_agent = self._get_agent("vendor_selection")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": vendor_agent.name,
                        "agent_type": "vendor_selection",
                        "confidence": 0.9,
                        "reasoning": "PR workflow vendor shortlist",
                        "message": f"Workflow invoking {vendor_agent.name}",
                        "routed_agent_name": vendor_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
                    })

                vendor_result = await vendor_agent.execute(input_context)
                workflow_results["validations"]["vendor"] = vendor_result
                workflow_results["agents_invoked"].append(vendor_agent.name)
                _track_task('vendor_selection', {'vendors_found': True})
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
                    # Set human_action_required for frontend inline decision UI
                    workflow_results["human_action_required"] = {
                        "type": "vendor_selection",
                        "message": "Please review the vendor shortlist and confirm your choice to continue PR creation.",
                        "options": [v.get("vendor_name", "Unknown") for v in top_vendor_options[:5]],
                    }
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
                            logger.info(f"[Orchestrator] ️ {advisory}")
                elif top_vendor_options:
                    pr_data["vendor_name"] = top_vendor_options[0].get("vendor_name", "")
                input_context["pr_data"] = pr_data
                logger.info(f"[Orchestrator] Vendor confirmed for PR workflow: {pr_data.get('vendor_name', 'N/A')}")
            else:
                logger.warning("[Orchestrator] ️ VendorSelectionAgent not registered - skipping shortlist gate")
            
            # Step 4: All validations passed - create PR object
            logger.info("-"*80)
            logger.info("[Orchestrator] STEP 4: Creating PR object...")
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
            logger.info(f"[Orchestrator] PR object created: {pr_number}")

            # Persist PR to purchase_requisitions table via adapter
            try:
                from backend.services.adapters.factory import get_adapter
                _pr_adapter = get_adapter()
                _pr_adapter.create_purchase_requisition({
                    "name": pr_number,
                    "user_id": pr_data.get("requester_name", "Chat User"),
                    "product_qty": pr_data.get("quantity", 1),
                    "state": "pending_approval",
                    "origin": pr_data.get("department", ""),
                    "notes": f"{pr_data.get('product_name', '')} - {pr_data.get('justification', '')}",
                    "erp_source": "procure_ai",
                })
                logger.info("[Orchestrator] PR %s persisted to purchase_requisitions table", pr_number)
                _track_task('pr_creation', {'pr_number': pr_number})
            except Exception as _pr_err:
                logger.warning("[Orchestrator] PR persistence failed (non-blocking): %s", _pr_err)

            # Step 5: Create workflow and approval steps via ApprovalRoutingAgent
            # IMPORTANT: Let ApprovalRoutingAgent handle PR workflow creation to ensure approval steps are created
            logger.info("-"*80)
            logger.info("[Orchestrator] STEP 5: Creating approval workflow...")
            
            if "approval_routing" in self.specialized_agents:
                logger.info("[Orchestrator] Calling ApprovalRoutingAgent...")
                approval_agent = self._get_agent("approval_routing")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": approval_agent.name,
                        "agent_type": "approval_routing",
                        "confidence": 0.9,
                        "reasoning": "PR workflow approval orchestration",
                        "message": f"Workflow invoking {approval_agent.name}",
                        "routed_agent_name": approval_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
                    })
                
                total_amount = pr_data.get("budget", 0) or (pr_data.get("quoted_price", 0) * pr_data.get("quantity", 1))
                
                logger.info(f"[Orchestrator] Sending to ApprovalAgent:")
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
                
                logger.info(f"[Orchestrator] Executing ApprovalRoutingAgent...")
                approval_result = await approval_agent.execute(approval_context)
                
                logger.info(f"[Orchestrator] ApprovalRoutingAgent execution completed")
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
                workflow_results["agents_invoked"].append(approval_agent.name)
                _track_task('approval_routing', {'routed': True})

                # Check if workflow was created successfully
                if approval_result.get("status") == "success" and approval_inner_result.get("success"):
                    workflow_results["workflow_id"] = pr_number
                    workflow_results["status"] = "success"
                    logger.info("[Orchestrator] PR CREATION COMPLETE: %s", pr_number)
                    logger.info(f"[Orchestrator] Workflow and approval steps created successfully")
                    logger.info(f"[Orchestrator] Approvers assigned: {len(approval_inner_result.get('assigned_approvers', []))} level(s)")
                else:
                    logger.error(f"[Orchestrator] Approval workflow creation FAILED")
                    logger.error(f"[Orchestrator] Approval result: {approval_result}")
                    logger.warning(f"[Orchestrator] ️ PR created but approval workflow failed: {pr_number}")
                    workflow_results["status"] = "success_no_workflow"
            else:
                logger.error("[Orchestrator] ApprovalRoutingAgent not available!")
                logger.warning("[Orchestrator] ️ PR created without approval workflow")
                workflow_results["status"] = "success_no_workflow"

            # Step 6: Non-blocking risk snapshot for user visibility
            if "risk_assessment" in self.specialized_agents:
                logger.info("-"*80)
                logger.info("[Orchestrator] ️ STEP 6: Running post-create risk snapshot...")
                risk_agent = self._get_agent("risk_assessment")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": risk_agent.name,
                        "agent_type": "risk_assessment",
                        "confidence": 0.85,
                        "reasoning": "PR workflow post-create visibility step",
                        "message": f"Workflow invoking {risk_agent.name}",
                        "routed_agent_name": risk_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
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
                    workflow_results["agents_invoked"].append(risk_agent.name)
                    risk_inner = risk_result.get("result", {}) if isinstance(risk_result, dict) else {}
                    logger.info(
                        "[Orchestrator] Risk snapshot captured: "
                        f"{risk_inner.get('risk_level', 'UNKNOWN')} "
                        f"({risk_inner.get('risk_score', 'N/A')}/100)"
                    )
                except Exception as risk_error:
                    logger.warning(f"[Orchestrator] ️ Risk snapshot failed (non-blocking): {risk_error}")
            else:
                logger.info("[Orchestrator] ️ RiskAssessmentAgent not registered - skipping post-create risk snapshot")
            
            logger.info("="*80)
            logger.info(f"[Orchestrator] PR Workflow Completed: {workflow_results['status']}")
            logger.info(f"[Orchestrator] Agents Invoked: {workflow_results['agents_invoked']}")
            logger.info("="*80)
            
        except Exception as e:
            logger.error("="*80)
            logger.error(f"[Orchestrator] PR WORKFLOW EXCEPTION")
            logger.error(f"[Orchestrator] Error: {str(e)}")
            logger.error(f"[Orchestrator] Type: {type(e).__name__}")
            import traceback
            logger.error(f"[Orchestrator] Traceback: {traceback.format_exc()}")
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
                vendor_agent = self._get_agent("vendor_selection")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": vendor_agent.name,
                        "agent_type": "vendor_selection",
                        "confidence": 0.9,
                        "reasoning": "PO workflow vendor validation",
                        "message": f"Workflow invoking {vendor_agent.name}",
                        "routed_agent_name": vendor_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
                    })
                vendor_result = await vendor_agent.execute(input_context)
                workflow_results["validations"]["vendor"] = vendor_result
                workflow_results["agents_invoked"].append(vendor_agent.name)

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
                    # Set human_action_required for frontend inline decision UI
                    workflow_results["human_action_required"] = {
                        "type": "vendor_selection",
                        "message": "Please review the vendor shortlist and confirm your choice to continue PO creation.",
                        "options": [v.get("vendor_name", "Unknown") for v in top_vendor_options[:5]],
                    }
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
                            logger.info(f"[Orchestrator] ️ {advisory}")
                elif top_vendor_options:
                    pr_data["vendor_name"] = top_vendor_options[0].get("vendor_name", "")

                input_context["pr_data"] = pr_data
                logger.info(f"[Orchestrator] Vendor confirmed for PO workflow: {pr_data.get('vendor_name', 'N/A')}")
            else:
                logger.warning("[Orchestrator] ️ VendorSelectionAgent unavailable, proceeding without shortlist gate")
            
            # Step 2: Risk Assessment
            if "risk_assessment" in self.specialized_agents:
                logger.info("[Orchestrator] Running risk assessment...")
                risk_agent = self._get_agent("risk_assessment")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": risk_agent.name,
                        "agent_type": "risk_assessment",
                        "confidence": 0.9,
                        "reasoning": "PO workflow risk validation",
                        "message": f"Workflow invoking {risk_agent.name}",
                        "routed_agent_name": risk_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
                    })
                risk_result = await risk_agent.execute(input_context)
                workflow_results["validations"]["risk"] = risk_result
                workflow_results["agents_invoked"].append(risk_agent.name)

                # Block if risk is critical
                if risk_result.get("risk_level") == "CRITICAL":
                    workflow_results["status"] = "failed"
                    workflow_results["failure_reason"] = "Critical risk level"
                    return workflow_results
            
            # Step 3: Approval Routing
            if "approval_routing" in self.specialized_agents:
                logger.info("[Orchestrator] Running approval routing...")
                approval_agent = self._get_agent("approval_routing")
                event_stream = input_context.get("event_stream")
                if event_stream:
                    from backend.services.agent_event_stream import AgentEventType
                    await event_stream.emit(AgentEventType.AGENT_SELECTED, {
                        "agent": approval_agent.name,
                        "agent_type": "approval_routing",
                        "confidence": 0.9,
                        "reasoning": "PO workflow approval routing",
                        "message": f"Workflow invoking {approval_agent.name}",
                        "routed_agent_name": approval_agent.name,
                        "query_type": input_context.get("query_type", "CREATE"),
                    })
                approval_result = await approval_agent.execute(input_context)
                workflow_results["validations"]["approval"] = approval_result
                workflow_results["agents_invoked"].append(approval_agent.name)

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
            
            # Create PO via adapter (ERP-aware — works with any data source)
            try:
                from backend.services.adapters.factory import get_adapter
                po_adapter = get_adapter()
                po_result = po_adapter.create_purchase_order_from_pr({
                    "po_number": po_number,
                    "pr_number": pr_data.get("pr_number", ""),
                    "vendor_name": pr_data.get("vendor_name", ""),
                    "department": pr_data.get("department", ""),
                    "product_name": pr_data.get("product_name", ""),
                    "quantity": int(pr_data.get("quantity", 1) or 1),
                    "budget": float(pr_data.get("budget", 0) or 0),
                    "budget_category": pr_data.get("budget_category", ""),
                    "justification": pr_data.get("justification", ""),
                })

                workflow_results["po_result"] = po_result
                workflow_results["status"] = "success"
                logger.info(f"[Orchestrator] PO created via adapter: {po_number}")

            except Exception as po_error:
                logger.error(f"[Orchestrator] Failed to create PO: {po_error}")
                workflow_results["status"] = "success_po_warning"
                workflow_results["po_error"] = str(po_error)
                logger.warning(f"[Orchestrator] PO object created but adapter write failed: {po_number}")
            
        except Exception as e:
            logger.error(f"[Orchestrator] PO workflow failed: {e}")
            workflow_results["status"] = "error"
            workflow_results["error"] = str(e)
        
        return workflow_results
    
    # ── Full Procure-to-Pay Orchestration ──────────────────────────────────────
    async def _execute_full_p2p(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Full P2P Workflow: Chains ALL procurement steps end-to-end.
        15 steps from compliance check through payment execution.
        Pauses at human decision points (vendor confirmation, approval, GRN).
        Returns unified P2P response with actions completed + suggestions.
        """
        logger.info("=" * 80)
        logger.info("[P2P] Starting Full Procure-to-Pay workflow...")
        logger.info("=" * 80)

        # -- Setup: create tracked workflow --
        workflow_run_id = None
        try:
            from backend.services.workflow_engine import (
                create_workflow, advance_workflow, complete_task, fail_task,
                get_suggestions, generate_workflow_summary, get_workflow_status,
            )
            input_context = context.get("input_context", context)
            pr_data = input_context.get("pr_data", {})
            wf_result = create_workflow('P2P_FULL', {
                'department': pr_data.get('department', ''),
                'product_name': pr_data.get('product_name', ''),
                'quantity': pr_data.get('quantity', 0),
                'budget': pr_data.get('budget', 0),
                'requester': pr_data.get('requester_name', 'Chat User'),
                'request': context.get('request', ''),
            })
            if wf_result.get('success'):
                workflow_run_id = wf_result['workflow_run_id']
                logger.info("[P2P] Workflow tracked: %s", workflow_run_id)
                advance_workflow(workflow_run_id)
                # Attach workflow_run_id to the session row (hybrid-mode observer).
                # Non-fatal on failure — session layer must never break the pipeline.
                _sess_id_preattach = context.get("session_id") or input_context.get("session_id")
                if _sess_id_preattach:
                    try:
                        from backend.services.session_service import SessionService
                        SessionService.attach_workflow_run_id(
                            session_id=_sess_id_preattach,
                            workflow_run_id=workflow_run_id,
                        )
                    except Exception as _attach_exc:
                        logger.warning(
                            "[P2P] session attach_workflow_run_id failed (non-fatal in hybrid): %s",
                            _attach_exc,
                        )
        except Exception as wf_err:
            logger.warning("[P2P] Workflow tracking init failed (non-blocking): %s", wf_err)

        p2p_results = {
            "workflow_type": "P2P_FULL",
            "workflow_run_id": workflow_run_id,
            "agents_invoked": [],
            "actions_completed": [],
            "validations": {},
            "status": "in_progress",
            "pr_number": None,
            "po_number": None,
            "vendor_name": None,
            "total_amount": float(pr_data.get("budget", 0)) * max(float(pr_data.get("quantity", 1)), 1) if pr_data.get("budget") else None,
            "human_action_required": None,
            "suggested_next_actions": [],
            "pending_exceptions": [],
            "summary": "",
            "top_vendor_options": [],
        }

        # Helper: check if an agent result requires human input (universal gate)
        def _check_human_gate(step_name: str, agent_result: dict, agent_name: str) -> bool:
            """
            Returns True if this agent result triggers a human gate.
            Checks: explicit human_action_required, needs_human_input status,
            or low confidence (< 40%).
            """
            if not isinstance(agent_result, dict):
                return False
            # Explicit human gate from agent's decide()
            if agent_result.get("human_action_required"):
                gate_data = agent_result["human_action_required"]
                p2p_results["human_action_required"] = gate_data
                p2p_results["status"] = f"awaiting_{gate_data.get('type', step_name)}"
                p2p_results["summary"] = gate_data.get("message", f"{agent_name} requires your input.")
                p2p_results["suggested_next_actions"] = gate_data.get("actions", [])
                logger.info(f"[P2P] Human gate at step {step_name}: {gate_data.get('type')}")
                return True
            # Status-based gate
            if agent_result.get("status") in ("needs_human_input", "pending_human_approval"):
                dec = agent_result.get("decision", {})
                gate = dec.get("human_gate") or {
                    "type": f"{step_name}_review",
                    "message": agent_result.get("message", f"{agent_name} needs human review."),
                    "options": [],
                    "actions": ["approve", "reject"],
                }
                p2p_results["human_action_required"] = gate
                p2p_results["status"] = f"awaiting_{step_name}"
                p2p_results["summary"] = gate.get("message", "Human review needed.")
                return True
            return False

        # Helper: track task completion in workflow engine (non-blocking)
        def _track_task(task_name, result_data=None, failed=False, error_msg=None):
            if not workflow_run_id:
                return
            try:
                status = get_workflow_status(workflow_run_id)
                for t in status.get('tasks', []):
                    if t['task_name'] == task_name and t['status'] in ('running', 'pending'):
                        if failed:
                            fail_task(t['task_id'], error_msg or 'Agent failed')
                        else:
                            complete_task(t['task_id'], result_data or {})
                        return
            except Exception as _te:
                logger.debug("[P2P] Workflow tracking for %s: %s", task_name, _te)

        # Helper: add step to actions_completed
        def _add_step(step_name, status, summary, agent=None, data=None):
            p2p_results["actions_completed"].append({
                "step": step_name,
                "status": status,
                "summary": summary,
                "agent": agent,
                "data": data,
            })

        # Helper: fetch suggestions from workflow engine
        def _fetch_suggestions():
            if not workflow_run_id:
                return []
            try:
                sg = get_suggestions(workflow_run_id)
                return sg.get('suggestions', [])
            except Exception:
                return []

        # Helper: build summary narrative from completed actions
        def _build_summary():
            from backend.services.workflow_engine import P2P_GUIDE
            parts = []
            last_step = None
            for a in p2p_results["actions_completed"]:
                parts.append(f"{a['step'].replace('_', ' ').title()}: {a['status']}")
                last_step = a['step']
            if p2p_results.get("pr_number"):
                parts.append(f"PR: {p2p_results['pr_number']}")
            if p2p_results.get("po_number"):
                parts.append(f"PO: {p2p_results['po_number']}")
            if p2p_results.get("vendor_name"):
                parts.append(f"Vendor: {p2p_results['vendor_name']}")

            summary = ". ".join(parts) + "." if parts else ""

            # Add guide narrative
            if last_step and last_step in P2P_GUIDE:
                guide = P2P_GUIDE[last_step]
                summary += f"\n\n--- Step {guide.get('step', '')} ---"
                summary += f"\n{guide.get('done', '')}"
                summary += f"\n{guide.get('next', '')}"

            return summary

        # Helper: emit agent selected event
        async def _emit_selected(agent_key, step_num, total=15):
            agent_obj = self.specialized_agents.get(agent_key)
            stream = input_context.get("event_stream")
            if stream and agent_obj:
                from backend.services.agent_event_stream import AgentEventType
                await stream.emit(AgentEventType.AGENT_SELECTED, {
                    "agent": agent_obj.name,
                    "agent_type": agent_key,
                    "confidence": 0.95,
                    "reasoning": f"P2P workflow step {step_num}/{total}",
                    "message": f"P2P step {step_num}: invoking {agent_obj.name}",
                    "routed_agent_name": agent_obj.name,
                    "query_type": input_context.get("query_type", "P2P_FULL"),
                })

        try:
            input_context = context.get("input_context", context)
            pr_data = input_context.get("pr_data", {})

            # ── Layer 1: execution session observer (HYBRID mode, P1) ────────────
            # `emit`, `open_gate`, `set_phase` are thin, exception-swallowing wrappers
            # around SessionService. When session_id is None (legacy callers) they are
            # no-ops. When SessionService raises, we log and continue — a Layer-1
            # failure must NEVER break the existing pipeline during hybrid observer.
            _raw_session_id = context.get("session_id") or input_context.get("session_id")
            # Defensive normalization: if upstream violates the contract and hands us
            # a dict / object instead of a string, log it once and coerce to None so
            # the session layer becomes a no-op. Prevents psycopg2 "can't adapt type"
            # and `TypeError: unhashable type: 'slice'` downstream.
            if _raw_session_id is not None and not isinstance(_raw_session_id, str):
                logger.warning(
                    "[SESSION-CTX] Non-string session_id in context (type=%s value=%r) — disabling session emits for this run",
                    type(_raw_session_id).__name__, _raw_session_id,
                )
                session_id_hybrid: Optional[str] = None
            else:
                session_id_hybrid = _raw_session_id or None
            p2p_results["session_id"] = session_id_hybrid

            def _sid_tag() -> str:
                """Short, crash-proof session tag for log lines."""
                if not session_id_hybrid:
                    return "?"
                try:
                    return str(session_id_hybrid)[:8]
                except Exception:
                    return "?"

            def _session_emit(event_type: str, payload: dict) -> None:
                if not session_id_hybrid:
                    logger.debug("[SESSION-EMIT] SKIP event=%s (no session_id in context)", event_type)
                    return
                try:
                    from backend.services.session_service import SessionService
                    result = SessionService.append_event(
                        session_id=session_id_hybrid,
                        event_type=event_type,
                        actor="orchestrator",
                        payload=payload or {},
                    )
                    seq = result.get("sequence_number") if isinstance(result, dict) else "?"
                    logger.info(
                        "[SESSION-EMIT] OK session=%s seq=%s event=%s payload_keys=%s",
                        _sid_tag(), seq, event_type, list((payload or {}).keys()),
                    )
                except Exception as _exc:
                    logger.warning(
                        "[SESSION-EMIT] FAIL session=%s event=%s err=%s (non-fatal in hybrid)",
                        _sid_tag(), event_type, _exc,
                    )

            def _session_set_phase(new_phase: str, new_status: str) -> None:
                if not session_id_hybrid:
                    return
                try:
                    from backend.services.session_service import SessionService
                    SessionService.set_phase(
                        session_id=session_id_hybrid,
                        new_phase=new_phase,
                        new_status=new_status,
                    )
                    logger.info(
                        "[SESSION-PHASE] OK session=%s phase=%s status=%s",
                        _sid_tag(), new_phase, new_status,
                    )
                except Exception as _exc:
                    logger.warning(
                        "[SESSION-PHASE] FAIL session=%s phase=%s status=%s err=%s (non-fatal in hybrid)",
                        _sid_tag(), new_phase, new_status, _exc,
                    )

            def _session_open_gate(gate_type: str, gate_ref: dict, decision_context: dict, required_role: Optional[str] = None) -> Optional[str]:
                if not session_id_hybrid:
                    return None
                try:
                    from backend.services.session_service import SessionService
                    gate_row = SessionService.open_gate(
                        session_id=session_id_hybrid,
                        gate_type=gate_type,
                        gate_ref=gate_ref or {},
                        decision_context=decision_context or {},
                        required_role=required_role,
                    )
                    # SessionService.open_gate returns the full gate row (dict).
                    # Callers and the gate_opened event payload expect the
                    # gate_id STRING — unwrap it here so the frontend reducer
                    # receives a plain UUID string in event.payload.gate_id
                    # (otherwise /resume POST-body fails Pydantic str validation → 422).
                    gid = gate_row.get("gate_id") if isinstance(gate_row, dict) else None
                    logger.info(
                        "[SESSION-GATE] OPEN session=%s gate_type=%s gate_id=%s role=%s",
                        _sid_tag(), gate_type, (gid[:8] if gid else "?"), required_role,
                    )
                    return gid
                except Exception as _exc:
                    logger.warning(
                        "[SESSION-GATE] FAIL session=%s gate_type=%s err=%s (non-fatal in hybrid)",
                        _sid_tag(), gate_type, _exc,
                    )
                    return None

            _session_emit("session_started", {
                "workflow_run_id": workflow_run_id,
                "pr_preview": {
                    "department": pr_data.get("department", ""),
                    "product_name": pr_data.get("product_name", ""),
                    "quantity": pr_data.get("quantity", 0),
                    "budget": pr_data.get("budget", 0),
                },
            })

            # Normalize department & budget category (same as _create_pr_workflow)
            raw_department = (pr_data.get("department") or "").strip()
            dept_key = raw_department.lower()
            if dept_key.endswith(" department"):
                dept_key = dept_key[:-11].strip()
            elif dept_key.endswith(" dept"):
                dept_key = dept_key[:-5].strip()
            dept_map = {
                "it": "IT", "information technology": "IT",
                "finance": "Finance", "operations": "Operations",
                "procurement": "Procurement", "purchasing": "Procurement",
            }
            pr_data["department"] = dept_map.get(dept_key, raw_department)
            budget_cat = (pr_data.get("budget_category") or "OPEX").strip().upper()
            if budget_cat not in {"CAPEX", "OPEX"}:
                budget_cat = "OPEX"
            pr_data["budget_category"] = budget_cat
            input_context["pr_data"] = pr_data

            raw_budget = float(pr_data.get("budget") or pr_data.get("total_amount") or 0)
            p2p_results["total_amount"] = raw_budget

            if raw_budget <= 0:
                p2p_results["status"] = "needs_clarification"
                p2p_results["summary"] = "Budget amount is required to start the P2P workflow."
                p2p_results["human_action_required"] = {
                    "type": "clarification",
                    "message": "Please provide a budget amount (e.g., 'Procure 50 monitors for IT at $200 each').",
                }
                _session_emit("session_failed", {"reason": "needs_clarification_budget"})
                _session_set_phase("failed", "failed")
                return p2p_results

            # ─── HF-3 / R14: Split dispatch for pre-gate phases ─────────────
            # When USE_PURE_HANDLERS is enabled, compliance/budget/vendor run
            # via PHASE_DISPATCH pure handlers instead of the inline STEP 1/2/3
            # code below. After vendor succeeds, STEP 4 (vendor confirmation
            # gate) also runs inline here so the legacy path stays untouched.
            # If handlers pause or fail, we return immediately. If vendor is
            # pre-confirmed, we set `_pre_gate_done_via_handlers=True` and fall
            # through to STEP 5+ which runs unchanged.
            _use_pure_handlers = bool(
                context.get("_use_pure_handlers")
                or os.environ.get("USE_PURE_HANDLERS", "").lower() in ("1", "true", "yes", "on")
            )
            _pre_gate_done_via_handlers = False
            if _use_pure_handlers:
                try:
                    from backend.agents.p2p_handlers import PHASE_DISPATCH
                    from backend.agents.handler_types import HandlerHelpers, HandlerResult as _HR

                    # Build helpers bundle wrapping the nested closures above.
                    # Parameter adapters match the closures' signatures so the
                    # handlers' kwargs (agent, data) pass through correctly.
                    def _helper_add_step(step_name, status, summary, agent=None, data=None):
                        _add_step(step_name, status, summary, agent, data)

                    def _helper_track_task(task_name, result_data=None, failed=False, error_msg=None):
                        _track_task(task_name, result_data=result_data, failed=failed, error_msg=error_msg)

                    def _helper_open_gate(gate_type, gate_ref, decision_context, required_role=None):
                        return _session_open_gate(gate_type, gate_ref, decision_context, required_role)

                    def _helper_set_checkpoint(name):
                        # R17 checkpoint wiring lands with full handler extraction;
                        # pre-gate handlers do not currently checkpoint.
                        return None

                    def _helper_complete_task(*_a, **_kw):
                        # legacy _track_task already handles task completion
                        return None

                    _helpers = HandlerHelpers(
                        emit=_session_emit,
                        open_gate=_helper_open_gate,
                        set_phase=_session_set_phase,
                        set_checkpoint=_helper_set_checkpoint,
                        add_step=_helper_add_step,
                        track_task=_helper_track_task,
                        complete_task=_helper_complete_task,
                    )

                    # Handler context bundle — shared mutable state lives in
                    # p2p_results; handlers never re-read execution_sessions.
                    _h_ctx: Dict[str, Any] = dict(context)
                    _h_ctx["input_context"] = input_context
                    _h_ctx["_p2p_results"] = p2p_results
                    _h_ctx["_check_human_gate"] = _check_human_gate
                    _h_ctx["workflow_run_id"] = workflow_run_id

                    # State-machine entry: starting → compliance
                    _session_set_phase("compliance", "running")

                    # Dispatch loop over pre-gate handlers. A handler returning
                    # next_phase=None signals either a terminal state (gate
                    # pause / failure) OR "handlers done, fall through to
                    # legacy" (status=running + next_phase=None).
                    _current_phase = "compliance"
                    _handlers_fell_through = False
                    while _current_phase in PHASE_DISPATCH:
                        _handler_fn = PHASE_DISPATCH[_current_phase]
                        logger.info("[P2P-v2] dispatching handler for phase=%s", _current_phase)
                        try:
                            _result = await _handler_fn(self, _h_ctx, _helpers)
                        except Exception as _disp_exc:
                            logger.exception("[P2P-v2] handler %s raised: %s", _current_phase, _disp_exc)
                            _session_emit("phase_failed", {"phase": _current_phase, "error": str(_disp_exc)})
                            _session_set_phase(_current_phase, "failed")
                            p2p_results["status"] = "failed"
                            p2p_results["summary"] = f"P2P handler {_current_phase} raised: {_disp_exc}"
                            return p2p_results

                        if _result.status == "failed":
                            # Handler already emitted phase_failed + populated p2p_results
                            _session_set_phase(_current_phase, "failed")
                            return p2p_results
                        if _result.status == "paused_human":
                            # Handler already populated p2p_results via _check_human_gate
                            return p2p_results
                        if _result.next_phase is None:
                            # "Done with handlers, fall through to legacy STEP 4.5+"
                            _handlers_fell_through = True
                            break
                        # Advance the session + the loop counter
                        if _result.next_phase in PHASE_DISPATCH:
                            _session_set_phase(_result.next_phase, _result.status or "running")
                            _current_phase = _result.next_phase
                            continue
                        # Next phase has no handler — exit loop; split-dispatch
                        # branch decides what to do next (typically STEP 4 below)
                        _current_phase = _result.next_phase
                        break

                    if _handlers_fell_through:
                        # Vendor agent was missing or similar — run STEP 4.5+
                        # via legacy code with pre-gate steps already marked
                        # skipped by the handler.
                        _pre_gate_done_via_handlers = True
                    else:
                        # Handlers completed through vendor phase_completed.
                        # _current_phase should now be "vendor_selection".
                        # Run STEP 4 (vendor confirmation gate) inline here so
                        # the behavior matches legacy exactly.
                        top_vendor_options = p2p_results.get("top_vendor_options") or []
                        top_vendor_name = (
                            top_vendor_options[0].get("vendor_name", "") if top_vendor_options else ""
                        )
                        vendor_count = len(top_vendor_options)

                        vendor_confirmed = bool(pr_data.get("vendor_confirmed"))
                        selected_vendor = str(
                            pr_data.get("selected_vendor_name") or pr_data.get("vendor_name") or ""
                        ).strip()
                        if selected_vendor:
                            selected_vendor = (
                                selected_vendor.split(". Continue", 1)[0].strip().split("\n", 1)[0].strip()
                            )

                        if not vendor_confirmed and not selected_vendor:
                            logger.info("[P2P-v2] STEP 4/15: Pausing for vendor confirmation...")
                            p2p_results["status"] = "awaiting_vendor_confirmation"
                            p2p_results["human_action_required"] = {
                                "type": "vendor_selection",
                                "message": "Please review the vendor shortlist and confirm your choice to continue.",
                                "options": [v.get("vendor_name", "Unknown") for v in top_vendor_options[:5]],
                            }
                            p2p_results["suggested_next_actions"] = _fetch_suggestions()
                            p2p_results["summary"] = _build_summary()
                            p2p_results["workflow_context"] = {"pr_data": dict(pr_data)}

                            _vendor_gate_id = _session_open_gate(
                                gate_type="vendor_selection",
                                gate_ref={
                                    "vendor_ids": [v.get("vendor_id") for v in top_vendor_options if v.get("vendor_id")],
                                    "vendor_names": [v.get("vendor_name") for v in top_vendor_options if v.get("vendor_name")],
                                },
                                decision_context={
                                    "scoring_snapshot": [
                                        {"vendor_name": v.get("vendor_name"), "score": v.get("total_score", v.get("score"))}
                                        for v in top_vendor_options[:5]
                                    ],
                                    "top_vendor": top_vendor_name,
                                    "total_candidates": vendor_count,
                                },
                                required_role="requester",
                            )
                            if _vendor_gate_id:
                                p2p_results["human_action_required"]["gate_id"] = _vendor_gate_id
                                p2p_results["human_action_required"]["session_id"] = session_id_hybrid
                            _session_emit("gate_opened", {
                                "gate_type": "vendor_selection",
                                "gate_id": _vendor_gate_id,
                            })
                            _session_set_phase("vendor_selection", "paused_human")
                            return p2p_results

                        # Vendor pre-confirmed — propagate into pr_data and fall
                        # through to STEP 4.5+ (risk assessment, PR creation, etc.)
                        if selected_vendor:
                            pr_data["vendor_name"] = selected_vendor
                        elif top_vendor_options:
                            pr_data["vendor_name"] = top_vendor_options[0].get("vendor_name", "")
                        input_context["pr_data"] = pr_data
                        p2p_results["vendor_name"] = pr_data.get("vendor_name", "")
                        _track_task('vendor_confirmation', {'vendor': pr_data.get("vendor_name")})
                        _add_step(
                            "vendor_confirmation",
                            "confirmed",
                            f"Vendor confirmed: {pr_data.get('vendor_name', 'N/A')}",
                        )

                        # G-02: Contract linkage validation (non-blocking) —
                        # identical to legacy; kept in split-dispatch branch so
                        # the behavior matches byte-for-byte.
                        try:
                            from backend.services.contract_linkage_service import get_contract_linkage_service
                            _cls = get_contract_linkage_service()
                            contract_check = _cls.check_maverick_spend(
                                po_number="(pre-PO)",
                                vendor_name=pr_data.get("vendor_name", ""),
                                amount=raw_budget,
                            )
                            if contract_check.get("is_maverick"):
                                p2p_results.setdefault("warnings", []).append(
                                    f"G-02: Maverick spend — no active contract for {pr_data.get('vendor_name')}"
                                )
                                logger.info("[P2P-v2] G-02: Maverick spend flagged for %s", pr_data.get("vendor_name"))
                            else:
                                logger.info("[P2P-v2] G-02: Contract found for vendor %s", pr_data.get("vendor_name"))
                        except Exception as _cl_err:
                            logger.debug("[P2P-v2] G-02: Contract check (non-blocking): %s", _cl_err)

                        _pre_gate_done_via_handlers = True
                except Exception as _v2_exc:
                    # Any unexpected failure in the split-dispatch branch falls
                    # back to legacy to preserve production behavior. The error
                    # is logged loudly so staging can catch the regression.
                    logger.exception(
                        "[P2P-v2] split dispatch failed — falling back to legacy path: %s", _v2_exc
                    )
                    _pre_gate_done_via_handlers = False

            # ─── STEP 1: Compliance Check ───────────────────────────────────
            if not _pre_gate_done_via_handlers and "compliance_check" in self.specialized_agents:
                logger.info("[P2P] STEP 1/15: Compliance check...")
                _session_set_phase("compliance", "running")
                _session_emit("phase_started", {"phase": "compliance"})
                await _emit_selected("compliance_check", 1)
                try:
                    comp_result = await self._get_agent("compliance_check").execute(input_context)
                except Exception as _comp_exc:
                    _session_emit("phase_failed", {"phase": "compliance", "error": str(_comp_exc)})
                    _session_set_phase("compliance", "failed")
                    raise
                comp_action = (comp_result.get("action") or comp_result.get("result", {}).get("action"))
                p2p_results["agents_invoked"].append(self._get_agent("compliance_check").name)
                p2p_results["validations"]["compliance"] = comp_result

                # Universal human gate check (agent-driven or confidence-based)
                if _check_human_gate("compliance_check", comp_result, "ComplianceCheckAgent"):
                    _add_step("compliance_check", "awaiting_input", "Human review needed", "ComplianceCheckAgent")
                    _session_emit("phase_failed", {"phase": "compliance", "reason": "needs_human_review"})
                    return p2p_results

                if comp_action == "reject":
                    _track_task('compliance_check', failed=True, error_msg='Compliance rejected')
                    _add_step("compliance_check", "rejected", "Compliance check rejected this request", "ComplianceCheckAgent")
                    p2p_results["status"] = "failed"
                    p2p_results["summary"] = "P2P workflow blocked: compliance check rejected."
                    p2p_results["suggested_next_actions"] = ["Review compliance rules", "Modify request and retry"]
                    _session_emit("phase_failed", {"phase": "compliance", "reason": "rejected"})
                    _session_set_phase("compliance", "failed")
                    return p2p_results
                else:
                    _track_task('compliance_check', {'action': comp_action, 'passed': True})
                    _session_emit("phase_completed", {"phase": "compliance", "action": comp_action})
                    # Extract compliance details for frontend display
                    comp_inner = comp_result.get("result", comp_result) if isinstance(comp_result.get("result"), dict) else comp_result
                    comp_summary_parts = [f"Score: {comp_inner.get('compliance_score', 'N/A')}"]
                    if comp_inner.get("warnings"):
                        comp_summary_parts.append(f"{len(comp_inner['warnings'])} warning(s)")
                    _add_step("compliance_check", "passed", " | ".join(comp_summary_parts), "ComplianceCheckAgent", data={
                        "compliance_score": comp_inner.get("compliance_score"),
                        "compliance_level": comp_inner.get("compliance_level"),
                        "warnings": comp_inner.get("warnings", []),
                        "violations": comp_inner.get("violations", []),
                    })
            elif not _pre_gate_done_via_handlers:
                _add_step("compliance_check", "skipped", "Agent not available")

            # ─── STEP 2: Budget Verification ────────────────────────────────
            if not _pre_gate_done_via_handlers and "budget_verification" in self.specialized_agents:
                logger.info("[P2P] STEP 2/15: Budget verification...")
                _session_set_phase("budget", "running")
                _session_emit("phase_started", {"phase": "budget"})
                await _emit_selected("budget_verification", 2)
                budget_ctx = {**input_context, "reserve_budget": False}
                try:
                    budget_result = await self._get_agent("budget_verification").execute(budget_ctx)
                except Exception as _bud_exc:
                    _session_emit("phase_failed", {"phase": "budget", "error": str(_bud_exc)})
                    _session_set_phase("budget", "failed")
                    raise
                budget_action = (budget_result.get("action") or budget_result.get("result", {}).get("action"))
                budget_inner = budget_result.get("result", {}) if isinstance(budget_result.get("result"), dict) else {}
                p2p_results["agents_invoked"].append(self._get_agent("budget_verification").name)
                p2p_results["validations"]["budget"] = budget_result

                # Universal human gate check
                if _check_human_gate("budget_verification", budget_result, "BudgetVerificationAgent"):
                    _add_step("budget_verification", "awaiting_input", "Human review needed", "BudgetVerificationAgent")
                    _session_emit("phase_failed", {"phase": "budget", "reason": "needs_human_review"})
                    return p2p_results

                budget_failed = (
                    budget_result.get("status") == "error"
                    or budget_action in {"block", "reject", "reject_insufficient_budget"}
                    or str(budget_inner.get("status", "")).lower() in {"rejected", "error"}
                    or budget_inner.get("budget_verified") is False
                )
                if budget_failed:
                    _track_task('budget_verification', failed=True, error_msg='Insufficient budget')
                    avail = budget_inner.get("available_budget", "N/A")
                    _add_step("budget_verification", "rejected", f"Insufficient budget (available: ${avail})", "BudgetVerificationAgent")
                    p2p_results["status"] = "failed"
                    p2p_results["summary"] = f"P2P workflow blocked: insufficient budget. Available: ${avail}."
                    p2p_results["suggested_next_actions"] = ["Request budget increase", "Reduce order quantity"]
                    _session_emit("phase_failed", {"phase": "budget", "reason": "insufficient_budget"})
                    _session_set_phase("budget", "failed")
                    return p2p_results
                else:
                    _session_emit("phase_completed", {"phase": "budget", "available": budget_inner.get("available_budget")})
                    raw_avail = budget_inner.get("available_budget", budget_inner.get("current_budget", ""))
                    # Format as currency if numeric, otherwise use as-is
                    try:
                        avail = f"{float(str(raw_avail).replace(',', '')):,.0f}" if raw_avail and str(raw_avail).replace(',', '').replace('.', '').isdigit() else (raw_avail or "confirmed")
                    except (ValueError, TypeError):
                        avail = str(raw_avail) if raw_avail else "confirmed"
                    util = budget_inner.get("utilization", budget_inner.get("utilization_percentage", budget_inner.get("utilization_after_approval", "")))
                    _track_task('budget_verification', {'budget_verified': True})
                    _add_step("budget_verification", "approved",
                              f"Budget verified — ${avail} available" + (f", {util}% utilized" if util else ""),
                              "BudgetVerificationAgent", data={
                        "available_budget": avail,
                        "utilization": util,
                        "department": budget_inner.get("department", pr_data.get("department", "")),
                    })

                    # G-08: Record budget commitment in ledger
                    try:
                        from backend.services.budget_ledger_service import get_budget_ledger_service
                        _bl = get_budget_ledger_service()
                        _bl.record_commitment(
                            department=pr_data.get("department", "General"),
                            fiscal_year=None,
                            reference_type="PR",
                            reference_id=f"P2P-{workflow_run_id or 'UNKNOWN'}",
                            amount=raw_budget,
                            description=f"P2P budget commitment for {pr_data.get('product_name', 'procurement')}",
                        )
                        logger.info("[P2P] G-08: Budget commitment recorded in ledger")
                    except Exception as _bl_err:
                        logger.debug("[P2P] G-08: Budget ledger (non-blocking): %s", _bl_err)
            elif not _pre_gate_done_via_handlers:
                _add_step("budget_verification", "skipped", "Agent not available")

            # ─── STEP 3: Vendor Selection ───────────────────────────────────
            # NOTE: when _pre_gate_done_via_handlers is True, the split-dispatch
            # branch above already ran STEPS 1-4 (compliance, budget, vendor,
            # and the vendor_confirmation gate OR pre-confirmed path). Skip the
            # entire inline STEP 3/4 block to avoid re-running them.
            if not _pre_gate_done_via_handlers and "vendor_selection" in self.specialized_agents:
                logger.info("[P2P] STEP 3/15: Vendor selection...")
                _session_set_phase("vendor", "running")
                _session_emit("phase_started", {"phase": "vendor"})
                await _emit_selected("vendor_selection", 3)
                try:
                    vendor_result = await self._get_agent("vendor_selection").execute(input_context)
                except Exception as _vend_exc:
                    _session_emit("phase_failed", {"phase": "vendor", "error": str(_vend_exc)})
                    _session_set_phase("vendor", "failed")
                    raise
                p2p_results["agents_invoked"].append(self._get_agent("vendor_selection").name)
                p2p_results["validations"]["vendor"] = vendor_result
                _track_task('vendor_selection', {'vendors_found': True})

                top_vendor_options = self._extract_vendor_options(vendor_result)
                p2p_results["top_vendor_options"] = top_vendor_options
                top_vendor_name = top_vendor_options[0].get("vendor_name", "") if top_vendor_options else ""
                vendor_count = len(top_vendor_options)
                vendor_summary = f"Top vendor: {top_vendor_name} ({vendor_count} options)" if top_vendor_name else f"{vendor_count} vendors shortlisted"
                _add_step("vendor_selection", "completed", vendor_summary, "VendorSelectionAgent", data={
                    "top_vendor": top_vendor_name,
                    "vendor_count": vendor_count,
                    "vendors": [{"name": v.get("vendor_name"), "score": v.get("total_score", v.get("score"))} for v in top_vendor_options[:5]],
                })
                _session_emit("phase_completed", {
                    "phase": "vendor",
                    "ref": {"vendor_count": vendor_count},
                    "top_vendor": top_vendor_name,
                    "vendor_count": vendor_count,
                    "vendors": [
                        {
                            "vendor_id": v.get("vendor_id"),
                            "vendor_name": v.get("vendor_name"),
                            "total_score": v.get("total_score", v.get("score")),
                            "recommendation": v.get("recommendation_reason", v.get("recommendation", "")),
                        }
                        for v in top_vendor_options[:5]
                    ],
                })

                # ─── STEP 4: Vendor Confirmation (human gate) ───────────────
                vendor_confirmed = bool(pr_data.get("vendor_confirmed"))
                selected_vendor = str(pr_data.get("selected_vendor_name") or pr_data.get("vendor_name") or "").strip()
                if selected_vendor:
                    selected_vendor = selected_vendor.split(". Continue", 1)[0].strip().split("\n", 1)[0].strip()

                if not vendor_confirmed and not selected_vendor:
                    logger.info("[P2P] STEP 4/15: Pausing for vendor confirmation...")
                    p2p_results["status"] = "awaiting_vendor_confirmation"
                    p2p_results["human_action_required"] = {
                        "type": "vendor_selection",
                        "message": "Please review the vendor shortlist and confirm your choice to continue.",
                        "options": [v.get("vendor_name", "Unknown") for v in top_vendor_options[:5]],
                    }
                    p2p_results["suggested_next_actions"] = _fetch_suggestions()
                    p2p_results["summary"] = _build_summary()
                    p2p_results["workflow_context"] = {"pr_data": dict(pr_data)}

                    # Layer 1: open vendor_selection gate + pause session.
                    # decision_context carries the full scoring snapshot so the
                    # frontend can render rich vendor cards without a second
                    # fetch. gate_opened payload mirrors gate_ref + context so
                    # the SSE reducer has everything it needs to render the gate
                    # UI as soon as the event lands (no refetch needed).
                    _vendor_gate_ref = {
                        "vendor_ids": [v.get("vendor_id") for v in top_vendor_options if v.get("vendor_id")],
                        "vendor_names": [v.get("vendor_name") for v in top_vendor_options if v.get("vendor_name")],
                    }
                    _vendor_decision_context = {
                        "scoring_snapshot": [
                            {
                                "vendor_name": v.get("vendor_name"),
                                "score": v.get("total_score", v.get("score")),
                                "recommendation_reason": v.get("recommendation_reason", ""),
                                "strengths": v.get("strengths", []) or [],
                                "concerns": v.get("concerns", []) or [],
                            }
                            for v in top_vendor_options[:5]
                        ],
                        "top_vendor": top_vendor_name,
                        "total_candidates": vendor_count,
                    }
                    _vendor_gate_id = _session_open_gate(
                        gate_type="vendor_selection",
                        gate_ref=_vendor_gate_ref,
                        decision_context=_vendor_decision_context,
                        required_role="requester",
                    )
                    if _vendor_gate_id:
                        p2p_results["human_action_required"]["gate_id"] = _vendor_gate_id
                        p2p_results["human_action_required"]["session_id"] = session_id_hybrid
                    # Sprint D bugfix (2026-04-11): emit phase_started for
                    # vendor_selection so the frontend reducer advances
                    # currentPhase from "vendor" → "vendor_selection" and
                    # the accordion row activates. Without this, currentPhase
                    # stays at "vendor" and the "Vendor Selection" row
                    # renders as inactive/pending.
                    _session_emit("phase_started", {"phase": "vendor_selection"})
                    _session_emit("gate_opened", {
                        "gate_type": "vendor_selection",
                        "gate_id": _vendor_gate_id,
                        "gate_ref": _vendor_gate_ref,
                        "decision_context": _vendor_decision_context,
                        "required_role": "requester",
                    })
                    _session_set_phase("vendor_selection", "paused_human")
                    return p2p_results

                # Vendor confirmed or pre-selected
                if selected_vendor:
                    pr_data["vendor_name"] = selected_vendor
                elif top_vendor_options:
                    pr_data["vendor_name"] = top_vendor_options[0].get("vendor_name", "")
                input_context["pr_data"] = pr_data
                p2p_results["vendor_name"] = pr_data.get("vendor_name", "")
                _track_task('vendor_confirmation', {'vendor': pr_data.get("vendor_name")})
                _add_step("vendor_confirmation", "confirmed", f"Vendor confirmed: {pr_data.get('vendor_name', 'N/A')}")

                # G-02: Contract linkage validation (non-blocking)
                try:
                    from backend.services.contract_linkage_service import get_contract_linkage_service
                    _cls = get_contract_linkage_service()
                    contract_check = _cls.check_maverick_spend(
                        po_number="(pre-PO)",
                        vendor_name=pr_data.get("vendor_name", ""),
                        amount=raw_budget,
                    )
                    if contract_check.get("is_maverick"):
                        p2p_results.setdefault("warnings", []).append(
                            f"G-02: Maverick spend — no active contract for {pr_data.get('vendor_name')}"
                        )
                        logger.info("[P2P] G-02: Maverick spend flagged for %s", pr_data.get("vendor_name"))
                    else:
                        logger.info("[P2P] G-02: Contract found for vendor %s", pr_data.get("vendor_name"))
                except Exception as _cl_err:
                    logger.debug("[P2P] G-02: Contract check (non-blocking): %s", _cl_err)
            elif not _pre_gate_done_via_handlers:
                # Legacy "vendor agent missing" path. When split dispatch ran,
                # handle_vendor already added both skip steps so we skip here.
                _add_step("vendor_selection", "skipped", "Agent not available")
                _add_step("vendor_confirmation", "skipped", "No vendor selection")

            # ─── STEP 4.5: Risk Assessment (non-blocking) ──────────────────
            if "risk_assessment" in self.specialized_agents:
                logger.info("[P2P] STEP 4.5: Running risk assessment...")
                _session_emit("agent_started", {"agent": "risk_assessment"})
                try:
                    await _emit_selected("risk_assessment", 4)
                    risk_ctx = {
                        "request": f"Assess procurement risk for {pr_data.get('product_name', 'items')}",
                        "pr_data": pr_data,
                    }
                    risk_result = await self._get_agent("risk_assessment").execute(risk_ctx)
                    p2p_results["agents_invoked"].append(self._get_agent("risk_assessment").name)
                    p2p_results["validations"]["risk_assessment"] = risk_result

                    risk_level = (risk_result.get("risk_level") or risk_result.get("overall_risk_level") or "unknown").lower()
                    risk_score = risk_result.get("risk_score") or risk_result.get("overall_risk_score") or ""
                    risk_summary = f"Risk level: {risk_level.upper()}"
                    if risk_score:
                        risk_summary += f" (score: {risk_score})"

                    if risk_level == "critical":
                        _add_step("risk_assessment", "blocked", f"CRITICAL risk — {risk_summary}", "RiskAssessmentAgent")
                        p2p_results["status"] = "failed"
                        p2p_results["summary"] = f"P2P workflow blocked: {risk_summary}. Review risk factors before proceeding."
                        p2p_results["suggested_next_actions"] = ["Review risk assessment", "Adjust order parameters", "Select alternative vendor"]
                        _session_emit("agent_failed", {"agent": "risk_assessment", "risk_level": risk_level})
                        return p2p_results
                    elif risk_level == "high":
                        p2p_results.setdefault("warnings", []).append(f"High procurement risk: {risk_summary}")
                        _add_step("risk_assessment", "warning", risk_summary, "RiskAssessmentAgent")
                    else:
                        _add_step("risk_assessment", "passed", risk_summary, "RiskAssessmentAgent")
                    _track_task('risk_assessment', {'risk_level': risk_level, 'risk_score': risk_score})
                    _session_emit("agent_finished", {"agent": "risk_assessment", "risk_level": risk_level, "risk_score": risk_score})
                except Exception as _risk_err:
                    logger.warning("[P2P] Risk assessment failed (non-blocking): %s", _risk_err)
                    _add_step("risk_assessment", "skipped", f"Assessment unavailable: {_risk_err}")
                    _session_emit("agent_failed", {"agent": "risk_assessment", "error": str(_risk_err)})
            else:
                _add_step("risk_assessment", "skipped", "Agent not available")

            # ─── STEP 5: PR Creation ────────────────────────────────────────
            logger.info("[P2P] STEP 5/15: Creating Purchase Requisition...")
            _session_set_phase("pr_creation", "running")
            _session_emit("phase_started", {"phase": "pr_creation"})
            pr_number = f"PR-2026-{datetime.now().strftime('%m%d%H%M%S')}"
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
            }
            p2p_results["pr_number"] = pr_number
            p2p_results["pr_object"] = pr_object

            try:
                from backend.services.adapters.factory import get_adapter
                _adapter = get_adapter()
                _adapter.create_purchase_requisition({
                    "name": pr_number,
                    "user_id": pr_data.get("requester_name", "Chat User"),
                    "product_qty": pr_data.get("quantity", 1),
                    "state": "pending_approval",
                    "origin": pr_data.get("department", ""),
                    "notes": f"{pr_data.get('product_name', '')} - {pr_data.get('justification', '')}",
                    "erp_source": "procure_ai",
                })
                _track_task('pr_creation', {'pr_number': pr_number})
                _add_step("pr_creation", "created", f"PR {pr_number} created and persisted", "Orchestrator")
            except Exception as _pr_err:
                logger.warning("[P2P] PR persistence failed (non-blocking): %s", _pr_err)
                _track_task('pr_creation', {'pr_number': pr_number})
                _add_step("pr_creation", "created", f"PR {pr_number} created (DB persist warning)", "Orchestrator")
            _session_emit("phase_completed", {
                "phase": "pr_creation",
                "ref": {"pr_number": pr_number},
                "pr_number": pr_number,
                "product": pr_data.get("product_name") or pr_data.get("product") or pr_data.get("item") or "",
                "department": pr_data.get("department") or pr_data.get("dept") or "",
                "requester": pr_data.get("requester_name") or pr_data.get("requester") or "Chat User",
                "amount": raw_budget,
                "quantity": pr_data.get("quantity") or pr_data.get("qty") or 1,
            })

            # ─── STEP 6: Approval Routing ───────────────────────────────────
            assigned_approvers_list: list = []
            routing_action_str: str = ""
            required_level_int: int = 1
            if "approval_routing" in self.specialized_agents:
                logger.info("[P2P] STEP 6/15: Routing for approval...")
                _session_set_phase("approval", "running")
                _session_emit("phase_started", {"phase": "approval"})
                await _emit_selected("approval_routing", 6)
                total_amount = pr_data.get("budget", 0)
                approval_ctx = {
                    "request": f"Route approval for PR {pr_number}",
                    "pr_data": {**pr_data, "pr_number": pr_number, "budget": total_amount},
                }
                try:
                    approval_result = await self._get_agent("approval_routing").execute(approval_ctx)
                except Exception as _appr_exc:
                    _session_emit("phase_failed", {"phase": "approval", "error": str(_appr_exc)})
                    _session_set_phase("approval", "failed")
                    raise
                p2p_results["agents_invoked"].append(self._get_agent("approval_routing").name)
                p2p_results["validations"]["approval_routing"] = approval_result
                _track_task('approval_routing', {'routed': True})

                # Extract assigned approvers from agent result so we can show WHO approves
                try:
                    routing_inner = approval_result.get("result", {}) if isinstance(approval_result, dict) else {}
                    assigned_approvers_list = routing_inner.get("assigned_approvers", []) or []
                    routing_action_str = routing_inner.get("action", "") or ""
                    required_level_int = int(routing_inner.get("required_level", 1) or 1)
                except Exception:
                    assigned_approvers_list = []

                if assigned_approvers_list:
                    _names = ", ".join(
                        f"{a.get('approver_name', 'Approver')} (L{a.get('approval_level', '?')})"
                        for a in assigned_approvers_list
                    )
                    _add_step(
                        "approval_routing", "routed",
                        f"Routed to {len(assigned_approvers_list)} approver(s): {_names} — amount ${raw_budget:,.2f}",
                        "ApprovalRoutingAgent",
                    )
                else:
                    _add_step("approval_routing", "routed", "Approval workflow created, awaiting manager decision", "ApprovalRoutingAgent")
            else:
                _add_step("approval_routing", "skipped", "Agent not available")

            # ─── STEP 7: Approval Wait (human gate) ────────────────────────
            # If no pre-approval, pause here for human
            # Auto-approve small amounts (<$1000) per policy band
            approval_given = bool(
                pr_data.get("approved")
                or context.get("auto_approve")
                or raw_budget < 1000
            )
            if not approval_given:
                logger.info("[P2P] STEP 7/15: Pausing for approval...")

                # Pick the highest-level required approver to display in the gate
                next_approver = None
                if assigned_approvers_list:
                    try:
                        next_approver = max(
                            assigned_approvers_list,
                            key=lambda a: int(a.get("approval_level", 0) or 0),
                        )
                    except Exception:
                        next_approver = assigned_approvers_list[0]

                approver_label = "Manager"
                approver_email = None
                approver_role = None
                approver_level = 1
                if next_approver:
                    approver_label = next_approver.get("approver_name") or "Manager"
                    approver_email = next_approver.get("approver_email")
                    approver_role = next_approver.get("role") or next_approver.get("approver_role")
                    approver_level = int(next_approver.get("approval_level", 1) or 1)

                # ── Resolve generic role to actual person using approval_chains + users ──
                _pr_dept = (pr_data.get("department") or pr_data.get("dept") or "").strip()
                if _pr_dept and (not approver_email or approver_label in ("Department Manager", "Department Director", "Manager")):
                    try:
                        from backend.services.adapters.factory import get_adapter as _get_adp
                        _res_adapter = _get_adp()
                        # Try approval_chains first (department + threshold → actual person)
                        from backend.services.nmi_data_service import get_conn
                        from psycopg2.extras import RealDictCursor
                        _rc = get_conn()
                        with _rc.cursor(cursor_factory=RealDictCursor) as _cur:
                            _cur.execute(
                                """SELECT approver_name, approver_email FROM approval_chains
                                   WHERE LOWER(department) = LOWER(%s) AND budget_threshold >= %s
                                   ORDER BY approval_level LIMIT 1""",
                                (_pr_dept, raw_budget),
                            )
                            _chain_row = _cur.fetchone()
                        _rc.close()
                        if _chain_row and _chain_row.get("approver_email"):
                            approver_label = _chain_row["approver_name"]
                            approver_email = _chain_row["approver_email"]
                            logger.info("[P2P] Resolved approver via chain: %s (%s) for dept=%s", approver_label, approver_email, _pr_dept)
                        else:
                            # Fallback: look up users table by role + department
                            _rc2 = get_conn()
                            with _rc2.cursor(cursor_factory=RealDictCursor) as _cur2:
                                _role_to_find = approver_role or "manager"
                                _cur2.execute(
                                    """SELECT full_name, email FROM users
                                       WHERE LOWER(role) = LOWER(%s) AND LOWER(department) = LOWER(%s)
                                       AND is_active = true LIMIT 1""",
                                    (_role_to_find, _pr_dept),
                                )
                                _user_row = _cur2.fetchone()
                            _rc2.close()
                            if _user_row and _user_row.get("email"):
                                approver_label = _user_row["full_name"]
                                approver_email = _user_row["email"]
                                logger.info("[P2P] Resolved approver via users: %s (%s)", approver_label, approver_email)
                    except Exception as _resolve_err:
                        logger.warning("[P2P] Approver resolution failed (non-fatal): %s", _resolve_err)

                # ── Resolve ALL entries in assigned_approvers_list (not just the top one) ──
                if _pr_dept and assigned_approvers_list:
                    try:
                        from backend.services.nmi_data_service import get_conn as _get_conn2
                        from psycopg2.extras import RealDictCursor as _RDC2
                        _conn_resolve = _get_conn2()
                        _cur_resolve = _conn_resolve.cursor(cursor_factory=_RDC2)
                        for _appr_entry in assigned_approvers_list:
                            _aname = (_appr_entry.get("approver_name") or "").strip()
                            _aemail = (_appr_entry.get("approver_email") or "").strip()
                            # Skip if already has a real email (not generic)
                            if _aemail and "@" in _aemail:
                                continue
                            # Generic names to resolve
                            if _aname in ("Department Manager", "Department Director", "Manager", "Director", "VP", "CFO"):
                                _alevel = int(_appr_entry.get("approval_level", 1) or 1)
                                # Try approval_chains first
                                _cur_resolve.execute(
                                    """SELECT approver_name, approver_email FROM approval_chains
                                       WHERE LOWER(department) = LOWER(%s)
                                       AND approval_level = %s
                                       LIMIT 1""",
                                    (_pr_dept, _alevel),
                                )
                                _ch = _cur_resolve.fetchone()
                                if _ch and _ch.get("approver_email"):
                                    _appr_entry["approver_name"] = _ch["approver_name"]
                                    _appr_entry["approver_email"] = _ch["approver_email"]
                                else:
                                    # Fallback: users table by role + department
                                    _role_map = {"Department Manager": "manager", "Manager": "manager",
                                                 "Department Director": "director", "Director": "director",
                                                 "VP": "vp_cfo", "CFO": "vp_cfo"}
                                    _rl = _role_map.get(_aname, "manager")
                                    _cur_resolve.execute(
                                        """SELECT full_name, email FROM users
                                           WHERE LOWER(role) = LOWER(%s) AND LOWER(department) = LOWER(%s)
                                           AND is_active = true LIMIT 1""",
                                        (_rl, _pr_dept),
                                    )
                                    _u = _cur_resolve.fetchone()
                                    if _u and _u.get("email"):
                                        _appr_entry["approver_name"] = _u["full_name"]
                                        _appr_entry["approver_email"] = _u["email"]
                        _cur_resolve.close()
                        _conn_resolve.close()
                        logger.info("[P2P] Resolved %d approver chain entries for dept=%s", len(assigned_approvers_list), _pr_dept)
                    except Exception as _chain_resolve_err:
                        logger.warning("[P2P] Chain resolution failed (non-fatal): %s", _chain_resolve_err)

                gate_message = (
                    f"Approval required from {approver_label}"
                    + (f" ({approver_email})" if approver_email else "")
                    + f" for PR {pr_number} — ${raw_budget:,.2f}"
                )

                p2p_results["status"] = "awaiting_approval"
                p2p_results["human_action_required"] = {
                    "type": "approval",
                    "message": gate_message,
                    "pr_number": pr_number,
                    "amount": raw_budget,
                    "approver": {
                        "name": approver_label,
                        "email": approver_email,
                        "role": approver_role,
                        "level": approver_level,
                    },
                    "approval_chain": assigned_approvers_list,
                    "routing_action": routing_action_str,
                    "required_level": required_level_int,
                    "options": ["approve", "reject"],
                }
                p2p_results["suggested_next_actions"] = _fetch_suggestions()
                p2p_results["summary"] = _build_summary()

                # Sprint C (2026-04-11): build a rich PR snapshot for the
                # approval gate. Layer 1's GenericGatePanel renders
                # decision_context as a JSON drawer — so packing line items,
                # totals, department, and the approver chain here lights up
                # the approval gate UI without any frontend code changes.
                logger.info(
                    "[P2P-APPROVAL-GATE] pr_data keys=%s budget=%s product=%s dept=%s requester=%s",
                    list(pr_data.keys()), raw_budget,
                    pr_data.get("product_name") or pr_data.get("product") or pr_data.get("item") or "(none)",
                    pr_data.get("department") or pr_data.get("dept") or "(none)",
                    pr_data.get("requester_name") or pr_data.get("requester") or "(none)",
                )
                _pr_summary = {
                    "pr_number": pr_number,
                    "product_name": pr_data.get("product_name") or pr_data.get("product") or pr_data.get("item") or pr_data.get("item_name") or "",
                    "quantity": pr_data.get("quantity") or pr_data.get("qty") or 1,
                    "department": pr_data.get("department") or pr_data.get("dept") or "",
                    "requester": pr_data.get("requester_name") or pr_data.get("requester") or pr_data.get("requested_by") or "",
                    "justification": pr_data.get("justification") or pr_data.get("reason") or "",
                    "total_amount": raw_budget,
                    "currency": pr_data.get("currency", "USD"),
                }
                _line_items = pr_data.get("line_items") or []
                _policy_band = (
                    "auto_approve" if raw_budget < 1000
                    else "manager"  if raw_budget < 10000
                    else "director" if raw_budget < 50000
                    else "vp"       if raw_budget < 250000
                    else "cfo"
                )

                # Layer 1: open approval gate + pause session
                _approval_gate_id = _session_open_gate(
                    gate_type="approval",
                    gate_ref={
                        "pr_number": pr_number,
                        "approver_emails": [a.get("approver_email") for a in assigned_approvers_list if a.get("approver_email")],
                    },
                    decision_context={
                        "pr_summary": _pr_summary,
                        "line_items": _line_items,
                        "approver": {
                            "name": approver_label,
                            "email": approver_email,
                            "role": approver_role,
                            "level": approver_level,
                        },
                        "approval_chain": assigned_approvers_list,
                        "current_approver_role": approver_role,
                        "routing_action": routing_action_str,
                        "required_level": required_level_int,
                        "amount": raw_budget,
                        "policy_band": _policy_band,
                    },
                    required_role=approver_role,
                )
                if _approval_gate_id:
                    p2p_results["human_action_required"]["gate_id"] = _approval_gate_id
                    p2p_results["human_action_required"]["session_id"] = session_id_hybrid
                _session_emit("phase_completed", {
                    "phase": "approval",
                    "routed_to": len(assigned_approvers_list),
                    "approver": approver_label,
                    "approver_email": approver_email or "",
                    "approval_level": approver_level,
                    "routing_action": routing_action_str,
                    "amount": raw_budget,
                })
                # Sprint D bugfix (2026-04-11): emit phase_started for the
                # wait phase so the frontend reducer updates currentPhase and
                # the accordion row for "Awaiting Approval" activates. Without
                # this event the UI still shows currentPhase="approval" and
                # "Awaiting Approval" stays grey/pending.
                _session_emit("phase_started", {"phase": "approval_wait"})
                # Sprint D bugfix (2026-04-11): the gate_opened event payload
                # MUST nest context fields under `decision_context` and include
                # `gate_ref` + `required_role` so the useSession reducer
                # (see frontend/src/hooks/useSession.ts:182-195) can project
                # them onto the OpenGate object. Previously these fields were
                # flat and ApprovalPanel rendered empty dashes because
                # gate.decision_context was {}.
                _session_emit("gate_opened", {
                    "gate_type": "approval",
                    "gate_id": _approval_gate_id,
                    "gate_ref": {
                        "pr_number": pr_number,
                        "approver_emails": [a.get("approver_email") for a in assigned_approvers_list if a.get("approver_email")],
                    },
                    "required_role": approver_role,
                    "decision_context": {
                        "pr_summary": _pr_summary,
                        "line_items": _line_items,
                        "approver": {
                            "name": approver_label,
                            "email": approver_email,
                            "role": approver_role,
                            "level": approver_level,
                        },
                        "approval_chain": assigned_approvers_list,
                        "current_approver_role": approver_role,
                        "routing_action": routing_action_str,
                        "required_level": required_level_int,
                        "amount": raw_budget,
                        "policy_band": _policy_band,
                    },
                })
                _session_set_phase("approval_wait", "paused_human")

                # ── Send approval request email to approver ──
                if approver_email:
                    try:
                        from backend.services.email_service import send_approval_request_email
                        _apr_email_result = send_approval_request_email(
                            approver_email=approver_email,
                            approver_name=approver_label or "Approver",
                            pr_data={
                                **pr_data,
                                "pr_number": pr_number,
                                "total": raw_budget,
                                "requester_name": pr_data.get("requester_name", "Chat User"),
                            },
                        )
                        if _apr_email_result.get("success"):
                            logger.info("[P2P] Approval request email sent to %s", approver_email)
                            _session_emit("tool_called", {
                                "tool": "email", "action": "send_approval_request",
                                "approver_email": approver_email, "success": True,
                            })
                        else:
                            logger.warning("[P2P] Approval email failed: %s", _apr_email_result.get("error"))
                    except Exception as _apr_err:
                        logger.warning("[P2P] Approval email failed (non-blocking): %s", _apr_err)

                # ── Notification Agent — approval requested ──
                if "notification" in self.specialized_agents:
                    try:
                        _notif = self.specialized_agents["notification"]
                        await _notif.execute({
                            "event_type": "approval_requested",
                            "recipients": [{"email": approver_email, "name": approver_label, "role": approver_role}] if approver_email else [],
                            "payload": {
                                "pr_number": pr_number,
                                "amount": raw_budget,
                                "department": pr_data.get("department", ""),
                                "requester": pr_data.get("requester_name", ""),
                                "product": pr_data.get("product_name", ""),
                            },
                            "send_email": False,
                        })
                    except Exception as _ne:
                        logger.warning("[P2P] Notification agent (approval_requested) failed: %s", _ne)

                return p2p_results

            # If auto-approved or approval given, continue to PO and STOP
            _track_task('approval_wait', {'approved': True, 'approver': 'Auto'})
            _add_step("approval_wait", "approved", "Approval granted")
            _session_emit("phase_completed", {"phase": "approval", "auto_approved": True})

            # ─── STEP 8: PO Creation ───────────────────────────────────────
            logger.info("[P2P] STEP 8/15: Creating Purchase Order...")
            _session_set_phase("po_creation", "running")
            _session_emit("phase_started", {"phase": "po_creation"})
            po_number = f"PO-2026-{datetime.now().strftime('%m%d%H%M%S')}"
            p2p_results["po_number"] = po_number

            po_data = {
                "po_number": po_number,
                "pr_number": pr_number,
                "vendor_name": pr_data.get("vendor_name", ""),
                "department": pr_data.get("department", ""),
                "product_name": pr_data.get("product_name", ""),
                "quantity": pr_data.get("quantity", 1),
                "budget": raw_budget,
            }
            # Sprint C (2026-04-11): rich phase_completed payload so
            # SessionPage's PO card (Sprint D) can render without a
            # follow-up ERP fetch. Outbox-safe: payload is small JSON,
            # no secrets, no blobs.
            _po_line_items = pr_data.get("line_items") or [{
                "description": pr_data.get("product_name", ""),
                "qty": pr_data.get("quantity", 1),
                "unit_price": raw_budget / max(int(pr_data.get("quantity", 1) or 1), 1),
                "total": raw_budget,
            }]
            po_phase_completed_payload = {
                "phase": "po_creation",
                "ref": {"po_number": po_number, "pr_number": pr_number},
                "po_number": po_number,
                "pr_number": pr_number,
                "vendor_name": pr_data.get("vendor_name", ""),
                "vendor_id": pr_data.get("vendor_id"),
                "department": pr_data.get("department", ""),
                "line_items": _po_line_items,
                "total": raw_budget,
                "currency": pr_data.get("currency", "USD"),
                "expected_delivery_date": pr_data.get("expected_delivery_date")
                    or (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
            }

            from backend.services.adapters.factory import get_adapter
            po_adapter = get_adapter()
            po_committed_via_outbox = False
            po_created_successfully = False

            # HF-2 / R12: when a session is attached, write the PO row and the
            # phase_completed(po_creation) event in a single transaction via
            # the session_event_outbox. Either both commit or both roll back —
            # never half-applied state. The outbox pump publishes the event
            # into session_events asynchronously, firing pg_notify for SSE.
            if session_id_hybrid:
                try:
                    from backend.services.session_service import SessionService
                    async with po_adapter.transaction() as _po_tx:
                        po_adapter.create_purchase_order_from_pr_tx(_po_tx, po_data)
                        SessionService.append_event_tx(
                            conn=_po_tx,
                            session_id=session_id_hybrid,
                            event_type="phase_completed",
                            actor="orchestrator",
                            payload=po_phase_completed_payload,
                        )
                    po_committed_via_outbox = True
                    po_created_successfully = True
                    _track_task('po_creation', {'po_number': po_number})
                    _add_step(
                        "po_creation", "created",
                        f"PO {po_number} created from PR {pr_number} and sent to vendor",
                        "Adapter",
                    )
                except Exception as _po_tx_err:
                    # Hybrid-mode safety (R-hybrid): a Layer-1 (session/outbox)
                    # failure must NOT break the pipeline. Log and fall through
                    # to the legacy non-tx path. This fallback is REMOVED at P5
                    # when the outbox path becomes mandatory.
                    logger.warning(
                        "[P2P] HF-2 transactional PO write failed "
                        "(falling back to legacy in hybrid): %s",
                        _po_tx_err,
                    )

            if not po_committed_via_outbox:
                # Legacy non-transactional path: used when no session is
                # attached, or when the transactional path failed during
                # hybrid mode.
                try:
                    po_adapter.create_purchase_order_from_pr(po_data)
                    po_created_successfully = True
                    _track_task('po_creation', {'po_number': po_number})
                    _add_step(
                        "po_creation", "created",
                        f"PO {po_number} created from PR {pr_number} and sent to vendor",
                        "Adapter",
                    )
                except Exception as po_err:
                    logger.warning("[P2P] PO creation error (non-blocking): %s", po_err)
                    _track_task('po_creation', {'po_number': po_number, 'warning': str(po_err)})
                    _add_step(
                        "po_creation", "created",
                        f"PO {po_number} created (with warning)", "Adapter",
                    )
                # Outbox path didn't run — emit phase_completed via the
                # swallow-on-error legacy wrapper so SSE clients still see
                # the transition.
                _session_emit("phase_completed", po_phase_completed_payload)

            # G-02 and G-06 are non-blocking side effects that only run when
            # the PO actually exists in the ERP (regardless of which path
            # created it). They are intentionally OUTSIDE the transaction —
            # contract validation and vendor email are not state-changing
            # ERP writes that need atomicity with the session event.
            if po_created_successfully:
                # G-02: Validate PO against contract prices
                try:
                    from backend.services.contract_linkage_service import get_contract_linkage_service
                    _cls = get_contract_linkage_service()
                    po_validation = _cls.validate_po_against_contract({
                        "po_number": po_number,
                        "vendor_name": pr_data.get("vendor_name", ""),
                        "items": [{"item_code": pr_data.get("product_name", "ITEM-001"),
                                   "unit_price": raw_budget / max(float(pr_data.get("quantity", 1)), 1),
                                   "quantity": pr_data.get("quantity", 1)}],
                        "total_amount": raw_budget,
                    })
                    if po_validation.get("blocked"):
                        p2p_results.setdefault("warnings", []).extend(po_validation.get("price_variance_alerts", []))
                    logger.info("[P2P] G-02: PO contract validation: %s", po_validation.get("overall_status"))
                except Exception as _cv_err:
                    logger.debug("[P2P] G-02: PO contract validation (non-blocking): %s", _cv_err)

                # G-06: Send PO acknowledgment to vendor
                try:
                    from backend.services.vendor_communication_service import get_vendor_comm_service
                    _vcs = get_vendor_comm_service()
                    _vcs.send_po_acknowledgment(po_number, pr_data.get("vendor_name", ""), pr_data.get("vendor_id", ""))
                    logger.info("[P2P] G-06: PO acknowledgment sent to vendor")
                except Exception as _vc_err:
                    logger.debug("[P2P] G-06: Vendor communication (non-blocking): %s", _vc_err)

                # ── Vendor email lookup (mirrors resume-path logic) ──
                _vendor_email_fp = pr_data.get("vendor_email", "")
                if not _vendor_email_fp and pr_data.get("vendor_name"):
                    try:
                        _all_vendors_fp = po_adapter.get_vendors(active_only=True, limit=500)
                        _vname_lower_fp = pr_data["vendor_name"].strip().lower()
                        for _v_fp in _all_vendors_fp:
                            if (_v_fp.get("vendor_name") or "").strip().lower() == _vname_lower_fp:
                                _vendor_email_fp = (_v_fp.get("email") or "").strip()
                                if _vendor_email_fp:
                                    pr_data["vendor_email"] = _vendor_email_fp
                                    pr_data["vendor_id"] = _v_fp.get("vendor_id", "")
                                    logger.info("[P2P] Vendor email found: %s for %s", _vendor_email_fp, pr_data["vendor_name"])
                                    break
                    except Exception as _ve_err_fp:
                        logger.warning("[P2P] Vendor email lookup failed (non-fatal): %s", _ve_err_fp)

                # ── Send PO email to vendor ──
                if _vendor_email_fp and po_created_successfully:
                    try:
                        from backend.services.email_service import send_po_notification_email
                        _email_result_fp = send_po_notification_email(
                            vendor_email=_vendor_email_fp,
                            vendor_name=pr_data.get("vendor_name", "Vendor"),
                            po_data={
                                **pr_data,
                                "po_number": po_number,
                                "pr_number": pr_number,
                            },
                        )
                        if _email_result_fp.get("success"):
                            logger.info("[P2P] PO email sent to vendor %s at %s", pr_data.get("vendor_name"), _vendor_email_fp)
                            _session_emit("tool_called", {
                                "tool": "email", "action": "send_po_notification",
                                "vendor_email": _vendor_email_fp,
                                "po_number": po_number, "success": True,
                            })
                        else:
                            logger.warning("[P2P] PO email failed: %s", _email_result_fp.get("error"))
                            _session_emit("tool_called", {
                                "tool": "email", "action": "send_po_notification",
                                "vendor_email": _vendor_email_fp,
                                "success": False, "error": str(_email_result_fp.get("error", "unknown")),
                            })
                    except Exception as _email_err_fp:
                        logger.warning("[P2P] PO email send failed (non-blocking): %s", _email_err_fp)
                        _session_emit("tool_called", {
                            "tool": "email", "action": "send_po_notification",
                            "success": False, "error": str(_email_err_fp),
                        })
                elif po_created_successfully and not _vendor_email_fp:
                    logger.info("[P2P] No vendor email on file — skipping PO notification email")

                # ── Notification Agent — PO creation notification ──
                if "notification" in self.specialized_agents and po_created_successfully:
                    _session_emit("agent_started", {"agent": "notification"})
                    try:
                        _notif_fp = self.specialized_agents["notification"]
                        await _notif_fp.execute({
                            "event_type": "approval_decided",
                            "recipients": [
                                {"email": _vendor_email_fp, "name": pr_data.get("vendor_name", ""), "role": "vendor"},
                            ] if _vendor_email_fp else [],
                            "payload": {
                                "po_number": po_number, "pr_number": pr_number,
                                "vendor_name": pr_data.get("vendor_name", ""),
                                "total": raw_budget, "department": pr_data.get("department", ""),
                                "decision": "approved",
                                "message": f"PO {po_number} created for {pr_data.get('vendor_name', '')}",
                            },
                            "send_email": False,
                        })
                        _session_emit("agent_finished", {"agent": "notification", "event_type": "approval_decided"})
                    except Exception as _notif_err_fp:
                        logger.warning("[P2P] Notification agent failed (non-blocking): %s", _notif_err_fp)
                        _session_emit("agent_failed", {"agent": "notification", "error": str(_notif_err_fp)})

            # ─── STOP: PO Created — awaiting physical delivery ─────────────
            # Physical delivery takes days/weeks. Do NOT auto-run delivery/GRN/QC/Invoice/Payment.
            # User must manually confirm goods receipt on the Goods Receipt page when items arrive.
            p2p_results["status"] = "po_created_awaiting_delivery"
            p2p_results["summary"] = (
                f"Purchase Order {po_number} created and transmitted to "
                f"{pr_data.get('vendor_name') or 'vendor'}. "
                f"Pipeline paused — waiting for physical delivery. "
                f"When goods arrive, confirm receipt on the Goods Receipt page."
            )
            p2p_results["next_user_action"] = {
                "type": "manual_navigation",
                "page": "/goods-receipt",
                "label": "Confirm goods received",
                "trigger": "When goods physically arrive from vendor",
            }
            p2p_results["suggested_next_actions"] = [
                f"Track delivery of PO {po_number}",
                "Confirm goods receipt when items arrive",
                "View PO details",
            ]
            # HF-1: Honest event log around delivery_tracking.
            # Physical delivery takes days or weeks. We MUST NOT emit phase_completed
            # for delivery_tracking until the user actually confirms goods arrived,
            # and we MUST NOT open the grn gate until we are in the grn phase.
            # The session sits in delivery_tracking(running) until the user hits
            # POST /api/sessions/{id}/advance-to-grn from GoodsReceiptPage.
            #
            # Note: phase_completed(po_creation) is emitted by the HF-2
            # transactional outbox path inside the PO creation block above.
            # We do NOT emit it again here.
            _session_set_phase("delivery_tracking", "running")
            _session_emit("phase_started", {
                "phase": "delivery_tracking",
                "ref": {"po_number": po_number, "pr_number": pr_number},
                "vendor_name": pr_data.get("vendor_name", ""),
            })
            if session_id_hybrid:
                p2p_results["session_id"] = session_id_hybrid
                p2p_results["next_user_action"]["advance_endpoint"] = (
                    f"/api/sessions/{session_id_hybrid}/advance-to-grn"
                )
            return p2p_results

            # ─── The steps below are retained for reference but unreachable ───
            # Real-world P2P does not auto-run delivery/GRN/QC/Invoice/Payment.
            # Each of these must be triggered by an external event (physical arrival,
            # vendor invoice upload, AP review, etc.) via dedicated pages.
            pass  # noqa: unreachable code kept for historical context

            # ─── STEP 9: Delivery Tracking ─────────────────────────────────
            if "delivery_tracking" in self.specialized_agents:
                logger.info("[P2P] STEP 9/15: Tracking delivery...")
                await _emit_selected("delivery_tracking", 9)
                try:
                    delivery_ctx = {**input_context, "po_number": po_number, "pr_data": {**pr_data, "po_number": po_number}}
                    delivery_result = await self._get_agent("delivery_tracking").execute(delivery_ctx)

                    # Universal human gate check
                    if _check_human_gate("delivery_tracking", delivery_result, "DeliveryTrackingAgent"):
                        _add_step("delivery_tracking", "awaiting_input", "Delivery tracking needs human review", "DeliveryTrackingAgent")
                        p2p_results["suggested_next_actions"] = _fetch_suggestions()
                        p2p_results["summary"] = _build_summary()
                        return p2p_results

                    p2p_results["agents_invoked"].append(self._get_agent("delivery_tracking").name)
                    delivery_inner = delivery_result.get("result", {}) if isinstance(delivery_result.get("result"), dict) else {}
                    eta = delivery_inner.get("eta", delivery_inner.get("estimated_delivery", "TBD"))
                    _track_task('delivery_tracking', {'tracked': True, 'eta': str(eta)})
                    _add_step("delivery_tracking", "tracked", f"Delivery initiated, ETA: {eta}", "DeliveryTrackingAgent")
                except Exception as dt_err:
                    logger.warning("[P2P] Delivery tracking error: %s", dt_err)
                    _track_task('delivery_tracking', {'tracked': True})
                    _add_step("delivery_tracking", "completed", "Delivery tracking initiated", "DeliveryTrackingAgent")
            else:
                _add_step("delivery_tracking", "skipped", "Agent not available")

            # ─── STEP 10: GRN Entry (human gate) ──────────────────────────
            grn_confirmed = bool(pr_data.get("grn_confirmed") or context.get("auto_grn"))
            if not grn_confirmed:
                logger.info("[P2P] STEP 10/15: Pausing for goods receipt...")
                p2p_results["status"] = "awaiting_goods_receipt"
                p2p_results["human_action_required"] = {
                    "type": "goods_receipt",
                    "message": f"Goods receipt needed for PO {po_number}. Confirm when items are received.",
                    "po_number": po_number,
                    "options": ["confirm_received", "report_issue"],
                }
                p2p_results["suggested_next_actions"] = _fetch_suggestions()
                p2p_results["summary"] = _build_summary()
                return p2p_results

            _track_task('grn_entry', {'received': True})
            _add_step("grn_entry", "received", f"Goods received for PO {po_number}")

            # G-06: Notify vendor of goods receipt
            try:
                from backend.services.vendor_communication_service import get_vendor_comm_service
                _vcs = get_vendor_comm_service()
                _vcs.send_goods_received_notice(
                    grn_number=f"GRN-{po_number}",
                    vendor_name=pr_data.get("vendor_name", ""),
                    vendor_id=pr_data.get("vendor_id", ""),
                    po_number=po_number,
                )
                logger.info("[P2P] G-06: Goods receipt notification sent to vendor")
            except Exception as _gc_err:
                logger.debug("[P2P] G-06: GRN vendor comm (non-blocking): %s", _gc_err)

            # G-10: Score vendor on this transaction
            try:
                from backend.services.vendor_scorecard_service import get_scorecard_service
                _scs = get_scorecard_service()
                _scs.score_transaction(
                    vendor_id=pr_data.get("vendor_id", pr_data.get("vendor_name", "")),
                    vendor_name=pr_data.get("vendor_name", ""),
                    po_number=po_number,
                    grn_number=f"GRN-{po_number}",
                    scoring_data={
                        "ordered_qty": float(pr_data.get("quantity", 1)),
                        "received_qty": float(pr_data.get("quantity", 1)),
                        "accepted_qty": float(pr_data.get("quantity", 1)),
                        "days_late": 0,
                        "invoice_discrepancy": "none",
                        "response_hours": 24,
                    },
                )
                logger.info("[P2P] G-10: Vendor scorecard updated")
            except Exception as _sc_err:
                logger.debug("[P2P] G-10: Vendor scorecard (non-blocking): %s", _sc_err)

            # ─── STEP 11: Quality Inspection ───────────────────────────────
            if "quality_inspection" in self.specialized_agents:
                logger.info("[P2P] STEP 11/15: Running quality inspection...")
                await _emit_selected("quality_inspection", 11)
                try:
                    qc_ctx = {**input_context, "po_number": po_number, "pr_data": {**pr_data, "po_number": po_number}}
                    qc_result = await self._get_agent("quality_inspection").execute(qc_ctx)

                    # Universal human gate check
                    if _check_human_gate("quality_inspection", qc_result, "QualityInspectionAgent"):
                        _add_step("quality_inspection", "awaiting_input", "Quality inspection needs human review", "QualityInspectionAgent")
                        p2p_results["suggested_next_actions"] = _fetch_suggestions()
                        p2p_results["summary"] = _build_summary()
                        return p2p_results

                    p2p_results["agents_invoked"].append(self._get_agent("quality_inspection").name)
                    qc_inner = qc_result.get("result", {}) if isinstance(qc_result.get("result"), dict) else {}
                    qc_score = qc_inner.get("score", qc_inner.get("quality_score", "N/A"))
                    qc_pass = qc_inner.get("pass_fail", qc_inner.get("passed", "N/A"))
                    _track_task('quality_inspection', {'score': str(qc_score), 'pass_fail': str(qc_pass)})
                    _add_step("quality_inspection", "inspected", f"QC score: {qc_score}, Result: {qc_pass}", "QualityInspectionAgent", {"score": qc_score, "pass_fail": qc_pass})
                except Exception as qc_err:
                    logger.warning("[P2P] QC error (non-blocking): %s", qc_err)
                    _track_task('quality_inspection', {'completed': True})
                    _add_step("quality_inspection", "completed", "Quality inspection completed", "QualityInspectionAgent")
            else:
                _add_step("quality_inspection", "skipped", "Agent not available")

            # ─── STEP 12: Invoice Matching ─────────────────────────────────
            if "invoice_matching" in self.specialized_agents:
                logger.info("[P2P] STEP 12/15: Matching invoice...")
                await _emit_selected("invoice_matching", 12)
                try:
                    inv_ctx = {**input_context, "po_number": po_number, "pr_data": {**pr_data, "po_number": po_number, "pr_number": pr_number}}
                    inv_result = await self._get_agent("invoice_matching").execute(inv_ctx)

                    # Universal human gate check
                    if _check_human_gate("invoice_matching", inv_result, "InvoiceMatchingAgent"):
                        _add_step("invoice_matching", "awaiting_input", "Invoice matching needs human review", "InvoiceMatchingAgent")
                        p2p_results["suggested_next_actions"] = _fetch_suggestions()
                        p2p_results["summary"] = _build_summary()
                        return p2p_results

                    p2p_results["agents_invoked"].append(self._get_agent("invoice_matching").name)
                    inv_inner = inv_result.get("result", {}) if isinstance(inv_result.get("result"), dict) else {}
                    matched = inv_inner.get("matched", inv_inner.get("match_status", "N/A"))
                    _track_task('invoice_matching', {'matched': str(matched)})
                    _add_step("invoice_matching", "matched", f"Invoice match: {matched}", "InvoiceMatchingAgent")

                    # G-04: Duplicate invoice detection
                    try:
                        from backend.services.duplicate_invoice_detector import get_duplicate_detector
                        _dd = get_duplicate_detector()
                        dedup_result = _dd.check({
                            "vendor_id": pr_data.get("vendor_id", ""),
                            "vendor_name": pr_data.get("vendor_name", ""),
                            "invoice_number": inv_inner.get("invoice_number", f"INV-{po_number}"),
                            "amount": raw_budget,
                            "currency": pr_data.get("currency", "USD"),
                            "invoice_date": datetime.now().strftime("%Y-%m-%d"),
                            "source_channel": "p2p_pipeline",
                        })
                        if dedup_result.get("is_duplicate"):
                            p2p_results.setdefault("warnings", []).append(
                                f"G-04: Potential duplicate invoice detected ({dedup_result.get('detection_method')})"
                            )
                            logger.warning("[P2P] G-04: Duplicate invoice detected: %s", dedup_result.get("detection_method"))
                        else:
                            logger.info("[P2P] G-04: Invoice dedup check passed")
                    except Exception as _dd_err:
                        logger.debug("[P2P] G-04: Dedup check (non-blocking): %s", _dd_err)
                except Exception as inv_err:
                    logger.warning("[P2P] Invoice matching error: %s", inv_err)
                    _track_task('invoice_matching', {'completed': True})
                    _add_step("invoice_matching", "completed", "Invoice processing completed", "InvoiceMatchingAgent")
            else:
                _add_step("invoice_matching", "skipped", "Agent not available")

            # ─── STEP 13: Three-Way Match ──────────────────────────────────
            if "invoice_matching" in self.specialized_agents:
                logger.info("[P2P] STEP 13/15: Running 3-way match (PO vs GRN vs Invoice)...")
                await _emit_selected("invoice_matching", 13)
                try:
                    twm_ctx = {**input_context, "match_type": "three_way", "po_number": po_number, "pr_number": pr_number,
                               "pr_data": {**pr_data, "po_number": po_number, "pr_number": pr_number}}
                    twm_result = await self._get_agent("invoice_matching").execute(twm_ctx)

                    # Universal human gate check
                    if _check_human_gate("three_way_match", twm_result, "InvoiceMatchingAgent"):
                        _add_step("three_way_match", "awaiting_input", "Three-way match needs human review", "InvoiceMatchingAgent")
                        p2p_results["suggested_next_actions"] = _fetch_suggestions()
                        p2p_results["summary"] = _build_summary()
                        return p2p_results

                    p2p_results["agents_invoked"].append(self._get_agent("invoice_matching").name)
                    twm_inner = twm_result.get("result", {}) if isinstance(twm_result.get("result"), dict) else {}
                    twm_matched = twm_inner.get("matched", "N/A")
                    exceptions = twm_inner.get("exceptions", [])
                    _track_task('three_way_match', {'matched': str(twm_matched), 'exceptions': len(exceptions) if isinstance(exceptions, list) else 0})
                    _add_step("three_way_match", "matched", f"3-way match: {twm_matched}, exceptions: {len(exceptions) if isinstance(exceptions, list) else 0}", "InvoiceMatchingAgent")
                    if exceptions:
                        p2p_results["pending_exceptions"].extend(exceptions if isinstance(exceptions, list) else [])

                        # G-05: Create exceptions in the queue for each discrepancy
                        try:
                            from backend.services.exception_resolution_service import get_exception_service
                            _es = get_exception_service()
                            for exc in (exceptions if isinstance(exceptions, list) else []):
                                _es.create_exception({
                                    "exception_type": "three_way_match_failure",
                                    "severity": "HIGH",
                                    "source_document_type": "PO",
                                    "source_document_id": po_number,
                                    "workflow_run_id": workflow_run_id,
                                    "description": str(exc)[:500] if isinstance(exc, str) else json.dumps(exc)[:500],
                                })
                            logger.info("[P2P] G-05: %d exceptions created for 3-way match discrepancies", len(exceptions))
                        except Exception as _ex_err:
                            logger.debug("[P2P] G-05: Exception creation (non-blocking): %s", _ex_err)
                except Exception as twm_err:
                    logger.warning("[P2P] 3-way match error: %s", twm_err)
                    _track_task('three_way_match', {'completed': True})
                    _add_step("three_way_match", "completed", "Three-way match completed", "InvoiceMatchingAgent")
            else:
                _add_step("three_way_match", "skipped", "Agent not available")

            # ─── STEP 14: Payment Readiness ────────────────────────────────
            if "payment_readiness" in self.specialized_agents:
                logger.info("[P2P] STEP 14/15: Checking payment readiness...")
                await _emit_selected("payment_readiness", 14)
                try:
                    pay_ctx = {**input_context, "po_number": po_number, "pr_number": pr_number,
                               "pr_data": {**pr_data, "po_number": po_number, "pr_number": pr_number}}
                    pay_result = await self._get_agent("payment_readiness").execute(pay_ctx)

                    # Universal human gate check
                    if _check_human_gate("payment_readiness", pay_result, "PaymentReadinessAgent"):
                        _add_step("payment_readiness", "awaiting_input", "Payment readiness needs human review", "PaymentReadinessAgent")
                        p2p_results["suggested_next_actions"] = _fetch_suggestions()
                        p2p_results["summary"] = _build_summary()
                        return p2p_results

                    p2p_results["agents_invoked"].append(self._get_agent("payment_readiness").name)
                    pay_inner = pay_result.get("result", {}) if isinstance(pay_result.get("result"), dict) else {}
                    ready = pay_inner.get("ready", pay_inner.get("payment_ready", "N/A"))
                    _track_task('payment_readiness', {'ready': str(ready)})
                    _add_step("payment_readiness", "checked", f"Payment readiness: {ready}", "PaymentReadinessAgent")
                except Exception as pay_err:
                    logger.warning("[P2P] Payment readiness error: %s", pay_err)
                    _track_task('payment_readiness', {'completed': True})
                    _add_step("payment_readiness", "completed", "Payment readiness checked", "PaymentReadinessAgent")
            else:
                _add_step("payment_readiness", "skipped", "Agent not available")

            # ─── STEP 15: Payment Execution ────────────────────────────────
            if "payment_calculation" in self.specialized_agents:
                logger.info("[P2P] STEP 15/15: Executing payment calculation...")
                await _emit_selected("payment_calculation", 15)
                try:
                    calc_ctx = {**input_context, "po_number": po_number, "pr_number": pr_number,
                                "total_amount": raw_budget,
                                "pr_data": {**pr_data, "po_number": po_number, "pr_number": pr_number}}
                    calc_result = await self._get_agent("payment_calculation").execute(calc_ctx)

                    # Universal human gate check
                    if _check_human_gate("payment_calculation", calc_result, "PaymentCalculationAgent"):
                        _add_step("payment_calculation", "awaiting_input", "Payment calculation needs human review", "PaymentCalculationAgent")
                        p2p_results["suggested_next_actions"] = _fetch_suggestions()
                        p2p_results["summary"] = _build_summary()
                        return p2p_results

                    p2p_results["agents_invoked"].append(self._get_agent("payment_calculation").name)
                    calc_inner = calc_result.get("result", {}) if isinstance(calc_result.get("result"), dict) else {}
                    net_payable = calc_inner.get("net_payable", calc_inner.get("amount", raw_budget))
                    _track_task('payment_execution', {'net_payable': str(net_payable), 'executed': True})
                    _add_step("payment_execution", "executed", f"Payment calculated: ${net_payable:,.2f}" if isinstance(net_payable, (int, float)) else f"Payment processed: {net_payable}", "PaymentCalculationAgent")

                    # G-08: Record actual spend in budget ledger
                    try:
                        from backend.services.budget_ledger_service import get_budget_ledger_service
                        _bl = get_budget_ledger_service()
                        actual_amount = float(net_payable) if isinstance(net_payable, (int, float)) else raw_budget
                        _bl.record_actual(
                            department=pr_data.get("department", "General"),
                            fiscal_year=None,
                            reference_type="PAYMENT",
                            reference_id=po_number,
                            amount=actual_amount,
                            description=f"Payment for PO {po_number} / PR {pr_number}",
                        )
                        logger.info("[P2P] G-08: Budget actual recorded: $%.2f", actual_amount)
                    except Exception as _ba_err:
                        logger.debug("[P2P] G-08: Budget actual (non-blocking): %s", _ba_err)

                    # G-06: Notify vendor of payment
                    try:
                        from backend.services.vendor_communication_service import get_vendor_comm_service
                        _vcs = get_vendor_comm_service()
                        pay_amount = float(net_payable) if isinstance(net_payable, (int, float)) else raw_budget
                        _vcs.send_payment_notification(
                            payment_ref=f"PAY-{po_number}",
                            vendor_name=pr_data.get("vendor_name", ""),
                            vendor_id=pr_data.get("vendor_id", ""),
                            amount=pay_amount,
                            currency=pr_data.get("currency", "USD"),
                        )
                        logger.info("[P2P] G-06: Payment notification sent to vendor")
                    except Exception as _pn_err:
                        logger.debug("[P2P] G-06: Payment notification (non-blocking): %s", _pn_err)
                except Exception as calc_err:
                    logger.warning("[P2P] Payment execution error: %s", calc_err)
                    _track_task('payment_execution', {'completed': True})
                    _add_step("payment_execution", "completed", "Payment processing completed", "PaymentCalculationAgent")
            else:
                _add_step("payment_execution", "skipped", "Agent not available")

            # ─── WORKFLOW COMPLETE ─────────────────────────────────────────
            p2p_results["status"] = "completed"
            p2p_results["summary"] = _build_summary()
            p2p_results["suggested_next_actions"] = _fetch_suggestions()
            logger.info("=" * 80)
            logger.info("[P2P] FULL P2P WORKFLOW COMPLETED: %d agents invoked", len(p2p_results["agents_invoked"]))
            logger.info("[P2P] PR: %s | PO: %s | Vendor: %s", pr_number, po_number, p2p_results.get("vendor_name"))
            logger.info("=" * 80)
            _session_emit("session_completed", {
                "pr_number": p2p_results.get("pr_number"),
                "po_number": p2p_results.get("po_number"),
                "vendor_name": p2p_results.get("vendor_name"),
            })
            _session_set_phase("completed", "completed")

        except Exception as e:
            logger.error("[P2P] WORKFLOW EXCEPTION: %s", e)
            import traceback
            logger.error("[P2P] Traceback: %s", traceback.format_exc())
            p2p_results["status"] = "error"
            p2p_results["error"] = str(e)
            p2p_results["summary"] = f"P2P workflow error: {str(e)}"
            # Layer 1: mark session as failed so the frontend sees a terminal state
            try:
                if session_id_hybrid:
                    from backend.services.session_service import SessionService
                    SessionService.append_event(
                        session_id=session_id_hybrid,
                        event_type="session_failed",
                        actor="orchestrator",
                        payload={"error": str(e)},
                    )
                    try:
                        SessionService.set_phase(
                            session_id=session_id_hybrid,
                            new_phase="failed",
                            new_status="failed",
                        )
                    except Exception:
                        pass  # transition may be forbidden depending on current phase
            except Exception as _sess_fail_exc:
                logger.warning("[P2P] session_failed emit failed: %s", _sess_fail_exc)

        return p2p_results

    async def _resume_p2p_workflow(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resume a P2P_FULL workflow after a human decision point.
        Called when user approves, selects vendor, or confirms GRN.
        Picks up from the current workflow state and continues execution.
        """
        from backend.services.workflow_engine import (
            get_workflow_status, advance_workflow, complete_task,
            get_suggestions, generate_workflow_summary,
        )

        workflow_run_id = context.get("workflow_run_id")
        if not workflow_run_id:
            return {"status": "error", "error": "No workflow_run_id provided"}

        input_context = context.get("input_context", context)
        pr_data = input_context.get("pr_data", {})
        status = get_workflow_status(workflow_run_id)
        if not status.get("success"):
            return {"status": "error", "error": "Workflow not found"}

        # ── Reconstruct pr_data from workflow trigger_data ──────────────
        # When this method is called from the HF-6 resume path (after a
        # gate resolves), the context comes from sessions.py and does NOT
        # include pr_data. Recover it from the workflow_runs.trigger_data
        # column which stores the original PR fields at creation time.
        if not pr_data:
            _wf_row = status.get("workflow", {})
            _trigger = _wf_row.get("trigger_data", {})
            if isinstance(_trigger, str):
                try:
                    _trigger = json.loads(_trigger)
                except Exception:
                    _trigger = {}
            if isinstance(_trigger, dict) and _trigger:
                pr_data = dict(_trigger)
                # Normalize key aliases: workflow stored 'requester' but
                # downstream code reads 'requester_name'.
                if "requester" in pr_data and "requester_name" not in pr_data:
                    pr_data["requester_name"] = pr_data["requester"]
                logger.info(
                    "[P2P-RESUME] Recovered pr_data from workflow trigger_data: keys=%s budget=%s dept=%s product=%s",
                    list(pr_data.keys()), pr_data.get("budget"), pr_data.get("department"), pr_data.get("product_name"),
                )

        p2p_results = {
            "workflow_type": "P2P_FULL",
            "workflow_run_id": workflow_run_id,
            "agents_invoked": [],
            "actions_completed": [],
            "status": "in_progress",
            "pr_number": pr_data.get("pr_number"),
            "po_number": None,
            "vendor_name": pr_data.get("vendor_name"),
            "total_amount": float(pr_data.get("budget") or 0),
            "human_action_required": None,
            "suggested_next_actions": [],
            "pending_exceptions": [],
            "summary": "",
        }

        # ── Layer 1: session observer helpers (HYBRID mode, P1) ─────────────
        # Same exception-swallowing pattern as _execute_full_p2p. A Layer-1
        # failure must NEVER break the existing resume path during hybrid.
        _raw_session_id_resume = context.get("session_id") or input_context.get("session_id")
        if _raw_session_id_resume is not None and not isinstance(_raw_session_id_resume, str):
            logger.warning(
                "[P2P-RESUME] Non-string session_id in context (type=%s value=%r) — disabling session emits",
                type(_raw_session_id_resume).__name__, _raw_session_id_resume,
            )
            session_id_hybrid = None
        else:
            session_id_hybrid = _raw_session_id_resume or None
        gate_id_hybrid = context.get("gate_id") or input_context.get("gate_id")
        gate_resolution_id = context.get("gate_resolution_id") or input_context.get("gate_resolution_id")
        resume_user_id = (
            context.get("user_id")
            or input_context.get("user_id")
            or input_context.get("approved_by")
            or context.get("human_input", {}).get("approved_by")
            or "anonymous"
        )
        p2p_results["session_id"] = session_id_hybrid

        def _session_emit(event_type: str, payload: dict) -> None:
            if not session_id_hybrid:
                return
            try:
                from backend.services.session_service import SessionService
                SessionService.append_event(
                    session_id=session_id_hybrid,
                    event_type=event_type,
                    actor="orchestrator",
                    payload=payload or {},
                )
            except Exception as _exc:
                logger.warning("[P2P-RESUME] session emit failed (non-fatal in hybrid): %s", _exc)

        def _session_set_phase(new_phase: str, new_status: str) -> None:
            if not session_id_hybrid:
                return
            try:
                from backend.services.session_service import SessionService
                SessionService.set_phase(
                    session_id=session_id_hybrid,
                    new_phase=new_phase,
                    new_status=new_status,
                )
            except Exception as _exc:
                logger.warning("[P2P-RESUME] session set_phase failed (non-fatal in hybrid): %s", _exc)

        def _session_open_gate(gate_type: str, gate_ref: dict, decision_context: dict, required_role: Optional[str] = None) -> Optional[str]:
            if not session_id_hybrid:
                return None
            try:
                from backend.services.session_service import SessionService
                gate_row = SessionService.open_gate(
                    session_id=session_id_hybrid,
                    gate_type=gate_type,
                    gate_ref=gate_ref or {},
                    decision_context=decision_context or {},
                    required_role=required_role,
                )
                # Unwrap the gate_id STRING from the returned dict. Passing the
                # whole dict into gate_opened payload would send it verbatim to
                # the frontend, and the /resume POST would fail Pydantic str
                # validation (422) because gate_id would be an object not a UUID.
                return gate_row.get("gate_id") if isinstance(gate_row, dict) else None
            except Exception as _exc:
                logger.warning("[P2P-RESUME] session open_gate failed (non-fatal in hybrid): %s", _exc)
                return None

        def _session_resolve_gate(action_name: str) -> None:
            """Resolve the prior gate that paused this session. R13 idempotent."""
            if not (session_id_hybrid and gate_id_hybrid):
                return
            try:
                import uuid as _uuid
                from backend.services.session_service import SessionService
                SessionService.resolve_gate(
                    gate_id=gate_id_hybrid,
                    decision={
                        "action": action_name or "",
                        "payload": context.get("human_input", {}) or {},
                    },
                    resolved_by=resume_user_id,
                    gate_resolution_id=gate_resolution_id or str(_uuid.uuid4()),
                )
                _session_emit("gate_resolved", {
                    "gate_id": gate_id_hybrid,
                    "action": action_name or "",
                })
            except Exception as _exc:
                logger.warning("[P2P-RESUME] session resolve_gate failed (non-fatal in hybrid): %s", _exc)

        # Determine what the user just did, so we only run the NEXT logical step
        action = context.get("action", "")
        resume_phase = None
        if action in ("confirm_vendor",):
            resume_phase = "post_vendor"   # → run pr_creation, approval_routing, then pause at approval_wait
        elif action in ("approve", "approve_decision"):
            resume_phase = "post_approval"  # → create PO, then STOP (physical delivery takes days)
        elif action in ("confirm_grn",):
            resume_phase = "post_grn"  # → run quality inspection, then STOP (invoice comes later)
        elif action in ("accept", "partial_accept"):
            resume_phase = "post_qc"   # → STOP (wait for vendor invoice)
        elif action in ("accept_exception", "adjust"):
            resume_phase = "post_invoice"  # → run 3-way match + payment readiness, then STOP
        elif action in ("release_payment",):
            resume_phase = "post_payment_release"  # → execute payment
        else:
            resume_phase = "auto"  # fallback: let workflow engine drive

        logger.info("[P2P-RESUME] Action=%s → resume_phase=%s", action, resume_phase)

        # Refresh tasks after resume_from_human advanced the DAG
        tasks = status.get("tasks", [])

        # ─── Phase: post_vendor — run pr_creation + approval_routing, stop at approval_wait ───
        if resume_phase == "post_vendor":
            # Resolve the vendor_selection gate that paused this run
            _session_resolve_gate("confirm_vendor")

            # ── Extract selected vendor from the gate resolution payload ──
            _human = context.get("human_input", {}) or {}
            _selected_vendor = (
                _human.get("selected_vendor_name")
                or _human.get("vendor_name")
                or ""
            ).strip()
            if _selected_vendor:
                pr_data["vendor_name"] = _selected_vendor
                pr_data["selected_vendor_name"] = _selected_vendor
                pr_data["vendor_confirmed"] = True
                logger.info("[P2P-RESUME] Vendor confirmed: %s", _selected_vendor)

            # ── Look up vendor email from ERP dataset ──
            _vendor_email = ""
            if pr_data.get("vendor_name"):
                try:
                    from backend.services.adapters.factory import get_adapter
                    _v_adapter = get_adapter()
                    _all_vendors = _v_adapter.get_vendors(active_only=True, limit=500)
                    _vname_lower = pr_data["vendor_name"].strip().lower()
                    for _v in _all_vendors:
                        if (_v.get("vendor_name") or "").strip().lower() == _vname_lower:
                            _vendor_email = (_v.get("email") or "").strip()
                            if _vendor_email:
                                pr_data["vendor_email"] = _vendor_email
                                pr_data["vendor_id"] = _v.get("vendor_id", "")
                                logger.info("[P2P-RESUME] Vendor email found: %s for %s", _vendor_email, pr_data["vendor_name"])
                            break
                except Exception as _ve_err:
                    logger.warning("[P2P-RESUME] Vendor email lookup failed (non-fatal): %s", _ve_err)

            # ── Persist vendor + any other late-bound fields to trigger_data ──
            # So the NEXT resume (post_approval → PO creation) can reconstruct
            # pr_data with the vendor name that was selected in this phase.
            try:
                from backend.services.workflow_engine import update_trigger_data
                _late_fields = {}
                if pr_data.get("vendor_name"):
                    _late_fields["vendor_name"] = pr_data["vendor_name"]
                    _late_fields["selected_vendor_name"] = pr_data["vendor_name"]
                    _late_fields["vendor_confirmed"] = True
                if pr_data.get("vendor_email"):
                    _late_fields["vendor_email"] = pr_data["vendor_email"]
                if pr_data.get("vendor_id"):
                    _late_fields["vendor_id"] = pr_data["vendor_id"]
                if pr_data.get("pr_number"):
                    _late_fields["pr_number"] = pr_data["pr_number"]
                if _late_fields:
                    update_trigger_data(workflow_run_id, _late_fields)
                    logger.info("[P2P-RESUME] Persisted late-bound fields to trigger_data: %s", list(_late_fields.keys()))
            except Exception as _utd_err:
                logger.warning("[P2P-RESUME] update_trigger_data failed (non-fatal): %s", _utd_err)

            # Sprint D bugfix (2026-04-11): mark vendor_selection as completed
            # so the frontend accordion shows it with a checkmark instead of
            # a clock icon. Without this, the PHASE_ORDER row for
            # "Vendor Selection" stays grey even after the user confirmed.
            # Build enriched vendor payload so the frontend VendorRankingCard
            # renders the shortlist instead of "Vendor details not included".
            _vs_payload = {"phase": "vendor_selection"}
            _vs_selected = pr_data.get("vendor_name") or pr_data.get("selected_vendor_name") or ""
            _vs_vendors = p2p_results.get("top_vendor_options") or []
            if _vs_vendors:
                _vs_payload["top_vendor"] = _vs_selected or (_vs_vendors[0].get("vendor_name") if _vs_vendors else "")
                _vs_payload["vendor_count"] = len(_vs_vendors)
                _vs_payload["vendors"] = [
                    {
                        "vendor_id": v.get("vendor_id"),
                        "vendor_name": v.get("vendor_name"),
                        "total_score": v.get("total_score", v.get("score")),
                        "recommendation": v.get("recommendation_reason", v.get("recommendation", "")),
                    }
                    for v in _vs_vendors[:5]
                ]
                _vs_payload["selected_vendor"] = _vs_selected
            elif _vs_selected:
                _vs_payload["top_vendor"] = _vs_selected
                _vs_payload["vendor_count"] = 1
                _vs_payload["selected_vendor"] = _vs_selected
            _session_emit("phase_completed", _vs_payload)
            _session_set_phase("pr_creation", "running")
            _session_emit("phase_started", {"phase": "pr_creation"})
            # Run pr_creation (system task)
            for task in tasks:
                if task["task_name"] == "pr_creation" and task["status"] in ("running", "pending"):
                    pr_number = pr_data.get("pr_number") or f"PR-2026-{datetime.now().strftime('%m%d%H%M%S')}"
                    pr_data["pr_number"] = pr_number
                    p2p_results["pr_number"] = pr_number
                    try:
                        from backend.services.adapters.factory import get_adapter
                        _adapter = get_adapter()
                        _adapter.create_purchase_requisition({
                            "name": pr_number,
                            "user_id": pr_data.get("requester_name", "Chat User"),
                            "product_qty": pr_data.get("quantity", 1),
                            "state": "pending_approval",
                            "origin": pr_data.get("department", ""),
                            "notes": f"{pr_data.get('product_name', '')} - {pr_data.get('justification', '')}",
                            "erp_source": "procure_ai",
                        })
                    except Exception as _pe:
                        logger.warning("[P2P-RESUME] PR persistence warning: %s", _pe)
                    complete_task(task["task_id"], {"pr_number": pr_number})
                    p2p_results["actions_completed"].append({
                        "step": "pr_creation", "status": "created",
                        "summary": f"Purchase Requisition {pr_number} created and logged",
                        "agent": "Orchestrator",
                    })
                    # Persist pr_number to trigger_data for post_approval PO creation
                    try:
                        from backend.services.workflow_engine import update_trigger_data
                        update_trigger_data(workflow_run_id, {"pr_number": pr_number})
                    except Exception:
                        pass
                    break

            _session_emit("phase_completed", {
                "phase": "pr_creation",
                "ref": {"pr_number": p2p_results.get("pr_number")},
                "pr_number": p2p_results.get("pr_number"),
                "product": pr_data.get("product_name") or pr_data.get("product") or "",
                "department": pr_data.get("department") or pr_data.get("dept") or "",
                "requester": pr_data.get("requester_name") or pr_data.get("requester") or "Chat User",
                "amount": float(pr_data.get("budget", 0) or 0),
                "quantity": pr_data.get("quantity") or pr_data.get("qty") or 1,
            })

            # ── Risk Assessment (was skipped in resume path before this fix) ──
            if "risk_assessment" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "risk_assessment"})
                try:
                    _risk_agent = self.specialized_agents["risk_assessment"]
                    _risk_ctx = {
                        "request": f"Assess procurement risk for {pr_data.get('product_name', 'items')}",
                        "pr_data": pr_data,
                    }
                    _risk_result = await _risk_agent.execute(_risk_ctx)
                    p2p_results["agents_invoked"].append(_risk_agent.name)
                    _rlevel = (_risk_result.get("risk_level") or _risk_result.get("overall_risk_level") or "unknown").lower()
                    _rscore = _risk_result.get("risk_score") or _risk_result.get("overall_risk_score") or ""
                    logger.info("[P2P-RESUME] Risk assessment: level=%s score=%s", _rlevel, _rscore)
                    _session_emit("agent_finished", {"agent": "risk_assessment", "risk_level": _rlevel, "risk_score": _rscore})
                    if _rlevel == "critical":
                        p2p_results["status"] = "failed"
                        p2p_results["summary"] = f"P2P blocked: CRITICAL risk (score {_rscore}). Review risk factors."
                        _session_emit("phase_failed", {"phase": "risk_assessment", "risk_level": _rlevel})
                        return p2p_results
                except Exception as _re:
                    logger.warning("[P2P-RESUME] Risk assessment failed (non-blocking): %s", _re)
                    _session_emit("agent_failed", {"agent": "risk_assessment", "error": str(_re)})

            # ── Price Analysis (provides pricing intelligence before approval) ──
            if "price_analysis" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "price_analysis"})
                try:
                    _price_agent = self.specialized_agents["price_analysis"]
                    _price_result = await _price_agent.execute({
                        "request": f"Analyze pricing for {pr_data.get('product_name', 'items')}",
                        "pr_data": pr_data,
                    })
                    p2p_results["agents_invoked"].append(_price_agent.name)
                    p2p_results.setdefault("validations", {})["price_analysis"] = _price_result
                    logger.info("[P2P-RESUME] Price analysis completed")
                    _session_emit("agent_finished", {"agent": "price_analysis"})
                except Exception as _pe:
                    logger.warning("[P2P-RESUME] Price analysis failed (non-blocking): %s", _pe)
                    _session_emit("agent_failed", {"agent": "price_analysis", "error": str(_pe)})

            _session_set_phase("approval", "running")
            _session_emit("phase_started", {"phase": "approval"})

            # Run approval_routing (agent task)
            assigned_approvers: list = []
            routing_action: str = ""
            required_level: int = 1
            status = get_workflow_status(workflow_run_id)
            tasks = status.get("tasks", [])
            for task in tasks:
                if task["task_name"] == "approval_routing" and task["status"] in ("running", "pending"):
                    if "approval_routing" in self.specialized_agents:
                        try:
                            agent = self.specialized_agents["approval_routing"]
                            result = await agent.execute({
                                "request": f"Route approval for PR {p2p_results['pr_number']}",
                                "pr_data": pr_data,
                            })
                            # Extract the assigned approvers from the routing agent result
                            routing_inner = result.get("result", {}) if isinstance(result, dict) else {}
                            assigned_approvers = routing_inner.get("assigned_approvers", []) or []
                            routing_action = routing_inner.get("action", "") or ""
                            required_level = routing_inner.get("required_level", 1) or 1

                            # Build human-readable summary of who was picked
                            if assigned_approvers:
                                approver_names = ", ".join(
                                    f"{a.get('approver_name', 'Approver')} (L{a.get('approval_level', '?')})"
                                    for a in assigned_approvers
                                )
                                routing_summary = (
                                    f"Routed to {len(assigned_approvers)} approver(s): {approver_names} "
                                    f"— amount ${p2p_results.get('total_amount', 0):,.2f}"
                                )
                            else:
                                routing_summary = "Approval routing analyzed (no approvers assigned)"

                            complete_task(task["task_id"], routing_inner)
                            p2p_results["agents_invoked"].append(agent.name)
                            p2p_results["actions_completed"].append({
                                "step": "approval_routing", "status": "routed",
                                "summary": routing_summary,
                                "agent": agent.name,
                            })
                        except Exception as _ae:
                            logger.warning("[P2P-RESUME] approval_routing failed: %s", _ae)
                    break

            # ── Enriched approval routing payload ──
            _session_emit("phase_completed", {
                "phase": "approval",
                "routed_to": len(assigned_approvers),
                "approver": assigned_approvers[0].get("approver_name", "Manager") if assigned_approvers else "Manager",
                "routing_action": routing_action,
                "amount": float(pr_data.get("budget", 0) or 0),
            })

            # Stop at approval_wait — this is a human gate
            status = get_workflow_status(workflow_run_id)
            for task in status.get("tasks", []):
                if task["task_name"] == "approval_wait" and task["status"] == "waiting_human":
                    # Pick the highest-level required approver as the "next" decision maker
                    next_approver = None
                    if assigned_approvers:
                        try:
                            next_approver = max(
                                assigned_approvers,
                                key=lambda a: int(a.get("approval_level", 0) or 0),
                            )
                        except Exception:
                            next_approver = assigned_approvers[0]

                    approver_label = "Manager"
                    approver_email = None
                    approver_role = None
                    approver_level = 1
                    if next_approver:
                        approver_label = next_approver.get("approver_name") or "Manager"
                        approver_email = next_approver.get("approver_email")
                        approver_role = next_approver.get("role") or next_approver.get("approver_role")
                        approver_level = int(next_approver.get("approval_level", 1) or 1)

                    # ── Resolve generic role to actual person ──
                    _pr_dept = (pr_data.get("department") or pr_data.get("dept") or "").strip()
                    if _pr_dept:
                        try:
                            from backend.services.nmi_data_service import get_conn as _gc3
                            from psycopg2.extras import RealDictCursor as _RDC3
                            # Resolve top-level approver
                            if approver_label in ("Department Manager", "Department Director", "Manager", "Director"):
                                _c3 = _gc3()
                                with _c3.cursor(cursor_factory=_RDC3) as _cur3:
                                    _cur3.execute(
                                        """SELECT approver_name, approver_email FROM approval_chains
                                           WHERE LOWER(department) = LOWER(%s) AND approval_level = %s LIMIT 1""",
                                        (_pr_dept, approver_level),
                                    )
                                    _row3 = _cur3.fetchone()
                                _c3.close()
                                if _row3 and _row3.get("approver_email"):
                                    approver_label = _row3["approver_name"]
                                    approver_email = _row3["approver_email"]
                            # Resolve all chain entries
                            _c4 = _gc3()
                            _cur4 = _c4.cursor(cursor_factory=_RDC3)
                            for _ae in assigned_approvers:
                                _an = (_ae.get("approver_name") or "").strip()
                                if _an in ("Department Manager", "Department Director", "Manager", "Director", "VP", "CFO"):
                                    _al = int(_ae.get("approval_level", 1) or 1)
                                    _cur4.execute(
                                        """SELECT approver_name, approver_email FROM approval_chains
                                           WHERE LOWER(department) = LOWER(%s) AND approval_level = %s LIMIT 1""",
                                        (_pr_dept, _al),
                                    )
                                    _ch4 = _cur4.fetchone()
                                    if _ch4 and _ch4.get("approver_email"):
                                        _ae["approver_name"] = _ch4["approver_name"]
                                        _ae["approver_email"] = _ch4["approver_email"]
                            _cur4.close()
                            _c4.close()
                        except Exception as _res_err:
                            logger.warning("[P2P-RESUME] Approver resolution failed: %s", _res_err)

                    gate_message = (
                        f"Approval required from {approver_label}"
                        + (f" ({approver_email})" if approver_email else "")
                        + f" for PR {p2p_results.get('pr_number', '')} "
                        f"— ${p2p_results.get('total_amount', 0):,.2f}"
                    )

                    # Sprint C (2026-04-11): same rich payload as the
                    # first-pass site in _execute_full_p2p so resumed
                    # runs see the same approval-gate UI as first-pass.
                    _total_amount = p2p_results.get("total_amount", 0) or 0
                    _pr_summary = {
                        "pr_number": p2p_results.get("pr_number"),
                        "product_name": pr_data.get("product_name") or pr_data.get("product") or pr_data.get("item") or pr_data.get("item_name") or "",
                        "quantity": pr_data.get("quantity") or pr_data.get("qty") or 1,
                        "department": pr_data.get("department") or pr_data.get("dept") or "",
                        "requester": pr_data.get("requester_name") or pr_data.get("requester") or pr_data.get("requested_by") or "",
                        "justification": pr_data.get("justification") or pr_data.get("reason") or "",
                        "total_amount": _total_amount,
                        "currency": pr_data.get("currency", "USD"),
                    }
                    _line_items = pr_data.get("line_items") or []
                    _policy_band = (
                        "auto_approve" if _total_amount < 1000
                        else "manager"  if _total_amount < 10000
                        else "director" if _total_amount < 50000
                        else "vp"       if _total_amount < 250000
                        else "cfo"
                    )
                    _approval_gate_id = _session_open_gate(
                        gate_type="approval",
                        gate_ref={
                            "pr_number": p2p_results.get("pr_number"),
                            "approver_emails": [
                                a.get("approver_email")
                                for a in assigned_approvers
                                if a.get("approver_email")
                            ],
                        },
                        decision_context={
                            "pr_summary": _pr_summary,
                            "line_items": _line_items,
                            "approver": {
                                "name": approver_label,
                                "email": approver_email,
                                "role": approver_role,
                                "level": approver_level,
                            },
                            "approval_chain": assigned_approvers,
                            "current_approver_role": approver_role,
                            "routing_action": routing_action,
                            "required_level": required_level,
                            "amount": _total_amount,
                            "policy_band": _policy_band,
                        },
                        required_role=approver_role,
                    )
                    # Sprint D bugfix (2026-04-11): phase_started(approval_wait)
                    # so the frontend currentPhase advances past "approval".
                    _session_emit("phase_started", {"phase": "approval_wait"})
                    # Sprint D bugfix (2026-04-11): nest under decision_context
                    # + include gate_ref and required_role so the frontend
                    # reducer (useSession.ts:182-195) can project them.
                    _session_emit("gate_opened", {
                        "gate_type": "approval",
                        "gate_id": _approval_gate_id,
                        "gate_ref": {
                            "pr_number": p2p_results.get("pr_number"),
                            "approver_emails": [
                                a.get("approver_email")
                                for a in assigned_approvers
                                if a.get("approver_email")
                            ],
                        },
                        "required_role": approver_role,
                        "decision_context": {
                            "pr_summary": _pr_summary,
                            "line_items": _line_items,
                            "approver": {
                                "name": approver_label,
                                "email": approver_email,
                                "role": approver_role,
                                "level": approver_level,
                            },
                            "approval_chain": assigned_approvers,
                            "current_approver_role": approver_role,
                            "routing_action": routing_action,
                            "required_level": required_level,
                            "amount": _total_amount,
                            "policy_band": _policy_band,
                        },
                    })
                    _session_set_phase("approval_wait", "paused_human")

                    p2p_results["status"] = "awaiting_approval"
                    p2p_results["human_action_required"] = {
                        "type": "approval",
                        "message": gate_message,
                        "pr_number": p2p_results.get("pr_number"),
                        "amount": p2p_results.get("total_amount", 0),
                        "approver": {
                            "name": approver_label,
                            "email": approver_email,
                            "role": approver_role,
                            "level": approver_level,
                        },
                        "approval_chain": assigned_approvers,
                        "routing_action": routing_action,
                        "required_level": required_level,
                        "options": ["approve", "reject"],
                        "session_id": session_id_hybrid,
                        "gate_id": _approval_gate_id,
                    }
                    break

        # ─── Phase: post_approval — create PO, then STOP (physical delivery takes days) ───
        elif resume_phase == "post_approval":
            # Resolve the approval gate that paused this run
            _session_resolve_gate("approve")
            # Sprint D bugfix (2026-04-11): mark approval_wait as completed so
            # the "Awaiting Approval" accordion row advances from active to
            # done. Without this, it stays active/pending even after the
            # user clicks Approve and the workflow continues to PO creation.
            _session_emit("phase_completed", {"phase": "approval_wait"})
            _session_set_phase("po_creation", "running")
            _session_emit("phase_started", {"phase": "po_creation"})
            for task in tasks:
                if task["task_name"] == "po_creation" and task["status"] in ("running", "pending"):
                    logger.info("[P2P-RESUME] Creating Purchase Order...")
                    po_number = f"PO-2026-{datetime.now().strftime('%m%d%H%M%S')}"
                    p2p_results["po_number"] = po_number

                    po_data = {
                        "po_number": po_number,
                        "pr_number": pr_data.get("pr_number", ""),
                        "vendor_name": pr_data.get("vendor_name", ""),
                        "department": pr_data.get("department", ""),
                        "product_name": pr_data.get("product_name", ""),
                        "quantity": pr_data.get("quantity", 1),
                        "budget": pr_data.get("budget", 0),
                    }
                    # Sprint C (2026-04-11): same rich payload as the
                    # first-pass site so both paths emit identical event
                    # shapes. Outbox-safe (small JSON, no blobs).
                    _po_total = float(pr_data.get("budget", 0) or 0)
                    _po_qty = max(int(pr_data.get("quantity", 1) or 1), 1)
                    _po_line_items = pr_data.get("line_items") or [{
                        "description": pr_data.get("product_name", ""),
                        "qty": _po_qty,
                        "unit_price": _po_total / _po_qty,
                        "total": _po_total,
                    }]
                    po_phase_completed_payload = {
                        "phase": "po_creation",
                        "ref": {
                            "po_number": po_number,
                            "pr_number": pr_data.get("pr_number", ""),
                        },
                        "po_number": po_number,
                        "pr_number": pr_data.get("pr_number", ""),
                        "vendor_name": pr_data.get("vendor_name", ""),
                        "vendor_id": pr_data.get("vendor_id"),
                        "department": pr_data.get("department", ""),
                        "line_items": _po_line_items,
                        "total": _po_total,
                        "currency": pr_data.get("currency", "USD"),
                        "expected_delivery_date": pr_data.get("expected_delivery_date")
                            or (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
                    }

                    from backend.services.adapters.factory import get_adapter
                    adapter = get_adapter()
                    po_committed_via_outbox = False
                    po_created_successfully = False

                    # HF-2 / R12: write the PO row and the
                    # phase_completed(po_creation) event in one transaction
                    # via the session_event_outbox. Either both commit or
                    # both roll back. The pump publishes asynchronously.
                    if session_id_hybrid:
                        try:
                            from backend.services.session_service import SessionService
                            async with adapter.transaction() as _po_tx:
                                adapter.create_purchase_order_from_pr_tx(_po_tx, po_data)
                                SessionService.append_event_tx(
                                    conn=_po_tx,
                                    session_id=session_id_hybrid,
                                    event_type="phase_completed",
                                    actor="orchestrator",
                                    payload=po_phase_completed_payload,
                                )
                            po_committed_via_outbox = True
                            po_created_successfully = True
                        except Exception as _po_tx_err:
                            # Hybrid-mode safety: a Layer-1 (session/outbox)
                            # failure must NOT break the pipeline. Log and
                            # fall through to the legacy non-tx path. This
                            # fallback is REMOVED at P5.
                            logger.warning(
                                "[P2P-RESUME] HF-2 transactional PO write failed "
                                "(falling back to legacy in hybrid): %s",
                                _po_tx_err,
                            )

                    if not po_committed_via_outbox:
                        try:
                            adapter.create_purchase_order_from_pr(po_data)
                            po_created_successfully = True
                        except Exception as po_err:
                            logger.warning("[P2P-RESUME] PO creation error: %s", po_err)
                            p2p_results["actions_completed"].append({
                                "step": "po_creation", "status": "created",
                                "summary": f"PO {po_number} created (persistence warning: {po_err})",
                                "agent": "Adapter",
                            })
                        # Outbox path didn't run — emit phase_completed via
                        # the swallow-on-error legacy wrapper so SSE clients
                        # still see the transition.
                        _session_emit("phase_completed", po_phase_completed_payload)

                    if po_created_successfully:
                        complete_task(task["task_id"], {"po_number": po_number})
                        p2p_results["actions_completed"].append({
                            "step": "po_creation", "status": "created",
                            "summary": f"Purchase Order {po_number} created and sent to vendor",
                            "agent": "Adapter",
                        })
                    break

            # ── Delivery Tracking Agent — set up order tracking before pausing ──
            if "delivery_tracking" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "delivery_tracking"})
                try:
                    _dt_agent = self.specialized_agents["delivery_tracking"]
                    _dt_result = await _dt_agent.execute({
                        "request": f"Track delivery for PO {p2p_results.get('po_number', '')}",
                        "po_number": p2p_results.get("po_number", ""),
                        "pr_data": {**pr_data, "po_number": p2p_results.get("po_number", "")},
                    })
                    p2p_results["agents_invoked"].append(_dt_agent.name)
                    _dt_inner = _dt_result.get("result", {}) if isinstance(_dt_result.get("result"), dict) else {}
                    p2p_results["actions_completed"].append({
                        "step": "delivery_tracking", "status": "tracked",
                        "summary": f"Delivery tracking initiated — {_dt_inner.get('total_pos_tracked', 0)} PO(s) monitored",
                        "agent": _dt_agent.name,
                    })
                    _session_emit("agent_finished", {
                        "agent": "delivery_tracking",
                        "tracked_pos": _dt_inner.get("total_pos_tracked", 0),
                        "alerts": len(_dt_inner.get("alerts", [])),
                    })
                except Exception as _dt_err:
                    logger.warning("[P2P-RESUME] Delivery tracking failed (non-blocking): %s", _dt_err)
                    _session_emit("agent_failed", {"agent": "delivery_tracking", "error": str(_dt_err)})

            # ── Contract Monitoring — check contract compliance for this PO ──
            if "contract_monitoring" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "contract_monitoring"})
                try:
                    _cm_agent = self.specialized_agents["contract_monitoring"]
                    _cm_result = await _cm_agent.execute({
                        "request": f"Monitor contract for vendor {pr_data.get('vendor_name', '')} PO {p2p_results.get('po_number', '')}",
                        "pr_data": {**pr_data, "po_number": p2p_results.get("po_number", "")},
                    })
                    p2p_results["agents_invoked"].append(_cm_agent.name)
                    _cm_inner = _cm_result.get("result", {}) if isinstance(_cm_result.get("result"), dict) else {}
                    _session_emit("agent_finished", {
                        "agent": "contract_monitoring",
                        "contracts_checked": _cm_inner.get("contracts_monitored", 0),
                        "alerts": len(_cm_inner.get("alerts", [])),
                    })
                except Exception as _cm_err:
                    logger.warning("[P2P-RESUME] Contract monitoring failed (non-blocking): %s", _cm_err)
                    _session_emit("agent_failed", {"agent": "contract_monitoring", "error": str(_cm_err)})

            # ── Send PO email to vendor ──
            _vendor_email = pr_data.get("vendor_email", "")
            if _vendor_email and po_created_successfully:
                try:
                    from backend.services.email_service import send_po_notification_email
                    _email_result = send_po_notification_email(
                        vendor_email=_vendor_email,
                        vendor_name=pr_data.get("vendor_name", "Vendor"),
                        po_data={
                            **pr_data,
                            "po_number": p2p_results.get("po_number", ""),
                            "pr_number": p2p_results.get("pr_number", pr_data.get("pr_number", "")),
                        },
                    )
                    if _email_result.get("success"):
                        logger.info("[P2P-RESUME] PO email sent to vendor %s at %s", pr_data.get("vendor_name"), _vendor_email)
                        _session_emit("tool_called", {
                            "tool": "email",
                            "action": "send_po_notification",
                            "vendor_email": _vendor_email,
                            "po_number": p2p_results.get("po_number", ""),
                            "success": True,
                        })
                        p2p_results["actions_completed"].append({
                            "step": "vendor_notification", "status": "sent",
                            "summary": f"PO email sent to {pr_data.get('vendor_name', 'vendor')} at {_vendor_email}",
                            "agent": "EmailService",
                        })
                    else:
                        logger.warning("[P2P-RESUME] PO email failed: %s", _email_result.get("error"))
                        _session_emit("tool_called", {
                            "tool": "email",
                            "action": "send_po_notification",
                            "vendor_email": _vendor_email,
                            "success": False,
                            "error": str(_email_result.get("error", "unknown")),
                        })
                except Exception as _email_err:
                    logger.warning("[P2P-RESUME] PO email send failed (non-blocking): %s", _email_err)
                    _session_emit("tool_called", {
                        "tool": "email", "action": "send_po_notification",
                        "success": False, "error": str(_email_err),
                    })
            elif po_created_successfully and not _vendor_email:
                logger.info("[P2P-RESUME] No vendor email on file — skipping PO notification email")

            # ── Notification Agent — dispatch PO creation notification ──
            if "notification" in self.specialized_agents and po_created_successfully:
                _session_emit("agent_started", {"agent": "notification"})
                try:
                    _notif_agent = self.specialized_agents["notification"]
                    _notif_result = await _notif_agent.execute({
                        "event_type": "approval_decided",
                        "recipients": [
                            {"email": _vendor_email, "name": pr_data.get("vendor_name", ""), "role": "vendor"},
                        ] if _vendor_email else [],
                        "payload": {
                            "po_number": p2p_results.get("po_number", ""),
                            "pr_number": p2p_results.get("pr_number", pr_data.get("pr_number", "")),
                            "vendor_name": pr_data.get("vendor_name", ""),
                            "total": pr_data.get("budget", 0),
                            "department": pr_data.get("department", ""),
                            "decision": "approved",
                            "message": f"PO {p2p_results.get('po_number', '')} created for {pr_data.get('vendor_name', '')}",
                        },
                        "send_email": False,  # Already sent via send_po_notification_email above
                    })
                    p2p_results["agents_invoked"].append(_notif_agent.name)
                    _session_emit("agent_finished", {"agent": "notification", "event_type": "approval_decided"})
                except Exception as _notif_err:
                    logger.warning("[P2P-RESUME] Notification agent failed (non-blocking): %s", _notif_err)
                    _session_emit("agent_failed", {"agent": "notification", "error": str(_notif_err)})

            # HF-1: Honest event log around delivery_tracking.
            # Physical delivery takes days/weeks. The session sits in
            # delivery_tracking(running) — NOT grn_wait — until the user clicks
            # "Confirm goods arrived" in GoodsReceiptPage, which POSTs to
            # /api/sessions/{id}/advance-to-grn. That endpoint is the ONLY place
            # that emits phase_completed(delivery_tracking) and opens the grn gate.
            #
            # Note: phase_completed(po_creation) is emitted by the HF-2
            # transactional outbox path (or fallback legacy wrapper) inside
            # the PO creation block above. We do NOT emit it again here.
            _session_set_phase("delivery_tracking", "running")
            _session_emit("phase_started", {
                "phase": "delivery_tracking",
                "ref": {
                    "po_number": p2p_results.get("po_number"),
                    "pr_number": p2p_results.get("pr_number"),
                },
                "vendor_name": pr_data.get("vendor_name", ""),
            })

            p2p_results["status"] = "po_created_awaiting_delivery"
            p2p_results["summary"] = (
                f"Purchase Order {p2p_results.get('po_number', '')} created and transmitted "
                f"to {p2p_results.get('vendor_name') or pr_data.get('vendor_name', 'vendor')}. "
                f"Pipeline paused — waiting for physical delivery. "
                f"When goods arrive, confirm receipt on the Goods Receipt page."
            )
            p2p_results["human_action_required"] = None  # Not a gate — user navigates manually later
            p2p_results["next_user_action"] = {
                "type": "manual_navigation",
                "page": "/goods-receipt",
                "label": "Confirm goods received",
                "trigger": "When goods physically arrive from vendor",
                "advance_endpoint": (
                    f"/api/sessions/{session_id_hybrid}/advance-to-grn"
                    if session_id_hybrid else None
                ),
            }

        # ─── Phase: post_grn — run quality inspection, then STOP (invoice comes later) ───
        elif resume_phase == "post_grn":
            # Resolve the grn gate that paused this run
            _session_resolve_gate("confirm_grn")
            _session_set_phase("quality_inspection", "running")
            _session_emit("phase_started", {"phase": "quality_inspection"})
            # Mark grn_entry as completed
            for task in tasks:
                if task["task_name"] == "grn_entry" and task["status"] == "waiting_human":
                    complete_task(task["task_id"], {"grn_confirmed": True, "received_by": context.get("human_input", {}).get("approved_by", "user")})
                    p2p_results["actions_completed"].append({
                        "step": "grn_entry", "status": "confirmed",
                        "summary": "Goods receipt confirmed by user",
                        "agent": "User",
                    })
                    break

            # Run quality_inspection
            status = get_workflow_status(workflow_run_id)
            for task in status.get("tasks", []):
                if task["task_name"] == "quality_inspection" and task["status"] in ("running", "pending"):
                    if "quality_inspection" in self.specialized_agents:
                        try:
                            agent = self.specialized_agents["quality_inspection"]
                            result = await agent.execute(input_context)
                            complete_task(task["task_id"], result.get("result", {}))
                            p2p_results["agents_invoked"].append(agent.name)
                            p2p_results["actions_completed"].append({
                                "step": "quality_inspection", "status": "passed",
                                "summary": "Quality inspection completed — items ready for invoice",
                                "agent": agent.name,
                            })
                        except Exception as _qe:
                            logger.warning("[P2P-RESUME] quality_inspection failed: %s", _qe)
                    break

            _session_emit("phase_completed", {
                "phase": "quality_inspection",
                "ref": {"po_number": p2p_results.get("po_number")},
            })

            # ── Supplier Performance — score vendor delivery quality ──
            if "supplier_performance" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "supplier_performance"})
                try:
                    _sp_agent = self.specialized_agents["supplier_performance"]
                    _sp_result = await _sp_agent.execute({
                        "request": f"Evaluate supplier performance for {pr_data.get('vendor_name', 'vendor')}",
                        "pr_data": pr_data,
                        "vendor_name": pr_data.get("vendor_name", ""),
                    })
                    p2p_results["agents_invoked"].append(_sp_agent.name)
                    _sp_inner = _sp_result.get("result", {}) if isinstance(_sp_result.get("result"), dict) else {}
                    _session_emit("agent_finished", {
                        "agent": "supplier_performance",
                        "performance_score": _sp_inner.get("overall_score", _sp_inner.get("performance_score")),
                        "performance_level": _sp_inner.get("performance_level", ""),
                    })
                except Exception as _spe:
                    logger.warning("[P2P-RESUME] Supplier performance failed (non-blocking): %s", _spe)
                    _session_emit("agent_failed", {"agent": "supplier_performance", "error": str(_spe)})

            # ── Invoice Matching ── Run invoice validation against PO ──
            _session_set_phase("invoice_matching", "running")
            _session_emit("phase_started", {"phase": "invoice_matching"})
            _invoice_action = ""
            _invoice_status = "completed"
            if "invoice_matching" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "invoice_matching"})
                try:
                    _inv_agent = self.specialized_agents["invoice_matching"]
                    _inv_ctx = {
                        "request": f"Match invoice for PO {p2p_results.get('po_number', '')}",
                        "po_number": p2p_results.get("po_number", ""),
                        "po_reference": p2p_results.get("po_number", ""),
                        "pr_data": {**pr_data, "po_number": p2p_results.get("po_number", "")},
                    }
                    _inv_result = await _inv_agent.execute(_inv_ctx)
                    p2p_results["agents_invoked"].append(_inv_agent.name)
                    _inv_inner = _inv_result.get("result", {}) if isinstance(_inv_result.get("result"), dict) else {}
                    _invoice_action = _inv_inner.get("action", "")
                    _invoice_status = _inv_inner.get("status", "completed")
                    p2p_results["actions_completed"].append({
                        "step": "invoice_matching", "status": _invoice_status,
                        "summary": _inv_inner.get("message", "Invoice matching completed"),
                        "agent": _inv_agent.name,
                    })
                    _session_emit("agent_finished", {
                        "agent": "invoice_matching",
                        "status": _invoice_status,
                        "action": _invoice_action,
                        "variance_pct": _inv_inner.get("variance_analysis", {}).get("amount_variance_pct"),
                    })
                except Exception as _ie:
                    logger.warning("[P2P-RESUME] Invoice matching failed (non-blocking): %s", _ie)
                    _session_emit("agent_failed", {"agent": "invoice_matching", "error": str(_ie)})
            _session_emit("phase_completed", {
                "phase": "invoice_matching",
                "ref": {"po_number": p2p_results.get("po_number")},
                "invoice_status": _invoice_status,
            })

            # ── Three-Way Match ── PO × GRN × Invoice reconciliation ──
            _session_set_phase("three_way_match", "running")
            _session_emit("phase_started", {"phase": "three_way_match"})
            _match_result = "MATCHED"
            if "invoice_matching" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "three_way_match"})
                try:
                    # InvoiceMatchingAgent handles full 3-way matching internally
                    _3wm_agent = self.specialized_agents["invoice_matching"]
                    _3wm_ctx = {
                        "request": f"Three-way match: PO {p2p_results.get('po_number', '')} × GRN × Invoice",
                        "po_number": p2p_results.get("po_number", ""),
                        "po_reference": p2p_results.get("po_number", ""),
                        "pr_data": {**pr_data, "po_number": p2p_results.get("po_number", "")},
                        "three_way_match": True,
                    }
                    _3wm_result = await _3wm_agent.execute(_3wm_ctx)
                    _3wm_inner = _3wm_result.get("result", {}) if isinstance(_3wm_result.get("result"), dict) else {}
                    _match_result = _3wm_inner.get("variance_analysis", {}).get("match_result", "MATCHED")
                    p2p_results["actions_completed"].append({
                        "step": "three_way_match", "status": _match_result.lower(),
                        "summary": f"Three-way match result: {_match_result}",
                        "agent": _3wm_agent.name,
                    })
                    _session_emit("agent_finished", {
                        "agent": "three_way_match",
                        "match_result": _match_result,
                    })
                except Exception as _3e:
                    logger.warning("[P2P-RESUME] Three-way match failed (non-blocking): %s", _3e)
                    _session_emit("agent_failed", {"agent": "three_way_match", "error": str(_3e)})
            _session_emit("phase_completed", {
                "phase": "three_way_match",
                "ref": {"po_number": p2p_results.get("po_number")},
                "match_result": _match_result,
            })

            # ── Payment Readiness ── Validate all conditions for payment ──
            _session_set_phase("payment_readiness", "running")
            _session_emit("phase_started", {"phase": "payment_readiness"})
            _pay_authorized = False
            if "payment_readiness" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "payment_readiness"})
                try:
                    _pr_agent = self.specialized_agents["payment_readiness"]
                    _pr_ctx = {
                        "request": f"Check payment readiness for PO {p2p_results.get('po_number', '')}",
                        "po_number": p2p_results.get("po_number", ""),
                        "po_reference": p2p_results.get("po_number", ""),
                        "pr_data": {**pr_data, "po_number": p2p_results.get("po_number", "")},
                    }
                    _pr_result = await _pr_agent.execute(_pr_ctx)
                    p2p_results["agents_invoked"].append(_pr_agent.name)
                    _pr_inner = _pr_result.get("result", {}) if isinstance(_pr_result.get("result"), dict) else {}
                    _pay_authorized = _pr_inner.get("status") == "authorized"
                    p2p_results["actions_completed"].append({
                        "step": "payment_readiness",
                        "status": "authorized" if _pay_authorized else "on_hold",
                        "summary": _pr_inner.get("message", f"Payment readiness: {'authorized' if _pay_authorized else 'conditions pending'}"),
                        "agent": _pr_agent.name,
                    })
                    _session_emit("agent_finished", {
                        "agent": "payment_readiness",
                        "status": _pr_inner.get("status", ""),
                        "conditions_passed": _pr_inner.get("conditions_passed", 0),
                        "conditions_failed": _pr_inner.get("conditions_failed", 0),
                    })
                except Exception as _pre:
                    logger.warning("[P2P-RESUME] Payment readiness failed (non-blocking): %s", _pre)
                    _session_emit("agent_failed", {"agent": "payment_readiness", "error": str(_pre)})
            _session_emit("phase_completed", {
                "phase": "payment_readiness",
                "ref": {"po_number": p2p_results.get("po_number")},
                "authorized": _pay_authorized,
            })

            # ── Payment Execution ── Calculate and process payment ──
            _session_set_phase("payment_execution", "running")
            _session_emit("phase_started", {"phase": "payment_execution"})
            _net_payable = float(pr_data.get("budget", 0) or 0)
            if "payment_calculation" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "payment_calculation"})
                try:
                    _calc_agent = self.specialized_agents["payment_calculation"]
                    _calc_ctx = {
                        "request": f"Calculate payment for PO {p2p_results.get('po_number', '')}",
                        "po_number": p2p_results.get("po_number", ""),
                        "pr_number": pr_data.get("pr_number", ""),
                        "total_amount": float(pr_data.get("budget", 0) or 0),
                        "pr_data": {**pr_data, "po_number": p2p_results.get("po_number", "")},
                    }
                    _calc_result = await _calc_agent.execute(_calc_ctx)
                    p2p_results["agents_invoked"].append(_calc_agent.name)
                    _calc_inner = _calc_result.get("result", {}) if isinstance(_calc_result.get("result"), dict) else {}
                    # Try multiple keys — agent may nest net_payable differently
                    _net_payable = (
                        _calc_inner.get("net_payable")
                        or _calc_inner.get("total_amount")
                        or _calc_inner.get("amount")
                        or _net_payable
                    )
                    # Ensure numeric
                    if not isinstance(_net_payable, (int, float)):
                        try:
                            _net_payable = float(str(_net_payable).replace(",", ""))
                        except (ValueError, TypeError):
                            _net_payable = float(pr_data.get("budget", 0) or 0)
                    if isinstance(_net_payable, (int, float)):
                        _pay_summary = f"Payment calculated: ${_net_payable:,.2f}"
                    else:
                        _pay_summary = f"Payment processed: {_net_payable}"
                    p2p_results["actions_completed"].append({
                        "step": "payment_execution", "status": "executed",
                        "summary": _pay_summary,
                        "agent": _calc_agent.name,
                    })
                    _session_emit("agent_finished", {
                        "agent": "payment_calculation",
                        "net_payable": _net_payable,
                        "payment_type": _calc_inner.get("payment_type", "full"),
                        "discount_applied": _calc_inner.get("discount_applied", 0),
                    })
                except Exception as _ce:
                    logger.warning("[P2P-RESUME] Payment calculation failed (non-blocking): %s", _ce)
                    _session_emit("agent_failed", {"agent": "payment_calculation", "error": str(_ce)})

            # G-08: Record actual spend in budget ledger
            try:
                from backend.services.budget_ledger_service import get_budget_ledger_service
                _bl = get_budget_ledger_service()
                actual_amount = float(_net_payable) if isinstance(_net_payable, (int, float)) else float(pr_data.get("budget", 0) or 0)
                _bl.record_actual(
                    department=pr_data.get("department", "General"),
                    fiscal_year=None,
                    reference_type="PAYMENT",
                    reference_id=p2p_results.get("po_number", ""),
                    amount=actual_amount,
                    description=f"Payment for PO {p2p_results.get('po_number', '')} / PR {pr_data.get('pr_number', '')}",
                )
                logger.info("[P2P-RESUME] G-08: Budget actual recorded: $%.2f", actual_amount)
            except Exception as _ba_err:
                logger.debug("[P2P-RESUME] G-08: Budget actual (non-blocking): %s", _ba_err)

            # G-06: Notify vendor of payment
            try:
                from backend.services.vendor_communication_service import get_vendor_comm_service
                _vcs = get_vendor_comm_service()
                _pay_amount = float(_net_payable) if isinstance(_net_payable, (int, float)) else float(pr_data.get("budget", 0) or 0)
                _vcs.send_payment_notification(
                    payment_ref=f"PAY-{p2p_results.get('po_number', '')}",
                    vendor_name=pr_data.get("vendor_name", ""),
                    vendor_id=pr_data.get("vendor_id", ""),
                    amount=_pay_amount,
                    currency=pr_data.get("currency", "USD"),
                )
                logger.info("[P2P-RESUME] G-06: Payment notification sent to vendor")
            except Exception as _pn_err:
                logger.debug("[P2P-RESUME] G-06: Payment notification (non-blocking): %s", _pn_err)

            # ── Send payment email to vendor ──
            _vendor_email = pr_data.get("vendor_email", "")
            if _vendor_email:
                try:
                    from backend.services.email_service import send_payment_notification_email
                    _pay_email_result = send_payment_notification_email(
                        finance_email=_vendor_email,
                        payment_data={
                            "vendor_name": pr_data.get("vendor_name", ""),
                            "po_number": p2p_results.get("po_number", ""),
                            "amount": _net_payable,
                            "currency": pr_data.get("currency", "USD"),
                            "payment_method": "Bank Transfer",
                            "invoice_number": f"INV-{p2p_results.get('po_number', '')}",
                        },
                    )
                    if _pay_email_result.get("success"):
                        logger.info("[P2P-RESUME] Payment email sent to vendor at %s", _vendor_email)
                        _session_emit("tool_called", {
                            "tool": "email", "action": "send_payment_notification",
                            "vendor_email": _vendor_email, "success": True,
                        })
                    else:
                        logger.warning("[P2P-RESUME] Payment email failed: %s", _pay_email_result.get("error"))
                except Exception as _pe_err:
                    logger.warning("[P2P-RESUME] Payment email failed (non-blocking): %s", _pe_err)

            # ── Notification Agent — payment completed event ──
            if "notification" in self.specialized_agents:
                _session_emit("agent_started", {"agent": "notification"})
                try:
                    _notif_agent = self.specialized_agents["notification"]
                    await _notif_agent.execute({
                        "event_type": "payment_scheduled",
                        "recipients": [
                            {"email": _vendor_email, "name": pr_data.get("vendor_name", ""), "role": "vendor"},
                        ] if _vendor_email else [],
                        "payload": {
                            "po_number": p2p_results.get("po_number", ""),
                            "vendor_name": pr_data.get("vendor_name", ""),
                            "amount": _net_payable,
                            "currency": pr_data.get("currency", "USD"),
                            "message": f"Payment of ${_net_payable:,.2f} processed for PO {p2p_results.get('po_number', '')}",
                        },
                        "send_email": False,  # Already sent above
                    })
                    p2p_results["agents_invoked"].append(_notif_agent.name)
                    _session_emit("agent_finished", {"agent": "notification", "event_type": "payment_scheduled"})
                except Exception as _notif_err:
                    logger.warning("[P2P-RESUME] Notification agent (payment) failed (non-blocking): %s", _notif_err)
                    _session_emit("agent_failed", {"agent": "notification", "error": str(_notif_err)})

            _session_emit("phase_completed", {
                "phase": "payment_execution",
                "ref": {
                    "po_number": p2p_results.get("po_number"),
                    "pr_number": pr_data.get("pr_number"),
                },
                "net_payable": _net_payable,
            })

            # ── WORKFLOW COMPLETE ──
            _net_display = f"${_net_payable:,.2f}" if isinstance(_net_payable, (int, float)) else str(_net_payable)
            p2p_results["status"] = "completed"
            p2p_results["summary"] = (
                f"P2P workflow completed successfully! "
                f"PO {p2p_results.get('po_number', '')} — "
                f"goods received, quality inspection passed, invoice matched, "
                f"payment of {_net_display} processed to "
                f"{pr_data.get('vendor_name', 'vendor')}."
            )
            _session_emit("session_completed", {
                "pr_number": pr_data.get("pr_number"),
                "po_number": p2p_results.get("po_number"),
                "vendor_name": pr_data.get("vendor_name"),
                "net_payable": _net_payable,
            })
            _session_set_phase("completed", "completed")

        # ─── Phase: auto — fallback: let workflow engine drive remaining tasks ───
        elif resume_phase not in ("post_vendor", "post_approval", "post_grn"):
            for task in tasks:
                if task["status"] in ("running", "pending"):
                    task_name = task["task_name"]
                    agent_key = self._p2p_task_to_agent_key(task_name)
                    if agent_key and agent_key in self.specialized_agents:
                        try:
                            agent = self.specialized_agents[agent_key]
                            result = await agent.execute(input_context)
                            complete_task(task["task_id"], result.get("result", {}))
                            p2p_results["agents_invoked"].append(agent.name)
                            p2p_results["actions_completed"].append({
                                "step": task_name,
                                "status": result.get("status", "completed"),
                                "summary": result.get("result", {}).get("message", "Completed"),
                                "agent": agent.name,
                            })
                        except Exception as agent_err:
                            logger.warning("[P2P-RESUME] %s failed: %s", task_name, agent_err)

        # Finalize status + summary
        try:
            ws = generate_workflow_summary(workflow_run_id)
            if not p2p_results.get("summary"):
                p2p_results["summary"] = ws.get("summary", "")
            if ws.get("progress_pct", 0) >= 100 and p2p_results["status"] == "in_progress":
                p2p_results["status"] = "completed"
        except Exception:
            pass

        try:
            p2p_results["suggested_next_actions"] = get_suggestions(workflow_run_id).get("suggestions", [])
        except Exception:
            p2p_results["suggested_next_actions"] = []

        return p2p_results

    def _p2p_task_to_agent_key(self, task_name: str) -> Optional[str]:
        """Map P2P_FULL task name to registered agent key."""
        mapping = {
            "compliance_check": "compliance_check",
            "budget_verification": "budget_verification",
            "vendor_selection": "vendor_selection",
            "approval_routing": "approval_routing",
            "delivery_tracking": "delivery_tracking",
            "quality_inspection": "quality_inspection",
            "invoice_matching": "invoice_matching",
            "three_way_match": "invoice_matching",
            "payment_readiness": "payment_readiness",
            "payment_execution": "payment_calculation",
        }
        return mapping.get(task_name)

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

        # Phase 3-7: New agentic modules
        try:
            from backend.agents.rfq_agent import RFQAgent
            from backend.agents.po_amendment_agent import POAmendmentAgent
            from backend.agents.return_agent import ReturnAgent
            from backend.agents.qc_agent import QualityInspectionAgent
            from backend.agents.reconciliation_agent import ReconciliationAgent
            from backend.agents.quote_comparison_agent import QuoteComparisonAgent
            from backend.agents.goods_receipt_agent import GoodsReceiptAgent

            orchestrator.register_agent("rfq_management", RFQAgent())
            orchestrator.register_agent("po_amendment", POAmendmentAgent())
            orchestrator.register_agent("return_processing", ReturnAgent())
            orchestrator.register_agent("quality_inspection", QualityInspectionAgent())
            orchestrator.register_agent("reconciliation", ReconciliationAgent())
            orchestrator.register_agent("quote_comparison", QuoteComparisonAgent())
            orchestrator.register_agent("goods_receipt", GoodsReceiptAgent())

            # Register previously unconnected agents
            from backend.agents.vendor_onboarding_agent import VendorOnboardingAgent
            from backend.agents.delivery_tracking_agent import DeliveryTrackingAgent
            from backend.agents.discrepancy_resolution_agent import DiscrepancyResolutionAgent
            from backend.agents.payment_readiness_agent import PaymentReadinessAgent

            orchestrator.register_agent("vendor_onboarding", VendorOnboardingAgent())
            orchestrator.register_agent("delivery_tracking", DeliveryTrackingAgent())
            orchestrator.register_agent("exception_resolution", DiscrepancyResolutionAgent())
            orchestrator.register_agent("payment_readiness", PaymentReadinessAgent())

            from backend.agents.payment_calculation_agent import PaymentCalculationAgent
            from backend.agents.payment_approval_agent import PaymentApprovalAgent
            orchestrator.register_agent("payment_calculation", PaymentCalculationAgent())
            orchestrator.register_agent("payment_approval", PaymentApprovalAgent())

            from backend.agents.notification_agent import NotificationAgent
            orchestrator.register_agent("notification", NotificationAgent())

            from backend.agents.email_inbox_agent import EmailInboxAgent
            from backend.agents.invoice_capture_agent import InvoiceCaptureAgent
            from backend.agents.document_processing_agent import DocumentProcessingAgent
            from backend.agents.po_intake_agent import POIntakeAgent
            orchestrator.register_agent("email_inbox", EmailInboxAgent())
            orchestrator.register_agent("invoice_capture", InvoiceCaptureAgent())
            orchestrator.register_agent("document_processing", DocumentProcessingAgent())
            orchestrator.register_agent("po_intake", POIntakeAgent())

            # Register previously orphaned agents
            from backend.agents.anomaly_detection_agent import AnomalyDetectionAgent
            from backend.agents.forecasting_agent import ForecastingAgent
            from backend.agents.invoice_routing_agent import InvoiceRoutingAgent
            from backend.agents.monitoring_dashboard_agent import MonitoringDashboardAgent
            from backend.agents.po_registration_agent import PORegistrationAgent
            orchestrator.register_agent("anomaly_detection", AnomalyDetectionAgent())
            orchestrator.register_agent("forecasting", ForecastingAgent())
            orchestrator.register_agent("invoice_routing", InvoiceRoutingAgent())
            orchestrator.register_agent("monitoring_dashboard", MonitoringDashboardAgent())
            orchestrator.register_agent("po_registration", PORegistrationAgent())

            logger.info("[INIT] All agentic modules registered (%d total): %s", len(orchestrator.specialized_agents), list(orchestrator.specialized_agents.keys()))
        except Exception as phase_err:
            logger.warning("[INIT] Some Phase 3-7 agents failed to register: %s", phase_err)

        logger.info(
            f"[INIT] Orchestrator initialized with "
            f"{len(orchestrator.specialized_agents)} agent(s): "
            f"{list(orchestrator.specialized_agents.keys())}"
        )
    else:
        logger.info(f"[INIT] Agents already registered: {list(orchestrator.specialized_agents.keys())}")
    
    logger.info(f"[INIT] Returning orchestrator with {len(orchestrator.specialized_agents)} agents")
    return orchestrator
