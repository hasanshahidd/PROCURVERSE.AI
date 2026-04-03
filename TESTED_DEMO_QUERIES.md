# Tested Demo Queries (Verified Live)

Last verified: 2026-03-17
Verification target: `http://127.0.0.1:5000/api/agentic/execute`

These queries were executed and passed in the current running backend.

## 1. Separate Queries (Run in Order)

### A) Budget
Query:
Check IT budget for $2 OPEX

Expected:
- Agentic budget result returns approved status
- May include critical utilization warning

### B) Vendor
Query:
Find best vendor for office chairs for IT with budget $2

Expected:
- Vendor recommendation status is recommended
- Primary vendor is returned (example: Ready Mat)

### C) Risk
Query:
Assess risk for ordering from Office Depot LLC, $25k, IT OPEX, requester: John Smith, justification: Office equipment renewal for operational continuity

Expected:
- Risk result returns low_risk_proceed
- Risk level and score are present

### D) Create PR (Step 1)
Query:
Create PR for IT department, budget $2, buy 7 office chairs, OPEX, justification: Office chairs replacement for operations continuity

Expected:
- PR workflow status = awaiting_vendor_confirmation
- workflow_type = pr_creation

### E) Create PR (Step 2: Confirm Vendor)
Query:
CONFIRM_VENDOR: Ready Mat. Continue PR creation workflow with department IT, budget $2, category Office Supplies, product Office Chairs, quantity 7, budget category OPEX, business justification: Office chairs replacement for operations continuity.

Expected:
- PR workflow status = success
- workflow_type = pr_creation

## 2. Combined Query (Budget + Risk)

Query:
Check IT budget with amount 2 USD and budget category OPEX. Then assess risk for ordering from Office Depot LLC with amount 25000 USD, requester John Smith, justification Office equipment renewal for operational continuity.

Expected:
- MultiIntentOrchestrator returns intent_count = 2
- First intent: BUDGET approved
- Second intent: RISK low_risk_proceed

## Notes

- Use explicit "amount ... USD" format for combined prompts to avoid ambiguity.
- PR creation intentionally pauses at vendor confirmation in step 1.
- Risk visibility is now embedded in PR success output as a Risk Snapshot, and you can still run standalone risk for full details.

## 3. Additional Verified Queries (Same 4 Workflows)

### A) Budget (Tested Rejection Case)
Query:
Check IT budget for amount 10 USD and budget category OPEX

Observed result:
- Budget status returned `rejected`
- This is a valid and expected behavior when current utilization and policy thresholds do not allow additional spend

### B) Vendor (Additional Pass Cases)
Query:
Recommend vendor for office supplies for IT with amount 10 USD

Observed result:
- Vendor status returned `recommended`

Query:
Find best vendor for electronics for IT with budget 1000 USD

Observed result:
- Vendor status returned `recommended`

### C) Risk (Additional Pass Case)
Query:
Assess risk for $50k IT OPEX purchase, requester: Ali Khan, justification: replacement of aging network equipment for security and uptime

Observed result:
- Risk status returned `low_risk_proceed`
- Risk level was present and response completed successfully

### D) Create PR
Use the already-verified Step 1 and Step 2 create queries above.

Observed result:
- Create PR workflow remains covered by the verified `awaiting_vendor_confirmation` and final `success` sequence already listed in this document
