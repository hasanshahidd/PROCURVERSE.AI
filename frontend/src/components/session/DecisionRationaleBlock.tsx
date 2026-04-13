/**
 * Sprint B (2026-04-11) — DecisionRationaleBlock
 *
 * Renders the "why did the agent decide this?" detail card:
 *   - AI model used
 *   - Action verdict (approve / reject / create / ...)
 *   - Confidence bar
 *   - Reasoning paragraph
 *   - Alternatives considered
 *
 * Extracted from the `deciding` case of `renderPhaseDetail` in the now-
 * deleted `AgentProcessPage.tsx`. Zero pipelineStore imports — feeds
 * purely from props, so Sprint D can drive it from a session-event
 * projection (`phase_completed.decision_rationale` or the richer
 * `agent_activity.decide` event payload) without any refactor.
 */

import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import {
  DecisionRationaleData,
  extractAction,
  normConf,
} from "./phase-helpers";

interface DecisionRationaleBlockProps {
  data: DecisionRationaleData;
  /** When true, the block will render a bordered card wrapper.
   *  Defaults to false so the caller can compose it inside a parent card. */
  bordered?: boolean;
}

export function DecisionRationaleBlock({ data, bordered = false }: DecisionRationaleBlockProps) {
  const actionStr = extractAction(data.action);
  const confPct = normConf(data.confidence);
  const hasAnything =
    Boolean(data.model) ||
    Boolean(actionStr) ||
    data.confidence != null ||
    Boolean(data.reasoning) ||
    (Array.isArray(data.alternatives) && data.alternatives.length > 0);

  if (!hasAnything) return null;

  const inner = (
    <div className="grid gap-3 sm:grid-cols-2">
      {data.model && (
        <div>
          <span className="text-[10px] text-slate-400 block mb-1">AI Model</span>
          <Badge variant="secondary" className="text-[10px]">{data.model}</Badge>
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

      {data.confidence != null && (
        <div>
          <span className="text-[10px] text-slate-400 block mb-1">Confidence</span>
          <div className="flex items-center gap-2">
            <Progress value={confPct} className="h-2 flex-1" />
            <span className="text-xs font-mono">{confPct.toFixed(0)}%</span>
          </div>
        </div>
      )}

      {data.reasoning && (
        <div className="sm:col-span-2">
          <span className="text-[10px] text-slate-400 block mb-1">Reasoning</span>
          <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
            {data.reasoning}
          </p>
        </div>
      )}

      {Array.isArray(data.alternatives) && data.alternatives.length > 0 && (
        <div className="sm:col-span-2">
          <span className="text-[10px] text-slate-400 block mb-1">Alternatives Considered</span>
          <div className="flex flex-wrap gap-1.5">
            {data.alternatives.map((alt: string, i: number) => (
              <Badge key={i} variant="outline" className="text-[10px]">{alt}</Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  if (!bordered) return inner;

  return (
    <div className="rounded-lg border border-slate-200/60 dark:border-slate-700/60 p-4 bg-white/80 dark:bg-slate-900/80">
      {inner}
    </div>
  );
}
