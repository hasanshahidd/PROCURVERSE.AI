import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ArrowRight, RefreshCw, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";

type PanelStatus = "active" | "completed" | "failed";
type Mode = "demo" | "live";

type TechnicalPayload = {
  agent_name: string;
  phase: "OBSERVE" | "DECIDE" | "ACT" | "LEARN" | "COMPLETE" | string;
  confidence_score?: number | null;
  tool_calls_made?: string[];
  duration_ms?: number | null;
  status: PanelStatus;
};

type BusinessPayload = {
  summary: string;
  status_badge: "Processing" | "Approved" | "Escalated" | "Attention Required" | string;
  financial_impact_note?: string | null;
  risk_level: "Low" | "Medium" | "High" | string;
  recommended_next_action: string;
};

type ExecutiveEvent = {
  event_type: "technical-panel" | "business-panel" | "connection" | "keepalive" | string;
  session_id?: string;
  timestamp?: string;
  payload?: TechnicalPayload | BusinessPayload | { message?: string };
};

type AgentCardState = {
  agentName: string;
  phase: string;
  confidenceScore?: number | null;
  toolCalls: string[];
  durationMs?: number | null;
  status: PanelStatus;
  updatedAt: number;
};

const PHASE_ORDER = ["OBSERVE", "DECIDE", "ACT", "LEARN"];
const API_BASE = (import.meta as any).env?.VITE_API_URL || "";

function getApiUrl(path: string): string {
  if (API_BASE) {
    return `${API_BASE}${path}`;
  }
  return path;
}

function getWsUrl(path: string): string {
  if (API_BASE) {
    return `${API_BASE.replace(/^http/i, "ws")}${path}`;
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.hostname;
  const backendPort = "5000";
  return `${protocol}//${host}:${backendPort}${path}`;
}

function formatDuration(ms: number): string {
  const total = Math.max(ms, 0);
  const mins = Math.floor(total / 60000);
  const secs = Math.floor((total % 60000) / 1000);
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function buildDemoTimeline(): ExecutiveEvent[] {
  return [
    {
      event_type: "technical-panel",
      session_id: "demo-session",
      payload: {
        agent_name: "BudgetVerificationAgent",
        phase: "OBSERVE",
        confidence_score: 0.92,
        tool_calls_made: ["get_department_budget_status", "check_budget_availability"],
        duration_ms: 220,
        status: "active",
      },
    },
    {
      event_type: "business-panel",
      session_id: "demo-session",
      payload: {
        summary: "Budget Verification is gathering live department budget data for this request.",
        status_badge: "Processing",
        financial_impact_note: "Budget remaining: $145,000.00",
        risk_level: "Low",
        recommended_next_action: "Continue monitoring while budget validation completes.",
      },
    },
    {
      event_type: "technical-panel",
      session_id: "demo-session",
      payload: {
        agent_name: "BudgetVerificationAgent",
        phase: "ACT",
        confidence_score: 0.92,
        tool_calls_made: ["update_committed_budget"],
        duration_ms: 310,
        status: "completed",
      },
    },
    {
      event_type: "business-panel",
      session_id: "demo-session",
      payload: {
        summary: "Budget Verification completed and reserved funds for this procurement action.",
        status_badge: "Approved",
        financial_impact_note: "Budget remaining: $95,000.00",
        risk_level: "Low",
        recommended_next_action: "Proceed to vendor recommendation and risk review.",
      },
    },
    {
      event_type: "technical-panel",
      session_id: "demo-session",
      payload: {
        agent_name: "RiskAssessmentAgent",
        phase: "DECIDE",
        confidence_score: 0.74,
        tool_calls_made: ["get_vendors", "query_agent_history"],
        duration_ms: 470,
        status: "active",
      },
    },
    {
      event_type: "business-panel",
      session_id: "demo-session",
      payload: {
        summary: "Risk Assessment is evaluating vendor and compliance exposure for this purchase.",
        status_badge: "Processing",
        financial_impact_note: null,
        risk_level: "Medium",
        recommended_next_action: "Prepare approver context if escalation is required.",
      },
    },
    {
      event_type: "technical-panel",
      session_id: "demo-session",
      payload: {
        agent_name: "ApprovalRoutingAgent",
        phase: "LEARN",
        confidence_score: 0.58,
        tool_calls_made: ["get_approval_chain", "record_approval_decision"],
        duration_ms: 640,
        status: "completed",
      },
    },
    {
      event_type: "business-panel",
      session_id: "demo-session",
      payload: {
        summary: "Approval Routing completed with low confidence and routed this case for human review.",
        status_badge: "Escalated",
        financial_impact_note: "Potential savings identified: $6,400.00",
        risk_level: "High",
        recommended_next_action: "Send to Director approver for immediate confirmation.",
      },
    },
    {
      event_type: "technical-panel",
      session_id: "demo-session",
      payload: {
        agent_name: "Orchestrator",
        phase: "COMPLETE",
        confidence_score: 0.8,
        tool_calls_made: [],
        duration_ms: 1800,
        status: "completed",
      },
    },
    {
      event_type: "business-panel",
      session_id: "demo-session",
      payload: {
        summary: "Pipeline completed. Final outcome is ready for executive review.",
        status_badge: "Approved",
        financial_impact_note: null,
        risk_level: "Low",
        recommended_next_action: "Share outcome with procurement and finance stakeholders.",
      },
    },
  ];
}

export default function ExecutiveLiveDemoPage() {
  const [mode, setMode] = useState<Mode>("demo");
  const [clock, setClock] = useState(new Date());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStartMs, setSessionStartMs] = useState<number | null>(null);
  const [sessionEndMs, setSessionEndMs] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [agentOrder, setAgentOrder] = useState<string[]>([]);
  const [agentStateMap, setAgentStateMap] = useState<Record<string, AgentCardState>>({});
  const [businessCards, setBusinessCards] = useState<Array<BusinessPayload & { id: string }>>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const demoTimersRef = useRef<number[]>([]);
  const businessContainerRef = useRef<HTMLDivElement | null>(null);

  const elapsedMs = useMemo(() => {
    if (!sessionStartMs) return 0;
    if (running) return Math.max(Date.now() - sessionStartMs, 0);
    if (sessionEndMs) return Math.max(sessionEndMs - sessionStartMs, 0);
    return Math.max(Date.now() - sessionStartMs, 0);
  }, [running, sessionEndMs, sessionStartMs, clock]);

  const technicalCards = useMemo(() => {
    return agentOrder.map((name) => agentStateMap[name]).filter(Boolean);
  }, [agentOrder, agentStateMap]);

  const progressValue = useMemo(() => {
    const completed = technicalCards.filter((card) => card.status === "completed").length;
    const total = Math.max(technicalCards.length, 1);
    return Math.round((completed / total) * 100);
  }, [technicalCards]);

  const clearAllState = () => {
    setSessionId(null);
    setSessionStartMs(null);
    setSessionEndMs(null);
    setRunning(false);
    setReplaying(false);
    setAgentOrder([]);
    setAgentStateMap({});
    setBusinessCards([]);
  };

  const clearDemoTimers = () => {
    demoTimersRef.current.forEach((id) => window.clearTimeout(id));
    demoTimersRef.current = [];
  };

  const handleExecutiveEvent = (evt: ExecutiveEvent, opts?: { replay?: boolean }) => {
    if (!evt || !evt.event_type) return;
    if (evt.event_type === "connection" || evt.event_type === "keepalive") return;

    const sid = evt.session_id || sessionId || "unknown-session";
    const now = Date.now();
    const isReplay = opts?.replay === true;

    if (!sessionId || sid !== sessionId) {
      setSessionId(sid);
      setSessionStartMs(now);
      setSessionEndMs(null);
      setRunning(true);
      setAgentOrder([]);
      setAgentStateMap({});
      setBusinessCards([]);
    }

    if (evt.event_type === "technical-panel") {
      const payload = evt.payload as TechnicalPayload;
      if (!payload?.agent_name) return;

      setAgentOrder((prev) => (prev.includes(payload.agent_name) ? prev : [...prev, payload.agent_name]));
      setAgentStateMap((prev) => ({
        ...prev,
        [payload.agent_name]: {
          agentName: payload.agent_name,
          phase: payload.phase,
          confidenceScore: payload.confidence_score,
          toolCalls: payload.tool_calls_made || [],
          durationMs: payload.duration_ms,
          status: payload.status,
          updatedAt: now,
        },
      }));

      if (payload.status === "active") {
        setRunning(true);
        setSessionEndMs(null);
      }
      if (payload.phase === "COMPLETE" || (payload.status === "completed" && payload.phase === "LEARN")) {
        setRunning(false);
        setSessionEndMs(now);
      }
      if (payload.status === "failed") {
        setRunning(false);
        setSessionEndMs(now);
      }
    }

    if (evt.event_type === "business-panel") {
      const payload = evt.payload as BusinessPayload;
      if (!payload?.summary) return;
      const cardId = `${sid}-${now}-${Math.random().toString(16).slice(2)}`;
      setBusinessCards((prev) => [...prev, { ...payload, id: cardId }]);
      if (!isReplay) {
        setRunning(payload.status_badge === "Processing" ? true : running);
      }
    }
  };

  const replaySessionEvents = (events: ExecutiveEvent[]) => {
    if (!events || events.length === 0) return;
    clearDemoTimers();
    setReplaying(true);

    events.forEach((evt, idx) => {
      const timer = window.setTimeout(() => {
        handleExecutiveEvent(evt, { replay: true });
        if (idx === events.length - 1) {
          setReplaying(false);
          setRunning(false);
          setSessionEndMs(Date.now());
        }
      }, idx * 650);
      demoTimersRef.current.push(timer);
    });
  };

  const fetchLastSessionAndReplay = async () => {
    try {
      const res = await fetch(getApiUrl("/api/executive-demo/last-session"));
      if (!res.ok) return;
      const data = await res.json();
      const events = data?.session?.events || [];
      if (Array.isArray(events) && events.length > 0) {
        replaySessionEvents(events);
      }
    } catch {
      // Silent fallback: screen remains in idle state.
    }
  };

  const startDemoTimeline = () => {
    clearDemoTimers();
    const timeline = buildDemoTimeline();
    setReplaying(true);
    timeline.forEach((evt, idx) => {
      const timer = window.setTimeout(() => {
        handleExecutiveEvent(evt);
        if (idx === timeline.length - 1) {
          setReplaying(false);
          setRunning(false);
          setSessionEndMs(Date.now());
        }
      }, idx * 800);
      demoTimersRef.current.push(timer);
    });
  };

  const stopLiveSocket = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };

  const startLiveSocket = () => {
    stopLiveSocket();
    const ws = new WebSocket(getWsUrl("/ws/executive-demo"));
    wsRef.current = ws;

    ws.onmessage = (message) => {
      try {
        const parsed = JSON.parse(message.data) as ExecutiveEvent;
        handleExecutiveEvent(parsed);
      } catch {
        // Ignore malformed messages.
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
    };
  };

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    fetchLastSessionAndReplay();
    return () => {
      stopLiveSocket();
      clearDemoTimers();
    };
  }, []);

  useEffect(() => {
    clearAllState();
    if (mode === "demo") {
      stopLiveSocket();
      startDemoTimeline();
      return;
    }

    clearDemoTimers();
    startLiveSocket();
    fetchLastSessionAndReplay();
  }, [mode]);

  useEffect(() => {
    const container = businessContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [businessCards]);

  const idle = !running && !replaying && technicalCards.length === 0 && businessCards.length === 0;

  return (
    <div className="h-screen w-full bg-slate-950 text-slate-100 overflow-hidden">
      <div className="h-full flex flex-col">
        <header className="h-16 border-b border-slate-800 px-6 flex items-center justify-between bg-slate-900">
          <div className="w-1/3">
            <h1 className="text-xl font-semibold tracking-tight">Procurement AI - Live Decision Theater</h1>
          </div>

          <div className="w-1/3 text-center text-sm text-slate-300">
            {clock.toLocaleTimeString()}
          </div>

          <div className="w-1/3 flex items-center justify-end gap-3">
            <div className="inline-flex items-center rounded-md border border-slate-700 overflow-hidden">
              <button
                className={`px-3 py-1 text-sm ${mode === "demo" ? "bg-slate-200 text-slate-900" : "bg-slate-900 text-slate-300"}`}
                onClick={() => setMode("demo")}
                type="button"
              >
                Demo
              </button>
              <button
                className={`px-3 py-1 text-sm ${mode === "live" ? "bg-slate-200 text-slate-900" : "bg-slate-900 text-slate-300"}`}
                onClick={() => setMode("live")}
                type="button"
              >
                Live
              </button>
            </div>

            <Badge variant="secondary" className="bg-slate-800 text-slate-100">
              {mode === "demo" ? "Demo" : "Live"}
            </Badge>

            <Badge variant="outline" className="border-slate-600 text-slate-200">
              Session {formatDuration(elapsedMs)}
            </Badge>

            <Button
              size="sm"
              variant="outline"
              className="border-slate-600 text-slate-100"
              onClick={() => {
                clearAllState();
                if (mode === "demo") {
                  startDemoTimeline();
                } else {
                  fetchLastSessionAndReplay();
                }
              }}
            >
              <RefreshCw className="h-4 w-4 mr-1" />
              Reset
            </Button>
          </div>
        </header>

        <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 min-h-0">
          <section className="h-full bg-slate-950 border-r border-slate-800 p-5 overflow-hidden flex flex-col">
            <div className="mb-4">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-sm uppercase tracking-wider text-slate-400">Technical Pipeline</h2>
                <span className="text-xs text-slate-400">Session: {sessionId || "n/a"}</span>
              </div>
              <Progress value={progressValue} className="h-2 bg-slate-800" />
            </div>

            {idle ? (
              <div className="h-full grid place-items-center text-slate-400 text-lg">
                Waiting for next procurement request.
              </div>
            ) : (
              <div className="flex-1 overflow-auto pr-1">
                <div className="flex flex-col gap-3">
                  {technicalCards.map((card, idx) => {
                    const active = card.status === "active";
                    return (
                      <div key={card.agentName} className="space-y-2">
                        <Card
                          className={`border ${
                            card.status === "failed"
                              ? "border-red-500/60 bg-red-950/30"
                              : card.status === "completed"
                                ? "border-emerald-500/40 bg-emerald-950/20"
                                : "border-cyan-400/60 bg-cyan-950/30"
                          } ${active ? "shadow-[0_0_24px_rgba(34,211,238,0.35)]" : ""}`}
                        >
                          <CardHeader className="pb-2">
                            <CardTitle className="text-base flex items-center justify-between">
                              <span>{card.agentName}</span>
                              <Badge
                                className={
                                  card.status === "failed"
                                    ? "bg-red-600"
                                    : card.status === "completed"
                                      ? "bg-emerald-600"
                                      : "bg-cyan-600"
                                }
                              >
                                {card.status}
                              </Badge>
                            </CardTitle>
                          </CardHeader>
                          <CardContent className="space-y-2 text-sm">
                            <div className="flex justify-between text-slate-300">
                              <span>Phase</span>
                              <span className="font-medium">{card.phase}</span>
                            </div>
                            <div className="flex justify-between text-slate-300">
                              <span>Confidence</span>
                              <span className="font-medium">
                                {typeof card.confidenceScore === "number"
                                  ? `${Math.round(card.confidenceScore * 100)}%`
                                  : "n/a"}
                              </span>
                            </div>
                            <div className="flex justify-between text-slate-300">
                              <span>Duration</span>
                              <span className="font-medium">{card.durationMs ? `${card.durationMs}ms` : "-"}</span>
                            </div>
                            <div>
                              <p className="text-slate-400 mb-1">Tool Calls</p>
                              {card.toolCalls.length === 0 ? (
                                <p className="text-slate-500">No tool calls recorded for this step.</p>
                              ) : (
                                <div className="flex flex-wrap gap-1">
                                  {card.toolCalls.map((tool) => (
                                    <Badge key={`${card.agentName}-${tool}`} variant="secondary" className="bg-slate-800 text-slate-200">
                                      {tool}
                                    </Badge>
                                  ))}
                                </div>
                              )}
                            </div>
                          </CardContent>
                        </Card>

                        {idx < technicalCards.length - 1 ? (
                          <div className="flex justify-center text-slate-500">
                            <ArrowRight className="h-4 w-4" />
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </section>

          <section className="h-full bg-slate-50 text-slate-900 p-5 overflow-hidden flex flex-col">
            <div className="mb-3">
              <h2 className="text-lg font-semibold">What Is Happening Right Now</h2>
              <p className="text-sm text-slate-500">Business narrative generated from live agent execution data.</p>
            </div>

            {idle ? (
              <div className="h-full grid place-items-center text-slate-500 text-lg">
                Waiting for next procurement request.
              </div>
            ) : (
              <div ref={businessContainerRef} className="flex-1 overflow-y-auto space-y-3 pr-1">
                {businessCards.map((card) => (
                  <Card key={card.id} className="border-slate-200 shadow-sm animate-in slide-in-from-bottom-4 duration-300">
                    <CardContent className="pt-4 space-y-3">
                      <p className="text-sm leading-6">{card.summary}</p>

                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          className={
                            card.status_badge === "Approved"
                              ? "bg-emerald-600"
                              : card.status_badge === "Escalated"
                                ? "bg-amber-600"
                                : card.status_badge === "Attention Required"
                                  ? "bg-red-600"
                                  : "bg-blue-600"
                          }
                        >
                          {card.status_badge}
                        </Badge>

                        <Badge variant="outline" className="border-slate-300">
                          {card.risk_level === "Low" ? <ShieldCheck className="h-3.5 w-3.5 mr-1" /> : null}
                          {card.risk_level === "Medium" ? <ShieldQuestion className="h-3.5 w-3.5 mr-1" /> : null}
                          {card.risk_level === "High" ? <ShieldAlert className="h-3.5 w-3.5 mr-1" /> : null}
                          Risk: {card.risk_level}
                        </Badge>
                      </div>

                      {card.financial_impact_note ? (
                        <div className="text-sm rounded-md bg-slate-100 border border-slate-200 px-3 py-2">
                          {card.financial_impact_note}
                        </div>
                      ) : null}

                      <p className="text-sm text-slate-600">
                        <span className="font-medium text-slate-800">Next:</span> {card.recommended_next_action}
                      </p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
