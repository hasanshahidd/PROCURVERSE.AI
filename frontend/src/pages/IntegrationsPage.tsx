import { useState, useEffect, useCallback } from "react";
import {
  Bell,
  Mail,
  MessageSquare,
  Shield,
  DollarSign,
  FileSearch,
  Zap,
  RefreshCw,
  CheckCircle,
  XCircle,
  Send,
  Database,
  ArrowRightLeft,
  Info,
  Loader2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface SlackStatus {
  enabled: boolean;
  channel?: string;
  mode?: string;
}

type IntegrationStatus = "active" | "disabled" | "loading" | "error";

interface Integration {
  id: string;
  name: string;
  description: string;
  icon: React.ElementType;
  status: IntegrationStatus;
  detail?: string;
  lastChecked?: string;
  actionLabel?: string;
  onAction?: () => void;
  actionLoading?: boolean;
}

// ─── Status Dot ───────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: IntegrationStatus }) {
  if (status === "loading") {
    return (
      <span className="inline-block h-2.5 w-2.5 rounded-full bg-blue-400 animate-pulse" />
    );
  }
  if (status === "active") {
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-500" />;
  }
  if (status === "error") {
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500" />;
  }
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-400" />;
}

function statusLabel(status: IntegrationStatus) {
  const map: Record<IntegrationStatus, { text: string; cls: string }> = {
    active: { text: "Active", cls: "bg-green-100 text-green-800 border-green-200" },
    disabled: { text: "Disabled", cls: "bg-gray-100 text-gray-600 border-gray-200" },
    loading: { text: "Checking...", cls: "bg-blue-100 text-blue-700 border-blue-200" },
    error: { text: "Error", cls: "bg-red-100 text-red-700 border-red-200" },
  };
  const { text, cls } = map[status];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${cls}`}
    >
      <StatusDot status={status} />
      {text}
    </span>
  );
}

// ─── Integration Card ─────────────────────────────────────────────────────────

function IntegrationCard({ integration }: { integration: Integration }) {
  const Icon = integration.icon;
  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-blue-50 flex items-center justify-center">
              <Icon className="h-5 w-5 text-blue-700" />
            </div>
            <CardTitle className="text-sm font-semibold">{integration.name}</CardTitle>
          </div>
          {statusLabel(integration.status)}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{integration.description}</p>
        {integration.detail && (
          <p className="text-xs font-mono text-muted-foreground bg-muted/50 px-2 py-1 rounded">
            {integration.detail}
          </p>
        )}
        {integration.lastChecked && (
          <p className="text-xs text-muted-foreground">
            Last checked: {integration.lastChecked}
          </p>
        )}
        {integration.actionLabel && integration.onAction && (
          <Button
            size="sm"
            variant="outline"
            onClick={integration.onAction}
            disabled={integration.actionLoading}
            className="w-full"
          >
            {integration.actionLoading ? (
              <RefreshCw className="h-3.5 w-3.5 mr-1.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5 mr-1.5" />
            )}
            {integration.actionLoading ? "Working..." : integration.actionLabel}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function IntegrationsPage() {
  const [slackStatus, setSlackStatus] = useState<SlackStatus | null>(null);
  const [slackLoading, setSlackLoading] = useState(true);
  const [slackTestLoading, setSlackTestLoading] = useState(false);
  const [slackTestMsg, setSlackTestMsg] = useState<string | null>(null);

  const [emailScanLoading, setEmailScanLoading] = useState(false);
  const [emailScanMsg, setEmailScanMsg] = useState<string | null>(null);

  const [testNotifLoading, setTestNotifLoading] = useState(false);
  const [testNotifMsg, setTestNotifMsg] = useState<{ text: string; ok: boolean } | null>(null);

  // ── ERP Data Source Switcher ──
  const [erpCurrent, setErpCurrent] = useState("");
  const [erpLabel, setErpLabel] = useState("");
  const [erpMode, setErpMode] = useState("");
  const [erpGuidance, setErpGuidance] = useState("");
  const [erpDemoSources, setErpDemoSources] = useState<any[]>([]);
  const [erpLiveSources, setErpLiveSources] = useState<any[]>([]);
  const [erpSelected, setErpSelected] = useState("");
  const [erpSwitching, setErpSwitching] = useState(false);
  const [erpMsg, setErpMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [erpHowToLive, setErpHowToLive] = useState<Record<string, string>>({});

  const fetchErpConfig = useCallback(async () => {
    try {
      const res = await apiFetch("/api/config/data-source");
      if (!res.ok) return;
      const data = await res.json();
      setErpCurrent(data.current);
      setErpLabel(data.current_label);
      setErpMode(data.current_mode);
      setErpGuidance(data.guidance);
      setErpSelected(data.current);
      setErpDemoSources(data.demo_sources || []);
      setErpLiveSources(data.live_sources || []);
      setErpHowToLive(data.how_to_go_live || {});
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchErpConfig(); }, [fetchErpConfig]);

  const handleErpSwitch = async () => {
    if (!erpSelected || erpSelected === erpCurrent) return;
    setErpSwitching(true);
    setErpMsg(null);
    try {
      const res = await apiFetch("/api/config/data-source", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data_source: erpSelected }),
      });
      const data = await res.json();
      if (data.success) {
        setErpMsg({ text: data.message, ok: true });
        fetchErpConfig();
      } else {
        setErpMsg({ text: data.detail || "Switch failed", ok: false });
      }
    } catch (e: any) {
      setErpMsg({ text: e.message, ok: false });
    } finally {
      setErpSwitching(false);
    }
  };

  const now = new Date().toLocaleTimeString();

  // Fetch Slack status on mount
  useEffect(() => {
    (async () => {
      setSlackLoading(true);
      try {
        const res = await apiFetch("/api/agentic/slack/status");
        if (!res.ok) throw new Error("non-ok");
        const data = await res.json();
        setSlackStatus(data);
      } catch {
        setSlackStatus({ enabled: false });
      } finally {
        setSlackLoading(false);
      }
    })();
  }, []);

  const sendSlackTest = async () => {
    setSlackTestLoading(true);
    setSlackTestMsg(null);
    try {
      const res = await apiFetch("/api/agentic/slack/notify", {
        method: "POST",
        body: JSON.stringify({
          event_type: "general",
          payload: { text: "Test from Procure AI" },
        }),
      });
      const data = await res.json();
      setSlackTestMsg(res.ok ? (data.message ?? "Test notification sent!") : (data.error ?? "Failed"));
    } catch {
      setSlackTestMsg("Failed to send test — check Slack configuration.");
    } finally {
      setSlackTestLoading(false);
    }
  };

  const scanEmailInbox = async () => {
    setEmailScanLoading(true);
    setEmailScanMsg(null);
    try {
      const res = await apiFetch("/api/agentic/email/inbox/scan", { method: "POST" });
      const data = await res.json();
      setEmailScanMsg(
        res.ok
          ? (data.message ?? `Inbox scan complete. Processed ${data.emails_processed ?? 0} emails.`)
          : (data.error ?? "Scan failed.")
      );
    } catch {
      setEmailScanMsg("Email inbox scan failed — check IMAP configuration.");
    } finally {
      setEmailScanLoading(false);
    }
  };

  const sendTestNotification = async () => {
    setTestNotifLoading(true);
    setTestNotifMsg(null);
    try {
      const res = await apiFetch("/api/agentic/notifications/test", {
        method: "POST",
        body: JSON.stringify({
          type: "approval_request",
          email: "test@example.com",
        }),
      });
      const data = await res.json();
      setTestNotifMsg({
        ok: res.ok,
        text: res.ok
          ? (data.message ?? "Test notification sent successfully!")
          : (data.error ?? "Notification failed."),
      });
    } catch {
      setTestNotifMsg({ ok: false, text: "Notification failed — check email configuration." });
    } finally {
      setTestNotifLoading(false);
    }
  };

  const slackDetail = slackStatus
    ? [
        slackStatus.channel ? `Channel: ${slackStatus.channel}` : null,
        slackStatus.mode ? `Mode: ${slackStatus.mode}` : null,
      ]
        .filter(Boolean)
        .join("  |  ")
    : undefined;

  const integrations: Integration[] = [
    {
      id: "slack",
      name: "Slack",
      description: "Sends procurement event notifications to a Slack channel.",
      icon: MessageSquare,
      status: slackLoading
        ? "loading"
        : slackStatus?.enabled
        ? "active"
        : "disabled",
      detail: slackDetail,
      actionLabel: "Send Test",
      onAction: sendSlackTest,
      actionLoading: slackTestLoading,
    },
    {
      id: "email",
      name: "Email (SMTP)",
      description: "Outbound email notifications for approvals and alerts.",
      icon: Mail,
      status: "active",
      detail: "SMTP configured via environment",
      lastChecked: now,
    },
    {
      id: "email-imap",
      name: "Email Inbox (IMAP)",
      description: "Scan incoming email inbox for purchase requests and invoices.",
      icon: Mail,
      status: "active",
      actionLabel: "Scan Now",
      onAction: scanEmailInbox,
      actionLoading: emailScanLoading,
    },
    {
      id: "sanctions",
      name: "Sanctions Screening",
      description: "Screens vendors against global sanctions and watchlists.",
      icon: Shield,
      status: "active",
      lastChecked: now,
    },
    {
      id: "fx",
      name: "FX Rates",
      description: "Live foreign exchange rates for multi-currency POs (fallback to cached rates when offline).",
      icon: DollarSign,
      status: "active",
      detail: "Fallback rates active",
      lastChecked: now,
    },
    {
      id: "ocr",
      name: "OCR Processing",
      description: "Optical character recognition for uploaded invoice and document images.",
      icon: FileSearch,
      status: "active",
      lastChecked: now,
    },
  ];

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-lg bg-purple-100 flex items-center justify-center">
          <Zap className="h-5 w-5 text-purple-600" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Integrations & Notifications</h1>
          <p className="text-sm text-muted-foreground">
            Manage external service connections and notification channels
          </p>
        </div>
      </div>

      {/* ── ERP Data Source Switcher ───────────────────────────────────── */}
      <Card className="border-2 border-blue-200">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Database className="h-5 w-5 text-blue-600" />
              ERP Data Source
            </CardTitle>
            <Badge className={
              erpMode === "demo" ? "bg-amber-100 text-amber-800" :
              erpMode === "live" ? "bg-green-100 text-green-800" :
              "bg-blue-100 text-blue-800"
            }>
              {erpLabel || erpCurrent || "Loading..."}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Current mode guidance */}
          {erpGuidance && (
            <div className={`rounded-md px-4 py-3 text-sm flex items-start gap-2 ${
              erpMode === "demo" ? "bg-amber-50 border border-amber-200 text-amber-800" :
              erpMode === "live" ? "bg-green-50 border border-green-200 text-green-800" :
              "bg-blue-50 border border-blue-200 text-blue-800"
            }`}>
              <Info className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>{erpGuidance}</span>
            </div>
          )}

          {/* Switcher */}
          <div className="flex items-center gap-3">
            <select
              value={erpSelected}
              onChange={(e) => setErpSelected(e.target.value)}
              className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            >
              <optgroup label="Demo / Sandbox (test data in PostgreSQL)">
                {erpDemoSources.map((s: any) => (
                  <option key={s.key} value={s.key}>
                    {s.label} {s.is_current ? "(current)" : ""}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Live ERP Connectors">
                {erpLiveSources.map((s: any) => (
                  <option key={s.key} value={s.key}>
                    {s.label} {s.configured === false ? "(not configured)" : ""} {s.is_current ? "(current)" : ""}
                  </option>
                ))}
              </optgroup>
            </select>
            <Button
              onClick={handleErpSwitch}
              disabled={erpSwitching || erpSelected === erpCurrent || !erpSelected}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {erpSwitching ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <ArrowRightLeft className="h-4 w-4 mr-2" />
              )}
              {erpSwitching ? "Switching..." : "Switch"}
            </Button>
          </div>

          {/* Switch result message */}
          {erpMsg && (
            <div className={`rounded-md px-4 py-3 text-sm flex items-center gap-2 ${
              erpMsg.ok ? "bg-green-50 border border-green-200 text-green-700"
                        : "bg-red-50 border border-red-200 text-red-700"
            }`}>
              {erpMsg.ok ? <CheckCircle className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
              {erpMsg.text}
            </div>
          )}

          {/* How to go live guidance */}
          {Object.keys(erpHowToLive).length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-blue-600 font-medium">
                How to connect a real ERP (production mode)
              </summary>
              <ol className="mt-2 space-y-1 text-muted-foreground list-decimal list-inside">
                {Object.values(erpHowToLive).map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
            </details>
          )}
        </CardContent>
      </Card>

      {/* Status messages from Slack test */}
      {slackTestMsg && (
        <div className="rounded-md bg-blue-50 border border-blue-200 px-4 py-3 text-sm text-blue-700 flex items-center gap-2">
          <MessageSquare className="h-4 w-4 flex-shrink-0" />
          Slack: {slackTestMsg}
        </div>
      )}
      {emailScanMsg && (
        <div className="rounded-md bg-blue-50 border border-blue-200 px-4 py-3 text-sm text-blue-700 flex items-center gap-2">
          <Mail className="h-4 w-4 flex-shrink-0" />
          Email Inbox: {emailScanMsg}
        </div>
      )}

      {/* Integration Cards Grid */}
      <div>
        <h2 className="text-lg font-semibold mb-4">Connected Services</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {integrations.map((integration) => (
            <IntegrationCard key={integration.id} integration={integration} />
          ))}
        </div>
      </div>

      {/* Send Test Notification Section */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Bell className="h-4 w-4 text-purple-500" />
            Send Test Notification
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Triggers a test approval request notification to{" "}
            <span className="font-mono">test@example.com</span> to verify your
            notification pipeline is working end-to-end.
          </p>
          {testNotifMsg && (
            <div
              className={`rounded-md px-4 py-3 text-sm flex items-center gap-2 ${
                testNotifMsg.ok
                  ? "bg-green-50 border border-green-200 text-green-700"
                  : "bg-red-50 border border-red-200 text-red-700"
              }`}
            >
              {testNotifMsg.ok ? (
                <CheckCircle className="h-4 w-4 flex-shrink-0" />
              ) : (
                <XCircle className="h-4 w-4 flex-shrink-0" />
              )}
              {testNotifMsg.text}
            </div>
          )}
          <Button
            onClick={sendTestNotification}
            disabled={testNotifLoading}
            className="bg-purple-600 hover:bg-purple-700 text-white"
          >
            {testNotifLoading ? (
              <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Send className="h-4 w-4 mr-2" />
            )}
            {testNotifLoading ? "Sending..." : "Send Test Notification"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
