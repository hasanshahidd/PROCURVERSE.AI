import { useQuery } from "@tanstack/react-query";
import { Settings, Shield, DollarSign, Users, CheckCircle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface ApprovalChain {
  id: number;
  department: string;
  budget_threshold: number;
  approval_level: number;
  approver_email: string;
  approver_name: string;
  status: string;
}

const LEVEL_LABELS: { [key: number]: string } = {
  1: "Manager",
  2: "Director",
  3: "VP/CFO",
};

const LEVEL_COLORS: { [key: number]: string } = {
  1: "bg-blue-500",
  2: "bg-purple-500",
  3: "bg-orange-500",
};

export default function ApprovalSettingsPage() {
  const API_BASE_URL = import.meta.env.VITE_API_URL || "";
  // Fetch approval chains from database
  const { data: chains, isLoading } = useQuery<ApprovalChain[]>({
    queryKey: ["/api/agentic/approval-chains"],
    queryFn: async () => {
      // This endpoint needs to be created in backend
      const res = await fetch(`${API_BASE_URL}/api/agentic/approval-chains`);
      if (!res.ok) throw new Error("Failed to fetch approval chains");
      const data = await res.json();
      return data.chains || [];
    },
  });

  // Group by department
  const chainsByDepartment = chains?.reduce((acc, chain) => {
    if (!acc[chain.department]) {
      acc[chain.department] = [];
    }
    acc[chain.department].push(chain);
    return acc;
  }, {} as Record<string, ApprovalChain[]>);

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
          <Settings className="h-7 w-7" />
          Approval System Configuration
        </h1>
        <p className="text-muted-foreground text-sm">
          View how the <strong>AI Agent</strong> automatically routes purchase requisitions based on department and amount
        </p>
      </div>

      {/* Info Alert */}
      <Alert>
        <Shield className="h-4 w-4" />
        <AlertDescription>
          <strong>How It Works:</strong> When a PR is created, the <strong>ApprovalRoutingAgent</strong> reads these rules
          and automatically assigns the correct approvers based on department + budget thresholds ⚡
        </AlertDescription>
      </Alert>

      {/* Explanation Card */}
      <Card className="border-2 border-primary/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Approval Routing Logic
          </CardTitle>
          <CardDescription>
            The agent uses a 3-level approval hierarchy based on amount
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-start gap-3">
            <Badge className="bg-blue-500 mt-1">Level 1: Manager</Badge>
            <div>
              <p className="font-semibold">Under $10,000</p>
              <p className="text-sm text-muted-foreground">
                Manager only. Quick approval for small purchases.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Badge className="bg-purple-500 mt-1">Level 2: Director</Badge>
            <div>
              <p className="font-semibold">$10,000 - $50,000</p>
              <p className="text-sm text-muted-foreground">
                Manager approval → Director approval. 2-step process.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <Badge className="bg-orange-500 mt-1">Level 3: VP/CFO</Badge>
            <div>
              <p className="font-semibold">Over $50,000</p>
              <p className="text-sm text-muted-foreground">
                Manager → Director → VP/CFO. Full 3-step approval for large purchases.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Department Approval Chains */}
      {isLoading ? (
        <Card>
          <CardContent className="py-16 text-center">
            <p className="text-muted-foreground">Loading approval chains...</p>
          </CardContent>
        </Card>
      ) : (
        <ScrollArea className="h-[calc(100vh-500px)]">
          <div className="grid gap-6 md:grid-cols-2">
            {chainsByDepartment &&
              Object.entries(chainsByDepartment)
                .sort()
                .map(([department, deptChains]) => (
                  <Card key={department} className="hover:shadow-lg transition-shadow">
                    <CardHeader>
                      <CardTitle className="flex items-center justify-between">
                        <span>{department} Department</span>
                        <Badge variant="outline">{deptChains.length} levels</Badge>
                      </CardTitle>
                      <CardDescription>
                        Approval chain configured for this department
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {deptChains
                        .sort((a, b) => a.approval_level - b.approval_level)
                        .map((chain, index) => (
                          <div
                            key={chain.id}
                            className="flex items-start gap-4 p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                          >
                            {/* Level Badge */}
                            <div className="flex flex-col items-center gap-1">
                              <div
                                className={`w-10 h-10 rounded-full ${
                                  LEVEL_COLORS[chain.approval_level]
                                } flex items-center justify-center text-white font-bold`}
                              >
                                {chain.approval_level}
                              </div>
                              {index < deptChains.length - 1 && (
                                <div className="w-0.5 h-8 bg-border" />
                              )}
                            </div>

                            {/* Approver Info */}
                            <div className="flex-1">
                              <div className="flex items-center gap-2 mb-1">
                                <Badge className={LEVEL_COLORS[chain.approval_level]}>
                                  {LEVEL_LABELS[chain.approval_level]}
                                </Badge>
                                <Badge variant="outline" className="gap-1">
                                  <DollarSign className="h-3 w-3" />
                                  {chain.budget_threshold >= 100000
                                    ? `${(chain.budget_threshold / 1000).toFixed(0)}K+`
                                    : `${(chain.budget_threshold / 1000).toFixed(0)}K`}
                                </Badge>
                              </div>
                              <p className="font-semibold text-sm">{chain.approver_name}</p>
                              <p className="text-xs text-muted-foreground">
                                {chain.approver_email}
                              </p>
                            </div>

                            {/* Status */}
                            <div className="text-right">
                              {chain.status === "approved" && (
                                <CheckCircle className="h-5 w-5 text-green-500" />
                              )}
                            </div>
                          </div>
                        ))}
                    </CardContent>
                  </Card>
                ))}
          </div>
        </ScrollArea>
      )}

      {/* Example Scenarios */}
      <Card className="border-2 border-green-500/20">
        <CardHeader>
          <CardTitle className="text-green-600 dark:text-green-400">
            📋 Example Scenarios
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="bg-muted p-3 rounded-md">
            <p className="font-semibold mb-1">Scenario 1: $8,000 IT Purchase</p>
            <p className="text-sm text-muted-foreground">
              Agent routes to: <strong>IT Manager</strong> only (Level 1)
            </p>
          </div>
          <div className="bg-muted p-3 rounded-md">
            <p className="font-semibold mb-1">Scenario 2: $35,000 Finance Purchase</p>
            <p className="text-sm text-muted-foreground">
              Agent routes to: <strong>Finance Manager</strong> → <strong>Finance Director</strong>{" "}
              (Levels 1-2)
            </p>
          </div>
          <div className="bg-muted p-3 rounded-md">
            <p className="font-semibold mb-1">Scenario 3: $120,000 Operations Purchase</p>
            <p className="text-sm text-muted-foreground">
              Agent routes to: <strong>Ops Manager</strong> → <strong>Ops Director</strong> → <strong>COO</strong>{" "}
              (All 3 levels)
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Future Enhancement Note */}
      <Alert>
        <Settings className="h-4 w-4" />
        <AlertDescription>
          <strong>Future Enhancement:</strong> Add ability to edit approval chains, add custom rules,
          and configure email notifications for approvers.
        </AlertDescription>
      </Alert>
    </div>
  );
}
