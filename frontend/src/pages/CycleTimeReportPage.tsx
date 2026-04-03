import { Timer } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

// All demo data - analytics only
const PHASES = [
  { name: "PR to Approval", avg_days: 1.5, target: 2 },
  { name: "Approval to PO", avg_days: 0.5, target: 1 },
  { name: "PO to Invoice", avg_days: 12, target: 15 },
  { name: "Invoice Matching", avg_days: 1, target: 2 },
  { name: "Discrepancy Resolution", avg_days: 3, target: 5 },
  { name: "Payment Approval", avg_days: 2, target: 3 },
  { name: "Payment Execution", avg_days: 1, target: 2 },
];

const MONTHLY_TREND = [
  { month: "Nov", days: 28 },
  { month: "Dec", days: 25 },
  { month: "Jan", days: 23 },
  { month: "Feb", days: 22 },
  { month: "Mar", days: 21 },
  { month: "Apr", days: 20 },
];

const RECENT_TRANSACTIONS = [
  {
    id: "PO-2026-0142",
    vendor: "TechCorp FZE",
    pr_to_po: 1.8,
    po_to_invoice: 10,
    invoice_to_payment: 5,
    total: 16.8,
  },
  {
    id: "PO-2026-0139",
    vendor: "Office World LLC",
    pr_to_po: 2.5,
    po_to_invoice: 14,
    invoice_to_payment: 6,
    total: 22.5,
  },
  {
    id: "PO-2026-0135",
    vendor: "CloudSoft MENA",
    pr_to_po: 1.2,
    po_to_invoice: 8,
    invoice_to_payment: 4,
    total: 13.2,
  },
  {
    id: "PO-2026-0131",
    vendor: "Maintenance Pro",
    pr_to_po: 3.0,
    po_to_invoice: 18,
    invoice_to_payment: 8,
    total: 29.0,
  },
  {
    id: "PO-2026-0128",
    vendor: "Facilities Plus",
    pr_to_po: 2.0,
    po_to_invoice: 12,
    invoice_to_payment: 7,
    total: 21.0,
  },
];

const TOTAL_AVG = 21;
const TOTAL_TARGET = 30;

// Summary cards derived from phases
const avgPrToPo = PHASES.slice(0, 2).reduce((s, p) => s + p.avg_days, 0);
const avgPoToInvoice = PHASES[2].avg_days;
const avgInvoiceToPayment = PHASES.slice(3).reduce(
  (s, p) => s + p.avg_days,
  0
);

export default function CycleTimeReportPage() {
  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-purple-100">
          <Timer className="h-6 w-6 text-purple-700" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">P2P Cycle Times</h1>
          <p className="text-muted-foreground">
            Procure-to-pay cycle time analytics
          </p>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">
              Avg PR-to-PO
            </div>
            <div className="text-2xl font-bold">{avgPrToPo} days</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">
              Avg PO-to-Invoice
            </div>
            <div className="text-2xl font-bold">{avgPoToInvoice} days</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">
              Avg Invoice-to-Payment
            </div>
            <div className="text-2xl font-bold">{avgInvoiceToPayment} days</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">
              Total P2P Cycle
            </div>
            <div className="text-2xl font-bold text-green-600">
              {TOTAL_AVG} days
            </div>
            <div className="text-xs text-muted-foreground">
              Target: {TOTAL_TARGET} days
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Phase Duration Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Phase Durations (Actual vs Target)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={PHASES} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" unit=" days" />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={160}
                  tick={{ fontSize: 12 }}
                />
                <Tooltip
                  formatter={(value: number, name: string) => [
                    `${value} days`,
                    name === "avg_days" ? "Actual" : "Target",
                  ]}
                />
                <Legend />
                <Bar
                  dataKey="avg_days"
                  name="Actual"
                  fill="#6366f1"
                  radius={[0, 4, 4, 0]}
                />
                <Bar
                  dataKey="target"
                  name="Target"
                  fill="#e2e8f0"
                  radius={[0, 4, 4, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Monthly Trend */}
      <Card>
        <CardHeader>
          <CardTitle>Monthly Cycle Time Trend</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={MONTHLY_TREND}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" />
                <YAxis unit=" days" />
                <Tooltip
                  formatter={(value: number) => [`${value} days`, "Cycle Time"]}
                />
                <Legend />
                <ReferenceLine
                  y={TOTAL_TARGET}
                  stroke="#ef4444"
                  strokeDasharray="5 5"
                  label={{ value: "Target", position: "right", fill: "#ef4444" }}
                />
                <Line
                  type="monotone"
                  dataKey="days"
                  name="Avg Cycle Time"
                  stroke="#6366f1"
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Recent Transactions Table */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Transaction Cycle Times</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>PO Number</TableHead>
                  <TableHead>Vendor</TableHead>
                  <TableHead className="text-right">PR-to-PO (days)</TableHead>
                  <TableHead className="text-right">
                    PO-to-Invoice (days)
                  </TableHead>
                  <TableHead className="text-right">
                    Invoice-to-Payment (days)
                  </TableHead>
                  <TableHead className="text-right">Total (days)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {RECENT_TRANSACTIONS.map((txn) => (
                  <TableRow key={txn.id}>
                    <TableCell className="font-mono text-sm">
                      {txn.id}
                    </TableCell>
                    <TableCell className="font-medium">{txn.vendor}</TableCell>
                    <TableCell className="text-right">{txn.pr_to_po}</TableCell>
                    <TableCell className="text-right">
                      {txn.po_to_invoice}
                    </TableCell>
                    <TableCell className="text-right">
                      {txn.invoice_to_payment}
                    </TableCell>
                    <TableCell className="text-right">
                      <span
                        className={
                          txn.total > TOTAL_TARGET
                            ? "text-red-600 font-semibold"
                            : txn.total <= TOTAL_AVG
                            ? "text-green-600 font-semibold"
                            : ""
                        }
                      >
                        {txn.total}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
