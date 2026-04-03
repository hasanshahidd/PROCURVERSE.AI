/**
 * Pipeline Visualizer Page
 * 16-Step Real-Time Execution Monitor
 * Three-panel layout: Query Input | Pipeline Steps | Live Logs
 */

import { useState } from 'react';
import { usePipelineStore } from '../store/pipelineStore';
import { usePipelineRunner } from '../hooks/usePipelineRunner';
import type { QueryType, PRData } from '../types/pipeline';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2,
  Loader2,
  Circle,
  X,
  Play,
  RotateCcw,
  Download,
  Zap,
  Clock,
  Gauge,
} from 'lucide-react';

export default function PipelineVisualizerPage() {
  const store = usePipelineStore();
  const { runPipeline, isRunning, reset } = usePipelineRunner();
  
  const [queryInput, setQueryInput] = useState("");
  const [selectedType, setSelectedType] = useState<QueryType>("COMPLIANCE");

  const handleSubmit = () => {
    if (!queryInput.trim() || isRunning) return;
    
    const prData: PRData = {
      department: "IT",
      budget: 5000,
      category: "CAPEX",
    };
    
    runPipeline(queryInput, selectedType, prData);
  };

  const handleQuickQuery = (type: QueryType, text: string) => {
    setSelectedType(type);
    setQueryInput(text);
    setTimeout(() => {
      const prData: PRData = {
        department: "IT",
        budget: type === "BUDGET" ? 50000 : 5000,
        category: "CAPEX",
      };
      runPipeline(text, type, prData);
    }, 100);
  };

  return (
    <div className="h-screen flex flex-col bg-slate-50">
      {/* Top Bar */}
      <header className="h-14 border-b bg-white flex items-center justify-between px-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-violet-600 rounded-lg flex items-center justify-center">
            <span className="text-white font-bold text-sm">PA</span>
          </div>
          <h1 className="text-lg font-semibold text-slate-900">Procurement AI Pipeline</h1>
          <Badge variant="outline" className="ml-2">
            16 Steps | 11 Agents | ~120ms
          </Badge>
        </div>
        
        <div className="flex items-center gap-4">
          {/* Animation Speed Control */}
          <div className="flex items-center gap-2">
            <Gauge className="w-4 h-4 text-slate-500" />
            <select
              value={store.animationSpeed}
              onChange={(e) => store.setAnimationSpeed(e.target.value as any)}
              className="text-sm border border-slate-200 rounded px-2 py-1"
              disabled={isRunning}
            >
              <option value="fast">Fast (1.2s)</option>
              <option value="normal">Normal (2.4s)</option>
              <option value="detailed">Detailed (4.8s)</option>
            </select>
          </div>
          
          {/* Progress */}
          {store.status !== "idle" && (
            <div className="flex items-center gap-2 text-sm">
              <Clock className="w-4 h-4 text-slate-500" />
              <span className="font-mono">{store.completedSteps.size}/16</span>
              <span className="text-slate-500">|</span>
              <span className="font-mono text-blue-600">{store.elapsed}ms</span>
            </div>
          )}
        </div>
      </header>

      {/* Three-Panel Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* LEFT PANEL - Query Input */}
        <aside className="w-80 bg-slate-900 text-white p-6 overflow-y-auto">
          <div className="space-y-6">
            {/* Query Input */}
            <div>
              <label className="block text-sm font-medium mb-2">Query</label>
              <Input
                value={queryInput}
                onChange={(e) => setQueryInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                placeholder="Enter your procurement query..."
                className="bg-slate-800 border-slate-700 text-white placeholder:text-slate-500"
                disabled={isRunning}
              />
            </div>

            {/* Query Type Selector */}
            <div>
              <label className="block text-sm font-medium mb-2">Query Type</label>
              <div className="grid grid-cols-2 gap-2">
                {(["COMPLIANCE", "VENDOR", "BUDGET", "RISK", "APPROVAL"] as QueryType[]).map((type) => (
                  <Button
                    key={type}
                    variant={selectedType === type ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSelectedType(type)}
                    disabled={isRunning}
                    className={selectedType === type ? "" : "bg-slate-800 border-slate-700 text-white hover:bg-slate-700"}
                  >
                    {type}
                  </Button>
                ))}
              </div>
            </div>

            {/* Submit Button */}
            <Button
              onClick={handleSubmit}
              disabled={!queryInput.trim() || isRunning}
              className="w-full"
              size="lg"
            >
              {isRunning ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Running Pipeline...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 mr-2" />
                  Execute Pipeline
                </>
              )}
            </Button>

            {/* Quick Queries */}
            <div>
              <label className="block text-sm font-medium mb-2">Quick Examples</label>
              <div className="space-y-2">
                <button
                  onClick={() => handleQuickQuery("COMPLIANCE", "Check compliance for IT $5,000 purchase")}
                  disabled={isRunning}
                  className="w-full text-left text-sm p-2 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-50 transition-colors"
                >
                  <span className="text-slate-400">Compliance:</span> IT $5K purchase check
                </button>
                <button
                  onClick={() => handleQuickQuery("BUDGET", "Analyze IT department Q4 budget")}
                  disabled={isRunning}
                  className="w-full text-left text-sm p-2 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-50 transition-colors"
                >
                  <span className="text-slate-400">Budget:</span> Q4 budget analysis
                </button>
                <button
                  onClick={() => handleQuickQuery("VENDOR", "Find vendors for office furniture under $20K")}
                  disabled={isRunning}
                  className="w-full text-left text-sm p-2 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-50 transition-colors"
                >
                  <span className="text-slate-400">Vendor:</span> Office furniture vendors
                </button>
              </div>
            </div>

            {/* Weak Points Summary */}
            <Card className="bg-slate-800 border-slate-700 p-4">
              <h3 className="text-sm font-medium mb-3">System Weak Points</h3>
              <div className="flex gap-2">
                <Badge variant="destructive" className="flex-1 justify-center">
                  3 HIGH
                </Badge>
                <Badge variant="outline" className="flex-1 justify-center bg-amber-500/10 border-amber-500 text-amber-400">
                  3 MEDIUM
                </Badge>
                <Badge variant="outline" className="flex-1 justify-center bg-slate-700 border-slate-600">
                  3 LOW
                </Badge>
              </div>
            </Card>
          </div>
        </aside>

        {/* CENTER PANEL - Pipeline Visualizer */}
        <main className="flex-1 overflow-y-auto p-6">
          <div className="max-w-5xl mx-auto space-y-6">
            {/* Progress Bar */}
            {store.status !== "idle" && (
              <Card className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">Pipeline Progress</span>
                  <span className="text-sm text-slate-600">
                    {store.completedSteps.size} / 16 steps
                  </span>
                </div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-gradient-to-r from-blue-500 to-violet-600"
                    initial={{ width: 0 }}
                    animate={{ width: `${(store.completedSteps.size / 16) * 100}%` }}
                    transition={{ duration: 0.3 }}
                  />
                </div>
              </Card>
            )}

            {/* Pipeline Steps */}
            <Card className="p-4">
              <h2 className="text-lg font-semibold mb-4">Execution Timeline</h2>
              <div className="space-y-1">
                <AnimatePresence mode="popLayout">
                  {store.steps.map((step) => (
                    <PipelineStepRow key={step.id} step={step} />
                  ))}
                </AnimatePresence>
              </div>
            </Card>

            {/* Orchestrator + Agents (shows at step 7) */}
            {store.activeStep >= 7 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
              >
                <Card className="p-4">
                  <h3 className="text-sm font-medium mb-3">Agent Selection</h3>
                  <div className="flex flex-wrap gap-2">
                    {store.agents.map((agent) => (
                      <Badge
                        key={agent.name}
                        variant={agent.isSelected ? "default" : "outline"}
                        className={`transition-all ${
                          agent.isSelected
                            ? "scale-105"
                            : "opacity-30"
                        }`}
                      >
                        {agent.name.replace("Agent", "")}
                        {agent.isSelected && agent.confidence && (
                          <span className="ml-1 text-xs">
                            ({Math.round(agent.confidence * 100)}%)
                          </span>
                        )}
                      </Badge>
                    ))}
                  </div>
                </Card>
              </motion.div>
            )}

            {/* BaseAgent Phases (shows at step 8+) */}
            {store.activeStep >= 8 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.1 }}
              >
                <Card className="p-4">
                  <h3 className="text-sm font-medium mb-3">BaseAgent Framework</h3>
                  <div className="grid grid-cols-4 gap-3">
                    {store.baseAgentPhases.map((phase) => (
                      <PhaseCard key={phase.phase} phase={phase} />
                    ))}
                  </div>
                </Card>
              </motion.div>
            )}

            {/* Tool Calls (shows during ACT phase) */}
            {store.toolCalls.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
              >
                <Card className="p-4">
                  <h3 className="text-sm font-medium mb-3">Tool Executions</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <h4 className="text-xs font-medium text-slate-600 mb-2">PostgreSQL (15%)</h4>
                      {store.toolCalls
                        .filter(t => t.source === "PostgreSQL")
                        .map(tool => <ToolCallRow key={tool.id} tool={tool} />)}
                    </div>
                    <div>
                      <h4 className="text-xs font-medium text-slate-600 mb-2">Odoo ERP (85%)</h4>
                      {store.toolCalls
                        .filter(t => t.source === "Odoo")
                        .map(tool => <ToolCallRow key={tool.id} tool={tool} />)}
                    </div>
                  </div>
                </Card>
              </motion.div>
            )}

            {/* Result Panel (shows when done) */}
            {store.result && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.5 }}
              >
                <ResultPanel result={store.result} onReset={reset} />
              </motion.div>
            )}
          </div>
        </main>

        {/* RIGHT PANEL - Live Log + Weak Points */}
        <aside className="w-80 border-l bg-slate-950 text-white overflow-y-auto">
          <LiveLogPanel />
          <WeakPointsInspector />
        </aside>
      </div>
    </div>
  );
}

// Sub-components defined inline for now (will extract later)

function PipelineStepRow({ step }: { step: any }) {
  const categoryColors: Record<string, string> = {
    FRONTEND: "bg-blue-100 text-blue-700",
    FASTAPI: "bg-amber-100 text-amber-700",
    TRANSLATE: "bg-green-100 text-green-700",
    CLASSIFY: "bg-violet-100 text-violet-700",
    ORCHESTRATE: "bg-slate-100 text-slate-700",
    BASEAGENT: "bg-orange-100 text-orange-700",
    TOOL: "bg-teal-100 text-teal-700",
    FORMAT: "bg-purple-100 text-purple-700",
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: step.status === "idle" ? 0.35 : 1, x: 0 }}
      className={`flex items-center gap-3 p-2.5 rounded-lg border ${
        step.status === "active" ? "border-l-4 border-l-blue-500 bg-blue-50" :
        step.status === "complete" ? "border-l-4 border-l-green-500" :
        "border-transparent"
      }`}
    >
      {/* Status Icon */}
      <div className="flex-shrink-0">
        {step.status === "complete" && <CheckCircle2 className="w-5 h-5 text-green-600" />}
        {step.status === "active" && <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />}
        {step.status === "idle" && <Circle className="w-5 h-5 text-slate-300" />}
      </div>

      {/* Step Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <Badge variant="outline" className={`text-xs ${categoryColors[step.category]}`}>
            {step.category}
          </Badge>
          <span className="text-sm font-medium">{step.id}. {step.name}</span>
        </div>
        <div className="text-xs text-slate-500 font-mono">{step.file}</div>
        {step.detailLine && (
          <div className="text-xs text-slate-600 font-mono mt-1">{step.detailLine}</div>
        )}
      </div>

      {/* Timing */}
      <div className="flex-shrink-0 text-sm font-mono text-slate-500">
        {step.baseMs}ms
      </div>
    </motion.div>
  );
}

function PhaseCard({ phase }: { phase: any }) {
  const icons: Record<string, React.ReactNode> = {
    OBSERVE: "🔍",
    DECIDE: "💡",
    ACT: "⚙️",
    LEARN: "📋",
  };

  return (
    <div
      className={`p-3 rounded-lg border-2 transition-all ${
        phase.status === "active"
          ? "border-orange-500 bg-orange-50 scale-105"
          : phase.status === "complete"
          ? "border-green-500 bg-green-50"
          : "border-slate-200 bg-white opacity-50"
      }`}
    >
      <div className="text-2xl mb-1">{icons[phase.phase]}</div>
      <div className="text-xs font-semibold">{phase.phase}</div>
    </div>
  );
}

function ToolCallRow({ tool }: { tool: any }) {
  return (
    <div className="text-xs p-2 bg-slate-800 rounded flex items-center justify-between mb-1">
      <span className="font-mono">{tool.name}</span>
      {tool.status === "complete" && (
        <span className="text-green-400">{tool.result}</span>
      )}
      {tool.status === "running" && (
        <Loader2 className="w-3 h-3 animate-spin text-blue-400" />
      )}
    </div>
  );
}

function LiveLogPanel() {
  const logs = usePipelineStore(s => s.logs);
  const categoryColors: Record<string, string> = {
    FRONTEND: "text-blue-400",
    FASTAPI: "text-amber-400",
    TRANSLATE: "text-green-400",
    CLASSIFY: "text-violet-400",
    ORCHESTRATE: "text-slate-400",
    BASEAGENT: "text-orange-400",
    TOOL: "text-teal-400",
    FORMAT: "text-purple-400",
  };

  return (
    <div className="p-4 border-b border-slate-800">
      <h3 className="text-sm font-medium mb-3">Live Log Stream</h3>
      <div className="space-y-1 font-mono text-xs max-h-80 overflow-y-auto">
        <AnimatePresence>
          {logs.map((log) => (
            <motion.div
              key={log.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex justify-between"
            >
              <span>
                <span className={categoryColors[log.category]}>[{log.category}]</span>{" "}
                {log.message}
              </span>
              <span className="text-slate-500">{log.ms}ms</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

function WeakPointsInspector() {
  const weakPoints = usePipelineStore(s => s.weakPoints);
  
  return (
    <div className="p-4">
      <h3 className="text-sm font-medium mb-3">Weak Points Inspector</h3>
      <div className="space-y-2">
        {weakPoints.map((wp) => (
          <div
            key={wp.id}
            className={`text-xs p-2 rounded border transition-all ${
              wp.isHighlighted
                ? "border-yellow-500 bg-yellow-500/10 animate-pulse"
                : "border-slate-800"
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <Badge
                variant={wp.severity === "HIGH" ? "destructive" : "outline"}
                className="text-xs"
              >
                {wp.severity}
              </Badge>
              <span className="font-medium">{wp.title}</span>
            </div>
            <div className="text-slate-500">Step {wp.triggeredAtStep}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResultPanel({ result, onReset }: { result: any; onReset: () => void }) {
  const verdictColors: Record<string, string> = {
    MAJOR_VIOLATION: "bg-red-100 text-red-700 border-red-300",
    SUCCESS: "bg-green-100 text-green-700 border-green-300",
    HIGH_RISK: "bg-red-100 text-red-700 border-red-300",
    ANALYSIS_COMPLETE: "bg-green-100 text-green-700 border-green-300",
  };

  const findingColors: Record<string, string> = {
    error: "bg-red-50 border-red-200 text-red-900",
    warning: "bg-amber-50 border-amber-200 text-amber-900",
    success: "bg-green-50 border-green-200 text-green-900",
    info: "bg-blue-50 border-blue-200 text-blue-900",
  };

  return (
    <Card className="p-6">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold mb-2">Pipeline Complete</h2>
          <div className="flex items-center gap-3">
            <Badge variant="outline">{result.agent}</Badge>
            <Badge variant="outline">{Math.round(result.confidence * 100)}% confidence</Badge>
            <span className="text-sm text-slate-600">
              {result.executionTimeMs}ms agent / {result.totalTimeMs}ms total
            </span>
          </div>
        </div>
        <Badge className={`text-lg px-4 py-2 ${verdictColors[result.verdict]}`}>
          {result.verdict.replace(/_/g, " ")}
        </Badge>
      </div>

      {/* Score (if present) */}
      {result.score && (
        <div className="mb-6">
          <h3 className="text-lg font-semibold mb-2">Score: {result.score.total}/100</h3>
          <div className="h-8 bg-slate-100 rounded-full overflow-hidden flex">
            {result.score.subscores.policy && (
              <div
                className="bg-blue-500 flex items-center justify-center text-xs text-white font-medium"
                style={{ width: `${result.score.subscores.policy}%` }}
              >
                Policy: {result.score.subscores.policy}
              </div>
            )}
            {result.score.subscores.budget && (
              <div
                className="bg-green-500 flex items-center justify-center text-xs text-white font-medium"
                style={{ width: `${result.score.subscores.budget}%` }}
              >
                Budget: {result.score.subscores.budget}
              </div>
            )}
            {result.score.subscores.approval !== undefined && (
              <div
                className="bg-purple-500 flex items-center justify-center text-xs text-white font-medium"
                style={{ width: `${result.score.subscores.approval}%` }}
              >
                Approval: {result.score.subscores.approval}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Findings */}
      <div className="mb-6">
        <h3 className="text-lg font-semibold mb-3">Findings</h3>
        <div className="space-y-2">
          {result.findings.map((finding: any, i: number) => (
            <div
              key={i}
              className={`p-3 rounded-lg border ${findingColors[finding.severity]}`}
            >
              {finding.message}
            </div>
          ))}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3">
        <Button onClick={onReset} variant="default" className="flex-1">
          <RotateCcw className="w-4 h-4 mr-2" />
          New Query
        </Button>
        <Button variant="outline" className="flex-1">
          <Download className="w-4 h-4 mr-2" />
          Export Report
        </Button>
      </div>
    </Card>
  );
}
