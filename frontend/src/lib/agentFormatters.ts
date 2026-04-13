/**
 * Agent-specific markdown formatting helpers.
 *
 * Each formatter receives the FLAT agent payload (already extracted by
 * agentResultExtractor) and returns a markdown string for display in
 * the chat bubble.
 */

import type { NormalisedResult } from "./agentResultExtractor";

// ─── Shared table helpers ───────────────────────────────────────────────

const sanitizeCell = (value: unknown): string =>
  String(value ?? "-").replaceAll("|", " ").replace(/\s+/g, " ").trim();

const formatMetric = (value: unknown): string => {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number")
    return Number.isInteger(value) ? `${value}` : `${value.toFixed(2)}`;
  return sanitizeCell(value);
};

const mdTable = (headers: string[], rows: unknown[][]): string => {
  if (!rows.length) return "";
  const h = `| ${headers.map(sanitizeCell).join(" | ")} |\n`;
  const s = `| ${headers.map(() => "---").join(" | ")} |\n`;
  const r = rows.map((row) => `| ${row.map(formatMetric).join(" | ")} |`).join("\n");
  return `${h}${s}${r}\n`;
};

const toTitle = (v: string): string =>
  v.replaceAll("_", " ").replaceAll("-", " ").trim().replace(/\s+/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());

// ─── Budget ─────────────────────────────────────────────────────────────

export function formatBudgetResult(r: NormalisedResult): string {
  const p = r.payload;

  // ── Budget Status Report (query without a specific purchase amount) ──
  if (p.status === "budget_status") {
    const report = (p.budget_status_report || {}) as Record<string, any>;
    const rawDept = p.department || report.department || "";
    const budgets: any[] = Array.isArray(report.budgets) ? report.budgets : [];

    // Determine if showing all departments or a specific one
    const uniqueDepts = [...new Set(budgets.map((b: any) => b.department).filter(Boolean))];
    const isAllDepts = !rawDept || rawDept.toLowerCase() === "unknown" || uniqueDepts.length > 1;
    const deptLabel = isAllDepts ? "All Departments" : (rawDept || uniqueDepts[0] || "General");

    let md = `## 📊 ${deptLabel} Budget Status\n\n`;

    if (budgets.length === 0) {
      md += `No budget data found${rawDept ? ` for ${rawDept}` : ""}.\n`;
      return md;
    }

    // Include Department column when showing multiple departments
    if (isAllDepts) {
      md += mdTable(
        ["Department", "Category", "Allocated", "Spent", "Committed", "Available", "Utilization"],
        budgets.map((b: any) => [
          b.department || "—",
          b.category,
          `$${Number(b.allocated).toLocaleString()}`,
          `$${Number(b.spent).toLocaleString()}`,
          `$${Number(b.committed).toLocaleString()}`,
          `$${Number(b.available).toLocaleString()}`,
          `${Number(b.utilization_pct).toFixed(1)}%`,
        ])
      );
    } else {
      md += mdTable(
        ["Category", "Allocated", "Spent", "Committed", "Available", "Utilization"],
        budgets.map((b: any) => [
          b.category,
          `$${Number(b.allocated).toLocaleString()}`,
          `$${Number(b.spent).toLocaleString()}`,
          `$${Number(b.committed).toLocaleString()}`,
          `$${Number(b.available).toLocaleString()}`,
          `${Number(b.utilization_pct).toFixed(1)}%`,
        ])
      );
    }

    budgets.forEach((b: any) => {
      const util = Number(b.utilization_pct);
      if (util >= 95) {
        md += `\n🚨 **${b.category} Critical:** ${util.toFixed(0)}% utilized — budget nearly exhausted.\n`;
      } else if (util >= 90) {
        md += `\n⚠️ **${b.category} High Alert:** ${util.toFixed(0)}% utilized.\n`;
      } else if (util >= 80) {
        md += `\nℹ️ **${b.category} Warning:** ${util.toFixed(0)}% utilized.\n`;
      }
    });

    return md;
  }

  if (p.status === "approved" || p.budget_verified) {
    const bu = p.budget_update || {};
    const available = bu.new_available_budget ?? 0;
    const committed = bu.amount_committed ?? 0;
    const totalCommitted = bu.new_committed_budget ?? 0;
    // allocated = committed + available (the total budget envelope)
    const allocated = totalCommitted + available;
    const utilization = allocated > 0 ? ((totalCommitted / allocated) * 100) : 0;
    // Resolve department from multiple possible locations
    const decisionCtx = r.decision && "context" in r.decision ? (r.decision as any).context : null;
    const dept = p.department || bu.department || decisionCtx?.department || p.budget_category || "General";

    let md = `## ✅ Budget Approved\n\n`;
    md += `Great news! The budget has been verified for this purchase.\n\n`;
    md += `### 💰 Budget Summary\n`;
    md += mdTable(
      ["Metric", "Value"],
      [
        ["Department", dept],
        ["Request Amount", `$${committed.toLocaleString()}`],
        ["Available Balance", `$${available.toLocaleString()}`],
        ["Budget Usage", `${utilization.toFixed(1)}%`],
      ]
    );
    if (p.reasoning) md += `\n**Note:** ${p.reasoning}\n`;
    if (utilization >= 90) {
      md += `\n⚠️ **Warning:** Budget is ${utilization.toFixed(0)}% utilized. Consider reviewing remaining expenses.\n`;
    } else if (utilization >= 80) {
      md += `\nℹ️ **Info:** Budget utilization is at ${utilization.toFixed(0)}%. Within safe limits.\n`;
    }
    if (p.alert_level) {
      md += `\n**Alert Level:** ${p.alert_level}\n`;
    }
    return md;
  }

  // Rejected / insufficient
  let md = `## ❌ Budget Not Available\n\n`;
  md += `Unfortunately, there isn't sufficient budget for this request.\n\n`;
  md += `**Reason:** ${p.reason || p.reasoning || "Insufficient funds"}\n\n`;
  if (p.alternatives) {
    md += `### 💡 Suggested Actions\n`;
    (Array.isArray(p.alternatives) ? p.alternatives : [p.alternatives]).forEach(
      (a: string) => { md += `- ${toTitle(a)}\n`; }
    );
    md += "\n";
  }
  md += `**Recommendation:** Contact your finance team to discuss budget reallocation or wait for the next fiscal period.\n`;
  return md;
}

// ─── Vendor Selection ───────────────────────────────────────────────────

export function formatVendorResult(r: NormalisedResult): string {
  const p = r.payload;
  const prim = p.primary_recommendation || {};
  const vendorName = prim.vendor_name || p.recommended_vendor || "N/A";
  const reason = prim.reason || p.reasoning || r.decision?.reasoning || "Best overall score";

  let md = `## 🏆 Vendor Recommendation\n\n`;
  md += mdTable(["Recommendation", "Vendor", "Reason"], [["Primary", vendorName, reason]]);

  if (prim.score !== undefined) {
    md += `\n### Score\n`;
    const scoreRows: unknown[][] = [["Total", `${prim.score}/100`]];
    if (prim.strengths) {
      md += `\n**Strengths:** ${Array.isArray(prim.strengths) ? prim.strengths.join(", ") : prim.strengths}\n`;
    }
    if (prim.concerns) {
      md += `**Concerns:** ${Array.isArray(prim.concerns) ? prim.concerns.join(", ") : prim.concerns}\n`;
    }
    md += mdTable(["Score Dimension", "Value"], scoreRows);
  } else if (p.score) {
    md += `\n### Score\n`;
    const total = typeof p.score === "object" ? p.score.total : p.score;
    const scoreRows: unknown[][] = [["Total", `${total}/100`]];
    if (p.score.subscores) {
      Object.entries(p.score.subscores).forEach(([k, v]) => {
        scoreRows.push([toTitle(k), `${v}`]);
      });
    }
    md += mdTable(["Score Dimension", "Value"], scoreRows);
  }

  if (Array.isArray(p.alternative_recommendations) && p.alternative_recommendations.length > 0) {
    md += `\n### Alternatives\n`;
    md += mdTable(
      ["Vendor", "Score", "Reason"],
      p.alternative_recommendations.slice(0, 5).map((a: any) => [
        a.vendor_name,
        `${a.score}/100`,
        a.reason || "-",
      ])
    );
  }

  if (p.total_evaluated !== undefined) {
    md += `\n*Evaluated ${p.total_evaluated} vendor(s) total.*\n`;
  }
  return md;
}

// ─── Risk Assessment ────────────────────────────────────────────────────

export function formatRiskResult(r: NormalisedResult): string {
  const p = r.payload;
  // Multi-vendor comparison renderer
  if (Array.isArray(p.vendor_risk_comparison) && p.vendor_risk_comparison.length > 0) {
    return formatMultiVendorRiskResult(r);
  }
  const level = p.risk_level || "UNKNOWN";
  const emoji = level === "CRITICAL" || level === "HIGH" ? "🔴" : level === "MEDIUM" ? "🟡" : "🟢";

  let md = `## ${emoji} Risk Assessment — ${level}\n\n`;
  md += mdTable(
    ["Metric", "Value"],
    [
      ["Overall Risk Score", `${p.risk_score}/100`],
      ["Risk Level", level],
      ["Can Proceed", p.can_proceed ? "Yes" : "No"],
    ]
  );

  // Breakdown (could be risk_scores, breakdown, or risk_breakdown)
  // Values may be flat numbers OR nested objects like {score: 65, weight: "30%", concerns: [...]}
  const breakdownRaw: Record<string, any> = p.risk_scores || p.breakdown || p.risk_breakdown || {};
  if (Object.keys(breakdownRaw).length > 0) {
    md += `\n### Risk Breakdown\n`;
    md += mdTable(
      ["Risk Dimension", "Score", "Weight"],
      Object.entries(breakdownRaw).map(([k, v]) => {
        if (v && typeof v === "object" && "score" in v) {
          return [toTitle(k), `${v.score}/100`, v.weight || "-"];
        }
        return [toTitle(k), `${v}/100`, "-"];
      })
    );

    // Show per-dimension concerns if available
    const allConcerns = Object.entries(breakdownRaw)
      .filter(([, v]) => v && typeof v === "object" && Array.isArray(v.concerns) && v.concerns.length > 0)
      .flatMap(([k, v]) => v.concerns.map((c: string) => `**${toTitle(k)}:** ${c}`));
    if (allConcerns.length > 0) {
      md += `\n### ⚠️ Key Concerns\n`;
      allConcerns.forEach((c: string) => { md += `- ${c}\n`; });
    }
  }

  if (Array.isArray(p.mitigations) && p.mitigations.length > 0) {
    md += `\n### 🛡️ Mitigations\n`;
    p.mitigations.forEach((m: string) => { md += `- ${m}\n`; });
  }

  if (Array.isArray(p.recommended_actions) && p.recommended_actions.length > 0) {
    md += `\n### 💡 Recommended Actions\n`;
    p.recommended_actions.forEach((a: string) => { md += `- ${a}\n`; });
  } else if (Array.isArray(p.recommendations) && p.recommendations.length > 0) {
    md += `\n### 💡 Recommendations\n`;
    p.recommendations.forEach((rec: string) => { md += `- ${rec}\n`; });
  }

  if (p.requires_human_review) {
    md += `\n⚠️ **This assessment requires human review before proceeding.**\n`;
  }
  return md;
}


export function formatMultiVendorRiskResult(r: NormalisedResult): string {
  const p = r.payload;
  const comps: any[] = Array.isArray(p.vendor_risk_comparison) ? p.vendor_risk_comparison : [];
  const total = comps.length;

  let md = `## 📊 Vendor Risk Comparison (${total} vendors)
\n`;
  if (total === 0) {
    md += `No vendor data available for comparison.`;
    return md;
  }

  md += mdTable(["Vendor", "Risk Score", "Level"], comps.map((c: any) => {
    const score = Number(c.risk_score ?? 100);
    const level = score >= 80 ? "CRITICAL" : score >= 60 ? "HIGH" : score >= 40 ? "MEDIUM" : "LOW";
    const emoji = level === "CRITICAL" || level === "HIGH" ? "🔴" : level === "MEDIUM" ? "🟡" : "🟢";
    return [c.vendor_name || `id:${c.vendor_id}`, `${score}/100`, `${emoji} ${level}`];
  }));

  const lowest = p.lowest_risk_vendor || comps[0];
  if (lowest) {
    md += `\n### ✅ Lowest Risk Vendor: ${lowest.vendor_name} (${Number(lowest.risk_score)}/100)\n\n`;
    const payload = lowest.payload || {};
    if (payload && Object.keys(payload).length > 0) {
      md += `#### Breakdown for ${lowest.vendor_name}\n`;
      // reuse formatRiskResult for single-vendor risk payload if shaped similarly
      const single: NormalisedResult = { ...r, payload } as any;
      md += formatRiskResult(single);
    }
  }

  if (p.summary) md += `\n${p.summary}\n`;
  return md;
}

// ─── Approval Routing ───────────────────────────────────────────────────

export function formatApprovalResult(r: NormalisedResult): string {
  const p = r.payload;
  const analysisOnly = Boolean(p.analysis_only || !p.workflow_id);

  let md = `## 📋 Approval Routing\n\n`;

  if (Array.isArray(p.approval_chain) && p.approval_chain.length > 0) {
    md += `### Approval Chain\n`;
    md += mdTable(
      ["Level", "Approver", "Email", "Status"],
      p.approval_chain.map((step: any) => [
        step.level ?? step.approval_level,
        step.approver ?? step.approver_name,
        step.email ?? step.approver_email,
        step.status || "pending",
      ])
    );
  }

  if (Array.isArray(p.assigned_approvers) && p.assigned_approvers.length > 0) {
    md += `### Assigned Approvers\n`;
    md += mdTable(
      ["Level", "Approver", "Email", "Threshold"],
      p.assigned_approvers.map((step: any) => [
        step.approval_level,
        step.approver_name,
        step.approver_email,
        step.budget_threshold !== undefined
          ? `$${Number(step.budget_threshold).toLocaleString()}`
          : "-",
      ])
    );
  }

  if (analysisOnly) {
    md += `\n**Mode:** Analysis only (no PR/workflow record created)\n`;
  }
  if (p.pr_number) md += `\n**PR Number:** ${p.pr_number}\n`;
  if (p.required_level) md += `**Required Approval Level:** ${p.required_level}\n`;
  if (p.workflow_id) md += `**Workflow ID:** ${p.workflow_id}\n`;
  if (p.reasoning) md += `\n**Routing Logic:** ${p.reasoning}\n`;
  if (p.message) md += `\n**Outcome:** ${p.message}\n`;
  return md;
}

// ─── Generic fallback ───────────────────────────────────────────────────

export function formatGenericResult(r: NormalisedResult): string {
  const p = r.payload;
  const agent = r.agent || "Agent";

  // Simple message-only response (e.g. greetings, help)
  if (p.message && !p.action && !p.risk_score && !p.risk_level && !p.performance_score && !p.compliance_score) {
    return `## 🤖 ${agent}\n\n${p.message}\n`;
  }

  let md = `## 🤖 ${agent} Analysis\n\n`;

  const status = String(p.status || "completed").toUpperCase();
  const action = p.action ? toTitle(String(p.action)) : undefined;
  const reasoning = p.reasoning || r.decision?.reasoning;

  const summaryRows: unknown[][] = [["Status", status]];
  if (action) summaryRows.push(["Action", action]);
  if (p.risk_level) summaryRows.push(["Risk Level", p.risk_level]);
  if (p.performance_level) summaryRows.push(["Performance Level", p.performance_level]);
  if (p.compliance_score !== undefined) summaryRows.push(["Compliance Score", `${p.compliance_score}/100`]);
  if (p.risk_score !== undefined) summaryRows.push(["Risk Score", `${p.risk_score}/100`]);
  if (p.performance_score !== undefined || p.overall_score !== undefined)
    summaryRows.push(["Score", `${p.performance_score ?? p.overall_score}/100`]);

  md += mdTable(["Metric", "Value"], summaryRows);

  if (reasoning) md += `\n**Analysis:** ${reasoning}\n`;

  if (Array.isArray(p.recommendations) && p.recommendations.length > 0) {
    md += `\n### 💡 Recommendations\n`;
    p.recommendations.forEach((rec: string) => { md += `- ${rec}\n`; });
  }
  if (Array.isArray(p.next_steps) && p.next_steps.length > 0) {
    md += `\n### Next Steps\n`;
    p.next_steps.forEach((s: string) => { md += `- ${s}\n`; });
  }

  return md;
}

// ─── Odoo PO ────────────────────────────────────────────────────────────

export function formatOdooPoResult(r: NormalisedResult): string {
  const p = r.payload;
  const total = Number(p.total_purchase_orders || 0);
  const orders = Array.isArray(p.purchase_orders) ? p.purchase_orders : [];

  let md = `## 📦 Purchase Orders (ERP Data)\n\n`;
  md += `**Total Purchase Orders:** ${total}\n\n`;
  if (orders.length > 0) {
    md += `### Purchase Order Details\n`;
    md += mdTable(
      ["PO Number", "State", "Amount", "Vendor", "Order Date"],
      orders.map((po: any) => [
        `**${sanitizeCell(po.name || "PO")}**`,
        String(po.state || "unknown").toUpperCase(),
        `$${Number(po.amount_total || 0).toLocaleString()}`,
        sanitizeCell(po.vendor_name || "Unknown Vendor"),
        sanitizeCell(po.date_order || "-"),
      ])
    );
  }
  return md;
}

// ─── PR Creation Workflow ───────────────────────────────────────────────

export function formatPrWorkflowResult(r: NormalisedResult): string {
  const p = r.payload;
  const status = String(p.status || "unknown").toLowerCase();
  const prNumber = p.pr_object?.pr_number || "Pending";
  const failureReason = p.failure_reason;
  const validations = p.validations || {};
  const complianceData = validations.compliance?.result || (validations.compliance as any)?.decision?.context || {};
  const violations = complianceData.violations || [];
  const warnings = complianceData.warnings || [];
  const workflowWarnings = Array.isArray(p.warnings) ? p.warnings : [];
  const vendorSelectionNote = typeof p.vendor_selection_note === "string" ? p.vendor_selection_note : "";
  const allWarnings = [...new Set([
    ...warnings,
    ...workflowWarnings,
    ...(vendorSelectionNote ? [vendorSelectionNote] : []),
  ])];

  if (status === "needs_clarification") {
    return p.clarification_question || "Please provide the missing information to continue with PR creation.";
  }

  if (status === "awaiting_vendor_confirmation") {
    let md = `## ⏸️ Vendor Confirmation Required\n\n`;
    md += `${p.message || "Please choose one of the recommended vendors to continue PR creation."}\n\n`;

    const options = Array.isArray(p.top_vendor_options) ? p.top_vendor_options : [];
    if (options.length > 0) {
      md += `### 📦 Top Recommended Vendors\n`;
      md += mdTable(
        ["Vendor", "Score", "Reason"],
        options.slice(0, 5).map((opt: any) => [
          sanitizeCell(opt.vendor_name || "Unknown"),
          `${Number(opt.total_score ?? opt.score ?? 0).toFixed(1)}/100`,
          sanitizeCell(opt.recommendation_reason || opt.reason || "No reason provided"),
        ])
      );
      md += "\n";
    }

    if (allWarnings.length > 0) {
      md += `### ⚠️ Advisory Notes\n`;
      allWarnings.forEach((w: string) => { md += `- ${w}\n`; });
      md += "\n";
    }

    md += `### 📝 Why It Paused\n`;
    md += `- PR creation is waiting for your vendor selection from the recommended shortlist.\n`;
    md += `- This is not a hard validation failure unless blocking violations are listed.\n`;
    return md;
  }

  if (status === "success" || status === "success_no_workflow") {
    let md = `## ✅ PR Created\n\n`;
    md += `Purchase request **${prNumber}** has been created and submitted for approval.\n\n`;
    md += `### 📋 Workflow Steps\n`;
    md += `1. ✅ **PR Created** (Current Stage)\n`;
    md += `2. ⏳ **Approval Workflow** → Approvers will review budget and justification\n`;
    md += `3. ⏳ **PO Creation** → After approval, Purchase Order will be created with vendor selection\n`;

    const riskValidation = validations.risk?.result || (validations.risk as any)?.decision?.context?.risk_assessment;
    const riskLevel = riskValidation?.risk_level || riskValidation?.risk_assessment?.risk_level;
    const riskScore = riskValidation?.risk_score ?? riskValidation?.total_score ?? riskValidation?.risk_assessment?.total_score;
    const riskBreakdown = riskValidation?.breakdown || riskValidation?.risk_assessment?.breakdown;
    if (riskLevel || riskScore !== undefined) {
      const vendorScore = riskBreakdown?.vendor_risk?.score;
      const financialScore = riskBreakdown?.financial_risk?.score;
      const complianceScore = riskBreakdown?.compliance_risk?.score;
      const operationalScore = riskBreakdown?.operational_risk?.score;

      md += `\n### ⚠️ Risk Snapshot\n`;
      md += mdTable(
        ["Metric", "Value"],
        [
          ["Risk Level", String(riskLevel || "UNKNOWN").toUpperCase()],
          ["Overall Risk Score", `${Number(riskScore || 0).toFixed(1)}/100`],
          ["Vendor Risk", vendorScore !== undefined ? `${vendorScore}/100` : "-"],
          ["Financial Risk", financialScore !== undefined ? `${financialScore}/100` : "-"],
          ["Compliance Risk", complianceScore !== undefined ? `${complianceScore}/100` : "-"],
          ["Operational Risk", operationalScore !== undefined ? `${operationalScore}/100` : "-"],
        ]
      );

      const riskConcerns = [
        ...(riskBreakdown?.vendor_risk?.concerns || []),
        ...(riskBreakdown?.financial_risk?.concerns || []),
        ...(riskBreakdown?.compliance_risk?.concerns || []),
        ...(riskBreakdown?.operational_risk?.concerns || []),
      ].filter(Boolean);
      if (riskConcerns.length > 0) {
        md += `\n**Top Concerns:**\n`;
        riskConcerns.slice(0, 2).forEach((c: string) => { md += `- ${c}\n`; });
      }
    }

    if (allWarnings.length > 0) {
      md += `\n### ⚠️ Advisory Notes\n`;
      allWarnings.forEach((w: string) => { md += `- ${w}\n`; });
    }

    return md;
  }

  // Failed workflow
  const budgetData = validations.budget?.result || (validations.budget as any)?.decision?.context || {};
  const riskData = validations.risk?.result || (validations.risk as any)?.decision?.context || {};
  const complianceScore = complianceData.compliance_score;
  const complianceLevel = complianceData.compliance_level;

  let md = `## ⚠️ PR Validation Failed\n\n`;

  if (complianceScore !== undefined && complianceLevel) {
    md += `**Compliance Status:** ${complianceLevel} (Score: ${complianceScore}/100)\n\n`;
  }

  if (violations.length > 0) {
    md += `### ❌ Blocking Issues\n`;
    violations.forEach((v: string) => { md += `- ${v}\n`; });
    md += "\n";
  }
  if (allWarnings.length > 0) {
    md += `### ⚠️ Warnings\n`;
    allWarnings.forEach((w: string) => { md += `- ${w}\n`; });
    md += "\n";
  }

  const budgetAvailable = budgetData.available_budget ?? budgetData.budget_status?.available;
  const budgetRequested = budgetData.requested_amount ?? budgetData.amount;
  if (budgetAvailable !== undefined && budgetRequested !== undefined) {
    md += `### 💰 Budget Status\n`;
    md += mdTable(
      ["Metric", "Value"],
      [
        ["Department", budgetData.department || "N/A"],
        ["Requested Amount", `$${Number(budgetRequested).toLocaleString()}`],
        ["Available Budget", `$${Number(budgetAvailable).toLocaleString()}`],
        ["Shortfall", `$${(Number(budgetRequested) - Number(budgetAvailable)).toLocaleString()}`],
      ]
    );
  }

  const riskScore = riskData.overall_risk_score ?? riskData.risk_score;
  if (riskScore !== undefined) {
    md += `\n### 🎯 Risk Assessment\n`;
    md += `**Risk Score:** ${riskScore}/100 (${riskData.risk_level || "UNKNOWN"})\n`;
  }

  if (violations.length === 0 && allWarnings.length === 0 && budgetAvailable === undefined && riskScore === undefined) {
    md += `**Reason:** ${failureReason || "Validation failed before workflow creation"}\n`;
  }

  md += `\n### 📝 Next Steps\n`;
  if (violations.length > 0) {
    md += `**Blocking violations must be resolved** before PR can be created.\n`;
    md += `**Warnings** are informational and do not block PR creation.\n`;
  } else {
    md += `Please review the warnings above and resubmit your request.\n`;
  }
  return md;
}

// ─── Multi-Intent Orchestrator ──────────────────────────────────────────

export function formatMultiIntentResult(r: NormalisedResult): string {
  const children = r.multiResults || [];
  const intentCount = children.length || r.payload.intent_count || 0;

  const humanize = (v: unknown, fallback = "-") => {
    const raw = String(v ?? "").trim();
    return raw ? toTitle(raw.replaceAll("_", " ")) : fallback;
  };

  const getFriendlyName = (agent: string): string => {
    const a = agent.toLowerCase();
    if (a.includes("vendor")) return "📦 Vendor Selection";
    if (a.includes("budget")) return "💰 Budget Check";
    if (a.includes("approval")) return "✅ Approval Routing";
    if (a.includes("risk")) return "⚠️  Risk Assessment";
    if (a.includes("contract")) return "📄 Contract Monitoring";
    if (a.includes("supplier") || a.includes("performance")) return "⭐ Supplier Performance";
    if (a.includes("price")) return "💵 Price Analysis";
    if (a.includes("compliance")) return "📋 Compliance Check";
    if (a.includes("invoice")) return "🧾 Invoice Matching";
    if (a.includes("spend")) return "📊 Spend Analytics";
    if (a.includes("inventory")) return "📦 Inventory Check";
    if (a.includes("pr")) return "📝 Purchase Request Creation";
    return agent;
  };

  const getDepartmentLabel = (c: NormalisedResult): string => {
    const dept =
      c.payload?.department
      || c.payload?.context?.department
      || c.payload?.input_context?.pr_data?.department;
    return dept ? ` (${String(dept).toUpperCase()})` : "";
  };

  const classifyChild = (c: NormalisedResult) => {
    const agent = (c.agent || "").toLowerCase();
    const status = String(c.status || "").toLowerCase().replace(/_/g, " ");
    const reasonBlob = String(c.payload.reason || c.payload.message || c.decision?.reasoning || "").toLowerCase();

    // Failure should mean execution failure, not business risk/warning outcomes.
    const failed = ["error", "failed", "exception", "timeout", "crash"].some((bad) => status.includes(bad));
    const completed = !failed;

    if (agent.includes("budget")) {
      const attention =
        c.payload.budget_verified === false ||
        reasonBlob.includes("critical threshold") ||
        reasonBlob.includes("insufficient budget");
      return { completed, attention, failed };
    }

    if (agent.includes("risk")) {
      const riskLevel = String(c.payload.risk_level || "").toLowerCase();
      const attention =
        c.payload.requires_human_review === true ||
        c.payload.can_proceed === false ||
        riskLevel === "medium" ||
        riskLevel === "high" ||
        riskLevel === "critical" ||
        reasonBlob.includes("review recommended");
      return { completed, attention, failed };
    }

    if (agent.includes("approval")) {
      const attention = Boolean(c.payload.analysis_only || !c.payload.workflow_id);
      return { completed, attention, failed };
    }

    if (agent.includes("vendor")) {
      const attention = !Boolean(c.payload.primary_recommendation || c.payload.recommended_vendor);
      return { completed, attention, failed };
    }

    return { completed, attention: false, failed };
  };

  const completed = children.filter((c) => classifyChild(c).completed);
  const attentionItems = children.filter((c) => classifyChild(c).attention);
  const failed = children.filter((c) => classifyChild(c).failed);

  let md = `## 🎯 Your Request Summary\n\n`;
  md += `I processed **${intentCount} tasks** from your request:\n`;
  if (completed.length) md += `- ✅ **${completed.length} completed**\n`;
  if (attentionItems.length) md += `- ⚠️  **${attentionItems.length} require follow-up**\n`;
  if (failed.length) md += `- ❌ **${failed.length} failed**\n`;
  if (!attentionItems.length && !failed.length) md += `- ✅ **All tasks completed** — no follow-up needed\n`;
  md += "\n";

  if (attentionItems.length || failed.length) {
    md += `### ⚠️ What Needs Your Attention\n\n`;
    [...new Set([...attentionItems, ...failed])].forEach((c) => {
      md += `- **${getFriendlyName(c.agent)}${getDepartmentLabel(c)}**\n`;
      md += `  ${c.payload.reason || c.payload.message || c.decision?.reasoning || c.status}\n\n`;
    });
  }

  const cleanSuccesses = children.filter((c) => {
    const cls = classifyChild(c);
    return cls.completed && !cls.attention;
  });

  if (cleanSuccesses.length) {
    md += `### ✅ What Worked\n\n`;
    cleanSuccesses.forEach((c) => {
      md += `- **${getFriendlyName(c.agent)}${getDepartmentLabel(c)}:** ${c.payload.message || c.payload.reasoning || c.decision?.reasoning || "Completed"}\n`;
    });
    md += "\n";
  }

  md += `### 📋 Detailed Results\n\n`;
  children.forEach((c, i) => {
    const cls = classifyChild(c);
    const emoji = cls.failed ? "❌" : cls.attention ? "⚠️" : "✅";
    md += `**${i + 1}. ${getFriendlyName(c.agent)}${getDepartmentLabel(c)}**\n\n`;
    md += `${emoji} **Result:** ${c.payload.reason || c.payload.message || c.decision?.reasoning || c.status}\n\n`;
    if (c.payload.risk_score !== undefined) {
      md += `- Risk score: ${c.payload.risk_score}/100 (${humanize(c.payload.risk_level)})\n`;
    }
    if (Array.isArray(c.payload.assigned_approvers) && c.payload.assigned_approvers.length) {
      md += `- Approvers: ${c.payload.assigned_approvers.map((a: any) => `${a.approver_name} (${a.approver_email})`).join(", ")}\n`;
    }
    md += "\n";
  });

  return md;
}

// ─── P2P Full Workflow ─────────────────────────────────────────────────

export function formatP2PResult(r: NormalisedResult): string {
  const p = r.payload;
  const status = String(p.status || "in_progress").toLowerCase();
  const prNumber = p.pr_number || "Pending";
  const poNumber = p.po_number || "Pending";
  const vendorName = p.vendor_name || "Pending selection";
  const totalAmount = p.total_amount ? `$${Number(p.total_amount).toLocaleString()}` : "TBD";
  const summary = p.summary || p.message || "";
  const actionsCompleted: any[] = Array.isArray(p.actions_completed) ? p.actions_completed : [];
  const humanAction = p.human_action_required;
  const suggestions: string[] = Array.isArray(p.suggested_next_actions) ? p.suggested_next_actions : [];

  // P2P step definitions for display
  const P2P_STEPS = [
    { key: "compliance_check", label: "Compliance Check", icon: "📋" },
    { key: "budget_verification", label: "Budget Verification", icon: "💰" },
    { key: "vendor_selection", label: "Vendor Selection", icon: "🏢" },
    { key: "vendor_confirmation", label: "Vendor Confirmation", icon: "✋" },
    { key: "pr_creation", label: "PR Creation", icon: "📝" },
    { key: "approval_routing", label: "Approval Routing", icon: "📋" },
    { key: "approval_wait", label: "Manager Approval", icon: "✋" },
    { key: "po_creation", label: "PO Creation", icon: "📦" },
    { key: "delivery_tracking", label: "Delivery Tracking", icon: "🚚" },
    { key: "grn_entry", label: "Goods Receipt", icon: "✋" },
    { key: "quality_inspection", label: "Quality Inspection", icon: "🔍" },
    { key: "invoice_matching", label: "Invoice Matching", icon: "🧾" },
    { key: "three_way_match", label: "3-Way Match", icon: "🔗" },
    { key: "payment_readiness", label: "Payment Readiness", icon: "✅" },
    { key: "payment_execution", label: "Payment Execution", icon: "💳" },
  ];

  const normalizeStepKey = (key: string): string => {
    const k = (key || "").toLowerCase().replace(/[\-\s]+/g, "_");
    const aliases: Record<string, string> = {
      compliance: "compliance_check",
      vendor_select: "vendor_selection",
      vendor_confirm: "vendor_confirmation",
      pr_create: "pr_creation",
      approval_route: "approval_routing",
      po_create: "po_creation",
      delivery: "delivery_tracking",
      grn: "grn_entry",
      quality: "quality_inspection",
      invoice: "invoice_matching",
      three_way: "three_way_match",
      payment_ready: "payment_readiness",
      payment: "payment_execution",
    };
    return aliases[k] || k;
  };
  const completedKeys = new Set(actionsCompleted.map((a: any) => normalizeStepKey(a.step)));
  const currentStep = p.current_step || "";

  // Header
  let md = `## 🔄 Procure-to-Pay Pipeline\n\n`;

  if (summary) {
    md += `> ${summary}\n\n`;
  }

  // Key metrics
  md += mdTable(
    ["Metric", "Value"],
    [
      ["Vendor", vendorName],
      ["Total Amount", totalAmount],
      ["PR Number", prNumber],
      ["PO Number", poNumber],
      ["Status", toTitle(status.replace(/_/g, " "))],
    ]
  );
  md += "\n";

  // Pipeline progress
  const completedCount = actionsCompleted.length;
  const totalSteps = P2P_STEPS.length;
  const progressPct = Math.round((completedCount / totalSteps) * 100);
  md += `### Progress: ${completedCount}/${totalSteps} steps (${progressPct}%)\n\n`;

  // Step-by-step visualization
  for (const step of P2P_STEPS) {
    const completed = completedKeys.has(step.key);
    const isCurrent = step.key === currentStep;
    const isHumanStep = ["vendor_confirmation", "approval_wait", "grn_entry"].includes(step.key);
    const stepData = actionsCompleted.find((a: any) => normalizeStepKey(a.step) === step.key);

    let statusIcon: string;
    let stepSuffix = "";

    if (completed) {
      const stepStatus = String(stepData?.status || "completed").toLowerCase();
      if (stepStatus.includes("fail") || stepStatus.includes("reject")) {
        statusIcon = "❌";
      } else if (stepStatus.includes("skip")) {
        statusIcon = "⏭️";
      } else {
        statusIcon = "✅";
      }
      if (stepData?.summary) {
        stepSuffix = ` — ${stepData.summary}`;
      }
    } else if (isCurrent) {
      statusIcon = "⏳";
      stepSuffix = " ← **Current**";
    } else if (isHumanStep && !completed) {
      statusIcon = "🔲";
      stepSuffix = " *(human input needed)*";
    } else {
      statusIcon = "🔲";
    }

    md += `${statusIcon} ${step.icon} **${step.label}**${stepSuffix}\n`;
  }

  md += "\n";

  // Human action required
  if (humanAction) {
    md += `### ✋ Action Required\n\n`;
    const actionType = String(humanAction.type || "").replace(/_/g, " ");
    md += `**Type:** ${toTitle(actionType)}\n\n`;
    if (humanAction.message) {
      md += `${humanAction.message}\n\n`;
    }
    if (Array.isArray(humanAction.options) && humanAction.options.length > 0) {
      md += `**Options:**\n`;
      humanAction.options.forEach((opt: string) => {
        md += `- ${opt}\n`;
      });
      md += "\n";
    }
  }

  // Vendor options (when awaiting vendor confirmation)
  if (status.includes("vendor") && Array.isArray(p.top_vendor_options) && p.top_vendor_options.length > 0) {
    md += `### 📦 Recommended Vendors\n\n`;
    md += mdTable(
      ["Vendor", "Score", "Reason"],
      p.top_vendor_options.slice(0, 5).map((v: any) => [
        sanitizeCell(v.vendor_name || "Unknown"),
        `${Number(v.total_score ?? v.score ?? 0).toFixed(1)}/100`,
        sanitizeCell(v.recommendation_reason || v.reason || "-"),
      ])
    );
    md += "\n";
  }

  // Suggested next actions
  if (suggestions.length > 0) {
    md += `### 💡 What You Can Do Next\n\n`;
    suggestions.forEach((s: string) => { md += `- ${s}\n`; });
    md += "\n";
  }

  // Completed step details (collapsible style)
  if (actionsCompleted.length > 0) {
    md += `### 📊 Completed Step Details\n\n`;
    for (const action of actionsCompleted) {
      const stepDef = P2P_STEPS.find(s => s.key === action.step);
      const label = stepDef ? `${stepDef.icon} ${stepDef.label}` : toTitle(action.step || "");
      const stepStatus = String(action.status || "completed").toUpperCase();
      md += `**${label}** — ${stepStatus}`;
      if (action.agent) md += ` *(${action.agent})*`;
      md += "\n";
      if (action.summary) md += `> ${action.summary}\n`;
      md += "\n";
    }
  }

  return md;
}

// ─── Master dispatcher ──────────────────────────────────────────────────

import {
  isBudgetResult,
  isVendorResult,
  isRiskResult,
  isApprovalResult,
  isOdooPoResult,
  isPrWorkflow,
  isMultiIntent,
  isP2PWorkflow,
} from "./agentResultExtractor";

/**
 * Given a NormalisedResult, pick the right formatter and return markdown.
 */
export function isComplianceResult(r: NormalisedResult): boolean {
  const a = r.agent.toLowerCase();
  const p = r.payload;
  return (
    a.includes("compliance") &&
    (p.compliance_score !== undefined || p.violations !== undefined ||
     p.compliance_level !== undefined || p.checks !== undefined)
  );
}

function formatComplianceResult(r: NormalisedResult): string {
  const p = r.payload;
  const score = p.compliance_score ?? p.score ?? "N/A";
  const level = p.compliance_level ?? p.status ?? "Unknown";
  const dept = p.department || "General";

  let md = `## ✅ Compliance Check — ${dept}\n\n`;
  md += `**Score:** ${score}${typeof score === "number" ? "%" : ""} | **Level:** ${String(level).toUpperCase()}\n\n`;

  if (Array.isArray(p.violations) && p.violations.length > 0) {
    md += `### 🚨 Violations\n`;
    p.violations.forEach((v: any) => { md += `- ${typeof v === "string" ? v : v.message || JSON.stringify(v)}\n`; });
    md += "\n";
  }
  if (Array.isArray(p.warnings) && p.warnings.length > 0) {
    md += `### ⚠️ Warnings\n`;
    p.warnings.forEach((w: any) => { md += `- ${typeof w === "string" ? w : w.message || JSON.stringify(w)}\n`; });
    md += "\n";
  }
  if (Array.isArray(p.checks)) {
    md += `### Checks\n`;
    md += mdTable(["Check", "Status", "Details"],
      p.checks.map((c: any) => [c.name || "—", c.passed ? "✅ Pass" : "❌ Fail", c.detail || ""]));
  }
  if (p.reasoning) md += `\n**Reasoning:** ${p.reasoning}\n`;
  return md;
}

export function formatAgentMarkdown(r: NormalisedResult): string {
  if (isP2PWorkflow(r)) return formatP2PResult(r);
  if (isMultiIntent(r)) return formatMultiIntentResult(r);
  if (isPrWorkflow(r)) return formatPrWorkflowResult(r);
  if (isOdooPoResult(r)) return formatOdooPoResult(r);
  if (isBudgetResult(r)) return formatBudgetResult(r);
  if (isVendorResult(r)) return formatVendorResult(r);
  if (isRiskResult(r)) return formatRiskResult(r);
  if (isApprovalResult(r)) return formatApprovalResult(r);
  if (isComplianceResult(r)) return formatComplianceResult(r);
  return formatGenericResult(r);
}

/**
 * Build the `agentResult` object expected by the `<ResultCard>` component.
 */
export function buildResultCardProps(r: NormalisedResult): {
  agent: string;
  confidence: number;
  executionTimeMs: number;
  verdict: string;
  dataSource?: string;
  queryType?: string;
  score?: { total: number; subscores?: Record<string, number> };
  findings: Array<{ severity: "error" | "warning" | "success" | "info"; message: string }>;
  approvalChain?: Array<{ level: number; approver: string; email: string; status: string }>;
} {
  const p = r.payload;

  // P2P Full workflow: build findings from actions_completed
  if (isP2PWorkflow(r)) {
    const actions: any[] = Array.isArray(p.actions_completed) ? p.actions_completed : [];
    const findings: Array<{ severity: "error" | "warning" | "success" | "info"; message: string }> = [];
    for (const action of actions) {
      const stepStatus = String(action.status || "").toLowerCase();
      const sev: "error" | "warning" | "success" | "info" =
        stepStatus.includes("fail") || stepStatus.includes("reject") ? "error" :
        stepStatus.includes("skip") ? "warning" : "success";
      findings.push({
        severity: sev,
        message: `${toTitle(String(action.step || "").replace(/_/g, " "))}: ${action.summary || action.status || "Done"}`,
      });
    }
    if (p.human_action_required) {
      findings.push({
        severity: "warning",
        message: `Action required: ${p.human_action_required.message || toTitle(String(p.human_action_required.type || "").replace(/_/g, " "))}`,
      });
    }
    const totalSteps = 15;
    const completedCount = actions.length;
    const verdict = p.status === "completed"
      ? "P2P COMPLETE"
      : `${completedCount}/${totalSteps} STEPS COMPLETE`;

    return {
      agent: "P2POrchestrator",
      confidence: 0.95,
      executionTimeMs: r.executionTimeMs ?? 0,
      verdict,
      dataSource: "Agentic",
      queryType: "P2P_FULL",
      score: { total: Math.round((completedCount / totalSteps) * 100), subscores: {} },
      findings,
      approvalChain: undefined,
    };
  }

  // PR Workflow: dedicated handler for purchase request creation results
  if (isPrWorkflow(r)) {
    const p = r.payload;
    const status = String(p.status || "").toLowerCase();
    const verdictMap: Record<string, string> = {
      success: "PR CREATED",
      success_no_workflow: "PR CREATED",
      awaiting_vendor_confirmation: "VENDOR SELECTION REQUIRED",
      failed: "PR VALIDATION FAILED",
      needs_clarification: "CLARIFICATION NEEDED",
      in_progress: "IN PROGRESS",
    };

    const findings: Array<{severity: "error"|"warning"|"success"|"info"; message: string}> = [];

    // Extract from validations
    const validations = p.validations || {};
    const compliance = validations.compliance?.result || {};
    if (Array.isArray(compliance.violations)) {
      compliance.violations.forEach((v: string) => findings.push({severity: "error", message: v}));
    }
    if (Array.isArray(compliance.warnings)) {
      compliance.warnings.forEach((w: string) => findings.push({severity: "warning", message: w}));
    }
    if (Array.isArray(p.warnings)) {
      p.warnings.forEach((w: string) => {
        if (!findings.some(f => f.message === w)) findings.push({severity: "warning", message: w});
      });
    }

    // Status-specific findings
    if (status === "success" || status === "success_no_workflow") {
      findings.push({severity: "success", message: `PR ${p.pr_object?.pr_number || ''} created and submitted for approval`});
    }
    if (status === "awaiting_vendor_confirmation") {
      const vendorCount = Array.isArray(p.top_vendor_options) ? p.top_vendor_options.length : 0;
      findings.push({severity: "info", message: `${vendorCount} vendors shortlisted — select one to continue`});
    }
    if (p.vendor_selection_note) {
      findings.push({severity: "info", message: p.vendor_selection_note});
    }

    // Budget info
    const budgetResult = validations.budget?.result || {};
    if (budgetResult.budget_verified) {
      findings.push({severity: "success", message: `Budget verified: $${Number(budgetResult.available_budget || 0).toLocaleString()} available`});
    }

    return {
      agent: r.agent,
      confidence: r.decision?.confidence ?? 0.95,
      executionTimeMs: r.executionTimeMs ?? 0,
      verdict: verdictMap[status] || status.toUpperCase().replace(/_/g, " "),
      dataSource: r.dataSource,
      queryType: "CREATE",
      score: undefined,
      findings,
      approvalChain: undefined,
    };
  }

  // Multi-intent: build findings from children instead of outer envelope
  if (isMultiIntent(r) && r.multiResults?.length) {
    const findings: Array<{ severity: "error" | "warning" | "success" | "info"; message: string }> = [];
    const getFriendlyName = (agent: string): string => {
      const a = agent.toLowerCase();
      if (a.includes("budget")) return "Budget Check";
      if (a.includes("risk")) return "Risk Assessment";
      if (a.includes("approval")) return "Approval Routing";
      if (a.includes("vendor")) return "Vendor Selection";
      return agent;
    };
    const classify = (child: NormalisedResult) => {
      const agent = (child.agent || "").toLowerCase();
      const status = String(child.status || "").toLowerCase().replace(/_/g, " ");
      const reasonBlob = String(child.payload.reason || child.payload.message || child.decision?.reasoning || "").toLowerCase();
      const failed = ["error", "failed", "exception", "timeout", "crash"].some((bad) => status.includes(bad));
      const completed = !failed;

      if (agent.includes("budget")) {
        const attention =
          child.payload.budget_verified === false ||
          reasonBlob.includes("critical threshold") ||
          reasonBlob.includes("insufficient budget");
        return { completed, attention, failed };
      }
      if (agent.includes("risk")) {
        const riskLevel = String(child.payload.risk_level || "").toLowerCase();
        const attention =
          child.payload.requires_human_review === true ||
          child.payload.can_proceed === false ||
          riskLevel === "medium" || riskLevel === "high" || riskLevel === "critical" ||
          reasonBlob.includes("review recommended");
        return { completed, attention, failed };
      }
      if (agent.includes("approval")) {
        return { completed, attention: Boolean(child.payload.analysis_only || !child.payload.workflow_id), failed };
      }
      if (agent.includes("vendor")) {
        return { completed, attention: !Boolean(child.payload.primary_recommendation || child.payload.recommended_vendor), failed };
      }
      return { completed, attention: false, failed };
    };

    const deptLabel = (child: NormalisedResult): string => {
      const dept =
        child.payload?.department
        || child.payload?.context?.department
        || child.payload?.input_context?.pr_data?.department;
      return dept ? ` (${String(dept).toUpperCase()})` : "";
    };

    for (const child of r.multiResults) {
      const cls = classify(child);
      const label = getFriendlyName(child.agent);
      const detail =
        child.payload.reason ||
        child.payload.message ||
        child.decision?.reasoning ||
        child.status;
      findings.push({
        severity: cls.failed ? "error" : cls.attention ? "warning" : "success",
        message: `${label}${deptLabel(child)}: ${detail}`,
      });
    }
    const successes = r.multiResults.filter((c) => {
      const cls = classify(c);
      return cls.completed && !cls.attention;
    }).length;
    const warnings = r.multiResults.filter((c) => classify(c).attention).length;
    const errors = r.multiResults.filter((c) => classify(c).failed).length;
    const total = r.multiResults.length;
    let verdict = `${successes}/${total} COMPLETED`;
    if (errors === 0 && warnings === 0 && successes === total) verdict = `ALL ${total} TASKS COMPLETED`;
    else if (errors === 0 && warnings > 0) verdict = `${total} COMPLETED (${warnings} NEED FOLLOW-UP)`;
    else if (errors > 0) verdict = `${total - errors}/${total} COMPLETED (${errors} FAILED)`;

    return {
      agent: r.agent,
      confidence: r.decision?.confidence ?? 0.95,
      executionTimeMs: r.executionTimeMs ?? 0,
      verdict,
      dataSource: r.dataSource,
      queryType: r.queryType || undefined,
      score: undefined,
      findings,
      approvalChain: undefined,
    };
  }

  // Score
  let score: { total: number; subscores?: Record<string, number> } | undefined;
  if (p.score && typeof p.score === "object") {
    score = { total: p.score.total ?? p.score, subscores: p.score.subscores };
  } else if (p.risk_score !== undefined) {
    const subscores: Record<string, number> = {};
    const bd = p.risk_scores || p.breakdown || {};
    Object.entries(bd).forEach(([k, v]) => {
      // v may be a flat number or nested object {score, weight, concerns}
      subscores[k] = (v && typeof v === "object" && "score" in v) ? Number(v.score) : Number(v);
    });
    score = { total: p.risk_score, subscores };
  } else if (p.overall_score !== undefined || p.performance_score !== undefined) {
    score = {
      total: Number(p.overall_score ?? p.performance_score),
      subscores: {
        ...(p.delivery_score !== undefined && { delivery: p.delivery_score }),
        ...(p.quality_score !== undefined && { quality: p.quality_score }),
        ...(p.price_score !== undefined && { price: p.price_score }),
        ...(p.communication_score !== undefined && { communication: p.communication_score }),
      },
    };
  } else if (p.compliance_score !== undefined) {
    score = { total: p.compliance_score, subscores: {} };
  } else if (p.primary_recommendation?.score !== undefined) {
    score = { total: p.primary_recommendation.score, subscores: {} };
  }

  // Findings
  const findings: Array<{ severity: "error" | "warning" | "success" | "info"; message: string }> = [];
  const addArr = (arr: any, sev: "error" | "warning" | "success" | "info") => {
    if (!Array.isArray(arr)) return;
    arr.forEach((msg: string) => {
      if (!findings.some((f) => f.severity === sev && f.message === msg)) {
        findings.push({ severity: sev, message: msg });
      }
    });
  };
  addArr(p.violations, "error");
  addArr(p.warnings, "warning");
  addArr(p.successes, "success");
  addArr(p.info, "info");
  addArr(p.recommended_actions, "info");
  addArr(p.mitigations, "info");
  // Budget-specific findings
  if (p.budget_verified === false && p.reason) {
    findings.push({ severity: "error", message: String(p.reason) });
  } else if (p.budget_verified === true) {
    findings.push({ severity: "success", message: "Budget verified and approved" });
  }
  if (findings.length === 0 && (p.reasoning || r.decision?.reasoning)) {
    findings.push({ severity: "info", message: String(p.reasoning || r.decision?.reasoning) });
  }

  // Approval chain
  let approvalChain: Array<{ level: number; approver: string; email: string; status: string }> | undefined;
  if (Array.isArray(p.approval_chain) && p.approval_chain.length > 0) {
    approvalChain = p.approval_chain.map((s: any) => ({
      level: s.level ?? s.approval_level,
      approver: s.approver ?? s.approver_name,
      email: s.email ?? s.approver_email,
      status: s.status || "pending",
    }));
  } else if (Array.isArray(p.assigned_approvers) && p.assigned_approvers.length > 0) {
    approvalChain = p.assigned_approvers.map((s: any) => ({
      level: s.approval_level,
      approver: s.approver_name,
      email: s.approver_email,
      status: s.status || "pending",
    }));
  }

  return {
    agent: r.agent,
    confidence: r.decision?.confidence ?? 0.95,
    executionTimeMs: r.executionTimeMs ?? 0,
    verdict: (p.status || p.action || "completed").toUpperCase(),
    dataSource: r.dataSource,
    queryType: r.queryType || undefined,
    score,
    findings,
    approvalChain,
  };
}
