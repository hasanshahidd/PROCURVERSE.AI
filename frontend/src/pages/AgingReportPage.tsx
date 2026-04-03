import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import { Clock, Loader2 } from "lucide-react";
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
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// Demo data fallback
const DEMO_AGING = {
  summary: {
    total_outstanding: 482000,
    total_overdue: 279000,
    dso_estimate: 42,
    invoice_count: 12,
  },
  buckets: {
    current: { count: 5, total: 125000 },
    "1_30_days": { count: 3, total: 78000 },
    "31_60_days": { count: 2, total: 45000 },
    "61_90_days": { count: 1, total: 78000 },
    over_90_days: { count: 1, total: 156000 },
  },
  vendor_aging: [
    { vendor: "Construction Co", total: 230000, oldest_days: 15, invoice_count: 4 },
    { vendor: "IT Solutions", total: 156000, oldest_days: 95, invoice_count: 2 },
    { vendor: "Industrial Parts", total: 78000, oldest_days: 72, invoice_count: 3 },
    { vendor: "Office World LLC", total: 12000, oldest_days: 28, invoice_count: 2 },
    { vendor: "Facilities Plus", total: 6000, oldest_days: 5, invoice_count: 1 },
  ],
};

const BUCKET_LABELS: Record<string, string> = {
  current: "Current",
  "1_30_days": "1-30 Days",
  "31_60_days": "31-60 Days",
  "61_90_days": "61-90 Days",
  over_90_days: "90+ Days",
};

const BUCKET_COLORS: Record<string, string> = {
  current: "#22c55e",
  "1_30_days": "#eab308",
  "31_60_days": "#f97316",
  "61_90_days": "#ef4444",
  over_90_days: "#991b1b",
};

function formatCurrency(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "AED",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

export default function AgingReportPage() {
  const [data, setData] = useState(DEMO_AGING);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchAging();
  }, []);

  async function fetchAging() {
    setLoading(true);
    try {
      const res = await apiFetch("/api/agentic/reports/aging");
      if (res.ok) {
        const json = await res.json();
        if (json.buckets) {
          setData({
            summary: json.summary || DEMO_AGING.summary,
            buckets: json.buckets || DEMO_AGING.buckets,
            vendor_aging: json.vendor_aging || DEMO_AGING.vendor_aging,
          });
        }
      }
    } catch {
      // Use demo data
    } finally {
      setLoading(false);
    }
  }

  // Prepare chart data
  const chartData = Object.entries(data.buckets).map(([key, bucket]) => ({
    name: BUCKET_LABELS[key] || key,
    count: bucket.count,
    total: bucket.total,
    fill: BUCKET_COLORS[key] || "#6366f1",
  }));

  const { summary } = data;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-orange-100">
          <Clock className="h-6 w-6 text-orange-700" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">AP Aging Report</h1>
          <p className="text-muted-foreground">
            Accounts payable aging analysis
          </p>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">
              Total Outstanding
            </div>
            <div className="text-2xl font-bold">
              {formatCurrency(summary.total_outstanding)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">Total Overdue</div>
            <div className="text-2xl font-bold text-red-600">
              {formatCurrency(summary.total_overdue)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">DSO Estimate</div>
            <div className="text-2xl font-bold">{summary.dso_estimate} days</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">Invoice Count</div>
            <div className="text-2xl font-bold">{summary.invoice_count}</div>
          </CardContent>
        </Card>
      </div>

      {/* Aging Bucket Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Aging Buckets</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  tickFormatter={(v: number) =>
                    `${(v / 1000).toFixed(0)}K`
                  }
                />
                <YAxis type="category" dataKey="name" width={100} />
                <Tooltip
                  formatter={(value: number, name: string) => [
                    name === "total"
                      ? formatCurrency(value)
                      : value,
                    name === "total" ? "Amount" : "Count",
                  ]}
                />
                <Legend />
                <Bar
                  dataKey="total"
                  name="Amount"
                  radius={[0, 4, 4, 0]}
                >
                  {chartData.map((entry, index) => (
                    <rect key={index} fill={entry.fill} />
                  ))}
                </Bar>
                <Bar dataKey="count" name="Invoices" fill="#93c5fd" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Bucket summary cards */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-4">
            {chartData.map((bucket) => (
              <div
                key={bucket.name}
                className="rounded-lg border p-3 text-center"
                style={{ borderColor: bucket.fill }}
              >
                <div className="text-xs text-muted-foreground">
                  {bucket.name}
                </div>
                <div className="font-bold">{formatCurrency(bucket.total)}</div>
                <div className="text-xs text-muted-foreground">
                  {bucket.count} invoices
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Vendor Aging Table */}
      <Card>
        <CardHeader>
          <CardTitle>Vendor Aging Detail</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Vendor</TableHead>
                  <TableHead className="text-right">
                    Outstanding Amount
                  </TableHead>
                  <TableHead className="text-right">
                    Oldest Invoice (days)
                  </TableHead>
                  <TableHead className="text-right">Invoice Count</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.vendor_aging
                  .sort((a, b) => b.total - a.total)
                  .map((v) => (
                    <TableRow key={v.vendor}>
                      <TableCell className="font-medium">{v.vendor}</TableCell>
                      <TableCell className="text-right">
                        {formatCurrency(v.total)}
                      </TableCell>
                      <TableCell className="text-right">
                        <span
                          className={
                            v.oldest_days > 90
                              ? "text-red-600 font-semibold"
                              : v.oldest_days > 60
                              ? "text-orange-600"
                              : ""
                          }
                        >
                          {v.oldest_days}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        {v.invoice_count}
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
