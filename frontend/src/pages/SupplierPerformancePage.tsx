import { useState, useEffect } from "react";
import { useLocation } from "wouter";
import { apiFetch } from "@/lib/api";
import {
  ArrowLeft,
  Star,
  TrendingUp,
  TrendingDown,
  Minus,
  Loader2,
  Eye,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Progress } from "@/components/ui/progress";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

// ── Demo data ──────────────────────────────────────────────────────────────────
const DEMO_VENDORS = [
  { name: "TechCorp FZE", category: "IT Equipment", score: 92, ontime: 96, quality: 95, response: "< 2hrs", trend: "up" },
  { name: "Office World LLC", category: "Office Supplies", score: 85, ontime: 91, quality: 88, response: "< 4hrs", trend: "stable" },
  { name: "Maintenance Pro", category: "Maintenance", score: 71, ontime: 78, quality: 74, response: "< 8hrs", trend: "down" },
  { name: "CloudSoft MENA", category: "Software", score: 88, ontime: 93, quality: 90, response: "< 2hrs", trend: "up" },
  { name: "Facilities Plus", category: "Facilities", score: 63, ontime: 85, quality: 65, response: "< 12hrs", trend: "down" },
  { name: "LogiFreight", category: "Logistics", score: 79, ontime: 82, quality: 80, response: "< 6hrs", trend: "stable" },
  { name: "MediaBrand LLC", category: "Marketing", score: 55, ontime: 72, quality: 58, response: "> 24hrs", trend: "down" },
  { name: "SoftServe Inc", category: "Software", score: 84, ontime: 89, quality: 87, response: "< 4hrs", trend: "up" },
];

type Vendor = (typeof DEMO_VENDORS)[number];

// ── Helpers ────────────────────────────────────────────────────────────────────
function scoreColor(score: number) {
  if (score >= 80) return "bg-emerald-100 text-emerald-800 border-emerald-300";
  if (score >= 60) return "bg-amber-100 text-amber-800 border-amber-300";
  return "bg-red-100 text-red-800 border-red-300";
}

function barColor(score: number) {
  if (score >= 80) return "#10b981";
  if (score >= 60) return "#f59e0b";
  return "#ef4444";
}

function TrendIcon({ trend }: { trend: string }) {
  if (trend === "up") return <TrendingUp className="h-4 w-4 text-emerald-600" />;
  if (trend === "down") return <TrendingDown className="h-4 w-4 text-red-500" />;
  return <Minus className="h-4 w-4 text-gray-400" />;
}

// ── Custom Tooltip ─────────────────────────────────────────────────────────────
const ScoreTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-sm">
      <p className="font-semibold text-gray-700 mb-1">{label}</p>
      <p style={{ color: barColor(payload[0].value) }}>Score: {payload[0].value}/100</p>
    </div>
  );
};

// ── Quadrant card ──────────────────────────────────────────────────────────────
function QuadrantCard({
  title,
  emoji,
  vendors,
  borderColor,
  bgColor,
}: {
  title: string;
  emoji: string;
  vendors: string[];
  borderColor: string;
  bgColor: string;
}) {
  return (
    <div className={`rounded-lg border-2 ${borderColor} ${bgColor} p-4`}>
      <p className="font-semibold text-sm mb-2">
        {emoji} {title}
      </p>
      {vendors.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">None</p>
      ) : (
        <ul className="space-y-1">
          {vendors.map((v) => (
            <li key={v} className="text-sm text-gray-700 flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-current flex-shrink-0" />
              {v}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────
export default function SupplierPerformancePage() {
  const [, setLocation] = useLocation();
  const [isLoading, setIsLoading] = useState(false);
  const [vendors, setVendors] = useState<Vendor[]>(DEMO_VENDORS);

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const res = await apiFetch("/api/agentic/supplier/performance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vendor_id: "all" }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const rows = json.vendors || json.data || json;
      if (Array.isArray(rows) && rows.length > 0) {
        setVendors(rows);
      } else {
        setVendors(DEMO_VENDORS);
      }
    } catch {
      setVendors(DEMO_VENDORS);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // ── Derived stats ──
  const avgScore = Math.round(vendors.reduce((s, v) => s + v.score, 0) / (vendors.length || 1));
  const avgOntime = Math.round(vendors.reduce((s, v) => s + v.ontime, 0) / (vendors.length || 1));
  const ratedThisMonth = vendors.length;

  // ── Quadrant classification ──
  const strategic = vendors.filter((v) => v.score >= 80 && v.ontime >= 90).map((v) => v.name);
  const develop = vendors.filter((v) => v.score >= 80 && v.ontime < 90).map((v) => v.name);
  const monitor = vendors.filter((v) => v.score < 80 && v.ontime >= 90).map((v) => v.name);
  const atRisk = vendors.filter((v) => v.score < 80 && v.ontime < 90).map((v) => v.name);

  // ── Chart data (top 10 by score) ──
  const chartData = [...vendors]
    .sort((a, b) => b.score - a.score)
    .slice(0, 10)
    .map((v) => ({ name: v.name.split(" ")[0], fullName: v.name, score: v.score }));

  return (
    <div className="bg-background flex flex-col h-full">
      {/* ── Header ── */}
      <header className="border-b bg-gradient-to-r from-amber-500 to-orange-500 text-white px-4 py-3 flex items-center justify-between shadow-md flex-shrink-0">
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
            <Star className="h-5 w-5" />
            <div>
              <h1 className="text-lg font-semibold leading-tight">Supplier Performance</h1>
              <p className="text-xs text-white/70">WF-16 — Vendor scorecards &amp; performance tracking</p>
            </div>
          </div>
        </div>
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-white/80" />
        ) : (
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchData}
            className="text-white hover:bg-white/20 text-xs"
          >
            Refresh
          </Button>
        )}
      </header>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-5 max-w-7xl mx-auto">

          {/* ── Summary Cards ── */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="shadow-sm border-l-4 border-l-amber-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Avg Performance Score</p>
                <div className="flex items-end gap-2 mt-1">
                  <span
                    className={`text-4xl font-bold ${
                      avgScore >= 80
                        ? "text-emerald-600"
                        : avgScore >= 60
                        ? "text-amber-600"
                        : "text-red-600"
                    }`}
                  >
                    {avgScore}
                  </span>
                  <span className="text-gray-400 text-lg mb-1">/100</span>
                </div>
                <Progress
                  value={avgScore}
                  className="mt-2 h-2"
                />
              </CardContent>
            </Card>

            <Card className="shadow-sm border-l-4 border-l-emerald-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">On-Time Delivery Rate</p>
                <p className="text-4xl font-bold text-emerald-600 mt-1">{avgOntime}%</p>
                <Progress value={avgOntime} className="mt-2 h-2" />
              </CardContent>
            </Card>

            <Card className="shadow-sm border-l-4 border-l-blue-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Suppliers Rated This Month</p>
                <p className="text-4xl font-bold text-blue-600 mt-1">{ratedThisMonth}</p>
                <p className="text-xs text-muted-foreground mt-1">vendors evaluated</p>
              </CardContent>
            </Card>
          </div>

          {/* ── Charts + Table Row ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Scoring Chart */}
            <Card className="shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">Supplier Scores (Top 10)</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart
                    data={chartData}
                    layout="vertical"
                    margin={{ top: 0, right: 16, left: 8, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
                    <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={75} />
                    <Tooltip content={<ScoreTooltip />} />
                    <Bar dataKey="score" radius={[0, 4, 4, 0]}>
                      {chartData.map((entry, idx) => (
                        <Cell key={idx} fill={barColor(entry.score)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            {/* Quadrant Analysis */}
            <Card className="shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">Quadrant Analysis</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-3 h-full">
                  <QuadrantCard
                    title="Strategic Partners"
                    emoji="⭐"
                    vendors={strategic}
                    borderColor="border-emerald-400"
                    bgColor="bg-emerald-50"
                  />
                  <QuadrantCard
                    title="Develop"
                    emoji="🔄"
                    vendors={develop}
                    borderColor="border-blue-400"
                    bgColor="bg-blue-50"
                  />
                  <QuadrantCard
                    title="Monitor"
                    emoji="⚠️"
                    vendors={monitor}
                    borderColor="border-amber-400"
                    bgColor="bg-amber-50"
                  />
                  <QuadrantCard
                    title="At Risk"
                    emoji="🚨"
                    vendors={atRisk}
                    borderColor="border-red-400"
                    bgColor="bg-red-50"
                  />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* ── Performance Table ── */}
          <Card className="shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">Vendor Performance Details</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {vendors.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                  <Star className="h-12 w-12 mb-3 opacity-30" />
                  <p className="text-sm">No vendor data available</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-gray-50 text-left text-muted-foreground">
                        <th className="py-3 pl-4 pr-2 font-medium">Vendor Name</th>
                        <th className="py-3 pr-2 font-medium">Category</th>
                        <th className="py-3 pr-2 font-medium text-center">Score /100</th>
                        <th className="py-3 pr-2 font-medium text-center">On-Time %</th>
                        <th className="py-3 pr-2 font-medium text-center">Quality</th>
                        <th className="py-3 pr-2 font-medium text-center">Response</th>
                        <th className="py-3 pr-2 font-medium text-center">Trend</th>
                        <th className="py-3 pr-4 font-medium text-center">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {vendors.map((v) => (
                        <tr
                          key={v.name}
                          className="border-b border-border/40 hover:bg-gray-50 transition-colors"
                        >
                          <td className="py-3 pl-4 pr-2 font-semibold text-gray-800">{v.name}</td>
                          <td className="py-3 pr-2">
                            <Badge variant="outline" className="text-xs font-normal">
                              {v.category}
                            </Badge>
                          </td>
                          <td className="py-3 pr-2 text-center">
                            <Badge className={`text-xs border ${scoreColor(v.score)}`}>
                              {v.score}
                            </Badge>
                          </td>
                          <td className="py-3 pr-2 text-center">
                            <span
                              className={`font-medium ${
                                v.ontime >= 90
                                  ? "text-emerald-600"
                                  : v.ontime >= 75
                                  ? "text-amber-600"
                                  : "text-red-500"
                              }`}
                            >
                              {v.ontime}%
                            </span>
                          </td>
                          <td className="py-3 pr-2 text-center text-gray-600">{v.quality}</td>
                          <td className="py-3 pr-2 text-center text-gray-500 text-xs">{v.response}</td>
                          <td className="py-3 pr-2 text-center">
                            <span className="inline-flex items-center justify-center">
                              <TrendIcon trend={v.trend} />
                            </span>
                          </td>
                          <td className="py-3 pr-4 text-center">
                            <Button variant="outline" size="sm" className="gap-1 h-7 text-xs">
                              <Eye className="h-3 w-3" />
                              View
                            </Button>
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
      </ScrollArea>
    </div>
  );
}
