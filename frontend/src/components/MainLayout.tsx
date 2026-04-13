import { ReactNode, useState, useEffect, useCallback, useMemo } from "react";
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
  ChevronDown,
  ChevronRight,
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
  Upload,
  CreditCard,
  Clock,
  Timer,
  Brain,
  Database,
  Layers,
  type LucideIcon,
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
  /** P2P pipeline step number — shows a "Step N" badge on the sidebar item */
  p2pStep?: number;
  /**
   * Layer 1 / Layer 3 — gate awareness. When the polling endpoint
   * /api/sessions/gates/pending reports at least one open gate of this type,
   * the sidebar item gets a red dot. Click goes to the matching session if
   * exactly one is open, otherwise to the filtered sessions list.
   */
  p2pGateType?: "grn" | "approval" | "payment_release" | "three_way_match" | "vendor_selection";
}

interface PendingGate {
  gate_id: string;
  session_id: string;
  gate_type: string;
  status: string;
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
  // ── Matches backend users + approval_rules tables ──
  { name: "AP Manager", email: "ap.manager@procure.ai", role: "Manager" },
  { name: "Finance Head", email: "finance@procure.ai", role: "Director" },
  { name: "Procurement Manager", email: "procurement@procure.ai", role: "Manager" },
  { name: "System Admin", email: "admin@procure.ai", role: "VP/CFO" },
  // ── Matches approval_rules from create_agent_tables.py ──
  { name: "Finance Manager", email: "finance.manager@company.com", role: "Manager" },
  { name: "Finance Director", email: "finance.director@company.com", role: "Director" },
  { name: "CFO", email: "cfo@company.com", role: "VP/CFO" },
  // ── Additional department leads ──
  { name: "Operations Manager", email: "ops.manager@company.com", role: "Manager" },
  { name: "Operations Director", email: "ops.director@company.com", role: "Director" },
  { name: "COO", email: "coo@company.com", role: "VP/CFO" },
];

const levelToRole: Record<number, string> = {
  1: "Manager",
  2: "Director",
  3: "VP/CFO",
};

// ERP Connection Badge — always shows current ERP
function ErpBadge() {
  const [erp, setErp] = useState({ label: "", mode: "" });

  useEffect(() => {
    const fetchErp = async () => {
      try {
        const res = await apiFetch("/api/config/data-source");
        if (res.ok) {
          const d = await res.json();
          setErp({ label: d.current_label || d.current || "", mode: d.current_mode || "" });
        }
      } catch { }
    };
    fetchErp();
    const interval = setInterval(fetchErp, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  if (!erp.label) return null;

  const modeColors: Record<string, string> = {
    demo: "bg-amber-100 text-amber-800 border-amber-300",
    live: "bg-green-100 text-green-800 border-green-300",
    direct: "bg-blue-100 text-blue-800 border-blue-300",
  };

  return (
    <div className={cn("flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border", modeColors[erp.mode] || "bg-gray-100 text-gray-800 border-gray-300")}>
      <Database className="h-3 w-3" />
      <span>{erp.label}</span>
    </div>
  );
}

export default function MainLayout({ children }: MainLayoutProps) {
  const [location, setLocation] = useLocation();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  
  // Get current user from localStorage or default to Finance Manager (common approver)
  const [currentUser, setCurrentUser] = useState<UserProfile>(() => {
    const stored = localStorage.getItem("currentUser");
    if (stored) {
      try {
        return JSON.parse(stored);
      } catch {
        return DEFAULT_USERS[4]; // Finance Manager
      }
    }
    return DEFAULT_USERS[4]; // Default to Finance Manager (matches approval_rules)
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

  // Layer 1 — sidebar gate awareness. Poll the pending-gates projection from
  // session_gates and group counts by gate_type so each NavItem with a
  // p2pGateType can render a red dot. Quiet 30s polling — the SSE stream
  // already powers per-page truth, this is just the cross-page hint.
  const { data: pendingGatesData } = useQuery({
    queryKey: ["/api/sessions/gates/pending"],
    queryFn: async () => {
      try {
        const res = await apiFetch("/api/sessions/gates/pending");
        if (!res.ok) return { gates: [] as PendingGate[] };
        return (await res.json()) as { gates: PendingGate[] };
      } catch {
        return { gates: [] as PendingGate[] };
      }
    },
    refetchInterval: 30000,
  });

  const gateCountByType = useMemo(() => {
    const m: Record<string, number> = {};
    const sidsByType: Record<string, string[]> = {};
    for (const g of pendingGatesData?.gates ?? []) {
      if (!g.gate_type || g.status !== "pending") continue;
      m[g.gate_type] = (m[g.gate_type] ?? 0) + 1;
      (sidsByType[g.gate_type] ??= []).push(g.session_id);
    }
    return { counts: m, sidsByType };
  }, [pendingGatesData]);

  // ── Grouped Navigation ──
  interface NavGroup {
    label: string;
    icon: LucideIcon;
    items: NavItem[];
    defaultOpen?: boolean;
  }

  const navGroups: NavGroup[] = [
    {
      label: "Overview",
      icon: LayoutDashboard,
      defaultOpen: true,
      items: [
        { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
        { path: "/chat", label: "AI Chat", icon: MessageSquare },
      ],
    },
    {
      label: "Procurement",
      icon: ClipboardList,
      items: [
        { path: "/goods-receipt", label: "Goods Receipt", icon: Package, p2pStep: 10, p2pGateType: "grn" },
        { path: "/rfq", label: "RFQ & Quotes", icon: FileSearch },
        { path: "/delivery-tracking", label: "Delivery Tracking", icon: Truck, p2pStep: 9 },
      ],
    },
    {
      label: "Approvals",
      icon: CheckCircle,
      items: [
        { path: "/pending-approvals", label: "Pending Approvals", icon: CheckCircle, badge: pendingCount?.count || 0, p2pStep: 7, p2pGateType: "approval" },
        { path: "/approval-workflows", label: "Workflows", icon: GitBranch, p2pStep: 6 },
        { path: "/my-approvals", label: "My Approvals", icon: UserCheck, p2pStep: 7 },
      ],
    },
    {
      label: "AI Agents",
      icon: Brain,
      items: [
        { path: "/sessions", label: "Sessions", icon: Layers },
        { path: "/pipeline", label: "Pipeline", icon: Workflow },
      ],
    },
    {
      label: "Finance",
      icon: DollarSign,
      items: [
        { path: "/budget", label: "Budget Tracking", icon: DollarSign, p2pStep: 2 },
        { path: "/payment-execution", label: "Payments", icon: CreditCard, p2pStep: 14, p2pGateType: "payment_release" },
        { path: "/aging-report", label: "Aging Report", icon: Clock },
        { path: "/spend-analytics", label: "Spend Analytics", icon: BarChart3 },
        { path: "/reconciliation", label: "Reconciliation", icon: DollarSign, p2pStep: 12, p2pGateType: "three_way_match" },
      ],
    },
    {
      label: "Intelligence",
      icon: AlertTriangle,
      items: [
        { path: "/risk-assessment", label: "Risk Assessment", icon: AlertTriangle },
        { path: "/anomaly-detection", label: "Anomaly Detection", icon: AlertTriangle },
        { path: "/supplier-performance", label: "Supplier Perf.", icon: Star },
        { path: "/contracts", label: "Contracts", icon: ShieldCheck },
        { path: "/forecasting", label: "Forecasting", icon: TrendingUp },
        { path: "/cycle-times", label: "Cycle Times", icon: Timer },
      ],
    },
    {
      label: "Data",
      icon: Database,
      items: [
        { path: "/data-import", label: "Data Import", icon: Upload },
        { path: "/data-quality", label: "Data Quality", icon: ShieldCheck },
        { path: "/document-processing", label: "Doc Processing", icon: FileSearch },
        { path: "/integrations", label: "Integrations", icon: Zap },
      ],
    },
  ];

  // Track which groups are open
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem("sidebar_open_groups");
      if (saved) return new Set(JSON.parse(saved));
    } catch {}
    // Default: Overview always open + auto-expand group containing current page
    return new Set(["Overview"]);
  });

  // Auto-expand the group containing the active page
  useEffect(() => {
    for (const group of navGroups) {
      if (group.items.some(item => item.path === location)) {
        setOpenGroups(prev => {
          const next = new Set(prev);
          next.add(group.label);
          return next;
        });
        break;
      }
    }
  }, [location]);

  // Persist open groups
  useEffect(() => {
    localStorage.setItem("sidebar_open_groups", JSON.stringify([...openGroups]));
  }, [openGroups]);

  const toggleGroup = useCallback((label: string) => {
    setOpenGroups(prev => {
      const next = new Set(prev);
      if (next.has(label)) {
        if (label !== "Overview") next.delete(label); // Overview always open
      } else {
        next.add(label);
      }
      return next;
    });
  }, []);

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
            <ErpBadge />
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

      {/* Grouped Navigation */}
      <ScrollArea className="flex-1 px-3 py-2">
        <nav className="space-y-1">
          {navGroups.map((group) => {
            const GroupIcon = group.icon;
            const isOpen = openGroups.has(group.label);
            const hasActivePage = group.items.some(i => i.path === location);

            return (
              <div key={group.label}>
                {/* Group Header */}
                <button
                  onClick={() => toggleGroup(group.label)}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-2 rounded-md text-xs font-semibold uppercase tracking-wider",
                    "text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent/50 transition-colors",
                    hasActivePage && "text-sidebar-foreground/90",
                    isCollapsed && "justify-center px-2"
                  )}
                >
                  <GroupIcon className="h-4 w-4 flex-shrink-0" />
                  {!isCollapsed && (
                    <>
                      <span className="flex-1 text-left">{group.label}</span>
                      {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                    </>
                  )}
                </button>

                {/* Group Items (collapsed sidebar: hidden; expanded: show when group open) */}
                {!isCollapsed && isOpen && (
                  <div className="ml-2 space-y-0.5 mb-2">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const isActive = location === item.path;
                      const gateCount = item.p2pGateType
                        ? gateCountByType.counts[item.p2pGateType] ?? 0
                        : 0;
                      const hasGate = gateCount > 0;
                      const handleNavClick = () => {
                        // If exactly one session has this gate type open, deep-link
                        // straight into it. Otherwise route to the page itself
                        // (which will project the filtered sessions list).
                        if (item.p2pGateType && gateCount === 1) {
                          const sids = gateCountByType.sidsByType[item.p2pGateType] || [];
                          if (sids[0]) {
                            setLocation(`/sessions/${sids[0]}`);
                            setIsMobileOpen(false);
                            return;
                          }
                        }
                        setLocation(item.path);
                        setIsMobileOpen(false);
                      };
                      return (
                        <Button
                          key={item.path}
                          variant={isActive ? "default" : "ghost"}
                          size="sm"
                          className={cn(
                            "w-full justify-start gap-2.5 text-sidebar-foreground h-8 text-[13px] relative",
                            isActive && "bg-sidebar-primary text-sidebar-primary-foreground hover:bg-sidebar-primary",
                            !isActive && "hover:bg-sidebar-accent"
                          )}
                          onClick={handleNavClick}
                          title={hasGate ? `${gateCount} open ${item.p2pGateType} gate(s)` : undefined}
                        >
                          <div className="relative flex-shrink-0">
                            <Icon className="h-4 w-4" />
                            {hasGate && (
                              <span
                                className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-red-500 ring-2 ring-sidebar"
                                style={{ ringColor: "hsl(221, 83%, 25%)" } as any}
                              />
                            )}
                          </div>
                          <span className="flex-1 text-left truncate">{item.label}</span>
                          {item.badge !== undefined && item.badge > 0 && (
                            <Badge variant={isActive ? "secondary" : "default"} className="ml-auto text-[10px] h-5 px-1.5">
                              {item.badge}
                            </Badge>
                          )}
                          {hasGate && item.badge === undefined && (
                            <Badge
                              variant="default"
                              className="ml-auto text-[10px] h-5 px-1.5 bg-red-500 hover:bg-red-500"
                            >
                              {gateCount}
                            </Badge>
                          )}
                          {item.p2pStep && !isCollapsed && (
                            <span className="ml-auto text-[9px] font-mono text-slate-400 dark:text-slate-600 opacity-70">
                              P{item.p2pStep}
                            </span>
                          )}
                        </Button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
      </ScrollArea>

      {/* Footer */}
      <div className="p-3 border-t border-sidebar-border space-y-1">
        {[
          { path: "/system-health", label: "System Health", icon: Activity },
          { path: "/approval-settings", label: "Settings", icon: Settings },
        ].map((item) => {
          const Icon = item.icon;
          return (
            <Button
              key={item.path}
              variant="ghost"
              size="sm"
              className={cn(
                "w-full justify-start gap-2.5 text-sidebar-foreground hover:bg-sidebar-accent h-8 text-[13px]",
                isCollapsed && "justify-center px-2",
                location === item.path && "bg-sidebar-accent"
              )}
              onClick={() => { setLocation(item.path); setIsMobileOpen(false); }}
            >
              <Icon className="h-4 w-4 flex-shrink-0" />
              {!isCollapsed && <span>{item.label}</span>}
            </Button>
          );
        })}
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

  // Chat page manages its own scroll — prevent double scrollbar
  const isFullBleedPage = location === "/chat";

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
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile Header */}
        {!isFullBleedPage && (
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
            <ErpBadge />
          </header>
        )}

        {/* Page Content */}
        <main className={cn(
          "flex-1",
          isFullBleedPage ? "overflow-hidden h-full" : "overflow-y-auto h-full"
        )}>
          {children}
        </main>
      </div>
    </div>
  );
}
