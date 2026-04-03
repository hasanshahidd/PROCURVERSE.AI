import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Check,
  Clock,
  RefreshCcw,
  AlertCircle,
  BarChart3,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
  User,
  DollarSign,
  Building2,
  FileText,
  ShoppingCart,
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface MyApprovalItem {
  pr_number: string;
  department: string;
  total_amount: number;
  requester_name: string;
  approval_level: number;
  approval_level_name: string;
  request_data: any;
  created_at: string;
  days_pending: number;
}

interface ApprovalHistory {
  pr_number: string;
  department: string;
  total_amount: number;
  requester_name: string;
  approval_level_name: string;
  decision: "approved" | "rejected";
  decided_at: string;
  notes?: string;
  rejection_reason?: string;
}

interface ApprovalStats {
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  rejection_rate: number;
  avg_decision_time_hours: number;
}

interface UserProfile {
  name: string;
  email: string;
  role: string;
}

interface ApprovalChainRow {
  approver_name: string;
  approver_email: string;
  approval_level: number;
}

// Available test users
const DEFAULT_USERS: UserProfile[] = [
  { name: "Mik Jhonson", email: "mike.manager@company.com", role: "Manager" },
  { name: "Diana Director", email: "diana.director@company.com", role: "Director" },
  { name: "Victor VP", email: "victor.vp@company.com", role: "VP/CFO" },
  { name: "Finance Manager", email: "finance.manager@company.com", role: "Manager" },
  { name: "Finance Director", email: "finance.director@company.com", role: "Director" },
  { name: "Operations Manager", email: "ops.manager@company.com", role: "Manager" },
  { name: "Operations Director", email: "ops.director@company.com", role: "Director" },
  { name: "COO", email: "coo@company.com", role: "VP/CFO" },
];

const levelToRole: Record<number, string> = {
  1: "Manager",
  2: "Director",
  3: "VP/CFO",
};

export default function MyApprovalsPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const API_BASE_URL = import.meta.env.VITE_API_URL || "";
  const [selectedPR, setSelectedPR] = useState<MyApprovalItem | null>(null);
  const [actionType, setActionType] = useState<"approve" | "reject" | null>(null);
  const [notes, setNotes] = useState("");
  const [expandedPRs, setExpandedPRs] = useState<Set<string>>(new Set());
  
  // Get current user from localStorage (synced with MainLayout)
  const [currentUser, setCurrentUser] = useState<UserProfile>(() => {
    const stored = localStorage.getItem("currentUser");
    if (stored) {
      try {
        return JSON.parse(stored);
      } catch {
        return DEFAULT_USERS[1];
      }
    }
    return DEFAULT_USERS[1]; // Default to Diana Director
  });

  const { data: approverUsers } = useQuery<UserProfile[]>({
    queryKey: ["/api/agentic/approval-chains/users"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/agentic/approval-chains`);
      if (!res.ok) {
        return DEFAULT_USERS;
      }

      const data = await res.json();
      const chainRows = (data.chains || []) as ApprovalChainRow[];

      const byEmail = new Map<string, UserProfile>();
      for (const user of DEFAULT_USERS) {
        byEmail.set(user.email.toLowerCase(), user);
      }

      for (const row of chainRows) {
        const email = (row.approver_email || "").trim().toLowerCase();
        if (!email) continue;
        byEmail.set(email, {
          name: row.approver_name || email,
          email,
          role: levelToRole[row.approval_level] || "Approver",
        });
      }

      return Array.from(byEmail.values()).sort((a, b) => a.name.localeCompare(b.name));
    },
    staleTime: 60000,
  });

  const availableUsers = approverUsers && approverUsers.length > 0 ? approverUsers : DEFAULT_USERS;

  // Listen for user changes from MainLayout
  useEffect(() => {
    const handleUserChange = (e: CustomEvent) => {
      setCurrentUser(e.detail);
    };
    window.addEventListener("userChanged", handleUserChange as EventListener);
    return () => window.removeEventListener("userChanged", handleUserChange as EventListener);
  }, []);

  // Sync to localStorage when changed locally
  useEffect(() => {
    localStorage.setItem("currentUser", JSON.stringify(currentUser));
  }, [currentUser]);

  // Fetch pending approvals
  const { data: pendingApprovals, isLoading: loadingPending } = useQuery<MyApprovalItem[]>({
    queryKey: ["/api/agentic/my-approvals", currentUser.email, "pending"],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE_URL}/api/agentic/my-approvals/${currentUser.email}?status=pending`
      );
      if (!res.ok) throw new Error("Failed to fetch pending approvals");
      const data = await res.json();
      return data.approvals || [];
    },
    refetchInterval: 10000, // Refetch every 10 seconds
  });

  // Fetch approval history
  const { data: history, isLoading: loadingHistory } = useQuery<ApprovalHistory[]>({
    queryKey: ["/api/agentic/my-approvals", currentUser.email, "history"],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE_URL}/api/agentic/my-approvals/${currentUser.email}?status=history`
      );
      if (!res.ok) throw new Error("Failed to fetch history");
      const data = await res.json();
      return data.history || [];
    },
  });

  // Fetch statistics
  const { data: stats } = useQuery<ApprovalStats>({
    queryKey: ["/api/agentic/my-approvals", currentUser.email, "stats"],
    queryFn: async () => {
      const res = await fetch(
        `${API_BASE_URL}/api/agentic/my-approvals/${currentUser.email}/stats`
      );
      if (!res.ok) throw new Error("Failed to fetch stats");
      return await res.json();
    },
  });

  // Approve mutation
  const approveMutation = useMutation({
    mutationFn: async ({ prNumber, notes }: { prNumber: string; notes?: string }) => {
      const res = await fetch(
        `${API_BASE_URL}/api/agentic/approval-workflows/${prNumber}/approve`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Approver-Email": currentUser.email,
          },
          body: JSON.stringify({
            approver_email: currentUser.email,
            notes,
          }),
        }
      );
      if (!res.ok) throw new Error("Failed to approve");
      return await res.json();
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/my-approvals"] });
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/approval-workflows"] });
      
      // Check if workflow completed and PO was created in Odoo
      if (response.completed && response.odoo_po_id) {
        toast({
          title: "🎉 Purchase Order Created!",
          description: (
            <div className="space-y-2 mt-2">
              <div className="flex items-center gap-2">
                <ShoppingCart className="h-4 w-4" />
                <span className="font-semibold">PO #{response.odoo_po_id}</span>
              </div>
              <div className="text-sm">
                <div>✅ All approvals complete</div>
                <div>📦 Purchase order created in Odoo</div>
                <div>🔗 PR: {response.pr_number}</div>
              </div>
            </div>
          ),
          duration: 10000, // Show for 10 seconds
        });
      }
      
      setSelectedPR(null);
      setActionType(null);
      setNotes("");
    },
  });

  // Reject mutation
  const rejectMutation = useMutation({
    mutationFn: async ({ prNumber, reason }: { prNumber: string; reason: string }) => {
      const res = await fetch(
        `${API_BASE_URL}/api/agentic/approval-workflows/${prNumber}/reject`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Approver-Email": currentUser.email,
          },
          body: JSON.stringify({
            approver_email: currentUser.email,
            rejection_reason: reason,
          }),
        }
      );
      if (!res.ok) throw new Error("Failed to reject");
      return await res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/my-approvals"] });
      queryClient.invalidateQueries({ queryKey: ["/api/agentic/approval-workflows"] });
      setSelectedPR(null);
      setActionType(null);
      setNotes("");
    },
  });

  const handleAction = (pr: MyApprovalItem, action: "approve" | "reject") => {
    setSelectedPR(pr);
    setActionType(action);
  };

  const handleConfirmAction = () => {
    if (!selectedPR) return;

    if (actionType === "approve") {
      approveMutation.mutate({ prNumber: selectedPR.pr_number, notes });
    } else if (actionType === "reject") {
      if (!notes.trim()) {
        alert("Please provide a reason for rejection");
        return;
      }
      rejectMutation.mutate({ prNumber: selectedPR.pr_number, reason: notes });
    }
  };

  const toggleExpanded = (prNumber: string) => {
    const newExpanded = new Set(expandedPRs);
    if (newExpanded.has(prNumber)) {
      newExpanded.delete(prNumber);
    } else {
      newExpanded.add(prNumber);
    }
    setExpandedPRs(newExpanded);
  };

  const getUrgencyBadge = (daysPending: number) => {
    if (daysPending >= 5) {
      return <Badge variant="destructive">URGENT ({daysPending}d)</Badge>;
    } else if (daysPending >= 3) {
      return <Badge className="bg-yellow-500">High Priority ({daysPending}d)</Badge>;
    } else {
      return <Badge variant="secondary">{daysPending}d pending</Badge>;
    }
  };

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">My Approvals</h1>
          <p className="text-muted-foreground text-sm flex items-center gap-2">
            <User className="h-4 w-4" />
            {currentUser.name} ({currentUser.role})
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex flex-col items-end">
            <label className="text-xs text-muted-foreground mb-1">Switch User (Testing)</label>
            <Select 
              value={currentUser.email} 
              onValueChange={(email) => {
                const user = availableUsers.find((u) => u.email === email);
                if (user) setCurrentUser(user);
              }}
            >
              <SelectTrigger className="w-[240px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {availableUsers.map((user) => (
                  <SelectItem key={user.email} value={user.email}>
                    {user.name} - {user.role}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Statistics Cards */}
      {stats && (
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Pending Approvals</CardTitle>
              <Clock className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.pending_count}</div>
              <p className="text-xs text-muted-foreground">Awaiting your decision</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Approved</CardTitle>
              <CheckCircle className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.approved_count}</div>
              <p className="text-xs text-muted-foreground">Total approved</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Rejected</CardTitle>
              <XCircle className="h-4 w-4 text-red-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.rejected_count}</div>
              <p className="text-xs text-muted-foreground">
                {stats.rejection_rate.toFixed(1)}% rejection rate
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Avg Response Time</CardTitle>
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.avg_decision_time_hours.toFixed(1)}h</div>
              <p className="text-xs text-muted-foreground">Average decision time</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tabs */}
      <Tabs defaultValue="pending" className="space-y-4">
        <TabsList>
          <TabsTrigger value="pending" className="gap-2">
            <Clock className="h-4 w-4" />
            Pending ({pendingApprovals?.length || 0})
          </TabsTrigger>
          <TabsTrigger value="history" className="gap-2">
            <FileText className="h-4 w-4" />
            History ({history?.length || 0})
          </TabsTrigger>
        </TabsList>

        {/* Pending Approvals Tab */}
        <TabsContent value="pending" className="space-y-4">
          {loadingPending ? (
            <Card>
              <CardContent className="flex items-center justify-center py-16">
                <RefreshCcw className="h-8 w-8 animate-spin text-muted-foreground" />
              </CardContent>
            </Card>
          ) : !pendingApprovals || pendingApprovals.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <Check className="h-16 w-16 text-green-500 mb-4" />
                <h3 className="text-xl font-semibold mb-2">All Caught Up!</h3>
                <p className="text-muted-foreground">No pending approvals at this time.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {pendingApprovals.map((approval) => (
                  <Card key={approval.pr_number} className="hover:shadow-lg transition-shadow">
                    <CardHeader>
                      <div className="flex items-start justify-between">
                        <div className="space-y-2 flex-1">
                          <div className="flex items-center gap-3">
                            <CardTitle className="text-xl">{approval.pr_number}</CardTitle>
                            {getUrgencyBadge(approval.days_pending)}
                            <Badge variant="outline" className="gap-1">
                              <Building2 className="h-3 w-3" />
                              {approval.department}
                            </Badge>
                          </div>
                          <CardDescription className="flex flex-wrap items-center gap-3">
                            <span className="flex items-center gap-1">
                              <User className="h-3 w-3" />
                              {approval.requester_name}
                            </span>
                            <span>•</span>
                            <span className="flex items-center gap-1">
                              <DollarSign className="h-3 w-3" />
                              {new Intl.NumberFormat("en-US", {
                                style: "currency",
                                currency: "USD",
                              }).format(approval.total_amount)}
                            </span>
                            <span>•</span>
                            <span>
                              Requires {approval.approval_level_name} approval
                            </span>
                            <span>•</span>
                            <span>
                              Created {format(new Date(approval.created_at), "MMM d, yyyy")}
                            </span>
                          </CardDescription>
                        </div>
                      </div>
                    </CardHeader>

                    <CardContent className="space-y-4">
                      {/* Request Details */}
                      <Collapsible open={expandedPRs.has(approval.pr_number)}>
                        <CollapsibleTrigger
                          onClick={() => toggleExpanded(approval.pr_number)}
                          className="flex items-center gap-2 text-sm font-medium hover:underline"
                        >
                          {expandedPRs.has(approval.pr_number) ? (
                            <ChevronUp className="h-4 w-4" />
                          ) : (
                            <ChevronDown className="h-4 w-4" />
                          )}
                          View Request Details
                        </CollapsibleTrigger>
                        <CollapsibleContent className="mt-2">
                          <div className="border p-4 rounded text-sm space-y-2">
                            <pre className="whitespace-pre-wrap font-mono text-xs overflow-x-auto">
                              {JSON.stringify(approval.request_data, null, 2)}
                            </pre>
                          </div>
                        </CollapsibleContent>
                      </Collapsible>

                      {/* Action Buttons */}
                      <div className="flex gap-3">
                        <Button
                          onClick={() => handleAction(approval, "approve")}
                          className="flex-1"
                          size="lg"
                        >
                          <Check className="h-4 w-4 mr-2" />
                          Approve
                        </Button>
                        <Button
                          onClick={() => handleAction(approval, "reject")}
                          variant="destructive"
                          className="flex-1"
                          size="lg"
                        >
                          <XCircle className="h-4 w-4 mr-2" />
                          Reject
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
          )}
        </TabsContent>

        {/* History Tab */}
        <TabsContent value="history" className="space-y-4">
          {loadingHistory ? (
            <Card>
              <CardContent className="flex items-center justify-center py-16">
                <RefreshCcw className="h-8 w-8 animate-spin text-muted-foreground" />
              </CardContent>
            </Card>
          ) : !history || history.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <AlertCircle className="h-16 w-16 text-muted-foreground mb-4" />
                <h3 className="text-xl font-semibold mb-2">No History Yet</h3>
                <p className="text-muted-foreground">
                  Your approval history will appear here once you've made decisions.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {history.map((item) => (
                  <Card key={`${item.pr_number}-${item.decided_at}`}>
                    <CardContent className="pt-6">
                      <div className="flex items-start justify-between">
                        <div className="space-y-1 flex-1">
                          <div className="flex items-center gap-3">
                            <h4 className="font-semibold">{item.pr_number}</h4>
                            {item.decision === "approved" ? (
                              <Badge className="bg-green-500">
                                <CheckCircle className="h-3 w-3 mr-1" />
                                Approved
                              </Badge>
                            ) : (
                              <Badge variant="destructive">
                                <XCircle className="h-3 w-3 mr-1" />
                                Rejected
                              </Badge>
                            )}
                            <Badge variant="outline">
                              {item.approval_level_name}
                            </Badge>
                          </div>
                          <p className="text-sm text-muted-foreground flex flex-wrap items-center gap-2">
                            <span>{item.department}</span>
                            <span>•</span>
                            <span>{item.requester_name}</span>
                            <span>•</span>
                            <span>
                              {new Intl.NumberFormat("en-US", {
                                style: "currency",
                                currency: "USD",
                              }).format(item.total_amount)}
                            </span>
                            <span>•</span>
                            <span>{format(new Date(item.decided_at), "MMM d, yyyy HH:mm")}</span>
                          </p>
                          {item.notes && (
                            <p className="text-sm border p-2 rounded mt-2">
                              <span className="font-medium">Notes:</span> {item.notes}
                            </p>
                          )}
                          {item.rejection_reason && (
                            <p className="text-sm bg-destructive/10 text-destructive p-2 rounded mt-2">
                              <span className="font-medium">Reason:</span> {item.rejection_reason}
                            </p>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Action Dialog */}
      <Dialog open={!!selectedPR} onOpenChange={(open) => !open && setSelectedPR(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {actionType === "approve" ? "Approve" : "Reject"} {selectedPR?.pr_number}
            </DialogTitle>
            <DialogDescription>
              {actionType === "approve"
                ? "You can optionally add notes to your approval."
                : "Please provide a reason for rejecting this purchase requisition."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <Textarea
              placeholder={
                actionType === "approve"
                  ? "Add notes (optional)..."
                  : "Reason for rejection (required)..."
              }
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelectedPR(null)}>
              Cancel
            </Button>
            <Button
              onClick={handleConfirmAction}
              variant={actionType === "approve" ? "default" : "destructive"}
              disabled={approveMutation.isPending || rejectMutation.isPending}
            >
              {approveMutation.isPending || rejectMutation.isPending ? (
                <RefreshCcw className="h-4 w-4 mr-2 animate-spin" />
              ) : actionType === "approve" ? (
                <Check className="h-4 w-4 mr-2" />
              ) : (
                <XCircle className="h-4 w-4 mr-2" />
              )}
              Confirm {actionType === "approve" ? "Approval" : "Rejection"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
