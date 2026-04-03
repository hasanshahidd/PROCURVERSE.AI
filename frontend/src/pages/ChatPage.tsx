import { useState, useRef, useEffect, useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Send, Bot, User, Loader2, LogOut, CheckCircle2, Circle, ArrowDown, LayoutDashboard, Activity, AlertCircle, DollarSign, GitBranch, ShieldCheck, Users, Package, BarChart3, FileText, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { VoiceInput, speakText } from "@/components/VoiceInput";
import { LanguageSelector } from "@/components/LanguageSelector";
import { ChatSidebar } from "@/components/ChatSidebar";
import DataCharts from "@/components/DataCharts";
import { AgentProcessMonitor } from "@/components/AgentProcessMonitor";
import { PipelineSidePanel } from "@/components/PipelineSidePanel";
import { ResultCard } from "@/components/ResultCard";
import { usePipelineStore } from "@/store/pipelineStore";
import { usePipelineQueue } from "@/hooks/usePipelineQueue";
import type { QueryType, StepCategory } from "@/types/pipeline";
import { apiRequest } from "@/lib/queryClient";
import { extractAgentResult, isPrWorkflow as isPrWorkflowCheck, isVendorResult } from "@/lib/agentResultExtractor";
import { formatAgentMarkdown, buildResultCardProps } from "@/lib/agentFormatters";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useLocation, useSearch } from "wouter";
import { useToast } from "@/hooks/use-toast";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  dataSource?: string;
  queryType?: string;
  agentModeCard?: {
    agentType: string;
    agentName: string;
    description?: string;
  };
  chartData?: Array<Record<string, string | number | null | undefined>>;
  agentResult?: {
    agent: string;
    confidence: number;
    executionTimeMs: number;
    verdict: string;
    dataSource?: string;
    queryType?: string;
    score?: {
      total: number;
      subscores?: Record<string, number>;
    };
    findings: Array<{
      severity: 'error' | 'warning' | 'success' | 'info';
      message: string;
    }>;
    approvalChain?: Array<{
      level: number;
      approver: string;
      email: string;
      status: string;
    }>;
  };
}

interface ChatSession {
  id: string;
  title: string;
  timestamp: number;
  messages: Message[];
  language: string;
  processHistory?: Array<{
    messageId: string;
    agent: string;
    agents?: string[];
    query?: string;
    timestamp?: number;
    steps: any[];
    details: any;
  }>;
}

interface AgentStep {
  id: string;
  name: string;
  status: 'pending' | 'active' | 'complete' | 'error';
  message: string;
  agent?: string;
  startedAt?: number;
  completedAt?: number;
  durationMs?: number;
}

interface VendorChoiceOption {
  name: string;
  score?: number;
  reason?: string;
}

type PendingDepartmentSelection = {
  originalMessage: string;
  selectedDepartment: string;
  options: string[];
  context?: 'budget' | 'pr_creation';
};

type VendorResumeContext = {
  department?: string;
  budget?: number;
  budget_category?: string;
  category?: string;
  quantity?: number;
  product_name?: string;
  requester_name?: string;
  urgency?: string;
  justification?: string;
};

interface AgentRegistryItem {
  type: string;
  name: string;
  description?: string;
  status?: string;
  tools_count?: number;
}

interface AgentRegistryResponse {
  success: boolean;
  count: number;
  agents: AgentRegistryItem[];
}

const createLiveAgentSteps = (): AgentStep[] => [
  { id: 'received', name: 'Request Received', status: 'pending', message: 'Waiting for backend acknowledgment' },
  { id: 'classifying', name: 'Intent Classification', status: 'pending', message: 'Determining request intent' },
  { id: 'routing', name: 'Routing', status: 'pending', message: 'Selecting best agent/workflow' },
  { id: 'observing', name: 'Observe', status: 'pending', message: 'Gathering required context and data' },
  { id: 'deciding', name: 'Decide', status: 'pending', message: 'Model reasoning on gathered context' },
  { id: 'acting', name: 'Act', status: 'pending', message: 'Executing tool/database actions' },
  { id: 'learning', name: 'Learn', status: 'pending', message: 'Recording execution outcomes' },
  { id: 'complete', name: 'Finalize', status: 'pending', message: 'Preparing final response for UI' },
];

const extractVendorChoices = (payload: Record<string, any>): VendorChoiceOption[] => {
  const choices: VendorChoiceOption[] = [];

  const primary = payload?.primary_recommendation;
  if (primary?.vendor_name) {
    choices.push({
      name: String(primary.vendor_name),
      score: typeof primary.score === "number" ? primary.score : undefined,
      reason: primary.reason,
    });
  } else if (payload?.recommended_vendor) {
    choices.push({ name: String(payload.recommended_vendor) });
  }

  if (Array.isArray(payload?.alternative_recommendations)) {
    for (const alt of payload.alternative_recommendations) {
      if (!alt?.vendor_name) continue;
      choices.push({
        name: String(alt.vendor_name),
        score: typeof alt.score === "number" ? alt.score : undefined,
        reason: alt.reason,
      });
    }
  }

  if (Array.isArray(payload?.top_vendor_options)) {
    for (const opt of payload.top_vendor_options) {
      if (!opt) continue;
      const name = String(opt.vendor_name || opt.name || "").trim();
      if (!name) continue;
      choices.push({
        name,
        score: typeof opt.score === "number" ? opt.score : undefined,
        reason: opt.reason,
      });
    }
  }

  const unique = new Map<string, VendorChoiceOption>();
  for (const item of choices) {
    if (!item.name) continue;
    if (!unique.has(item.name)) unique.set(item.name, item);
  }
  return Array.from(unique.values()).slice(0, 5);
};

const STORAGE_KEY = "chat_sessions";
const ACTIVE_SESSION_KEY = "active_session_id";
const AGENT_MODE_STORAGE_KEY = "chat_selected_agent_type";
const COMPANY_DEPARTMENTS = ["IT", "Finance", "Operations", "Procurement", "HR"];


const getAgentModeGreeting = (agentName: string): string => {
  return `Hi, I am ${agentName}. I am ready to help with this agent workflow.`;
};

const getAgentIcon = (agentType: string) => {
  const normalized = (agentType || "").toLowerCase();
  if (normalized.includes("budget")) return DollarSign;
  if (normalized.includes("approval")) return GitBranch;
  if (normalized.includes("risk")) return ShieldCheck;
  if (normalized.includes("vendor") || normalized.includes("supplier")) return Users;
  if (normalized.includes("inventory")) return Package;
  if (normalized.includes("spend") || normalized.includes("price")) return BarChart3;
  if (normalized.includes("compliance") || normalized.includes("invoice") || normalized.includes("contract")) return FileText;
  return Bot;
};

// Helper functions for localStorage
const loadSessions = (): ChatSession[] => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
};

const saveSessions = (sessions: ChatSession[]) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  } catch (e) {
    console.error("Failed to save sessions:", e);
  }
};

const generateSessionTitle = (firstMessage: string): string => {
  // Generate title from first user message (max 80 chars for better context)
  const title = firstMessage.slice(0, 80).trim();
  return title.length < firstMessage.length ? title + "..." : title;
};

const inferQueryType = (message: string): QueryType => {
  const text = message.toLowerCase();

  if (text.includes("budget") || text.includes("capex") || text.includes("opex")) return "BUDGET";
  if (text.includes("vendor") || text.includes("supplier")) return "VENDOR";
  if (text.includes("risk") || text.includes("compliance") || text.includes("policy")) return "RISK";
  if (text.includes("approve") || text.includes("approval") || text.includes("workflow")) return "APPROVAL";
  return "COMPLIANCE";
};

const parseAmountWithSuffix = (rawAmount?: string, rawSuffix?: string): number | undefined => {
  if (!rawAmount) return undefined;

  const numeric = Number(rawAmount.replace(/,/g, ""));
  if (!Number.isFinite(numeric)) return undefined;

  const suffix = (rawSuffix || "").toLowerCase();
  const multiplier = suffix === "k" ? 1_000 : suffix === "m" ? 1_000_000 : 1;
  return numeric * multiplier;
};

const extractPrDataFromMessage = (message: string): Record<string, any> => {
  const vendorConfirmMatch = message.match(/^\s*confirm_vendor\s*:\s*"?([^"\n.]+?)"?\s*(?:\.|$)/i)
    || message.match(/^\s*select\s+vendor\s*:\s*"?([^"\n.]+?)"?\s*(?:\.|$)/i)
    || message.match(/^\s*user\s+selected\s+vendor\s*"([^"]+)"/i);

  const payload: Record<string, any> = {};

  if (vendorConfirmMatch?.[1]) {
    const selectedVendor = vendorConfirmMatch[1].trim();
    const workflowResume = /\bcontinue\s+pr\s+creation\s+workflow\b/i.test(message);
    Object.assign(payload, {
      intent_hint: "vendor_confirmation",
      workflow_resume: workflowResume,
      vendor_confirmed: true,
      selected_vendor_name: selectedVendor,
      vendor_name: selectedVendor,
    });
  }

  const text = message.toLowerCase();

  const deptMatch = text.match(/\b(it|finance|operations|procurement|hr)\b/i);
  const department = deptMatch
    ? (deptMatch[1].toLowerCase() === "it"
      ? "IT"
      : `${deptMatch[1].charAt(0).toUpperCase()}${deptMatch[1].slice(1).toLowerCase()}`)
    : undefined;

  const qtyKeywordMatch = text.match(/\b(?:quantity|qty)\s*[:=]?\s*(\d+)\b/i);
  const qtyItemMatch = text.match(/(\d+)\s*(?:laptop\s+accessories|laptops?|accessories|units?|items?|pcs?|pieces?)/i);
  const qtyMatch = qtyKeywordMatch || qtyItemMatch;
  const quantity = qtyMatch ? Number(qtyMatch[1]) : 1;
  const budgetCategoryMatch = text.match(/\b(capex|opex)\b/i);
  const budgetCategory = budgetCategoryMatch ? budgetCategoryMatch[1].toUpperCase() : undefined;

  const budgetContextMatch = text.match(/(?:budget|amount|total|cost)\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\b/i);
  const currencyMatch = text.match(/\$\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\b/i);
  const shorthandMatch = text.match(/\b([0-9][0-9,]*(?:\.\d+)?)\s*([km])\b/i);
  const dollarWordMatch = text.match(/\b([0-9][0-9,]*(?:\.\d+)?)\s*(?:dollars?|dollar|usd|bucks?|dollr|doller|follar|dolor)\b/i);
  const unitPriceEachMatch = text.match(/(?:at|for)\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\s*(?:each|per\s*(?:item|unit|pc|piece))\b/i);
  const atPriceMatch = text.match(/\bat\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\b/i);
  const parsedUnitPriceEach = parseAmountWithSuffix(unitPriceEachMatch?.[1], unitPriceEachMatch?.[2]);
  const parsedAtPrice = parseAmountWithSuffix(atPriceMatch?.[1], atPriceMatch?.[2]);

  // Parsing rule:
  // - "... at $X each/per ..." => total budget = quantity * X
  // - "... at $X ..." (without each/per) => total budget = X
  // - explicit "budget/amount/total/cost" phrases take precedence over plain currency mentions
  const budget = parsedUnitPriceEach !== undefined
    ? (quantity * parsedUnitPriceEach)
    : parseAmountWithSuffix(
      budgetContextMatch?.[1] || atPriceMatch?.[1] || currencyMatch?.[1] || shorthandMatch?.[1] || dollarWordMatch?.[1],
      budgetContextMatch?.[2] || atPriceMatch?.[2] || currencyMatch?.[2] || shorthandMatch?.[2]
    );

  const vendorFromMatch = message.match(/\bfrom\s+([^.,;\n]+?)(?=\s*(?:\.|,|;|$|business\s+justification))/i);
  const businessJustificationMatch = message.match(/\bbusiness\s+justification\s*:\s*(.+)$/i);
  const explicitJustificationMatch = message.match(/\bjustification\s*:\s*(.+)$/i);
  const justification = (businessJustificationMatch?.[1] || explicitJustificationMatch?.[1] || "").trim();

  const officeSuppliesRequested = /\boffice\s+supplies\b/i.test(message);

  const productName = officeSuppliesRequested
    ? "Office Supplies"
    : text.includes("laptop")
    ? "Laptop"
    : text.includes("printer")
      ? "Printer"
      : text.includes("server")
        ? "Server"
        : "Equipment";

  const isCreateIntent = /\b(create|raise|submit|make)\b.{0,40}\b(pr|purchase requisition|requisition)\b|\b(i want to|need to|please)\s+(buy|purchase|order)\b/i.test(text);

  if (!payload.intent_hint) {
    payload.intent_hint = isCreateIntent ? "pr_creation" : "general";
  }

  // Keep request payload conservative to avoid forcing wrong agent paths.
  if (department) payload.department = department;
  if (budget !== undefined && Number.isFinite(budget)) payload.budget = budget;
  if (budgetCategory) payload.budget_category = budgetCategory;
  if (qtyMatch) payload.quantity = quantity;
  if (/(laptop|printer|server|equipment|item)/i.test(text)) payload.product_name = productName;

  // For explicit create intents, fill missing operational defaults.
  if (isCreateIntent) {
    const hasAnyNumericToken = /\b\d+(?:\.\d+)?\b/.test(text);
    // NOTE: department is intentionally NOT defaulted here.
    // handleSend will prompt the user to choose a department if it is missing.
    // Do not override user-provided numeric requests with 50k fallback.
    if (payload.budget === undefined && !hasAnyNumericToken) payload.budget = 50000;
    if (!payload.quantity) payload.quantity = 1;
    if (!payload.product_name) payload.product_name = "Equipment";
    payload.category = officeSuppliesRequested ? "Office Supplies" : "Electronics";
    if (!payload.budget_category) payload.budget_category = officeSuppliesRequested ? "OPEX" : "CAPEX";
    payload.requester_name = "Chat User";
    payload.urgency = "Normal";
  }

  if (vendorFromMatch?.[1]) payload.vendor_name = vendorFromMatch[1].trim();
  if (justification) payload.justification = justification;
  if (officeSuppliesRequested) {
    payload.category = "Office Supplies";
    payload.product_name = "Office Supplies";
    if (!payload.budget_category) payload.budget_category = "OPEX";
  }

  if (payload.intent_hint === "vendor_confirmation") {
    if (!payload.requester_name) payload.requester_name = "Chat User";
    if (!payload.urgency) payload.urgency = "Normal";
    if (!payload.quantity) payload.quantity = 1;
    if (!payload.product_name && officeSuppliesRequested) payload.product_name = "Office Supplies";
  }

  return payload;
};

const shouldAttachFollowupHints = (currentMessage: string): boolean => {
  const text = currentMessage.trim().toLowerCase();
  if (!text) return false;

  const explicitDomain = /\b(pr|purchase request|purchase requisition|po|purchase order|purchase orders|budget|vendor|supplier|risk|approval|contract|compliance|invoice|inventory)\b/i.test(text);
  const explicitContext = /\b(it|finance|operations|procurement|hr|capex|opex)\b/i.test(text) || /\$?\s*\d/.test(text);

  // Keep previous hints only for short/ambiguous follow-ups (e.g. "what about 120k?").
  const likelyFollowup = /^(what about|and\b|also\b|same\b|it\b|this\b|that\b|those\b|now\b|then\b|re-?run\b|use same\b|keep\b|based on\b|from above\b|who approves this\b)/i.test(text);

  if (explicitDomain && explicitContext) return false;
  return likelyFollowup || text.split(/\s+/).length <= 7;
};

const resolveContextAwareMessage = (rawInput: string, history: Message[]): string => {
  const text = rawInput.trim();
  const lower = text.toLowerCase();
  const lastAssistant = [...history].reverse().find((m) => m.role === "assistant");

  const mentionsExplicitDomain = /\b(pr|purchase request|purchase requisition|po|purchase order|purchase orders|budget|vendor|supplier|risk|approval|contract|compliance|invoice|inventory)\b/i.test(lower);
  const likelyFollowupList = /\b(list|show|view)\b/i.test(lower) && /\b(all\s*\d+|those|them|that\s+list|those\s+list|list\s+here|all)\b/i.test(lower);
  const lastWasPOContext = Boolean(
    lastAssistant && (
      String(lastAssistant.dataSource || "").toLowerCase().includes("odoo")
      || /purchase orders|total purchase orders/i.test(lastAssistant.content || "")
    )
  );

  if (!mentionsExplicitDomain && likelyFollowupList && lastWasPOContext) {
    return `${text} purchase orders`;
  }

  return text;
};

const buildFollowupContextHints = (history: Message[], currentMessage: string): Record<string, string> => {
  if (!shouldAttachFollowupHints(currentMessage)) return {};

  const lastAssistant = [...history].reverse().find((m) => m.role === "assistant");
  const lastUser = [...history].reverse().find((m) => m.role === "user");

  if (!lastAssistant && !lastUser) return {};

  const hints: Record<string, string> = {};
  if (lastAssistant?.dataSource) hints._prev_data_source = String(lastAssistant.dataSource);
  if (lastAssistant?.queryType) hints._prev_query_type = String(lastAssistant.queryType);
  if (lastAssistant?.agentResult?.agent) hints._prev_agent = String(lastAssistant.agentResult.agent);
  if (lastUser?.content) hints._prev_user_message = String(lastUser.content).slice(0, 500);

  return hints;
};

export default function ChatPage() {
  const debugLog = (stage: string, data?: unknown) => {
    if (data !== undefined) {
      console.log(`[CHAT DEBUG] ${stage}`, data);
    } else {
      console.log(`[CHAT DEBUG] ${stage}`);
    }
  };

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [language, setLanguage] = useState("en");
  const [voiceOutputEnabled, setVoiceOutputEnabled] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [progressSteps, setProgressSteps] = useState<Array<{step: number, message: string, status: 'pending' | 'active' | 'completed'}>>([
    { step: 1, message: 'Analyzing your question', status: 'pending' },
    { step: 2, message: 'Searching for information', status: 'pending' },
    { step: 3, message: 'Generating response..', status: 'pending' },
    { step: 4, message: 'Finalizing answer..', status: 'pending' },
  ]);
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);
  const [currentAgent, setCurrentAgent] = useState<string>("");
  const [agentPhaseDetails, setAgentPhaseDetails] = useState<Record<string, any>>({});
  const [processedResult, setProcessedResult] = useState<any>(null);
  const [processHistory, setProcessHistory] = useState<Array<{messageId: string, agent: string, steps: any[], details: any}>>(() => {
    // Load process history from active session on init
    const sessions = loadSessions();
    const activeId = localStorage.getItem(ACTIVE_SESSION_KEY);  // Fix: Use localStorage directly
    const activeSession = sessions.find(s => s.id === activeId);
    return activeSession?.processHistory || [];
  });
  const [expandedHistory, setExpandedHistory] = useState<string | null>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [isPipelinePanelOpen, setIsPipelinePanelOpen] = useState(false);
  const [welcomeIntroVisible, setWelcomeIntroVisible] = useState(false);
  const [welcomeIntroPhase, setWelcomeIntroPhase] = useState<"center" | "to-top">("center");
  const [headerWelcomeVisible, setHeaderWelcomeVisible] = useState(true);
  const [sessionsReady, setSessionsReady] = useState(false);
  const [selectedAgentType, setSelectedAgentType] = useState<string>(() => {
    return localStorage.getItem(AGENT_MODE_STORAGE_KEY) || "auto";
  });
  const [isAgentModeOpen, setIsAgentModeOpen] = useState(false);
  const [pendingVendorSelection, setPendingVendorSelection] = useState<{
    sourceAgent: string;
    options: VendorChoiceOption[];
    resumeContext?: VendorResumeContext;
    requiresWorkflowResume?: boolean;
  } | null>(null);
  const [pendingDepartmentSelection, setPendingDepartmentSelection] = useState<PendingDepartmentSelection | null>(null);
  const [selectedVendorOption, setSelectedVendorOption] = useState("");
  const [vendorSelectionNote, setVendorSelectionNote] = useState("");
  const streamAbortRef = useRef<AbortController | null>(null);
  const observedAgentsRef = useRef<Set<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pipelineStepsRef = useRef<HTMLDivElement>(null);
  const isMountedRef = useRef(false);
  const vendorPromptFingerprintRef = useRef<string>("");
  const [, setLocation] = useLocation();
  const search = useSearch();
  const { toast } = useToast();
  const API_BASE_URL = import.meta.env.VITE_API_URL || '';

  const { data: agentRegistry } = useQuery<AgentRegistryResponse>({
    queryKey: ["/api/agentic/agents"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/api/agentic/agents`, {
        credentials: 'include',
      });
      if (!response.ok) {
        throw new Error(`Failed to load agents: ${response.status}`);
      }
      return response.json();
    },
    staleTime: 30000,
    retry: 1,
  });

  const agentModeOptions = useMemo(() => {
    const fetched = (agentRegistry?.agents || []).map((agent) => ({
      type: agent.type,
      name: agent.name,
      description: agent.description || "Specialized procurement workflow agent",
    }));

    return [
      {
        type: "auto",
        name: "Auto Routing",
        description: "Orchestrator chooses the best agent for each request",
      },
      ...fetched,
    ];
  }, [agentRegistry]);

  useEffect(() => {
    localStorage.setItem(AGENT_MODE_STORAGE_KEY, selectedAgentType);
  }, [selectedAgentType]);

  const selectedAgentMeta = useMemo(() => {
    return agentModeOptions.find((option) => option.type === selectedAgentType) || agentModeOptions[0];
  }, [agentModeOptions, selectedAgentType]);

  const handleAgentModeSelect = (agentType: string) => {
    if (agentType === selectedAgentType) {
      setIsAgentModeOpen(false);
      return;
    }

    const selected = agentModeOptions.find((option) => option.type === agentType);
    const selectedName = selected?.name || agentType;

    setSelectedAgentType(agentType);
    setPendingDepartmentSelection(null);
    setPendingVendorSelection(null);
    vendorPromptFingerprintRef.current = "";

    if (agentType !== "auto") {
      const modeMessage: Message = {
        id: `${Date.now()}_agent_switch_${agentType}`,
        role: "assistant",
        content: "",
        dataSource: "agent_mode",
        queryType: "AGENT_MODE",
        agentModeCard: {
          agentType,
          agentName: selectedName,
          description: selected?.description,
        },
      };

      setMessages((prev) => {
        const updated = [...prev, modeMessage];

        if (activeSessionId) {
          const title = sessions.find(s => s.id === activeSessionId)?.title || "New Chat";
          const updatedSessions = sessions.map(s =>
            s.id === activeSessionId
              ? { ...s, messages: updated, title, timestamp: Date.now() }
              : s
          );
          saveSessions(updatedSessions);
          setSessions(updatedSessions);
        }

        return updated;
      });
    }

    setIsAgentModeOpen(false);
  };

  const promptDepartmentSelection = (originalMessage: string, context: 'budget' | 'pr_creation' = 'budget') => {
    setPendingDepartmentSelection({
      originalMessage,
      selectedDepartment: COMPANY_DEPARTMENTS[0],
      options: COMPANY_DEPARTMENTS,
      context,
    });

    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}_department_prompt`,
        role: "assistant",
        content: context === 'pr_creation'
          ? "Which department is this purchase request for? Please select one from the list below to continue."
          : "Budget verification needs a department. Please choose one department from the list to continue.",
        dataSource: "Agentic",
        queryType: context === 'pr_creation' ? "CREATE" : "BUDGET",
      },
    ]);
  };

  const handleConfirmDepartmentFromPanel = () => {
    if (!pendingDepartmentSelection || chatMutation.isPending) return;

    const selectedDepartment = pendingDepartmentSelection.selectedDepartment;
    const userMessageText = `${pendingDepartmentSelection.originalMessage} (Department: ${selectedDepartment})`;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: userMessageText,
    };

    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);

    if (activeSessionId) {
      const title = sessions.find(s => s.id === activeSessionId)?.title || "New Chat";
      const updatedSessions = sessions.map(s =>
        s.id === activeSessionId
          ? { ...s, messages: updatedMessages, title: title === "New Chat" ? generateSessionTitle(userMessage.content) : title, timestamp: Date.now() }
          : s
      );
      saveSessions(updatedSessions);
    }

    setPendingDepartmentSelection(null);
    const composedRequest = `${pendingDepartmentSelection.originalMessage}. Department: ${selectedDepartment}.`;
    chatMutation.mutate(composedRequest);
    setInput("");
  };

  useEffect(() => {
    if (!sessionsReady) return;

    const params = new URLSearchParams(search);
    const explicitIntro = params.get("intro") === "1";
    const defaultIntroForEmptyAutoMode = messages.length === 0 && selectedAgentType === "auto";
    const shouldRunIntro = explicitIntro || defaultIntroForEmptyAutoMode;

    if (!shouldRunIntro || messages.length > 0) {
      setWelcomeIntroVisible(false);
      setHeaderWelcomeVisible(true);
      setWelcomeIntroPhase("center");
      return;
    }

    setHeaderWelcomeVisible(false);
    setWelcomeIntroVisible(true);
    setWelcomeIntroPhase("center");

    const promoteTimer = window.setTimeout(() => {
      setWelcomeIntroPhase("to-top");
    }, 900);

    const finishTimer = window.setTimeout(() => {
      setWelcomeIntroVisible(false);
      setHeaderWelcomeVisible(true);
      setWelcomeIntroPhase("center");
    }, 1800);

    return () => {
      window.clearTimeout(promoteTimer);
      window.clearTimeout(finishTimer);
    };
  }, [search, messages.length, selectedAgentType, sessionsReady]);

  useEffect(() => {
    if (!pendingVendorSelection || pendingVendorSelection.options.length === 0) {
      setSelectedVendorOption("");
      setVendorSelectionNote("");
      return;
    }

    setSelectedVendorOption((prev) => {
      if (prev && pendingVendorSelection.options.some((opt) => opt.name === prev)) {
        return prev;
      }
      return pendingVendorSelection.options[0]?.name || "";
    });
  }, [pendingVendorSelection]);

  const maybePromptVendorSelection = (normalised: any) => {
    const payload = normalised?.payload || {};
    const workflowStatus = String(payload?.status || "").toLowerCase();
    if (workflowStatus === "failed" || workflowStatus === "error") {
      setPendingVendorSelection(null);
      vendorPromptFingerprintRef.current = "";
      return;
    }
    const workflowContext = payload?.workflow_context || {};
    const workflowPrData = workflowContext?.pr_data || {};
    const isWorkflowConfirmationStep =
      payload?.awaiting_vendor_confirmation === true
      || workflowStatus === "awaiting_vendor_confirmation";

    if (!isWorkflowConfirmationStep) {
      // Standalone vendor recommendations should not force selection UI.
      setPendingVendorSelection(null);
      vendorPromptFingerprintRef.current = "";
      return;
    }

    const options = extractVendorChoices(payload);
    if (options.length === 0) return;

    const fingerprint = `${normalised.agent}:${options.map((o) => o.name).join("|")}`;
    if (vendorPromptFingerprintRef.current === fingerprint) return;

    vendorPromptFingerprintRef.current = fingerprint;
    setPendingVendorSelection({
      sourceAgent: normalised.agent || "VendorSelectionAgent",
      options,
      requiresWorkflowResume: true,
      resumeContext: {
        department: payload?.department ?? workflowContext?.department ?? workflowPrData?.department,
        budget: typeof payload?.budget === "number"
          ? payload.budget
          : (typeof workflowContext?.budget === "number" ? workflowContext.budget : workflowPrData?.budget),
        budget_category: payload?.budget_category ?? workflowContext?.budget_category ?? workflowPrData?.budget_category,
        category: payload?.category ?? workflowContext?.category ?? workflowPrData?.category,
        quantity: typeof payload?.quantity === "number"
          ? payload.quantity
          : (typeof workflowContext?.quantity === "number" ? workflowContext.quantity : workflowPrData?.quantity),
        product_name: payload?.product_name ?? workflowContext?.product_name ?? workflowPrData?.product_name,
        requester_name: payload?.requester_name ?? workflowContext?.requester_name ?? workflowPrData?.requester_name,
        urgency: payload?.urgency ?? workflowPrData?.urgency,
        justification: payload?.justification ?? workflowContext?.justification ?? workflowPrData?.justification,
      },
    });

    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}_vendor_prompt`,
        role: "assistant",
        content: "Please choose a vendor to continue PR creation. You can add a comment with your selection (for example: 'Vendor Name - reason').",
        dataSource: "Agentic",
        queryType: "VENDOR",
      },
    ]);
  };

  const scrollChatToBottomExact = (reason: string, attempts = 6) => {
    console.log(`[CHAT SCROLL] Request bottom scroll | reason=${reason} | attempts=${attempts}`);
    let attempt = 0;

    const tick = () => {
      attempt += 1;
      const container = scrollRef.current;
      if (container) {
        container.scrollTop = container.scrollHeight;
        console.log(
          `[CHAT SCROLL] attempt=${attempt} top=${container.scrollTop} height=${container.scrollHeight} client=${container.clientHeight}`
        );
      }
      messagesEndRef.current?.scrollIntoView({ behavior: attempt === 1 ? "smooth" : "auto", block: "end" });

      if (attempt < attempts) {
        requestAnimationFrame(tick);
      }
    };

    requestAnimationFrame(tick);
  };
  
  // Pipeline queue for delayed visualization
  const pipelineQueue = usePipelineQueue();
  
  // Create alias for queued pipeline methods (replaces direct store calls)
  const queuedPipeline = {
    ...usePipelineStore.getState(),
    ...pipelineQueue, // Override methods with queued versions
  };

  // Load sessions on mount
  useEffect(() => {
    const loadedSessions = loadSessions();
    setSessions(loadedSessions);

    const params = new URLSearchParams(search);
    const forceNewFromQuery = params.get("new") === "1";
    const forceNewFromStorage = localStorage.getItem("force_new_chat_session") === "1";
    const forceNewSession = forceNewFromQuery || forceNewFromStorage;

    if (forceNewSession) {
      localStorage.removeItem("force_new_chat_session");

      const newSession: ChatSession = {
        id: Date.now().toString(),
        title: "New Chat",
        timestamp: Date.now(),
        messages: [],
        language: "en",
        processHistory: [],
      };

      const updatedSessions = [newSession, ...loadedSessions];
      setSessions(updatedSessions);
      saveSessions(updatedSessions);
      setActiveSessionId(newSession.id);
      setMessages([]);
      setLanguage("en");
      setProcessHistory([]);
      localStorage.setItem(ACTIVE_SESSION_KEY, newSession.id);

      toast({
        title: "New Chat",
        description: "Started a new conversation",
      });

      setSessionsReady(true);
      return;
    }
    
    // Load active session or create new one
    const lastActiveId = localStorage.getItem(ACTIVE_SESSION_KEY);
    if (lastActiveId && loadedSessions.find(s => s.id === lastActiveId)) {
      const activeSession = loadedSessions.find(s => s.id === lastActiveId)!;
      setActiveSessionId(lastActiveId);
      setMessages(activeSession.messages);
      setLanguage(activeSession.language);
      setProcessHistory(activeSession.processHistory || []);  // Load process history
    } else if (loadedSessions.length > 0) {
      // Load most recent session
      const recent = loadedSessions[0];
      setActiveSessionId(recent.id);
      setMessages(recent.messages);
      setLanguage(recent.language);
      setProcessHistory(recent.processHistory || []);  // Load process history
      localStorage.setItem(ACTIVE_SESSION_KEY, recent.id);
    } else {
      // Create first session
      createNewSession();
    }

    setSessionsReady(true);
  }, [search]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    if (!showScrollButton) {
      scrollChatToBottomExact("messages-change", 4);
    }
  }, [messages, streamingContent, isStreaming, agentSteps]);

  // Auto-scroll to keep pipeline steps visible during streaming
  useEffect(() => {
    if (!isStreaming) return;
    // Scroll to the currently active step element
    const activeStep = agentSteps.find(s => s.status === 'active');
    if (activeStep) {
      const el = document.getElementById(`inline-step-${activeStep.id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        return;
      }
    }
    // Fallback: scroll the whole pipeline bubble into view
    if (pipelineStepsRef.current) {
      pipelineStepsRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [agentSteps, isStreaming]);

  // NOTE: We intentionally do NOT abort the SSE stream on unmount.
  // The stream writes to Zustand (pipelineStore) which survives navigation.
  // This allows the user to navigate to /process and see live progress.

  // Track mounted state so onSuccess knows not to clear pendingChatResult when unmounted
  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, []);

  // On mount: check if there's a pending chat result from a stream that completed
  // while we were on the /process page. If so, consume it and add to messages.
  useEffect(() => {
    const pending = usePipelineStore.getState().pendingChatResult;
    if (!pending) return;

    console.log('[CHAT RETURN] Found pendingChatResult, restoring assistant response after /process');
    
    // Consume immediately so we don't re-process
    usePipelineStore.getState().setPendingChatResult(null);

    const agentName = pending.agentName || usePipelineStore.getState().currentAgentName || "Agent";
    const normalised = extractAgentResult(pending.data, agentName);
    let formattedContent = formatAgentMarkdown(normalised);

    if (isPrWorkflowCheck(normalised) && normalised.status === "success") {
      setTimeout(() => setLocation("/approval-workflows"), 900);
    }

    const cardProps = buildResultCardProps(normalised);
    const agentDurationMs = usePipelineStore.getState().agentExecutions.find((exec) => exec.name === normalised.agent)?.durationMs;
    const pipelineElapsedMs = usePipelineStore.getState().elapsed;
    if (!cardProps.executionTimeMs && (agentDurationMs || pipelineElapsedMs)) {
      cardProps.executionTimeMs = agentDurationMs || pipelineElapsedMs || 0;
    }

    const isGeneralQuery = normalised.dataSource === "general" || normalised.queryType === "GENERAL";
    const agentResult = isGeneralQuery ? undefined : cardProps;

    const assistantMessage: Message = {
      id: Date.now().toString(),
      role: "assistant",
      content: formattedContent,
      dataSource: normalised.dataSource,
      queryType: normalised.queryType || undefined,
      agentResult,
    };
    setMessages((prev) => [...prev, assistantMessage]);
    if (!isVendorResult(normalised)) {
      setPendingVendorSelection(null);
      vendorPromptFingerprintRef.current = "";
    }
    maybePromptVendorSelection(normalised);
    setTimeout(() => scrollChatToBottomExact("pending-result-restored", 8), 0);
    setTimeout(() => scrollChatToBottomExact("pending-result-restored-late", 8), 200);

    // Save to process history
    const storeState = usePipelineStore.getState();
    setProcessHistory(prev => [
      {
        messageId: assistantMessage.id,
        agent: agentName,
        agents: [...new Set(storeState.agentExecutions.map(e => e.name))],
        query: storeState.queryText || "",
        timestamp: Date.now(),
        steps: [],
        details: { ...storeState.agentPhaseDetails },
      },
      ...prev.slice(0, 9),
    ]);
  }, []);

  // Handle scroll to detect if user scrolled up
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const target = e.currentTarget;
    const isNearBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 100;
    setShowScrollButton(!isNearBottom);
  };

  // Scroll to bottom function
  const scrollToBottom = () => {
    scrollChatToBottomExact("manual-scroll-button", 6);
  };

  // Save current session whenever messages change
  useEffect(() => {
    if (!activeSessionId || messages.length === 0) return;
    
    setSessions(prevSessions => {
      const updated = prevSessions.map(session => {
        if (session.id === activeSessionId) {
          const title = session.title === "New Chat" && messages.length > 0
            ? generateSessionTitle(messages[0].content)
            : session.title;
          
          return {
            ...session,
            title,
            messages,
            language,
            processHistory,  // Save process history with session
            timestamp: Date.now(),
          };
        }
        return session;
      });
      
      saveSessions(updated);
      return updated;
    });
  }, [messages, activeSessionId, language, processHistory]);  // Add processHistory to deps

  const createNewSession = () => {
    const newSession: ChatSession = {
      id: Date.now().toString(),
      title: "New Chat",
      timestamp: Date.now(),
      messages: [],
      language: "en",
      processHistory: [],  // Initialize empty process history
    };
    
    setSessions(prev => {
      const updated = [newSession, ...prev];
      saveSessions(updated);
      return updated;
    });
    
    setActiveSessionId(newSession.id);
    setMessages([]);
    setLanguage("en");
    localStorage.setItem(ACTIVE_SESSION_KEY, newSession.id);
    
    toast({
      title: "New Chat",
      description: "Started a new conversation",
    });
  };

  const switchSession = (sessionId: string) => {
    const session = sessions.find(s => s.id === sessionId);
    if (!session) return;
    
    setActiveSessionId(sessionId);
    setMessages(session.messages);
    setLanguage(session.language);
    setProcessHistory(session.processHistory || []);  // Load process history for this session
    localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  };

  const deleteSession = (sessionId: string) => {
    if (sessions.length === 1) {
      toast({
        title: "Cannot Delete",
        description: "You must have at least one chat session",
        variant: "destructive",
      });
      return;
    }
    
    setSessions(prev => {
      const updated = prev.filter(s => s.id !== sessionId);
      saveSessions(updated);
      return updated;
    });
    
    // If deleting active session, switch to another
    if (sessionId === activeSessionId) {
      const remaining = sessions.filter(s => s.id !== sessionId);
      if (remaining.length > 0) {
        switchSession(remaining[0].id);
      }
    }
    
    toast({
      title: "Chat Deleted",
      description: "Conversation removed from history",
    });
  };

  const handleLogout = () => {
    localStorage.removeItem("isAuthenticated");
    localStorage.removeItem("userEmail");
    toast({
      title: "Logged Out",
      description: "You have been successfully logged out.",
    });
    setLocation("/");
  };

  const chatMutation = useMutation({
    mutationFn: async (message: string) => {
      const parsedPrData = extractPrDataFromMessage(message);
      const contextHints = buildFollowupContextHints(messages, message);
      const isCreateIntent = parsedPrData.intent_hint === "pr_creation";
      const isWorkflowResume = parsedPrData.workflow_resume === true;
      const forcedAgentType = selectedAgentType !== "auto" ? selectedAgentType : undefined;
      const requestedAgentType = forcedAgentType || ((isCreateIntent || isWorkflowResume) ? 'pr_creation' : undefined);

      console.log('\n' + '='.repeat(80));
      console.log('[CHAT MUTATION START]');
      console.log('='.repeat(80));
      console.log('[USER MESSAGE]', message);
      console.log('[LANGUAGE]', language);
      console.log('[TIMESTAMP]', new Date().toISOString());
      console.log('='.repeat(80));
      
      setIsStreaming(true);
      setStreamingContent("");
      setAgentSteps(createLiveAgentSteps());
      setCurrentAgent("");
      
      setLoadingMessage("Processing...");
      setIsPipelinePanelOpen(true);
      const mutationStartMs = Date.now();
      let streamAgentName = "";
      observedAgentsRef.current = new Set();
      debugLog("stream:start", {
        message,
        parsedPrData,
        contextHints,
        isCreateIntent,
        isWorkflowResume,
        requestedAgentType,
        language,
      });

      // Start real-time pipeline visualization (driven by SSE backend events).
      usePipelineStore.getState().startPipeline(
        message,
        inferQueryType(message),
        { department: parsedPrData.department, budget: parsedPrData.budget }
      );
      queuedPipeline.advanceStep(1, `query=\"${message.slice(0, 80)}\"`);
      queuedPipeline.completeStep(1);
      queuedPipeline.advanceStep(2, 'Sending request to backend stream endpoint');
      queuedPipeline.addLog("FRONTEND", "Request built from chat input", 0);

      console.log('\ud83d\udd17 [FETCH] Preparing SSE request...');
      console.log('[API_URL]', API_BASE_URL);
      console.log('[REQUEST_BODY]', {
        request: message,
        pr_data: { ...parsedPrData, ...contextHints },
        agent_type: requestedAgentType,
      });
      
      const abortController = new AbortController();
      streamAbortRef.current = abortController;

      const response = await fetch(`${API_BASE_URL}/api/agentic/execute/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          request: message, 
          pr_data: { ...parsedPrData, ...contextHints },
          agent_type: requestedAgentType,
        }),
        credentials: 'include',
        signal: abortController.signal,
      });

      console.log('[RESPONSE STATUS]', response.status, response.statusText);
      
      if (!response.ok) {
        console.error('[FETCH ERROR]', response.status, response.statusText);
        const retryAfter = response.headers.get('Retry-After');
        if (response.status === 429) {
          throw new Error(
            `Backend returned 429: Too Many Requests${retryAfter ? ` (retry in ${retryAfter}s)` : ''}`
          );
        }
        throw new Error(`Backend returned ${response.status}: ${response.statusText}`);
      }

      // Navigate to Agent Process Theater only after stream is accepted.
      // This avoids redirecting to /process for rejected requests (e.g., 429).
      setLocation("/process");
      
      console.log('\u2705 [FETCH SUCCESS] Reading event stream...');

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let finalData: any = null;

      if (!reader) {
        console.error('❌ [READER ERROR] No body reader available');
        throw new Error('No response body reader');
      }

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const event = JSON.parse(line.slice(6));
                console.log('[SSE EVENT]', event.type, event);
                debugLog("sse:event", {
                  type: event?.type,
                  agent: event?.data?.agent,
                  message: event?.data?.message,
                  timestamp: event?.timestamp,
                });
                
                const eventTs = event?.timestamp ? Date.parse(event.timestamp) : Date.now();
                const elapsedMs = Number.isFinite(eventTs) && eventTs > 0
                  ? Math.max(0, eventTs - mutationStartMs)
                  : 0;

                // Update agent steps with real timing (start/end/duration)
                const updateStep = (
                  id: string,
                  status: 'pending' | 'active' | 'complete' | 'error',
                  message?: string,
                  agent?: string
                ) => {
                  setAgentSteps(prev => prev.map(step => {
                    if (step.id !== id) return step;

                    const startedAt = status === 'active'
                      ? (step.startedAt ?? eventTs)
                      : step.startedAt;

                    const completedAt = (status === 'complete' || status === 'error')
                      ? (step.completedAt ?? eventTs)
                      : step.completedAt;

                    const durationMs = (status === 'complete' || status === 'error')
                      ? Math.max(0, (completedAt ?? eventTs) - (startedAt ?? eventTs))
                      : step.durationMs;

                    return {
                      ...step,
                      status,
                      message: message || step.message,
                      agent: agent || step.agent,
                      startedAt,
                      completedAt,
                      durationMs,
                    };
                  }));
                };

                const pipelineLog = (category: StepCategory, message: string) => {
                  queuedPipeline.addLog(category, message, elapsedMs);
                };

                const resolveEventAgent = (): string => {
                  return String(event?.data?.agent || streamAgentName || "").trim();
                };
                
                switch (event.type) {
                  case 'received':
                    updateStep('received', 'complete', 'POST request dispatched');
                    queuedPipeline.completeStep(2);
                    queuedPipeline.advanceStep(3, `request_id=${event.data.request_id || 'unknown'}`);
                    setAgentPhaseDetails(prev => ({...prev, received: {message: event.data.request || 'Query received', timestamp: new Date().toISOString()}}));
                    queuedPipeline.updatePhaseDetail('received', {message: event.data.request || message, timestamp: new Date().toISOString()});
                    pipelineLog('FASTAPI', 'Request dispatched to /api/agentic/execute/stream');
                    break;
                  case 'classifying':
                    updateStep('received', 'complete');
                    updateStep('classifying', 'active', 'Analyzing user intent and routing request...');
                    queuedPipeline.completeStep(3);
                    queuedPipeline.advanceStep(4, event.data.message || 'Orchestrator analyzing request intent');
                    pipelineLog('CLASSIFY', event.data.message || 'Orchestrator analyzing request intent');
                    break;
                  case 'routing':
                    updateStep('classifying', 'complete', 'Intent classified successfully');
                    updateStep('routing', 'active', 'Routing to specialized agent...');
                    setAgentPhaseDetails(prev => ({...prev, classifying: {intent: event.data.intent || 'Analyzing'}}));
                    queuedPipeline.updatePhaseDetail('classifying', {intent: event.data.intent || 'Analyzing'});
                    queuedPipeline.completeStep(4);
                    queuedPipeline.advanceStep(5, event.data.message || 'Routing request');
                    pipelineLog('ORCHESTRATE', event.data.message || 'Routing request');
                    break;
                  case 'agent_selected':
                    console.log('[AGENT SELECTED]', event.data.agent, 'Confidence:', event.data.confidence);
                    console.log('[ROUTING REASON]', event.data.reasoning);
                    debugLog('agent:selected', {
                      previousAgent: streamAgentName,
                      nextAgent: event.data.agent,
                      confidence: event.data.confidence,
                      secondaryAgents: event.data.secondary_agents || [],
                    });
                    // If orchestrator switches to another specialized agent, close the previous one.
                    if (
                      streamAgentName &&
                      event.data.agent &&
                      streamAgentName !== event.data.agent &&
                      streamAgentName !== 'OrchestratorAgent'
                    ) {
                      queuedPipeline.completeAgentExecution(streamAgentName, 'Workflow step complete');
                    }
                    updateStep('routing', 'complete', `Agent selected: ${event.data.agent}`);
                    setCurrentAgent(event.data.agent);
                    streamAgentName = String(event.data.agent || "");
                    if (streamAgentName) observedAgentsRef.current.add(streamAgentName);
                    for (const secondary of (event.data.secondary_agents || [])) {
                      if (secondary) observedAgentsRef.current.add(String(secondary));
                    }
                    debugLog('agent:observed-set', Array.from(observedAgentsRef.current));
                    setAgentPhaseDetails(prev => ({...prev, routing: {
                      agent: event.data.agent, 
                      reason: event.data.reasoning || 'Best match for request',
                      confidence: event.data.confidence || 0.95
                    }}));
                    queuedPipeline.updatePhaseDetail('routing', {
                      agent: event.data.agent,
                      reason: event.data.reasoning || 'Best match for request',
                      confidence: event.data.confidence || 0.95
                    });
                    queuedPipeline.setCurrentAgentName(String(event.data.agent || ""));
                    queuedPipeline.completeStep(5);
                    queuedPipeline.advanceStep(6, `Agent selected: ${event.data.agent}`);
                    queuedPipeline.selectAgent(event.data.agent, event.data.confidence || 0.95);
                    queuedPipeline.upsertAgentExecution(event.data.agent, {
                      status: 'active',
                      confidence: event.data.confidence || 0.95,
                      lastMessage: event.data.reasoning || 'Selected by orchestrator',
                    });
                    for (const secondary of (event.data.secondary_agents || [])) {
                      queuedPipeline.selectAgent(String(secondary), event.data.confidence || 0.8);
                      queuedPipeline.upsertAgentExecution(String(secondary), {
                        status: 'active',
                        confidence: event.data.confidence || 0.8,
                        lastMessage: 'Queued as secondary agent',
                      });
                    }
                    pipelineLog('ORCHESTRATE', `Selected ${event.data.agent}`);
                    break;
                  case 'observing': {
                    const _obsAgent = resolveEventAgent();
                    if (_obsAgent) observedAgentsRef.current.add(_obsAgent);
                    updateStep('observing', 'active', 'Gathering data from databases and systems...', _obsAgent);
                    updateStep('routing', 'complete', `Agent selected: ${_obsAgent || 'Specialized agent'}`);
                    setAgentPhaseDetails(prev => ({...prev, observing: {
                      status: 'active', 
                      details: event.data.message || 'Fetching context...',
                      sources: event.data.sources || ['Internal Memory']  // Use real backend data
                    }}));
                    const _obsData = {
                      status: 'active',
                      sources: event.data.sources || ['Internal Memory'],
                      agent: _obsAgent,
                    };
                    queuedPipeline.updatePhaseDetail('observing', _obsData);
                    if (_obsAgent) queuedPipeline.updatePhaseDetail(`${_obsAgent}_observing`, _obsData);
                    queuedPipeline.completeStep(6);
                    queuedPipeline.advanceStep(7, `${event.data.agent || 'Agent'} reading: ${(event.data.sources || []).join(', ') || 'internal memory'}`);
                    queuedPipeline.activatePhase('OBSERVE', event.data.message || 'Gathering context');
                    if (_obsAgent) {
                      queuedPipeline.setAgentPhase(
                        _obsAgent,
                        'OBSERVE',
                        'active',
                        event.data.message || 'Gathering context'
                      );
                    }
                    pipelineLog('BASEAGENT', event.data.message || 'Observe phase started');
                    break;
                  }
                  case 'observation_complete': {
                    const _obsDoneAgent = resolveEventAgent();
                    if (_obsDoneAgent) observedAgentsRef.current.add(_obsDoneAgent);
                    updateStep('observing', 'complete', 'Data gathered successfully', _obsDoneAgent);
                    setAgentPhaseDetails(prev => ({...prev, observing: {
                      ...prev.observing, 
                      status: 'complete', 
                      data: event.data.observations || 'Context loaded',
                      recordsFound: event.data.records_count || 'Multiple records'
                    }}));
                    const _obsDoneData = {
                      ...usePipelineStore.getState().agentPhaseDetails.observing,
                      status: 'complete',
                      recordsFound: event.data.records_count || 'Multiple records',
                      agent: _obsDoneAgent,
                    };
                    queuedPipeline.updatePhaseDetail('observing', _obsDoneData);
                    if (_obsDoneAgent) queuedPipeline.updatePhaseDetail(`${_obsDoneAgent}_observing`, _obsDoneData);
                    queuedPipeline.completeStep(7);
                    if (_obsDoneAgent) {
                      queuedPipeline.setAgentPhase(
                        _obsDoneAgent,
                        'OBSERVE',
                        'complete',
                        'Context ready'
                      );
                    }
                    break;
                  }
                  case 'deciding': {
                    const _decAgent = resolveEventAgent();
                    if (_decAgent) observedAgentsRef.current.add(_decAgent);
                    updateStep('deciding', 'active', 'AI analyzing data and making decision...', _decAgent);
                    setAgentPhaseDetails(prev => ({...prev, deciding: {
                      status: 'active', 
                      model: event.data.model || 'GPT-4o-mini'
                    }}));
                    const _decData = {
                      status: 'active',
                      model: event.data.model || 'GPT-4o-mini',
                      agent: _decAgent,
                    };
                    queuedPipeline.updatePhaseDetail('deciding', _decData);
                    if (_decAgent) queuedPipeline.updatePhaseDetail(`${_decAgent}_deciding`, _decData);
                    queuedPipeline.advanceStep(8, `${event.data.model || 'GPT-4o-mini'} decision in progress`);
                    queuedPipeline.activatePhase('DECIDE', event.data.message || 'Reasoning on context');
                    if (_decAgent) {
                      queuedPipeline.setAgentPhase(
                        _decAgent,
                        'DECIDE',
                        'active',
                        event.data.message || 'Decision in progress'
                      );
                    }
                    pipelineLog('BASEAGENT', event.data.message || 'Decide phase started');
                    break;
                  }
                  case 'decision_made': {
                    const _dmAgent = resolveEventAgent();
                    if (_dmAgent) observedAgentsRef.current.add(_dmAgent);
                    const confidence = Math.round(event.data.confidence * 100);
                    updateStep('deciding', 'complete', `Decision: ${event.data.action} (${confidence}% confidence)`, _dmAgent);
                    setAgentPhaseDetails(prev => ({...prev, deciding: {
                      action: event.data.action, 
                      confidence, 
                      reasoning: event.data.reasoning || 'Analysis complete',
                      alternatives: event.data.alternatives || []
                    }}));
                    const _dmData = {
                      action: event.data.action,
                      confidence,
                      reasoning: event.data.reasoning || 'Analysis complete',
                      model: usePipelineStore.getState().agentPhaseDetails.deciding?.model || 'GPT-4o-mini',
                      alternatives: event.data.alternatives || [],
                      agent: _dmAgent,
                    };
                    queuedPipeline.updatePhaseDetail('deciding', _dmData);
                    if (_dmAgent) queuedPipeline.updatePhaseDetail(`${_dmAgent}_deciding`, _dmData);
                    queuedPipeline.completeStep(8);
                    if (_dmAgent) {
                      queuedPipeline.setAgentPhase(
                        _dmAgent,
                        'DECIDE',
                        'complete',
                        `Decision: ${event.data.action}`
                      );
                    }
                    pipelineLog('BASEAGENT', `Decision made: ${event.data.action} (${confidence}%)`);
                    break;
                  }
                  case 'acting': {
                    const _actAgent = resolveEventAgent();
                    if (_actAgent) observedAgentsRef.current.add(_actAgent);
                    updateStep('acting', 'active', 'Executing actions and tools...', _actAgent);
                    setAgentPhaseDetails(prev => ({...prev, acting: {
                      status: 'active', 
                      action: event.data.message || 'Processing...',
                      tools: event.data.tools || []
                    }}));
                    const _actData = {
                      status: 'active',
                      tools: event.data.tools || [],
                      agent: _actAgent,
                    };
                    queuedPipeline.updatePhaseDetail('acting', _actData);
                    if (_actAgent) queuedPipeline.updatePhaseDetail(`${_actAgent}_acting`, _actData);
                    queuedPipeline.activatePhase('ACT', event.data.message || 'Executing tools');
                    if (_actAgent) {
                      queuedPipeline.setAgentPhase(
                        _actAgent,
                        'ACT',
                        'active',
                        event.data.message || 'Executing tools'
                      );
                    }
                    queuedPipeline.advanceStep(9, `Tools: ${(event.data.tools || []).slice(0, 3).join(', ') || 'none listed'}`);
                    pipelineLog('TOOL', event.data.message || 'Executing tool calls');

                    // Add real tool list into panel groups (PostgreSQL vs Odoo)
                    const isEstimatedToolList = Boolean(event.data.tools_estimated);
                    if (!isEstimatedToolList) {
                      for (const toolName of (event.data.tools || [])) {
                      const lowerName = String(toolName).toLowerCase();
                      const source = (lowerName.includes('budget') || lowerName.includes('approval') || lowerName.includes('chain'))
                        ? 'PostgreSQL'
                        : 'Odoo';
                      usePipelineStore.getState().addToolCall({
                        source,
                        name: String(toolName),
                      });
                    }
                    }
                    break;
                  }
                  case 'action_complete': {
                    const _actDoneAgent = resolveEventAgent();
                    if (_actDoneAgent) observedAgentsRef.current.add(_actDoneAgent);
                    updateStep('acting', 'complete', `Execution complete (${event.data.execution_time_ms}ms)`, _actDoneAgent);
                    setAgentPhaseDetails(prev => ({...prev, acting: {
                      ...prev.acting, 
                      status: 'complete', 
                      timing: event.data.execution_time_ms,
                      result: event.data.result || 'Success'
                    }}));
                    const _actDoneData = {
                      ...usePipelineStore.getState().agentPhaseDetails.acting,
                      status: 'complete',
                      timing: event.data.execution_time_ms,
                      agent: _actDoneAgent,
                    };
                    queuedPipeline.updatePhaseDetail('acting', _actDoneData);
                    if (_actDoneAgent) queuedPipeline.updatePhaseDetail(`${_actDoneAgent}_acting`, _actDoneData);
                    queuedPipeline.completeStep(9);
                    if (_actDoneAgent) {
                      queuedPipeline.setAgentPhase(
                        _actDoneAgent,
                        'ACT',
                        'complete',
                        event.data.result || 'Action complete'
                      );
                    }

                    // Mark all pending tool calls complete with backend summary
                    for (const tool of usePipelineStore.getState().toolCalls) {
                      if (tool.status !== 'complete') {
                        usePipelineStore.getState().completeToolCall(tool.id, event.data.result || 'Done');
                      }
                    }
                    break;
                  }
                  case 'learning': {
                    const _learnAgent = resolveEventAgent();
                    if (_learnAgent) observedAgentsRef.current.add(_learnAgent);
                    updateStep('learning', 'active', 'Recording decisions and outcomes to database...');
                    setAgentPhaseDetails(prev => ({...prev, learning: {status: 'active', table: 'agent_actions'}}));
                    const _learnData = { status: 'active', table: 'agent_actions', agent: _learnAgent };
                    queuedPipeline.updatePhaseDetail('learning', _learnData);
                    if (_learnAgent) queuedPipeline.updatePhaseDetail(`${_learnAgent}_learning`, _learnData);
                    queuedPipeline.activatePhase('LEARN', event.data.message || 'Recording outcomes');
                    if (_learnAgent) {
                      queuedPipeline.setAgentPhase(
                        _learnAgent,
                        'LEARN',
                        'active',
                        event.data.message || 'Recording outcomes'
                      );
                    }
                    queuedPipeline.advanceStep(10, `Writing audit trail to ${event.data.table || 'agent_actions'}`);
                    pipelineLog('BASEAGENT', event.data.message || 'Learning phase started');
                    break;
                  }
                  case 'learning_complete': {
                    const _learnDoneAgent = resolveEventAgent();
                    if (_learnDoneAgent) observedAgentsRef.current.add(_learnDoneAgent);
                    updateStep('learning', 'complete', 'Audit trail saved to agent_actions table');
                    updateStep('complete', 'active', 'Preparing human-readable response');
                    setAgentPhaseDetails(prev => ({...prev, learning: {status: 'complete', recorded: true}}));
                    const _learnDoneData = { status: 'complete', recorded: true, agent: _learnDoneAgent };
                    queuedPipeline.updatePhaseDetail('learning', _learnDoneData);
                    if (_learnDoneAgent) queuedPipeline.updatePhaseDetail(`${_learnDoneAgent}_learning`, _learnDoneData);
                    queuedPipeline.completeStep(10);
                    if (_learnDoneAgent) {
                      queuedPipeline.setAgentPhase(
                        _learnDoneAgent,
                        'LEARN',
                        'complete',
                        'Execution recorded'
                      );
                      queuedPipeline.completeAgentExecution(_learnDoneAgent, 'Execution recorded');
                    }
                    queuedPipeline.advanceStep(11, 'Response formatted for UI');
                    break;
                  }
                  case 'complete':
                    console.log('[COMPLETE EVENT]', event.data);
                    console.log('[RESULT DATA]', JSON.stringify(event.data, null, 2));
                    debugLog('stream:complete-event-received', {
                      streamAgentName,
                      currentAgent,
                      observedAgents: Array.from(observedAgentsRef.current),
                      agentsInvoked: event.data?.agents_invoked || event.data?.result?.agents_invoked || [],
                    });
                    updateStep('learning', 'complete', 'Audit trail saved');
                    updateStep('complete', 'complete', 'Response formatted successfully');
                    finalData = event.data;
                    for (const agentName of (event.data?.agents_invoked || event.data?.result?.agents_invoked || [])) {
                      queuedPipeline.selectAgent(String(agentName), 0.95);
                      queuedPipeline.completeAgentExecution(String(agentName), 'Workflow step complete');
                    }
                    // Ensure no agent remains stuck in active/buffering state.
                    // Use observedAgentsRef because queued pipeline updates may not have flushed into store yet.
                    const activeOrKnownAgents = new Set<string>([
                      ...Array.from(observedAgentsRef.current),
                      ...usePipelineStore.getState().agentExecutions.map((exec) => exec.name),
                      ...usePipelineStore.getState().agents.filter((a) => a.isSelected).map((a) => a.name),
                      streamAgentName,
                      currentAgent,
                    ].filter(Boolean) as string[]);
                    debugLog('agent:finalize-candidates', Array.from(activeOrKnownAgents));
                    for (const name of activeOrKnownAgents) {
                      queuedPipeline.completeAgentExecution(name, 'Workflow complete');
                    }
                    queuedPipeline.completeStep(11);
                    queuedPipeline.advanceStep(12, 'Chat response rendered successfully');
                    queuedPipeline.completeStep(12);
                    pipelineLog('FORMAT', 'Final answer returned to chat');

                    queuedPipeline.updatePhaseDetail('complete', {status: 'complete'});
                    
                    const finalResult = event.data?.result?.result?.primary_result?.result
                      || event.data?.result?.result
                      || event.data?.result
                      || {};
                    queuedPipeline.setResult({
                      agent: event.data?.result?.result?.primary_result?.agent || event.data?.result?.agent || currentAgent || 'Agent',
                      confidence: finalResult?.confidence || 0.95,
                      executionTimeMs: finalResult?.execution_time_ms || 0,
                      totalTimeMs: finalResult?.execution_time_ms || 0,
                      verdict: (finalResult?.status?.toUpperCase() || finalResult?.action?.toUpperCase() || 'ANALYSIS_COMPLETE') as any,
                      score: finalResult?.score ? {
                        total: finalResult.score.total || finalResult.score,
                        subscores: finalResult.score.subscores || {}
                      } : undefined,
                      findings: [
                        ...(finalResult?.violations || []).map((v: string) => ({ severity: 'error' as const, message: v })),
                        ...(finalResult?.warnings || []).map((w: string) => ({ severity: 'warning' as const, message: w })),
                        ...(finalResult?.successes || []).map((s: string) => ({ severity: 'success' as const, message: s })),
                        ...(finalResult?.info || []).map((i: string) => ({ severity: 'info' as const, message: i })),
                      ]
                    });
                    break;
                  case 'error':
                    setLoadingMessage("Error: " + event.data.error);
                    debugLog('stream:error-event', {
                      error: event?.data?.error,
                      agent: event?.data?.agent,
                      observedAgents: Array.from(observedAgentsRef.current),
                    });
                    const errorAgent = resolveEventAgent();
                    if (errorAgent) {
                      queuedPipeline.setAgentPhase(
                        errorAgent,
                        'ACT',
                        'error',
                        event.data.error || 'Execution failed'
                      );
                    }
                    throw new Error(event.data.error);
                }
                
              } catch (e) {
                console.error('[PARSE ERROR]', line, e);
                debugLog('sse:parse-error', {
                  rawLine: line,
                  error: e instanceof Error ? e.message : String(e),
                });
              }
            }
          }
        }
      } catch (streamError) {
        console.error('\n' + '='.repeat(80));
        console.error('[CRITICAL ERROR IN STREAM]');
        console.error('='.repeat(80));
        console.error('Error type:', streamError instanceof Error ? streamError.name : typeof streamError);
        console.error('Error message:', streamError instanceof Error ? streamError.message : String(streamError));
        console.error('Stack trace:', streamError instanceof Error ? streamError.stack : 'N/A');
        console.error('='.repeat(80));
        throw streamError;
      } finally {
        setIsStreaming(false);
        console.log('✅ [SSE CLOSED] Stream ended');
      }
      
      console.log('\n' + '='.repeat(80));
      console.log('[MUTATION COMPLETE]');
      console.log('='.repeat(80));
      console.log('[FINAL DATA]', finalData);
      console.log('='.repeat(80));

      // IMPORTANT: Do not show chat answer until the queued pipeline updates finish.
      console.log('[CHAT GATE] Waiting for pipeline queue to drain before returning response...');
      await pipelineQueue.waitForDrain(120000);
      console.log('[CHAT GATE] Pipeline queue drained - returning response now');
      debugLog('stream:queue-drained', {
        observedAgents: Array.from(observedAgentsRef.current),
        finalDataPresent: Boolean(finalData),
      });
      
      setProcessedResult(finalData);
      // Store result in global store so ChatPage can pick it up after remount
      usePipelineStore.getState().setPendingChatResult({
        data: finalData,
        agentName: streamAgentName || currentAgent || "",
      });
      return finalData || { response: "Request processed successfully" };
    },
    onSuccess: (data, variables) => {
      console.log('[MUTATION SUCCESS]', data);
      console.log('[CURRENT AGENT]', currentAgent);
      console.log('[IS_MOUNTED]', isMountedRef.current);

      // If component is unmounted (user navigated to /process), skip entirely.
      // The mount useEffect will consume pendingChatResult when ChatPage remounts.
      if (!isMountedRef.current) {
        console.log('[MUTATION SUCCESS] Component unmounted � deferring to mount useEffect');
        return;
      }

      // Component is mounted � handle normally and clear pending result
      usePipelineStore.getState().setPendingChatResult(null);
      
      setLoadingMessage("");
      setStreamingContent("");

      // ── Unified extraction via agentResultExtractor ──
      const normalised = extractAgentResult(data, currentAgent);
      console.log('[NORMALISED RESULT]', normalised);
      debugLog('result:normalised', {
        kind: normalised.kind,
        agent: normalised.agent,
        status: normalised.status,
        dataSource: normalised.dataSource,
        queryType: normalised.queryType,
      });

      // Format the markdown content using the formatter module
      let formattedContent = formatAgentMarkdown(normalised);

      // If PR workflow created successfully, redirect to approval workflows page
      if (isPrWorkflowCheck(normalised) && normalised.status === "success") {
        setTimeout(() => setLocation("/approval-workflows"), 900);
      }

      // Build ResultCard props from the normalised result
      const cardProps = buildResultCardProps(normalised);

      // Use pipeline store timing if available
      const agentDurationMs = usePipelineStore
        .getState()
        .agentExecutions.find((exec) => exec.name === normalised.agent)?.durationMs;
      const pipelineElapsedMs = usePipelineStore.getState().elapsed;
      if (!cardProps.executionTimeMs && (agentDurationMs || pipelineElapsedMs)) {
        cardProps.executionTimeMs = agentDurationMs || pipelineElapsedMs || 0;
      }

      console.log('[FORMATTED CONTENT LENGTH]', formattedContent.length);

      // Don't show ResultCard for general/greeting queries
      const isGeneralQuery = normalised.dataSource === "general" || normalised.queryType === "GENERAL";
      const agentResult = isGeneralQuery ? undefined : cardProps;
      
      const assistantMessage: Message = {
        id: Date.now().toString(),
        role: "assistant",
        content: formattedContent,
        dataSource: normalised.dataSource,
        queryType: normalised.queryType || undefined,
        chartData: undefined,
        agentResult: agentResult,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      if (!isVendorResult(normalised)) {
        setPendingVendorSelection(null);
        vendorPromptFingerprintRef.current = "";
      }
      maybePromptVendorSelection(normalised);
      
      // Save to process history for later review
      const messageId = assistantMessage.id;
      const storeState = usePipelineStore.getState();
      setProcessHistory(prev => [
        { 
          messageId, 
          agent: currentAgent, 
          agents: [...new Set(storeState.agentExecutions.map(e => e.name))],
          query: storeState.queryText || "",
          timestamp: Date.now(),
          steps: [...agentSteps], 
          details: {...agentPhaseDetails} 
        },
        ...prev.slice(0, 9) // Keep last 10 processes
      ]);
      
      // Clear current visualization
      setAgentSteps([]);
      setCurrentAgent("");
      setAgentPhaseDetails({});
      setProcessedResult(null);

      // Don't navigate here � user is already on /process page (navigated mid-stream).
      // AgentProcessPage detects pipeline "done" and auto-redirects back to /chat.
      
      if (voiceOutputEnabled && data.result) {
        const textResponse = typeof data.result === 'string' ? data.result : JSON.stringify(data.result);
        speakText(textResponse, language);
      }
    },
    onError: (error: Error) => {
      // AbortError is expected when navigating away mid-stream � ignore it silently.
      if (error?.name === 'AbortError') {
        console.log('[STREAM ABORTED] Navigation or cleanup triggered � not a real error.');
        setLoadingMessage("");
        setIsStreaming(false);
        setStreamingContent("");
        return;
      }

      console.error('\n' + '='.repeat(80));
      console.error('[MUTATION ERROR]');
      console.error('='.repeat(80));
      console.error('Error name:', error?.name || 'Unknown');
      console.error('Error message:', error?.message || 'No message');
      console.error('Error stack:',error?.stack || 'No stack trace');
      console.error('='.repeat(80));
      
      setLoadingMessage("");
      setIsStreaming(false);
      setStreamingContent("");
      queuedPipeline.clearQueue();
      usePipelineStore.getState().reset();
      setAgentSteps([]);
      setAgentPhaseDetails({});
      setProcessedResult(null);
      setCurrentAgent("");

      for (const exec of usePipelineStore.getState().agentExecutions) {
        if (exec.status === 'active') {
          queuedPipeline.upsertAgentExecution(exec.name, {
            status: 'error',
            lastMessage: error?.message || 'Execution failed',
            completedAt: Date.now(),
          });
        }
      }
      
      // Add user-friendly error message to chat
      const errorMessage: Message = {
        id: Date.now().toString(),
        role: "assistant",
        content: `## \u274c System Error\n\n**Error:** ${error?.message || 'Unknown error'}\n\n**What happened:** The system encountered an issue while processing your request.\n\n**What to try:**\n- Check your internet connection\n- Try rephrasing your question\n- Refresh the page and try again\n- Contact support if the issue persists\n\n**Technical details:** \`${error?.name || 'Error'}\``,
      };
      setMessages((prev) => [...prev, errorMessage]);
      
      toast({
        title: "Request Failed",
        description: error?.message || 'An unknown error occurred',
        variant: "destructive",
      });
    },
  });

  const handleSend = () => {
    if (!input.trim() || chatMutation.isPending) return;

    if (pendingDepartmentSelection) {
      toast({
        title: "Department required",
        description: "Please select a department from the combo box to continue budget verification.",
      });
      return;
    }

    if (pendingVendorSelection) {
      const trimmed = input.trim();
      const yesConfirmation = /^(yes|y|ok|okay|confirm|proceed|continue)$/i.test(trimmed);
      if (yesConfirmation && pendingVendorSelection.options[0]?.name) {
        handleVendorSelection(pendingVendorSelection.options[0].name);
        setInput("");
        return;
      }

      // Allow free-form selection with a note, e.g.
      // "Industrial Parts Inc - urgent onboarding need"
      // "Ready Mat: better delivery timeline"
      const optionMatch = pendingVendorSelection.options.find((opt) => {
        const name = opt.name.toLowerCase();
        const value = trimmed.toLowerCase();
        return value.startsWith(name);
      });
      if (optionMatch) {
        const remaining = trimmed.slice(optionMatch.name.length).trim();
        const comment = remaining.replace(/^[:\-\u2013\u2014\s]+/, "").trim();
        handleVendorSelection(optionMatch.name, comment || undefined);
        setInput("");
        return;
      }

      const exactOption = pendingVendorSelection.options.find(
        (opt) => opt.name.toLowerCase() === trimmed.toLowerCase()
      );
      if (exactOption) {
        handleVendorSelection(exactOption.name);
        setInput("");
        return;
      }

      toast({
        title: "Vendor confirmation required",
        description: "Select one of the top 5 vendors. You can also add a note like: 'Vendor Name - reason'.",
      });
      return;
    }

    setPendingVendorSelection(null);
    vendorPromptFingerprintRef.current = "";

    const resolvedMessage = resolveContextAwareMessage(input.trim(), messages);
    const parsedResolvedPrData = extractPrDataFromMessage(resolvedMessage);

    // Only ask for department when the message is genuinely budget-related.
    // If the user is in budget-agent mode but asks something else (e.g. "who is
    // the best vendor?"), let the message pass through unguarded.
    const isBudgetQuery = /\b(budget|capex|opex|funds?|allocat|available|spending|utiliz|balance|verify|check)\b/i.test(resolvedMessage);
    if (selectedAgentType === "budget_verification" && isBudgetQuery && !parsedResolvedPrData.department) {
      promptDepartmentSelection(resolvedMessage, 'budget');
      return;
    }

    // For create/PR intents in any mode, ask for department if not specified.
    const isCreateIntentInMessage = parsedResolvedPrData.intent_hint === "pr_creation";
    if (isCreateIntentInMessage && !parsedResolvedPrData.department) {
      promptDepartmentSelection(resolvedMessage, 'pr_creation');
      return;
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input.trim(),
    };

    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);

    // Force-save to localStorage IMMEDIATELY so the user message survives
    // navigation to /process (the save-to-localStorage useEffect won't fire
    // because the component unmounts before the next render cycle).
    if (activeSessionId) {
      const title = sessions.find(s => s.id === activeSessionId)?.title || "New Chat";
      const updatedSessions = sessions.map(s =>
        s.id === activeSessionId
          ? { ...s, messages: updatedMessages, title: title === "New Chat" ? generateSessionTitle(userMessage.content) : title, timestamp: Date.now() }
          : s
      );
      saveSessions(updatedSessions);
    }

    chatMutation.mutate(resolvedMessage);
    setInput("");
  };

  const handleVendorSelection = (vendorName: string, selectionComment?: string) => {
    if (!vendorName || chatMutation.isPending) return;

    const note = (selectionComment || "").trim();
    const userVisible = note
      ? `Select vendor: ${vendorName} - ${note}`
      : `Select vendor: ${vendorName}`;
    const resumeContext = pendingVendorSelection?.resumeContext || {};
    const shouldResumeWorkflow = pendingVendorSelection?.requiresWorkflowResume === true;
    const noteAsJustification = note && !resumeContext.justification
      ? `business justification: ${note}`
      : "";
    const contextHint = [
      resumeContext.department ? `department ${resumeContext.department}` : '',
      typeof resumeContext.budget === 'number' ? `budget $${resumeContext.budget}` : '',
      resumeContext.category ? `category ${resumeContext.category}` : '',
      resumeContext.product_name ? `product ${resumeContext.product_name}` : '',
      typeof resumeContext.quantity === 'number' ? `quantity ${resumeContext.quantity}` : '',
      resumeContext.budget_category ? `budget category ${resumeContext.budget_category}` : '',
      resumeContext.justification ? `business justification: ${resumeContext.justification}` : '',
      note ? `vendor selection note: ${note}` : '',
      noteAsJustification,
    ].filter(Boolean).join(', ');
    const followupMessage = shouldResumeWorkflow
      ? (
          contextHint
            ? `CONFIRM_VENDOR: ${vendorName}. Continue PR creation workflow with ${contextHint}.`
            : `CONFIRM_VENDOR: ${vendorName}. Continue PR creation workflow.`
        )
      : (
          contextHint
            ? `CONFIRM_VENDOR: ${vendorName}. Save this vendor selection with context: ${contextHint}. Do not create PR unless I explicitly ask.`
            : `CONFIRM_VENDOR: ${vendorName}. Save this vendor selection only. Do not create PR unless I explicitly ask.`
        );

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: userVisible,
    };

    const updatedMessages = [...messages, userMessage];
    setMessages(updatedMessages);
    setPendingVendorSelection(null);

    if (activeSessionId) {
      const title = sessions.find(s => s.id === activeSessionId)?.title || "New Chat";
      const updatedSessions = sessions.map(s =>
        s.id === activeSessionId
          ? { ...s, messages: updatedMessages, title: title === "New Chat" ? generateSessionTitle(userMessage.content) : title, timestamp: Date.now() }
          : s
      );
      saveSessions(updatedSessions);
    }

    chatMutation.mutate(followupMessage);
  };

  const handleConfirmVendorFromPanel = () => {
    const vendorName = selectedVendorOption.trim();
    if (!vendorName || chatMutation.isPending) return;
    const note = vendorSelectionNote.trim();
    handleVendorSelection(vendorName, note || undefined);
  };

  const handleShowPipeline = () => {
    setIsPipelinePanelOpen(true);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleVoiceTranscript = (text: string) => {
    setInput(text);
  };

  useEffect(() => {
    scrollChatToBottomExact("messages-effect", 3);
  }, [messages]);

  return (
    <div className="flex h-screen bg-background overflow-x-hidden overflow-y-hidden">
      {/* Sidebar - Fixed */}
      <ChatSidebar
        sessions={sessions.map(s => ({
          id: s.id,
          title: s.title,
          timestamp: s.timestamp,
          messageCount: s.messages.length,
        }))}
        activeSessionId={activeSessionId}
        onSelectSession={switchSession}
        onNewChat={createNewSession}
        onDeleteSession={deleteSession}
      />

      {/* Main Chat Area */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Header - Fixed */}
        <header className="flex-shrink-0 flex items-center justify-between gap-4 p-4 border-b border-blue-400/30 bg-gradient-to-r from-blue-700 via-blue-600 to-blue-700 text-white shadow-sm">
          <div className="flex items-center gap-3">
            <Bot className="h-6 w-6 text-white" />
            <div className={`transition-opacity duration-500 ${headerWelcomeVisible ? "opacity-100" : "opacity-0"}`}>
              <h1 className="text-lg font-semibold whitespace-nowrap" data-testid="text-app-title">
                Welcome to Procurement AI
              </h1>
              <p className="text-xs text-blue-100">ProcAI Bot • Powered by OpenAI GPT-4o</p>
            </div>
          </div>
          <div className="flex items-center gap-4 flex-wrap">
            <LanguageSelector
              value={language}
              onChange={setLanguage}
              triggerClassName="w-[165px] border-white/40 bg-white/20 text-white hover:bg-white/25 focus:border-white/70 focus:ring-white/60 [&>span]:text-white"
              iconClassName="text-white"
            />
            <VoiceInput
              onTranscript={handleVoiceTranscript}
              language={language}
              voiceOutputEnabled={voiceOutputEnabled}
              onVoiceOutputToggle={setVoiceOutputEnabled}
              labelClassName="text-white"
              activeIconClassName="text-cyan-100"
              inactiveIconClassName="text-blue-100"
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setLocation("/dashboard")}
              className="gap-2 border-white/40 bg-white/10 text-white hover:bg-white/20 hover:text-white"
            >
              <LayoutDashboard className="h-4 w-4" />
              Dashboard
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLogout}
              className="gap-2 text-white hover:bg-white/20 hover:text-white"
            >
              <LogOut className="h-4 w-4" />
              Logout
            </Button>
          </div>
        </header>

        {/* Messages Area - Scrollable */}
        <div className="flex-1 relative overflow-hidden bg-gradient-to-b from-background to-muted/20">
          {welcomeIntroVisible && messages.length === 0 && (
            <div className="absolute inset-0 z-20 flex items-center justify-center pointer-events-none">
              <div
                className={`rounded-2xl border border-blue-200/80 bg-gradient-to-br from-blue-50 via-sky-100 to-indigo-100 px-8 py-6 text-center text-slate-900 shadow-2xl transition-all duration-700 ease-out ${
                  welcomeIntroPhase === "to-top"
                    ? "-translate-y-[38vh] scale-75 opacity-70"
                    : "translate-y-0 scale-100 opacity-100"
                }`}
              >
                <div className="mx-auto mb-3 h-1.5 w-40 rounded-full bg-gradient-to-r from-blue-700 via-blue-500 via-sky-500 via-indigo-500 to-blue-700" />
                <p className="text-3xl font-extrabold tracking-tight text-blue-900">Welcome to Procurement Chat</p>
                <p className="mt-2 text-sm font-medium text-blue-700">AI-guided enterprise procurement intelligence</p>
                <p className="mt-2 text-sm font-semibold">
                  <span className="text-blue-700">Finance</span>
                  <span className="mx-2 text-blue-400">•</span>
                  <span className="text-sky-700">Vendor</span>
                  <span className="mx-2 text-blue-400">•</span>
                  <span className="text-indigo-700">Risk</span>
                  <span className="mx-2 text-blue-400">•</span>
                  <span className="text-blue-800">Approvals</span>
                  <span className="mx-2 text-blue-400">•</span>
                  <span className="text-cyan-700">Compliance</span>
                </p>
              </div>
            </div>
          )}
          <div 
            ref={scrollRef}
            className="h-full overflow-y-auto overflow-x-hidden scroll-smooth" 
            onScroll={handleScroll}
            style={{ 
              scrollbarWidth: 'thin',
              scrollbarColor: 'rgb(203 213 225) transparent'
            }}
          >
            <div className="p-6 space-y-6 max-w-6xl mx-auto min-h-full">
              {messages.length === 0 && !welcomeIntroVisible && (
                <div className="text-center py-20 space-y-4" data-testid="text-empty-state">
                  <div className="mx-auto w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center">
                    <Bot className="h-8 w-8 text-primary" />
                  </div>
                  <p className="text-muted-foreground">Ask me anything about your procurement data</p>
                  {selectedAgentType === "auto" && (
                    <div className="flex flex-wrap gap-2 justify-center mt-6">
                      <div className="px-4 py-2 rounded-full text-sm font-medium border text-blue-900 border-blue-300 bg-gradient-to-r from-blue-100 to-blue-50 shadow-sm">"What is the total budget?"</div>
                      <div className="px-4 py-2 rounded-full text-sm font-medium border text-sky-900 border-sky-300 bg-gradient-to-r from-sky-100 to-cyan-50 shadow-sm">"Show high risk projects"</div>
                      <div className="px-4 py-2 rounded-full text-sm font-medium border text-indigo-900 border-indigo-300 bg-gradient-to-r from-indigo-100 to-blue-50 shadow-sm">"List approved requests"</div>
                    </div>
                  )}

                </div>
              )}
            
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex gap-4 ${message.role === "user" ? "justify-end" : "justify-start"} animate-in fade-in slide-in-from-bottom-2 duration-300`}
                data-testid={`message-${message.role}-${message.id}`}
              >
                {/* Bot avatar for assistant messages without agent result */}
                {message.role === "assistant" && !message.agentResult && (
                  <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center shadow-sm border border-primary/10">
                    <Bot className="h-5 w-5 text-primary" />
                  </div>
                )}
                
                {/* User message */}
                {message.role === "user" && (
                  <div className="max-w-[85%] rounded-2xl px-5 py-3.5 shadow-sm bg-gradient-to-br from-primary to-primary/90 text-primary-foreground">
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  </div>
                )}

                {/* Agent switch message card */}
                {message.role === "assistant" && message.agentModeCard && (
                  <div className="max-w-[85%] w-full">
                    <div className="relative overflow-hidden rounded-3xl border border-cyan-300/80 bg-gradient-to-br from-slate-900 via-blue-900 to-cyan-900 px-8 py-7 text-center text-white shadow-2xl animate-in fade-in zoom-in-95 duration-300">
                      <div className="pointer-events-none absolute -left-10 top-6 h-28 w-28 rounded-full bg-cyan-300/20 blur-2xl animate-pulse" />
                      <div className="pointer-events-none absolute -right-8 bottom-4 h-24 w-24 rounded-full bg-blue-300/20 blur-2xl animate-pulse" />
                      <div className="pointer-events-none absolute inset-0 border border-white/10 rounded-3xl" />

                      <div className="relative">
                        <div className="mx-auto mb-3 h-1.5 w-44 rounded-full bg-gradient-to-r from-cyan-300 via-blue-300 to-indigo-300 shadow-[0_0_20px_rgba(125,211,252,0.5)]" />
                        <p className="text-3xl font-extrabold tracking-tight text-cyan-100 drop-shadow-sm">{message.agentModeCard.agentName}</p>
                        <p className="mt-2 text-sm font-medium text-blue-100">Ready in dedicated mode. Your next prompt will run through this selected agent.</p>
                        <p className="mt-3 text-xs font-semibold uppercase tracking-[0.12em] text-cyan-200">Single-agent execution lock is active</p>
                      </div>
                    </div>
                  </div>
                )}
                
                {/* Assistant message with agent result - Use ResultCard */}
                {message.role === "assistant" && message.agentResult && !message.agentModeCard && (
                  <div className="max-w-[85%] w-full space-y-3">
                    <ResultCard
                      agent={message.agentResult.agent}
                      confidence={message.agentResult.confidence}
                      executionTimeMs={message.agentResult.executionTimeMs}
                      verdict={message.agentResult.verdict}
                      dataSource={message.agentResult.dataSource || message.dataSource}
                      score={message.agentResult.score}
                      findings={message.agentResult.findings}
                      approvalChain={message.agentResult.approvalChain}
                      onShowPipeline={handleShowPipeline}
                      onViewApprovalChain={message.agentResult.approvalChain ? () => {
                        toast({
                          title: "Approval Chain",
                          description: "Viewing approval chain details...",
                        });
                      } : undefined}
                    />

                    {/* View Full Process button */}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 -mt-1"
                      onClick={() => setLocation(`/process?id=${message.id}`)}
                    >
                      <Activity className="h-3.5 w-3.5" /> View Full Process
                    </Button>

                    {message.content && (
                      <div className="rounded-2xl px-5 py-3.5 shadow-sm bg-card border border-border/50">
                        <div className="prose prose-base dark:prose-invert max-w-none">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              table: ({ node, ...props }) => (
                                <div className="overflow-x-auto my-4 rounded-lg border border-border">
                                  <table className="border-collapse w-full text-sm" {...props} />
                                </div>
                              ),
                              th: ({ node, ...props }) => (
                                <th className="border-b-2 border-border px-4 py-3 bg-muted/80 font-semibold text-left text-xs uppercase tracking-wider" {...props} />
                              ),
                              td: ({ node, ...props }) => (
                                <td className="border-b border-border/50 px-4 py-3 hover:bg-muted/30 transition-colors" {...props} />
                              ),
                            }}
                          >
                            {message.content}
                          </ReactMarkdown>
                        </div>
                      </div>
                    )}
                  </div>
                )}
                
                {/* Assistant message without agent result - Use plain markdown */}
                {message.role === "assistant" && !message.agentResult && !message.agentModeCard && (
                  <div className="max-w-[85%] rounded-2xl px-5 py-3.5 shadow-sm bg-card border border-border/50">
                    <div>
                      {message.dataSource && (
                        <div className="mb-2">
                          <span className="px-2 py-0.5 text-[11px] font-medium rounded border bg-slate-50 text-slate-700 border-slate-200 dark:bg-slate-900/40 dark:text-slate-200 dark:border-slate-700">
                            Data Source: {message.dataSource}
                          </span>
                        </div>
                      )}
                      <div className="prose prose-base dark:prose-invert max-w-none">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            table: ({ node, ...props }) => (
                              <div className="overflow-x-auto my-4 rounded-lg border border-border">
                                <table className="border-collapse w-full text-sm" {...props} />
                              </div>
                            ),
                            th: ({ node, ...props }) => (
                              <th className="border-b-2 border-border px-4 py-3 bg-muted/80 font-semibold text-left text-xs uppercase tracking-wider" {...props} />
                            ),
                            td: ({ node, ...props }) => (
                              <td className="border-b border-border/50 px-4 py-3 hover:bg-muted/30 transition-colors" {...props} />
                            ),
                          }}
                        >
                          {message.content}
                        </ReactMarkdown>
                      </div>
                      {message.chartData && message.chartData.length > 1 && (
                        <DataCharts data={message.chartData} />
                      )}
                    </div>
                  </div>
                )}
                
                {/* User avatar on right side */}
                {message.role === "user" && (
                  <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primary/90 flex items-center justify-center shadow-md">
                    <User className="h-5 w-5 text-primary-foreground" />
                  </div>
                )}
              </div>
            ))}
            
            {/* Agentic Pipeline Steps - Live OBSERVE?DECIDE?ACT?LEARN visualization */}
            {(isStreaming || chatMutation.isPending) && agentSteps.some(s => s.status !== 'pending') && (
              <div ref={pipelineStepsRef} className="flex gap-4 justify-start animate-in fade-in slide-in-from-bottom-2 duration-300">
                <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600/30 to-purple-600/30 flex items-center justify-center shadow-md border border-blue-500/30">
                  <Activity className="h-5 w-5 text-blue-400 animate-pulse" />
                </div>
                <div className="bg-card border border-blue-500/20 rounded-2xl px-5 py-4 max-w-[80%] w-full space-y-3 shadow-md">
                  {/* Agent name header */}
                  {currentAgent && (
                    <div className="flex items-center gap-2 pb-2 border-b border-blue-500/20">
                      <span className="text-sm font-bold uppercase tracking-wider text-blue-400">
                        {currentAgent.replace(/([A-Z])/g, ' $1').trim()}
                      </span>
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 font-semibold animate-pulse">
                        ? Processing
                      </span>
                    </div>
                  )}
                  {/* Step list � show ALL steps so user sees the full journey */}
                  <div className="space-y-1.5">
                    {agentSteps.map((step) => (
                      <div 
                        key={step.id} 
                        id={`inline-step-${step.id}`}
                        className={`flex items-center gap-3 text-sm px-2 py-1.5 rounded-lg transition-all duration-300 ${
                          step.status === 'active' ? 'bg-blue-500/10 border border-blue-500/30 scale-[1.01]' :
                          step.status === 'complete' ? 'bg-emerald-500/5' : 
                          'opacity-40'
                        }`}
                      >
                        {step.status === 'complete' ? (
                          <div className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center shadow-sm shadow-emerald-500/30">
                            <CheckCircle2 className="h-3.5 w-3.5 text-white" />
                          </div>
                        ) : step.status === 'active' ? (
                          <div className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center shadow-sm shadow-blue-500/40">
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-white" />
                          </div>
                        ) : step.status === 'error' ? (
                          <div className="flex-shrink-0 w-5 h-5 rounded-full bg-red-500 flex items-center justify-center shadow-sm shadow-red-500/30">
                            <AlertCircle className="h-3.5 w-3.5 text-white" />
                          </div>
                        ) : (
                          <div className="flex-shrink-0 w-5 h-5 rounded-full border-2 border-border/50" />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className={`font-semibold ${
                              step.status === 'complete' ? 'text-emerald-400' : 
                              step.status === 'active' ? 'text-blue-300' : 
                              step.status === 'error' ? 'text-red-400' : 'text-muted-foreground/50'
                            }`}>
                              {step.name}
                            </span>
                            {step.status === 'complete' && step.durationMs != null && step.durationMs > 0 && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono">{step.durationMs}ms</span>
                            )}
                            {step.status === 'active' && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/15 text-blue-400 animate-pulse">in progress</span>
                            )}
                          </div>
                          {step.message && (
                            <p className={`text-xs mt-0.5 ${
                              step.status === 'active' ? 'text-blue-300/80' : 'text-foreground/50'
                            }`}>{step.message}</p>
                          )}
                          {step.agent && step.status === 'complete' && (
                            <p className="text-[10px] text-emerald-500/70 mt-0.5">via {step.agent}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* Progress bar */}
                  <div className="relative h-2 bg-muted/50 rounded-full overflow-hidden mt-2">
                    <div 
                      className="absolute h-full bg-gradient-to-r from-blue-500 via-purple-500 to-emerald-500 transition-all duration-500 rounded-full shadow-sm shadow-blue-500/30"
                      style={{ 
                        width: `${(agentSteps.filter(s => s.status === 'complete').length / agentSteps.length) * 100}%` 
                      }}
                    />
                  </div>
                  {/* Step counter + Pipeline panel link */}
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-[11px] text-foreground/60 font-medium">
                      {agentSteps.filter(s => s.status === 'complete').length}/{agentSteps.length} steps
                    </span>
                    <button
                      onClick={() => setIsPipelinePanelOpen(true)}
                      className="text-[11px] text-blue-400 hover:text-blue-300 hover:underline cursor-pointer font-medium"
                    >
                      View full pipeline details ?
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Old Progress Steps - Fallback for non-agentic queries */}
            {(isStreaming || (chatMutation.isPending && progressSteps.length > 0)) && agentSteps.length === 0 && (
              <div className="flex gap-4 justify-start animate-in fade-in slide-in-from-bottom-2 duration-300">
                <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center shadow-sm border border-primary/10">
                  <Bot className="h-5 w-5 text-primary" />
                </div>
                <div className="bg-card border border-border/50 rounded-2xl px-5 py-4 max-w-[75%] space-y-3 shadow-sm">
                  {/* Progress Steps */}
                  {progressSteps.length > 0 && (
                    <div className="space-y-3">
                      {progressSteps.map((step, index) => (
                        <div key={index} className="flex items-center gap-3 text-sm">
                          {step.status === 'completed' ? (
                            <div className="flex-shrink-0 w-5 h-5 rounded-sm bg-green-500 flex items-center justify-center">
                              <CheckCircle2 className="h-4 w-4 text-white" />
                            </div>
                          ) : step.status === 'active' ? (
                            <div className="flex-shrink-0 w-5 h-5 rounded-sm bg-orange-500 flex items-center justify-center">
                              <Loader2 className="h-3 w-3 animate-spin text-white" />
                            </div>
                          ) : (
                            <div className="flex-shrink-0 w-5 h-5 rounded-sm border-2 border-gray-300"></div>
                          )}
                          <span className={step.status === 'completed' ? "text-muted-foreground" : step.status === 'active' ? "text-foreground font-medium" : "text-muted-foreground/50"}>
                            {step.message}
                          </span>
                        </div>
                      ))}
                      
                      {/* Progress Bar */}
                      <div className="relative h-2 bg-gray-200 rounded-full overflow-hidden mt-2">
                        <div 
                          className="absolute h-full bg-blue-500 transition-all duration-300 rounded-full"
                          style={{ 
                            width: `${(progressSteps.filter(s => s.status === 'completed').length / progressSteps.length) * 100}%` 
                          }}
                        ></div>
                      </div>
                      <p className="text-xs text-center text-muted-foreground">Processing...</p>
                    </div>
                  )}
                  
                  {/* Streaming Content */}
                  {streamingContent && (
                    <div className="prose prose-sm dark:prose-invert max-w-none border-t border-border/50 pt-3 mt-3">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {streamingContent}
                      </ReactMarkdown>
                      <span className="inline-block w-2 h-4 bg-primary animate-pulse ml-1"></span>
                    </div>
                  )}
                </div>
              </div>
            )}
            
            {chatMutation.isPending && !isStreaming && progressSteps.length === 0 && (
              <div className="flex gap-3 justify-start" data-testid="loading-indicator">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                  <Bot className="h-4 w-4 text-primary" />
                </div>
                <div className="bg-muted rounded-lg px-4 py-3 flex items-center gap-3">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  {loadingMessage && (
                    <span className="text-sm text-muted-foreground">{loadingMessage}</span>
                  )}
                </div>
              </div>
            )}
              
              {/* Invisible div for scroll anchor */}
              <div ref={messagesEndRef} />
            </div>
          </div>
          
          {/* Scroll to Bottom Button */}
          {showScrollButton && (
            <Button
              onClick={scrollToBottom}
              size="icon"
              className="absolute  bottom-20 left-[92%] rounded-full shadow-xl hover:shadow-2xl transition-all hover:scale-110 z-50 bg-primary"
              variant="default"
            >
              <ArrowDown className="h-5 w-5" />
            </Button>
          )}
        </div>

        {/* Input Area - Fixed */}
        <div className="flex-shrink-0 border-t bg-card/95 backdrop-blur-sm p-4 shadow-lg">
          <div className="max-w-6xl mx-auto space-y-3">
            {isPipelinePanelOpen && (
              <PipelineSidePanel
                isOpen={isPipelinePanelOpen}
                onClose={() => setIsPipelinePanelOpen(false)}
                variant="inline"
              />
            )}

            {pendingVendorSelection && pendingVendorSelection.options.length > 0 && (
              <div className="rounded-xl border border-amber-500/40 bg-amber-50 dark:bg-amber-500/10 px-4 py-3 space-y-3">
                <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">
                  Vendor confirmation needed. Choose one option to continue the workflow.
                </p>
                <div className="flex flex-wrap gap-2">
                  {pendingVendorSelection.options.map((option) => (
                    <Button
                      key={option.name}
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={chatMutation.isPending}
                      onClick={() => setSelectedVendorOption(option.name)}
                      className="h-auto py-2 px-3 border-amber-500/50 text-amber-900 dark:text-amber-100 bg-white dark:bg-transparent hover:bg-amber-100 dark:hover:bg-amber-500/20"
                    >
                      {option.name}
                      {typeof option.score === "number" ? ` (${option.score}/100)` : ""}
                    </Button>
                  ))}
                </div>
                <div className="grid gap-2 md:grid-cols-[minmax(180px,1fr)_minmax(220px,2fr)_auto]">
                  <select
                    value={selectedVendorOption}
                    onChange={(e) => setSelectedVendorOption(e.target.value)}
                    disabled={chatMutation.isPending}
                    className="h-10 rounded-md border border-amber-500/50 bg-white dark:bg-slate-900 px-3 text-sm"
                  >
                    {pendingVendorSelection.options.map((option) => (
                      <option key={option.name} value={option.name}>
                        {option.name}
                      </option>
                    ))}
                  </select>
                  <input
                    value={vendorSelectionNote}
                    onChange={(e) => setVendorSelectionNote(e.target.value)}
                    disabled={chatMutation.isPending}
                    placeholder="Add reason (optional): urgent need, best delivery, etc."
                    className="h-10 rounded-md border border-amber-500/50 bg-white dark:bg-slate-900 px-3 text-sm"
                  />
                  <Button
                    type="button"
                    disabled={!selectedVendorOption || chatMutation.isPending}
                    onClick={handleConfirmVendorFromPanel}
                    className="h-10"
                  >
                    Confirm Vendor
                  </Button>
                </div>
              </div>
            )}

            {pendingDepartmentSelection && (
              <div className="rounded-xl border border-sky-500/40 bg-sky-50 dark:bg-sky-500/10 px-4 py-3 space-y-3">
                <p className="text-sm font-semibold text-sky-900 dark:text-sky-200">
                  {pendingDepartmentSelection.context === 'pr_creation'
                    ? "Which department is this purchase request for?"
                    : "Budget agent needs a department. Select one to continue."}
                </p>
                <div className="grid gap-2 md:grid-cols-[minmax(180px,1fr)_auto_auto]">
                  <select
                    value={pendingDepartmentSelection.selectedDepartment}
                    onChange={(e) => setPendingDepartmentSelection((prev) => prev ? { ...prev, selectedDepartment: e.target.value } : prev)}
                    disabled={chatMutation.isPending}
                    className="h-10 rounded-md border border-sky-500/50 bg-white dark:bg-slate-900 px-3 text-sm"
                  >
                    {pendingDepartmentSelection.options.map((department) => (
                      <option key={department} value={department}>
                        {department}
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    disabled={chatMutation.isPending}
                    onClick={handleConfirmDepartmentFromPanel}
                    className="h-10"
                  >
                    Continue with Department
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={chatMutation.isPending}
                    onClick={() => setPendingDepartmentSelection(null)}
                    className="h-10"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            <div className="rounded-xl border border-blue-200/60 bg-blue-50/60 px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setIsAgentModeOpen((prev) => !prev)}
                    className="gap-2 border-blue-300 bg-white text-blue-900 hover:bg-blue-100"
                  >
                    <Bot className="h-4 w-4" />
                    Agent Mode
                    {isAgentModeOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  </Button>
                  <span className="rounded-full border border-blue-300 bg-white px-2 py-1 text-[11px] font-semibold text-blue-800">
                    Active: {selectedAgentMeta?.name || "Auto Routing"}
                  </span>
                </div>
              </div>

              {isAgentModeOpen && (
                <div className="mt-3 space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-blue-800">Select Agent</p>
                  <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
                    {agentModeOptions.map((agent) => {
                      const Icon = getAgentIcon(agent.type);
                      const isActive = selectedAgentType === agent.type;

                      return (
                        <button
                          key={agent.type}
                          type="button"
                          onClick={() => handleAgentModeSelect(agent.type)}
                          className={`rounded-lg border px-3 py-2 text-left transition-all ${
                            isActive
                              ? "border-blue-500 bg-blue-600 text-white shadow-md"
                              : "border-blue-200 bg-white text-blue-900 hover:border-blue-400 hover:bg-blue-50"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <Icon className={`h-4 w-4 ${isActive ? "text-white" : "text-blue-600"}`} />
                            <span className="truncate text-xs font-semibold">{agent.name}</span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

            </div>
            
            <div className="flex gap-3 items-end">
              <Textarea
                value={input}
                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about procurement data..."
                className="min-h-[56px] max-h-32 resize-none rounded-2xl border-2 focus:border-primary/50 transition-colors shadow-sm"
                data-testid="input-chat"
              />
              <Button
                onClick={handleSend}
                disabled={!input.trim() || chatMutation.isPending}
                size="icon"
                className="h-14 w-14 rounded-2xl shadow-md hover:shadow-lg transition-all hover:scale-105"
                data-testid="button-send"
              >
                {chatMutation.isPending ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Send className="h-5 w-5" />
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}

