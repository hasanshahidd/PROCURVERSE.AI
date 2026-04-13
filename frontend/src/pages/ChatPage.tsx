/**
 * ChatPage — Enterprise Procurement AI Chat Interface
 *
 * Sprint B (2026-04-11) rewrite — **pipelineStore-free**.
 * - SSE stream from POST /api/agentic/execute/stream drives purely local
 *   React state (`agentSteps`, `currentAgent`, `agentPhaseDetails`).
 * - `session_created` → redirect to /sessions/:id (Execution Sessions layer).
 * - No usePipelineQueue, no usePipelineStore, no PipelineSidePanel drawer,
 *   no /process page link. P2P workflows live on /sessions/:id.
 * - Department list fetched from /api/config/departments (React Query).
 * - Agent mode selector from /api/agentic/agents registry.
 * - PR data extraction + vendor confirmation workflow (non-P2P only).
 * - Session management persisted to localStorage.
 */

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Send, Bot, User, Loader2, LogOut, CheckCircle2, ArrowDown,
  LayoutDashboard, Activity, AlertCircle, DollarSign, GitBranch,
  ShieldCheck, Users, Package, BarChart3, FileText, ChevronDown, ChevronUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { VoiceInput, speakText } from "@/components/VoiceInput";
import { LanguageSelector } from "@/components/LanguageSelector";
import { ChatSidebar } from "@/components/ChatSidebar";
import DataCharts from "@/components/DataCharts";
import { ResultCard } from "@/components/ResultCard";
import { extractAgentResult, isPrWorkflow as isPrWorkflowCheck, isVendorResult } from "@/lib/agentResultExtractor";
import { formatAgentMarkdown, buildResultCardProps } from "@/lib/agentFormatters";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useLocation, useSearch } from "wouter";
import { useToast } from "@/hooks/use-toast";

/* ================================================================ */
/*  Types                                                            */
/* ================================================================ */

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  dataSource?: string;
  queryType?: string;
  resultKind?: string;
  agentModeCard?: { agentType: string; agentName: string; description?: string };
  chartData?: Array<Record<string, string | number | null | undefined>>;
  agentResult?: {
    agent: string;
    confidence: number;
    executionTimeMs: number;
    verdict: string;
    dataSource?: string;
    queryType?: string;
    score?: { total: number; subscores?: Record<string, number> };
    findings: Array<{ severity: "error" | "warning" | "success" | "info"; message: string }>;
    approvalChain?: Array<{ level: number; approver: string; email: string; status: string }>;
  };
}

interface ChatSession {
  id: string;
  title: string;
  timestamp: number;
  messages: Message[];
  language: string;
  processHistory?: ProcessHistoryEntry[];
}

interface ProcessHistoryEntry {
  messageId: string;
  agent: string;
  agents?: string[];
  query?: string;
  timestamp?: number;
  steps: AgentStep[];
  details: Record<string, any>;
}

interface AgentStep {
  id: string;
  name: string;
  status: "pending" | "active" | "complete" | "error";
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

interface PendingDepartmentSelection {
  originalMessage: string;
  selectedDepartment: string;
  options: string[];
  context: "budget" | "pr_creation";
}

interface VendorResumeContext {
  department?: string;
  budget?: number;
  budget_category?: string;
  category?: string;
  quantity?: number;
  product_name?: string;
  requester_name?: string;
  urgency?: string;
  justification?: string;
}

interface AgentRegistryItem {
  type: string;
  name: string;
  description?: string;
  status?: string;
  tools_count?: number;
}

/* ================================================================ */
/*  Constants                                                        */
/* ================================================================ */

const STORAGE_KEY = "chat_sessions";
const ACTIVE_SESSION_KEY = "active_session_id";
const AGENT_MODE_KEY = "chat_selected_agent_type";
const DEFAULT_DEPARTMENTS = ["IT", "Finance", "Operations", "Procurement", "HR"];

/**
 * Chat data version — increment this whenever the chat data schema changes
 * or a major UI overhaul requires a clean slate.
 * v2 = dark-theme rewrite (April 2026)
 */
const CHAT_DATA_VERSION = "2";
const CHAT_VERSION_KEY = "chat_data_version";

/* ================================================================ */
/*  Pure helpers — no React state, no side effects                   */
/* ================================================================ */

const createLiveSteps = (): AgentStep[] => [
  { id: "received",    name: "Request Received",      status: "pending", message: "Waiting for backend acknowledgment" },
  { id: "classifying", name: "Intent Classification", status: "pending", message: "Determining request intent" },
  { id: "routing",     name: "Routing",               status: "pending", message: "Selecting best agent/workflow" },
  { id: "observing",   name: "Observe",               status: "pending", message: "Gathering required context and data" },
  { id: "deciding",    name: "Decide",                status: "pending", message: "Model reasoning on gathered context" },
  { id: "acting",      name: "Act",                   status: "pending", message: "Executing tool/database actions" },
  { id: "learning",    name: "Learn",                 status: "pending", message: "Recording execution outcomes" },
  { id: "complete",    name: "Finalize",              status: "pending", message: "Preparing final response for UI" },
];

const getAgentIcon = (type: string) => {
  const t = (type || "").toLowerCase();
  if (t.includes("budget")) return DollarSign;
  if (t.includes("approval")) return GitBranch;
  if (t.includes("risk")) return ShieldCheck;
  if (t.includes("vendor") || t.includes("supplier")) return Users;
  if (t.includes("inventory")) return Package;
  if (t.includes("spend") || t.includes("price")) return BarChart3;
  if (t.includes("compliance") || t.includes("invoice") || t.includes("contract")) return FileText;
  return Bot;
};

const parseAmountWithSuffix = (raw?: string, suffix?: string): number | undefined => {
  if (!raw) return undefined;
  const n = Number(raw.replace(/,/g, ""));
  if (!Number.isFinite(n)) return undefined;
  const s = (suffix || "").toLowerCase();
  return n * (s === "k" ? 1_000 : s === "m" ? 1_000_000 : 1);
};

const extractPrData = (message: string): Record<string, any> => {
  const payload: Record<string, any> = {};
  const text = message.toLowerCase();

  // Vendor confirmation
  const vendorConfirm =
    message.match(/^\s*confirm_vendor\s*:\s*"?([^"\n.]+?)"?\s*(?:\.|$)/i) ||
    message.match(/^\s*select\s+vendor\s*:\s*"?([^"\n.]+?)"?\s*(?:\.|$)/i) ||
    message.match(/^\s*user\s+selected\s+vendor\s*"([^"]+)"/i);
  if (vendorConfirm?.[1]) {
    const selectedVendor = vendorConfirm[1].trim();
    Object.assign(payload, {
      intent_hint: "vendor_confirmation",
      workflow_resume: /\bcontinue\s+pr\s+creation\s+workflow\b/i.test(message),
      vendor_confirmed: true,
      selected_vendor_name: selectedVendor,
      vendor_name: selectedVendor,
    });
  }

  // Department
  const deptMatch = text.match(/\b(it|finance|operations|procurement|hr)\b/i);
  const department = deptMatch
    ? deptMatch[1].toLowerCase() === "it" ? "IT" : deptMatch[1].charAt(0).toUpperCase() + deptMatch[1].slice(1).toLowerCase()
    : undefined;

  // Quantity
  // Sprint D bugfix (2026-04-11): add procurement-verb pattern (procure/buy/
  // order/purchase/get/need/request N) + generic-noun fallback so "Procure 20
  // Dell PowerEdge servers at $8 each" extracts quantity=20 (was 1 before,
  // making total budget = 1 * 8 = $8 instead of 20 * 8 = $160).
  const qtyKw = text.match(/\b(?:quantity|qty)\s*[:=]?\s*(\d+)\b/i);
  const qtyItem = text.match(/(\d+)\s*(?:laptop\s+accessories|laptops?|accessories|servers?|monitors?|printers?|desktops?|workstations?|devices?|machines?|units?|items?|pcs?|pieces?)/i);
  const qtyVerb = text.match(/\b(?:procure|buy|order|purchase|get|need|request|acquire)\s+(?:me\s+)?(\d+)\b/i);
  // Fallback: when "at $X each" or "for $X each" is present, the first
  // integer in the text is almost always the quantity (regardless of noun).
  const qtyUnitContext = /(?:at|for)\s*\$?\s*[0-9][0-9,]*(?:\.\d+)?\s*(?:k|m)?\s*(?:each|per\s*(?:item|unit|pc|piece))\b/i.test(text);
  const qtyFirstNum = qtyUnitContext ? text.match(/\b(\d+)\b/) : null;
  const qtyMatch = qtyKw || qtyItem || qtyVerb || qtyFirstNum;
  const quantity = qtyMatch ? Number(qtyMatch[1]) : 1;

  // Budget category
  const budgetCatMatch = text.match(/\b(capex|opex)\b/i);
  const budgetCategory = budgetCatMatch ? budgetCatMatch[1].toUpperCase() : undefined;

  // Amount parsing (multiple strategies)
  const budgetCtx = text.match(/(?:budget|amount|total|cost)\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\b/i);
  const currencyM = text.match(/\$\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\b/i);
  const shorthand = text.match(/\b([0-9][0-9,]*(?:\.\d+)?)\s*([km])\b/i);
  const dollarWord = text.match(/\b([0-9][0-9,]*(?:\.\d+)?)\s*(?:dollars?|usd|bucks?)\b/i);
  const unitEach = text.match(/(?:at|for)\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\s*(?:each|per\s*(?:item|unit|pc|piece))\b/i);
  const atPrice = text.match(/\bat\s*\$?\s*([0-9][0-9,]*(?:\.\d+)?)\s*([km])?\b/i);

  const parsedUnitEach = parseAmountWithSuffix(unitEach?.[1], unitEach?.[2]);
  const budget = parsedUnitEach !== undefined
    ? quantity * parsedUnitEach
    : parseAmountWithSuffix(
        budgetCtx?.[1] || atPrice?.[1] || currencyM?.[1] || shorthand?.[1] || dollarWord?.[1],
        budgetCtx?.[2] || atPrice?.[2] || currencyM?.[2] || shorthand?.[2]
      );

  // Product name
  const officeSupplies = /\boffice\s+supplies\b/i.test(message);
  const productName = officeSupplies ? "Office Supplies"
    : text.includes("laptop") ? "Laptop"
    : text.includes("printer") ? "Printer"
    : text.includes("server") ? "Server"
    : "Equipment";

  // Create intent detection
  const isCreate = /\b(create|raise|submit|make)\b.{0,40}\b(pr|purchase requisition|requisition)\b|\b(i want to|need to|please)\s+(buy|purchase|order)\b/i.test(text);

  if (!payload.intent_hint) {
    payload.intent_hint = isCreate ? "pr_creation" : "general";
  }

  if (department) payload.department = department;
  if (budget !== undefined && Number.isFinite(budget)) payload.budget = budget;
  if (budgetCategory) payload.budget_category = budgetCategory;
  if (qtyMatch) payload.quantity = quantity;
  if (/(laptop|printer|server|equipment|item)/i.test(text)) payload.product_name = productName;

  // Defaults for create intents
  if (isCreate) {
    const hasNum = /\b\d+(?:\.\d+)?\b/.test(text);
    if (payload.budget === undefined && !hasNum) payload.budget = 50000;
    if (!payload.quantity) payload.quantity = 1;
    if (!payload.product_name) payload.product_name = "Equipment";
    payload.category = officeSupplies ? "Office Supplies" : "Electronics";
    if (!payload.budget_category) payload.budget_category = officeSupplies ? "OPEX" : "CAPEX";
    payload.requester_name = "Chat User";
    payload.urgency = "Normal";
  }

  // Vendor from "from XYZ"
  const vendorFrom = message.match(/\bfrom\s+([^.,;\n]+?)(?=\s*(?:\.|,|;|$|business\s+justification))/i);
  if (vendorFrom?.[1]) payload.vendor_name = vendorFrom[1].trim();

  // Justification
  const justMatch = message.match(/\b(?:business\s+)?justification\s*:\s*(.+)$/i);
  if (justMatch?.[1]?.trim()) payload.justification = justMatch[1].trim();

  if (officeSupplies) {
    payload.category = "Office Supplies";
    payload.product_name = "Office Supplies";
    if (!payload.budget_category) payload.budget_category = "OPEX";
  }

  if (payload.intent_hint === "vendor_confirmation") {
    if (!payload.requester_name) payload.requester_name = "Chat User";
    if (!payload.urgency) payload.urgency = "Normal";
    if (!payload.quantity) payload.quantity = 1;
    if (!payload.product_name && officeSupplies) payload.product_name = "Office Supplies";
  }

  return payload;
};

/** Build context hints from previous messages for short follow-up queries */
const buildFollowupHints = (history: Message[], current: string): Record<string, string> => {
  const text = current.trim().toLowerCase();
  if (!text) return {};

  const hasDomain = /\b(pr|purchase request|purchase requisition|budget|vendor|supplier|risk|approval|contract|compliance|invoice|inventory)\b/i.test(text);
  const hasContext = /\b(it|finance|operations|procurement|hr|capex|opex)\b/i.test(text) || /\$?\s*\d/.test(text);
  const isFollowup = /^(what about|and\b|also\b|same\b|it\b|this\b|that\b|those\b|now\b|then\b|re-?run\b)/i.test(text);

  if (hasDomain && hasContext) return {};
  if (!isFollowup && text.split(/\s+/).length > 7) return {};

  const lastAssistant = [...history].reverse().find(m => m.role === "assistant");
  const lastUser = [...history].reverse().find(m => m.role === "user");
  if (!lastAssistant && !lastUser) return {};

  const hints: Record<string, string> = {};
  if (lastAssistant?.dataSource) hints._prev_data_source = String(lastAssistant.dataSource);
  if (lastAssistant?.queryType) hints._prev_query_type = String(lastAssistant.queryType);
  if (lastAssistant?.agentResult?.agent) hints._prev_agent = String(lastAssistant.agentResult.agent);
  if (lastUser?.content) hints._prev_user_message = String(lastUser.content).slice(0, 500);
  return hints;
};

const extractVendorChoices = (payload: Record<string, any>): VendorChoiceOption[] => {
  const choices: VendorChoiceOption[] = [];
  const primary = payload?.primary_recommendation;
  if (primary?.vendor_name) {
    choices.push({ name: String(primary.vendor_name), score: typeof primary.score === "number" ? primary.score : undefined, reason: primary.reason });
  } else if (payload?.recommended_vendor) {
    choices.push({ name: String(payload.recommended_vendor) });
  }
  for (const alt of payload?.alternative_recommendations || []) {
    if (alt?.vendor_name) choices.push({ name: String(alt.vendor_name), score: typeof alt.score === "number" ? alt.score : undefined, reason: alt.reason });
  }
  for (const opt of payload?.top_vendor_options || []) {
    const name = String(opt?.vendor_name || opt?.name || "").trim();
    if (name) choices.push({ name, score: typeof opt?.score === "number" ? opt.score : undefined, reason: opt?.reason });
  }
  const unique = new Map<string, VendorChoiceOption>();
  for (const item of choices) if (item.name && !unique.has(item.name)) unique.set(item.name, item);
  return Array.from(unique.values()).slice(0, 5);
};

/** localStorage session helpers */
const loadSessions = (): ChatSession[] => {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); } catch { return []; }
};
const saveSessions = (sessions: ChatSession[]) => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions)); } catch {}
};
const genTitle = (msg: string) => {
  const t = msg.slice(0, 80).trim();
  return t.length < msg.length ? t + "..." : t;
};

/* ================================================================ */
/*  Markdown renderer components (shared between message variants)   */
/* ================================================================ */

const mdComponents = {
  table: ({ node, ...props }: any) => (
    <div className="overflow-x-auto my-4 rounded-lg border border-border">
      <table className="border-collapse w-full text-sm" {...props} />
    </div>
  ),
  th: ({ node, ...props }: any) => (
    <th className="border-b-2 border-border px-4 py-3 bg-muted/80 font-semibold text-left text-xs uppercase tracking-wider" {...props} />
  ),
  td: ({ node, ...props }: any) => (
    <td className="border-b border-border/50 px-4 py-3 hover:bg-muted/30 transition-colors" {...props} />
  ),
};

/* ================================================================ */
/*  Main Component                                                   */
/* ================================================================ */

export default function ChatPage() {
  /* ---- routing / toast ---- */
  const [, setLocation] = useLocation();
  const search = useSearch();
  const { toast } = useToast();
  const API_BASE = import.meta.env.VITE_API_URL || "";

  /* ---- sessions ---- */
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [processHistory, setProcessHistory] = useState<ProcessHistoryEntry[]>([]);
  const [sessionsReady, setSessionsReady] = useState(false);

  /* ---- input ---- */
  const [input, setInput] = useState("");
  const [language, setLanguage] = useState("en");
  const [voiceOutputEnabled, setVoiceOutputEnabled] = useState(false);

  /* ---- streaming state ---- */
  const [isStreaming, setIsStreaming] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("");
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);
  const [currentAgent, setCurrentAgent] = useState("");
  const [agentPhaseDetails, setAgentPhaseDetails] = useState<Record<string, any>>({});

  /* ---- UI toggles ---- */
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [welcomeVisible, setWelcomeVisible] = useState(false);
  const [welcomePhase, setWelcomePhase] = useState<"center" | "to-top">("center");
  const [headerVisible, setHeaderVisible] = useState(true);

  /* ---- agent mode ---- */
  const [selectedAgentType, setSelectedAgentType] = useState(() => localStorage.getItem(AGENT_MODE_KEY) || "auto");
  const [isAgentModeOpen, setIsAgentModeOpen] = useState(false);

  /* ---- vendor / department workflow ---- */
  const [pendingVendor, setPendingVendor] = useState<{
    sourceAgent: string;
    options: VendorChoiceOption[];
    resumeContext?: VendorResumeContext;
    requiresWorkflowResume?: boolean;
  } | null>(null);
  const [pendingDept, setPendingDept] = useState<PendingDepartmentSelection | null>(null);
  const [selectedVendorOpt, setSelectedVendorOpt] = useState("");
  const [vendorNote, setVendorNote] = useState("");

  /* ---- departments from API ---- */
  const [departments, setDepartments] = useState<string[]>(DEFAULT_DEPARTMENTS);

  /* ---- refs ---- */
  const scrollRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pipelineStepsRef = useRef<HTMLDivElement>(null);
  const isMountedRef = useRef(false);
  const streamAbortRef = useRef<AbortController | null>(null);
  const observedAgentsRef = useRef<Set<string>>(new Set());
  const vendorFpRef = useRef("");

  /* ================================================================ */
  /*  Fetch departments from API on mount                             */
  /* ================================================================ */
  useEffect(() => {
    fetch(`${API_BASE}/api/config/departments`)
      .then(r => r.json())
      .then(d => {
        if (Array.isArray(d.departments) && d.departments.length > 0) {
          setDepartments(d.departments);
        }
      })
      .catch(() => {});
  }, [API_BASE]);

  /* ================================================================ */
  /*  Agent registry from /api/agentic/agents                        */
  /* ================================================================ */
  const { data: agentRegistry } = useQuery<{ success: boolean; count: number; agents: AgentRegistryItem[] }>({
    queryKey: ["/api/agentic/agents"],
    queryFn: async () => {
      const r = await fetch(`${API_BASE}/api/agentic/agents`, { credentials: "include" });
      if (!r.ok) throw new Error(`Failed: ${r.status}`);
      return r.json();
    },
    staleTime: 30000,
    retry: 1,
  });

  const agentModeOptions = useMemo(() => [
    { type: "auto", name: "Auto Routing", description: "Orchestrator chooses the best agent for each request" },
    ...(agentRegistry?.agents || []).map(a => ({
      type: a.type,
      name: a.name,
      description: a.description || "Specialized procurement workflow agent",
    })),
  ], [agentRegistry]);

  const selectedAgentMeta = useMemo(
    () => agentModeOptions.find(o => o.type === selectedAgentType) || agentModeOptions[0],
    [agentModeOptions, selectedAgentType],
  );

  useEffect(() => { localStorage.setItem(AGENT_MODE_KEY, selectedAgentType); }, [selectedAgentType]);

  /* ================================================================ */
  /*  Scroll helpers                                                  */
  /* ================================================================ */
  const scrollToBottom = useCallback((attempts = 6) => {
    let n = 0;
    const tick = () => {
      n++;
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
      messagesEndRef.current?.scrollIntoView({ behavior: n === 1 ? "smooth" : "auto", block: "end" });
      if (n < attempts) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, []);

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const t = e.currentTarget;
    setShowScrollBtn(t.scrollHeight - t.scrollTop - t.clientHeight > 100);
  }, []);

  // Auto-scroll when messages / streaming change
  useEffect(() => { if (!showScrollBtn) scrollToBottom(4); }, [messages, isStreaming, agentSteps, showScrollBtn, scrollToBottom]);

  // Keep active step visible during streaming
  useEffect(() => {
    if (!isStreaming) return;
    const active = agentSteps.find(s => s.status === "active");
    if (active) {
      document.getElementById(`step-${active.id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else {
      pipelineStepsRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [agentSteps, isStreaming]);

  /* ================================================================ */
  /*  Mount / unmount tracking                                        */
  /* ================================================================ */
  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, []);

  /* ================================================================ */
  /*  Session management                                              */
  /* ================================================================ */
  const createNewSession = useCallback(() => {
    const newSession: ChatSession = {
      id: Date.now().toString(),
      title: "New Chat",
      timestamp: Date.now(),
      messages: [],
      language: "en",
      processHistory: [],
    };
    setSessions(prev => {
      const updated = [newSession, ...prev];
      saveSessions(updated);
      return updated;
    });
    setActiveSessionId(newSession.id);
    setMessages([]);
    setLanguage("en");
    setProcessHistory([]);
    localStorage.setItem(ACTIVE_SESSION_KEY, newSession.id);
    toast({ title: "New Chat", description: "Started a new conversation" });
  }, [toast]);

  const switchSession = useCallback((id: string) => {
    const session = sessions.find(s => s.id === id);
    if (!session) return;
    setActiveSessionId(id);
    setMessages(session.messages);
    setLanguage(session.language);
    setProcessHistory(session.processHistory || []);
    localStorage.setItem(ACTIVE_SESSION_KEY, id);
  }, [sessions]);

  const deleteSession = useCallback((id: string) => {
    if (sessions.length <= 1) {
      toast({ title: "Cannot Delete", description: "You must have at least one session", variant: "destructive" });
      return;
    }
    setSessions(prev => {
      const updated = prev.filter(s => s.id !== id);
      saveSessions(updated);
      return updated;
    });
    if (id === activeSessionId) {
      const remaining = sessions.filter(s => s.id !== id);
      if (remaining.length > 0) switchSession(remaining[0].id);
    }
    toast({ title: "Chat Deleted", description: "Conversation removed" });
  }, [sessions, activeSessionId, switchSession, toast]);

  // Load sessions on mount — with version migration to clear stale data
  useEffect(() => {
    // Version migration: clear old sessions from previous UI versions
    const storedVersion = localStorage.getItem(CHAT_VERSION_KEY);
    if (storedVersion !== CHAT_DATA_VERSION) {
      console.log(`[CHAT MIGRATION] Clearing stale sessions (old version: ${storedVersion ?? "none"}, new: ${CHAT_DATA_VERSION})`);
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(ACTIVE_SESSION_KEY);
      localStorage.removeItem("force_new_chat_session");
      // Also clear stale pipeline store data from old sessions
      localStorage.removeItem("pipeline-store-v1");
      localStorage.setItem(CHAT_VERSION_KEY, CHAT_DATA_VERSION);
    }

    const loaded = loadSessions();
    setSessions(loaded);

    const params = new URLSearchParams(search);
    const forceNew = params.get("new") === "1" || localStorage.getItem("force_new_chat_session") === "1";
    if (forceNew) {
      localStorage.removeItem("force_new_chat_session");
      const ns: ChatSession = { id: Date.now().toString(), title: "New Chat", timestamp: Date.now(), messages: [], language: "en", processHistory: [] };
      const updated = [ns, ...loaded];
      setSessions(updated);
      saveSessions(updated);
      setActiveSessionId(ns.id);
      setMessages([]);
      setProcessHistory([]);
      localStorage.setItem(ACTIVE_SESSION_KEY, ns.id);
      setSessionsReady(true);
      return;
    }

    const lastId = localStorage.getItem(ACTIVE_SESSION_KEY);
    const existing = loaded.find(s => s.id === lastId);
    if (existing) {
      setActiveSessionId(lastId!);
      setMessages(existing.messages);
      setLanguage(existing.language);
      setProcessHistory(existing.processHistory || []);
    } else if (loaded.length > 0) {
      setActiveSessionId(loaded[0].id);
      setMessages(loaded[0].messages);
      setLanguage(loaded[0].language);
      setProcessHistory(loaded[0].processHistory || []);
      localStorage.setItem(ACTIVE_SESSION_KEY, loaded[0].id);
    } else {
      createNewSession();
    }
    setSessionsReady(true);
  }, [search]);

  // Persist session on message / history change
  useEffect(() => {
    if (!activeSessionId || messages.length === 0) return;
    setSessions(prev => {
      const updated = prev.map(s => {
        if (s.id !== activeSessionId) return s;
        const title = s.title === "New Chat" && messages.length > 0 ? genTitle(messages[0].content) : s.title;
        return { ...s, title, messages, language, processHistory, timestamp: Date.now() };
      });
      saveSessions(updated);
      return updated;
    });
  }, [messages, activeSessionId, language, processHistory]);

  /* ================================================================ */
  /*  Welcome intro animation                                         */
  /* ================================================================ */
  useEffect(() => {
    if (!sessionsReady) return;
    const params = new URLSearchParams(search);
    const shouldShow = (params.get("intro") === "1" || (messages.length === 0 && selectedAgentType === "auto")) && messages.length === 0;
    if (!shouldShow) { setWelcomeVisible(false); setHeaderVisible(true); return; }

    setHeaderVisible(false);
    setWelcomeVisible(true);
    setWelcomePhase("center");
    const t1 = setTimeout(() => setWelcomePhase("to-top"), 900);
    const t2 = setTimeout(() => { setWelcomeVisible(false); setHeaderVisible(true); }, 1800);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [search, messages.length, selectedAgentType, sessionsReady]);

  /* ================================================================ */
  /*  Vendor prompt helper                                            */
  /* ================================================================ */
  const maybePromptVendor = useCallback((normalised: any) => {
    const payload = normalised?.payload || {};
    const ws = String(payload?.status || "").toLowerCase();
    if (ws === "failed" || ws === "error") { setPendingVendor(null); vendorFpRef.current = ""; return; }

    // If the workflow is already past the vendor gate (resumed elsewhere — e.g. /sessions/:id),
    // skip the inline vendor prompt. The gate lives on SessionPage now.
    const wasResumed = ws === "in_progress" || ws === "completed" || ws === "awaiting_approval" || ws === "awaiting_goods_receipt";
    if (wasResumed) { setPendingVendor(null); vendorFpRef.current = ""; return; }

    const isAwaiting = payload?.awaiting_vendor_confirmation === true
      || ws === "awaiting_vendor_confirmation"
      || String(normalised?.status || "").toLowerCase() === "awaiting_vendor_confirmation";
    if (!isAwaiting) { setPendingVendor(null); vendorFpRef.current = ""; return; }

    const options = extractVendorChoices(payload);
    if (options.length === 0) return;

    const fp = `${normalised.agent}:${options.map(o => o.name).join("|")}`;
    if (vendorFpRef.current === fp) return;
    vendorFpRef.current = fp;

    const wc = payload.workflow_context || {};
    const wp = wc.pr_data || {};
    setPendingVendor({
      sourceAgent: normalised.agent || "VendorSelectionAgent",
      options,
      requiresWorkflowResume: true,
      resumeContext: {
        department: payload.department ?? wc.department ?? wp.department,
        budget: typeof payload.budget === "number" ? payload.budget : (typeof wc.budget === "number" ? wc.budget : wp.budget),
        budget_category: payload.budget_category ?? wc.budget_category ?? wp.budget_category,
        category: payload.category ?? wc.category ?? wp.category,
        quantity: typeof payload.quantity === "number" ? payload.quantity : (typeof wc.quantity === "number" ? wc.quantity : wp.quantity),
        product_name: payload.product_name ?? wc.product_name ?? wp.product_name,
        requester_name: payload.requester_name ?? wc.requester_name ?? wp.requester_name,
        urgency: payload.urgency ?? wp.urgency,
        justification: payload.justification ?? wc.justification ?? wp.justification,
      },
    });
    setMessages(prev => [...prev, {
      id: `${Date.now()}_vendor_prompt`,
      role: "assistant",
      content: "Please choose a vendor to continue PR creation. You can add a comment with your selection.",
      dataSource: "Agentic",
      queryType: "VENDOR",
    }]);
  }, []);

  // Sync vendor option when vendor selection changes
  useEffect(() => {
    if (!pendingVendor || pendingVendor.options.length === 0) { setSelectedVendorOpt(""); setVendorNote(""); return; }
    setSelectedVendorOpt(prev => (prev && pendingVendor.options.some(o => o.name === prev)) ? prev : pendingVendor.options[0]?.name || "");
  }, [pendingVendor]);

  /* ================================================================ */
  /*  Agent mode select handler                                       */
  /* ================================================================ */
  const handleAgentModeSelect = useCallback((agentType: string) => {
    if (agentType === selectedAgentType) { setIsAgentModeOpen(false); return; }
    const selected = agentModeOptions.find(o => o.type === agentType);
    setSelectedAgentType(agentType);
    setPendingDept(null);
    setPendingVendor(null);
    vendorFpRef.current = "";

    if (agentType !== "auto") {
      const modeMsg: Message = {
        id: `${Date.now()}_agent_switch`,
        role: "assistant",
        content: "",
        dataSource: "agent_mode",
        queryType: "AGENT_MODE",
        agentModeCard: { agentType, agentName: selected?.name || agentType, description: selected?.description },
      };
      setMessages(prev => {
        const updated = [...prev, modeMsg];
        if (activeSessionId) {
          const title = sessions.find(s => s.id === activeSessionId)?.title || "New Chat";
          const updatedSessions = sessions.map(s =>
            s.id === activeSessionId ? { ...s, messages: updated, title, timestamp: Date.now() } : s
          );
          saveSessions(updatedSessions);
          setSessions(updatedSessions);
        }
        return updated;
      });
    }
    setIsAgentModeOpen(false);
  }, [selectedAgentType, agentModeOptions, activeSessionId, sessions]);

  /* ================================================================ */
  /*  Department selection prompt                                     */
  /* ================================================================ */
  const promptDepartment = useCallback((originalMsg: string, context: "budget" | "pr_creation") => {
    setPendingDept({ originalMessage: originalMsg, selectedDepartment: departments[0], options: departments, context });
    setMessages(prev => [...prev, {
      id: `${Date.now()}_dept_prompt`,
      role: "assistant",
      content: context === "pr_creation"
        ? "Which department is this purchase request for? Please select one from the list below."
        : "Budget verification needs a department. Please choose one to continue.",
      dataSource: "Agentic",
      queryType: context === "pr_creation" ? "CREATE" : "BUDGET",
    }]);
  }, [departments]);

  const handleConfirmDepartment = useCallback(() => {
    if (!pendingDept || chatMutation.isPending) return;
    const dept = pendingDept.selectedDepartment;
    const userMsg: Message = { id: Date.now().toString(), role: "user", content: `${pendingDept.originalMessage} (Department: ${dept})` };
    const updated = [...messages, userMsg];
    setMessages(updated);

    if (activeSessionId) {
      const title = sessions.find(s => s.id === activeSessionId)?.title || "New Chat";
      saveSessions(sessions.map(s => s.id === activeSessionId ? { ...s, messages: updated, title: title === "New Chat" ? genTitle(userMsg.content) : title, timestamp: Date.now() } : s));
    }

    setPendingDept(null);
    chatMutation.mutate(`${pendingDept.originalMessage}. Department: ${dept}.`);
    setInput("");
  }, [pendingDept, messages, activeSessionId, sessions]);

  /* ================================================================ */
  /*  Build normalised result + assistant message (shared logic)      */
  /* ================================================================ */
  const buildAssistantMessage = useCallback((data: any, agentName: string): { message: Message; normalised: any } => {
    const normalised = extractAgentResult(data, agentName);

    let formatted: string;
    try { formatted = formatAgentMarkdown(normalised); }
    catch { formatted = `## Agent Result (${normalised.agent})\n\n\`\`\`json\n${JSON.stringify(normalised.payload, null, 2).slice(0, 2000)}\n\`\`\``; }

    let cardProps: ReturnType<typeof buildResultCardProps>;
    try { cardProps = buildResultCardProps(normalised); }
    catch { cardProps = { agent: normalised.agent, confidence: 0.95, executionTimeMs: 0, verdict: normalised.status, findings: [{ severity: "info", message: `Kind: ${normalised.kind}` }] }; }

    const isGeneral = normalised.dataSource === "general" || normalised.queryType === "GENERAL";
    return {
      normalised,
      message: {
        id: Date.now().toString(),
        role: "assistant",
        content: formatted,
        dataSource: normalised.dataSource,
        queryType: normalised.queryType || undefined,
        resultKind: normalised.kind,
        agentResult: isGeneral ? undefined : cardProps,
      },
    };
  }, []);

  /* ================================================================ */
  /*  SSE Mutation — the core streaming engine                        */
  /* ================================================================ */
  const chatMutation = useMutation({
    mutationFn: async (message: string) => {
      const prData = extractPrData(message);
      const contextHints = buildFollowupHints(messages, message);
      const isCreate = prData.intent_hint === "pr_creation";
      const isResume = prData.workflow_resume === true;
      const forced = selectedAgentType !== "auto" ? selectedAgentType : undefined;
      const agentType = forced || ((isCreate || isResume) ? "pr_creation" : undefined);

      setIsStreaming(true);
      setLoadingMessage("Processing...");
      const initialSteps = createLiveSteps();
      // Immediately activate the first step so the pipeline progress UI
      // renders right away — otherwise there's a 10-15s blank screen while
      // the backend classifies the intent before the first SSE event arrives.
      if (initialSteps.length > 0) {
        initialSteps[0] = { ...initialSteps[0], status: "active", message: "Connecting to AI..." };
      }
      setAgentSteps(initialSteps);
      setCurrentAgent("");
      setAgentPhaseDetails({});

      const mutationStart = Date.now();
      let streamAgentName = "";
      observedAgentsRef.current = new Set();

      const abortCtrl = new AbortController();
      streamAbortRef.current = abortCtrl;

      console.log("[SSE] Sending request:", { message: message.slice(0, 80), agentType, prDataKeys: Object.keys(prData) });

      const response = await fetch(`${API_BASE}/api/agentic/execute/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request: message, pr_data: { ...prData, ...contextHints }, agent_type: agentType }),
        credentials: "include",
        signal: abortCtrl.signal,
      });

      console.log("[SSE] Response status:", response.status, response.statusText);

      if (!response.ok) {
        if (response.status === 429) {
          const retry = response.headers.get("Retry-After");
          throw new Error(`Too Many Requests${retry ? ` (retry in ${retry}s)` : ""}`);
        }
        throw new Error(`Backend returned ${response.status}: ${response.statusText}`);
      }

      // GENERAL/greeting queries stay on ChatPage for instant inline response.
      // P2P_FULL queries hop to /sessions/:id via the session_created SSE event.
      let isGeneralQuery = false;
      // sessionRedirected: this run hopped to /sessions/:id via session_created.
      // When true, the chat MUST NOT render the legacy "complete" payload as a
      // chat bubble, because the session view is the source of truth and the
      // legacy payload is stale by the time it arrives.
      let sessionRedirected = false;

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let finalData: any = null;

      if (!reader) throw new Error("No response body reader");

      /* ---- helper closures for SSE handler ---- */
      const updateStep = (id: string, status: AgentStep["status"], message?: string, agent?: string) => {
        setAgentSteps(prev => prev.map(s => {
          if (s.id !== id) return s;
          const ts = Date.now();
          const startedAt = status === "active" ? (s.startedAt ?? ts) : s.startedAt;
          const completedAt = (status === "complete" || status === "error") ? (s.completedAt ?? ts) : s.completedAt;
          const durationMs = (status === "complete" || status === "error") ? Math.max(0, (completedAt ?? ts) - (startedAt ?? ts)) : s.durationMs;
          return { ...s, status, message: message || s.message, agent: agent || s.agent, startedAt, completedAt, durationMs };
        }));
      };

      const elapsed = (ts?: string): number => {
        const parsed = ts ? Date.parse(ts) : Date.now();
        return Number.isFinite(parsed) && parsed > 0 ? Math.max(0, parsed - mutationStart) : 0;
      };

      /* ---- stream read loop ---- */
      let event: any;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          for (const line of chunk.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            try {
              event = JSON.parse(line.slice(6));
            } catch { continue; }

            const ms = elapsed(event?.timestamp);
            const evtAgent = String(event?.data?.agent || streamAgentName || "").trim();

            console.log(`[SSE-EVENT] type=${event.type} agent=${evtAgent} ms=${ms}`, event.data ? Object.keys(event.data) : "no-data");

            switch (event.type) {
              /* ---- SESSION_CREATED (P2P_FULL) ---- */
              // Backend just created an execution_session for this P2P run.
              // Redirect immediately to the session-driven view — the rest of the
              // event log will be streamed to /sessions/:id via the session SSE
              // endpoint, so we don't need to keep consuming this stream here.
              case "session_created": {
                const sid = String(event.data?.session_id || "").trim();
                if (sid) {
                  const isReused = !!event.data?.reused_existing;
                  const existingStatus = event.data?.existing_status || "";
                  const existingPhase = event.data?.existing_phase || "";
                  if (isReused) {
                    console.log(`[ChatPage] SESSION-REUSED sid=${sid.slice(0, 8)} status=${existingStatus} phase=${existingPhase}`);
                    toast({
                      title: "Session already exists",
                      description: `This request matched an in-progress session (${existingPhase}, ${existingStatus}). Opening it.`,
                    });
                  } else {
                    console.log(`[ChatPage] SESSION-CREATED sid=${sid.slice(0, 8)} ms=${ms} — redirecting to /sessions/${sid.slice(0, 8)}`);
                  }
                  sessionRedirected = true;
                  setLocation(`/sessions/${sid}`);
                  finalData = {
                    __session_pointer: true,
                    session_id: sid,
                    response: isReused
                      ? `Existing session **${sid.slice(0, 8)}** (${existingStatus}). [Open session →](/sessions/${sid})`
                      : `Procurement session **${sid.slice(0, 8)}** started. [Open session →](/sessions/${sid})`,
                  };
                  break;
                }
                console.warn("[ChatPage] SESSION-CREATED but session_id was empty — falling through");
                break;
              }

              /* ---- RECEIVED ---- */
              case "received":
                updateStep("received", "complete", "Request dispatched");
                break;

              /* ---- CLASSIFYING ---- */
              case "classifying":
                updateStep("received", "complete");
                updateStep("classifying", "active", "Analyzing user intent...");
                break;

              /* ---- ROUTING ---- */
              case "routing": {
                const routeQueryType = String(event.data.query_type || "").toUpperCase();
                if (routeQueryType === "GENERAL") {
                  isGeneralQuery = true;
                }
                updateStep("classifying", "complete", "Intent classified");
                updateStep("routing", "active", isGeneralQuery ? "General query — responding inline" : "Routing to specialized agent...");
                break;
              }

              /* ---- AGENT_SELECTED ---- */
              case "agent_selected": {
                const agName = String(event.data.agent || "");
                updateStep("routing", "complete", `Agent: ${agName}`);
                setCurrentAgent(agName);
                streamAgentName = agName;
                if (agName) observedAgentsRef.current.add(agName);
                for (const sec of event.data.secondary_agents || []) if (sec) observedAgentsRef.current.add(String(sec));
                break;
              }

              /* ---- OBSERVING ---- */
              case "observing": {
                if (evtAgent) observedAgentsRef.current.add(evtAgent);
                updateStep("observing", "active", "Gathering data from databases...", evtAgent);
                updateStep("routing", "complete");
                break;
              }

              /* ---- OBSERVATION_COMPLETE ---- */
              case "observation_complete": {
                if (evtAgent) observedAgentsRef.current.add(evtAgent);
                updateStep("observing", "complete", "Data gathered", evtAgent);
                break;
              }

              /* ---- DECIDING ---- */
              case "deciding": {
                if (evtAgent) observedAgentsRef.current.add(evtAgent);
                updateStep("deciding", "active", "AI analyzing data...", evtAgent);
                break;
              }

              /* ---- DECISION_MADE ---- */
              case "decision_made": {
                if (evtAgent) observedAgentsRef.current.add(evtAgent);
                const conf = typeof event.data.confidence === "number"
                  ? Math.round(event.data.confidence <= 1 ? event.data.confidence * 100 : event.data.confidence)
                  : 95;
                // Format action for human readability (avoid raw JSON in logs/UI)
                const _ACTION_MAP: Record<string, string> = {
                  p2p_full: "Full Procure-to-Pay Pipeline", pr_creation: "Purchase Requisition Creation",
                  approve: "Approved", approve_with_warnings: "Approved with Warnings",
                  approve_with_warning: "Approved with Warning", approve_with_high_alert: "Approved — High Alert",
                  approve_with_critical_alert: "Approved — Critical Alert", reject_insufficient_budget: "Rejected — Insufficient Budget",
                  recommend_vendor: "Vendor Recommended", approve_low_risk: "Approved — Low Risk",
                  error_budget_check: "Budget Check Error", report_status: "Status Report",
                };
                const _fmtAction = (raw: any): string => {
                  if (!raw) return "Completed";
                  if (typeof raw === "string") {
                    if (raw.startsWith("{")) try { return _fmtAction(JSON.parse(raw)); } catch {}
                    return _ACTION_MAP[raw] || raw.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
                  }
                  if (typeof raw === "object") {
                    const v = raw.primary || raw.action || raw.decision || raw.type || raw.status;
                    if (v && typeof v === "string") return _ACTION_MAP[v] || v.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
                    for (const val of Object.values(raw)) {
                      if (typeof val === "string" && val.length > 0 && val.length < 80) return _ACTION_MAP[val as string] || (val as string);
                    }
                  }
                  return "Completed";
                };
                const actionLabel = _fmtAction(event.data.action);
                updateStep("deciding", "complete", `Decision: ${actionLabel} (${conf}%)`, evtAgent);
                setAgentPhaseDetails(prev => ({ ...prev, deciding: { action: event.data.action, confidence: conf, reasoning: event.data.reasoning } }));
                break;
              }

              /* ---- ACTING ---- */
              case "acting": {
                if (evtAgent) observedAgentsRef.current.add(evtAgent);
                updateStep("acting", "active", "Executing actions...", evtAgent);
                break;
              }

              /* ---- ACTION_COMPLETE ---- */
              case "action_complete": {
                if (evtAgent) observedAgentsRef.current.add(evtAgent);
                updateStep("acting", "complete", `Done (${event.data.execution_time_ms || 0}ms)`, evtAgent);
                break;
              }

              /* ---- LEARNING ---- */
              case "learning": {
                if (evtAgent) observedAgentsRef.current.add(evtAgent);
                updateStep("learning", "active", "Recording outcomes to database...");
                break;
              }

              /* ---- LEARNING_COMPLETE ---- */
              case "learning_complete": {
                if (evtAgent) observedAgentsRef.current.add(evtAgent);
                updateStep("learning", "complete", "Audit trail saved");
                updateStep("complete", "active", "Preparing response");
                break;
              }

              /* ---- BUSINESS_SUMMARY ---- */
              case "business_summary":
                // Business summary is rendered by the ResultCard on finalization.
                // No inline pipeline-store write needed here.
                break;

              /* ---- COMPLETE ---- */
              case "complete": {
                console.log("[SSE-COMPLETE]", {
                  isGeneralQuery,
                  sessionRedirected,
                  isMounted: isMountedRef.current,
                  dataKeys: event.data ? Object.keys(event.data) : [],
                  status: event.data?.status,
                  agent: event.data?.agent || event.data?.agent_name,
                  hasResult: !!event.data?.result,
                  agentsInvoked: event.data?.agents_invoked || event.data?.result?.agents_invoked,
                });

                // SESSION HAND-OFF GUARD ───────────────────────────────────
                // If we already redirected to /sessions/:id via session_created,
                // the backend's stale legacy "complete" payload (which carries
                // human_action_required=vendor_selection etc.) MUST NOT bleed
                // back into the chat history. The session view is the truth;
                // chat just shows a session pointer card.
                if (sessionRedirected) {
                  console.log("[SSE-COMPLETE] sessionRedirected=true — suppressing legacy chat-side state writes");
                  // Keep the session-pointer finalData stashed in session_created.
                  break;
                }

                // For GENERAL queries: complete all steps that were active/pending
                if (isGeneralQuery) {
                  updateStep("routing", "complete", "General query — no agent needed");
                  // Mark remaining steps as complete so the progress shows 100%
                  for (const s of ["observing", "deciding", "acting", "learning", "complete"] as const) {
                    updateStep(s, "complete", s === "complete" ? "Response ready" : "Skipped (general)");
                  }
                } else {
                  updateStep("learning", "complete", "Audit trail saved");
                  updateStep("complete", "complete", "Response ready");
                }
                finalData = event.data;
                break;
              }

              /* ---- ERROR ---- */
              case "error": {
                setLoadingMessage(`Error: ${event.data.error}`);
                throw new Error(event.data.error);
              }
            }
          }
        }
      } finally {
        setIsStreaming(false);
      }

      console.log("[SSE-STREAM-END] Stream loop exited.", {
        finalData: finalData ? Object.keys(finalData) : null,
        isGeneralQuery,
        sessionRedirected,
        isMounted: isMountedRef.current,
      });

      // Nothing to drain — ChatPage no longer writes to any pipeline store.
      // GENERAL / inline answers flow to onSuccess; P2P_FULL already redirected
      // to /sessions/:id via session_created and onSuccess just renders the
      // session-pointer card.
      return finalData || { response: "Request processed successfully" };
    },

    onSuccess: (data) => {
      console.log("[onSuccess] fired.", { isMounted: isMountedRef.current, dataKeys: data ? Object.keys(data) : null, dataType: typeof data });
      if (!isMountedRef.current) {
        console.log("[onSuccess] SKIPPED — component unmounted mid-flight.");
        return;
      }

      // Session pointer fast-path: if the SSE handler stashed a session-pointer
      // payload (P2P_FULL handed off to /sessions/:id), render the pointer card
      // instead of the legacy "result" bubble.
      const pointerData = data as any;
      if (pointerData && pointerData.__session_pointer && pointerData.session_id) {
        const sid = String(pointerData.session_id);
        setLoadingMessage("");
        const pointerMsg: Message = {
          id: Date.now().toString(),
          role: "assistant",
          content:
            `**Procurement session started**\n\n` +
            `Session \`${sid.slice(0, 8)}\` is now running. Open it to review the live pipeline, ` +
            `respond to vendor selection, approval, and goods-receipt gates, and watch each phase as it completes.\n\n` +
            `[Open session →](/sessions/${sid})`,
          dataSource: "Agentic",
          queryType: "P2P_FULL" as any,
        };
        setMessages(prev => [...prev, pointerMsg]);
        setAgentSteps([]);
        setCurrentAgent("");
        setAgentPhaseDetails({});
        return;
      }

      try {
        setLoadingMessage("");
        const { message: assistantMsg, normalised } = buildAssistantMessage(data, currentAgent);
        setMessages(prev => [...prev, assistantMsg]);

        if (isPrWorkflowCheck(normalised) && normalised.status === "success") {
          setTimeout(() => setLocation("/approval-workflows"), 900);
        }

        if (!isVendorResult(normalised)) { setPendingVendor(null); vendorFpRef.current = ""; }
        maybePromptVendor(normalised);

        // Save process history (derived from local refs/state — no pipeline store read)
        setProcessHistory(prev => [{
          messageId: assistantMsg.id,
          agent: currentAgent,
          agents: Array.from(observedAgentsRef.current),
          query: "",
          timestamp: Date.now(),
          steps: [...agentSteps],
          details: { ...agentPhaseDetails },
        }, ...prev.slice(0, 9)]);
      } catch (err) {
        console.error("[onSuccess] Error building assistant message:", err);
        // Fallback: add raw data as message so user sees something
        const fallbackMsg: Message = {
          id: Date.now().toString(),
          role: "assistant",
          content: `## Agent Result\n\n\`\`\`json\n${JSON.stringify(data, null, 2).slice(0, 3000)}\n\`\`\``,
        };
        setMessages(prev => [...prev, fallbackMsg]);
      }

      // Reset — always runs even if formatter threw
      setAgentSteps([]);
      setCurrentAgent("");
      setAgentPhaseDetails({});

      if (voiceOutputEnabled && data?.result) {
        speakText(typeof data.result === "string" ? data.result : JSON.stringify(data.result), language);
      }
    },

    onError: (error: Error) => {
      console.error("[onError] SSE mutation failed:", error?.name, error?.message, error?.stack?.slice(0, 300));
      if (error?.name === "AbortError") {
        setLoadingMessage("");
        setIsStreaming(false);
        return;
      }

      setLoadingMessage("");
      setIsStreaming(false);
      setAgentSteps([]);
      setAgentPhaseDetails({});
      setCurrentAgent("");
      observedAgentsRef.current.clear();

      setMessages(prev => [...prev, {
        id: Date.now().toString(),
        role: "assistant",
        content: `## System Error\n\n**Error:** ${error?.message || "Unknown error"}\n\n**What to try:**\n- Check your internet connection\n- Try rephrasing your question\n- Refresh the page\n\n**Technical:** \`${error?.name || "Error"}\``,
      }]);

      toast({ title: "Request Failed", description: error?.message || "An error occurred", variant: "destructive" });
    },
  });

  /* ================================================================ */
  /*  Send handlers                                                   */
  /* ================================================================ */
  const handleSend = useCallback(() => {
    if (!input.trim() || chatMutation.isPending) return;

    if (pendingDept) {
      toast({ title: "Department required", description: "Please select a department to continue." });
      return;
    }

    if (pendingVendor) {
      const trimmed = input.trim();
      if (/^(yes|y|ok|okay|confirm|proceed|continue)$/i.test(trimmed) && pendingVendor.options[0]?.name) {
        handleVendorSelection(pendingVendor.options[0].name);
        setInput("");
        return;
      }
      const match = pendingVendor.options.find(o => trimmed.toLowerCase().startsWith(o.name.toLowerCase()));
      if (match) {
        const comment = trimmed.slice(match.name.length).replace(/^[:\-\s]+/, "").trim();
        handleVendorSelection(match.name, comment || undefined);
        setInput("");
        return;
      }
      toast({ title: "Vendor confirmation required", description: "Select one of the available vendors." });
      return;
    }

    setPendingVendor(null);
    vendorFpRef.current = "";

    const resolved = input.trim();
    const prData = extractPrData(resolved);

    // Prompt for department if needed
    const isBudget = /\b(budget|capex|opex|funds?|allocat|available|spending|utiliz|balance|verify|check)\b/i.test(resolved);
    if (selectedAgentType === "budget_verification" && isBudget && !prData.department) {
      promptDepartment(resolved, "budget");
      return;
    }
    if (prData.intent_hint === "pr_creation" && !prData.department) {
      promptDepartment(resolved, "pr_creation");
      return;
    }

    const userMsg: Message = { id: Date.now().toString(), role: "user", content: input.trim() };
    const updated = [...messages, userMsg];
    setMessages(updated);

    // Persist immediately before potential unmount
    if (activeSessionId) {
      const title = sessions.find(s => s.id === activeSessionId)?.title || "New Chat";
      saveSessions(sessions.map(s =>
        s.id === activeSessionId ? { ...s, messages: updated, title: title === "New Chat" ? genTitle(userMsg.content) : title, timestamp: Date.now() } : s
      ));
    }

    chatMutation.mutate(resolved);
    setInput("");
  }, [input, chatMutation, pendingDept, pendingVendor, messages, activeSessionId, sessions, selectedAgentType, promptDepartment, toast]);

  const handleVendorSelection = useCallback(async (vendorName: string, comment?: string) => {
    if (!vendorName || chatMutation.isPending) return;
    const note = (comment || "").trim();
    const userVisible = note ? `Select vendor: ${vendorName} - ${note}` : `Select vendor: ${vendorName}`;

    // Show user's selection in chat
    const userMsg: Message = { id: Date.now().toString(), role: "user", content: userVisible };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setPendingVendor(null);

    if (activeSessionId) {
      const title = sessions.find(s => s.id === activeSessionId)?.title || "New Chat";
      saveSessions(sessions.map(s =>
        s.id === activeSessionId ? { ...s, messages: updated, title: title === "New Chat" ? genTitle(userMsg.content) : title, timestamp: Date.now() } : s
      ));
    }

    // Non-P2P vendor confirmations flow through chat as a natural-language
    // follow-up. P2P vendor gates now live on /sessions/:id, so this path is
    // only used for standalone vendor-ranking queries where the user picks
    // from a shortlist and the agent saves the selection.
    const rc = pendingVendor?.resumeContext || {};
    const ctx = [
      rc.department ? `department ${rc.department}` : "",
      typeof rc.budget === "number" ? `budget $${rc.budget}` : "",
      rc.category ? `category ${rc.category}` : "",
      rc.product_name ? `product ${rc.product_name}` : "",
      typeof rc.quantity === "number" ? `quantity ${rc.quantity}` : "",
      rc.budget_category ? `budget category ${rc.budget_category}` : "",
      note ? `vendor note: ${note}` : "",
    ].filter(Boolean).join(", ");

    const followup = `CONFIRM_VENDOR: ${vendorName}. Save this vendor selection only${ctx ? ` with context: ${ctx}` : ""}. Do not create PR unless I explicitly ask.`;
    chatMutation.mutate(followup);
  }, [chatMutation, pendingVendor, messages, activeSessionId, sessions]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }, [handleSend]);

  /* ================================================================ */
  /*  RENDER                                                          */
  /* ================================================================ */

  const completedCount = agentSteps.filter(s => s.status === "complete").length;
  const progressPct = agentSteps.length > 0 ? (completedCount / agentSteps.length) * 100 : 0;
  const activeAgentLabel = currentAgent ? currentAgent.replace(/([A-Z])/g, " $1").trim() : "";

  /** Result kind → human label + color class */
  const kindMeta = (kind: string) => {
    switch (kind) {
      case "pr_workflow": return { label: "PR Workflow", cls: "bg-violet-100 text-violet-700 border-violet-300" };
      case "p2p_full":    return { label: "P2P Pipeline", cls: "bg-teal-100 text-teal-700 border-teal-300" };
      case "multi":       return { label: "Multi-Intent", cls: "bg-amber-100 text-amber-700 border-amber-300" };
      case "pending":     return { label: "Awaiting Approval", cls: "bg-orange-100 text-orange-700 border-orange-300" };
      default:            return { label: kind, cls: "bg-sky-100 text-sky-700 border-sky-300" };
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      {/* ---- Chat History Sidebar ---- */}
      <ChatSidebar
        sessions={sessions.map(s => ({ id: s.id, title: s.title, timestamp: s.timestamp, messageCount: s.messages.length }))}
        activeSessionId={activeSessionId}
        onSelectSession={switchSession}
        onNewChat={createNewSession}
        onDeleteSession={deleteSession}
      />

      {/* ---- Main Chat Column ---- */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

        {/* ══════════ HEADER — white with blue accent ══════════ */}
        <header className="flex-shrink-0 flex items-center justify-between gap-3 px-5 py-3 border-b border-slate-200 bg-white shadow-sm">
          <div className="flex items-center gap-3">
            <div className="relative">
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-md">
                <Bot className="h-5 w-5 text-white" />
              </div>
              <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-400 border-2 border-white" />
            </div>
            <div className={`transition-opacity duration-500 ${headerVisible ? "opacity-100" : "opacity-0"}`}>
              <h1 className="text-[15px] font-bold text-slate-800 tracking-tight">Procurement AI</h1>
              <p className="text-[11px] text-slate-500 font-medium">GPT-4o &middot; {agentRegistry?.count || 12} Agents Online</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <LanguageSelector value={language} onChange={setLanguage}
              triggerClassName="w-[140px] h-8 text-xs border-slate-200 bg-white text-slate-600 hover:bg-slate-50 focus:border-blue-400 [&>span]:text-slate-600"
              iconClassName="text-slate-400"
            />
            <VoiceInput onTranscript={setInput} language={language}
              voiceOutputEnabled={voiceOutputEnabled} onVoiceOutputToggle={setVoiceOutputEnabled}
              labelClassName="text-slate-500" activeIconClassName="text-blue-500" inactiveIconClassName="text-slate-400"
            />
            <div className="w-px h-6 bg-slate-200 mx-1" />
            <Button variant="ghost" size="sm" onClick={() => setLocation("/dashboard")}
              className="h-8 gap-1.5 text-xs text-slate-500 hover:text-blue-600 hover:bg-blue-50">
              <LayoutDashboard className="h-3.5 w-3.5" /> Dashboard
            </Button>
            <Button variant="ghost" size="sm" onClick={() => {
              localStorage.removeItem("isAuthenticated");
              localStorage.removeItem("userEmail");
              toast({ title: "Logged Out", description: "Successfully logged out." });
              setLocation("/");
            }} className="h-8 gap-1.5 text-xs text-slate-400 hover:text-red-600 hover:bg-red-50">
              <LogOut className="h-3.5 w-3.5" />
            </Button>
          </div>
        </header>

        {/* ══════════ MESSAGES AREA ══════════ */}
        <div className="flex-1 relative overflow-hidden bg-gradient-to-b from-slate-50 to-white">

          {/* Welcome overlay */}
          {welcomeVisible && messages.length === 0 && (
            <div className="absolute inset-0 z-20 flex items-center justify-center pointer-events-none">
              <div className={`rounded-3xl border border-blue-100 bg-white/95 backdrop-blur-xl px-10 py-8 text-center shadow-2xl shadow-blue-200/30 transition-all duration-700 ease-out ${
                welcomePhase === "to-top" ? "-translate-y-[38vh] scale-75 opacity-0" : "translate-y-0 scale-100 opacity-100"
              }`}>
                <div className="mx-auto mb-4 w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-300/40">
                  <Bot className="h-7 w-7 text-white" />
                </div>
                <p className="text-2xl font-bold tracking-tight text-slate-800">Procurement AI</p>
                <p className="mt-2 text-sm text-blue-600 font-medium">Enterprise-grade AI procurement intelligence</p>
                <div className="mt-4 flex items-center justify-center gap-3 text-[11px] font-semibold uppercase tracking-widest">
                  {["Budget", "Vendor", "Risk", "Approval", "Compliance"].map((t, i) => (
                    <span key={t} className="text-slate-400">{i > 0 && <span className="mr-3 text-slate-300">/</span>}{t}</span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Scrollable messages */}
          <div ref={scrollRef} className="h-full overflow-y-auto overflow-x-hidden scroll-smooth"
            onScroll={handleScroll}
            style={{ scrollbarWidth: "thin", scrollbarColor: "rgba(0,0,0,0.1) transparent" }}>
            <div className="px-5 py-6 space-y-5 max-w-4xl mx-auto min-h-full">

              {/* Empty state */}
              {messages.length === 0 && !welcomeVisible && (
                <div className="text-center py-24 space-y-6">
                  <div className="mx-auto w-20 h-20 rounded-3xl bg-gradient-to-br from-blue-100 to-indigo-100 flex items-center justify-center border border-blue-200">
                    <Bot className="h-9 w-9 text-blue-500" />
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-slate-800">How can I help today?</p>
                    <p className="text-sm text-slate-500 mt-1">Ask about budgets, vendors, approvals, risk assessments, or create purchase requests</p>
                  </div>
                  {selectedAgentType === "auto" && (
                    <div className="flex flex-wrap gap-2 justify-center mt-4">
                      {[
                        { q: "Check IT budget for $50K CAPEX", icon: DollarSign, color: "emerald" },
                        { q: "Create a PR for 10 laptops", icon: FileText, color: "violet" },
                        { q: "Assess vendor risk for TechCorp", icon: ShieldCheck, color: "amber" },
                      ].map(({ q, icon: I, color }) => (
                        <button key={q} onClick={() => { setInput(q); }}
                          className={`group flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border border-slate-200 bg-white text-slate-600 hover:text-blue-700 hover:bg-blue-50 hover:border-blue-300 transition-all cursor-pointer shadow-sm`}>
                          <I className={`h-3.5 w-3.5 text-${color}-500 group-hover:text-${color}-600`} />
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* ── Message list ── */}
              {messages.map(msg => (
                <div key={msg.id} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"} animate-in fade-in slide-in-from-bottom-2 duration-300`}>

                  {/* Bot avatar */}
                  {msg.role === "assistant" && !msg.agentResult && (
                    <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-blue-100 to-indigo-100 flex items-center justify-center border border-blue-200 mt-0.5">
                      <Bot className="h-4 w-4 text-blue-600" />
                    </div>
                  )}

                  {/* User message */}
                  {msg.role === "user" && (
                    <div className="max-w-[78%] rounded-2xl rounded-tr-md px-4 py-3 bg-gradient-to-br from-blue-500 to-blue-600 text-white shadow-md shadow-blue-300/30">
                      <p className="whitespace-pre-wrap text-[14px] leading-relaxed">{msg.content}</p>
                    </div>
                  )}

                  {/* Agent mode card */}
                  {msg.role === "assistant" && msg.agentModeCard && (
                    <div className="max-w-[78%] w-full">
                      <div className="relative overflow-hidden rounded-2xl border border-blue-200 bg-gradient-to-br from-blue-50 via-indigo-50 to-blue-50 px-6 py-5 text-center shadow-lg">
                        <div className="relative">
                          <div className="mx-auto mb-3 h-1 w-32 rounded-full bg-gradient-to-r from-blue-400 via-indigo-400 to-blue-400" />
                          <p className="text-xl font-bold tracking-tight text-slate-800">{msg.agentModeCard.agentName}</p>
                          <p className="mt-1.5 text-xs text-slate-500">Dedicated mode active. All queries route through this agent.</p>
                          <div className="mt-3 inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-100 border border-blue-200">
                            <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                            <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600">Locked</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Assistant message with ResultCard */}
                  {msg.role === "assistant" && msg.agentResult && !msg.agentModeCard && (
                    <div className="max-w-[85%] w-full space-y-2.5">
                      {/* Kind + Query badges */}
                      {msg.resultKind && (
                        <div className="flex items-center gap-2">
                          {(() => { const m = kindMeta(msg.resultKind); return (
                            <span className={`px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-full border ${m.cls}`}>{m.label}</span>
                          ); })()}
                          {msg.queryType && (
                            <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-slate-100 text-slate-500 border border-slate-200">
                              {msg.queryType}
                            </span>
                          )}
                        </div>
                      )}
                      <ResultCard
                        agent={msg.agentResult.agent} confidence={msg.agentResult.confidence}
                        executionTimeMs={msg.agentResult.executionTimeMs} verdict={msg.agentResult.verdict}
                        dataSource={msg.agentResult.dataSource || msg.dataSource} score={msg.agentResult.score}
                        findings={msg.agentResult.findings} approvalChain={msg.agentResult.approvalChain}
                        onViewApprovalChain={msg.agentResult.approvalChain ? () => toast({ title: "Approval Chain", description: "Viewing details..." }) : undefined}
                      />
                      {/* Sprint B: `/process` page + pipelineStore + side panel deleted.
                          P2P runs now live on /sessions/:id, and chat no longer hosts a
                          pipeline drawer — nothing to link to from an agent result card. */}
                      {msg.content && (
                        <div className="rounded-xl px-4 py-3 bg-slate-50 border border-slate-200">
                          <div className="prose prose-sm max-w-none prose-headings:text-slate-800 prose-p:text-slate-600 prose-strong:text-slate-700 prose-td:text-slate-600 prose-th:text-slate-700">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{msg.content}</ReactMarkdown>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Plain assistant message */}
                  {msg.role === "assistant" && !msg.agentResult && !msg.agentModeCard && (
                    <div className="max-w-[78%] rounded-2xl rounded-tl-md px-4 py-3 bg-white border border-slate-200 shadow-sm">
                      {msg.dataSource && (
                        <div className="mb-2">
                          <span className="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded bg-blue-100 text-blue-600 border border-blue-200">
                            {msg.dataSource}
                          </span>
                        </div>
                      )}
                      <div className="prose prose-sm max-w-none prose-headings:text-slate-800 prose-p:text-slate-600 prose-strong:text-slate-700">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{msg.content}</ReactMarkdown>
                      </div>
                      {msg.chartData && msg.chartData.length > 1 && <DataCharts data={msg.chartData} />}
                    </div>
                  )}

                  {/* User avatar */}
                  {msg.role === "user" && (
                    <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow-md mt-0.5">
                      <User className="h-4 w-4 text-white" />
                    </div>
                  )}
                </div>
              ))}

              {/* ── Live Pipeline Steps ── */}
              {(isStreaming || chatMutation.isPending) && agentSteps.some(s => s.status !== "pending") && (
                <div ref={pipelineStepsRef} className="flex gap-3 justify-start animate-in fade-in slide-in-from-bottom-3 duration-400">
                  <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center border border-blue-200 mt-0.5">
                    <Activity className="h-4 w-4 text-blue-500 animate-pulse" />
                  </div>
                  <div className="flex-1 max-w-[85%] rounded-xl border border-blue-200 bg-gradient-to-b from-blue-50 to-white overflow-hidden shadow-sm">
                    {/* Agent header bar */}
                    {activeAgentLabel && (
                      <div className="flex items-center justify-between px-4 py-2.5 bg-blue-50 border-b border-blue-100">
                        <div className="flex items-center gap-2">
                          <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                          <span className="text-xs font-bold text-blue-700 uppercase tracking-wider">{activeAgentLabel}</span>
                        </div>
                        <span className="text-[10px] font-mono text-slate-400">{completedCount}/{agentSteps.length}</span>
                      </div>
                    )}
                    {/* Steps */}
                    <div className="px-3 py-2 space-y-0.5">
                      {agentSteps.map(step => {
                        const isDone = step.status === "complete";
                        const isActive = step.status === "active";
                        const isErr = step.status === "error";
                        return (
                          <div key={step.id} id={`step-${step.id}`}
                            className={`flex items-center gap-2.5 text-[13px] px-2 py-1.5 rounded-lg transition-all duration-300 ${
                              isActive ? "bg-blue-50" : isDone ? "bg-emerald-50/50" : "opacity-40"
                            }`}>
                            <div className={`flex-shrink-0 w-[18px] h-[18px] rounded-full flex items-center justify-center ${
                              isDone ? "bg-emerald-500" : isActive ? "bg-blue-500" : isErr ? "bg-red-500" : "border border-slate-300"
                            }`}>
                              {isDone ? <CheckCircle2 className="h-3 w-3 text-white" /> :
                               isActive ? <Loader2 className="h-3 w-3 animate-spin text-white" /> :
                               isErr ? <AlertCircle className="h-3 w-3 text-white" /> : null}
                            </div>
                            <span className={`font-medium ${isDone ? "text-emerald-700" : isActive ? "text-blue-700" : isErr ? "text-red-600" : "text-slate-400"}`}>
                              {step.name}
                            </span>
                            {isDone && step.durationMs != null && step.durationMs > 0 && (
                              <span className="text-[10px] font-mono text-emerald-500 ml-auto">{step.durationMs}ms</span>
                            )}
                            {isActive && <span className="text-[10px] text-blue-500 ml-auto animate-pulse">running</span>}
                          </div>
                        );
                      })}
                    </div>
                    {/* Progress bar */}
                    <div className="px-3 pb-2.5 pt-1">
                      <div className="relative h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div className="absolute h-full bg-gradient-to-r from-blue-500 via-indigo-500 to-emerald-500 rounded-full transition-all duration-700 ease-out"
                          style={{ width: `${progressPct}%` }} />
                      </div>
                      <div className="flex items-center justify-between mt-1.5">
                        <span className="text-[10px] text-slate-400">{completedCount} of {agentSteps.length} phases</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Loading indicator */}
              {chatMutation.isPending && !isStreaming && !agentSteps.some(s => s.status !== "pending") && (
                <div className="flex gap-3 justify-start">
                  <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center border border-blue-200">
                    <Bot className="h-4 w-4 text-blue-500" />
                  </div>
                  <div className="rounded-xl bg-white border border-slate-200 shadow-sm px-4 py-3 flex items-center gap-3">
                    <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                    <span className="text-sm text-slate-500">{loadingMessage || "Connecting to AI..."}</span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Scroll FAB */}
          {showScrollBtn && (
            <Button onClick={() => scrollToBottom()} size="icon"
              className="absolute bottom-24 right-6 h-9 w-9 rounded-full shadow-lg bg-blue-600 hover:bg-blue-500 transition-all hover:scale-110 z-50">
              <ArrowDown className="h-4 w-4 text-white" />
            </Button>
          )}
        </div>

        {/* ══════════ INPUT AREA — white with subtle border ══════════ */}
        <div className="flex-shrink-0 border-t border-slate-200 bg-white">
          <div className="max-w-4xl mx-auto px-5 py-3 space-y-2.5">

            {/* Vendor selection */}
            {pendingVendor && pendingVendor.options.length > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 space-y-3">
                <div className="flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                  <p className="text-sm font-semibold text-amber-800">Select a vendor to continue</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {pendingVendor.options.map(opt => (
                    <button key={opt.name} disabled={chatMutation.isPending}
                      onClick={() => setSelectedVendorOpt(opt.name)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                        selectedVendorOpt === opt.name
                          ? "border-amber-400 bg-amber-200 text-amber-900"
                          : "border-slate-200 bg-white text-slate-600 hover:bg-amber-50"
                      }`}>
                      {opt.name}{typeof opt.score === "number" ? ` (${opt.score})` : ""}
                    </button>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input value={vendorNote} onChange={e => setVendorNote(e.target.value)} disabled={chatMutation.isPending}
                    placeholder="Add reason (optional)"
                    className="flex-1 h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 placeholder:text-slate-400 focus:outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-200" />
                  <Button disabled={!selectedVendorOpt || chatMutation.isPending} size="sm"
                    onClick={() => handleVendorSelection(selectedVendorOpt, vendorNote.trim() || undefined)}
                    className="h-9 bg-amber-600 hover:bg-amber-500 text-white">
                    Confirm
                  </Button>
                </div>
              </div>
            )}

            {/* Department selection */}
            {pendingDept && (
              <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 space-y-2.5">
                <div className="flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                  <p className="text-sm font-semibold text-blue-800">
                    {pendingDept.context === "pr_creation" ? "Select department for this purchase request" : "Select department for budget verification"}
                  </p>
                </div>
                <div className="flex gap-2">
                  <select value={pendingDept.selectedDepartment}
                    onChange={e => setPendingDept(prev => prev ? { ...prev, selectedDepartment: e.target.value } : prev)}
                    disabled={chatMutation.isPending}
                    className="flex-1 h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-200">
                    {pendingDept.options.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                  <Button disabled={chatMutation.isPending} onClick={handleConfirmDepartment} size="sm"
                    className="h-9 bg-blue-600 hover:bg-blue-500 text-white">Continue</Button>
                  <Button variant="ghost" size="sm" disabled={chatMutation.isPending} onClick={() => setPendingDept(null)}
                    className="h-9 text-slate-500 hover:text-slate-700 hover:bg-slate-100">Cancel</Button>
                </div>
              </div>
            )}

            {/* Agent mode row */}
            <div className="flex items-center gap-2">
              <button onClick={() => setIsAgentModeOpen(prev => !prev)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold border border-slate-200 bg-white text-slate-500 hover:bg-blue-50 hover:text-blue-600 hover:border-blue-200 transition-all shadow-sm">
                <Bot className="h-3 w-3" />
                {selectedAgentMeta?.name || "Auto Routing"}
                {isAgentModeOpen ? <ChevronUp className="h-3 w-3 ml-0.5" /> : <ChevronDown className="h-3 w-3 ml-0.5" />}
              </button>
              {isStreaming && (
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-100 border border-blue-200">
                  <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                  <span className="text-[10px] font-semibold text-blue-600 uppercase tracking-wider">Streaming</span>
                </div>
              )}
            </div>

            {/* Agent mode dropdown */}
            {isAgentModeOpen && (
              <div className="rounded-xl border border-slate-200 bg-white p-3 space-y-2 shadow-lg animate-in fade-in slide-in-from-bottom-2 duration-200">
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 px-1">Agent Selection</p>
                <div className="grid grid-cols-2 gap-1.5 md:grid-cols-3 xl:grid-cols-4">
                  {agentModeOptions.map(agent => {
                    const Icon = getAgentIcon(agent.type);
                    const active = selectedAgentType === agent.type;
                    return (
                      <button key={agent.type} type="button" onClick={() => handleAgentModeSelect(agent.type)}
                        className={`rounded-lg px-3 py-2 text-left transition-all ${
                          active
                            ? "bg-blue-100 border border-blue-300 text-blue-700"
                            : "bg-slate-50 border border-slate-200 text-slate-600 hover:bg-blue-50 hover:text-blue-600 hover:border-blue-200"
                        }`}>
                        <div className="flex items-center gap-2">
                          <Icon className={`h-3.5 w-3.5 ${active ? "text-blue-500" : "text-slate-400"}`} />
                          <span className="truncate text-[11px] font-semibold">{agent.name}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Input row */}
            <div className="flex gap-2 items-end">
              <div className="flex-1 relative">
                <Textarea value={input} onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about budgets, vendors, approvals, risk..."
                  className="min-h-[48px] max-h-28 resize-none rounded-xl border border-slate-200 bg-white text-slate-700 placeholder:text-slate-400 focus:border-blue-400 focus:ring-1 focus:ring-blue-200 pr-4 text-[14px]"
                />
              </div>
              <Button onClick={handleSend} disabled={!input.trim() || chatMutation.isPending}
                className="h-12 w-12 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-slate-200 disabled:text-slate-400 shadow-md transition-all hover:scale-105">
                {chatMutation.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
