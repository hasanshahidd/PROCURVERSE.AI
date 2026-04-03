"""
Centralized LLM routing guidance for classifier and orchestrator.

This keeps module-selection logic in one place so behavior is consistent
across chat, agentic execute, and streaming flows.
"""

from typing import Dict

MODULE_GUIDE: Dict[str, Dict[str, str]] = {
    "budget_verification": {
        "when": "User asks affordability, budget availability, reservation, or budget threshold impact.",
        "signals": "can we afford, within budget, reserve funds, budget status for a request",
        "query_type": "BUDGET",
    },
    "approval_routing": {
        "when": "User asks who should approve, approval path, or routing by amount/department.",
        "signals": "who approves, approval chain, route this request",
        "query_type": "APPROVAL",
    },
    "vendor_selection": {
        "when": "User asks to choose the best supplier/vendor.",
        "signals": "best vendor, recommend supplier, choose vendor",
        "query_type": "VENDOR",
    },
    "risk_assessment": {
        "when": "User asks for procurement risk analysis or safety assessment.",
        "signals": "risky, risk analysis, what could go wrong",
        "query_type": "RISK",
    },
    "contract_monitoring": {
        "when": "User asks about contract expiry, renewals, or contract health.",
        "signals": "contract renewal, expiring contract, contract status",
        "query_type": "CONTRACT",
    },
    "supplier_performance": {
        "when": "User asks about supplier performance/KPIs over time.",
        "signals": "supplier performance, on-time delivery, quality score",
        "query_type": "PERFORMANCE",
    },
    "price_analysis": {
        "when": "User asks whether quoted price is fair/competitive.",
        "signals": "is this price fair, compare quote, negotiation",
        "query_type": "PRICE",
    },
    "compliance_check": {
        "when": "User asks if a request complies with policy/regulation.",
        "signals": "policy check, compliant, allowed",
        "query_type": "COMPLIANCE",
    },
    "invoice_matching": {
        "when": "User asks to validate invoice against PO/receipt.",
        "signals": "3-way match, match invoice, invoice variance",
        "query_type": "INVOICE",
    },
    "spend_analytics": {
        "when": "User asks for spending patterns/trends/savings opportunities.",
        "signals": "spend analysis, where money goes, savings opportunities",
        "query_type": "SPEND",
    },
    "inventory_check": {
        "when": "User asks about stock level, reorder, or replenishment needs.",
        "signals": "inventory level, low stock, reorder",
        "query_type": "INVENTORY",
    },
    "pr_creation": {
        "when": "User asks to create/raise/submit a purchase requisition.",
        "signals": "create PR, raise requisition, submit purchase request",
        "query_type": "CREATE",
    },
    "po_creation": {
        "when": "User asks to create a purchase order from approved inputs.",
        "signals": "create PO, issue purchase order",
        "query_type": "PO_CREATE",
    },
}


def build_module_selection_instructions() -> str:
    lines = [
        "Module-selection guide:",
        "Choose the module whose primary business outcome best matches the user request.",
    ]
    for module_name, spec in MODULE_GUIDE.items():
        lines.append(
            f"- {module_name}: when={spec['when']} signals={spec['signals']} query_type={spec['query_type']}"
        )
    return "\n".join(lines)


def build_classifier_instructions() -> str:
    return (
        "Classify the user request for procurement routing.\n"
        "Return only JSON with keys: intents (array), confidence.\n"
        "Each intent in 'intents' must have: data_source, query_type, filters.\n"
        "Use semantic intent, not keyword forcing.\n"
        "For pure record retrieval use data_source=odoo.\n"
        "For reasoning/decision support use data_source=agentic.\n"
        "For data_source=odoo, query_type MUST be exactly one of: purchase_orders, vendors, products.\n"
        "If querying purchase orders, include filters.state/amount_min/amount_max when clearly requested.\n"
        "If querying vendors/products, set query_type accordingly and avoid defaulting to purchase_orders.\n"
        "\n"
        "MULTI-INTENT SUPPORT:\n"
        "If the user request contains MULTIPLE distinct actions (e.g., 'check budget AND route approval'),\n"
        "return MULTIPLE intents in the intents array, ordered by execution sequence.\n"
        "Each intent should be independent and executable.\n"
        "If the user references MULTIPLE departments/entities (e.g., 'IT needs X and Finance needs Y — do Z for both'),\n"
        "create SEPARATE intents for EACH department. 'For both' means duplicate the requested actions per entity.\n"
        "\n"
        "SINGLE-INTENT RULES (do NOT over-split):\n"
        "- When 'budget' appears as a CONSTRAINT/LIMIT for another action (not a standalone question),\n"
        "  keep it as ONE intent. Budget in filters, not a separate BUDGET intent.\n"
        "  Example: 'Find best vendor for electronics under $50000' → 1 intent: VENDOR with filters {category:'Electronics', amount:50000}\n"
        "  Example: 'Recommend vendor, budget 30k' → 1 intent: VENDOR with filters {amount:30000}\n"
        "- Only create a BUDGET intent when the user explicitly asks about budget availability/status.\n"
        "  Example: 'Check budget for IT' → 1 intent: BUDGET\n"
        "  Example: 'Find vendor AND check budget' → 2 intents: VENDOR + BUDGET (explicit 'check budget')\n"
        "\n"
        "CRITICAL — CREATE vs analysis intents:\n"
        "- 'buy', 'purchase', 'need to order' ALONE means CREATE (pr_creation).\n"
        "- But if the user ALSO says 'check budget', 'assess risk', 'route approval', etc., those are\n"
        "  SEPARATE analysis intents (BUDGET, RISK, APPROVAL). Do NOT wrap them as CREATE.\n"
        "- Example: 'I need to buy servers. Check budget, assess risks, route approval' → 3 intents:\n"
        "  BUDGET + RISK + APPROVAL (NOT 3 × CREATE).\n"
        "- Only use CREATE when the user's primary goal is to actually create/submit a PR.\n"
        "\n"
        "CRITICAL — ROUTE vs CREATE:\n"
        "- 'Route' / 'Route approval for' / 'Route this PR' → APPROVAL (just routing, not creating).\n"
        "- 'Create' / 'Submit' / 'Raise a new PR' → CREATE (full creation pipeline).\n"
        "- 'Route a new purchase request' → APPROVAL (the word 'route' dominates over 'purchase request').\n"
        "- 'Route PR-2026-XXXX' → APPROVAL (routing an existing PR).\n"
        "\n"
        "FILTERS EXTRACTION GUIDE:\n"
        "- ALWAYS extract amount/budget from phrases like '20k', '$50k', '100,000'\n"
        "- ALWAYS extract category from product types: 'Electronics', 'Office Supplies', 'Furniture', 'IT Hardware'\n"
        "- ALWAYS extract department if mentioned: 'IT', 'Finance', 'Operations', 'Procurement'\n"
        "- ALWAYS extract pr_number if mentioned: 'PR-2026-0200', 'PR-2026-0001'\n"
        "- ALWAYS extract urgency if mentioned: 'critical', 'high', 'medium', 'low'\n"
        "- ALWAYS extract vendor/vendor_name if mentioned: 'TechSupply Co', 'Office Depot LLC', etc.\n"
        "- ALWAYS extract budget_category if mentioned: 'OPEX', 'CAPEX'\n"
        "- ALWAYS extract requester_name if mentioned: 'requester: John Smith', 'requested by Jane Doe', 'for Alice'\n"
        "- ALWAYS extract justification if a reason or justification is provided\n"
        "- For vendor selection, category is CRITICAL - extract from context like 'Electronics vendor', 'Office Supplies supplier'\n"
        "\n"
        "Examples:\n"
        "- 'show current purchase orders' -> {intents:[{data_source:'odoo', query_type:'purchase_orders', filters:{}}]}\n"
        "- 'show cancelled purchase orders' -> {intents:[{data_source:'odoo', query_type:'purchase_orders', filters:{state:'cancel'}}]}\n"
        "- 'show vendors' -> {intents:[{data_source:'odoo', query_type:'vendors', filters:{}}]}\n"
        "- 'list products' -> {intents:[{data_source:'odoo', query_type:'products', filters:{}}]}\n"
        "- 'check budget and route approval for 75k IT purchase' -> {intents:[{data_source:'agentic', query_type:'BUDGET', filters:{department:'IT',amount:75000}}, {data_source:'agentic', query_type:'APPROVAL', filters:{department:'IT',amount:75000}}]}\n"
        "- 'Find best vendor for Electronics' -> {intents:[{data_source:'agentic', query_type:'VENDOR', filters:{category:'Electronics'}}]}\n"
        "- 'Find best vendor for electronics under $50000' -> {intents:[{data_source:'agentic', query_type:'VENDOR', filters:{category:'Electronics', amount:50000}}]}\n"
        "- 'Recommend vendor for office supplies, budget 30k' -> {intents:[{data_source:'agentic', query_type:'VENDOR', filters:{category:'Office Supplies', amount:30000}}]}\n"
        "- 'Find best vendor, check budget, and route approval for 20k Electronics' -> {intents:[{data_source:'agentic', query_type:'VENDOR', filters:{amount:20000,category:'Electronics'}}, {data_source:'agentic', query_type:'BUDGET', filters:{amount:20000,category:'Electronics'}}, {data_source:'agentic', query_type:'APPROVAL', filters:{amount:20000,category:'Electronics'}}]}\n"
        "- 'I need to buy 75k servers for IT. Check budget, assess risks, route approval' -> {intents:[{data_source:'agentic', query_type:'BUDGET', filters:{department:'IT',amount:75000}}, {data_source:'agentic', query_type:'RISK', filters:{department:'IT',amount:75000}}, {data_source:'agentic', query_type:'APPROVAL', filters:{department:'IT',amount:75000}}]}\n"
        "- 'Create a purchase request for IT department, $60000 servers' -> {intents:[{data_source:'agentic', query_type:'CREATE', filters:{department:'IT',amount:60000,category:'IT Hardware'}}]}\n"
        "- 'Submit a PR for Operations, $25000 office furniture' -> {intents:[{data_source:'agentic', query_type:'CREATE', filters:{department:'Operations',amount:25000,category:'Furniture'}}]}\n"
        "- 'Route a new purchase request for Finance department, $120000 CAPEX' -> {intents:[{data_source:'agentic', query_type:'APPROVAL', filters:{department:'Finance',amount:120000,budget_category:'CAPEX'}}]}\n"
        "- 'Route PR-2026-0700 for Operations, $45000' -> {intents:[{data_source:'agentic', query_type:'APPROVAL', filters:{pr_number:'PR-2026-0700',department:'Operations',amount:45000}}]}\n"
        "- 'IT needs $42 for supplies and Finance needs $38 for electronics - check budget, risk, and recommend vendor for both' -> {intents:[{data_source:'agentic', query_type:'BUDGET', filters:{department:'IT',amount:42,category:'Office Supplies'}}, {data_source:'agentic', query_type:'RISK', filters:{department:'IT',amount:42,category:'Office Supplies'}}, {data_source:'agentic', query_type:'VENDOR', filters:{department:'IT',amount:42,category:'Office Supplies'}}, {data_source:'agentic', query_type:'BUDGET', filters:{department:'Finance',amount:38,category:'Electronics'}}, {data_source:'agentic', query_type:'RISK', filters:{department:'Finance',amount:38,category:'Electronics'}}, {data_source:'agentic', query_type:'VENDOR', filters:{department:'Finance',amount:38,category:'Electronics'}}]}\n\n"
        + build_module_selection_instructions()
    )
