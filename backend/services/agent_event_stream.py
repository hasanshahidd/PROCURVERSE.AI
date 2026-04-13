"""
Agent Event Streaming Service
Provides real-time event emission for agent execution visualization
"""

import asyncio
import json
import logging
from typing import Dict, Any, AsyncGenerator
from datetime import datetime, date
from enum import Enum
from decimal import Decimal
import time
import uuid

logger = logging.getLogger(__name__)


class AgentEventType(str, Enum):
    """Types of events emitted during agent execution"""
    RECEIVED = "received"           # Request received by orchestrator
    CLASSIFYING = "classifying"     # Orchestrator analyzing request
    ROUTING = "routing"             # Routing to specialized agent
    AGENT_SELECTED = "agent_selected"  # Agent selected for execution
    OBSERVING = "observing"         # Agent gathering context
    OBSERVATION_COMPLETE = "observation_complete"  # Observations ready
    DECIDING = "deciding"           # Agent making decision with LLM
    DECISION_MADE = "decision_made" # Decision complete
    ACTING = "acting"               # Agent executing action
    ACTION_COMPLETE = "action_complete"  # Action executed
    LEARNING = "learning"           # Agent learning from result
    LEARNING_COMPLETE = "learning_complete"  # Learning complete
    COMPLETE = "complete"           # Full execution done
    ERROR = "error"                 # Error occurred
    SESSION_CREATED = "session_created"  # Layer 1: execution session created for P2P_FULL intent


class AgentEventStream:
    """
    Manages event streaming for agent execution visualization.
    
    Usage:
        stream = AgentEventStream()
        await stream.emit(AgentEventType.OBSERVING, {"data": "..."})
        
        # In SSE endpoint:
        async for event in stream.generate_sse():
            yield event
    """
    
    def __init__(self, request_id: str | None = None):
        self.events: asyncio.Queue = asyncio.Queue()
        self.is_complete = False
        self.request_id = request_id or str(uuid.uuid4())

    @staticmethod
    def _json_default(value: Any) -> Any:
        """Convert non-JSON-native values to a safe representation."""
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, Enum):
            return value.value
        return str(value)
        
    async def emit(self, event_type: AgentEventType, data: Dict[str, Any]) -> None:
        """
        Emit an event to all subscribers.
        
        Args:
            event_type: Type of event
            data: Event payload
        """
        event = {
            "type": event_type.value,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        
        logger.info(f"[EVENT STREAM] Emitting: {event_type.value}")

        await self.events.put(event)
        # Yield control briefly so the SSE generator can flush events to the client
        await asyncio.sleep(0)
        await emit_executive_from_agent_event(self.request_id, event)

        # Also inject business summary into SSE stream for ChatPage
        try:
            result_data = _extract_result_data(data)
            agent_name = str(data.get("agent_name", data.get("agent", "")))
            phase = event_type.value
            summary = _build_dynamic_business_summary(agent_name, phase, result_data)
            if summary and summary.strip() and "No detailed summary" not in summary:
                business_event = {
                    "type": "business_summary",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "summary": summary,
                        "agent_name": agent_name,
                        "phase": phase,
                        "status_badge": _business_status_badge(
                            data.get("status", "active"),
                            data.get("confidence"),
                            summary
                        ),
                        "risk_level": _infer_risk_level(
                            data.get("risk_level"),
                            data.get("status"),
                            "Processing",
                        ),
                    }
                }
                await self.events.put(business_event)
        except Exception:
            pass  # Non-blocking — don't break SSE stream for business summary
        
    async def emit_error(self, error_message: str, error_details: Dict[str, Any] = None) -> None:
        """Emit an error event"""
        await self.emit(AgentEventType.ERROR, {
            "error": error_message,
            "details": error_details or {}
        })
        self.is_complete = True
        finalize_executive_session(self.request_id, "error")
        
    async def emit_complete(self, result: Dict[str, Any]) -> None:
        """Emit completion event"""
        await self.emit(AgentEventType.COMPLETE, {
            "result": result,
            "status": "success"
        })
        self.is_complete = True
        finalize_executive_session(self.request_id, "success")
        
    async def generate_sse(self) -> AsyncGenerator[str, None]:
        """
        Generate Server-Sent Events format.

        Yields:
            SSE formatted strings: "data: {...}\n\n"
        """
        logger.info(f"[EVENT STREAM] Starting SSE generation (is_complete={self.is_complete}, queue_size={self.events.qsize()})")

        while not self.is_complete or not self.events.empty():
            try:
                # Wait for next event with timeout
                event = await asyncio.wait_for(self.events.get(), timeout=30.0)
                
                # Format as SSE
                event_json = json.dumps(event, default=self._json_default)
                sse_message = f"data: {event_json}\n\n"
                
                logger.debug(f"[EVENT STREAM] -> Sending: {event['type']}")
                
                yield sse_message
                
                # Keep this near-zero to avoid artificial timing inflation while still
                # yielding control to the event loop for streaming flush.
                await asyncio.sleep(0.01)
                
                # Check if this was completion event
                if event["type"] in [AgentEventType.COMPLETE.value, AgentEventType.ERROR.value]:
                    logger.info(f"[EVENT STREAM] Stream complete: {event['type']}")
                    break
                    
            except asyncio.TimeoutError:
                # Send keepalive
                yield ": keepalive\n\n"
                logger.debug("[EVENT STREAM] Keepalive sent")
                
            except Exception as e:
                logger.error(f"[EVENT STREAM] Error: {e}")
                error_event = {
                    "type": AgentEventType.ERROR.value,
                    "timestamp": datetime.now().isoformat(),
                    "data": {"error": str(e)}
                }
                yield f"data: {json.dumps(error_event, default=self._json_default)}\n\n"
                break
        
        logger.info("[EVENT STREAM] SSE generation complete")


# Global registry for active streams (keyed by request ID)
_active_streams: Dict[str, AgentEventStream] = {}
_executive_subscribers: set[asyncio.Queue] = set()
_executive_subscribers_lock = asyncio.Lock()
_executive_sessions: Dict[str, Dict[str, Any]] = {}
_phase_started_at_ms: Dict[str, int] = {}
_last_executive_session: Dict[str, Any] = {
    "session_id": None,
    "started_at": None,
    "ended_at": None,
    "status": "idle",
    "events": [],
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _phase_key(session_id: str, agent_name: str, phase: str) -> str:
    return f"{session_id}:{agent_name}:{phase}"


def ensure_executive_session(session_id: str | None = None, metadata: Dict[str, Any] | None = None) -> str:
    sid = session_id or f"exec-{uuid.uuid4().hex[:10]}"
    if sid not in _executive_sessions:
        _executive_sessions[sid] = {
            "session_id": sid,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
            "status": "running",
            "metadata": metadata or {},
            "events": [],
        }
    elif metadata:
        _executive_sessions[sid]["metadata"] = {
            **(_executive_sessions[sid].get("metadata") or {}),
            **metadata,
        }
    return sid


def finalize_executive_session(session_id: str, status: str) -> None:
    session = _executive_sessions.get(session_id)
    if not session:
        return
    session["ended_at"] = datetime.now().isoformat()
    session["status"] = status
    _last_executive_session.update({
        "session_id": session.get("session_id"),
        "started_at": session.get("started_at"),
        "ended_at": session.get("ended_at"),
        "status": session.get("status"),
        "metadata": session.get("metadata", {}),
        "events": list(session.get("events", [])),
    })


def get_last_executive_session() -> Dict[str, Any]:
    if _last_executive_session.get("events"):
        return dict(_last_executive_session)

    if not _executive_sessions:
        return dict(_last_executive_session)

    latest = max(
        _executive_sessions.values(),
        key=lambda item: item.get("started_at") or "",
    )
    return {
        "session_id": latest.get("session_id"),
        "started_at": latest.get("started_at"),
        "ended_at": latest.get("ended_at"),
        "status": latest.get("status"),
        "metadata": latest.get("metadata", {}),
        "events": list(latest.get("events", [])),
    }


async def subscribe_executive_events() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=250)
    async with _executive_subscribers_lock:
        _executive_subscribers.add(queue)
    return queue


async def unsubscribe_executive_events(queue: asyncio.Queue) -> None:
    async with _executive_subscribers_lock:
        _executive_subscribers.discard(queue)


async def _broadcast_executive_event(event: Dict[str, Any]) -> None:
    async with _executive_subscribers_lock:
        subscribers = list(_executive_subscribers)

    for queue in subscribers:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(event)
            except Exception:
                continue


def _business_status_badge(status: str, confidence_score: float | None, summary: str) -> str:
    normalized = (status or "").lower()
    lower_summary = (summary or "").lower()
    if normalized in {"active", "running", "in_progress", "pending"}:
        return "Processing"
    if "escalat" in lower_summary:
        return "Escalated"
    if any(token in lower_summary for token in ["alert", "warning", "requires additional review", "manual review required"]):
        return "Attention Required"
    if normalized in {"failed", "error"}:
        return "Attention Required"
    if normalized in {"completed", "success", "passed", "approved"}:
        return "Approved"
    if confidence_score is not None and confidence_score < 0.6:
        return "Escalated"
    return "Processing"


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_percent(value: Any) -> str | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    pct = numeric * 100 if numeric <= 1 else numeric
    return f"{pct:.1f}%" if abs(pct - round(pct)) > 1e-9 else f"{int(round(pct))}%"


def _to_currency(value: Any) -> str | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return f"${numeric:,.2f}"


def _to_readable_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.strftime("%B %d, %Y")
    if isinstance(value, date):
        return value.strftime("%B %d, %Y")
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%B %d, %Y")
    except Exception:
        return text


def _to_seconds(value: Any) -> str | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return f"{numeric:.1f}"


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _extract_result_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw_data, dict):
        return {}

    result_val = raw_data.get("result")
    result_is_dict = isinstance(result_val, dict)
    primary_result_val = result_val.get("primary_result") if result_is_dict else None

    candidates = [
        raw_data,
        result_val,
        result_val.get("result") if result_is_dict else None,
        primary_result_val,
        primary_result_val.get("result") if isinstance(primary_result_val, dict) else None,
    ]

    # Also pull from decision context (orchestrator embeds routing info here)
    decision_val = raw_data.get("decision")
    if isinstance(decision_val, dict):
        candidates.append(decision_val)

    merged: Dict[str, Any] = {}
    for item in candidates:
        if isinstance(item, dict):
            merged.update(item)

    # Ensure key top-level fields aren't lost during nested merging
    for key in ("agent", "agent_name", "routed_agent", "routed_agent_name",
                "detected_intent", "intent", "query_type", "confidence",
                "status", "message"):
        if key not in merged and raw_data.get(key) is not None:
            merged[key] = raw_data[key]

    return merged


def _build_dynamic_business_summary(agent_name: str, phase: str, result_data: Dict[str, Any]) -> str:
    if not result_data:
        # Return empty so the filter at line 91 skips this event
        return ""

    agent = (agent_name or "").lower()
    phase_upper = (phase or "").upper()

    if "orchestrator" in agent:
        detected_intent = _coalesce(result_data.get("detected_intent"), result_data.get("intent"), result_data.get("query_type"))
        routed_agent = _coalesce(
            result_data.get("routed_agent_name"),
            result_data.get("routed_agent"),
            result_data.get("primary_agent"),
            result_data.get("agent"),
        )
        if detected_intent and routed_agent:
            return f"A {detected_intent} request has been received and assigned to {routed_agent} for processing."
        # Provide a more specific fallback when we at least know the query type
        if detected_intent:
            return f"A {detected_intent.replace('_', ' ').title()} request has been received and is being processed by the AI system."
        return "Your procurement request has been received and is being processed by the AI system."

    if "compliancecheck" in agent or "compliance_check" in agent:
        status = str(_coalesce(result_data.get("status"), "")).lower()
        violations = result_data.get("violations") or []
        warnings = result_data.get("warnings") or []
        score = result_data.get("score")
        policy = _coalesce(result_data.get("policy_name"), result_data.get("policy"))

        if status in {"passed", "approved", "success"}:
            msg = "Compliance check passed."
            if policy:
                msg = f"Compliance check passed against {policy}."
            if isinstance(score, (int, float)):
                msg += f" Score: {score}%."
            return msg
        if status in {"failed", "rejected", "violation"}:
            msg = "Compliance violation detected."
            if isinstance(violations, list) and violations:
                msg += f" {len(violations)} violation(s) found."
            return msg + " Manual review required."
        if isinstance(warnings, list) and warnings:
            return f"Compliance check completed with {len(warnings)} warning(s). Review recommended."
        return result_data.get("message", "Compliance check in progress.")

    if "priceanalysis" in agent or "price_analysis" in agent:
        avg_price = _to_currency(result_data.get("average_price"))
        recommended = _to_currency(result_data.get("recommended_price"))
        savings = _to_currency(result_data.get("potential_savings"))
        if avg_price and recommended:
            msg = f"Price analysis complete. Market average: {avg_price}, recommended: {recommended}."
            if savings:
                msg += f" Potential savings: {savings}."
            return msg
        return result_data.get("message", "Price analysis completed.")

    if "budgetverification" in agent:
        department = _coalesce(result_data.get("department_name"), result_data.get("department"))
        requested = _to_currency(_coalesce(result_data.get("requested_amount"), result_data.get("budget"), result_data.get("amount")))
        available = _to_currency(_coalesce(result_data.get("available_budget"), result_data.get("available")))
        remaining = _to_currency(result_data.get("remaining_after"))
        approved = bool(result_data.get("approved") or result_data.get("budget_verified") or str(result_data.get("status", "")).lower() in {"approved", "success", "passed"})

        if approved:
            parts = ["Budget confirmed"]
            if department:
                parts[-1] += f" for {department}"
            parts[-1] += "."
            if requested and available:
                parts.append(f"The requested {requested} is covered by the available {available} allocation.")
            if remaining:
                parts.append(f"{remaining} will remain after this approval.")
            return " ".join(parts)

        parts = ["Budget alert"]
        if department:
            parts[-1] += f" for {department}"
        parts[-1] += "."
        if requested and available:
            parts.append(f"The requested {requested} exceeds the available {available}.")
        parts.append("Escalation is required before this can proceed.")
        return " ".join(parts)

    if "approvalrouting" in agent:
        approver_role = _coalesce(result_data.get("approver_role"), result_data.get("required_level"), result_data.get("role"))
        approver_name = _coalesce(result_data.get("approver_name"), result_data.get("next_approver"))
        threshold = _to_currency(result_data.get("amount_threshold"))
        reason = _coalesce(result_data.get("routing_reason"), result_data.get("reason"))

        first = "This request has been routed"
        if approver_name and approver_role:
            first += f" to {approver_name} ({approver_role}) for approval."
        elif approver_name:
            first += f" to {approver_name} for approval."
        elif approver_role:
            first += f" to {approver_role} for approval."
        else:
            first += " for approval."

        second_parts = []
        if reason:
            second_parts.append(f"Routing is based on {reason}")
        if threshold:
            second_parts.append(f"the {threshold} spend threshold")
        if second_parts:
            return f"{first} {' and '.join(second_parts)}."
        return first

    if "vendorselection" in agent:
        winner = _coalesce(result_data.get("winning_vendor"), result_data.get("selected_vendor"), result_data.get("vendor_name"))
        total = _coalesce(result_data.get("total_vendors_evaluated"), result_data.get("evaluated_vendors"))
        score = _to_float(result_data.get("winning_score"))
        reason = _coalesce(result_data.get("selection_reason"), result_data.get("reason"))
        runner_up = _coalesce(result_data.get("runner_up"), result_data.get("alternate_vendor"))

        pieces = []
        if winner and total and score is not None:
            pieces.append(f"{winner} has been selected from {total} evaluated suppliers with a score of {score:.1f} out of 100.")
        elif winner and total:
            pieces.append(f"{winner} has been selected from {total} evaluated suppliers.")
        elif winner:
            pieces.append(f"{winner} has been selected as the preferred supplier.")
        if reason:
            pieces.append(f"Selection was driven by {reason}.")
        if runner_up:
            pieces.append(f"Runner-up was {runner_up}.")
        return " ".join(pieces) if pieces else ""

    if "riskassessment" in agent:
        risk_level = str(_coalesce(result_data.get("risk_level"), "medium")).lower()
        vendor = _coalesce(result_data.get("vendor_name"), result_data.get("vendor"), "this supplier")
        compliance = _coalesce(result_data.get("compliance_status"), result_data.get("compliance"))
        reasons = result_data.get("risk_reasons")
        if isinstance(reasons, list):
            reasons_text = "; ".join(str(x) for x in reasons if x not in (None, ""))
        else:
            reasons_text = str(reasons) if reasons not in (None, "") else ""

        if risk_level == "low":
            if compliance:
                return f"Risk assessment passed for {vendor}. Compliance status is {compliance} with no significant flags detected."
            return f"Risk assessment passed for {vendor}. No significant compliance or supplier risks detected."
        if risk_level == "high":
            if reasons_text:
                return f"High risk detected for {vendor}: {reasons_text}. Manual review is required before this request can proceed."
            return f"High risk detected for {vendor}. Manual review is required before this request can proceed."
        if reasons_text:
            return f"Moderate risk identified for {vendor}: {reasons_text}. Review is recommended before final approval."
        return f"Moderate risk identified for {vendor}. Review is recommended before final approval."

    if "supplierperformance" in agent:
        vendor = _coalesce(result_data.get("vendor_name"), result_data.get("supplier_name"), "Supplier")
        period = _coalesce(result_data.get("evaluation_period"), result_data.get("period"))
        on_time = _to_percent(result_data.get("on_time_delivery_rate"))
        quality = _coalesce(_to_percent(result_data.get("quality_score")), result_data.get("quality_score"))
        accuracy = _coalesce(_to_percent(result_data.get("invoice_accuracy")), result_data.get("invoice_accuracy"))

        pieces = [f"{vendor} performance verified"]
        if period:
            pieces[0] += f" over {period}."
        else:
            pieces[0] += "."
        if on_time:
            pieces.append(f"On-time delivery: {on_time}.")
        if quality:
            pieces.append(f"Quality score: {quality}.")
        if accuracy:
            pieces.append(f"Invoice accuracy: {accuracy}.")
        return " ".join(pieces)

    if "contractmonitoring" in agent:
        vendor = _coalesce(result_data.get("vendor_name"), result_data.get("supplier_name"), "this supplier")
        status_text = str(_coalesce(result_data.get("contract_status"), "")).lower()
        expiry = _to_readable_date(result_data.get("expiry_date"))
        days = _coalesce(result_data.get("days_until_expiry"), result_data.get("days_to_expiry"))
        renewal_required = bool(result_data.get("renewal_required"))

        if renewal_required or status_text in {"expired", "inactive"}:
            if expiry:
                return f"Contract with {vendor} requires immediate attention. Expiry date was {expiry} and renewal has not been completed."
            return f"Contract with {vendor} requires immediate attention and renewal has not been completed."
        if days is not None and _to_float(days) is not None and float(days) <= 60:
            if expiry:
                return f"Contract with {vendor} expires on {expiry}, which is {int(float(days))} days away. Renewal should be initiated promptly."
            return f"Contract with {vendor} expires in {int(float(days))} days. Renewal should be initiated promptly."
        if expiry:
            return f"Contract with {vendor} is active and valid until {expiry}. No renewal action is required at this time."
        return f"Contract with {vendor} is active. No renewal action is required at this time."

    # ── New P2P Agents ──────────────────────────────────────────────────────
    if "rfqagent" in agent or "rfq_management" in agent:
        rfq_num = _coalesce(result_data.get("rfq_number"))
        title = _coalesce(result_data.get("title"), result_data.get("message"))
        if rfq_num:
            return f"RFQ {rfq_num} has been created and sent to vendors for quotation. {title or ''}"
        return result_data.get("message", "RFQ process initiated.")

    if "poamendment" in agent or "po_amendment" in agent:
        amd_num = _coalesce(result_data.get("amendment_number"))
        po_num = _coalesce(result_data.get("po_number"))
        amd_type = _coalesce(result_data.get("amendment_type"), "modification")
        needs_approval = result_data.get("requires_approval", False)
        if amd_num:
            msg = f"Amendment {amd_num} created for {po_num or 'purchase order'} ({amd_type.replace('_', ' ')})."
            if needs_approval:
                msg += " Re-approval required due to significant impact."
            return msg
        return result_data.get("message", "PO amendment initiated.")

    if "returnagent" in agent or "return_processing" in agent:
        rtv_num = _coalesce(result_data.get("rtv_number"))
        qty = result_data.get("items_returned", result_data.get("total_return_qty"))
        credit = result_data.get("credit_expected")
        if rtv_num:
            msg = f"Return {rtv_num} initiated."
            if qty:
                msg += f" {qty} items being returned."
            if credit:
                msg += f" Expected credit: ${float(credit):,.2f}."
            return msg
        return result_data.get("message", "Return to vendor initiated.")

    if "qualityinspection" in agent or "quality_inspection" in agent:
        score = result_data.get("score", result_data.get("total_score"))
        pass_fail = result_data.get("pass_fail", "")
        grn = result_data.get("grn_number", "")
        hold = result_data.get("hold_goods", False)
        if score is not None:
            msg = f"Quality inspection for {grn or 'goods'}: Score {score}% — {str(pass_fail).upper()}."
            if hold:
                msg += " Goods placed ON HOLD pending review."
            return msg
        return result_data.get("message", "Quality inspection completed.")

    if "reconciliation" in agent:
        matched = result_data.get("matched", 0)
        exceptions = result_data.get("exceptions", 0)
        processed = result_data.get("processed", 0)
        if processed:
            return f"Reconciliation complete: {processed} bank entries processed, {matched} matched, {exceptions} exceptions."
        return result_data.get("message", "Payment reconciliation completed.")

    if "vendoronboarding" in agent or "vendor_onboarding" in agent:
        vendor = _coalesce(result_data.get("vendor_name"), result_data.get("supplier_name"))
        status = result_data.get("onboarding_status", result_data.get("status"))
        if vendor:
            return f"Vendor onboarding for {vendor}: {status or 'in progress'}."
        return result_data.get("message", "Vendor onboarding process initiated.")

    if "deliverytracking" in agent or "delivery_tracking" in agent:
        po = _coalesce(result_data.get("po_number"))
        status = result_data.get("delivery_status", result_data.get("status"))
        eta = result_data.get("estimated_delivery", result_data.get("eta"))
        if po:
            msg = f"Delivery tracking for {po}: {status or 'in transit'}."
            if eta:
                msg += f" ETA: {eta}."
            return msg
        return result_data.get("message", "Delivery tracking check completed.")

    if "discrepancyresolution" in agent or "exception_resolution" in agent:
        resolved = result_data.get("auto_resolved_count", result_data.get("resolved"))
        manual = result_data.get("manual_review_count", result_data.get("pending_review"))
        if resolved is not None or manual is not None:
            return f"Exception resolution: {resolved or 0} auto-resolved, {manual or 0} sent for manual review."
        return result_data.get("message", "Exception resolution completed.")

    if "paymentreadiness" in agent or "payment_readiness" in agent:
        gates_passed = result_data.get("gates_passed", result_data.get("conditions_passed"))
        ready = result_data.get("payment_ready", result_data.get("authorized"))
        if ready:
            return f"Payment readiness check: ALL gates passed. Payment authorized."
        if gates_passed is not None:
            return f"Payment readiness: {gates_passed}/7 gates passed. Review required."
        return result_data.get("message", "Payment readiness check completed.")

    # ── Generic / fallback for any agent with a message field ──────────────
    if result_data.get("message"):
        return str(result_data["message"])[:300]

    # ── Phase-aware generic summaries (always generate useful text) ────────
    agent_label = agent_name or "AI Agent"
    if agent_label.endswith("Agent"):
        # Convert "BudgetVerificationAgent" → "Budget Verification Agent"
        import re
        agent_label = re.sub(r'([a-z])([A-Z])', r'\1 \2', agent_label)

    if phase_upper == "RECEIVED":
        request_text = _coalesce(result_data.get("request"), "")
        if request_text:
            return f"Processing procurement request: {str(request_text)[:120]}"
        return "A new procurement request has been received and is being validated."

    if phase_upper == "CLASSIFYING":
        intent = _coalesce(result_data.get("intent"), result_data.get("query_type"), result_data.get("detected_intent"))
        if intent:
            return f"Request classified as: {str(intent).replace('_', ' ').title()}. Selecting optimal agent."
        return "Analyzing request intent and determining the appropriate agent."

    if phase_upper == "ROUTING":
        routed = _coalesce(result_data.get("agent"), result_data.get("routed_agent_name"), result_data.get("routed_agent"))
        confidence = result_data.get("confidence")
        reason = result_data.get("reasoning") or result_data.get("reason") or ""
        if routed:
            conf_str = f" ({confidence}% confidence)" if confidence else ""
            return f"Request routed to {routed}{conf_str}. {reason}".strip()
        return "Routing request to the most appropriate specialized agent."

    if phase_upper == "AGENT_SELECTED":
        selected = _coalesce(result_data.get("agent"), result_data.get("agent_name"))
        if selected:
            return f"{selected} has been selected and is beginning execution."
        return "Specialized agent selected for this request."

    if phase_upper in ("OBSERVING", "OBSERVATION_COMPLETE"):
        sources = result_data.get("sources") or result_data.get("data_sources") or []
        if isinstance(sources, list) and sources:
            return f"{agent_label} is gathering data from {', '.join(str(s) for s in sources[:3])}."
        return f"{agent_label} is gathering context from enterprise databases and ERP systems."

    if phase_upper in ("DECIDING", "DECISION_MADE"):
        action = result_data.get("action")
        model = result_data.get("model")
        if action:
            action_str = action if isinstance(action, str) else (action.get("primary", "") if isinstance(action, dict) else str(action))
            action_str = action_str.replace("_", " ").title() if action_str else "analysis"
            return f"{agent_label} decision: {action_str}.{f' Model: {model}.' if model else ''}"
        if model:
            return f"{agent_label} is analyzing the data using {model}."
        return f"{agent_label} is forming a decision based on the collected data."

    if phase_upper in ("ACTING", "ACTION_COMPLETE"):
        tools = result_data.get("tools") or []
        if isinstance(tools, list) and tools:
            return f"{agent_label} executing: {', '.join(str(t) for t in tools[:3])}."
        timing = result_data.get("execution_time_ms")
        if timing:
            return f"{agent_label} completed tool execution in {timing}ms."
        return f"{agent_label} is executing the required actions."

    if phase_upper in ("LEARNING", "LEARNING_COMPLETE"):
        recorded = result_data.get("recorded")
        if recorded:
            return f"{agent_label} has recorded the decision and outcome to the audit trail."
        return f"{agent_label} is recording the decision for compliance and audit purposes."

    if phase_upper == "COMPLETE":
        escalated_to = _coalesce(result_data.get("escalated_to"), result_data.get("reviewer"))
        escalation_reason = _coalesce(result_data.get("escalation_reason"), result_data.get("failure_reason"), result_data.get("reason"))
        if escalated_to or escalation_reason:
            subject = f"Request escalated to {escalated_to}" if escalated_to else "Request escalated"
            reason = f" Reason: {escalation_reason}." if escalation_reason else ""
            return f"{subject} for manual review.{reason} No further automated steps will run until a decision is made."

        total_agents = _coalesce(result_data.get("total_agents_run"), result_data.get("agents_invoked") and len(result_data.get("agents_invoked")))
        duration = _coalesce(_to_seconds(result_data.get("total_duration_seconds")), _to_seconds(_to_float(result_data.get("total_execution_time_ms")) / 1000 if _to_float(result_data.get("total_execution_time_ms")) is not None else None))
        decision = _coalesce(result_data.get("final_decision"), result_data.get("status"), "approved")

        sentence = "Procurement request completed successfully."
        if total_agents and duration:
            sentence += f" {total_agents} checks passed in {duration} seconds."
        elif total_agents:
            sentence += f" {total_agents} checks passed."
        if decision:
            sentence += f" Final decision: {decision}."
        return sentence

    # Return empty so the filter skips this event rather than showing useless text
    return ""


def _financial_note(data: Dict[str, Any]) -> str | None:
    if not isinstance(data, dict):
        return None
    if data.get("available_budget") is not None:
        return f"Budget remaining: ${float(data['available_budget']):,.2f}"
    if data.get("budget_remaining") is not None:
        return f"Budget remaining: ${float(data['budget_remaining']):,.2f}"
    if data.get("potential_savings") is not None:
        return f"Potential savings identified: ${float(data['potential_savings']):,.2f}"
    return None


def _recommended_action(status_badge: str, result_data: Dict[str, Any]) -> str:
    explicit = _coalesce(result_data.get("next_action"), result_data.get("recommended_action"))
    if explicit:
        return str(explicit)
    if status_badge == "Approved":
        return "No action required, proceeding automatically"
    if status_badge == "Attention Required":
        return "Review the flagged item and confirm before proceeding"
    if status_badge == "Escalated":
        escalated_to = _coalesce(result_data.get("escalated_to"), "assigned approver")
        return f"Await manual review decision from {escalated_to} before next steps"
    return "Continue monitoring this request while validations complete"


def _risk_level(result_data: Dict[str, Any], status_badge: str, status: str) -> str:
    raw_risk = result_data.get("risk_level")
    if isinstance(raw_risk, str) and raw_risk.strip():
        normalized = raw_risk.strip().capitalize()
        if normalized in {"Low", "Medium", "High"}:
            return normalized
    if (status or "").lower() in {"failed", "error"}:
        return "High"
    if status_badge == "Approved":
        return "Low"
    if status_badge in {"Attention Required", "Escalated"}:
        return "Medium"
    return "Low"


def _derive_business_payload(technical_payload: Dict[str, Any], raw_data: Dict[str, Any]) -> Dict[str, Any]:
    result_data = _extract_result_data(raw_data)
    agent_name = str(technical_payload.get("agent_name", ""))
    phase = str(technical_payload.get("phase", ""))
    summary = _build_dynamic_business_summary(agent_name, phase, result_data)
    # If no meaningful summary, generate a phase-based description
    if not summary or not summary.strip():
        phase_labels = {
            "received": f"Request received by {agent_name or 'system'}.",
            "classifying": f"Analyzing request intent and routing.",
            "routing": f"Routing to specialized agent.",
            "agent_selected": f"{agent_name} selected for processing.",
            "observing": f"{agent_name} gathering data from databases and ERP.",
            "observation_complete": f"{agent_name} finished data collection.",
            "deciding": f"{agent_name} analyzing data with AI model.",
            "decision_made": f"{agent_name} made a decision.",
            "acting": f"{agent_name} executing actions.",
            "action_complete": f"{agent_name} completed execution.",
            "learning": f"{agent_name} recording audit trail.",
            "learning_complete": f"{agent_name} saved execution record.",
            "complete": f"Processing complete.",
        }
        summary = phase_labels.get(phase, f"{agent_name} processing ({phase}).")
    confidence_score = technical_payload.get("confidence_score")
    status = technical_payload.get("status", "active")
    badge = _business_status_badge(status, confidence_score, summary)
    payload = {
        "summary": summary,
        "status_badge": badge,
        "financial_impact_note": _coalesce(
            result_data.get("financial_note"),
            result_data.get("financial_impact_note"),
            _financial_note(result_data),
            _financial_note(raw_data),
            (
                f"{_to_currency(result_data.get('remaining_after'))} remaining after approval"
                if _to_currency(result_data.get("remaining_after")) and badge == "Approved" else None
            ),
            (
                f"Shortfall of {_to_currency(_coalesce(result_data.get('shortfall_amount'), (_to_float(result_data.get('requested_amount')) or 0) - (_to_float(result_data.get('available_budget')) or 0)))}"
                if badge in {"Escalated", "Attention Required"} and (
                    _to_float(result_data.get("shortfall_amount")) is not None
                    or (_to_float(result_data.get("requested_amount")) is not None and _to_float(result_data.get("available_budget")) is not None)
                )
                else None
            ),
        ),
        "risk_level": _risk_level(result_data, badge, str(status)),
        "recommended_next_action": _recommended_action(badge, result_data),
    }
    return payload


_sample_payload_logged_sessions: set[str] = set()


async def emit_executive_pair(
    session_id: str,
    technical_payload: Dict[str, Any],
    raw_data: Dict[str, Any] | None = None,
) -> None:
    sid = ensure_executive_session(session_id)
    timestamp = datetime.now().isoformat()
    technical_event = {
        "event_type": "technical-panel",
        "session_id": sid,
        "timestamp": timestamp,
        "payload": technical_payload,
    }
    business_event = {
        "event_type": "business-panel",
        "session_id": sid,
        "timestamp": timestamp,
        "payload": _derive_business_payload(technical_payload, raw_data or {}),
    }

    if sid not in _sample_payload_logged_sessions:
        logger.info(f"[EXECUTIVE SAMPLE PAYLOAD] {json.dumps(business_event['payload'], default=str)}")
        _sample_payload_logged_sessions.add(sid)

    session = _executive_sessions.get(sid)
    if session is not None:
        session["events"].append(technical_event)
        session["events"].append(business_event)

    await _broadcast_executive_event(technical_event)
    await _broadcast_executive_event(business_event)


async def emit_executive_step(
    session_id: str,
    agent_name: str,
    phase: str,
    *,
    confidence_score: float | None = None,
    tool_calls: list[str] | None = None,
    duration_ms: int | None = None,
    status: str = "active",
    raw_data: Dict[str, Any] | None = None,
) -> None:
    payload = {
        "agent_name": agent_name,
        "phase": phase,
        "confidence_score": confidence_score,
        "tool_calls_made": tool_calls or [],
        "duration_ms": duration_ms,
        "status": status,
    }
    await emit_executive_pair(session_id, payload, raw_data=raw_data)


def _normalize_phase_and_status(agent_event_type: str) -> tuple[str | None, str | None]:
    mapping = {
        AgentEventType.OBSERVING.value: ("OBSERVE", "active"),
        AgentEventType.OBSERVATION_COMPLETE.value: ("OBSERVE", "completed"),
        AgentEventType.DECIDING.value: ("DECIDE", "active"),
        AgentEventType.DECISION_MADE.value: ("DECIDE", "completed"),
        AgentEventType.ACTING.value: ("ACT", "active"),
        AgentEventType.ACTION_COMPLETE.value: ("ACT", "completed"),
        AgentEventType.LEARNING.value: ("LEARN", "active"),
        AgentEventType.LEARNING_COMPLETE.value: ("LEARN", "completed"),
        AgentEventType.ERROR.value: ("ACT", "failed"),
        AgentEventType.COMPLETE.value: ("COMPLETE", "completed"),
    }
    return mapping.get(agent_event_type, (None, None))


async def emit_executive_from_agent_event(session_id: str, event: Dict[str, Any]) -> None:
    raw_data = event.get("data", {}) if isinstance(event, dict) else {}
    data = raw_data if isinstance(raw_data, dict) else {"message": str(raw_data)}
    event_type = event.get("type", "") if isinstance(event, dict) else ""
    phase, status = _normalize_phase_and_status(event_type)
    if not phase or not status:
        return

    sid = ensure_executive_session(session_id)
    agent_name = data.get("agent") or data.get("agent_name") or data.get("agent_type") or "Orchestrator"

    phase_key = _phase_key(sid, agent_name, phase)
    duration_ms = data.get("execution_time_ms")
    if duration_ms is None:
        if status == "active":
            _phase_started_at_ms[phase_key] = _now_ms()
        elif status in {"completed", "failed"}:
            started = _phase_started_at_ms.get(phase_key)
            if started is not None:
                duration_ms = max(_now_ms() - started, 0)

    confidence_score = data.get("confidence")
    tool_calls = data.get("tools") or data.get("available_tools") or data.get("sources") or []
    if not isinstance(tool_calls, list):
        tool_calls = [str(tool_calls)]

    technical_payload = {
        "agent_name": agent_name,
        "phase": phase,
        "confidence_score": confidence_score,
        "tool_calls_made": tool_calls,
        "duration_ms": duration_ms,
        "status": status,
    }
    await emit_executive_pair(sid, technical_payload, raw_data=data)

    if event_type == AgentEventType.COMPLETE.value:
        finalize_executive_session(sid, "success")
    elif event_type == AgentEventType.ERROR.value:
        finalize_executive_session(sid, "error")


def create_stream(request_id: str) -> AgentEventStream:
    """
    Create a new event stream for a request.
    
    Args:
        request_id: Unique identifier for this request
        
    Returns:
        AgentEventStream instance
    """
    stream = AgentEventStream(request_id=request_id)
    _active_streams[request_id] = stream
    ensure_executive_session(request_id)
    logger.info(f"[EVENT STREAM] 🆕 Created stream for request: {request_id}")
    return stream


def get_stream(request_id: str) -> AgentEventStream:
    """
    Get existing stream for a request.
    
    Args:
        request_id: Request identifier
        
    Returns:
        AgentEventStream instance or None
    """
    return _active_streams.get(request_id)


def cleanup_stream(request_id: str) -> None:
    """
    Clean up stream after completion.
    
    Args:
        request_id: Request identifier
    """
    if request_id in _active_streams:
        del _active_streams[request_id]
        logger.info(f"[EVENT STREAM] ️  Cleaned up stream: {request_id}")


def get_active_stream_count() -> int:
    """Get count of active streams"""
    return len(_active_streams)
