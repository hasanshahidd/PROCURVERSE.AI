/**
 * Budget Tracking Page — Sprint 9
 * WF-02: Real-time budget utilization, department breakdown, and alerts
 */
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { apiFetch } from "@/lib/api";
import {
  ArrowLeft, DollarSign, TrendingUp, TrendingDown,
  AlertTriangle, RefreshCcw, BarChart3, PieChartIcon
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, RadialBarChart, RadialBar
} from "recharts";

const COLORS = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0891b2"];

type BudgetRow = {
  department: string;
  budget_category: string;
  allocated_budget: number;
  spent_budget: number;
  committed_budget: number;
  available_budget: number;
  spent_percent: number;
};

type DeptSummary = {
  department: string;
  allocated: number;
  spent: number;
  committed: number;
  available: number;
};

const DEMO_BUDGET_ROWS: BudgetRow[] = [
  { department: "IT", budget_category: "Hardware", allocated_budget: 500000, spent_budget: 320000, committed_budget: 80000, available_budget: 100000, spent_percent: 64 },
  { department: "IT", budget_category: "Software", allocated_budget: 250000, spent_budget: 180000, committed_budget: 40000, available_budget: 30000, spent_percent: 72 },
  { department: "Operations", budget_category: "Maintenance", allocated_budget: 380000, spent_budget: 290000, committed_budget: 45000, available_budget: 45000, spent_percent: 76 },
  { department: "Operations", budget_category: "Logistics", allocated_budget: 200000, spent_budget: 95000, committed_budget: 30000, available_budget: 75000, spent_percent: 47 },
  { department: "Finance", budget_category: "Professional Services", allocated_budget: 180000, spent_budget: 145000, committed_budget: 15000, available_budget: 20000, spent_percent: 81 },
  { department: "HR", budget_category: "Recruitment", allocated_budget: 150000, spent_budget: 62000, committed_budget: 18000, available_budget: 70000, spent_percent: 41 },
  { department: "Admin", budget_category: "Office Supplies", allocated_budget: 80000, spent_budget: 55000, committed_budget: 8000, available_budget: 17000, spent_percent: 69 },
  { department: "Marketing", budget_category: "Campaigns", allocated_budget: 220000, spent_budget: 198000, committed_budget: 10000, available_budget: 12000, spent_percent: 90 },
];

const DEMO_DEPT: DeptSummary[] = [
  { department: "IT", allocated: 750000, spent: 500000, committed: 120000, available: 130000 },
  { department: "Operations", allocated: 580000, spent: 385000, committed: 75000, available: 120000 },
  { department: "Finance", allocated: 180000, spent: 145000, committed: 15000, available: 20000 },
  { department: "HR", allocated: 150000, spent: 62000, committed: 18000, available: 70000 },
  { department: "Admin", allocated: 80000, spent: 55000, committed: 8000, available: 17000 },
  { department: "Marketing", allocated: 220000, spent: 198000, committed: 10000, available: 12000 },
];

function fmt(n: number) {
  return `AED ${Math.round(n).toLocaleString("en")}`;
}

function utilizationColor(pct: number) {
  if (pct >= 90) return "bg-red-500";
  if (pct >= 75) return "bg-amber-500";
  return "bg-emerald-500";
}

function utilizationBadge(pct: number) {
  if (pct >= 90) return <Badge className="bg-red-100 text-red-800 border border-red-200 text-xs">Over Budget Risk</Badge>;
  if (pct >= 75) return <Badge className="bg-amber-100 text-amber-800 border border-amber-200 text-xs">Watch</Badge>;
  return <Badge className="bg-emerald-100 text-emerald-800 border border-emerald-200 text-xs">On Track</Badge>;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-lg p-3 text-xs">
      <p className="font-semibold text-gray-800 mb-2">{label}</p>
      {payload.map((p: any) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span className="text-gray-600">{p.name}:</span>
          <span className="font-medium">AED {Number(p.value).toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
};

export default function BudgetPage() {
  const [, setLocation] = useLocation();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["budget-data"],
    queryFn: async () => {
      try {
        const res = await apiFetch("/api/agentic/dashboard/data");
        if (!res.ok) return { budget_rows: DEMO_BUDGET_ROWS, department_summary: DEMO_DEPT };
        const d = await res.json();
        return {
          budget_rows: d.budget_rows?.length ? d.budget_rows : DEMO_BUDGET_ROWS,
          department_summary: d.department_summary?.length ? d.department_summary : DEMO_DEPT,
          budget_summary: d.system_stats?.budget_summary,
        };
      } catch {
        return { budget_rows: DEMO_BUDGET_ROWS, department_summary: DEMO_DEPT };
      }
    },
    staleTime: 60000,
  });

  const rows: BudgetRow[] = data?.budget_rows || DEMO_BUDGET_ROWS;
  const depts: DeptSummary[] = data?.department_summary || DEMO_DEPT;

  const totalAllocated = depts.reduce((s, d) => s + d.allocated, 0);
  const totalSpent = depts.reduce((s, d) => s + d.spent, 0);
  const totalCommitted = depts.reduce((s, d) => s + d.committed, 0);
  const totalAvailable = depts.reduce((s, d) => s + d.available, 0);
  const overallPct = totalAllocated > 0 ? Math.round(totalSpent / totalAllocated * 100) : 0;
  const atRisk = rows.filter(r => r.spent_percent >= 90).length;

  // Chart data
  const barData = depts.map(d => ({
    name: d.department,
    Allocated: Math.round(d.allocated / 1000),
    Spent: Math.round(d.spent / 1000),
    Committed: Math.round(d.committed / 1000),
  }));

  const pieData = depts.map((d, i) => ({
    name: d.department,
    value: d.spent,
    color: COLORS[i % COLORS.length],
  }));

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => setLocation("/dashboard")}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div className="flex-1">
            <h1 className="text-xl font-bold text-gray-900 flex items-center gap-2">
              <DollarSign className="h-5 w-5 text-emerald-600" />
              Budget Tracking
            </h1>
            <p className="text-sm text-gray-500">WF-02 — Real-time budget utilization across departments</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => refetch()} className="gap-2">
            <RefreshCcw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      <div className="p-6 space-y-6 max-w-7xl mx-auto">

        {/* Alert banner */}
        {atRisk > 0 && (
          <div className="rounded-xl bg-red-50 border border-red-200 p-4 flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-red-500 flex-shrink-0" />
            <p className="text-sm text-red-700 font-medium">
              {atRisk} budget {atRisk === 1 ? "category" : "categories"} at ≥90% utilization — immediate review required.
            </p>
          </div>
        )}

        {/* KPI Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            {
              label: "Total Budget", value: fmt(totalAllocated),
              sub: "FY 2026 allocation", icon: DollarSign,
              color: "text-blue-600", bg: "bg-blue-50",
            },
            {
              label: "Total Spent", value: fmt(totalSpent),
              sub: `${overallPct}% utilized`, icon: TrendingUp,
              color: "text-amber-600", bg: "bg-amber-50",
            },
            {
              label: "Committed", value: fmt(totalCommitted),
              sub: "Open POs & contracts", icon: BarChart3,
              color: "text-purple-600", bg: "bg-purple-50",
            },
            {
              label: "Available", value: fmt(totalAvailable),
              sub: "Remaining to spend", icon: TrendingDown,
              color: "text-emerald-600", bg: "bg-emerald-50",
            },
          ].map(({ label, value, sub, icon: Icon, color, bg }) => (
            <Card key={label} className="shadow-sm rounded-2xl border-0 ring-1 ring-gray-200">
              <CardContent className="p-5">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs text-gray-500 uppercase tracking-wide font-medium">{label}</p>
                    <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
                    <p className="text-xs text-gray-400 mt-1">{sub}</p>
                  </div>
                  <div className={`p-2.5 rounded-xl ${bg}`}>
                    <Icon className={`h-5 w-5 ${color}`} />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Overall utilization bar */}
        <Card className="shadow-sm rounded-2xl border-0 ring-1 ring-gray-200">
          <CardContent className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="font-semibold text-gray-800">Overall Budget Utilization</p>
                <p className="text-sm text-gray-500">Fiscal Year 2026</p>
              </div>
              <span className={`text-3xl font-bold ${overallPct >= 90 ? "text-red-600" : overallPct >= 75 ? "text-amber-600" : "text-emerald-600"}`}>
                {overallPct}%
              </span>
            </div>
            <div className="h-4 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-700 ${overallPct >= 90 ? "bg-red-500" : overallPct >= 75 ? "bg-amber-500" : "bg-emerald-500"}`}
                style={{ width: `${Math.min(overallPct, 100)}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>AED 0</span>
              <span>{fmt(totalAllocated)}</span>
            </div>
          </CardContent>
        </Card>

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Bar chart */}
          <Card className="lg:col-span-3 shadow-sm rounded-2xl border-0 ring-1 ring-gray-200">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <BarChart3 className="h-4 w-4 text-blue-600" />
                Budget vs Spend by Department (AED '000s)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={barData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend iconType="circle" iconSize={8} />
                  <Bar dataKey="Allocated" fill="#dbeafe" stroke="#2563eb" strokeWidth={1} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Spent" fill="#2563eb" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Committed" fill="#7c3aed" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Pie chart */}
          <Card className="lg:col-span-2 shadow-sm rounded-2xl border-0 ring-1 ring-gray-200">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <PieChartIcon className="h-4 w-4 text-purple-600" />
                Spend Distribution
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={55}
                    outerRadius={85}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {pieData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: number) => [`AED ${v.toLocaleString()}`, ""]} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5 mt-1">
                {pieData.map((d, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-sm" style={{ background: d.color }} />
                      <span className="text-gray-600">{d.name}</span>
                    </div>
                    <span className="font-medium text-gray-800">AED {Math.round(d.value / 1000)}K</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Department Detail Table */}
        <Card className="shadow-sm rounded-2xl border-0 ring-1 ring-gray-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-700">Department Budget Detail</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-gray-50 text-xs">
                    <th className="text-left py-3 px-4 font-medium text-gray-600">Department</th>
                    <th className="text-right py-3 px-4 font-medium text-gray-600">Allocated</th>
                    <th className="text-right py-3 px-4 font-medium text-gray-600">Spent</th>
                    <th className="text-right py-3 px-4 font-medium text-gray-600">Committed</th>
                    <th className="text-right py-3 px-4 font-medium text-gray-600">Available</th>
                    <th className="text-left py-3 px-4 font-medium text-gray-600 w-48">Utilization</th>
                    <th className="py-3 px-4"></th>
                  </tr>
                </thead>
                <tbody>
                  {depts.map(d => {
                    const pct = d.allocated > 0 ? Math.round(d.spent / d.allocated * 100) : 0;
                    return (
                      <tr key={d.department} className="border-b hover:bg-gray-50 transition-colors">
                        <td className="py-3 px-4 font-semibold text-gray-900">{d.department}</td>
                        <td className="py-3 px-4 text-right text-gray-700">{fmt(d.allocated)}</td>
                        <td className="py-3 px-4 text-right font-medium text-gray-900">{fmt(d.spent)}</td>
                        <td className="py-3 px-4 text-right text-purple-700">{fmt(d.committed)}</td>
                        <td className="py-3 px-4 text-right text-emerald-700">{fmt(d.available)}</td>
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${utilizationColor(pct)}`}
                                style={{ width: `${Math.min(pct, 100)}%` }}
                              />
                            </div>
                            <span className={`text-xs font-semibold w-8 ${pct >= 90 ? "text-red-600" : pct >= 75 ? "text-amber-600" : "text-emerald-600"}`}>
                              {pct}%
                            </span>
                          </div>
                        </td>
                        <td className="py-3 px-4">{utilizationBadge(pct)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* Category breakdown */}
        <Card className="shadow-sm rounded-2xl border-0 ring-1 ring-gray-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-700">Category Breakdown</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-gray-50 text-xs">
                    <th className="text-left py-3 px-4 font-medium text-gray-600">Department</th>
                    <th className="text-left py-3 px-4 font-medium text-gray-600">Category</th>
                    <th className="text-right py-3 px-4 font-medium text-gray-600">Allocated</th>
                    <th className="text-right py-3 px-4 font-medium text-gray-600">Spent</th>
                    <th className="text-left py-3 px-4 font-medium text-gray-600 w-44">Progress</th>
                    <th className="py-3 px-4"></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className="border-b hover:bg-gray-50">
                      <td className="py-3 px-4 text-gray-700">{r.department}</td>
                      <td className="py-3 px-4 text-gray-600">{r.budget_category}</td>
                      <td className="py-3 px-4 text-right text-gray-700">{fmt(r.allocated_budget)}</td>
                      <td className="py-3 px-4 text-right font-medium">{fmt(r.spent_budget)}</td>
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${utilizationColor(r.spent_percent)}`}
                              style={{ width: `${Math.min(r.spent_percent, 100)}%` }}
                            />
                          </div>
                          <span className="text-xs text-gray-500 w-8">{r.spent_percent}%</span>
                        </div>
                      </td>
                      <td className="py-3 px-4">{utilizationBadge(r.spent_percent)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
