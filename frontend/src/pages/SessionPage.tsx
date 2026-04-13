/**
 * SessionPage — the P2P view for a single execution session (Layer 3).
 *
 * Everything rendered here is derived from `useSession(sessionId)`. There is
 * NO local source-of-truth store — the session event log is the truth.
 * On refresh, on navigation, on network blip: we reconnect and replay.
 */
import { useParams, useLocation } from "wouter";
import { useEffect, useState } from "react";
import {
  CheckCircle2,
  AlertCircle,
  Loader2,
  Play,
  X,
  ArrowRight,
  FileText,
  User,
  Package,
  DollarSign,
  Star,
  ThumbsUp,
  AlertTriangle,
  Trophy,
  Database,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useToast } from "@/hooks/use-toast";
import { useSession, type SessionEvent, type OpenGate } from "@/hooks/useSession";
import { apiFetch } from "@/lib/api";
// Sprint D (2026-04-11) — event-sourced session UI ingredients
import { LiveActivityTicker } from "@/components/session/LiveActivityTicker";
import { PhaseDetailAccordion } from "@/components/session/PhaseDetailAccordion";
import { ApprovalPanel } from "@/components/session/ApprovalPanel";
import { POResultCard } from "@/components/session/POResultCard";

// ─────────────────────────────────────────────────────────────────────────────
// Phase visualization
// ─────────────────────────────────────────────────────────────────────────────

const PHASE_ORDER: { key: string; label: string }[] = [
  { key: "compliance", label: "Compliance" },
  { key: "budget", label: "Budget" },
  { key: "vendor", label: "Vendor Ranking" },
  { key: "vendor_selection", label: "Vendor Selection" },
  { key: "pr_creation", label: "PR Created" },
  { key: "approval", label: "Approval Routing" },
  { key: "approval_wait", label: "Awaiting Approval" },
  { key: "po_creation", label: "PO Creation" },
  { key: "delivery_tracking", label: "Delivery" },
  { key: "grn", label: "Goods Receipt" },
  { key: "grn_wait", label: "Awaiting GRN" },
  { key: "quality_inspection", label: "Quality Check" },
  { key: "invoice_matching", label: "Invoice Match" },
  { key: "three_way_match", label: "3-Way Match" },
  { key: "payment_readiness", label: "Payment Ready" },
  { key: "payment_execution", label: "Payment" },
];

function statusBadge(status: string) {
  const map: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline"; className: string }> = {
    running: { label: "Running", variant: "default", className: "bg-blue-600 hover:bg-blue-700" },
    paused_human: { label: "Waiting on You", variant: "default", className: "bg-amber-500 hover:bg-amber-600" },
    completed: { label: "Completed", variant: "default", className: "bg-emerald-600 hover:bg-emerald-700" },
    failed: { label: "Failed", variant: "destructive", className: "" },
    cancelled: { label: "Cancelled", variant: "secondary", className: "" },
  };
  const cfg = map[status] || { label: status, variant: "outline" as const, className: "" };
  return (
    <Badge variant={cfg.variant} className={cfg.className}>
      {cfg.label}
    </Badge>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-component: session header
// ─────────────────────────────────────────────────────────────────────────────

// Sprint D / Oracle-focus (2026-04-11): per-session data-source badge.
// Fetches /api/config/data-source once on mount and renders a small pill next
// to the session status so the operator can see, at a glance, that this run
// is reading from Oracle Fusion (or whichever ERP they picked). This is the
// frontend half of the "make Oracle usage visible" promise — backend side is
// the [ADAPTER-BOOT] / [ADAPTER-CALL] log lines in OracleAdapter.
function SessionDataSourceBadge() {
  const [erp, setErp] = useState<{
    label: string;
    mode: string;
    name: string;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/api/config/data-source");
        if (!res.ok || cancelled) return;
        const d = await res.json();
        setErp({
          label: d.current_label || d.current || "Unknown",
          mode: d.current_mode || "",
          name: d.current || "",
        });
      } catch {
        // non-fatal — the badge just hides
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!erp) return null;

  const modeTone: Record<string, string> = {
    demo: "bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-950/30 dark:text-amber-200 dark:border-amber-700",
    live: "bg-emerald-50 text-emerald-900 border-emerald-300 dark:bg-emerald-950/30 dark:text-emerald-200 dark:border-emerald-700",
    direct: "bg-blue-50 text-blue-900 border-blue-300 dark:bg-blue-950/30 dark:text-blue-200 dark:border-blue-700",
  };

  return (
    <div
      className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
        modeTone[erp.mode] || "bg-gray-50 text-gray-900 border-gray-300"
      }`}
      title={`All ERP reads during this session hit: ${erp.label} (${erp.mode || "unknown mode"})`}
    >
      <Database className="h-3 w-3" />
      <span>Data source: {erp.label}</span>
    </div>
  );
}

function SessionHeader({
  sessionId,
  session,
  status,
  onCancel,
}: {
  sessionId: string;
  session: ReturnType<typeof useSession>["session"];
  status: string;
  onCancel: () => void;
}) {
  const summary = (session?.request_summary || {}) as any;
  const prData = summary.pr_data || {};
  const canCancel = status === "running" || status === "paused_human";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <CardTitle className="text-xl">Session {sessionId.slice(0, 8)}</CardTitle>
              {statusBadge(status)}
              <SessionDataSourceBadge />
            </div>
            {summary.request && (
              <p className="text-sm text-muted-foreground mb-3">"{summary.request}"</p>
            )}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              {prData.product_name && (
                <div className="flex items-center gap-2">
                  <Package className="w-4 h-4 text-muted-foreground" />
                  <span>{prData.product_name}</span>
                </div>
              )}
              {prData.department && (
                <div className="flex items-center gap-2">
                  <User className="w-4 h-4 text-muted-foreground" />
                  <span>{prData.department}</span>
                </div>
              )}
              {prData.quantity != null && (
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-muted-foreground" />
                  <span>Qty {prData.quantity}</span>
                </div>
              )}
              {prData.budget != null && (
                <div className="flex items-center gap-2">
                  <DollarSign className="w-4 h-4 text-muted-foreground" />
                  <span>${Number(prData.budget).toLocaleString()}</span>
                </div>
              )}
            </div>
          </div>
          {canCancel && (
            <Button variant="outline" size="sm" onClick={onCancel}>
              <X className="w-4 h-4 mr-1" />
              Cancel
            </Button>
          )}
        </div>
      </CardHeader>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sprint D (2026-04-11): The old flat SessionTimeline sub-component was
// removed from this file. Its replacement is PhaseDetailAccordion, which
// lives in @/components/session/PhaseDetailAccordion and folds the event
// log into rich per-phase templates (compliance score, budget bars,
// vendor ranking). The old Pipeline Progress card is now a single import
// statement near the top of this file — intentional, the accordion owns
// all phase rendering.
// ─────────────────────────────────────────────────────────────────────────────
// Sub-component: vendor_selection gate (rich card view from decision_context)
// ─────────────────────────────────────────────────────────────────────────────

type ScoredVendor = {
  vendor_name: string;
  score?: number | null;
  recommendation_reason?: string;
  strengths?: string[];
  concerns?: string[];
};

function VendorSelectionPanel({
  gate,
  onResolve,
}: {
  gate: OpenGate;
  onResolve: (action: string, payload?: Record<string, any>) => Promise<void>;
}) {
  const ctx = gate.decision_context || {};
  const snapshot: ScoredVendor[] = Array.isArray(ctx.scoring_snapshot)
    ? (ctx.scoring_snapshot as ScoredVendor[])
    : [];
  const topVendorName: string =
    (typeof ctx.top_vendor === "string" && ctx.top_vendor) ||
    snapshot[0]?.vendor_name ||
    "";
  const totalCandidates: number =
    typeof ctx.total_candidates === "number" ? (ctx.total_candidates as number) : snapshot.length;

  const [selected, setSelected] = useState<string>(topVendorName);
  const [submitting, setSubmitting] = useState(false);

  // Keep selection in sync if a fresh gate event arrives with a different top
  useEffect(() => {
    if (topVendorName && !snapshot.find((v) => v.vendor_name === selected)) {
      setSelected(topVendorName);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gate.gate_id]);

  const handle = async (action: string, payload: Record<string, any> = {}) => {
    setSubmitting(true);
    try {
      await onResolve(action, payload);
    } finally {
      setSubmitting(false);
    }
  };

  if (snapshot.length === 0) {
    // Fallback: backend didn't include the snapshot — show vendor names from gate_ref
    const names: string[] = Array.isArray(gate.gate_ref?.vendor_names)
      ? (gate.gate_ref?.vendor_names as string[])
      : [];
    return (
      <Card className="border-amber-300 dark:border-amber-700 shadow-lg">
        <CardHeader>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
            <CardTitle className="text-lg">Confirm Vendor</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Top vendor: <span className="font-semibold text-foreground">{topVendorName || "—"}</span>
          </p>
          {names.length > 0 && (
            <div className="text-sm">
              Shortlist:{" "}
              <span className="font-medium">{names.join(", ")}</span>
            </div>
          )}
          <div className="flex gap-2 pt-2">
            <Button disabled={submitting} onClick={() => handle("confirm_vendor", { selected_vendor_name: topVendorName })}>
              {submitting ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Play className="w-4 h-4 mr-1" />}
              Confirm {topVendorName || "top vendor"}
            </Button>
            <Button variant="destructive" disabled={submitting} onClick={() => handle("reject")}>
              Reject
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-amber-300 dark:border-amber-700 shadow-lg">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
            <CardTitle className="text-lg">Confirm Vendor</CardTitle>
          </div>
          <Badge variant="outline" className="text-xs">
            {snapshot.length} of {totalCandidates} candidates shown
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground mt-2">
          The vendor agent ranked these candidates. Pick one to continue, or reject the shortlist.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3">
          {snapshot.map((v, idx) => {
            const isTop = v.vendor_name === topVendorName;
            const isSelected = v.vendor_name === selected;
            return (
              <button
                key={`${v.vendor_name}-${idx}`}
                type="button"
                onClick={() => setSelected(v.vendor_name)}
                className={`text-left rounded-lg border p-4 transition-all ${
                  isSelected
                    ? "border-amber-500 bg-amber-50 dark:bg-amber-950/30 ring-2 ring-amber-400/40"
                    : "border-border hover:border-amber-300 hover:bg-muted/30"
                }`}
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <div
                      className={`w-4 h-4 rounded-full border-2 flex-shrink-0 ${
                        isSelected ? "border-amber-500 bg-amber-500" : "border-muted-foreground"
                      }`}
                    >
                      {isSelected && <CheckCircle2 className="w-3 h-3 text-white -ml-px -mt-px" />}
                    </div>
                    <span className="font-semibold text-base truncate">{v.vendor_name}</span>
                    {isTop && (
                      <Badge className="bg-amber-500 hover:bg-amber-600 text-white text-xs gap-1 flex-shrink-0">
                        <Trophy className="w-3 h-3" />
                        Top pick
                      </Badge>
                    )}
                  </div>
                  {v.score != null && (
                    <Badge variant="outline" className="gap-1 flex-shrink-0">
                      <Star className="w-3 h-3 text-amber-500" />
                      {Number(v.score).toFixed(1)}
                    </Badge>
                  )}
                </div>
                {v.recommendation_reason && (
                  <p className="text-sm text-muted-foreground mb-2 ml-6">{v.recommendation_reason}</p>
                )}
                {(v.strengths?.length || v.concerns?.length) ? (
                  <div className="ml-6 space-y-1.5">
                    {v.strengths && v.strengths.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {v.strengths.slice(0, 4).map((s, i) => (
                          <span
                            key={i}
                            className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300"
                          >
                            <ThumbsUp className="w-3 h-3" />
                            {s}
                          </span>
                        ))}
                      </div>
                    )}
                    {v.concerns && v.concerns.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {v.concerns.slice(0, 4).map((c, i) => (
                          <span
                            key={i}
                            className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300"
                          >
                            <AlertTriangle className="w-3 h-3" />
                            {c}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ) : null}
              </button>
            );
          })}
        </div>

        <div className="flex gap-2 pt-2 border-t">
          <Button
            disabled={submitting || !selected}
            onClick={() => handle("confirm_vendor", { selected_vendor_name: selected })}
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            {submitting ? (
              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
            ) : (
              <CheckCircle2 className="w-4 h-4 mr-1" />
            )}
            Confirm {selected || "vendor"}
          </Button>
          <Button variant="destructive" disabled={submitting} onClick={() => handle("reject")}>
            Reject all
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-component: open gate action panel (generic — dispatches to specialized panels)
// ─────────────────────────────────────────────────────────────────────────────

function SessionGate({
  gate,
  onResolve,
  sessionId,
}: {
  gate: OpenGate;
  onResolve: (action: string, payload?: Record<string, any>) => Promise<void>;
  sessionId?: string;
}) {
  // Specialized panels for known gate types.
  // Sprint D (2026-04-11): approval gates now route to the dedicated
  // ApprovalPanel which reads pr_summary / line_items / approval_chain
  // from gate.decision_context. Vendor selection keeps its in-file panel
  // (was already rich from Sprint A). Everything else falls back to
  // GenericGatePanel which shows a JSON drawer + action buttons.
  if (gate.gate_type === "vendor_selection") {
    return <VendorSelectionPanel gate={gate} onResolve={onResolve} />;
  }
  if (gate.gate_type === "approval") {
    return <ApprovalPanel gate={gate} onResolve={onResolve} sessionId={sessionId} />;
  }
  return <GenericGatePanel gate={gate} onResolve={onResolve} />;
}

function GenericGatePanel({
  gate,
  onResolve,
}: {
  gate: OpenGate;
  onResolve: (action: string, payload?: Record<string, any>) => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState(false);

  const handle = async (action: string, payload: Record<string, any> = {}) => {
    setSubmitting(true);
    try {
      await onResolve(action, payload);
    } finally {
      setSubmitting(false);
    }
  };

  const gateRef = gate.gate_ref || {};
  const ctx = gate.decision_context || {};

  const gateConfig: Record<
    string,
    { title: string; description: string; actions: { label: string; action: string; variant?: "default" | "destructive" | "outline" }[] }
  > = {
    approval: {
      title: "Approval Required",
      description: "Review the PR details and approve or reject.",
      actions: [
        { label: "Approve", action: "approve" },
        { label: "Reject", action: "reject", variant: "destructive" },
      ],
    },
    grn: {
      title: "Confirm Goods Received",
      description: "Confirm that the items have physically arrived from the vendor.",
      actions: [
        { label: "Confirm received", action: "confirm_grn" },
        { label: "Report issue", action: "report_issue", variant: "outline" },
      ],
    },
  };

  const cfg = gateConfig[gate.gate_type] || {
    title: `Gate: ${gate.gate_type}`,
    description: "Human decision required to proceed.",
    actions: [{ label: "Confirm", action: "confirm" }],
  };

  return (
    <Card className="border-amber-300 dark:border-amber-700 shadow-lg">
      <CardHeader>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
          <CardTitle className="text-lg">{cfg.title}</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{cfg.description}</p>

        {/* Gate reference fields */}
        {Object.keys(gateRef).length > 0 && (
          <div className="grid grid-cols-2 gap-2 text-sm bg-muted/30 p-3 rounded">
            {Object.entries(gateRef).map(([k, v]) => (
              <div key={k}>
                <span className="text-muted-foreground">{k}:</span>{" "}
                <span className="font-medium">{Array.isArray(v) ? v.join(", ") : String(v)}</span>
              </div>
            ))}
          </div>
        )}

        {/* Decision context snapshot */}
        {Object.keys(ctx).length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              Why this gate? (context snapshot)
            </summary>
            <pre className="mt-2 p-2 bg-muted/20 rounded overflow-auto max-h-40">
              {JSON.stringify(ctx, null, 2)}
            </pre>
          </details>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 pt-2">
          {cfg.actions.map((a) => (
            <Button
              key={a.action}
              variant={a.variant || "default"}
              disabled={submitting}
              onClick={() => handle(a.action)}
            >
              {submitting ? (
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              ) : (
                <Play className="w-4 h-4 mr-1" />
              )}
              {a.label}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function SessionPage() {
  const params = useParams<{ id: string }>();
  const sessionId = params?.id;
  const [, setLocation] = useLocation();
  const { toast } = useToast();

  // Diagnostic: confirm SessionPage mounted with the right session id
  useEffect(() => {
    console.log(`[SessionPage] MOUNT params=${JSON.stringify(params)} sessionId=${sessionId || "(none)"}`);
    return () => console.log(`[SessionPage] UNMOUNT sessionId=${sessionId || "(none)"}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const {
    session,
    events,
    gate,
    status,
    currentPhase,
    completedPhases,
    loading,
    error,
    resume,
    cancel,
  } = useSession(sessionId);

  // Diagnostic: trace projected view state every time it changes
  useEffect(() => {
    console.log(
      `[SessionPage] VIEW session=${(sessionId || "?").slice(0, 8)} phase=${currentPhase} status=${status} events=${events.length} completed=[${completedPhases.join(",")}] gate=${gate?.gate_type || "none"} loading=${loading} error=${error || "—"}`
    );
  }, [sessionId, currentPhase, status, events.length, completedPhases, gate, loading, error]);

  const handleResume = async (action: string, payload: Record<string, any> = {}) => {
    if (!gate) return;
    const r = await resume(gate.gate_id, action, payload);
    if (r.success) {
      toast({ title: "Decision submitted", description: `Gate ${gate.gate_type} → ${action}` });
    } else {
      toast({ title: "Failed", description: r.error || "Resume failed", variant: "destructive" });
    }
  };

  const handleCancel = async () => {
    const r = await cancel("user_cancelled");
    if (r.success) {
      toast({ title: "Session cancelled" });
      setLocation("/sessions");
    } else {
      toast({ title: "Cancel failed", description: r.error, variant: "destructive" });
    }
  };

  if (!sessionId) {
    return (
      <div className="p-6">
        <Alert variant="destructive">
          <AlertDescription>No session id in URL.</AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4">
      {/* Sprint D: sticky "Now:" strip — hides on terminal status */}
      <LiveActivityTicker events={events} status={status} />

      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <button
          onClick={() => setLocation("/sessions")}
          className="hover:text-foreground transition-colors"
        >
          Sessions
        </button>
        <ArrowRight className="w-3 h-3" />
        <span className="font-mono">{sessionId.slice(0, 8)}</span>
      </div>

      <SessionHeader
        sessionId={sessionId}
        session={session}
        status={status}
        onCancel={handleCancel}
      />

      {loading && !session && (
        <Card>
          <CardContent className="p-8 flex items-center justify-center text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading session...
          </CardContent>
        </Card>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Sprint D: replaces the old flat SessionTimeline. Accordion per
          phase, expands to phase-specific template (compliance score,
          budget bars, vendor ranking, etc).
          Gate panels (approval / vendor / GRN) render INLINE inside the
          active accordion row via gateElement — no more separate block
          above that the user has to scroll up to find. */}
      <PhaseDetailAccordion
        events={events}
        completedPhases={completedPhases}
        currentPhase={currentPhase}
        status={status}
        gateElement={
          gate
            ? <SessionGate gate={gate} onResolve={handleResume} sessionId={sessionId} />
            : undefined
        }
      />

      {/* Sprint D: celebratory PO card — appears once po_creation is
          completed, and shows a Goods-Receipt CTA while delivery is
          pending. Returns null if no PO event has arrived yet. */}
      <POResultCard
        events={events}
        currentPhase={currentPhase}
        status={status}
        sessionId={sessionId}
      />

      {/* Event log (debug / audit) — kept as a thin raw view for support.
          The accordion above is the user-facing representation. */}
      {events.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Event Log ({events.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1 text-xs font-mono max-h-64 overflow-auto">
              {events.map((ev) => (
                <div key={ev.event_id} className="flex gap-2 py-1 border-b border-border/50 last:border-0">
                  <span className="text-muted-foreground">#{ev.sequence_number}</span>
                  <span className="text-blue-600 dark:text-blue-400">{ev.event_type}</span>
                  <span className="text-muted-foreground">
                    {ev.payload?.phase ? `(${ev.payload.phase})` : ""}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
