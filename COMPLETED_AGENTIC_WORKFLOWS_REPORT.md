# Completed Agentic Workflows Report (Verified Working)

Last Updated: 2026-03-17
System: Procurement AI Platform (Agentic + Odoo)

This document covers only the workflows/agents that are currently implemented, tested, and working in the live backend.

---

## 1) Scope of This Report

This report includes 5 verified working flows:

1. Budget Verification Flow
2. Vendor Selection Flow
3. Risk Assessment Flow
4. PR Creation Flow (with Vendor Confirmation and Auto Risk Snapshot)
5. Combined Multi-Intent Flow (Budget + Risk)

These were validated through live API execution on `/api/agentic/execute` and direct agent endpoints during current testing.

---

## 2) Completed/Working Agents Used in These Flows

The following agents are actively used in the verified flows:

1. `BudgetVerificationAgent`
2. `VendorSelectionAgent`
3. `RiskAssessmentAgent`
4. `ComplianceCheckAgent`
5. `ApprovalRoutingAgent`
6. `Orchestrator` (routing + workflow sequencing)

---

## 3) Flow #1 - Budget Verification (Working)

### Purpose
Checks if requested budget is available for a department/category and returns approval/rejection with utilization info.

### Primary Agent
`BudgetVerificationAgent`

### Input Example (Verified)
`Check IT budget for $2 OPEX`

### What It Does

1. Reads department + amount + budget category
2. Queries budget availability
3. Calculates utilization impact
4. Returns decision (`approved`/`rejected`) with alert level

### Observed Working Behavior

- Returned status: `approved`
- Returned warning when utilization reached critical threshold

### Business Value

- Prevents over-commitment
- Gives finance visibility before approvals

---

## 4) Flow #2 - Vendor Selection (Working)

### Purpose
Evaluates vendors and recommends the best option for the requested item/category.

### Primary Agent
`VendorSelectionAgent`

### Input Example (Verified)
`Find best vendor for office chairs for IT with budget $2`

### What It Does

1. Pulls eligible vendors
2. Scores each vendor by weighted criteria
3. Returns primary recommendation + alternatives
4. Provides reason text for each recommendation

### Observed Working Behavior

- Returned status: `recommended`
- Returned primary vendor (example observed: `Ready Mat`)
- Returned alternatives and scores

### Business Value

- Standardizes vendor decisioning
- Improves transparency of procurement choice

---

## 5) Flow #3 - Risk Assessment (Working)

### Purpose
Computes procurement risk across four dimensions and provides actionable recommendations.

### Primary Agent
`RiskAssessmentAgent`

### Input Example (Verified)
`Assess risk for ordering from Office Depot LLC, $25k, IT OPEX, requester: John Smith, justification: Office equipment renewal for operational continuity`

### Risk Model

Weighted scoring:

1. Vendor Risk (30%)
2. Financial Risk (30%)
3. Compliance Risk (25%)
4. Operational Risk (15%)

### What It Does

1. Builds risk context from request
2. Scores each risk dimension
3. Computes total weighted score
4. Assigns level (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
5. Returns recommendations/mitigations

### Observed Working Behavior

- Returned status: `low_risk_proceed`
- Returned level and score consistently
- Returned dimension-wise risk breakdown

### Business Value

- Converts raw checks into decision-quality risk insight
- Supports safer procurement decisions

---

## 6) Flow #4 - PR Creation Workflow (Working)

### Purpose
Creates a purchase request using orchestrated validations and approval workflow setup.

### Workflow Controller
`Orchestrator` (`pr_creation` workflow)

### Agents Involved

1. `ComplianceCheckAgent`
2. `BudgetVerificationAgent`
3. `VendorSelectionAgent` (confirmation gate)
4. `ApprovalRoutingAgent`
5. `RiskAssessmentAgent` (auto post-create snapshot for visibility)

### Input Example (Step 1, Verified)
`Create PR for IT department, budget $2, buy 7 office chairs, OPEX, justification: Office chairs replacement for operations continuity`

### Step 1 Observed Behavior

- Status: `awaiting_vendor_confirmation`
- Returns vendor shortlist and prompts user to confirm one

### Input Example (Step 2 Confirm, Verified)
`CONFIRM_VENDOR: Ready Mat. Continue PR creation workflow with department IT, budget $2, category Office Supplies, product Office Chairs, quantity 7, budget category OPEX, business justification: Office chairs replacement for operations continuity.`

### Step 2 Observed Behavior

- Status: `success`
- PR created
- Approval workflow initialized
- Risk Snapshot shown in PR success response

### Business Value

- Full PR lifecycle initiation from one conversational workflow
- Human-in-loop vendor confirmation before completion
- Built-in visibility of risk at PR completion stage

---

## 7) Flow #5 - Combined Multi-Intent (Budget + Risk) (Working)

### Purpose
Executes multiple analysis intents in one user query.

### Controller
`MultiIntentOrchestrator`

### Input Example (Verified)
`Check IT budget with amount 2 USD and budget category OPEX. Then assess risk for ordering from Office Depot LLC with amount 25000 USD, requester John Smith, justification Office equipment renewal for operational continuity.`

### What It Does

1. Detects 2 intents from one query
2. Runs Budget and Risk sequentially
3. Returns combined summary and per-intent results

### Observed Working Behavior

- Returned `intent_count = 2`
- Budget child intent completed
- Risk child intent completed

### Business Value

- Faster analyst workflow
- Single prompt for multi-step procurement checks

---

## 8) Current Production-Ready Demo Sequence

For demonstrations, use this order:

1. Budget check
2. Vendor recommendation
3. Risk assessment
4. PR creation (step 1)
5. Vendor confirmation (step 2)
6. Optional combined budget+risk query

A verified query list is maintained in:

`TESTED_DEMO_QUERIES.md`

---

## 9) Known Constraints (Current)

1. PR creation intentionally pauses for vendor confirmation before final success
2. Combined query amount parsing is most reliable with explicit `amount ... USD` phrasing
3. Risk details are now visible inside PR success snapshot, and full standalone risk output remains available

---

## 10) Conclusion

The system currently has a stable and demonstrable core with 5 working flows:

1. Budget verification
2. Vendor recommendation
3. Risk assessment
4. PR creation workflow (with confirmation gate + risk snapshot)
5. Multi-intent budget+risk orchestration

These flows are validated in live backend execution and are ready for guided demo use.
