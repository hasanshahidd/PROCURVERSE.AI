import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, CircleDashed, Clock3, Layers3, Rocket, ShieldCheck, Target } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { useLocation } from "wouter";
import { apiFetch } from "@/lib/api";

type AgentInfo = {
  type: string;
  name: string;
  description: string;
  status: string;
  tools_count: number;
};

type AgentsResponse = {
  success: boolean;
  count: number;
  agents: AgentInfo[];
};

type WorkflowCard = {
  title: string;
  status: "LIVE" | "PARTIAL";
  summary: string;
  outcome: string;
};

type AgentMaturity = "live" | "partial" | "development";

type ClassifiedAgent = AgentInfo & {
  maturity: AgentMaturity;
  maturityReason: string;
};

const TARGET_SPECIALIZED_AGENTS = 17;

const documentedRoadmapAgents: string[] = [
  "DeliveryTrackingAgent",
  "ForecastingAgent",
  "DocumentProcessingAgent",
  "MonitoringDashboardAgent",
];

const explicitMaturity: Record<string, { maturity: AgentMaturity; reason: string }> = {
  BudgetVerificationAgent: {
    maturity: "partial",
    reason: "Core budget checks are live, but full human-in-loop budget override/review is still pending.",
  },
  ApprovalRoutingAgent: {
    maturity: "live",
    reason: "Fully operational in governed PR routing workflows.",
  },
  VendorSelectionAgent: {
    maturity: "live",
    reason: "Top-5 recommendation flow is active in production scenarios.",
  },
  RiskAssessmentAgent: {
    maturity: "live",
    reason: "Risk scoring and mitigation guidance are active in current workflows.",
  },
  ComplianceCheckAgent: {
    maturity: "live",
    reason: "Compliance gating is active in PR creation orchestration.",
  },
  PriceAnalysisAgent: {
    maturity: "partial",
    reason: "Available in registry but still under broader UAT and hardening.",
  },
  ContractMonitoringAgent: {
    maturity: "development",
    reason: "Not fully functional end-to-end in current delivery scope.",
  },
  SupplierPerformanceAgent: {
    maturity: "development",
    reason: "Not fully functional end-to-end in current delivery scope.",
  },
  InvoiceMatchingAgent: {
    maturity: "development",
    reason: "Registered but not fully implemented yet.",
  },
  SpendAnalyticsAgent: {
    maturity: "development",
    reason: "Registered but not fully implemented yet.",
  },
  InventoryCheckAgent: {
    maturity: "development",
    reason: "Registered but not fully implemented yet.",
  },
};

const workflowCards: WorkflowCard[] = [
  {
    title: "Budget Verification",
    status: "PARTIAL",
    summary: "Checks available budget and utilization thresholds before commitment.",
    outcome: "Approves or rejects with utilization guidance; full human review control is still being added.",
  },
  {
    title: "Vendor Selection",
    status: "LIVE",
    summary: "Scores suppliers and returns a top-5 recommendation shortlist.",
    outcome: "Primary recommendation plus alternatives with rationale.",
  },
  {
    title: "Risk Assessment",
    status: "LIVE",
    summary: "Calculates weighted risk across vendor, financial, compliance, operational lenses.",
    outcome: "Structured score, level, concerns, and mitigation guidance.",
  },
  {
    title: "PR Creation (Governed)",
    status: "LIVE",
    summary: "Runs compliance + budget + vendor shortlist, pauses for human vendor confirmation.",
    outcome: "Finalizes PR with approval routing and a non-blocking risk snapshot.",
  },
];

async function fetchAgentRegistry(): Promise<AgentsResponse> {
  const res = await apiFetch("/api/agentic/agents");
  if (!res.ok) {
    throw new Error("Failed to load agent registry");
  }
  return res.json();
}

function statusPillClass(kind: "live" | "partial" | "planned") {
  if (kind === "live") {
    return "bg-emerald-100 text-emerald-800 border-emerald-300";
  }
  if (kind === "partial") {
    return "bg-amber-100 text-amber-800 border-amber-300";
  }
  return "bg-slate-200 text-slate-700 border-slate-300";
}

export default function AgenticFlowPage() {
  const [, setLocation] = useLocation();

  const { data, isLoading, isError, refetch, isFetching } = useQuery<AgentsResponse>({
    queryKey: ["/api/agentic/agents"],
    queryFn: fetchAgentRegistry,
    refetchInterval: 20000,
    retry: 1,
  });

  const computed = useMemo(() => {
    const allAgents = data?.agents || [];

    const classifiedAgents: ClassifiedAgent[] = allAgents.map((agent) => {
      const override = explicitMaturity[agent.name];
      if (override) {
        return {
          ...agent,
          maturity: override.maturity,
          maturityReason: override.reason,
        };
      }

      if (agent.tools_count === 0) {
        return {
          ...agent,
          maturity: "development",
          maturityReason: "Registered but tool wiring or integration is incomplete.",
        };
      }

      return {
        ...agent,
        maturity: "partial",
        maturityReason: "Runtime registered, but full UAT/business sign-off is pending.",
      };
    });

    const liveAgents = classifiedAgents.filter((agent) => agent.maturity === "live");
    const partialAgents = classifiedAgents.filter((agent) => agent.maturity === "partial");
    const inDevelopmentAgents = classifiedAgents.filter((agent) => agent.maturity === "development");

    const remainingToTarget = Math.max(TARGET_SPECIALIZED_AGENTS - allAgents.length, 0);
    const plannedBacklog = [...documentedRoadmapAgents];

    if (remainingToTarget > plannedBacklog.length) {
      const extraSlots = remainingToTarget - plannedBacklog.length;
      for (let i = 1; i <= extraSlots; i += 1) {
        plannedBacklog.push(`Roadmap Slot ${i}`);
      }
    }

    return {
      registeredCount: allAgents.length,
      liveCount: liveAgents.length,
      partialCount: partialAgents.length,
      inDevelopmentCount: inDevelopmentAgents.length,
      plannedCount: plannedBacklog.length,
      completionPercent: Math.round((liveAgents.length / TARGET_SPECIALIZED_AGENTS) * 100),
      liveAgents,
      partialAgents,
      inDevelopmentAgents,
      plannedBacklog,
    };
  }, [data]);

  return (
    <div className="min-h-full bg-gradient-to-b from-slate-50 via-white to-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-6 md:px-6 md:py-8 space-y-6">
        <section className="rounded-2xl border bg-gradient-to-r from-slate-900 via-slate-800 to-slate-900 text-white p-6 md:p-8 shadow-lg">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Enterprise Program View</p>
              <h1 className="mt-2 text-2xl md:text-3xl font-bold">Agentic Procurement Delivery Flow</h1>
              <p className="mt-2 text-slate-300 max-w-3xl">
                Executive visibility into what is running now, what is still in development, and how the four governed
                workflows execute across finance, procurement, risk, and approvals.
              </p>
            </div>
            <Button
              onClick={() => refetch()}
              disabled={isFetching}
              variant="outline"
              className="border-slate-500 bg-slate-800 text-white hover:bg-slate-700"
            >
              Refresh Live Status
            </Button>
          </div>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Card className="border-emerald-300 bg-emerald-50/80">
            <CardHeader className="pb-2">
              <CardDescription>Fully Live</CardDescription>
              <CardTitle className="text-3xl text-emerald-700">{computed.liveCount}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-emerald-900">Agents confirmed as fully functional for current scope.</CardContent>
          </Card>

          <Card className="border-amber-300 bg-amber-50/80">
            <CardHeader className="pb-2">
              <CardDescription>Partial</CardDescription>
              <CardTitle className="text-3xl text-amber-700">{computed.partialCount}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-amber-900">Implemented but still needing completion, controls, or full UAT.</CardContent>
          </Card>

          <Card className="border-slate-300 bg-slate-100/80">
            <CardHeader className="pb-2">
              <CardDescription>In Development</CardDescription>
              <CardTitle className="text-3xl text-slate-700">{computed.inDevelopmentCount + computed.plannedCount}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-slate-700">Registered-but-not-wired plus roadmap agents not yet registered.</CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Program Completion</CardDescription>
              <CardTitle className="text-3xl">{computed.completionPercent}%</CardTitle>
            </CardHeader>
            <CardContent>
              <Progress value={computed.completionPercent} className="h-2" />
              <p className="mt-2 text-sm text-muted-foreground">Target: {TARGET_SPECIALIZED_AGENTS} specialized agents.</p>
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Layers3 className="h-5 w-5 text-blue-600" />
                Working Agent Inventory (Green)
              </CardTitle>
              <CardDescription>Only fully functional agents remain green.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {isLoading && <p className="text-sm text-muted-foreground">Loading live registry...</p>}
              {isError && <p className="text-sm text-red-600">Could not read agent registry from backend.</p>}

              {computed.liveAgents.map((agent) => (
                <div key={agent.name} className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-emerald-900">{agent.name}</p>
                      <p className="text-sm text-emerald-800 mt-1">{agent.description}</p>
                      <p className="text-xs text-emerald-700/90 mt-2">{agent.maturityReason}</p>
                    </div>
                    <Badge className={statusPillClass("live")}>LIVE</Badge>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CircleDashed className="h-5 w-5 text-slate-600" />
                Partial + In Development (Gray)
              </CardTitle>
              <CardDescription>All non-fully-functional agents are shown in gray with explicit reasons.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {computed.partialAgents.map((agent) => (
                <div key={agent.name} className="rounded-lg border border-slate-300 bg-slate-100 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-800">{agent.name}</p>
                      <p className="text-sm text-slate-700 mt-1">{agent.description}</p>
                      <p className="text-xs text-slate-600 mt-2">{agent.maturityReason}</p>
                    </div>
                    <Badge className={statusPillClass("partial")}>PARTIAL</Badge>
                  </div>
                </div>
              ))}

              {computed.inDevelopmentAgents.map((agent) => (
                <div key={agent.name} className="rounded-lg border border-slate-300 bg-slate-100 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-800">{agent.name}</p>
                      <p className="text-sm text-slate-700 mt-1">{agent.description}</p>
                      <p className="text-xs text-slate-600 mt-2">{agent.maturityReason}</p>
                    </div>
                    <Badge className={statusPillClass("planned")}>IN DEV</Badge>
                  </div>
                </div>
              ))}

              {computed.plannedBacklog.map((agentName) => (
                <div key={agentName} className="rounded-lg border border-dashed border-slate-400 bg-slate-100 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-semibold text-slate-700">{agentName}</p>
                    <Badge className={statusPillClass("planned")}>PLANNED</Badge>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Target className="h-5 w-5 text-blue-600" />
                Four Live Business Workflows
              </CardTitle>
              <CardDescription>Current production-grade business outcomes from your documented scope.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {workflowCards.map((workflow) => (
                <div key={workflow.title} className="rounded-lg border p-4 bg-white">
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-semibold">{workflow.title}</p>
                    <Badge className={workflow.status === "LIVE" ? statusPillClass("live") : statusPillClass("partial")}>{workflow.status}</Badge>
                  </div>
                  <p className="text-sm text-muted-foreground mt-2">{workflow.summary}</p>
                  <p className="text-sm mt-1"><span className="font-medium">Outcome:</span> {workflow.outcome}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Rocket className="h-5 w-5 text-violet-600" />
                Executive Flow Order
              </CardTitle>
              <CardDescription>Navigation and operational review sequence aligned to leadership workflow.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-lg border bg-white p-4">
                <div className="flex items-center gap-2 font-semibold">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  1. Dashboard
                </div>
                <p className="text-sm text-muted-foreground mt-1">Overall KPIs, budget health, and system metrics first.</p>
              </div>

              <div className="flex justify-center">
                <ArrowRight className="h-5 w-5 text-slate-400" />
              </div>

              <div className="rounded-lg border bg-white p-4">
                <div className="flex items-center gap-2 font-semibold">
                  <ShieldCheck className="h-4 w-4 text-blue-600" />
                  2. Agentic Flow
                </div>
                <p className="text-sm text-muted-foreground mt-1">Live vs planned agent maturity, workflow control, and execution readiness.</p>
              </div>

              <div className="flex justify-center">
                <ArrowRight className="h-5 w-5 text-slate-400" />
              </div>

              <div className="rounded-lg border bg-white p-4">
                <div className="flex items-center gap-2 font-semibold">
                  <Clock3 className="h-4 w-4 text-slate-700" />
                  3. Chat
                </div>
                <p className="text-sm text-muted-foreground mt-1">Operational execution and user interaction after strategic review.</p>
              </div>

              <div className="pt-2 flex gap-2">
                <Button onClick={() => setLocation("/dashboard")} className="flex-1">Go Dashboard</Button>
                <Button
                  onClick={() => {
                    localStorage.setItem("force_new_chat_session", "1");
                    setLocation("/chat?new=1");
                  }}
                  variant="outline"
                  className="flex-1"
                >
                  Go Chat
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>
      </div>
    </div>
  );
}
