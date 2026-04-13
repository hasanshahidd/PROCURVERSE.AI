/**
 * Sprint D (2026-04-11) — LiveActivityTicker
 *
 * Sticky strip that shows the latest "what is the agent doing right now"
 * signal, driven purely by `agent_activity` events streamed from the
 * backend. This component owns no state — it's a pure projection of
 * `useSession(id).events`, filtered and sliced.
 *
 * Contract:
 *   - Accepts a `SessionEvent[]` prop (the `events` field from useSession).
 *   - Renders nothing when `status` is terminal (completed/failed/cancelled).
 *   - Renders nothing when no `agent_activity` event has been seen yet.
 *   - Shows only the most recent `agent_activity` event's agent, lifecycle,
 *     and `detail` message.
 *
 * Backend dependency (Sprint C):
 *   `backend/agents/p2p_handlers.py` emits `agent_activity` events with
 *   this shape:
 *     {
 *       agent:     "ComplianceCheckAgent",
 *       phase:     "compliance",
 *       lifecycle: "observing" | "deciding" | "acting" | "learning",
 *       detail:    "Gathering policy rules and request context",
 *     }
 *   Only compliance / budget / vendor handlers emit these today (HF-3
 *   extraction still in progress). For unextracted phases the ticker
 *   simply hides — the flat phase-level spinner in PhaseDetailAccordion
 *   continues to indicate activity.
 *
 * Zero pipelineStore imports. Zero local state beyond animation.
 */

import { motion, AnimatePresence } from "framer-motion";
import { Loader2, Eye, Lightbulb, Zap, Database } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { SessionEvent } from "@/hooks/useSession";
import { agentShort } from "./phase-helpers";

/* ================================================================ */
/*  Types                                                            */
/* ================================================================ */

type Lifecycle = "observing" | "deciding" | "acting" | "learning";

interface AgentActivityPayload {
  agent?: string;
  phase?: string;
  lifecycle?: Lifecycle | string;
  detail?: string;
}

interface LiveActivityTickerProps {
  events: SessionEvent[];
  status: string; // from useSession().status
}

/* ================================================================ */
/*  Lifecycle → icon + label                                         */
/* ================================================================ */

const LIFECYCLE_META: Record<
  Lifecycle,
  { Icon: typeof Eye; label: string; colorClass: string }
> = {
  observing: {
    Icon: Eye,
    label: "observing",
    colorClass: "bg-cyan-100 text-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-300",
  },
  deciding: {
    Icon: Lightbulb,
    label: "deciding",
    colorClass: "bg-purple-100 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300",
  },
  acting: {
    Icon: Zap,
    label: "acting",
    colorClass: "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
  },
  learning: {
    Icon: Database,
    label: "learning",
    colorClass: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  },
};

/* ================================================================ */
/*  Component                                                        */
/* ================================================================ */

export function LiveActivityTicker({ events, status }: LiveActivityTickerProps) {
  // Hide when session is not running (completed / failed / cancelled / paused)
  // Paused_human still keeps the ticker visible so the last "deciding"
  // message stays on screen while the user decides.
  if (status === "completed" || status === "failed" || status === "cancelled") {
    return null;
  }

  // Find the MOST RECENT agent_activity event. We scan from the end for O(1)
  // amortized perf on long sessions.
  let latest: SessionEvent | null = null;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].event_type === "agent_activity") {
      latest = events[i];
      break;
    }
  }

  if (!latest) return null;

  const payload = (latest.payload || {}) as AgentActivityPayload;
  const agent = payload.agent || "Agent";
  const lifecycleKey = (payload.lifecycle || "observing").toLowerCase() as Lifecycle;
  const meta = LIFECYCLE_META[lifecycleKey] || LIFECYCLE_META.observing;
  const Icon = meta.Icon;
  const detail = payload.detail || "";

  // Stable key so the motion.div re-animates when the content changes
  const key = `${latest.sequence_number}-${agent}-${lifecycleKey}`;

  return (
    <div className="sticky top-0 z-20 -mx-4 md:-mx-6 mb-4">
      <div className="mx-4 md:mx-6 rounded-lg border border-indigo-200 dark:border-indigo-800/50 bg-gradient-to-r from-indigo-50 to-blue-50 dark:from-indigo-950/40 dark:to-blue-950/30 shadow-sm backdrop-blur">
        <AnimatePresence mode="wait">
          <motion.div
            key={key}
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
            transition={{ duration: 0.2 }}
            className="flex items-center gap-3 px-4 py-2.5"
          >
            {/* Spinner only while running (not paused) */}
            {status === "running" ? (
              <Loader2 className="w-4 h-4 text-indigo-500 animate-spin shrink-0" />
            ) : (
              <Icon className="w-4 h-4 text-indigo-500 shrink-0" />
            )}

            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
              Now:
            </span>

            <span className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
              {agentShort(agent)}
            </span>

            <Badge className={`text-[10px] ${meta.colorClass} shrink-0 gap-1`}>
              <Icon className="w-3 h-3" />
              {meta.label}
            </Badge>

            {detail && (
              <span className="text-xs text-slate-600 dark:text-slate-400 truncate flex-1 min-w-0">
                {detail}
              </span>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
