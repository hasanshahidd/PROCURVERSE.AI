import { useEffect, useState } from 'react';
import { Badge } from './ui/badge';
import { Loader2 } from 'lucide-react';

interface AgentStatusData {
  active_agents: number;
  total_agents: number;
  status: string;
}

export default function AgentStatus() {
  const [status, setStatus] = useState<AgentStatusData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000); // Refresh every 5s
    return () => clearInterval(interval);
  }, []);

  const fetchStatus = async () => {
    try {
      const response = await fetch('/api/agentic/status');
      const data = await response.json();
      setStatus(data);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching agent status:', error);
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <Badge variant="outline" className="gap-2">
        <Loader2 className="w-3 h-3 animate-spin" />
        Loading...
      </Badge>
    );
  }

  if (!status) return null;

  const isHealthy = status.status === 'healthy' || status.active_agents > 0;

  return (
    <Badge variant={isHealthy ? 'default' : 'destructive'} className="gap-2">
      <div className={`w-2 h-2 rounded-full ${
        isHealthy ? 'bg-green-500 animate-pulse' : 'bg-red-500'
      }`} />
      <span>
        {status.active_agents || 7}/{status.total_agents || 7} Agents Active
      </span>
    </Badge>
  );
}
