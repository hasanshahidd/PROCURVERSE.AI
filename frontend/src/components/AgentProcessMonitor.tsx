import { useEffect, useState } from 'react';
import { Activity, Loader2, CheckCircle2, AlertCircle, Zap, Database, Brain, Trophy, Clock, Wrench } from 'lucide-react';

interface AgentStep {
  id: string;
  name: string;
  status: 'pending' | 'active' | 'complete' | 'error';
  message: string;
  agent?: string;
}

interface PhaseData {
  [key: string]: any;
}

interface AgentProcessMonitorProps {
  isActive: boolean;
  currentAgent: string;
  agentSteps: AgentStep[];
  phaseDetails: PhaseData;
}

export function AgentProcessMonitor({
  isActive,
  currentAgent,
  agentSteps,
  phaseDetails
}: AgentProcessMonitorProps) {
  const [expandedPhase, setExpandedPhase] = useState<string | null>(null);
  const [processStartTime, setProcessStartTime] = useState<number | null>(null);
  const [elapsedTime, setElapsedTime] = useState(0);

  useEffect(() => {
    if (isActive && !processStartTime) {
      setProcessStartTime(Date.now());
    }
    if (!isActive) {
      setProcessStartTime(null);
      setElapsedTime(0);
    }
  }, [isActive]);

  useEffect(() => {
    if (!processStartTime) return;
    
    const interval = setInterval(() => {
      setElapsedTime(Date.now() - processStartTime);
    }, 100);

    return () => clearInterval(interval);
  }, [processStartTime]);

  if (!isActive && agentSteps.length === 0) return null;

  const completedSteps = agentSteps.filter(s => s.status === 'complete').length;
  const activeStep = agentSteps.find(s => s.status === 'active');
  const progressPercent = (completedSteps / agentSteps.length) * 100;

  return (
    <div className="fixed right-4 top-20 w-96 max-h-[calc(100vh-6rem)] overflow-y-auto z-50 
                    bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900 
                    rounded-2xl shadow-2xl border-2 border-blue-400/30 backdrop-blur-xl">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-gradient-to-r from-blue-600 to-purple-600 p-6 rounded-t-2xl border-b-2 border-blue-400/30">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="relative">
              <Activity className="h-10 w-10 text-white" />
              {isActive && (
                <span className="absolute -top-1 -right-1 flex h-4 w-4">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-4 w-4 bg-white"></span>
                </span>
              )}
            </div>
            <div>
              <h3 className="text-xl font-bold text-white">Agent Monitor</h3>
              <p className="text-blue-100 text-sm">Real-time Processing</p>
            </div>
          </div>
          <div className="text-right">
            <div className="text-2xl font-mono font-bold text-white">{(elapsedTime / 1000).toFixed(1)}s</div>
            <div className="text-blue-100 text-xs">Elapsed</div>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="space-y-2">
          <div className="flex justify-between text-white text-sm font-medium">
            <span>{completedSteps} / {agentSteps.length} Steps</span>
            <span>{Math.round(progressPercent)}%</span>
          </div>
          <div className="h-3 bg-white/20 rounded-full overflow-hidden backdrop-blur-sm">
            <div 
              className="h-full bg-gradient-to-r from-green-400 to-blue-400 transition-all duration-500 ease-out relative"
              style={{ width: `${progressPercent}%` }}
            >
              <div className="absolute inset-0 bg-white/30 animate-pulse"></div>
            </div>
          </div>
        </div>

        {/* Current Agent Badge */}
        {currentAgent && (
          <div className="mt-4 bg-white/10 backdrop-blur-sm rounded-lg p-3 border border-white/20">
            <div className="flex items-center gap-2">
              <Zap className="h-5 w-5 text-yellow-300 animate-pulse" />
              <div className="flex-1">
                <div className="text-xs text-blue-100">Active Agent</div>
                <div className="text-sm font-bold text-white font-mono">{currentAgent}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Process Flow */}
      <div className="p-4 space-y-3">
        {agentSteps.map((step, index) => {
          const isExpanded = expandedPhase === step.id;
          const hasDetails = phaseDetails[step.id];
          const isLast = index === agentSteps.length - 1;

          return (
            <div key={step.id} className="relative">
              {/* Step Card */}
              <div
                onClick={() => hasDetails && setExpandedPhase(isExpanded ? null : step.id)}
                className={`
                  rounded-xl transition-all duration-300 cursor-pointer
                  ${step.status === 'active' ? 'bg-gradient-to-r from-blue-600/90 to-blue-500/90 shadow-lg shadow-blue-500/50 scale-105' : ''}
                  ${step.status === 'complete' ? 'bg-gradient-to-r from-green-600/80 to-emerald-600/80 shadow-md' : ''}
                  ${step.status === 'pending' ? 'bg-slate-800/50 opacity-60' : ''}
                  ${step.status === 'error' ? 'bg-gradient-to-r from-red-600/90 to-red-500/90 shadow-lg shadow-red-500/50' : ''}
                  ${hasDetails ? 'hover:scale-102' : ''}
                `}
              >
                <div className="p-4">
                  <div className="flex items-center gap-3">
                    {/* Icon */}
                    <div className={`
                      flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center font-bold
                      ${step.status === 'active' ? 'bg-white/20 animate-pulse' : ''}
                      ${step.status === 'complete' ? 'bg-white/20' : ''}
                      ${step.status === 'pending' ? 'bg-slate-700/50' : ''}
                    `}>
                      {step.status === 'pending' && <div className="w-6 h-6 rounded-full border-2 border-slate-500" />}
                      {step.status === 'active' && <Loader2 className="h-6 w-6 text-white animate-spin" />}
                      {step.status === 'complete' && <CheckCircle2 className="h-6 w-6 text-white" />}
                      {step.status === 'error' && <AlertCircle className="h-6 w-6 text-white" />}
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className={`font-bold text-sm ${
                          step.status === 'pending' ? 'text-slate-400' : 'text-white'
                        }`}>
                          {step.name}
                        </h4>
                        {step.status === 'active' && (
                          <span className="px-2 py-0.5 bg-white/20 text-white text-xs font-bold rounded-full animate-pulse">
                            LIVE
                          </span>
                        )}
                      </div>
                      <p className={`text-xs ${
                        step.status === 'pending' ? 'text-slate-500' : 'text-white/80'
                      }`}>
                        {step.message}
                      </p>
                    </div>
                  </div>

                  {/* Expanded Details */}
                  {isExpanded && hasDetails && (
                    <div className="mt-3 pt-3 border-t border-white/20 space-y-2 animate-in fade-in slide-in-from-top-2 duration-300">
                      {/* Routing Phase Details */}
                      {step.id === 'routing' && phaseDetails.routing && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-white/90">
                            <Trophy className="h-4 w-4" />
                            <span className="text-xs font-semibold">AGENT SELECTED</span>
                          </div>
                          <div className="bg-black/30 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-2">
                              <div className="text-white font-mono text-sm">{phaseDetails.routing.agent}</div>
                              {phaseDetails.routing.confidence && (
                                <span className="px-2 py-1 bg-green-400/30 text-green-100 text-xs font-bold rounded-full">
                                  {Math.round(phaseDetails.routing.confidence * 100)}% match
                                </span>
                              )}
                            </div>
                            {phaseDetails.routing.reason && (
                              <div className="text-white/70 text-xs">{phaseDetails.routing.reason}</div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Observing Phase Details */}
                      {step.id === 'observing' && phaseDetails.observing && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-white/90">
                            <Database className="h-4 w-4" />
                            <span className="text-xs font-semibold">EXTERNAL SYSTEMS ACCESSED</span>
                          </div>
                          {phaseDetails.observing.sources && phaseDetails.observing.sources.length > 0 && (
                            <div className="space-y-1">
                              {phaseDetails.observing.sources.map((source: string, idx: number) => (
                                <div key={idx} className="flex items-center gap-2 bg-black/40 rounded px-3 py-2">
                                  {(source.includes('Odoo') || source.includes('ERP') || source.includes('Adapter')) && <Database className="h-4 w-4 text-blue-300" />}
                                  {source.includes('PostgreSQL') && <Database className="h-4 w-4 text-green-300" />}
                                  {source.includes('Budget') && <Database className="h-4 w-4 text-purple-300" />}
                                  <span className="text-white text-sm font-mono">{source}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          <div className="bg-black/30 rounded-lg p-3">
                            <div className="text-white/80 text-xs mb-2">{phaseDetails.observing.details}</div>
                            {phaseDetails.observing.recordsFound && (
                              <div className="flex items-center gap-2 text-green-300 text-sm font-semibold">
                                <CheckCircle2 className="h-4 w-4" />
                                <span>Retrieved: {phaseDetails.observing.recordsFound}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Deciding Phase Details */}
                      {step.id === 'deciding' && phaseDetails.deciding && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-white/90">
                            <Brain className="h-4 w-4" />
                            <span className="text-xs font-semibold">AI DECISION ENGINE</span>
                          </div>
                          {phaseDetails.deciding.model && (
                            <div className="bg-purple-900/30 border border-purple-400/30 rounded px-3 py-1 text-xs text-purple-200">
                              🤖 Model: {phaseDetails.deciding.model}
                            </div>
                          )}
                          <div className="bg-black/30 rounded-lg p-3 space-y-2">
                            <div className="flex items-center justify-between">
                              <span className="text-white font-bold text-lg">{phaseDetails.deciding.action}</span>
                              <span className="px-3 py-1 bg-blue-400/30 text-blue-100 text-sm font-bold rounded-full">
                                {phaseDetails.deciding.confidence}%
                              </span>
                            </div>
                            {phaseDetails.deciding.reasoning && (
                              <div className="text-white/70 text-xs border-l-2 border-white/30 pl-3">
                                {phaseDetails.deciding.reasoning}
                              </div>
                            )}
                            {phaseDetails.deciding.alternatives && phaseDetails.deciding.alternatives.length > 0 && (
                              <div className="mt-3 pt-2 border-t border-white/20">
                                <div className="text-white/60 text-xs mb-2">Alternatives Considered:</div>
                                <div className="flex flex-wrap gap-1">
                                  {phaseDetails.deciding.alternatives.map((alt: string, idx: number) => (
                                    <span key={idx} className="px-2 py-1 bg-white/10 text-white/80 text-xs rounded">
                                      {alt}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Acting Phase Details */}
                      {step.id === 'acting' && phaseDetails.acting && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-white/90">
                            <Wrench className="h-4 w-4" />
                            <span className="text-xs font-semibold">TOOLS EXECUTED</span>
                          </div>
                          {phaseDetails.acting.tools && phaseDetails.acting.tools.length > 0 && (
                            <div className="space-y-1">
                              {phaseDetails.acting.tools.map((tool: string, idx: number) => (
                                <div key={idx} className="bg-black/40 rounded px-3 py-2 font-mono text-xs text-white flex items-center gap-2">
                                  <Wrench className="h-3 w-3 text-orange-300" />
                                  {tool}
                                </div>
                              ))}
                            </div>
                          )}
                          {phaseDetails.acting.timing && (
                            <div className="bg-black/30 rounded-lg p-3">
                              <div className="flex items-center gap-2 text-green-300 font-mono text-lg font-bold">
                                <Clock className="h-5 w-5" />
                                {phaseDetails.acting.timing}ms
                              </div>
                            </div>
                          )}
                          {phaseDetails.acting.result && (
                            <div className="bg-green-900/30 border border-green-400 rounded p-3">
                              <div className="flex items-center gap-2">
                                <CheckCircle2 className="h-4 w-4 text-green-300" />
                                <span className="text-white text-sm font-semibold">Result:</span>
                              </div>
                              <div className="text-green-100 text-xs mt-1">{phaseDetails.acting.result}</div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Learning Phase Details */}
                      {step.id === 'learning' && phaseDetails.learning && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 text-white/90">
                            <Database className="h-4 w-4" />
                            <span className="text-xs font-semibold">DATABASE OPERATIONS</span>
                          </div>
                          <div className="bg-black/30 rounded-lg p-3">
                            {phaseDetails.learning.table && (
                              <div className="flex items-center gap-2 mb-2">
                                <Database className="h-4 w-4 text-purple-300" />
                                <span className="text-white text-sm font-mono">{phaseDetails.learning.table}</span>
                              </div>
                            )}
                            {phaseDetails.learning.recorded && (
                              <div className="flex items-center gap-2 text-green-300 text-xs">
                                <CheckCircle2 className="h-4 w-4" />
                                <span>Knowledge successfully recorded</span>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Connecting Line */}
              {!isLast && (step.status === 'complete' || step.status === 'active') && (
                <div className="flex justify-center my-2">
                  <div className={`w-1 h-4 rounded-full ${
                    step.status === 'complete' ? 'bg-green-400' : 'bg-blue-400 animate-pulse'
                  }`} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer Status */}
      {!isActive && agentSteps.length > 0 && (
        <div className="sticky bottom-0 bg-green-600 p-4 rounded-b-2xl text-center">
          <div className="flex items-center justify-center gap-2 text-white font-bold">
            <CheckCircle2 className="h-5 w-5" />
            <span>Process Complete</span>
          </div>
        </div>
      )}
    </div>
  );
}
