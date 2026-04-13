/**
 * Sprint D (2026-04-11) — ApprovalPanel
 *
 * Specialized gate panel for `gate.gate_type === "approval"`. Replaces
 * the generic JSON-drawer fallback that GenericGatePanel rendered for
 * approval gates before Sprint D.
 *
 * Contract:
 *   - Props: `gate: OpenGate`, `onResolve: (action, payload?) => Promise<void>`
 *   - Pure projection of `gate.decision_context`. No pipelineStore, no
 *     separate fetches.
 *   - Two terminal actions: `approve` and `reject`. Both are accepted
 *     by orchestrator._resume_p2p_workflow (see orchestrator.py:3055).
 *     Notes (optional) and reject reason (required) are passed through
 *     as payload fields.
 *
 * Backend dependency (Sprint A/B):
 *   backend/agents/orchestrator.py (~line 2340) packs the following into
 *   `decision_context` when opening the approval gate:
 *     {
 *       pr_summary: { pr_number, product_name, quantity, department,
 *                     requester, justification, total_amount, currency },
 *       line_items: [...],
 *       approver:   { name, email, role, level },
 *       approval_chain: [{ approver_name, approver_email, role|approver_role,
 *                          approval_level, approval_status, ... }],
 *       current_approver_role: "finance_manager",
 *       routing_action: "auto_route" | "manual_review" | ...,
 *       required_level: 2,
 *       amount:        12345.67,
 *       policy_band:   "auto_approve" | "manager" | "director" | "vp" | "cfo",
 *     }
 *
 *   If any field is missing (older gate rows, partial runs), the panel
 *   falls back to gate_ref.pr_number + the approver_emails array, so
 *   rendering never crashes.
 */

import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Crown,
  Mail,
  UserCircle2,
  FileText,
  DollarSign,
  Building2,
  Package,
  Clock,
  ShieldCheck,
  ExternalLink,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import type { OpenGate } from "@/hooks/useSession";

/* ================================================================ */
/*  Types                                                            */
/* ================================================================ */

interface PRSummary {
  pr_number?: string;
  product_name?: string;
  quantity?: number;
  department?: string;
  requester?: string;
  justification?: string;
  total_amount?: number;
  currency?: string;
}

interface LineItem {
  description?: string;
  product_name?: string;
  quantity?: number;
  unit_price?: number;
  total_price?: number;
  [k: string]: any;
}

interface ApproverEntry {
  approver_name?: string;
  approver_email?: string;
  role?: string;
  approver_role?: string;
  approval_level?: number | string;
  approval_status?: string;
  [k: string]: any;
}

interface ApprovalDecisionContext {
  pr_summary?: PRSummary;
  line_items?: LineItem[];
  approver?: {
    name?: string;
    email?: string;
    role?: string | null;
    level?: number | string;
  };
  approval_chain?: ApproverEntry[];
  current_approver_role?: string;
  routing_action?: string;
  required_level?: number;
  amount?: number;
  policy_band?: string;
  [k: string]: any;
}

interface ApprovalPanelProps {
  gate: OpenGate;
  onResolve: (action: string, payload?: Record<string, any>) => Promise<void>;
  sessionId?: string;
}

/* ================================================================ */
/*  Policy band → badge styling                                      */
/* ================================================================ */

const POLICY_BAND_META: Record<
  string,
  { label: string; className: string; description: string }
> = {
  auto_approve: {
    label: "Auto-Approve Band",
    className: "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/50",
    description: "Under policy threshold — routine approval",
  },
  manager: {
    label: "Manager Approval",
    className: "bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-800/50",
    description: "Requires manager sign-off",
  },
  director: {
    label: "Director Approval",
    className: "bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-950/40 dark:text-purple-300 dark:border-purple-800/50",
    description: "Requires director sign-off",
  },
  vp: {
    label: "VP Approval",
    className: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800/50",
    description: "Requires VP sign-off",
  },
  cfo: {
    label: "CFO Approval",
    className: "bg-red-100 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-800/50",
    description: "High-value — requires CFO sign-off",
  },
};

function fmtMoney(amount: number | undefined | null, currency: string = "USD"): string {
  if (amount == null || isNaN(Number(amount))) return "—";
  const n = Number(amount);
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return `$${n.toLocaleString()}`;
  }
}

/* ================================================================ */
/*  Sub-component: PR Summary card                                   */
/* ================================================================ */

function PRSummaryBlock({
  pr,
  gateRef,
  amountFallback,
}: {
  pr: PRSummary | undefined;
  gateRef: Record<string, any>;
  amountFallback: number | undefined;
}) {
  const prNumber = pr?.pr_number || gateRef.pr_number || "—";
  const product = pr?.product_name || "—";
  const qty = pr?.quantity ?? "—";
  const dept = pr?.department || "—";
  const requester = pr?.requester || "—";
  const justification = pr?.justification;
  const total =
    pr?.total_amount != null ? pr.total_amount : amountFallback != null ? amountFallback : null;
  const currency = pr?.currency || "USD";

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-900/30">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-slate-500" />
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">
            Purchase Request
          </span>
          <Badge variant="outline" className="text-xs font-mono">
            {prNumber}
          </Badge>
        </div>
        {total != null && (
          <div className="flex items-center gap-1 text-sm font-semibold text-slate-900 dark:text-slate-100">
            <DollarSign className="w-4 h-4 text-emerald-500" />
            {fmtMoney(total, currency)}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3 text-sm">
        <div>
          <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 mb-0.5">
            <Package className="w-3 h-3" /> Product
          </div>
          <div className="font-medium text-slate-900 dark:text-slate-100 truncate" title={product}>
            {product}
          </div>
        </div>
        <div>
          <div className="text-xs text-slate-500 dark:text-slate-400 mb-0.5">Quantity</div>
          <div className="font-medium text-slate-900 dark:text-slate-100">{qty}</div>
        </div>
        <div>
          <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 mb-0.5">
            <Building2 className="w-3 h-3" /> Department
          </div>
          <div className="font-medium text-slate-900 dark:text-slate-100 truncate" title={dept}>
            {dept}
          </div>
        </div>
        <div>
          <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 mb-0.5">
            <UserCircle2 className="w-3 h-3" /> Requester
          </div>
          <div className="font-medium text-slate-900 dark:text-slate-100 truncate" title={requester}>
            {requester}
          </div>
        </div>
      </div>

      {justification && (
        <div className="px-4 pb-3 -mt-1">
          <div className="text-xs text-slate-500 dark:text-slate-400 mb-0.5">Justification</div>
          <p className="text-sm text-slate-700 dark:text-slate-300 italic">
            "{justification}"
          </p>
        </div>
      )}
    </div>
  );
}

/* ================================================================ */
/*  Sub-component: Line items table                                  */
/* ================================================================ */

function LineItemsTable({ items, currency }: { items: LineItem[]; currency: string }) {
  if (!items || items.length === 0) return null;

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 bg-slate-50 dark:bg-slate-900/40 border-b border-slate-200 dark:border-slate-800">
        <Package className="w-4 h-4 text-slate-500" />
        <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">
          Line Items
        </span>
        <Badge variant="outline" className="text-xs ml-auto">
          {items.length} {items.length === 1 ? "item" : "items"}
        </Badge>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/50 dark:bg-slate-900/20 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
            <tr>
              <th className="text-left px-4 py-2 font-medium">Description</th>
              <th className="text-right px-4 py-2 font-medium">Qty</th>
              <th className="text-right px-4 py-2 font-medium">Unit Price</th>
              <th className="text-right px-4 py-2 font-medium">Total</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => {
              const desc = item.description || item.product_name || `Item ${idx + 1}`;
              const qty = item.quantity ?? 1;
              const unit = item.unit_price;
              const total = item.total_price ?? (unit != null ? Number(unit) * Number(qty) : null);
              return (
                <tr
                  key={idx}
                  className="border-t border-slate-200 dark:border-slate-800 hover:bg-slate-50/50 dark:hover:bg-slate-900/20"
                >
                  <td className="px-4 py-2 text-slate-800 dark:text-slate-200">{desc}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-slate-700 dark:text-slate-300">
                    {qty}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-slate-700 dark:text-slate-300">
                    {unit != null ? fmtMoney(Number(unit), currency) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums font-medium text-slate-900 dark:text-slate-100">
                    {total != null ? fmtMoney(Number(total), currency) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================================================================ */
/*  Sub-component: Approval chain stepper                            */
/* ================================================================ */

function ApprovalChainStepper({
  chain,
  currentRole,
}: {
  chain: ApproverEntry[];
  currentRole?: string;
}) {
  if (!chain || chain.length === 0) return null;

  // Sort by approval_level ascending so the stepper goes bottom-up authority
  const ordered = [...chain].sort((a, b) => {
    const la = Number(a.approval_level ?? 0);
    const lb = Number(b.approval_level ?? 0);
    return la - lb;
  });

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800">
      <div className="flex items-center gap-2 px-4 py-2 bg-slate-50 dark:bg-slate-900/40 border-b border-slate-200 dark:border-slate-800">
        <Crown className="w-4 h-4 text-amber-500" />
        <span className="text-sm font-semibold text-slate-800 dark:text-slate-200">
          Approval Chain
        </span>
        <Badge variant="outline" className="text-xs ml-auto">
          {ordered.length} {ordered.length === 1 ? "approver" : "approvers"}
        </Badge>
      </div>
      <div className="p-3 space-y-2">
        {ordered.map((a, idx) => {
          const name = a.approver_name || "Approver";
          const role = a.role || a.approver_role || "";
          const email = a.approver_email || "";
          const level = a.approval_level != null ? String(a.approval_level) : "—";
          const status = (a.approval_status || "").toLowerCase();
          const isCurrent = !!currentRole && role.toLowerCase() === currentRole.toLowerCase();
          const isApproved = status === "approved";
          const isRejected = status === "rejected";

          return (
            <div
              key={`${name}-${idx}`}
              className={`flex items-center gap-3 p-2.5 rounded-md border transition-colors ${
                isCurrent
                  ? "border-amber-400 bg-amber-50 dark:bg-amber-950/30 ring-1 ring-amber-300/60"
                  : isApproved
                  ? "border-emerald-200 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/20"
                  : isRejected
                  ? "border-red-200 bg-red-50/40 dark:border-red-900/40 dark:bg-red-950/20"
                  : "border-slate-200 dark:border-slate-800"
              }`}
            >
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${
                  isCurrent
                    ? "bg-amber-500 text-white"
                    : isApproved
                    ? "bg-emerald-500 text-white"
                    : isRejected
                    ? "bg-red-500 text-white"
                    : "bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                }`}
              >
                {isApproved ? (
                  <CheckCircle2 className="w-4 h-4" />
                ) : isRejected ? (
                  <AlertCircle className="w-4 h-4" />
                ) : (
                  `L${level}`
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm text-slate-900 dark:text-slate-100 truncate">
                    {name}
                  </span>
                  {isCurrent && (
                    <Badge className="text-[10px] bg-amber-500 hover:bg-amber-500 text-white gap-1">
                      <Clock className="w-2.5 h-2.5" />
                      pending you
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  {role && <span className="capitalize">{role.replace(/_/g, " ")}</span>}
                  {email && (
                    <span className="flex items-center gap-1 truncate">
                      <Mail className="w-3 h-3" />
                      {email}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ================================================================ */
/*  Main component                                                   */
/* ================================================================ */

export function ApprovalPanel({ gate, onResolve, sessionId }: ApprovalPanelProps) {
  const ctx = (gate.decision_context || {}) as ApprovalDecisionContext;
  const gateRef = gate.gate_ref || {};

  const pr = ctx.pr_summary;
  const lineItems = ctx.line_items || [];
  const chain = ctx.approval_chain || [];
  const currentApprover = ctx.approver;
  const policyBand = ctx.policy_band || "";
  const amount = ctx.amount;
  const currency = pr?.currency || "USD";

  const policyMeta = useMemo(
    () => POLICY_BAND_META[policyBand] || null,
    [policyBand]
  );

  const [submitting, setSubmitting] = useState(false);
  const [submittingAction, setSubmittingAction] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [rejectMode, setRejectMode] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(true);

  /* ── Role-based gate: only the matching approver can act ──────── */
  const [currentUserEmail, setCurrentUserEmail] = useState<string>("");
  useEffect(() => {
    const readUser = () => {
      try {
        const raw = localStorage.getItem("currentUser");
        if (raw) {
          const parsed = JSON.parse(raw);
          setCurrentUserEmail((parsed.email || "").toLowerCase().trim());
          return;
        }
      } catch { /* ignore */ }
      // Fallback to login email
      setCurrentUserEmail(
        (localStorage.getItem("userEmail") || "").toLowerCase().trim()
      );
    };
    readUser();
    // Listen for user-switcher changes from MainLayout
    window.addEventListener("userChanged", readUser);
    return () => window.removeEventListener("userChanged", readUser);
  }, []);

  // Collect ALL approver emails from the gate's approval chain
  const approverEmails = useMemo(() => {
    const emails = new Set<string>();
    // From the primary approver field
    if (currentApprover?.email)
      emails.add(currentApprover.email.toLowerCase().trim());
    // From the full approval chain
    chain.forEach((entry) => {
      const e = entry.approver_email;
      if (e) emails.add(e.toLowerCase().trim());
    });
    // From gate_ref fallback
    const refEmails = gateRef.approver_emails;
    if (Array.isArray(refEmails)) {
      refEmails.forEach((e: string) => {
        if (e) emails.add(e.toLowerCase().trim());
      });
    }
    return emails;
  }, [currentApprover, chain, gateRef]);

  const isCurrentUserApprover =
    currentUserEmail !== "" && approverEmails.size > 0
      ? approverEmails.has(currentUserEmail)
      : true; // If we can't determine, allow (backwards-compat)

  const handleApprove = async () => {
    setSubmitting(true);
    setSubmittingAction("approve");
    try {
      await onResolve("approve", notes.trim() ? { notes: notes.trim() } : {});
    } finally {
      setSubmitting(false);
      setSubmittingAction(null);
    }
  };

  const handleReject = async () => {
    if (!rejectReason.trim()) {
      setRejectMode(true);
      return;
    }
    setSubmitting(true);
    setSubmittingAction("reject");
    try {
      await onResolve("reject", { reason: rejectReason.trim() });
    } finally {
      setSubmitting(false);
      setSubmittingAction(null);
    }
  };

  const approverName = currentApprover?.name || "your manager";

  return (
    <Card className="border-amber-300 dark:border-amber-700 shadow-lg overflow-hidden">
      {/* Header */}
      <CardHeader className="bg-gradient-to-r from-amber-50 to-yellow-50 dark:from-amber-950/30 dark:to-yellow-950/20 border-b border-amber-200 dark:border-amber-900/40">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="relative mt-0.5">
              <div className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
              <div className="absolute inset-0 w-2 h-2 bg-amber-500 rounded-full animate-ping opacity-60" />
            </div>
            <div>
              <CardTitle className="text-lg flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                Approval Required
              </CardTitle>
              <p className="text-sm text-muted-foreground mt-1">
                Awaiting decision from{" "}
                <span className="font-semibold text-foreground">{approverName}</span>
                {currentApprover?.role && (
                  <span className="text-xs ml-1">
                    ({String(currentApprover.role).replace(/_/g, " ")})
                  </span>
                )}
              </p>
            </div>
          </div>
          {policyMeta && (
            <Badge
              variant="outline"
              className={`text-xs shrink-0 ${policyMeta.className}`}
              title={policyMeta.description}
            >
              {policyMeta.label}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4 pt-4">
        {/* PR summary */}
        <PRSummaryBlock pr={pr} gateRef={gateRef} amountFallback={amount} />

        {/* Collapsible details: line items + approval chain */}
        {(lineItems.length > 0 || chain.length > 0) && (
          <div>
            <button
              type="button"
              onClick={() => setDetailsOpen((v) => !v)}
              className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-slate-100 transition-colors"
            >
              {detailsOpen ? (
                <ChevronUp className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
              {detailsOpen ? "Hide details" : "Show details"}
            </button>
            {detailsOpen && (
              <div className="mt-3 space-y-3">
                {lineItems.length > 0 && (
                  <LineItemsTable items={lineItems} currency={currency} />
                )}
                {chain.length > 0 && (
                  <ApprovalChainStepper
                    chain={chain}
                    currentRole={ctx.current_approver_role}
                  />
                )}
              </div>
            )}
          </div>
        )}

        {/* Link to full approval lifecycle page */}
        {(pr?.pr_number || gateRef.pr_number) && (
          <a
            href={`/approval-workflows?pr=${encodeURIComponent(pr?.pr_number || gateRef.pr_number)}${sessionId ? `&session=${encodeURIComponent(sessionId)}` : ""}`}
            className="flex items-center gap-2 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 hover:underline transition-colors w-fit"
          >
            <ExternalLink className="w-4 h-4" />
            View full approval lifecycle
          </a>
        )}

        <Separator />

        {/* Notes / reject reason — only for the designated approver */}
        {!isCurrentUserApprover ? null : rejectMode ? (
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-800 dark:text-slate-200">
              Reason for rejection <span className="text-red-500">*</span>
            </label>
            <Textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Explain why this PR is being rejected so the requester can adjust it..."
              rows={3}
              className="resize-none"
            />
            <p className="text-xs text-muted-foreground">
              A rejection reason is required before submitting.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-800 dark:text-slate-200">
              Approval notes (optional)
            </label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add a note for audit trail (optional)..."
              rows={2}
              className="resize-none"
            />
          </div>
        )}

        {/* Action buttons — role-gated */}
        {isCurrentUserApprover ? (
          <div className="flex flex-wrap gap-2 pt-1">
            {!rejectMode ? (
              <>
                <Button
                  disabled={submitting}
                  onClick={handleApprove}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                  {submittingAction === "approve" ? (
                    <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                  ) : (
                    <CheckCircle2 className="w-4 h-4 mr-1.5" />
                  )}
                  Approve {amount != null ? fmtMoney(amount, currency) : "PR"}
                </Button>
                <Button
                  variant="destructive"
                  disabled={submitting}
                  onClick={() => setRejectMode(true)}
                >
                  <AlertCircle className="w-4 h-4 mr-1.5" />
                  Reject
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="destructive"
                  disabled={submitting || !rejectReason.trim()}
                  onClick={handleReject}
                >
                  {submittingAction === "reject" ? (
                    <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                  ) : (
                    <AlertCircle className="w-4 h-4 mr-1.5" />
                  )}
                  Confirm Rejection
                </Button>
                <Button
                  variant="outline"
                  disabled={submitting}
                  onClick={() => {
                    setRejectMode(false);
                    setRejectReason("");
                  }}
                >
                  Cancel
                </Button>
              </>
            )}
          </div>
        ) : (
          <div className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50/70 dark:bg-blue-950/30 p-3">
            <div className="flex items-start gap-2">
              <Info className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
                  Awaiting approver action
                </p>
                <p className="text-xs text-blue-600 dark:text-blue-400 mt-0.5">
                  This approval is assigned to{" "}
                  <span className="font-semibold">
                    {currentApprover?.name || chain[0]?.approver_name || "the designated approver"}
                  </span>
                  {(currentApprover?.email || chain[0]?.approver_email) && (
                    <> ({currentApprover?.email || chain[0]?.approver_email})</>
                  )}
                  . Switch to their role in the sidebar to approve or reject.
                </p>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
