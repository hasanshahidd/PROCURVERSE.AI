import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { FileText, Plus, CheckCircle2, RefreshCw, Loader2, AlertTriangle } from "lucide-react";
import { apiFetch } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  pending_approval: "bg-yellow-100 text-yellow-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
};

export default function POAmendmentsPage() {
  const [amendments, setAmendments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [form, setForm] = useState({ po_number: "", amendment_type: "quantity_change", reason: "", old_value: "", new_value: "", amount_impact: 0 });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/api/amendments/list");
      const data = await res.json();
      setAmendments(data.amendments || []);
    } catch { }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleCreate = async () => {
    try {
      const res = await apiFetch("/api/amendments/create", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      setMsg({ text: `Amendment ${data.amendment_number} created (${data.requires_approval ? "needs approval" : "auto-approved"})`, ok: data.success });
      setShowCreate(false); fetchData();
    } catch (e: any) { setMsg({ text: e.message, ok: false }); }
  };

  const handleApprove = async (id: number) => {
    try {
      const res = await apiFetch(`/api/amendments/${id}/approve`, { method: "POST" });
      const data = await res.json();
      setMsg({ text: `Amendment approved`, ok: data.success });
      fetchData();
    } catch { setMsg({ text: "Approve failed", ok: false }); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">PO Amendments</h1>
          <p className="text-muted-foreground">Modify purchase orders — quantity, price, dates</p>
        </div>
      {/* Chat-driven banner */}
      <div className="rounded-lg border-2 border-blue-200 bg-blue-50 p-4 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-blue-900">This is managed by AI agents via Chat</p>
          <p className="text-xs text-blue-700 mt-1">Try: "Amend PO-XXXX quantity from X to Y"</p>
        </div>
        <a href="/chat" className="px-3 py-1.5 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700">Open Chat</a>
      </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchData}><RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} /> Refresh</Button>
          <Button size="sm" onClick={() => setShowCreate(!showCreate)}><Plus className="h-4 w-4 mr-1" /> New Amendment</Button>
        </div>
      </div>
      {msg && <div className={`rounded-md px-4 py-3 text-sm ${msg.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>{msg.text}</div>}
      {showCreate && (
        <Card>
          <CardHeader><CardTitle className="text-base">Create Amendment</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <input value={form.po_number} onChange={e => setForm({ ...form, po_number: e.target.value })} placeholder="PO Number" className="w-full border rounded px-3 py-2 text-sm" />
            <select value={form.amendment_type} onChange={e => setForm({ ...form, amendment_type: e.target.value })} className="border rounded px-3 py-2 text-sm">
              <option value="quantity_change">Quantity Change</option>
              <option value="price_change">Price Change</option>
              <option value="date_change">Delivery Date Change</option>
              <option value="item_add">Add Item</option>
              <option value="item_remove">Remove Item</option>
            </select>
            <div className="grid grid-cols-2 gap-3">
              <input value={form.old_value} onChange={e => setForm({ ...form, old_value: e.target.value })} placeholder="Old Value" className="border rounded px-3 py-2 text-sm" />
              <input value={form.new_value} onChange={e => setForm({ ...form, new_value: e.target.value })} placeholder="New Value" className="border rounded px-3 py-2 text-sm" />
            </div>
            <input value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} placeholder="Reason for change" className="w-full border rounded px-3 py-2 text-sm" />
            <input type="number" value={form.amount_impact} onChange={e => setForm({ ...form, amount_impact: parseFloat(e.target.value) || 0 })} placeholder="Amount Impact ($)" className="border rounded px-3 py-2 text-sm" />
            <Button onClick={handleCreate} disabled={!form.po_number}><FileText className="h-4 w-4 mr-1" /> Submit Amendment</Button>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><FileText className="h-5 w-5" /> Amendments ({amendments.length})</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Amendment #</TableHead><TableHead>PO #</TableHead><TableHead>Type</TableHead>
              <TableHead>Change</TableHead><TableHead>Impact</TableHead><TableHead>Status</TableHead><TableHead>Action</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {amendments.map((a: any) => (
                <TableRow key={a.id}>
                  <TableCell className="font-mono text-sm">{a.amendment_number}</TableCell>
                  <TableCell className="font-mono">{a.po_number}</TableCell>
                  <TableCell>{a.amendment_type?.replace(/_/g, " ")}</TableCell>
                  <TableCell className="text-sm">{a.old_value} &rarr; {a.new_value}</TableCell>
                  <TableCell>${a.amount_impact?.toLocaleString()}</TableCell>
                  <TableCell><Badge className={STATUS_COLORS[a.status] || "bg-gray-100"}>{a.status}</Badge></TableCell>
                  <TableCell>
                    {a.status === "pending_approval" && (
                      <Button size="sm" variant="outline" onClick={() => handleApprove(a.id)}><CheckCircle2 className="h-3 w-3 mr-1" /> Approve</Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {amendments.length === 0 && <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">No amendments yet</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
