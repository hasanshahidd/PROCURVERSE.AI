import { useState, useEffect } from "react";
import { AlertTriangle, RefreshCcw, ShieldCheck, TrendingDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
} from "recharts";

// ─── Types ────────────────────────────────────────────────────────────────────

type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
type ImpactLevel = "low" | "medium" | "high";

interface RiskFactor {
  factor: string;
  score: number;
  weight: string;
  impact: ImpactLevel;
  recommendation: string;
}

interface RiskResult {
  vendor: string;
  overall_score: number;
  risk_level: RiskLevel;
  price_risk?: number;
  delivery_risk?: number;
  compliance_risk?: number;
  supply_risk?: number;
  factors: RiskFactor[];
}

interface Vendor {
  id: string | number;
  name: string;
}

// ─── Demo data ────────────────────────────────────────────────────────────────

const DEMO_RISK: RiskResult = {
  vendor: "Maintenance Pro",
  overall_score: 67,
  risk_level: "MEDIUM",
  price_risk: 72,
  delivery_risk: 58,
  compliance_risk: 75,
  supply_risk: 45,
  factors: [
    { factor: "Price Competitiveness", score: 72, weight: "30%", impact: "medium", recommendation: "Negotiate annual price lock" },
    { factor: "Delivery Reliability", score: 58, weight: "25%", impact: "high", recommendation: "Add delivery SLA clause to contract" },
    { factor: "Financial Stability", score: 80, weight: "20%", impact: "low", recommendation: "Annual financial review" },
    { factor: "Compliance", score: 75, weight: "15%", impact: "medium", recommendation: "Verify ISO certifications" },
    { factor: "Single-Source Risk", score: 45, weight: "10%", impact: "high", recommendation: "Identify alternative suppliers" },
  ],
};

const DEMO_TREND = [
  { month: "Oct", score: 74 },
  { month: "Nov", score: 70 },
  { month: "Dec", score: 68 },
  { month: "Jan", score: 72 },
  { month: "Feb", score: 65 },
  { month: "Mar", score: 67 },
];

const CATEGORIES = [
  "Electronics",
  "Office Supplies",
  "Raw Materials",
  "Services",
  "Machinery",
  "Maintenance",
  "Logistics",
];

const SCOPE_OPTIONS = [
  { id: "price_risk", label: "Price Risk" },
  { id: "delivery_risk", label: "Delivery Risk" },
  { id: "compliance_risk", label: "Compliance Risk" },
  { id: "single_source", label: "Single-Source Risk" },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function riskBadge(level: RiskLevel) {
  const map: Record<RiskLevel, string> = {
    LOW: "bg-green-100 text-green-800 border-green-300",
    MEDIUM: "bg-amber-100 text-amber-800 border-amber-300",
    HIGH: "bg-red-100 text-red-800 border-red-300",
    CRITICAL: "bg-red-900 text-white border-red-900",
  };
  return (
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-bold border ${map[level]}`}>
      {level}
    </span>
  );
}

function impactBadge(impact: ImpactLevel) {
  const map: Record<ImpactLevel, string> = {
    low: "bg-green-100 text-green-800",
    medium: "bg-amber-100 text-amber-800",
    high: "bg-red-100 text-red-800",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${map[impact]}`}>
      {impact}
    </span>
  );
}

function ScoreRing({ score, label }: { score: number; label: string }) {
  const radius = 48;
  const circumference = 2 * Math.PI * radius;
  // Lower score = higher risk, so we invert for display color
  const riskColor = score <= 40 ? "#dc2626" : score <= 60 ? "#d97706" : score <= 75 ? "#ca8a04" : "#16a34a";
  const filled = (score / 100) * circumference;

  return (
    <div className="flex flex-col items-center">
      <svg width="120" height="120" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r={radius} fill="none" stroke="#e5e7eb" strokeWidth="10" />
        <circle
          cx="60" cy="60" r={radius} fill="none"
          stroke={riskColor} strokeWidth="10"
          strokeDasharray={`${filled} ${circumference - filled}`}
          strokeLinecap="round"
          transform="rotate(-90 60 60)"
        />
        <text x="60" y="57" textAnchor="middle" fontSize="22" fontWeight="700" fill={riskColor}>{score}</text>
        <text x="60" y="72" textAnchor="middle" fontSize="10" fill="#6b7280">/ 100</text>
      </svg>
      <p className="text-xs text-center text-muted-foreground mt-1 max-w-[100px]">{label}</p>
    </div>
  );
}

function MiniScoreCard({ label, score }: { label: string; score: number }) {
  const color = score <= 40 ? "text-red-600" : score <= 60 ? "text-amber-600" : "text-green-700";
  return (
    <Card>
      <CardContent className="p-3 text-center">
        <p className={`text-xl font-bold ${color}`}>{score}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </CardContent>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function RiskAssessmentPage() {
  const [vendorName, setVendorName] = useState("");
  const [selectedVendor, setSelectedVendor] = useState("");
  const [category, setCategory] = useState("");
  const [scope, setScope] = useState<string[]>(["price_risk", "delivery_risk", "compliance_risk", "single_source"]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [result, setResult] = useState<RiskResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [assessed, setAssessed] = useState(false);
  const [isDemo, setIsDemo] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch("/api/odoo/vendors");
        if (!res.ok) throw new Error();
        const data = await res.json();
        setVendors(Array.isArray(data) ? data : data.vendors || []);
      } catch {
        // silently leave vendors empty
      }
    })();
  }, []);

  const toggleScope = (id: string) => {
    setScope((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  };

  const runAssessment = async () => {
    const targetVendor = selectedVendor || vendorName;
    if (!targetVendor) return;
    setLoading(true);
    setAssessed(false);

    try {
      const res = await apiFetch("/api/agentic/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_type: "risk_assessment",
          vendor_name: targetVendor,
          category,
        }),
      });
      if (!res.ok) throw new Error("Non-OK response");
      const data = await res.json();
      setResult(data);
      setIsDemo(false);
    } catch {
      setResult({ ...DEMO_RISK, vendor: targetVendor || DEMO_RISK.vendor });
      setIsDemo(true);
    } finally {
      setLoading(false);
      setAssessed(true);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-lg bg-red-100 flex items-center justify-center">
          <AlertTriangle className="h-5 w-5 text-red-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Procurement Risk Assessment</h1>
          <p className="text-sm text-muted-foreground">WF-16 — Vendor & supply chain risk analysis</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Assessment Form */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-base">Run Assessment</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Vendor name input */}
            <div className="space-y-1.5">
              <Label htmlFor="vendor-name">Vendor Name</Label>
              <Input
                id="vendor-name"
                placeholder="Type vendor name..."
                value={vendorName}
                onChange={(e) => setVendorName(e.target.value)}
              />
            </div>

            {/* Or pick from dropdown */}
            {vendors.length > 0 && (
              <div className="space-y-1.5">
                <Label>Or Select from List</Label>
                <Select value={selectedVendor} onValueChange={setSelectedVendor}>
                  <SelectTrigger>
                    <SelectValue placeholder="Choose vendor..." />
                  </SelectTrigger>
                  <SelectContent>
                    {vendors.map((v) => (
                      <SelectItem key={String(v.id)} value={v.name}>
                        {v.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Category */}
            <div className="space-y-1.5">
              <Label>Category</Label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger>
                  <SelectValue placeholder="Select category..." />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c.toLowerCase()}>{c}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Assessment Scope */}
            <div className="space-y-2">
              <Label>Assessment Scope</Label>
              <div className="space-y-2">
                {SCOPE_OPTIONS.map((opt) => (
                  <label key={opt.id} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={scope.includes(opt.id)}
                      onChange={() => toggleScope(opt.id)}
                      className="h-4 w-4 rounded border-gray-300"
                    />
                    <span className="text-sm">{opt.label}</span>
                  </label>
                ))}
              </div>
            </div>

            <Button
              onClick={runAssessment}
              disabled={loading || (!vendorName && !selectedVendor)}
              className="w-full"
            >
              {loading ? (
                <><RefreshCcw className="h-4 w-4 mr-2 animate-spin" />Assessing...</>
              ) : (
                <><ShieldCheck className="h-4 w-4 mr-2" />Run Assessment</>
              )}
            </Button>

            {isDemo && assessed && (
              <p className="text-xs text-center text-amber-600 bg-amber-50 rounded p-2">
                Demo data shown — backend unavailable
              </p>
            )}
          </CardContent>
        </Card>

        {/* Results Panel */}
        <div className="lg:col-span-2 space-y-6">
          {assessed && result ? (
            <>
              {/* Score Display */}
              <Card>
                <CardContent className="pt-6">
                  <div className="flex flex-col sm:flex-row items-center gap-6">
                    <ScoreRing score={result.overall_score} label="Overall Risk Score" />
                    <div className="flex-1 space-y-3">
                      <div className="flex items-center gap-3">
                        <h3 className="text-xl font-bold">{result.vendor}</h3>
                        {riskBadge(result.risk_level)}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        A score below 60 indicates elevated risk. Immediate attention may be required.
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        {result.price_risk !== undefined && (
                          <MiniScoreCard label="Price Risk" score={result.price_risk} />
                        )}
                        {result.delivery_risk !== undefined && (
                          <MiniScoreCard label="Delivery Risk" score={result.delivery_risk} />
                        )}
                        {result.compliance_risk !== undefined && (
                          <MiniScoreCard label="Compliance Risk" score={result.compliance_risk} />
                        )}
                        {result.supply_risk !== undefined && (
                          <MiniScoreCard label="Supply Risk" score={result.supply_risk} />
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Risk Factors Table */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Risk Factors</CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <ScrollArea className="h-[260px]">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50 sticky top-0">
                        <tr>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Factor</th>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Score</th>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Weight</th>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Impact</th>
                          <th className="text-left px-4 py-2 font-medium text-muted-foreground">Recommendation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.factors.map((f, i) => (
                          <tr key={i} className="border-t hover:bg-muted/30 transition-colors">
                            <td className="px-4 py-3 font-medium">{f.factor}</td>
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-2">
                                <Progress value={f.score} className="h-1.5 w-16" />
                                <span className="text-xs font-medium">{f.score}</span>
                              </div>
                            </td>
                            <td className="px-4 py-3 text-muted-foreground">{f.weight}</td>
                            <td className="px-4 py-3">{impactBadge(f.impact)}</td>
                            <td className="px-4 py-3 text-muted-foreground text-xs">{f.recommendation}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </ScrollArea>
                </CardContent>
              </Card>

              {/* Risk Trend Chart */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base flex items-center gap-2">
                    <TrendingDown className="h-4 w-4 text-red-500" />
                    Risk Score Trend (Last 6 Months)
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={180}>
                    <LineChart data={DEMO_TREND} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Line
                        type="monotone"
                        dataKey="score"
                        stroke="#ef4444"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                        name="Risk Score"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full min-h-[300px] text-center text-muted-foreground space-y-3">
              <AlertTriangle className="h-12 w-12 text-gray-300" />
              <p className="text-lg font-medium">No Assessment Yet</p>
              <p className="text-sm">Enter a vendor name and click "Run Assessment" to begin analysis.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
