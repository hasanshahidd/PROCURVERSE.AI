/**
 * Pipeline Side Panel - Sliding panel showing real-time pipeline execution
 * Slides in from right (420px) when query runs, closes when idle
 */

import { motion, AnimatePresence } from 'framer-motion';
import { X, CheckCircle, Loader2, Circle, Search, Lightbulb, Cog, ClipboardCheck } from 'lucide-react';
import { useEffect, useMemo, useRef } from 'react';
import { usePipelineStore } from '../store/pipelineStore';

interface PipelineSidePanelProps {
  isOpen: boolean;
  onClose: () => void;
  variant?: 'side' | 'inline';
}

export function PipelineSidePanel({ isOpen, onClose, variant = 'side' }: PipelineSidePanelProps) {
  const { steps, agents, agentExecutions, baseAgentPhases, toolCalls, logs, result, status } = usePipelineStore();
  const isInline = variant === 'inline';
  const contentRef = useRef<HTMLDivElement | null>(null);
  const logsRef = useRef<HTMLDivElement | null>(null);

  const activeStepId = useMemo(() => {
    const active = steps.find((step) => step.status === 'active');
    return active?.id;
  }, [steps]);

  const activeAgentName = useMemo(() => {
    const active = agentExecutions.find((agent) => agent.status === 'active');
    return active?.name;
  }, [agentExecutions]);

  useEffect(() => {
    if (!activeStepId) return;

    // Keep the currently active pipeline step visible while processing.
    const el = document.getElementById(`pipeline-step-${activeStepId}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [activeStepId]);

  useEffect(() => {
    if (!activeAgentName) return;

    const el = document.getElementById(`pipeline-agent-${activeAgentName}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [activeAgentName]);

  useEffect(() => {
    if (!logsRef.current) return;

    // Keep live logs pinned to the latest update.
    logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs.length]);

  const containerClass = isInline
    ? 'w-full max-h-[52vh] rounded-2xl bg-card border border-border shadow-sm overflow-hidden flex flex-col'
    : 'fixed right-0 top-0 h-full w-[420px] bg-gradient-to-b from-blue-50 to-blue-100 dark:from-slate-800 dark:to-slate-900/95 shadow-2xl z-50 overflow-hidden flex flex-col border-l border-blue-200 dark:border-slate-700';

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={isInline ? { y: 12, opacity: 0 } : { x: 420, opacity: 0 }}
          animate={isInline ? { y: 0, opacity: 1 } : { x: 0, opacity: 1 }}
          exit={isInline ? { y: 12, opacity: 0 } : { x: 420, opacity: 0 }}
          transition={{ type: 'spring', damping: 25, stiffness: 200 }}
          className={containerClass}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-border">
            <div>
              <h2 className="text-lg font-semibold text-foreground">Request Progress</h2>
              <p className="text-sm text-muted-foreground">
                {steps.filter(s => s.status === 'complete').length}/{steps.length} steps complete
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-muted rounded-lg transition-colors"
            >
              <X className="w-5 h-5 text-muted-foreground" />
            </button>
          </div>

          {/* Scrollable Content */}
          <div ref={contentRef} className="flex-1 overflow-y-auto">
            {/* Progress Bar */}
            <div className="p-4 border-b border-border">
              <div className="w-full bg-muted rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full transition-all duration-300"
                  style={{ width: `${(steps.filter(s => s.status === 'complete').length / Math.max(steps.length, 1)) * 100}%` }}
                />
              </div>
            </div>

            {/* Pipeline Steps */}
            <div className="p-4 space-y-2">
              <h3 className="text-sm font-semibold text-foreground mb-3">What is happening now</h3>
              {steps.map((step) => (
                <motion.div
                  key={step.id}
                  id={`pipeline-step-${step.id}`}
                  layout
                  className={`flex items-start gap-3 p-3 rounded-lg transition-colors ${
                    step.status === 'active' ? 'bg-blue-500/20 border border-blue-400' :
                    step.status === 'complete' ? 'bg-emerald-500/5 dark:bg-emerald-900/20 border border-emerald-500/10' :
                    'bg-muted/30 dark:bg-muted/10'
                  }`}
                >
                  <div className="flex-shrink-0 mt-0.5">
                    {step.status === 'complete' && <CheckCircle className="w-5 h-5 text-green-500" />}
                    {step.status === 'active' && <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />}
                    {(step.status === 'idle' || step.status === 'error') && <Circle className="w-5 h-5 text-gray-400" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${getCategoryColor(step.category)}`}>
                        {getCategoryLabel(step.category)}
                      </span>
                      {step.status === 'complete' && (
                        <span className="text-xs text-muted-foreground">{step.durationMs ?? step.baseMs}ms</span>
                      )}
                    </div>
                    <p className="text-sm font-semibold text-foreground mt-1">{step.name}</p>
                    {step.detailLine && (
                      <p className="text-xs text-muted-foreground mt-1">{toFriendlyDetail(step.detailLine)}</p>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>

            {/* Agent Workstreams */}
            {(agentExecutions.length > 0 || agents.some(a => a.isSelected)) && (
              <div className="p-4 border-t border-border">
                <h3 className="text-sm font-semibold text-foreground mb-3">Selected Agents</h3>
                <div className="space-y-2">
                  {(agentExecutions.length > 0
                    ? agentExecutions
                    : agents.filter(a => a.isSelected).map(a => ({
                        name: a.name,
                        status: 'active' as const,
                        currentPhase: undefined,
                        lastMessage: 'Selected for this workflow',
                        confidence: a.confidence,
                        phases: { OBSERVE: 'idle', DECIDE: 'idle', ACT: 'idle', LEARN: 'idle' } as const,
                      }))
                  ).map((agent) => (
                    <motion.div
                      key={agent.name}
                      id={`pipeline-agent-${agent.name}`}
                      initial={{ scale: 0.9, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      className={`p-3 border rounded-lg ${agent.status === 'active'
                        ? 'bg-blue-50 dark:bg-blue-500/10 border-blue-200 dark:border-blue-500/40'
                        : agent.status === 'complete'
                          ? 'bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/30'
                          : agent.status === 'error'
                            ? 'bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30'
                            : 'bg-muted/30 border-border'
                        }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-foreground truncate">{agent.name}</span>
                        <div className="flex items-center gap-2">
                          {agent.confidence !== undefined && (
                            <span className="text-[11px] text-muted-foreground">{(agent.confidence * 100).toFixed(0)}%</span>
                          )}
                          <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${getExecutionStatusClass(agent.status)}`}>
                            {agent.status}
                          </span>
                        </div>
                      </div>
                      {agent.lastMessage && (
                        <p className="text-xs text-muted-foreground mt-1">{toFriendlyDetail(agent.lastMessage)}</p>
                      )}
                      <div className="mt-2 grid grid-cols-4 gap-1">
                        {(['OBSERVE', 'DECIDE', 'ACT', 'LEARN'] as const).map((phase) => (
                          <div
                            key={`${agent.name}-${phase}`}
                            className={`text-[10px] px-1.5 py-1 rounded text-center font-medium ${getPhaseStatusClass(agent.phases?.[phase] || 'idle')}`}
                          >
                            {phase}
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  ))}
                </div>
              </div>
            )}

            {/* BaseAgent Phases */}
            {baseAgentPhases.some(p => p.status !== 'idle') && (
              <div className="p-4 border-t border-border">
                <h3 className="text-sm font-semibold text-foreground mb-3">Process Stages</h3>
                <div className="grid grid-cols-2 gap-2">
                  {baseAgentPhases.map((phase) => (
                    <motion.div
                      key={phase.phase}
                      layout
                      className={`p-3 rounded-lg border transition-all ${
                        phase.status === 'active' ? 'bg-green-500/10 border-green-500/30 scale-105' :
                        phase.status === 'complete' ? 'bg-emerald-500/5 border-emerald-500/20' :
                        'bg-muted/20 border-border/50'
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        {getPhaseIcon(phase.phase)}
                        <div className="text-xs font-semibold text-foreground">{phase.phase}</div>
                        <div className={`ml-auto text-[10px] px-1.5 py-0.5 rounded-full ${getPhaseStatusClass(phase.status)}`}>
                          {phase.status}
                        </div>
                      </div>
                      <div className="text-[11px] text-muted-foreground line-clamp-2">
                        {phase.content || getDefaultPhaseDescription(phase.phase)}
                      </div>
                    </motion.div>
                  ))}
                </div>
              </div>
            )}

            {/* Tool Calls */}
            {toolCalls.length > 0 && (
              <div className="p-4 border-t border-border">
                <h3 className="text-sm font-semibold text-foreground mb-3">Data Sources Used</h3>
                <div className="space-y-3">
                  {/* PostgreSQL Tools */}
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-2">Business records database</div>
                    {toolCalls.filter(t => t.source === 'PostgreSQL').map((tool) => (
                      <div key={tool.id} className="flex items-center gap-2 text-sm p-2 bg-teal-500/5 dark:bg-teal-900/20 border border-teal-500/10 rounded mb-1">
                        <span className="flex-1 text-foreground truncate text-xs">{tool.name}</span>
                        {tool.status === 'complete' ? (
                          <span className="text-xs text-emerald-400">{tool.result}</span>
                        ) : (
                          <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Odoo Tools */}
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-2">ERP system checks</div>
                    {toolCalls.filter(t => t.source === 'Odoo').map((tool) => (
                      <div key={tool.id} className="flex items-center gap-2 text-sm p-2 bg-amber-500/5 dark:bg-amber-900/20 border border-amber-500/10 rounded mb-1">
                        <span className="flex-1 text-foreground truncate text-xs">{tool.name}</span>
                        {tool.status === 'complete' ? (
                          <span className="text-xs text-green-400">{tool.result}</span>
                        ) : (
                          <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Live Logs */}
            {logs.length > 0 && (
              <div className="p-4 border-t border-border">
                <h3 className="text-sm font-semibold text-foreground mb-3">Live Updates</h3>
                <div ref={logsRef} className="space-y-1 max-h-64 overflow-y-auto text-xs">
                  <AnimatePresence>
                    {logs.slice(-20).map((log) => (
                      <motion.div
                        key={log.id}
                        initial={{ x: -10, opacity: 0 }}
                        animate={{ x: 0, opacity: 1 }}
                        className="flex items-start gap-2"
                      >
                        <span className={`${getCategoryTextColor(log.category)} whitespace-nowrap`}>
                          [{getCategoryLabel(log.category)}]
                        </span>
                        <span className="text-muted-foreground flex-1">{toFriendlyDetail(log.message)}</span>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              </div>
            )}

            {/* Result Summary */}
            {status === 'done' && result && (
              <div className="p-4 border-t border-border">
                <h3 className="text-sm font-semibold text-foreground mb-3">Result</h3>
                <div className="space-y-3">
                  <div className={`px-3 py-2 rounded-lg font-semibold text-center ${
                    result.verdict.includes('APPROVED') || result.verdict.includes('SUCCESS') ? 'bg-green-500/20 text-green-400' :
                    result.verdict.includes('VIOLATION') || result.verdict.includes('REJECTED') ? 'bg-red-500/20 text-red-400' :
                    'bg-amber-500/20 text-amber-400'
                  }`}>
                    {result.verdict}
                  </div>
                  
                  {result.score && (
                    <div>
                      <div className="flex justify-between text-xs text-foreground/70 mb-1">
                        <span>Score</span>
                        <span>{result.score.total}/100</span>
                      </div>
                      <div className="w-full bg-muted rounded-full h-2">
                        <div
                          className={`h-2 rounded-full ${
                            result.score.total >= 70 ? 'bg-green-500' :
                            result.score.total >= 50 ? 'bg-amber-500' :
                            'bg-red-500'
                          }`}
                          style={{ width: `${result.score.total}%` }}
                        />
                      </div>
                    </div>
                  )}

                  <div className="space-y-1">
                    {result.findings.slice(0, 3).map((finding, idx) => (
                      <div key={idx} className={`text-xs flex items-start gap-2 ${
                        finding.severity === 'error' ? 'text-red-400' :
                        finding.severity === 'warning' ? 'text-amber-400' :
                        finding.severity === 'success' ? 'text-green-400' :
                        'text-blue-400'
                      }`}>
                        <span className="mt-0.5">
                          {finding.severity === 'error' ? '🔴' :
                           finding.severity === 'warning' ? '🟡' :
                           finding.severity === 'success' ? '🟢' : '🔵'}
                        </span>
                        <span>{finding.message}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// Helper functions
function getCategoryColor(category: string): string {
  const colors: Record<string, string> = {
    FRONTEND: 'bg-blue-500/20 text-blue-300',
    FASTAPI: 'bg-amber-500/20 text-amber-300',
    TRANSLATE: 'bg-green-500/20 text-green-300',
    CLASSIFY: 'bg-violet-500/20 text-violet-300',
    ORCHESTRATE: 'bg-indigo-500/20 text-indigo-300',
    BASEAGENT: 'bg-orange-500/20 text-orange-300',
    TOOL: 'bg-teal-500/20 text-teal-300',
    FORMAT: 'bg-purple-500/20 text-purple-300',
  };
  return colors[category] || 'bg-gray-500/20 text-gray-300';
}

function getCategoryLabel(category: string): string {
  const labels: Record<string, string> = {
    FRONTEND: 'App',
    FASTAPI: 'Server',
    TRANSLATE: 'Language',
    CLASSIFY: 'Intent',
    ORCHESTRATE: 'Routing',
    BASEAGENT: 'Decision',
    TOOL: 'Data',
    FORMAT: 'Response',
    SYSTEM: 'System',
  };
  return labels[category] || category;
}

function toFriendlyDetail(text?: string): string {
  if (!text) return '';

  return text
    .replace(/request_id=\S+/gi, 'Request tracked')
    .replace(/lang=\w+\s+translation-check/gi, 'Language detected')
    .replace(/GPT-4o-mini/gi, 'AI model')
    .replace(/POST request dispatched/gi, 'Request sent')
    .replace(/Pydantic validation passed/gi, 'Input verified')
    .replace(/Tools:\s*/gi, 'Data checks: ')
    .replace(/agent_actions/gi, 'activity history');
}

function getCategoryTextColor(category: string): string {
  const colors: Record<string, string> = {
    FRONTEND: 'text-blue-300',
    FASTAPI: 'text-amber-300',
    TRANSLATE: 'text-green-300',
    CLASSIFY: 'text-violet-300',
    ORCHESTRATE: 'text-indigo-300',
    BASEAGENT: 'text-orange-300',
    TOOL: 'text-teal-300',
    FORMAT: 'text-purple-300',
    SYSTEM: 'text-yellow-300',
  };
  return colors[category] || 'text-gray-300';
}

function getExecutionStatusClass(status: string): string {
  if (status === 'active') return 'bg-blue-500/20 text-blue-500';
  if (status === 'complete') return 'bg-emerald-500/20 text-emerald-500';
  if (status === 'error') return 'bg-red-500/20 text-red-500';
  return 'bg-muted text-muted-foreground';
}

function getPhaseStatusClass(status: string): string {
  if (status === 'active') return 'bg-blue-500/20 text-blue-500';
  if (status === 'complete') return 'bg-emerald-500/20 text-emerald-500';
  if (status === 'error') return 'bg-red-500/20 text-red-500';
  return 'bg-muted text-muted-foreground';
}

function getPhaseIcon(phase: string) {
  const className = 'w-4 h-4 text-muted-foreground';
  if (phase === 'OBSERVE') return <Search className={className} />;
  if (phase === 'DECIDE') return <Lightbulb className={className} />;
  if (phase === 'ACT') return <Cog className={className} />;
  return <ClipboardCheck className={className} />;
}

function getDefaultPhaseDescription(phase: string): string {
  if (phase === 'OBSERVE') return 'Reading required context and records';
  if (phase === 'DECIDE') return 'Reasoning and action selection';
  if (phase === 'ACT') return 'Executing tools and workflow actions';
  return 'Recording outcomes for traceability';
}
