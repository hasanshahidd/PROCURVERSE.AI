import { ReactNode, useState, useEffect } from "react";
import { useLocation } from "wouter";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  MessageSquare,
  CheckCircle,
  GitBranch,
  UserCheck,
  Activity,
  Workflow,
  Menu,
  X,
  ChevronLeft,
  LogOut,
  Settings,
  User,
  Package,
  UserPlus,
  Truck,
  TrendingUp,
  GitMerge,
  BarChart3,
  Star,
  ShieldCheck,
  AlertTriangle,
  FileSearch,
  DollarSign,
  ClipboardList,
  Zap,
  CreditCard,
  Clock,
  Timer,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";

interface MainLayoutProps {
  children: ReactNode;
}

interface NavItem {
  path: string;
  label: string;
  icon: React.ElementType;
  badge?: number;
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

// Available test users - must match MyApprovalsPage
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

export default function MainLayout({ children }: MainLayoutProps) {
  const [location, setLocation] = useLocation();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  
  // Get current user from localStorage or default to Diana Director
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
      try {
        const res = await apiFetch("/api/agentic/approval-chains");
        if (!res.ok) return DEFAULT_USERS;
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
      } catch {
        return DEFAULT_USERS;
      }
    },
    staleTime: 60000,
  });

  const availableUsers = approverUsers && approverUsers.length > 0 ? approverUsers : DEFAULT_USERS;

  // Sync user to localStorage whenever it changes
  useEffect(() => {
    localStorage.setItem("currentUser", JSON.stringify(currentUser));
    // Trigger a custom event so MyApprovalsPage can listen
    window.dispatchEvent(new CustomEvent("userChanged", { detail: currentUser }));
  }, [currentUser]);

  // Fetch pending approvals count
  const { data: pendingCount } = useQuery({
    queryKey: ["/api/agentic/pending-approvals/count"],
    queryFn: async () => {
      try {
        const res = await apiFetch("/api/agentic/pending-approvals/count");
        if (!res.ok) return { count: 0 };
        return await res.json();
      } catch {
        return { count: 0 };
      }
    },
    refetchInterval: 30000, // Refetch every 30 seconds
  });

  const navigationItems: NavItem[] = [
    {
      path: "/dashboard",
      label: "Dashboard",
      icon: LayoutDashboard,
    },
    {
      path: "/agentic-flow",
      label: "Agentic Flow",
      icon: Workflow,
    },
    {
      path: "/chat",
      label: "Chat",
      icon: MessageSquare,
    },
    {
      path: "/pending-approvals",
      label: "Pending Approvals",
      icon: CheckCircle,
      badge: pendingCount?.count || 0,
    },
    {
      path: "/approval-workflows",
      label: "Approval Workflows",
      icon: GitBranch,
    },
    {
      path: "/my-approvals",
      label: "My Approvals",
      icon: UserCheck,
    },
    {
      path: "/process",
      label: "Agent Process",
      icon: Activity,
    },
    {
      path: "/pipeline",
      label: "Pipeline",
      icon: Workflow,
    },
    {
      path: "/goods-receipt",
      label: "Goods Receipt",
      icon: Package,
    },
    {
      path: "/vendor-onboarding",
      label: "Vendor Onboarding",
      icon: UserPlus,
    },
    {
      path: "/delivery-tracking",
      label: "Delivery Tracking",
      icon: Truck,
    },
    {
      path: "/forecasting",
      label: "Forecasting",
      icon: TrendingUp,
    },
    {
      path: "/pipeline-visualizer",
      label: "Pipeline Visualizer",
      icon: GitMerge,
    },
    {
      path: "/spend-analytics",
      label: "Spend Analytics",
      icon: BarChart3,
    },
    {
      path: "/supplier-performance",
      label: "Supplier Performance",
      icon: Star,
    },
    {
      path: "/contracts",
      label: "Contracts",
      icon: ShieldCheck,
    },
    {
      path: "/system-health",
      label: "System Health",
      icon: Activity,
    },
    {
      path: "/risk-assessment",
      label: "Risk Assessment",
      icon: AlertTriangle,
    },
    {
      path: "/document-processing",
      label: "Doc Processing",
      icon: FileSearch,
    },
    {
      path: "/purchase-requisitions",
      label: "Purchase Requests",
      icon: ClipboardList,
    },
    {
      path: "/budget",
      label: "Budget Tracking",
      icon: DollarSign,
    },
    {
      path: "/anomaly-detection",
      label: "Anomaly Detection",
      icon: AlertTriangle,
    },
    {
      path: "/integrations",
      label: "Integrations",
      icon: Zap,
    },
    {
      path: "/payment-execution",
      label: "Payments",
      icon: CreditCard,
    },
    {
      path: "/aging-report",
      label: "Aging Report",
      icon: Clock,
    },
    {
      path: "/cycle-times",
      label: "Cycle Times",
      icon: Timer,
    },
  ];

  const handleLogout = () => {
    localStorage.removeItem("isAuthenticated");
    setLocation("/");
  };

  const SidebarContent = () => (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className={cn(
        "flex items-center justify-between p-4 border-b border-sidebar-border",
        isCollapsed && "justify-center"
      )}>
        {!isCollapsed && (
          <div>
            <h2 className="text-lg font-bold text-sidebar-foreground">
              Procurement AI
            </h2>
            <p className="text-xs text-sidebar-foreground/70">Smart Procurement Platform</p>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="hidden lg:flex text-sidebar-foreground hover:bg-sidebar-accent"
        >
          <ChevronLeft className={cn(
            "h-4 w-4 transition-transform",
            isCollapsed && "rotate-180"
          )} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIsMobileOpen(false)}
          className="lg:hidden text-sidebar-foreground hover:bg-sidebar-accent"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* User Profile Section */}
      {!isCollapsed && (
        <div className="p-4 border-b border-sidebar-border">
          <Card className="bg-white/10 backdrop-blur-sm border-white/20">
            <CardContent className="p-3 space-y-2">
              <div className="flex items-center gap-2">
                <div className="h-10 w-10 rounded-full bg-gradient-to-br from-white/20 to-white/10 flex items-center justify-center text-white font-semibold border-2 border-white/30">
                  {currentUser.name.split(' ').map(n => n[0]).join('')}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold truncate text-white">{currentUser.name}</p>
                  <p className="text-xs text-white/70 truncate">{currentUser.role}</p>
                </div>
              </div>
              <Select 
                value={currentUser.email} 
                onValueChange={(email) => {
                  const user = availableUsers.find((u) => u.email === email);
                  if (user) setCurrentUser(user);
                }}
              >
                <SelectTrigger className="w-full h-8 text-xs bg-white/10 border-white/20 text-white">
                  <SelectValue placeholder="Switch role..." />
                </SelectTrigger>
                <SelectContent>
                  {availableUsers.map((user) => (
                    <SelectItem key={user.email} value={user.email}>
                      <div className="flex items-center gap-2">
                        <User className="h-3 w-3" />
                        <span>{user.name} - {user.role}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-[10px] text-white/60 text-center">
                Switch to test different approval roles
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Navigation */}
      <ScrollArea className="flex-1 p-4">
        <nav className="space-y-2">
          {navigationItems.map((item) => {
            const Icon = item.icon;
            const isActive = location === item.path;
            
            return (
              <Button
                key={item.path}
                variant={isActive ? "default" : "ghost"}
                className={cn(
                  "w-full justify-start gap-3 text-sidebar-foreground",
                  isCollapsed && "justify-center px-2",
                  isActive && "bg-sidebar-primary text-sidebar-primary-foreground hover:bg-sidebar-primary",
                  !isActive && "hover:bg-sidebar-accent"
                )}
                onClick={() => {
                  setLocation(item.path);
                  setIsMobileOpen(false);
                }}
              >
                <Icon className="h-5 w-5 flex-shrink-0" />
                {!isCollapsed && (
                  <>
                    <span className="flex-1 text-left">{item.label}</span>
                    {item.badge !== undefined && item.badge > 0 && (
                      <Badge 
                        variant={isActive ? "secondary" : "default"}
                        className="ml-auto"
                      >
                        {item.badge}
                      </Badge>
                    )}
                  </>
                )}
              </Button>
            );
          })}
        </nav>
      </ScrollArea>

      {/* Footer */}
      <div className="p-4 border-t border-sidebar-border space-y-2">
        <Button
          variant="ghost"
          className={cn(
            "w-full justify-start gap-3 text-sidebar-foreground hover:bg-sidebar-accent",
            isCollapsed && "justify-center px-2",
            location === "/approval-settings" && "bg-sidebar-accent"
          )}
          onClick={() => {
            setLocation("/approval-settings");
            setIsMobileOpen(false);
          }}
        >
          <Settings className="h-5 w-5 flex-shrink-0" />
          {!isCollapsed && <span>Approval Settings</span>}
        </Button>
        <Button
          variant="ghost"
          className={cn(
            "w-full justify-start gap-3 text-sidebar-foreground hover:bg-sidebar-accent",
            isCollapsed && "justify-center px-2"
          )}
          onClick={handleLogout}
        >
          <LogOut className="h-5 w-5 flex-shrink-0" />
          {!isCollapsed && <span>Logout</span>}
        </Button>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-background">
      {/* Desktop Sidebar */}
      <aside
        className={cn(
          "hidden lg:flex flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-all duration-300",
          isCollapsed ? "w-20" : "w-64"
        )}
        style={{ backgroundColor: 'hsl(221, 83%, 25%)', color: 'white' }}
      >
        <SidebarContent />
      </aside>

      {/* Mobile Sidebar */}
      {isMobileOpen && (
        <>
          <div
            className="fixed inset-0 bg-background/80 backdrop-blur-sm z-40 lg:hidden"
            onClick={() => setIsMobileOpen(false)}
          />
          <aside 
            className="fixed inset-y-0 left-0 w-64 border-r border-sidebar-border bg-sidebar text-sidebar-foreground z-50 lg:hidden"
            style={{ backgroundColor: 'hsl(221, 83%, 25%)', color: 'white' }}
          >
            <SidebarContent />
          </aside>
        </>
      )}

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Mobile Header */}
        <header className="lg:hidden flex items-center justify-between p-4 border-b bg-card">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsMobileOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </Button>
          <h1 className="text-lg font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            Procurement AI
          </h1>
          <div className="w-10" /> {/* Spacer for centering */}
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto h-full">
          {children}
        </main>
      </div>
    </div>
  );
}
