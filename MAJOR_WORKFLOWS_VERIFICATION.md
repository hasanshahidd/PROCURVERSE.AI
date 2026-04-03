# 4 MAJOR AGENTIC WORKFLOWS - COMPLETE VERIFICATION

## Executive Summary
You have **4 MAJOR end-to-end workflows** that write actual business data. Each workflow uses multiple agents orchestrated together.

---

## WORKFLOW 1: CREATE (Full PR Creation Pipeline) ⭐ MOST COMPREHENSIVE

**What it does:** Creates a complete Purchase Requisition from scratch with all validations and approval routing.

**Query triggers:**
- "Create a PR for IT department, $50k servers"
- "I need to buy office supplies, budget $20k"
- "Submit a purchase request for electronics"
- "Raise a requisition for $75k furniture"

**Agents involved (5 agents in sequence):**
1. **ComplianceCheckAgent** - Validates against policies, preferred vendor lists, regulations
2. **BudgetVerificationAgent** - Checks budget availability, updates committed budget
3. **PriceAnalysisAgent** - [Optional] Analyzes if quoted price is fair (only if price provided)
4. **ApprovalRoutingAgent** - Creates approval workflow, assigns approvers (Manager → Director → VP/CFO)
5. [Creates PR object with PR number like PR-2026-031501234]

**What gets WRITTEN:**
- `budget_tracking` table → UPDATE `committed_budget` (+$amount)
- `pr_approval_workflows` table → INSERT new workflow record (PR number, department, amount, status)
- `pr_approval_steps` table → INSERT 2-3 rows (one per approver level)
- `agent_actions` table → INSERT 5 audit records (one per agent)

**Business outcome:** Complete PR created, budget reserved, approvers assigned, ready for approval process.

**Classification:** `query_type: "CREATE"` or `"PR_CREATION"`

---

## WORKFLOW 2: BUDGET VERIFICATION (Standalone Budget Check)

**What it does:** Checks if budget is available for a specific request and optionally reserves/commits it.

**Query triggers:**
- "Check budget for Operations department, $50k CAPEX"
- "Do we have budget for IT, $100k?"
- "What's the budget status for Finance OPEX?"
- "Can we afford $25k from Procurement budget?"

**Agents involved (1 agent):**
1. **BudgetVerificationAgent** - Checks budget availability, calculates utilization, updates committed budget

**What gets WRITTEN:**
- `budget_tracking` table → UPDATE `committed_budget` (+$amount) [if approved]
- `agent_actions` table → INSERT 1 audit record

**Business outcome:** Budget availability confirmed, funds reserved (committed) for future purchase.

**Classification:** `query_type: "BUDGET"`

---

## WORKFLOW 3: VENDOR SELECTION (Vendor Scoring + PO Creation) ⭐ CREATES ODOO PO

**What it does:** Scores all vendors based on quality/price/delivery/category expertise, recommends best vendor, **creates actual Purchase Order in Odoo ERP**.

**Query triggers:**
- "Find best vendor for electronics equipment"
- "Recommend a vendor for office supplies, budget $30k"
- "Which vendor should I use for IT hardware?"
- "Choose the best supplier for furniture"

**Agents involved (1 agent + Odoo):**
1. **VendorSelectionAgent** - Multi-criteria scoring (Quality 40%, Price 30%, Delivery 20%, Category 10%)
   - Fetches all Odoo vendors
   - Filters by category if specified
   - Scores each vendor 0-100
   - Returns top 3 recommendations
   - **Creates Purchase Order in Odoo** with vendor notes

**What gets WRITTEN:**
- **Odoo `purchase.order` table** → INSERT new PO record (vendor, line items, notes)
- **Odoo `purchase.order` table** → UPDATE notes field with scoring breakdown
- `agent_actions` table → INSERT 1 audit record

**Business outcome:** Best vendor identified with scoring justification, **actual PO created in Odoo** ready for approval.

**Classification:** `query_type: "VENDOR"`

**Example PO notes written to Odoo:**
```
Vendor: TechSupply Co
Score: 72.0/100
Reason: Best choice due to: reasonable pricing, reliable delivery

Scoring Breakdown:
{
  "quality": 27,
  "price": 23.0,
  "delivery": 19.0,
  "category": 3.0
}

Strengths: Competitive pricing, Reliable delivery
Concerns: Limited category experience

Alternative Vendors:
[{"name": "Ready Mat", "score": 71.0}, {"name": "Office Depot LLC", "score": 55.0}]
```

---

## WORKFLOW 4: RISK ASSESSMENT (4-Dimensional Risk Analysis)

**What it does:** Analyzes procurement risks across 4 dimensions (Vendor 30%, Financial 30%, Compliance 25%, Operational 15%), stores assessment, recommends mitigation actions.

**Query triggers:**
- "Assess risks for ordering from Office Depot LLC, $25k"
- "What are the risks of this $100k purchase?"
- "Analyze procurement risks for vendor Acme Corporation"
- "Is this purchase risky?"

**Agents involved (1 agent):**
1. **RiskAssessmentAgent** - 4-dimensional risk scoring:
   - **Vendor Risk** (30%): Vendor history, payment terms, on-time delivery, quality issues
   - **Financial Risk** (30%): Budget exceeded, amount vs threshold, payment terms
   - **Compliance Risk** (25%): Requester identified, justification provided, approvals complete
   - **Operational Risk** (15%): Urgency vs lead time, inventory impact, supplier capacity
   - Resolves vendor name → Odoo vendor ID (fuzzy matching)
   - Returns risk level: LOW (<30), MEDIUM (30-60), HIGH (60-80), CRITICAL (>80)

**What gets WRITTEN:**
- `po_risk_assessments` table → INSERT new assessment record (PR number, risk level, score, breakdown, mitigations)
- `agent_actions` table → INSERT 1 audit record

**Business outcome:** Risk level determined (LOW/MEDIUM/HIGH/CRITICAL), mitigation actions recommended, assessment stored for audit trail.

**Classification:** `query_type: "RISK"`

**Example risk assessment stored:**
```json
{
  "pr_number": "Unknown",
  "risk_level": "LOW",
  "risk_score": 21.8,
  "vendor_risk": 0.0,
  "financial_risk": 40.0,
  "compliance_risk": 30.0,
  "operational_risk": 15.0,
  "mitigations": [],
  "can_proceed": true,
  "blocked_po_creation": false
}
```

---

## WORKFLOW 5: APPROVAL ROUTING (Standalone - Can be used alone or part of CREATE)

**What it does:** Determines approval chain based on department and amount, creates workflow records, assigns approvers.

**Query triggers:**
- "Route PR-2026-0300 for IT department, $75k"
- "Who needs to approve this Finance request, $120k?"
- "Route approval for this purchase"
- "Assign approvers for $50k Operations requisition"

**Agents involved (1 agent):**
1. **ApprovalRoutingAgent** - Multi-level approval routing:
   - Queries `approval_chains` table for department rules
   - Determines required approval level based on amount:
     - Level 1 (Manager): Up to $10k
     - Level 2 (Director): $10k - $50k
     - Level 3 (VP/CFO): >$50k
   - Auto-generates PR number if not provided (PR-2026-XXXX)
   - Creates workflow + approval steps in database

**What gets WRITTEN:**
- `pr_approval_workflows` table → INSERT workflow record (PR number, department, amount, current level, status)
- `pr_approval_steps` table → INSERT 2-3 rows (one per required approver: Mike Manager, Diana Director, Victor VP)
- `agent_actions` table → INSERT 1 audit record

**Business outcome:** Approval chain established, approvers notified, workflow tracking enabled.

**Classification:** `query_type: "APPROVAL"`

**Note:** This workflow is ALSO executed as Step 5 of the CREATE workflow. When used standalone, it routes an existing PR. When used in CREATE, it routes the newly-created PR.

---

## COMPARISON TABLE

| Workflow | Agents Used | Odoo Writes | Custom DB Writes | End-to-End? | Business Impact |
|----------|-------------|-------------|------------------|-------------|-----------------|
| **CREATE** | 5 (compliance, budget, price, approval, PR object) | None | budget_tracking, pr_approval_workflows, pr_approval_steps | ✅ Yes | **Complete PR creation pipeline** |
| **BUDGET** | 1 (budget_verification) | None | budget_tracking | ❌ No (validation only) | Budget check + commit |
| **VENDOR** | 1 (vendor_selection) | **purchase.order** | None | ⚠️ Partial | Vendor recommendation + **PO creation** |
| **RISK** | 1 (risk_assessment) | None | po_risk_assessments | ❌ No (analysis only) | Risk analysis + storage |
| **APPROVAL** | 1 (approval_routing) | None | pr_approval_workflows, pr_approval_steps | ⚠️ Partial | Approval chain setup |

---

## THE 4 MAJOR WORKFLOWS YOUR CEO MEANT

Based on business impact and end-to-end coverage, the **4 major workflows** are:

1. **CREATE (PR Creation)** - Most comprehensive, full pipeline
2. **VENDOR (Vendor Selection + PO)** - Only one that writes to Odoo
3. **BUDGET (Budget Verification)** - Financial control
4. **RISK (Risk Assessment)** - Risk management

**APPROVAL** is technically a sub-workflow of CREATE, but can be used standalone to route existing PRs.

---

## QUERY EXAMPLES FOR EACH WORKFLOW

### CREATE Workflow
```
"Create a PR for IT department, $50,000 servers"
"I need to buy office supplies for Finance, budget $20k"
"Submit a purchase request for electronics equipment"
"Raise a requisition for $75k furniture for Operations"
```

### VENDOR Workflow
```
"Find best vendor for electronics equipment under $50k"
"Recommend a vendor for office supplies, budget $30k"
"Which vendor should I use for IT hardware?"
"Choose the best supplier for furniture"
```

### BUDGET Workflow
```
"Check budget for Operations department, $50k CAPEX"
"Do we have budget for IT department, $100k OPEX?"
"What's the budget status for Finance?"
"Can we afford $25k from Procurement budget?"
```

### RISK Workflow
```
"Assess risks for ordering from Office Depot LLC, $25k"
"What are the risks of this $100k purchase from Acme?"
"Analyze procurement risks for vendor TechSupply Co"
"Is this purchase risky? Vendor: XYZ Corp, Amount: $120k"
```

### APPROVAL Workflow (Standalone)
```
"Route PR-2026-0300 for IT department, $75k"
"Who needs to approve this Finance request for $120k?"
"Route approval for this Operations purchase, $50k"
"Assign approvers for $80k IT requisition, PR-2026-0400"
```

---

## WHAT EACH WORKFLOW ACTUALLY CREATES IN THE DATABASE

### CREATE Workflow Database Changes
```sql
-- Step 1: Budget commit
UPDATE budget_tracking 
SET committed_budget = committed_budget + 50000 
WHERE department = 'IT' AND budget_category = 'CAPEX';

-- Step 2: Create PR workflow
INSERT INTO pr_approval_workflows (
    pr_number, department, total_amount, requester_name, 
    current_level, status, created_at
) VALUES (
    'PR-2026-031501234', 'IT', 50000, 'John Doe', 
    1, 'pending', NOW()
);

-- Step 3: Create approval steps (3 rows)
INSERT INTO pr_approval_steps (workflow_id, approval_level, approver_email, approver_name, status)
VALUES 
    (123, 1, 'mike.manager@company.com', 'Mike Manager', 'pending'),
    (123, 2, 'diana.director@company.com', 'Diana Director', 'pending'),
    (123, 3, 'victor.vp@company.com', 'Victor VP', 'pending');
```

### VENDOR Workflow Database Changes
```python
# Odoo XML-RPC call
odoo.execute_kw('purchase.order', 'create', [{
    'partner_id': 66,  # Industrial Parts Inc
    'order_line': [[0, 0, {
        'product_id': 45,
        'product_qty': 10,
        'price_unit': 5000.0
    }]]
}])
# Returns PO ID: 234

# Update PO with vendor selection notes
odoo.execute_kw('purchase.order', 'write', [234, {
    'notes': '''Vendor: Industrial Parts Inc
Score: 72.0/100
Reason: Best choice due to: reasonable pricing, reliable delivery...'''
}])
```

### RISK Workflow Database Changes
```sql
INSERT INTO po_risk_assessments (
    pr_number, vendor_id, risk_level, risk_score,
    vendor_risk, financial_risk, compliance_risk, operational_risk,
    mitigations, can_proceed, blocked_po_creation, created_at
) VALUES (
    'Unknown', 65, 'LOW', 21.8,
    0.0, 40.0, 30.0, 15.0,
    '[]'::jsonb, true, false, NOW()
);
```

---

## VERIFICATION CHECKLIST ✅

- [x] **CREATE workflow** uses 5 agents (compliance → budget → price → approval → PR object)
- [x] **VENDOR workflow** creates real PO in Odoo (`purchase.order` table)
- [x] **BUDGET workflow** updates `committed_budget` in `budget_tracking`
- [x] **RISK workflow** stores assessment in `po_risk_assessments`
- [x] **APPROVAL workflow** creates workflow + steps in custom DB (can be standalone or part of CREATE)
- [x] All workflows write to `agent_actions` for audit trail
- [x] Query classification correctly routes to each workflow via `query_type`
- [x] Each workflow returns structured results for frontend display

---

## WHEN TO USE WHICH WORKFLOW

| User Need | Use This Workflow | Why |
|-----------|-------------------|-----|
| "I need to submit a complete purchase request" | **CREATE** | Full pipeline with all validations |
| "Just check if we have budget" | **BUDGET** | Quick budget availability check |
| "Find me a good vendor" | **VENDOR** | Vendor comparison + PO creation |
| "Is this purchase safe?" | **RISK** | Risk analysis before committing |
| "Route this existing PR for approval" | **APPROVAL** | Setup approval chain for existing PR |

