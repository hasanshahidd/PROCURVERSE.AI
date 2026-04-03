# Four Completed Agentic Workflows (Business View)

Last updated: 2026-03-18
Scope: Only what is currently live and already demonstrated as completed for these 4 workflows.

This document is written in business terms only: what the platform is doing today, which agent contributes what, why it matters, and how the end-to-end outcome is produced.

## 1) Executive Summary: What is live right now

The current live procurement intelligence layer is delivering 4 completed business workflows:

1. Budget Verification
2. Vendor Selection
3. Risk Assessment
4. PR Creation (with human vendor confirmation, approval routing, and risk visibility)

Business result:
- Procurement decisions are now guided by structured checks instead of ad-hoc chat replies.
- Finance control, policy control, and risk visibility are embedded into the same flow.
- Human oversight remains where it matters most (vendor confirmation in the PR path).

## 2) Business problem this solves

Before this setup, teams typically faced:
- Budget uncertainty at request time.
- Inconsistent vendor selection logic.
- Risk reviewed too late or not systematically.
- PRs created without reliable governance sequence.

Current platform behavior addresses these by making each request pass through clear decision stages that are understandable by business users.

## 3) Business role of each active agent

### A) BudgetVerificationAgent

Business role:
- Acts as finance guardrail before commitments.

What it decides:
- Whether requested spend is acceptable now.
- Whether utilization is in safe, warning, high, or critical band.

Business value delivered:
- Prevents overspending.
- Gives early utilization alerts.
- Reduces late-stage rejection waste.

### B) VendorSelectionAgent

Business role:
- Acts as a procurement recommender with transparent rationale.

What it decides:
- Ranks vendors and proposes a top shortlist (currently top 5).
- Identifies strengths and concerns for each recommendation.

Business value delivered:
- Standardized supplier choice.
- Better auditability of why a vendor was selected.
- Better negotiation posture through alternatives.

### C) RiskAssessmentAgent

Business role:
- Converts procurement requests into a measurable risk profile.

What it decides:
- Risk score and risk level across four lenses:
  - vendor
  - financial
  - compliance
  - operational
- Suggested mitigations and whether review escalation is needed.

Business value delivered:
- Risk-aware procurement instead of reactive firefighting.
- Consistent risk communication for business and leadership.
- Better quality decisions on large or sensitive requests.

### D) ComplianceCheckAgent

Business role:
- Performs policy fit check before progressing PR in the orchestrated flow.

What it decides:
- Whether request is compliant, needs warning-based continuation, needs correction, or must be blocked.

Business value delivered:
- Reduces policy breach risk.
- Ensures required request quality (for example, sufficient justification).

### E) ApprovalRoutingAgent

Business role:
- Converts approved PR intent into a real approval chain path.

What it decides:
- Which approval level path is required by amount and department.
- Which approvers are assigned for the request.

Business value delivered:
- Reliable governance workflow.
- Clear accountability and approval ownership.

### F) Orchestrator

Business role:
- Coordinates all relevant agents in correct order for complex workflows.

What it does:
- Runs checks in sequence.
- Pauses for human decision when needed.
- Continues automatically once user confirms vendor.

Business value delivered:
- One business conversation can complete a multi-step governed process.
- Fewer handoffs and fewer missed checks.

## 4) Completed Workflow 1: Budget Verification

### What the business user is trying to do
- Confirm whether a planned purchase can move forward financially.

### How the workflow behaves today
1. Reads department, amount, and budget type.
2. Evaluates available budget and projected utilization after request.
3. Returns outcome as approved or rejected, with alert severity where relevant.

### Business outcomes currently observed
- Approved outcomes exist.
- Rejected outcomes exist.
- Alerts are raised when utilization bands are tight.

### Why this is complete
- It is not a placeholder; it is returning production-style decision statuses and guidance already used in demos and testing.

## 5) Completed Workflow 2: Vendor Selection

### What the business user is trying to do
- Get best-fit supplier recommendations for an item/category and budget context.

### How the workflow behaves today
1. Builds vendor pool for the need.
2. Scores vendors on quality, price, delivery, and category fit.
3. Returns ranked recommendation with alternatives and reasons.

### Business outcomes currently observed
- Recommendation status is returning successfully.
- Primary and alternative vendors are presented.
- Top-5 shortlist behavior is active.

### Why this is complete
- The recommendation model is operational and integrated into PR flow pause/confirm behavior.

## 6) Completed Workflow 3: Risk Assessment

### What the business user is trying to do
- Understand if a purchase is low, medium, high, or critical risk before committing.

### How the workflow behaves today
1. Builds risk context from request details.
2. Computes weighted risk across vendor, financial, compliance, operational dimensions.
3. Returns risk level, score, top concerns, and mitigation guidance.

### Business outcomes currently observed
- Low-risk proceed outcomes are being returned in validated scenarios.
- Risk-level and breakdown are available to decision makers.

### Why this is complete
- Risk output is structured, repeatable, and already used both standalone and as part of PR completion visibility.

## 7) Completed Workflow 4: PR Creation (Governed Conversational Flow)

### What the business user is trying to do
- Create a purchase request through one guided conversation while preserving governance controls.

### How the workflow behaves today
1. Compliance check runs first.
2. Budget check runs second.
3. Vendor shortlist is prepared.
4. Workflow pauses and asks user to confirm one vendor.
5. After confirmation, PR is finalized with approval routing.
6. Risk snapshot is added for visibility (non-blocking to finalization).

### Human-in-loop behavior currently active
- User must confirm vendor to continue.
- This pause is intentional and part of control design.

### Business outcomes currently observed
- Step 1 result: waiting for vendor confirmation.
- Step 2 result: successful completion after confirmation.

### Why this is complete
- It executes the full business cycle from request intent to governed PR completion with approvals and risk visibility.

## 8) How the 4 workflows fit together as one business operating model

Current practical sequence used by teams:

1. Budget feasibility
2. Vendor recommendation
3. Risk clarity
4. PR creation with human vendor selection and approval routing

What this achieves:
- Better decision quality before commitment.
- Faster cycle time with fewer rework loops.
- Clear ownership at each stage (finance, procurement, approvers, requester).

## 9) Current coverage boundaries (what is intentionally true today)

1. Vendor confirmation is required in PR flow before final success.
2. Risk snapshot after PR completion is informational and non-blocking.
3. Budget results can be approved or rejected depending on live budget state.
4. These four workflows are already functioning as the core completed business path.

## 10) Final business statement

The platform is currently operating as a governed procurement decision assistant, not just a chatbot. The completed value today is clear:

- Financial control at intake
- Evidence-based supplier choice
- Structured risk governance
- End-to-end PR progression with human confirmation and approval ownership

This is the active, completed scope for the four workflows in business terms.
