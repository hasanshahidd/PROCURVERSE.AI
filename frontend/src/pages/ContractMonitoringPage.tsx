import { useState, useEffect } from "react";
import { useLocation } from "wouter";
import { apiFetch } from "@/lib/api";
import {
  ArrowLeft,
  ShieldCheck,
  AlertTriangle,
  RefreshCcw,
  Loader2,
  FileText,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
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
const DEMO_CONTRACTS = [
  { id: "CTR-2024-001", vendor: "TechCorp FZE", category: "IT Equipment", value: 480000, start: "2024-01-15", end: "2026-04-10", status: "expiring_soon" },
  { id: "CTR-2024-002", vendor: "Office World LLC", category: "Office Supplies", value: 120000, start: "2024-03-01", end: "2026-06-30", status: "active" },
  { id: "CTR-2024-003", vendor: "CloudSoft MENA", category: "Software", value: 240000, start: "2023-07-01", end: "2026-03-20", status: "expiring_soon" },
  { id: "CTR-2023-008", vendor: "Maintenance Pro", category: "Maintenance", value: 380000, start: "2023-01-01", end: "2025-12-31", status: "expiring_soon" },
  { id: "CTR-2023-015", vendor: "LogiFreight", category: "Logistics", value: 95000, start: "2023-06-15", end: "2026-09-15", status: "active" },
  { id: "CTR-2022-003", vendor: "MediaBrand LLC", category: "Marketing", value: 60000, start: "2022-04-01", end: "2025-03-31", status: "expired" },
  { id: "CTR-2024-007", vendor: "SoftServe Inc", category: "Software", value: 185000, start: "2024-08-01", end: "2027-07-31", status: "active" },
  { id: "CTR-2024-010", vendor: "Facilities Plus", category: "Facilities", value: 210000, start: "2024-10-01", end: "2026-12-31", status: "active" },
];

type Contract = (typeof DEMO_CONTRACTS)[number];
type TabFilter = "all" | "active" | "expiring_soon" | "expired" | "renewed";

// ── Helpers ────────────────────────────────────────────────────────────────────
const aed = (value: number) =>
  `AED ${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value || 0)}`;

function daysUntilExpiry(endDateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const end = new Date(endDateStr);
  return Math.round((end.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

function daysColor(days: number) {
  if (days < 0) return "text-gray-400";
  if (days <= 30) return "text-red-600 font-bold";
  if (days <= 90) return "text-amber-600 font-semibold";
  return "text-emerald-600";
}

function statusBadge(status: string) {
  switch (status) {
    case "active":
      return <Badge className="bg-emerald-100 text-emerald-800 border border-emerald-300 text-xs">Active</Badge>;
    case "expiring_soon":
      return <Badge className="bg-amber-100 text-amber-800 border border-amber-300 text-xs">Expiring Soon</Badge>;
    case "expired":
      return <Badge className="bg-red-100 text-red-800 border border-red-300 text-xs">Expired</Badge>;
    case "renewed":
      return <Badge className="bg-blue-100 text-blue-800 border border-blue-300 text-xs">Renewed</Badge>;
    default:
      return <Badge variant="outline" className="text-xs">{status}</Badge>;
  }
}

function fmtDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

// ── Timeline: group contracts by expiry month (next 6 months) ─────────────────
function buildTimeline(contracts: Contract[]) {
  const today = new Date();
  const months: { label: string; count: number; key: string }[] = [];
  for (let i = 0; i < 6; i++) {
    const d = new Date(today.getFullYear(), today.getMonth() + i, 1);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = d.toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
    const count = contracts.filter((c) => {
      const end = new Date(c.end);
      return (
        end.getFullYear() === d.getFullYear() &&
        end.getMonth() === d.getMonth()
      );
    }).length;
    months.push({ label, count, key });
  }
  return months;
}

// ── Custom Tooltip ─────────────────────────────────────────────────────────────
const TimelineTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-sm">
      <p className="font-semibold text-gray-700">{label}</p>
      <p className="text-emerald-700">{payload[0].value} contract(s) expiring</p>
    </div>
  );
};

// ── Main Component ─────────────────────────────────────────────────────────────
export default function ContractMonitoringPage() {
  const [, setLocation] = useLocation();
  const [isLoading, setIsLoading] = useState(false);
  const [contracts, setContracts] = useState<Contract[]>(DEMO_CONTRACTS);
  const [activeTab, setActiveTab] = useState<TabFilter>("all");

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const res = await apiFetch("/api/agentic/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_type: "contract_monitoring", action: "scan_all" }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const rows = json.contracts || json.data || json;
      if (Array.isArray(rows) && rows.length > 0) {
        setContracts(rows);
      } else {
        setContracts(DEMO_CONTRACTS);
      }
    } catch {
      setContracts(DEMO_CONTRACTS);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // ── Derived stats ──
  const activeContracts = contracts.filter((c) => c.status === "active").length;
  const expiring30 = contracts.filter((c) => {
    const days = daysUntilExpiry(c.end);
    return days >= 0 && days <= 30;
  }).length;
  const expiring90 = contracts.filter((c) => {
    const days = daysUntilExpiry(c.end);
    return days > 30 && days <= 90;
  }).length;
  const totalValue = contracts.reduce((s, c) => s + c.value, 0);

  // ── Filtered table data ──
  const filtered =
    activeTab === "all"
      ? contracts
      : contracts.filter((c) => c.status === activeTab);

  // ── Timeline data ──
  const timelineData = buildTimeline(contracts);

  return (
    <div className="bg-background flex flex-col h-full">
      {/* ── Header ── */}
      <header className="border-b bg-gradient-to-r from-emerald-600 to-teal-600 text-white px-4 py-3 flex items-center justify-between shadow-md flex-shrink-0">
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
            <ShieldCheck className="h-5 w-5" />
            <div>
              <h1 className="text-lg font-semibold leading-tight">Contract Monitoring</h1>
              <p className="text-xs text-white/70">WF-17/18 — Contract lifecycle &amp; renewal alerts</p>
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
            className="gap-2 text-white hover:bg-white/20 text-xs"
          >
            <RefreshCcw className="h-3 w-3" />
            Refresh
          </Button>
        )}
      </header>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-5 max-w-7xl mx-auto">

          {/* ── Alert Banner ── */}
          {expiring30 > 0 && (
            <div className="rounded-lg border-2 border-red-300 bg-red-50 p-4 flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-red-800 text-sm">
                  {expiring30} contract{expiring30 > 1 ? "s" : ""} expiring within 30 days — Review required
                </p>
                <p className="text-xs text-red-600 mt-0.5">
                  Initiate renewal process to avoid service disruption
                </p>
              </div>
            </div>
          )}

          {/* ── KPI Cards ── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card className="shadow-sm border-l-4 border-l-emerald-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Active Contracts</p>
                <p className="text-3xl font-bold text-emerald-700 mt-1">{activeContracts}</p>
                <p className="text-xs text-muted-foreground mt-1">currently in force</p>
              </CardContent>
            </Card>

            <Card className={`shadow-sm border-l-4 ${expiring30 > 0 ? "border-l-red-500" : "border-l-gray-300"}`}>
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Expiring in 30 Days</p>
                <p className={`text-3xl font-bold mt-1 ${expiring30 > 0 ? "text-red-600" : "text-gray-500"}`}>
                  {expiring30}
                </p>
                <p className="text-xs text-muted-foreground mt-1">require urgent action</p>
              </CardContent>
            </Card>

            <Card className={`shadow-sm border-l-4 ${expiring90 > 0 ? "border-l-amber-500" : "border-l-gray-300"}`}>
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Expiring in 90 Days</p>
                <p className={`text-3xl font-bold mt-1 ${expiring90 > 0 ? "text-amber-600" : "text-gray-500"}`}>
                  {expiring90}
                </p>
                <p className="text-xs text-muted-foreground mt-1">plan renewal soon</p>
              </CardContent>
            </Card>

            <Card className="shadow-sm border-l-4 border-l-blue-500">
              <CardContent className="pt-4 pb-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Contract Value</p>
                <p className="text-xl font-bold text-blue-700 mt-1">{aed(totalValue)}</p>
                <p className="text-xs text-muted-foreground mt-1">across all contracts</p>
              </CardContent>
            </Card>
          </div>

          {/* ── Timeline ── */}
          <Card className="shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold">Contract Expiry Timeline — Next 6 Months</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={timelineData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip content={<TimelineTooltip />} />
                  <Bar dataKey="count" name="Contracts" radius={[4, 4, 0, 0]}>
                    {timelineData.map((entry, idx) => (
                      <Cell
                        key={idx}
                        fill={entry.count === 0 ? "#e5e7eb" : entry.count >= 2 ? "#ef4444" : "#f59e0b"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* ── Contracts Table with Tabs ── */}
          <Card className="shadow-sm">
            <CardHeader className="pb-0">
              <CardTitle className="text-sm font-semibold mb-3">Contracts</CardTitle>
              <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as TabFilter)}>
                <TabsList className="h-9">
                  <TabsTrigger value="all" className="text-xs">All ({contracts.length})</TabsTrigger>
                  <TabsTrigger value="active" className="text-xs">
                    Active ({contracts.filter((c) => c.status === "active").length})
                  </TabsTrigger>
                  <TabsTrigger value="expiring_soon" className="text-xs">
                    Expiring ({contracts.filter((c) => c.status === "expiring_soon").length})
                  </TabsTrigger>
                  <TabsTrigger value="expired" className="text-xs">
                    Expired ({contracts.filter((c) => c.status === "expired").length})
                  </TabsTrigger>
                  <TabsTrigger value="renewed" className="text-xs">
                    Renewed ({contracts.filter((c) => c.status === "renewed").length})
                  </TabsTrigger>
                </TabsList>

                <TabsContent value={activeTab} className="mt-0">
                  {filtered.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
                      <FileText className="h-12 w-12 mb-3 opacity-30" />
                      <p className="text-sm">No contracts in this category</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b bg-gray-50 text-left text-muted-foreground">
                            <th className="py-3 pl-4 pr-2 font-medium">Contract #</th>
                            <th className="py-3 pr-2 font-medium">Vendor</th>
                            <th className="py-3 pr-2 font-medium">Category</th>
                            <th className="py-3 pr-2 font-medium text-right">Value</th>
                            <th className="py-3 pr-2 font-medium">Start Date</th>
                            <th className="py-3 pr-2 font-medium">End Date</th>
                            <th className="py-3 pr-2 font-medium text-center">Days Left</th>
                            <th className="py-3 pr-2 font-medium text-center">Status</th>
                            <th className="py-3 pr-4 font-medium text-center">Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filtered.map((c) => {
                            const days = daysUntilExpiry(c.end);
                            return (
                              <tr
                                key={c.id}
                                className="border-b border-border/40 hover:bg-gray-50 transition-colors"
                              >
                                <td className="py-3 pl-4 pr-2 font-mono text-xs text-gray-600">{c.id}</td>
                                <td className="py-3 pr-2 font-semibold text-gray-800">{c.vendor}</td>
                                <td className="py-3 pr-2">
                                  <Badge variant="outline" className="text-xs font-normal">
                                    {c.category}
                                  </Badge>
                                </td>
                                <td className="py-3 pr-2 text-right text-gray-700">{aed(c.value)}</td>
                                <td className="py-3 pr-2 text-gray-500 text-xs">{fmtDate(c.start)}</td>
                                <td className="py-3 pr-2 text-gray-500 text-xs">{fmtDate(c.end)}</td>
                                <td className="py-3 pr-2 text-center">
                                  <span className={`text-sm ${daysColor(days)}`}>
                                    {days < 0 ? "Expired" : days === 0 ? "Today" : `${days}d`}
                                  </span>
                                </td>
                                <td className="py-3 pr-2 text-center">{statusBadge(c.status)}</td>
                                <td className="py-3 pr-4 text-center">
                                  {(c.status === "expiring_soon" || c.status === "expired") ? (
                                    <Button
                                      size="sm"
                                      className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                                    >
                                      Renew
                                    </Button>
                                  ) : (
                                    <Button variant="outline" size="sm" className="h-7 text-xs">
                                      View
                                    </Button>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            </CardHeader>
          </Card>
        </div>
      </ScrollArea>
    </div>
  );
}
