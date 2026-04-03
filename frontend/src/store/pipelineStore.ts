/**
 * Pipeline Zustand Store
 * Global state management for 16-step pipeline visualizer
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type {
  PipelineState,
  PipelineStep,
  AgentChip,
  AgentExecution,
  BaseAgentPhaseCard,
  WeakPoint,
  StepCategory,
  QueryType,
  AnimationSpeed,
  PRData,
} from '../types/pipeline';

// Event-aligned pipeline definition (real SSE-driven progression)
const INITIAL_STEPS: PipelineStep[] = [
  { id: 1, category: "FRONTEND", name: "Request built", file: "ChatPage.tsx", baseMs: 0, status: "idle" },
  { id: 2, category: "FRONTEND", name: "Request sent", file: "ChatPage.tsx", baseMs: 0, status: "idle" },
  { id: 3, category: "FASTAPI", name: "Request received", file: "routes/agentic.py", baseMs: 0, status: "idle" },
  { id: 4, category: "CLASSIFY", name: "Intent classification", file: "routes/agentic.py", baseMs: 0, status: "idle" },
  { id: 5, category: "ORCHESTRATE", name: "Routing", file: "agents/orchestrator.py", baseMs: 0, status: "idle" },
  { id: 6, category: "ORCHESTRATE", name: "Agent selected", file: "agents/orchestrator.py", baseMs: 0, status: "idle" },
  { id: 7, category: "BASEAGENT", name: "Observe phase", file: "agents/__init__.py", baseMs: 0, status: "idle" },
  { id: 8, category: "BASEAGENT", name: "Decide phase", file: "agents/__init__.py", baseMs: 0, status: "idle" },
  { id: 9, category: "TOOL", name: "Act phase", file: "agents/__init__.py", baseMs: 0, status: "idle" },
  { id: 10, category: "BASEAGENT", name: "Learn phase", file: "agents/__init__.py", baseMs: 0, status: "idle" },
  { id: 11, category: "FORMAT", name: "Final response", file: "routes/agentic.py", baseMs: 0, status: "idle" },
  { id: 12, category: "FRONTEND", name: "UI rendered", file: "ChatPage.tsx", baseMs: 0, status: "idle" },
];

// Agent chips shown in pipeline panel
const INITIAL_AGENTS: AgentChip[] = [
  { name: "OrchestratorAgent", isSelected: false },
  { name: "ComplianceCheckAgent", isSelected: false },
  { name: "BudgetVerificationAgent", isSelected: false },
  { name: "ApprovalRoutingAgent", isSelected: false },
  { name: "VendorSelectionAgent", isSelected: false },
  { name: "RiskAssessmentAgent", isSelected: false },
  { name: "PriceAnalysisAgent", isSelected: false },
  { name: "ContractMonitoringAgent", isSelected: false },
  { name: "SupplierPerformanceAgent", isSelected: false },
  { name: "InvoiceMatchingAgent", isSelected: false },
  { name: "SpendAnalysisAgent", isSelected: false },
  { name: "InventoryCheckAgent", isSelected: false },
];

// BaseAgent 4 phases
const INITIAL_PHASES: BaseAgentPhaseCard[] = [
  { phase: "OBSERVE", icon: "search", content: "", status: "idle", stepRange: [8] },
  { phase: "DECIDE", icon: "lightbulb", content: "", status: "idle", stepRange: [9] },
  { phase: "ACT", icon: "gear", content: "", status: "idle", stepRange: [10, 11, 12, 13] },
  { phase: "LEARN", icon: "clipboard", content: "", status: "idle", stepRange: [14] },
];

const createEmptyAgentPhases = (): AgentExecution["phases"] => ({
  OBSERVE: "idle",
  DECIDE: "idle",
  ACT: "idle",
  LEARN: "idle",
});

// 9 Weak Points
const INITIAL_WEAK_POINTS: WeakPoint[] = [
  { id: 1, severity: "MEDIUM", title: "Multi-intent queries not detected", triggeredAtStep: 6, isHighlighted: false },
  { id: 2, severity: "HIGH", title: "No retry / circuit breaker on tools", triggeredAtStep: 10, isHighlighted: false },
  { id: 3, severity: "MEDIUM", title: "No caching layer (Redis needed)", triggeredAtStep: 10, isHighlighted: false },
  { id: 4, severity: "LOW", title: "agent_decisions table = 0 rows", triggeredAtStep: 14, isHighlighted: false },
  { id: 5, severity: "MEDIUM", title: "No SLA on human escalation", triggeredAtStep: 14, isHighlighted: false },
  { id: 6, severity: "LOW", title: "Translation RTL layout issues", triggeredAtStep: 5, isHighlighted: false },
  { id: 7, severity: "HIGH", title: "No rate limiting / request queue", triggeredAtStep: 15, isHighlighted: false },
  { id: 8, severity: "HIGH", title: "No timeout on LLM or Odoo calls", triggeredAtStep: 9, isHighlighted: false },
  { id: 9, severity: "LOW", title: "No escalation email notifications", triggeredAtStep: 14, isHighlighted: false },
];

const getSpeedMultiplier = (speed: AnimationSpeed): number => {
  switch (speed) {
    case "fast": return 10;
    case "normal": return 20;
    case "detailed": return 40;
  }
};

export const usePipelineStore = create<PipelineState>()(persist((set, get) => ({
  // Initial state
  status: "idle",
  activeStep: -1,
  completedSteps: new Set(),
  
  queryType: "COMPLIANCE",
  queryText: "",
  prData: {},
  
  elapsed: 0,
  animationSpeed: "normal",
  speedMultiplier: 20,
  
  steps: INITIAL_STEPS,
  logs: [],
  agents: INITIAL_AGENTS,
  baseAgentPhases: INITIAL_PHASES,
  agentExecutions: [],
  toolCalls: [],
  weakPoints: INITIAL_WEAK_POINTS,
  result: null,

  agentPhaseDetails: {},
  currentAgentName: "",
  pendingChatResult: null,
  
  // Actions
  startPipeline: (queryText, queryType, prData = {}) => {
    set({
      status: "running",
      queryText,
      queryType,
      prData,
      activeStep: -1,
      completedSteps: new Set(),
      elapsed: 0,
      steps: INITIAL_STEPS.map(s => ({
        ...s,
        status: "idle",
        detailLine: undefined,
        startedAt: undefined,
        completedAt: undefined,
        durationMs: undefined,
      })),
      logs: [],
      agents: INITIAL_AGENTS.map(a => ({ ...a, isSelected: false })),
      baseAgentPhases: INITIAL_PHASES.map(p => ({ ...p, status: "idle", content: "" })),
      agentExecutions: [],
      toolCalls: [],
      weakPoints: INITIAL_WEAK_POINTS.map(w => ({ ...w, isHighlighted: false })),
      result: null,
      agentPhaseDetails: {},
      currentAgentName: "",
      pendingChatResult: null,
    });
  },
  
  advanceStep: (stepId, detailLine) => {
    set(state => ({
      steps: state.steps.map(step =>
        step.id === stepId
          ? {
              ...step,
              status: "active",
              detailLine,
              startedAt: step.startedAt ?? Date.now(),
            }
          : step
      ),
      activeStep: stepId,
    }));
  },
  
  completeStep: (stepId) => {
    set(state => {
      const newCompleted = new Set(state.completedSteps);
      newCompleted.add(stepId);
      const now = Date.now();
      
      return {
        steps: state.steps.map(step =>
          step.id === stepId
            ? {
                ...step,
                status: "complete",
                completedAt: now,
                durationMs: Math.max(0, now - (step.startedAt ?? now)),
              }
            : step
        ),
        completedSteps: newCompleted,
        status: newCompleted.size === state.steps.length ? "done" : state.status,
      };
    });
  },
  
  addLog: (category, message, ms) => {
    set(state => ({
      logs: [
        ...state.logs,
        {
          id: `log_${Date.now()}_${Math.random()}`,
          category,
          message,
          timestamp: Date.now(),
          ms,
        },
      ],
      elapsed: ms,
    }));
  },
  
  selectAgent: (agentName, confidence) => {
    set(state => {
      const existing = state.agents.find(a => a.name === agentName);
      if (existing) {
        return {
          agents: state.agents.map(agent =>
            agent.name === agentName
              ? { ...agent, isSelected: true, confidence }
              : agent
          ),
        };
      }

      return {
        agents: [
          ...state.agents,
          { name: agentName, isSelected: true, confidence },
        ],
      };
    });
  },

  upsertAgentExecution: (agentName, patch = {}) => {
    set(state => {
      const existing = state.agentExecutions.find(a => a.name === agentName);
      const now = Date.now();

      if (existing) {
        return {
          agentExecutions: state.agentExecutions.map(agent =>
            agent.name === agentName
              ? {
                  ...agent,
                  ...patch,
                  phases: patch.phases ? { ...agent.phases, ...patch.phases } : agent.phases,
                }
              : agent
          ),
        };
      }

      return {
        agentExecutions: [
          ...state.agentExecutions,
          {
            name: agentName,
            status: patch.status ?? "active",
            currentPhase: patch.currentPhase,
            lastMessage: patch.lastMessage,
            confidence: patch.confidence,
            startedAt: patch.startedAt ?? now,
            completedAt: patch.completedAt,
            durationMs: patch.durationMs,
            phases: patch.phases ? { ...createEmptyAgentPhases(), ...patch.phases } : createEmptyAgentPhases(),
          },
        ],
      };
    });
  },

  setAgentPhase: (agentName, phase, status, message) => {
    set(state => {
      const now = Date.now();
      const existing = state.agentExecutions.find(a => a.name === agentName);

      if (!existing) {
        return {
          agentExecutions: [
            ...state.agentExecutions,
            {
              name: agentName,
              status: status === "error" ? "error" : "active",
              currentPhase: phase,
              lastMessage: message,
              startedAt: now,
              phases: { ...createEmptyAgentPhases(), [phase]: status },
            },
          ],
        };
      }

      return {
        agentExecutions: state.agentExecutions.map(agent => {
          if (agent.name !== agentName) return agent;

          const nextOverallStatus = status === "error"
            ? "error"
            : (phase === "LEARN" && status === "complete")
              ? "complete"
              : "active";

          const completedAt = nextOverallStatus === "complete" || nextOverallStatus === "error"
            ? now
            : agent.completedAt;

          return {
            ...agent,
            status: nextOverallStatus,
            currentPhase: phase,
            lastMessage: message ?? agent.lastMessage,
            phases: {
              ...agent.phases,
              [phase]: status,
            },
            completedAt,
            durationMs: completedAt ? Math.max(0, completedAt - (agent.startedAt ?? now)) : agent.durationMs,
          };
        }),
      };
    });
  },

  completeAgentExecution: (agentName, message) => {
    set(state => {
      const now = Date.now();
      const existing = state.agentExecutions.find(agent => agent.name === agentName);

      if (!existing) {
        return {
          agentExecutions: [
            ...state.agentExecutions,
            {
              name: agentName,
              status: "complete",
              lastMessage: message ?? "Workflow complete",
              startedAt: now,
              completedAt: now,
              durationMs: 0,
              phases: {
                ...createEmptyAgentPhases(),
                LEARN: "complete",
              },
            },
          ],
        };
      }

      return {
        agentExecutions: state.agentExecutions.map(agent =>
          agent.name === agentName
            ? {
                ...agent,
                status: "complete",
                lastMessage: message ?? agent.lastMessage,
                completedAt: now,
                durationMs: Math.max(0, now - (agent.startedAt ?? now)),
                phases: {
                  ...agent.phases,
                  LEARN: agent.phases.LEARN === "idle" ? "complete" : agent.phases.LEARN,
                },
              }
            : agent
        ),
      };
    });
  },
  
  activatePhase: (phase, content) => {
    set(state => ({
      baseAgentPhases: state.baseAgentPhases.map(p =>
        p.phase === phase
          ? { ...p, status: "active", content: content ?? p.content }
          : p.status === "active"
          ? { ...p, status: "complete" }
          : p
      ),
    }));
  },
  
  addToolCall: (toolCall) => {
    set(state => ({
      toolCalls: [
        ...state.toolCalls,
        {
          ...toolCall,
          id: `tool_${Date.now()}_${Math.random()}`,
          status: "pending" as const,
        },
      ],
    }));
  },
  
  completeToolCall: (toolId, result) => {
    set(state => ({
      toolCalls: state.toolCalls.map(tool =>
        tool.id === toolId
          ? { ...tool, status: "complete" as const, result }
          : tool
      ),
    }));
  },
  
  setResult: (result) => {
    set({ result, status: "done" });
  },
  
  highlightWeakPoint: (stepId) => {
    set(state => ({
      weakPoints: state.weakPoints.map(wp =>
        wp.triggeredAtStep === stepId
          ? { ...wp, isHighlighted: true }
          : wp
      ),
    }));
  },

  updatePhaseDetail: (phase, data) => {
    set(state => ({
      agentPhaseDetails: { ...state.agentPhaseDetails, [phase]: data },
    }));
  },

  setCurrentAgentName: (name) => {
    set({ currentAgentName: name });
  },

  setPendingChatResult: (result) => {
    set({ pendingChatResult: result });
  },
  
  setAnimationSpeed: (speed) => {
    set({
      animationSpeed: speed,
      speedMultiplier: getSpeedMultiplier(speed),
    });
  },
  
  reset: () => {
    set({
      status: "idle",
      activeStep: -1,
      completedSteps: new Set(),
      queryType: "COMPLIANCE",
      queryText: "",
      prData: {},
      elapsed: 0,
      steps: INITIAL_STEPS,
      logs: [],
      agents: INITIAL_AGENTS,
      baseAgentPhases: INITIAL_PHASES,
      agentExecutions: [],
      toolCalls: [],
      weakPoints: INITIAL_WEAK_POINTS,
      result: null,
      agentPhaseDetails: {},
      currentAgentName: "",
      pendingChatResult: null,
    });
  },
}), {
  name: 'pipeline-store-v1',
  storage: createJSONStorage(() => localStorage),
  partialize: (state) => ({
    status: state.status,
    activeStep: state.activeStep,
    completedSteps: Array.from(state.completedSteps),
    queryType: state.queryType,
    queryText: state.queryText,
    prData: state.prData,
    elapsed: state.elapsed,
    animationSpeed: state.animationSpeed,
    speedMultiplier: state.speedMultiplier,
    steps: state.steps,
    logs: state.logs,
    agents: state.agents,
    agentExecutions: state.agentExecutions,
    baseAgentPhases: state.baseAgentPhases,
    toolCalls: state.toolCalls,
    weakPoints: state.weakPoints,
    result: state.result,
    agentPhaseDetails: state.agentPhaseDetails,
    currentAgentName: state.currentAgentName,
    pendingChatResult: state.pendingChatResult,
  }),
  merge: (persistedState, currentState) => {
    const persisted = persistedState as any;
    const normalizedStatus = persisted?.status === 'running' ? 'done' : persisted?.status;
    return {
      ...currentState,
      ...persisted,
      status: normalizedStatus ?? currentState.status,
      completedSteps: new Set(persisted?.completedSteps ?? []),
    };
  },
}));
