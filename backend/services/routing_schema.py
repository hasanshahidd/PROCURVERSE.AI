"""
Shared routing schema and normalization helpers.

This module keeps routing enums and normalization logic centralized so
classifier, chat, and agentic routes cannot drift.
"""

from typing import Any, Dict

ALLOWED_DATA_SOURCES = {
    "odoo",
    "agentic",
    "approval_chains",
    "budget_tracking",
    "agent_history",
    "general",
}


def normalize_source_hint(value: str) -> str:
    hint = (value or "").strip().lower()
    if "odoo" in hint:
        return "odoo"
    if "agent" in hint:
        return "agentic"
    if "budget" in hint:
        return "budget_tracking"
    if "approval" in hint:
        return "approval_chains"
    return hint


def normalize_odoo_query_type(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"vendors", "vendor", "suppliers", "supplier"}:
        return "vendors"
    if normalized in {"products", "product", "items", "item", "catalog"}:
        return "products"
    return "purchase_orders"


def _normalize_data_source(value: Any) -> str:
    raw = str(value or "general").strip().lower()
    if raw in ALLOWED_DATA_SOURCES:
        return raw
    return normalize_source_hint(raw) or "general"


def _normalize_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    if confidence < 0.0:
        return 0.0
    if confidence > 1.0:
        return 1.0
    return confidence


def normalize_classification_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize classifier output into a stable contract shape."""
    result = dict(payload or {})
    data_source = _normalize_data_source(result.get("data_source"))
    query_type = str(result.get("query_type") or "GENERAL")
    filters = result.get("filters", {})

    if not isinstance(filters, dict):
        filters = {}

    if data_source == "odoo":
        query_type = normalize_odoo_query_type(query_type)

    result["data_source"] = data_source
    result["query_type"] = query_type
    result["filters"] = filters
    result["confidence"] = _normalize_confidence(result.get("confidence", 0.5))
    return result
