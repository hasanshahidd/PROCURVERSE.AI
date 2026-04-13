/**
 * SessionsListPage — "My Sessions" view for Layer 3 session-driven UI.
 *
 * Lists all execution sessions owned by the current user with status filters.
 * Each row links to /sessions/:id which renders the full SessionPage view.
 *
 * The list itself is a plain REST fetch (no SSE) — it's an index, not a live
 * projection. Individual session pages stream their own event log.
 */
import { useMemo, useState } from "react";
import { useLocation } from "wouter";
import { useQuery } from "@tanstack/react-query";
import {
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock,
  Pause,
  XCircle,
  ArrowRight,
  Inbox,
  Package,
  DollarSign,
  User,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { BASE_URL } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Types (mirror the backend SessionMaster shape)
// ─────────────────────────────────────────────────────────────────────────────

interface SessionRow {
  session_id: string;
  session_kind: string;
  initiated_by_user_id: string;
  current_phase: string;
  current_status: "running" | "paused_human" | "completed" | "failed" | "cancelled";
  workflow_run_id?: string | null;
  request_summary: Record<string, any>;
  last_event_sequence: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  open_gates?: Array<{
    gate_id: string;
    gate_type: string;
    status: "pending" | "resolved" | "expired";
  }>;
}

type FilterKey = "all" | "running" | "paused_human" | "completed" | "failed";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("authToken") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function statusBadge(status: SessionRow["current_status"]) {
  const map: Record<
    string,
    { label: string; icon: typeof Loader2; className: string }
  > = {
    running: { label: "Running", icon: Loader2, className: "bg-blue-600 hover:bg-blue-700 text-white" },
    paused_human: { label: "Waiting on You", icon: Pause, className: "bg-amber-500 hover:bg-amber-600 text-white" },
    completed: { label: "Completed", icon: CheckCircle2, className: "bg-emerald-600 hover:bg-emerald-700 text-white" },
    failed: { label: "Failed", icon: XCircle, className: "bg-red-600 hover:bg-red-700 text-white" },
    cancelled: { label: "Cancelled", icon: XCircle, className: "bg-muted text-muted-foreground" },
  };
  const cfg = map[status] || { label: status, icon: Clock, className: "" };
  const Icon = cfg.icon;
  return (
    <Badge className={cfg.className}>
      <Icon className={`w-3 h-3 mr-1 ${status === "running" ? "animate-spin" : ""}`} />
      {cfg.label}
    </Badge>
  );
}

function relativeTime(iso: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const diff = Math.max(0, Date.now() - t);
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function phaseLabel(phase: string): string {
  const map: Record<string, string> = {
    starting: "Starting",
    compliance: "Compliance",
    budget: "Budget",
    vendor: "Vendor Ranking",
    vendor_selection: "Vendor Selection",
    pr_creation: "PR Created",
    approval: "Approval Routing",
    approval_wait: "Awaiting Approval",
    po_creation: "PO Creation",
    delivery_tracking: "Delivery",
    grn: "Goods Receipt",
    grn_wait: "Awaiting GRN",
    quality_inspection: "Quality Check",
    invoice_matching: "Invoice Match",
    three_way_match: "3-Way Match",
    payment_readiness: "Payment Ready",
    payment_execution: "Payment",
    completed: "Completed",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  return map[phase] || phase;
}

// ─────────────────────────────────────────────────────────────────────────────
// Filter tab bar
// ─────────────────────────────────────────────────────────────────────────────

function FilterTabs({
  active,
  counts,
  onChange,
}: {
  active: FilterKey;
  counts: Record<FilterKey, number>;
  onChange: (k: FilterKey) => void;
}) {
  const tabs: { key: FilterKey; label: string }[] = [
    { key: "all", label: "All" },
    { key: "running", label: "Running" },
    { key: "paused_human", label: "Waiting on You" },
    { key: "completed", label: "Completed" },
    { key: "failed", label: "Failed" },
  ];
  return (
    <div className="flex flex-wrap gap-2">
      {tabs.map((t) => {
        const isActive = active === t.key;
        const n = counts[t.key] ?? 0;
        return (
          <Button
            key={t.key}
            size="sm"
            variant={isActive ? "default" : "outline"}
            onClick={() => onChange(t.key)}
          >
            {t.label}
            <span
              className={`ml-2 px-1.5 py-0.5 rounded text-xs ${
                isActive
                  ? "bg-primary-foreground/20 text-primary-foreground"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {n}
            </span>
          </Button>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Row card
// ─────────────────────────────────────────────────────────────────────────────

function SessionCard({
  row,
  onOpen,
}: {
  row: SessionRow;
  onOpen: (id: string) => void;
}) {
  const summary = (row.request_summary || {}) as any;
  const prData = summary.pr_data || {};
  const pendingGate = (row.open_gates || []).find((g) => g.status === "pending");

  return (
    <Card
      className="cursor-pointer hover-elevate transition-shadow"
      onClick={() => onOpen(row.session_id)}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <span className="font-mono text-sm text-muted-foreground">
                {row.session_id.slice(0, 8)}
              </span>
              {statusBadge(row.current_status)}
              {pendingGate && (
                <Badge variant="outline" className="border-amber-500 text-amber-700 dark:text-amber-400">
                  Gate: {pendingGate.gate_type}
                </Badge>
              )}
            </div>

            {summary.request && (
              <p className="text-sm mb-2 line-clamp-1" title={summary.request}>
                "{summary.request}"
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <div className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                Phase: <span className="font-medium text-foreground">{phaseLabel(row.current_phase)}</span>
              </div>
              {prData.product_name && (
                <div className="flex items-center gap-1">
                  <Package className="w-3 h-3" />
                  {prData.product_name}
                </div>
              )}
              {prData.department && (
                <div className="flex items-center gap-1">
                  <User className="w-3 h-3" />
                  {prData.department}
                </div>
              )}
              {prData.budget != null && (
                <div className="flex items-center gap-1">
                  <DollarSign className="w-3 h-3" />
                  {Number(prData.budget).toLocaleString()}
                </div>
              )}
              <div className="ml-auto">{relativeTime(row.created_at)}</div>
            </div>
          </div>

          <ArrowRight className="w-4 h-4 text-muted-foreground shrink-0 mt-1" />
        </div>
      </CardContent>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function SessionsListPage() {
  const [, setLocation] = useLocation();
  const [filter, setFilter] = useState<FilterKey>("all");

  const { data, isLoading, error, refetch } = useQuery<SessionRow[]>({
    queryKey: ["sessions", "list"],
    queryFn: async () => {
      const res = await fetch(`${BASE_URL}/api/sessions`, {
        headers: { ...authHeaders() },
        credentials: "include",
      });
      if (!res.ok) {
        throw new Error(`Failed to load sessions (${res.status})`);
      }
      const body = await res.json();
      // Backend may return {sessions: [...]} or a raw list — accept both.
      if (Array.isArray(body)) return body as SessionRow[];
      if (Array.isArray(body?.sessions)) return body.sessions as SessionRow[];
      return [] as SessionRow[];
    },
    refetchInterval: 15_000,
  });

  const sessions = data ?? [];

  const counts = useMemo<Record<FilterKey, number>>(() => {
    const c: Record<FilterKey, number> = {
      all: sessions.length,
      running: 0,
      paused_human: 0,
      completed: 0,
      failed: 0,
    };
    for (const s of sessions) {
      if (s.current_status === "running") c.running += 1;
      else if (s.current_status === "paused_human") c.paused_human += 1;
      else if (s.current_status === "completed") c.completed += 1;
      else if (s.current_status === "failed") c.failed += 1;
    }
    return c;
  }, [sessions]);

  const filtered = useMemo(() => {
    if (filter === "all") return sessions;
    return sessions.filter((s) => s.current_status === filter);
  }, [sessions, filter]);

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold">My Sessions</h1>
          <p className="text-sm text-muted-foreground">
            Active and historical P2P workflows you initiated.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          Refresh
        </Button>
      </div>

      <FilterTabs active={filter} counts={counts} onChange={setFilter} />

      {isLoading && (
        <Card>
          <CardContent className="p-8 flex items-center justify-center text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading sessions...
          </CardContent>
        </Card>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{String((error as Error).message || error)}</AlertDescription>
        </Alert>
      )}

      {!isLoading && !error && filtered.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Inbox className="w-4 h-4" />
              No sessions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              {filter === "all"
                ? "You haven't initiated any P2P workflows yet. Start one from the chat."
                : `No sessions in "${filter}" state.`}
            </p>
            {filter === "all" && (
              <Button className="mt-3" size="sm" onClick={() => setLocation("/chat")}>
                Go to chat
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      <div className="flex flex-col gap-2">
        {filtered.map((row) => (
          <SessionCard
            key={row.session_id}
            row={row}
            onOpen={(id) => setLocation(`/sessions/${id}`)}
          />
        ))}
      </div>
    </div>
  );
}
