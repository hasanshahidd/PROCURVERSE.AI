import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  FileText, Plus, Send, Award, BarChart3, RefreshCw, Loader2,
  CheckCircle2, Clock, Eye, ChevronDown, ChevronRight,
} from "lucide-react";
import { apiFetch } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-100 text-gray-800",
  sent: "bg-blue-100 text-blue-800",
  evaluation: "bg-purple-100 text-purple-800",
  awarded: "bg-green-100 text-green-800",
  closed: "bg-slate-100 text-slate-800",
};

interface RFQ {
  id: number; rfq_number: string; title: string; department: string;
  status: string; vendors_invited: number; quotes_received: number;
  winning_vendor_name: string | null; pr_number: string | null;
  submission_deadline: string; created_at: string;
}

interface Quote {
  quote_id: number; vendor_id: string; vendor_name: string; item_name: string;
  unit_price: number; lead_time_days: number; total_price: number;
  total_score: number; recommended: boolean;
}

export default function RFQPage() {
  const [rfqs, setRfqs] = useState<RFQ[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedRfq, setSelectedRfq] = useState<number | null>(null);
  const [comparison, setComparison] = useState<any>(null);
  const [compLoading, setCompLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [msg, setMsg] = useState<{text: string; ok: boolean} | null>(null);

  // Create form
  const [newTitle, setNewTitle] = useState("");
  const [newDept, setNewDept] = useState("IT");
  const [newItems, setNewItems] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const fetchRfqs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/api/rfq/list");
      const data = await res.json();
      setRfqs(data.rfqs || []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchRfqs(); }, [fetchRfqs]);

  const handleCreate = async () => {
    if (!newTitle) return;
    setCreating(true); setMsg(null);
    try {
      const items = newItems.split("\n").filter(l => l.trim()).map(line => {
        const parts = line.split(",").map(p => p.trim());
        return { item_name: parts[0] || line, quantity: parseFloat(parts[1]) || 1, estimated_price: parseFloat(parts[2]) || 0 };
      });
      const res = await apiFetch("/api/rfq/create", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle, department: newDept, items }),
      });
      const data = await res.json();
      if (data.success) {
        setMsg({ text: `RFQ ${data.rfq_number} created with ${data.lines_added} items`, ok: true });
        setShowCreate(false); setNewTitle(""); setNewItems("");
        fetchRfqs();
      } else {
        setMsg({ text: data.detail || "Failed", ok: false });
      }
    } catch (e: any) { setMsg({ text: e.message, ok: false }); }
    finally { setCreating(false); }
  };

  const handleSend = async (rfqId: number) => {
    try {
      const res = await apiFetch(`/api/rfq/${rfqId}/send`, { method: "POST" });
      const data = await res.json();
      setMsg({ text: `RFQ sent to vendors`, ok: data.success });
      fetchRfqs();
    } catch { setMsg({ text: "Send failed", ok: false }); }
  };

  const handleCompare = async (rfqId: number) => {
    if (selectedRfq === rfqId) { setSelectedRfq(null); setComparison(null); return; }
    setSelectedRfq(rfqId); setCompLoading(true);
    try {
      const res = await apiFetch(`/api/rfq/${rfqId}/compare`);
      const data = await res.json();
      setComparison(data);
    } catch { /* ignore */ }
    finally { setCompLoading(false); }
  };

  const handleAward = async (rfqId: number, vendorId: string, vendorName: string) => {
    try {
      const res = await apiFetch(`/api/rfq/${rfqId}/award`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vendor_id: vendorId, vendor_name: vendorName }),
      });
      const data = await res.json();
      setMsg({ text: `Awarded to ${vendorName}. PO: ${data.po_number || 'pending'}`, ok: data.success });
      fetchRfqs(); setSelectedRfq(null); setComparison(null);
    } catch { setMsg({ text: "Award failed", ok: false }); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Request for Quotation (RFQ)</h1>
          <p className="text-muted-foreground">Create RFQs, collect vendor quotes, compare and award</p>
        </div>
      {/* Chat-driven banner */}
      <div className="rounded-lg border-2 border-blue-200 bg-blue-50 p-4 flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-blue-900">This is managed by AI agents via Chat</p>
          <p className="text-xs text-blue-700 mt-1">Try: "Create RFQ for [items] and invite [vendors]"</p>
        </div>
        <a href="/chat" className="px-3 py-1.5 rounded-md bg-blue-600 text-white text-sm hover:bg-blue-700">Open Chat</a>
      </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchRfqs}>
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button size="sm" onClick={() => setShowCreate(!showCreate)}>
            <Plus className="h-4 w-4 mr-1" /> New RFQ
          </Button>
        </div>
      </div>

      {msg && (
        <div className={`rounded-md px-4 py-3 text-sm flex items-center gap-2 ${msg.ok ? "bg-green-50 border border-green-200 text-green-700" : "bg-red-50 border border-red-200 text-red-700"}`}>
          {msg.ok ? <CheckCircle2 className="h-4 w-4" /> : <Clock className="h-4 w-4" />}
          {msg.text}
        </div>
      )}

      {/* Create RFQ Form */}
      {showCreate && (
        <Card>
          <CardHeader><CardTitle className="text-base">Create New RFQ</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <input value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="RFQ Title (e.g., '100 Dell Laptops for IT')" className="w-full border rounded px-3 py-2 text-sm" />
            <select value={newDept} onChange={e => setNewDept(e.target.value)} className="border rounded px-3 py-2 text-sm">
              <option>IT</option><option>Engineering</option><option>Operations</option><option>Finance</option><option>HR</option><option>Procurement</option>
            </select>
            <textarea value={newItems} onChange={e => setNewItems(e.target.value)} placeholder={"Items (one per line: name, quantity, estimated price)\nDell Latitude 5540, 80, 1200\nDell Latitude 7440, 20, 1800"} rows={4} className="w-full border rounded px-3 py-2 text-sm font-mono" />
            <Button onClick={handleCreate} disabled={creating || !newTitle}>
              {creating ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <FileText className="h-4 w-4 mr-1" />}
              {creating ? "Creating..." : "Create RFQ"}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* RFQ List */}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><FileText className="h-5 w-5" /> RFQs ({rfqs.length})</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>RFQ #</TableHead>
                <TableHead>Title</TableHead>
                <TableHead>Dept</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-center">Quotes</TableHead>
                <TableHead>Winner</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rfqs.map(rfq => (
                <TableRow key={rfq.id} className={selectedRfq === rfq.id ? "bg-blue-50" : ""}>
                  <TableCell className="font-mono text-sm">{rfq.rfq_number}</TableCell>
                  <TableCell className="max-w-[200px] truncate">{rfq.title}</TableCell>
                  <TableCell>{rfq.department}</TableCell>
                  <TableCell><Badge className={STATUS_COLORS[rfq.status] || "bg-gray-100"}>{rfq.status}</Badge></TableCell>
                  <TableCell className="text-center">{rfq.quotes_received}</TableCell>
                  <TableCell>{rfq.winning_vendor_name || "—"}</TableCell>
                  <TableCell className="space-x-1">
                    {rfq.status === "draft" && (
                      <Button size="sm" variant="outline" onClick={() => handleSend(rfq.id)}>
                        <Send className="h-3 w-3 mr-1" /> Send
                      </Button>
                    )}
                    {(rfq.status === "evaluation" || rfq.quotes_received > 0) && (
                      <Button size="sm" variant="outline" onClick={() => handleCompare(rfq.id)}>
                        <BarChart3 className="h-3 w-3 mr-1" /> Compare
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => handleCompare(rfq.id)}>
                      {selectedRfq === rfq.id ? <ChevronDown className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {rfqs.length === 0 && (
                <TableRow><TableCell colSpan={7} className="text-center py-8 text-muted-foreground">No RFQs yet. Create one above.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Quote Comparison */}
      {selectedRfq && comparison && (
        <Card className="border-blue-200 border-2">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-blue-600" />
              Quote Comparison — {comparison.rfq?.rfq_number}
              {comparison.recommendation && (
                <Badge className="bg-green-100 text-green-800 ml-2">
                  Recommended: {comparison.recommendation.vendor_name} (score {comparison.recommendation.score})
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {compLoading ? (
              <div className="flex items-center justify-center py-8"><Loader2 className="h-6 w-6 animate-spin" /></div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Vendor</TableHead>
                    <TableHead>Item</TableHead>
                    <TableHead className="text-right">Unit Price</TableHead>
                    <TableHead className="text-right">Lead Time</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead className="text-right">Score</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(comparison.quotes || []).map((q: Quote, i: number) => (
                    <TableRow key={i} className={q.recommended ? "bg-green-50" : ""}>
                      <TableCell className="font-medium">{q.vendor_name} {q.recommended && <Badge className="bg-green-600 text-white text-[10px] ml-1">Best</Badge>}</TableCell>
                      <TableCell>{q.item_name}</TableCell>
                      <TableCell className="text-right font-mono">${q.unit_price.toLocaleString()}</TableCell>
                      <TableCell className="text-right">{q.lead_time_days}d</TableCell>
                      <TableCell className="text-right font-mono">${q.total_price.toLocaleString()}</TableCell>
                      <TableCell className="text-right font-bold">{q.total_score}</TableCell>
                      <TableCell>
                        {comparison.rfq?.status !== "awarded" && (
                          <Button size="sm" variant="outline" onClick={() => handleAward(selectedRfq!, q.vendor_id, q.vendor_name)}>
                            <Award className="h-3 w-3 mr-1" /> Award
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
