# 🧪 Complete System Test Queries

## 📋 Quick Reference - All Agent Categories

| Agent | Test Queries | Expected Agent |
|-------|-------------|----------------|
| [Budget Verification](#1-budget-verification-agent) | 5 queries | BudgetVerificationAgent |
| [Approval Routing](#2-approval-routing-agent) | 6 queries | ApprovalRoutingAgent |
| [Vendor Selection](#3-vendor-selection-agent) | 5 queries | VendorSelectionAgent |
| [Risk Assessment](#4-risk-assessment-agent) | 6 queries | RiskAssessmentAgent |
| [Contract Monitoring](#5-contract-monitoring-agent) | 5 queries | ContractMonitoringAgent |
| [Supplier Performance](#6-supplier-performance-agent) | 5 queries | SupplierPerformanceAgent |
| [Compliance Check](#7-compliance-check-agent) | 4 queries | ComplianceCheckAgent |
| [PR Creation Workflow](#8-pr-creation-workflow-complete) | 8 queries | PRCreationWorkflow |
| [Multi-Intent Orchestration](#9-multi-intent-queries) | 6 queries | MultiIntentOrchestrator |
| [Odoo Data](#10-odoo-integration-queries) | 5 queries | OdooQueryAgent |
| [General Analytics](#11-general-procurement-analytics) | 5 queries | GeneralAgent |

---

## 1. 💰 Budget Verification Agent

### Simple Budget Checks
```
Check IT budget availability
```
**Expected:** Shows allocated, spent, committed, available budget for IT department

```
Verify Finance department has 50k available for CAPEX purchase
```
**Expected:** Budget verification with threshold alerts (80%, 90%, 95% utilization)

### Budget with Category
```
Check budget for 75k IT OPEX expense
```
**Expected:** OPEX-specific budget check with availability confirmation

```
Is there 100k available in Operations CAPEX budget?
```
**Expected:** CAPEX budget check with alert if utilization > 90%

### Budget Status Overview
```
Show me all department budget statuses
```
**Expected:** Table with 4 departments (IT, Finance, Operations, Procurement) × 2 categories (CAPEX, OPEX)

---

## 2. 📋 Approval Routing Agent

### Single-Level Approval (≤$10K)
```
Route approval for 8k IT purchase
```
**Expected:** Manager only (Level 1), confidence 0.9+

```
Who needs to approve a 5k Finance expense?
```
**Expected:** Finance Manager only

### Two-Level Approval ($10K-$50K)
```
Route approval for 25k Operations CAPEX
```
**Expected:** Manager → Director (Level 1 + Level 2)

```
Show approval chain for 12k IT OPEX
```
**Expected:** IT Manager → IT Director

### Three-Level Approval (>$50K)
```
Route approval for 75k Finance expense
```
**Expected:** Manager → Director → VP/CFO (Level 1 + Level 2 + Level 3)

```
Who approves 120k IT CAPEX purchases?
```
**Expected:** 3-level chain with email addresses and thresholds

---

## 3. 🏆 Vendor Selection Agent

### Basic Vendor Recommendation
```
Recommend best vendor for Electronics purchase
```
**Expected:** Multi-criteria scoring (Quality 40%, Price 30%, Delivery 20%, Category 10%)

```
Find vendor for Office Supplies under 10k budget
```
**Expected:** Vendor recommendation with score breakdown and alternatives

### Vendor Comparison
```
Compare vendors for IT Hardware purchase
```
**Expected:** Top 3 vendors with scores, reasons, and recommendations

```
Which vendor is best for Furniture category?
```
**Expected:** Primary recommendation + alternative vendors

### Category-Specific
```
Select vendor for 50k Electronics purchase
```
**Expected:** Vendor with Electronics category match gets higher score

---

## 4. 🎯 Risk Assessment Agent

### Basic Risk Analysis
```
Assess risk for 40k Finance purchase
```
**Expected:** 4-dimensional risk (Vendor 30%, Financial 30%, Compliance 25%, Operational 15%)

```
What are the risks for 120k IT CAPEX expense?
```
**Expected:** Risk score (0-100), risk level (LOW/MEDIUM/HIGH/CRITICAL), risk factors

### Vendor-Specific Risk
```
Assess risk for purchase from XYZ Corporation worth 75k
```
**Expected:** Vendor risk analysis with reliability score

### Urgency-Based Risk
```
Evaluate risk for urgent 100k Operations purchase
```
**Expected:** Higher operational risk due to urgency, recommendations for mitigation

### High-Value Risk
```
What are risks for 500k equipment purchase?
```
**Expected:** CRITICAL financial risk, detailed mitigation strategies

### Category Risk
```
Assess compliance risk for Restricted category purchase
```
**Expected:** HIGH compliance risk, special approval requirements

---

## 5. 📄 Contract Monitoring Agent

### Contract Expiration Checks
```
Show contracts expiring in next 60 days
```
**Expected:** Table with contract numbers, days until expiry, end dates

```
Monitor contract CNT-001 expiration status
```
**Expected:** Days remaining, renewal recommendation, spend analysis

### Contract Renewal Alerts
```
Which contracts need renewal soon?
```
**Expected:** 90/60/30/7 day alert tiers, prioritized by urgency

```
Track contract CNT-002 worth 100k ending in 45 days
```
**Expected:** Renewal recommendation based on spend utilization and performance

### Contract Spend Analysis
```
Show spend analysis for contract CNT-003
```
**Expected:** Contract value vs spent amount, utilization percentage, remaining balance

---

## 6. 📊 Supplier Performance Agent

### Performance Evaluation
```
Evaluate supplier performance for ABC Corp
```
**Expected:** 4-dimensional breakdown (Delivery 40%, Quality 30%, Price 15%, Communication 15%)

```
How is XYZ Supplier performing?
```
**Expected:** Overall score (0-100), performance level (EXCELLENT/GOOD/AVERAGE/POOR/UNACCEPTABLE)

### Delivery Performance
```
Check delivery performance for supplier with 48 on-time out of 50 orders
```
**Expected:** Delivery score 96/100, EXCELLENT rating

### Quality Analysis
```
Analyze quality for supplier with 10 defects in 100 items
```
**Expected:** Quality score calculation, recommended action

### Comprehensive Evaluation
```
Evaluate supplier: 50 orders, 48 on-time, 10 defects, 4.5 communication rating
```
**Expected:** All 4 dimensions + overall score + recommended action + next steps

---

## 7. ✅ Compliance Check Agent

### Budget Compliance
```
Check compliance for 40k Finance OPEX with 1800 available budget
```
**Expected:** Compliance score 55/100, MAJOR_VIOLATION, budget insufficient violation

```
Verify compliance for 5k IT purchase with sufficient budget
```
**Expected:** Compliance score 85+/100, SUCCESS/MINOR_ISSUES

### Vendor Compliance
```
Check compliance for purchase from non-preferred vendor
```
**Expected:** Warning about vendor not on preferred list, score -10

### Documentation Compliance
```
Verify compliance for PR with insufficient justification
```
**Expected:** Warning about justification < 20 characters, score -10

---

## 8. 🔄 PR Creation Workflow (Complete)

### Successful PR Creation
```
Create a PR for 5k IT CAPEX for laptop replacement with justification "Replace broken laptops for development team"
```
**Expected:** 
- ✅ PR-2026-XXXXXXXX created
- Compliance checks passed (warnings OK)
- Auto-redirect to Approval Workflows page

### Budget Violation (Should Fail)
```
Create a PR for 40k Finance OPEX and route approval
```
**Expected:**
- ❌ FAILED status
- Violation: Insufficient budget
- Warnings: No vendor, insufficient justification
- Budget Status table showing shortfall

### Successful with Vendor
```
Create PR for 8k Operations OPEX from ABC Corp for office supplies with justification "Monthly office supply restocking for Q2 operations"
```
**Expected:**
- ✅ PR created
- Vendor compliance check (preferred vendor)
- Manager-only approval

### Multi-Step PR Creation
```
Create 15k IT CAPEX PR for network equipment, route to approvers, and verify budget
```
**Expected:** Multi-intent execution (CREATE + BUDGET + APPROVAL in sequence)

### PR with Full Details
```
Create a purchase request:
- Department: IT
- Amount: 25000
- Category: CAPEX
- Vendor: TechVendor Inc
- Justification: Upgrade server infrastructure to support 50% user growth projected in Q3-Q4 2026
```
**Expected:**
- ✅ PR created with all details
- 2-level approval (Manager + Director)
- Compliance score 95+/100

### Urgent PR Creation
```
Create urgent PR for 12k Finance OPEX needed by end of week
```
**Expected:**
- PR created with urgency flag
- Risk assessment shows operational risk
- 2-level approval required

### CAPEX vs OPEX Validation
```
Create 60k OPEX expense for equipment purchase
```
**Expected:**
- Warning: "Large OPEX expense - verify not a capital asset"
- Suggests CAPEX if equipment is long-term asset

### Restricted Category (Should Fail)
```
Create PR for Software Licenses category purchase
```
**Expected:**
- ❌ FAILED
- Violation: "Category 'Software Licenses' is restricted - requires special approval"

---

## 9. 🔀 Multi-Intent Queries

### Budget + Approval
```
Verify budget and route approval for 30k IT CAPEX
```
**Expected:** 
- Intent 1: Budget check (SUCCESS)
- Intent 2: Approval routing (2 levels)
- Summary with both results

### Create + Route + Risk
```
Create PR for 75k Operations purchase, route approval, and assess risks
```
**Expected:**
- Intent 1: PR creation workflow
- Intent 2: Approval routing (3 levels)
- Intent 3: Risk assessment (MEDIUM/HIGH)

### Vendor + Budget + Approval
```
Find best vendor, check budget, and route approval for 20k Electronics purchase
```
**Expected:**
- Intent 1: Vendor selection (top 3 recommendations)
- Intent 2: Budget verification
- Intent 3: Approval routing (2 levels)

### Compliance + Risk + Approval
```
Check compliance, assess risks, and route approval for 100k IT CAPEX
```
**Expected:**
- Intent 1: Compliance check
- Intent 2: Risk assessment (HIGH financial risk)
- Intent 3: Approval routing (3 levels)

### Budget + Vendor + Create
```
Verify 15k budget available, select best Office Supplies vendor, then create PR
```
**Expected:**
- Intent 1: Budget check (IT/Finance/Operations)
- Intent 2: Vendor recommendation
- Intent 3: PR creation with selected vendor

### Contract + Supplier + Renewal
```
Check contract CNT-001 status, evaluate supplier performance, recommend renewal
```
**Expected:**
- Intent 1: Contract monitoring (expiration, spend)
- Intent 2: Supplier performance (4 dimensions)
- Intent 3: Renewal recommendation based on performance

---

## 10. 🗄️ Odoo Integration Queries

### Purchase Orders
```
Show all draft purchase orders
```
**Expected:** Live Odoo data with PO numbers, states, amounts, vendors

```
List purchase orders above 50k
```
**Expected:** Filtered PO list from Odoo database

### Vendor Data
```
Show all vendors in the system
```
**Expected:** Vendor list from res.partner model

```
Find vendors for Electronics category
```
**Expected:** Filtered vendor list by category

### Product Catalog
```
Show available products
```
**Expected:** Product list from product.product model

---

## 11. 📈 General Procurement Analytics

### Department Analytics
```
Show procurement statistics by department
```
**Expected:** Budget usage, PR counts, approval rates by department

### Budget Utilization
```
What is the overall budget utilization across all departments?
```
**Expected:** Summary table with CAPEX/OPEX utilization percentages

### Approval Chain Overview
```
Explain the approval process for different purchase amounts
```
**Expected:** 
- ≤$10K: Manager only
- $10K-$50K: Manager + Director
- >$50K: Manager + Director + VP/CFO

### System Status
```
Show agent system status
```
**Expected:** List of registered agents, execution stats, health check

### Procurement Workflow Overview
```
Explain the complete procurement workflow from PR to PO
```
**Expected:**
1. PR Creation (vendor optional)
2. Approval Workflow (multi-level)
3. PO Creation (vendor required/auto-selected)

---

## 🎯 Testing Strategy

### Phase 1: Individual Agents (Test 1-7)
Run 1-2 queries from each agent section to verify:
- Correct agent is invoked
- Response includes expected data (scores, violations, recommendations)
- Execution time < 5 seconds
- No errors in console

### Phase 2: PR Workflow (Test 8)
Test full workflow scenarios:
- Success cases (sufficient budget)
- Failure cases (budget violations)
- Warning cases (missing vendor, justification)
- Edge cases (restricted categories, large OPEX)

### Phase 3: Multi-Intent (Test 9)
Verify orchestration:
- Multiple intents execute sequentially
- Dependencies handled (e.g., budget failure blocks approval)
- Summary shows all intent results
- No duplicate execution

### Phase 4: Odoo Integration (Test 10)
Validate live data access:
- Purchase orders fetched correctly
- Vendors list accurate
- Product catalog accessible
- No XML-RPC connection errors

### Phase 5: Analytics (Test 11)
Check system-wide features:
- Department summaries
- Budget reporting
- Agent health monitoring
- Workflow explanations

---

## 📊 Expected Results Checklist

For **each query**, verify:

1. ✅ **Agent Card** appears showing:
   - Correct agent name
   - Execution time (ms)
   - Confidence score (0.6-1.0)
   - Data source (Agentic/Odoo)

2. ✅ **Formatted Response** includes:
   - Markdown tables for structured data
   - Color-coded findings (❌ violations, ⚠️ warnings, ✅ successes)
   - Scores/metrics when applicable
   - Recommendations or next steps

3. ✅ **Pipeline Visualization** (click "Show Pipeline"):
   - Observe → Decide → Act → Learn phases
   - Phase details populated
   - No stuck/hanging phases

4. ✅ **No Errors**:
   - Browser console: No red errors
   - Backend logs: No exceptions
   - UI: No crash/freeze

---

## 🐛 Known Edge Cases to Test

### Budget Edge Cases
```
Check budget for 0 amount
Check budget for negative amount -1000
Check budget for non-existent department XYZ
```

### Approval Edge Cases
```
Route approval for 0 amount (should default to Level 1)
Route approval for 1 million amount (should still be 3-level)
Route approval without department specified
```

### Vendor Edge Cases
```
Find vendor for category with no matching vendors
Recommend vendor for 0 budget
Compare vendors when only 1 vendor exists
```

### Risk Edge Cases
```
Assess risk for 0 amount
Assess risk with no vendor and no amount
Assess risk for non-urgent vs urgent (compare scores)
```

### PR Creation Edge Cases
```
Create PR with no justification
Create PR with 1 character justification
Create PR for 0 amount
Create PR without department
Create PR without budget category
```

---

## 🚀 Quick Test Script (PowerShell)

```powershell
# Test Budget Agent
$body = @{ request = 'Check IT budget availability'; pr_data = @{} } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://localhost:5000/api/agentic/execute' -Method Post -ContentType 'application/json' -Body $body

# Test Approval Agent
$body = @{ request = 'Route approval for 25k IT CAPEX'; pr_data = @{ department='IT'; budget=25000; budget_category='CAPEX' } } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://localhost:5000/api/agentic/execute' -Method Post -ContentType 'application/json' -Body $body

# Test Vendor Agent
$body = @{ request = 'Recommend vendor for Electronics'; pr_data = @{ category='Electronics'; budget=10000 } } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://localhost:5000/api/agentic/execute' -Method Post -ContentType 'application/json' -Body $body

# Test Risk Agent
$body = @{ request = 'Assess risk for 75k purchase'; pr_data = @{ budget=75000; vendor_name='ABC Corp'; urgency='High' } } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://localhost:5000/api/agentic/execute' -Method Post -ContentType 'application/json' -Body $body

# Test PR Creation (Success)
$body = @{ request = 'Create PR for 5k IT CAPEX'; pr_data = @{ department='IT'; budget=5000; budget_category='CAPEX'; justification='Test PR creation workflow' } } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://localhost:5000/api/agentic/execute' -Method Post -ContentType 'application/json' -Body $body
```

---

## 📝 Test Results Template

| Query | Agent | Status | Response Time | Notes |
|-------|-------|--------|---------------|-------|
| Check IT budget | BudgetAgent | ✅ | 234ms | Shows all budget data |
| Route 25k approval | ApprovalAgent | ✅ | 189ms | 2-level chain correct |
| Recommend vendor | VendorAgent | ✅ | 312ms | Top 3 with scores |
| Assess 75k risk | RiskAgent | ✅ | 276ms | HIGH risk, 4 dimensions |
| Create 5k PR | PRWorkflow | ✅ | 891ms | PR created, redirected |
| Create 40k PR | PRWorkflow | ❌ | 823ms | Budget violation (expected) |

---

## ✅ Success Criteria

**System is working correctly if:**
- ✅ 90%+ of queries execute without errors
- ✅ Correct agent is invoked for each query type
- ✅ All nested data is displayed (violations, warnings, scores)
- ✅ PR creation workflow completes all 3 stages
- ✅ Multi-intent queries execute sequentially without duplicates
- ✅ Odoo queries return live data
- ✅ No crashes or UI freezes

**Total Test Coverage:** 60+ queries across 11 categories 🎯
