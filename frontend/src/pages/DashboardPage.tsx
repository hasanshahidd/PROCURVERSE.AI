import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import {
  ArrowLeft, RefreshCcw, TrendingUp, TrendingDown, DollarSign, Package,
  Users, Activity, CheckCircle, Clock, FileText, ShieldCheck, Zap,
  BarChart2, AlertTriangle, Bot
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Progress } from "@/components/ui/progress";
import { apiRequest } from "@/lib/queryClient";
import {
  BarChart, Bar, PieChart, Pie, LineChart, Line, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Area, AreaChart, Defs, LinearGradient, Stop
} from "recharts";

// ─── Types ──────────────────────────────────────────────────────────────────
type BudgetRow = {
  department: string;
  budget_category: string;
  allocated_budget: number;
  spent_budget: number;
  committed_budget: number;
  available_budget: number;
  spent_percent: number;
  committed_percent: number;
  available_percent: number;
};

type ActionRow = {
  agent_name: string;
  action_type: string;
  success: boolean;
  execution_time_ms?: number;
  created_at: string;
};

type DashboardPayload = {
  success: boolean;
  fiscal_year: number;
  system_stats: {
    odoo?: { purchase_orders: number; vendors: number; products: number };
    agentic_tables?: { approval_chains: number; budget_tracking: number; agent_actions: number; agent_decisions: number };
    budget_summary?: { total_allocated: number; total_spent: number; total_committed: number; total_available: number };
    error?: string;
  };
  budget_rows: BudgetRow[];
  department_summary: Array<{ department: string; allocated: number; spent: number; committed: number; available: number }>;
  recent_actions: ActionRow[];
  workflow_stats?: { total: number; pending: number; completed: number; rejected: number; pos_created: number };
  agent_breakdown?: Array<{ agent_name: string; total: number; successes: number; avg_ms: number }>;
};

// ─── Helpers ────────────────────────────────────────────────────────────────
const currency = (v: number) =>
  new Intl.NumberFormat("en-AE", { style: "currency", currency: "AED", maximumFractionDigits: 0 }).format(v || 0);

const pct = (v: number) => `${(v || 0).toFixed(1)}%`;

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// Demo monthly spend data (used when API doesn't return monthly breakdown)
const DEMO_MONTHLY = [
  { month: "Oct", spend: 420000, pos: 38 },
  { month: "Nov", spend: 510000, pos: 44 },
  { month: "Dec", spend: 380000, pos: 31 },
  { month: "Jan", spend: 620000, pos: 52 },
  { month: "Feb", spend: 590000, pos: 49 },
  { month: "Mar", spend: 740000, pos: 61 },
];

const CHART_COLORS = {
  blue:   "#2563eb",
  purple: "#7c3aed",
  green:  "#059669",
  amber:  "#d97706",
  red:    "#dc2626",
  sky:    "#0ea5e9",
  indigo: "#4f46e5",
};

const PIE_COLORS = [CHART_COLORS.red, CHART_COLORS.amber, CHART_COLORS.green];

// ─── Custom Tooltip ──────────────────────────────────────────────────────────
const CustomBarTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-100 rounded-xl shadow-xl p-3 text-xs">
      <p className="font-semibold text-gray-700 mb-2">{label}</p>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full inline-block" style={{ background: p.color }} />
          <span className="text-gray-500">{p.name}:</span>
          <span className="font-medium">{currency(p.value)}</span>
        </div>
      ))}
    </div>
  );
};

// ─── Skeleton ────────────────────────────────────────────────────────────────
function SkeletonCard() {
  return (
    <Card className="rounded-2xl animate-pulse">
      <CardContent className="pt-6 space-y-3">
        <div className="h-4 bg-gray-200 rounded w-2/3" />
        <div className="h-8 bg-gray-200 rounded w-1/2" />
        <div className="h-3 bg-gray-200 rounded w-full" />
      </CardContent>
    </Card>
  );
}

// ─── KPI Card ────────────────────────────────────────────────────────────────
type KpiProps = {
  title: string;
  value: string;
  subtitle: string;
  icon: React.ReactNode;
  iconBg: string;
  trend?: { value: string; up: boolean };
  badge?: { label: string; color: string };
};

function KpiCard({ title, value, subtitle, icon, iconBg, trend, badge }: KpiProps) {
  return (
    <Card className="rounded-2xl shadow-sm hover:shadow-md transition-shadow border-0 bg-white overflow-hidden">
      <CardContent className="pt-5 pb-4 px-5">
        <div className="flex items-start justify-between mb-3">
          <div className={`w-11 h-11 rounded-xl flex items-center justify-center ${iconBg}`}>
            {icon}
          </div>
          {trend && (
            <span className={`flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full ${
              trend.up ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
            }`}>
              {trend.up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {trend.value}
            </span>
          )}
          {badge && (
            <span className={`text-xs font-semibold px-2 py-1 rounded-full ${badge.color}`}>
              {badge.label}
            </span>
          )}
        </div>
        <p className="text-2xl font-bold text-gray-900 tracking-tight">{value}</p>
        <p className="text-sm font-medium text-gray-500 mt-0.5">{title}</p>
        <p className="text-xs text-gray-400 mt-1">{subtitle}</p>
      </CardContent>
    </Card>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────
async function fetchDashboard(): Promise<DashboardPayload> {
  const res = await apiRequest("GET", "/api/agentic/dashboard/data");
  return res.json();
}

export default function DashboardPage() {
  const [, setLocation] = useLocation();
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(t);
  }, []);

  const { data, isLoading, error, refetch, isFetching, dataUpdatedAt } = useQuery<DashboardPayload>({
    queryKey: ["/api/agentic/dashboard/data"],
    queryFn: fetchDashboard,
    refetchInterval: 30000,
    retry: 1,
  });

  const stats  = data?.system_stats;
  const budget = stats?.budget_summary;

  const departmentChartData = data?.department_summary?.map(r => ({
    name: r.department.replace("Department", "Dept."),
    Spent: r.spent,
    Committed: r.committed,
    Available: r.available,
  })) || [];

  const budgetPieData = [
    { name: "Spent",     value: budget?.total_spent     || 0, color: CHART_COLORS.red   },
    { name: "Committed", value: budget?.total_committed || 0, color: CHART_COLORS.amber },
    { name: "Available", value: budget?.total_available || 0, color: CHART_COLORS.green },
  ].filter(d => d.value > 0);

  const totalPOs     = stats?.odoo?.purchase_orders ?? 0;
  const totalVendors = stats?.odoo?.vendors ?? 0;
  const pendingCount = data?.workflow_stats?.pending ?? 0;
  const spentPct     = budget?.total_allocated
    ? (budget.total_spent / budget.total_allocated) * 100
    : 0;

  const formattedDate = now.toLocaleDateString("en-AE", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  const updatedLabel  = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : "—";
  const userName      = localStorage.getItem("userName") || "User";

  return (
    <div className="bg-gray-50 flex flex-col min-h-screen">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header
        className="flex-shrink-0 px-6 py-4 flex items-center justify-between shadow-lg"
        style={{ background: "linear-gradient(135deg, hsl(221,83%,25%) 0%, hsl(221,83%,15%) 100%)" }}
      >
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setLocation("/chat")}
            className="gap-2 text-white hover:bg-white/20 rounded-xl"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight">
              Procurement Intelligence Dashboard
            </h1>
            <p className="text-blue-200 text-xs mt-0.5">{formattedDate}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right hidden sm:block">
            <p className="text-white text-sm font-medium">Welcome, {userName}</p>
            <p className="text-blue-200 text-xs">Last updated {updatedLabel}</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-2 bg-white/10 border-white/30 text-white hover:bg-white/20 rounded-xl"
          >
            <RefreshCcw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </header>

      <ScrollArea className="flex-1">
        <div className="p-6 space-y-6 max-w-7xl mx-auto">

          {/* Error state */}
          {error && (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 flex items-center gap-3">
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              Failed to load dashboard data. Ensure backend is running and VITE_API_URL is configured.
            </div>
          )}

          {/* ── KPI Row ──────────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {isLoading ? (
              Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)
            ) : (
              <>
                <KpiCard
                  title="Purchase Orders"
                  value={totalPOs.toLocaleString()}
                  subtitle="Total in Odoo system"
                  iconBg="bg-blue-100"
                  icon={<FileText className="h-5 w-5 text-blue-600" />}
                  trend={{ value: "+12%", up: true }}
                />
                <KpiCard
                  title="Total Spend YTD"
                  value={currency(budget?.total_spent || 0)}
                  subtitle={`${pct(spentPct)} of ${currency(budget?.total_allocated || 0)} budget`}
                  iconBg="bg-purple-100"
                  icon={<DollarSign className="h-5 w-5 text-purple-600" />}
                  trend={{ value: pct(spentPct), up: spentPct < 80 }}
                />
                <KpiCard
                  title="Pending Approvals"
                  value={pendingCount.toString()}
                  subtitle="Workflows awaiting sign-off"
                  iconBg="bg-amber-100"
                  icon={<Clock className="h-5 w-5 text-amber-600" />}
                  badge={pendingCount > 0
                    ? { label: `${pendingCount} urgent`, color: "bg-amber-100 text-amber-700" }
                    : { label: "All clear", color: "bg-green-100 text-green-700" }
                  }
                />
                <KpiCard
                  title="Active Vendors"
                  value={totalVendors.toLocaleString()}
                  subtitle="Registered in system"
                  iconBg="bg-green-100"
                  icon={<Users className="h-5 w-5 text-green-600" />}
                  trend={{ value: "+3 this month", up: true }}
                />
              </>
            )}
          </div>

          {/* ── Charts Row 1 ─────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {/* Bar Chart */}
            <Card className="rounded-2xl shadow-sm border-0 bg-white overflow-hidden">
              <CardHeader className="px-6 pt-5 pb-4">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base font-bold text-gray-900">Spend by Department</CardTitle>
                    <p className="text-xs text-gray-400 mt-0.5">Budget vs actual vs committed</p>
                  </div>
                  <span className="text-xs text-gray-400 bg-gray-100 px-2 py-1 rounded-lg">FY {data?.fiscal_year || 2026}</span>
                </div>
              </CardHeader>
              <CardContent className="px-2 pb-4">
                {isLoading ? (
                  <div className="h-[280px] flex items-center justify-center">
                    <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
                  </div>
                ) : departmentChartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={departmentChartData} barGap={4}>
                      <defs>
                        <linearGradient id="gradSpent" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={CHART_COLORS.blue} />
                          <stop offset="100%" stopColor="#1e40af" />
                        </linearGradient>
                        <linearGradient id="gradCommitted" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={CHART_COLORS.amber} />
                          <stop offset="100%" stopColor="#b45309" />
                        </linearGradient>
                        <linearGradient id="gradAvailable" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={CHART_COLORS.green} />
                          <stop offset="100%" stopColor="#047857" />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#6b7280" }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 11, fill: "#6b7280" }} axisLine={false} tickLine={false} tickFormatter={(v) => `${(v/1000).toFixed(0)}k`} />
                      <Tooltip content={<CustomBarTooltip />} />
                      <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                      <Bar dataKey="Spent"     fill="url(#gradSpent)"     radius={[4,4,0,0]} />
                      <Bar dataKey="Committed" fill="url(#gradCommitted)" radius={[4,4,0,0]} />
                      <Bar dataKey="Available" fill="url(#gradAvailable)" radius={[4,4,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={DEMO_MONTHLY} barGap={4}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#6b7280" }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 11, fill: "#6b7280" }} axisLine={false} tickLine={false} tickFormatter={(v) => `${(v/1000).toFixed(0)}k`} />
                      <Tooltip content={<CustomBarTooltip />} />
                      <Bar dataKey="spend" name="Spend" fill={CHART_COLORS.blue} radius={[4,4,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            {/* Donut Pie Chart */}
            <Card className="rounded-2xl shadow-sm border-0 bg-white overflow-hidden">
              <CardHeader className="px-6 pt-5 pb-4">
                <div>
                  <CardTitle className="text-base font-bold text-gray-900">Budget Distribution</CardTitle>
                  <p className="text-xs text-gray-400 mt-0.5">Spent · Committed · Available</p>
                </div>
              </CardHeader>
              <CardContent className="pb-4">
                {isLoading ? (
                  <div className="h-[280px] flex items-center justify-center">
                    <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
                  </div>
                ) : (
                  <div className="flex items-center gap-4">
                    <ResponsiveContainer width="60%" height={280}>
                      <PieChart>
                        <Pie
                          data={budgetPieData.length > 0 ? budgetPieData : [
                            { name: "Spent", value: 55, color: CHART_COLORS.red },
                            { name: "Committed", value: 20, color: CHART_COLORS.amber },
                            { name: "Available", value: 25, color: CHART_COLORS.green },
                          ]}
                          cx="50%" cy="50%"
                          innerRadius={70} outerRadius={110}
                          paddingAngle={4}
                          dataKey="value"
                        >
                          {(budgetPieData.length > 0 ? budgetPieData : [
                            { name: "Spent", color: CHART_COLORS.red },
                            { name: "Committed", color: CHART_COLORS.amber },
                            { name: "Available", color: CHART_COLORS.green },
                          ]).map((entry, i) => (
                            <Cell key={i} fill={entry.color} strokeWidth={0} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(v) => currency(Number(v))} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="flex-1 space-y-3">
                      {[
                        { label: "Spent",     value: budget?.total_spent,     color: CHART_COLORS.red,   pctVal: spentPct },
                        { label: "Committed", value: budget?.total_committed, color: CHART_COLORS.amber, pctVal: budget?.total_allocated ? (budget.total_committed / budget.total_allocated) * 100 : 0 },
                        { label: "Available", value: budget?.total_available, color: CHART_COLORS.green, pctVal: budget?.total_allocated ? (budget.total_available / budget.total_allocated) * 100 : 0 },
                      ].map(item => (
                        <div key={item.label}>
                          <div className="flex items-center justify-between mb-1">
                            <div className="flex items-center gap-2">
                              <span className="w-2.5 h-2.5 rounded-full inline-block flex-shrink-0" style={{ background: item.color }} />
                              <span className="text-xs text-gray-600 font-medium">{item.label}</span>
                            </div>
                            <span className="text-xs font-semibold text-gray-700">{pct(item.pctVal)}</span>
                          </div>
                          <Progress value={item.pctVal} className="h-1.5" />
                          <p className="text-xs text-gray-400 mt-0.5">{currency(item.value || 0)}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* ── Charts Row 2: Line + Budget Bars ─────────────────────────── */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {/* PO Volume Line Chart */}
            <Card className="rounded-2xl shadow-sm border-0 bg-white overflow-hidden">
              <CardHeader className="px-6 pt-5 pb-4">
                <CardTitle className="text-base font-bold text-gray-900">PO Volume Trend</CardTitle>
                <p className="text-xs text-gray-400 mt-0.5">Monthly purchase order activity</p>
              </CardHeader>
              <CardContent className="px-2 pb-4">
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={DEMO_MONTHLY}>
                    <defs>
                      <linearGradient id="gradArea" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor={CHART_COLORS.blue} stopOpacity={0.15} />
                        <stop offset="95%" stopColor={CHART_COLORS.blue} stopOpacity={0.01} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#6b7280" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: "#6b7280" }} axisLine={false} tickLine={false} />
                    <Tooltip />
                    <Area type="monotone" dataKey="pos" name="POs" stroke={CHART_COLORS.blue} strokeWidth={2.5} fill="url(#gradArea)" dot={{ r: 4, fill: CHART_COLORS.blue, strokeWidth: 0 }} activeDot={{ r: 6 }} />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            {/* Budget Utilization Horizontal Bars */}
            <Card className="rounded-2xl shadow-sm border-0 bg-white overflow-hidden">
              <CardHeader className="px-6 pt-5 pb-4">
                <CardTitle className="text-base font-bold text-gray-900">Budget Utilization</CardTitle>
                <p className="text-xs text-gray-400 mt-0.5">Spend rate per department</p>
              </CardHeader>
              <CardContent className="px-6 pb-5">
                {isLoading ? (
                  <div className="space-y-4">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="animate-pulse space-y-1">
                        <div className="h-3 bg-gray-200 rounded w-1/3" />
                        <div className="h-2 bg-gray-200 rounded" />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="space-y-5 mt-1">
                    {(data?.department_summary || []).slice(0, 6).map(dept => {
                      const usedPct = dept.allocated > 0 ? Math.min((dept.spent / dept.allocated) * 100, 100) : 0;
                      const color = usedPct >= 90 ? "bg-red-500" : usedPct >= 70 ? "bg-amber-500" : "bg-blue-500";
                      return (
                        <div key={dept.department}>
                          <div className="flex items-center justify-between mb-1.5">
                            <span className="text-sm font-medium text-gray-700 truncate max-w-[160px]">{dept.department}</span>
                            <div className="flex items-center gap-2">
                              <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                                usedPct >= 90 ? "text-red-700 bg-red-100" :
                                usedPct >= 70 ? "text-amber-700 bg-amber-100" :
                                "text-blue-700 bg-blue-100"
                              }`}>{pct(usedPct)}</span>
                            </div>
                          </div>
                          <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all duration-700 ${color}`}
                              style={{ width: `${usedPct}%` }}
                            />
                          </div>
                          <p className="text-xs text-gray-400 mt-1">{currency(dept.spent)} of {currency(dept.allocated)}</p>
                        </div>
                      );
                    })}
                    {!data?.department_summary?.length && (
                      [
                        { label: "Operations", pct: 78 },
                        { label: "Finance", pct: 62 },
                        { label: "IT", pct: 91 },
                        { label: "HR", pct: 45 },
                      ].map(d => (
                        <div key={d.label}>
                          <div className="flex items-center justify-between mb-1.5">
                            <span className="text-sm font-medium text-gray-700">{d.label}</span>
                            <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${d.pct >= 90 ? "text-red-700 bg-red-100" : d.pct >= 70 ? "text-amber-700 bg-amber-100" : "text-blue-700 bg-blue-100"}`}>{d.pct}%</span>
                          </div>
                          <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
                            <div className={`h-full rounded-full ${d.pct >= 90 ? "bg-red-500" : d.pct >= 70 ? "bg-amber-500" : "bg-blue-500"}`} style={{ width: `${d.pct}%` }} />
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* ── Workflow Stats Row ────────────────────────────────────────── */}
          {data?.workflow_stats && (
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
              {[
                { label: "Total Workflows", value: data.workflow_stats.total,     icon: <BarChart2 className="h-5 w-5 text-indigo-600" />, bg: "bg-indigo-50",  color: "text-indigo-600" },
                { label: "In Progress",     value: data.workflow_stats.pending,   icon: <Clock className="h-5 w-5 text-amber-600" />,   bg: "bg-amber-50",   color: "text-amber-600"  },
                { label: "Completed",       value: data.workflow_stats.completed, icon: <CheckCircle className="h-5 w-5 text-green-600" />, bg: "bg-green-50", color: "text-green-600" },
                { label: "Rejected",        value: data.workflow_stats.rejected,  icon: <TrendingDown className="h-5 w-5 text-red-600" />, bg: "bg-red-50",   color: "text-red-600"   },
                { label: "POs Created",     value: data.workflow_stats.pos_created, icon: <ShieldCheck className="h-5 w-5 text-blue-600" />, bg: "bg-blue-50", color: "text-blue-600"  },
              ].map(item => (
                <Card key={item.label} className="rounded-2xl shadow-sm hover:shadow-md transition-shadow border-0 bg-white">
                  <CardContent className="pt-5 px-5 pb-4">
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${item.bg} mb-3`}>
                      {item.icon}
                    </div>
                    <p className={`text-2xl font-bold ${item.color}`}>{item.value}</p>
                    <p className="text-xs text-gray-500 mt-1">{item.label}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* ── System Metrics Row ───────────────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
            {[
              { label: "Purchase Orders", value: stats?.odoo?.purchase_orders, icon: <Package className="h-6 w-6 text-blue-600" />,   bg: "from-blue-50"   },
              { label: "Vendors",         value: stats?.odoo?.vendors,          icon: <Users className="h-6 w-6 text-green-600" />,   bg: "from-green-50"  },
              { label: "Products",        value: stats?.odoo?.products,         icon: <Package className="h-6 w-6 text-purple-600" />, bg: "from-purple-50" },
              { label: "Approval Chains", value: stats?.agentic_tables?.approval_chains, icon: <Activity className="h-6 w-6 text-orange-600" />, bg: "from-orange-50" },
              { label: "Agent Actions",   value: stats?.agentic_tables?.agent_actions,   icon: <Bot className="h-6 w-6 text-red-600" />,    bg: "from-red-50"    },
              { label: "Agent Decisions", value: stats?.agentic_tables?.agent_decisions, icon: <Zap className="h-6 w-6 text-indigo-600" />, bg: "from-indigo-50" },
            ].map(item => (
              <Card key={item.label} className={`rounded-2xl shadow-sm hover:shadow-md transition-shadow border-0 bg-gradient-to-br ${item.bg} to-white`}>
                <CardContent className="pt-5 pb-4 text-center">
                  <div className="flex justify-center mb-2">{item.icon}</div>
                  <p className="text-2xl font-bold text-gray-900">{item.value ?? "—"}</p>
                  <p className="text-xs text-gray-500 mt-1">{item.label}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* ── Agent Performance + Recent Actions ───────────────────────── */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">

            {/* Agent Performance */}
            {data?.agent_breakdown && data.agent_breakdown.length > 0 && (
              <Card className="rounded-2xl shadow-sm border-0 bg-white overflow-hidden">
                <CardHeader className="px-6 pt-5 pb-4 border-b border-gray-50">
                  <CardTitle className="text-base font-bold text-gray-900 flex items-center gap-2">
                    <Bot className="h-5 w-5 text-indigo-600" />
                    Agent Performance
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-50 bg-gray-50/50">
                          <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Agent</th>
                          <th className="px-3 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Runs</th>
                          <th className="px-3 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Rate</th>
                          <th className="px-5 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Avg ms</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50">
                        {data.agent_breakdown.map((agent, i) => {
                          const rate = agent.total > 0 ? (agent.successes / agent.total) * 100 : 0;
                          return (
                            <tr key={i} className="hover:bg-gray-50/50 transition-colors">
                              <td className="px-5 py-3 font-medium text-gray-800 text-xs">{agent.agent_name}</td>
                              <td className="px-3 py-3 text-right text-gray-600 text-xs">{agent.total}</td>
                              <td className="px-3 py-3 text-right">
                                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                                  rate >= 90 ? "bg-green-100 text-green-700" :
                                  rate >= 70 ? "bg-amber-100 text-amber-700" :
                                  "bg-red-100 text-red-700"
                                }`}>{rate.toFixed(0)}%</span>
                              </td>
                              <td className="px-5 py-3 text-right text-gray-500 text-xs">{agent.avg_ms ? `${agent.avg_ms}ms` : "—"}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Recent Agent Actions */}
            <Card className="rounded-2xl shadow-sm border-0 bg-white overflow-hidden">
              <CardHeader className="px-6 pt-5 pb-4 border-b border-gray-50">
                <CardTitle className="text-base font-bold text-gray-900 flex items-center gap-2">
                  <Activity className="h-5 w-5 text-blue-600" />
                  Recent Agent Actions
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="max-h-[360px] overflow-y-auto divide-y divide-gray-50">
                  {isLoading ? (
                    Array.from({ length: 5 }).map((_, i) => (
                      <div key={i} className="px-5 py-3 flex items-center gap-3 animate-pulse">
                        <div className="w-8 h-8 bg-gray-200 rounded-full flex-shrink-0" />
                        <div className="flex-1 space-y-1.5">
                          <div className="h-3 bg-gray-200 rounded w-1/2" />
                          <div className="h-3 bg-gray-200 rounded w-3/4" />
                        </div>
                      </div>
                    ))
                  ) : data?.recent_actions?.length ? (
                    data.recent_actions.slice(0, 12).map((action, i) => (
                      <div key={i} className="px-5 py-3 flex items-center gap-3 hover:bg-gray-50/50 transition-colors">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                          action.success ? "bg-green-100" : "bg-red-100"
                        }`}>
                          {action.success
                            ? <CheckCircle className="h-4 w-4 text-green-600" />
                            : <AlertTriangle className="h-4 w-4 text-red-600" />
                          }
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-semibold text-gray-800 truncate">{action.agent_name}</p>
                          <p className="text-xs text-gray-400 truncate">{action.action_type}</p>
                        </div>
                        <div className="text-right flex-shrink-0">
                          <Badge className={`text-xs mb-1 ${
                            action.success
                              ? "bg-green-100 text-green-700 border-green-200"
                              : "bg-red-100 text-red-700 border-red-200"
                          }`}>
                            {action.success ? "success" : "failed"}
                          </Badge>
                          <p className="text-xs text-gray-400">{timeAgo(action.created_at)}</p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="px-5 py-8 text-center text-gray-400 text-sm">No recent actions</div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* ── Budget Rows Table ─────────────────────────────────────────── */}
          {data?.budget_rows && data.budget_rows.length > 0 && (
            <Card className="rounded-2xl shadow-sm border-0 bg-white overflow-hidden">
              <CardHeader className="px-6 pt-5 pb-4 border-b border-gray-50">
                <CardTitle className="text-base font-bold text-gray-900">
                  Budget Rows — FY {data.fiscal_year || 2026}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm min-w-[700px]">
                    <thead>
                      <tr className="bg-gray-50/50 border-b border-gray-50">
                        {["Department", "Category", "Allocated", "Spent", "Committed", "Available", "Utilization"].map(h => (
                          <th key={h} className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {data.budget_rows.map((row, i) => (
                        <tr key={i} className="hover:bg-gray-50/40 transition-colors">
                          <td className="px-5 py-3 font-medium text-gray-800 text-xs">{row.department}</td>
                          <td className="px-5 py-3 text-gray-600 text-xs">{row.budget_category}</td>
                          <td className="px-5 py-3 text-gray-700 text-xs">{currency(row.allocated_budget)}</td>
                          <td className="px-5 py-3 text-red-600 text-xs font-medium">{currency(row.spent_budget)}</td>
                          <td className="px-5 py-3 text-amber-600 text-xs">{currency(row.committed_budget)}</td>
                          <td className="px-5 py-3 text-green-600 text-xs font-medium">{currency(row.available_budget)}</td>
                          <td className="px-5 py-3">
                            <div className="flex items-center gap-2">
                              <div className="flex-1 bg-gray-100 rounded-full h-1.5 overflow-hidden w-20">
                                <div
                                  className={`h-full rounded-full ${row.spent_percent >= 90 ? "bg-red-500" : row.spent_percent >= 70 ? "bg-amber-500" : "bg-blue-500"}`}
                                  style={{ width: `${Math.min(row.spent_percent, 100)}%` }}
                                />
                              </div>
                              <span className="text-xs text-gray-500">{pct(row.spent_percent)}</span>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

        </div>
      </ScrollArea>
    </div>
  );
}
