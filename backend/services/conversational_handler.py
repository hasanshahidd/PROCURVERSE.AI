"""
Simple Conversational Handler for General Queries
Replaces legacy 550-line openai_client.py (moved to archive Feb 24, 2026)

This handles:
- Greetings (hi, hello, hey)
- Help requests (what can you do, help me)
- System information
- Query suggestions (autocomplete)
- SQL validation (for legacy endpoints)
"""

import re
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# Pre-defined responses for common queries
GREETING_RESPONSES = {
    "greeting": """👋 Hello! I'm your AI procurement assistant.

I can help you with:
- 💰 **Budget Verification**: "Can Finance afford $50,000?"
- 📋 **Approval Routing**: "Who needs to approve a $75,000 IT purchase?"
- 📦 **Purchase Orders**: "Show pending purchase orders"
- 🏢 **Vendors**: "List all active vendors"
- 📊 **Budget Status**: "Show IT department budget for 2026"

Try asking me about budgets, approvals, or purchase orders!""",
    
    "help": """🔍 **What I Can Do:**

**Autonomous Actions** (AI Agents):
- Verify budgets and reserve funds
- Route purchase requisitions through approval chains
- Check budget availability before purchases
- Assign appropriate approvers based on amount/department

**Data Queries**:
- View purchase orders from Odoo ERP
- Check vendor and product catalogs
- Display budget status for departments
- Show approval chain rules

**Examples**:
- "Verify IT budget for $30,000 CAPEX and reserve the amount"
- "Route PR-2026-0100 for $55,000 in Finance to required approvers"
- "Show all pending purchase orders"
- "List approval chain for Operations department"

Just ask naturally - I'll understand! 🚀""",
    
    "capabilities": """🤖 **System Capabilities:**

**Data Sources**:
- Odoo ERP (17 purchase orders, vendors, products)
- Custom budget tracking (4 departments: IT, Finance, Operations, Procurement)
- Multi-level approval chains (Manager → Director → VP/CFO)
- Real-time agent action logs

**AI Agents**:
- BudgetVerificationAgent: Checks/commits budgets (80%, 90%, 95% alerts)
- ApprovalRoutingAgent: Routes PRs based on amount thresholds
- Orchestrator: Coordinates multi-agent workflows

**Languages**: English, Urdu, Arabic (RTL support)

Try asking: "Verify Finance budget for $25,000 OPEX and route to approvers" """
}


def handle_general_query(message: str, language: str = "en", history: list = None) -> dict:
    """
    Handle general conversational queries (greetings, help).
    
    Args:
        message: User's message
        language: Language code (en/ur/ar)
        history: Conversation history (unused - stateless responses)
    
    Returns:
        dict with response, sql=None, data=[]
    """
    
    message_lower = message.lower().strip()
    
    # Detect greetings
    if re.match(r'^(hi|hello|hey|good morning|good afternoon|good evening|greetings|hola|namaste)[\s!.?]*$', message_lower):
        return {
            "response": GREETING_RESPONSES["greeting"],
            "explanation": GREETING_RESPONSES["greeting"],
            "sql": None,
            "data": []
        }
    
    # Detect help requests
    if any(keyword in message_lower for keyword in ['help', 'what can you do', 'how to use', 'guide', 'assist me']):
        return {
            "response": GREETING_RESPONSES["help"],
            "explanation": GREETING_RESPONSES["help"],
            "sql": None,
            "data": []
        }
    
    # Detect capability questions
    if any(keyword in message_lower for keyword in ['capabilities', 'features', 'what do you know', 'what data', 'available']):
        return {
            "response": GREETING_RESPONSES["capabilities"],
            "explanation": GREETING_RESPONSES["capabilities"],
            "sql": None,
            "data": []
        }
    
    # Fallback: Use LLM for truly conversational queries
    # (Questions like "How's the weather?" that don't fit data queries)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """You are a friendly procurement assistant.

The user asked a general question that doesn't require data access.

Respond helpfully and suggest they ask about:
- Budget verification
- Approval routing
- Purchase orders
- Vendor information
- Budget status

Keep responses brief and friendly."""},
                {"role": "user", "content": message}
            ],
            temperature=0.7,
            max_tokens=200
        )
        
        explanation = response.choices[0].message.content
        
        return {
            "response": explanation,
            "explanation": explanation,
            "sql": None,
            "data": []
        }
    except Exception as e:
        # If LLM fails, provide generic helpful response
        return {
            "response": "I can help you with procurement data! Try asking about budgets, approvals, purchase orders, or vendors.",
            "explanation": "I can help you with procurement data! Try asking about budgets, approvals, purchase orders, or vendors.",
            "sql": None,
            "data": [],
            "error": str(e)
        }


def generate_query_suggestions(partial_input: str, language: str = "en", conversation_context: list = None) -> list:
    """
    Generate smart query suggestions based on partial input.
    Agentic-aware autocomplete (no SQL, focuses on budget/approval/Odoo queries).
    
    Args:
        partial_input: What user is typing
        language: Language code (currently unused - suggestions in English)
        conversation_context: Recent queries (currently unused)
    
    Returns:
        List of 3-5 completion suggestions
    """
    
    partial = partial_input.lower().strip()
    
    # Budget-related suggestions
    if any(word in partial for word in ['budget', 'verify', 'check', 'afford', 'available', 'reserve']):
        return [
            "Verify IT budget for $30,000 CAPEX and reserve the amount",
            "Check Finance department budget status for 2026",
            "Show Operations OPEX budget availability",
            "Can IT afford $50,000 for new servers?",
            "Reserve $25,000 from Procurement budget"
        ]
    
    # Approval-related suggestions
    if any(word in partial for word in ['approve', 'approval', 'route', 'approver', 'chain', 'pr-']):
        return [
            "Route PR-2026-0100 for $40,000 in Finance to required approvers",
            "Who needs to approve a $75,000 IT purchase?",
            "Show approval chain for Operations department",
            "Route PR for $15,000 in Procurement",
            "Get approvers for Finance purchase above $50K"
        ]
    
    # Purchase order suggestions
    if any(word in partial for word in ['purchase', 'po', 'order', 'pending', 'show']):
        return [
            "Show all pending purchase orders",
            "List purchase orders from IT department",
            "Show completed purchase orders from last month",
            "Display purchase orders over $100,000",
            "Show recent purchase orders from Finance"
        ]
    
    # Vendor suggestions
    if any(word in partial for word in ['vendor', 'supplier', 'company', 'partner']):
        return [
            "List all active vendors",
            "Show vendors for IT equipment",
            "Find vendors with high ratings",
            "Display supplier performance reports",
            "Show vendors for Finance services"
        ]
    
    # Department-specific suggestions
    if 'it' in partial or 'information' in partial or 'technology' in partial:
        return [
            "Show IT department budget for 2026",
            "Verify IT budget for $30,000 CAPEX",
            "Who approves IT purchases over $50K?",
            "List approval chain for IT department",
            "Show IT purchase orders this quarter"
        ]
    
    if 'finance' in partial or 'financial' in partial:
        return [
            "Show Finance department budget status",
            "Verify Finance OPEX budget for $40,000",
            "Who approves Finance purchases above $10K?",
            "List Finance approval chain",
            "Show Finance budget utilization"
        ]
    
    if 'operations' in partial or 'ops' in partial:
        return [
            "Show Operations department budget",
            "Verify Operations budget for $20,000",
            "Who approves Operations purchases?",
            "List Operations approval levels",
            "Check Operations CAPEX availability"
        ]
    
    # Default general suggestions
    return [
        "Verify IT budget for $30,000 and reserve the amount",
        "Route PR for $50,000 in Finance to required approvers",
        "Show all pending purchase orders",
        "List active vendors and suppliers",
        "Show IT department budget status for 2026"
    ]


def validate_sql(sql: str) -> bool:
    """
    Validate SQL query for security.
    Only allows SELECT queries against the known procurement table allowlist.

    Note: This is for the legacy `/query` endpoint. New system doesn't generate SQL.
    """
    if not sql or not isinstance(sql, str):
        return False

    # Remove SQL comments before analysis
    normalized = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    normalized = re.sub(r'/\*.*?\*/', '', normalized, flags=re.DOTALL)
    normalized = ' '.join(normalized.split()).lower().strip()

    # Must start with SELECT
    if not normalized.startswith("select"):
        return False

    # Block multiple statements (prevents stacked injection)
    if ";" in normalized and normalized.index(";") < len(normalized) - 1:
        return False

    # Block UNION — prevents cross-table data exfiltration
    if re.search(r'\bunion\b', normalized):
        return False

    # Block all dangerous keywords and functions
    forbidden = [
        "drop", "delete", "update", "insert", "alter", "truncate",
        "create", "grant", "revoke", "exec", "call", "copy",
        "pg_", "information_schema", "pg_catalog",
        "sleep", "waitfor", "delay",  # timing-based injection
        "load_file", "into outfile", "into dumpfile",  # file exfiltration
        "current_user", "session_user", "current_database",  # reconnaissance
        "dblink", "lo_import", "lo_export",  # PostgreSQL-specific attacks
    ]
    for keyword in forbidden:
        if keyword in normalized:
            return False

    # Allowlist: only permit queries against known procurement tables
    allowed_tables = {
        "procurement_records", "chat_messages", "agent_actions", "agent_decisions",
        "approval_chains", "budget_tracking", "pending_approvals",
        "pr_approval_workflows", "pr_approval_steps", "po_risk_assessments",
        # Sprint 1 NMI tables
        "vendors", "items", "chart_of_accounts", "cost_centers", "employees",
        "exchange_rates", "uom_master", "tax_codes", "payment_terms",
        "warehouses", "companies", "buyers",
        "purchase_requisitions", "approved_supplier_list", "vendor_evaluations",
        "rfq_headers", "vendor_quotes", "quote_comparisons", "contracts",
        "po_headers", "po_line_items", "po_amendments", "po_approval_log",
        "blanket_pos", "grn_headers", "grn_line_items", "qc_inspection_log",
        "returns_to_vendor", "vendor_invoices", "invoice_line_items",
        "three_way_match_log", "invoice_exceptions", "invoice_approval_log",
        "payment_proposals", "payment_runs", "payment_holds",
        "early_payment_discounts", "ap_aging",
        "spend_analytics", "budget_vs_actuals", "vendor_performance",
        "duplicate_invoice_log", "audit_trail", "workflow_approval_matrix",
        "integration_transaction_log",
    }
    # Extract table names referenced in the query (after FROM / JOIN)
    table_refs = re.findall(r'\b(?:from|join)\s+([a-z_][a-z0-9_]*)', normalized)
    for ref in table_refs:
        if ref not in allowed_tables:
            return False

    return True
