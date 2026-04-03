import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, Brain, CheckCircle2, Database, Route, Sparkles } from 'lucide-react';

interface AgentFlowNode {
  id: string;
  label: string;
  icon: 'route' | 'database' | 'brain' | 'check';
  status: 'pending' | 'active' | 'complete';
  detail?: string;
}

interface AgentFlowDiagramProps {
  currentAgent: string;
  phaseDetails: Record<string, any>;
  isActive: boolean;
}

export function AgentFlowDiagram({ currentAgent, phaseDetails, isActive }: AgentFlowDiagramProps) {
  const [nodes, setNodes] = useState<AgentFlowNode[]>([]);
  const activeCount = useMemo(() => nodes.filter((n) => n.status === 'complete').length, [nodes]);
  
  useEffect(() => {
    const observing = phaseDetails.observing || {};
    const deciding = phaseDetails.deciding || {};
    const acting = phaseDetails.acting || {};
    const learning = phaseDetails.learning || {};
    const routing = phaseDetails.routing || {};

    const rawSources: string[] = Array.isArray(observing.sources) ? observing.sources : [];
    const cleanSources = Array.from(
      new Set(
        rawSources
          .map((s) => String(s).trim())
          .filter(Boolean)
          .map((s) => (s.toLowerCase().includes('budget') ? 'Budget Tables' : s))
      )
    );

    const sourceLabel = cleanSources.length > 0 ? cleanSources.join(' • ') : 'Internal context';
    const routeLabel = routing.agent || currentAgent || 'Selecting best agent';

    const flowNodes: AgentFlowNode[] = [
      {
        id: 'route',
        label: 'Routing',
        icon: 'route',
        status: routing.agent ? 'complete' : phaseDetails.classifying ? 'active' : 'pending',
        detail: routeLabel,
      },
      {
        id: 'data',
        label: 'Data Access',
        icon: 'database',
        status: observing.status === 'complete' ? 'complete' : observing.status === 'active' ? 'active' : 'pending',
        detail: sourceLabel,
      },
      {
        id: 'decision',
        label: 'AI Decision',
        icon: 'brain',
        status: deciding.action ? 'complete' : deciding.status === 'active' ? 'active' : 'pending',
        detail: deciding.action || deciding.model || 'Reasoning in progress',
      },
      {
        id: 'result',
        label: 'Result',
        icon: 'check',
        status: learning.status === 'complete' ? 'complete' : acting.status === 'complete' ? 'active' : 'pending',
        detail: acting.result || 'Finalizing response',
      },
    ];

    setNodes(flowNodes);
  }, [phaseDetails]);
  
  if (!isActive || nodes.length === 0) return null;
  
  const NodeIcon = ({ type, status }: { type: string; status: string }) => {
    const iconClass = status === 'active' ? 'animate-pulse' : '';
    const colorClass = status === 'complete' ? 'text-green-400' : 
                       status === 'active' ? 'text-blue-400' : 'text-gray-400';
    
    switch (type) {
      case 'route':
        return <Route className={`h-8 w-8 ${colorClass} ${iconClass}`} />;
      case 'database':
        return <Database className={`h-8 w-8 ${colorClass} ${iconClass}`} />;
      case 'brain':
        return <Brain className={`h-8 w-8 ${colorClass} ${iconClass}`} />;
      case 'check':
        return <CheckCircle2 className={`h-8 w-8 ${colorClass} ${iconClass}`} />;
      default:
        return <Route className={`h-8 w-8 ${colorClass}`} />;
    }
  };
  
  return (
    <div className="fixed top-4 right-4 w-96 bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900 rounded-xl shadow-2xl border border-cyan-400/30 p-6 z-50">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Sparkles className="h-6 w-6 text-cyan-300 animate-pulse" />
        <div>
          <h3 className="text-white font-bold text-lg">Execution Flow</h3>
          <p className="text-cyan-100 text-xs">{currentAgent || 'Orchestrator'}</p>
        </div>
        <div className="ml-auto px-2 py-1 rounded-md bg-white/10 text-xs text-cyan-100">
          Live
        </div>
      </div>
      
      {/* Flow Diagram */}
      <div className="space-y-4">
        {nodes.map((node, index) => (
          <div key={node.id}>
            {/* Node */}
            <div className={`
              flex items-center gap-4 p-4 rounded-lg border-2 transition-all duration-300
              ${node.status === 'active' ? 'bg-blue-500/20 border-blue-400 scale-105' : 
                node.status === 'complete' ? 'bg-green-500/10 border-green-400' : 
                'bg-black/20 border-gray-600'}
            `}>
              <NodeIcon type={node.icon} status={node.status} />
              <div className="flex-1 min-w-0">
                <div className="text-white font-semibold">{node.label}</div>
                {node.detail && (
                  <div className={`text-xs mt-1 truncate
                    ${node.status === 'complete' ? 'text-green-300' : 'text-cyan-200'}
                  `}>
                    {node.detail}
                  </div>
                )}
              </div>
              {node.status === 'complete' && (
                <CheckCircle2 className="h-5 w-5 text-green-400 flex-shrink-0" />
              )}
              {node.status === 'active' && (
                <div className="flex-shrink-0">
                  <div className="h-3 w-3 bg-blue-400 rounded-full animate-ping" />
                </div>
              )}
            </div>
            
            {/* Connector Arrow (animated) */}
            {index < nodes.length - 1 && (
              <div className="flex justify-center my-2">
                <div className={`transition-all duration-500
                  ${node.status === 'complete' ? 'text-green-400' : 
                    node.status === 'active' ? 'text-cyan-300 animate-bounce' : 'text-gray-600'}
                `}>
                  <ArrowRight className="h-6 w-6 rotate-90" />
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      
      {/* Progress Indicator */}
      <div className="mt-6 pt-4 border-t border-white/10">
        <div className="flex items-center justify-between text-xs text-white/70 mb-2">
          <span>Progress</span>
          <span>{activeCount}/{nodes.length}</span>
        </div>
        <div className="w-full bg-black/30 rounded-full h-2">
          <div 
            className="bg-gradient-to-r from-cyan-400 to-green-500 h-2 rounded-full transition-all duration-500"
            style={{ 
              width: `${(activeCount / nodes.length) * 100}%` 
            }}
          />
        </div>
      </div>
    </div>
  );
}
