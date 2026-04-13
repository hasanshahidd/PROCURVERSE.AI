import { useState, useEffect, useCallback, useMemo } from "react";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Scale, Play, RefreshCw, CheckCircle2, AlertTriangle, FileSpreadsheet, Workflow, ArrowRight, Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useSession } from "@/hooks/useSession";

// Read ?session=:id from URL — if present, this page enters session-observer mode
function readSessionIdFromUrl(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const params = new URLSearchParams(window.location.search);
  const sid = params.get("session");
  return sid && sid.trim() ? sid.trim() : undefined;
}

export default function ReconciliationPage() {
  const [, setLocation] = useLocation();
  const sessionId = useMemo(() => readSessionIdFromUrl(), []);
  const {
    session,
    gate,
    status: sessionStatus,
    currentPhase,
    loading: sessionLoading,
    resume,
  } = useSession(sessionId);
  const inSessionMode = !!sessionId;

  // Future-ready: when HF-3 extracts three_way_match into a dedicated gate,
  // this branch will render the actual match-confirmation UI. Until then, the
  // page is observer-only when mounted with ?session=:id.
  const matchGate =
    inSessionMode && gate?.gate_type === "three_way_match" ? gate : null;
  const inMatchPhase =
    inSessionMode &&
    (currentPhase === "invoice_matching" ||
      currentPhase === "three_way_match" ||
      currentPhase === "payment_readiness" ||
      currentPhase === "payment_execution" ||
      currentPhase === "completed");
  const summary = (session?.request_summary as Record<string, any>) || {};
  const sessionPrData = (summary.pr_data as Record<string, any>) || {};

  const [results, setResults] = useState<any[]>([]);
  const [exceptions, setExceptions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function handleConfirmMatch() {
    if (!matchGate) return;
    setConfirming(true);
    try {
      const result = await resume(matchGate.gate_id, "confirm_match", {
        confirmed_by: "Finance (UI)",
        notes: "3-way match confirmed from Reconciliation page",
      });
      if (!result.success) {
        setMsg({ text: `Failed to confirm match: ${result.error}`, ok: false });
      }
    } finally {
      setConfirming(false);
    }
  }

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [rRes, eRes] = await Promise.all([
        apiFetch("/api/reconciliation/results"),
        apiFetch("/api/reconciliation/exceptions"),
      ]);
      const rData = await rRes.json();
      const eData = await eRes.json();
      setResults(rData.results || []);
      setExceptions(eData.exceptions || []);
    } catch { }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true); setMsg(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await apiFetch("/api/reconciliation/upload-statement", { method: "POST", body: formData });
      const data = await res.json();
      setMsg({ text: `Uploaded ${data.rows_imported} bank transactions (ref: ${data.statement_ref})`, ok: data.success });
    } catch (err: any) { setMsg({ text: err.message, ok: false }); }
    finally { setUploading(false); }
  };

  const handleRun = async () => {
    setRunning(true); setMsg(null);
    try {
      const res = await apiFetch("/api/reconciliation/run", { method: "POST" });
      const data = await res.json();
      setMsg({ text: `Reconciliation complete: ${data.matched} matched, ${data.exceptions} exceptions`, ok: data.success });
      fetchData();
    } catch (err: any) { setMsg({ text: err.message, ok: false }); }
    finally { setRunning(false); }
  };

  const handleResolve = async (id: number) => {
    try {
      const res = await apiFetch(`/api/reconciliation/resolve/${id}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolved_by: "user" }),
      });
      const data = await res.json();
      setMsg({ text: "Exception resolved", ok: data.success });
      fetchData();
    } catch { setMsg({ text: "Resolve failed", ok: false }); }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold">Payment Reconciliation</h1><p className="text-muted-foreground">Match bank statements to payments</p></div>
        <Button variant="outline" size="sm" onClick={fetchData}><RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} /></Button>
      </div>

      {/* Session-observer banner — shown when ?session=:id is in URL */}
      {inSessionMode && (
        <Card className="border-2 border-blue-500/40 bg-blue-50 dark:bg-blue-950/20">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="flex items-start gap-3 flex-1 min-w-0">
                <div className="rounded-full bg-blue-600 p-2 shrink-0">
                  <Workflow className="h-5 w-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <CardTitle className="text-base flex items-center gap-2 flex-wrap">
                    P2P Workflow — Reconciliation Phase
                    {sessionLoading ? (
                      <Badge variant="outline">
                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                        Loading…
                      </Badge>
                    ) : (
                      <>
                        <Badge className="bg-blue-600">{currentPhase}</Badge>
                        <Badge
                          variant="outline"
                          className={
                            sessionStatus === "completed"
                              ? "bg-green-50 text-green-700 border-green-300"
                              : sessionStatus === "failed"
                              ? "bg-red-50 text-red-700 border-red-300"
                              : "bg-blue-50 text-blue-700 border-blue-300"
                          }
                        >
                          {sessionStatus}
                        </Badge>
                      </>
                    )}
                  </CardTitle>
                  <CardDescription className="text-xs font-mono mt-1 truncate">
                    Session {sessionId}
                  </CardDescription>
                  {(summary.request as string) && (
                    <CardDescription className="text-sm mt-1">
                      {summary.request as string}
                    </CardDescription>
                  )}
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setLocation(`/sessions/${sessionId}`)}
              >
                Open Session View
                <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* PR snapshot from session */}
            {Object.keys(sessionPrData).length > 0 && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs bg-white dark:bg-slate-900 rounded-md p-3 border">
                <div>
                  <div className="text-muted-foreground">Department</div>
                  <div className="font-medium">{sessionPrData.department || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Item</div>
                  <div className="font-medium truncate">
                    {sessionPrData.product_name || "—"}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Quantity</div>
                  <div className="font-medium">{sessionPrData.quantity || "—"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Amount</div>
                  <div className="font-medium">
                    {sessionPrData.budget
                      ? `$${Number(sessionPrData.budget).toLocaleString()}`
                      : "—"}
                  </div>
                </div>
              </div>
            )}

            {/* Active three_way_match gate (post-HF-3 future) */}
            {matchGate && (
              <div className="rounded-md border-2 border-blue-600 bg-blue-100/50 dark:bg-blue-900/20 p-3">
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle className="h-4 w-4 text-blue-700" />
                  <div className="text-sm font-semibold">
                    3-way match needs confirmation
                  </div>
                </div>
                <Button
                  size="sm"
                  className="bg-blue-600 hover:bg-blue-700 text-white"
                  disabled={confirming}
                  onClick={handleConfirmMatch}
                >
                  {confirming ? (
                    <Loader2 className="h-3 w-3 animate-spin mr-1" />
                  ) : (
                    <CheckCircle2 className="h-3 w-3 mr-1" />
                  )}
                  Confirm Match
                </Button>
              </div>
            )}

            {/* Phase status — observer mode (no gate yet for invoice/match) */}
            {!matchGate && inMatchPhase && (
              <div className="rounded-md bg-white dark:bg-slate-900 border p-3 text-sm flex items-start gap-2">
                {sessionStatus === "completed" ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-green-600 mt-0.5 shrink-0" />
                    <div>
                      Reconciliation phase complete. The session is fully
                      settled — see the timeline in the Session View for the
                      full audit log.
                    </div>
                  </>
                ) : (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin text-blue-600 mt-0.5 shrink-0" />
                    <div>
                      Session is in <strong>{currentPhase}</strong>. The
                      orchestrator is processing 3-way match automatically —
                      the live timeline is available in the Session View.
                    </div>
                  </>
                )}
              </div>
            )}

            {!matchGate && !inMatchPhase && !sessionLoading && (
              <div className="rounded-md bg-white dark:bg-slate-900 border p-3 text-xs text-muted-foreground">
                This session is in <strong>{currentPhase}</strong> — not yet at
                the reconciliation phase. Open the Session View to see the
                active step.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {msg && <div className={`rounded-md px-4 py-3 text-sm ${msg.ok ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>{msg.text}</div>}

      {/* Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardContent className="pt-6 space-y-3">
            <div className="flex items-center gap-2"><FileSpreadsheet className="h-5 w-5 text-blue-500" /><span className="font-medium">Upload Bank Statement</span></div>
            <p className="text-sm text-muted-foreground">Upload a CSV with columns: date, description, debit, credit, balance, reference</p>
            <input type="file" accept=".csv" onChange={handleUpload} disabled={uploading} className="text-sm" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6 space-y-3">
            <div className="flex items-center gap-2"><Scale className="h-5 w-5 text-purple-500" /><span className="font-medium">Run Auto-Matching</span></div>
            <p className="text-sm text-muted-foreground">Match uploaded bank entries to payment runs automatically</p>
            <Button onClick={handleRun} disabled={running}>
              {running ? <RefreshCw className="h-4 w-4 mr-1 animate-spin" /> : <Play className="h-4 w-4 mr-1" />}
              {running ? "Matching..." : "Run Reconciliation"}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Matched Results */}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><CheckCircle2 className="h-5 w-5 text-green-500" /> Matched ({results.length})</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Run</TableHead><TableHead>Payment</TableHead><TableHead className="text-right">Bank Amt</TableHead>
              <TableHead className="text-right">Ledger Amt</TableHead><TableHead className="text-right">Variance</TableHead>
              <TableHead>Confidence</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {results.map((r: any) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono text-xs">{r.reconciliation_run_id}</TableCell>
                  <TableCell>{r.payment_run_id}</TableCell>
                  <TableCell className="text-right">${r.bank_amount?.toLocaleString()}</TableCell>
                  <TableCell className="text-right">${r.ledger_amount?.toLocaleString()}</TableCell>
                  <TableCell className="text-right">${r.variance?.toLocaleString()}</TableCell>
                  <TableCell><Badge className="bg-green-100 text-green-800">{r.match_confidence}%</Badge></TableCell>
                </TableRow>
              ))}
              {results.length === 0 && <TableRow><TableCell colSpan={6} className="text-center py-6 text-muted-foreground">No matched entries</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Exceptions */}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><AlertTriangle className="h-5 w-5 text-orange-500" /> Exceptions ({exceptions.length})</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Type</TableHead><TableHead>Description</TableHead><TableHead className="text-right">Amount</TableHead>
              <TableHead>Reference</TableHead><TableHead>Status</TableHead><TableHead>Action</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {exceptions.map((e: any) => (
                <TableRow key={e.id}>
                  <TableCell>{e.exception_type}</TableCell>
                  <TableCell className="max-w-[200px] truncate">{e.description}</TableCell>
                  <TableCell className="text-right">${e.bank_amount?.toLocaleString()}</TableCell>
                  <TableCell>{e.reference}</TableCell>
                  <TableCell><Badge className={e.status === "open" ? "bg-orange-100 text-orange-800" : "bg-green-100 text-green-800"}>{e.status}</Badge></TableCell>
                  <TableCell>
                    {e.status === "open" && <Button size="sm" variant="outline" onClick={() => handleResolve(e.id)}><CheckCircle2 className="h-3 w-3 mr-1" /> Resolve</Button>}
                  </TableCell>
                </TableRow>
              ))}
              {exceptions.length === 0 && <TableRow><TableCell colSpan={6} className="text-center py-6 text-muted-foreground">No exceptions</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
