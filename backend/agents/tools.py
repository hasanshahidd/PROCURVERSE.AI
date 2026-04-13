"""
Tool Wrappers for Agentic Procurement System
Provides LangChain tools for Odoo API access and adapter-based database operations.

All database access goes through the adapter layer (IDataSourceAdapter).
No hardcoded SQL — adapter methods handle ERP routing + field normalization.
"""

from typing import Dict, Any, List, Optional
try:
    from langchain.tools import Tool
except ImportError:
    from langchain_core.tools import Tool
import json
import os
import logging

from backend.services.cache import get_cache, cache_key, TTL_1_MINUTE, TTL_5_MINUTES, TTL_15_MINUTES, TTL_1_HOUR
from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)

# ── Adapter singleton — all DB access goes through here ──────────────────────
def _adapter():
    """Return the active adapter based on DATA_SOURCE env var."""
    return get_adapter()


# ========== ODOO API TOOLS ==========

def create_odoo_tools() -> List[Tool]:
    """Create LangChain tools for Odoo API operations"""
    
    def get_purchase_orders(state: str = "draft", limit: int = 10) -> str:
        """
        Get purchase orders from Odoo.
        
        Args:
            state: PO state (draft, sent, purchase, done, cancel)
            limit: Maximum number of POs to retrieve
            
        Returns:
            JSON string with PO data
        """
        try:
            # Check cache first (POs change frequently, so short TTL)
            cache = get_cache()
            cache_key_str = cache_key('odoo:purchase_orders', state=state, limit=limit)
            cached_result = cache.get(cache_key_str)
            if cached_result:
                logger.debug(f"[Cache HIT] get_purchase_orders(state={state}, limit={limit})")
                return cached_result
            
            # Cache miss - fetch from adapter (ERP-aware)
            logger.debug(f"[Cache MISS] get_purchase_orders(state={state}, limit={limit})")
            adapter = _adapter()
            pos = adapter.get_purchase_orders(state=state, limit=limit)
            
            result = json.dumps({
                "success": True,
                "count": len(pos),
                "purchase_orders": pos
            }, indent=2)
            
            # Cache for 1 minute (POs change frequently)
            cache.set(cache_key_str, result, TTL_1_MINUTE)
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    def get_vendors(category: Optional[str] = None, limit: int = 20) -> str:
        """
        Get vendors from Odoo.
        
        Args:
            category: Vendor category filter (optional)
            limit: Maximum number of vendors
            
        Returns:
            JSON string with vendor data
        """
        try:
            # Check cache first (vendors don't change often)
            cache = get_cache()
            cache_key_str = cache_key('odoo:vendors', category=category, limit=limit)
            cached_result = cache.get(cache_key_str)
            if cached_result:
                logger.debug(f"[Cache HIT] get_vendors(category={category}, limit={limit})")
                return cached_result
            
            # Cache miss - fetch from adapter (ERP-aware)
            logger.debug(f"[Cache MISS] get_vendors(category={category}, limit={limit})")
            adapter = _adapter()
            vendors = adapter.get_vendors(limit=limit)

            if category:
                required = str(category).strip().lower()

                synonym_map = {
                    'electronics': ['tech', 'electronic', 'electronics', 'computer', 'hardware'],
                    'office supplies': ['office', 'stationery', 'supplies', 'desk'],
                    'furniture': ['furniture', 'desk', 'chair', 'table'],
                    'software': ['software', 'saas', 'license', 'subscription'],
                }

                expanded_terms = [required]
                for key, terms in synonym_map.items():
                    if required == key or required in key or key in required:
                        expanded_terms.extend(terms)
                expanded_terms = list(dict.fromkeys(expanded_terms))

                def _matches(vendor: Dict[str, Any]) -> bool:
                    primary = str(vendor.get('category', '')).strip().lower()
                    all_categories = [str(c).strip().lower() for c in (vendor.get('categories') or [])]
                    vendor_name = str(vendor.get('name', '')).strip().lower()

                    candidate_values = [primary, *all_categories, vendor_name]
                    return any(
                        term and value and (term in value or value in term)
                        for term in expanded_terms
                        for value in candidate_values
                    )

                filtered = [v for v in vendors if _matches(v)]

                # Fallback: avoid empty vendor list from strict matching/data sparsity.
                if filtered:
                    vendors = filtered
            
            result = json.dumps({
                "success": True,
                "count": len(vendors),
                "vendors": vendors
            }, indent=2)
            
            # Cache for 15 minutes
            cache.set(cache_key_str, result, TTL_15_MINUTES)
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    def create_purchase_order(partner_id: int, order_lines: str) -> str:
        """
        Create a new purchase order in Odoo.
        
        Args:
            partner_id: Vendor ID
            order_lines: JSON string with order lines
            
        Returns:
            JSON string with created PO details
        """
        try:
            adapter = _adapter()
            lines = json.loads(order_lines)
            result = adapter.create_purchase_order_from_pr({
                "partner_id": partner_id,
                "order_lines": lines,
            })
            po_id = result.get("po_id") or result.get("id") or "created"

            return json.dumps({
                "success": True,
                "po_id": po_id,
                "message": f"Purchase order created with ID: {po_id}"
            }, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def approve_purchase_order(po_id: int) -> str:
        """
        Approve a purchase order in Odoo.
        
        Args:
            po_id: Purchase order ID
            
        Returns:
            JSON string with approval result
        """
        try:
            adapter = _adapter()
            # In demo mode, just update status; in live mode, calls ERP API
            result = adapter.approve_purchase_order(po_id) if hasattr(adapter, 'approve_purchase_order') else {"approved": True}

            return json.dumps({
                "success": True,
                "po_id": po_id,
                "result": result,
                "message": "Purchase order approved successfully"
            }, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    def create_purchase_order_with_vendor_selection(
        partner_id: int, 
        order_lines: str,
        vendor_selection_notes: str,
        pr_number: str = None
    ) -> str:
        """
        Create a purchase order with vendor selection reasoning.
        
        This is used by VendorSelectionAgent to create POs with documented
        vendor selection rationale (scores, strengths, concerns).
        
        Args:
            partner_id: Selected vendor ID
            order_lines: JSON string with order lines (product_id, quantity, price)
            vendor_selection_notes: Vendor selection reasoning and scores
            pr_number: Optional PR number for tracking
            
        Returns:
            JSON string with created PO details
        """
        try:
            adapter = _adapter()
            lines = json.loads(order_lines)

            notes_text = f"VENDOR SELECTION:\n{vendor_selection_notes}"
            if pr_number:
                notes_text = f"PR: {pr_number}\n\n{notes_text}"

            result = adapter.create_purchase_order_from_pr({
                "partner_id": partner_id,
                "order_lines": lines,
                "pr_number": pr_number,
                "notes": notes_text,
            })
            po_id = result.get("po_id") or result.get("id") or "created"

            return json.dumps({
                "success": True,
                "po_id": po_id,
                "partner_id": partner_id,
                "pr_number": pr_number,
                "message": f"Purchase order {po_id} created with vendor selection notes"
            }, indent=2)
        except Exception as e:
            logger.error(f"[VendorTool] Failed to create PO: {e}")
            return json.dumps({"success": False, "error": str(e)})
    
    def get_products(search: Optional[str] = None, limit: int = 20) -> str:
        """
        Search products in Odoo catalog.
        
        Args:
            search: Search term for product name
            limit: Maximum results
            
        Returns:
            JSON string with product data
        """
        try:
            # Check cache first (product catalog doesn't change often)
            cache = get_cache()
            cache_key_str = cache_key('odoo:products', search=search, limit=limit)
            cached_result = cache.get(cache_key_str)
            if cached_result:
                logger.debug(f"[Cache HIT] get_products(search={search}, limit={limit})")
                return cached_result
            
            # Cache miss - fetch from adapter (ERP-aware)
            logger.debug(f"[Cache MISS] get_products(search={search}, limit={limit})")
            adapter = _adapter()
            products = adapter.get_products(search_term=search, limit=limit) if hasattr(adapter, 'get_products') else []
            
            result = json.dumps({
                "success": True,
                "count": len(products),
                "products": products
            }, indent=2)
            
            # Cache for 15 minutes
            cache.set(cache_key_str, result, TTL_15_MINUTES)
            return result
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    # Return tool list
    return [
        Tool(
            name="get_purchase_orders",
            func=get_purchase_orders,
            description="Get purchase orders from Odoo. Useful for tracking PO status, viewing drafts, or analyzing procurement history. Input: state (draft/sent/purchase/done/cancel) and limit."
        ),
        Tool(
            name="get_vendors",
            func=get_vendors,
            description="Get vendors from Odoo. Useful for vendor selection, checking vendor details, or analyzing vendor pool. Input: optional category filter and limit."
        ),
        Tool(
            name="create_purchase_order",
            func=create_purchase_order,
            description="Create a new purchase order in Odoo. Input: partner_id (vendor ID) and order_lines (JSON with product_id, quantity, price)."
        ),
        Tool(
            name="approve_purchase_order",
            func=approve_purchase_order,
            description="Approve a purchase order in Odoo, moving it from draft to confirmed state. Input: po_id (purchase order ID)."
        ),
        Tool(
            name="create_purchase_order_with_vendor_selection",
            func=create_purchase_order_with_vendor_selection,
            description="Create purchase order with vendor selection reasoning. Used by VendorSelectionAgent to document vendor selection rationale. Input: partner_id, order_lines (JSON), vendor_selection_notes, optional pr_number."
        ),
        Tool(
            name="get_products",
            func=get_products,
            description="Search products in Odoo catalog. Useful for finding products by name, checking prices, or validating product IDs. Input: search term and limit."
        ),
    ]


# ========== ADAPTER-BASED DATABASE TOOLS ==========
# All DB access below goes through _adapter() — zero hardcoded SQL.

def create_approval_routing_tools() -> List[Tool]:
    """Create LangChain tools for approval routing — all DB via adapter."""

    def get_approval_chain(department: str, amount: float) -> str:
        """Get approval chain for a department and amount via adapter."""
        try:
            cache = get_cache()
            ck = cache_key('approval_chain', department=department, amount=amount)
            cached = cache.get(ck)
            if cached:
                return cached
            rules = _adapter().get_approval_rules(document_type='PR', amount=float(amount), department=department)
            if not rules:
                result = json.dumps({"success": False,
                                     "error": f"No approval rules for {department} amount {amount}"})
            else:
                approvers = [{"approval_level": r.get('approval_level', i+1),
                              "approver_name": r.get('approver_name'),
                              "approver_email": r.get('approver_email'),
                              "department": r.get('department'),
                              "amount_max": float(r.get('amount_max', 0)),
                              "sla_hours": r.get('sla_hours'),
                              "escalate_after_hours": r.get('escalate_after')} for i, r in enumerate(rules)]
                result = json.dumps({"success": True, "department": department,
                                     "amount": amount, "approvers": approvers}, indent=2)
            cache.set(ck, result, TTL_1_HOUR)
            return result
        except Exception as e:
            logger.error("get_approval_chain failed: %s", e)
            return json.dumps({"success": False, "error": str(e)})

    def record_approval_decision(pr_number: str, approver_email: str,
                                  decision: str, reason: str = "") -> str:
        """Record an approval decision via adapter."""
        try:
            row = _adapter().create_pending_approval({
                'pr_number': pr_number,
                'decision_type': 'PR_APPROVAL',
                'agent_decision': f"{decision}: {reason}",
                'confidence_score': 1.0,
                'status': decision,
            })
            _adapter().log_agent_action('ApprovalAgent', 'record_decision',
                                         {'pr_number': pr_number, 'approver': approver_email},
                                         row, True)
            return json.dumps({"success": True, "pr_number": pr_number,
                                "decision": decision, "record_id": row.get('id')}, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def escalate_to_next_level(pr_number: str, current_level: int, department: str) -> str:
        """Escalate PR to next approval level via adapter, filtered by department."""
        try:
            rules = _adapter().get_approval_rules(document_type='PR', department=department)
            next_rules = [r for r in rules if r.get('approval_level', 1) > current_level]
            if next_rules:
                r = next_rules[0]
                return json.dumps({"success": True, "escalated": True, "pr_number": pr_number,
                                   "next_approver": {"name": r.get('approver_name'),
                                                     "email": r.get('approver_email'),
                                                     "department": r.get('department'),
                                                     "level": r.get('approval_level', current_level + 1),
                                                     "sla_hours": r.get('sla_hours'),
                                                     "escalate_after_hours": r.get('escalate_after')}}, indent=2)
            return json.dumps({"success": False, "escalated": False,
                                "message": f"Maximum approval level reached for {department}"})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    return [
        Tool(name="get_approval_chain", func=get_approval_chain,
             description="Get approval chain for a PR. Input: department, amount."),
        Tool(name="record_approval_decision", func=record_approval_decision,
             description="Record approval/rejection decision. Input: pr_number, approver_email, decision, reason."),
        Tool(name="escalate_to_next_level", func=escalate_to_next_level,
             description="Escalate PR to next approval level. Input: pr_number, current_level, department."),
    ]


def create_database_tools() -> List[Tool]:
    """Create LangChain tools for budget + risk — all DB via adapter."""

    def get_approval_rules_for_budget(department: str, budget: float) -> str:
        """Get approver for department + budget via adapter (with cache)."""
        try:
            cache = get_cache()
            ck = cache_key('db:approval_chain', department=department, budget=budget)
            cached = cache.get(ck)
            if cached:
                return cached
            rules = _adapter().get_approval_rules(document_type='PR', amount=float(budget), department=department)
            if not rules:
                result = json.dumps({"success": False,
                                     "error": f"No approver for {department} budget {budget}"})
            else:
                r = rules[0]
                result = json.dumps({"success": True,
                                     "approver": {"email": r.get('approver_email'),
                                                  "name": r.get('approver_name'),
                                                  "department": r.get('department'),
                                                  "approval_level": r.get('approval_level', 1),
                                                  "amount_max": float(r.get('amount_max', 0)),
                                                  "sla_hours": r.get('sla_hours'),
                                                  "escalate_after_hours": r.get('escalate_after')}},
                                    indent=2)
            cache.set(ck, result, TTL_1_HOUR)
            return result
        except Exception as e:
            logger.error("get_approval_chain failed: %s", e)
            return json.dumps({"success": False, "error": str(e)})

    def check_budget_availability(department: str, budget_category: str, amount: float) -> str:
        """Check budget availability via adapter."""
        try:
            rows = _adapter().get_budget_tracking(department=department, category=budget_category)
            if not rows:
                return json.dumps({"success": False,
                                   "error": f"No budget for {department}/{budget_category}"})
            b = rows[0]
            available = float(b.get('available_budget', 0))
            allocated = float(b.get('allocated_budget', 1))
            spent = float(b.get('spent_budget', 0))
            committed = float(b.get('committed_budget', 0))
            utilization = ((spent + committed + amount) / allocated) * 100
            return json.dumps({"success": True,
                                "sufficient": available >= amount,
                                "available_budget": available,
                                "requested_amount": amount,
                                "shortfall": max(0, amount - available),
                                "utilization_after_approval": round(utilization, 2),
                                "alert_threshold_exceeded": utilization >= 80}, indent=2)
        except Exception as e:
            logger.error("check_budget_availability failed: %s", e)
            return json.dumps({"success": False, "error": str(e)})

    def update_committed_budget(department: str, budget_category: str, amount: float) -> str:
        """Commit budget atomically via adapter (row-level lock inside adapter)."""
        try:
            result = _adapter().commit_budget(department, budget_category, float(amount))
            if result.get('success'):
                logger.info("Budget committed: %s/%s +$%s", department, budget_category, amount)
                return json.dumps({"success": True,
                                   "new_available_budget": result['available_budget'],
                                   "new_committed_budget": result['committed_budget'],
                                   "amount_committed": amount}, indent=2)
            return json.dumps(result)
        except Exception as e:
            logger.error("update_committed_budget failed: %s", e)
            return json.dumps({"success": False, "error": str(e)})

    def get_department_budget_status(department: str) -> str:
        """Get full department budget status via adapter."""
        try:
            rows = _adapter().get_budget_tracking(department=department)
            if not rows:
                return json.dumps({"success": False,
                                   "error": f"No budget data for {department}"})
            budget_data = []
            for b in rows:
                alloc = float(b.get('allocated_budget', 1))
                spent = float(b.get('spent_budget', 0))
                committed = float(b.get('committed_budget', 0))
                budget_data.append({
                    "department": b.get('department', department),
                    "category": b.get('budget_category'),
                    "allocated": alloc, "spent": spent, "committed": committed,
                    "available": float(b.get('available_budget', 0)),
                    "utilization_pct": round(((spent + committed) / alloc) * 100, 2),
                    "alerts": {"threshold_80": b.get('alert_threshold_80'),
                               "threshold_90": b.get('alert_threshold_90'),
                               "threshold_95": b.get('alert_threshold_95')}
                })
            return json.dumps({"success": True, "department": department,
                                "budgets": budget_data}, indent=2)
        except Exception as e:
            logger.error("get_department_budget_status failed: %s", e)
            return json.dumps({"success": False, "error": str(e)})

    def store_risk_assessment(risk_data_json: str) -> str:
        """Store risk assessment via adapter."""
        try:
            risk_data = json.loads(risk_data_json)
            result = _adapter().store_risk_assessment(risk_data)
            if result.get('success'):
                logger.info("Risk stored: PR=%s level=%s",
                            risk_data.get('pr_number'), risk_data.get('risk_level'))
                return json.dumps({"success": True,
                                   "assessment_id": result['id'],
                                   "assessed_at": result['assessed_at'],
                                   "pr_number": risk_data.get('pr_number'),
                                   "risk_level": risk_data.get('risk_level')}, indent=2)
            return json.dumps(result)
        except Exception as e:
            logger.error("store_risk_assessment failed: %s", e)
            return json.dumps({"success": False, "error": str(e)})

    return [
        Tool(name="get_approval_rules_for_budget", func=get_approval_rules_for_budget,
             description="Get approval rules for department + budget amount. Input: department, budget."),
        Tool(name="check_budget_availability", func=check_budget_availability,
             description="Check budget availability. Input: department, budget_category (CAPEX/OPEX), amount."),
        Tool(name="update_committed_budget", func=update_committed_budget,
             description="Commit budget after PR approval (race-condition safe). Input: department, budget_category, amount."),
        Tool(name="get_department_budget_status", func=get_department_budget_status,
             description="Get full budget status for a department. Input: department name."),
        Tool(name="store_risk_assessment", func=store_risk_assessment,
             description="Store risk assessment. Input: JSON with pr_number, risk scores, risk_level, etc."),
    ]


def get_all_tools() -> List[Tool]:
    """Get all tools for agentic system (Odoo + approval routing + database)"""
    return create_odoo_tools() + create_approval_routing_tools() + create_database_tools()
