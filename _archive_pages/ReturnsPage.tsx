import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Undo2, Plus, CheckCircle2, Truck, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  initiated: "bg-yellow-100 text-yellow-800",
  approved: "bg-blue-100 text-blue-800",
  shipped: "bg-purple-100 text-purple-800",
  credit_received: "bg-green-100 text-green-800",
};

export default function ReturnsPage() {
  const [returns, setReturns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [form, setForm] = useState({ grn_number: "", po_number: "", vendor_name: "", return_reason: "quality_failure", items_text: "" });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/api/rtv/list");
      const data = await res.json();
      setReturns(data.returns || []);
    } catch { }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleCreate = async () => {
    const items = form.items_text.split("\n").filter(l => l.trim()).map(line => {
      const parts = line.split(",").map(p => p.trim());
      return { item_name: parts[0], return_qty: parseFloat(parts[1]) || 1, unit_price: parseFloat(parts[2]) || 0, condition: "damaged" };
    });
    try {
      const res = await apiFetch("/api/rtv/create", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, items }),
      });
      const data = await res.json();
      setMsg({ text: `RTV ${data.rtv_number} created (credit: $${data.credit_expected})`, ok: data.success });
      setShowCreate(false); fetchData();
    } catch (e: any) { setMsg({ text: e.message, ok: false }); }
  };

  const handleAction = async (id: number, action: string) => {
    try {
      const res = await apiFetch(`/api/rtv/${id}/${action}`, { method: "POST" });
      const data = await res.json();
      setMsg({ text: `RTV ${action}d`, ok: data.success });
      fetchData();
    } catch { setMsg({ text: "Action failed", ok: false }); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold">Returns to Vendor</h1><p className="text-muted-foreground">Return damaged or incorrect goods</p></div>
      {/* Chat-driven banner */}
      <div className="rounded-lg border-2 border-blue-200 bg-blue-50 p-4 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-blue-900">This is managed by AI agents via Chat</p>
          <p className="text-xs text-blue-700 mt-1">Try: "Return [qty] damaged [items] from GRN-XXXX"</p>
        </div>
        <a href="/chat" className="px-3 py-1.5 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700">Open Chat</a>
      </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchData}><RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} /></Button>
          <Button size="sm" onClick={() => setShowCreate(!showCreate)}><Plus className="h-4 w-4 mr-1" /> New Return</Button>
        </div>
      </div>
      {msg && <div className={`rounded-md px-4 py-3 text-sm ${msg.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>{msg.text}</div>}
      {showCreate && (
        <Card>
          <CardHeader><CardTitle className="text-base">Create Return</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <input value={form.grn_number} onChange={e => setForm({ ...form, grn_number: e.target.value })} placeholder="GRN Number" className="border rounded px-3 py-2 text-sm" />
              <input value={form.po_number} onChange={e => setForm({ ...form, po_number: e.target.value })} placeholder="PO Number" className="border rounded px-3 py-2 text-sm" />
              <input value={form.vendor_name} onChange={e => setForm({ ...form, vendor_name: e.target.value })} placeholder="Vendor Name" className="border rounded px-3 py-2 text-sm" />
            </div>
            <select value={form.return_reason} onChange={e => setForm({ ...form, return_reason: e.target.value })} className="border rounded px-3 py-2 text-sm">
              <option value="quality_failure">Quality Failure</option>
              <option value="wrong_item">Wrong Item</option>
              <option value="damaged">Damaged in Transit</option>
              <option value="excess">Excess Quantity</option>
            </select>
            <textarea value={form.items_text} onChange={e => setForm({ ...form, items_text: e.target.value })} placeholder={"Items (name, qty, unit_price per line)\nDefective Widget, 5, 50\nWrong Part, 2, 120"} rows={3} className="w-full border rounded px-3 py-2 text-sm font-mono" />
            <Button onClick={handleCreate}><Undo2 className="h-4 w-4 mr-1" /> Create Return</Button>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Undo2 className="h-5 w-5" /> Returns ({returns.length})</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>RTV #</TableHead><TableHead>GRN</TableHead><TableHead>Vendor</TableHead>
              <TableHead>Reason</TableHead><TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Credit</TableHead><TableHead>Status</TableHead><TableHead>Actions</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {returns.map((r: any) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono text-sm">{r.rtv_number}</TableCell>
                  <TableCell>{r.grn_number}</TableCell>
                  <TableCell>{r.vendor_name}</TableCell>
                  <TableCell>{r.return_reason?.replace(/_/g, " ")}</TableCell>
                  <TableCell className="text-right">{r.total_return_qty}</TableCell>
                  <TableCell className="text-right">${r.credit_expected?.toLocaleString()}</TableCell>
                  <TableCell><Badge className={STATUS_COLORS[r.status] || "bg-gray-100"}>{r.status}</Badge></TableCell>
                  <TableCell className="space-x-1">
                    {r.status === "initiated" && <Button size="sm" variant="outline" onClick={() => handleAction(r.id, "approve")}><CheckCircle2 className="h-3 w-3 mr-1" /> Approve</Button>}
                    {r.status === "approved" && <Button size="sm" variant="outline" onClick={() => handleAction(r.id, "ship")}><Truck className="h-3 w-3 mr-1" /> Ship</Button>}
                  </TableCell>
                </TableRow>
              ))}
              {returns.length === 0 && <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground">No returns yet</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
