# Procure-to-Pay (P2P) Full Architecture

## 15-Step Pipeline — Agent, Input, Output, Conditions, Human Gates, Pages

| # | Step | Agent | Input | Output | Next Condition | Human Gate? | Page/Component |
|---|------|-------|-------|--------|----------------|-------------|----------------|
| 1 | **Compliance Check** | ComplianceCheckAgent | Request + PR data | Score, violations, warnings | Score > threshold | If violations found: policy override approval | AgentProcessPage |
| 2 | **Budget Verification** | BudgetVerificationAgent | Department, amount, category | Available budget, utilization% | Budget sufficient | If above threshold: continue confirmation | AgentProcessPage > BudgetPage |
| 3 | **Vendor Discovery** | VendorSelectionAgent | Category, budget, requirements | Ranked vendor list (top 5) | Vendors found | **YES**: Select vendor from shortlist | AgentProcessPage > HumanGatePanel |
| 4 | **Vendor Confirmation** | — (human) | Vendor shortlist | Selected vendor name | User selects | **YES**: Pick vendor | HumanGatePanel (inline) |
| 5 | **PR Creation** | Orchestrator (system) | Vendor + PR data | PR number (PR-2026-xxx) | PR created | — | AgentProcessPage |
| 6 | **Approval Routing** | ApprovalRoutingAgent | PR, amount, department | Approval chain, assigned approvers | Chain created | — | ApprovalWorkflowPage |
| 7 | **Manager Approval** | — (human) | PR details, approval chain | Approved/Rejected | Manager decides | **YES**: Approve or Reject | HumanGatePanel > MyApprovalsPage |
| 8 | **PO Creation** | Orchestrator (adapter) | Approved PR + vendor | PO number (PO-2026-xxx) | PO created in ERP | — | AgentProcessPage |
| 9 | **Delivery Tracking** | DeliveryTrackingAgent | PO number | ETA, delivery status | Delivery initiated | — | DeliveryTrackingPage |
| 10 | **Goods Receipt** | GoodsReceiptAgent | PO, delivery data | GRN number | — | **YES**: Confirm received | HumanGatePanel > GoodsReceiptPage |
| 11 | **Quality Inspection** | QualityInspectionAgent | GRN number | QC score, pass/fail | Score > threshold | If fail: accept/reject/return decision | AgentProcessPage > HumanGatePanel |
| 12 | **Invoice Matching** | InvoiceMatchingAgent | Invoice + PO | Match status | Matched | If mismatch: resolve exception | ReconciliationPage |
| 13 | **3-Way Match** | InvoiceMatchingAgent | PO + GRN + Invoice | Match validation | All 3 match | If discrepancy: human resolution | ReconciliationPage |
| 14 | **Payment Readiness** | PaymentReadinessAgent | All validations | Ready/Not ready flag | All checks pass | If not ready: review blockers | PaymentExecutionPage |
| 15 | **Payment Execution** | PaymentCalculationAgent | Net payable amount | Payment processed | Completed | **YES**: Final release approval | PaymentExecutionPage |

## Universal Human Gate System

Any of the 24 agents can trigger a human gate at any time by:

1. **Agent-driven**: Agent's `decide()` returns `AgentDecision(human_gate=HumanGateRequest(...))`
2. **Confidence-based**: Any decision with confidence < 40% auto-triggers review
3. **Exception-based**: Mismatches, violations, or anomalies trigger resolution gates

### Human Gate Types

| Gate Type | Trigger | Options Shown | Resume Action |
|-----------|---------|---------------|---------------|
| `vendor_selection` | Vendor shortlist ready | Vendor cards with scores | `confirm_vendor` |
| `approval` | PR/PO needs manager sign-off | Approve / Reject buttons | `approve` or `reject` |
| `goods_receipt` | Delivery arrived | Confirm Received / Report Issue | `confirm_grn` |
| `policy_override` | Compliance violation detected | Override / Block | `override` or `block` |
| `budget_threshold` | Amount exceeds limit | Continue / Escalate | `continue` or `escalate` |
| `exception_resolution` | Invoice mismatch found | Accept / Adjust / Reject | `resolve` |
| `payment_release` | Final payment approval | Release / Hold | `release` or `hold` |
| `quality_decision` | QC failed | Accept / Return / Partial | `accept` or `return` |
| `low_confidence_review` | Agent confidence < 40% | Approve / Reject agent decision | `approve` or `reject` |

## Page-to-Agent-to-Pipeline Mapping

### Chat Entry Point
- **Page**: `/chat` (ChatPage)
- **Purpose**: Natural language entry — user types request, orchestrator routes to right agent(s)
- **Agents**: ALL 24 (via orchestrator routing)

### Pipeline Visualization
- **Page**: `/process` (AgentProcessPage)
- **Purpose**: Real-time ODAL phase visualization + inline human gate panels
- **Agents**: Shows whatever agent(s) are currently executing
- **Human Gates**: HumanGatePanel renders inline when agent pauses

### Procurement Pages (P2P steps)
| Page | Route | P2P Steps | Connected Agents |
|------|-------|-----------|-----------------|
| RFQ & Quotes | `/rfq` | Pre-step (vendor discovery) | RFQAgent, QuoteComparisonAgent |
| Goods Receipt | `/goods-receipt` | Step 10 | GoodsReceiptAgent |
| Delivery Tracking | `/delivery-tracking` | Step 9 | DeliveryTrackingAgent |

### Approval Pages
| Page | Route | P2P Steps | Connected Agents |
|------|-------|-----------|-----------------|
| Pending Approvals | `/pending-approvals` | Step 7 + confidence gates | ApprovalRoutingAgent |
| Approval Workflows | `/approval-workflows` | Step 6 | ApprovalRoutingAgent |
| My Approvals | `/my-approvals` | Step 7 | ApprovalRoutingAgent |

### Finance Pages
| Page | Route | P2P Steps | Connected Agents |
|------|-------|-----------|-----------------|
| Budget Tracking | `/budget` | Step 2 | BudgetVerificationAgent |
| Payments | `/payment-execution` | Steps 14-15 | PaymentReadiness, PaymentCalculation |
| Aging Report | `/aging-report` | (Analytics) | AP aging data |
| Spend Analytics | `/spend-analytics` | (Analytics) | SpendAnalyticsAgent |
| Reconciliation | `/reconciliation` | Steps 12-13 | InvoiceMatchingAgent, ReconciliationAgent |

### Intelligence Pages (standalone agents)
| Page | Route | Connected Agents |
|------|-------|-----------------|
| Risk Assessment | `/risk-assessment` | RiskAssessmentAgent |
| Anomaly Detection | `/anomaly-detection` | AnomalyDetectionAgent |
| Supplier Performance | `/supplier-performance` | SupplierPerformanceAgent |
| Contracts | `/contracts` | ContractMonitoringAgent |
| Forecasting | `/forecasting` | ForecastingAgent |

## ERP Adapter Layer

All agents access data through `get_adapter()` — never directly to any ERP.

| Adapter | DATA_SOURCE | Tables |
|---------|-------------|--------|
| PostgreSQL | `postgresql` | Generic tables |
| Odoo | `odoo` / `demo_odoo` | `odoo_*` tables |
| SAP S/4HANA | `sap` / `demo_sap_s4` | `sap_*` tables |
| SAP Business One | `sap_b1` / `demo_sap_b1` | `sap_b1_*` tables |
| Oracle Fusion | `oracle` / `demo_oracle` | `oracle_*` tables |
| Dynamics 365 | `dynamics` / `demo_dynamics` | `d365_*` tables |
| ERPNext | `erpnext` / `demo_erpnext` | `erpnext_*` tables |

Switch ERP: Change `DATA_SOURCE` in `.env` → restart backend → all agents auto-adapt.
