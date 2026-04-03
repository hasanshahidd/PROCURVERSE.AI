/**
 * Robust agent result extraction utility.
 *
 * The backend response arrives through various layers of wrapping:
 *   emit_complete → SSE event.data → onSuccess(data)
 *
 * Possible structures:
 *  A) Single-intent:   data.result = { status, agent, result: {agent_payload}, agents_invoked }
 *  B) Multi-intent:    data.result = { intent_count, results: [...] }
 *  C) PR workflow:     data.result = { workflow_type, pr_object, validations, status }
 *  D) Odoo data:       data.result = { data_source:"odoo", purchase_orders:[...], ... }
 *  E) Pending:         data = { status:"pending_human_approval", ... }
 *
 *  This module normalises all structures into a single contract:
 *  {
 *    kind: "single" | "multi" | "pr_workflow" | "odoo" | "pending",
 *    agent: string,
 *    status: string,
 *    payload: Record<string, any>,   // the agent-specific data
 *    dataSource: string,
 *    queryType: string,
 *    decision: { action, reasoning, confidence, alternatives } | null,
 *    agentsInvoked: string[],
 *    multiResults: NormalisedResult[] | null,   // only for multi-intent
 *  }
 */

export interface NormalisedResult {
  kind: "single" | "multi" | "pr_workflow" | "odoo" | "pending";
  agent: string;
  status: string;
  payload: Record<string, any>;
  dataSource: string;
  queryType: string;
  decision: {
    action: string;
    reasoning: string;
    confidence: number;
    alternatives: string[];
  } | null;
  agentsInvoked: string[];
  multiResults: NormalisedResult[] | null;
  executionTimeMs: number | undefined;
}

/** Safe accessor – never throws */
function get(obj: any, key: string): any {
  if (obj && typeof obj === "object" && key in obj) return obj[key];
  return undefined;
}

/**
 * Main extraction: turns raw SSE `event.data` (stored as `finalData`)
 * into a normalised result.
 */
export function extractAgentResult(raw: any, fallbackAgent?: string): NormalisedResult {
  if (!raw || typeof raw !== "object") {
    return emptyResult(fallbackAgent);
  }

  // Level 1: emit_complete wraps in { result: ..., status: "success" }
  const envelope = get(raw, "result") ?? raw;
  // envelope is now { status, agent, result: {payload}, ... } OR multi-intent

  // Detect multi-intent
  const envelopeInner = get(envelope, "result");
  if (
    get(envelope, "agent") === "MultiIntentOrchestrator" ||
    (get(envelope, "intent_count") !== undefined && Array.isArray(get(envelope, "results"))) ||
    (envelopeInner && typeof envelopeInner === "object" &&
      get(envelopeInner, "intent_count") !== undefined && Array.isArray(get(envelopeInner, "results")))
  ) {
    return extractMultiIntent(envelope, raw, fallbackAgent);
  }

  // Detect PR workflow
  if (get(envelope, "workflow_type") === "pr_creation") {
    return extractPrWorkflow(envelope, raw, fallbackAgent);
  }

  // Detect Odoo data
  if (
    get(envelope, "data_source") === "odoo" ||
    get(envelope, "query_type") === "purchase_orders" ||
    get(envelope, "total_purchase_orders") !== undefined
  ) {
    return extractOdooData(envelope, raw, fallbackAgent);
  }

  // MultiVendorRiskAgent: result is flat at envelope.result — no orchestrator wrapper
  if (
    get(envelope, "agent") === "MultiVendorRiskAgent" ||
    get(raw, "agent") === "MultiVendorRiskAgent"
  ) {
    const innerResult = get(envelope, "result") ?? envelope;
    return {
      kind: "single",
      agent: "MultiVendorRiskAgent",
      status: String(get(innerResult, "status") || get(envelope, "status") || "completed"),
      payload: innerResult && typeof innerResult === "object" ? innerResult : {},
      dataSource: "Agentic",
      queryType: String(get(raw, "query_type") || "RISK:VENDOR_COMPARISON"),
      decision: null,
      agentsInvoked: ["MultiVendorRiskAgent"],
      multiResults: null,
      executionTimeMs: undefined,
    };
  }

  // Detect pending human approval (from low-confidence agent)
  if (get(raw, "status") === "pending_human_approval" || get(envelope, "status") === "pending_human_approval") {
    const src = get(raw, "status") === "pending_human_approval" ? raw : envelope;
    return {
      kind: "pending",
      agent: src.agent_name || src.agent || fallbackAgent || "Agent",
      status: "pending_human_approval",
      payload: src,
      dataSource: "Agentic",
      queryType: "",
      decision: src.decision ?? null,
      agentsInvoked: [],
      multiResults: null,
      executionTimeMs: undefined,
    };
  }

  // ----- Single-intent (common case for 4 core agents) -----
  return extractSingleIntent(envelope, raw, fallbackAgent);
}

function extractSingleIntent(envelope: any, raw: any, fallback?: string): NormalisedResult {
  // envelope = { status, agent, result: {payload}, data_source, query_type, agents_invoked }
  //   OR just the payload itself if we drilled too deep
  const hasAgentField = typeof get(envelope, "agent") === "string";
  const innerResult = hasAgentField ? (get(envelope, "result") ?? envelope) : envelope;

  // If the innerResult also has a "primary_result" layer (orchestrator output)
  const primary = get(innerResult, "primary_result") ?? innerResult;
  const payload = get(primary, "result") ?? primary;

  // Deep-check: if the drilled payload is actually a PR creation workflow,
  // hand off to the pr_workflow extractor so kind is set correctly.
  if (payload && typeof payload === "object" && get(payload, "workflow_type") === "pr_creation") {
    return extractPrWorkflow(payload, raw, get(primary, "agent") || get(envelope, "agent") || fallback);
  }

  const agent =
    get(primary, "agent") ||
    get(envelope, "agent") ||
    get(raw, "agent") ||
    fallback ||
    "Agent";

  const decision = get(primary, "decision") ?? get(envelope, "decision") ?? null;

  return {
    kind: "single",
    agent,
    status: String(get(payload, "status") || get(primary, "status") || get(envelope, "status") || "completed"),
    payload: payload && typeof payload === "object" ? payload : {},
    dataSource: resolveDataSource(raw, envelope, primary, payload, agent),
    queryType: String(
      get(raw, "query_type") ||
      get(envelope, "query_type") ||
      get(primary, "query_type") ||
      ""
    ),
    decision: decision
      ? {
          action: String(decision.action ?? ""),
          reasoning: String(decision.reasoning ?? ""),
          confidence: Number(decision.confidence ?? 0),
          alternatives: Array.isArray(decision.alternatives) ? decision.alternatives : [],
        }
      : null,
    agentsInvoked: extractInvoked(raw, envelope, innerResult),
    multiResults: null,
    executionTimeMs:
      get(payload, "execution_time_ms") ??
      get(primary, "execution_time_ms") ??
      get(envelope, "execution_time_ms") ??
      undefined,
  };
}

function extractMultiIntent(envelope: any, raw: any, fallback?: string): NormalisedResult {
  // The streaming endpoint sends: { agent:"MultiIntentOrchestrator", result: { intent_count, results:[...] } }
  // So results may be at envelope.result.results rather than envelope.results
  const inner = get(envelope, "result");
  const resultArrayRaw =
    get(envelope, "results") ??
    (inner && typeof inner === "object" ? get(inner, "results") : undefined) ??
    [];
  const resultArray: any[] = Array.isArray(resultArrayRaw) ? resultArrayRaw : [];

  const children: NormalisedResult[] = resultArray.map((item: any, idx: number) => {
    // Each item can be a pr_workflow or an orchestrator sub-result.
    // IMPORTANT: only treat as PR workflow when workflow_type explicitly says so.
    // Using loose heuristics (e.g. presence of pr_object) can misclassify other results.
    if (get(item, "workflow_type") === "pr_creation") {
      return extractPrWorkflow(item, raw, fallback);
    }

    // Otherwise treat as normal orchestrator single-agent result.
    const primary = get(item, "primary_result") ?? item;
    const payload = get(primary, "result") ?? primary;
    const agent =
      get(primary, "agent") ??
      get(item, "agent") ??
      `Intent ${idx + 1}`;

    return {
      kind: "single" as const,
      agent,
      status: String(get(payload, "status") || get(primary, "status") || "completed"),
      payload: payload && typeof payload === "object" ? payload : {},
      dataSource: "Agentic",
      queryType: "",
      decision: get(primary, "decision") ?? null,
      agentsInvoked: [],
      multiResults: null,
      executionTimeMs: get(payload, "execution_time_ms") ?? undefined,
    };
  });

  return {
    kind: "multi",
    agent: "MultiIntentOrchestrator",
    status: "completed",
    payload: envelope,
    dataSource: "multi-intent",
    queryType: String(get(raw, "query_type") || get(envelope, "query_type") || "MULTI"),
    decision: null,
    agentsInvoked: get(raw, "agents_invoked") ?? get(envelope, "agents_invoked") ?? [],
    multiResults: children,
    executionTimeMs: undefined,
  };
}

function extractPrWorkflow(envelope: any, raw: any, fallback?: string): NormalisedResult {
  return {
    kind: "pr_workflow",
    agent: "PRCreationWorkflow",
    status: String(get(envelope, "status") || "in_progress"),
    payload: envelope,
    dataSource: "Agentic",
    queryType: "CREATE",
    decision: null,
    agentsInvoked: get(envelope, "agents_invoked") ?? [],
    multiResults: null,
    executionTimeMs: undefined,
  };
}

function extractOdooData(envelope: any, raw: any, fallback?: string): NormalisedResult {
  const payload = get(envelope, "result") ?? envelope;
  return {
    kind: "odoo",
    agent: get(envelope, "agent") || "OdooDataService",
    status: "completed",
    payload: payload && typeof payload === "object" ? payload : {},
    dataSource: "Odoo",
    queryType: String(get(payload, "query_type") || get(envelope, "query_type") || "purchase_orders"),
    decision: null,
    agentsInvoked: [],
    multiResults: null,
    executionTimeMs: undefined,
  };
}

function resolveDataSource(
  ...sources: any[]
): string {
  for (const s of sources) {
    const ds = get(s, "data_source");
    if (ds) {
      const v = String(ds).toLowerCase();
      if (v.includes("odoo")) return "Odoo";
      if (v.includes("agent")) return "Agentic";
      if (v.includes("budget")) return "Budget Tracking";
      if (v.includes("approval")) return "Approval Chains";
      return ds;
    }
  }
  // Infer from agent name
  const agentName = String(
    get(sources[1], "agent") || get(sources[0], "agent") || ""
  ).toLowerCase();
  if (agentName.includes("odoo")) return "Odoo";
  return "Agentic";
}

function extractInvoked(...sources: any[]): string[] {
  for (const s of sources) {
    const arr = get(s, "agents_invoked");
    if (Array.isArray(arr) && arr.length > 0) return arr.map(String);
  }
  return [];
}

function emptyResult(fallback?: string): NormalisedResult {
  return {
    kind: "single",
    agent: fallback || "Agent",
    status: "completed",
    payload: {},
    dataSource: "Agentic",
    queryType: "",
    decision: null,
    agentsInvoked: [],
    multiResults: null,
    executionTimeMs: undefined,
  };
}

// ─────────────────── Agent-type detection helpers ───────────────────

export function isBudgetResult(r: NormalisedResult): boolean {
  const a = r.agent.toLowerCase();
  const p = r.payload;
  return (
    a.includes("budget") ||
    p.budget_verified !== undefined ||
    p.budget_update !== undefined
  );
}

export function isApprovalResult(r: NormalisedResult): boolean {
  const a = r.agent.toLowerCase();
  const p = r.payload;
  return (
    a.includes("approval") &&
    (p.approval_chain !== undefined ||
      p.assigned_approvers !== undefined ||
      p.required_level !== undefined)
  );
}

export function isVendorResult(r: NormalisedResult): boolean {
  const a = r.agent.toLowerCase();
  const p = r.payload;
  return (
    a.includes("vendor") &&
    (p.primary_recommendation !== undefined ||
      p.recommended_vendor !== undefined)
  );
}

export function isRiskResult(r: NormalisedResult): boolean {
  const a = r.agent.toLowerCase();
  const p = r.payload;
  if (!a.includes("risk")) return false;
  // Multi-vendor comparison result (no top-level risk_score)
  if (Array.isArray(p.vendor_risk_comparison)) return true;
  return p.risk_score !== undefined;
}

export function isOdooPoResult(r: NormalisedResult): boolean {
  const p = r.payload;
  return (
    p.total_purchase_orders !== undefined ||
    (Array.isArray(p.purchase_orders) && p.query_type === "purchase_orders")
  );
}

export function isPrWorkflow(r: NormalisedResult): boolean {
  return r.kind === "pr_workflow" || r.payload?.workflow_type === "pr_creation";
}

export function isMultiIntent(r: NormalisedResult): boolean {
  return r.kind === "multi";
}
