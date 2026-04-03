/**
 * Pipeline Queue Hook
 * 
 * Delays pipeline store updates to create streaming visual effect.
 * Even though SSE events arrive within 50-100ms, this queues them
 * and processes one every 700ms for smooth animation.
 */

import { useRef, useEffect } from 'react';
import { usePipelineStore } from '../store/pipelineStore';

type QueuedUpdate = {
  type: 'advanceStep' | 'completeStep' | 'addLog' | 'selectAgent' | 'upsertAgentExecution' | 'setAgentPhase' | 'updatePhaseDetail' | 'activatePhase' | 'setCurrentAgentName' | 'completeAgentExecution' | 'setResult';
  args: any[];
};

export function usePipelineQueue() {
  const priorityQueue = useRef<QueuedUpdate[]>([]);
  const normalQueue = useRef<QueuedUpdate[]>([]);
  const intervalRef = useRef<number | null>(null);
  const isProcessing = useRef(false);
  const tickCount = useRef(0);
  const drainResolvers = useRef<Array<() => void>>([]);
  const INTERVAL_MS = 120;
  const BATCH_SIZE = 10;

  const isPriorityType = (type: QueuedUpdate['type']) => {
    return type === 'updatePhaseDetail'
      || type === 'setAgentPhase'
      || type === 'activatePhase'
      || type === 'setCurrentAgentName'
      || type === 'upsertAgentExecution'
      || type === 'completeAgentExecution'
      || type === 'setResult'
      || type === 'selectAgent';
  };

  const totalQueued = () => priorityQueue.current.length + normalQueue.current.length;

  const popNextUpdate = (): QueuedUpdate | undefined => {
    if (priorityQueue.current.length > 0) return priorityQueue.current.shift();
    return normalQueue.current.shift();
  };

  const getCoalesceKey = (item: QueuedUpdate): string | null => {
    switch (item.type) {
      case 'updatePhaseDetail':
        return `${item.type}:${String(item.args[0] ?? '')}`;
      case 'setAgentPhase':
        return `${item.type}:${String(item.args[0] ?? '')}:${String(item.args[1] ?? '')}`;
      case 'setCurrentAgentName':
      case 'setResult':
        return item.type;
      case 'selectAgent':
      case 'upsertAgentExecution':
      case 'completeAgentExecution':
      case 'activatePhase':
        return `${item.type}:${String(item.args[0] ?? '')}`;
      default:
        return null;
    }
  };

  const upsertQueueItem = (queue: QueuedUpdate[], item: QueuedUpdate) => {
    const key = getCoalesceKey(item);
    if (!key) {
      queue.push(item);
      return;
    }

    for (let i = queue.length - 1; i >= 0; i--) {
      const existingKey = getCoalesceKey(queue[i]);
      if (existingKey === key) {
        queue[i] = item;
        return;
      }
    }

    queue.push(item);
  };

  const resolveDrainWaiters = () => {
    if (drainResolvers.current.length === 0) return;
    const resolvers = [...drainResolvers.current];
    drainResolvers.current = [];
    for (const resolve of resolvers) resolve();
  };
  
  // Start processing queue
  const startQueue = () => {
    if (intervalRef.current) return;
    
    console.log(`[PIPELINE QUEUE] Starting processor - ${INTERVAL_MS}ms intervals, batch=${BATCH_SIZE}`);
    isProcessing.current = true;
    
    intervalRef.current = window.setInterval(() => {
      if (totalQueued() === 0) {
        return;
      }

      const store = usePipelineStore.getState() as any;
      const queuedBeforeTick = totalQueued();
      const dynamicBatchSize = queuedBeforeTick > 300
        ? 80
        : queuedBeforeTick > 200
          ? 60
          : queuedBeforeTick > 100
            ? 35
            : BATCH_SIZE;

      for (let i = 0; i < dynamicBatchSize; i++) {
        const next = popNextUpdate();
        if (!next) break;

        // Execute the queued update
        switch (next.type) {
          case 'advanceStep':
            store.advanceStep(...(next.args as any[]));
            break;
          case 'completeStep':
            store.completeStep(...(next.args as any[]));
            break;
          case 'addLog':
            store.addLog(...(next.args as any[]));
            break;
          case 'selectAgent':
            store.selectAgent(...(next.args as any[]));
            break;
          case 'upsertAgentExecution':
            store.upsertAgentExecution(...(next.args as any[]));
            break;
          case 'setAgentPhase':
            store.setAgentPhase(...(next.args as any[]));
            break;
          case 'updatePhaseDetail':
            store.updatePhaseDetail(...(next.args as any[]));
            break;
          case 'activatePhase':
            store.activatePhase(...(next.args as any[]));
            break;
          case 'setCurrentAgentName':
            store.setCurrentAgentName(...(next.args as any[]));
            break;
          case 'completeAgentExecution':
            store.completeAgentExecution(...(next.args as any[]));
            break;
          case 'setResult':
            store.setResult(...(next.args as any[]));
            break;
        }
      }
      
      // If queue is empty, stop interval
      if (totalQueued() === 0) {
        console.log('[PIPELINE QUEUE] Queue drained - stopping processor');
        tickCount.current = 0;
        stopQueue();
        resolveDrainWaiters();
      } else {
        tickCount.current += 1;
        const remaining = totalQueued();
        const shouldLog = remaining <= 50 || tickCount.current % 10 === 0;
        if (shouldLog) {
          console.log(
            '[PIPELINE QUEUE] Tick complete | Queue remaining:',
            remaining,
            `(priority=${priorityQueue.current.length}, normal=${normalQueue.current.length}, batch=${dynamicBatchSize})`
          );
        }
      }
    }, INTERVAL_MS);
  };
  
  // Stop processing queue
  const stopQueue = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    isProcessing.current = false;
  };
  
  // Queue an update instead of executing it immediately
  const queueUpdate = (type: QueuedUpdate['type'], ...args: any[]) => {
    const item = { type, args };
    if (isPriorityType(type)) {
      upsertQueueItem(priorityQueue.current, item);
    } else {
      upsertQueueItem(normalQueue.current, item);
    }
    console.log(
      '[PIPELINE QUEUE] Queued:',
      type,
      '| Total queued:',
      totalQueued(),
      `(priority=${priorityQueue.current.length}, normal=${normalQueue.current.length})`
    );
    
    // Start processing if not already running
    if (!intervalRef.current) {
      startQueue();
    }
  };
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopQueue();
    };
  }, []);
  
  // Return queued versions of store methods
  return {
    advanceStep: (...args: any[]) => queueUpdate('advanceStep', ...args),
    completeStep: (...args: any[]) => queueUpdate('completeStep', ...args),
    addLog: (...args: any[]) => queueUpdate('addLog', ...args),
    selectAgent: (...args: any[]) => queueUpdate('selectAgent', ...args),
    upsertAgentExecution: (...args: any[]) => queueUpdate('upsertAgentExecution', ...args),
    setAgentPhase: (...args: any[]) => queueUpdate('setAgentPhase', ...args),
    updatePhaseDetail: (...args: any[]) => queueUpdate('updatePhaseDetail', ...args),
    activatePhase: (...args: any[]) => queueUpdate('activatePhase', ...args),
    setCurrentAgentName: (...args: any[]) => queueUpdate('setCurrentAgentName', ...args),
    completeAgentExecution: (...args: any[]) => queueUpdate('completeAgentExecution', ...args),
    setResult: (...args: any[]) => queueUpdate('setResult', ...args),
    waitForDrain: (timeoutMs = 120000) => {
      if (totalQueued() === 0 && !isProcessing.current) {
        return Promise.resolve();
      }

      return new Promise<void>((resolve) => {
        let done = false;
        const wrappedResolve = () => {
          if (done) return;
          done = true;
          resolve();
        };

        drainResolvers.current.push(wrappedResolve);

        window.setTimeout(() => {
          if (!done) {
            console.warn('[PIPELINE QUEUE] waitForDrain timeout reached, continuing');
            wrappedResolve();
          }
        }, timeoutMs);
      });
    },
    clearQueue: () => {
      priorityQueue.current = [];
      normalQueue.current = [];
      stopQueue();
      resolveDrainWaiters();
    },
    queueLength: totalQueued(),
  };
}
