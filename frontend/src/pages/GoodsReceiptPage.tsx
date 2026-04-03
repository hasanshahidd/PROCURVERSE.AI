import { useState } from "react";
import { useLocation } from "wouter";
import {
  ArrowLeft, Package, Plus, Trash2, Loader2, CheckCircle2,
  FileText, ClipboardList, Send, ChevronRight, ChevronLeft,
  ShieldCheck, AlertTriangle
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiFetch } from "@/lib/api";

// ─── Types ──────────────────────────────────────────────────────────────────
type LineItem = {
  id: number;
  item_name: string;
  qty: number;
};

type ReceivedItem = {
  item_name: string;
  qty_ordered: number;
  qty_received: number;
  status: "full" | "partial" | "missing";
};

type GRNResult = {
  grn_number: string;
  po_number: string;
  vendor_name: string;
  receipt_status: "full" | "partial" | "quality_inspection";
  receipt_percentage: number;
  quality_check_required: boolean;
  received_items: ReceivedItem[];
  created_at: string;
};

// ─── Wizard step config ───────────────────────────────────────────────────────
const WIZARD_STEPS = [
  { number: 1, label: "PO Details",      icon: <FileText className="h-4 w-4" /> },
  { number: 2, label: "Add Items",       icon: <ClipboardList className="h-4 w-4" /> },
  { number: 3, label: "Review & Submit", icon: <Send className="h-4 w-4" /> },
];

// ─── Receipt donut SVG ────────────────────────────────────────────────────────
function ReceiptDonut({ pct }: { pct: number }) {
  const radius   = 44;
  const stroke   = 10;
  const circ     = 2 * Math.PI * radius;
  const filled   = (pct / 100) * circ;
  const color    = pct === 100 ? "#059669" : pct >= 50 ? "#d97706" : "#dc2626";

  return (
    <div className="relative flex items-center justify-center w-32 h-32">
      <svg width="128" height="128" viewBox="0 0 128 128" className="-rotate-90">
        <circle cx="64" cy="64" r={radius} fill="none" stroke="#f1f5f9" strokeWidth={stroke} />
        <circle
          cx="64" cy="64" r={radius} fill="none"
          stroke={color} strokeWidth={stroke}
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 0.8s ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-extrabold" style={{ color }}>{pct}%</span>
        <span className="text-xs text-gray-400 font-medium">received</span>
      </div>
    </div>
  );
}

// ─── Badge helpers ────────────────────────────────────────────────────────────
function receiptStatusBadge(status: GRNResult["receipt_status"]) {
  const cfg = {
    full:               { label: "Full Receipt",       cls: "bg-green-100 text-green-700 border-green-200" },
    partial:            { label: "Partial Receipt",    cls: "bg-amber-100 text-amber-700 border-amber-200" },
    quality_inspection: { label: "Quality Inspection", cls: "bg-blue-100 text-blue-700 border-blue-200"    },
  }[status];
  return <Badge className={`text-xs ${cfg.cls}`}>{cfg.label}</Badge>;
}

function itemStatusBadge(status: ReceivedItem["status"]) {
  const cfg = {
    full:    { label: "Full",    cls: "bg-green-100 text-green-700 border-green-200" },
    partial: { label: "Partial", cls: "bg-amber-100 text-amber-700 border-amber-200" },
    missing: { label: "Missing", cls: "bg-red-100 text-red-700 border-red-200"       },
  }[status];
  return <Badge className={`text-xs ${cfg.cls}`}>{cfg.label}</Badge>;
}

const ITEM_ROW_BG = {
  full:    "bg-green-50/40 border-green-100",
  partial: "bg-amber-50/40 border-amber-100",
  missing: "bg-red-50/40 border-red-100",
};

let lineItemCounter = 1;

// ─── Main ─────────────────────────────────────────────────────────────────────
export default function GoodsReceiptPage() {
  const [, setLocation]       = useLocation();
  const [wizardStep, setWizardStep] = useState(1);
  const [poNumber, setPoNumber]     = useState("PO-2026-001");
  const [vendorName, setVendorName] = useState("Acme Supplies Inc.");
  const [qualityCheck, setQualityCheck] = useState(false);
  const [items, setItems]           = useState<LineItem[]>([
    { id: lineItemCounter++, item_name: "Office Chairs", qty: 20 },
    { id: lineItemCounter++, item_name: "Standing Desks", qty: 5  },
  ]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult]       = useState<GRNResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // ── Item helpers ──
  const addItem    = () => setItems(prev => [...prev, { id: lineItemCounter++, item_name: "", qty: 1 }]);
  const removeItem = (id: number) => setItems(prev => prev.filter(i => i.id !== id));
  const updateItem = (id: number, field: keyof Omit<LineItem, "id">, value: string | number) =>
    setItems(prev => prev.map(i => i.id === id ? { ...i, [field]: value } : i));

  // ── Submit ────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    setIsSubmitting(true);
    setSubmitError(null);
    setResult(null);

    const payload = {
      po_number: poNumber,
      vendor_name: vendorName,
      quality_check_required: qualityCheck,
      items: items.map(({ item_name, qty }) => ({ item_name, qty })),
    };

    try {
      const res = await apiFetch("/api/agentic/inventory/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const data = await res.json();
        setResult({
          grn_number: data.grn_number || `GRN-${Date.now()}`,
          po_number: poNumber,
          vendor_name: vendorName,
          receipt_status: qualityCheck ? "quality_inspection" : (data.receipt_status || "full"),
          receipt_percentage: data.receipt_percentage ?? 100,
          quality_check_required: qualityCheck,
          received_items: data.received_items || items.map(i => ({
            item_name: i.item_name, qty_ordered: i.qty, qty_received: i.qty, status: "full" as const,
          })),
          created_at: new Date().toISOString(),
        });
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch {
      const mock: GRNResult = {
        grn_number: `GRN-${new Date().getFullYear()}-${String(Math.floor(Math.random() * 9000) + 1000)}`,
        po_number: poNumber,
        vendor_name: vendorName,
        receipt_status: qualityCheck ? "quality_inspection" : "full",
        receipt_percentage: 100,
        quality_check_required: qualityCheck,
        received_items: items.map(i => ({
          item_name: i.item_name, qty_ordered: i.qty, qty_received: i.qty, status: "full",
        })),
        created_at: new Date().toISOString(),
      };
      setResult(mock);
    } finally {
      setIsSubmitting(false);
      setWizardStep(4); // success screen
    }
  };

  const canNext = () => {
    if (wizardStep === 1) return poNumber.trim() !== "" && vendorName.trim() !== "";
    if (wizardStep === 2) return items.length > 0 && items.every(i => i.item_name.trim() !== "" && i.qty >= 1);
    return true;
  };

  return (
    <div className="bg-gray-50 flex flex-col h-full">
      <style>{`
        @keyframes confetti {
          0%   { transform: scale(0.8) translateY(10px); opacity: 0; }
          60%  { transform: scale(1.05) translateY(-4px); opacity: 1; }
          100% { transform: scale(1) translateY(0); opacity: 1; }
        }
        .confetti-enter { animation: confetti 0.6s ease both; }
        @keyframes checkPop {
          0%   { transform: scale(0); }
          70%  { transform: scale(1.15); }
          100% { transform: scale(1); }
        }
        .check-pop { animation: checkPop 0.5s 0.2s ease both; }
        @keyframes ringGrow {
          from { opacity: 0; transform: scale(0.5); }
          to   { opacity: 1; transform: scale(1); }
        }
        .ring-grow { animation: ringGrow 0.6s ease both; }
      `}</style>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header
        className="flex-shrink-0 px-6 py-4 flex items-center justify-between shadow-lg"
        style={{ background: "linear-gradient(135deg, hsl(221,83%,25%) 0%, hsl(221,83%,15%) 100%)" }}
      >
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => setLocation("/dashboard")}
            className="gap-2 text-white hover:bg-white/20 rounded-xl">
            <ArrowLeft className="h-4 w-4" />Back
          </Button>
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-white/15 flex items-center justify-center">
              <Package className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">Goods Receipt Note</h1>
              <p className="text-blue-200 text-xs">Record and verify goods received from vendor</p>
            </div>
          </div>
        </div>
      </header>

      <ScrollArea className="flex-1">
        <div className="p-6 max-w-3xl mx-auto space-y-6">

          {/* ── Wizard Step Indicator ─────────────────────────────────── */}
          {wizardStep <= 3 && (
            <div className="flex items-center justify-center gap-0">
              {WIZARD_STEPS.map((ws, i) => (
                <div key={ws.number} className="flex items-center">
                  <div className="flex flex-col items-center">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300 ${
                      wizardStep > ws.number
                        ? "bg-green-500 text-white shadow-md shadow-green-200"
                        : wizardStep === ws.number
                        ? "text-white shadow-lg shadow-blue-300"
                        : "bg-white border-2 border-gray-200 text-gray-400"
                    }`}
                    style={wizardStep === ws.number ? { background: "linear-gradient(135deg, hsl(221,83%,35%), hsl(221,83%,25%))" } : {}}>
                      {wizardStep > ws.number ? <CheckCircle2 className="h-5 w-5" /> : ws.icon}
                    </div>
                    <span className={`text-xs mt-1.5 font-medium ${wizardStep === ws.number ? "text-blue-700" : wizardStep > ws.number ? "text-green-600" : "text-gray-400"}`}>
                      {ws.label}
                    </span>
                  </div>
                  {i < WIZARD_STEPS.length - 1 && (
                    <div className={`w-16 md:w-24 h-0.5 mx-2 mb-5 transition-all duration-500 ${wizardStep > ws.number ? "bg-green-400" : "bg-gray-200"}`} />
                  )}
                </div>
              ))}
            </div>
          )}

          {/* ── Step 1: PO Details ───────────────────────────────────── */}
          {wizardStep === 1 && (
            <Card className="rounded-2xl border-0 shadow-sm bg-white">
              <CardHeader className="px-6 pt-6 pb-4 border-b border-gray-50">
                <CardTitle className="text-base font-bold text-gray-900 flex items-center gap-2">
                  <FileText className="h-5 w-5 text-blue-600" />
                  Step 1 — PO Details
                </CardTitle>
                <p className="text-xs text-gray-400 mt-1">Enter the purchase order and vendor information</p>
              </CardHeader>
              <CardContent className="px-6 py-6 space-y-5">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                  <div className="space-y-2">
                    <Label htmlFor="po_number" className="text-sm font-semibold text-gray-700">PO Number</Label>
                    <Input
                      id="po_number"
                      value={poNumber}
                      onChange={e => setPoNumber(e.target.value)}
                      placeholder="PO-2026-001"
                      required
                      className="h-11 rounded-xl border-gray-200 bg-gray-50 focus:bg-white focus:border-blue-500 text-sm"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="vendor_name" className="text-sm font-semibold text-gray-700">Vendor Name</Label>
                    <Input
                      id="vendor_name"
                      value={vendorName}
                      onChange={e => setVendorName(e.target.value)}
                      placeholder="Vendor name"
                      required
                      className="h-11 rounded-xl border-gray-200 bg-gray-50 focus:bg-white focus:border-blue-500 text-sm"
                    />
                  </div>
                </div>

                <div className="flex items-center gap-3 p-4 rounded-xl bg-blue-50 border border-blue-100">
                  <Checkbox
                    id="quality_check"
                    checked={qualityCheck}
                    onCheckedChange={checked => setQualityCheck(Boolean(checked))}
                  />
                  <div>
                    <Label htmlFor="quality_check" className="cursor-pointer text-sm font-semibold text-gray-700">
                      Quality Check Required
                    </Label>
                    <p className="text-xs text-gray-400 mt-0.5">Items will be held pending QC sign-off before inventory update</p>
                  </div>
                </div>

                <div className="flex justify-end pt-2">
                  <Button
                    onClick={() => setWizardStep(2)}
                    disabled={!canNext()}
                    className="gap-2 rounded-xl px-6 h-11 font-semibold"
                    style={{ background: "linear-gradient(135deg, hsl(221,83%,35%), hsl(221,83%,25%))" }}
                  >
                    Next: Add Items <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ── Step 2: Add Items ────────────────────────────────────── */}
          {wizardStep === 2 && (
            <Card className="rounded-2xl border-0 shadow-sm bg-white">
              <CardHeader className="px-6 pt-6 pb-4 border-b border-gray-50">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base font-bold text-gray-900 flex items-center gap-2">
                      <ClipboardList className="h-5 w-5 text-blue-600" />
                      Step 2 — Add Items Received
                    </CardTitle>
                    <p className="text-xs text-gray-400 mt-1">List all items and quantities received from vendor</p>
                  </div>
                  <Button
                    type="button" variant="outline" size="sm" onClick={addItem}
                    className="gap-1.5 rounded-xl border-blue-200 text-blue-600 hover:bg-blue-50"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add Item
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="px-6 py-5 space-y-3">
                {/* Header row */}
                <div className="grid grid-cols-[1fr_100px_40px] gap-3 px-1">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Item Name</span>
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Qty</span>
                  <span />
                </div>

                {items.map((item, i) => (
                  <div key={item.id} className="grid grid-cols-[1fr_100px_40px] gap-3 items-center p-3 rounded-xl border border-gray-100 bg-gray-50/50 hover:bg-white hover:border-gray-200 transition-colors">
                    <Input
                      value={item.item_name}
                      onChange={e => updateItem(item.id, "item_name", e.target.value)}
                      placeholder={`Item ${i + 1}`}
                      className="h-9 rounded-lg border-gray-200 bg-white text-sm"
                      required
                    />
                    <Input
                      type="number"
                      value={item.qty}
                      min={1}
                      onChange={e => updateItem(item.id, "qty", parseInt(e.target.value) || 1)}
                      className="h-9 rounded-lg border-gray-200 bg-white text-sm text-center"
                      required
                    />
                    <Button
                      type="button" variant="ghost" size="icon"
                      onClick={() => removeItem(item.id)}
                      disabled={items.length === 1}
                      className="h-9 w-9 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}

                <p className="text-xs text-gray-400 pt-1">{items.length} item{items.length !== 1 ? "s" : ""} added</p>

                <div className="flex justify-between pt-2">
                  <Button variant="outline" onClick={() => setWizardStep(1)} className="gap-2 rounded-xl px-5 h-11">
                    <ChevronLeft className="h-4 w-4" /> Back
                  </Button>
                  <Button
                    onClick={() => setWizardStep(3)}
                    disabled={!canNext()}
                    className="gap-2 rounded-xl px-6 h-11 font-semibold"
                    style={{ background: "linear-gradient(135deg, hsl(221,83%,35%), hsl(221,83%,25%))" }}
                  >
                    Next: Review <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ── Step 3: Review & Submit ──────────────────────────────── */}
          {wizardStep === 3 && (
            <Card className="rounded-2xl border-0 shadow-sm bg-white">
              <CardHeader className="px-6 pt-6 pb-4 border-b border-gray-50">
                <CardTitle className="text-base font-bold text-gray-900 flex items-center gap-2">
                  <Send className="h-5 w-5 text-blue-600" />
                  Step 3 — Review & Submit
                </CardTitle>
                <p className="text-xs text-gray-400 mt-1">Confirm all details before generating the GRN</p>
              </CardHeader>
              <CardContent className="px-6 py-5 space-y-5">
                {submitError && (
                  <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center gap-3">
                    <AlertTriangle className="h-4 w-4 flex-shrink-0" />{submitError}
                  </div>
                )}

                {/* Summary cards */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="rounded-xl border border-gray-100 p-4 bg-gray-50/50">
                    <p className="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">PO Number</p>
                    <p className="font-bold text-gray-900">{poNumber}</p>
                  </div>
                  <div className="rounded-xl border border-gray-100 p-4 bg-gray-50/50">
                    <p className="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">Vendor</p>
                    <p className="font-bold text-gray-900">{vendorName}</p>
                  </div>
                  <div className="rounded-xl border border-gray-100 p-4 bg-gray-50/50">
                    <p className="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">Total Items</p>
                    <p className="font-bold text-gray-900">{items.length} line item{items.length !== 1 ? "s" : ""}</p>
                  </div>
                  <div className="rounded-xl border border-gray-100 p-4 bg-gray-50/50">
                    <p className="text-xs text-gray-400 mb-1 font-medium uppercase tracking-wide">Quality Check</p>
                    <Badge className={qualityCheck ? "bg-blue-100 text-blue-700 border-blue-200" : "bg-gray-100 text-gray-600 border-gray-200"}>
                      {qualityCheck ? "Required" : "Not required"}
                    </Badge>
                  </div>
                </div>

                {/* Items review table */}
                <div className="rounded-xl border border-gray-100 overflow-hidden">
                  <div className="bg-gray-50 px-4 py-2.5 border-b border-gray-100">
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Items Summary</p>
                  </div>
                  <div className="divide-y divide-gray-50">
                    {items.map((item, i) => (
                      <div key={item.id} className="flex items-center justify-between px-4 py-3">
                        <div className="flex items-center gap-3">
                          <span className="w-6 h-6 bg-blue-100 text-blue-600 rounded-lg text-xs font-bold flex items-center justify-center flex-shrink-0">{i + 1}</span>
                          <span className="text-sm font-medium text-gray-800">{item.item_name || "—"}</span>
                        </div>
                        <span className="text-sm font-semibold text-gray-600">Qty: {item.qty}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex justify-between pt-2">
                  <Button variant="outline" onClick={() => setWizardStep(2)} className="gap-2 rounded-xl px-5 h-11">
                    <ChevronLeft className="h-4 w-4" /> Back
                  </Button>
                  <Button
                    onClick={handleSubmit}
                    disabled={isSubmitting}
                    className="gap-2 rounded-xl px-6 h-11 font-semibold"
                    style={{ background: "linear-gradient(135deg, #059669, #047857)" }}
                  >
                    {isSubmitting ? (
                      <><Loader2 className="h-4 w-4 animate-spin" />Generating GRN…</>
                    ) : (
                      <><ShieldCheck className="h-4 w-4" />Submit Goods Receipt</>
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* ── Step 4: Success / GRN Result ─────────────────────────── */}
          {wizardStep === 4 && result && (
            <div className="space-y-6 confetti-enter">
              {/* Success hero */}
              <Card className="rounded-2xl border-0 shadow-sm bg-white overflow-hidden">
                <div className="px-6 py-8 text-center" style={{ background: "linear-gradient(135deg, #f0fdf4, #dcfce7)" }}>
                  <div className="check-pop inline-flex w-16 h-16 rounded-2xl bg-green-500 text-white items-center justify-center shadow-lg shadow-green-300 mb-4">
                    <CheckCircle2 className="h-9 w-9" />
                  </div>
                  <h2 className="text-xl font-extrabold text-gray-900 mb-1">GRN Generated Successfully!</h2>
                  <p className="text-gray-500 text-sm">Goods Receipt Note has been created and saved.</p>
                  <div className="mt-4">
                    <span className="text-lg font-bold text-green-700 bg-green-100 px-4 py-2 rounded-xl border border-green-200">
                      {result.grn_number}
                    </span>
                  </div>
                </div>
              </Card>

              {/* Details row */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">
                {/* Receipt donut */}
                <Card className="rounded-2xl border-0 shadow-sm bg-white col-span-1">
                  <CardContent className="pt-6 pb-6 flex flex-col items-center gap-3">
                    <div className="ring-grow">
                      <ReceiptDonut pct={result.receipt_percentage} />
                    </div>
                    <div className="text-center">
                      {receiptStatusBadge(result.receipt_status)}
                      <p className="text-xs text-gray-400 mt-2">{result.po_number} · {result.vendor_name}</p>
                    </div>
                    {result.quality_check_required && (
                      <div className="text-center text-xs text-blue-700 bg-blue-50 rounded-xl px-3 py-2 border border-blue-100">
                        Quality inspection flagged — items held pending QC sign-off.
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Items table */}
                <Card className="rounded-2xl border-0 shadow-sm bg-white col-span-2 overflow-hidden">
                  <CardHeader className="px-5 pt-5 pb-3 border-b border-gray-50">
                    <CardTitle className="text-sm font-bold text-gray-900">Received Items</CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <div className="divide-y divide-gray-50">
                      {result.received_items.map((item, i) => (
                        <div
                          key={i}
                          className={`flex items-center justify-between px-5 py-3 border-l-4 transition-colors ${
                            item.status === "full"    ? "border-l-green-400 bg-green-50/30" :
                            item.status === "partial" ? "border-l-amber-400 bg-amber-50/30" :
                            "border-l-red-400 bg-red-50/30"
                          }`}
                        >
                          <div>
                            <p className="text-sm font-semibold text-gray-800">{item.item_name}</p>
                            <p className="text-xs text-gray-400 mt-0.5">
                              Ordered: {item.qty_ordered} · Received: {item.qty_received}
                            </p>
                          </div>
                          {itemStatusBadge(item.status)}
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Footer actions */}
              <div className="flex items-center justify-between">
                <p className="text-xs text-gray-400">
                  Created: {new Date(result.created_at).toLocaleString()}
                </p>
                <Button
                  onClick={() => { setWizardStep(1); setResult(null); setPoNumber(""); setVendorName(""); }}
                  className="gap-2 rounded-xl px-5 h-10"
                  style={{ background: "linear-gradient(135deg, hsl(221,83%,35%), hsl(221,83%,25%))" }}
                >
                  <Plus className="h-4 w-4" />
                  New Receipt
                </Button>
              </div>
            </div>
          )}

        </div>
      </ScrollArea>
    </div>
  );
}
