"""
Base Agent Framework for Agentic Procurement System
Implements: Observe → Decide → Act → Learn pattern
"""

from typing import Dict, Any, List, Optional, Callable
from abc import ABC, abstractmethod
from enum import Enum
import asyncio
import logging
import time
import json
import uuid
from datetime import datetime

from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

# LangChain 1.x removed AgentExecutor, ConversationBufferMemory, and related.
# Guard imports so BaseAgent (used by all 5 agents) still initialises.
try:
    from langchain.agents import AgentExecutor, create_openai_functions_agent
    from langchain.memory import ConversationBufferMemory
    from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
    _LEGACY_LANGCHAIN = True
except ImportError:
    _LEGACY_LANGCHAIN = False
    # Stub classes so ToolBasedAgent definition doesn't crash at import time.
    class AgentExecutor:  # type: ignore
        pass
    class ConversationBufferMemory:  # type: ignore
        def __init__(self, **_):
            self.chat_history = []
    class ChatPromptTemplate:  # type: ignore
        @staticmethod
        def from_messages(_):
            return None
    class MessagesPlaceholder:  # type: ignore
        def __init__(self, **_):
            pass
    def create_openai_functions_agent(*_, **__):  # type: ignore
        return None

from backend.services.db_pool import get_db_connection, return_db_connection
from backend.services import agent_event_stream
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Agent execution status"""
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    LEARNING = "learning"
    ERROR = "error"
    COMPLETED = "completed"


class AgentDecision:
    """Represents an agent's decision with confidence and reasoning"""
    
    def __init__(
        self,
        action: str,
        reasoning: str,
        confidence: float,
        context: Dict[str, Any],
        alternatives: Optional[List[str]] = None
    ):
        self.action = action
        self.reasoning = reasoning
        self.confidence = confidence  # 0.0 to 1.0
        self.context = context
        self.alternatives = alternatives or []
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "context": self.context,
            "alternatives": self.alternatives,
            "timestamp": self.timestamp.isoformat()
        }


class BaseAgent(ABC):
    """
    Base class for all agentic workflows in the procurement system.
    
    Implements the core agentic pattern:
    1. OBSERVE: Monitor environment and input
    2. DECIDE: Choose optimal action using LLM reasoning
    3. ACT: Execute action via tools
    4. LEARN: Update patterns from results
    
    Key Features:
    - Error recovery with automatic retry
    - Human escalation when confidence is low
    - Action logging for audit trail
    - Decision history for learning
    """
    
    def __init__(
        self,
        name: str,
        description: str,
        tools: Optional[List[Tool]] = None,
        temperature: float = 0.2,
        max_retries: int = 3
    ):
        self.name = name
        self.description = description
        self.tools = tools or []
        self.temperature = temperature
        self.max_retries = max_retries
        self.status = AgentStatus.IDLE
        
        # Initialize LLM with timeout and request settings
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=temperature,
            request_timeout=15.0,  # 15 second timeout per LLM call
            max_retries=2          # Retry twice on timeout
        )
        
        # Agent memory for context retention
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        # Decision history (last 100 decisions)
        self.decision_history: List[AgentDecision] = []
        self.max_history = 100
        
        logger.info(f"Initialized agent: {self.name}")
    
    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main execution method - must be implemented by subclasses.
        
        Args:
            input_data: Input context for the agent
            
        Returns:
            Dictionary with execution results
        """
        pass
    
    async def observe(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        OBSERVE phase: Analyze input and gather additional context.
        
        Args:
            context: Initial input context
            
        Returns:
            Enriched context with observations
        """
        self.status = AgentStatus.OBSERVING
        logger.info(f"[{self.name}] Observing context...")
        
        # Emit event if stream available
        event_stream = context.get("event_stream")
        if event_stream:
            from backend.services.agent_event_stream import AgentEventType
            # Determine which data sources will be accessed based on available tools
            sources = []
            for tool in self.tools:
                if "odoo" in tool.name.lower() or "purchase" in tool.name.lower() or "vendor" in tool.name.lower():
                    if "Odoo ERP" not in sources:
                        sources.append("Odoo ERP")
                if "budget" in tool.name.lower() or "approval" in tool.name.lower():
                    if "PostgreSQL Database" not in sources:
                        sources.append("PostgreSQL Database")
                    if "Budget Tables" not in sources:
                        sources.append("Budget Tables")
            
            await event_stream.emit(AgentEventType.OBSERVING, {
                "agent": self.name,
                "message": f"{self.name} gathering context and data...",
                "phase": "observe",
                "sources": sources if sources else ["Internal Memory"]
            })
        
        # Subclasses can override to add custom observations
        observations = {
            "agent": self.name,
            "timestamp": datetime.now().isoformat(),
            "input_context": context,
            "available_tools": [tool.name for tool in self.tools]
        }
        
        # Emit observation complete
        if event_stream:
            await event_stream.emit(AgentEventType.OBSERVATION_COMPLETE, {
                "agent": self.name,
                "observations": f"Loaded {len(observations)} data points",
                "records_count": f"{len(self.tools)} tools available",
                "tools_available": len(self.tools)
            })
        
        return observations
    
    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        DECIDE phase: Use LLM to determine optimal action.
        
        Args:
            observations: Context from observe phase
            
        Returns:
            AgentDecision with action, reasoning, and confidence
        """
        self.status = AgentStatus.THINKING
        logger.info(f"[{self.name}] Deciding on action...")
        
        # NOTE: SSE events are emitted in execute_with_recovery() to avoid duplicates
        # when subclasses override this method
        
        # Build decision prompt
        decision_prompt = self._build_decision_prompt(observations)
        
        # Get LLM decision
        response = await self.llm.ainvoke(decision_prompt)
        
        # Parse decision (simplified - in production, use structured output)
        decision = self._parse_decision(response.content, observations)
        
        # Store decision in history
        self._add_to_history(decision)
        
        logger.info(
            f"[{self.name}] Decision: {decision.action} "
            f"(confidence: {decision.confidence:.2f})"
        )
        
        return decision
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def act(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        ACT phase: Execute the decided action with error recovery.
        
        Args:
            decision: The decision to execute
            
        Returns:
            Result of the action
        """
        self.status = AgentStatus.ACTING
        logger.info(f"[{self.name}] Acting on decision: {decision.action}")
        
        # Emit event if stream available
        event_stream = decision.context.get("input_context", {}).get("event_stream")
        if event_stream:
            from backend.services.agent_event_stream import AgentEventType
            # Get tool names being used
            tool_names = [tool.name for tool in self.tools]
            await event_stream.emit(AgentEventType.ACTING, {
                "agent": self.name,
                "message": f"{self.name} executing action: {decision.action}",
                "action": decision.action,
                "phase": "act",
                "tools": tool_names[:5],  # Candidate tools (not guaranteed invocation)
                "tools_estimated": True
            })
        
        start_time = time.time()
        
        try:
            # Execute the action using tools
            result = await self._execute_action(decision)
            
            execution_time = int((time.time() - start_time) * 1000)
            
            # Log successful action
            await self._log_action(
                action_type=decision.action,
                input_data=decision.context,
                output_data=result,
                success=True,
                execution_time_ms=execution_time
            )
            
            logger.info(
                f"[{self.name}] Action completed successfully "
                f"({execution_time}ms)"
            )
            
            # Emit action complete
            if event_stream:
                # Extract result summary if available
                result_summary = "Success"
                if isinstance(result, dict):
                    if "status" in result:
                        result_summary = f"{result['status'].title()}"
                    if "budget_verified" in result:
                        result_summary += f" - Budget {'verified' if result['budget_verified'] else 'insufficient'}"
                    if "action" in result:
                        result_summary = f"{result['action'].replace('_', ' ').title()}"
                
                await event_stream.emit(AgentEventType.ACTION_COMPLETE, {
                    "agent": self.name,
                    "action": decision.action,
                    "execution_time_ms": execution_time,
                    "success": True,
                    "result": result_summary
                })
            
            return result
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            
            # Log failed action
            await self._log_action(
                action_type=decision.action,
                input_data=decision.context,
                output_data={},
                success=False,
                error_message=str(e),
                execution_time_ms=execution_time
            )
            
            logger.error(f"[{self.name}] Action failed: {str(e)}")
            
            # Try alternative action if available
            if decision.alternatives:
                logger.info(
                    f"[{self.name}] Trying alternative: "
                    f"{decision.alternatives[0]}"
                )
                # Recursive call with alternative (will retry via decorator)
                alternative_decision = AgentDecision(
                    action=decision.alternatives[0],
                    reasoning=f"Fallback from {decision.action}",
                    confidence=decision.confidence * 0.8,
                    context=decision.context,
                    alternatives=decision.alternatives[1:]
                )
                return await self.act(alternative_decision)
            
            # If no alternatives, raise for human escalation
            raise
    
    async def learn(self, learn_context: Dict[str, Any]) -> None:
        """
        LEARN phase: Update patterns based on execution results.
        
        Args:
            learn_context: Dict containing result, decision, and event_stream
        """
        self.status = AgentStatus.LEARNING
        logger.info(f"[{self.name}] Learning from result...")
        
        # Extract components
        result = learn_context.get("result", {})
        event_stream = learn_context.get("event_stream")
        
        if event_stream:
            from backend.services.agent_event_stream import AgentEventType
            await event_stream.emit(AgentEventType.LEARNING, {
                "agent": self.name,
                "message": f"{self.name} learning from execution outcome...",
                "phase": "learn",
                "table": "agent_actions"  # Primary logging table
            })
        
        # Subclasses can implement custom learning logic
        # For now, we just maintain decision history
        
        if len(self.decision_history) > self.max_history:
            # Keep only recent decisions
            self.decision_history = self.decision_history[-self.max_history:]
        
        # Emit learning complete
        if event_stream:
            await event_stream.emit(AgentEventType.LEARNING_COMPLETE, {
                "agent": self.name,
                "decision_history_size": len(self.decision_history),
                "recorded": True
            })
    
    async def execute_with_recovery(
        self,
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Full execution cycle with error recovery and human escalation.
        
        This is the main entry point that orchestrates:
        OBSERVE → DECIDE → ACT → LEARN
        
        Args:
            input_data: Input context
            
        Returns:
            Execution result
        """
        try:
            request_id = input_data.get("request_id")
            if not request_id:
                request_id = f"exec-{uuid.uuid4().hex[:10]}"
                input_data["request_id"] = request_id
            agent_event_stream.ensure_executive_session(
                request_id,
                metadata={"request": input_data.get("request", ""), "mode": input_data.get("mode", "orchestrated")},
            )

            def _tools_snapshot() -> List[str]:
                return [tool.name for tool in self.tools]

            event_stream = input_data.get("event_stream")

            # 1. OBSERVE
            observe_started = int(time.time() * 1000)
            if not event_stream:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "OBSERVE",
                    tool_calls=_tools_snapshot(),
                    status="active",
                    raw_data=input_data,
                )
            observations = await self.observe(input_data)
            if not event_stream:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "OBSERVE",
                    tool_calls=_tools_snapshot(),
                    duration_ms=max(int(time.time() * 1000) - observe_started, 0),
                    status="completed",
                    raw_data=observations,
                )
            
            # No synthetic delay: keep per-phase timing true to real execution.
            
            # Emit DECIDING event (for agents that override decide without SSE emission)
            if event_stream:
                from backend.services.agent_event_stream import AgentEventType
                await event_stream.emit(AgentEventType.DECIDING, {
                    "agent": self.name,
                    "message": f"{self.name} analyzing data and making decision with AI...",
                    "phase": "decide",
                    "model": "GPT-4o-mini"
                })
            else:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "DECIDE",
                    tool_calls=_tools_snapshot(),
                    status="active",
                    raw_data=observations,
                )
            
            # 2. DECIDE
            decide_started = int(time.time() * 1000)
            decision = await self.decide(observations)
            
            # Emit DECISION_MADE event (for agents that override decide without SSE emission)
            if event_stream:
                await event_stream.emit(AgentEventType.DECISION_MADE, {
                    "agent": self.name,
                    "action": decision.action,
                    "reasoning": decision.reasoning[:200] if decision.reasoning else "Decision made",
                    "confidence": decision.confidence,
                    "alternatives": decision.alternatives[:3] if decision.alternatives else []
                })
            else:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "DECIDE",
                    confidence_score=decision.confidence,
                    tool_calls=_tools_snapshot(),
                    duration_ms=max(int(time.time() * 1000) - decide_started, 0),
                    status="completed",
                    raw_data=decision.to_dict(),
                )
            
            # No synthetic delay: keep per-phase timing true to real execution.
            
            # Check if human approval needed (low confidence)
            if decision.confidence < 0.6:
                logger.warning(
                    f"[{self.name}] Low confidence ({decision.confidence:.2f}), "
                    "requesting human approval"
                )
                
                # Save to pending_approvals table
                approval_id = self._save_pending_approval(decision, input_data)
                agent_event_stream.finalize_executive_session(request_id, "escalated")
                
                return {
                    "status": "pending_human_approval",
                    "approval_id": approval_id,
                    "agent_name": self.name,
                    "confidence": decision.confidence,
                    "decision": decision.to_dict(),
                    "message": (
                        f"Agent confidence too low ({decision.confidence:.2f}). "
                        f"Saved as {approval_id} for human review. "
                        f"Reason: {decision.reasoning}"
                    )
                }
            
            # 3. ACT (with automatic retry)
            act_started = int(time.time() * 1000)
            if not event_stream:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "ACT",
                    confidence_score=decision.confidence,
                    tool_calls=_tools_snapshot(),
                    status="active",
                    raw_data=decision.to_dict(),
                )
            result = await self.act(decision)
            if not event_stream:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "ACT",
                    confidence_score=decision.confidence,
                    tool_calls=_tools_snapshot(),
                    duration_ms=max(int(time.time() * 1000) - act_started, 0),
                    status="completed",
                    raw_data=result if isinstance(result, dict) else {"result": result},
                )
            
            # 4. LEARN (pass input_data for event_stream access)
            learn_started = int(time.time() * 1000)
            if not event_stream:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "LEARN",
                    confidence_score=decision.confidence,
                    tool_calls=_tools_snapshot(),
                    status="active",
                    raw_data=result if isinstance(result, dict) else {"result": result},
                )
            learn_context = {
                "result": result,
                "decision": decision,
                "event_stream": input_data.get("event_stream")
            }
            await self.learn(learn_context)
            if not event_stream:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "LEARN",
                    confidence_score=decision.confidence,
                    tool_calls=_tools_snapshot(),
                    duration_ms=max(int(time.time() * 1000) - learn_started, 0),
                    status="completed",
                    raw_data={"decision": decision.to_dict()},
                )
            
            self.status = AgentStatus.COMPLETED
            agent_event_stream.finalize_executive_session(request_id, "success")
            
            return {
                "status": "success",
                "agent": self.name,
                "decision": decision.to_dict(),
                "result": result
            }
            
        except Exception as e:
            self.status = AgentStatus.ERROR
            logger.error(f"[{self.name}] Execution failed: {str(e)}")
            request_id = input_data.get("request_id")
            if request_id:
                await agent_event_stream.emit_executive_step(
                    request_id,
                    self.name,
                    "ACT",
                    tool_calls=[tool.name for tool in self.tools],
                    status="failed",
                    raw_data={"error": str(e)},
                )
                agent_event_stream.finalize_executive_session(request_id, "error")
            
            return {
                "status": "error",
                "agent": self.name,
                "error": str(e),
                "message": "Agent failed after maximum retries. Human intervention required."
            }
    
    # Helper methods
    
    def _build_decision_prompt(self, observations: Dict[str, Any]) -> str:
        """Build LLM prompt for decision-making"""
        return f"""
You are {self.name}, an AI agent in a procurement automation system.

Your purpose: {self.description}

Available tools: {', '.join([tool.name for tool in self.tools])}

Current observations:
{json.dumps(observations, indent=2)}

Recent decision history (last 5):
{self._format_recent_decisions()}

Task: Analyze the situation and decide on the best action.

Respond in JSON format:
{{
    "action": "tool_name_or_action",
    "reasoning": "why this is the best choice",
    "confidence": 0.85,
    "alternatives": ["alternative_action_1", "alternative_action_2"]
}}
"""
    
    def _parse_decision(
        self,
        llm_response: str,
        observations: Dict[str, Any]
    ) -> AgentDecision:
        """Parse LLM response into AgentDecision"""
        try:
            # Try to parse JSON response
            data = json.loads(llm_response)
            return AgentDecision(
                action=data.get("action", "unknown"),
                reasoning=data.get("reasoning", "No reasoning provided"),
                confidence=float(data.get("confidence", 0.5)),
                context=observations,
                alternatives=data.get("alternatives", [])
            )
        except (json.JSONDecodeError, ValueError):
            # Fallback if LLM didn't return valid JSON
            return AgentDecision(
                action="parse_error",
                reasoning=f"Failed to parse LLM response: {llm_response[:100]}",
                confidence=0.3,
                context=observations,
                alternatives=[]
            )
    
    def _format_recent_decisions(self, count: int = 5) -> str:
        """Format recent decisions for context"""
        if not self.decision_history:
            return "No previous decisions"
        
        recent = self.decision_history[-count:]
        formatted = []
        for i, decision in enumerate(recent, 1):
            formatted.append(
                f"{i}. {decision.action} (confidence: {decision.confidence:.2f}) "
                f"- {decision.reasoning[:50]}..."
            )
        return "\n".join(formatted)
    
    def _add_to_history(self, decision: AgentDecision) -> None:
        """Add decision to history"""
        self.decision_history.append(decision)
    
    def _save_pending_approval(
        self,
        decision: AgentDecision,
        input_data: Dict[str, Any]
    ) -> str:
        """
        Save low-confidence decision to pending_approvals table.
        
        Args:
            decision: The decision to save
            input_data: Original input context
            
        Returns:
            Generated approval_id
        """
        try:
            from backend.services import hybrid_query
            
            # Generate unique approval ID
            approval_id = f"APR-{datetime.now().year}-{int(time.time() * 1000) % 100000:05d}"
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO pending_approvals 
                (approval_id, agent_name, request_type, request_data, recommendation, 
                 confidence_score, reasoning, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
            """, (
                approval_id,
                self.name,
                input_data.get("request_type", "generic"),
                json.dumps(input_data),
                json.dumps(decision.context),
                decision.confidence,
                decision.reasoning
            ))
            
            conn.commit()
            cursor.close()

            return_db_connection(conn)
            
            logger.info(f"[{self.name}] Saved pending approval: {approval_id}")
            return approval_id
            
        except Exception as e:
            logger.error(f"[{self.name}] Failed to save pending approval: {e}")
            return f"ERROR-{int(time.time())}"
    
    @abstractmethod
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """
        Execute the actual action - must be implemented by subclasses.
        
        Args:
            decision: The decision to execute
            
        Returns:
            Action result
        """
        pass
    
    def _serialize_for_json(self, obj: Any) -> Any:
        """
        Recursively serialize objects to JSON-compatible format.
        Handles datetime objects by converting to ISO 8601 strings.
        Filters out non-serializable objects like event_stream.
        
        Args:
            obj: Object to serialize
            
        Returns:
            JSON-serializable object
        """
        if isinstance(obj, (datetime, __import__('datetime').date)):
            return obj.isoformat()
        elif isinstance(obj, dict):
            # Filter out event_stream and other non-serializable keys
            return {
                k: self._serialize_for_json(v) 
                for k, v in obj.items() 
                if k not in ["event_stream", "llm", "tools"] and not callable(v)
            }
        elif isinstance(obj, list):
            return [self._serialize_for_json(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(self._serialize_for_json(item) for item in obj)
        # Skip non-serializable objects (return None instead of the object)
        elif hasattr(obj, '__dict__') or callable(obj):
            return str(type(obj).__name__)  # Return type name for debugging
        return obj

    async def _log_action(
        self,
        action_type: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        success: bool,
        error_message: Optional[str] = None,
        execution_time_ms: int = 0
    ) -> None:
        """
        Log action to agent_actions table for monitoring.
        
        Args:
            action_type: Type of action performed
            input_data: Input data for the action
            output_data: Output data from the action
            success: Whether action succeeded
            error_message: Error message if failed
            execution_time_ms: Execution time in milliseconds
        """
        
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Truncate action_type to fit VARCHAR(50) constraint
            truncated_action = action_type[:50] if action_type else "unknown"
            
            # Serialize datetime objects to JSON-compatible format
            serialized_input = self._serialize_for_json(input_data)
            serialized_output = self._serialize_for_json(output_data)
            
            cur.execute("""
                INSERT INTO agent_actions 
                    (agent_name, action_type, input_data, output_data, 
                     success, error_message, execution_time_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    self.name,
                    truncated_action,
                    json.dumps(serialized_input),
                    json.dumps(serialized_output),
                    success,
                    error_message,
                    execution_time_ms
                ))
            conn.commit()
            cur.close()
            return_db_connection(conn)
        except Exception as e:
            logger.error(f"Failed to log action: {str(e)}")
            if 'conn' in locals():
                return_db_connection(conn)


class ToolBasedAgent(BaseAgent):
    """
    Agent that uses LangChain tools for actions.
    Suitable for agents that interact with external systems (Odoo, database).
    """
    
    def __init__(self, name: str, description: str, tools: List[Tool], **kwargs):
        super().__init__(name, description, tools, **kwargs)
        
        # Create LangChain agent with tools
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""You are {name}. {description}
            
Use the available tools to complete tasks. Think step by step.
If you're unsure, explain your reasoning and ask for clarification.
"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        self.agent = create_openai_functions_agent(self.llm, self.tools, prompt)
        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            memory=self.memory,
            verbose=True,
            max_iterations=5
        )
    
    async def _execute_action(self, decision: AgentDecision) -> Dict[str, Any]:
        """Execute action using LangChain tools"""
        result = await self.agent_executor.ainvoke({
            "input": decision.action,
            "context": decision.context
        })
        return result
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute using the full agentic cycle"""
        return await self.execute_with_recovery(input_data)
