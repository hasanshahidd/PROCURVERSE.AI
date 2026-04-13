/**
 * Sprint B (2026-04-11) — PhaseTimelineCard
 *
 * Vertical timeline with observe/decide/act/learn icons, the signature
 * visualization of the legacy `/process` page. Extracted from
 * `AgentProcessPage.tsx` (now deleted) so it can be reused by Session
 * Page in Sprint D without the pipelineStore dependency.
 *
 * Rendering contract:
 *   - Consumes a `phases: TimelinePhase[]` prop built by `buildTimeline`
 *     (which itself is in `phase-helpers.ts` and takes a plain
 *     `agentPhaseDetails`-shaped keymap + an agent-name list).
 *   - Expand/collapse is *controlled* via `expanded` + `onToggle`. The
 *     caller owns the Set so persistence (localStorage, session store,
 *     URL param) is caller-decided.
 *   - `isLive` drives the spinner + auto-scroll target on the last row.
 *   - `getPhaseStatus` is derivable from phase data + mode, but the
 *     caller can override via `statusFor` to inject external state
 *     (e.g. a gate-blocked indicator sourced from a session event).
 *
 * Zero pipelineStore imports.
 */

import { useRef, useEffect, ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Database,
  Loader2,
  ShieldCheck,
  Settings,
  Sparkles,
} from "lucide-react";
import {
  TimelinePhase,
  PHASE_META,
  agentShort,
  extractAction,
  fmtMs,
  normConf,
} from "./phase-helpers";

/* ================================================================ */
/*  Phase detail renderer (inlined; copied from AgentProcessPage)    */
/* ================================================================ */

function renderPhaseDetail(phase: TimelinePhase): ReactNode {
  const { basePhase, data } = phase;
  const d = data as Record<string, unknown>;

  switch (basePhase) {
    case "received":
      return (
        <div className="space-y-2">
          <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3">
            <p className="text-xs text-slate-600 dark:text-slate-400">
              {(d.message as string) || "Request received by backend"}
            </p>
          </div>
          {d.timestamp != null && (
            <span className="text-[10px] text-slate-400">
              at {new Date(d.timestamp as string | number).toLocaleTimeString()}
            </span>
          )}
        </div>
      );

    case "classifying":
      return (
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Detected intent:</span>
          <Badge className="bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300">
            {(d.intent as string) || "Unknown"}
          </Badge>
        </div>
      );

    case "routing":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <span className="text-[10px] text-slate-400 block mb-1">Selected Agent</span>
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-indigo-500" />
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {d.agent ? agentShort(d.agent as string) : "—"}
              </span>
            </div>
          </div>
          {d.confidence != null && (
            <div>
              <span className="text-[10px] text-slate-400 block mb-1">Confidence</span>
              <div className="flex items-center gap-2">
                <Progress value={normConf(d.confidence)} className="h-2 flex-1" />
                <span className="text-xs font-mono text-slate-500">
                  {normConf(d.confidence).toFixed(0)}%
                </span>
              </div>
            </div>
          )}
          {d.reason && (
            <div className="sm:col-span-2">
              <span className="text-[10px] text-slate-400 block mb-1">Reasoning</span>
              <p className="text-xs text-slate-600 dark:text-slate-400">{d.reason as string}</p>
            </div>
          )}
        </div>
      );

    case "observing":
      return (
        <div className="space-y-2">
          {Array.isArray(d.sources) && (d.sources as unknown[]).length > 0 && (
            <div>
              <span className="text-[10px] text-slate-400 block mb-1">Data Sources</span>
              <div className="flex flex-wrap gap-1.5">
                {(d.sources as string[]).map((s, i) => (
                  <Badge key={i} variant="secondary" className="text-[10px]">
                    <Database className="w-3 h-3 mr-1" /> {s}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {d.recordsFound != null && (
            <span className="text-xs text-slate-500">
              {d.recordsFound as number} records found
            </span>
          )}
        </div>
      );

    case "deciding": {
      const actionStr = extractAction(d.action);
      const confPct = normConf(d.confidence);
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          {d.model && (
            <div>
              <span className="text-[10px] text-slate-400 block mb-1">AI Model</span>
              <Badge variant="secondary" className="text-[10px]">{d.model as string}</Badge>
            </div>
          )}
          {actionStr && (
            <div>
              <span className="text-[10px] text-slate-400 block mb-1">Decision</span>
              <Badge
                className={`text-[10px] ${
                  /approve|pass|success|create/i.test(actionStr)
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                    : /reject|block|fail/i.test(actionStr)
                      ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
                      : "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300"
                }`}
              >
                {actionStr}
              </Badge>
            </div>
          )}
          {d.confidence != null && (
            <div>
              <span className="text-[10px] text-slate-400 block mb-1">Confidence</span>
              <div className="flex items-center gap-2">
                <Progress value={confPct} className="h-2 flex-1" />
                <span className="text-xs font-mono">{confPct.toFixed(0)}%</span>
              </div>
            </div>
          )}
          {d.reasoning && (
            <div className="sm:col-span-2">
              <span className="text-[10px] text-slate-400 block mb-1">Reasoning</span>
              <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                {d.reasoning as string}
              </p>
            </div>
          )}
          {Array.isArray(d.alternatives) && (d.alternatives as unknown[]).length > 0 && (
            <div className="sm:col-span-2">
              <span className="text-[10px] text-slate-400 block mb-1">Alternatives Considered</span>
              <div className="flex flex-wrap gap-1.5">
                {(d.alternatives as string[]).map((alt, i) => (
                  <Badge key={i} variant="outline" className="text-[10px]">{alt}</Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      );
    }

    case "acting":
      return (
        <div className="space-y-2">
          {Array.isArray(d.tools) && (d.tools as unknown[]).length > 0 && (
            <div>
              <span className="text-[10px] text-slate-400 block mb-1">Tools Invoked</span>
              <div className="flex flex-wrap gap-1.5">
                {(d.tools as string[]).map((t, i) => (
                  <Badge
                    key={i}
                    className={`text-[10px] ${
                      /erp|odoo/i.test(t)
                        ? "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300"
                        : "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
                    }`}
                  >
                    <Settings className="w-3 h-3 mr-1" /> {t}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {d.timing != null && (
            <span className="text-xs text-slate-500">
              Execution: {fmtMs(d.timing as number)}
            </span>
          )}
        </div>
      );

    case "learning":
      return (
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-emerald-500" />
          <span className="text-xs text-slate-600 dark:text-slate-400">
            {d.recorded
              ? "Decision recorded to audit trail"
              : "Recording audit trail…"}
            {d.table != null && (
              <span className="text-slate-400"> → {d.table as string}</span>
            )}
          </span>
          {d.recorded ? <CheckCircle2 className="w-4 h-4 text-emerald-500" /> : null}
        </div>
      );

    case "complete":
      return (
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-green-500" />
          <span className="text-xs text-slate-600 dark:text-slate-400">
            Execution complete. Results delivered to the frontend.
          </span>
        </div>
      );

    default:
      return (
        <pre className="text-[10px] text-slate-400 overflow-x-auto whitespace-pre-wrap">
          {JSON.stringify(data, null, 2)}
        </pre>
      );
  }
}

/* ================================================================ */
/*  PhaseTimelineCard component                                      */
/* ================================================================ */

export type PhaseStatus = "active" | "complete" | "blocked";

export interface PhaseTimelineCardProps {
  phases: TimelinePhase[];
  expanded: Set<string>;
  onToggle: (key: string) => void;
  /** When true, the last row shows the spinner + scrollIntoView effect. */
  isLive?: boolean;
  /** Indicates whether the run reached a `done` state (for status fall-through). */
  isDone?: boolean;
  /** When set, the last row paints "blocked" styling (amber). */
  blockedLast?: boolean;
  /**
   * Optional override for per-row status. When omitted, a default rule
   * is applied (active for last live row, complete otherwise).
   */
  statusFor?: (phase: TimelinePhase, index: number) => PhaseStatus;
}

export function PhaseTimelineCard({
  phases,
  expanded,
  onToggle,
  isLive = false,
  isDone = false,
  blockedLast = false,
  statusFor,
}: PhaseTimelineCardProps) {
  const lastPhaseRef = useRef<HTMLDivElement>(null);
  const prevTimelineLen = useRef(0);

  // Auto-scroll to latest phase during live streaming.
  useEffect(() => {
    if (!isLive) return;
    if (phases.length > prevTimelineLen.current) {
      prevTimelineLen.current = phases.length;
      requestAnimationFrame(() => {
        lastPhaseRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }
  }, [phases.length, isLive]);

  if (phases.length === 0) return null;

  const computeStatus = (phase: TimelinePhase, idx: number): PhaseStatus => {
    if (statusFor) return statusFor(phase, idx);
    const d = phase.data as Record<string, unknown>;
    if (d?.status === "blocked" || d?.status === "awaiting_input" || d?.status === "rejected") {
      return "blocked";
    }
    if (isDone && blockedLast && idx === phases.length - 1) return "blocked";
    if (isDone) return "complete";
    if (d?.status === "complete" || d?.recorded) return "complete";
    if (idx === phases.length - 1 && isLive) return "active";
    return "complete";
  };

  return (
    <div className="space-y-0 relative">
      {phases.map((phase, idx) => {
        const status = computeStatus(phase, idx);
        const meta = PHASE_META[phase.basePhase] || PHASE_META.received;
        const Icon = meta.Icon;
        const isExpanded = expanded.has(phase.key);
        const isLast = idx === phases.length - 1;
        const prevAgent = idx > 0 ? phases[idx - 1].agentName : undefined;
        const showSep = Boolean(phase.agentName && phase.agentName !== prevAgent);

        return (
          <div
            key={phase.key}
            ref={isLast ? lastPhaseRef : undefined}
            className="animate-in fade-in slide-in-from-left-2 duration-300"
            style={{ animationDelay: `${idx * 50}ms` }}
          >
            {/* Agent separator header */}
            {showSep && (
              <div className="flex items-center gap-3 py-3 mb-1">
                <div className="flex-1 h-px bg-gradient-to-r from-transparent to-indigo-300/40 dark:to-indigo-700/40" />
                <Badge className="bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 text-[11px] px-3 py-1 shadow-sm">
                  <Brain className="w-3 h-3 mr-1.5" />
                  {agentShort(phase.agentName!)}
                </Badge>
                <div className="flex-1 h-px bg-gradient-to-l from-transparent to-indigo-300/40 dark:to-indigo-700/40" />
              </div>
            )}

            <div className="flex gap-3">
              {/* Timeline rail */}
              <div className="flex flex-col items-center w-10 shrink-0">
                <div
                  className={`
                    w-8 h-8 rounded-full flex items-center justify-center relative
                    transition-all duration-500
                    ${status === "complete"
                      ? "bg-emerald-500 text-white shadow-lg shadow-emerald-500/20"
                      : status === "blocked"
                        ? "bg-amber-500 text-white shadow-lg shadow-amber-500/20"
                        : "bg-indigo-500 text-white shadow-lg shadow-indigo-500/30"
                    }
                  `}
                >
                  {status === "active" ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Icon className="w-4 h-4" />
                  )}
                  {status === "active" && (
                    <span className="absolute inset-0 rounded-full animate-ping bg-indigo-400/30" />
                  )}
                  {status === "blocked" && (
                    <span className="absolute inset-0 rounded-full animate-pulse bg-amber-400/30" />
                  )}
                </div>
                {!isLast && (
                  <div
                    className={`w-0.5 flex-1 min-h-[16px] transition-colors duration-500 ${
                      status === "complete"
                        ? "bg-emerald-300 dark:bg-emerald-700"
                        : status === "blocked"
                          ? "bg-amber-300 dark:bg-amber-700"
                          : "bg-slate-200 dark:bg-slate-700"
                    }`}
                  />
                )}
              </div>

              {/* Phase content */}
              <div className="flex-1 pb-4 min-w-0">
                <button
                  className="w-full text-left group"
                  onClick={() => onToggle(phase.key)}
                >
                  <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                    {phase.agentName && (
                      <span className="text-[10px] text-indigo-500 dark:text-indigo-400 font-medium">
                        {agentShort(phase.agentName)} ›
                      </span>
                    )}
                    <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                      {meta.label}
                    </span>
                    {status === "active" && (
                      <Badge className="bg-indigo-100 dark:bg-indigo-900/50 text-indigo-600 dark:text-indigo-300 text-[9px] animate-pulse">
                        PROCESSING
                      </Badge>
                    )}
                    <span className="text-[10px] text-slate-400 ml-auto flex items-center gap-1">
                      {idx + 1}/{phases.length}
                      {isExpanded ? (
                        <ChevronUp className="w-3.5 h-3.5 group-hover:text-slate-600" />
                      ) : (
                        <ChevronDown className="w-3.5 h-3.5 group-hover:text-slate-600" />
                      )}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    {meta.desc}
                  </p>
                </button>

                {/* Expanded detail card */}
                {isExpanded && (
                  <Card className="mt-2 border-slate-200/60 dark:border-slate-700/60 shadow-sm animate-in fade-in slide-in-from-top-1 duration-200">
                    <CardContent className="p-4">
                      {renderPhaseDetail(phase)}
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Convenience re-export so session consumers can import both in one line. */
export type { TimelinePhase } from "./phase-helpers";
