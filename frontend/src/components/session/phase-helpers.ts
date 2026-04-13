/**
 * Sprint B (2026-04-11) — phase-helpers.ts
 *
 * Shared types, constants, and pure functions used by the three extracted
 * session display components:
 *
 *   - PhaseTimelineCard.tsx
 *   - AgentExecutionCard.tsx
 *   - DecisionRationaleBlock.tsx
 *
 * Extracted from frontend/src/pages/AgentProcessPage.tsx (deleted in the
 * same sprint). Everything in this file is presentation logic with NO
 * pipelineStore or store imports — the components can be driven by any
 * data source (legacy pipelineStore during hybrid P1–P4, or `useSession`
 * once Sprint D wires the new reducer-fed data shape).
 *
 * Why it lives here: Sprint D needs reusable phase rendering in
 * SessionPage + sub-pages, and the legacy AgentProcessPage had the best
 * implementation of that rendering anywhere in the codebase. Instead of
 * rewriting from scratch or leaving it stranded in a doomed file, we
 * moved it into the session components folder, decoupled it from the
 * store, and left it ready for `useSession` to feed.
 */

import type {
  LucideIcon,
} from "lucide-react";
import {
  CheckCircle2,
  Database,
  Eye,
  Lightbulb,
  Network,
  Search,
  Server,
  Zap,
} from "lucide-react";

/* ================================================================ */
/*  Types                                                            */
/* ================================================================ */

/**
 * A flat timeline phase entry. `key` is unique across the timeline,
 * `basePhase` is the coarse phase name used for display metadata.
 */
export interface TimelinePhase {
  key: string;          // "received" | "BudgetVerificationAgent_deciding" | …
  basePhase: string;    // "deciding"
  agentName?: string;   // "BudgetVerificationAgent"
  data: Record<string, unknown>;
}

/**
 * Per-agent summary used by AgentExecutionCard. This shape is
 * intentionally tolerant so it can be populated from either the legacy
 * `pipelineStore.agentExecutions` array or a future `useSession`-fed
 * reducer projection of `agent_activity` events.
 */
export interface AgentSummary {
  name: string;
  status: "active" | "complete" | "error" | string;
  confidence?: number | null;
  durationMs?: number | null;
  action?: string;
  reasoning?: string;
  model?: string;
  alternatives?: string[];
  tools?: string[];
  phases?: Partial<Record<"OBSERVE" | "DECIDE" | "ACT" | "LEARN", "active" | "complete" | "error">>;
}

/**
 * Decision rationale payload — fed to DecisionRationaleBlock. Matches
 * the shape of the `deciding` phase detail in legacy
 * `agentPhaseDetails` AND the `decision.rationale` branch of a future
 * session-event-based projection.
 */
export interface DecisionRationaleData {
  model?: string;
  action?: unknown;  // string or object (see extractAction)
  confidence?: number | null;
  reasoning?: string;
  alternatives?: string[];
}

/* ================================================================ */
/*  Phase display metadata                                           */
/* ================================================================ */

/**
 * Phase display metadata keyed by SSE/session event base phase name.
 * Used by PhaseTimelineCard rail + labels. Icons are lucide-react.
 */
export const PHASE_META: Record<string, {
  label: string;
  Icon: LucideIcon;
  color: string;
  desc: string;
}> = {
  received:    { label: "Request Received",      Icon: Server,       color: "slate",   desc: "Backend received and validated the incoming request." },
  classifying: { label: "Intent Classification", Icon: Search,       color: "blue",    desc: "AI analyzing the request intent and query type." },
  routing:     { label: "Agent Routing",          Icon: Network,      color: "indigo",  desc: "Orchestrator selecting the optimal specialized agent." },
  observing:   { label: "Observe",                Icon: Eye,          color: "cyan",    desc: "Agent gathering data from databases and ERP systems." },
  deciding:    { label: "Decide",                 Icon: Lightbulb,    color: "purple",  desc: "AI model analyzing data and forming a decision." },
  acting:      { label: "Execute",                Icon: Zap,          color: "amber",   desc: "Agent executing tools and applying the decision." },
  learning:    { label: "Audit Trail",            Icon: Database,     color: "emerald", desc: "Recording decision and outcome for compliance." },
  complete:    { label: "Complete",               Icon: CheckCircle2, color: "green",   desc: "Execution finished — results delivered to frontend." },
};

/**
 * Human-friendly short labels for known agent class names. Unknown
 * agents fall through to `name.replace(/Agent$/, "")` in `agentShort`.
 */
export const AGENT_SHORT: Record<string, string> = {
  BudgetVerificationAgent:   "Budget Check",
  ApprovalRoutingAgent:      "Approval Routing",
  VendorSelectionAgent:      "Vendor Evaluation",
  RiskAssessmentAgent:       "Risk Assessment",
  ComplianceCheckAgent:      "Compliance Check",
  PriceAnalysisAgent:        "Price Analysis",
  SupplierPerformanceAgent:  "Supplier Review",
  ContractMonitoringAgent:   "Contract Check",
  InvoiceMatchingAgent:      "Invoice Matching",
  SpendAnalyticsAgent:       "Spend Analysis",
  SpendAnalysisAgent:        "Spend Analysis",
  InventoryCheckAgent:       "Inventory Check",
  DeliveryTrackingAgent:     "Delivery Tracking",
  ForecastingAgent:          "Demand Forecast",
  DocumentProcessingAgent:   "Doc Processing",
  PaymentReadinessAgent:     "Payment Readiness",
  ReconciliationAgent:       "Reconciliation",
  GoodsReceiptAgent:         "Goods Receipt",
  QualityInspectionAgent:    "Quality Inspection",
  POAmendmentAgent:          "PO Amendment",
  ReturnProcessingAgent:     "Return Processing",
  MultiVendorRiskAgent:      "Multi-Vendor Risk",
};

/**
 * Friendly labels for known P2P / orchestrator action codes. Used by
 * `extractAction` to stringify decision payloads.
 */
export const ACTION_LABELS: Record<string, string> = {
  p2p_full: "Full Procure-to-Pay Pipeline",
  pr_creation: "Purchase Requisition Creation",
  approve: "Approved",
  approve_with_warnings: "Approved with Warnings",
  approve_with_warning: "Approved with Warning",
  approve_with_high_alert: "Approved — High Alert",
  approve_with_critical_alert: "Approved — Critical Alert",
  reject_insufficient_budget: "Rejected — Insufficient Budget",
  recommend_vendor: "Vendor Recommended",
  approve_low_risk: "Approved — Low Risk",
  error_budget_check: "Budget Check Error",
  report_status: "Status Report",
};

/* ================================================================ */
/*  Pure helper functions                                            */
/* ================================================================ */

/** Filter out orchestrator / non-agent names. */
export const isRealAgent = (n: string | undefined | null): boolean =>
  Boolean(n) && typeof n === "string" && n.endsWith("Agent") && n !== "OrchestratorAgent";

/** Format milliseconds for display ("350ms" / "2.4s"). */
export const fmtMs = (ms: number): string =>
  ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;

/** Map a full agent class name to its short display name. */
export const agentShort = (n: string): string =>
  AGENT_SHORT[n] || n.replace(/Agent$/, "");

/**
 * Normalise a confidence value to a 0–100 percent. The backend is
 * inconsistent: some agents emit 0–1 decimals, some emit 0–100 already.
 */
export const normConf = (val: unknown): number => {
  const n = typeof val === "number" ? val : parseFloat(String(val ?? "0"));
  if (isNaN(n)) return 0;
  return n > 1 ? Math.min(n, 100) : n * 100;
};

/**
 * Extract a human-readable action string from a possibly-nested
 * decision payload. Handles strings, stringified JSON, and nested
 * objects with `primary` / `action` / `decision` / etc. keys.
 */
export const extractAction = (action: unknown): string => {
  if (action == null) return "";
  if (typeof action === "string") {
    if (action.startsWith("{")) {
      try { return extractAction(JSON.parse(action)); } catch { /* not JSON */ }
    }
    return ACTION_LABELS[action] || action.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
  }
  if (typeof action === "object" && action !== null) {
    const a = action as Record<string, unknown>;
    const raw =
      a.primary || a.action || a.decision ||
      a.type || a.status || a.verdict;
    if (raw && typeof raw === "string") {
      return ACTION_LABELS[raw] || raw.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
    }
    for (const v of Object.values(a)) {
      if (typeof v === "string" && v.length > 0 && v.length < 80) {
        return ACTION_LABELS[v] || v;
      }
    }
    const keys = Object.keys(a).filter(k => a[k]).slice(0, 3);
    return keys.length > 0 ? keys.join(", ") : "Action recorded";
  }
  return String(action);
};

/**
 * Extract real agent names from a flat `agentPhaseDetails` keymap and
 * an optional `agentExecutions` list. Both inputs may carry the same
 * agents — the function dedupes via Set.
 */
export function extractAgentNames(
  details: Record<string, unknown>,
  executions: Array<{ name: string }> = [],
): string[] {
  const names = new Set<string>();
  for (const key of Object.keys(details)) {
    const m = key.match(/^(.+Agent)_(observing|deciding|acting|learning)$/);
    if (m?.[1] && isRealAgent(m[1])) names.add(m[1]);
  }
  for (const e of executions) {
    if (isRealAgent(e.name)) names.add(e.name);
  }
  return Array.from(names);
}

/**
 * Build a flat TimelinePhase[] from an `agentPhaseDetails` keymap.
 * Copied from the legacy AgentProcessPage `buildTimeline` — same
 * semantics, same fall-through for single-agent runs. Only phases
 * that have actual data appear; nothing is hardcoded or synthesised.
 */
export function buildTimeline(
  details: Record<string, unknown>,
  agents: string[],
): TimelinePhase[] {
  const out: TimelinePhase[] = [];
  const agentPhaseKeys = ["observing", "deciding", "acting", "learning"];

  for (const p of ["received", "classifying", "routing"]) {
    if (details[p]) {
      out.push({ key: p, basePhase: p, data: details[p] as Record<string, unknown> });
    }
  }

  if (agents.length > 0) {
    for (const agent of agents) {
      for (const phase of agentPhaseKeys) {
        const agentKey = `${agent}_${phase}`;
        const data =
          (details[agentKey] as Record<string, unknown> | undefined) ||
          (agents.length === 1 ? (details[phase] as Record<string, unknown> | undefined) : undefined);
        if (data) {
          out.push({ key: agentKey, basePhase: phase, agentName: agent, data });
        }
      }
    }
  } else {
    for (const phase of agentPhaseKeys) {
      if (details[phase]) {
        const data = details[phase] as Record<string, unknown>;
        const agent = data?.agent as string | undefined;
        out.push({
          key: phase,
          basePhase: phase,
          agentName: agent && isRealAgent(agent) ? agent : undefined,
          data,
        });
      }
    }
  }

  if (details.complete) {
    out.push({ key: "complete", basePhase: "complete", data: details.complete as Record<string, unknown> });
  }

  return out;
}
