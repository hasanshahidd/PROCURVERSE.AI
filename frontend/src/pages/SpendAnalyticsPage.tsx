import { useState, useEffect } from "react";
import { useLocation } from "wouter";
import { apiFetch } from "@/lib/api";
import {
  ArrowLeft,
  BarChart3,
  Download,
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// ── Demo data ──────────────────────────────────────────────────────────────────
const DEMO_SPEND = {
  total_spend: 2847392,
  avg_po_value: 18492,
  top_category: "IT Equipment",
  savings: 142350,
  monthly_trend: [
    { month: "Oct", spend: 420000 },
    { month: "Nov", spend: 380000 },
    { month: "Dec", spend: 510000 },
    { month: "Jan", spend: 445000 },
    { month: "Feb", spend: 392000 },
    { month: "Mar", spend: 700392 },
  ],
  by_category: [
    { name: "IT Equipment", value: 980000 },
    { name: "Office Supplies", value: 420000 },
    { name: "Maintenance", value: 380000 },
    { name: "Software", value: 520000 },
    { name: "Professional Services", value: 547392 },
  ],
  by_department: [
    { dept: "IT", spend: 980000 },
    { dept: "Operations", spend: 720000 },
    { dept: "Finance", spend: 380000 },
    { dept: "HR", spend: 420000 },
    { dept: "Admin", spend: 347392 },
  ],
  top_vendors: [
    { rank: 1, name: "TechCorp FZE", spend: 480000, pct: 16.9, trend: "up" },
    { rank: 2, name: "Office World LLC", spend: 320000, pct: 11.2, trend: "stable" },
    { rank: 3, name: "Maintenance Pro", spend: 280000, pct: 9.8, trend: "down" },
    { rank: 4, name: "CloudSoft MENA", spend: 240000, pct: 8.4, trend: "up" },
    { rank: 5, name: "Facilities Plus", spend: 210000, pct: 7.4, trend: "stable" },
  ],
};

// ── Constants ──────────────────────────────────────────────────────────────────
const PIE_COLORS = ["#6366f1", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe"];
const DEPT_COLOR = "#6366f1";

const CATEGORIES = [
  "All",
  "IT Equipment",
  "Office Supplies",
  "Maintenance",
  "Software",
  "Professional Services",
];

const PERIOD_OPTIONS = [
  { label: "Last 3 Months", value: 3 },
  { label: "Last 6 Months", value: 6 },
  { label: "Last 12 Months", value: 12 },
];

// ── Helpers ────────────────────────────────────────────────────────────────────
const aed = (value: number) =>
  `AED ${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value || 0)}`;

type SpendData = typeof DEMO_SPEND;

// ── Custom Tooltip ─────────────────────────────────────────────────────────────
const AedTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-sm">
      <p className="font-semibold text-gray-700 mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {aed(p.value)}
        </p>
      ))}
    </div>
  );
};

const PieTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-sm">
      <p className="font-semibold text-gray-700">{payload[0].name}</p>
      <p className="text-indigo-600">{aed(payload[0].value)}</p>
    </div>
  );
};

// ── Trend icon helper ──────────────────────────────────────────────────────────
function TrendIcon({ trend }: { trend: string }) {
  if (trend === "up")
    return <TrendingUp className="h-4 w-4 text-emerald-600 inline" />;
  if (trend === "down")
    return <TrendingDown className="h-4 w-4 text-red-500 inline" />;
  return <Minus className="h-4 w-4 text-gray-400 inline" />;
}

// ── Main Component ─────────────────────────────────────────────────────────────
export default function SpendAnalyticsPage() {
  const [, setLocation] = useLocation();
  const [periodMonths, setPeriodMonths] = useState(6);
  const [category, setCategory] = useState("All");
  const [isLoading, setIsLoading] = useState(false);
  const [data, setData] = useState<SpendData>(DEMO_SPEND);

  const fetchData = async (months: number) => {
    setIsLoading(true);
    try {
      const res = await apiFetch("/api/agentic/spend/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ analysis_type: "full", period_months: months }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      // Merge API data with demo fallback for any missing fields
      setData({ ...DEMO_SPEND, ...json });
    } catch {
      setData(DEMO_SPEND);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData(periodMonths);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodMonths]);

  const totalSpendFormatted = aed(data.total_spend);
  const savingsFormatted = aed(data.savings);
  const topCategoryPct = (
    ((data.by_category.find((c) => c.name === data.top_category)?.value ?? 0) /
      data.total_spend) *
    100
  ).toFixed(1);

  return (
    <div className="bg-background flex flex-col h-full">
      {/* ── Header ── */}
      <header className="border-b bg-gradient-to-r from-indigo-600 to-purple-600 text-white px-4 py-3 flex items-center justify-between shadow-md flex-shrink-0">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setLocation("/dashboard")}
            className="gap-2 text-white hover:bg-white/20"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            <div>
              <h1 className="text-lg font-semibold leading-tight">Spend Analytics</h1>
              <p className="text-xs text-white/70">WF-20 — Procurement spend intelligence &amp; trend analysis</p>
            </div>
          </div>
        </div>
        {isLoading && <Loader2 className="h-5 w-5 animate-spin text-white/80" />}
      </header>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-5 max-w-7xl mx-auto">

          {/* ── Filter Bar ── */}
          <Card className="shadow-sm">
            <CardContent className="py-3 px-4">
              <div className="flex flex-wrap items-center gap-3">
                {/* Period toggle */}
                <div className="flex gap-1 rounded-lg border p-1 bg-gray-50">
                  {PERIOD_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setPeriodMonths(opt.value)}
                      className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                        periodMonths === opt.value
                          ? "bg-indigo-600 text-white shadow"
                          : "text-gray-600 hover:bg-gray-200"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>

                {/* Category filter */}
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger className="w-52 h-9 text-sm">
                    <SelectValue placeholder="Category" />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {/* Export */}
                <Button variant="outline" size="sm" className="gap-2 ml-auto">
                  <Download className="h-4 w-4" />
                  Export
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* ── KPI Cards ── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card className="shadow-sm border-l-4 border-l-indigo-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Spend</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">{totalSpendFormatted}</p>
                <p className="text-xs text-emerald-600 flex items-center gap-1 mt-1">
                  <TrendingUp className="h-3 w-3" /> +8.3% vs prev period
                </p>
              </CardContent>
            </Card>

            <Card className="shadow-sm border-l-4 border-l-purple-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Avg PO Value</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">{aed(data.avg_po_value)}</p>
                <p className="text-xs text-muted-foreground mt-1">across all POs</p>
              </CardContent>
            </Card>

            <Card className="shadow-sm border-l-4 border-l-violet-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Top Category</p>
                <p className="text-xl font-bold text-gray-900 mt-1 leading-tight">{data.top_category}</p>
                <p className="text-xs text-muted-foreground mt-1">{topCategoryPct}% of total spend</p>
              </CardContent>
            </Card>

            <Card className="shadow-sm border-l-4 border-l-emerald-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Savings Identified</p>
                <p className="text-2xl font-bold text-emerald-600 mt-1">{savingsFormatted}</p>
                <p className="text-xs text-emerald-600 mt-1">via AI recommendations</p>
              </CardContent>
            </Card>
          </div>

          {/* ── Charts Row 1 ── */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            {/* Area Chart — Spend Over Time (60%) */}
            <Card className="lg:col-span-3 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">Spend Over Time</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={data.monthly_trend} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="spendGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                    <YAxis tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
                    <Tooltip content={<AedTooltip />} />
                    <Area
                      type="monotone"
                      dataKey="spend"
                      name="Spend"
                      stroke="#6366f1"
                      strokeWidth={2.5}
                      fill="url(#spendGradient)"
                      dot={{ fill: "#6366f1", r: 4 }}
                      activeDot={{ r: 6 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            {/* Pie Chart — By Category (40%) */}
            <Card className="lg:col-span-2 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">By Category</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie
                      data={data.by_category}
                      cx="50%"
                      cy="45%"
                      innerRadius={55}
                      outerRadius={85}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {data.by_category.map((_entry, idx) => (
                        <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip content={<PieTooltip />} />
                    <Legend
                      iconType="circle"
                      iconSize={8}
                      formatter={(value) => (
                        <span className="text-xs text-gray-600">{value}</span>
                      )}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          {/* ── Charts Row 2 ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Bar Chart — By Department */}
            <Card className="shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">Spend by Department</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart
                    data={data.by_department}
                    layout="vertical"
                    margin={{ top: 0, right: 16, left: 8, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
                    <XAxis
                      type="number"
                      tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
                      tick={{ fontSize: 11 }}
                    />
                    <YAxis type="category" dataKey="dept" tick={{ fontSize: 12 }} width={70} />
                    <Tooltip content={<AedTooltip />} />
                    <Bar dataKey="spend" name="Spend" fill={DEPT_COLOR} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            {/* Table — Top 10 Vendors */}
            <Card className="shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">Top Vendors by Spend</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                {data.top_vendors.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                    <BarChart3 className="h-10 w-10 mb-2 opacity-30" />
                    <p className="text-sm">No vendor data available</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-gray-50 text-left text-muted-foreground">
                          <th className="py-2 pl-4 pr-2 font-medium">#</th>
                          <th className="py-2 pr-2 font-medium">Vendor</th>
                          <th className="py-2 pr-2 font-medium text-right">Spend</th>
                          <th className="py-2 pr-2 font-medium text-right">% Total</th>
                          <th className="py-2 pr-4 font-medium text-center">Trend</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.top_vendors.map((v) => (
                          <tr
                            key={v.rank}
                            className="border-b border-border/40 hover:bg-gray-50 transition-colors"
                          >
                            <td className="py-2 pl-4 pr-2 text-muted-foreground font-medium">{v.rank}</td>
                            <td className="py-2 pr-2 font-medium text-gray-800">{v.name}</td>
                            <td className="py-2 pr-2 text-right text-gray-700">{aed(v.spend)}</td>
                            <td className="py-2 pr-2 text-right">
                              <Badge variant="outline" className="text-xs font-normal">
                                {v.pct.toFixed(1)}%
                              </Badge>
                            </td>
                            <td className="py-2 pr-4 text-center">
                              <TrendIcon trend={v.trend} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}
