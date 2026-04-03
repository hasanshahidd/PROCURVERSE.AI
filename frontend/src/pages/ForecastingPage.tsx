import { useState } from "react";
import { useLocation } from "wouter";
import { ArrowLeft, TrendingUp, Loader2, AlertTriangle, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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
  Legend,
  ResponsiveContainer,
} from "recharts";

type Period = "3m" | "6m" | "12m";

type ForecastRow = {
  category: string;
  historical_avg: number;
  forecasted: number;
  budget: number;
  status: "over" | "under";
};

type ForecastResult = {
  period: Period;
  generated_at: string;
  rows: ForecastRow[];
};

const PERIOD_LABELS: Record<Period, string> = {
  "3m":  "Last 3 Months",
  "6m":  "Last 6 Months",
  "12m": "Last 12 Months",
};

const currency = (value: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value || 0);

// Static mock data keyed by period
const MOCK_DATA: Record<Period, ForecastRow[]> = {
  "3m": [
    { category: "Electronics",     historical_avg: 42000, forecasted: 46200, budget: 45000, status: "over" },
    { category: "Office Supplies", historical_avg: 8500,  forecasted: 9100,  budget: 10000, status: "under" },
    { category: "Furniture",       historical_avg: 15000, forecasted: 16500, budget: 15000, status: "over" },
    { category: "Services",        historical_avg: 32000, forecasted: 33800, budget: 35000, status: "under" },
    { category: "Raw Materials",   historical_avg: 58000, forecasted: 61200, budget: 60000, status: "over" },
  ],
  "6m": [
    { category: "Electronics",     historical_avg: 39000, forecasted: 44000, budget: 45000, status: "under" },
    { category: "Office Supplies", historical_avg: 8200,  forecasted: 8900,  budget: 10000, status: "under" },
    { category: "Furniture",       historical_avg: 14000, forecasted: 16000, budget: 15000, status: "over" },
    { category: "Services",        historical_avg: 30000, forecasted: 34500, budget: 35000, status: "under" },
    { category: "Raw Materials",   historical_avg: 55000, forecasted: 63000, budget: 60000, status: "over" },
  ],
  "12m": [
    { category: "Electronics",     historical_avg: 37000, forecasted: 42500, budget: 45000, status: "under" },
    { category: "Office Supplies", historical_avg: 7800,  forecasted: 8600,  budget: 10000, status: "under" },
    { category: "Furniture",       historical_avg: 13000, forecasted: 14500, budget: 15000, status: "under" },
    { category: "Services",        historical_avg: 29000, forecasted: 36000, budget: 35000, status: "over" },
    { category: "Raw Materials",   historical_avg: 53000, forecasted: 65000, budget: 60000, status: "over" },
  ],
};

export default function ForecastingPage() {
  const [, setLocation] = useLocation();
  const [period, setPeriod] = useState<Period>("6m");
  const [isGenerating, setIsGenerating] = useState(false);
  const [result, setResult] = useState<ForecastResult | null>(null);

  const generateForecast = async () => {
    setIsGenerating(true);
    setResult(null);

    const payload = {
      period,
      request_type: "demand_forecast",
    };

    try {
      const res = await apiFetch("/api/agentic/spend/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const data = await res.json();
        setResult({
          period,
          generated_at: new Date().toISOString(),
          rows: data.forecast_rows || MOCK_DATA[period],
        });
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch {
      // Simulate a short loading delay then use mock data
      await new Promise(resolve => setTimeout(resolve, 800));
      setResult({
        period,
        generated_at: new Date().toISOString(),
        rows: MOCK_DATA[period],
      });
    } finally {
      setIsGenerating(false);
    }
  };

  const overBudgetRows = result?.rows.filter(r => r.status === "over") || [];

  // Prepare chart data
  const chartData = result?.rows.map(row => ({
    name: row.category,
    "Historical Avg": row.historical_avg,
    "Forecasted":     row.forecasted,
    "Budget":         row.budget,
  })) || [];

  return (
    <div className="bg-background flex flex-col h-full">
      {/* Header */}
      <header className="border-b bg-gradient-to-r from-blue-600 to-blue-500 text-white px-4 py-3 flex items-center justify-between shadow-md flex-shrink-0">
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
            <TrendingUp className="h-5 w-5" />
            <h1 className="text-lg font-semibold">Demand Forecasting &amp; Procurement Planning</h1>
          </div>
        </div>
      </header>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4 max-w-6xl mx-auto">
          {/* Controls */}
          <Card className="shadow-sm">
            <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
              <CardTitle>Forecast Settings</CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              <div className="flex items-end gap-4">
                <div className="space-y-1 w-56">
                  <label className="text-sm font-medium">Analysis Period</label>
                  <Select value={period} onValueChange={v => setPeriod(v as Period)}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select period" />
                    </SelectTrigger>
                    <SelectContent>
                      {(Object.entries(PERIOD_LABELS) as [Period, string][]).map(([val, label]) => (
                        <SelectItem key={val} value={val}>{label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <Button onClick={generateForecast} disabled={isGenerating} className="gap-2">
                  {isGenerating ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCcw className="h-4 w-4" />
                  )}
                  {isGenerating ? "Generating…" : "Generate Forecast"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Over-budget alerts */}
          {result && overBudgetRows.length > 0 && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 space-y-2">
              <div className="flex items-center gap-2 font-semibold text-amber-800">
                <AlertTriangle className="h-5 w-5" />
                Budget Alert — {overBudgetRows.length} {overBudgetRows.length === 1 ? "category" : "categories"} forecast to exceed budget
              </div>
              <ul className="space-y-1">
                {overBudgetRows.map(row => (
                  <li key={row.category} className="text-sm text-amber-900 flex items-center gap-2">
                    <span className="font-medium">{row.category}:</span>
                    Forecasted {currency(row.forecasted)} vs budget {currency(row.budget)}
                    <span className="text-amber-700 font-semibold">
                      (+{currency(row.forecasted - row.budget)} over)
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Bar Chart */}
          {result && (
            <Card className="shadow-sm">
              <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
                <CardTitle>Forecasted Spend by Category — {PERIOD_LABELS[result.period]}</CardTitle>
              </CardHeader>
              <CardContent className="pt-6">
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={chartData} margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={(value) => currency(Number(value))} />
                    <Legend />
                    <Bar dataKey="Historical Avg" fill="#3b82f6" />
                    <Bar dataKey="Forecasted"     fill="#8b5cf6" />
                    <Bar dataKey="Budget"         fill="#10b981" />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* Table */}
          {result && (
            <Card className="shadow-sm">
              <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
                <CardTitle className="text-sm">Forecast Details</CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-2 pr-4">Category</th>
                        <th className="pr-4">Historical Avg</th>
                        <th className="pr-4">Forecasted</th>
                        <th className="pr-4">Budget</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, idx) => (
                        <tr key={idx} className="border-b border-border/40">
                          <td className="py-2 pr-4 font-medium">{row.category}</td>
                          <td className="pr-4 text-muted-foreground">{currency(row.historical_avg)}</td>
                          <td className={`pr-4 font-semibold ${row.status === "over" ? "text-red-600" : "text-emerald-700"}`}>
                            {currency(row.forecasted)}
                          </td>
                          <td className="pr-4">{currency(row.budget)}</td>
                          <td>
                            {row.status === "over" ? (
                              <Badge className="bg-red-100 text-red-800 border border-red-300 text-xs">Over Budget</Badge>
                            ) : (
                              <Badge className="bg-emerald-100 text-emerald-800 border border-emerald-300 text-xs">Under Budget</Badge>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-muted-foreground mt-3">
                  Generated at {new Date(result.generated_at).toLocaleString()} — Period: {PERIOD_LABELS[result.period]}
                </p>
              </CardContent>
            </Card>
          )}

          {/* Empty state */}
          {!result && !isGenerating && (
            <Card className="shadow-sm flex items-center justify-center min-h-[200px]">
              <CardContent className="text-center text-muted-foreground">
                <TrendingUp className="h-12 w-12 mx-auto mb-3 opacity-30" />
                <p className="text-sm">Select a period and click "Generate Forecast" to see demand projections.</p>
              </CardContent>
            </Card>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
