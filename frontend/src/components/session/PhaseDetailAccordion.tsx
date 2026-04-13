/**
 * Sprint D (2026-04-11) — PhaseDetailAccordion
 *
 * Replaces the flat SessionTimeline that used to live inside SessionPage.
 * Every row is a phase from PHASE_ORDER. Rows are clickable when the
 * phase has a `phase_completed` event in the session log; expanding a
 * row shows a phase-specific template (compliance score, budget bars,
 * vendor ranking table) or a generic key/value drawer for phases whose
 * handler hasn't been enriched yet.
 *
 * Contract:
 *   - Purely driven by `events: SessionEvent[]`, `completedPhases`,
 *     `currentPhase`, `status`. No local source-of-truth store.
 *   - Folds events[] into a phase-keyed payload map ONCE per render
 *     via useMemo. Each phase's payload is the *latest* phase_completed
 *     event payload for that phase (supports retry / re-entry via R20
 *     soft transitions).
 *   - Expansion state is local (Set<string>). On mount, the currently-
 *     active phase is auto-expanded so the user always sees what's
 *     happening right now without clicking.
 *
 * Backend dependency (Sprint C):
 *   Enriched phase_completed payloads are emitted by
 *   backend/agents/p2p_handlers.py for compliance / budget / vendor:
 *     compliance → { compliance_score, compliance_level, warnings, violations, policies_checked }
 *     budget     → { available, total_budget, committed, utilization_pct, department, source_account }
 *     vendor     → { top_vendor, vendor_count, vendors: [...] }
 *   Other phases still emit minimal `{ phase, ref }` payloads until
 *   their handlers are extracted. The accordion renders a GenericCard
 *   for those — no crash, no regression, just less detail.
 *
 * Zero pipelineStore imports.
 */

import { useMemo, useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle2,
  Clock,
  Loader2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Shield,
  DollarSign,
  Users,
  Star,
  ThumbsUp,
  AlertTriangle,
  Trophy,
  FileText,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { SessionEvent } from "@/hooks/useSession";

/* ================================================================ */
/*  Phase order (single source of truth for the accordion)          */
/* ================================================================ */

export const PHASE_ORDER: { key: string; label: string; stage: string }[] = [
  { key: "compliance",         label: "Compliance",          stage: "Planning" },
  { key: "budget",             label: "Budget",              stage: "Planning" },
  { key: "vendor",             label: "Vendor Ranking",      stage: "Planning" },
  { key: "vendor_selection",   label: "Vendor Selection",    stage: "Planning" },
  { key: "pr_creation",        label: "PR Created",          stage: "Execution" },
  { key: "approval",           label: "Approval Routing",    stage: "Execution" },
  { key: "approval_wait",      label: "Awaiting Approval",   stage: "Execution" },
  { key: "po_creation",        label: "PO Creation",         stage: "Execution" },
  { key: "delivery_tracking",  label: "Delivery",            stage: "Fulfillment" },
  { key: "grn",                label: "Goods Receipt",       stage: "Fulfillment" },
  { key: "grn_wait",           label: "Awaiting GRN",        stage: "Fulfillment" },
  { key: "quality_inspection", label: "Quality Check",       stage: "Fulfillment" },
  { key: "invoice_matching",   label: "Invoice Match",       stage: "Settlement" },
  { key: "three_way_match",    label: "3-Way Match",         stage: "Settlement" },
  { key: "payment_readiness",  label: "Payment Ready",       stage: "Settlement" },
  { key: "payment_execution",  label: "Payment",             stage: "Settlement" },
];

type PhaseStatus = "pending" | "active" | "done" | "failed";

interface PhasePayloadMap {
  [phase: string]: Record<string, any>;
}

/* ================================================================ */
/*  Phase-specific template: Compliance                              */
/* ================================================================ */

function ComplianceCard({ payload }: { payload: Record<string, any> }) {
  const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
  const violations = Array.isArray(payload.violations) ? payload.violations : [];
  const policies = Array.isArray(payload.policies_checked) ? payload.policies_checked : [];

  // Sprint D bugfix (2026-04-11): when the backend handler reports no
  // violations AND no warnings but the compliance_score field is null/0
  // (older agent versions don't populate it), show 100 instead of 0.
  // Previously the UI displayed "0/100 — All policies passed", which was
  // contradictory. The visual contract: if the check passed cleanly,
  // we're fully compliant.
  const rawScore = payload.compliance_score;
  const hasExplicitScore =
    rawScore != null && rawScore !== "" && !isNaN(Number(rawScore));
  const passedCleanly = violations.length === 0 && warnings.length === 0;
  const score = hasExplicitScore
    ? Number(rawScore)
    : passedCleanly
    ? 100
    : Math.max(0, 100 - violations.length * 20 - warnings.length * 5);
  const level = payload.compliance_level as string | undefined;

  const scoreColor =
    score >= 80
      ? "text-emerald-600 dark:text-emerald-400"
      : score >= 60
      ? "text-amber-600 dark:text-amber-400"
      : "text-red-600 dark:text-red-400";

  const barColor =
    score >= 80
      ? "bg-emerald-500"
      : score >= 60
      ? "bg-amber-500"
      : "bg-red-500";

  return (
    <div className="space-y-4">
      {/* Score dial */}
      <div className="flex items-center gap-4">
        <div className="relative w-20 h-20 shrink-0">
          <svg className="w-20 h-20 -rotate-90" viewBox="0 0 80 80">
            <circle
              cx="40" cy="40" r="34"
              strokeWidth="6"
              className="fill-none stroke-slate-200 dark:stroke-slate-700"
            />
            <circle
              cx="40" cy="40" r="34"
              strokeWidth="6"
              strokeLinecap="round"
              className={`fill-none ${
                score >= 80 ? "stroke-emerald-500" : score >= 60 ? "stroke-amber-500" : "stroke-red-500"
              }`}
              strokeDasharray={`${(score / 100) * 213.6} 213.6`}
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className={`text-xl font-bold ${scoreColor}`}>{Math.round(score)}</span>
          </div>
        </div>
        <div className="flex-1">
          <div className="text-xs text-slate-500 mb-0.5">Compliance Score</div>
          <div className={`text-lg font-semibold ${scoreColor}`}>{score}/100</div>
          {level && (
            <Badge variant="outline" className="mt-1 text-[10px]">
              {level}
            </Badge>
          )}
        </div>
      </div>

      {/* Policies checked */}
      {policies.length > 0 && (
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1.5">
            Policies Checked ({policies.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {policies.slice(0, 8).map((p: any, i: number) => (
              <Badge key={i} variant="secondary" className="text-[10px]">
                <Shield className="w-3 h-3 mr-1" />
                {typeof p === "string" ? p : p?.name || p?.id || "policy"}
              </Badge>
            ))}
            {policies.length > 8 && (
              <Badge variant="outline" className="text-[10px]">
                +{policies.length - 8} more
              </Badge>
            )}
          </div>
        </div>
      )}

      {/* Violations */}
      {violations.length > 0 && (
        <div>
          <div className="text-[10px] text-red-600 dark:text-red-400 uppercase tracking-wide mb-1.5 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" /> Violations ({violations.length})
          </div>
          <div className="space-y-1.5">
            {violations.map((v: any, i: number) => (
              <div
                key={i}
                className="text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/50 rounded px-2.5 py-1.5"
              >
                {typeof v === "string" ? v : v?.message || v?.description || JSON.stringify(v)}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div>
          <div className="text-[10px] text-amber-600 dark:text-amber-400 uppercase tracking-wide mb-1.5 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Warnings ({warnings.length})
          </div>
          <div className="space-y-1.5">
            {warnings.map((w: any, i: number) => (
              <div
                key={i}
                className="text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50 rounded px-2.5 py-1.5"
              >
                {typeof w === "string" ? w : w?.message || w?.description || JSON.stringify(w)}
              </div>
            ))}
          </div>
        </div>
      )}

      {warnings.length === 0 && violations.length === 0 && (
        <div className="text-xs text-emerald-700 dark:text-emerald-400 flex items-center gap-1.5">
          <CheckCircle2 className="w-4 h-4" />
          All policies passed with no warnings or violations.
        </div>
      )}
    </div>
  );
}

/* ================================================================ */
/*  Phase-specific template: Budget                                  */
/* ================================================================ */

function BudgetCard({ payload }: { payload: Record<string, any> }) {
  const num = (v: unknown): number | null => {
    if (v == null) return null;
    const n = typeof v === "number" ? v : parseFloat(String(v).replace(/,/g, ""));
    return isNaN(n) ? null : n;
  };

  const total = num(payload.total_budget);
  const committed = num(payload.committed);
  const available = num(payload.available ?? payload.budget_remaining);
  const utilPct =
    typeof payload.utilization_pct === "number"
      ? payload.utilization_pct
      : parseFloat(String(payload.utilization_pct || 0)) || 0;
  const department = payload.department as string | undefined;
  const account = payload.source_account as string | undefined;

  const fmt = (n: number | null): string =>
    n == null ? "—" : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

  // Derive missing fields when possible
  const effectiveCommitted =
    committed != null ? committed : total != null && available != null ? total - available : null;
  const effectivePct =
    utilPct > 0
      ? utilPct
      : total != null && total > 0 && effectiveCommitted != null
      ? (effectiveCommitted / total) * 100
      : 0;

  const barColor =
    effectivePct < 60 ? "bg-emerald-500" : effectivePct < 85 ? "bg-amber-500" : "bg-red-500";

  return (
    <div className="space-y-4">
      {/* Top row — dept + account */}
      {(department || account) && (
        <div className="flex gap-2 flex-wrap">
          {department && (
            <Badge variant="secondary" className="text-[10px]">
              <Users className="w-3 h-3 mr-1" />
              {department}
            </Badge>
          )}
          {account && (
            <Badge variant="outline" className="text-[10px]">
              <FileText className="w-3 h-3 mr-1" />
              {account}
            </Badge>
          )}
        </div>
      )}

      {/* Utilization bar */}
      <div>
        <div className="flex items-end justify-between mb-1.5">
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Utilization</div>
            <div className="text-2xl font-bold text-slate-800 dark:text-slate-200">
              {effectivePct.toFixed(0)}%
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">Available</div>
            <div className="text-lg font-semibold text-emerald-700 dark:text-emerald-400">
              {fmt(available)}
            </div>
          </div>
        </div>
        <div className="w-full h-3 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(effectivePct, 100)}%` }}
            transition={{ duration: 1, ease: "easeOut" }}
            className={`h-3 ${barColor}`}
          />
        </div>
      </div>

      {/* Breakdown grid */}
      <div className="grid grid-cols-3 gap-3 text-center">
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-2">
          <div className="text-[10px] text-slate-500 uppercase mb-0.5">Total</div>
          <div className="text-sm font-semibold flex items-center justify-center gap-1">
            <DollarSign className="w-3.5 h-3.5 text-slate-400" />
            {fmt(total)}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-2">
          <div className="text-[10px] text-slate-500 uppercase mb-0.5">Committed</div>
          <div className="text-sm font-semibold text-amber-700 dark:text-amber-400">
            {fmt(effectiveCommitted)}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-2">
          <div className="text-[10px] text-slate-500 uppercase mb-0.5">Available</div>
          <div className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">
            {fmt(available)}
          </div>
        </div>
      </div>

      {payload.budget_verified === true && (
        <div className="text-xs text-emerald-700 dark:text-emerald-400 flex items-center gap-1.5">
          <CheckCircle2 className="w-4 h-4" />
          Budget verified — funds reserved for this PR.
        </div>
      )}
    </div>
  );
}

/* ================================================================ */
/*  Phase-specific template: Vendor Ranking                          */
/* ================================================================ */

interface VendorRow {
  vendor_id?: string;
  vendor_name?: string;
  total_score?: number | null;
  price?: number | null;
  delivery_days?: number | null;
  quality_score?: number | null;
  compliance_score?: number | null;
  risk_score?: number | null;
  recommendation?: string;
}

function VendorRankingCard({ payload }: { payload: Record<string, any> }) {
  const topVendor = payload.top_vendor as string | undefined;
  const vendorCount = payload.vendor_count as number | undefined;
  const vendors: VendorRow[] = Array.isArray(payload.vendors) ? payload.vendors : [];

  if (vendors.length === 0) {
    return (
      <div className="text-xs text-slate-500">
        Vendor details not included in payload. Shortlist size: {vendorCount ?? "unknown"}.
        {topVendor && <> Top pick: <span className="font-semibold">{topVendor}</span></>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {topVendor && (
        <div className="flex items-center gap-2">
          <Trophy className="w-4 h-4 text-amber-500" />
          <span className="text-xs text-slate-500">Top pick:</span>
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">
            {topVendor}
          </span>
          {vendorCount != null && (
            <Badge variant="outline" className="text-[10px] ml-auto">
              {vendors.length} of {vendorCount} shown
            </Badge>
          )}
        </div>
      )}

      {/* Ranked list */}
      <div className="space-y-2">
        {vendors.map((v, idx) => {
          const isTop = v.vendor_name === topVendor;
          const score = typeof v.total_score === "number" ? v.total_score : Number(v.total_score || 0);
          return (
            <div
              key={v.vendor_id || `${v.vendor_name}-${idx}`}
              className={`rounded-lg border p-3 transition-colors ${
                isTop
                  ? "border-amber-300 dark:border-amber-700 bg-amber-50/50 dark:bg-amber-950/20"
                  : "border-slate-200 dark:border-slate-700"
              }`}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <div className="text-xs font-mono text-slate-400 shrink-0">#{idx + 1}</div>
                  <span className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate">
                    {v.vendor_name || "Unknown vendor"}
                  </span>
                  {isTop && (
                    <Badge className="bg-amber-500 hover:bg-amber-600 text-white text-[10px] gap-1 shrink-0">
                      <Trophy className="w-3 h-3" />
                      Top
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Star className="w-3 h-3 text-amber-500" />
                  <span className="text-sm font-semibold tabular-nums">{score.toFixed(1)}</span>
                </div>
              </div>

              {/* Mini metrics row */}
              <div className="grid grid-cols-4 gap-2 text-[10px]">
                {v.price != null && (
                  <div>
                    <div className="text-slate-400 uppercase">Price</div>
                    <div className="font-semibold text-slate-700 dark:text-slate-300">
                      ${Number(v.price).toLocaleString()}
                    </div>
                  </div>
                )}
                {v.delivery_days != null && (
                  <div>
                    <div className="text-slate-400 uppercase">Delivery</div>
                    <div className="font-semibold text-slate-700 dark:text-slate-300">
                      {v.delivery_days}d
                    </div>
                  </div>
                )}
                {v.quality_score != null && (
                  <div>
                    <div className="text-slate-400 uppercase">Quality</div>
                    <div className="font-semibold text-slate-700 dark:text-slate-300">
                      {Number(v.quality_score).toFixed(1)}
                    </div>
                  </div>
                )}
                {v.risk_score != null && (
                  <div>
                    <div className="text-slate-400 uppercase">Risk</div>
                    <div className="font-semibold text-slate-700 dark:text-slate-300">
                      {Number(v.risk_score).toFixed(1)}
                    </div>
                  </div>
                )}
              </div>

              {v.recommendation && (
                <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400 italic">
                  <ThumbsUp className="w-3 h-3 inline mr-1" />
                  {v.recommendation}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ================================================================ */
/*  Phase-specific template: Generic fallback                        */
/* ================================================================ */

function GenericPayloadCard({ payload }: { payload: Record<string, any> }) {
  const entries = Object.entries(payload).filter(([k]) => k !== "phase" && k !== "ref");

  if (entries.length === 0) {
    return (
      <div className="text-xs text-slate-500 italic">
        Phase completed. No enriched payload yet — this handler's Sprint C
        enrichment is not wired (see HF-3 extraction status).
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => {
        const isScalar = typeof v === "string" || typeof v === "number" || typeof v === "boolean";
        return (
          <div key={k} className="text-xs">
            <span className="text-slate-500 capitalize">{k.replace(/_/g, " ")}:</span>{" "}
            {isScalar ? (
              <span className="font-medium text-slate-800 dark:text-slate-200">{String(v)}</span>
            ) : Array.isArray(v) ? (
              <span className="font-medium text-slate-800 dark:text-slate-200">
                [{v.length} items]
              </span>
            ) : (
              <pre className="mt-1 bg-slate-50 dark:bg-slate-900/40 rounded p-2 overflow-auto max-h-32 text-[10px]">
                {JSON.stringify(v, null, 2)}
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ================================================================ */
/*  Template dispatcher                                              */
/* ================================================================ */

function PhaseTemplate({ phase, payload }: { phase: string; payload: Record<string, any> }) {
  switch (phase) {
    case "compliance":
      return <ComplianceCard payload={payload} />;
    case "budget":
      return <BudgetCard payload={payload} />;
    case "vendor":
    case "vendor_selection":
      return <VendorRankingCard payload={payload} />;
    default:
      return <GenericPayloadCard payload={payload} />;
  }
}

/* ================================================================ */
/*  Row icon helper                                                  */
/* ================================================================ */

function StatusIcon({ status }: { status: PhaseStatus }) {
  if (status === "done") return <CheckCircle2 className="w-5 h-5 text-emerald-600" />;
  if (status === "active") return <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />;
  if (status === "failed") return <AlertCircle className="w-5 h-5 text-red-600" />;
  return <Clock className="w-5 h-5 text-muted-foreground" />;
}

/* ================================================================ */
/*  Main component                                                   */
/* ================================================================ */

interface PhaseDetailAccordionProps {
  events: SessionEvent[];
  completedPhases: string[];
  currentPhase: string;
  status: string;
  /** When a gate is open, SessionPage passes the gate panel here so it
   *  renders INLINE inside the active accordion row instead of above. */
  gateElement?: React.ReactNode;
}

export function PhaseDetailAccordion({
  events,
  completedPhases,
  currentPhase,
  status,
  gateElement,
}: PhaseDetailAccordionProps) {
  // Fold events → phase payload map (latest phase_completed per phase)
  const phasePayloads = useMemo<PhasePayloadMap>(() => {
    const map: PhasePayloadMap = {};
    for (const ev of events) {
      if (ev.event_type === "phase_completed" && ev.payload?.phase) {
        const phase = ev.payload.phase as string;
        map[phase] = ev.payload;
      }
    }
    return map;
  }, [events]);

  // Sprint D bugfix (2026-04-11): compute effective completed phases.
  // Any phase whose PHASE_ORDER index is STRICTLY LESS THAN the index of
  // currentPhase is implicitly done — even if the backend never emitted an
  // explicit phase_completed event for it. This fixes:
  //   - vendor_selection showing as pending after gate resolved (the
  //     backend used to only emit gate_resolved, not phase_completed)
  //   - auto-approved workflows where steps are skipped over
  //   - any future phase that only has a phase_started without a
  //     phase_completed in the event stream
  // Explicit completedPhases from phase_completed events still take
  // priority — this only fills in the gaps.
  const effectiveCompleted = useMemo<Set<string>>(() => {
    const set = new Set<string>(completedPhases);
    const currentIdx = PHASE_ORDER.findIndex((p) => p.key === currentPhase);
    if (currentIdx > 0) {
      for (let i = 0; i < currentIdx; i++) {
        set.add(PHASE_ORDER[i].key);
      }
    }
    return set;
  }, [completedPhases, currentPhase]);

  // Per-row status derivation
  const phaseStatus = useMemo<Record<string, PhaseStatus>>(() => {
    const s: Record<string, PhaseStatus> = {};
    for (const p of PHASE_ORDER) {
      if (effectiveCompleted.has(p.key)) {
        s[p.key] = "done";
      } else if (p.key === currentPhase) {
        s[p.key] = status === "failed" ? "failed" : "active";
      } else {
        s[p.key] = "pending";
      }
    }
    return s;
  }, [effectiveCompleted, currentPhase, status]);

  // Expansion state — auto-expand the currently-active phase on mount/update
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set<string>());

  useEffect(() => {
    // Whenever currentPhase changes, add it to the expanded set so the user
    // always sees what's happening right now without clicking.
    setExpanded((prev) => {
      if (prev.has(currentPhase)) return prev;
      const next = new Set(prev);
      next.add(currentPhase);
      return next;
    });
  }, [currentPhase]);

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Group phases by stage for visual separation
  const stages = useMemo(() => {
    const groups: { stage: string; phases: typeof PHASE_ORDER }[] = [];
    let currentGroup: { stage: string; phases: typeof PHASE_ORDER } | null = null;
    for (const p of PHASE_ORDER) {
      if (!currentGroup || currentGroup.stage !== p.stage) {
        currentGroup = { stage: p.stage, phases: [] };
        groups.push(currentGroup);
      }
      currentGroup.phases.push(p);
    }
    return groups;
  }, []);

  // Sprint D bugfix (2026-04-11): count rows marked "done" in phaseStatus
  // (which uses effectiveCompleted), not raw completedPhases. This keeps
  // the header "X of 16 phases completed" and the progress % in sync with
  // the visual row states.
  const completedCount = Object.values(phaseStatus).filter(
    (s) => s === "done"
  ).length;
  const totalCount = PHASE_ORDER.length;

  return (
    <Card>
      <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">Pipeline Progress</h3>
          <p className="text-[11px] text-slate-500 mt-0.5">
            {completedCount} of {totalCount} phases completed · click any row to drill down
          </p>
        </div>
        <div className="text-xs tabular-nums text-slate-500">
          {Math.round((completedCount / totalCount) * 100)}%
        </div>
      </div>

      <CardContent className="p-0">
        {stages.map((group) => (
          <div key={group.stage} className="border-b border-slate-100 dark:border-slate-800 last:border-0">
            <div className="px-4 py-1.5 bg-slate-50/60 dark:bg-slate-900/40 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              {group.stage}
            </div>
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {group.phases.map((p, idxInGroup) => {
                const st = phaseStatus[p.key];
                const payload = phasePayloads[p.key];
                const hasDetail = !!payload;
                const isExpanded = expanded.has(p.key);
                const isExpandable = hasDetail || st === "active";
                const globalIdx = PHASE_ORDER.findIndex((pp) => pp.key === p.key);

                return (
                  <div key={p.key}>
                    <button
                      type="button"
                      onClick={() => isExpandable && toggle(p.key)}
                      disabled={!isExpandable}
                      className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                        isExpandable
                          ? "hover:bg-slate-50 dark:hover:bg-slate-900/40 cursor-pointer"
                          : "cursor-default"
                      } ${
                        st === "active"
                          ? "bg-blue-50/50 dark:bg-blue-950/20"
                          : ""
                      }`}
                    >
                      <span className="w-5 text-[10px] font-mono text-slate-400 text-right shrink-0">
                        {globalIdx + 1}
                      </span>
                      <StatusIcon status={st} />
                      <span
                        className={`flex-1 text-sm ${
                          st === "done"
                            ? "text-slate-600 dark:text-slate-400"
                            : st === "active"
                            ? "font-semibold text-slate-900 dark:text-slate-100"
                            : st === "failed"
                            ? "text-red-700 dark:text-red-400 font-medium"
                            : "text-slate-400 dark:text-slate-500"
                        }`}
                      >
                        {p.label}
                      </span>
                      {hasDetail && <DetailSummary phase={p.key} payload={payload} />}
                      {isExpandable && (
                        isExpanded
                          ? <ChevronUp className="w-4 h-4 text-slate-400 shrink-0" />
                          : <ChevronDown className="w-4 h-4 text-slate-400 shrink-0" />
                      )}
                    </button>

                    <AnimatePresence initial={false}>
                      {isExpanded && isExpandable && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="px-4 pb-4 pt-1 pl-12">
                            {hasDetail ? (
                              <PhaseTemplate phase={p.key} payload={payload} />
                            ) : st === "active" && gateElement && p.key === currentPhase ? (
                              /* Gate panel (approval / vendor / GRN) rendered
                                 inline so the user sees it right here instead
                                 of needing to scroll above the accordion. */
                              gateElement
                            ) : (
                              <div className="text-xs text-slate-500 italic">
                                Phase in progress — waiting for the handler to report results.
                              </div>
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/* ================================================================ */
/*  One-liner summary shown inline on collapsed row                  */
/* ================================================================ */

function DetailSummary({ phase, payload }: { phase: string; payload: Record<string, any> }) {
  let text = "";
  if (phase === "compliance" && typeof payload.compliance_score === "number") {
    text = `${payload.compliance_score}/100`;
  } else if (phase === "budget") {
    const avail = payload.available ?? payload.budget_remaining;
    if (avail != null) text = `$${Number(avail).toLocaleString()} available`;
  } else if (phase === "vendor" && payload.top_vendor) {
    text = String(payload.top_vendor);
  } else if (phase === "po_creation" && payload.ref?.po_number) {
    text = String(payload.ref.po_number);
  } else if (phase === "pr_creation" && payload.ref?.pr_id) {
    text = String(payload.ref.pr_id);
  }

  if (!text) return null;

  return (
    <span className="text-[11px] text-slate-500 dark:text-slate-400 font-mono truncate max-w-[40%] shrink-0">
      {text}
    </span>
  );
}
