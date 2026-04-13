"""
Smart Query Router
Determines which data source to query based on natural language input
"""

from typing import Dict, List, Any, Optional
from openai import OpenAI
import os
import json
import asyncio
import httpx
from concurrent.futures import ThreadPoolExecutor

from backend.services import hybrid_query
from backend.services.llm_routing_guide import build_classifier_instructions
from backend.services.routing_schema import (
    normalize_classification_payload,
    normalize_odoo_query_type,
    normalize_source_hint,
)
from backend.agents.orchestrator import initialize_orchestrator_with_agents

# OpenAI client with timeout configuration
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    timeout=httpx.Timeout(
        connect=5.0,   # 5 seconds to establish connection
        read=20.0,     # 20 seconds to read response
        write=5.0,     # 5 seconds to send request
        pool=5.0       # 5 seconds for connection pooling
    ),
    max_retries=2      # Retry twice on timeout
)


def _refine_odoo_query_intent(question: str, query_type: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run a narrow LLM pass for Odoo retrieval entity selection.

    This keeps routing intelligence-driven while constraining output to
    supported Odoo retrieval targets.
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Resolve Odoo retrieval target for procurement queries using the user's question. "
                    "Return ONLY JSON with keys: query_type, filters. "
                    "query_type MUST be exactly one of: purchase_orders, vendors, products. "
                    "Treat current_query_type as a weak hint that may be wrong. "
                    "Choose products for product/item/catalog requests, vendors for vendor/supplier requests, "
                    "and purchase_orders for PO/order status/amount requests. "
                    "Preserve or extend filters only when relevant (state, amount_min, amount_max, search, limit)."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n"
                    f"Current query_type (may be wrong): {query_type}\n"
                    f"Current filters: {json.dumps(filters)}"
                ),
            },
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    parsed = json.loads(response.choices[0].message.content)
    refined_type = normalize_odoo_query_type(str(parsed.get("query_type") or query_type))
    refined_filters = parsed.get("filters", {}) or filters or {}
    return {"query_type": refined_type, "filters": refined_filters}


def resolve_followup_context_with_llm(
    question: str,
    classification: Dict[str, Any],
    pr_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Resolve follow-up context using LLM rather than regex heuristics.

    The model decides whether previous turn context should be reused.
    """
    q = (question or "").strip().lower()
    vendor_confirmation_only = (
        (
            q.startswith("confirm_vendor:")
            or q.startswith("select vendor:")
            or q.startswith("vendor selected")
            or q.startswith("user selected vendor")
        )
        and not any(
            kw in q
            for kw in [
                "create pr",
                "create purchase request",
                "continue pr creation",
                "proceed with approval",
                "route approval",
            ]
        )
    )

    if vendor_confirmation_only:
        forced = dict(classification or {})
        forced["data_source"] = "agentic"
        forced["query_type"] = "VENDOR"
        forced["confidence"] = max(float(forced.get("confidence", 0.0) or 0.0), 0.85)
        intents = forced.get("intents")
        if isinstance(intents, list) and intents:
            first_filters = intents[0].get("filters", {}) if isinstance(intents[0], dict) else {}
            forced["intents"] = [{
                "data_source": "agentic",
                "query_type": "VENDOR",
                "filters": first_filters if isinstance(first_filters, dict) else {},
            }]
        return normalize_classification_payload(forced)

    prev = pr_data or {}
    prev_source = normalize_source_hint(str(prev.get("_prev_data_source", "")))
    prev_query_type = str(prev.get("_prev_query_type", "")).strip()

    if not prev_source and not prev_query_type:
        return classification

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Decide if the new user message is a follow-up that should reuse previous routing context. "
                        "Return ONLY JSON with keys: use_previous_context, data_source, query_type, confidence. "
                        "use_previous_context must be boolean. confidence must be 0..1. "
                        "If the user explicitly asks a new topic, set use_previous_context=false."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": question,
                            "current_classification": classification,
                            "previous_context": {
                                "data_source": prev_source,
                                "query_type": prev_query_type,
                            },
                        }
                    ),
                },
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        parsed = json.loads(response.choices[0].message.content)
        use_previous = bool(parsed.get("use_previous_context", False))
        decision_confidence = float(parsed.get("confidence", 0.0) or 0.0)

        if not use_previous or decision_confidence < 0.65:
            return classification

        resolved = dict(classification)
        resolved["data_source"] = str(parsed.get("data_source") or prev_source or classification.get("data_source", "general"))
        resolved["query_type"] = str(parsed.get("query_type") or prev_query_type or classification.get("query_type", "GENERAL"))
        resolved["confidence"] = max(float(classification.get("confidence", 0.0) or 0.0), decision_confidence)
        return normalize_classification_payload(resolved)
    except Exception as followup_error:
        print(f"[FOLLOWUP RESOLVER] Using base classification due to resolver error: {followup_error}")
        return classification


def _execute_agentic_request_sync(orchestrator, agent_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute async orchestrator request from sync context safely.

    If already inside an active event loop (e.g., async SSE route),
    run the coroutine in a dedicated worker thread with its own loop.
    """
    logger.info(f"[AGENTIC SYNC WRAPPER] Preparing to execute orchestrator...")
    logger.info(f"[AGENTIC SYNC WRAPPER] Request: {agent_request.get('request', 'N/A')}")
    logger.info(f"[AGENTIC SYNC WRAPPER] PR Data: {agent_request.get('pr_data', {})}")
    
    try:
        asyncio.get_running_loop()
        has_running_loop = True
    except RuntimeError:
        has_running_loop = False

    if not has_running_loop:
        logger.info(f"[AGENTIC SYNC WRAPPER] No active loop, using asyncio.run()")
        result = asyncio.run(orchestrator.execute(agent_request))
        logger.info(f"[AGENTIC SYNC WRAPPER] Orchestrator execution completed")
        logger.info(f"[AGENTIC SYNC WRAPPER] Result status: {result.get('status')}")
        return result

    logger.info("[AGENTIC SYNC WRAPPER] ️ Active event loop detected; executing in worker thread")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: asyncio.run(orchestrator.execute(agent_request)))
        result = future.result()
        logger.info(f"[AGENTIC SYNC WRAPPER] Worker thread execution completed")
        logger.info(f"[AGENTIC SYNC WRAPPER] Result status: {result.get('status')}")
        return result


import re as _re

# Keyword → query_type mapping for post-classification correction
_ANALYSIS_KEYWORD_MAP = [
    (_re.compile(r"\b(check\s+budget|budget\s+availab|afford|within\s+budget|verify\s+budget)", _re.I), "BUDGET"),
    (_re.compile(r"\b(assess\s+risks?|risk\s+assess|risk\s+analy|what\s+could\s+go\s+wrong)", _re.I), "RISK"),
    (_re.compile(r"\b(route\s+(for\s+)?approv|approval\s+rout|who\s+should\s+approv|get\s+approv)", _re.I), "APPROVAL"),
    (_re.compile(r"\b(best\s+vendor|recommend\s+(?:vendor|supplier)s?|choose\s+vendor|select\s+vendor|find\s+\w*\s*vendor|vendor\s+select|compare\s+vendor)", _re.I), "VENDOR"),
    (_re.compile(r"\b(compliance|policy\s+check|regulat)", _re.I), "COMPLIANCE"),
    (_re.compile(r"\b(procure\s+to\s+pay|end[\s-]+to[\s-]+end|full\s+p2p|full\s+procur|procure\s+\d+\s+\w+\s+for)", _re.I), "P2P_FULL"),
]

# Known departments for multi-department detection
_KNOWN_DEPARTMENTS = ["IT", "Finance", "Operations", "Procurement", "HR", "Marketing", "Sales"]

# Pattern to extract "DeptName needs $Amount for Category" clauses
_DEPT_CLAUSE_RE = _re.compile(
    r"(?P<dept>" + "|".join(_KNOWN_DEPARTMENTS) + r")"
    r"\s+(?:needs?|requires?|wants?)\s+\$?(?P<amount>[\d,.]+[kKmM]?)"
    r"(?:\s+(?:for|worth\s+of)\s+(?P<category>[A-Za-z][A-Za-z &]+?))?",
    _re.I,
)


def _strip_descriptive_segments(question: str) -> str:
    """Remove free-text descriptive tails that should not affect routing.

    These fields often contain words like "operations" or "finance" in plain
    language (e.g., "justification: ... operations continuity"), which can
    incorrectly trigger multi-department routing.
    """
    if not question:
        return ""

    sanitized = question
    # Remove trailing descriptive field blocks from their label to end of message.
    sanitized = _re.sub(
        r"\b(?:business\s+justification|justification|reason|notes?|description)\s*:\s*[\s\S]*$",
        "",
        sanitized,
        flags=_re.I,
    )
    return sanitized.strip()


def _extract_departments_from_text(question: str) -> List[str]:
    """Extract ordered unique department mentions from free text."""
    routing_text = _strip_descriptive_segments(question)
    if not routing_text:
        return []

    found: List[str] = []
    lower = routing_text.lower()
    for dept in _KNOWN_DEPARTMENTS:
        if _re.search(rf"\b{_re.escape(dept.lower())}\b", lower):
            found.append(dept)

    # Keep stable order from text appearance
    found.sort(key=lambda d: lower.find(d.lower()))
    return list(dict.fromkeys(found))


def _parse_amount(raw: str) -> float:
    """Parse amount strings like '42', '42k', '1.5M'."""
    raw = raw.replace(",", "").strip()
    multiplier = 1
    if raw[-1:].lower() == "k":
        multiplier = 1000
        raw = raw[:-1]
    elif raw[-1:].lower() == "m":
        multiplier = 1_000_000
        raw = raw[:-1]
    return float(raw) * multiplier


def _fix_multi_intent_routing(question: str, intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Post-classification correction for multi-intent queries.

    Handles two cases:
    1. MULTI-DEPARTMENT: "IT needs $42 and Finance needs $38 — check budget and risk for both"
       → separate intents per department per action
    2. SINGLE-DEPARTMENT: user names 2+ analysis actions with shared context
       → corrected intents with shared filters
    """
    def _extract_explicit_target_department(text: str) -> Optional[str]:
        if not text:
            return None
        dept_alt = "|".join(_re.escape(d) for d in _KNOWN_DEPARTMENTS)
        patterns = [
            _re.compile(rf"\bfor\s+(?P<dept>{dept_alt})\s+department\b", _re.I),
            _re.compile(rf"\b(?P<dept>{dept_alt})\s+department\b", _re.I),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                raw = m.group("dept")
                for known in _KNOWN_DEPARTMENTS:
                    if known.lower() == raw.lower():
                        return known
        return None

    routing_question = _strip_descriptive_segments(question)

    # --- Guardrail: collapse duplicate CREATE intents with conflicting departments ---
    # Example false split:
    # "Create PR for IT department ... justification: ... operations continuity"
    # LLM may return CREATE for IT + CREATE for Operations; user intent is single CREATE.
    if len(intents) >= 2:
        agentic_intents = [i for i in intents if str((i or {}).get("data_source", "")).lower() == "agentic"]
        agentic_types = {str((i or {}).get("query_type", "")).upper() for i in agentic_intents}
        if agentic_intents and agentic_types == {"CREATE"}:
            explicit_target = _extract_explicit_target_department(routing_question)
            depts = [((i.get("filters") or {}).get("department") if isinstance(i, dict) else None) for i in agentic_intents]
            unique_depts = {str(d).strip().lower() for d in depts if d}
            if explicit_target and len(unique_depts) > 1:
                # Keep one CREATE intent and force department to explicit target.
                base_intent = agentic_intents[0]
                for cand in agentic_intents:
                    cand_dept = str(((cand.get("filters") or {}).get("department") or "")).strip().lower()
                    if cand_dept == explicit_target.lower():
                        base_intent = cand
                        break

                base_filters = dict((base_intent or {}).get("filters") or {})
                base_filters["department"] = explicit_target
                corrected_single = [{
                    "data_source": "agentic",
                    "query_type": "CREATE",
                    "filters": base_filters,
                }]
                print(
                    "[MULTI-INTENT FIX] Collapsed conflicting CREATE intents "
                    f"to explicit department '{explicit_target}'"
                )
                return corrected_single

    # --- Multi-department detection ---
    dept_clauses = list(_DEPT_CLAUSE_RE.finditer(routing_question))
    if len(dept_clauses) >= 2:
        # Detect which analysis actions are requested
        detected_types = []
        for pattern, query_type in _ANALYSIS_KEYWORD_MAP:
            if pattern.search(routing_question):
                detected_types.append(query_type)
        
        if not detected_types:
            # Fallback: check "for both" with existing LLM intents' query types
            detected_types = list(dict.fromkeys(i.get("query_type", "") for i in intents if i.get("data_source") == "agentic"))
        
        if detected_types:
            corrected = []
            for m in dept_clauses:
                dept = m.group("dept")
                amount = _parse_amount(m.group("amount"))
                category = (m.group("category") or "").strip() or None
                for qt in detected_types:
                    filt: Dict[str, Any] = {"department": dept, "amount": amount}
                    if category:
                        filt["category"] = category
                    corrected.append({"data_source": "agentic", "query_type": qt, "filters": filt})
            
            print(f"[MULTI-DEPT FIX] {len(dept_clauses)} depts × {len(detected_types)} actions → {len(corrected)} intents")
            for c in corrected:
                print(f"  → {c['query_type']} for {c['filters'].get('department')} ${c['filters'].get('amount')}")
            return corrected

    # --- Multi-department detection (no explicit amounts) ---
    # Example: "top vendors for IT and Finance separately"
    dept_mentions = _extract_departments_from_text(routing_question)
    if len(dept_mentions) >= 2:
        detected_types = []
        for pattern, query_type in _ANALYSIS_KEYWORD_MAP:
            if pattern.search(routing_question):
                detected_types.append(query_type)

        if not detected_types:
            detected_types = list(dict.fromkeys(i.get("query_type", "") for i in intents if i.get("data_source") == "agentic"))

        if detected_types:
            # Reuse shared non-department filters from classifier output.
            shared_filters: Dict[str, Any] = {}
            for intent in intents:
                filt = (intent or {}).get("filters") or {}
                if isinstance(filt, dict):
                    for key, value in filt.items():
                        if key != "department" and value not in (None, ""):
                            shared_filters[key] = value

            corrected = []
            for dept in dept_mentions:
                for qt in detected_types:
                    filt = dict(shared_filters)
                    filt["department"] = dept
                    corrected.append({"data_source": "agentic", "query_type": qt, "filters": filt})

            print(f"[MULTI-DEPT FIX] expanded dept mentions {dept_mentions} for actions {detected_types} -> {len(corrected)} intents")
            return corrected

    # --- Single-department multi-action correction (original logic) ---
    if len(intents) < 2:
        return intents

    detected_types = []
    for pattern, query_type in _ANALYSIS_KEYWORD_MAP:
        if pattern.search(routing_question):
            detected_types.append(query_type)

    if len(detected_types) < 2:
        return intents

    shared_filters: Dict[str, Any] = {}
    for intent in intents:
        filt = (intent or {}).get("filters") or {}
        if isinstance(filt, dict):
            shared_filters.update(filt)

    corrected = [
        {"data_source": "agentic", "query_type": qt, "filters": dict(shared_filters)}
        for qt in detected_types
    ]

    print(f"[MULTI-INTENT FIX] Remapped {len(intents)} LLM intents → {[i['query_type'] for i in corrected]}")
    return corrected


# Sprint E (2026-04-11): local deterministic pre-classifier.
# Hard-guarantees a correct intent for the most common shapes so the LLM
# classifier is an "enhancement" layer rather than a single point of failure.
# If any of these match, we SHORT-CIRCUIT before calling the LLM. If the LLM
# call later fails or returns garbage, we also fall back to this layer so the
# classifier never drops to a blank "GENERAL".

_CONVERSATIONAL_GREETING_RE = _re.compile(
    r"^\s*(hi|hello|hey|howdy|good\s+(?:morning|afternoon|evening|night)|"
    r"what(?:'s| is)\s+up|yo|sup|greetings|thanks|thank\s+you|thx|ty)\b",
    _re.I,
)
_CONVERSATIONAL_QA_RE = _re.compile(
    r"^\s*(what\s+can\s+you|what\s+do\s+you|who\s+are\s+you|help|"
    r"how\s+(?:do\s+i|does\s+this)|explain|tell\s+me\s+about|can\s+you)\b",
    _re.I,
)
_PROCUREMENT_VERB_FULL_RE = _re.compile(
    r"\b(procure|procurement|buy|buying|purchase|purchasing|order|ordering|"
    r"acquire|acquiring|source)\b",
    _re.I,
)
_QUANTITY_NOUN_RE = _re.compile(
    r"(\d+)\s+(laptop\s+accessories|laptops?|accessories|servers?|monitors?|"
    r"printers?|desktops?|workstations?|devices?|machines?|units?|items?|"
    r"pcs?|pieces?|chairs?|desks?|tables?|cameras?|supplies?)",
    _re.I,
)


def _pre_classify_deterministic(question: str) -> Optional[Dict[str, Any]]:
    """Hard-coded local rules that ALWAYS win over the LLM when they match.

    Returns a normalized classification dict or None.

    Ordering matters — more specific rules go first. The LLM classifier only
    runs if this function returns None.
    """
    if not question or not question.strip():
        return None

    q = question.strip()
    lowered = q.lower()

    # ── Rule 1: purely conversational / greetings / "what can you do"  ──
    if _CONVERSATIONAL_GREETING_RE.match(q) or _CONVERSATIONAL_QA_RE.match(q):
        return {
            "intents": [
                {"data_source": "general", "query_type": "GENERAL", "filters": {}}
            ],
            "data_source": "general",
            "query_type": "GENERAL",
            "filters": {},
            "confidence": 0.99,
            "_pre_classified": True,
            "_rule": "conversational",
        }

    # ── Rule 2: explicit "procure N <thing>" → P2P_FULL ─────────────────
    # Very high confidence: a procurement verb PLUS a quantity+noun is almost
    # always an execution request.
    has_proc_verb = bool(_PROCUREMENT_VERB_FULL_RE.search(q))
    qty_match = _QUANTITY_NOUN_RE.search(q)
    if has_proc_verb and qty_match:
        return {
            "intents": [
                {
                    "data_source": "agentic",
                    "query_type": "P2P_FULL",
                    "filters": {},
                }
            ],
            "data_source": "agentic",
            "query_type": "P2P_FULL",
            "filters": {},
            "confidence": 0.98,
            "_pre_classified": True,
            "_rule": "procurement_verb+quantity_noun",
        }

    # ── Rule 3: "show purchase orders / vendors / products" → Odoo read ─
    for pattern, q_type in (
        (r"\b(show|list|get|display|fetch)\s+(?:all\s+)?(?:open\s+|current\s+|recent\s+)?purchase\s+orders?\b", "purchase_orders"),
        (r"\b(show|list|get|display|fetch)\s+(?:all\s+)?(?:active\s+|current\s+)?vendors?\b", "vendors"),
        (r"\b(show|list|get|display|fetch)\s+(?:all\s+)?(?:active\s+)?suppliers?\b", "vendors"),
        (r"\b(show|list|get|display|fetch)\s+(?:all\s+)?products?\b", "products"),
        (r"\b(show|list|get|display|fetch)\s+(?:all\s+)?items?\b", "products"),
    ):
        if _re.search(pattern, lowered):
            return {
                "intents": [
                    {"data_source": "odoo", "query_type": q_type, "filters": {}}
                ],
                "data_source": "odoo",
                "query_type": q_type,
                "filters": {},
                "confidence": 0.97,
                "_pre_classified": True,
                "_rule": f"odoo_show_{q_type}",
            }

    return None


def _fallback_classify(question: str) -> Dict[str, Any]:
    """Last-resort classifier used when the LLM call raises or returns junk.

    Tries deterministic rules first; if none fit, returns a GENERAL intent with
    lower confidence (but never blank). Callers should always get a valid
    classification shape back.
    """
    pre = _pre_classify_deterministic(question)
    if pre is not None:
        return pre

    # Minimal keyword net — biased toward NOT breaking user workflows.
    lower = (question or "").lower()
    if any(k in lower for k in ("budget", "afford", "within budget")):
        return {
            "intents": [{"data_source": "agentic", "query_type": "BUDGET", "filters": {}}],
            "data_source": "agentic",
            "query_type": "BUDGET",
            "filters": {},
            "confidence": 0.55,
            "_pre_classified": False,
            "_rule": "fallback_budget_keyword",
        }
    if any(k in lower for k in ("vendor", "supplier")):
        return {
            "intents": [{"data_source": "agentic", "query_type": "VENDOR", "filters": {}}],
            "data_source": "agentic",
            "query_type": "VENDOR",
            "filters": {},
            "confidence": 0.55,
            "_pre_classified": False,
            "_rule": "fallback_vendor_keyword",
        }

    return {
        "intents": [{"data_source": "general", "query_type": "GENERAL", "filters": {}}],
        "data_source": "general",
        "query_type": "GENERAL",
        "filters": {},
        "confidence": 0.4,
        "_pre_classified": False,
        "_rule": "fallback_general",
    }


def classify_query_intent(question: str) -> Dict[str, Any]:
    """
    Classify user's question to determine data source(s)

    Returns:
        {
            "intents": [
                {
                    "data_source": "odoo" | "approval_chains" | "budget_tracking" | "agent_history",
                    "query_type": specific type like "purchase_orders", "vendors", etc.,
                    "filters": dict of filters to apply
                }
            ],
            "confidence": float
        }

        For backward compatibility, also includes flat fields for single-intent queries:
        "data_source", "query_type", "filters" copied from first intent
    """

    print(f"\n{'='*60}")
    print(f"[QUERY CLASSIFIER] Analyzing question: '{question}'")
    print(f"{'='*60}")

    # Sprint E (2026-04-11): deterministic short-circuit. If the input matches
    # a rock-solid pattern, skip the LLM entirely. Lower latency AND no risk of
    # the LLM drifting on the most common shapes. The LLM classifier still runs
    # for everything else and is further enriched below.
    pre = _pre_classify_deterministic(question)
    if pre is not None:
        print(
            f"[CLASSIFIER PRE] Deterministic rule '{pre['_rule']}' matched "
            f"→ {pre['query_type']} (confidence {pre['confidence']})"
        )
        return pre

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": build_classifier_instructions()},
                {"role": "user", "content": question}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
    except Exception as llm_exc:
        # Sprint E: never crash on LLM failure — fall back deterministically.
        print(f"[CLASSIFIER LLM] call failed, using fallback: {llm_exc}")
        return _fallback_classify(question)

    try:
        result = json.loads(response.choices[0].message.content)
        
        # Extract intents array (new multi-intent format)
        intents = result.get("intents", [])
        confidence = float(result.get("confidence", 0.5))
        
        # Backward compatibility: if no intents array, construct from flat fields
        if not intents:
            # Legacy single-intent format
            intents = [{
                "data_source": result.get("data_source", "general"),
                "query_type": result.get("query_type", "GENERAL"),
                "filters": result.get("filters", {})
            }]
        
        # Normalize each intent
        normalized_intents = []
        for intent in intents:
            normalized = normalize_classification_payload(intent)
            
            # Second pass for Odoo retrieval target accuracy
            if str(normalized.get("data_source", "")).strip().lower() == "odoo":
                try:
                    refined = _refine_odoo_query_intent(
                        question,
                        str(normalized.get("query_type") or ""),
                        normalized.get("filters", {}) or {},
                    )
                    normalized["query_type"] = refined["query_type"]
                    normalized["filters"] = refined["filters"]
                except Exception as refine_error:
                    print(f"[CLASSIFIER] Odoo refinement failed, using primary output: {refine_error}")
                    normalized["query_type"] = normalize_odoo_query_type(str(normalized.get("query_type") or ""))
            
            normalized_intents.append(normalized)
        
        # Post-classification correction: fix misclassified multi-intent queries
        normalized_intents = _fix_multi_intent_routing(question, normalized_intents)

        # Build result with backward compatibility
        result = {
            "intents": normalized_intents,
            "confidence": confidence
        }
        
        # Add flat fields from first intent for backward compatibility
        if normalized_intents:
            first = normalized_intents[0]
            result["data_source"] = first["data_source"]
            result["query_type"] = first["query_type"]
            result["filters"] = first["filters"]
        else:
            result["data_source"] = "general"
            result["query_type"] = "GENERAL"
            result["filters"] = {}
        
        print(f"\n[CLASSIFICATION RESULT]")
        print(f"  Intent Count: {len(normalized_intents)}")
        for idx, intent in enumerate(normalized_intents, 1):
            print(f"  Intent {idx}:")
            print(f"    Data Source: {intent.get('data_source', 'unknown')}")
            print(f"    Query Type: {intent.get('query_type', 'unknown')}")
            print(f"    Filters: {intent.get('filters', {})}")
        print(f"  Overall Confidence: {confidence}")
        print(f"{'='*60}\n")
        return result
    except Exception as e:
        # Sprint E (2026-04-11): fall back deterministically so the downstream
        # pipeline NEVER sees a blank GENERAL when a keyword rule could save
        # it. Previously this dropped to {query_type:GENERAL,confidence:0.3}
        # which then got routed to the chat handler as "I can't help with
        # that" regardless of the actual request.
        print(f"[CLASSIFICATION ERROR] {str(e)}")
        print(f"[CLASSIFIER] Falling back to deterministic rule engine")
        print(f"{'='*60}\n")
        return _fallback_classify(question)


def _execute_single_intent(
    question: str,
    data_source: str,
    query_type: str,
    filters: Dict[str, Any],
    language: str = "en"
) -> Dict[str, Any]:
    """
    Execute a single classified intent and return results.
    
    This is the core execution logic extracted from route_and_execute_query
    to support multi-intent sequential execution.
    """
    data = []
    
    try:
        if data_source == "odoo":
            normalized_type = normalize_odoo_query_type(query_type)
            print(f"[ODOO QUERY] Fetching {normalized_type} with filters: {filters}")
            data = hybrid_query.query_odoo_data(normalized_type, filters)
        
        elif data_source == "approval_chains":
            dept = filters.get("department")
            amount = filters.get("amount")
            print(f"[APPROVAL QUERY] dept={dept}, amount={amount}")
            data = hybrid_query.query_approval_chains(department=dept, amount=amount)
        
        elif data_source == "budget_tracking":
            dept = filters.get("department")
            fiscal_year = filters.get("fiscal_year", 2026)
            # Convert "FY2026" string to integer 2026 if needed
            if isinstance(fiscal_year, str) and fiscal_year.startswith("FY"):
                fiscal_year = int(fiscal_year.replace("FY", ""))
            print(f"[BUDGET QUERY] dept={dept}, fiscal_year={fiscal_year}")
            data = hybrid_query.query_budget_status(department=dept, fiscal_year=fiscal_year)
        
        elif data_source == "agentic":
            # Route to AI agents for decision-making
            print(f"[AGENTIC] Routing to AI agent for: {query_type}")
            print(f"[AGENTIC] Filters: {filters}")
            
            try:
                print(f"[AGENTIC] Calling initialize_orchestrator_with_agents()...")
                orchestrator = initialize_orchestrator_with_agents()
                print(f"[AGENTIC] Orchestrator instance: {id(orchestrator)}")
                print(f"[AGENTIC] Registered agents: {list(orchestrator.specialized_agents.keys())}")
                print(f"[AGENTIC] Agent count: {len(orchestrator.specialized_agents)}")
                
                # Build agent request from filters
                pr_data = {
                    "department": filters.get("department", "IT"),
                    "budget": filters.get("amount") or filters.get("total_cost") or filters.get("budget", 0),
                    "vendor_name": filters.get("vendor") or filters.get("vendor_name", ""),
                    "product_name": filters.get("item") or filters.get("product") or filters.get("product_name", ""),
                    "quantity": filters.get("quantity", 1)
                }
                
                # Only include budget_category if explicitly specified
                if "budget_category" in filters:
                    pr_data["budget_category"] = filters["budget_category"]
                else:
                    # Default to CAPEX if not specified (capital purchases are more common)
                    pr_data["budget_category"] = "CAPEX"
                    print(f"[AGENTIC] WARNING: budget_category not specified, defaulting to CAPEX")
                
                agent_request = {
                    "request": question,
                    "pr_data": pr_data,
                    "query_type": query_type  # Pass classification result to orchestrator!
                }
                
                # Run async agent execution safely from sync router
                agent_result = _execute_agentic_request_sync(orchestrator, agent_request)
                
                logger.info(f"[AGENTIC] Agent execution completed")
                logger.info(f"[AGENTIC] Result status: {agent_result.get('status')}")
                
                # Format agent result for return (simplified extraction for multi-intent)
                if agent_result and agent_result.get("status") == "success":
                    orchestrator_result = agent_result.get("result", {})
                    
                    # Check for workflow type
                    workflow_type = orchestrator_result.get("workflow_type")
                    if workflow_type:
                        # Workflow result
                        pr_object = orchestrator_result.get("pr_object", {})
                        data = [{
                            "agent": "Orchestrator",
                            "workflow": workflow_type,
                            "status": orchestrator_result.get("status", "completed"),
                            "pr_number": pr_object.get("pr_number", ""),
                            "department": pr_object.get("department", ""),
                            "amount": pr_object.get("budget", 0)
                        }]
                    else:
                        # Direct agent result
                        primary_result = orchestrator_result.get("primary_result", {})
                        if primary_result.get("status") == "success":
                            actual_result = primary_result.get("result", {})
                            primary_decision = primary_result.get("decision", {})
                            
                            data = [{
                                "agent": primary_result.get("agent", "Unknown"),
                                "status": actual_result.get("status", "completed"),
                                "action": actual_result.get("action", primary_decision.get("action", "")),
                                "reasoning": actual_result.get("reasoning", primary_decision.get("reasoning", "")),
                                "confidence": primary_decision.get("confidence", 0.0)
                            }]
                            
                            # Copy any additional result fields
                            for key in ["budget_verified", "alert_level", "assigned_approvers", "required_level"]:
                                if key in actual_result:
                                    data[0][key] = actual_result[key]
                        else:
                            data = [{
                                "status": "error",
                                "agent": primary_result.get("agent", "Unknown"),
                                "message": primary_result.get("message", "Agent execution failed")
                            }]
                else:
                    data = [{
                        "status": "error",
                        "message": agent_result.get("error", "Agent execution failed")
                    }]
                    
            except Exception as agent_error:
                logger.info(f"[AGENTIC ERROR] Exception occurred: {str(agent_error)}")
                import traceback
                print(f"[AGENTIC ERROR] Traceback: {traceback.format_exc()}")
                data = [{
                    "status": "error",
                    "message": str(agent_error)
                }]
        
        elif data_source == "agent_history":
            agent_name = filters.get("agent_name")
            limit = filters.get("limit", 50)
            # Check if asking about decisions or actions
            if "decision" in question.lower():
                print(f"[AGENT HISTORY] Fetching decisions for: {agent_name}")
                data = hybrid_query.query_agent_decisions(agent_name=agent_name, limit=limit)
            else:
                print(f"[AGENT HISTORY] Fetching actions for: {agent_name}")
                data = hybrid_query.query_agent_actions(agent_name=agent_name, limit=limit)
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\\n[QUERY ERROR] {str(e)}")
        print(f"[ERROR DETAILS]\\n{error_details}")
        return {
            "data": [],
            "source": data_source,
            "explanation": f"Error executing {data_source} query: {str(e)}",
            "error": str(e)
        }
    
    # Generate explanation for this intent
    explanation = generate_explanation(question, data, data_source, language)
    
    return {
        "data": data,
        "source": data_source,
        "query_type": query_type,
        "filters": filters,
        "explanation": explanation,
        "count": len(data)
    }


def route_and_execute_query(question: str, language: str = "en") -> Dict[str, Any]:
    """
    Route question to appropriate data source and execute query
    
    Returns:
        {
            "data": list of records,
            "source": data source used,
            "explanation": natural language explanation
        }
    """
    
    print(f"\n[QUERY ROUTER] Starting route_and_execute_query")
    print(f"  Question: '{question}'")
    print(f"  Language: {language}")
    
    # Step 1: Classify intent(s)
    classification = classify_query_intent(question)
    intents = classification.get("intents", [])
    overall_confidence = classification.get("confidence", 0.5)
    
    # Multi-intent handling: if we have multiple intents, execute sequentially
    if len(intents) > 1:
        print(f"\n[MULTI-INTENT DETECTED] {len(intents)} intents found")
        for idx, intent in enumerate(intents, 1):
            print(f"  Intent {idx}: {intent.get('data_source')} / {intent.get('query_type')}")
        
        # Execute each intent and collect results
        all_data = []
        all_sources = []
        all_explanations = []
        budget_failed = False
        
        for idx, intent in enumerate(intents, 1):
            data_source = intent.get("data_source", "odoo")
            query_type = intent.get("query_type", "")
            query_type_upper = str(query_type).upper()
            filters = intent.get("filters", {})
            
            print(f"\n[ROUTING DECISION - Intent {idx}/{len(intents)}]")
            print(f"  → Routing to: {data_source}")
            print(f"  → Query type: {query_type}")
            print(f"  → Filters: {filters}")

            # Budget gate: if budget verification has failed, skip approval routing
            if budget_failed and query_type_upper == "APPROVAL":
                print(f"[BUDGET GATE] Skipping approval routing due to failed budget verification")
                intent_result = {
                    "data": [{
                        "agent": "ApprovalRoutingAgent",
                        "status": "blocked_by_budget",
                        "action": "skip_approval_routing",
                        "reasoning": "Approval routing was skipped because budget verification failed.",
                        "message": "Budget must be available before approval routing can proceed."
                    }],
                    "source": "agentic",
                    "query_type": query_type,
                    "filters": filters,
                    "explanation": "Approval routing skipped because budget verification failed.",
                    "count": 1
                }
            else:
                # Execute this intent
                intent_result = _execute_single_intent(question, data_source, query_type, filters, language)
            
            # Track budget outcome for gating downstream intents
            if query_type_upper == "BUDGET":
                first_item = (intent_result.get("data") or [{}])[0]
                budget_status = str(first_item.get("status", "")).lower()
                budget_verified = first_item.get("budget_verified")
                if budget_verified is False or budget_status in {"rejected", "error", "insufficient_budget", "pending_human_approval"}:
                    budget_failed = True
                    print("[BUDGET GATE] Budget verification failed; subsequent approval intents will be skipped")
            
            if intent_result.get("data"):
                all_data.extend(intent_result["data"])
            all_sources.append(intent_result.get("source", data_source))
            if intent_result.get("explanation"):
                all_explanations.append(intent_result["explanation"])
        
        # Combine results
        combined_explanation = " ".join(all_explanations) if all_explanations else generate_explanation(question, all_data, "multi-intent", language)
        
        print(f"\n[MULTI-INTENT COMPLETE] Executed {len(intents)} intents")
        print(f"[MULTI-INTENT COMPLETE] Total records: {len(all_data)}")
        
        return {
            "data": all_data,
            "source": "multi-intent: " + ", ".join(all_sources),
            "query_type": "MULTI",
            "filters": {},
            "explanation": combined_explanation,
            "count": len(all_data),
            "intent_count": len(intents)
        }
    
    # Single intent (backward compatible path) - delegate to helper
    data_source = classification.get("data_source", "odoo")
    query_type = classification.get("query_type", "")
    filters = classification.get("filters", {})
    
    print(f"\n[ROUTING DECISION - Single Intent]")
    print(f"  → Routing to: {data_source}")
    print(f"  → Query type: {query_type}")
    print(f"  → Filters: {filters}")
    
    # Execute using shared helper to avoid duplication
    return _execute_single_intent(question, data_source, query_type, filters, language)


def synthesize_agentic_response(question: str, agent_result: Dict[str, Any], language: str = "en") -> str:
    """
    Convert raw orchestrator/agent output into a smart, business-friendly answer.

    This is used by chat routes that execute agents directly (bypassing route_and_execute_query)
    so all agentic responses remain consistent and intelligent.
    """
    try:
        # Keep prompt payload bounded while still preserving core signal.
        compact_payload = {
            "status": agent_result.get("status"),
            "agent": agent_result.get("agent"),
            "decision": agent_result.get("decision", {}),
            "result": agent_result.get("result", {}),
        }

        system_prompt = f"""You are a senior procurement advisor. Write a smart, clear response in {language}.

Rules:
1. Never expose raw technical/internal fields like JSON keys, wrappers, or internal pipeline jargon.
2. Explain what happened in business terms.
3. Use this structure:
   - Executive Summary (1-2 lines)
   - Key Insights (bullets)
   - Recommended Next Steps (bullets)
4. Include numbers and thresholds if available.
5. If confidence exists, mention it as decision confidence (not supplier score).
6. Keep tone professional, concise, and actionable.
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\n"
                        f"Agent output: {json.dumps(compact_payload, default=str)}"
                    ),
                },
            ],
            temperature=0.25,
            max_tokens=800,
        )

        return response.choices[0].message.content
    except Exception as e:
        # Deterministic fallback to avoid silent degradation.
        result_block = agent_result.get("result", {})
        decision = agent_result.get("decision", {})
        status = result_block.get("status") or agent_result.get("status") or "processed"
        action = result_block.get("action") or decision.get("action") or "completed"
        confidence = decision.get("confidence")
        reasoning = result_block.get("reasoning") or decision.get("reasoning")

        fallback = [
            "Executive Summary:",
            f"Your request was {status} with action: {str(action).replace('_', ' ')}.",
            "",
            "Key Insights:",
        ]
        if confidence is not None:
            fallback.append(f"- Decision confidence: {round(float(confidence) * 100)}%")
        if reasoning:
            fallback.append(f"- Analysis: {reasoning}")
        fallback.append("")
        fallback.append("Recommended Next Steps:")
        fallback.append("- Review the result and proceed with the suggested action.")
        fallback.append("- If needed, request a deeper breakdown by risk, budget, or approval chain.")
        fallback.append("")
        fallback.append(f"(Fallback formatter used due to: {str(e)})")
        return "\n".join(fallback)


def generate_explanation(question: str, data: List[Dict], source: str, language: str = "en") -> str:
    """Generate natural language explanation of results"""
    
    if not data:
        return f"No results found for your query in {source}."
    
    # Enhanced system prompt for agentic responses
    if source == "agentic":
        system_prompt = f"""You are a procurement assistant. Generate a business-friendly response in {language}.

**CRITICAL RULES FOR AGENTIC RESPONSES:**

1. **Budget Verification Results** - Focus on business impact:
   - Start with action taken: "Reserved $XX,XXX from [Department] [Budget Category]"
   - Show budget change: "Available balance: $X,XXX,XXX (was $X,XXX,XXX before reservation)"
   - Include utilization: "Budget utilization: XX% (Safe/Warning/Critical)"
   - Alert levels: Show if 80%+ (️ Warning at 80%, Critical at 90%, Emergency at 95%)
   - Hide technical fields: agent, status, action, reasoning, confidence

2. **Approval Routing Results** - Show actionable information:
   - Start with routing action: "Routed to [X] approver(s) for $XX,XXX purchase"
   - List approvers in hierarchy: "Level 1: [Name] ([Title]) → Level 2: [Name] ([Title])"
   - Include approval threshold: "Requires [Manager/Director/VP] approval (amount exceeds $XX,XXX threshold)"
   - If combined with budget: Show budget action first, then approval routing
   - Hide technical fields: pr_number if "Unknown", agent_message if generic

3. **Combined Actions** (Budget + Approval):
   - Budget action first (reservation/commitment)
   - Then approval routing
   - Use sections: "Budget Status" and "Approval Chain"

4. **Formatting Rules:**
   - Use emojis strategically (️ )
   - NO tables with "Agent", "Status", "Action", "Confidence" - these are internal fields
   - Use bullet points or numbered lists for clarity
   - Amounts always with $ and commas: $1,234,567
   - Department and category in context: "IT CAPEX" not just "CAPEX"

5. **Language Style:**
   - Action-oriented: "Reserved", "Routed", "Committed" (not "Approved", "Completed")
   - Business-focused: Hide AI/agent terminology
   - Conversational but professional
   - No jargon: "Budget utilization" not "Current utilization rate"

**Example Good Response:**
"Reserved $50,000 from IT CAPEX budget

Budget Status:
- Available balance: $1,650,000 (was $1,700,000)
- Budget utilization: 41% (Safe - no alerts)
- Fiscal Year: 2026

Approval Chain:
Purchase requires 2 approvals (amount exceeds $10,000):
1. Jane Smith (IT Manager) - jane.smith@company.com
2. Emily Brown (IT Director) - emily.brown@company.com

Budget committed and ready for approval workflow"

**Example Bad Response:**
"Agent: BudgetVerificationAgent
Status: Approved
Action: Approve
Reasoning: Budget available. Utilization: 41.0%"

Number of records: {len(data)}"""
    else:
        # Smart default prompt for all non-agentic sources
        system_prompt = f"""You are a senior procurement analyst. Generate a smart, business-ready response in {language}.

Data source: {source}
Number of records: {len(data)}

Required output sections:
1. Executive Summary (1-2 lines)
2. Key Insights (3-6 bullets with concrete numbers/trends)
3. Recommended Next Steps (2-4 practical actions)
4. Markdown table with important fields (max 10 rows)

Rules:
- Be concise but intelligent.
- Highlight anomalies, risks, or opportunities.
- Use professional language suitable for procurement managers.
- Avoid raw technical/internal wording.
"""
    
    # Create summary based on data
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}\n\nData: {json.dumps(data[:10], default=str)}"}  # Limit to 10 for prompt
        ],
        temperature=0.3,
        max_tokens=1000
    )
    
    return response.choices[0].message.content
