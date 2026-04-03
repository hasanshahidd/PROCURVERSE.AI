/**
 * Pipeline Runner Hook
 * Orchestrates 16-step animation with realistic timing
 */

import { useEffect, useRef } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { apiFetch } from '@/lib/api';
import type { QueryType, PRData, PipelineState } from '../types/pipeline';

interface RunPipelineOptions {
  useBackend?: boolean;
}

export function usePipelineRunner() {
  const store = usePipelineStore();
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const runStep = async (stepId: number) => {
    const step = store.steps.find(s => s.id === stepId);
    if (!step) return;

    // Calculate scaled timing
    const scaledMs = step.baseMs * store.speedMultiplier;
    const delay = stepId === 1 ? 0 : scaledMs - (store.steps[stepId - 2]?.baseMs || 0) * store.speedMultiplier;

    return new Promise<void>((resolve) => {
      timeoutRef.current = setTimeout(() => {
        // Activate step
        const detailLine = generateDetailLine(stepId, store.queryType, store.prData);
        store.advanceStep(stepId, detailLine);
        
        // Add log entry
        store.addLog(step.category, `${step.name}`, step.baseMs);
        
        // Highlight weak points
        store.highlightWeakPoint(stepId);
        
        // Special actions per step
        executeStepAction(stepId, store);
        
        // Complete step after brief active time
        setTimeout(() => {
          store.completeStep(stepId);
          resolve();
        }, 300); // 300ms active state
        
      }, delay);
    });
  };

  const runPipeline = async (
    queryText: string,
    queryType: QueryType,
    prData?: PRData,
    options: RunPipelineOptions = {}
  ) => {
    const useBackend = options.useBackend ?? true;

    // Reset and start
    store.startPipeline(queryText, queryType, prData);
    startTimeRef.current = Date.now();

    // Run animation and API call in parallel
    const [_, apiResult] = await Promise.all([
      // Animation: Run all 16 steps
      (async () => {
        for (let i = 1; i <= 16; i++) {
          await runStep(i);
        }
      })(),
      
      // Optional real API call
      useBackend
        ? callAgenticEndpoint(queryText, queryType, prData).catch(error => {
            console.error('Backend offline, using demo mode:', error);
            store.addLog('FASTAPI', '🟡 Demo mode - backend offline', 0);
            return null; // Fallback to mock data
          })
        : Promise.resolve(null)
    ]);

    // Set final result after completion only in full mode
    setTimeout(() => {
      if (useBackend) {
        if (apiResult) {
          // Use real API data
          store.setResult(mapApiResultToStore(apiResult, queryType));
        } else {
          // Fallback to mock data
          store.setResult(generateMockResult(queryType, store.prData));
        }
      }
    }, 500);
  };

  // Call real backend API
  const callAgenticEndpoint = async (queryText: string, queryType: QueryType, prData?: PRData) => {
    const response = await apiFetch('/api/agentic/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: queryText,
        session_id: `session_${Date.now()}`,
        pr_data: prData || {}
      })
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return await response.json();
  };

  // Map real API response to store format
  const mapApiResultToStore = (apiResult: any, queryType: QueryType) => {
    const result = apiResult.result || apiResult;
    
    return {
      agent: apiResult.agent || getAgentForType(queryType),
      confidence: apiResult.confidence || 0.95,
      executionTimeMs: apiResult.execution_time_ms || 120,
      totalTimeMs: apiResult.total_time_ms || 150,
      verdict: result.action || result.verdict || "COMPLETED",
      score: result.score ? {
        total: result.score,
        subscores: result.subscores || {}
      } : undefined,
      findings: [
        ...(result.violations || []).map((v: string) => ({ severity: "error" as const, message: v })),
        ...(result.warnings || []).map((w: string) => ({ severity: "warning" as const, message: w })),
        ...(result.successes || []).map((s: string) => ({ severity: "success" as const, message: s })),
        ...(result.info || []).map((i: string) => ({ severity: "info" as const, message: i }))
      ]
    };
  };

  return {
    runPipeline,
    isRunning: store.status === "running",
    reset: store.reset,
  };
}

// Generate realistic detail lines for each step
function generateDetailLine(stepId: number, queryType: QueryType, prData: PRData): string {
  switch (stepId) {
    case 1:
      return `query="${prData.department || 'IT'}" budget=${prData.budget || 5000}`;
    case 3:
      return `request_id: req_${Math.random().toString(36).slice(2, 8)}`;
    case 5:
      return `lang=en - translation skipped`;
    case 6:
      return `type:${queryType} conf:0.95`;
    case 7:
      return `routing -> ${getAgentForType(queryType)}`;
    case 8:
      return `dept=${prData.department || 'IT'} budget=${prData.budget || 5000}`;
    case 9:
      return `LangChain executor + GPT-4o plan: 3 tool calls`;
    case 10:
      return `get_approval_chain -> 1 row returned`;
    case 11:
      return `check_budget -> $${(prData.budget || 5000).toLocaleString()} available`;
    case 12:
      return `get_vendors -> 47 vendors`;
    case 13:
      return queryType === "COMPLIANCE" ? `score=55/100 MAJOR_VIOLATION` : `action complete`;
    case 14:
      return `_log_action() -> agent_actions #${91 + Math.floor(Math.random() * 10)}`;
    case 15:
      return `GPT-4o explanation generated`;
    case 16:
      return `2847 bytes - 120ms total`;
    default:
      return "";
  }
}

// Execute special actions for specific steps
function executeStepAction(stepId: number, store: PipelineState) {
  switch (stepId) {
    case 7: // Agent selected
      const agentName = getAgentForType(store.queryType);
      store.selectAgent(agentName, 0.95);
      break;
      
    case 8: // OBSERVE phase
      store.activatePhase("OBSERVE");
      break;
      
    case 9: // DECIDE phase
      store.activatePhase("DECIDE");
      break;
      
    case 10: // ACT phase starts with tool calls
      store.activatePhase("ACT");
      store.addToolCall({
        source: "PostgreSQL",
        name: "get_approval_chain",
      });
      setTimeout(() => {
        const toolId = store.toolCalls[0]?.id;
        if (toolId) store.completeToolCall(toolId, "1 row returned");
      }, 200);
      break;
      
    case 11: // PostgreSQL query 2
      store.addToolCall({
        source: "PostgreSQL",
        name: "check_budget_availability",
      });
      setTimeout(() => {
        const toolId = store.toolCalls[1]?.id;
        if (toolId) store.completeToolCall(toolId, `$${(store.prData.budget || 5000).toLocaleString()} available`);
      }, 200);
      break;
      
    case 12: // Odoo XML-RPC
      store.addToolCall({
        source: "Odoo",
        name: "get_vendors",
        model: "res.partner",
      });
      setTimeout(() => {
        const toolId = store.toolCalls[2]?.id;
        if (toolId) store.completeToolCall(toolId, "47 vendors");
      }, 200);
      break;
      
    case 14: // LEARN phase
      store.activatePhase("LEARN");
      break;
  }
}

// Map query type to agent name
function getAgentForType(queryType: QueryType): string {
  switch (queryType) {
    case "COMPLIANCE": return "ComplianceCheckAgent";
    case "VENDOR": return "VendorSelectionAgent";
    case "BUDGET": return "BudgetAnalysisAgent";
    case "RISK": return "RiskAssessmentAgent";
    case "APPROVAL": return "ApprovalWorkflowAgent";
  }
}

// Generate mock result for demo mode
function generateMockResult(queryType: QueryType, prData: PRData) {
  const baseResult = {
    agent: getAgentForType(queryType),
    confidence: 0.95,
    executionTimeMs: 91,
    totalTimeMs: 120,
  };

  switch (queryType) {
    case "COMPLIANCE":
      return {
        ...baseResult,
        verdict: "MAJOR_VIOLATION" as const,
        score: {
          total: 55,
          subscores: { policy: 40, budget: 15, approval: 0 },
        },
        findings: [
          { severity: "error" as const, message: "No approval chain defined for IT department" },
          { severity: "warning" as const, message: "Budget exceeds department threshold ($5,000 > $1,000)" },
          { severity: "success" as const, message: "Vendor is on preferred supplier list" },
          { severity: "info" as const, message: "Purchase falls under CAPEX category" },
        ],
      };
      
    case "BUDGET":
      return {
        ...baseResult,
        verdict: "ANALYSIS_COMPLETE" as const,
        score: {
          total: 85,
          subscores: { policy: 90, budget: 80, approval: 85 },
        },
        findings: [
          { severity: "success" as const, message: "Budget utilization: 67% across all departments" },
          { severity: "warning" as const, message: "IT department approaching 80% threshold" },
          { severity: "info" as const, message: "Q4 forecast: $2.3M total procurement spend" },
        ],
      };
      
    case "VENDOR":
      return {
        ...baseResult,
        verdict: "SUCCESS" as const,
        findings: [
          { severity: "success" as const, message: "Found 3 qualified vendors for office furniture" },
          { severity: "info" as const, message: "Top vendor: Premium Office Solutions (score: 92/100)" },
          { severity: "info" as const, message: "Average delivery time: 5-7 business days" },
        ],
      };
      
    case "RISK":
      return {
        ...baseResult,
        verdict: "HIGH_RISK" as const,
        score: {
          total: 75,
          subscores: { policy: 85, budget: 70, approval: 70 },
        },
        findings: [
          { severity: "error" as const, message: "Single-source vendor risk detected" },
          { severity: "warning" as const, message: "Vendor has no performance history in system" },
          { severity: "info" as const, message: "PO value: $125,000 (High value transaction)" },
        ],
      };
      
    case "APPROVAL":
      return {
        ...baseResult,
        verdict: "SUCCESS" as const,
        findings: [
          { severity: "success" as const, message: "3-level approval chain created" },
          { severity: "info" as const, message: "Manager → Director → VP/CFO" },
          { severity: "info" as const, message: "Estimated approval time: 2-3 business days" },
        ],
      };
  }
}
