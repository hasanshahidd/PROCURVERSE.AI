/**
 * Sprint D (2026-04-11) — POResultCard
 *
 * Celebratory card rendered below the phase accordion ONCE the session
 * has emitted a `phase_completed` event for `po_creation`. Pure projection
 * of `events` — no pipelineStore, no follow-up ERP fetch.
 *
 * Contract:
 *   - Props: `events: SessionEvent[]`, `currentPhase: string`, `status: string`.
 *   - Returns null unless a `phase_completed(po_creation)` event exists.
 *   - Reads ALL data from the event payload (po_number, vendor_name,
 *     line_items, total, currency, expected_delivery_date, etc).
 *   - When `currentPhase === "delivery_tracking"`, shows a "next action"
 *     banner pointing to Goods Receipt confirmation.
 *
 * Backend dependency (Sprint C):
 *   backend/agents/orchestrator.py (~line 2414) packs this payload when
 *   emitting `phase_completed(po_creation)` — outbox-safe, small JSON:
 *     {
 *       phase: "po_creation",
 *       ref: { po_number, pr_number },
 *       po_number:     "PO-...",
 *       pr_number:     "PR-...",
 *       vendor_name:   "Brown & Sons",
 *       vendor_id:     "v123",
 *       department:    "IT",
 *       line_items:    [{ description, qty, unit_price, total }],
 *       total:         12345.67,
 *       currency:      "USD",
 *       expected_delivery_date: "2026-04-25" | null,
 *     }
 *
 *   Both emission sites (first-pass and post_approval resume) emit
 *   identical shapes. If fields are missing (older runs), the card
 *   falls back to "—" placeholders instead of crashing.
 */

import { useMemo } from "react";
import {
  CheckCircle2,
  Truck,
  Package,
  Building2,
  Calendar,
  DollarSign,
  ArrowRight,
  FileCheck2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { SessionEvent } from "@/hooks/useSession";
import { useLocation } from "wouter";

/* ================================================================ */
/*  Types                                                            */
/* ================================================================ */

interface POLineItem {
  description?: string;
  product_name?: string;
  qty?: number;
  quantity?: number;
  unit_price?: number;
  total?: number;
  total_price?: number;
  [k: string]: any;
}

interface POPayload {
  phase?: string;
  po_number?: string;
  pr_number?: string;
  vendor_name?: string;
  vendor_id?: string;
  department?: string;
  line_items?: POLineItem[];
  total?: number;
  currency?: string;
  expected_delivery_date?: string | null;
  [k: string]: any;
}

interface POResultCardProps {
  events: SessionEvent[];
  currentPhase: string;
  status: string;
  sessionId?: string;
}

/* ================================================================ */
/*  Helpers                                                          */
/* ================================================================ */

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

function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function daysFromNow(iso: string | null | undefined): number | null {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    const now = new Date();
    const ms = d.getTime() - now.getTime();
    return Math.round(ms / (1000 * 60 * 60 * 24));
  } catch {
    return null;
  }
}

/* ================================================================ */
/*  Component                                                        */
/* ================================================================ */

export function POResultCard({
  events,
  currentPhase,
  status,
  sessionId,
}: POResultCardProps) {
  const [, setLocation] = useLocation();

  // Find the LATEST phase_completed(po_creation) event.
  // Scan from the end; soft transitions (R20) may produce multiple copies,
  // the most recent is the truth.
  const poPayload = useMemo<POPayload | null>(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const ev = events[i];
      if (
        ev.event_type === "phase_completed" &&
        ev.payload?.phase === "po_creation"
      ) {
        return ev.payload as POPayload;
      }
    }
    return null;
  }, [events]);

  // Check if a PO notification email was actually sent to vendor
  const emailSentToVendor = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const ev = events[i];
      if (
        ev.event_type === "tool_called" &&
        ev.payload?.tool === "email" &&
        ev.payload?.action === "send_po_notification" &&
        ev.payload?.success === true
      ) {
        return ev.payload.vendor_email as string | undefined;
      }
    }
    return null;
  }, [events]);

  if (!poPayload) return null;

  const poNumber = poPayload.po_number || poPayload.ref?.po_number || "—";
  const prNumber = poPayload.pr_number || poPayload.ref?.pr_number || "—";
  const vendor = poPayload.vendor_name || "—";
  const department = poPayload.department || "—";
  const currency = poPayload.currency || "USD";
  const total = poPayload.total;
  const lineItems = poPayload.line_items || [];
  const eta = poPayload.expected_delivery_date || null;
  const etaFmt = fmtDate(eta);
  const etaDays = daysFromNow(eta);

  // Delivery-tracking banner: the session has shipped a PO and is waiting
  // for the user to confirm goods received.
  const showDeliveryCTA =
    currentPhase === "delivery_tracking" &&
    (status === "running" || status === "paused_human");

  const handleOpenGRN = () => {
    if (sessionId) {
      setLocation(`/goods-receipt?session=${sessionId}`);
    } else {
      setLocation("/goods-receipt");
    }
  };

  return (
    <Card className="border-emerald-300 dark:border-emerald-800/60 shadow-md overflow-hidden">
      <CardHeader className="bg-gradient-to-r from-emerald-50 to-green-50 dark:from-emerald-950/30 dark:to-green-950/20 border-b border-emerald-200 dark:border-emerald-900/40">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-emerald-500/15 p-2 border border-emerald-400/30">
              <FileCheck2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            </div>
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                Purchase Order Created
                {emailSentToVendor ? (
                  <Badge className="bg-emerald-500 hover:bg-emerald-500 text-white gap-1 text-[10px]">
                    <CheckCircle2 className="w-3 h-3" />
                    sent to vendor
                  </Badge>
                ) : (
                  <Badge className="bg-blue-500 hover:bg-blue-500 text-white gap-1 text-[10px]">
                    <CheckCircle2 className="w-3 h-3" />
                    created
                  </Badge>
                )}
              </CardTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                PO{" "}
                <span className="font-mono font-semibold text-foreground">
                  {poNumber}
                </span>{" "}
                linked to PR{" "}
                <span className="font-mono font-semibold text-foreground">
                  {prNumber}
                </span>
              </p>
            </div>
          </div>
          {total != null && (
            <div className="text-right shrink-0">
              <div className="text-xs text-muted-foreground">Total value</div>
              <div className="text-lg font-bold text-emerald-700 dark:text-emerald-400 tabular-nums flex items-center gap-1 justify-end">
                <DollarSign className="w-4 h-4" />
                {fmtMoney(total, currency)}
              </div>
            </div>
          )}
        </div>
      </CardHeader>

      <CardContent className="pt-4 space-y-3">
        {/* Metadata row */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          <div className="rounded-md border border-slate-200 dark:border-slate-800 p-2.5">
            <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 mb-0.5">
              <Building2 className="w-3 h-3" /> Vendor
            </div>
            <div className="font-medium text-slate-900 dark:text-slate-100 truncate" title={vendor}>
              {vendor}
            </div>
          </div>
          <div className="rounded-md border border-slate-200 dark:border-slate-800 p-2.5">
            <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 mb-0.5">
              <Package className="w-3 h-3" /> Department
            </div>
            <div className="font-medium text-slate-900 dark:text-slate-100 truncate" title={department}>
              {department}
            </div>
          </div>
          <div className="rounded-md border border-slate-200 dark:border-slate-800 p-2.5">
            <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 mb-0.5">
              <Calendar className="w-3 h-3" /> Expected delivery
            </div>
            <div className="font-medium text-slate-900 dark:text-slate-100">
              {etaFmt || "—"}
              {etaDays != null && (
                <span className="text-xs text-muted-foreground ml-1">
                  {etaDays > 0
                    ? `in ${etaDays}d`
                    : etaDays === 0
                    ? "today"
                    : `${Math.abs(etaDays)}d ago`}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Line items */}
        {lineItems.length > 0 && (
          <div className="rounded-md border border-slate-200 dark:border-slate-800 overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-50/70 dark:bg-slate-900/40 border-b border-slate-200 dark:border-slate-800">
              <Package className="w-3.5 h-3.5 text-slate-500" />
              <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wide">
                Line Items
              </span>
              <Badge variant="outline" className="text-[10px] ml-auto">
                {lineItems.length}
              </Badge>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-slate-800">
              {lineItems.map((item, idx) => {
                const desc = item.description || item.product_name || `Item ${idx + 1}`;
                const qty = item.qty ?? item.quantity ?? 1;
                const unit = item.unit_price;
                const lineTotal = item.total ?? item.total_price ??
                  (unit != null ? Number(unit) * Number(qty) : null);
                return (
                  <div
                    key={idx}
                    className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-slate-900 dark:text-slate-100 truncate">
                        {desc}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 tabular-nums">
                        {qty} × {unit != null ? fmtMoney(Number(unit), currency) : "—"}
                      </div>
                    </div>
                    <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 tabular-nums shrink-0">
                      {lineTotal != null ? fmtMoney(Number(lineTotal), currency) : "—"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Delivery CTA — only while waiting on physical goods */}
        {showDeliveryCTA && (
          <div className="rounded-lg border border-blue-200 dark:border-blue-900/40 bg-gradient-to-r from-blue-50 to-indigo-50/50 dark:from-blue-950/30 dark:to-indigo-950/20 p-3">
            <div className="flex items-start gap-3">
              <div className="rounded-full bg-blue-500/15 p-1.5 border border-blue-400/30 shrink-0">
                <Truck className="w-4 h-4 text-blue-600 dark:text-blue-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  Awaiting physical delivery
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Vendor has been notified. When the goods arrive, confirm receipt
                  to continue the workflow.
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="shrink-0 border-blue-400 text-blue-700 dark:text-blue-300 hover:bg-blue-500/10"
                onClick={handleOpenGRN}
              >
                Goods Receipt
                <ArrowRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
