/**
 * Agent Execution Theater — Enterprise Process Visualization
 *
 * Full-screen cinematic view of the AI agent execution pipeline.
 * Data: Zustand pipelineStore (live) + localStorage processHistory (replay).
 * Purely read-only; never mutates backend state.
 */

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useLocation, useSearch } from "wouter";
import {
  ArrowLeft,
  Activity,
  Brain,
  CheckCircle2,
  ChevronRight,
  Clock,
  Database,
  Eye,
  Lightbulb,
  Loader2,
  MessageSquare,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Trash2,
  Zap,
  ArrowDown,
  Timer,
  Cpu,
  Network,
  BarChart3,
  Sparkles,
  History,
  ChevronDown,
  ChevronUp,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { usePipelineStore } from "@/store/pipelineStore";

/* ================================================================== */
/*  Types                                                              */
/* ================================================================== */

interface HistoryEntry {
  messageId: string;
  sessionId?: string;
  sessionTitle?: string;
  agent: string;
  steps: Array<{
    id: string;
    name: string;
    status: string;
    message: string;
    agent?: string;
    startedAt?: number;
    completedAt?: number;
    durationMs?: number;
  }>;
  details: Record<string, any>;
  timestamp?: number;
  query?: string;
  agents?: string[];
}

interface AgentOutputSummary {
  agentName: string;
  decisionAction?: string;
  confidencePct?: number;
  reasoning?: string;
  model?: string;
  alternatives?: string[];
  tools?: string[];
  executionMs?: number;
  actionResult?: string;
  learned?: boolean;
  lastMessage?: string;
  status?: string;
}

interface BackendBusinessCard {
  id: string;
  summary: string;
  statusBadge: "Processing" | "Approved" | "Escalated" | "Attention Required";
  riskLevel: "Low" | "Medium" | "High";
  financialNote?: string;
  nextAction: string;
}

/* ================================================================== */
/*  Constants                                                          */
/* ================================================================== */

const STORAGE_KEY = "chat_sessions";
const ACTIVE_SESSION_KEY = "active_session_id";
const LIVE_PHASE_HOLD_MS = 700;

const PHASE_ORDER = [
  "received", "classifying", "routing", "observing",
  "deciding", "acting", "learning", "complete",
] as const;

type PhaseKey = typeof PHASE_ORDER[number];

/** A single entry in the dynamic phase list (may be agent-scoped) */
interface DynamicPhase {
  key: string;          // unique key: "received" or "BudgetVerificationAgent_observing"
  basePhase: PhaseKey;  // lookup key in PHASE_META for styling
  agentName?: string;   // set for per-agent phases
  detailKey: string;    // key to look up in phase-details dict
}

interface PhaseMeta {
  icon: React.ReactNode;
  label: string;
  sublabel: string;
  description: string;
  color: string;       // tailwind color stem e.g. "slate", "blue"
  gradient: string;    // from-X-500 to-X-600
}

const PHASE_META: Record<PhaseKey, PhaseMeta> = {
  received: {
    icon: <Server className="h-6 w-6" />,
    label: "REQUEST RECEIVED",
    sublabel: "Entry point",
    description: "The user's natural-language query arrives at the FastAPI backend. The SSE stream opens a persistent connection and the request is hydrated with context hints, PR data extraction, and language metadata.",
    color: "slate",
    gradient: "from-slate-500 to-slate-600",
  },
  classifying: {
    icon: <Search className="h-6 w-6" />,
    label: "INTENT ANALYSIS",
    sublabel: "AI classification",
    description: "The OrchestratorAgent uses GPT-4o-mini to classify the user's intent across 12+ categories: Budget Verification, Risk Assessment, Vendor Selection, Approval Routing, Contract Monitoring, Compliance Check, Price Analysis, and more.",
    color: "blue",
    gradient: "from-blue-500 to-blue-600",
  },
  routing: {
    icon: <Network className="h-6 w-6" />,
    label: "AGENT SELECTION",
    sublabel: "Specialist routing",
    description: "Based on the classification, the orchestrator selects the best specialized agent from 12+ registered agents. Selection factors: confidence score, department context, budget amount, and request complexity.",
    color: "indigo",
    gradient: "from-indigo-500 to-indigo-600",
  },
  observing: {
    icon: <Eye className="h-6 w-6" />,
    label: "BUDGET CHECK",
    sublabel: "Validation",
    description: "The specialized agent's OBSERVE phase gathers context from multiple data sources: Odoo ERP (XML-RPC for purchase orders, vendors, products), PostgreSQL custom tables (budget_tracking, approval_chains), and internal memory.",
    color: "cyan",
    gradient: "from-cyan-500 to-cyan-600",
  },
  deciding: {
    icon: <Brain className="h-6 w-6" />,
    label: "APPROVAL ROUTING",
    sublabel: "Decisioning",
    description: "GPT-4o-mini processes the gathered context through the agent's decision framework. It produces a structured decision with action, confidence score (0–1), reasoning chain, and ranked alternatives for human review.",
    color: "purple",
    gradient: "from-purple-500 to-purple-600",
  },
  acting: {
    icon: <Zap className="h-6 w-6" />,
    label: "VENDOR EVALUATION",
    sublabel: "Execution",
    description: "The decision is executed through LangChain tools: Odoo API calls (create/approve POs, query vendors), PostgreSQL writes (budget updates, approval chain lookups), and notification triggers. Includes retry logic with exponential backoff.",
    color: "amber",
    gradient: "from-amber-500 to-amber-600",
  },
  learning: {
    icon: <Lightbulb className="h-6 w-6" />,
    label: "RISK ASSESSMENT",
    sublabel: "Review",
    description: "The agent records execution outcomes to the agent_actions audit table: input/output data (JSONB), execution time, success status, and error details. This data feeds future pattern recognition and decision optimization.",
    color: "emerald",
    gradient: "from-emerald-500 to-emerald-600",
  },
  complete: {
    icon: <CheckCircle2 className="h-6 w-6" />,
    label: "FINAL DECISION",
    sublabel: "Outcome",
    description: "The structured agent result is formatted into a human-readable response with rich cards: confidence badges, score breakdowns, findings lists, and approval chain visualizations. The SSE stream closes and the UI renders the final answer.",
    color: "green",
    gradient: "from-green-500 to-green-600",
  },
};

/* ================================================================== */
/*  Helpers                                                            */
/* ================================================================== */

function loadLatestProcess(): HistoryEntry | null {
  try {
    const sessionsRaw = localStorage.getItem(STORAGE_KEY);
    const activeId = localStorage.getItem(ACTIVE_SESSION_KEY);
    if (!sessionsRaw || !activeId) return null;
    const sessions = JSON.parse(sessionsRaw) as Array<{
      id: string;
      processHistory?: HistoryEntry[];
    }>;
    const active = sessions.find((s) => s.id === activeId);
    return active?.processHistory?.[0] ?? null;
  } catch {
    return null;
  }
}

function loadAllProcessHistory(): HistoryEntry[] {
  try {
    const sessionsRaw = localStorage.getItem(STORAGE_KEY);
    if (!sessionsRaw) return [];
    const sessions = JSON.parse(sessionsRaw) as Array<{
      id: string;
      title?: string;
      processHistory?: HistoryEntry[];
    }>;

    const all: HistoryEntry[] = [];
    for (const session of sessions) {
      const history = session.processHistory || [];
      for (const entry of history) {
        all.push({
          ...entry,
          sessionId: session.id,
          sessionTitle: session.title,
        });
      }
    }

    return all.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
  } catch {
    return [];
  }
}

function findHistoryEntryById(messageId: string): HistoryEntry | null {
  const all = loadAllProcessHistory();
  return all.find((h) => h.messageId === messageId) || null;
}

function deleteProcessHistoryEntry(messageId: string) {
  try {
    const sessionsRaw = localStorage.getItem(STORAGE_KEY);
    if (!sessionsRaw) return;
    const sessions = JSON.parse(sessionsRaw) as Array<{
      id: string;
      processHistory?: HistoryEntry[];
      [k: string]: any;
    }>;
    const updated = sessions.map((s) => ({
      ...s,
      processHistory: (s.processHistory || []).filter((h) => h.messageId !== messageId),
    }));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  } catch {
    // ignore
  }
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function toPct(value: unknown): number | undefined {
  if (typeof value !== "number" || Number.isNaN(value)) return undefined;
  return value <= 1 ? Math.round(value * 100) : Math.round(value);
}

/* ================================================================== */
/*  Animated elapsed timer                                             */
/* ================================================================== */

function ElapsedTimer({ startMs, isRunning }: { startMs: number; isRunning: boolean }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => setNow(Date.now()), 47);
    return () => clearInterval(id);
  }, [isRunning]);
  const elapsed = isRunning ? now - startMs : 0;
  const secs = (elapsed / 1000).toFixed(1);
  return (
    <span className="font-mono tabular-nums text-lg tracking-wider">
      {secs}<span className="text-muted-foreground text-sm">s</span>
    </span>
  );
}

/* ================================================================== */
/*  Phase Node — a single large step in the timeline                   */
/* ================================================================== */

function PhaseNode({
  phaseKey,
  meta,
  status,
  detail,
  index,
  isLast,
  durationMs,
  agentName,
  phaseCount,
}: {
  phaseKey: PhaseKey;
  meta: PhaseMeta;
  status: "pending" | "active" | "complete";
  detail: Record<string, any> | undefined;
  index: number;
  isLast: boolean;
  durationMs?: number;
  agentName?: string;
  phaseCount?: number;
}) {
  const nodeRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);

  // Auto-scroll active phase into view
  useEffect(() => {
    if (status === "active" && nodeRef.current) {
      nodeRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [status]);

  const isPending = status === "pending";
  const isActive = status === "active";
  const isComplete = status === "complete";

  const collapsedLabel = (() => {
    if (phaseKey === "received") return "Request Received";
    if (phaseKey === "classifying") return "Intent Analysis";
    if (phaseKey === "routing") return "Agent Selection";
    if (phaseKey === "complete") return "Final Decision";
    if (agentName?.includes("BudgetVerification")) return "Budget Check";
    if (agentName?.includes("ApprovalRouting")) return "Approval Routing";
    if (agentName?.includes("VendorSelection")) return "Vendor Evaluation";
    if (agentName?.includes("RiskAssessment")) return "Risk Assessment";
    if (agentName?.includes("SupplierPerformance")) return "Supplier Review";
    if (agentName?.includes("ContractMonitoring")) return "Contract Check";
    if (agentName?.includes("ComplianceCheck")) return "Compliance Check";
    if (agentName?.includes("PriceAnalysis")) return "Price Analysis";
    if (agentName?.includes("InvoiceMatching")) return "Invoice Matching";
    if (agentName?.includes("SpendAnalysis") || agentName?.includes("SpendAnalytics")) return "Spend Analysis";
    if (agentName?.includes("InventoryCheck")) return "Inventory Check";
    if (agentName?.includes("DeliveryTracking")) return "Delivery Tracking";
    if (agentName?.includes("Forecasting")) return "Demand Forecast";
    if (agentName?.includes("DocumentProcessing")) return "Doc Processing";
    if (agentName?.includes("Monitoring") || agentName?.includes("Dashboard")) return "System Monitor";
    // Generic fallback using phase name so it's still meaningful
    if (agentName) {
      const phaseSuffix = phaseKey === "observing" ? "→ Observe" : phaseKey === "deciding" ? "→ Decide" : phaseKey === "acting" ? "→ Act" : phaseKey === "learning" ? "→ Learn" : "";
      return `${agentName.replace(/Agent$/, "")} ${phaseSuffix}`;
    }
    return meta.label;
  })();

  return (
    <div ref={nodeRef} className={`transition-all duration-700 ${isPending ? "opacity-25 scale-[0.97]" : "opacity-100 scale-100"}`}>
      <div className="flex gap-3">
        {/* ---- Timeline column ---- */}
        <div className="flex flex-col items-center w-12 shrink-0">
          {/* Node circle */}
          <div
            className={`relative w-11 h-11 rounded-xl flex items-center justify-center transition-all duration-700 ${
              isActive
                ? `bg-gradient-to-br ${meta.gradient} text-white shadow-lg shadow-${meta.color}-500/30 scale-110`
                : isComplete
                ? "bg-emerald-500/20 text-emerald-400 ring-2 ring-emerald-500/40"
                : "bg-muted/50 text-muted-foreground/40 border-2 border-dashed border-muted-foreground/20"
            }`}
          >
            {isActive && (
              <>
                <div className={`absolute inset-0 rounded-xl bg-gradient-to-br ${meta.gradient} animate-ping opacity-20`} />
                <div className={`absolute -inset-1 rounded-xl bg-gradient-to-br ${meta.gradient} opacity-20 blur-md`} />
              </>
            )}
            <div className="relative z-10">
              {isActive ? <Loader2 className="h-6 w-6 animate-spin" /> : isComplete ? <CheckCircle2 className="h-6 w-6" /> : meta.icon}
            </div>
          </div>
          {/* Connector line */}
          {!isLast && (
            <div className={`w-0.5 flex-1 min-h-[2rem] mt-1 transition-all duration-700 ${
              isComplete ? "bg-gradient-to-b from-emerald-500/60 to-emerald-500/20" : "bg-muted-foreground/10"
            }`} />
          )}
        </div>

        {/* ---- Content column ---- */}
        <div className={`flex-1 pb-3 ${isLast ? "pb-0" : ""}`}>
          {/* Header */}
          <div className="flex items-center gap-3 mb-1.5">
            <h3 className={`font-bold tracking-wide text-sm ${
              isActive ? `text-${meta.color}-400` : isComplete ? "text-emerald-400" : "text-muted-foreground/50"
            }`}>
              {agentName && (
                <span className="text-indigo-400 mr-1.5">{agentName.replace(/Agent$/, '')} →</span>
              )}
              {collapsedLabel}
            </h3>
            {isActive && (
              <Badge className={`bg-${meta.color}-500/20 text-${meta.color}-300 border-${meta.color}-500/30 animate-pulse text-[10px]`}>
                PROCESSING
              </Badge>
            )}
            {isComplete && durationMs != null && (
              <Badge variant="outline" className="text-[10px] border-emerald-500/30 text-emerald-400 gap-1 font-mono">
                <Clock className="h-2.5 w-2.5" /> {formatMs(durationMs)}
              </Badge>
            )}
            <span className="text-[10px] text-muted-foreground/40 ml-auto">
              STEP {index + 1} / {phaseCount ?? PHASE_ORDER.length}
            </span>
            <button
              type="button"
              onClick={() => setExpanded((prev) => !prev)}
              className="text-muted-foreground/70 hover:text-foreground transition-colors"
              aria-label={expanded ? "Collapse details" : "Expand details"}
            >
              {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
          </div>

          {/* Sub-label */}
          <p className={`text-xs mb-2 ${isActive ? `text-${meta.color}-400/70` : "text-muted-foreground/40"}`}>
            {meta.sublabel}
          </p>

          {/* Description card (collapsed by default) */}
          {expanded && (
            <div className={`rounded-xl border p-4 space-y-3 transition-all duration-500 ${
              isActive
                ? `border-${meta.color}-500/30 bg-${meta.color}-500/5 shadow-md shadow-${meta.color}-500/5`
                : "border-border/50 bg-card/50"
            }`}>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {meta.description}
              </p>

              {/* ---- Phase-specific live details ---- */}
              {detail && (
                <div className={`rounded-lg p-3 text-xs space-y-2 bg-${meta.color}-500/5 border border-${meta.color}-500/10`}>
                  {phaseKey === "received" && detail.message && (
                    <div className="space-y-1">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Query</div>
                      <p className="font-medium text-sm leading-snug">"{detail.message}"</p>
                      {detail.timestamp && <div className="text-[10px] text-muted-foreground/50 font-mono">{detail.timestamp}</div>}
                    </div>
                  )}

                  {phaseKey === "classifying" && detail.intent && (
                    <div className="space-y-1">
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Detected Intent</div>
                      <Badge className="bg-blue-500/20 text-blue-300 border-blue-500/30 text-xs">{detail.intent}</Badge>
                    </div>
                  )}

                  {phaseKey === "routing" && (
                    <div className="grid grid-cols-2 gap-3">
                      {detail.agent && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Selected Agent</div>
                          <div className="flex items-center gap-2">
                            <ShieldCheck className="h-4 w-4 text-indigo-400" />
                            <span className="font-semibold text-sm">{detail.agent}</span>
                          </div>
                        </div>
                      )}
                      {detail.confidence != null && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Routing Confidence</div>
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                              <div
                                className="h-full bg-gradient-to-r from-indigo-500 to-indigo-400 rounded-full transition-all duration-1000"
                                style={{ width: `${typeof detail.confidence === "number" && detail.confidence <= 1 ? detail.confidence * 100 : detail.confidence}%` }}
                              />
                            </div>
                            <span className="font-mono font-bold text-sm">
                              {typeof detail.confidence === "number" && detail.confidence <= 1 ? Math.round(detail.confidence * 100) : detail.confidence}%
                            </span>
                          </div>
                        </div>
                      )}
                      {detail.reason && (
                        <div className="col-span-2 space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Reasoning</div>
                          <p className="text-muted-foreground italic">"{detail.reason}"</p>
                        </div>
                      )}
                    </div>
                  )}

                  {phaseKey === "observing" && (
                    <div className="space-y-2">
                      {detail.sources && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Data Sources Queried</div>
                          <div className="flex items-center gap-2 flex-wrap">
                            {(Array.isArray(detail.sources) ? detail.sources : [detail.sources]).map((s: string, i: number) => (
                              <Badge key={i} variant="outline" className="text-[10px] gap-1">
                                <Database className="h-2.5 w-2.5" /> {s}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                      {detail.recordsFound && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Records Retrieved</div>
                          <span className="font-mono font-bold text-lg">{detail.recordsFound}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {phaseKey === "deciding" && (
                    <div className="space-y-2">
                      <div className="grid grid-cols-2 gap-3">
                        {detail.model && (
                          <div className="space-y-1">
                            <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">AI Model</div>
                            <div className="flex items-center gap-2"><Cpu className="h-3.5 w-3.5 text-purple-400" /><span className="font-mono text-sm">{detail.model}</span></div>
                          </div>
                        )}
                        {detail.action && (
                          <div className="space-y-1">
                            <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Decision</div>
                            <Badge className="bg-purple-500/20 text-purple-300 border-purple-500/30">{detail.action}</Badge>
                          </div>
                        )}
                      </div>
                      {detail.confidence != null && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Decision Confidence</div>
                          <div className="flex items-center gap-3">
                            <div className="flex-1 h-3 bg-muted rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all duration-1000 ${
                                  (detail.confidence > 80 || detail.confidence > 0.8) ? "bg-gradient-to-r from-emerald-500 to-emerald-400" :
                                  (detail.confidence > 60 || detail.confidence > 0.6) ? "bg-gradient-to-r from-amber-500 to-amber-400" :
                                  "bg-gradient-to-r from-red-500 to-red-400"
                                }`}
                                style={{ width: `${detail.confidence > 1 ? detail.confidence : detail.confidence * 100}%` }}
                              />
                            </div>
                            <span className="font-mono font-bold text-lg min-w-[3rem] text-right">
                              {detail.confidence > 1 ? detail.confidence : Math.round(detail.confidence * 100)}%
                            </span>
                          </div>
                        </div>
                      )}
                      {detail.reasoning && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Reasoning Chain</div>
                          <p className="text-muted-foreground italic leading-relaxed">"{detail.reasoning}"</p>
                        </div>
                      )}
                      {detail.alternatives && Array.isArray(detail.alternatives) && detail.alternatives.length > 0 && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Alternatives Considered</div>
                          <div className="flex gap-2 flex-wrap">
                            {detail.alternatives.map((alt: string, i: number) => (
                              <Badge key={i} variant="outline" className="text-[10px] text-muted-foreground">{alt}</Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {phaseKey === "acting" && (
                    <div className="space-y-2">
                      {detail.tools && Array.isArray(detail.tools) && detail.tools.length > 0 && (
                        <div className="space-y-1.5">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Tools Invoked</div>
                          <div className="space-y-1.5">
                            {detail.tools.map((t: string, i: number) => {
                              const lower = t.toLowerCase();
                              const isOdoo = lower.includes("odoo") || lower.includes("vendor") || lower.includes("purchase") || lower.includes("product");
                              return (
                                <div key={i} className="flex items-center gap-2 p-2 rounded-lg bg-background/50 border border-border/30">
                                  <Badge className={`text-[9px] ${isOdoo ? "bg-amber-500/20 text-amber-300 border-amber-500/30" : "bg-teal-500/20 text-teal-300 border-teal-500/30"}`}>
                                    {isOdoo ? "Odoo" : "PostgreSQL"}
                                  </Badge>
                                  <span className="font-mono text-xs">{t}</span>
                                  {isComplete && <CheckCircle2 className="h-3 w-3 text-emerald-400 ml-auto" />}
                                  {isActive && <Loader2 className="h-3 w-3 text-blue-400 ml-auto animate-spin" />}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                      {detail.timing != null && (
                        <div className="space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Execution Time</div>
                          <span className="font-mono font-bold text-lg">{formatMs(detail.timing)}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {phaseKey === "learning" && (
                    <div className="flex items-center gap-3 py-1">
                      <Database className="h-5 w-5 text-emerald-400" />
                      <div>
                        <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Audit Trail</div>
                        <span className="font-mono text-sm">agent_actions</span>
                        {detail.recorded && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 inline ml-2" />}
                      </div>
                    </div>
                  )}

                  {phaseKey === "complete" && (
                    <div className="flex items-center gap-2 text-emerald-400">
                      <Sparkles className="h-4 w-4" />
                      <span className="font-medium">Response delivered to UI</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  Auto-return banner with countdown                                  */
/* ================================================================== */

function AutoReturnBanner({
  totalMs,
  agentExecutions,
  onBack,
}: {
  totalMs: number | null;
  agentExecutions: Array<{ name: string; confidence?: number | null; status: string }>;
  onBack: () => void;
}) {
  const [countdown, setCountdown] = useState(15);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  useEffect(() => {
    setCountdown(15); // Start at 15 seconds
    const id = setInterval(() => setCountdown((c) => c - 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div ref={ref} className="rounded-2xl border border-emerald-500/30 bg-gradient-to-br from-emerald-500/10 via-background to-emerald-500/5 p-6 text-center space-y-4 animate-in fade-in duration-700">
      <div className="flex justify-center">
        <div className="w-16 h-16 rounded-full bg-emerald-500/20 flex items-center justify-center">
          <CheckCircle2 className="h-8 w-8 text-emerald-400" />
        </div>
      </div>
      <div>
        <h3 className="text-lg font-bold text-emerald-400">Execution Complete</h3>
        <p className="text-sm text-muted-foreground mt-1">
          All pipeline phases finished successfully.
          {totalMs != null && <> Total time: <span className="font-mono font-bold">{formatMs(totalMs)}</span></>}
        </p>
        <p className="text-xs text-muted-foreground/60 mt-2">
          Returning to chat in <span className="font-mono font-bold text-indigo-400">{Math.max(countdown, 0)}s</span> — <span className="text-emerald-400">Review the pipeline details above</span>
        </p>
      </div>
      <div className="flex gap-3 justify-center pt-2">
        {agentExecutions.length > 0 && agentExecutions.map((exec) => (
          <Badge key={exec.name} variant="outline" className="text-xs gap-1">
            {exec.name}
            {exec.confidence != null && (
              <span className="font-mono text-emerald-400">
                {Math.round((exec.confidence > 1 ? exec.confidence : exec.confidence * 100))}%
              </span>
            )}
          </Badge>
        ))}
      </div>
      <Button variant="outline" onClick={onBack} className="gap-2 mt-2">
        <ArrowLeft className="h-4 w-4" /> Back to Chat Now
      </Button>
    </div>
  );
}

/* ================================================================== */
/*  Main Page                                                          */
/* ================================================================== */

export default function AgentProcessPage() {
  const [locationPath, setLocation] = useLocation();
  const searchString = useSearch();
  const pipelineStatus = usePipelineStore((s) => s.status);
  const pipelineAgentExecutions = usePipelineStore((s) => s.agentExecutions);
  const pipelineToolCalls = usePipelineStore((s) => s.toolCalls);
  const pipelineLogs = usePipelineStore((s) => s.logs);
  const pipelineQueryText = usePipelineStore((s) => s.queryText);
  const storePhaseDetails = usePipelineStore((s) => s.agentPhaseDetails);
  const storeAgentName = usePipelineStore((s) => s.currentAgentName);

  // URL param: ?id=<messageId> to load a specific pipeline
  const urlId = useMemo(() => new URLSearchParams(searchString).get("id"), [searchString]);

  const [historyEntry, setHistoryEntry] = useState<HistoryEntry | null>(null);
  const [allHistory, setAllHistory] = useState<HistoryEntry[]>([]);
  // Auto-show history when we're not in a live stream
  const [showHistory, setShowHistory] = useState(false);
  const [showCommentary, setShowCommentary] = useState(false);
  const isExecutiveAlias = locationPath === "/executive-demo";
  const [showBusinessPanel, setShowBusinessPanel] = useState(isExecutiveAlias);
  const [backendBusinessCards, setBackendBusinessCards] = useState<BackendBusinessCard[]>([]);
  const [businessSource, setBusinessSource] = useState<"backend-live" | "fallback">("fallback");
  const [isPresenting, setIsPresenting] = useState(false);
  const pageRootRef = useRef<HTMLDivElement | null>(null);
  const businessCardSeqRef = useRef(0);

  useEffect(() => {
    if (isExecutiveAlias) {
      setShowBusinessPanel(true);
    }
  }, [isExecutiveAlias]);

  useEffect(() => {
    const root = pageRootRef.current;
    if (!root) return;

    const mainEl = root.closest("main");
    const contentShell = mainEl?.parentElement as HTMLElement | null;
    const appShell = contentShell?.parentElement as HTMLElement | null;
    const desktopSidebar = appShell?.querySelector(":scope > aside") as HTMLElement | null;

    if (!contentShell || !desktopSidebar) return;

    const prevSidebarDisplay = desktopSidebar.style.display;
    const prevContentWidth = contentShell.style.width;
    const prevContentMaxWidth = contentShell.style.maxWidth;

    if (isPresenting) {
      desktopSidebar.style.display = "none";
      contentShell.style.width = "100%";
      contentShell.style.maxWidth = "100%";
    } else {
      desktopSidebar.style.display = prevSidebarDisplay || "";
      contentShell.style.width = prevContentWidth || "";
      contentShell.style.maxWidth = prevContentMaxWidth || "";
    }

    return () => {
      desktopSidebar.style.display = prevSidebarDisplay || "";
      contentShell.style.width = prevContentWidth || "";
      contentShell.style.maxWidth = prevContentMaxWidth || "";
    };
  }, [isPresenting]);

  useEffect(() => {
    const toWsUrl = () => {
      const envBase = (import.meta as any).env?.VITE_API_URL || "";
      if (envBase) {
        return `${String(envBase).replace(/^http/i, "ws")}/ws/executive-demo`;
      }
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${protocol}//${window.location.hostname}:5000/ws/executive-demo`;
    };

    const nextBusinessCardId = (sessionId: string, channel: "b" | "t") => {
      businessCardSeqRef.current += 1;
      return `${sessionId}-${channel}-${businessCardSeqRef.current}`;
    };

    const mapBusinessPayloadToCard = (payload: any, idSeed: string): BackendBusinessCard | null => {
      if (!payload) return null;

      const summary = typeof payload.summary === "string" && payload.summary.trim()
        ? payload.summary
        : "Procurement check in progress. The system is validating this step automatically.";

      const statusRaw = String(payload.status_badge || "Processing");
      const statusBadge: BackendBusinessCard["statusBadge"] =
        statusRaw === "Approved" || statusRaw === "Escalated" || statusRaw === "Attention Required"
          ? statusRaw
          : "Processing";

      const riskRaw = String(payload.risk_level || "Medium");
      const riskLevel: BackendBusinessCard["riskLevel"] =
        riskRaw === "Low" || riskRaw === "High" ? riskRaw : "Medium";

      const financialNote = payload.financial_impact_note
        ? String(payload.financial_impact_note)
        : undefined;

      const nextAction = typeof payload.recommended_next_action === "string" && payload.recommended_next_action.trim()
        ? payload.recommended_next_action
        : "Continue monitoring this request while validations complete.";

      return {
        id: idSeed,
        summary,
        statusBadge,
        riskLevel,
        financialNote,
        nextAction,
      };
    };

    const mapTechnicalToBusinessCard = (payload: any, idSeed: string): BackendBusinessCard | null => {
      if (!payload) return null;

      const agentName = String(payload.agent_name || "");
      const phase = String(payload.phase || "").toUpperCase();
      const status = String(payload.status || "").toLowerCase();
      const confidence = typeof payload.confidence_score === "number"
        ? (payload.confidence_score <= 1 ? payload.confidence_score * 100 : payload.confidence_score)
        : undefined;

      let summary = "Procurement check in progress. The system is validating this step automatically.";
      let statusBadge: BackendBusinessCard["statusBadge"] = "Processing";
      let riskLevel: BackendBusinessCard["riskLevel"] = "Medium";
      let nextAction = "Wait for the current validation step to complete automatically.";

      if (agentName.includes("Orchestrator") && phase === "OBSERVE") {
        summary = "Your procurement request has been received and is being reviewed by the AI system.";
        statusBadge = "Processing";
        riskLevel = "Low";
        nextAction = "No action required, the request intake review is in progress.";
      } else if (agentName.includes("Orchestrator") && phase === "DECIDE") {
        summary = "The system has understood what you need and is identifying the right approval process.";
        statusBadge = "Processing";
        riskLevel = "Low";
        nextAction = "Wait while the correct approval path is selected automatically.";
      } else if (agentName.includes("Orchestrator") && phase === "ACT") {
        summary = "The request has been assigned to the relevant procurement specialists for processing.";
        statusBadge = "Processing";
        riskLevel = "Low";
        nextAction = "Await specialist validation results before taking action.";
      } else if (agentName.includes("BudgetVerification")) {
        if (status === "failed" || (typeof confidence === "number" && confidence < 60)) {
          summary = "Budget alert. Available funds may be insufficient for this request. Escalation recommended.";
          statusBadge = "Escalated";
          riskLevel = "High";
          nextAction = "Await Finance Director approval.";
        } else {
          summary = "Budget confirmed. Sufficient funds are available in the department to proceed with this request.";
          statusBadge = status === "completed" ? "Approved" : "Processing";
          riskLevel = "Low";
          nextAction = "No action required, proceeding automatically.";
        }
      } else if (agentName.includes("ApprovalRouting")) {
        summary = "Approval path identified. The request will be reviewed by the appropriate authority based on the order value.";
        statusBadge = status === "completed" ? "Approved" : "Processing";
        riskLevel = "Low";
        nextAction = "Await assigned approver decision.";
      } else if (agentName.includes("VendorSelection")) {
        summary = "Vendor evaluation complete. The highest-scoring supplier has been identified based on price, quality, and delivery history.";
        statusBadge = status === "completed" ? "Approved" : "Processing";
        riskLevel = "Low";
        nextAction = "Review recommended supplier and confirm purchase direction.";
      } else if (agentName.includes("RiskAssessment")) {
        if ((typeof confidence === "number" && confidence >= 80) && status !== "failed") {
          summary = "Risk check passed. No significant compliance or supplier risks detected.";
          statusBadge = status === "completed" ? "Approved" : "Processing";
          riskLevel = "Low";
          nextAction = "No action required, proceeding automatically.";
        } else {
          summary = "Risk flagged. This request requires additional review before proceeding.";
          statusBadge = status === "completed" ? "Escalated" : "Processing";
          riskLevel = status === "failed" ? "High" : "Medium";
          nextAction = "Review risk notes and confirm mitigation decision.";
        }
      } else if (agentName.includes("SupplierPerformance")) {
        summary = "Supplier track record verified. Historical performance meets the required standards.";
        statusBadge = status === "completed" ? "Approved" : "Processing";
        riskLevel = "Low";
        nextAction = "No action required, proceeding automatically.";
      } else if (agentName.includes("ContractMonitoring")) {
        summary = "Contract status checked. Existing agreements with this supplier are current and valid.";
        statusBadge = status === "completed" ? "Approved" : "Processing";
        riskLevel = "Low";
        nextAction = "Proceed under current contract terms.";
      } else if (phase === "COMPLETE") {
        if (status === "failed" || (typeof confidence === "number" && confidence < 60)) {
          summary = "Request escalated for human review. The system has flagged items that require manual decision before proceeding.";
          statusBadge = "Escalated";
          riskLevel = "High";
          nextAction = "Await senior approver decision before release.";
        } else {
          summary = "Request processed successfully. All checks passed and the procurement request is ready for final approval.";
          statusBadge = "Approved";
          riskLevel = "Low";
          nextAction = "Await Finance Director approval.";
        }
      } else if (status === "failed") {
        statusBadge = "Attention Required";
        riskLevel = "High";
        nextAction = "Review the issue and restart this request after correction.";
      }

      return {
        id: idSeed,
        summary,
        statusBadge,
        riskLevel,
        financialNote: undefined,
        nextAction,
      };
    };

    const toApiUrl = (path: string) => {
      const envBase = (import.meta as any).env?.VITE_API_URL || "";
      return envBase ? `${envBase}${path}` : path;
    };

    const loadLastSession = async () => {
      try {
        const res = await fetch(toApiUrl("/api/executive-demo/last-session"), { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const events = Array.isArray(data?.session?.events) ? data.session.events : [];
        const businessEvents = events.filter((evt: any) => evt?.event_type === "business-panel");

        const mapped = (businessEvents.length > 0
          ? businessEvents.map((evt: any) => mapBusinessPayloadToCard(evt?.payload, nextBusinessCardId(String(evt?.session_id || "last"), "b")))
          : events
              .filter((evt: any) => evt?.event_type === "technical-panel")
              .map((evt: any) => mapTechnicalToBusinessCard(evt?.payload, nextBusinessCardId(String(evt?.session_id || "last"), "t")))
        ).filter(Boolean) as BackendBusinessCard[];

        if (mapped.length > 0) {
          setBackendBusinessCards(mapped.slice(-20));
          setBusinessSource("backend-live");
        }
      } catch {
        // fallback stays active
      }
    };

    loadLastSession();

    const ws = new WebSocket(toWsUrl());
    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data || "{}");
        const eventType = String(parsed?.event_type || "");
        if (eventType !== "business-panel" && eventType !== "technical-panel") return;
        const eventSessionId = String(parsed?.session_id || "live");

        const mapped = eventType === "business-panel"
          ? mapBusinessPayloadToCard(parsed?.payload, nextBusinessCardId(eventSessionId, "b"))
          : mapTechnicalToBusinessCard(parsed?.payload, nextBusinessCardId(eventSessionId, "t"));

        if (!mapped) return;
        setBackendBusinessCards((prev) => [...prev, mapped].slice(-20));
        setBusinessSource("backend-live");
      } catch {
        // ignore malformed event
      }
    };
    ws.onerror = () => {
      setBusinessSource((prev) => (prev === "backend-live" ? prev : "fallback"));
    };

    return () => {
      try {
        ws.close();
      } catch {
        // ignore close failures
      }
    };
  }, []);

  // Determine mode: live (stream running) vs replay (from history).
  // When a specific history run is selected via ?id=..., always render replay mode.
  const isViewingHistory = Boolean(urlId);
  const isLive = !isViewingHistory && pipelineStatus === "running";
  const isDone = !isViewingHistory && pipelineStatus === "done";

  // Load pipeline history
  const refreshHistory = useCallback(() => {
    const all = loadAllProcessHistory();
    setAllHistory(all);
    return all;
  }, []);

  // Reload history when pipeline status changes or on mount
  useEffect(() => {
    const all = refreshHistory();
    if (!isLive) {
      if (urlId) {
        const match = findHistoryEntryById(urlId);
        setHistoryEntry(match || all[0] || null);
      } else {
        setHistoryEntry(all[0] || null);
      }
    }
  }, [isLive, urlId, refreshHistory]);

  const handleDeleteEntry = useCallback((messageId: string) => {
    deleteProcessHistoryEntry(messageId);
    const all = refreshHistory();
    if (historyEntry?.messageId === messageId) {
      setHistoryEntry(all[0] || null);
    }
  }, [refreshHistory, historyEntry?.messageId]);

  const handleSelectEntry = useCallback((entry: HistoryEntry) => {
    if (entry.sessionId) {
      localStorage.setItem(ACTIVE_SESSION_KEY, entry.sessionId);
    }
    setHistoryEntry(entry);
    setShowHistory(false);
    setLocation(`/process?id=${entry.messageId}`, { replace: true });
  }, [setLocation]);

  const entry = historyEntry;

  // Keep history dropdown fully manual: never auto-open.
  useEffect(() => {
    if (isLive && showHistory) {
      setShowHistory(false);
    }
  }, [isLive, showHistory]);

  // DATA SOURCES: live mode uses pipelineStore directly; replay uses history
  const details: Record<string, any> = isLive || isDone
    ? storePhaseDetails
    : (entry?.details ?? {});
  // Collect all agent names: from live pipelineStore or from saved history
  const allAgentNames: string[] = useMemo(() => {
    if (isLive || isDone) {
      const names = new Set<string>();
      // Add all completed agents from executions array
      pipelineAgentExecutions.forEach(e => names.add(e.name));
      // CRITICAL: Also add the currently-executing agent
      if (storeAgentName) names.add(storeAgentName);
      return Array.from(names);
    }
    if (entry?.agents && entry.agents.length > 0) return entry.agents;
    if (entry?.agent) return [entry.agent];
    return [];
  }, [isLive, isDone, pipelineAgentExecutions, storeAgentName, entry]);
  const queryText = pipelineQueryText || entry?.query || (details.received as any)?.message || "";
  const steps = entry?.steps ?? [];

  const [startTime] = useState(Date.now());

  // Build the dynamic phase list: single-agent uses flat keys, multi-agent expands per-agent
  const dynamicPhases: DynamicPhase[] = useMemo(() => {
    const phases: DynamicPhase[] = [
      { key: "received",    basePhase: "received",    detailKey: "received" },
      { key: "classifying", basePhase: "classifying", detailKey: "classifying" },
      { key: "routing",     basePhase: "routing",     detailKey: "routing" },
    ];

    // Filter out OrchestratorAgent — it doesn't run OBSERVE/DECIDE/ACT/LEARN
    const executingAgents = allAgentNames.filter(n => n !== "OrchestratorAgent");
    const agentPhases = ["observing", "deciding", "acting", "learning"] as const;

    if (executingAgents.length > 1) {
      // Multi-agent: per-agent OBSERVE → DECIDE → ACT → LEARN sections
      for (const agent of executingAgents) {
        for (const phase of agentPhases) {
          phases.push({
            key: `${agent}_${phase}`,
            basePhase: phase,
            agentName: agent,
            detailKey: `${agent}_${phase}`,
          });
        }
      }
    } else {
      // Single agent: flat keys
      for (const phase of agentPhases) {
        phases.push({ key: phase, basePhase: phase, detailKey: phase });
      }
    }

    phases.push({ key: "complete", basePhase: "complete", detailKey: "complete" });
    return phases;
  }, [allAgentNames]);

  // Determine which phases have arrived (for step-by-step reveal in live mode)
  const arrivedPhases = useMemo(() => {
    const arrived = new Set<string>();
    for (const phase of dynamicPhases) {
      if (details[phase.detailKey]) arrived.add(phase.key);
    }
    return arrived;
  }, [details, dynamicPhases]);

  // Keep a cumulative set of phases that have ever arrived in this run.
  // This prevents already-revealed phases from disappearing if `details` is overwritten.
  const [arrivedEver, setArrivedEver] = useState<Set<string>>(new Set());
  useEffect(() => {
    setArrivedEver((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const key of arrivedPhases) {
        if (!next.has(key)) {
          next.add(key);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [arrivedPhases]);

  // Compute the highest arrived phase index for step-by-step reveal
  const highestArrivedIdx = useMemo(() => {
    let highest = -1;
    for (let i = 0; i < dynamicPhases.length; i++) {
      if (arrivedEver.has(dynamicPhases[i].key)) highest = i;
    }
    return highest;
  }, [arrivedEver, dynamicPhases]);

  // For replay mode: animated reveal one step at a time
  const [replayRevealIdx, setReplayRevealIdx] = useState(-1);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // For live mode: gradual reveal with 700ms delays (streaming effect)
  const [liveRevealIdx, setLiveRevealIdx] = useState(-1);
  const [isRevealing, setIsRevealing] = useState(false);
  const [visiblePhaseKeys, setVisiblePhaseKeys] = useState<Set<string>>(new Set());
  const liveTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const arrivedPhasesRef = useRef<Set<string>>(new Set());
  const dynamicPhasesRef = useRef<DynamicPhase[]>([]);
  const isDoneRef = useRef(false);

  // Update ref whenever cumulative arrivals change (no timer restart)
  useEffect(() => {
    arrivedPhasesRef.current = arrivedEver;
  }, [arrivedEver]);

  useEffect(() => {
    dynamicPhasesRef.current = dynamicPhases;
  }, [dynamicPhases]);

  useEffect(() => {
    isDoneRef.current = isDone;
  }, [isDone]);

  // Start revealing when live mode begins
  useEffect(() => {
    console.log(`[REVEAL STATE] isLive: ${isLive}, isDone: ${isDone}, isRevealing: ${isRevealing}`);
    if (isLive && !isRevealing) {
      console.log(`[LIVE REVEAL] ✅ Pipeline started - beginning gradual reveal`);
      setArrivedEver(new Set());
      setVisiblePhaseKeys(new Set());
      setIsRevealing(true);
      setLiveRevealIdx(-1);
    }
    if (!isLive && !isDone && isRevealing) {
      // Only stop if we're truly idle (not just done)
      console.log(`[LIVE REVEAL] ❌ Stopping reveal - pipeline idle`);
      setIsRevealing(false);
    }
  }, [isLive, isDone, isRevealing]);

  // Live reveal timer: increment every 5 seconds until all phases revealed
  useEffect(() => {
    if (!isRevealing) {
      if (liveTimerRef.current) {
        clearInterval(liveTimerRef.current);
        liveTimerRef.current = null;
      }
      return;
    }

    // Start gradual reveal timer
    console.log(`[LIVE REVEAL] Starting timer - ${LIVE_PHASE_HOLD_MS}ms intervals`);
    let idx = -1;
    
    liveTimerRef.current = setInterval(() => {
      const phases = dynamicPhasesRef.current;
      const arrived = arrivedPhasesRef.current;

      // Reveal the next arrived phase in timeline order.
      // This handles sparse arrivals where some intermediate phases never emit.
      let nextIdx = -1;
      for (let i = idx + 1; i < phases.length; i++) {
        if (arrived.has(phases[i].key)) {
          nextIdx = i;
          break;
        }
      }

      if (nextIdx !== -1) {
        idx = nextIdx;
        console.log(`[LIVE REVEAL] 🎬 Revealing phase ${idx} (${phases[idx].key}) | Arrived: ${arrived.size}`);
        setLiveRevealIdx(idx);
        setVisiblePhaseKeys((prev) => {
          const next = new Set(prev);
          next.add(phases[idx].key);
          return next;
        });
        return;
      }

      let highestArrived = -1;
      for (let i = phases.length - 1; i >= 0; i--) {
        if (arrived.has(phases[i].key)) {
          highestArrived = i;
          break;
        }
      }

      if (isDoneRef.current && highestArrived !== -1 && idx >= highestArrived) {
        console.log(`[LIVE REVEAL] ✅ All phases revealed (last index ${highestArrived}) - stopping timer`);
        setIsRevealing(false);
      } else {
        console.log(`[LIVE REVEAL] ⏳ Waiting... idx: ${idx}, arrivedCount: ${arrived.size}, highestArrived: ${highestArrived}`);
      }
    }, LIVE_PHASE_HOLD_MS);

    return () => {
      console.log(`[LIVE REVEAL] Cleaning up timer`);
      if (liveTimerRef.current) {
        clearInterval(liveTimerRef.current);
        liveTimerRef.current = null;
      }
    };
  }, [isRevealing]); // Only re-run when isRevealing changes

  // Replay mode timer (unchanged)
  useEffect(() => {
    if (isLive || isDone) {
      setReplayRevealIdx(dynamicPhases.length);
      return;
    }
    // Replay: reveal one step every 600ms
    setReplayRevealIdx(-1);
    let idx = -1;
    timerRef.current = setInterval(() => {
      idx += 1;
      if (idx >= dynamicPhases.length) {
        if (timerRef.current) clearInterval(timerRef.current);
        return;
      }
      setReplayRevealIdx(idx);
    }, 600);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [isLive, isDone, entry?.messageId]);

  // The effective revealed index: prioritize active reveal, fallback to instant display
  const revealedIndex = isRevealing 
    ? liveRevealIdx 
    : (isLive || isDone) 
      ? highestArrivedIdx 
      : replayRevealIdx;

  // Debug: Log revealedIndex changes
  useEffect(() => {
    console.log(`[REVEALED INDEX] Changed to: ${revealedIndex} | isRevealing: ${isRevealing}, isLive: ${isLive}, isDone: ${isDone}`);
  }, [revealedIndex, isRevealing, isLive, isDone]);

  // Auto-follow the newest revealed phase in the timeline.
  useEffect(() => {
    if (revealedIndex < 0) return;
    const phase = dynamicPhases[revealedIndex];
    if (!phase) return;
    const node = document.getElementById(`phase-row-${phase.key}`);
    if (!node) {
      console.log(`[PROCESS SCROLL] Target not found for revealed index ${revealedIndex} (${phase.key})`);
      return;
    }
    console.log(`[PROCESS SCROLL] Scrolling to phase ${revealedIndex} (${phase.key})`);
    node.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [revealedIndex, dynamicPhases]);

  // Debug: High-level state snapshot for each major transition
  useEffect(() => {
    console.log("[PROCESS SNAPSHOT]", {
      pipelineStatus,
      isLive,
      isDone,
      isRevealing,
      visibleCount: visiblePhaseKeys.size,
      revealedIndex,
      highestArrivedIdx,
      arrivedCount: arrivedPhases.size,
      arrivedEverCount: arrivedEver.size,
      dynamicPhaseCount: dynamicPhases.length,
    });
  }, [
    pipelineStatus,
    isLive,
    isDone,
    isRevealing,
    visiblePhaseKeys,
    revealedIndex,
    highestArrivedIdx,
    arrivedPhases,
    arrivedEver,
    dynamicPhases.length,
  ]);

  // Compute step map for quick lookup (from history)
  const stepMap = useMemo(() => {
    const m: Record<string, HistoryEntry["steps"][0]> = {};
    for (const s of steps) m[s.id] = s;
    return m;
  }, [steps]);

  // Compute overall timing from pipeline elapsed
  const pipelineElapsed = usePipelineStore((s) => s.elapsed);
  const totalMs = useMemo(() => {
    if (pipelineElapsed > 0) return pipelineElapsed;
    if (steps.length === 0) return null;
    const first = steps.find((s) => s.startedAt);
    const last = [...steps].reverse().find((s) => s.completedAt);
    if (first?.startedAt && last?.completedAt) return last.completedAt - first.startedAt;
    return steps.reduce((sum, s) => sum + (s.durationMs ?? 0), 0) || null;
  }, [steps, pipelineElapsed]);

  const phaseCount = dynamicPhases.length;
  const arrivedCount = arrivedEver.size;
  const staggerComplete = isDone;
  const progressPct = (isLive || isDone)
    ? (staggerComplete ? 100 : Math.min(95, Math.round((arrivedCount / phaseCount) * 100)))
    : steps.length > 0
    ? Math.round((steps.filter((s) => s.status === "complete").length / steps.length) * 100)
    : 0;

  const hasData = arrivedCount > 0 || steps.length > 0 || isLive;

  // Aggregate a concise, per-agent output view from streamed phase details.
  const agentOutputSummaries: AgentOutputSummary[] = useMemo(() => {
    const names = new Set<string>(allAgentNames.filter(n => n !== "OrchestratorAgent"));

    for (const key of Object.keys(details || {})) {
      const m = key.match(/^(.*)_(observing|deciding|acting|learning)$/);
      if (m && m[1]) names.add(m[1]);
    }

    return Array.from(names).map((agentName) => {
      const deciding = details?.[`${agentName}_deciding`] || {};
      const acting = details?.[`${agentName}_acting`] || {};
      const learning = details?.[`${agentName}_learning`] || {};
      const exec = pipelineAgentExecutions.find((e) => e.name === agentName);

      return {
        agentName,
        decisionAction: deciding.action,
        confidencePct: toPct(deciding.confidence ?? exec?.confidence),
        reasoning: deciding.reasoning,
        model: deciding.model,
        alternatives: Array.isArray(deciding.alternatives) ? deciding.alternatives : [],
        tools: Array.isArray(acting.tools) ? acting.tools : [],
        executionMs: typeof acting.timing === "number" ? acting.timing : exec?.durationMs,
        actionResult: acting.result,
        learned: Boolean(learning.recorded),
        lastMessage: exec?.lastMessage,
        status: exec?.status,
      };
    });
  }, [allAgentNames, details, pipelineAgentExecutions]);

  // Build short narrative commentary from the currently visible phases.
  const commentaryLines = useMemo(() => {
    const lines: string[] = [];

    for (const phase of dynamicPhases) {
      if (!arrivedEver.has(phase.key)) continue;

      const detail = details?.[phase.detailKey] ?? {};
      const agentPrefix = phase.agentName ? `${phase.agentName.replace(/Agent$/, "")}: ` : "";

      switch (phase.basePhase) {
        case "received": {
          const msg = detail?.message ? `Request received: "${String(detail.message)}"` : "Request received by backend stream.";
          lines.push(msg);
          break;
        }
        case "classifying": {
          const intent = detail?.intent ? String(detail.intent) : "request";
          lines.push(`Intent classified as ${intent}.`);
          break;
        }
        case "routing": {
          const routedAgent = detail?.agent ? String(detail.agent) : "specialized agent";
          const confidence = typeof detail?.confidence === "number"
            ? (detail.confidence <= 1 ? `${Math.round(detail.confidence * 100)}%` : `${Math.round(detail.confidence)}%`)
            : null;
          lines.push(
            confidence
              ? `Routed to ${routedAgent} with ${confidence} confidence.`
              : `Routed to ${routedAgent}.`
          );
          break;
        }
        case "observing": {
          const sources = Array.isArray(detail?.sources)
            ? detail.sources.join(", ")
            : detail?.sources
              ? String(detail.sources)
              : "multiple sources";
          lines.push(`${agentPrefix}Collecting context from ${sources}.`);
          break;
        }
        case "deciding": {
          const action = detail?.action ? String(detail.action) : "decision";
          const confidence = typeof detail?.confidence === "number"
            ? (detail.confidence <= 1 ? `${Math.round(detail.confidence * 100)}%` : `${Math.round(detail.confidence)}%`)
            : null;
          lines.push(
            confidence
              ? `${agentPrefix}Decision: ${action} (${confidence} confidence).`
              : `${agentPrefix}Decision made: ${action}.`
          );
          if (detail?.reasoning) {
            lines.push(`${agentPrefix}${String(detail.reasoning)}`);
          }
          break;
        }
        case "acting": {
          const toolCount = Array.isArray(detail?.tools) ? detail.tools.length : 0;
          lines.push(
            toolCount > 0
              ? `${agentPrefix}Executing ${toolCount} tool${toolCount > 1 ? "s" : ""}.`
              : `${agentPrefix}Executing action.`
          );
          break;
        }
        case "learning": {
          lines.push(`${agentPrefix}Recording execution in audit trail.`);
          break;
        }
        case "complete": {
          lines.push("Response finalized and delivered to the chat UI.");
          break;
        }
      }
    }

    return lines.slice(-8);
  }, [arrivedEver, details, dynamicPhases]);

  const businessNarrativeCards = useMemo(() => {
    if (backendBusinessCards.length > 0) {
      return backendBusinessCards;
    }

    const cards: BackendBusinessCard[] = [];

    const normalizeConfidence = (value: unknown): number | undefined => {
      if (typeof value !== "number" || Number.isNaN(value)) return undefined;
      return value <= 1 ? value * 100 : value;
    };

    for (const phase of dynamicPhases) {
      if (!arrivedEver.has(phase.key)) continue;
      const detail = details?.[phase.detailKey] ?? {};
      const confidence = normalizeConfidence(detail?.confidence);
      const phaseName = phase.basePhase.toUpperCase();
      const agentLabel = phase.agentName ? phase.agentName.replace(/Agent$/, "") : "Pipeline";

      let statusBadge: "Processing" | "Approved" | "Escalated" | "Attention Required" = "Processing";
      if (phase.basePhase === "complete") statusBadge = "Approved";
      if (typeof confidence === "number" && confidence < 60) statusBadge = "Escalated";
      if (String(detail?.result || "").toLowerCase().includes("error") || String(detail?.status || "").toLowerCase().includes("error")) {
        statusBadge = "Attention Required";
      }

      const riskLevel: "Low" | "Medium" | "High" =
        statusBadge === "Attention Required"
          ? "High"
          : statusBadge === "Escalated"
          ? "High"
          : statusBadge === "Approved"
          ? "Low"
          : "Medium";

      const summary = phase.basePhase === "received"
        ? `Request received and pipeline started for execution.`
        : `${agentLabel} is executing ${phaseName} for this procurement request.`;

      let financialNote: string | undefined;
      if (typeof detail?.available_budget === "number") {
        financialNote = `Budget remaining: $${detail.available_budget.toLocaleString()}`;
      } else if (typeof detail?.budget_remaining === "number") {
        financialNote = `Budget remaining: $${detail.budget_remaining.toLocaleString()}`;
      }

      const nextAction =
        statusBadge === "Approved"
          ? "Proceed to the next workflow step and notify stakeholders."
          : statusBadge === "Escalated"
          ? "Route this item to approver review for final confirmation."
          : statusBadge === "Attention Required"
          ? "Investigate the issue and re-run the request after fix."
          : "Continue monitoring this request as the pipeline progresses.";

      cards.push({
        id: phase.key,
        summary,
        statusBadge,
        riskLevel,
        financialNote,
        nextAction,
      });
    }

    return cards.slice(-12);
  }, [backendBusinessCards, arrivedEver, details, dynamicPhases]);

  // Auto-navigate back to /chat ONLY when we witness the running → done transition.
  // This prevents redirect when revisiting /process after a previous run completed.
  const sawRunningRef = useRef(pipelineStatus === "running");
  useEffect(() => {
    if (pipelineStatus === "running") sawRunningRef.current = true;
  }, [pipelineStatus]);

  useEffect(() => {
    if (!isDone || !sawRunningRef.current) return;

    // Wait until reveal animation is complete before leaving /process.
    if (isRevealing) {
      console.log('[PROCESS->CHAT] Pipeline done, waiting for reveal animation to finish before auto-return');
      return;
    }

    sawRunningRef.current = false;
    console.log('[PROCESS->CHAT] Pipeline done and reveal complete, scheduling return to /chat in 15s');
    const timer = setTimeout(() => {
      console.log('[PROCESS->CHAT] Navigating back to /chat now');
      setLocation("/chat?intro=1");
      // Force scroll to bottom when returning to chat
      setTimeout(() => {
        const chatContainer = document.querySelector('[class*="overflow-y-auto"]');
        if (chatContainer) {
          console.log('[PROCESS->CHAT] Applying fallback DOM scroll-to-bottom after navigation');
          chatContainer.scrollTop = chatContainer.scrollHeight;
        } else {
          console.log('[PROCESS->CHAT] Fallback DOM chat container not found');
        }
      }, 100);
    }, 15000);
    return () => clearTimeout(timer);
  }, [isDone, isRevealing, setLocation]);

  return (
    <div ref={pageRootRef} className="flex flex-col h-full bg-background relative overflow-hidden">
      {/* Subtle animated grid background */}
      <div className="absolute inset-0 pointer-events-none opacity-[0.02]" style={{
        backgroundImage: "linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)",
        backgroundSize: "60px 60px",
      }} />

      {/* ===== Header ===== */}
      <header className="relative z-10 border-b bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 text-white px-6 py-4 flex items-center justify-between shadow-xl">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => setLocation("/chat?intro=1")} className="gap-2 text-white/80 hover:text-white hover:bg-white/10">
            <ArrowLeft className="h-4 w-4" /> Chat
          </Button>
          <div className="h-6 w-px bg-white/20" />
          <div>
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-indigo-400" />
              <h1 className="text-xl font-bold tracking-tight">Agent Execution Theater</h1>
            </div>
            <p className="text-[11px] text-white/40 mt-0.5">Real-time AI Agent Pipeline Visualization</p>
          </div>
          <Badge variant="outline" className="border-indigo-400/40 text-indigo-300 text-[10px] ml-2">ENTERPRISE</Badge>
        </div>

        <div className="flex items-center gap-3">
          {allHistory.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowHistory(h => !h)}
              className="gap-2 bg-indigo-500/20 border-indigo-500/60 text-indigo-200 hover:bg-indigo-500/30 hover:border-indigo-400 hover:text-white shadow-sm shadow-indigo-500/20"
            >
              <History className="h-4 w-4" />
              <span className="font-medium">Pipeline History</span>
              <Badge variant="secondary" className="ml-1 bg-indigo-300/30 text-indigo-100">{allHistory.length}</Badge>
              {showHistory ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </Button>
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowCommentary((prev) => !prev)}
            className={`gap-2 border-white/30 text-white hover:bg-white/10 ${showCommentary ? "bg-white/10" : "bg-transparent"}`}
          >
            <MessageSquare className="h-4 w-4" />
            {showCommentary ? "Hide Commentary" : "Show Commentary"}
          </Button>

          {!isExecutiveAlias && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowBusinessPanel((prev) => !prev)}
              className={`gap-2 border-indigo-300/40 text-indigo-100 hover:bg-indigo-400/10 ${showBusinessPanel ? "bg-indigo-500/20" : "bg-transparent"}`}
            >
              <MessageSquare className="h-4 w-4" />
              {showBusinessPanel ? "Hide Business Panel" : "Show Business Panel"}
            </Button>
          )}

          {isExecutiveAlias && (
            <Badge className="bg-indigo-500/25 border-indigo-300/30 text-indigo-100">Business Narrative View</Badge>
          )}

          {!isPresenting ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsPresenting(true)}
              className="gap-2 border-indigo-300/40 text-indigo-100 hover:bg-indigo-400/10"
            >
              <Maximize2 className="h-4 w-4" /> Present
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsPresenting(false)}
              className="gap-2 border-emerald-300/40 text-emerald-100 hover:bg-emerald-400/10"
            >
              <Minimize2 className="h-4 w-4" /> Exit
            </Button>
          )}

          {isLive && (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <Timer className="h-4 w-4 text-white/60" />
                <ElapsedTimer startMs={startTime} isRunning={isLive} />
              </div>
              <Badge className="bg-red-500/90 text-white animate-pulse gap-1.5 px-3">
                <span className="h-2 w-2 rounded-full bg-white inline-block animate-ping" />
                LIVE
              </Badge>
            </div>
          )}
          {!isLive && totalMs != null && (
            <div className="flex items-center gap-2 text-white/60">
              <Clock className="h-4 w-4" />
              <span className="font-mono text-sm">{formatMs(totalMs)} total</span>
            </div>
          )}
        </div>
      </header>

      {/* ===== Pipeline History Panel ===== */}
      {showHistory && allHistory.length > 0 && (
        <div className="relative z-10 border-b bg-slate-900/80 backdrop-blur-sm animate-in slide-in-from-top-2 duration-200">
          <div className="max-w-5xl mx-auto px-6 py-4 space-y-2">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs uppercase tracking-wider text-muted-foreground/60 font-medium">Pipeline Runs</span>
              <span className="text-[10px] text-muted-foreground/40">{allHistory.length} saved</span>
            </div>
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {allHistory.map(h => {
                const isActive = h.messageId === (entry?.messageId ?? urlId);
                const agentLabel = h.agents?.join(", ") || h.agent || "Agent";
                const querySnippet = h.query || (h.details?.received as any)?.message || "";
                const ts = h.timestamp ? new Date(h.timestamp).toLocaleString() : "";
                const sessionLabel = h.sessionTitle || h.sessionId || "Session";
                return (
                  <div
                    key={h.messageId}
                    className={`flex items-center gap-3 rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
                      isActive
                        ? "bg-indigo-500/15 border border-indigo-500/30"
                        : "bg-slate-700/40 border border-slate-600/30 hover:bg-slate-600/50 hover:border-slate-500/40"
                    }`}
                    onClick={() => handleSelectEntry(h)}
                  >
                    <Cpu className="h-4 w-4 text-indigo-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium truncate text-slate-100">{agentLabel}</span>
                        <span className="text-[10px] text-indigo-300/70 truncate max-w-[12rem]">{sessionLabel}</span>
                        {ts && <span className="text-[10px] text-slate-400 shrink-0">{ts}</span>}
                      </div>
                      {querySnippet && (
                        <p className="text-[11px] text-slate-300 truncate mt-0.5">{querySnippet}</p>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 p-0 text-red-400/60 hover:text-red-400 hover:bg-red-500/10 shrink-0"
                      onClick={(e) => { e.stopPropagation(); handleDeleteEntry(h.messageId); }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ===== Main Content ===== */}
      <div className="relative z-10 flex-1 overflow-y-auto">
        <div className={`mx-auto px-6 py-6 ${showBusinessPanel ? "max-w-[1500px]" : "max-w-6xl"}`}>
          <div className={`grid gap-6 ${showBusinessPanel ? "xl:grid-cols-[minmax(0,2.2fr)_minmax(360px,1fr)]" : "grid-cols-1"}`}>
            <div className="space-y-6">

          {/* --- Query Banner --- */}
          {hasData && (
            <div className="rounded-2xl border border-indigo-500/20 bg-gradient-to-br from-indigo-500/5 via-background to-purple-500/5 p-4 space-y-3">
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 shrink-0">
                  <MessageSquare className="h-4 w-4 text-indigo-400" />
                  <span className="text-[10px] uppercase tracking-[0.15em] text-indigo-400/70 font-medium">Query</span>
                </div>
                <p className="text-sm font-medium leading-snug flex-1 min-w-0 truncate">{queryText || "—"}</p>
                <div className="h-5 w-px bg-indigo-500/20 shrink-0" />
                <div className="flex items-center gap-1.5 flex-wrap shrink-0">
                  {allAgentNames.length > 0 ? allAgentNames.map(name => (
                    <Badge key={name} className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30 text-[10px] px-2 py-0.5">{name.replace(/Agent$/, '')}</Badge>
                  )) : (
                    <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30 text-[10px] px-2 py-0.5">—</Badge>
                  )}
                </div>
              </div>

              {/* Progress bar */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <BarChart3 className="h-3 w-3" />
                    {staggerComplete ? "All steps complete" : isDone ? `All agents complete (${arrivedCount} steps)` : isLive ? `Processing… ${arrivedCount}/${phaseCount} phases` : `${arrivedCount}/${phaseCount} phases`}
                  </span>
                  <span className="font-mono">{progressPct}%</span>
                </div>
                <div className="h-2 bg-muted/30 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-1000 ease-out ${
                      staggerComplete
                        ? "bg-gradient-to-r from-emerald-500 to-emerald-400"
                        : "bg-gradient-to-r from-indigo-500 via-blue-500 to-indigo-400"
                    }`}
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* --- Empty state --- */}
          {!hasData && (
            <div className="flex flex-col items-center justify-center py-32 text-center space-y-6">
              <div className="relative">
                <Activity className="h-20 w-20 text-muted-foreground/20" />
                <div className="absolute inset-0 animate-ping opacity-10"><Activity className="h-20 w-20 text-indigo-400" /></div>
              </div>
              <div className="space-y-2">
                <h2 className="text-xl font-bold text-muted-foreground/60">No Execution Data</h2>
                <p className="text-sm text-muted-foreground/40 max-w-md">
                  Send a query in the Chat to see the full AI agent execution pipeline visualized here in real-time.
                </p>
              </div>
              <Button variant="outline" onClick={() => setLocation("/chat?intro=1")} className="gap-2 mt-4">
                <MessageSquare className="h-4 w-4" /> Go to Chat
              </Button>
            </div>
          )}

          {/* ====== Phase Timeline ====== */}
          {hasData && (
            <div className="space-y-0">
              {dynamicPhases.map((phase, index) => {
                // PURE STREAMING: Only show phases that have data from backend
                if (isLive || isDone) {
                  // Debug first phase only to avoid spam
                  const shouldLog = index === 0 || index === revealedIndex || index === revealedIndex + 1;
                  
                  // Gradual reveal: use explicit visible set to avoid index/key drift.
                  if (isRevealing && !visiblePhaseKeys.has(phase.key)) {
                    if (shouldLog) console.log(`[RENDER FILTER] ❌ Hiding phase ${index} (${phase.key}) - revealedIndex: ${revealedIndex}`);
                    return null; // Not revealed yet - waiting for timer
                  }
                  // Check if this phase has arrived from backend
                  if (!arrivedEver.has(phase.key)) {
                    if (shouldLog) console.log(`[RENDER FILTER] ⏸️  Phase ${index} not arrived yet`);
                    return null; // Hide - no data yet
                  }
                  if (shouldLog) console.log(`[RENDER] ✅ Showing phase ${index} (${phase.key})`);
                }

                // Phase status: active if latest, complete if past
                let phaseStatus: "pending" | "active" | "complete";
                if (isLive || isDone) {
                  if (index === highestArrivedIdx) {
                    phaseStatus = "active"; // Latest phase with data
                  } else {
                    phaseStatus = "complete"; // Already processed
                  }
                } else {
                  // Replay mode: animated reveal
                  const step = stepMap[phase.basePhase];
                  if (index > revealedIndex) {
                    phaseStatus = "pending";
                  } else if (step?.status === "complete") {
                    phaseStatus = "complete";
                  } else if (step?.status === "active") {
                    phaseStatus = "active";
                  } else {
                    phaseStatus = index < revealedIndex ? "complete" : "active";
                  }
                }

                // Agent separator: show a header when agent changes in multi-agent mode
                const prevAgent = index > 0 ? dynamicPhases[index - 1]?.agentName : undefined;
                const showAgentSeparator = phase.agentName && phase.agentName !== prevAgent;

                return (
                  <div key={phase.key} id={`phase-row-${phase.key}`} data-phase-key={phase.key}>
                    {showAgentSeparator && (
                      <div className="flex items-center gap-3 py-3 mb-1">
                        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-indigo-500/30 to-transparent" />
                        <div className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-indigo-500/10 border border-indigo-500/20">
                          <ShieldCheck className="h-3.5 w-3.5 text-indigo-400" />
                          <span className="text-xs font-bold tracking-wide text-indigo-300">
                            {phase.agentName!.replace(/Agent$/, '')}
                          </span>
                          {(() => {
                            const exec = pipelineAgentExecutions.find(e => e.name === phase.agentName);
                            if (!exec) return null;
                            return (
                              <Badge className={
                                exec.status === "complete"
                                  ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-[9px]"
                                  : exec.status === "error"
                                  ? "bg-red-500/20 text-red-400 border-red-500/30 text-[9px]"
                                  : "bg-blue-500/20 text-blue-400 border-blue-500/30 text-[9px] animate-pulse"
                              }>
                                {exec.status.toUpperCase()}
                              </Badge>
                            );
                          })()}
                        </div>
                        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-indigo-500/30 to-transparent" />
                      </div>
                    )}
                    <PhaseNode
                      key={phase.key}
                      phaseKey={phase.basePhase}
                      meta={PHASE_META[phase.basePhase]}
                      status={phaseStatus}
                      detail={details[phase.detailKey]}
                      index={index}
                      isLast={index === dynamicPhases.length - 1}
                      durationMs={stepMap[phase.basePhase]?.durationMs}
                      agentName={phase.agentName}
                      phaseCount={dynamicPhases.length}
                    />
                  </div>
                );
              })}
            </div>
          )}

          {/* ====== Execution Complete Banner ====== */}
          {isDone && staggerComplete && (
            <AutoReturnBanner
              totalMs={totalMs}
              agentExecutions={pipelineAgentExecutions}
              onBack={() => setLocation("/chat?intro=1")}
            />
          )}

          {/* ====== Tool Calls ====== */}
          {pipelineToolCalls.length > 0 && (
            <div className="rounded-xl border border-amber-500/20 overflow-hidden">
              <div className="px-5 py-3 bg-amber-500/5 border-b border-amber-500/20 flex items-center gap-2">
                <Settings className="h-4 w-4 text-amber-400" />
                <span className="text-sm font-semibold">Tool Calls</span>
                <Badge variant="outline" className="text-[10px] ml-auto">{pipelineToolCalls.length}</Badge>
              </div>
              <div className="p-3 space-y-1.5">
                {pipelineToolCalls.map((tc) => (
                  <div key={tc.id} className="flex items-center justify-between text-xs rounded-lg border border-border/30 bg-background/50 p-2.5">
                    <div className="flex items-center gap-2">
                      <Badge className={`text-[9px] px-2 ${tc.source === "Odoo" ? "bg-amber-500/20 text-amber-300 border-amber-500/30" : "bg-teal-500/20 text-teal-300 border-teal-500/30"}`}>
                        {tc.source}
                      </Badge>
                      <span className="font-mono">{tc.name}</span>
                    </div>
                    {tc.status === "complete" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <Loader2 className="h-4 w-4 animate-spin text-blue-400" />}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ====== Agent Outputs (Who Checked What) ====== */}
          {agentOutputSummaries.length > 0 && (
            <div className="rounded-xl border border-indigo-500/20 overflow-hidden">
              <div className="px-5 py-3 bg-indigo-500/5 border-b border-indigo-500/20 flex items-center gap-2">
                <Brain className="h-4 w-4 text-indigo-400" />
                <span className="text-sm font-semibold">Agent Outputs</span>
                <span className="text-[11px] text-muted-foreground">Who validated price/risk/approval during PR flow</span>
                <Badge variant="outline" className="text-[10px] ml-auto">{agentOutputSummaries.length}</Badge>
              </div>
              <div className="p-4 space-y-3">
                {agentOutputSummaries.map((summary) => (
                  <div key={summary.agentName} className="rounded-xl border p-4 space-y-3 bg-background/50">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <ShieldCheck className="h-4 w-4 text-indigo-400 shrink-0" />
                        <span className="text-sm font-bold truncate">{summary.agentName}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {summary.confidencePct != null && (
                          <Badge variant="outline" className="text-[10px] font-mono">
                            {summary.confidencePct}% confidence
                          </Badge>
                        )}
                        {summary.executionMs != null && (
                          <Badge variant="outline" className="text-[10px] font-mono gap-1">
                            <Clock className="h-2.5 w-2.5" /> {formatMs(summary.executionMs)}
                          </Badge>
                        )}
                        {summary.status && (
                          <Badge className={
                            summary.status === "complete"
                              ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                              : summary.status === "error"
                              ? "bg-red-500/20 text-red-400 border-red-500/30"
                              : "bg-blue-500/20 text-blue-400 border-blue-500/30"
                          }>
                            {summary.status.toUpperCase()}
                          </Badge>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 text-xs">
                      {summary.decisionAction && (
                        <div className="rounded-lg border border-border/40 p-3 space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Decision</div>
                          <Badge className="bg-indigo-500/20 text-indigo-300 border-indigo-500/30">{summary.decisionAction}</Badge>
                          {summary.model && (
                            <div className="text-muted-foreground">Model: <span className="font-mono">{summary.model}</span></div>
                          )}
                        </div>
                      )}

                      {summary.tools && summary.tools.length > 0 && (
                        <div className="rounded-lg border border-border/40 p-3 space-y-1">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Tools Used</div>
                          <div className="flex flex-wrap gap-1.5">
                            {summary.tools.map((tool, i) => (
                              <Badge key={`${summary.agentName}_${tool}_${i}`} variant="outline" className="text-[10px] font-mono">{tool}</Badge>
                            ))}
                          </div>
                        </div>
                      )}

                      {summary.reasoning && (
                        <div className="rounded-lg border border-border/40 p-3 space-y-1 lg:col-span-2">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Reasoning</div>
                          <p className="text-muted-foreground leading-relaxed">{summary.reasoning}</p>
                        </div>
                      )}

                      {summary.alternatives && summary.alternatives.length > 0 && (
                        <div className="rounded-lg border border-border/40 p-3 space-y-1 lg:col-span-2">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Alternatives Considered</div>
                          <div className="flex flex-wrap gap-1.5">
                            {summary.alternatives.map((alt, i) => (
                              <Badge key={`${summary.agentName}_alt_${i}`} variant="outline" className="text-[10px]">{alt}</Badge>
                            ))}
                          </div>
                        </div>
                      )}

                      {(summary.actionResult || summary.lastMessage || summary.learned) && (
                        <div className="rounded-lg border border-border/40 p-3 space-y-1 lg:col-span-2">
                          <div className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Outcome</div>
                          {summary.actionResult && <p className="text-muted-foreground">Action: {summary.actionResult}</p>}
                          {summary.lastMessage && <p className="text-muted-foreground">Message: {summary.lastMessage}</p>}
                          {summary.learned && <p className="text-emerald-400">Recorded in learning/audit trail</p>}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ====== Execution Log ====== */}
          {pipelineLogs.length > 0 && (
            <div className="rounded-xl border border-slate-500/20 overflow-hidden">
              <div className="px-5 py-3 bg-slate-500/5 border-b border-slate-500/20 flex items-center gap-2">
                <Activity className="h-4 w-4 text-slate-400" />
                <span className="text-sm font-semibold">Execution Log</span>
                <Badge variant="outline" className="text-[10px] ml-auto">{pipelineLogs.length} entries</Badge>
              </div>
              <div className="max-h-56 overflow-y-auto">
                {pipelineLogs.map((log) => (
                  <div key={log.id} className="flex items-center gap-3 px-5 py-2 text-[11px] border-b border-border/20 font-mono hover:bg-accent/20 transition-colors">
                    <span className="text-muted-foreground w-16 shrink-0 text-right tabular-nums">{log.ms}ms</span>
                    <Badge variant="outline" className="text-[9px] w-24 justify-center shrink-0">{log.category}</Badge>
                    <span className="text-muted-foreground truncate">{log.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ====== Agent Workstreams ====== */}
          {pipelineAgentExecutions.length > 0 && (
            <div className="rounded-xl border border-purple-500/20 overflow-hidden">
              <div className="px-5 py-3 bg-purple-500/5 border-b border-purple-500/20 flex items-center gap-2">
                <Brain className="h-4 w-4 text-purple-400" />
                <span className="text-sm font-semibold">Agent Workstreams</span>
                <Badge variant="outline" className="text-[10px] ml-auto">{pipelineAgentExecutions.length}</Badge>
              </div>
              <div className="p-4 space-y-3">
                {pipelineAgentExecutions.map((exec) => (
                  <div key={exec.name} className="rounded-xl border p-4 space-y-3 bg-background/50">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <ShieldCheck className="h-4 w-4 text-purple-400" />
                        <span className="text-sm font-bold">{exec.name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {exec.confidence != null && (
                          <Badge variant="outline" className="text-[10px] font-mono">
                            {Math.round((exec.confidence > 1 ? exec.confidence : exec.confidence * 100))}%
                          </Badge>
                        )}
                        {exec.durationMs != null && (
                          <Badge variant="outline" className="text-[10px] gap-1 font-mono">
                            <Clock className="h-2.5 w-2.5" /> {formatMs(exec.durationMs)}
                          </Badge>
                        )}
                        <Badge className={
                          exec.status === "complete" ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" :
                          exec.status === "error" ? "bg-red-500/20 text-red-400 border-red-500/30" :
                          "bg-blue-500/20 text-blue-400 border-blue-500/30 animate-pulse"
                        }>{exec.status.toUpperCase()}</Badge>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      {(["OBSERVE", "DECIDE", "ACT", "LEARN"] as const).map((p) => {
                        const s = exec.phases[p];
                        return (
                          <div key={p} className={`flex items-center gap-1.5 text-[10px] px-3 py-1 rounded-full font-medium ${
                            s === "complete" ? "bg-emerald-500/15 text-emerald-400" :
                            s === "active"   ? "bg-blue-500/15 text-blue-400 animate-pulse" :
                            s === "error"    ? "bg-red-500/15 text-red-400" :
                            "bg-muted text-muted-foreground/40"
                          }`}>
                            {s === "complete" ? <CheckCircle2 className="h-3 w-3" /> :
                             s === "active"   ? <Loader2 className="h-3 w-3 animate-spin" /> :
                             <div className="h-3 w-3 rounded-full border border-current opacity-40" />}
                            {p}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
            </div>

            {showBusinessPanel && (
              <aside className="space-y-4 xl:sticky xl:top-6 h-fit">
                <div className="rounded-xl border border-slate-300/60 bg-white/90 px-4 py-3">
                  <h3 className="text-sm font-semibold text-slate-900">What Is Happening Right Now</h3>
                  <p className="text-xs text-slate-500 mt-1">Business narrative in plain language for procurement managers.</p>
                  <div className="mt-2">
                    <Badge variant="outline" className="text-[10px] border-slate-300 text-slate-600">
                      Source: {businessSource === "backend-live" ? "Backend Live" : "Local Fallback"}
                    </Badge>
                  </div>
                </div>

                {businessNarrativeCards.length === 0 ? (
                  <div className="rounded-xl border border-slate-300/60 bg-white/90 p-6 text-center text-sm text-slate-500">
                    Waiting for next procurement request.
                  </div>
                ) : (
                  <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
                    {businessNarrativeCards.map((card) => (
                      <div key={card.id} className="rounded-xl border border-slate-300/70 bg-white/95 p-4 shadow-sm animate-in slide-in-from-bottom-2 duration-300">
                        <p className="text-sm text-slate-800 leading-relaxed">{card.summary}</p>
                        <div className="flex items-center flex-wrap gap-2 mt-3">
                          <Badge className={
                            card.statusBadge === "Approved"
                              ? "bg-emerald-600"
                              : card.statusBadge === "Escalated"
                              ? "bg-amber-600"
                              : card.statusBadge === "Attention Required"
                              ? "bg-red-600"
                              : "bg-blue-600"
                          }>
                            {card.statusBadge}
                          </Badge>
                          <Badge variant="outline" className="border-slate-300 text-slate-700">{card.riskLevel}</Badge>
                        </div>
                        {card.financialNote && (
                          <div className="mt-3 text-xs rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-slate-700">
                            {card.financialNote}
                          </div>
                        )}
                        <p className="text-xs text-slate-600 mt-3"><span className="font-semibold text-slate-800">Next:</span> {card.nextAction}</p>
                      </div>
                    ))}
                  </div>
                )}

                <div className="rounded-xl border border-slate-300/60 bg-white/90 p-3 flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => setLocation("/chat?intro=1")} className="flex-1 gap-2">
                    <MessageSquare className="h-3.5 w-3.5" /> Go to Chat
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setShowBusinessPanel(false)} className="flex-1 gap-2">
                    <ChevronRight className="h-3.5 w-3.5" /> Hide Panel
                  </Button>
                </div>
              </aside>
            )}
          </div>
        </div>
      </div>

      {/* Optional floating commentary panel: bottom on mobile, right side on desktop */}
      {showCommentary && hasData && !showBusinessPanel && (
        <div className="fixed bottom-4 left-4 right-4 lg:left-auto lg:right-4 lg:w-[380px] z-30">
          <Card className="border-indigo-500/30 bg-slate-950/90 backdrop-blur shadow-xl">
            <CardContent className="p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 text-indigo-300" />
                  <span className="text-xs font-semibold tracking-wide text-indigo-200">Live Commentary</span>
                </div>
                <Badge variant="outline" className="text-[10px] border-indigo-400/30 text-indigo-200">
                  {isLive ? "LIVE" : "REPLAY"}
                </Badge>
              </div>

              <div className="max-h-52 overflow-y-auto space-y-1.5 pr-1">
                {commentaryLines.length > 0 ? (
                  commentaryLines.map((line, idx) => (
                    <div
                      key={`commentary_${idx}`}
                      className="text-[11px] leading-relaxed text-slate-200 border border-white/10 rounded-md px-2 py-1.5 bg-white/[0.03]"
                    >
                      {line}
                    </div>
                  ))
                ) : (
                  <p className="text-[11px] text-slate-400">Commentary will appear as pipeline phases arrive.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
