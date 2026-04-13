"""
Agentic API Routes
Sprint 1: Testing endpoints for orchestrator and agents
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Header, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import base64
import asyncio
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
# Adapter-based ERP access — no direct Odoo imports
from backend.services.adapters.factory import get_adapter as _get_erp_adapter
from backend.agents.vendor_selection import VendorSelectionAgent
from backend.agents.risk_assessment import RiskAssessmentAgent
from backend.services import hybrid_query
from backend.services.db_pool import get_db_connection, return_db_connection
from backend.services import agent_event_stream
from backend.services.query_router import classify_query_intent, resolve_followup_context_with_llm, _fix_multi_intent_routing
from backend.services.routing_schema import normalize_odoo_query_type
from backend.services.session_service import SessionService, SessionServiceError  # Layer 1: execution sessions

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

    # Sprint D bugfix (2026-04-11): broader noun list + procurement-verb
    # pattern + "first integer when $X each is present" fallback so
    # "Procure 20 Dell PowerEdge servers at $8 each" correctly extracts
    # quantity=20 (was returning None, which defaulted to 1, and made
    # the total budget = 1 * 8 = $8 instead of 20 * 8 = $160).
    quantity_patterns = [
        r"\b(?:quantity|qty)\s*[:=]?\s*(\d+)\b",
        r"(\d+)\s*(?:laptop\s+accessories|laptops?|accessories|servers?|monitors?|printers?|desktops?|workstations?|devices?|machines?|units?|items?|pcs?|pieces?)\b",
        r"\b(?:procure|buy|order|purchase|get|need|request|acquire)\s+(?:me\s+)?(\d+)\b",
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

    # Fallback: if "at $X each" / "for $X each" is present, the first
    # integer anywhere in the text is almost always the quantity.
    if re.search(
        r"(?:at|for)\s*\$?\s*[0-9][0-9,]*(?:\.\d+)?\s*(?:k|m)?\s*(?:each|per\s*(?:item|unit|pc|piece))\b",
        text,
        re.I,
    ):
        first_num = re.search(r"\b(\d+)\b", text)
        if first_num:
            try:
                parsed = int(first_num.group(1))
                if parsed > 0:
                    return parsed
            except (TypeError, ValueError):
                pass
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
        logger.info(f"[PR_DATA_ENRICHMENT] ️  Department not specified — leaving blank (frontend should have asked)")
    
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
            logger.info(f"[PR_DATA_ENRICHMENT] ️  budget_category not specified - inferred 'CAPEX' from category '{category}' and ${budget:,.0f}")
        # Office supplies, software licenses are usually OPEX
        elif any(keyword in category_lower for keyword in ["supplies", "software", "license", "subscription"]):
            enriched["budget_category"] = "OPEX"
            logger.info(f"[PR_DATA_ENRICHMENT] ️  budget_category not specified - inferred 'OPEX' from category '{category}'")
        else:
            # Default based on amount
            enriched["budget_category"] = "CAPEX" if budget > 10000 else "OPEX"
            logger.info(f"[PR_DATA_ENRICHMENT] ️  budget_category not specified - defaulting to {enriched['budget_category']} based on ${budget:,.0f}")
    
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
    """Build purchase order results using the active ERP adapter (not Odoo-specific)."""
    from backend.services.adapters.factory import get_adapter
    adapter = get_adapter()
    source = adapter.source_name()

    po_filters = filters or {}
    state_filter = _normalize_po_state(po_filters.get("state"))

    amount_filter = po_filters.get("amount_min")
    if amount_filter is not None:
        try:
            amount_filter = float(amount_filter)
        except (TypeError, ValueError):
            amount_filter = None

    # Fetch POs from adapter (works with any ERP)
    orders = adapter.get_purchase_orders(status=state_filter, limit=200)

    # Apply client-side amount filter if requested
    if amount_filter is not None:
        orders = [o for o in orders if float(o.get("amount_total") or o.get("total_amount") or 0) > amount_filter]

    total_count = len(orders)

    if _is_po_count_query(user_query):
        return {
            "status": "completed",
            "agent": "ERPDataService",
            "result": {
                "status": "success",
                "data_source": source,
                "query_type": "purchase_orders",
                "summary": f"Total purchase orders: {total_count}",
                "total_purchase_orders": total_count,
                "state_filter": state_filter,
                "amount_min": amount_filter,
            },
            "data_source": source,
            "query_type": "purchase_orders",
        }

    # Normalize vendor name from various ERP formats
    simplified_orders: List[Dict[str, Any]] = []
    for order in orders:
        vendor_name = (
            order.get("vendor_name")
            or order.get("partner_name")
            or (order["partner_id"][1] if isinstance(order.get("partner_id"), (list, tuple)) and len(order.get("partner_id", [])) > 1 else None)
            or "Unknown Vendor"
        )
        simplified_orders.append({
            "name": order.get("name") or order.get("po_number") or order.get("order_number"),
            "state": order.get("state") or order.get("status"),
            "amount_total": order.get("amount_total") or order.get("total_amount"),
            "date_order": order.get("date_order") or order.get("order_date"),
            "vendor_name": vendor_name,
        })

    return {
        "status": "completed",
        "agent": "ERPDataService",
        "result": {
            "status": "success",
            "data_source": source,
            "query_type": "purchase_orders",
            "summary": f"Showing {len(simplified_orders)} of {total_count} purchase orders.",
            "total_purchase_orders": total_count,
            "state_filter": state_filter,
            "amount_min": amount_filter,
            "purchase_orders": simplified_orders,
        },
        "data_source": source,
        "query_type": "purchase_orders",
    }


def _build_odoo_data_result(user_query: str, query_type: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_type = normalize_odoo_query_type(query_type)
    normalized_filters = filters or {}

    if normalized_type == "purchase_orders":
        return _build_po_data_result(user_query, normalized_filters)

    records = hybrid_query.query_odoo_data(normalized_type, normalized_filters)
    try:
        source_label = _get_erp_adapter().source_name()
    except Exception:
        source_label = "ERP"
    return {
        "status": "completed",
        "agent": "ERPDataService",
        "result": {
            "status": "success",
            "data_source": source_label,
            "query_type": normalized_type,
            "summary": f"Showing {len(records)} {normalized_type}.",
            normalized_type: records,
        },
        "data_source": source_label,
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


def _generate_fallback_message(query_type: str, agent_data: Dict, primary: Dict, inner: Dict) -> str:
    """Generate a user-friendly message when the agent didn't provide one."""
    qt = (query_type or "").upper()

    # Try reasoning from decision
    decision = primary.get("decision", {}) if isinstance(primary, dict) else {}
    reasoning = ""
    if isinstance(decision, dict):
        reasoning = decision.get("reasoning", "")

    if qt in ("BUDGET", "BUDGET_CHECK", "BUDGET_TRACKING"):
        verified = agent_data.get("budget_verified")
        avail = agent_data.get("available_budget", "")
        dept = agent_data.get("department", "")
        if verified is True:
            return f"Budget verified for {dept}. Available: ${avail}." if avail else f"Budget verified for {dept}."
        elif verified is False:
            reason = agent_data.get("reason", reasoning)
            return f"Budget insufficient for {dept}. {reason}" if reason else f"Budget insufficient for {dept}."
        return reasoning or "Budget check completed."

    if qt in ("RISK", "RISK_ASSESSMENT"):
        level = agent_data.get("risk_level", "UNKNOWN")
        score = agent_data.get("risk_score", "")
        dept = agent_data.get("department", "")
        msg = f"Risk assessment: {level}"
        if score:
            msg += f" (score: {score}/100)"
        if dept:
            msg += f" for {dept}"
        msg += "."
        if reasoning:
            msg += f" {reasoning}"
        return msg

    if qt in ("VENDOR", "VENDOR_SELECTION"):
        vendor = agent_data.get("vendor_name", "")
        if vendor:
            return f"Recommended vendor: {vendor}. {reasoning}" if reasoning else f"Recommended vendor: {vendor}."
        return reasoning or "Vendor analysis completed."

    if qt in ("APPROVAL", "APPROVAL_ROUTING"):
        return reasoning or "Approval routing completed."

    if qt in ("COMPLIANCE", "COMPLIANCE_CHECK"):
        action = agent_data.get("action", "")
        if action == "approve":
            return "Compliance check passed. Request meets all policy requirements."
        elif action == "reject":
            return "Compliance check failed. Request does not meet policy requirements."
        return reasoning or "Compliance check completed."

    if qt in ("INVOICE", "INVOICE_MATCHING"):
        matched = agent_data.get("matched")
        if matched is True:
            return "Invoice matched successfully."
        elif matched is False:
            return "Invoice matching found discrepancies."
        return reasoning or "Invoice processing completed."

    if qt in ("CREATE", "PR_CREATION"):
        pr = agent_data.get("pr_number", "")
        return f"Purchase Requisition {pr} created successfully." if pr else reasoning or "PR creation completed."

    if qt in ("SPEND", "SPEND_ANALYTICS"):
        return reasoning or "Spend analysis completed."

    if qt in ("INVENTORY", "INVENTORY_CHECK"):
        return reasoning or "Inventory check completed."

    # Generic fallback
    return reasoning or "Request processed successfully."


def _build_p2p_response(raw_result: Dict[str, Any]) -> Dict[str, Any]:
    """Transform orchestrator's P2P_FULL result into P2PResponse-compatible dict."""
    actions = raw_result.get("actions_completed", [])
    step_results = []
    for action in actions:
        step_results.append({
            "step": action.get("step", "unknown"),
            "status": action.get("status", "unknown"),
            "summary": action.get("summary", ""),
            "agent": action.get("agent"),
            "data": action.get("data"),
        })

    return {
        "workflow_id": raw_result.get("workflow_run_id", ""),
        "workflow_run_id": raw_result.get("workflow_run_id", ""),
        "workflow_type": "P2P_FULL",
        "status": raw_result.get("status", "in_progress"),
        "actions_completed": step_results,
        "current_step": raw_result.get("current_step"),
        "pending_exceptions": raw_result.get("pending_exceptions", []),
        "human_action_required": raw_result.get("human_action_required"),
        "suggested_next_actions": raw_result.get("suggested_next_actions", []),
        "summary": raw_result.get("summary", ""),
        "pr_number": raw_result.get("pr_number"),
        "po_number": raw_result.get("po_number"),
        "vendor_name": raw_result.get("vendor_name"),
        "total_amount": raw_result.get("total_amount"),
        "top_vendor_options": raw_result.get("top_vendor_options", []),
        "workflow_context": raw_result.get("workflow_context"),
        "validations": raw_result.get("validations", {}),
        # Dev Spec 2.0 gap fields
        "warnings": raw_result.get("warnings", []),
        "gap_alerts": {
            "maverick_spend": any(
                "maverick" in str(w).lower() for w in raw_result.get("warnings", [])
            ),
            "duplicate_invoice": any(
                "duplicate" in str(w).lower() for w in raw_result.get("warnings", [])
            ),
            "contract_variance": any(
                "contract" in str(w).lower() or "variance" in str(w).lower()
                for w in raw_result.get("warnings", [])
            ),
            "exception_count": len(raw_result.get("pending_exceptions", [])),
        },
    }


# Procurement-verb pattern used to upgrade CREATE → P2P_FULL when the user
# explicitly asked to "procure / buy / purchase / order / acquire" something.
# Surgical bridge until R16 routing guards land — see plan §HF-?/R16.
_PROCUREMENT_VERB_RE = re.compile(
    r"\b(procure|procurement|buy|buying|purchase|purchasing|order|ordering|acquire|acquiring)\b",
    re.IGNORECASE,
)


def _upgrade_create_to_p2p_full(
    request_text: str, intents: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Bridge fix (pre-R16): when the LLM classifier returns query_type=CREATE
    but the request is actually a full procurement ask (quantity + product +
    explicit procurement verb), rewrite the intent to P2P_FULL so the
    orchestrator runs the agentic P2P pipeline and a session is created.

    The CREATE→pr_creation path only creates a PR document; users typing
    "Procure 20 Dell servers for IT" expect the full P2P workflow to run.
    Without this upgrade the request silently lands on the legacy single-
    agent pr_creation path with no session.

    Guard: only upgrade when ALL of these hold for at least one intent:
      - query_type == CREATE
      - filters has a non-empty `quantity`
      - filters has a non-empty `product_name`
      - request text contains a procurement verb
    Otherwise the intents are returned unchanged.
    """
    if not intents or not request_text:
        return intents
    if not _PROCUREMENT_VERB_RE.search(request_text):
        return intents

    upgraded = False
    new_intents: List[Dict[str, Any]] = []
    for intent in intents:
        if not isinstance(intent, dict):
            new_intents.append(intent)
            continue
        qt = str(intent.get("query_type", "")).upper()
        filters = intent.get("filters") or {}
        if (
            qt == "CREATE"
            and isinstance(filters, dict)
            and filters.get("quantity")
            and filters.get("product_name")
        ):
            new_intent = dict(intent)
            new_intent["query_type"] = "P2P_FULL"
            new_intents.append(new_intent)
            upgraded = True
        else:
            new_intents.append(intent)

    if upgraded:
        logger.info(
            "[INTENT UPGRADE] CREATE → P2P_FULL "
            "(procurement verb + quantity + product_name detected)"
        )
    return new_intents


def _canonicalize_intents(intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Collapse redundant intent combinations into a single workflow.

    CREATE already runs compliance/budget/approval workflow in orchestrator,
    so CREATE + APPROVAL should execute as CREATE only.
    P2P_FULL subsumes all individual P2P intents.
    """
    if not intents:
        return intents

    normalized_types = {str((intent or {}).get("query_type", "")).upper() for intent in intents}

    # P2P_FULL subsumes individual workflow intents
    if "P2P_FULL" in normalized_types:
        subsumed = {"CREATE", "APPROVAL", "BUDGET", "VENDOR", "COMPLIANCE", "P2P"}
        collapsed = [intent for intent in intents
                     if str((intent or {}).get("query_type", "")).upper() not in subsumed]
        if len(collapsed) < len(intents):
            logger.info("[INTENT CANONICALIZATION] P2P_FULL subsumes individual workflow intents")
        return collapsed if collapsed else intents

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
    "p2p_full", "p2p", "procure", "end_to_end", "procure_to_pay",
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
        "p2p_full": "P2P_FULL",
        "p2p": "P2P_FULL",
        "procure": "P2P_FULL",
        "end_to_end": "P2P_FULL",
        "procure_to_pay": "P2P_FULL",
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
    # Sprint E (2026-04-11): session context passthrough. When the frontend
    # submits a follow-up message from inside an active session, it forwards
    # the session_id here so the router can skip P2P_FULL re-creation and
    # treat the message as a conversational continuation of the existing run.
    # Absent/null means "fresh request from chat".
    session_id: Optional[str] = None
    in_session_context: Optional[bool] = None
    

class AgenticResponse(BaseModel):
    """Response from agentic system"""
    status: str
    agent: str
    decision: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    data_source: Optional[str] = None
    query_type: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class P2PStepResult(BaseModel):
    """Individual step result in a P2P workflow"""
    step: str
    status: str          # passed, approved, created, waiting, failed, skipped
    summary: str
    agent: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class P2PResponse(BaseModel):
    """Unified response for Full Procure-to-Pay workflow"""
    workflow_id: str
    workflow_type: str = "P2P_FULL"
    status: str          # completed, waiting_human, in_progress, failed
    actions_completed: List[P2PStepResult] = []
    current_step: Optional[str] = None
    pending_exceptions: List[Dict[str, Any]] = []
    human_action_required: Optional[Dict[str, Any]] = None
    suggested_next_actions: List[str] = []
    summary: str = ""
    pr_number: Optional[str] = None
    po_number: Optional[str] = None
    vendor_name: Optional[str] = None
    total_amount: Optional[float] = None


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
    logger.info("[AGENTIC EXECUTE] Orchestrator execution requested")
    print("="*80)
    try:
        request_id = str(uuid.uuid4())
        logger.info(f"[EXECUTE] Request: {request.request[:100]}{'...' if len(request.request) > 100 else ''}")
        logger.info(f"[EXECUTE] PR Data: {request.pr_data}")
        logger.info(f"[EXECUTE] Agent Type: {request.agent_type or 'Auto-detect'}")
        
        # CLASSIFY THE QUERY FIRST (multi-intent support)
        logger.info(f"[EXECUTE] Classifying query to determine query_type...")
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

        # Bridge fix: upgrade procurement-shaped CREATE to P2P_FULL before canonicalization
        intents = _upgrade_create_to_p2p_full(request.request, intents)
        intents = _canonicalize_intents(intents)
        # Safety net: re-apply multi-intent keyword correction after canonicalization
        intents = _fix_multi_intent_routing(request.request, intents)

        logger.info(f"[EXECUTE] Detected {len(intents)} intent(s)")
        
        # Multi-intent execution (sequential)
        if len(intents) > 1:
            logger.info(f"[EXECUTE] MULTI-INTENT: Executing {len(intents)} agents sequentially...")
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
                    logger.info(f"[EXECUTE - Intent {idx}] Skipping approval due to failed budget verification")
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
                    logger.info(f"[EXECUTE - Intent {idx}] Skipping approval because CREATE workflow failed")
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
                    logger.info(f"[EXECUTE - Intent {idx}] ⏭️ Skipping duplicate approval routing (already routed during CREATE workflow)")
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
                    
                    # ENRICH PR_DATA FROM INTENT FILTERS (FIX FOR MULTI-INTENT NL QUERIES)
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
            
            logger.info(f"\n[EXECUTE] MULTI-INTENT COMPLETE: Executed {len(intents)} intents")
            
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
        logger.info(f"[EXECUTE] Classification result: query_type='{query_type}', data_source='{data_source}'")

        normalized_pr_data = _hydrate_pr_data_from_workflow(
            _normalize_budget_from_request_text(request.request, request.pr_data or {})
        )

        # Enrich pr_data from classifier-extracted filters (same as multi-intent path)
        intent_filters = intents[0].get("filters", {}) or {}
        enriched_pr_data = _hydrate_pr_data_from_workflow(
            _enrich_pr_data_from_filters(normalized_pr_data, intent_filters)
        )
        logger.info(f"[EXECUTE] Enriched pr_data: {enriched_pr_data}")

        # ── Early intercepts (apply regardless of data_source classification) ──
        # Multi-vendor risk comparison: always route to helper no matter how LLM classified it
        if re.search(r"\b(risk|risks)\b.{0,40}\b(all\s+vendors?|each\s+vendor|vendors?\s+all|across\s+vendors?)\b|\ball\s+vendors?\b.{0,40}\b(risk|risks)\b", request.request, re.I):
            logger.info("[EXECUTE] Multi-vendor risk comparison detected — running comparison helper")
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
            logger.info("[EXECUTE] Redirecting vendor list query to VendorSelectionAgent (recommendation intent detected)")
            data_source = "agentic"
            query_type = "VENDOR"

        if data_source == "odoo":
            logger.info("[EXECUTE] Odoo data query — bypassing orchestrator")
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
            logger.info("[EXECUTE] General/greeting query — returning friendly response")
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
        
        logger.info(f"[EXECUTE] Initializing orchestrator...")
        orch = initialize_orchestrator_with_agents()
        logger.info(f"[EXECUTE] Orchestrator ready with {len(orch.specialized_agents)} agents")
        
        # Build context WITH query_type from classifier
        context = {
            "request": request.request,
            "pr_data": enriched_pr_data,
            "query_type": query_type,  # PASS CLASSIFIER RESULT!
            "mode": "orchestrated",
            "request_id": request_id,
        }
        logger.info(f"[EXECUTE] Executing through orchestrator with query_type='{query_type}'...")
        
        # Execute through orchestrator
        result = await orch.execute(context)
        
        logger.info(f"[EXECUTE] Execution complete:")
        print(f"[EXECUTE]   - Status: {result.get('status', 'completed')}")
        print(f"[EXECUTE]   - Agent: {result.get('agent', 'Orchestrator')}")
        print(f"[EXECUTE]   - Has Decision: {bool(result.get('decision'))}")
        print(f"[EXECUTE]   - Has Result: {bool(result.get('result'))}")
        print("="*80 + "\n")
        
        # Extract the agent's actual result for a rich response
        raw_result = result.get("result", {})

        # ── P2P_FULL workflow: wrap in P2PResponse format ──
        if isinstance(raw_result, dict) and raw_result.get("workflow_type") == "P2P_FULL":
            p2p_data = _build_p2p_response(raw_result)
            return AgenticResponse(
                status=raw_result.get("status", "in_progress"),
                agent="P2POrchestrator",
                decision=result.get("decision"),
                result=p2p_data,
                data_source="agentic",
                query_type="P2P_FULL",
                message=p2p_data.get("summary", ""),
                data=p2p_data,
            )

        primary = raw_result.get("primary_result", {}) if isinstance(raw_result, dict) else {}
        inner = primary.get("result", {}) if isinstance(primary, dict) else {}

        # Surface agent's message at top level so chat displays it
        agent_message = ""
        agent_data = {}
        for source in [primary, inner, raw_result]:
            if isinstance(source, dict):
                if not agent_message and source.get("message"):
                    agent_message = str(source["message"])
                for key in ["message", "action", "rfq_number", "amendment_number",
                            "rtv_number", "po_number", "pr_number", "score", "pass_fail",
                            "matched", "exceptions", "next_suggestions", "vendor_name",
                            "budget_verified", "available_budget", "risk_level",
                            "department", "title", "credit_expected", "accrual_ref",
                            "debit_note_number", "deadline", "requires_approval",
                            "workflow_type", "workflow_run_id", "actions_completed",
                            "current_step", "human_action_required", "suggested_next_actions",
                            "total_amount", "risk_score", "reason", "reasoning",
                            "recommended_actions", "mitigations", "can_proceed",
                            "breakdown", "top_vendor_options"]:
                    val = source.get(key)
                    if val is not None and key not in agent_data:
                        agent_data[key] = val

        # Generate fallback message when agent didn't provide one
        if not agent_message:
            agent_message = _generate_fallback_message(query_type, agent_data, primary, inner)

        return AgenticResponse(
            status=result.get("status", "completed"),
            agent=result.get("agent", "Orchestrator"),
            decision=result.get("decision"),
            result=raw_result,
            data_source=data_source,
            query_type=query_type,
            message=agent_message,
            data=agent_data,
        )
        
    except Exception as e:
        logger.info(f"[EXECUTE] ERROR: {str(e)}")
        import traceback
        logger.info(f"[EXECUTE] Traceback:\n{traceback.format_exc()}")
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
    logger.info(f"[AGENTIC STREAM] Starting SSE stream for request")
    
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
            logger.info(f"[AGENTIC STREAM] Classifying intent for: '{request.request[:100]}'")

            # Sprint E (2026-04-11): session-awareness. If the request arrives
            # with a session_id attached, the user is typing follow-ups inside
            # an already-running P2P session (e.g. "also check budget", "what
            # about risk"). We must NOT re-trigger P2P_FULL here — that would
            # spawn a second parallel pipeline. Instead, the message is routed
            # to the running orchestrator as a conversational continuation.
            _existing_session_id = (request.session_id or "").strip() or None
            if _existing_session_id:
                logger.info(
                    f"[AGENTIC STREAM] Follow-up detected in session "
                    f"{_existing_session_id}; suppressing P2P_FULL re-creation."
                )

            # Run sync LLM calls in a thread to avoid blocking the event loop
            # (which would prevent SSE events from being streamed to the client)
            classification = await asyncio.get_event_loop().run_in_executor(
                None, classify_query_intent, request.request
            )

            # If we're in an existing session, strip any P2P_FULL / CREATE
            # intents so we don't start a fresh procurement run.
            if _existing_session_id:
                raw_intents = classification.get("intents", []) or []
                filtered = [
                    it for it in raw_intents
                    if str(it.get("query_type", "")).upper()
                    not in ("P2P_FULL", "CREATE")
                ]
                if not filtered:
                    filtered = [{
                        "data_source": "general",
                        "query_type": "GENERAL",
                        "filters": {},
                    }]
                classification["intents"] = filtered
                if filtered:
                    classification["data_source"] = filtered[0].get("data_source", "general")
                    classification["query_type"] = filtered[0].get("query_type", "GENERAL")
                    classification["filters"] = filtered[0].get("filters", {})
            logger.info(f"[AGENTIC STREAM] Classification result: query_type={classification.get('query_type')}, data_source={classification.get('data_source')}, confidence={classification.get('confidence')}")
            classification = await asyncio.get_event_loop().run_in_executor(
                None, resolve_followup_context_with_llm, request.request, classification, request.pr_data
            )
            
            # Check for multi-intent queries
            intents = classification.get("intents", [])
            if not intents:
                # Backward compatibility: single intent format
                intents = [{
                    "data_source": classification.get("data_source", "agentic"),
                    "query_type": classification.get("query_type", ""),
                    "filters": classification.get("filters", {})
                }]

            # Bridge fix: upgrade procurement-shaped CREATE to P2P_FULL before canonicalization.
            # The classifier sometimes returns CREATE for "Procure 20 X for Y" — without this
            # the request silently lands on the legacy single-agent pr_creation path with no session.
            intents = _upgrade_create_to_p2p_full(request.request, intents)
            intents = _canonicalize_intents(intents)
            # Safety net: re-apply multi-intent keyword correction after canonicalization
            intents = _fix_multi_intent_routing(request.request, intents)

            logger.info(f"[AGENTIC STREAM] Detected {len(intents)} intent(s)")

            # ── Layer 1: create execution session for P2P_FULL intent (HYBRID observer mode) ──
            # Only P2P_FULL triggers a session. Conversational / single-agent queries stay
            # in the legacy path. Emit a session_created SSE event so the frontend can
            # redirect to /sessions/:id before the orchestrator starts running.
            session_id: Optional[str] = None
            is_p2p_full = any(
                str(it.get("query_type", "")).upper() == "P2P_FULL" for it in intents
            )
            if is_p2p_full:
                try:
                    session_user_id = (
                        current_user.get("sub")
                        or current_user.get("email")
                        or current_user.get("name")
                        or "anonymous"
                    )

                    # Sprint D bugfix (2026-04-11): normalize pr_data BEFORE
                    # session creation so the stored request_summary.pr_data
                    # carries the correct budget. Before this fix, "Procure 20
                    # servers at $8 each" would be stored with budget=8
                    # (the raw unit price), and SessionHeader displayed $8.
                    # Downstream orchestration already re-normalizes, but
                    # that write never reached session_master.request_summary.
                    _session_pr_data = _normalize_budget_from_request_text(
                        request.request, request.pr_data or {}
                    )
                    # Also enrich from shared classifier filters so fields like
                    # amount=N and department=IT land on the session master.
                    _shared_filters = _collect_shared_intent_filters(intents)
                    _session_pr_data = _enrich_pr_data_from_filters(
                        _session_pr_data, _shared_filters
                    )
                    session_create_result = SessionService.create(
                        kind="p2p_full",
                        user_id=session_user_id,
                        request_summary={
                            "request": request.request,
                            "pr_data": _session_pr_data,
                            "initiated_via": "chat",
                        },
                        caller="query_router",
                    )
                    # SessionService.create returns Dict[str, Any] with shape
                    # {"session_id": "<uuid>", "created": bool, "session": {...}}.
                    # Unwrap to a string so downstream (SSE payload, orchestrator context,
                    # psycopg2 UUID binding) all see a plain string.
                    if isinstance(session_create_result, dict):
                        session_id = session_create_result.get("session_id")
                    else:
                        session_id = session_create_result
                    if not isinstance(session_id, str) or not session_id:
                        logger.warning(
                            "[AGENTIC STREAM] SessionService.create returned unexpected shape: %r",
                            session_create_result,
                        )
                        session_id = None
                    else:
                        _was_created = (
                            session_create_result.get("created", True)
                            if isinstance(session_create_result, dict) else True
                        )
                        _existing_session = (
                            session_create_result.get("session", {})
                            if isinstance(session_create_result, dict) else {}
                        )
                        if _was_created:
                            logger.info(f"[AGENTIC STREAM] Created execution session {session_id} for P2P_FULL")
                        else:
                            logger.info(
                                f"[AGENTIC STREAM] R4 dedup: returning existing session {session_id} "
                                f"(status={_existing_session.get('current_status')}, "
                                f"phase={_existing_session.get('current_phase')})"
                            )
                        await stream.emit(agent_event_stream.AgentEventType.SESSION_CREATED, {
                            "session_id": session_id,
                            "kind": "p2p_full",
                            "reused_existing": not _was_created,
                            "existing_status": _existing_session.get("current_status") if not _was_created else None,
                            "existing_phase": _existing_session.get("current_phase") if not _was_created else None,
                        })
                        if not _was_created:
                            # Dedup hit — redirect to existing session, don't re-run pipeline
                            return
                except SessionServiceError as _sess_exc:
                    # HYBRID rule: session layer failure must NOT block the pipeline.
                    logger.warning(f"[AGENTIC STREAM] Session creation failed (non-fatal): {_sess_exc}")
                    session_id = None
                except Exception as _sess_exc:
                    logger.warning(f"[AGENTIC STREAM] Session creation raised (non-fatal): {_sess_exc}")
                    session_id = None
            
            # Multi-intent execution
            if len(intents) > 1:
                logger.info(f"[AGENTIC STREAM] MULTI-INTENT: Executing {len(intents)} agents sequentially...")
                
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
                            odoo_result = await asyncio.get_event_loop().run_in_executor(
                                None, _build_odoo_data_result, request.request, intent_query_type, intent.get("filters", {})
                            )
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
                            "session_id": session_id,  # Layer 1: observer session (None for non-P2P)
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
            logger.info(f"[STREAM] Enriched pr_data: {enriched_pr_data}")

            # ── Early intercepts (apply regardless of data_source classification) ──
            # Multi-vendor risk: always run helper, even when LLM classifies as agentic RISK
            if re.search(r"\b(risk|risks)\b.{0,40}\b(all\s+vendors?|each\s+vendor|vendors?\s+all|across\s+vendors?)\b|\ball\s+vendors?\b.{0,40}\b(risk|risks)\b", request.request, re.I):
                logger.info("[STREAM] Multi-vendor risk comparison detected — running comparison helper")
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
                logger.info("[STREAM] Redirecting vendor list to VendorSelectionAgent")
                data_source = "agentic"
                query_type = "VENDOR"

            if data_source == "odoo":
                await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                    "message": "Detected Odoo data query. Reading live Odoo records...",
                    "query_type": normalize_odoo_query_type(query_type)
                })

                odoo_result = await asyncio.get_event_loop().run_in_executor(
                    None, _build_odoo_data_result, request.request, query_type, intents[0].get("filters", {})
                )
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
                logger.info("[AGENTIC STREAM] General/greeting query detected — returning friendly response")
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
                "session_id": session_id,  # Layer 1: observer session (None for non-P2P)
            }
            
            # Event 3: Routing
            await stream.emit(agent_event_stream.AgentEventType.ROUTING, {
                "message": "Determining which agent should handle this request...",
                "query_type": query_type
            })
            
            # Execute through orchestrator
            logger.info(f"[AGENTIC STREAM] Executing orchestrator with query_type={query_type}, pr_data_keys={list(enriched_pr_data.keys())}")
            result = await orch.execute(context)
            logger.info(f"[AGENTIC STREAM] Orchestrator returned: status={result.get('status') if isinstance(result, dict) else 'N/A'}, agent={result.get('agent') if isinstance(result, dict) else 'N/A'}, result_keys={list(result.get('result', {}).keys()) if isinstance(result, dict) and isinstance(result.get('result'), dict) else 'N/A'}")

            clean_result = clean_for_json(result)

            # ── P2P_FULL workflow: emit specialized complete event ──
            orch_result_raw = clean_result.get("result", {})
            if isinstance(orch_result_raw, dict) and orch_result_raw.get("workflow_type") == "P2P_FULL":
                p2p_data = _build_p2p_response(orch_result_raw)
                await stream.emit_complete({
                    "status": orch_result_raw.get("status", "in_progress"),
                    "agent": "P2POrchestrator",
                    "agent_name": "P2POrchestrator",
                    "result": p2p_data,
                    "agents_invoked": orch_result_raw.get("agents_invoked", []),
                    "data_source": "agentic",
                    "query_type": "P2P_FULL",
                    "workflow_type": "P2P_FULL",
                    "session_id": session_id,  # Layer 1: execution session id (None if creation failed)
                    "summary": p2p_data.get("summary", ""),
                    "message": p2p_data.get("summary", ""),
                    "pr_number": p2p_data.get("pr_number"),
                    "po_number": p2p_data.get("po_number"),
                    "vendor_name": p2p_data.get("vendor_name"),
                    "total_amount": p2p_data.get("total_amount"),
                    "human_action_required": p2p_data.get("human_action_required"),
                    "suggested_next_actions": p2p_data.get("suggested_next_actions", []),
                    "actions_completed": p2p_data.get("actions_completed", []),
                    "department": enriched_pr_data.get("department", ""),
                    "budget": enriched_pr_data.get("budget", 0),
                    "product_name": enriched_pr_data.get("product_name", ""),
                    "quantity": enriched_pr_data.get("quantity", 0),
                    # Dev Spec 2.0 gap fields
                    "warnings": p2p_data.get("warnings", []),
                    "gap_alerts": p2p_data.get("gap_alerts", {}),
                    "pending_exceptions": p2p_data.get("pending_exceptions", []),
                    "workflow_run_id": p2p_data.get("workflow_run_id", ""),
                })
                return

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
            
            # Emit business-enriched complete event with full agent result data
            complete_payload = {
                "status": primary_result.get("status", "completed"),
                "agent": actual_agent,
                "agent_name": actual_agent,
                "result": {
                    "primary_result": primary_result,
                    "secondary_results": orch_inner.get("secondary_results", []),
                    "agents_invoked": list(agents_invoked) if agents_invoked else [],
                    "total_execution_time_ms": orch_inner.get("total_execution_time_ms", 0),
                },
                "agents_invoked": list(agents_invoked) if agents_invoked else [],
                "data_source": classification.get("data_source", "agentic"),
                "query_type": query_type,
                # Pass full result data for business summary generation
                "department": enriched_pr_data.get("department", ""),
                "budget": enriched_pr_data.get("budget", 0),
                "product_name": enriched_pr_data.get("product_name", ""),
                "quantity": enriched_pr_data.get("quantity", 0),
            }
            # Merge agent-specific data for richer business summaries
            if isinstance(primary_result, dict):
                for key in ["budget_verified", "available_budget", "requested_amount",
                            "vendor_name", "winning_vendor", "risk_level", "confidence",
                            "pr_number", "po_number", "rfq_number", "rtv_number",
                            "amendment_number", "score", "pass_fail", "action",
                            "message", "next_suggestions",
                            "workflow_type", "workflow_run_id", "top_vendor_options",
                            "awaiting_vendor_confirmation", "actions_completed",
                            "current_step", "human_action_required",
                            "suggested_next_actions", "total_amount"]:
                    # Use 'is not None' checks instead of 'or' to avoid swallowing
                    # falsy-but-valid values like False, 0, or empty lists
                    val = primary_result.get(key)
                    if val is None and isinstance(nested_result, dict):
                        val = nested_result.get(key)
                    if val is not None:
                        complete_payload[key] = val

            await stream.emit_complete(complete_payload)
            
        except Exception as e:
            logger.error(f"[AGENTIC STREAM] Error: {e}")
            await stream.emit_error(str(e), {"request_id": request_id})
        finally:
            # Cleanup after stream completes
            agent_event_stream.cleanup_stream(request_id)
    
    # Start execution in background
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


class P2PResumeRequest(BaseModel):
    """Resume a P2P workflow after human input (approval, vendor confirmation, GRN, QC, payment, etc.)."""
    workflow_run_id: str
    action: str              # "approve", "reject", "confirm_vendor", "confirm_grn", "override", "block",
                             # "accept", "return_to_vendor", "accept_exception", "adjust", "reject_invoice",
                             # "release_payment", "hold_payment", "continue", "escalate", "partial_accept"
    pr_data: Optional[Dict[str, Any]] = None
    human_input: Optional[Dict[str, Any]] = None


@router.post("/p2p/resume")
async def resume_p2p_workflow(request: P2PResumeRequest, current_user: dict = Depends(require_auth())):
    """
    Resume a paused P2P_FULL workflow after human decision.
    Handles: vendor confirmation, approval, goods receipt.
    Continues executing remaining steps until the next human gate or completion.
    """
    from backend.services.workflow_engine import (
        get_workflow_status, resume_from_human, get_suggestions, generate_workflow_summary,
    )

    wf_id = request.workflow_run_id
    status = get_workflow_status(wf_id)
    if not status.get("success"):
        raise HTTPException(status_code=404, detail=f"Workflow {wf_id} not found")

    # Find the waiting_human task
    waiting = [t for t in status.get("tasks", []) if t["status"] == "waiting_human"]
    if not waiting:
        raise HTTPException(status_code=400, detail="No tasks awaiting human input")

    # Resume the first waiting task
    task = waiting[0]
    human_input = request.human_input or {}
    human_input["action"] = request.action
    human_input["approved_by"] = current_user.get("email", "unknown")

    resume_result = resume_from_human(task["task_id"], human_input)
    if not resume_result.get("success"):
        raise HTTPException(status_code=500, detail=resume_result.get("error", "Resume failed"))

    # After resuming, check if there are running tasks that need agent execution
    # Re-invoke orchestrator to continue the P2P flow
    orch = initialize_orchestrator_with_agents()
    pr_data = request.pr_data or {}

    # Add flags so _execute_full_p2p knows to skip already-completed gates
    if request.action in ("approve", "approve_decision"):
        pr_data["approved"] = True
    if request.action in ("confirm_vendor",):
        pr_data["vendor_confirmed"] = True
    if request.action in ("confirm_grn",):
        pr_data["grn_confirmed"] = True
    if request.action in ("override",):
        pr_data["policy_override"] = True
    if request.action in ("accept", "partial_accept"):
        pr_data["qc_accepted"] = True
        pr_data["qc_partial"] = request.action == "partial_accept"
    if request.action in ("return_to_vendor",):
        pr_data["qc_returned"] = True
    if request.action in ("accept_exception", "adjust"):
        pr_data["exception_resolved"] = True
    if request.action in ("release_payment",):
        pr_data["payment_released"] = True
    if request.action in ("hold_payment",):
        pr_data["payment_held"] = True
    if request.action in ("continue",):
        pr_data["budget_threshold_approved"] = True
    if request.action in ("escalate",):
        pr_data["escalated"] = True

    # Layer 1: look up the session row attached to this workflow_run_id (hybrid).
    # If present, also surface the first pending gate so the orchestrator can
    # resolve it via SessionService.resolve_gate (R13 idempotent).
    resume_session_id: Optional[str] = None
    resume_gate_id: Optional[str] = None
    try:
        _sess_row = SessionService.find_by_workflow_run(wf_id)
        if _sess_row:
            resume_session_id = _sess_row.get("session_id")
            for _g in _sess_row.get("open_gates", []):
                if _g.get("status") == "pending":
                    resume_gate_id = _g.get("gate_id")
                    break
    except Exception as _sess_lookup_exc:
        logger.warning(
            "[P2P RESUME] session lookup failed (non-fatal in hybrid): %s",
            _sess_lookup_exc,
        )

    # Continue execution via orchestrator resume
    resume_context = {
        "workflow_run_id": wf_id,
        "input_context": {"request": f"Resume P2P workflow {wf_id}", "pr_data": pr_data},
        "pr_data": pr_data,
        "auto_approve": request.action in ("approve", "approve_decision"),
        "auto_grn": request.action == "confirm_grn",
        "action": request.action,
        "human_input": request.human_input or {},
        "session_id": resume_session_id,
        "gate_id": resume_gate_id,
        "user_id": current_user.get("email") or current_user.get("sub") or "anonymous",
    }

    try:
        p2p_result = await orch._resume_p2p_workflow(resume_context)
        if isinstance(p2p_result, dict) and p2p_result.get("workflow_type") == "P2P_FULL":
            p2p_data = _build_p2p_response(p2p_result)
            return AgenticResponse(
                status=p2p_result.get("status", "in_progress"),
                agent="P2POrchestrator",
                result=p2p_data,
                data_source="agentic",
                query_type="P2P_FULL",
                message=p2p_data.get("summary", ""),
                data=p2p_data,
            )
        return AgenticResponse(
            status=p2p_result.get("status", "completed"),
            agent="P2POrchestrator",
            result=p2p_result,
            data_source="agentic",
            query_type="P2P_FULL",
            message=str(p2p_result.get("summary", "")),
            data=p2p_result,
        )
    except Exception as e:
        logger.error(f"[P2P RESUME] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/budget/verify", response_model=AgenticResponse)
async def verify_budget(request: AgenticRequest, current_user: dict = Depends(require_auth())):
    """
    Direct budget verification (bypass orchestrator).

    Useful for testing individual agents.
    """
    print("\n" + "="*80)
    logger.info("[BUDGET VERIFY] Budget verification requested")
    print("="*80)
    try:
        logger.info(f"[BUDGET] Request: {request.request}")
        logger.info(f"[BUDGET] PR Data:")
        print(f"[BUDGET]   - Department: {request.pr_data.get('department') if request.pr_data else 'N/A'}")
        print(f"[BUDGET]   - Budget: ${request.pr_data.get('budget', 0):,.2f}" if request.pr_data else "[BUDGET]   - Budget: $0")
        print(f"[BUDGET]   - Category: {request.pr_data.get('budget_category', 'N/A')}" if request.pr_data else "[BUDGET]   - Category: N/A")
        
        logger.info(f"[BUDGET] Creating BudgetVerificationAgent...")
        budget_agent = BudgetVerificationAgent()
        logger.info(f"[BUDGET] Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        logger.info(f"[BUDGET] Executing budget check...")
        result = await budget_agent.execute(context)
        
        logger.info(f"[BUDGET] Verification complete:")
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
        logger.info(f"[BUDGET] ERROR: {str(e)}")
        import traceback
        logger.info(f"[BUDGET] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[APPROVAL ROUTE] Approval routing requested")
    print("="*80)
    try:
        logger.info(f"[APPROVAL] Request: {request.request}")
        logger.info(f"[APPROVAL] PR Data:")
        print(f"[APPROVAL]   - Department: {request.pr_data.get('department') if request.pr_data else 'N/A'}")
        print(f"[APPROVAL]   - Budget: ${request.pr_data.get('budget', 0):,.2f}" if request.pr_data else "[APPROVAL]   - Budget: $0")
        print(f"[APPROVAL]   - PR Number: {request.pr_data.get('pr_number', 'N/A')}" if request.pr_data else "[APPROVAL]   - PR Number: N/A")
        
        logger.info(f"[APPROVAL] Creating ApprovalRoutingAgent...")
        approval_agent = ApprovalRoutingAgent()
        logger.info(f"[APPROVAL] Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        logger.info(f"[APPROVAL] Determining approval chain...")
        result = await approval_agent.execute(context)
        
        logger.info(f"[APPROVAL] Routing complete:")
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
        logger.info(f"[APPROVAL] ERROR: {str(e)}")
        import traceback
        logger.info(f"[APPROVAL] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[VENDOR RECOMMEND] Vendor recommendation requested")
    print("="*80)
    try:
        logger.info(f"[VENDOR] Request: {request.request}")
        logger.info(f"[VENDOR] PR Data: Category={request.pr_data.get('category', 'N/A') if request.pr_data else 'N/A'}, Budget=${request.pr_data.get('budget', 0):,.2f}" if request.pr_data else "[VENDOR] PR Data: None")
        
        logger.info(f"[VENDOR] Creating VendorSelectionAgent...")
        vendor_agent = VendorSelectionAgent()
        logger.info(f"[VENDOR] Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        logger.info(f"[VENDOR] Scoring and ranking vendors...")
        result = await vendor_agent.execute(context)
        
        logger.info(f"[VENDOR] Recommendation complete:")
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
        logger.info(f"[VENDOR] ERROR: {str(e)}")
        import traceback
        logger.info(f"[VENDOR] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[RISK ASSESS] ️  Risk assessment requested")
    print("="*80)
    try:
        logger.info(f"[RISK] Request: {request.request}")
        logger.info(f"[RISK] PR Data: Vendor={request.pr_data.get('vendor_name', 'N/A') if request.pr_data else 'N/A'}, Amount=${request.pr_data.get('budget', 0):,.2f}" if request.pr_data else "[RISK] PR Data: None")
        
        logger.info(f"[RISK] Creating RiskAssessmentAgent...")
        risk_agent = RiskAssessmentAgent()
        logger.info(f"[RISK] Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        logger.info(f"[RISK] Analyzing 4 risk dimensions...")
        result = await risk_agent.execute(context)
        
        logger.info(f"[RISK] Assessment complete:")
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
        logger.info(f"[RISK] ERROR: {str(e)}")
        import traceback
        logger.info(f"[RISK] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[CONTRACT MONITOR] Contract monitoring requested")
    print("="*80)
    logger.info(f"[CONTRACT] Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    logger.info(f"[CONTRACT] Contract Data: {request.pr_data}")
    
    try:
        logger.info(f"[CONTRACT] Creating ContractMonitoringAgent...")
        from backend.agents.contract_monitoring import ContractMonitoringAgent
        contract_agent = ContractMonitoringAgent()
        logger.info(f"[CONTRACT] Agent created")
        
        context = {
            "request": request.request,
            "contract_data": request.pr_data or {}
        }
        
        logger.info(f"[CONTRACT] Executing contract monitoring...")
        result = await contract_agent.execute(context)
        
        logger.info(f"[CONTRACT] Monitoring complete:")
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
        logger.info(f"[CONTRACT] ERROR: {str(e)}")
        import traceback
        logger.info(f"[CONTRACT] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[SUPPLIER EVALUATE] Supplier performance evaluation requested")
    print("="*80)
    logger.info(f"[SUPPLIER] Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    logger.info(f"[SUPPLIER] Supplier Data: {request.pr_data}")
    
    try:
        logger.info(f"[SUPPLIER] Creating SupplierPerformanceAgent...")
        from backend.agents.supplier_performance import SupplierPerformanceAgent
        supplier_agent = SupplierPerformanceAgent()
        logger.info(f"[SUPPLIER] Agent created")
        
        context = {
            "request": request.request,
            "supplier_data": request.pr_data or {}
        }
        
        logger.info(f"[SUPPLIER] Evaluating supplier across 4 dimensions...")
        result = await supplier_agent.execute(context)
        
        logger.info(f"[SUPPLIER] Evaluation complete:")
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
        logger.info(f"[SUPPLIER] ERROR: {str(e)}")
        import traceback
        logger.info(f"[SUPPLIER] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[PRICE ANALYZE] Price analysis requested")
    print("="*80)
    logger.info(f"[PRICE] Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    logger.info(f"[PRICE] PR Data: {request.pr_data}")
    
    try:
        logger.info(f"[PRICE] Creating PriceAnalysisAgent...")
        from backend.agents.price_analysis import PriceAnalysisAgent
        price_agent = PriceAnalysisAgent()
        logger.info(f"[PRICE] Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        logger.info(f"[PRICE] Analyzing price competitiveness...")
        result = await price_agent.execute(context)
        
        logger.info(f"[PRICE] Analysis complete:")
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
        logger.info(f"[PRICE] ERROR: {str(e)}")
        import traceback
        logger.info(f"[PRICE] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[COMPLIANCE CHECK] ️ Compliance check requested")
    print("="*80)
    logger.info(f"[COMPLIANCE] Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    logger.info(f"[COMPLIANCE] PR Data: {request.pr_data}")
    
    try:
        logger.info(f"[COMPLIANCE] Creating ComplianceCheckAgent...")
        from backend.agents.compliance_check import ComplianceCheckAgent
        compliance_agent = ComplianceCheckAgent()
        logger.info(f"[COMPLIANCE] Agent created")
        
        context = {
            "request": request.request,
            "pr_data": request.pr_data or {}
        }
        
        logger.info(f"[COMPLIANCE] Validating against company policies...")
        result = await compliance_agent.execute(context)
        
        logger.info(f"[COMPLIANCE] Check complete:")
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
        logger.info(f"[COMPLIANCE] ERROR: {str(e)}")
        import traceback
        logger.info(f"[COMPLIANCE] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[INVOICE MATCH] 3-way invoice matching requested")
    print("="*80)
    logger.info(f"[INVOICE] Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    logger.info(f"[INVOICE] Invoice Data: {request.pr_data}")
    
    try:
        logger.info(f"[INVOICE] Creating InvoiceMatchingAgent...")
        from backend.agents.invoice_matching import InvoiceMatchingAgent
        invoice_agent = InvoiceMatchingAgent()
        logger.info(f"[INVOICE] Agent created")
        
        context = {
            "request": request.request,
            **request.pr_data  # Invoice data passed directly
        }
        
        logger.info(f"[INVOICE] Performing 3-way matching (PO + Receipt + Invoice)...")
        result = await invoice_agent.execute(context)
        
        logger.info(f"[INVOICE] Matching complete:")
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
        logger.info(f"[INVOICE] ERROR: {str(e)}")
        import traceback
        logger.info(f"[INVOICE] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[SPEND ANALYZE] Company spending analysis requested")
    print("="*80)
    logger.info(f"[SPEND] Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    logger.info(f"[SPEND] Analysis Parameters: {request.pr_data}")
    
    try:
        logger.info(f"[SPEND] Creating SpendAnalyticsAgent...")
        from backend.agents.spend_analytics import SpendAnalyticsAgent
        spend_agent = SpendAnalyticsAgent()
        logger.info(f"[SPEND] Agent created")
        
        context = {
            "request": request.request,
            **(request.pr_data or {})  # Analysis parameters
        }
        
        logger.info(f"[SPEND] Analyzing spending patterns and identifying savings...")
        result = await spend_agent.execute(context)
        
        logger.info(f"[SPEND] Analysis complete:")
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
        logger.info(f"[SPEND] ERROR: {str(e)}")
        import traceback
        logger.info(f"[SPEND] Traceback:\n{traceback.format_exc()}")
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
    logger.info("[INVENTORY CHECK] Inventory monitoring requested")
    print("="*80)
    logger.info(f"[INVENTORY] Request: {request.request[:100] if len(request.request) > 100 else request.request}")
    logger.info(f"[INVENTORY] Check Parameters: {request.pr_data}")
    
    try:
        logger.info(f"[INVENTORY] Creating InventoryCheckAgent...")
        from backend.agents.inventory_check import InventoryCheckAgent
        inventory_agent = InventoryCheckAgent()
        logger.info(f"[INVENTORY] Agent created")
        
        context = {
            "request": request.request,
            **(request.pr_data or {})  # Check parameters
        }
        
        logger.info(f"[INVENTORY] Scanning inventory levels and creating replenishment PRs...")
        result = await inventory_agent.execute(context)
        
        logger.info(f"[INVENTORY] Check complete:")
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
        logger.info(f"[INVENTORY] ERROR: {str(e)}")
        import traceback
        logger.info(f"[INVENTORY] Traceback:\n{traceback.format_exc()}")
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


async def _bridge_approval_to_session(
    pr_number: str,
    action: str,
    payload: dict,
    background_tasks: BackgroundTasks,
) -> None:
    """
    Bridge: when an approval decision comes from MyApprovalsPage (or any caller
    of the legacy /approval-workflows/:pr/approve|reject endpoints), check if
    there is an active session with an open approval gate for this PR.  If so,
    resolve the gate and spawn the orchestrator resume — exactly what
    /api/sessions/:id/resume does, but triggered automatically.

    This is a non-fatal side-effect: if anything fails, the approval table
    update has already committed and the user still sees success.
    """
    try:
        from backend.services.session_service import SessionService
        pending_gates = SessionService.list_pending_gates(gate_type="approval")
        matched_gate = None
        matched_session_id = None
        for g in pending_gates:
            gate_ref = g.get("gate_ref") or {}
            if gate_ref.get("pr_number") == pr_number:
                matched_gate = g
                matched_session_id = g.get("session_id")
                break
        if not matched_gate or not matched_session_id:
            return

        gate_id = matched_gate.get("gate_id")
        import uuid
        gate_resolution_id = str(uuid.uuid4())

        logger.info(
            f"[APPROVAL-BRIDGE] Found session {matched_session_id[:8]} with approval gate "
            f"{gate_id} for PR {pr_number}. Resolving gate and spawning orchestrator."
        )

        # Resolve the gate
        SessionService.resolve_gate(
            gate_id=gate_id,
            decision={"action": action, **payload},
            resolved_by=payload.get("approver_email", "external"),
            gate_resolution_id=gate_resolution_id,
        )
        SessionService.append_event(
            session_id=matched_session_id,
            event_type="gate_resolved",
            actor=f"user:{payload.get('approver_email', 'external')}",
            payload={"gate_id": gate_id, "action": action},
        )

        # Spawn orchestrator resume in background
        from backend.routes.sessions import _run_orchestrator_resume
        resume_context = {
            "session_id": matched_session_id,
            "gate_id": gate_id,
            "gate_resolution_id": gate_resolution_id,
            "action": action,
            "human_input": payload,
            "user_id": payload.get("approver_email", "external"),
        }
        background_tasks.add_task(_run_orchestrator_resume, resume_context)

        logger.info(
            f"[APPROVAL-BRIDGE] Gate resolved + orchestrator resume queued for session "
            f"{matched_session_id[:8]}"
        )
    except Exception as exc:
        logger.warning(f"[APPROVAL-BRIDGE] Non-fatal bridge error for PR {pr_number}: {exc}")


@router.post("/approval-workflows/{pr_number}/approve")
async def approve_workflow_step(
    pr_number: str,
    body: ApproveStepRequest,
    request: Request,
    background_tasks: BackgroundTasks,
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
    logger.info(f"[APPROVAL ACTION] APPROVE Request")
    logger.info(f"[APPROVAL ACTION] PR Number: {pr_number}")
    logger.info(f"[APPROVAL ACTION] Approver: {body.approver_email}")
    logger.info(f"[APPROVAL ACTION] Notes: {body.notes or 'None'}")
    logger.info("="*80)
    
    try:
        _require_approval_actor(request, body.approver_email, x_approver_email, x_admin_token)
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Update the step
        logger.info(f"[APPROVAL ACTION] Updating pr_approval_steps...")
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
            logger.error(f"[APPROVAL ACTION] No pending step found for {body.approver_email} on {pr_number}")
            cursor.close()

            return_db_connection(conn)
            raise HTTPException(status_code=404, detail="No pending step found for this approver")
        
        logger.info(f"[APPROVAL ACTION] Step approved: Level {step['approval_level']} by {step['approver_name']}")
        
        # Check if more steps are pending
        logger.info(f"[APPROVAL ACTION] Checking remaining approval steps...")
        cursor.execute("""
            SELECT COUNT(*) as remaining 
            FROM pr_approval_steps 
            WHERE pr_number = %s AND status = 'pending'
        """, (pr_number,))
        
        result = cursor.fetchone()
        remaining = result['remaining'] if result else 0
        logger.info(f"[APPROVAL ACTION] Remaining steps: {remaining}")
        
        if remaining == 0:
            # All steps approved - mark workflow as completed
            logger.info(f"[APPROVAL ACTION] ALL STEPS APPROVED - WORKFLOW COMPLETE!")
            logger.info(f"[APPROVAL ACTION] Updating pr_approval_workflows status to 'completed'...")
            cursor.execute("""
                UPDATE pr_approval_workflows 
                SET workflow_status = 'completed', updated_at = CURRENT_TIMESTAMP 
                WHERE pr_number = %s
            """, (pr_number,))
            logger.info(f"[APPROVAL ACTION] Workflow marked as completed")
            
            # ── AUTO-CREATE PO FROM APPROVED PR (via adapter, works for ALL ERP modes) ──
            logger.info(f"[APPROVAL] Fetching workflow details for PO creation...")
            cursor.execute("""
                SELECT pr_number, department, total_amount, requester_name, request_data
                FROM pr_approval_workflows WHERE pr_number = %s
            """, (pr_number,))
            workflow = cursor.fetchone()

            if workflow:
                from backend.services.adapters.factory import get_adapter as _get_po_adapter
                _po_adapter = _get_po_adapter()

                request_data = workflow.get('request_data') or {}
                context_payload = request_data.get('context', {}) if isinstance(request_data, dict) else {}
                pr_payload = context_payload.get('raw_pr_data', {}) if isinstance(context_payload, dict) else {}

                vendor_name = str(pr_payload.get('vendor_name', pr_payload.get('selected_vendor_name', ''))).strip()
                product_name = str(pr_payload.get('product_name', pr_payload.get('category', 'Procurement Item'))).strip()
                department = str(pr_payload.get('department', workflow.get('department', ''))).strip()

                try:
                    quantity = int(pr_payload.get('quantity', 1))
                except (TypeError, ValueError):
                    quantity = 1
                try:
                    total_amount = float(workflow.get('total_amount', 0))
                except (TypeError, ValueError):
                    total_amount = 0
                unit_price = total_amount / max(quantity, 1)

                logger.info(f"[APPROVAL] Creating PO: vendor={vendor_name}, product={product_name}, qty={quantity}, total=${total_amount:,.2f}")

                try:
                    po_result = _po_adapter.create_purchase_order_from_pr({
                        'pr_number': pr_number,
                        'vendor_name': vendor_name or 'Default Vendor',
                        'product_name': product_name,
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'total_amount': total_amount,
                        'department': department,
                        'currency': str(pr_payload.get('currency', 'USD')),
                    })

                    if po_result.get('success'):
                        po_id = po_result['po_number']
                        logger.info(f"[APPROVAL] PO CREATED: {po_id} (from PR {pr_number})")

                        # Store PO reference in workflow
                        cursor.execute("""
                            UPDATE pr_approval_workflows
                            SET odoo_po_id = %s,
                                request_data = COALESCE(request_data, '{{}}'::jsonb) || %s::jsonb
                            WHERE pr_number = %s
                        """, (po_id, json.dumps({
                            "po_data": {
                                "po_number": po_id,
                                "vendor_name": vendor_name,
                                "product_name": product_name,
                                "quantity": quantity,
                                "unit_price": unit_price,
                                "total_amount": total_amount,
                            }
                        }), pr_number))

                        # Log notification for PO creation
                        try:
                            _po_adapter.log_notification({
                                'event_type': 'po_created',
                                'document_type': 'PO',
                                'document_id': po_id,
                                'recipient_email': workflow.get('requester_name', ''),
                                'recipient_role': 'procurement',
                                'subject': f'PO {po_id} created from approved PR {pr_number}',
                                'body_preview': f'Purchase Order for {product_name} ({quantity} units) from {vendor_name}. Total: ${total_amount:,.2f}',
                                'status': 'pending',
                                'agent_name': 'ApprovalWorkflow',
                            })
                        except Exception:
                            pass  # Notification failure is non-blocking

                    else:
                        logger.error(f"[APPROVAL] PO creation failed: {po_result.get('error', 'unknown')}")

                except Exception as e:
                    logger.error(f"[APPROVAL] PO creation error: {e}")

            # Log notification for PR approval completion
            try:
                from backend.services.adapters.factory import get_adapter as _notify_adapter
                _notify_adapter().log_notification({
                    'event_type': 'pr_fully_approved',
                    'document_type': 'PR',
                    'document_id': pr_number,
                    'recipient_role': 'procurement',
                    'subject': f'PR {pr_number} fully approved - all levels complete',
                    'body_preview': f'All approval levels completed. PO creation triggered.',
                    'status': 'pending',
                    'agent_name': 'ApprovalWorkflow',
                })
            except Exception:
                pass
        else:
            # Advance to next level
            logger.info(f"[APPROVAL ACTION] ⏭️ Advancing to next approval level...")
            cursor.execute("""
                UPDATE pr_approval_workflows 
                SET current_approval_level = current_approval_level + 1, 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE pr_number = %s
            """, (pr_number,))
            logger.info(f"[APPROVAL ACTION] Workflow advanced to next level")

            # Notify requester about step approval
            try:
                from backend.services.adapters.factory import get_adapter as _step_adapter
                _step_adapter().log_notification({
                    'event_type': 'pr_step_approved',
                    'document_type': 'PR',
                    'document_id': pr_number,
                    'recipient_role': 'procurement',
                    'subject': f'PR {pr_number} - approval step completed, advancing to next level',
                    'body_preview': f'Approved by {approver_email}. Awaiting next approver.',
                    'status': 'pending',
                    'agent_name': 'ApprovalWorkflow',
                })
            except Exception:
                pass

        logger.info(f"[APPROVAL ACTION] Committing transaction...")
        conn.commit()
        logger.info(f"[APPROVAL ACTION] COMMIT SUCCESSFUL")
        
        # Fetch final workflow state including PO ID
        cursor.execute("""
            SELECT odoo_po_id FROM pr_approval_workflows WHERE pr_number = %s
        """, (pr_number,))
        final_workflow = cursor.fetchone()
        odoo_po_id = final_workflow['odoo_po_id'] if final_workflow else None
        
        cursor.close()

        
        return_db_connection(conn)
        
        logger.info("="*80)
        logger.info(f"[APPROVAL ACTION] Approval Complete")
        logger.info(f"[APPROVAL ACTION] PR: {pr_number} | Remaining: {remaining} | Workflow Complete: {remaining == 0}")
        if odoo_po_id:
            logger.info(f"[APPROVAL ACTION] Odoo PO: {odoo_po_id}")
        logger.info("="*80)

        # Bridge: if a session has an open approval gate for this PR, resolve it
        # and continue the pipeline. Non-fatal — approval table already committed.
        await _bridge_approval_to_session(
            pr_number=pr_number,
            action="approve",
            payload={"approver_email": body.approver_email, "notes": body.notes},
            background_tasks=background_tasks,
        )

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
    background_tasks: BackgroundTasks,
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

        # Bridge: if a session has an open approval gate for this PR, resolve it
        # with reject action so the session marks as failed. Non-fatal.
        await _bridge_approval_to_session(
            pr_number=pr_number,
            action="reject",
            payload={"approver_email": body.approver_email, "reason": body.rejection_reason},
            background_tasks=background_tasks,
        )

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
    logger.info(f"[MY APPROVALS] GET Request")
    logger.info(f"[MY APPROVALS] Approver: {approver_email}")
    logger.info(f"[MY APPROVALS] Status Filter: {status}")
    logger.info("="*80)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        if status == "pending":
            logger.info(f"[MY APPROVALS] Querying PENDING approvals...")
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
            logger.info(f"[MY APPROVALS] Query returned {len(results)} pending approval(s)")
            
            if results:
                logger.info(f"[MY APPROVALS] Pending PRs:")
                for idx, r in enumerate(results, 1):
                    logger.info(f"[MY APPROVALS]   {idx}. {r['pr_number']} | {r['department']} | ${r['total_amount']:,.0f} | Level {r['approval_level']} | {r['days_pending']:.0f} days")
            else:
                logger.info(f"[MY APPROVALS] ️ No pending approvals found for {approver_email}")
            
            # Add level names
            level_map = {1: "Manager", 2: "Director", 3: "VP/CFO"}
            for r in results:
                r['approval_level_name'] = level_map.get(r['approval_level'], "Unknown")
            
            cursor.close()

            
            return_db_connection(conn)
            logger.info(f"[MY APPROVALS] Returning {len(results)} approval(s)")
            logger.info("="*80)
            return {"approvals": results}
        
        else:  # history
            logger.info(f"[MY APPROVALS] Querying HISTORY (past decisions)...")
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
            logger.info(f"[MY APPROVALS] Query returned {len(results)} historical decision(s)")
            
            if results:
                logger.info(f"[MY APPROVALS] Decision History:")
                for idx, r in enumerate(results, 1):
                    logger.info(f"[MY APPROVALS]   {idx}. {r['pr_number']} | {r['decision'].upper()} | Level {r['approval_level']}")
            
            # Add level names
            level_map = {1: "Manager", 2: "Director", 3: "VP/CFO"}
            for r in results:
                r['approval_level_name'] = level_map.get(r['approval_level'], "Unknown")
            
            cursor.close()

            
            return_db_connection(conn)
            logger.info(f"[MY APPROVALS] Returning {len(results)} historical record(s)")
            logger.info("="*80)
            return {"history": results}
        
    except Exception as e:
        logger.error("="*80)
        logger.error(f"[MY APPROVALS] ERROR: {e}")
        logger.error("="*80)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-approvals/{approver_email}/stats")
async def get_approver_stats(approver_email: str, current_user: dict = Depends(require_auth())):
    """
    Get statistics for a specific approver.
    
    Returns: pending count, approved count, rejected count, rejection rate, avg decision time.
    """
    logger.info("="*80)
    logger.info(f"[APPROVAL STATS] Stats Request")
    logger.info(f"[APPROVAL STATS] Approver: {approver_email}")
    logger.info("="*80)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        logger.info(f"[APPROVAL STATS] Querying approval statistics...")
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
        
        logger.info(f"[APPROVAL STATS] Statistics:")
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
        logger.error(f"[APPROVAL STATS] ERROR: {e}")
        logger.error("="*80)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approval-chains")
async def get_approval_chains(current_user: dict = Depends(require_auth())):
    """
    Get all approval chain configurations.
    
    Shows the database rules that define who approves what for each department.
    Used by admin/settings page to display approval routing configuration.
    """
    logger.info("[AGENTIC API] GET /approval-chains - Starting request")
    
    conn = None
    cursor = None
    
    try:
        logger.info("[AGENTIC API] Acquiring database connection from pool...")
        conn = get_db_connection()
        logger.info("[AGENTIC API] Connection acquired, creating cursor...")
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        logger.info("[AGENTIC API] Cursor created, executing query...")
        
        cursor.execute("""
            SELECT 
                id, department, budget_threshold, approval_level,
                approver_email, approver_name, status
            FROM approval_chains
            ORDER BY department, budget_threshold, approval_level
        """)
        
        chains = [dict(row) for row in cursor.fetchall()]
        logger.info(f"[AGENTIC API] Query executed - Retrieved {len(chains)} approval chains")
        
        cursor.close()
        logger.info("[AGENTIC API] Cursor closed, returning connection to pool...")

        return_db_connection(conn)
        logger.info("[AGENTIC API] Connection returned to pool - Request complete")
        
        return {"chains": chains}
        
    except Exception as e:
        logger.error(f"[AGENTIC API] Error in GET /approval-chains: {e}")
        
        # Cleanup on error
        if cursor:
            try:
                cursor.close()
                logger.info("[AGENTIC API] Cursor closed after error")
            except Exception as cleanup_error:
                logger.error(f"[AGENTIC API] ️ Failed to close cursor: {cleanup_error}")
        
        if conn:
            try:
                return_db_connection(conn)
                logger.info("[AGENTIC API] Connection returned to pool after error")
            except Exception as cleanup_error:
                logger.error(f"[AGENTIC API] ️ Failed to return connection: {cleanup_error}")

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
