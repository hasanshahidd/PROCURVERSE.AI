import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { Check, X, Clock, AlertCircle, RefreshCcw, ChevronDown, History } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

interface PendingApproval {
  approval_id: string;
  agent_name: string;
  request_type: string;
  request_data: any;
  recommendation: any;
  confidence_score: number;
  reasoning: string;
  status: string;
  created_at: string;
  reviewed_at?: string;
  reviewed_by?: string;
  review_notes?: string;
}

export default function PendingApprovalsPage() {
  const queryClient = useQueryClient();
  const API_BASE_URL = import.meta.env.VITE_API_URL || "";
  const [selectedApproval, setSelectedApproval] = useState<PendingApproval | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [isApproving, setIsApproving] = useState(false);
  const [activeTab, setActiveTab] = useState("pending");

  // Fetch pending approvals
  const { data: approvals, isLoading, error, refetch } = useQuery<PendingApproval[]>({
    queryKey: ["/api/agentic/pending-approvals"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/agentic/pending-approvals`);
      if (!res.ok) throw new Error("Failed to fetch pending approvals");
      const data = await res.json();
      return data.approvals || [];
    },
    refetchInterval: 10000, // Refetch every 10 seconds
  });

  // Fetch history
  const { data: history, isLoading: historyLoading, refetch: refetchHistory } = useQuery<PendingApproval[]>({
    queryKey: ["/api/agentic/pending-approvals/history"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/agentic/pending-approvals/history`);
      if (!res.ok) throw new Error("Failed to fetch history");
      const data = await res.json();
      return data.history || [];
    },
    enabled: activeTab === "history",
  });

  // Approve mutation
  const approveMutation = useMutation({
    mutationFn: async ({ approvalId, notes }: { approvalId: string; notes: string }) => {
      const res = await fetch(
        `${API_BASE_URL}/api/agentic/pending-approvals/${approvalId}/approve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ notes }),
        }
      );
      if (!res.ok) throw new Error("Failed to approve");
      return await res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/pending-approvals"] });
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/pending-approvals/history"] });
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/pending-approvals/count"] });
      setSelectedApproval(null);
      setReviewNotes("");
    },
  });

  // Reject mutation
  const rejectMutation = useMutation({
    mutationFn: async ({ approvalId, reason }: { approvalId: string; reason: string }) => {
      const res = await fetch(
        `${API_BASE_URL}/api/agentic/pending-approvals/${approvalId}/reject`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason }),
        }
      );
      if (!res.ok) throw new Error("Failed to reject");
      return await res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/pending-approvals"] });
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/pending-approvals/history"] });
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/pending-approvals/count"] });
      setSelectedApproval(null);
      setReviewNotes("");
    },
  });

  const handleApprove = () => {
    if (!selectedApproval) return;
    approveMutation.mutate({
      approvalId: selectedApproval.approval_id,
      notes: reviewNotes,
    });
  };

  const handleReject = () => {
    if (!selectedApproval) return;
    if (!reviewNotes.trim()) {
      alert("Please provide a reason for rejection");
      return;
    }
    setIsApproving(false);
    rejectMutation.mutate({
      approvalId: selectedApproval.approval_id,
      reason: reviewNotes,
    });
  };

  const getAgentBadgeColor = (agentName: string) => {
    if (agentName.includes("Budget")) return "bg-green-500";
    if (agentName.includes("Approval")) return "bg-blue-500";
    if (agentName.includes("Vendor")) return "bg-purple-500";
    return "bg-gray-500";
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <RefreshCcw className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Loading pending approvals...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Failed to load pending approvals. Please check your connection and try again.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">AI Decision Approvals</h1>
          <p className="text-muted-foreground text-sm">
            Review and approve low-confidence agent decisions
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => activeTab === "pending" ? refetch() : refetchHistory()}>
          <RefreshCcw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="pending" className="gap-2">
            <Clock className="h-4 w-4" />
            Pending
            {approvals && approvals.length > 0 && (
              <Badge variant="secondary" className="ml-1">{approvals.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="history" className="gap-2">
            <History className="h-4 w-4" />
            History
          </TabsTrigger>
        </TabsList>

        {/* Pending Tab */}
        <TabsContent value="pending">
          {!approvals || approvals.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Check className="h-16 w-16 text-green-500 mb-4" />
                <h3 className="text-xl font-semibold mb-2">All Clear!</h3>
                <p className="text-muted-foreground text-center max-w-md">
                  No pending approvals. Agent decisions with low confidence will appear here.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {approvals.map((approval) => (
                  <Card key={approval.approval_id} className="hover:shadow-md transition-shadow">
                    <CardHeader>
                      <div className="flex items-start justify-between">
                        <div className="space-y-1 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <CardTitle className="text-lg">{approval.approval_id}</CardTitle>
                            <Badge className={getAgentBadgeColor(approval.agent_name)}>
                              {approval.agent_name}
                            </Badge>
                            <Badge variant="outline" className="gap-1">
                              <Clock className="h-3 w-3" />
                              {format(new Date(approval.created_at), "MMM d, HH:mm")}
                            </Badge>
                          </div>
                          <CardDescription className="flex items-center gap-2 flex-wrap">
                            <span>Type: {approval.request_type}</span>
                            <span>•</span>
                            <span className="flex items-center gap-1">
                              Confidence:
                              <Badge variant={approval.confidence_score < 0.4 ? "destructive" : "secondary"}>
                                {(approval.confidence_score * 100).toFixed(0)}%
                              </Badge>
                            </span>
                          </CardDescription>
                        </div>
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            variant="default"
                            onClick={() => {
                              setSelectedApproval(approval);
                              setIsApproving(true);
                            }}
                          >
                            <Check className="h-4 w-4 mr-1" />
                            Approve
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => {
                              setSelectedApproval(approval);
                              setIsApproving(false);
                            }}
                          >
                            <X className="h-4 w-4 mr-1" />
                            Reject
                          </Button>
                        </div>
                      </div>
                    </CardHeader>

                    <CardContent className="space-y-4">
                      <div>
                        <h4 className="font-semibold text-sm mb-2">Why Agent Needs Your Help:</h4>
                        <p className="text-sm text-muted-foreground bg-muted p-3 rounded-md">
                          {approval.reasoning}
                        </p>
                      </div>

                      <Collapsible>
                        <CollapsibleTrigger asChild>
                          <Button variant="ghost" size="sm" className="w-full justify-between">
                            <span>View Details</span>
                            <ChevronDown className="h-4 w-4" />
                          </Button>
                        </CollapsibleTrigger>
                        <CollapsibleContent className="space-y-3 mt-3">
                          <div>
                            <h4 className="font-semibold text-sm mb-2">Request Data:</h4>
                            <pre className="text-xs bg-muted p-3 rounded-md overflow-x-auto">
                              {JSON.stringify(approval.request_data, null, 2)}
                            </pre>
                          </div>
                          {approval.recommendation && Object.keys(approval.recommendation).length > 0 && (
                            <div>
                              <h4 className="font-semibold text-sm mb-2">Agent's Recommendation:</h4>
                              <pre className="text-xs bg-muted p-3 rounded-md overflow-x-auto">
                                {JSON.stringify(approval.recommendation, null, 2)}
                              </pre>
                            </div>
                          )}
                        </CollapsibleContent>
                      </Collapsible>
                    </CardContent>
                  </Card>
                ))}
              </div>
          )}
        </TabsContent>

        {/* History Tab */}
        <TabsContent value="history">
          {historyLoading ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCcw className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : !history || history.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <History className="h-16 w-16 text-muted-foreground mb-4" />
                <h3 className="text-xl font-semibold mb-2">No History Yet</h3>
                <p className="text-muted-foreground text-center max-w-md">
                  Your approval history will show here after you approve or reject decisions.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {history.map((approval) => (
                  <Card key={approval.approval_id} className="opacity-80">
                    <CardHeader>
                      <div className="flex items-start justify-between">
                        <div className="space-y-1 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <CardTitle className="text-lg">{approval.approval_id}</CardTitle>
                            <Badge className={getAgentBadgeColor(approval.agent_name)}>
                              {approval.agent_name}
                            </Badge>
                            {approval.status === "approved" ? (
                              <Badge className="bg-green-500">
                                <Check className="h-3 w-3 mr-1" />
                                Approved
                              </Badge>
                            ) : (
                              <Badge variant="destructive">
                                <X className="h-3 w-3 mr-1" />
                                Rejected
                              </Badge>
                            )}
                            <Badge variant="outline">
                              {approval.reviewed_at && format(new Date(approval.reviewed_at), "MMM d, HH:mm")}
                            </Badge>
                          </div>
                          <CardDescription>
                            Confidence: {(approval.confidence_score * 100).toFixed(0)}%
                          </CardDescription>
                        </div>
                      </div>
                    </CardHeader>

                    <CardContent className="space-y-3">
                      <div>
                        <h4 className="font-semibold text-sm mb-1">Decision Reasoning:</h4>
                        <p className="text-sm text-muted-foreground">{approval.reasoning}</p>
                      </div>
                      {approval.review_notes && (
                        <div>
                          <h4 className="font-semibold text-sm mb-1">Your Notes:</h4>
                          <p className="text-sm bg-muted p-2 rounded-md">{approval.review_notes}</p>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Review Dialog */}
      <Dialog open={!!selectedApproval} onOpenChange={() => setSelectedApproval(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {isApproving ? "Approve" : "Reject"} Decision - {selectedApproval?.approval_id}
            </DialogTitle>
            <DialogDescription>
              {isApproving
                ? "Provide optional notes for this approval. The agent will execute the recommended action."
                : "Please provide a clear reason for rejection. This helps the agent learn and improve."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="bg-muted p-4 rounded-md">
              <p className="text-sm font-semibold mb-1">Agent: {selectedApproval?.agent_name}</p>
              <p className="text-sm text-muted-foreground">
                Confidence: {((selectedApproval?.confidence_score || 0) * 100).toFixed(0)}%
              </p>
            </div>

            <div>
              <label className="text-sm font-medium mb-2 block">
                {isApproving ? "Notes (Optional)" : "Rejection Reason (Required)"}
              </label>
              <Textarea
                placeholder={
                  isApproving
                    ? "Add any notes about this approval..."
                    : "Explain why this decision is being rejected..."
                }
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                rows={4}
                required={!isApproving}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setSelectedApproval(null)}>
              Cancel
            </Button>
            {isApproving ? (
              <Button
                onClick={handleApprove}
                disabled={approveMutation.isPending}
              >
                {approveMutation.isPending ? "Approving..." : "Confirm Approval"}
              </Button>
            ) : (
              <Button
                variant="destructive"
                onClick={handleReject}
                disabled={rejectMutation.isPending || !reviewNotes.trim()}
              >
                {rejectMutation.isPending ? "Rejecting..." : "Confirm Rejection"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
