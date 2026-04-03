/**
 * Live Agent Process Visualizer
 * 
 * Shows the real-time execution flow of AI agents:
 * - User prompt received
 * - Orchestrator analyzing
 * - Agent selected
 * - OBSERVE → DECIDE → ACT → LEARN cycle
 * - Final result
 * 
 * Uses Server-Sent Events (SSE) to stream execution events.
 */

import React, { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { 
  ArrowRight, 
  Brain, 
  Eye, 
  Lightbulb, 
  Play, 
  BookOpen,
  CheckCircle2,
  Loader2,
  AlertCircle
} from 'lucide-react';

const API_URL = (import.meta as any).env?.VITE_API_URL || '';

interface AgentEvent {
  type: string;
  timestamp: string;
  data: any;
}

interface ProcessStep {
  id: string;
  name: string;
  status: 'pending' | 'active' | 'complete' | 'error';
  icon: any;
  message: string;
  timestamp?: string;
  data?: any;
}

export default function AgentProcessVisualizer() {
  const [prompt, setPrompt] = useState('Check IT department budget for $50,000 laptop purchase');
  const [isExecuting, setIsExecuting] = useState(false);
  const [steps, setSteps] = useState<ProcessStep[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const initialSteps: ProcessStep[] = [
    {
      id: 'received',
      name: 'Request Received',
      status: 'pending',
      icon: Play,
      message: 'Waiting for user input...'
    },
    {
      id: 'classifying',
      name: 'Analyzing Intent',
      status: 'pending',
      icon: Brain,
      message: 'Understanding what you need...'
    },
    {
      id: 'routing',
      name: 'Selecting Agent',
      status: 'pending',
      icon: ArrowRight,
      message: 'Finding the right specialist...'
    },
    {
      id: 'observing',
      name: 'OBSERVE Phase',
      status: 'pending',
      icon: Eye,
      message: 'Gathering relevant data...'
    },
    {
      id: 'deciding',
      name: 'DECIDE Phase',
      status: 'pending',
      icon: Lightbulb,
      message: 'AI making decision...'
    },
    {
      id: 'acting',
      name: 'ACT Phase',
      status: 'pending',
      icon: CheckCircle2,
      message: 'Executing action...'
    },
    {
      id: 'learning',
      name: 'LEARN Phase',
      status: 'pending',
      icon: BookOpen,
      message: 'Learning from outcome...'
    }
  ];

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const executeAgent = async () => {
    if (!prompt.trim()) return;

    // Reset state
    setIsExecuting(true);
    setSteps(initialSteps);
    setEvents([]);
    setResult(null);
    setError(null);

    // Close any existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    try {
      // Create POST request body
      const requestBody = {
        request: prompt,
        pr_data: {
          department: 'IT',
          budget: 50000,
          budget_category: 'OPEX'
        }
      };

      // Open SSE connection with POST data in URL params (workaround for SSE POST limitation)
      // Note: In production, use a proper SSE library or WebSocket for POST
      const response = await fetch(`${API_URL}/api/agentic/execute/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Read SSE stream
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No response body');
      }

      // Process stream
      while (true) {
        const { done, value } = await reader.read();
        
        if (done) {
          setIsExecuting(false);
          break;
        }

        // Decode chunk
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            
            // Skip keepalive messages
            if (data.trim() === '') continue;

            try {
              const event: AgentEvent = JSON.parse(data);
              handleEvent(event);
            } catch (e) {
              console.error('Failed to parse event:', data);
            }
          }
        }
      }

    } catch (err: any) {
      console.error('Execution error:', err);
      setError(err.message);
      setIsExecuting(false);
    }
  };

  const handleEvent = (event: AgentEvent) => {
    console.log('[Event]', event.type, event.data);
    
    // Add to events log
    setEvents(prev => [...prev, event]);

    // Update steps based on event type
    setSteps(prevSteps => {
      const newSteps = [...prevSteps];
      
      const updateStep = (id: string, status: ProcessStep['status'], message?: string, data?: any) => {
        const step = newSteps.find(s => s.id === id);
        if (step) {
          step.status = status;
          if (message) step.message = message;
          if (data) step.data = data;
          step.timestamp = event.timestamp;
        }
      };

      switch (event.type) {
        case 'received':
          updateStep('received', 'complete', 'Request received successfully', event.data);
          break;
          
        case 'classifying':
          updateStep('received', 'complete');
          updateStep('classifying', 'active', 'Analyzing request intent...');
          break;
          
        case 'routing':
          updateStep('classifying', 'complete', 'Intent identified');
          updateStep('routing', 'active', 'Determining best agent for this task...');
          break;
          
        case 'agent_selected':
          updateStep('routing', 'complete', `Selected: ${event.data.agent}`, event.data);
          break;
          
        case 'observing':
          updateStep('observing', 'active', event.data.message || 'Gathering context...', event.data);
          break;
          
        case 'observation_complete':
          updateStep('observing', 'complete', 'Context gathered successfully', event.data);
          break;
          
        case 'deciding':
          updateStep('deciding', 'active', event.data.message || 'AI analyzing data...', event.data);
          break;
          
        case 'decision_made':
          updateStep('deciding', 'complete', 
            `Decision: ${event.data.action} (${Math.round(event.data.confidence * 100)}% confidence)`, 
            event.data
          );
          break;
          
        case 'acting':
          updateStep('acting', 'active', event.data.message || 'Executing action...', event.data);
          break;
          
        case 'action_complete':
          updateStep('acting', 'complete', 
            `Action completed in ${event.data.execution_time_ms}ms`, 
            event.data
          );
          break;
          
        case 'learning':
          updateStep('learning', 'active', 'Learning from outcome...');
          break;
          
        case 'learning_complete':
          updateStep('learning', 'complete', 'Learning complete');
          break;
          
        case 'complete':
          updateStep('learning', 'complete', 'All phases complete');
          setResult(event.data);
          setIsExecuting(false);
          break;
          
        case 'error':
          const activeStep = newSteps.find(s => s.status === 'active');
          if (activeStep) {
            activeStep.status = 'error';
            activeStep.message = event.data.error || 'An error occurred';
          }
          setError(event.data.error);
          setIsExecuting(false);
          break;
      }

      return newSteps;
    });
  };

  const getStepColor = (status: ProcessStep['status']) => {
    switch (status) {
      case 'complete': return 'bg-green-500';
      case 'active': return 'bg-blue-500 animate-pulse';
      case 'error': return 'bg-red-500';
      default: return 'bg-gray-300';
    }
  };

  const getStepTextColor = (status: ProcessStep['status']) => {
    switch (status) {
      case 'complete': return 'text-green-700';
      case 'active': return 'text-blue-700 font-semibold';
      case 'error': return 'text-red-700';
      default: return 'text-gray-500';
    }
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold mb-2">Live Agent Process Visualizer</h1>
        <p className="text-muted-foreground">
          Watch AI agents work in real-time: see the OBSERVE → DECIDE → ACT → LEARN cycle
        </p>
      </div>

      {/* Input Section */}
      <Card>
        <CardHeader>
          <CardTitle>Test Agent Execution</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            value={prompt}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setPrompt(e.target.value)}
            placeholder="Enter your request (e.g., 'Check IT budget for $50K purchase')"
            rows={3}
            disabled={isExecuting}
          />
          <Button 
            onClick={executeAgent} 
            disabled={isExecuting || !prompt.trim()}
            className="w-full"
          >
            {isExecuting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Executing...
              </>
            ) : (
              <>
                <Play className="mr-2 h-4 w-4" />
                Execute Agent
              </>
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Process Flow Visualization */}
      {steps.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Execution Flow</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {steps.map((step, index) => {
                const Icon = step.icon;
                return (
                  <div key={step.id} className="flex items-start gap-4">
                    {/* Step Number & Icon */}
                    <div className="flex flex-col items-center">
                      <div className={`w-10 h-10 rounded-full ${getStepColor(step.status)} flex items-center justify-center text-white`}>
                        {step.status === 'active' ? (
                          <Loader2 className="h-5 w-5 animate-spin" />
                        ) : step.status === 'error' ? (
                          <AlertCircle className="h-5 w-5" />
                        ) : (
                          <Icon className="h-5 w-5" />
                        )}
                      </div>
                      {index < steps.length - 1 && (
                        <div className={`w-0.5 h-8 ${
                          step.status === 'complete' ? 'bg-green-500' : 'bg-gray-300'
                        }`} />
                      )}
                    </div>

                    {/* Step Details */}
                    <div className="flex-1 pb-4">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className={`font-semibold ${getStepTextColor(step.status)}`}>
                          {step.name}
                        </h3>
                        {step.status === 'complete' && (
                          <Badge variant="outline" className="text-green-600 border-green-600">
                            <CheckCircle2 className="h-3 w-3 mr-1" />
                            Done
                          </Badge>
                        )}
                        {step.status === 'active' && (
                          <Badge className="bg-blue-500">Processing...</Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground">{step.message}</p>
                      
                      {/* Additional Data */}
                      {step.data && (
                        <div className="mt-2 text-xs text-muted-foreground bg-muted p-2 rounded">
                          {step.data.agent && <div>Agent: <strong>{step.data.agent}</strong></div>}
                          {step.data.reasoning && <div>Reasoning: {step.data.reasoning}</div>}
                          {step.data.confidence !== undefined && (
                            <div>Confidence: <strong>{Math.round(step.data.confidence * 100)}%</strong></div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Result */}
      {result && (
        <Card className="border-green-500">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-green-700">
              <CheckCircle2 className="h-5 w-5" />
              Execution Complete
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="bg-green-50 p-4 rounded-lg">
              <pre className="text-sm overflow-x-auto">
                {JSON.stringify(result, null, 2)}
              </pre>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Error */}
      {error && (
        <Card className="border-red-500">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-red-700">
              <AlertCircle className="h-5 w-5" />
              Execution Error
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="bg-red-50 p-4 rounded-lg">
              <p className="text-red-700">{error}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Events Log (Developer View) */}
      {events.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Event Stream (Developer View)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {events.map((event, index) => (
                <div key={index} className="text-xs font-mono bg-muted p-2 rounded">
                  <span className="text-muted-foreground">
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="ml-2 font-semibold">{event.type}</span>
                  <span className="ml-2 text-muted-foreground">
                    {JSON.stringify(event.data)}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
