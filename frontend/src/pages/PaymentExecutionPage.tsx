import { useState, useEffect, useMemo } from "react";
import { useLocation } from "wouter";
import { apiFetch } from "@/lib/api";
import { DollarSign, Loader2, FileText, Workflow, ArrowRight, AlertCircle, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSession } from "@/hooks/useSession";

// Read ?session=:id from URL — if present, this page enters session-observer mode
function readSessionIdFromUrl(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const params = new URLSearchParams(window.location.search);
  const sid = params.get("session");
  return sid && sid.trim() ? sid.trim() : undefined;
}

// Demo data fallback
const DEMO_PAYMENTS = [
  {
    execution_id: "PAY-2026-001",
    vendor: "TechCorp FZE",
    amount: 45000,
    currency: "AED",
    method: "bank_transfer",
    status: "dispatched",
    date: "2026-03-28",
  },
  {
    execution_id: "PAY-2026-002",
    vendor: "Office World LLC",
    amount: 12500,
    currency: "USD",
    method: "ach",
    status: "pending",
    date: "2026-03-29",
  },
  {
    execution_id: "PAY-2026-003",
    vendor: "CloudSoft MENA",
    amount: 8200,
    currency: "EUR",
    method: "bank_transfer",
    status: "dispatched",
    date: "2026-03-30",
  },
  {
    execution_id: "PAY-2026-004",
    vendor: "Maintenance Pro",
    amount: 3400,
    currency: "GBP",
    method: "check",
    status: "failed",
    date: "2026-03-31",
  },
  {
    execution_id: "PAY-2026-005",
    vendor: "Facilities Plus",
    amount: 67000,
    currency: "AED",
    method: "bank_transfer",
    status: "submitted",
    date: "2026-04-01",
  },
];

const STATUS_STYLES: Record<string, string> = {
  dispatched: "bg-green-100 text-green-800 border-green-300",
  pending: "bg-yellow-100 text-yellow-800 border-yellow-300",
  failed: "bg-red-100 text-red-800 border-red-300",
  submitted: "bg-blue-100 text-blue-800 border-blue-300",
};

function formatCurrency(amount: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

export default function PaymentExecutionPage() {
  const [, setLocation] = useLocation();
  const sessionId = useMemo(() => readSessionIdFromUrl(), []);
  const {
    session,
    gate,
    status: sessionStatus,
    currentPhase,
    loading: sessionLoading,
    resume,
  } = useSession(sessionId);
  const inSessionMode = !!sessionId;

  // Future-ready: when HF-3 extracts payment_release into a dedicated gate,
  // this branch will render the actual release UI. Until then, the page is
  // observer-only when mounted with ?session=:id.
  const paymentGate =
    inSessionMode && gate?.gate_type === "payment_release" ? gate : null;
  const inPaymentPhase =
    inSessionMode &&
    (currentPhase === "payment_readiness" ||
      currentPhase === "payment_execution" ||
      currentPhase === "completed");
  const summary = (session?.request_summary as Record<string, any>) || {};
  const sessionPrData = (summary.pr_data as Record<string, any>) || {};

  const [payments, setPayments] = useState(DEMO_PAYMENTS);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [releasing, setReleasing] = useState(false);

  // Form state
  const [vendor, setVendor] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("AED");
  const [method, setMethod] = useState("bank_transfer");
  const [reference, setReference] = useState("");

  useEffect(() => {
    fetchPayments();
  }, []);

  async function handleReleasePayment() {
    if (!paymentGate) return;
    setReleasing(true);
    try {
      const result = await resume(paymentGate.gate_id, "release_payment", {
        released_by: "Finance (UI)",
        notes: "Payment released from Payment Execution page",
      });
      if (!result.success) {
        alert(`Failed to release payment: ${result.error}`);
      }
    } finally {
      setReleasing(false);
    }
  }

  async function fetchPayments() {
    setLoading(true);
    try {
      const res = await apiFetch("/api/agentic/payment/history");
      if (res.ok) {
        const data = await res.json();
        if (data.payments && data.payments.length > 0) {
          setPayments(data.payments);
        }
      }
    } catch {
      // Use demo data
    } finally {
      setLoading(false);
    }
  }

  async function handleExecutePayment(e: React.FormEvent) {
    e.preventDefault();
    if (!vendor || !amount) return;
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/agentic/payment/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vendor,
          amount: parseFloat(amount),
          currency,
          method,
          reference,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.payment) {
          setPayments((prev) => [data.payment, ...prev]);
        }
      }
      // Reset form
      setVendor("");
      setAmount("");
      setReference("");
    } catch {
      // silent
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRemittance(id: string) {
    try {
      const res = await apiFetch(`/api/agentic/payment/remittance/${id}`);
      if (res.ok) {
        const data = await res.json();
        // Open remittance data - could be a download or display
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        window.open(url, "_blank");
      }
    } catch {
      // silent
    }
  }

  // Stats
  const totalPayments = payments.length;
  const pendingCount = payments.filter((p) => p.status === "pending").length;
  const dispatchedCount = payments.filter(
    (p) => p.status === "dispatched"
  ).length;
  const totalAmount = payments.reduce((sum, p) => sum + p.amount, 0);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-green-100">
          <DollarSign className="h-6 w-6 text-green-700" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Payment Execution</h1>
          <p className="text-muted-foreground">
            Execute and track vendor payments
          </p>
        </div>
      </div>

      {/* Session-observer banner — shown when ?session=:id is in URL */}
      {inSessionMode && (
        <Card className="border-2 border-blue-500/40 bg-blue-50 dark:bg-blue-950/20">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="flex items-start gap-3 flex-1 min-w-0">
                <div className="rounded-full bg-blue-600 p-2 shrink-0">
                  <Workflow className="h-5 w-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <CardTitle className="text-base flex items-center gap-2 flex-wrap">
                    P2P Workflow — Payment Phase
                    {sessionLoading ? (
                      <Badge variant="outline">
                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                        Loading…
                      </Badge>
                    ) : (
                      <>
                        <Badge className="bg-blue-600">{currentPhase}</Badge>
                        <Badge
                          variant="outline"
                          className={
                            sessionStatus === "completed"
                              ? "bg-green-50 text-green-700 border-green-300"
                              : sessionStatus === "failed"
                              ? "bg-red-50 text-red-700 border-red-300"
                              : "bg-blue-50 text-blue-700 border-blue-300"
                          }
                        >
                          {sessionStatus}
                        </Badge>
                      </>
                    )}
                  </CardTitle>
                  <CardDescription className="text-xs font-mono mt-1 truncate">
                    Session {sessionId}
                  </CardDescription>
                  {(summary.request as string) && (
                    <CardDescription className="text-sm mt-1">
                      {summary.request as string}
                    </CardDescription>
                  )}
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setLocation(`/sessions/${sessionId}`)}
              >
                Open Session View
                <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* PR / vendor / amount snapshot from session */}
            {Object.keys(sessionPrData).length > 0 && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs bg-white dark:bg-slate-900 rounded-md p-3 border">
                <div>
                  <div className="text-muted-foreground">Department</div>
                  <div className="font-medium">{sessionPrData.department || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Item</div>
                  <div className="font-medium truncate">
                    {sessionPrData.product_name || "—"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Quantity</div>
                  <div className="font-medium">{sessionPrData.quantity || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Amount</div>
                  <div className="font-medium">
                    {sessionPrData.budget
                      ? `$${Number(sessionPrData.budget).toLocaleString()}`
                      : "—"}
                  </div>
                </div>
              </div>
            )}

            {/* Active payment_release gate (post-HF-3 future) */}
            {paymentGate && (
              <div className="rounded-md border-2 border-blue-600 bg-blue-100/50 dark:bg-blue-900/20 p-3">
                <div className="flex items-center gap-2 mb-2">
                  <AlertCircle className="h-4 w-4 text-blue-700" />
                  <div className="text-sm font-semibold">
                    Awaiting payment release
                  </div>
                </div>
                <Button
                  size="sm"
                  className="bg-blue-600 hover:bg-blue-700 text-white"
                  disabled={releasing}
                  onClick={handleReleasePayment}
                >
                  {releasing ? (
                    <Loader2 className="h-3 w-3 animate-spin mr-1" />
                  ) : (
                    <DollarSign className="h-3 w-3 mr-1" />
                  )}
                  Release Payment
                </Button>
              </div>
            )}

            {/* Phase status — observer mode (no gate yet for payment_readiness/execution) */}
            {!paymentGate && inPaymentPhase && (
              <div className="rounded-md bg-white dark:bg-slate-900 border p-3 text-sm flex items-start gap-2">
                {sessionStatus === "completed" ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5 shrink-0" />
                    <div>
                      Payment phase complete. The session is fully settled —
                      see the timeline in the Session View for the full audit
                      log.
                    </div>
                  </>
                ) : (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin text-blue-600 mt-0.5 shrink-0" />
                    <div>
                      Session is in <strong>{currentPhase}</strong>. The
                      orchestrator is processing payment readiness checks
                      automatically — the live timeline is available in the
                      Session View.
                    </div>
                  </>
                )}
              </div>
            )}

            {!paymentGate && !inPaymentPhase && !sessionLoading && (
              <div className="rounded-md bg-white dark:bg-slate-900 border p-3 text-xs text-muted-foreground">
                This session is in <strong>{currentPhase}</strong> — not yet at
                the payment phase. Open the Session View to see the active
                step.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">Total Payments</div>
            <div className="text-2xl font-bold">{totalPayments}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">Pending</div>
            <div className="text-2xl font-bold text-yellow-600">
              {pendingCount}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">Dispatched</div>
            <div className="text-2xl font-bold text-green-600">
              {dispatchedCount}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">Total Amount</div>
            <div className="text-2xl font-bold">
              {formatCurrency(totalAmount, "AED")}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Execute Payment Form */}
      <Card>
        <CardHeader>
          <CardTitle>Execute Payment</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleExecutePayment} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="vendor">Vendor Name</Label>
                <Input
                  id="vendor"
                  placeholder="Enter vendor name"
                  value={vendor}
                  onChange={(e) => setVendor(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="amount">Amount</Label>
                <Input
                  id="amount"
                  type="number"
                  placeholder="0.00"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  required
                  min="0"
                  step="0.01"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="currency">Currency</Label>
                <Select value={currency} onValueChange={setCurrency}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="AED">AED</SelectItem>
                    <SelectItem value="USD">USD</SelectItem>
                    <SelectItem value="EUR">EUR</SelectItem>
                    <SelectItem value="GBP">GBP</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="method">Payment Method</Label>
                <Select value={method} onValueChange={setMethod}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bank_transfer">Bank Transfer</SelectItem>
                    <SelectItem value="check">Check</SelectItem>
                    <SelectItem value="ach">ACH</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="reference">Reference</Label>
                <Input
                  id="reference"
                  placeholder="Payment reference"
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                />
              </div>
              <div className="flex items-end">
                <Button type="submit" disabled={submitting} className="w-full">
                  {submitting ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : (
                    <DollarSign className="h-4 w-4 mr-2" />
                  )}
                  Execute Payment
                </Button>
              </div>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Payment History Table */}
      <Card>
        <CardHeader>
          <CardTitle>Payment History</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Execution ID</TableHead>
                    <TableHead>Vendor</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead>Currency</TableHead>
                    <TableHead>Method</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {payments.map((payment) => (
                    <TableRow key={payment.execution_id}>
                      <TableCell className="font-mono text-sm">
                        {payment.execution_id}
                      </TableCell>
                      <TableCell className="font-medium">
                        {payment.vendor}
                      </TableCell>
                      <TableCell className="text-right">
                        {payment.amount.toLocaleString()}
                      </TableCell>
                      <TableCell>{payment.currency}</TableCell>
                      <TableCell className="capitalize">
                        {payment.method.replace("_", " ")}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={
                            STATUS_STYLES[payment.status] || ""
                          }
                        >
                          {payment.status}
                        </Badge>
                      </TableCell>
                      <TableCell>{payment.date}</TableCell>
                      <TableCell>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            handleRemittance(payment.execution_id)
                          }
                        >
                          <FileText className="h-3 w-3 mr-1" />
                          Remittance
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
