import { useState } from "react";
import { useLocation } from "wouter";
import { ArrowLeft, Truck, Search, Loader2, AlertTriangle, CheckCircle2, Clock, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "@/lib/api";

type DeliveryStatus = "on_track" | "delayed" | "critical" | "delivered";

type DeliveryRecord = {
  po_number: string;
  vendor: string;
  item_description: string;
  expected_date: string;
  days_overdue: number;
  status: DeliveryStatus;
};

type TrackingResult = {
  po_number: string;
  overall_status: DeliveryStatus;
  deliveries: DeliveryRecord[];
  summary?: string;
};

function statusBadge(status: DeliveryStatus) {
  switch (status) {
    case "on_track":
      return <Badge className="bg-emerald-100 text-emerald-800 border border-emerald-300">On Track</Badge>;
    case "delayed":
      return <Badge className="bg-amber-100 text-amber-800 border border-amber-300">Delayed</Badge>;
    case "critical":
      return <Badge className="bg-red-100 text-red-800 border border-red-300">Critical</Badge>;
    case "delivered":
      return <Badge className="bg-blue-100 text-blue-800 border border-blue-300">Delivered</Badge>;
  }
}

function statusRowClass(status: DeliveryStatus) {
  switch (status) {
    case "on_track":  return "border-l-2 border-l-emerald-400";
    case "delayed":   return "border-l-2 border-l-amber-400";
    case "critical":  return "border-l-2 border-l-red-400";
    case "delivered": return "border-l-2 border-l-blue-400";
  }
}

function statusIcon(status: DeliveryStatus) {
  switch (status) {
    case "on_track":  return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
    case "delayed":   return <Clock className="h-4 w-4 text-amber-600" />;
    case "critical":  return <AlertTriangle className="h-4 w-4 text-red-600" />;
    case "delivered": return <CheckCircle2 className="h-4 w-4 text-blue-600" />;
  }
}

const MOCK_DELIVERIES: DeliveryRecord[] = [
  {
    po_number: "PO-2026-001",
    vendor: "Acme Supplies Inc.",
    item_description: "Office Chairs (x20), Standing Desks (x5)",
    expected_date: "2026-03-28",
    days_overdue: 5,
    status: "delayed",
  },
  {
    po_number: "PO-2026-002",
    vendor: "TechPro Solutions",
    item_description: "Laptops (x10), Monitors (x10)",
    expected_date: "2026-04-05",
    days_overdue: 0,
    status: "on_track",
  },
  {
    po_number: "PO-2025-091",
    vendor: "Office World",
    item_description: "Printer Cartridges (x100)",
    expected_date: "2025-12-15",
    days_overdue: 0,
    status: "delivered",
  },
];

export default function DeliveryTrackingPage() {
  const [, setLocation] = useLocation();
  const [poInput, setPoInput] = useState("PO-2026-001");
  const [isTracking, setIsTracking] = useState(false);
  const [result, setResult] = useState<TrackingResult | null>(null);
  const [trackError, setTrackError] = useState<string | null>(null);

  const handleTrack = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsTracking(true);
    setTrackError(null);
    setResult(null);

    const payload = {
      request_type: "delivery_tracking",
      po_number: poInput.trim(),
    };

    try {
      const res = await apiFetch("/api/agentic/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const data = await res.json();
        setResult({
          po_number: poInput.trim(),
          overall_status: data.overall_status || "on_track",
          deliveries: data.deliveries || buildMockResult(poInput.trim()),
          summary: data.summary,
        });
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch {
      // Mock result
      const deliveries = buildMockResult(poInput.trim());
      const overallStatus = deliveries.some(d => d.status === "critical")
        ? "critical"
        : deliveries.some(d => d.status === "delayed")
        ? "delayed"
        : deliveries.every(d => d.status === "delivered")
        ? "delivered"
        : "on_track";

      setResult({
        po_number: poInput.trim(),
        overall_status: overallStatus,
        deliveries,
      });
    } finally {
      setIsTracking(false);
    }
  };

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
            <Truck className="h-5 w-5" />
            <h1 className="text-lg font-semibold">Delivery Tracking</h1>
          </div>
        </div>
      </header>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4 max-w-5xl mx-auto">
          {/* Search bar */}
          <Card className="shadow-sm">
            <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
              <CardTitle>Track a Delivery</CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              <form onSubmit={handleTrack} className="flex items-end gap-3">
                <div className="flex-1 space-y-1">
                  <Label htmlFor="po_search">PO Number</Label>
                  <Input
                    id="po_search"
                    value={poInput}
                    onChange={e => setPoInput(e.target.value)}
                    placeholder="e.g. PO-2026-001"
                    required
                  />
                </div>
                <Button type="submit" disabled={isTracking} className="gap-2">
                  {isTracking ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4" />
                  )}
                  {isTracking ? "Tracking…" : "Track"}
                </Button>
              </form>
            </CardContent>
          </Card>

          {trackError && (
            <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
              {trackError}
            </div>
          )}

          {/* Result */}
          {result && (
            <Card className="shadow-sm">
              <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2">
                    {statusIcon(result.overall_status)}
                    Tracking Results for {result.po_number}
                  </CardTitle>
                  {statusBadge(result.overall_status)}
                </div>
                {result.summary && (
                  <p className="text-sm text-muted-foreground mt-1">{result.summary}</p>
                )}
              </CardHeader>
              <CardContent className="pt-4">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="py-2 pr-4">PO #</th>
                        <th className="pr-4">Vendor</th>
                        <th className="pr-4">Items</th>
                        <th className="pr-4">Expected Date</th>
                        <th className="pr-4">Days Overdue</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.deliveries.map((delivery, idx) => (
                        <tr key={idx} className={`border-b border-border/40 pl-2 ${statusRowClass(delivery.status)}`}>
                          <td className="py-2 pr-4 font-medium font-mono text-xs">{delivery.po_number}</td>
                          <td className="pr-4">{delivery.vendor}</td>
                          <td className="pr-4 text-muted-foreground max-w-[200px] truncate">{delivery.item_description}</td>
                          <td className="pr-4 text-xs">{delivery.expected_date}</td>
                          <td className="pr-4">
                            {delivery.days_overdue > 0 ? (
                              <span className={`font-semibold ${delivery.days_overdue >= 7 ? "text-red-600" : "text-amber-600"}`}>
                                +{delivery.days_overdue}d
                              </span>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                          <td>{statusBadge(delivery.status)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* All deliveries overview */}
          <Card className="shadow-sm">
            <CardHeader className="bg-gradient-to-r from-blue-50 to-white border-b">
              <CardTitle className="text-sm">All Active Deliveries</CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="py-2 pr-4">PO #</th>
                      <th className="pr-4">Vendor</th>
                      <th className="pr-4">Expected Date</th>
                      <th className="pr-4">Days Overdue</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {MOCK_DELIVERIES.map((delivery, idx) => (
                      <tr key={idx} className={`border-b border-border/40 ${statusRowClass(delivery.status)}`}>
                        <td className="py-2 pr-4 font-medium font-mono text-xs">{delivery.po_number}</td>
                        <td className="pr-4">{delivery.vendor}</td>
                        <td className="pr-4 text-xs">{delivery.expected_date}</td>
                        <td className="pr-4">
                          {delivery.days_overdue > 0 ? (
                            <span className={`font-semibold ${delivery.days_overdue >= 7 ? "text-red-600" : "text-amber-600"}`}>
                              +{delivery.days_overdue}d
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                        <td>{statusBadge(delivery.status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Legend */}
              <div className="flex flex-wrap gap-3 mt-4 pt-3 border-t">
                <div className="flex items-center gap-1 text-xs text-emerald-700">
                  <div className="h-3 w-3 rounded-full bg-emerald-400" /> On Track
                </div>
                <div className="flex items-center gap-1 text-xs text-amber-700">
                  <div className="h-3 w-3 rounded-full bg-amber-400" /> Delayed
                </div>
                <div className="flex items-center gap-1 text-xs text-red-700">
                  <div className="h-3 w-3 rounded-full bg-red-400" /> Critical
                </div>
                <div className="flex items-center gap-1 text-xs text-blue-700">
                  <div className="h-3 w-3 rounded-full bg-blue-400" /> Delivered
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
    </div>
  );
}

function buildMockResult(poNumber: string): DeliveryRecord[] {
  const found = MOCK_DELIVERIES.find(d => d.po_number.toLowerCase() === poNumber.toLowerCase());
  if (found) return [found];

  // Return a generic on-track result for unknown POs
  return [
    {
      po_number: poNumber,
      vendor: "Unknown Vendor",
      item_description: "See ERP for details",
      expected_date: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
      days_overdue: 0,
      status: "on_track",
    },
  ];
}
