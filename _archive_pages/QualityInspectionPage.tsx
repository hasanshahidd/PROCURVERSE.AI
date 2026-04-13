import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ClipboardCheck, RefreshCw, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { apiFetch } from "@/lib/api";

export default function QualityInspectionPage() {
  const [templates, setTemplates] = useState<any[]>([]);
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showInspect, setShowInspect] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [form, setForm] = useState({ grn_number: "", po_number: "", template_id: 0, item_name: "", inspector: "" });
  const [checklist, setChecklist] = useState<any[]>([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [tRes, rRes] = await Promise.all([
        apiFetch("/api/qc/templates"),
        apiFetch("/api/qc/results"),
      ]);
      const tData = await tRes.json();
      const rData = await rRes.json();
      setTemplates(tData.templates || []);
      setResults(rData.results || []);
    } catch { }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const selectTemplate = (id: number) => {
    setForm({ ...form, template_id: id });
    const t = templates.find(t => t.id === id);
    if (t) {
      const items = Array.isArray(t.checklist_items) ? t.checklist_items : JSON.parse(t.checklist_items || "[]");
      setChecklist(items.map((item: any) => ({ ...item, passed: true, notes: "" })));
    }
  };

  const handleInspect = async () => {
    try {
      const res = await apiFetch("/api/qc/inspect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          checklist_results: checklist.map(c => ({ passed: c.passed, notes: c.notes })),
        }),
      });
      const data = await res.json();
      const icon = data.pass_fail === "pass" ? "PASS" : "FAIL";
      setMsg({ text: `QC ${icon}: Score ${data.score}% (threshold ${data.threshold}%)${data.hold_goods ? " - GOODS ON HOLD" : ""}${data.trigger_rtv ? " - RTV TRIGGERED" : ""}`, ok: data.pass_fail === "pass" });
      setShowInspect(false); fetchData();
    } catch (e: any) { setMsg({ text: e.message, ok: false }); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold">Quality Inspection</h1><p className="text-muted-foreground">Run QC checklists on received goods</p></div>
      {/* Chat-driven banner */}
      <div className="rounded-lg border-2 border-blue-200 bg-blue-50 p-4 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-blue-900">This is managed by AI agents via Chat</p>
          <p className="text-xs text-blue-700 mt-1">Try: "Run quality inspection on GRN-XXXX"</p>
        </div>
        <a href="/chat" className="px-3 py-1.5 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700">Open Chat</a>
      </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchData}><RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} /></Button>
          <Button size="sm" onClick={() => setShowInspect(!showInspect)}><ClipboardCheck className="h-4 w-4 mr-1" /> New Inspection</Button>
        </div>
      </div>
      {msg && <div className={`rounded-md px-4 py-3 text-sm ${msg.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>{msg.text}</div>}

      {showInspect && (
        <Card>
          <CardHeader><CardTitle className="text-base">Run Inspection</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <input value={form.grn_number} onChange={e => setForm({ ...form, grn_number: e.target.value })} placeholder="GRN Number" className="border rounded px-3 py-2 text-sm" />
              <input value={form.item_name} onChange={e => setForm({ ...form, item_name: e.target.value })} placeholder="Item Name" className="border rounded px-3 py-2 text-sm" />
              <input value={form.inspector} onChange={e => setForm({ ...form, inspector: e.target.value })} placeholder="Inspector Name" className="border rounded px-3 py-2 text-sm" />
            </div>
            <div>
              <p className="text-sm font-medium mb-2">Select Template:</p>
              <div className="flex flex-wrap gap-2">
                {templates.map(t => (
                  <Button key={t.id} size="sm" variant={form.template_id === t.id ? "default" : "outline"} onClick={() => selectTemplate(t.id)}>
                    {t.template_name}
                  </Button>
                ))}
              </div>
            </div>
            {checklist.length > 0 && (
              <div className="space-y-2 border rounded-lg p-4">
                <p className="text-sm font-semibold">Checklist:</p>
                {checklist.map((item, i) => (
                  <div key={i} className="flex items-center gap-3 py-1">
                    <input type="checkbox" checked={item.passed} onChange={e => {
                      const updated = [...checklist]; updated[i] = { ...updated[i], passed: e.target.checked }; setChecklist(updated);
                    }} className="h-4 w-4" />
                    <span className="text-sm flex-1">{item.item} <span className="text-muted-foreground">(weight: {item.weight})</span></span>
                    <input value={item.notes} onChange={e => {
                      const updated = [...checklist]; updated[i] = { ...updated[i], notes: e.target.value }; setChecklist(updated);
                    }} placeholder="Notes" className="border rounded px-2 py-1 text-xs w-32" />
                  </div>
                ))}
                <Button onClick={handleInspect} className="mt-3"><ClipboardCheck className="h-4 w-4 mr-1" /> Submit Inspection</Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Templates */}
      <Card>
        <CardHeader><CardTitle className="text-sm">QC Templates ({templates.length})</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {templates.map(t => (
              <div key={t.id} className="border rounded-lg p-3 space-y-1">
                <p className="font-medium text-sm">{t.template_name}</p>
                <Badge variant="outline" className="text-[10px]">{t.category}</Badge>
                <p className="text-xs text-muted-foreground">Pass threshold: {t.pass_threshold}%</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><ClipboardCheck className="h-5 w-5" /> Results ({results.length})</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>GRN</TableHead><TableHead>Item</TableHead><TableHead>Inspector</TableHead>
              <TableHead className="text-right">Score</TableHead><TableHead>Result</TableHead><TableHead>Hold</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {results.map((r: any) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono text-sm">{r.grn_number}</TableCell>
                  <TableCell>{r.item_name}</TableCell>
                  <TableCell>{r.inspector}</TableCell>
                  <TableCell className="text-right font-bold">{r.total_score}%</TableCell>
                  <TableCell>
                    <Badge className={r.pass_fail === "pass" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}>
                      {r.pass_fail === "pass" ? <><CheckCircle2 className="h-3 w-3 mr-1" />PASS</> : <><XCircle className="h-3 w-3 mr-1" />FAIL</>}
                    </Badge>
                  </TableCell>
                  <TableCell>{r.hold_goods && <Badge className="bg-orange-100 text-orange-800"><AlertTriangle className="h-3 w-3 mr-1" />HELD</Badge>}</TableCell>
                </TableRow>
              ))}
              {results.length === 0 && <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">No inspections yet</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
