/**
 * Pipeline Type Definitions
 * Complete type system for 16-step pipeline visualizer
 */

export type PipelineStatus = "idle" | "running" | "done" | "error";

export type QueryType = "COMPLIANCE" | "VENDOR" | "BUDGET" | "RISK" | "APPROVAL";

export type AnimationSpeed = "fast" | "normal" | "detailed";

export type StepCategory = 
  | "FRONTEND" 
  | "FASTAPI" 
  | "TRANSLATE" 
  | "CLASSIFY" 
  | "ORCHESTRATE" 
  | "BASEAGENT" 
  | "TOOL" 
  | "FORMAT";

export type BaseAgentPhase = "OBSERVE" | "DECIDE" | "ACT" | "LEARN";

export type WeakPointSeverity = "HIGH" | "MEDIUM" | "LOW";

export interface PipelineStep {
  id: number;
  category: StepCategory;
  name: string;
  file: string;
  baseMs: number; // Legacy fallback, real timing uses durationMs
  detailLine?: string; // Runtime detail (e.g., "type:COMPLIANCE conf:0.95")
  status: "idle" | "active" | "complete" | "error";
  startedAt?: number;
  completedAt?: number;
  durationMs?: number;
}

export interface LogEntry {
  id: string;
  category: StepCategory;
  message: string;
  timestamp: number;
  ms: number;
}

export interface AgentChip {
  name: string;
  isSelected: boolean;
  confidence?: number;
}

export interface ToolCall {
  id: string;
  source: "PostgreSQL" | "Odoo" | "ERP Adapter" | "ERP";
  name: string;
  status: "pending" | "running" | "complete";
  result?: string; // e.g., "1 row returned" or "47 vendors"
  model?: string; // For ERP: "res.partner"
}

export interface BaseAgentPhaseCard {
  phase: BaseAgentPhase;
  icon: string;
  content: string;
  status: "idle" | "active" | "complete";
  stepRange: number[]; // Which pipeline steps trigger this (e.g., [8] for OBSERVE)
}

export interface AgentExecution {
  name: string;
  status: "idle" | "active" | "complete" | "error";
  currentPhase?: BaseAgentPhase;
  lastMessage?: string;
  confidence?: number;
  startedAt?: number;
  completedAt?: number;
  durationMs?: number;
  phases: Record<BaseAgentPhase, "idle" | "active" | "complete" | "error">;
}

export interface Finding {
  severity: "error" | "warning" | "success" | "info";
  message: string;
}

export interface AgentResult {
  agent: string;
  confidence: number;
  executionTimeMs: number;
  totalTimeMs: number;
  verdict: "MAJOR_VIOLATION" | "SUCCESS" | "HIGH_RISK" | "ANALYSIS_COMPLETE";
  score?: {
    total: number;
    subscores: { policy?: number; budget?: number; approval?: number };
  };
  findings: Finding[];
}

export interface WeakPoint {
  id: number;
  severity: WeakPointSeverity;
  title: string;
  triggeredAtStep: number;
  isHighlighted: boolean;
}

export interface PRData {
  department?: string;
  budget?: number;
  category?: string;
  [key: string]: any;
}

export interface PipelineState {
  // Status
  status: PipelineStatus;
  activeStep: number; // -1 = none active
  completedSteps: Set<number>;
  
  // Query
  queryType: QueryType;
  queryText: string;
  prData: PRData;
  
  // Timing
  elapsed: number; // Total elapsed ms
  animationSpeed: AnimationSpeed;
  speedMultiplier: number; // 10 / 20 / 40
  
  // Pipeline components
  steps: PipelineStep[];
  logs: LogEntry[];
  agents: AgentChip[];
  agentExecutions: AgentExecution[];
  baseAgentPhases: BaseAgentPhaseCard[];
  toolCalls: ToolCall[];
  weakPoints: WeakPoint[];
  result: AgentResult | null;

  // Live agent phase details (survives navigation)
  agentPhaseDetails: Record<string, any>;
  currentAgentName: string;
  pendingChatResult: { data: any; agentName: string; pipelineSteps?: any[]; pipelineDetails?: Record<string, any> } | null;

  // P2P human gate state — inline decisions on pipeline page
  humanActionRequired: null | {
    type: string;
    message: string;
    options: string[];
    pr_number?: string;
    po_number?: string;
    vendorOptions?: Array<{ vendor_name: string; total_score?: number; score?: number; recommendation_reason?: string; strengths?: string[]; concerns?: string[] }>;
  };
  workflowRunId: string | null;
  p2pStepData: null | {
    actionsCompleted: any[];
    totalSteps: number;
    currentStep: string;
    warnings?: string[];
    gapAlerts?: {
      maverick_spend?: boolean;
      duplicate_invoice?: boolean;
      contract_variance?: boolean;
      exception_count?: number;
    };
    pendingExceptions?: any[];
  };

  // Actions
  startPipeline: (queryText: string, queryType: QueryType, prData?: PRData) => void;
  advanceStep: (stepId: number, detailLine?: string) => void;
  completeStep: (stepId: number) => void;
  addLog: (category: StepCategory, message: string, ms: number) => void;
  selectAgent: (agentName: string, confidence: number) => void;
  upsertAgentExecution: (agentName: string, patch?: Partial<AgentExecution>) => void;
  setAgentPhase: (
    agentName: string,
    phase: BaseAgentPhase,
    status: "idle" | "active" | "complete" | "error",
    message?: string
  ) => void;
  completeAgentExecution: (agentName: string, message?: string) => void;
  activatePhase: (phase: BaseAgentPhase, content?: string) => void;
  addToolCall: (toolCall: Omit<ToolCall, "id" | "status">) => void;
  completeToolCall: (toolId: string, result: string) => void;
  setResult: (result: AgentResult) => void;
  completePipeline: () => void;
  highlightWeakPoint: (stepId: number) => void;
  setAnimationSpeed: (speed: AnimationSpeed) => void;
  updatePhaseDetail: (phase: string, data: any) => void;
  setCurrentAgentName: (name: string) => void;
  setPendingChatResult: (result: { data: any; agentName: string; pipelineSteps?: any[]; pipelineDetails?: Record<string, any> } | null) => void;
  setHumanActionRequired: (action: PipelineState["humanActionRequired"]) => void;
  setWorkflowRunId: (id: string | null) => void;
  setP2pStepData: (data: PipelineState["p2pStepData"]) => void;
  clearHumanGate: () => void;
  reset: () => void;
}
