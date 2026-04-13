/**
 * Sprint B (2026-04-11) — AgentExecutionCard
 *
 * Per-agent "workstream" card showing:
 *   - Agent short name + status badge
 *   - Confidence + duration
 *   - OBSERVE / DECIDE / ACT / LEARN phase pills
 *   - Decision action + reasoning (one-liner)
 *   - Tools invoked (truncated)
 *
 * Extracted from the "Agent Workstreams" block in the now-deleted
 * `AgentProcessPage.tsx` (`Brain` workstreams aside at lines ~1860-1968).
 *
 * Zero pipelineStore imports — takes a single `AgentSummary` prop. The
 * legacy AgentProcessPage mapped `agentExecutions` → `agentSummaries`
 * inline; callers now do that mapping themselves (in Sprint D the
 * session reducer will produce this shape from `agent_activity` events
 * directly, so the legacy mapping disappears naturally).
 */

import { Badge } from "@/components/ui/badge";
import { ShieldCheck } from "lucide-react";
import {
  AgentSummary,
  agentShort,
  fmtMs,
  normConf,
} from "./phase-helpers";

interface AgentExecutionCardProps {
  agent: AgentSummary;
}

export function AgentExecutionCard({ agent }: AgentExecutionCardProps) {
  return (
    <div className="rounded-lg border border-slate-200/60 dark:border-slate-700/60 p-3">
      {/* Agent header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <ShieldCheck className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 truncate">
            {agentShort(agent.name)}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {agent.confidence != null && (
            <span className="text-[10px] text-slate-400 tabular-nums">
              {normConf(agent.confidence).toFixed(0)}%
            </span>
          )}
          {agent.durationMs != null && (
            <span className="text-[10px] text-slate-400 tabular-nums">
              {fmtMs(agent.durationMs)}
            </span>
          )}
          <Badge
            className={`text-[8px] ${
              agent.status === "complete"
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                : agent.status === "error"
                  ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
                  : "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
            }`}
          >
            {agent.status}
          </Badge>
        </div>
      </div>

      {/* OBSERVE / DECIDE / ACT / LEARN phase pills */}
      <div className="flex gap-1">
        {(["OBSERVE", "DECIDE", "ACT", "LEARN"] as const).map((p) => {
          const ps = agent.phases?.[p];
          return (
            <div
              key={p}
              className={`flex-1 text-center py-0.5 rounded text-[8px] font-medium transition-colors ${
                ps === "complete"
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                  : ps === "active"
                    ? "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 animate-pulse"
                    : ps === "error"
                      ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
                      : "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500"
              }`}
            >
              {p}
            </div>
          );
        })}
      </div>

      {/* Decision action + reasoning */}
      {agent.action && (
        <div className="mt-2 text-[10px] text-slate-500 dark:text-slate-400 space-y-0.5">
          <div>
            <span className="font-medium">Decision:</span> {agent.action}
          </div>
          {agent.reasoning && (
            <p className="text-slate-400 dark:text-slate-500 line-clamp-2">
              {agent.reasoning}
            </p>
          )}
        </div>
      )}

      {/* Tools used */}
      {Array.isArray(agent.tools) && agent.tools.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {agent.tools.slice(0, 4).map((t: string, i: number) => (
            <Badge key={i} variant="outline" className="text-[8px]">
              {t}
            </Badge>
          ))}
          {agent.tools.length > 4 && (
            <Badge variant="outline" className="text-[8px]">
              +{agent.tools.length - 4}
            </Badge>
          )}
        </div>
      )}
    </div>
  );
}
