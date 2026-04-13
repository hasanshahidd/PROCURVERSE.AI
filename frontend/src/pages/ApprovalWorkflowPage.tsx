import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Check,
  Clock,
  AlertCircle,
  RefreshCcw,
  Search,
  ChevronRight,
  User,
  DollarSign,
  Building2,
  X,
  ShoppingCart,
  ArrowLeft,
} from "lucide-react";
import { useState, useEffect, useRef, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";

interface ApprovalStep {
  approval_level: number;
  approver_name: string;
  approver_email: string;
  status: "pending" | "approved" | "rejected";
  approved_at?: string;
  rejection_reason?: string;
  notes?: string;
}

interface ApprovalWorkflow {
  pr_number: string;
  department: string;
  total_amount: number;
  requester_name: string;
  current_approval_level: number;
  workflow_status: "in_progress" | "completed" | "rejected";
  created_at: string;
  updated_at: string;
  odoo_po_id?: number; // Odoo Purchase Order ID if workflow completed
  request_data?: Record<string, any>;
  steps: ApprovalStep[];
}

const LEVEL_LABELS: { [key: number]: string } = {
  1: "Manager",
  2: "Director",
  3: "VP/CFO",
};

export default function ApprovalWorkflowPage() {
  const API_BASE_URL = import.meta.env.VITE_API_URL || "";

  // Read ?pr= and ?session= query params
  const queryParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const highlightPR = queryParams.get("pr") || "";
  const sessionId = queryParams.get("session") || "";

  const [searchTerm, setSearchTerm] = useState(highlightPR);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [departmentFilter, setDepartmentFilter] = useState<string>("all");

  // Auto-scroll to highlighted PR card
  const highlightRef = useRef<HTMLDivElement>(null);
  const didScroll = useRef(false);

  // Fetch workflows
  const { data: workflows, isLoading, error, refetch } = useQuery<ApprovalWorkflow[]>({
    queryKey: ["/api/agentic/approval-workflows"],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/agentic/approval-workflows`);
      if (!res.ok) throw new Error("Failed to fetch workflows");
      const data = await res.json();
      return data.workflows || [];
    },
    refetchInterval: 15000, // Refetch every 15 seconds
  });

  // Auto-scroll to the highlighted PR once data loads
  useEffect(() => {
    if (highlightPR && workflows && workflows.length > 0 && !didScroll.current) {
      didScroll.current = true;
      // Small delay to let the DOM render
      setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 200);
    }
  }, [highlightPR, workflows]);

  // Filter workflows
  const filteredWorkflows = workflows?.filter((workflow) => {
    const matchesSearch =
      workflow.pr_number.toLowerCase().includes(searchTerm.toLowerCase()) ||
      workflow.requester_name.toLowerCase().includes(searchTerm.toLowerCase());
    
    const matchesStatus =
      statusFilter === "all" || workflow.workflow_status === statusFilter;
    
    const matchesDepartment =
      departmentFilter === "all" || workflow.department === departmentFilter;

    return matchesSearch && matchesStatus && matchesDepartment;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return <Badge className="bg-green-500">Completed</Badge>;
      case "rejected":
        return <Badge variant="destructive">Rejected</Badge>;
      case "in_progress":
        return <Badge variant="secondary">In Progress</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  const getStepStatusIcon = (status: string) => {
    switch (status) {
      case "approved":
        return <Check className="h-5 w-5 text-green-500" />;
      case "rejected":
        return <X className="h-5 w-5 text-red-500" />;
      case "pending":
        return <Clock className="h-5 w-5 text-yellow-500" />;
      default:
        return <Clock className="h-5 w-5 text-gray-400" />;
    }
  };

  const calculateProgress = (workflow: ApprovalWorkflow) => {
    const totalSteps = workflow.steps.length;
    const completedSteps = workflow.steps.filter((s) => s.status === "approved").length;
    return (completedSteps / totalSteps) * 100;
  };

  const departments = Array.from(
    new Set(workflows?.map((w) => w.department) || [])
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <RefreshCcw className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Loading approval workflows...</p>
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
            Failed to load approval workflows. Please check your connection and try again.
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
          <h1 className="text-2xl font-bold tracking-tight">Purchase Requisition Workflows</h1>
          <p className="text-muted-foreground text-sm">
            <strong>Track approval progress</strong> for all purchase requisitions. Each PR goes through 3 levels: Manager → Director → VP/CFO
          </p>
          <p className="text-xs text-muted-foreground mt-1 flex items-center gap-2">
            <AlertCircle className="h-4 w-4" />
            This shows all company PRs. For items needing your approval, go to "My Approvals" page.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCcw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Session back-link banner */}
      {sessionId && (
        <Alert className="border-blue-300 bg-blue-50 dark:bg-blue-950/30 dark:border-blue-800">
          <AlertDescription className="flex items-center justify-between">
            <span className="text-sm text-blue-800 dark:text-blue-200">
              Viewing approval lifecycle for an active P2P session
              {highlightPR && <> &mdash; <strong>{highlightPR}</strong></>}
            </span>
            <Button variant="outline" size="sm" asChild>
              <a href={`/sessions/${sessionId}`} className="gap-1.5">
                <ArrowLeft className="h-3.5 w-3.5" />
                Return to Session
              </a>
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Filters</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          <div className="flex-1 min-w-[200px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by PR number or requester..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="in_progress">In Progress</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="rejected">Rejected</SelectItem>
            </SelectContent>
          </Select>
          <Select value={departmentFilter} onValueChange={setDepartmentFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Department" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Departments</SelectItem>
              {departments.map((dept) => (
                <SelectItem key={dept} value={dept}>
                  {dept}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {/* Workflows List */}
      {!filteredWorkflows || filteredWorkflows.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <AlertCircle className="h-16 w-16 text-muted-foreground mb-4" />
            <h3 className="text-xl font-semibold mb-2">No Workflows Found</h3>
            <p className="text-muted-foreground text-center max-w-md">
              {searchTerm || statusFilter !== "all" || departmentFilter !== "all"
                ? "No workflows match your filters. Try adjusting your search criteria."
                : "No approval workflows yet. Workflows will appear here when PRs are routed for approval."}
            </p>
          </CardContent>
        </Card>
      ) : (
        <ScrollArea className="h-[calc(100vh-350px)]">
          <div className="space-y-4">
            {filteredWorkflows.map((workflow) => {
              const isHighlighted = highlightPR && workflow.pr_number === highlightPR;
              return (
              <Card
                key={workflow.pr_number}
                ref={isHighlighted ? highlightRef : undefined}
                className={`hover:shadow-lg transition-shadow ${isHighlighted ? "ring-2 ring-blue-500 border-blue-400" : ""}`}
              >
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="space-y-2 flex-1">
                      <div className="flex items-center gap-3">
                        <CardTitle className="text-xl">{workflow.pr_number}</CardTitle>
                        {getStatusBadge(workflow.workflow_status)}
                        <Badge variant="outline" className="gap-1">
                          <Building2 className="h-3 w-3" />
                          {workflow.department}
                        </Badge>
                        {/* Show PO badge if created in Odoo */}
                        {workflow.odoo_po_id && (
                          <Badge className="bg-green-600 gap-1">
                            <ShoppingCart className="h-3 w-3" />
                            PO #{workflow.odoo_po_id}
                          </Badge>
                        )}
                      </div>
                      <CardDescription className="flex flex-wrap items-center gap-3">
                        <span className="flex items-center gap-1">
                          <User className="h-3 w-3" />
                          {workflow.requester_name}
                        </span>
                        <span>•</span>
                        <span className="flex items-center gap-1">
                          <DollarSign className="h-3 w-3" />
                          {new Intl.NumberFormat("en-US", {
                            style: "currency",
                            currency: "USD",
                          }).format(workflow.total_amount)}
                        </span>
                        <span>•</span>
                        <span>Created {format(new Date(workflow.created_at), "MMM d, yyyy")}</span>
                      </CardDescription>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-4">
                  {/* Progress Bar */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">
                        Progress: {workflow.steps.filter((s) => s.status === "approved").length}/
                        {workflow.steps.length} steps completed
                      </span>
                      <span className="font-semibold">
                        {calculateProgress(workflow).toFixed(0)}%
                      </span>
                    </div>
                    <Progress value={calculateProgress(workflow)} className="h-2" />
                  </div>

                  {/* Approval Steps */}
                  <div className="space-y-3">
                    {workflow.steps.map((step, index) => (
                      <div key={index} className="flex items-start gap-4">
                        {/* Step Icon */}
                        <div className="flex flex-col items-center">
                          <div className="flex items-center justify-center w-10 h-10 rounded-full border-2 bg-background">
                            {getStepStatusIcon(step.status)}
                          </div>
                          {index < workflow.steps.length - 1 && (
                            <div className="w-0.5 h-12 bg-border my-1" />
                          )}
                        </div>

                        {/* Step Content */}
                        <div className="flex-1 pb-4">
                          <div className="flex items-center justify-between mb-1">
                            <div className="flex items-center gap-2">
                              <h4 className="font-semibold">
                                Step {step.approval_level}: {LEVEL_LABELS[step.approval_level]}
                              </h4>
                              {step.status === "pending" &&
                                workflow.current_approval_level === step.approval_level && (
                                  <Badge variant="secondary" className="gap-1">
                                    <ChevronRight className="h-3 w-3" />
                                    Current
                                  </Badge>
                                )}
                            </div>
                            {step.approved_at && (
                              <span className="text-xs text-muted-foreground">
                                {format(new Date(step.approved_at), "MMM d, HH:mm")}
                              </span>
                            )}
                          </div>
                          <p className="text-sm text-muted-foreground mb-1">
                            {step.approver_name} ({step.approver_email})
                          </p>
                          {step.notes && (
                            <p className="text-sm bg-muted p-2 rounded mt-2">
                              <span className="font-medium">Notes:</span> {step.notes}
                            </p>
                          )}
                          {step.rejection_reason && (
                            <p className="text-sm bg-destructive/10 text-destructive p-2 rounded mt-2">
                              <span className="font-medium">Rejected:</span> {step.rejection_reason}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Full saved payload snapshot for auditing */}
                  <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
                    <h5 className="text-sm font-semibold">Saved Data Snapshot</h5>
                    <div className="text-xs text-muted-foreground space-y-1">
                      <p>
                        Vendor: <span className="font-medium text-foreground">
                          {String(
                            workflow.request_data?.context?.raw_pr_data?.vendor_name
                            || workflow.request_data?.context?.raw_pr_data?.selected_vendor_name
                            || "Not provided"
                          )}
                        </span>
                      </p>
                      <p>
                        Product/Category: <span className="font-medium text-foreground">
                          {String(
                            workflow.request_data?.context?.raw_pr_data?.product_name
                            || workflow.request_data?.context?.raw_pr_data?.category
                            || "Not provided"
                          )}
                        </span>
                      </p>
                      <p>
                        Quantity: <span className="font-medium text-foreground">
                          {String(workflow.request_data?.context?.raw_pr_data?.quantity ?? "Not provided")}
                        </span>
                      </p>
                      <p>
                        Budget Category: <span className="font-medium text-foreground">
                          {String(workflow.request_data?.context?.raw_pr_data?.budget_category || "Not provided")}
                        </span>
                      </p>
                      <p>
                        Justification: <span className="font-medium text-foreground">
                          {String(workflow.request_data?.context?.raw_pr_data?.justification || "Not provided")}
                        </span>
                      </p>
                    </div>

                    {workflow.request_data?.odoo_po_data && (
                      <div className="pt-2 border-t">
                        <h6 className="text-xs font-semibold mb-1">Odoo PO Data</h6>
                        <div className="text-xs text-muted-foreground space-y-1">
                          <p>PO ID: <span className="font-medium text-foreground">{String(workflow.request_data.odoo_po_data.odoo_po_id ?? workflow.odoo_po_id)}</span></p>
                          <p>Vendor: <span className="font-medium text-foreground">{String(workflow.request_data.odoo_po_data.vendor_name || "N/A")}</span></p>
                          <p>Product: <span className="font-medium text-foreground">{String(workflow.request_data.odoo_po_data.product_name || "N/A")}</span></p>
                          <p>Quantity: <span className="font-medium text-foreground">{String(workflow.request_data.odoo_po_data.quantity ?? "N/A")}</span></p>
                          <p>Origin PR: <span className="font-medium text-foreground">{String(workflow.request_data.odoo_po_data.origin_pr_number || workflow.pr_number)}</span></p>
                        </div>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
              );
            })}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
