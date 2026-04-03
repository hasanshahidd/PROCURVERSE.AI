import { useState, useEffect } from "react";
import { AlertTriangle, Shield, RefreshCw, Search } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiFetch } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

interface Anomaly {
  id: string;
  rule: string;
  severity: Severity;
  description: string;
  entity_type: string;
  entity_id: string;
  detected_at: string;
  status: string;
}

// ─── Demo data ────────────────────────────────────────────────────────────────

const DEMO_ANOMALIES: Anomaly[] = [
  {
    id: "ANO-0001",
    rule: "DUPLICATE_INVOICE",
    severity: "HIGH",
    description: "Possible duplicate invoices for vendor 'Global Tech Ltd' with amount 15000: INV-001, INV-047",
    entity_type: "invoice",
    entity_id: "INV-001",
    detected_at: "2026-04-01T10:30:00Z",
    status: "open",
  },
  {
    id: "ANO-0002",
    rule: "SPEND_SPIKE",
    severity: "MEDIUM",
    description: "Spend spike for vendor 'Office Supplies Co': latest 45000 is 2.1x average 21000",
    entity_type: "vendor",
    entity_id: "VEND-23",
    detected_at: "2026-04-01T09:15:00Z",
    status: "open",
  },
  {
    id: "ANO-0003",
    rule: "DUPLICATE_VENDOR",
    severity: "CRITICAL",
    description: "Multiple vendors share the same bank account: VEND-45, VEND-67",
    entity_type: "vendor",
    entity_id: "VEND-45",
    detected_at: "2026-03-31T14:20:00Z",
    status: "open",
  },
  {
    id: "ANO-0004",
    rule: "UNUSUAL_VENDOR",
    severity: "MEDIUM",
    description: "Large invoice INV-089 (12500.00) from first-time vendor 'New Supplies LLC'",
    entity_type: "invoice",
    entity_id: "INV-089",
    detected_at: "2026-03-30T11:00:00Z",
    status: "open",
  },
  {
    id: "ANO-0005",
    rule: "CONTRACT_BYPASS",
    severity: "HIGH",
    description: "Invoice INV-112 from contracted vendor 'Tech Giant Corp' has no contract reference",
    entity_type: "invoice",
    entity_id: "INV-112",
    detected_at: "2026-03-29T16:45:00Z",
    status: "open",
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function severityBadge(severity: Severity) {
  const styles: Record<Severity, string> = {
    CRITICAL: "bg-red-100 text-red-800 border border-red-300",
    HIGH: "bg-orange-100 text-orange-800 border border-orange-300",
    MEDIUM: "bg-yellow-100 text-yellow-800 border border-yellow-300",
    LOW: "bg-gray-100 text-gray-700 border border-gray-300",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${styles[severity]}`}
    >
      {severity}
    </span>
  );
}

function ruleBadge(rule: string) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800 border border-blue-200">
      {rule.replace(/_/g, " ")}
    </span>
  );
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnomalyDetectionPage() {
  const [anomalies, setAnomalies] = useState<Anomaly[]>(DEMO_ANOMALIES);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [isDemo, setIsDemo] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");

  const fetchHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch("/api/agentic/anomaly/history");
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      const list: Anomaly[] = Array.isArray(data)
        ? data
        : data.anomalies ?? data.results ?? [];
      setAnomalies(list.length > 0 ? list : DEMO_ANOMALIES);
      setIsDemo(list.length === 0);
    } catch {
      setAnomalies(DEMO_ANOMALIES);
      setIsDemo(true);
    } finally {
      setLoading(false);
    }
  };

  const runScan = async () => {
    setScanning(true);
    setScanMessage(null);
    setError(null);
    try {
      const res = await apiFetch("/api/agentic/anomaly/detect", {
        method: "POST",
        body: JSON.stringify({
          invoices: [],
          purchase_orders: [],
          vendors: [],
          contracts: [],
        }),
      });
      if (!res.ok) throw new Error(`Scan failed with status ${res.status}`);
      const data = await res.json();
      setScanMessage(
        data.message ?? `Scan complete. Found ${data.anomalies_found ?? 0} anomalies.`
      );
      // Refresh history after scan
      await fetchHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed. Using demo data.");
    } finally {
      setScanning(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  // Derived stats
  const total = anomalies.length;
  const critical = anomalies.filter((a) => a.severity === "CRITICAL").length;
  const high = anomalies.filter((a) => a.severity === "HIGH").length;
  const medium = anomalies.filter((a) => a.severity === "MEDIUM").length;

  const filtered =
    severityFilter === "ALL"
      ? anomalies
      : anomalies.filter((a) => a.severity === severityFilter);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-red-100 flex items-center justify-center">
            <Shield className="h-5 w-5 text-red-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Anomaly Detection</h1>
            <p className="text-sm text-muted-foreground">
              AI-powered procurement fraud & compliance anomaly detection
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {isDemo && (
            <Badge
              variant="secondary"
              className="bg-amber-100 text-amber-800 border border-amber-200"
            >
              Demo Data
            </Badge>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={fetchHistory}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Button
            size="sm"
            onClick={runScan}
            disabled={scanning}
            className="bg-red-600 hover:bg-red-700 text-white"
          >
            <Search className={`h-4 w-4 mr-2 ${scanning ? "animate-spin" : ""}`} />
            {scanning ? "Scanning..." : "Run Scan Now"}
          </Button>
        </div>
      </div>

      {/* Status messages */}
      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {error}
        </div>
      )}
      {scanMessage && (
        <div className="rounded-md bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-700">
          {scanMessage}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-blue-700">{total}</p>
            <p className="text-xs text-muted-foreground mt-1">Total Anomalies</p>
          </CardContent>
        </Card>
        <Card className="border-red-200">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-red-600">{critical}</p>
            <p className="text-xs text-muted-foreground mt-1">Critical</p>
          </CardContent>
        </Card>
        <Card className="border-orange-200">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-orange-600">{high}</p>
            <p className="text-xs text-muted-foreground mt-1">High</p>
          </CardContent>
        </Card>
        <Card className="border-yellow-200">
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-yellow-600">{medium}</p>
            <p className="text-xs text-muted-foreground mt-1">Medium</p>
          </CardContent>
        </Card>
      </div>

      {/* Table section */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              Detected Anomalies
            </CardTitle>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Filter:</span>
              <Select value={severityFilter} onValueChange={setSeverityFilter}>
                <SelectTrigger className="w-36 h-8 text-sm">
                  <SelectValue placeholder="All severities" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All Severities</SelectItem>
                  <SelectItem value="CRITICAL">Critical</SelectItem>
                  <SelectItem value="HIGH">High</SelectItem>
                  <SelectItem value="MEDIUM">Medium</SelectItem>
                  <SelectItem value="LOW">Low</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <RefreshCw className="h-5 w-5 animate-spin mr-2" />
              Loading anomalies...
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">ID</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Rule</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Severity</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Description</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Entity</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Detected At</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((anomaly) => (
                    <tr
                      key={anomaly.id}
                      className="border-t hover:bg-muted/30 transition-colors"
                    >
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground whitespace-nowrap">
                        {anomaly.id}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {ruleBadge(anomaly.rule)}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {severityBadge(anomaly.severity)}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground max-w-xs">
                        {anomaly.description}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="text-xs font-medium">
                          {anomaly.entity_type}
                        </span>
                        <span className="ml-1 text-xs text-muted-foreground font-mono">
                          {anomaly.entity_id}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground whitespace-nowrap">
                        {formatDate(anomaly.detected_at)}
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td
                        colSpan={6}
                        className="px-4 py-10 text-center text-muted-foreground"
                      >
                        <Shield className="h-8 w-8 text-green-400 mx-auto mb-2" />
                        No anomalies found for the selected filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
