import { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Settings, Shield, DollarSign, Users, CheckCircle, Database, ArrowRightLeft, Info, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { apiFetch } from "@/lib/api";

interface ApprovalChain {
  id: number;
  department: string;
  budget_threshold: number;
  approval_level: number;
  approver_email: string;
  approver_name: string;
  status: string;
}

const LEVEL_LABELS: { [key: number]: string } = {
  1: "Manager",
  2: "Director",
  3: "VP/CFO",
};

const LEVEL_COLORS: { [key: number]: string } = {
  1: "bg-blue-500",
  2: "bg-purple-500",
  3: "bg-orange-500",
};

export default function ApprovalSettingsPage() {
  const API_BASE_URL = import.meta.env.VITE_API_URL || "";

  // ERP Switcher state
  const [erpCurrent, setErpCurrent] = useState("");
  const [erpLabel, setErpLabel] = useState("");
  const [erpMode, setErpMode] = useState("");
  const [erpGuidance, setErpGuidance] = useState("");
  const [erpDemoSources, setErpDemoSources] = useState<any[]>([]);
  const [erpLiveSources, setErpLiveSources] = useState<any[]>([]);
  const [erpSelected, setErpSelected] = useState("");
  const [erpSwitching, setErpSwitching] = useState(false);
  const [erpMsg, setErpMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const fetchErpConfig = useCallback(async () => {
    try {
      const res = await apiFetch("/api/config/data-source");
      if (!res.ok) return;
      const data = await res.json();
      setErpCurrent(data.current);
      setErpLabel(data.current_label);
      setErpMode(data.current_mode);
      setErpGuidance(data.guidance);
      setErpSelected(data.current);
      setErpDemoSources(data.demo_sources || []);
      setErpLiveSources(data.live_sources || []);
    } catch { }
  }, []);

  useEffect(() => { fetchErpConfig(); }, [fetchErpConfig]);

  const handleErpSwitch = async () => {
    if (!erpSelected || erpSelected === erpCurrent) return;
    setErpSwitching(true); setErpMsg(null);
    try {
      const res = await apiFetch("/api/config/data-source", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data_source: erpSelected }),
      });
      const data = await res.json();
      if (data.success) { setErpMsg({ text: data.message, ok: true }); fetchErpConfig(); }
      else { setErpMsg({ text: data.detail || "Switch failed", ok: false }); }
    } catch (e: any) { setErpMsg({ text: e.message, ok: false }); }
    finally { setErpSwitching(false); }
  };
  // Fetch approval chains from database
  const { data: chains, isLoading } = useQuery<ApprovalChain[]>({
    queryKey: ["/api/agentic/approval-chains"],
    queryFn: async () => {
      // This endpoint needs to be created in backend
      const res = await fetch(`${API_BASE_URL}/api/agentic/approval-chains`);
      if (!res.ok) throw new Error("Failed to fetch approval chains");
      const data = await res.json();
      return data.chains || [];
    },
  });

  // Group by department
  const chainsByDepartment = chains?.reduce((acc, chain) => {
    if (!acc[chain.department]) {
      acc[chain.department] = [];
    }
    acc[chain.department].push(chain);
    return acc;
  }, {} as Record<string, ApprovalChain[]>);

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
          <Settings className="h-7 w-7" />
          System Settings
        </h1>
        <p className="text-muted-foreground text-sm">
          ERP data source, approval rules, and system configuration
        </p>
      </div>

      {/* ERP Data Source Switcher */}
      <Card className="border-2 border-blue-200">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Database className="h-5 w-5 text-blue-600" />
              ERP Data Source
            </CardTitle>
            <Badge className={erpMode === "demo" ? "bg-amber-100 text-amber-800" : erpMode === "live" ? "bg-green-100 text-green-800" : "bg-blue-100 text-blue-800"}>
              {erpLabel || erpCurrent || "Loading..."}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {erpGuidance && (
            <div className={`rounded-md px-4 py-3 text-sm flex items-start gap-2 ${erpMode === "demo" ? "bg-amber-50 border border-amber-200 text-amber-800" : erpMode === "live" ? "bg-green-50 border border-green-200 text-green-800" : "bg-blue-50 border border-blue-200 text-blue-800"}`}>
              <Info className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>{erpGuidance}</span>
            </div>
          )}
          <div className="flex items-center gap-3">
            <select value={erpSelected} onChange={(e) => setErpSelected(e.target.value)} className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm bg-white">
              <optgroup label="Demo / Sandbox (test data in PostgreSQL)">
                {erpDemoSources.map((s: any) => (<option key={s.key} value={s.key}>{s.label} {s.is_current ? "(current)" : ""}</option>))}
              </optgroup>
              <optgroup label="Live ERP Connectors">
                {erpLiveSources.map((s: any) => (<option key={s.key} value={s.key}>{s.label} {s.configured === false ? "(not configured)" : ""} {s.is_current ? "(current)" : ""}</option>))}
              </optgroup>
            </select>
            <Button onClick={handleErpSwitch} disabled={erpSwitching || erpSelected === erpCurrent || !erpSelected} className="bg-blue-600 hover:bg-blue-700 text-white">
              {erpSwitching ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <ArrowRightLeft className="h-4 w-4 mr-2" />}
              {erpSwitching ? "Switching..." : "Switch"}
            </Button>
          </div>
          {erpMsg && (
            <div className={`rounded-md px-4 py-3 text-sm ${erpMsg.ok ? "bg-green-50 border border-green-200 text-green-700" : "bg-red-50 border border-red-200 text-red-700"}`}>
              {erpMsg.text}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Approval Configuration */}
      <h2 className="text-lg font-semibold mt-6">Approval Rules</h2>

      {/* Info Alert */}
      <Alert>
        <Shield className="h-4 w-4" />
        <AlertDescription>
          <strong>How It Works:</strong> When a PR is created, the <strong>ApprovalRoutingAgent</strong> reads these rules
          and automatically assigns the correct approvers based on department + budget thresholds ⚡
        </AlertDescription>
      </Alert>

      {/* Explanation Card */}
      <Card className="border-2 border-primary/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Approval Routing Logic
          </CardTitle>
          <CardDescription>
            The agent uses a 3-level approval hierarchy based on amount
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-start gap-3">
            <Badge className="bg-blue-500 mt-1">Level 1: Manager</Badge>
            <div>
              <p className="font-semibold">Under $10,000</p>
              <p className="text-sm text-muted-foreground">
                Manager only. Quick approval for small purchases.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Badge className="bg-purple-500 mt-1">Level 2: Director</Badge>
            <div>
              <p className="font-semibold">$10,000 - $50,000</p>
              <p className="text-sm text-muted-foreground">
                Manager approval → Director approval. 2-step process.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Badge className="bg-orange-500 mt-1">Level 3: VP/CFO</Badge>
            <div>
              <p className="font-semibold">Over $50,000</p>
              <p className="text-sm text-muted-foreground">
                Manager → Director → VP/CFO. Full 3-step approval for large purchases.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Department Approval Chains */}
      {isLoading ? (
        <Card>
          <CardContent className="py-16 text-center">
            <p className="text-muted-foreground">Loading approval chains...</p>
          </CardContent>
        </Card>
      ) : (
        <ScrollArea className="h-[calc(100vh-500px)]">
          <div className="grid gap-6 md:grid-cols-2">
            {chainsByDepartment &&
              Object.entries(chainsByDepartment)
                .sort()
                .map(([department, deptChains]) => (
                  <Card key={department} className="hover:shadow-lg transition-shadow">
                    <CardHeader>
                      <CardTitle className="flex items-center justify-between">
                        <span>{department} Department</span>
                        <Badge variant="outline">{deptChains.length} levels</Badge>
                      </CardTitle>
                      <CardDescription>
                        Approval chain configured for this department
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {deptChains
                        .sort((a, b) => a.approval_level - b.approval_level)
                        .map((chain, index) => (
                          <div
                            key={chain.id}
                            className="flex items-start gap-4 p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                          >
                            {/* Level Badge */}
                            <div className="flex flex-col items-center gap-1">
                              <div
                                className={`w-10 h-10 rounded-full ${
                                  LEVEL_COLORS[chain.approval_level]
                                } flex items-center justify-center text-white font-bold`}
                              >
                                {chain.approval_level}
                              </div>
                              {index < deptChains.length - 1 && (
                                <div className="w-0.5 h-8 bg-border" />
                              )}
                            </div>

                            {/* Approver Info */}
                            <div className="flex-1">
                              <div className="flex items-center gap-2 mb-1">
                                <Badge className={LEVEL_COLORS[chain.approval_level]}>
                                  {LEVEL_LABELS[chain.approval_level]}
                                </Badge>
                                <Badge variant="outline" className="gap-1">
                                  <DollarSign className="h-3 w-3" />
                                  {chain.budget_threshold >= 100000
                                    ? `${(chain.budget_threshold / 1000).toFixed(0)}K+`
                                    : `${(chain.budget_threshold / 1000).toFixed(0)}K`}
                                </Badge>
                              </div>
                              <p className="font-semibold text-sm">{chain.approver_name}</p>
                              <p className="text-xs text-muted-foreground">
                                {chain.approver_email}
                              </p>
                            </div>

                            {/* Status */}
                            <div className="text-right">
                              {chain.status === "approved" && (
                                <CheckCircle className="h-5 w-5 text-green-500" />
                              )}
                            </div>
                          </div>
                        ))}
                    </CardContent>
                  </Card>
                ))}
          </div>
        </ScrollArea>
      )}

      {/* Example Scenarios */}
      <Card className="border-2 border-green-500/20">
        <CardHeader>
          <CardTitle className="text-green-600 dark:text-green-400">
            📋 Example Scenarios
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="bg-muted p-3 rounded-md">
            <p className="font-semibold mb-1">Scenario 1: $8,000 IT Purchase</p>
            <p className="text-sm text-muted-foreground">
              Agent routes to: <strong>IT Manager</strong> only (Level 1)
            </p>
          </div>
          <div className="bg-muted p-3 rounded-md">
            <p className="font-semibold mb-1">Scenario 2: $35,000 Finance Purchase</p>
            <p className="text-sm text-muted-foreground">
              Agent routes to: <strong>Finance Manager</strong> → <strong>Finance Director</strong>{" "}
              (Levels 1-2)
            </p>
          </div>
          <div className="bg-muted p-3 rounded-md">
            <p className="font-semibold mb-1">Scenario 3: $120,000 Operations Purchase</p>
            <p className="text-sm text-muted-foreground">
              Agent routes to: <strong>Ops Manager</strong> → <strong>Ops Director</strong> → <strong>COO</strong>{" "}
              (All 3 levels)
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Future Enhancement Note */}
      <Alert>
        <Settings className="h-4 w-4" />
        <AlertDescription>
          <strong>Future Enhancement:</strong> Add ability to edit approval chains, add custom rules,
          and configure email notifications for approvers.
        </AlertDescription>
      </Alert>
    </div>
  );
}
