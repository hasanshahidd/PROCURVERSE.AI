# Available Workflows and Queries

Last verified against code: March 13, 2026
Source of truth checked:
- `backend/agents/orchestrator.py`
- `backend/routes/agentic.py`

## Current agent registration (11 agents)
The orchestrator currently registers these agent types:
- `budget_verification`
- `approval_routing`
- `vendor_selection`
- `risk_assessment`
- `contract_monitoring`
- `supplier_performance`
- `price_analysis`
- `compliance_check`
- `invoice_matching`
- `spend_analytics`
- `inventory_check`

## How routing works
Main entrypoints:
- `POST /api/agentic/execute`
- `POST /api/agentic/execute/stream`

The orchestrator either:
- routes to a single specialized agent, or
- runs a workflow branch (`pr_creation` or `po_creation`).

## Implemented workflows in code

### 1) Direct single-agent execution
When classifier maps to a specific domain (budget, vendor, risk, etc.), the orchestrator routes to one primary specialized agent.

Example queries:
- "Check IT budget for 50000"
- "Find best vendor for electronics"
- "Assess risk for this purchase"
- "Analyze spending by department"

### 2) PR creation workflow (`pr_creation`)
Implemented in `OrchestratorAgent._create_pr_workflow`.

Actual execution order:
1. Compliance check (`compliance_check`), if registered
2. Budget verification (`budget_verification`), if registered
3. Price analysis (`price_analysis`) only when `pr_data.quoted_price` is present
4. Create PR object
5. Approval routing (`approval_routing`) to create workflow/steps in DB

Important:
- This workflow does not currently auto-run `vendor_selection` or `risk_assessment`.
- Approval workflow records are created via `ApprovalRoutingAgent`.

Minimal payload example:
```json
{
  "request": "Create PR for IT laptop purchase",
  "pr_data": {
    "department": "IT",
    "budget": 50000,
    "budget_category": "CAPEX",
    "product_name": "Laptop",
    "quantity": 10,
    "quoted_price": 1500,
    "vendor_name": "Dell",
    "requester_name": "Chat User"
  }
}
```

### 3) PO creation workflow (`po_creation`)
Implemented in `OrchestratorAgent._create_po_workflow`.

Actual execution order:
1. Vendor selection (`vendor_selection`) only if vendor is missing
2. Risk assessment (`risk_assessment`)
3. Approval routing (`approval_routing`)
4. Create PO object
5. Attempt PO creation in Odoo via `create_purchase_order` tool

## Direct testing endpoints (implemented)
- `POST /api/agentic/budget/verify`
- `POST /api/agentic/approval/route`
- `POST /api/agentic/vendor/recommend`
- `POST /api/agentic/risk/assess`
- `POST /api/agentic/contract/monitor`
- `POST /api/agentic/supplier/evaluate`
- `POST /api/agentic/price/analyze`
- `POST /api/agentic/compliance/check`
- `POST /api/agentic/invoice/match`
- `POST /api/agentic/spend/analyze`
- `POST /api/agentic/inventory/check`

## Approval workflow endpoints (implemented)
- `GET /api/agentic/approval-workflows`
- `POST /api/agentic/approval-workflows/{pr_number}/approve`
- `POST /api/agentic/approval-workflows/{pr_number}/reject`
- `GET /api/agentic/my-approvals/{approver_email}`
- `GET /api/agentic/my-approvals/{approver_email}/stats`
- `GET /api/agentic/approval-chains`
- `GET /api/agentic/pending-approvals`
- `GET /api/agentic/pending-approvals/count`
- `GET /api/agentic/pending-approvals/history`
- `POST /api/agentic/pending-approvals/{approval_id}/approve`
- `POST /api/agentic/pending-approvals/{approval_id}/reject`

## Streaming notes (`/execute/stream`)
Event types emitted:
- `received`
- `classifying`
- `routing`
- `observing`
- `observation_complete`
- `deciding`
- `decision_made`
- `acting`
- `action_complete`
- `learning`
- `learning_complete`
- `complete`
- `error`

Notes:
- Step durations are not equal by design.
- LLM calls and Odoo/DB work can create longer gaps during `deciding`/action phases.

## Quick validation commands
```powershell
Invoke-RestMethod -Uri http://127.0.0.1:5000/api/agentic/status -Method Get
Invoke-RestMethod -Uri http://127.0.0.1:5000/api/agentic/agents -Method Get
```

```powershell
$body = @{
  request = 'Create PR for IT department: 10 laptops at $1500 each'
  pr_data = @{
    department = 'IT'
    budget = 50000
    budget_category = 'CAPEX'
    product_name = 'Laptop'
    quantity = 10
    quoted_price = 1500
    vendor_name = 'Dell'
  }
} | ConvertTo-Json -Depth 8
Invoke-RestMethod -Uri http://127.0.0.1:5000/api/agentic/execute -Method Post -ContentType 'application/json' -Body $body
```
