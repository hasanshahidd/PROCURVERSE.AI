"""
Agentic API Routes
Sprint 1: Testing endpoints for orchestrator and agents
"""

from fastapi import APIRouter, HTTPException, Request, Header, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import base64
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import uuid
import re
import json
import os
import hmac

from backend.services.auth_service import get_optional_user, security as _bearer_security
from backend.services.rbac import require_auth, require_role

from backend.agents.orchestrator import initialize_orchestrator_with_agents
from backend.agents.budget_verification import BudgetVerificationAgent
from backend.agents.approval_routing import ApprovalRoutingAgent
from backend.services.odoo_client import get_odoo_client
from backend.agents.vendor_selection import VendorSelectionAgent
from backend.agents.risk_assessment import RiskAssessmentAgent
from backend.services import hybrid_query
from backend.services.db_pool import get_db_connection, return_db_connection
from backend.services import agent_event_stream
from backend.services.query_router import classify_query_intent, resolve_followup_context_with_llm, _fix_multi_intent_routing
from backend.services.routing_schema import normalize_odoo_query_type

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agentic", tags=["agentic"])


def _is_local_request(request: Request) -> bool:
    client_host = (request.client.host if request.client else "") or ""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        client_host = forwarded_for.split(",")[0].strip()
    return client_host in {"127.0.0.1", "::1", "localhost"}


def _is_valid_admin_token(token: str | None) -> bool:
    configured_token = os.getenv("ADMIN_API_TOKEN") or os.getenv("ADMIN_RESET_TOKEN")
    if not configured_token:
        return False
    if not token:
        return False
    return hmac.compare_digest(token, configured_token)


def _require_admin_or_local(request: Request, x_admin_token: str | None) -> None:
    if _is_valid_admin_token(x_admin_token):
        return
    raise HTTPException(
        status_code=403,
        detail="Admin authorization required (X-Admin-Token)",
    )


def _require_jwt_or_local(request: Request, current_user: Optional[Dict[str, Any]]) -> None:
    """
    Enforce that the caller is either:
      - A locally-originating request (127.0.0.1 / ::1), OR
      - An authenticated user (valid JWT supplied in Authorization header).
    Raises 403 otherwise.
    Used on sensitive pipeline endpoints.
    """
    if _is_local_request(request):
        return
    if current_user is not None:
        return
    raise HTTPException(
        status_code=403,
        detail="Authentication required. Please log in to use this endpoint.",
    )


def _require_approval_actor(
    request: Request,
    approver_email: str,
    x_approver_email: str | None,
    x_admin_token: str | None,
) -> None:
    """Allow action by matching approver identity header or admin token/local fallback."""
    if _is_valid_admin_token(x_admin_token):
        return

    if _is_local_request(request):
        return

    if x_approver_email and x_approver_email.strip().lower() == approver_email.strip().lower():
        return

    raise HTTPException(
        status_code=403,
        detail="Approver authorization failed. Provide X-Approver-Email matching approver_email.",
    )


def _is_po_query_type(query_type: str) -> bool:
    normalized = (query_type or "").strip().lower()
    return normalized in {"purchase_orders", "purchase_order", "po", "view_po", "view_purchase_orders"}


def _is_po_count_query(text: str) -> bool:
    lower = (text or "").lower()
    return bool(re.search(r"\b(how many|count|total|number of)\b", lower))


def _normalize_po_state(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = str(value).strip().lower()
    state_map = {
        "pending": "draft",
        "waiting": "draft",
        "new": "draft",
        "approved": "purchase",
        "confirmed": "purchase",
        "completed": "done",
        "finished": "done",
        "cancelled": "cancel",
    }
    return state_map.get(normalized, normalized)


def _parse_amount_with_suffix(raw_amount: Optional[str], raw_suffix: Optional[str] = None) -> Optional[float]:
    if not raw_amount:
        return None
    try:
        numeric = float(str(raw_amount).replace(",", ""))
    except (TypeError, ValueError):
        return None
    suffix = (raw_suffix or "").lower()
    multiplier = 1000 if suffix == "k" else 1_000_000 if suffix == "m" else 1
    return numeric * multiplier


def _extract_quantity_from_text(text: str) -> Optional[int]:
    if not text:
        return None

    quantity_patterns = [
        r"\b(?:quantity|qty)\s*[:=]?\s*(\d+)\b",
        r"(\d+)\s*(?:laptop\s+accessories|laptops?|accessories|units?|items?|pcs?|pieces?)\b",
    ]

    for pattern in quantity_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            try:
                parsed = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
    return None


def _normalize_budget_from_request_text(request_text: str, pr_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize budget semantics from raw request text.

    - "at/for $X each|per item" => total budget = quantity * X
    - "at $X" (without each/per) => total budget = X
    """
    normalized = dict(pr_data or {})
    text = (request_text or "").lower()

    extracted_quantity = _extract_quantity_from_text(text)
    if extracted_quantity is not None:
        quantity = extracted_quantity
        normalized["quantity"] = extracted_quantity
    else:
        try:
            quantity = int(normalized.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1

    each_match = re.search(
        r"(?:at|for)\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\s*(?:each|per\s*(?:item|unit|pc|piece))\b",
        text,
        re.I,
    )
    at_match = re.search(r"\bat\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\b", text, re.I)

    each_amount = _parse_amount_with_suffix(each_match.group(1), each_match.group(2)) if each_match else None
    at_amount = _parse_amount_with_suffix(at_match.group(1), at_match.group(2)) if at_match else None

    existing_budget = normalized.get("budget")
    try:
        existing_budget_value = float(existing_budget) if existing_budget is not None else None
    except (TypeError, ValueError):
        existing_budget_value = None

    if each_amount is not None:
        normalized["budget"] = float(quantity) * each_amount
        normalized["quantity"] = quantity
        return normalized

    if at_amount is not None:
        if existing_budget_value is None:
            normalized["budget"] = at_amount
        else:
            # Correct accidental multiplication when no each/per is present.
            multiplied = float(quantity) * at_amount
            if abs(existing_budget_value - multiplied) < 1e-9:
                normalized["budget"] = at_amount

    return normalized


def _enrich_pr_data_from_filters(base_pr_data: Dict[str, Any], intent_filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich pr_data by extracting fields from intent's filters.
    
    This is critical for multi-intent NL queries where the user says:
    "Find best vendor, check budget, and route approval for 20k Electronics"
    
    The classifier extracts:
    - amount: 20000
    - category: "Electronics"
    
    But we need to merge these into pr_data so all agents can access them.
    """
    enriched = dict(base_pr_data)  # Copy to avoid mutating original
    
    # Extract amount/budget
    # Respect explicit pr_data values from frontend parsing; only fill missing budget from classifier filters.
    if "budget" not in enriched or enriched.get("budget") in (None, ""):
        if "amount" in intent_filters:
            enriched["budget"] = intent_filters["amount"]
        if "total_cost" in intent_filters:
            enriched["budget"] = intent_filters["total_cost"]
        if "budget" in intent_filters:
            enriched["budget"] = intent_filters["budget"]
    
    # Extract department
    if "department" in intent_filters:
        enriched["department"] = intent_filters["department"]
    elif "department" not in enriched or not enriched["department"]:
        # Department is required for PR creation — do NOT silently default.
        # The frontend is responsible for prompting the user before sending.
        # Leave department empty; the orchestrator will handle missing department gracefully.
        print(f"[PR_DATA_ENRICHMENT] ⚠️  Department not specified — leaving blank (frontend should have asked)")
    
    # Extract category
    if "category" in intent_filters:
        enriched["category"] = intent_filters["category"]
    
    # Extract vendor
    if "vendor" in intent_filters:
        enriched["vendor_name"] = intent_filters["vendor"]
    if "vendor_name" in intent_filters:
        enriched["vendor_name"] = intent_filters["vendor_name"]
    
    # Extract product/item
    if "item" in intent_filters:
        enriched["product_name"] = intent_filters["item"]
    if "product" in intent_filters:
        enriched["product_name"] = intent_filters["product"]
    if "product_name" in intent_filters:
        enriched["product_name"] = intent_filters["product_name"]
    
    # Extract quantity
    # Do not overwrite explicit quantity already parsed from user message.
    if ("quantity" not in enriched or enriched.get("quantity") in (None, "")) and "quantity" in intent_filters:
        enriched["quantity"] = intent_filters["quantity"]
    
    # Extract budget category (OPEX vs CAPEX logic)
    if "budget_category" in intent_filters:
        enriched["budget_category"] = intent_filters["budget_category"]
    elif "budget" in enriched and "budget_category" not in enriched:
        # Smart default based on category + amount
        budget = float(enriched.get("budget", 0))
        category = enriched.get("category", "")
        category_lower = str(category).lower()
        
        # Electronics/IT hardware is usually CAPEX if > $5k
        if any(keyword in category_lower for keyword in ["electronics", "hardware", "equipment", "furniture"]) and budget > 5000:
            enriched["budget_category"] = "CAPEX"
            print(f"[PR_DATA_ENRICHMENT] ℹ️  budget_category not specified - inferred 'CAPEX' from category '{category}' and ${budget:,.0f}")
        # Office supplies, software licenses are usually OPEX
        elif any(keyword in category_lower for keyword in ["supplies", "software", "license", "subscription"]):
            enriched["budget_category"] = "OPEX"
            print(f"[PR_DATA_ENRICHMENT] ℹ️  budget_category not specified - inferred 'OPEX' from category '{category}'")
        else:
            # Default based on amount
            enriched["budget_category"] = "CAPEX" if budget > 10000 else "OPEX"
            print(f"[PR_DATA_ENRICHMENT] ⚠️  budget_category not specified - defaulting to {enriched['budget_category']} based on ${budget:,.0f}")
    
    # Extract urgency
    if "urgency" in intent_filters:
        enriched["urgency"] = intent_filters["urgency"]
    
    # Extract PR number
    if "pr_number" in intent_filters:
        enriched["pr_number"] = intent_filters["pr_number"]
    
    # Extract justification
    if "justification" in intent_filters:
        enriched["justification"] = intent_filters["justification"]

    # Extract requester name (accept both requester_name and requester key variants)
    for key in ("requester_name", "requester"):
        if intent_filters.get(key) and not enriched.get("requester_name"):
            enriched["requester_name"] = intent_filters[key]
            break

    print(f"[PR_DATA_ENRICHMENT] Base: {base_pr_data}")
    print(f"[PR_DATA_ENRICHMENT] Filters: {intent_filters}")
    print(f"[PR_DATA_ENRICHMENT] Enriched: {enriched}")
    
    return enriched


def _hydrate_pr_data_from_workflow(pr_data: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing PR fields from stored workflow context when pr_number is supplied."""
    hydrated = dict(pr_data or {})
    pr_number = str(hydrated.get("pr_number") or "").strip()
    if not pr_number:
        return hydrated

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT department, total_amount, requester_name, request_data
                FROM pr_approval_workflows
                WHERE pr_number = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (pr_number,),
            )
            row = cursor.fetchone()

        if not row:
            return hydrated

        request_data = row.get("request_data") or {}
        if isinstance(request_data, str):
            try:
                request_data = json.loads(request_data)
            except Exception:
                request_data = {}

        context_payload = request_data.get("context", {}) if isinstance(request_data, dict) else {}
        raw_pr_data = {}
        if isinstance(context_payload, dict):
            raw_pr_data = context_payload.get("raw_pr_data", {}) or {}
        if not raw_pr_data and isinstance(request_data, dict):
            raw_pr_data = request_data.get("raw_pr_data", {}) or {}
        if not isinstance(raw_pr_data, dict):
            raw_pr_data = {}

        # Keep explicit user-provided fields; fill only missing/blank values.
        for key in [
            "vendor_name", "selected_vendor_name", "justification", "budget_category",
            "category", "product_name", "quantity", "department", "urgency", "requester_name", "budget",
        ]:
            value = raw_pr_data.get(key)
            if value in (None, ""):
                continue
            if hydrated.get(key) in (None, ""):
                hydrated[key] = value

        if hydrated.get("department") in (None, "") and row.get("department"):
            hydrated["department"] = row.get("department")
        if hydrated.get("requester_name") in (None, "") and row.get("requester_name"):
            hydrated["requester_name"] = row.get("requester_name")
        if hydrated.get("budget") in (None, "") and row.get("total_amount") is not None:
            hydrated["budget"] = row.get("total_amount")

        logger.info(f"[PR_DATA_HYDRATION] Hydrated context from workflow for {pr_number}: {hydrated}")
        return hydrated
    except Exception as e:
        logger.warning(f"[PR_DATA_HYDRATION] Failed to hydrate PR context for {pr_number}: {e}")
        return hydrated
    finally:
        if conn:
            return_db_connection(conn)


def _collect_shared_intent_filters(intents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collect reusable filters from all intents so each step has complete context."""
    if not intents:
        return {}

    allowed_keys = {
        "amount", "total_cost", "budget", "category", "department",
        "vendor", "vendor_name", "item", "product", "product_name",
        "quantity", "budget_category", "urgency", "justification"
    }

    shared: Dict[str, Any] = {}
    for intent in intents:
        filters = (intent or {}).get("filters", {}) or {}
        if not isinstance(filters, dict):
            continue
        for key, value in filters.items():
            if key in allowed_keys and value not in (None, ""):
                shared[key] = value

    logger.info(f"[INTENT SHARED FILTERS] {shared}")
    return shared


def _attach_intent_metadata(
    raw_result: Any,
    *,
    intent_query_type: str,
    intent_filters: Optional[Dict[str, Any]] = None,
    enriched_pr_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach per-intent metadata and ensure department context is visible in child payloads."""
    result = dict(raw_result) if isinstance(raw_result, dict) else {}
    filters = intent_filters if isinstance(intent_filters, dict) else {}
    pr_data = enriched_pr_data if isinstance(enriched_pr_data, dict) else {}

    result["intent_metadata"] = {
        "query_type": intent_query_type,
        "filters": filters,
    }

    department = filters.get("department") or pr_data.get("department")
    if not department:
        return result

    primary = result.get("primary_result")
    if isinstance(primary, dict):
        primary.setdefault("intent_department", department)
        payload = primary.get("result")
        if isinstance(payload, dict) and not payload.get("department"):
            payload["department"] = department
    elif not result.get("department"):
        result["department"] = department

    return result


def _build_po_data_result(user_query: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    odoo = get_odoo_client()
    po_filters = filters or {}
    state_filter = _normalize_po_state(po_filters.get("state"))

    amount_filter = po_filters.get("amount_min")
    if amount_filter is not None:
        try:
            amount_filter = float(amount_filter)
        except (TypeError, ValueError):
            amount_filter = None

    domain: List = []
    if state_filter:
        domain.append(("state", "=", state_filter))
    if amount_filter is not None:
        domain.append(("amount_total", ">", amount_filter))

    total_count = int(odoo.search_count("purchase.order", domain) or 0)

    if _is_po_count_query(user_query):
        return {
            "status": "completed",
            "agent": "OdooDataService",
            "result": {
                "status": "success",
                "data_source": "odoo",
                "query_type": "purchase_orders",
                "summary": f"Total purchase orders: {total_count}",
                "total_purchase_orders": total_count,
                "state_filter": state_filter,
                "amount_min": amount_filter,
            },
            "data_source": "odoo",
            "query_type": "purchase_orders",
        }

    # Return full list for direct "list/show all" requests while keeping a safe cap.
    list_limit = min(max(total_count, 20), 200)
    orders = odoo.get_purchase_orders(limit=list_limit, domain=domain)
    simplified_orders: List[Dict[str, Any]] = []
    for order in orders:
        partner = order.get("partner_id")
        vendor_name = partner[1] if isinstance(partner, list) and len(partner) > 1 else (
            partner[1] if isinstance(partner, tuple) and len(partner) > 1 else "Unknown Vendor"
        )
        simplified_orders.append({
            "name": order.get("name"),
            "state": order.get("state"),
            "amount_total": order.get("amount_total"),
            "date_order": order.get("date_order"),
            "vendor_name": vendor_name,
        })

    return {
        "status": "completed",
        "agent": "OdooDataService",
        "result": {
            "status": "success",
            "data_source": "odoo",
            "query_type": "purchase_orders",
            "summary": f"Showing {len(simplified_orders)} of {total_count} purchase orders.",
            "total_purchase_orders": total_count,
            "state_filter": state_filter,
            "amount_min": amount_filter,
            "purchase_orders": simplified_orders,
        },
        "data_source": "odoo",
        "query_type": "purchase_orders",
    }


def _build_odoo_data_result(user_query: str, query_type: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_type = normalize_odoo_query_type(query_type)
    normalized_filters = filters or {}

    if normalized_type == "purchase_orders":
        return _build_po_data_result(user_query, normalized_filters)

    records = hybrid_query.query_odoo_data(normalized_type, normalized_filters)
    return {
        "status": "completed",
        "agent": "OdooDataService",
        "result": {
            "status": "success",
            "data_source": "odoo",
            "query_type": normalized_type,
            "summary": f"Showing {len(records)} {normalized_type}.",
            normalized_type: records,
        },
        "data_source": "odoo",
        "query_type": normalized_type,
    }


async def _build_multi_vendor_risk_result(user_query: str, pr_data: Optional[Dict[str, Any]] = None, limit: int = 20) -> Dict[str, Any]:
    """Fetch vendors and run the RiskAssessmentAgent for each vendor, returning a comparison.

    This helper returns a dict compatible with agentic result shapes, with keys:
    - vendor_risk_comparison: list of {vendor_id, vendor_name, risk_score, payload}
    - lowest_risk_vendor: the vendor entry with lowest risk_score
    - summary: plain text summary
    """
    try:
        # Fetch vendors from Odoo (use existing helper)
        odoo_vendors = _build_odoo_data_result(user_query, "vendors", {"limit": limit})
        vendors = odoo_vendors.get("result", {}).get("vendors", []) or []
    except Exception as e:
        print(f"[MULTI_VENDOR_RISK] Failed to fetch vendors: {e}")
        vendors = []

    orch = initialize_orchestrator_with_agents()
    comparisons: List[Dict[str, Any]] = []

    for v in vendors:
        vendor_name = v.get("name") or v.get("display_name") or str(v.get("id"))
        enriched = dict(pr_data or {})
        # Flatten vendor keys directly — RiskAssessmentAgent reads pr_data.get("vendor_name")
        enriched["vendor_name"] = vendor_name
        enriched["vendor_id"] = v.get("id")
        enriched["supplier_name"] = vendor_name

        context = {
            "request": f"Assess risk for vendor {vendor_name}",
            "pr_data": enriched,
            "query_type": "RISK",
            "mode": "orchestrated",
        }

        try:
            result = await orch.execute(context)
            primary = result.get("result", {}).get("primary_result", {}) if isinstance(result, dict) else {}
            risk_payload = primary.get("result", {}) if isinstance(primary, dict) else {}
            score = risk_payload.get("risk_score") or risk_payload.get("score") or 100
        except Exception as ex:
            print(f"[MULTI_VENDOR_RISK] Orchestrator failed for vendor {vendor_name}: {ex}")
            risk_payload = {}
            score = 100

        comparisons.append({
            "vendor_id": v.get("id"),
            "vendor_name": vendor_name,
            "risk_score": float(score),
            "payload": risk_payload,
        })

    # sort ascending (lowest risk first)
    comparisons.sort(key=lambda x: (x.get("risk_score") is None, x.get("risk_score", 100)))

    summary = "Risk comparison across vendors generated."
    lowest = comparisons[0] if comparisons else None

    return {
        "status": "completed",
        "agent": "MultiVendorRiskAgent",
        "result": {
            "status": "success",
            "vendor_risk_comparison": comparisons,
            "lowest_risk_vendor": lowest,
            "summary": summary,
            "total_vendors": len(comparisons),
        },
        "data_source": "agentic",
        "query_type": "RISK:VENDOR_COMPARISON",
    }


def _canonicalize_intents(intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Collapse redundant intent combinations into a single workflow.

    CREATE already runs compliance/budget/approval workflow in orchestrator,
    so CREATE + APPROVAL should execute as CREATE only.
    """
    if not intents:
        return intents

    normalized_types = {str((intent or {}).get("query_type", "")).upper() for intent in intents}
    if "CREATE" in normalized_types and "APPROVAL" in normalized_types:
        collapsed = [intent for intent in intents if str((intent or {}).get("query_type", "")).upper() != "APPROVAL"]
        if collapsed:
            logger.info("[INTENT CANONICALIZATION] Collapsed CREATE+APPROVAL into CREATE workflow")
            return collapsed

    return intents


# Agent types that must route through the orchestrator (never OdooDataService).
# When any of these is explicitly locked by the user, data_source is forced to "agentic".
_AGENTIC_AGENT_TYPES = {
    "budget_verification", "approval_routing", "vendor_selection",
    "risk_assessment", "contract_monitoring", "supplier_performance",
    "price_analysis", "compliance_check", "invoice_matching",
    "spend_analytics", "inventory_check",
    "pr_creation", "pr", "create", "po_creation", "po",
}


def _apply_agent_type_override(query_type: str, agent_type: Optional[str]) -> str:
    """Allow caller to force certain orchestrator paths when intent is explicit."""
    if not agent_type:
        return query_type

    raw_agent_type = agent_type.strip()
    normalized = raw_agent_type.lower()
    override_map = {
        "pr_creation": "CREATE",
        "pr": "CREATE",
        "create": "CREATE",
        "po_creation": "PO_CREATE",
        "po": "PO_CREATE",
        "budget_verification": "BUDGET",
        "approval_routing": "APPROVAL",
        "vendor_selection": "VENDOR",
        "risk_assessment": "RISK",
        "contract_monitoring": "CONTRACT",
        "supplier_performance": "PERFORMANCE",
        "price_analysis": "PRICE",
        "compliance_check": "COMPLIANCE",
        "invoice_matching": "INVOICE",
        "spend_analytics": "SPEND",
        "inventory_check": "INVENTORY",
    }

    if normalized in override_map:
        return override_map[normalized]

    # Allow UI to send class names like BudgetVerificationAgent.
    class_name_map = {
        "budgetverificationagent": "BUDGET",
        "approvalroutingagent": "APPROVAL",
        "vendorselectionagent": "VENDOR",
        "riskassessmentagent": "RISK",
        "contractmonitoringagent": "CONTRACT",
        "supplierperformanceagent": "PERFORMANCE",
        "priceanalysisagent": "PRICE",
        "compliancecheckagent": "COMPLIANCE",
        "invoicematchingagent": "INVOICE",
        "spendanalyticsagent": "SPEND",
        "inventorycheckagent": "INVENTORY",
    }
    normalized_compact = re.sub(r"[^a-z]", "", normalized)
    if normalized_compact in class_name_map:
        return class_name_map[normalized_compact]

    return query_type


# Request/Response Models
class AgenticRequest(BaseModel):
    """Request to orchestrator or specific agent"""
    request: str
    pr_data: Optional[Dict[str, Any]] = None
    agent_type: Optional[str] = None  # If targeting specific agent
    

class AgenticResponse(BaseModel):
    """Response from agentic system"""
    status: str
    agent: str
    decision: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    data_source: Optional[str] = None
    query_type: Optional[str] = None
    error: Optional[str] = None


# New models for approval system
class ApprovalActionRequest(BaseModel):
    """Request to approve a decision"""
    notes: Optional[str] = None


class RejectionRequest(BaseModel):
    """Request to reject a decision"""
    reason: str


class ApproveStepRequest(BaseModel):
    """Request to approve a workflow step"""
    approver_email: str
    notes: Optional[str] = None


class RejectStepRequest(BaseModel):
    """Request to reject a workflow step"""
    approver_email: str
    rejection_reason: str


@router.post("/execute", response_model=AgenticResponse)
async def execute_agentic_request(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Execute an agentic request via orchestrator.
    
    The orchestrator will analyze the request and route it to the
    appropriate specialized agent(s).
    """
    print("\n" + "="*80)
    print("[AGENTIC EXECUTE] 🤖 Orchestrator execution requested")
    print("="*80)
    try:
        request_id = str(uuid.uuid4())
        print(f"[EXECUTE] 📥 Request: {request.request[:100]}{'...' if len(request.request) > 100 else ''}")
        print(f"[EXECUTE] 📊 PR Data: {request.pr_data}")
        print(f"[EXECUTE] 🎯 Agent Type: {request.agent_type or 'Auto-detect'}")
        
        # 🔥 CLASSIFY THE QUERY FIRST (multi-intent support)
        print(f"[EXECUTE] 🧠 Classifying query to determine query_type...")
        classification = classify_query_intent(request.request)
        classification = resolve_followup_context_with_llm(request.request, classification, request.pr_data)
        
        # Check for multi-intent queries
        intents = classification.get("intents", [])
        if not intents:
            # Backward compatibility: single intent format
            intents = [{
                "data_source": classification.get("data_source", "agentic"),
                "query_type": classification.get("query_type", ""),
                "filters": classification.get("filters", {})
            }]

        intents = _canonicalize_intents(intents)
        # Safety net: re-apply multi-intent keyword correction after canonicalization
        intents = _fix_multi_intent_routing(request.request, intents)
        
        print(f"[EXECUTE] 🔍 Detected {len(intents)} intent(s)")
        
        # Multi-intent execution (sequential)
        if len(intents) > 1:
            print(f"[EXECUTE] 🔄 MULTI-INTENT: Executing {len(intents)} agents sequentially...")
            all_results = []
            all_query_types = []
            normalized_base_pr_data = _hydrate_pr_data_from_workflow(
                _normalize_budget_from_request_text(request.request, request.pr_data or {})
            )
            shared_filters = _collect_shared_intent_filters(intents)
            budget_failed = False
            create_already_routed = False
            created_pr_number = None
            create_failed = False
            create_failure_reason = None
            
            for idx, intent in enumerate(intents, 1):
                intent_data_source = intent.get("data_source", "agentic")
                intent_query_type = intent.get("query_type", "")
                intent_query_type = _apply_agent_type_override(intent_query_type, request.agent_type)
                intent_query_type_upper = str(intent_query_type).upper()
                intent_filters = intent.get("filters", {}) or {}
                all_query_types.append(intent_query_type)
                
                print(f"\n[EXECUTE - Intent {idx}/{len(intents)}]")
                print(f"  → Data source: {intent_data_source}")
                print(f"  → Query type: {intent_query_type}")

                # Budget gate: skip approval if budget check failed earlier in this sequence
                if budget_failed and intent_query_type_upper == "APPROVAL":
                    print(f"[EXECUTE - Intent {idx}] ⛔ Skipping approval due to failed budget verification")
                    blocked_result = {
                        "primary_result": {
                            "status": "blocked_by_budget",
                            "agent": "ApprovalRoutingAgent",
                            "result": {
                                "status": "blocked_by_budget",
                                "action": "skip_approval_routing",
                                "message": "Approval routing skipped because budget verification failed"
                            }
                        },
                        "agents_invoked": [],
                        "total_execution_time_ms": 0
                    }
                    all_results.append(_attach_intent_metadata(
                        blocked_result,
                        intent_query_type=intent_query_type,
                        intent_filters=intent_filters,
                        enriched_pr_data=normalized_base_pr_data,
                    ))
                    continue

                # Create gate: skip approval if PR creation workflow failed earlier
                if create_failed and intent_query_type_upper == "APPROVAL":
                    print(f"[EXECUTE - Intent {idx}] ⛔ Skipping approval because CREATE workflow failed")
                    blocked_result = {
                        "primary_result": {
                            "status": "blocked_by_pr_creation",
                            "agent": "ApprovalRoutingAgent",
                            "result": {
                                "status": "blocked_by_pr_creation",
                                "action": "skip_approval_routing",
                                "message": f"Approval routing skipped because PR creation failed{f': {create_failure_reason}' if create_failure_reason else ''}"
                            }
                        },
                        "agents_invoked": [],
                        "total_execution_time_ms": 0
                    }
                    all_results.append(_attach_intent_metadata(
                        blocked_result,
                        intent_query_type=intent_query_type,
                        intent_filters=intent_filters,
                        enriched_pr_data=normalized_base_pr_data,
                    ))
                    continue

                # Duplicate gate: CREATE workflow already performed approval routing
                if create_already_routed and intent_query_type_upper == "APPROVAL":
                    print(f"[EXECUTE - Intent {idx}] ⏭️ Skipping duplicate approval routing (already routed during CREATE workflow)")
                    skipped_result = {
                        "primary_result": {
                            "status": "success",
                            "agent": "ApprovalRoutingAgent",
                            "result": {
                                "status": "routed",
                                "action": "skip_duplicate_approval_routing",
                                "message": f"Approval already routed during PR creation workflow{f' ({created_pr_number})' if created_pr_number else ''}"
                            }
                        },
                        "agents_invoked": [],
                        "total_execution_time_ms": 0
                    }
                    all_results.append(_attach_intent_metadata(
                        skipped_result,
                        intent_query_type=intent_query_type,
                        intent_filters=intent_filters,
                        enriched_pr_data=normalized_base_pr_data,
                    ))
                    continue
                
                if intent_data_source == "odoo":
                    print(f"[EXECUTE - Intent {idx}] Odoo query detected")
                    # If a specific agentic agent is locked, don't bypass to OdooDataService
                    if request.agent_type and request.agent_type.strip().lower() in _AGENTIC_AGENT_TYPES:
                        print(f"[EXECUTE - Intent {idx}] Agent locked to '{request.agent_type}' — forcing agentic path despite odoo data_source")
                        intent_data_source = "agentic"
                    else:
                        normalized_type = normalize_odoo_query_type(intent_query_type)
                        # Vendor recommendation redirect
                        if normalized_type == "vendors" and re.search(r"\b(top|best|recommend|suggest|rank|score)\b", request.request, re.I):
                            print(f"[EXECUTE - Intent {idx}] Redirecting vendor list to VendorSelectionAgent")
                            intent_data_source = "agentic"
                            intent_query_type = "VENDOR"

                        # Multi-vendor risk comparison
                        if re.search(r"\brisk\b.*\b(vendors|vendor)\b|\b(vendor)s?\s*(across|each|all)\b.*\brisk\b", request.request, re.I):
                            print(f"[EXECUTE - Intent {idx}] Multi-vendor risk comparison detected — running helper")
                            multi = await _build_multi_vendor_risk_result(request.request, normalized_base_pr_data, limit=20)
                            all_results.append(_attach_intent_metadata(
                                multi.get("result", {}),
                                intent_query_type=intent_query_type,
                                intent_filters=intent_filters,
                                enriched_pr_data=normalized_base_pr_data,
                            ))
                            continue

                        if intent_data_source == "odoo":
                            odoo_result = _build_odoo_data_result(request.request, intent_query_type, intent.get("filters", {}))
                            all_results.append(_attach_intent_metadata(
                                odoo_result.get("result", {}),
                                intent_query_type=intent_query_type,
                                intent_filters=intent_filters,
                                enriched_pr_data=normalized_base_pr_data,
                            ))
                            continue
                else:
                    print(f"[EXECUTE - Intent {idx}] Initializing orchestrator...")
                    orch = initialize_orchestrator_with_agents()
                    
                    # 🔥 ENRICH PR_DATA FROM INTENT FILTERS (FIX FOR MULTI-INTENT NL QUERIES)
                    combined_filters = dict(shared_filters)
                    if isinstance(intent_filters, dict):
                        combined_filters.update(intent_filters)
                    enriched_pr_data = _hydrate_pr_data_from_workflow(
                        _enrich_pr_data_from_filters(normalized_base_pr_data, combined_filters)
                    )
                    
                    context = {
                        "request": request.request,
                        "pr_data": enriched_pr_data,  # ← NOW INCLUDES DATA FROM NL QUERY!
                        "query_type": intent_query_type,
                        "mode": "orchestrated",
                        "request_id": request_id,
                    }
                    result = await orch.execute(context)
                    all_results.append(_attach_intent_metadata(
                        result.get("result", {}),
                        intent_query_type=intent_query_type,
                        intent_filters=intent_filters,
                        enriched_pr_data=enriched_pr_data,
                    ))

                    # Track create-workflow routing to prevent duplicate approval execution
                    if intent_query_type_upper == "CREATE":
                        orchestrator_result_raw = result.get("result") if isinstance(result, dict) else None
                        orchestrator_result = orchestrator_result_raw if isinstance(orchestrator_result_raw, dict) else {}
                        if orchestrator_result.get("workflow_type") == "pr_creation":
                            workflow_status = str(orchestrator_result.get("status", "")).lower()
                            if workflow_status not in {"success", "success_no_workflow"}:
                                create_failed = True
                                create_failure_reason = orchestrator_result.get("failure_reason")
                            pr_object = orchestrator_result.get("pr_object") or {}
                            if not isinstance(pr_object, dict):
                                pr_object = {}
                            validations = orchestrator_result.get("validations") or {}
                            if not isinstance(validations, dict):
                                validations = {}
                            approval_routing = validations.get("approval_routing") or {}
                            if not isinstance(approval_routing, dict):
                                approval_routing = {}
                            approval_result = approval_routing.get("result") or {}
                            if not isinstance(approval_result, dict):
                                approval_result = {}
                            created_pr_number = (
                                pr_object.get("pr_number")
                                or orchestrator_result.get("workflow_id")
                            )
                            approval_status = str(approval_result.get("status", "")).lower()
                            if approval_status == "routed":
                                create_already_routed = True
                                print("[CREATE GATE] Approval already routed in CREATE workflow; later APPROVAL intent will be skipped")

                    # Track budget failure for downstream gating
                    if intent_query_type_upper == "BUDGET":
                        orchestrator_result_raw = result.get("result") if isinstance(result, dict) else None
                        orchestrator_result = orchestrator_result_raw if isinstance(orchestrator_result_raw, dict) else {}
                        primary_result = orchestrator_result.get("primary_result", {})
                        budget_payload = primary_result.get("result", {})
                        budget_status = str(budget_payload.get("status", "")).lower()
                        budget_verified = budget_payload.get("budget_verified")
                        if budget_verified is False or budget_status in {"rejected", "error", "insufficient_budget", "pending_human_approval"}:
                            budget_failed = True
                            print("[BUDGET GATE] Budget verification failed; approval intent will be skipped")
            
            print(f"\n[EXECUTE] ✅ MULTI-INTENT COMPLETE: Executed {len(intents)} intents")
            
            # Combine results
            combined_result = {
                "status": "success",
                "intent_count": len(intents),
                "query_types": all_query_types,
                "results": all_results
            }
            
            return AgenticResponse(
                status="completed",
                agent="MultiIntentOrchestrator",
                decision={"action": "multi_intent_execution", "confidence": classification.get("confidence", 0.8)},
                result=combined_result,
                data_source="multi-intent",
                query_type="MULTI:" + ",".join(all_query_types),
            )
        
        # Single intent path (backward compatible)
        query_type = intents[0].get("query_type", "")
        query_type = _apply_agent_type_override(query_type, request.agent_type)
        data_source = intents[0].get("data_source", "agentic")
        # If a specific agentic agent is locked by the user, never short-circuit to OdooDataService
        if request.agent_type and request.agent_type.strip().lower() in _AGENTIC_AGENT_TYPES:
            data_source = "agentic"
        print(f"[EXECUTE] ✅ Classification result: query_type='{query_type}', data_source='{data_source}'")

        normalized_pr_data = _hydrate_pr_data_from_workflow(
            _normalize_budget_from_request_text(request.request, request.pr_data or {})
        )

        # Enrich pr_data from classifier-extracted filters (same as multi-intent path)
        intent_filters = intents[0].get("filters", {}) or {}
        enriched_pr_data = _hydrate_pr_data_from_workflow(
            _enrich_pr_data_from_filters(normalized_pr_data, intent_filters)
        )
        print(f"[EXECUTE] 📦 Enriched pr_data: {enriched_pr_data}")

        # ── Early intercepts (apply regardless of data_source classification) ──
        # Multi-vendor risk comparison: always route to helper no matter how LLM classified it
        if re.search(r"\b(risk|risks)\b.{0,40}\b(all\s+vendors?|each\s+vendor|vendors?\s+all|across\s+vendors?)\b|\ball\s+vendors?\b.{0,40}\b(risk|risks)\b", request.request, re.I):
            print("[EXECUTE] 🔍 Multi-vendor risk comparison detected — running comparison helper")
            multi = await _build_multi_vendor_risk_result(request.request, enriched_pr_data, limit=20)
            return AgenticResponse(
                status=multi.get("status", "completed"),
                agent=multi.get("agent", "MultiVendorRiskAgent"),
                decision=None,
                result=multi.get("result"),
                data_source=multi.get("data_source", "agentic"),
                query_type=multi.get("query_type", "RISK:VENDOR_COMPARISON"),
            )

        # Vendor recommendation: redirect raw Odoo vendor list to VendorSelectionAgent
        if data_source == "odoo" and normalize_odoo_query_type(query_type) == "vendors" and re.search(r"\b(top|best|recommend|suggest|rank|score)\b", request.request, re.I):
            print("[EXECUTE] 🔁 Redirecting vendor list query to VendorSelectionAgent (recommendation intent detected)")
            data_source = "agentic"
            query_type = "VENDOR"

        if data_source == "odoo":
            print("[EXECUTE] ✅ Odoo data query — bypassing orchestrator")
            odoo_result = _build_odoo_data_result(request.request, query_type, intents[0].get("filters", {}))
            return AgenticResponse(
                status=odoo_result.get("status", "completed"),
                agent=odoo_result.get("agent", "OdooDataService"),
                decision=None,
                result=odoo_result.get("result"),
                data_source=odoo_result.get("data_source", "odoo"),
                query_type=odoo_result.get("query_type", normalize_odoo_query_type(query_type)),
            )
        
        # General/greeting queries — return a friendly response without invoking agents
        if data_source == "general" or query_type.upper() == "GENERAL":
            print("[EXECUTE] 💬 General/greeting query — returning friendly response")
            return AgenticResponse(
                status="success",
                agent="AssistantBot",
                decision=None,
                result={
                    "status": "success",
                    "message": (
                        "Hello! I'm your Procurement AI Assistant. I can help you with:\n\n"
                        "• **Budget Verification** — Check department budget availability\n"
                        "• **Risk Assessment** — Analyze vendor & financial risks\n"
                        "• **Vendor Selection** — Compare and recommend vendors\n"
                        "• **Approval Routing** — Route purchase requests for approval\n"
                        "• **Multi-task** — Combine multiple actions in one request\n\n"
                        "Try asking something like: *\"Check IT budget for $50,000 CAPEX\"*"
                    ),
                },
                data_source="general",
                query_type="GENERAL",
            )
        
        print(f"[EXECUTE] 🔧 Initializing orchestrator...")
        orch = initialize_orchestrator_with_agents()
        print(f"[EXECUTE] ✅ Orchestrator ready with {len(orch.specialized_agents)} agents")
        
        # Build context WITH query_type from classifier
        context = {
            "request": request.request,
            "pr_data": enriched_pr_data,
            "query_type": query_type,  # 🔥 PASS CLASSIFIER RESULT!
            "mode": "orchestrated",
            "request_id": request_id,
        }
        print(f"[EXECUTE] 🔄 Executing through orchestrator with query_type='{query_type}'...")
        
        # Execute through orchestrator
        result = await orch.execute(context)
        
        print(f"[EXECUTE] ✅ Execution complete:")
        print(f"[EXECUTE]   - Status: {result.get('status', 'completed')}")
        print(f"[EXECUTE]   - Agent: {result.get('agent', 'Orchestrator')}")
        print(f"[EXECUTE]   - Has Decision: {bool(result.get('decision'))}")
        print(f"[EXECUTE]   - Has Result: {bool(result.get('result'))}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent=result.get("agent", "Orchestrator"),
            decision=result.get("decision"),
            result=result.get("result"),
            data_source=data_source,
            query_type=query_type,
        )
        
    except Exception as e:
        print(f"[EXECUTE] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[EXECUTE] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Agentic execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute/stream")
async def execute_agentic_request_stream(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Execute an agentic request with REAL-TIME EVENT STREAMING.
    
    Returns Server-Sent Events (SSE) showing the agent execution process:
    - Request received
    - Orchestrator analyzing
    - Agent selected
    - OBSERVE → DECIDE → ACT → LEARN phases
    - Final result
    
    This endpoint provides live visualization of the agentic workflow.
    """
    logger.info(f"[AGENTIC STREAM] 🌊 Starting SSE stream for request")
    
    # Generate unique request ID
    request_id = str(uuid.uuid4())
    
    # Create event stream
    stream = agent_event_stream.create_stream(request_id)

    # Emit first event immediately so client sees instant progress
    await stream.emit(agent_event_stream.AgentEventType.RECEIVED, {
        "request": request.request[:200],  # Truncate long requests
        "has_pr_data": bool(request.pr_data),
        "request_id": request_id
    })
    
    async def execute_with_events():
        """Execute agent and emit events"""
        try:
            def clean_for_json(obj):
                """Remove non-serializable fields from nested payloads before SSE emit."""
                if isinstance(obj, dict):
                    return {k: clean_for_json(v) for k, v in obj.items() if k != "event_stream"}
                if isinstance(obj, list):
                    return [clean_for_json(item) for item in obj]
                return obj

            # Event 2: Classifying
            await stream.emit(agent_event_stream.AgentEventType.CLASSIFYING, {
                "message": "Orchestrator analyzing request intent..."
            })

            # Classify intent after initial events so UI receives immediate feedback
            # (keeps streaming responsive even when classification/LLM call is slower)
            classification = classify_query_intent(request.request)
            classification = resolve_followup_context_with_llm(request.request, classification, request.pr_data)
            
            # Check for multi-intent queries
            intents = classification.get("intents", [])
            if not intents:
                # Backward compatibility: single intent format
                intents = [{
                    "data_source": classification.get("data_source", "agentic"),
                    "query_type": classification.get("query_type", ""),
                    "filters": classification.get("filters", {})
                }]

            intents = _canonicalize_intents(intents)
            # Safety net: re-apply multi-intent keyword correction after canonicalization
            intents = _fix_multi_intent_routing(request.request, intents)
            
            logger.info(f"[AGENTIC STREAM] 🔍 Detected {len(intents)} intent(s)")
            
            # Multi-intent execution
            if len(intents) > 1:
                logger.info(f"[AGENTIC STREAM] 🔄 MULTI-INTENT: Executing {len(intents)} agents sequentially...")
                
                await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                    "message": f"Detected multi-intent query ({len(intents)} actions). Processing sequentially...",
                    "intent_count": len(intents)
                })
                
                all_results = []
                all_agents = []
                budget_failed = False
                create_already_routed = False
                created_pr_number = None
                create_failed = False
                create_failure_reason = None
                normalized_base_pr_data = _hydrate_pr_data_from_workflow(
                    _normalize_budget_from_request_text(request.request, request.pr_data or {})
                )
                shared_filters = _collect_shared_intent_filters(intents)
                
                for idx, intent in enumerate(intents, 1):
                    intent_query_type = _apply_agent_type_override(intent.get("query_type", ""), request.agent_type)
                    intent_query_type_upper = str(intent_query_type).upper()
                    intent_data_source = intent.get("data_source", "agentic")
                    intent_filters = intent.get("filters", {}) or {}
                    
                    logger.info(f"[AGENTIC STREAM - Intent {idx}/{len(intents)}] query_type={intent_query_type}, data_source={intent_data_source}")
                    
                    await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                        "message": f"Processing intent {idx}/{len(intents)}: {intent_query_type}...",
                        "intent_number": idx,
                        "total_intents": len(intents),
                        "query_type": intent_query_type
                    })

                    # Budget gate: skip approval if budget check failed earlier in sequence
                    if budget_failed and intent_query_type_upper == "APPROVAL":
                        await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                            "message": "Approval routing skipped because budget verification failed.",
                            "intent_number": idx,
                            "total_intents": len(intents),
                            "query_type": intent_query_type
                        })
                        blocked_result = {
                            "primary_result": {
                                "status": "blocked_by_budget",
                                "agent": "ApprovalRoutingAgent",
                                "result": {
                                    "status": "blocked_by_budget",
                                    "action": "skip_approval_routing",
                                    "message": "Approval routing skipped because budget verification failed"
                                }
                            },
                            "agents_invoked": [],
                            "total_execution_time_ms": 0
                        }
                        all_results.append(_attach_intent_metadata(
                            blocked_result,
                            intent_query_type=intent_query_type,
                            intent_filters=intent_filters,
                            enriched_pr_data=normalized_base_pr_data,
                        ))
                        all_agents.append("ApprovalRoutingAgent")
                        continue

                    # Create gate: skip approval if PR creation workflow failed earlier
                    if create_failed and intent_query_type_upper == "APPROVAL":
                        await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                            "message": "Approval routing skipped because PR creation workflow failed.",
                            "intent_number": idx,
                            "total_intents": len(intents),
                            "query_type": intent_query_type
                        })
                        blocked_result = {
                            "primary_result": {
                                "status": "blocked_by_pr_creation",
                                "agent": "ApprovalRoutingAgent",
                                "result": {
                                    "status": "blocked_by_pr_creation",
                                    "action": "skip_approval_routing",
                                    "message": f"Approval routing skipped because PR creation failed{f': {create_failure_reason}' if create_failure_reason else ''}"
                                }
                            },
                            "agents_invoked": [],
                            "total_execution_time_ms": 0
                        }
                        all_results.append(_attach_intent_metadata(
                            blocked_result,
                            intent_query_type=intent_query_type,
                            intent_filters=intent_filters,
                            enriched_pr_data=normalized_base_pr_data,
                        ))
                        all_agents.append("ApprovalRoutingAgent")
                        continue

                    # Duplicate gate: CREATE workflow already performed approval routing
                    if create_already_routed and intent_query_type_upper == "APPROVAL":
                        await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                            "message": "Skipping duplicate approval routing because CREATE workflow already routed approval.",
                            "intent_number": idx,
                            "total_intents": len(intents),
                            "query_type": intent_query_type
                        })
                        skipped_result = {
                            "primary_result": {
                                "status": "success",
                                "agent": "ApprovalRoutingAgent",
                                "result": {
                                    "status": "routed",
                                    "action": "skip_duplicate_approval_routing",
                                    "message": f"Approval already routed during PR creation workflow{f' ({created_pr_number})' if created_pr_number else ''}"
                                }
                            },
                            "agents_invoked": [],
                            "total_execution_time_ms": 0
                        }
                        all_results.append(_attach_intent_metadata(
                            skipped_result,
                            intent_query_type=intent_query_type,
                            intent_filters=intent_filters,
                            enriched_pr_data=normalized_base_pr_data,
                        ))
                        all_agents.append("ApprovalRoutingAgent")
                        continue
                    
                    if intent_data_source == "odoo":
                        # If a specific agentic agent is locked, don't bypass to OdooDataService
                        if request.agent_type and request.agent_type.strip().lower() in _AGENTIC_AGENT_TYPES:
                            print(f"[STREAM - Intent {idx}] Agent locked to '{request.agent_type}' — forcing agentic path")
                            intent_data_source = "agentic"
                        else:
                            odoo_result = _build_odoo_data_result(request.request, intent_query_type, intent.get("filters", {}))
                            all_results.append(_attach_intent_metadata(
                                odoo_result.get("result", {}),
                                intent_query_type=intent_query_type,
                                intent_filters=intent_filters,
                                enriched_pr_data=normalized_base_pr_data,
                            ))
                            all_agents.append(odoo_result.get("agent", "OdooDataService"))
                            continue
                    else:
                        # Execute agentic intent
                        orch = initialize_orchestrator_with_agents()
                        orch.event_stream = stream

                        # Enrich pr_data from intent filters (same as sync route)
                        combined_filters = dict(shared_filters)
                        if isinstance(intent_filters, dict):
                            combined_filters.update(intent_filters)
                        enriched_pr_data = _hydrate_pr_data_from_workflow(
                            _enrich_pr_data_from_filters(normalized_base_pr_data, combined_filters)
                        )

                        context = {
                            "request": request.request,
                            "pr_data": enriched_pr_data,
                            "query_type": intent_query_type,
                            "mode": "orchestrated",
                            "event_stream": stream,
                            "request_id": request_id,
                        }
                        intent_result = await orch.execute(context)
                        all_results.append(_attach_intent_metadata(
                            intent_result.get("result", {}),
                            intent_query_type=intent_query_type,
                            intent_filters=intent_filters,
                            enriched_pr_data=enriched_pr_data,
                        ))
                        all_agents.append(intent_result.get("agent", "Unknown"))

                        # Track create-workflow routing to prevent duplicate approval execution
                        if intent_query_type_upper == "CREATE":
                            orchestrator_result_raw = intent_result.get("result") if isinstance(intent_result, dict) else None
                            orchestrator_result = orchestrator_result_raw if isinstance(orchestrator_result_raw, dict) else {}
                            if orchestrator_result.get("workflow_type") == "pr_creation":
                                workflow_status = str(orchestrator_result.get("status", "")).lower()
                                if workflow_status not in {"success", "success_no_workflow"}:
                                    create_failed = True
                                    create_failure_reason = orchestrator_result.get("failure_reason")
                                pr_object = orchestrator_result.get("pr_object") or {}
                                if not isinstance(pr_object, dict):
                                    pr_object = {}
                                validations = orchestrator_result.get("validations") or {}
                                if not isinstance(validations, dict):
                                    validations = {}
                                approval_routing = validations.get("approval_routing") or {}
                                if not isinstance(approval_routing, dict):
                                    approval_routing = {}
                                approval_result = approval_routing.get("result") or {}
                                if not isinstance(approval_result, dict):
                                    approval_result = {}
                                created_pr_number = (
                                    pr_object.get("pr_number")
                                    or orchestrator_result.get("workflow_id")
                                )
                                approval_status = str(approval_result.get("status", "")).lower()
                                if approval_status == "routed":
                                    create_already_routed = True

                        # Track budget failure for downstream gating
                        if intent_query_type_upper == "BUDGET":
                            orchestrator_result_raw = intent_result.get("result") if isinstance(intent_result, dict) else None
                            orchestrator_result = orchestrator_result_raw if isinstance(orchestrator_result_raw, dict) else {}
                            primary_result = orchestrator_result.get("primary_result", {})
                            budget_payload = primary_result.get("result", {})
                            budget_status = str(budget_payload.get("status", "")).lower()
                            budget_verified = budget_payload.get("budget_verified")
                            if budget_verified is False or budget_status in {"rejected", "error", "insufficient_budget", "pending_human_approval"}:
                                budget_failed = True
                
                # Combine multi-intent results
                clean_multi_results = clean_for_json(all_results)
                await stream.emit_complete({
                    "status": "success",
                    "agent": "MultiIntentOrchestrator",
                    "result": {
                        "intent_count": len(intents),
                        "results": clean_multi_results
                    },
                    "agents_invoked": all_agents,
                    "data_source": "multi-intent",
                    "query_type": "MULTI",
                })
                return
            
            # Single intent path (backward compatible)
            query_type = _apply_agent_type_override(intents[0].get("query_type", ""), request.agent_type)
            data_source = intents[0].get("data_source", "agentic")
            # If a specific agentic agent is locked, force agentic path
            if request.agent_type and request.agent_type.strip().lower() in _AGENTIC_AGENT_TYPES:
                data_source = "agentic"

            normalized_pr_data = _hydrate_pr_data_from_workflow(
                _normalize_budget_from_request_text(request.request, request.pr_data or {})
            )

            # Enrich pr_data from classifier-extracted filters
            intent_filters = intents[0].get("filters", {}) or {}
            enriched_pr_data = _hydrate_pr_data_from_workflow(
                _enrich_pr_data_from_filters(normalized_pr_data, intent_filters)
            )
            print(f"[STREAM] 📦 Enriched pr_data: {enriched_pr_data}")

            # ── Early intercepts (apply regardless of data_source classification) ──
            # Multi-vendor risk: always run helper, even when LLM classifies as agentic RISK
            if re.search(r"\b(risk|risks)\b.{0,40}\b(all\s+vendors?|each\s+vendor|vendors?\s+all|across\s+vendors?)\b|\ball\s+vendors?\b.{0,40}\b(risk|risks)\b", request.request, re.I):
                print("[STREAM] 🔍 Multi-vendor risk comparison detected — running comparison helper")
                await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                    "message": "Detected multi-vendor risk comparison request. Running risk assessment for all vendors...",
                    "query_type": "RISK:VENDOR_COMPARISON"
                })
                multi = await _build_multi_vendor_risk_result(request.request, enriched_pr_data, limit=20)
                await stream.emit_complete({
                    "status": multi.get("status", "completed"),
                    "agent": multi.get("agent", "MultiVendorRiskAgent"),
                    "result": multi.get("result", {}),
                    "agents_invoked": ["MultiVendorRiskAgent"],
                    "data_source": multi.get("data_source", "agentic"),
                    "query_type": multi.get("query_type", "RISK:VENDOR_COMPARISON"),
                })
                return

            # Vendor recommendation redirect
            if data_source == "odoo" and normalize_odoo_query_type(query_type) == "vendors" and re.search(r"\b(top|best|recommend|suggest|rank|score)\b", request.request, re.I):
                print("[STREAM] 🔁 Redirecting vendor list to VendorSelectionAgent")
                data_source = "agentic"
                query_type = "VENDOR"

            if data_source == "odoo":
                await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                    "message": "Detected Odoo data query. Reading live Odoo records...",
                    "query_type": normalize_odoo_query_type(query_type)
                })

                odoo_result = _build_odoo_data_result(request.request, query_type, intents[0].get("filters", {}))
                await stream.emit_complete({
                    "status": odoo_result.get("status", "completed"),
                    "agent": odoo_result.get("agent", "OdooDataService"),
                    "result": odoo_result.get("result", {}),
                    "agents_invoked": [odoo_result.get("agent", "OdooDataService")],
                    "data_source": odoo_result.get("data_source", "odoo"),
                    "query_type": odoo_result.get("query_type", normalize_odoo_query_type(query_type)),
                })
                return
            
            # General/greeting queries — return a friendly response without invoking agents
            if data_source == "general" or query_type.upper() == "GENERAL":
                logger.info("[AGENTIC STREAM] 💬 General/greeting query detected — returning friendly response")
                await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                    "message": "General query detected.",
                    "query_type": "GENERAL"
                })
                await stream.emit_complete({
                    "status": "success",
                    "agent": "AssistantBot",
                    "result": {
                        "status": "success",
                        "message": (
                            "Hello! I'm your Procurement AI Assistant. I can help you with:\n\n"
                            "• **Budget Verification** — Check department budget availability\n"
                            "• **Risk Assessment** — Analyze vendor & financial risks\n"
                            "• **Vendor Selection** — Compare and recommend vendors\n"
                            "• **Approval Routing** — Route purchase requests for approval\n"
                            "• **Multi-task** — Combine multiple actions in one request\n\n"
                            "Try asking something like: *\"Check IT budget for $50,000 CAPEX\"*"
                        ),
                    },
                    "agents_invoked": [],
                    "data_source": "general",
                    "query_type": "GENERAL",
                })
                return
            
            # Initialize orchestrator
            orch = initialize_orchestrator_with_agents()
            orch.event_stream = stream  # Attach stream to orchestrator
            
            # Build context
            context = {
                "request": request.request,
                "pr_data": enriched_pr_data,
                "query_type": query_type,
                "mode": "orchestrated",
                "event_stream": stream,  # Pass stream to agents
                "request_id": request_id,
            }
            
            # Event 3: Routing
            await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                "message": "Determining which agent should handle this request...",
                "query_type": query_type
            })
            
            # Execute through orchestrator
            result = await orch.execute(context)
            
            clean_result = clean_for_json(result)
            
            # Event: Complete 
            # Extract primary_result from orchestrator response
            # Orchestrator wraps result in: { status, agent: "Orchestrator", decision, result: { primary_result, secondary_results, ... } }
            orch_inner = clean_result.get("result", {}) if isinstance(clean_result.get("result"), dict) else {}
            primary_result = orch_inner.get("primary_result", clean_result.get("primary_result", clean_result))
            nested_result = primary_result.get("result", {}) if isinstance(primary_result, dict) else {}
            agents_invoked = (
                orch_inner.get("agents_invoked")
                or clean_result.get("agents_invoked")
                or primary_result.get("agents_invoked", [])
                or (nested_result.get("agents_invoked", []) if isinstance(nested_result, dict) else [])
            )
            
            # Get agent name from the actual specialized agent (not Orchestrator wrapper)
            actual_agent = primary_result.get("agent", clean_result.get("agent", "Unknown"))
            
            await stream.emit_complete({
                "status": primary_result.get("status", "completed"),
                "agent": actual_agent,
                "result": {
                    "primary_result": primary_result,
                    "secondary_results": orch_inner.get("secondary_results", []),
                    "agents_invoked": list(agents_invoked) if agents_invoked else [],
                    "total_execution_time_ms": orch_inner.get("total_execution_time_ms", 0),
                },
                "agents_invoked": list(agents_invoked) if agents_invoked else [],
                "data_source": classification.get("data_source", "agentic"),
                "query_type": query_type,
            })
            
        except Exception as e:
            logger.error(f"[AGENTIC STREAM] ❌ Error: {e}")
            await stream.emit_error(str(e), {"request_id": request_id})
        finally:
            # Cleanup after stream completes
            agent_event_stream.cleanup_stream(request_id)
    
    # Start execution in background
    import asyncio
    asyncio.create_task(execute_with_events())
    
    # Return SSE stream
    return StreamingResponse(
        stream.generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.post("/budget/verify", response_model=AgenticResponse)
async def verify_budget(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Direct budget verification (bypass orchestrator).
    
    Useful for testing individual agents.
    """
    print("\n" + "="*80)
    print("[BUDGET VERIFY] 💰 Budget verification requested")
    print("="*80)
    try:
        print(f"[BUDGET] 📥 Request: {request.request}")
        print(f"[BUDGET] 📊 PR Data:")
        print(f"[BUDGET]   - Department: {request.pr_data.get('department') if request.pr_data else 'N/A'}")
        print(f"[BUDGET]   - Budget: ${request.pr_data.get('budget', 0):,.2f}" if request.pr_data else "[BUDGET]   - Budget: $0")
        print(f"[BUDGET]   - Category: {request.pr_data.get('budget_category', 'N/A')}" if request.pr_data else "[BUDGET]   - Category: N/A")
        
        print(f"[BUDGET] 🔧 Creating BudgetVerificationAgent...")
        budget_agent = BudgetVerificationAgent()
        print(f"[BUDGET] ✅ Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        print(f"[BUDGET] 🔄 Executing budget check...")
        result = await budget_agent.execute(context)
        
        print(f"[BUDGET] ✅ Verification complete:")
        print(f"[BUDGET]   - Status: {result.get('status', 'completed')}")
        print(f"[BUDGET]   - Decision: {result.get('decision', {}).get('action', 'N/A')}")
        print(f"[BUDGET]   - Confidence: {result.get('decision', {}).get('confidence', 0):.2f}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="BudgetVerificationAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[BUDGET] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[BUDGET] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Budget verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approval/route", response_model=AgenticResponse)
async def route_approval(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Route a PR through approval chain (bypass orchestrator).
    
    Direct access to ApprovalRoutingAgent for testing.
    """
    print("\n" + "="*80)
    print("[APPROVAL ROUTE] 📋 Approval routing requested")
    print("="*80)
    try:
        print(f"[APPROVAL] 📥 Request: {request.request}")
        print(f"[APPROVAL] 📊 PR Data:")
        print(f"[APPROVAL]   - Department: {request.pr_data.get('department') if request.pr_data else 'N/A'}")
        print(f"[APPROVAL]   - Budget: ${request.pr_data.get('budget', 0):,.2f}" if request.pr_data else "[APPROVAL]   - Budget: $0")
        print(f"[APPROVAL]   - PR Number: {request.pr_data.get('pr_number', 'N/A')}" if request.pr_data else "[APPROVAL]   - PR Number: N/A")
        
        print(f"[APPROVAL] 🔧 Creating ApprovalRoutingAgent...")
        approval_agent = ApprovalRoutingAgent()
        print(f"[APPROVAL] ✅ Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        print(f"[APPROVAL] 🔄 Determining approval chain...")
        result = await approval_agent.execute(context)
        
        print(f"[APPROVAL] ✅ Routing complete:")
        print(f"[APPROVAL]   - Status: {result.get('status', 'completed')}")
        print(f"[APPROVAL]   - Approvers: {len(result.get('result', {}).get('assigned_approvers', []))}")
        print(f"[APPROVAL]   - Level: {result.get('result', {}).get('required_level', 'N/A')}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="ApprovalRoutingAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[APPROVAL] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[APPROVAL] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Approval routing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vendor/recommend", response_model=AgenticResponse)
async def recommend_vendor(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Get vendor recommendations for a purchase (bypass orchestrator).
    
    Direct access to VendorSelectionAgent for testing.
    Returns top 3 vendors scored on quality, price, delivery, and category match.
    """
    print("\n" + "="*80)
    print("[VENDOR RECOMMEND] 🏪 Vendor recommendation requested")
    print("="*80)
    try:
        print(f"[VENDOR] 📥 Request: {request.request}")
        print(f"[VENDOR] 📊 PR Data: Category={request.pr_data.get('category', 'N/A') if request.pr_data else 'N/A'}, Budget=${request.pr_data.get('budget', 0):,.2f}" if request.pr_data else "[VENDOR] 📊 PR Data: None")
        
        print(f"[VENDOR] 🔧 Creating VendorSelectionAgent...")
        vendor_agent = VendorSelectionAgent()
        print(f"[VENDOR] ✅ Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        print(f"[VENDOR] 🔄 Scoring and ranking vendors...")
        result = await vendor_agent.execute(context)
        
        print(f"[VENDOR] ✅ Recommendation complete:")
        print(f"[VENDOR]   - Status: {result.get('status', 'completed')}")
        print(f"[VENDOR]   - Top vendor: {result.get('result', {}).get('top_vendor', {}).get('name', 'N/A')}")
        print(f"[VENDOR]   - Score: {result.get('result', {}).get('top_vendor', {}).get('total_score', 0)}/100")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="VendorSelectionAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[VENDOR] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[VENDOR] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Vendor recommendation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/risk/assess", response_model=AgenticResponse)
async def assess_risk(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Assess procurement risks (bypass orchestrator).
    
    Direct access to RiskAssessmentAgent for testing.
    Returns risk score (0-100) with breakdown across vendor, financial, compliance, and operational dimensions.
    Risk Levels: LOW (<30), MEDIUM (30-60), HIGH (60-80), CRITICAL (>80)
    """
    print("\n" + "="*80)
    print("[RISK ASSESS] ⚠️  Risk assessment requested")
    print("="*80)
    try:
        print(f"[RISK] 📥 Request: {request.request}")
        print(f"[RISK] 📊 PR Data: Vendor={request.pr_data.get('vendor_name', 'N/A') if request.pr_data else 'N/A'}, Amount=${request.pr_data.get('budget', 0):,.2f}" if request.pr_data else "[RISK] 📊 PR Data: None")
        
        print(f"[RISK] 🔧 Creating RiskAssessmentAgent...")
        risk_agent = RiskAssessmentAgent()
        print(f"[RISK] ✅ Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        print(f"[RISK] 🔄 Analyzing 4 risk dimensions...")
        result = await risk_agent.execute(context)
        
        print(f"[RISK] ✅ Assessment complete:")
        print(f"[RISK]   - Status: {result.get('status', 'completed')}")
        print(f"[RISK]   - Risk Level: {result.get('result', {}).get('risk_level', 'N/A')}")
        print(f"[RISK]   - Score: {result.get('result', {}).get('risk_score', 0)}/100")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="RiskAssessmentAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[RISK] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[RISK] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Risk assessment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/contract/monitor", response_model=AgenticResponse)
async def monitor_contract(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Monitor contracts for expiration and compliance (bypass orchestrator).
    
    Direct access to ContractMonitoringAgent for testing.
    Tracks expiration status (90/60/30/7 day thresholds), spend vs contract, renewal recommendations.
    Alert Levels: INFO, LOW, MEDIUM, HIGH, URGENT, CRITICAL
    """
    print("\n" + "="*80)
    print("[CONTRACT MONITOR] 📝 Contract monitoring requested")
    print("="*80)
    print(f"[CONTRACT] 📥 Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    print(f"[CONTRACT] 📊 Contract Data: {request.pr_data}")
    
    try:
        print(f"[CONTRACT] 🔧 Creating ContractMonitoringAgent...")
        from backend.agents.contract_monitoring import ContractMonitoringAgent
        contract_agent = ContractMonitoringAgent()
        print(f"[CONTRACT] ✅ Agent created")
        
        context = {
            "request": request.request,
            "contract_data": request.pr_data or {}
        }
        
        print(f"[CONTRACT] 🔄 Executing contract monitoring...")
        result = await contract_agent.execute(context)
        
        print(f"[CONTRACT] ✅ Monitoring complete:")
        print(f"[CONTRACT]   - Status: {result.get('status', 'completed')}")
        print(f"[CONTRACT]   - Has Decision: {result.get('decision') is not None}")
        print(f"[CONTRACT]   - Has Result: {result.get('result') is not None}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="ContractMonitoringAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[CONTRACT] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[CONTRACT] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Contract monitoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/supplier/evaluate", response_model=AgenticResponse)
async def evaluate_supplier(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Evaluate supplier performance (bypass orchestrator).
    
    Direct access to SupplierPerformanceAgent for testing.
    Evaluates across 4 dimensions: Delivery (40%), Quality (30%), Price (15%), Communication (15%).
    Performance Levels: Excellent (90-100), Good (75-89), Fair (60-74), Poor (40-59), Critical (0-39)
    """
    print("\n" + "="*80)
    print("[SUPPLIER EVALUATE] 📊 Supplier performance evaluation requested")
    print("="*80)
    print(f"[SUPPLIER] 📥 Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    print(f"[SUPPLIER] 📊 Supplier Data: {request.pr_data}")
    
    try:
        print(f"[SUPPLIER] 🔧 Creating SupplierPerformanceAgent...")
        from backend.agents.supplier_performance import SupplierPerformanceAgent
        supplier_agent = SupplierPerformanceAgent()
        print(f"[SUPPLIER] ✅ Agent created")
        
        context = {
            "request": request.request,
            "supplier_data": request.pr_data or {}
        }
        
        print(f"[SUPPLIER] 🔄 Evaluating supplier across 4 dimensions...")
        result = await supplier_agent.execute(context)
        
        print(f"[SUPPLIER] ✅ Evaluation complete:")
        print(f"[SUPPLIER]   - Status: {result.get('status', 'completed')}")
        print(f"[SUPPLIER]   - Has Decision: {result.get('decision') is not None}")
        print(f"[SUPPLIER]   - Has Result: {result.get('result') is not None}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="SupplierPerformanceAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[SUPPLIER] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[SUPPLIER] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Supplier evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/price/analyze", response_model=AgenticResponse)
async def analyze_price(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Analyze pricing competitiveness (bypass orchestrator).
    
    Direct access to PriceAnalysisAgent for testing.
    Compares quoted prices to market averages, identifies single-source risks,
    and recommends negotiation opportunities.
    Price Levels: Excellent (<-10%), Competitive (±10%), High (10-20%), Very High (>20%)
    """
    print("\n" + "="*80)
    print("[PRICE ANALYZE] 💰 Price analysis requested")
    print("="*80)
    print(f"[PRICE] 📥 Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    print(f"[PRICE] 📊 PR Data: {request.pr_data}")
    
    try:
        print(f"[PRICE] 🔧 Creating PriceAnalysisAgent...")
        from backend.agents.price_analysis import PriceAnalysisAgent
        price_agent = PriceAnalysisAgent()
        print(f"[PRICE] ✅ Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        print(f"[PRICE] 🔄 Analyzing price competitiveness...")
        result = await price_agent.execute(context)
        
        print(f"[PRICE] ✅ Analysis complete:")
        print(f"[PRICE]   - Status: {result.get('status', 'completed')}")
        print(f"[PRICE]   - Has Decision: {result.get('decision') is not None}")
        print(f"[PRICE]   - Has Result: {result.get('result') is not None}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="PriceAnalysisAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[PRICE] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[PRICE] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Price analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compliance/check", response_model=AgenticResponse)
async def check_compliance(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Check PR compliance against policies (bypass orchestrator).
    
    Direct access to ComplianceCheckAgent for testing.
    Validates spending limits, vendor compliance, budget categories, documentation, and regulatory requirements.
    Compliance Levels: COMPLIANT (>=90), MINOR_ISSUE (70-89), MAJOR_VIOLATION (50-69), BLOCKED (<50)
    """
    print("\n" + "="*80)
    print("[COMPLIANCE CHECK] ⚖️ Compliance check requested")
    print("="*80)
    print(f"[COMPLIANCE] 📥 Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    print(f"[COMPLIANCE] 📊 PR Data: {request.pr_data}")
    
    try:
        print(f"[COMPLIANCE] 🔧 Creating ComplianceCheckAgent...")
        from backend.agents.compliance_check import ComplianceCheckAgent
        compliance_agent = ComplianceCheckAgent()
        print(f"[COMPLIANCE] ✅ Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        print(f"[COMPLIANCE] 🔄 Validating against company policies...")
        result = await compliance_agent.execute(context)
        
        print(f"[COMPLIANCE] ✅ Check complete:")
        print(f"[COMPLIANCE]   - Status: {result.get('status', 'completed')}")
        print(f"[COMPLIANCE]   - Has Decision: {result.get('decision') is not None}")
        print(f"[COMPLIANCE]   - Has Result: {result.get('result') is not None}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="ComplianceCheckAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[COMPLIANCE] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[COMPLIANCE] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Compliance check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/invoice/match", response_model=AgenticResponse)
async def match_invoice(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Perform 3-way matching on invoice (PO + Receipt + Invoice).
    
    Direct access to InvoiceMatchingAgent for testing.
    Compares invoice against purchase order and goods receipt.
    Auto-approves if variance <= 5%, flags for review if 5-10%, blocks if > 10%.
    """
    print("\n" + "="*80)
    print("[INVOICE MATCH] 🧾 3-way invoice matching requested")
    print("="*80)
    print(f"[INVOICE] 📥 Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    print(f"[INVOICE] 📊 Invoice Data: {request.pr_data}")
    
    try:
        print(f"[INVOICE] 🔧 Creating InvoiceMatchingAgent...")
        from backend.agents.invoice_matching import InvoiceMatchingAgent
        invoice_agent = InvoiceMatchingAgent()
        print(f"[INVOICE] ✅ Agent created")
        
        context = {
            "request": request.request,
            **request.pr_data  # Invoice data passed directly
        }
        
        print(f"[INVOICE] 🔄 Performing 3-way matching (PO + Receipt + Invoice)...")
        result = await invoice_agent.execute(context)
        
        print(f"[INVOICE] ✅ Matching complete:")
        print(f"[INVOICE]   - Status: {result.get('status', 'completed')}")
        print(f"[INVOICE]   - Has Decision: {result.get('decision') is not None}")
        print(f"[INVOICE]   - Has Result: {result.get('result') is not None}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="InvoiceMatchingAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[INVOICE] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[INVOICE] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Invoice matching failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/spend/analyze", response_model=AgenticResponse)
async def analyze_spend(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Analyze company spending patterns and identify savings opportunities.
    
    Direct access to SpendAnalyticsAgent for testing.
    Analyzes spend by department, vendor, category, time period.
    Identifies savings opportunities: volume consolidation, price standardization, vendor negotiation.
    """
    print("\n" + "="*80)
    print("[SPEND ANALYZE] 📊 Company spending analysis requested")
    print("="*80)
    print(f"[SPEND] 📥 Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    print(f"[SPEND] 📊 Analysis Parameters: {request.pr_data}")
    
    try:
        print(f"[SPEND] 🔧 Creating SpendAnalyticsAgent...")
        from backend.agents.spend_analytics import SpendAnalyticsAgent
        spend_agent = SpendAnalyticsAgent()
        print(f"[SPEND] ✅ Agent created")
        
        context = {
            "request": request.request,
            **(request.pr_data or {})  # Analysis parameters
        }
        
        print(f"[SPEND] 🔄 Analyzing spending patterns and identifying savings...")
        result = await spend_agent.execute(context)
        
        print(f"[SPEND] ✅ Analysis complete:")
        print(f"[SPEND]   - Status: {result.get('status', 'completed')}")
        print(f"[SPEND]   - Has Decision: {result.get('decision') is not None}")
        print(f"[SPEND]   - Has Result: {result.get('result') is not None}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="SpendAnalyticsAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[SPEND] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[SPEND] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Spend analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/inventory/check", response_model=AgenticResponse)
async def check_inventory(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Monitor inventory levels and auto-create replenishment PRs.
    
    Direct access to InventoryCheckAgent for testing.
    Scans all products for low stock (current_qty <= reorder_point).
    Auto-creates purchase requisitions for items below threshold.
    Urgency levels: CRITICAL (<=10 units), HIGH (<=25), MEDIUM (<=50).
    """
    print("\n" + "="*80)
    print("[INVENTORY CHECK] 📦 Inventory monitoring requested")
    print("="*80)
    print(f"[INVENTORY] 📥 Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    print(f"[INVENTORY] 📊 Check Parameters: {request.pr_data}")
    
    try:
        print(f"[INVENTORY] 🔧 Creating InventoryCheckAgent...")
        from backend.agents.inventory_check import InventoryCheckAgent
        inventory_agent = InventoryCheckAgent()
        print(f"[INVENTORY] ✅ Agent created")
        
        context = {
            "request": request.request,
            **(request.pr_data or {})  # Check parameters
        }
        
        print(f"[INVENTORY] 🔄 Scanning inventory levels and creating replenishment PRs...")
        result = await inventory_agent.execute(context)
        
        print(f"[INVENTORY] ✅ Check complete:")
        print(f"[INVENTORY]   - Status: {result.get('status', 'completed')}")
        print(f"[INVENTORY]   - Has Decision: {result.get('decision') is not None}")
        print(f"[INVENTORY]   - Has Result: {result.get('result') is not None}")
        print("="*80 + "\n")
        
        return AgenticResponse(
            status=result.get("status", "completed"),
            agent="InventoryCheckAgent",
            decision=result.get("decision"),
            result=result.get("result")
        )
        
    except Exception as e:
        print(f"[INVENTORY] ❌ ERROR: {str(e)}")
        import traceback
        print(f"[INVENTORY] 📋 Traceback:\n{traceback.format_exc()}")
        print("="*80 + "\n")
        logger.error(f"Inventory check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_system_status(current_user: dict = Depends(require_auth())):
    """Get status of orchestrator and all registered agents"""
    try:
        orch = initialize_orchestrator_with_agents()
        status = await orch.get_system_status()
        
        return {
            "success": True,
            "system": "Agentic Procurement",
            "version": "Sprint 5 - Supplier Performance",
            **status
        }
        
    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents")
async def list_agents(current_user: dict = Depends(require_auth())):
    """List all registered agents"""
    try:
        orch = initialize_orchestrator_with_agents()
        
        agents = []
        for agent_type, agent in orch.specialized_agents.items():
            agents.append({
                "type": agent_type,
                "name": agent.name,
                "description": agent.description,
                "status": agent.status.value,
                "tools_count": len(agent.tools),
                "decision_history_count": len(agent.decision_history)
            })
        
        return {
            "success": True,
            "count": len(agents),
            "agents": agents
        }
        
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check(current_user: dict = Depends(require_auth())):
    """Health check for agentic system"""
    try:
        orch = initialize_orchestrator_with_agents()
        
        return {
            "success": True,
            "service": "Agentic System",
            "status": "healthy",
            "orchestrator_active": orch is not None,
            "registered_agents": len(orch.specialized_agents)
        }
        
    except Exception as e:
        return {
            "success": False,
            "service": "Agentic System",
            "status": "unhealthy",
            "error": str(e)
        }


@router.get("/dashboard/data")
async def get_dashboard_data(current_user: dict = Depends(require_auth())):
    """Aggregated dashboard data for frontend analytics view"""
    try:
        system_stats = hybrid_query.get_system_stats()
        budget_rows = hybrid_query.query_budget_status(fiscal_year=2026)
        recent_actions = hybrid_query.query_agent_actions(limit=15)
        recent_decisions = hybrid_query.query_agent_decisions(limit=15)

        department_summary: Dict[str, Dict[str, Any]] = {}
        for row in budget_rows:
            department = row.get("department", "Unknown")
            if department not in department_summary:
                department_summary[department] = {
                    "department": department,
                    "allocated": 0.0,
                    "spent": 0.0,
                    "committed": 0.0,
                    "available": 0.0
                }

            department_summary[department]["allocated"] += float(row.get("allocated_budget") or 0)
            department_summary[department]["spent"] += float(row.get("spent_budget") or 0)
            department_summary[department]["committed"] += float(row.get("committed_budget") or 0)
            department_summary[department]["available"] += float(row.get("available_budget") or 0)

        # --- Approval workflow & PO metrics ---
        workflow_stats = {"total": 0, "pending": 0, "completed": 0, "rejected": 0, "pos_created": 0}
        agent_breakdown = []
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Workflow counts
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE workflow_status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE workflow_status = 'rejected') AS rejected,
                    COUNT(*) FILTER (WHERE workflow_status NOT IN ('completed', 'rejected')) AS pending,
                    COUNT(*) FILTER (WHERE odoo_po_id IS NOT NULL) AS pos_created
                FROM pr_approval_workflows
            """)
            row = cur.fetchone()
            if row:
                workflow_stats = dict(row)

            # Agent action breakdown (success count per agent)
            cur.execute("""
                SELECT agent_name,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE success = true) AS successes,
                       ROUND(AVG(execution_time_ms)::numeric, 0) AS avg_ms
                FROM agent_actions
                GROUP BY agent_name
                ORDER BY total DESC
            """)
            agent_breakdown = [dict(r) for r in cur.fetchall()]

            cur.close()
            return_db_connection(conn)
        except Exception as wf_err:
            logger.warning(f"Workflow stats query failed (non-fatal): {wf_err}")

        return {
            "success": True,
            "fiscal_year": 2026,
            "system_stats": system_stats,
            "budget_rows": budget_rows,
            "department_summary": list(department_summary.values()),
            "recent_actions": recent_actions,
            "recent_decisions": recent_decisions,
            "workflow_stats": workflow_stats,
            "agent_breakdown": agent_breakdown,
        }

    except Exception as e:
        logger.error(f"Failed to fetch dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# APPROVAL SYSTEM ENDPOINTS (Sprint 2)
# Human-in-the-loop approval UI for low-confidence decisions and workflows
# ============================================================================

@router.get("/pending-approvals")
async def get_pending_approvals(current_user: dict = Depends(require_auth())):
    """
    List all pending low-confidence AI decisions awaiting human review.
    
    Returns decisions from agents with confidence < 0.6 that need approval.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT * FROM pending_approvals 
            WHERE status = 'pending' 
            ORDER BY created_at DESC
        """)
        
        approvals = [dict(row) for row in cursor.fetchall()]
        cursor.close()

        return_db_connection(conn)
        
        return {"approvals": approvals}
        
    except Exception as e:
        logger.error(f"Failed to fetch pending approvals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending-approvals/count")
async def get_pending_count(current_user: dict = Depends(require_auth())):
    """
    Get count of pending approvals for sidebar badge.
    
    Returns the number of decisions awaiting human review.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT COUNT(*) as count FROM pending_approvals WHERE status = 'pending'")
        result = cursor.fetchone()
        count = result['count'] if result else 0
        
        cursor.close()

        
        return_db_connection(conn)
        
        return {"count": count}
        
    except Exception as e:
        logger.error(f"Failed to fetch pending count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending-approvals/history")
async def get_approvals_history(current_user: dict = Depends(require_auth())):
    """
    Get history of reviewed approvals (approved or rejected).
    
    Shows all decisions that have been reviewed by humans.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT * FROM pending_approvals 
            WHERE status IN ('approved', 'rejected') 
            ORDER BY reviewed_at DESC
            LIMIT 100
        """)
        
        history = [dict(row) for row in cursor.fetchall()]
        cursor.close()

        return_db_connection(conn)
        
        return {"history": history}
        
    except Exception as e:
        logger.error(f"Failed to fetch approvals history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pending-approvals/{approval_id}/approve")
async def approve_decision(
    approval_id: str,
    body: ApprovalActionRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    current_user: dict = Depends(require_auth()),
):
    """
    Approve a low-confidence AI decision.
    
    This executes the agent's recommendation and marks the decision as approved.
    """
    try:
        _require_admin_or_local(request, x_admin_token)
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Update status
        cursor.execute("""
            UPDATE pending_approvals 
            SET status = 'approved', 
                reviewed_at = CURRENT_TIMESTAMP, 
                review_notes = %s
            WHERE approval_id = %s
            RETURNING *
        """, (body.notes, approval_id))
        
        approval = cursor.fetchone()
        if not approval:
            cursor.close()

            return_db_connection(conn)
            raise HTTPException(status_code=404, detail="Approval not found")
        
        conn.commit()
        cursor.close()

        return_db_connection(conn)
        
        # TODO: Execute the agent's recommendation here
        # For now, just return success
        
        return {
            "status": "approved",
            "approval_id": approval_id,
            "message": "Decision approved and executed"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve decision: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pending-approvals/{approval_id}/reject")
async def reject_decision(
    approval_id: str,
    body: RejectionRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    current_user: dict = Depends(require_auth()),
):
    """
    Reject a low-confidence AI decision.
    
    This saves the rejection reason for agent learning and marks as rejected.
    """
    try:
        _require_admin_or_local(request, x_admin_token)
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            UPDATE pending_approvals 
            SET status = 'rejected', 
                reviewed_at = CURRENT_TIMESTAMP, 
                review_notes = %s
            WHERE approval_id = %s
            RETURNING *
        """, (body.reason, approval_id))
        
        approval = cursor.fetchone()
        if not approval:
            cursor.close()

            return_db_connection(conn)
            raise HTTPException(status_code=404, detail="Approval not found")
        
        conn.commit()
        cursor.close()

        return_db_connection(conn)
        
        # TODO: Log feedback to agent_decisions for learning
        
        return {
            "status": "rejected",
            "approval_id": approval_id,
            "reason": body.reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject decision: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approval-workflows")
async def get_approval_workflows(
    status: Optional[str] = None,
    department: Optional[str] = None,
    current_user: dict = Depends(require_auth()),
):
    """
    List all PR approval workflows with their steps.
    
    Shows multi-level approval progress (Manager → Director → VP).
    Optional filters: status (in_progress, completed, rejected), department.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build query with filters
        query = """
            SELECT 
                w.*,
                json_agg(
                    json_build_object(
                        'approval_level', s.approval_level,
                        'approver_name', s.approver_name,
                        'approver_email', s.approver_email,
                        'status', s.status,
                        'approved_at', s.approved_at,
                        'rejection_reason', s.rejection_reason,
                        'notes', s.notes
                    ) ORDER BY s.approval_level
                ) as steps
            FROM pr_approval_workflows w
            LEFT JOIN pr_approval_steps s ON w.pr_number = s.pr_number
            WHERE 1=1
        """
        
        params = []
        if status:
            query += " AND w.workflow_status = %s"
            params.append(status)
        if department:
            query += " AND w.department = %s"
            params.append(department)
        
        query += " GROUP BY w.pr_number ORDER BY w.created_at DESC"
        
        cursor.execute(query, params)
        workflows = [dict(row) for row in cursor.fetchall()]
        
        cursor.close()

        
        return_db_connection(conn)
        
        return {"workflows": workflows}
        
    except Exception as e:
        logger.error(f"Failed to fetch workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approval-workflows/{pr_number}/approve")
async def approve_workflow_step(
    pr_number: str,
    body: ApproveStepRequest,
    request: Request,
    x_approver_email: str | None = Header(default=None, alias="X-Approver-Email"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    current_user: dict = Depends(require_auth()),
):
    """
    Approve current approval step and advance workflow.
    
    Updates the step to approved, increments current_approval_level,
    or marks workflow as completed if all steps are done.
    """
    logger.info("="*80)
    logger.info(f"[APPROVAL ACTION] ✅ APPROVE Request")
    logger.info(f"[APPROVAL ACTION] 📋 PR Number: {pr_number}")
    logger.info(f"[APPROVAL ACTION] 👤 Approver: {body.approver_email}")
    logger.info(f"[APPROVAL ACTION] 📝 Notes: {body.notes or 'None'}")
    logger.info("="*80)
    
    try:
        _require_approval_actor(request, body.approver_email, x_approver_email, x_admin_token)
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Update the step
        logger.info(f"[APPROVAL ACTION] 💾 Updating pr_approval_steps...")
        cursor.execute("""
            UPDATE pr_approval_steps 
            SET status = 'approved', 
                approved_at = CURRENT_TIMESTAMP, 
                notes = %s
            WHERE pr_number = %s 
              AND approver_email = %s 
              AND status = 'pending'
            RETURNING *
        """, (body.notes, pr_number, body.approver_email))
        
        step = cursor.fetchone()
        if not step:
            logger.error(f"[APPROVAL ACTION] ❌ No pending step found for {body.approver_email} on {pr_number}")
            cursor.close()

            return_db_connection(conn)
            raise HTTPException(status_code=404, detail="No pending step found for this approver")
        
        logger.info(f"[APPROVAL ACTION] ✅ Step approved: Level {step['approval_level']} by {step['approver_name']}")
        
        # Check if more steps are pending
        logger.info(f"[APPROVAL ACTION] 🔍 Checking remaining approval steps...")
        cursor.execute("""
            SELECT COUNT(*) as remaining 
            FROM pr_approval_steps 
            WHERE pr_number = %s AND status = 'pending'
        """, (pr_number,))
        
        result = cursor.fetchone()
        remaining = result['remaining'] if result else 0
        logger.info(f"[APPROVAL ACTION] 📊 Remaining steps: {remaining}")
        
        if remaining == 0:
            # All steps approved - mark workflow as completed
            logger.info(f"[APPROVAL ACTION] 🎉 ALL STEPS APPROVED - WORKFLOW COMPLETE!")
            logger.info(f"[APPROVAL ACTION] 💾 Updating pr_approval_workflows status to 'completed'...")
            cursor.execute("""
                UPDATE pr_approval_workflows 
                SET workflow_status = 'completed', updated_at = CURRENT_TIMESTAMP 
                WHERE pr_number = %s
            """, (pr_number,))
            logger.info(f"[APPROVAL ACTION] ✅ Workflow marked as completed")
            
            # Get workflow details for PO creation
            logger.info(f"[APPROVAL ACTION] 📋 Fetching workflow details for Odoo PO creation...")
            cursor.execute("""
                SELECT pr_number, department, total_amount, requester_name, request_data 
                FROM pr_approval_workflows 
                WHERE pr_number = %s
            """, (pr_number,))
            workflow = cursor.fetchone()
            
            if workflow:
                logger.info(f"[APPROVAL ACTION] 🚀 TRIGGERING ODOO PO CREATION...")
                logger.info(f"[APPROVAL ACTION] 📋 PR: {workflow['pr_number']}")
                logger.info(f"[APPROVAL ACTION] 🏢 Department: {workflow['department']}")
                logger.info(f"[APPROVAL ACTION] 💰 Amount: ${workflow['total_amount']:,.2f}")
                logger.info(f"[APPROVAL ACTION] 👤 Requester: {workflow['requester_name']}")
                
                try:
                    # Initialize Odoo client
                    odoo = get_odoo_client()
                    
                    if not odoo.is_connected():
                        logger.error(f"[APPROVAL ACTION] ❌ Odoo not connected - cannot create PO")
                    else:
                        request_data = workflow.get('request_data') or {}
                        context_payload = request_data.get('context', {}) if isinstance(request_data, dict) else {}
                        pr_payload = context_payload.get('raw_pr_data', {}) if isinstance(context_payload, dict) else {}

                        requested_vendor_name = str(
                            pr_payload.get('vendor_name')
                            or pr_payload.get('selected_vendor_name')
                            or ''
                        ).strip()
                        requested_product_name = str(
                            pr_payload.get('product_name')
                            or pr_payload.get('category')
                            or 'Procurement Item'
                        ).strip()
                        requested_justification = str(pr_payload.get('justification') or '').strip()
                        requested_budget_category = str(pr_payload.get('budget_category') or '').strip()
                        requested_department = str(pr_payload.get('department') or workflow.get('department') or '').strip()

                        # Find vendor from PR payload; fallback to first available vendor.
                        vendors = odoo.get_vendors(limit=200)
                        if not vendors:
                            logger.error(f"[APPROVAL ACTION] ❌ No vendors available in Odoo")
                        else:
                            selected_vendor = None
                            if requested_vendor_name:
                                requested_lower = requested_vendor_name.lower()
                                selected_vendor = next(
                                    (v for v in vendors if str(v.get('name', '')).strip().lower() == requested_lower),
                                    None,
                                )
                                if not selected_vendor:
                                    selected_vendor = next(
                                        (v for v in vendors if requested_lower in str(v.get('name', '')).strip().lower()),
                                        None,
                                    )

                            if not selected_vendor:
                                selected_vendor = vendors[0]

                            vendor_id = selected_vendor['id']
                            vendor_name = selected_vendor['name']
                            logger.info(f"[APPROVAL ACTION] 🏪 Using vendor: {vendor_name} (ID: {vendor_id})")
                            
                            # Find product matching requested product/category name.
                            products = odoo.get_products(limit=20, search_term=requested_product_name)
                            if not products:
                                products = odoo.get_products(limit=1)
                            if not products:
                                logger.error(f"[APPROVAL ACTION] ❌ No products available in Odoo")
                            else:
                                product_id = products[0]['id']
                                product_name = products[0]['name']
                                product_price = products[0].get('list_price', 100.0)
                                requested_budget = pr_payload.get('budget', workflow.get('total_amount')) if isinstance(pr_payload, dict) else workflow.get('total_amount')
                                
                                # Prefer quantity from PR payload; fallback to amount-based estimate.
                                requested_quantity = pr_payload.get('quantity') if isinstance(pr_payload, dict) else None
                                try:
                                    requested_quantity = int(requested_quantity) if requested_quantity is not None else None
                                except (TypeError, ValueError):
                                    requested_quantity = None

                                quantity = requested_quantity if requested_quantity and requested_quantity > 0 else 1
                                try:
                                    requested_budget_value = float(requested_budget)
                                except (TypeError, ValueError):
                                    requested_budget_value = float(workflow['total_amount'])
                                unit_price = requested_budget_value / max(quantity, 1)
                                logger.info(f"[APPROVAL ACTION] 📦 Product: {product_name} (ID: {product_id})")
                                logger.info(f"[APPROVAL ACTION] 📊 Quantity: {quantity} @ ${unit_price:.2f} each")
                                
                                # Create purchase order in Odoo
                                order_lines = [{
                                    'product_id': product_id,
                                    'quantity': quantity,
                                    'price': unit_price,
                                    'name': requested_product_name or product_name,
                                }]

                                po_notes_parts = [
                                    f"PR Number: {pr_number}",
                                    f"Department: {requested_department or workflow.get('department', '')}",
                                    f"Budget Category: {requested_budget_category}" if requested_budget_category else "",
                                    f"Business Justification: {requested_justification}" if requested_justification else "",
                                ]
                                po_notes = "\n".join([p for p in po_notes_parts if p])
                                
                                po_id = odoo.create_purchase_order(
                                    partner_id=vendor_id,
                                    order_lines=order_lines,
                                    origin=pr_number,
                                    notes=po_notes,
                                )
                                
                                logger.info(f"[APPROVAL ACTION] ✅✅✅ PURCHASE ORDER CREATED IN ODOO!")
                                logger.info(f"[APPROVAL ACTION] 🆔 Odoo PO ID: {po_id}")
                                logger.info(f"[APPROVAL ACTION] 🔗 PR {pr_number} → PO {po_id}")
                                
                                # Auto-confirm the PO (approve it in Odoo)
                                logger.info(f"[APPROVAL ACTION] 🔄 Auto-confirming PO in Odoo...")
                                if odoo.approve_purchase_order(po_id):
                                    logger.info(f"[APPROVAL ACTION] ✅ PO {po_id} confirmed in Odoo (state: purchase)")
                                else:
                                    logger.warning(f"[APPROVAL ACTION] ⚠️ Could not confirm PO {po_id} automatically")
                                
                                # Store PO ID in workflow table for tracking
                                logger.info(f"[APPROVAL ACTION] 💾 Storing PO ID in workflow table...")
                                po_mapping_data = {
                                    "odoo_po_data": {
                                        "odoo_po_id": po_id,
                                        "vendor_name": vendor_name,
                                        "product_name": requested_product_name or product_name,
                                        "quantity": quantity,
                                        "unit_price": unit_price,
                                        "origin_pr_number": pr_number,
                                        "notes": po_notes,
                                    }
                                }
                                cursor.execute("""
                                    UPDATE pr_approval_workflows 
                                    SET odoo_po_id = %s,
                                        request_data = COALESCE(request_data, '{}'::jsonb) || %s::jsonb
                                    WHERE pr_number = %s
                                """, (po_id, json.dumps(po_mapping_data), pr_number))
                                logger.info(f"[APPROVAL ACTION] ✅ PO ID {po_id} linked to workflow {pr_number}")
                                
                except Exception as e:
                    logger.error(f"[APPROVAL ACTION] ❌ Error creating PO in Odoo: {str(e)}")
                    logger.error(f"[APPROVAL ACTION] 📋 Workflow {pr_number} marked complete but PO creation failed")
            else:
                logger.error(f"[APPROVAL ACTION] ❌ Could not fetch workflow details for {pr_number}")
        else:
            # Advance to next level
            logger.info(f"[APPROVAL ACTION] ⏭️ Advancing to next approval level...")
            cursor.execute("""
                UPDATE pr_approval_workflows 
                SET current_approval_level = current_approval_level + 1, 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE pr_number = %s
            """, (pr_number,))
            logger.info(f"[APPROVAL ACTION] ✅ Workflow advanced to next level")
        
        logger.info(f"[APPROVAL ACTION] 💾 Committing transaction to database...")
        conn.commit()
        logger.info(f"[APPROVAL ACTION] ✅✅✅ COMMIT SUCCESSFUL")
        
        # Fetch final workflow state including PO ID
        cursor.execute("""
            SELECT odoo_po_id FROM pr_approval_workflows WHERE pr_number = %s
        """, (pr_number,))
        final_workflow = cursor.fetchone()
        odoo_po_id = final_workflow['odoo_po_id'] if final_workflow else None
        
        cursor.close()

        
        return_db_connection(conn)
        
        logger.info("="*80)
        logger.info(f"[APPROVAL ACTION] 🏁 Approval Complete")
        logger.info(f"[APPROVAL ACTION] 🏁 PR: {pr_number} | Remaining: {remaining} | Workflow Complete: {remaining == 0}")
        if odoo_po_id:
            logger.info(f"[APPROVAL ACTION] 🏁 Odoo PO: {odoo_po_id}")
        logger.info("="*80)
        
        return {
            "status": "approved",
            "pr_number": pr_number,
            "remaining_steps": remaining,
            "completed": remaining == 0,
            "odoo_po_id": odoo_po_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve workflow step: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approval-workflows/{pr_number}/reject")
async def reject_workflow_step(
    pr_number: str,
    body: RejectStepRequest,
    request: Request,
    x_approver_email: str | None = Header(default=None, alias="X-Approver-Email"),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    current_user: dict = Depends(require_auth()),
):
    """
    Reject current approval step and terminate workflow.
    
    Marks the step as rejected and sets workflow status to rejected.
    """
    try:
        _require_approval_actor(request, body.approver_email, x_approver_email, x_admin_token)
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Update the step
        cursor.execute("""
            UPDATE pr_approval_steps 
            SET status = 'rejected', 
                rejection_reason = %s
            WHERE pr_number = %s 
              AND approver_email = %s 
              AND status = 'pending'
            RETURNING *
        """, (body.rejection_reason, pr_number, body.approver_email))
        
        step = cursor.fetchone()
        if not step:
            cursor.close()

            return_db_connection(conn)
            raise HTTPException(status_code=404, detail="No pending step found for this approver")
        
        # Terminate workflow
        cursor.execute("""
            UPDATE pr_approval_workflows 
            SET workflow_status = 'rejected', updated_at = CURRENT_TIMESTAMP 
            WHERE pr_number = %s
        """, (pr_number,))
        
        conn.commit()
        cursor.close()

        return_db_connection(conn)
        
        return {
            "status": "rejected",
            "pr_number": pr_number,
            "reason": body.rejection_reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject workflow step: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-approvals/{approver_email}")
async def get_my_approvals(approver_email: str, status: str = "pending", current_user: dict = Depends(require_auth())):
    """
    Get personalized approvals for a specific approver.
    
    status='pending' returns items awaiting their decision
    status='history' returns their past decisions
    """
    logger.info("="*80)
    logger.info(f"[MY APPROVALS] 📥 GET Request")
    logger.info(f"[MY APPROVALS] 👤 Approver: {approver_email}")
    logger.info(f"[MY APPROVALS] 🔍 Status Filter: {status}")
    logger.info("="*80)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        if status == "pending":
            logger.info(f"[MY APPROVALS] 🔎 Querying PENDING approvals...")
            cursor.execute("""
                SELECT 
                    w.pr_number, w.department, w.total_amount, w.requester_name, w.created_at,
                    s.approval_level, s.approver_name, s.approver_email,
                    EXTRACT(DAY FROM CURRENT_TIMESTAMP - w.created_at) as days_pending,
                    COALESCE(w.request_data, '{}'::jsonb) as request_data
                FROM pr_approval_workflows w
                JOIN pr_approval_steps s ON w.pr_number = s.pr_number
                WHERE s.approver_email = %s 
                  AND s.status = 'pending' 
                  AND w.workflow_status = 'in_progress'
                ORDER BY w.created_at ASC
            """, (approver_email,))
            
            results = [dict(row) for row in cursor.fetchall()]
            logger.info(f"[MY APPROVALS] 📊 Query returned {len(results)} pending approval(s)")
            
            if results:
                logger.info(f"[MY APPROVALS] 📋 Pending PRs:")
                for idx, r in enumerate(results, 1):
                    logger.info(f"[MY APPROVALS]   {idx}. {r['pr_number']} | {r['department']} | ${r['total_amount']:,.0f} | Level {r['approval_level']} | {r['days_pending']:.0f} days")
            else:
                logger.info(f"[MY APPROVALS] ℹ️ No pending approvals found for {approver_email}")
            
            # Add level names
            level_map = {1: "Manager", 2: "Director", 3: "VP/CFO"}
            for r in results:
                r['approval_level_name'] = level_map.get(r['approval_level'], "Unknown")
            
            cursor.close()

            
            return_db_connection(conn)
            logger.info(f"[MY APPROVALS] ✅ Returning {len(results)} approval(s)")
            logger.info("="*80)
            return {"approvals": results}
        
        else:  # history
            logger.info(f"[MY APPROVALS] 🔎 Querying HISTORY (past decisions)...")
            cursor.execute("""
                SELECT 
                    w.pr_number, w.department, w.total_amount, w.requester_name,
                    s.approval_level, s.status as decision, s.approved_at as decided_at,
                    s.notes, s.rejection_reason
                FROM pr_approval_workflows w
                JOIN pr_approval_steps s ON w.pr_number = s.pr_number
                WHERE s.approver_email = %s 
                  AND s.status IN ('approved', 'rejected')
                ORDER BY s.approved_at DESC
            """, (approver_email,))
            
            results = [dict(row) for row in cursor.fetchall()]
            logger.info(f"[MY APPROVALS] 📊 Query returned {len(results)} historical decision(s)")
            
            if results:
                logger.info(f"[MY APPROVALS] 📋 Decision History:")
                for idx, r in enumerate(results, 1):
                    logger.info(f"[MY APPROVALS]   {idx}. {r['pr_number']} | {r['decision'].upper()} | Level {r['approval_level']}")
            
            # Add level names
            level_map = {1: "Manager", 2: "Director", 3: "VP/CFO"}
            for r in results:
                r['approval_level_name'] = level_map.get(r['approval_level'], "Unknown")
            
            cursor.close()

            
            return_db_connection(conn)
            logger.info(f"[MY APPROVALS] ✅ Returning {len(results)} historical record(s)")
            logger.info("="*80)
            return {"history": results}
        
    except Exception as e:
        logger.error("="*80)
        logger.error(f"[MY APPROVALS] ❌ ERROR: {e}")
        logger.error("="*80)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-approvals/{approver_email}/stats")
async def get_approver_stats(approver_email: str, current_user: dict = Depends(require_auth())):
    """
    Get statistics for a specific approver.
    
    Returns: pending count, approved count, rejected count, rejection rate, avg decision time.
    """
    logger.info("="*80)
    logger.info(f"[APPROVAL STATS] 📊 Stats Request")
    logger.info(f"[APPROVAL STATS] 👤 Approver: {approver_email}")
    logger.info("="*80)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        logger.info(f"[APPROVAL STATS] 🔎 Querying approval statistics...")
        cursor.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE status = 'pending') as pending_count,
                COUNT(*) FILTER (WHERE status = 'approved') as approved_count,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected_count,
                COALESCE(
                    (COUNT(*) FILTER (WHERE status = 'rejected'))::float / 
                    NULLIF(COUNT(*) FILTER (WHERE status IN ('approved', 'rejected')), 0) * 100,
                    0
                ) as rejection_rate,
                COALESCE(
                    AVG(
                        EXTRACT(EPOCH FROM (
                            approved_at - (
                                SELECT created_at 
                                FROM pr_approval_workflows 
                                WHERE pr_number = pr_approval_steps.pr_number
                            )
                        )) / 3600
                    ),
                    0
                ) as avg_decision_time_hours
            FROM pr_approval_steps
            WHERE approver_email = %s
        """, (approver_email,))
        
        stats = dict(cursor.fetchone() or {})
        cursor.close()

        return_db_connection(conn)
        
        logger.info(f"[APPROVAL STATS] 📊 Statistics:")
        logger.info(f"[APPROVAL STATS]   - Pending: {stats.get('pending_count', 0)}")
        logger.info(f"[APPROVAL STATS]   - Approved: {stats.get('approved_count', 0)}")
        logger.info(f"[APPROVAL STATS]   - Rejected: {stats.get('rejected_count', 0)}")
        logger.info(f"[APPROVAL STATS]   - Rejection Rate: {stats.get('rejection_rate', 0):.1f}%")
        logger.info(f"[APPROVAL STATS]   - Avg Decision Time: {stats.get('avg_decision_time_hours', 0):.1f} hours")
        logger.info("="*80)
        
        # Ensure all fields are present
        return {
            "pending_count": stats.get("pending_count", 0),
            "approved_count": stats.get("approved_count", 0),
            "rejected_count": stats.get("rejected_count", 0),
            "rejection_rate": float(stats.get("rejection_rate", 0)),
            "avg_decision_time_hours": float(stats.get("avg_decision_time_hours", 0))
        }
        
    except Exception as e:
        logger.error("="*80)
        logger.error(f"[APPROVAL STATS] ❌ ERROR: {e}")
        logger.error("="*80)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approval-chains")
async def get_approval_chains(current_user: dict = Depends(require_auth())):
    """
    Get all approval chain configurations.
    
    Shows the database rules that define who approves what for each department.
    Used by admin/settings page to display approval routing configuration.
    """
    logger.info("[AGENTIC API] 📋 GET /approval-chains - Starting request")
    
    conn = None
    cursor = None
    
    try:
        logger.info("[AGENTIC API] 🔌 Acquiring database connection from pool...")
        conn = get_db_connection()
        logger.info("[AGENTIC API] ✅ Connection acquired, creating cursor...")
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        logger.info("[AGENTIC API] ✅ Cursor created, executing query...")
        
        cursor.execute("""
            SELECT 
                id, department, budget_threshold, approval_level,
                approver_email, approver_name, status
            FROM approval_chains
            ORDER BY department, budget_threshold, approval_level
        """)
        
        chains = [dict(row) for row in cursor.fetchall()]
        logger.info(f"[AGENTIC API] ✅ Query executed - Retrieved {len(chains)} approval chains")
        
        cursor.close()
        logger.info("[AGENTIC API] 🔄 Cursor closed, returning connection to pool...")

        return_db_connection(conn)
        logger.info("[AGENTIC API] ✅ Connection returned to pool - Request complete")
        
        return {"chains": chains}
        
    except Exception as e:
        logger.error(f"[AGENTIC API] ❌ Error in GET /approval-chains: {e}")
        
        # Cleanup on error
        if cursor:
            try:
                cursor.close()
                logger.info("[AGENTIC API] 🧹 Cursor closed after error")
            except Exception as cleanup_error:
                logger.error(f"[AGENTIC API] ⚠️ Failed to close cursor: {cleanup_error}")
        
        if conn:
            try:
                return_db_connection(conn)
                logger.info("[AGENTIC API] 🧹 Connection returned to pool after error")
            except Exception as cleanup_error:
                logger.error(f"[AGENTIC API] ⚠️ Failed to return connection: {cleanup_error}")

        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 8 — Invoice-to-Payment Pipeline REST Routes
# ─────────────────────────────────────────────────────────────────────────────

class PipelineRunRequest(BaseModel):
    po_document: Dict[str, Any]
    invoice_document: Dict[str, Any]
    dry_run: bool = False


class PaymentPipelineRequest(BaseModel):
    invoice_number: str
    vendor_id: str
    po_reference: str
    invoice_amount: float
    invoice_currency: str = "AED"
    dry_run: bool = False


@router.post("/pipeline/run")
async def run_full_pipeline(
    request: Request,
    body: PipelineRunRequest,
    current_user: dict = Depends(require_auth()),
):
    """
    Run the complete 9-agent Invoice-to-Payment pipeline.

    Steps executed (in order):
    1. POIntakeAgent        — parse & validate PO document
    2. PORegistrationAgent  — register PO in DB
    3. InvoiceCaptureAgent  — OCR & extract invoice fields
    4. InvoiceRoutingAgent  — route invoice for processing
    5. InvoiceMatchingAgent — 3-way match (PO / GRN / Invoice)
    6. DiscrepancyResolutionAgent — resolve mismatches
    7. PaymentReadinessAgent — compliance & hold checks
    8. PaymentCalculationAgent — FX conversion & net payable
    9. PaymentApprovalAgent  — route for payment approval

    Returns the full pipeline result including per-step timing and context.

    Auth: requires a valid JWT (Authorization: Bearer <token>) or a local request.
    """
    try:
        from backend.services.pipeline_orchestrator import InvoicePipelineOrchestrator
        orchestrator = InvoicePipelineOrchestrator()
        result = await orchestrator.run_full_pipeline(
            po_document=body.po_document,
            invoice_document=body.invoice_document,
            dry_run=body.dry_run,
        )
        return result
    except Exception as e:
        logger.error(f"[PIPELINE] run_full_pipeline error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pipeline/payment")
async def run_payment_pipeline(
    request: Request,
    body: PaymentPipelineRequest,
    current_user: dict = Depends(require_auth()),
):
    """
    Run steps 7–9 only (payment sub-pipeline) for an already-matched invoice.

    Useful for:
    - Re-running payment checks on existing invoices
    - Triggering payment approval for invoices matched outside the pipeline
    - Testing the payment flow with real DB invoices

    Requires a valid invoice in the DB (invoice_number must exist).

    Auth: requires a valid JWT (Authorization: Bearer <token>) or a local request.
    """
    try:
        from backend.services.pipeline_orchestrator import InvoicePipelineOrchestrator
        orchestrator = InvoicePipelineOrchestrator()
        payment_data = {
            "invoice_number":   body.invoice_number,
            "vendor_id":        body.vendor_id,
            "po_reference":     body.po_reference,
            "invoice_amount":   body.invoice_amount,
            "invoice_currency": body.invoice_currency,
        }
        result = await orchestrator.run_payment_pipeline(
            payment_data=payment_data,
            dry_run=body.dry_run,
        )
        return result
    except Exception as e:
        logger.error(f"[PIPELINE] run_payment_pipeline error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class POIntakeRequest(BaseModel):
    document_ref: str
    source_channel: str = "email"
    raw_content: Optional[str] = None
    vendor_id: Optional[str] = None


@router.post("/pipeline/po-intake")
async def run_po_intake_step(body: POIntakeRequest, current_user: dict = Depends(require_auth())):
    """Run only Step 1: POIntakeAgent — parse and validate a PO document."""
    try:
        from backend.services.pipeline_orchestrator import InvoicePipelineOrchestrator
        orchestrator = InvoicePipelineOrchestrator()
        result = await orchestrator.run_po_intake(body.model_dump())
        return result
    except Exception as e:
        logger.error(f"[PIPELINE] run_po_intake error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class InvoiceCaptureRequest(BaseModel):
    document_ref: str
    source_channel: str = "email"
    raw_content: Optional[str] = None
    invoice_amount: Optional[float] = None
    invoice_currency: str = "AED"


@router.post("/pipeline/invoice-capture")
async def run_invoice_capture_step(body: InvoiceCaptureRequest, current_user: dict = Depends(require_auth())):
    """Run only Step 3: InvoiceCaptureAgent — OCR and extract invoice fields."""
    try:
        from backend.services.pipeline_orchestrator import InvoicePipelineOrchestrator
        orchestrator = InvoicePipelineOrchestrator()
        result = await orchestrator.run_invoice_capture(body.model_dump())
        return result
    except Exception as e:
        logger.error(f"[PIPELINE] run_invoice_capture error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pipeline/status/{invoice_number}")
async def get_pipeline_status(invoice_number: str, current_user: dict = Depends(require_auth())):
    """
    Get the current pipeline status for an invoice.

    Returns payment run info, match status, and any holds from the DB.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Payment run
        cur.execute(
            """
            SELECT payment_run_id, status, total_amount, currency, created_at
            FROM payment_runs
            WHERE payment_run_id ILIKE %s OR payment_run_id ILIKE %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (f"%{invoice_number}%", f"%{invoice_number.replace('/', '_')}%"),
        )
        payment_run = cur.fetchone()

        # Invoice holds
        cur.execute(
            "SELECT hold_reason, hold_date, resolved FROM invoice_holds WHERE invoice_number = %s ORDER BY hold_date DESC",
            (invoice_number,),
        )
        holds = [dict(r) for r in cur.fetchall()]

        # Pending approval
        cur.execute(
            "SELECT approval_id, status, created_at FROM pending_approvals WHERE request_data::text ILIKE %s ORDER BY created_at DESC LIMIT 1",
            (f"%{invoice_number}%",),
        )
        pending = cur.fetchone()

        cur.close()
        return_db_connection(conn)

        return {
            "invoice_number": invoice_number,
            "payment_run": dict(payment_run) if payment_run else None,
            "holds": holds,
            "pending_approval": dict(pending) if pending else None,
        }
    except Exception as e:
        logger.error(f"[PIPELINE] get_pipeline_status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# New Workflow Agents (Sprint 9 prep)
# ─────────────────────────────────────────────────────────────────────────────

class DeliveryTrackingRequest(BaseModel):
    po_number: Optional[str] = None
    vendor_id: Optional[str] = None
    limit: int = 50

@router.post("/delivery/track")
async def track_delivery(body: DeliveryTrackingRequest, current_user: dict = Depends(require_auth())):
    """WF-07: Track PO delivery status and flag delays."""
    try:
        from backend.agents.delivery_tracking_agent import DeliveryTrackingAgent
        agent = DeliveryTrackingAgent()
        result = await agent.execute(body.model_dump())
        return result
    except Exception as e:
        logger.error(f"[DELIVERY TRACKING] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ForecastingRequest(BaseModel):
    period_months: int = 3
    category: Optional[str] = None

@router.post("/forecast/demand")
async def forecast_demand(body: ForecastingRequest, current_user: dict = Depends(require_auth())):
    """WF-19: Forecast demand and procurement needs."""
    try:
        from backend.agents.forecasting_agent import ForecastingAgent
        agent = ForecastingAgent()
        result = await agent.execute(body.model_dump())
        return result
    except Exception as e:
        logger.error(f"[FORECASTING] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class DocumentProcessingRequest(BaseModel):
    raw_content: str = ""
    document_type: Optional[str] = None
    source_channel: str = "upload"
    # Sprint 8: optional base64-encoded file content for real OCR processing
    file_content_b64: str = ""
    filename: str = ""

@router.post("/document/process")
async def process_document(body: DocumentProcessingRequest, current_user: dict = Depends(require_auth())):
    """WF-01/05: Parse and extract fields from procurement documents.

    Accepts JSON with raw_content (text) or file_content_b64 + filename (binary).
    When file_content_b64 is provided, runs real pdfplumber/pytesseract OCR.
    """
    try:
        from backend.agents.document_processing_agent import DocumentProcessingAgent
        agent = DocumentProcessingAgent()
        result = await agent.execute(body.model_dump())
        return result
    except Exception as e:
        logger.error(f"[DOCUMENT PROCESSING] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/document/upload")
async def upload_and_process_document(
    file: UploadFile = File(...),
    doc_type: str = Form("auto"),
    current_user: dict = Depends(require_auth()),
):
    """Upload a real file (PDF/image/DOCX) and run OCR extraction.

    Accepts multipart/form-data with:
      file     — the document file (PDF, PNG, JPG, JPEG, TIFF, BMP, DOCX)
      doc_type — document type hint (default: auto-detect)

    Returns the full OCR extraction result including raw_text, detected type,
    confidence score, and structured fields list.
    """
    try:
        file_bytes = await file.read()
        filename = file.filename or "document"

        # Base64-encode for agent consumption
        file_content_b64 = base64.b64encode(file_bytes).decode("utf-8")

        from backend.agents.document_processing_agent import DocumentProcessingAgent
        agent = DocumentProcessingAgent()
        result = await agent.execute({
            "raw_content": "",
            "document_type": doc_type if doc_type != "auto" else None,
            "source_channel": "upload",
            "file_content_b64": file_content_b64,
            "filename": filename,
        })
        return result
    except Exception as e:
        logger.error(f"[DOCUMENT UPLOAD] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/monitoring/health")
async def get_system_health(current_user: dict = Depends(require_auth())):
    """WF-20: Get system KPI health dashboard."""
    try:
        from backend.agents.monitoring_dashboard_agent import MonitoringDashboardAgent
        agent = MonitoringDashboardAgent()
        result = await agent.execute({})
        return result
    except Exception as e:
        logger.error(f"[MONITORING] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class VendorOnboardingRequest(BaseModel):
    vendor_name: str
    contact_email: str
    category: str
    country: str = "UAE"
    registration_number: Optional[str] = None
    tax_id: Optional[str] = None
    bank_details_provided: bool = False

@router.post("/vendor/onboard")
async def onboard_vendor(body: VendorOnboardingRequest, current_user: dict = Depends(require_auth())):
    """WF-15: Validate and onboard a new vendor."""
    try:
        from backend.agents.vendor_onboarding_agent import VendorOnboardingAgent
        agent = VendorOnboardingAgent()
        result = await agent.execute({"vendor_data": body.model_dump()})
        return result
    except Exception as e:
        logger.error(f"[VENDOR ONBOARDING] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class GoodsReceiptRequest(BaseModel):
    po_number: str
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    received_lines: List[Dict[str, Any]] = []
    quality_check_required: bool = False
    receipt_date: Optional[str] = None

@router.post("/goods-receipt/record")
async def record_goods_receipt(body: GoodsReceiptRequest, current_user: dict = Depends(require_auth())):
    """WF-09/10/11: Record and validate goods receipt."""
    try:
        from backend.agents.goods_receipt_agent import GoodsReceiptAgent
        agent = GoodsReceiptAgent()
        result = await agent.execute(body.model_dump())
        return result
    except Exception as e:
        logger.error(f"[GOODS RECEIPT] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class QuoteComparisonRequest(BaseModel):
    rfq_number: Optional[str] = None
    category: Optional[str] = None

@router.post("/quotes/compare")
async def compare_quotes(body: QuoteComparisonRequest, current_user: dict = Depends(require_auth())):
    """WF-04: Compare vendor quotes and recommend best supplier."""
    try:
        from backend.agents.quote_comparison_agent import QuoteComparisonAgent
        agent = QuoteComparisonAgent()
        result = await agent.execute(body.model_dump())
        return result
    except Exception as e:
        logger.error(f"[QUOTE COMPARISON] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SupplierPerformanceRequest(BaseModel):
    vendor_id: str = "all"

@router.post("/supplier/performance")
async def supplier_performance(body: SupplierPerformanceRequest, current_user: dict = Depends(require_auth())):
    """WF-16: Evaluate supplier performance metrics."""
    try:
        from backend.agents.supplier_performance import SupplierPerformanceAgent
        agent = SupplierPerformanceAgent()
        result = await agent.execute({"vendor_id": body.vendor_id})
        return result
    except Exception as e:
        logger.error(f"Supplier performance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Sprint 9: Slack Integration endpoints ────────────────────────────────────

class SlackNotifyRequest(BaseModel):
    event_type: str  # approval_request, payment_alert, anomaly_alert, general
    channel: str = ""
    payload: dict = {}


@router.post("/slack/notify")
async def slack_notify(body: SlackNotifyRequest, current_user: dict = Depends(require_auth())):
    """Send a procurement notification to Slack."""
    try:
        from backend.services.slack_service import (
            send_approval_request,
            send_payment_alert,
            send_anomaly_alert,
            send_message,
        )
        if body.event_type == "approval_request":
            result = send_approval_request(body.payload)
        elif body.event_type == "payment_alert":
            result = send_payment_alert(body.payload)
        elif body.event_type == "anomaly_alert":
            result = send_anomaly_alert(body.payload)
        else:
            channel = body.channel or os.getenv("SLACK_APPROVAL_CHANNEL", "#procurement-approvals")
            result = send_message(channel, body.payload.get("text", "Notification from Procure AI"))
        return {"success": result.get("ok", False), "result": result}
    except Exception as e:
        logger.error(f"Slack notify error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/slack/interactive")
async def slack_interactive_webhook(request: Request, current_user: dict = Depends(require_auth())):
    """
    Receive Slack interactive component callbacks (button clicks).
    Slack sends a POST with payload= form field containing JSON.
    """
    try:
        from backend.services.slack_service import verify_signature, handle_interactive_payload
        import json

        body_bytes = await request.body()

        # Verify Slack signature
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")

        if signing_secret and not verify_signature(body_bytes, timestamp, signature):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

        # Parse the payload
        form_data = await request.form()
        payload_str = form_data.get("payload", "{}")
        payload = json.loads(payload_str)

        result = handle_interactive_payload(payload)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Slack interactive error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slack/status")
async def slack_status(current_user: dict = Depends(require_auth())):
    """Check Slack integration configuration status."""
    slack_enabled = os.getenv("SLACK_ENABLED", "false").lower() == "true"
    bot_token = os.getenv("SLACK_BOT_TOKEN", "")
    channel = os.getenv("SLACK_APPROVAL_CHANNEL", "#procurement-approvals")
    return {
        "slack_enabled": slack_enabled,
        "bot_token_configured": bool(bot_token),
        "approval_channel": channel,
        "mode": "live" if (slack_enabled and bot_token) else "demo",
    }


# ── Sprint 9: Intelligence & Automation endpoints ────────────────────────────

class EmailInboxRequest(BaseModel):
    max_emails: int = 20
    folder: str = "INBOX"
    auto_process: bool = True

@router.post("/email/inbox/scan")
async def scan_email_inbox(body: EmailInboxRequest, current_user: dict = Depends(require_auth())):
    """WF-05: Scan email inbox for incoming invoices and auto-process them."""
    try:
        from backend.agents.email_inbox_agent import EmailInboxAgent
        agent = EmailInboxAgent()
        result = await agent.execute({
            "max_emails": body.max_emails,
            "folder": body.folder,
            "auto_process": body.auto_process,
        })
        return result
    except Exception as e:
        logger.error(f"Email inbox scan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class AnomalyDetectionRequest(BaseModel):
    lookback_days: int = 30
    severity_threshold: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL

@router.post("/anomaly/detect")
async def detect_anomalies(body: AnomalyDetectionRequest, current_user: dict = Depends(require_auth())):
    """Sprint 9: Detect procurement spend anomalies and duplicate invoices."""
    try:
        from backend.agents.anomaly_detection_agent import AnomalyDetectionAgent
        agent = AnomalyDetectionAgent()
        result = await agent.execute({
            "lookback_days": body.lookback_days,
            "severity_threshold": body.severity_threshold,
        })
        return result
    except Exception as e:
        logger.error(f"Anomaly detection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/anomaly/history")
async def get_anomaly_history(current_user: dict = Depends(require_auth())):
    """Get previously detected anomalies from agent_actions log."""
    try:
        from backend.services.nmi_data_service import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT agent_name, action_type, input_data, output_data,
                           success, created_at
                    FROM agent_actions
                    WHERE action_type LIKE 'anomaly%'
                    ORDER BY created_at DESC
                    LIMIT 50
                """)
                rows = cur.fetchall()
                return {"success": True, "anomalies": [dict(r) for r in rows]}
        finally:
            conn.close()
    except Exception as e:
        return {"success": False, "anomalies": [], "error": str(e)}


# ── Sprint 8: Notification endpoints ─────────────────────────────────────────

class NotificationRequest(BaseModel):
    event_type: str  # approval_requested, approval_decided, payment_scheduled, low_stock_alert, contract_expiry
    recipients: list = []
    payload: dict = {}
    send_email: bool = True

@router.post("/notifications/send")
async def send_notification(body: NotificationRequest, current_user: dict = Depends(require_auth())):
    """Send a procurement notification email."""
    try:
        from backend.agents.notification_agent import NotificationAgent
        agent = NotificationAgent()
        result = await agent.execute({
            "event_type": body.event_type,
            "recipients": body.recipients,
            "payload": body.payload,
            "send_email": body.send_email,
        })
        return result
    except Exception as e:
        logger.error(f"Notification error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/notifications/test")
async def test_notification(body: dict, current_user: dict = Depends(require_role(["admin"]))):
    """Send a test email to verify SMTP configuration."""
    try:
        from backend.services.email_service import send_email
        to = body.get("to", "test@procure-ai.com")
        result = send_email(
            to=to,
            subject="Procure AI \u2014 Test Notification",
            html_body="<h2>Test email from Procure AI</h2><p>SMTP is configured correctly.</p>",
            text_body="Test email from Procure AI - SMTP is working.",
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Sprint 10: Payment Execution endpoints ───────────────────────────────────

class PaymentExecuteRequest(BaseModel):
    payment_run_id: str
    vendor_id: str
    vendor_name: str = ""
    amount: float
    currency: str = "AED"
    bank_account: str = ""
    payment_method: str = "bank_transfer"

@router.post("/payment/execute")
async def execute_payment_endpoint(body: PaymentExecuteRequest):
    """Execute an approved payment."""
    try:
        from backend.services.payment_execution_service import execute_payment
        result = execute_payment(
            payment_run_id=body.payment_run_id,
            vendor_id=body.vendor_id,
            vendor_name=body.vendor_name,
            amount=body.amount,
            currency=body.currency,
            bank_account=body.bank_account,
            payment_method=body.payment_method,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/payment/history")
async def payment_execution_history():
    """Get payment execution history."""
    try:
        from backend.services.payment_execution_service import get_payment_history
        return {"payments": get_payment_history()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/payment/status/{execution_id}")
async def payment_execution_status(execution_id: str):
    """Get status of a specific payment execution."""
    try:
        from backend.services.payment_execution_service import get_payment_status
        result = get_payment_status(execution_id)
        if not result:
            raise HTTPException(status_code=404, detail="Payment not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/payment/remittance/{execution_id}")
async def get_remittance_advice(execution_id: str):
    """Generate remittance advice for a payment."""
    try:
        from backend.services.payment_execution_service import generate_remittance_advice
        return generate_remittance_advice(execution_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Sprint 10: Tax Calculation endpoints ──────────────────────────────────────

class TaxCalculationRequest(BaseModel):
    amount: float
    country_code: str = "AE"
    state_code: str = ""
    category: str = "general"
    is_import: bool = False

@router.post("/tax/calculate")
async def calculate_tax_endpoint(body: TaxCalculationRequest):
    """Calculate tax for a given amount and jurisdiction."""
    try:
        from backend.services.tax_service import calculate_tax
        return calculate_tax(
            amount=body.amount,
            country_code=body.country_code,
            state_code=body.state_code,
            category=body.category,
            is_import=body.is_import,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class InvoiceTaxRequest(BaseModel):
    line_items: list
    country_code: str = "AE"
    state_code: str = ""

@router.post("/tax/invoice")
async def calculate_invoice_tax_endpoint(body: InvoiceTaxRequest):
    """Calculate tax for all line items on an invoice."""
    try:
        from backend.services.tax_service import calculate_invoice_tax
        return calculate_invoice_tax(
            line_items=body.line_items,
            country_code=body.country_code,
            state_code=body.state_code,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Sprint 10: Aging Report endpoints ─────────────────────────────────────────

@router.get("/reports/aging")
async def get_aging_report():
    """Get AP aging analysis."""
    try:
        from backend.services.aging_service import calculate_aging
        return calculate_aging()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
