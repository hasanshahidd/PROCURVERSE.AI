import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { DollarSign, Loader2, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  const [payments, setPayments] = useState(DEMO_PAYMENTS);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Form state
  const [vendor, setVendor] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("AED");
  const [method, setMethod] = useState("bank_transfer");
  const [reference, setReference] = useState("");

  useEffect(() => {
    fetchPayments();
  }, []);

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
