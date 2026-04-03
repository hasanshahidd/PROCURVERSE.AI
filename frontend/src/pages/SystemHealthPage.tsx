import { useState, useEffect } from "react";
import { Activity, RefreshCcw, CheckCircle, AlertTriangle, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

type AgentStatus = "online" | "degraded" | "idle";

interface AgentHealth {
  name: string;
  status: AgentStatus;
  last_run: string;
  success_rate: number;
  avg_ms: number;
}

interface KPIs {
  avg_api_ms: number;
  avg_db_ms: number;
  success_rate: number;
  uptime: number;
}

interface Issue {
  time: string;
  agent: string;
  issue: string;
  severity: "critical" | "warning" | "info";
  status: "active" | "resolved";
}

interface HealthData {
  overall_score: number;
  agents: AgentHealth[];
  kpis: KPIs;
  issues: Issue[];
}

// ─── Demo data ────────────────────────────────────────────────────────────────

const DEMO_HEALTH: HealthData = {
  overall_score: 87,
  agents: [
    { name: "POIntakeAgent", status: "online", last_run: "2 min ago", success_rate: 98.5, avg_ms: 342 },
    { name: "InvoiceMatchingAgent", status: "online", last_run: "5 min ago", success_rate: 96.2, avg_ms: 521 },
    { name: "PaymentReadinessAgent", status: "online", last_run: "1 min ago", success_rate: 99.1, avg_ms: 287 },
    { name: "InventoryCheckAgent", status: "idle", last_run: "22 min ago", success_rate: 94.8, avg_ms: 603 },
    { name: "QuoteComparisonAgent", status: "online", last_run: "8 min ago", success_rate: 97.3, avg_ms: 418 },
    { name: "GoodsReceiptAgent", status: "idle", last_run: "45 min ago", success_rate: 99.7, avg_ms: 234 },
    { name: "VendorOnboardingAgent", status: "online", last_run: "12 min ago", success_rate: 95.4, avg_ms: 892 },
    { name: "DeliveryTrackingAgent", status: "degraded", last_run: "3 min ago", success_rate: 88.1, avg_ms: 1240 },
    { name: "ForecastingAgent", status: "idle", last_run: "2 hrs ago", success_rate: 91.6, avg_ms: 756 },
  ],
  kpis: { avg_api_ms: 387, avg_db_ms: 42, success_rate: 96.8, uptime: 99.9 },
  issues: [
    { time: "14:32", agent: "DeliveryTrackingAgent", issue: "External tracking API timeout", severity: "warning", status: "active" },
    { time: "11:15", agent: "InvoiceMatchingAgent", issue: "Duplicate invoice detected, auto-resolved", severity: "info", status: "resolved" },
    { time: "09:48", agent: "InventoryCheckAgent", issue: "Reorder threshold adjustment required", severity: "info", status: "resolved" },
  ],
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  if (score >= 80) return "text-green-600";
  if (score >= 60) return "text-amber-500";
  return "text-red-600";
}

function scoreRingColor(score: number): string {
  if (score >= 80) return "#16a34a";
  if (score >= 60) return "#d97706";
  return "#dc2626";
}

function statusDot(status: AgentStatus) {
  const colors: Record<AgentStatus, string> = {
    online: "bg-green-500",
    degraded: "bg-amber-400",
    idle: "bg-gray-400",
  };
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${colors[status]}`} />;
}

function severityBadge(severity: Issue["severity"]) {
  const map = {
    critical: "destructive" as const,
    warning: "outline" as const,
    info: "secondary" as const,
  };
  const colorMap = {
    critical: "bg-red-100 text-red-800 border-red-300",
    warning: "bg-amber-100 text-amber-800 border-amber-300",
    info: "bg-blue-100 text-blue-800 border-blue-300",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${colorMap[severity]}`}>
      {severity}
    </span>
  );
}

function statusBadge(status: Issue["status"]) {
  return status === "resolved" ? (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 border border-green-300">
      resolved
    </span>
  ) : (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800 border border-red-300">
      active
    </span>
  );
}

// ─── Circular Score Ring ──────────────────────────────────────────────────────

function ScoreRing({ score }: { score: number }) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const filled = (score / 100) * circumference;
  const color = scoreRingColor(score);

  return (
    <div className="flex flex-col items-center justify-center">
      <svg width="140" height="140" viewBox="0 0 140 140">
        <circle cx="70" cy="70" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="12" />
        <circle
          cx="70"
          cy="70"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeDasharray={`${filled} ${circumference - filled}`}
          strokeLinecap="round"
          transform="rotate(-90 70 70)"
        />
        <text x="70" y="66" textAnchor="middle" fontSize="28" fontWeight="700" fill={color}>
          {score}
        </text>
        <text x="70" y="84" textAnchor="middle" fontSize="11" fill="#6b7280">
          / 100
        </text>
      </svg>
      <p className="text-sm text-muted-foreground mt-1">System Health Score</p>
    </div>
  );
}

// ─── Agent Card ───────────────────────────────────────────────────────────────

function AgentCard({ agent }: { agent: AgentHealth }) {
  const shortName = agent.name.replace("Agent", "");
  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-sm">{shortName}</span>
          <div className="flex items-center gap-1.5">
            {statusDot(agent.status)}
            <span className="text-xs capitalize text-muted-foreground">{agent.status}</span>
          </div>
        </div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />
          {agent.last_run}
        </div>
        <div className="space-y-1">
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Success Rate</span>
            <span className="font-medium text-green-700">{agent.success_rate.toFixed(1)}%</span>
          </div>
          <Progress value={agent.success_rate} className="h-1.5" />
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">Avg Response</span>
          <span className={`font-medium ${agent.avg_ms > 1000 ? "text-red-600" : agent.avg_ms > 600 ? "text-amber-600" : "text-green-700"}`}>
            {agent.avg_ms}ms
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KpiCard({ label, value, unit = "" }: { label: string; value: string | number; unit?: string }) {
  return (
    <Card>
      <CardContent className="p-4 text-center">
        <p className="text-2xl font-bold text-blue-700">
          {value}
          <span className="text-base font-normal text-muted-foreground ml-1">{unit}</span>
        </p>
        <p className="text-xs text-muted-foreground mt-1">{label}</p>
      </CardContent>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function SystemHealthPage() {
  const [data, setData] = useState<HealthData>(DEMO_HEALTH);
  const [loading, setLoading] = useState(false);
  const [lastChecked, setLastChecked] = useState<string>(new Date().toLocaleTimeString());
  const [isDemo, setIsDemo] = useState(true);

  const fetchHealth = async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/api/agentic/monitoring/health");
      if (!res.ok) throw new Error("Non-OK response");
      const json = await res.json();
      setData(json);
      setIsDemo(false);
    } catch {
      setData(DEMO_HEALTH);
      setIsDemo(true);
    } finally {
      setLoading(false);
      setLastChecked(new Date().toLocaleTimeString());
    }
  };

  useEffect(() => {
    fetchHealth();
  }, []);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-green-100 flex items-center justify-center">
            <Activity className="h-5 w-5 text-green-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">System Health Monitor</h1>
            <p className="text-sm text-muted-foreground">WF-20 — Real-time agent performance & system KPIs</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {isDemo && (
            <Badge variant="secondary" className="bg-amber-100 text-amber-800">Demo Data</Badge>
          )}
          <span className="text-xs text-muted-foreground">Last checked: {lastChecked}</span>
          <Button variant="outline" size="sm" onClick={fetchHealth} disabled={loading}>
            <RefreshCcw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Overall Score + KPIs Row */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Score Ring Card */}
        <Card className="lg:col-span-1 flex items-center justify-center py-4">
          <CardContent className="pt-2 pb-0">
            <ScoreRing score={data.overall_score} />
          </CardContent>
        </Card>

        {/* KPI Cards */}
        <div className="lg:col-span-4 grid grid-cols-2 md:grid-cols-4 gap-4">
          <KpiCard label="API Response Time" value={data.kpis.avg_api_ms} unit="ms" />
          <KpiCard label="DB Query Time" value={data.kpis.avg_db_ms} unit="ms" />
          <KpiCard label="Agent Success Rate" value={`${data.kpis.success_rate.toFixed(1)}%`} />
          <KpiCard label="Uptime" value={`${data.kpis.uptime}%`} />
        </div>
      </div>

      {/* Agent Status Grid */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Agent Status</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.agents.map((agent) => (
            <AgentCard key={agent.name} agent={agent} />
          ))}
        </div>
      </div>

      {/* Recent Issues Table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            Recent Issues
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea className="h-[220px]">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Time</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Agent</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Issue</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Severity</th>
                  <th className="text-left px-4 py-2 font-medium text-muted-foreground">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.issues.map((issue, idx) => (
                  <tr key={idx} className="border-t hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-3 text-muted-foreground font-mono">{issue.time}</td>
                    <td className="px-4 py-3 font-medium">{issue.agent.replace("Agent", "")}</td>
                    <td className="px-4 py-3 text-muted-foreground max-w-xs truncate">{issue.issue}</td>
                    <td className="px-4 py-3">{severityBadge(issue.severity)}</td>
                    <td className="px-4 py-3">{statusBadge(issue.status)}</td>
                  </tr>
                ))}
                {data.issues.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                      <CheckCircle className="h-6 w-6 text-green-500 mx-auto mb-2" />
                      No recent issues
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
