# Procure-AI — Complete P2P Intelligence Guide

How the AI makes decisions, where data comes from, how OCR works, what triggers what, and how the user is guided through the entire procure-to-pay lifecycle.

---

## HOW THE USER KNOWS WHAT TO DO

The user NEVER needs to memorize steps. The system guides them:

```
AFTER EVERY AI ACTION, THE CHAT RETURNS:
  1. What just happened (result)
  2. What to do next (suggested queries)
  3. Who was notified (emails/slack)

Example:
  User: "I need 100 laptops for IT"

  AI responds:
    "PR-2026-001 created for 100 Laptops ($120,000).
     Vendor: Dell Technologies (score 89%).
     Routed for approval: Manager → Director → VP.

     Suggested next:
       • 'Check approval status for PR-2026-001'
       • 'Create RFQ for laptops and invite Dell, HP, Lenovo'
       • 'Show budget status for IT'"

After approval completes:
  System auto-creates PO, then EMAILS the user:
    "Your PR-2026-001 was approved. PO-2026-045 created.
     Vendor: Dell Technologies
     Expected delivery: May 15, 2026

     Suggested next:
       • 'Track delivery for PO-2026-045'
       • 'Set up quality inspection'"

After goods arrive:
  User enters GRN on /goods-receipt page, then AI suggests:
    "GRN-2026-012 recorded. 100 laptops received.

     Suggested next:
       • 'Run quality inspection on GRN-2026-012'
       • 'Check if invoice arrived for PO-2026-045'"

The user is NEVER left wondering "what now?" — every response includes next steps.
```

---

## STEP-BY-STEP: THE INTELLIGENCE BEHIND EACH DECISION

### STEP 1: UNDERSTANDING WHAT THE USER WANTS

```
USER TYPES: "I need 100 laptops for IT department at $1200 each"

HOW THE AI UNDERSTANDS THIS:

  1. Query sent to: classify_query_intent() in query_router.py

  2. OpenAI GPT-4o-mini receives this prompt:
     "Classify this procurement query. Extract:
      - intent (CREATE, BUDGET, VENDOR, RISK, etc.)
      - department
      - quantity
      - product name
      - budget amount
      Return JSON."

  3. LLM returns:
     {
       "intents": [{
         "data_source": "agentic",
         "query_type": "CREATE",
         "filters": {
           "department": "IT",
           "quantity": 100,
           "product_name": "laptops",
           "budget": 120000,
           "budget_category": "CAPEX"
         }
       }],
       "confidence": 0.95
     }

  4. Fast-path routing:
     query_type "CREATE" → _DIRECT_ROUTE_MAP → "pr_creation"
     Skips second LLM call (saves time + cost)
     Confidence: 0.95

  INTELLIGENCE: NLP intent extraction + fast-path routing
  COST: ~$0.001 (one GPT-4o-mini call)
  TIME: ~0.5 seconds
```

### STEP 2: COMPLIANCE CHECK — IS THIS PURCHASE ALLOWED?

```
ComplianceCheckAgent receives the request.

HOW IT DECIDES:

  CHECK 1: Spending Limits
    Table: hardcoded per department
    IT limit: $500,000/year
    Requested: $120,000
    Result: WITHIN LIMIT ✓

  CHECK 2: Category Restrictions
    "laptops" → category: "IT Equipment"
    Restricted categories: ["Weapons", "Gambling", "Tobacco"]
    Result: NOT RESTRICTED ✓

  CHECK 3: Vendor Blacklist
    Queries: SanctionsService (local blocklist)
    Dell Technologies: NOT on blocklist ✓

  CHECK 4: Budget Category Validation
    $120,000 for equipment → should be CAPEX (not OPEX)
    User specified: CAPEX
    Result: CORRECT ✓

  CHECK 5: Documentation
    Request has: department ✓, quantity ✓, price ✓, justification (implicit)
    Result: SUFFICIENT ✓

  CHECK 6: Duplicate Detection
    Queries: procurement_records table
    No existing PR for "100 laptops for IT" in last 30 days
    Result: NOT DUPLICATE ✓

  CHECK 7: Budget Category Rules
    IT + CAPEX + $120K: allowed
    Result: PASS ✓

  FINAL DECISION:
    action = "accept" (all 7 checks passed)
    confidence = 0.92

  IF ANY CHECK FAILS:
    action = "reject" → workflow STOPS
    action = "require_correction" → workflow continues with warnings
    User told: "Compliance issue: [specific reason]. Please correct and resubmit."

  INTELLIGENCE: Rule-based (no LLM needed — fast, deterministic, auditable)
  DATA FROM: hardcoded limits + sanctions_service + procurement_records table
  WRITES TO: agent_actions (audit log)
```

### STEP 3: BUDGET CHECK — CAN WE AFFORD THIS?

```
BudgetVerificationAgent receives the request.

HOW IT DECIDES:

  1. Queries: budget_tracking table via adapter
     SELECT * FROM budget_tracking
     WHERE department = 'IT' AND budget_category = 'CAPEX'

  2. Data returned:
     {
       "department": "IT",
       "budget_category": "CAPEX",
       "fiscal_year": 2026,
       "allocated_budget": 500000.00,
       "spent_budget": 280000.00,
       "committed_budget": 45000.00,
       "available_budget": 175000.00   ← (500K - 280K - 45K)
     }

  3. Decision logic:
     requested = $120,000
     available = $175,000

     IF requested > available:
       action = "reject_insufficient_budget"
       message = "Budget insufficient. Available: $175K, Requested: $120K"

     IF requested <= available:
       utilization_after = (280K + 45K + 120K) / 500K = 89%

       IF utilization > 95%: alert = "CRITICAL - approaching budget limit"
       IF utilization > 90%: alert = "WARNING - high utilization"
       IF utilization > 80%: alert = "CAUTION - monitor spending"

       action = "approve"

  4. Budget commitment (if approved):
     UPDATE budget_tracking
     SET committed_budget = committed_budget + 120000
     WHERE department = 'IT' AND budget_category = 'CAPEX'

     Uses ROW-LEVEL LOCK (SELECT ... FOR UPDATE) to prevent
     two people spending the same budget simultaneously.

  INTELLIGENCE: Real-time budget query + threshold alerts + atomic commitment
  DATA FROM: budget_tracking table (PostgreSQL)
  WRITES TO: budget_tracking (commits amount) + agent_actions (audit)
```

### STEP 4: VENDOR SELECTION — WHO SHOULD WE BUY FROM?

```
VendorSelectionAgent receives: "Find best vendor for 100 laptops"

HOW IT DECIDES:

  1. Queries vendor data via adapter:
     adapter.get_vendors(limit=200)
     → Returns from odoo_partners table (demo mode)
     → Returns from res.partner via XML-RPC (live Odoo mode)
     → Returns from sap_vendor_general (if SAP mode)

  2. For each vendor, calculates WEIGHTED SCORE:

     ┌─────────────────────────────────────────────────────────┐
     │ DIMENSION        │ WEIGHT │ HOW CALCULATED              │
     ├──────────────────┼────────┼─────────────────────────────┤
     │ Quality          │  40%   │ supplier_rating field        │
     │                  │        │ (1-5 scale → normalized)     │
     │──────────────────┼────────┼─────────────────────────────│
     │ Price            │  30%   │ Historical PO prices for     │
     │                  │        │ similar items. Lower = better│
     │──────────────────┼────────┼─────────────────────────────│
     │ Delivery         │  20%   │ on_time_delivery_rate from   │
     │                  │        │ vendor_performance table.    │
     │                  │        │ 95%+ = excellent             │
     │──────────────────┼────────┼─────────────────────────────│
     │ Category Match   │  10%   │ Does vendor supply this      │
     │                  │        │ category? (IT Equipment)     │
     └─────────────────────────────────────────────────────────┘

  3. Example scoring:

     Dell Technologies:
       Quality:  4.5/5 × 40 = 36.0
       Price:    competitive × 30 = 25.5
       Delivery: 96% on-time × 20 = 19.2
       Category: IT vendor ✓ × 10 = 10.0
       TOTAL: 90.7

     HP Enterprise:
       Quality:  4.2/5 × 40 = 33.6
       Price:    slightly higher × 30 = 24.0
       Delivery: 92% on-time × 20 = 18.4
       Category: IT vendor ✓ × 10 = 10.0
       TOTAL: 86.0

  4. Returns TOP 5 ranked vendors to user

  INTELLIGENCE: Multi-dimensional weighted scoring with real vendor data
  DATA FROM: odoo_partners + vendor_performance tables via adapter
  NOT JUST NAMES — actual scores with reasoning
```

### STEP 5: RFQ — GETTING COMPETITIVE QUOTES

```
User types: "Create RFQ for laptops and invite Dell, HP, Lenovo"

HOW RFQAgent WORKS:

  1. Creates RFQ record:
     INSERT INTO rfq_headers (rfq_number, title, department, status)
     VALUES ('RFQ-2026-001', '100 Dell Laptops for IT', 'IT', 'sent')

  2. Adds line items:
     INSERT INTO rfq_lines (rfq_id, item_name, quantity, estimated_price)
     VALUES (1, 'Business Laptop', 100, 1200)

  3. When vendors respond (submit quotes):
     INSERT INTO vendor_quotes (rfq_id, vendor_name, unit_price, lead_time_days)
     VALUES (1, 'Dell', 1150, 14)
     VALUES (1, 'HP', 1100, 21)
     VALUES (1, 'Lenovo', 1050, 30)

  4. User types: "Compare quotes for RFQ-2026-001"

     QuoteComparisonAgent SCORES each quote:

     ┌──────────┬───────────┬──────────┬───────────┬───────┐
     │ Vendor   │ Price     │ Lead Time│ Score     │ Rank  │
     ├──────────┼───────────┼──────────┼───────────┼───────┤
     │ Dell     │ $1,150    │ 14 days  │ 96.5      │ #1 ★  │
     │ HP       │ $1,100    │ 21 days  │ 88.2      │ #2    │
     │ Lenovo   │ $1,050    │ 30 days  │ 84.0      │ #3    │
     └──────────┴───────────┴──────────┴───────────┴───────┘

     Scoring:
       Price score = (cheapest_price / vendor_price) × 40
       Lead score = (shortest_lead / vendor_lead) × 30
       Vendor score = 30 (base, enhanced with performance data)

     Dell wins: fastest delivery compensates for slightly higher price.

  5. User types: "Award RFQ to Dell"
     → RFQ status = awarded
     → PO auto-created from winning quote

  INTELLIGENCE: Weighted multi-criteria comparison (not just cheapest price)
  DATA FROM: vendor_quotes table + vendor_performance for track record
```

### STEP 6: HOW APPROVALS WORK

```
APPROVAL RULES (from approval_rules table):

  ┌──────────────┬──────────┬──────────┬─────────────────────┐
  │ Document Type│ Min $    │ Max $    │ Approver            │
  ├──────────────┼──────────┼──────────┼─────────────────────┤
  │ PR           │ $0       │ $10,000  │ Department Manager  │
  │ PR           │ $10,000  │ $50,000  │ + Director          │
  │ PR           │ $50,000  │ $250,000 │ + VP/CFO            │
  │ PR           │ $250,000 │ $999M    │ + Board             │
  ├──────────────┼──────────┼──────────┼─────────────────────┤
  │ INVOICE      │ $0       │ $25,000  │ AP Specialist       │
  │ INVOICE      │ $25,000  │ $100,000 │ AP Manager          │
  │ INVOICE      │ $100,000 │ $999M    │ Finance Director    │
  ├──────────────┼──────────┼──────────┼─────────────────────┤
  │ PAYMENT      │ $0       │ $50,000  │ Finance Manager     │
  │ PAYMENT      │ $50,000  │ $250,000 │ Finance Director    │
  │ PAYMENT      │ $250,000 │ $999M    │ CFO/Treasury        │
  └──────────────┴──────────┴──────────┴─────────────────────┘

  For $120,000 PR:
    Level 1: Manager (amount > $0) — must approve
    Level 2: Director (amount > $10K) — must approve
    Level 3: VP/CFO (amount > $50K) — must approve

  Each approver:
    1. Gets EMAIL: "PR-2026-001 requires your approval"
    2. Opens /pending-approvals page
    3. Sees AI RECOMMENDATION: "APPROVE (confidence 89%)"
    4. Sees REASONING: "Budget sufficient, vendor qualified, compliance passed"
    5. Clicks [APPROVE] or [REJECT]

  After each approval:
    → Next approver notified via EMAIL
    → Workflow advances: current_approval_level += 1

  After ALL approved:
    → Event: approval_completed
    → Auto-triggers: PO creation via adapter
    → EMAIL: "Your PR approved. PO created." → requester

  INTELLIGENCE: Dynamic threshold-based routing (configurable in DB, not hardcoded)
  SLA: Each level has sla_hours (24h) and escalate_after (48h)
```

### STEP 7: HOW PO IS CREATED AFTER APPROVAL

```
TRIGGER: When last approval step completes

  Code path:
    approve_workflow_step() in agentic.py
      → checks: remaining_steps == 0
      → calls: adapter.create_purchase_order_from_pr()

  adapter.create_purchase_order_from_pr():
    1. Reads PR data from pr_approval_workflows.request_data
    2. Resolves correct ERP table:
       demo_odoo → INSERT INTO odoo_purchase_orders
       demo_sap → INSERT INTO sap_purchase_orders
       (etc. for all 5 ERPs)
    3. Generates PO number (PO-2026-XXXXXXXXXX)
    4. Inserts: vendor, items, quantity, price, delivery date, status
    5. Links back: pr_approval_workflows.odoo_po_id = PO number
    6. Logs: notification_log (PO created email)

  USER IS NOTIFIED:
    ┌────────────────────────────────────────────────────────┐
    │  EMAIL TO: requester@company.com                       │
    │  SUBJECT: PR-2026-001 Approved — PO Created            │
    │                                                        │
    │  Your purchase requisition has been approved.           │
    │  Purchase Order: PO-2026-045                           │
    │  Vendor: Dell Technologies                             │
    │  Items: 100 × Laptop @ $1,200                          │
    │  Total: $120,000                                       │
    │  Expected Delivery: May 15, 2026                       │
    │                                                        │
    │  Next steps:                                           │
    │  • Vendor has been notified                            │
    │  • Track delivery in the system                       │
    │  • Quality inspection will run on arrival              │
    └────────────────────────────────────────────────────────┘

    ┌────────────────────────────────────────────────────────┐
    │  EMAIL TO: vendor@dell.com                             │
    │  SUBJECT: New Purchase Order PO-2026-045               │
    │                                                        │
    │  Please confirm and deliver:                           │
    │  100 × Business Laptop                                 │
    │  Delivery by: May 15, 2026                             │
    │  Payment terms: Net 30                                 │
    └────────────────────────────────────────────────────────┘

  INTELLIGENCE: Auto-triggered by event, no human action needed after approval
  DATA FROM: pr_approval_workflows.request_data (JSONB)
  WRITES TO: ERP PO table + notification_log
```

### STEP 8: HOW OCR READS INVOICES

```
WHEN: Vendor emails an invoice PDF

HOW THE SYSTEM CAPTURES IT:

  1. EmailInboxAgent (runs every 15 minutes):
     Connects to IMAP inbox
     Scans for new emails with PDF attachments
     Detects "invoice" in subject/body
     Passes PDF to InvoiceCaptureAgent

  2. InvoiceCaptureAgent uses OCR Service:

     OCR PROVIDERS (pluggable):
     ┌──────────────┬───────────────────────────────────────┐
     │ Provider     │ How It Works                          │
     ├──────────────┼───────────────────────────────────────┤
     │ Regex        │ Pattern matching on text:             │
     │ (default)    │ "Invoice #: INV-(\d+)"                │
     │              │ "Total: \$([0-9,.]+)"                 │
     │              │ "PO Reference: (PO-\w+)"              │
     │              │ "Due Date: (\d{4}-\d{2}-\d{2})"      │
     │              │ Free, no API key needed               │
     │              │ Confidence: 50-85%                    │
     ├──────────────┼───────────────────────────────────────┤
     │ Mindee       │ AI-powered document extraction:       │
     │ ($10/month)  │ Sends PDF to Mindee API               │
     │              │ Returns structured fields              │
     │              │ Confidence: 85-97%                    │
     ├──────────────┼───────────────────────────────────────┤
     │ AWS Textract │ Amazon's document AI:                 │
     │ ($0.015/page)│ Sends PDF to AWS                      │
     │              │ Returns key-value pairs               │
     │              │ Confidence: 90-99%                    │
     └──────────────┴───────────────────────────────────────┘

  3. Fields extracted:
     {
       "invoice_number": "INV-DELL-2026-0892",
       "po_reference": "PO-2026-045",
       "vendor": "Dell Technologies",
       "invoice_date": "2026-05-20",
       "due_date": "2026-06-19",
       "total_amount": 120000.00,
       "tax_amount": 6000.00,
       "currency": "USD",
       "payment_terms": "Net 30",
       "confidence": 0.94
     }

  4. Validation:
     - Duplicate check: SELECT FROM vendor_invoices WHERE invoice_number = 'INV-DELL-2026-0892'
       → Not found = OK
     - PO link: SELECT FROM odoo_purchase_orders WHERE name = 'PO-2026-045'
       → Found = LINKED ✓
     - If duplicate: places HOLD on invoice, notifies AP team

  5. Writes to:
     - ocr_ingestion_log (raw extraction result + confidence)
     - notification_log (invoice received notification → AP team)

  INTELLIGENCE: Multi-provider OCR with confidence scoring + auto-validation
  CONFIGURABLE: Set OCR_PROVIDER=mindee + MINDEE_API_KEY in .env for production
```

### STEP 9: THREE-WAY MATCHING — THE CORE FINANCIAL CONTROL

```
InvoiceMatchingAgent compares THREE documents:

  ┌─────────────────────┬─────────────────────┬─────────────────────┐
  │ PURCHASE ORDER      │ GOODS RECEIPT NOTE  │ VENDOR INVOICE      │
  │ (what we ordered)   │ (what we received)  │ (what vendor claims)│
  ├─────────────────────┼─────────────────────┼─────────────────────┤
  │ PO-2026-045         │ GRN-2026-012        │ INV-DELL-0892       │
  │ 100 laptops         │ 100 laptops         │ 100 laptops         │
  │ $1,200 each         │ (no price)          │ $1,200 each         │
  │ Total: $120,000     │ Qty: 100 received   │ Total: $126,000     │
  │                     │                     │ (incl. $6K tax)     │
  └─────────────────────┴─────────────────────┴─────────────────────┘

HOW THE MATCHING WORKS:

  1. Quantity match:
     PO qty (100) vs GRN qty (100) vs Invoice qty (100)
     Variance: 0% → EXACT MATCH ✓

  2. Amount match:
     PO amount ($120,000) vs Invoice amount ($120,000 + $6,000 tax)
     Pre-tax amount matches → PASS ✓
     Tax validated by TaxService (5% UAE VAT on $120K = $6K) → CORRECT ✓

  3. Decision by variance:

     ┌──────────────┬──────────────────────────────────────────┐
     │ Variance     │ Action                                   │
     ├──────────────┼──────────────────────────────────────────┤
     │ ≤ 5%         │ AUTO-APPROVE (no human needed)           │
     │ 5% - 10%     │ FLAG for AP specialist review            │
     │ 10% - 20%    │ FLAG + EMAIL AP manager                  │
     │ > 20%        │ BLOCK + investigate + notify procurement │
     └──────────────┴──────────────────────────────────────────┘

  4. Auto-resolution (DiscrepancyResolutionAgent):
     - Blanket PO + partial delivery → auto-approve partial qty
     - Price ≤ 5% higher than PO → auto-approve with note
     - Standard PO within 2% tolerance → auto-approve
     - Missing GRN → NEVER auto-approve (always human review)

  IF MISMATCH:
    → discrepancy_log record created
    → invoice_hold placed
    → EMAIL to AP specialist: "Invoice INV-DELL-0892 has 15% price variance"
    → AP specialist reviews on /pending-approvals
    → Approves or rejects

  INTELLIGENCE: Automated matching with configurable tolerances + auto-resolution
  DATA FROM: PO table + GRN table + Invoice table via adapter
  WRITES TO: discrepancy_log + invoice_holds + notification_log
```

### STEP 10: PAYMENT CALCULATION — THE MATH

```
PaymentCalculationAgent calculates EXACTLY how much to pay:

  INPUT:
    Invoice: $120,000 USD
    Tax: $6,000 (verified)

  CALCULATION:

    1. PAYMENT TYPE:
       GRN qty (100) vs Invoice qty (100) → FULL payment
       (if GRN < Invoice → PARTIAL payment, pay only received portion)

    2. EARLY PAYMENT DISCOUNT:
       Contract says: "2/10 Net 30" (2% discount if paid within 10 days)
       Invoice date: May 20
       Today: May 25
       Days since invoice: 5 days (within 10-day window)
       Discount: $120,000 × 2% = $2,400

    3. TAX CALCULATION (TaxService):
       Country: UAE
       Rate: 5% VAT
       Tax: $120,000 × 5% = $6,000
       Validated against invoice tax amount → MATCH ✓

       ┌───────────────┬──────────┐
       │ Country       │ Tax Rate │
       ├───────────────┼──────────┤
       │ UAE           │ 5% VAT   │
       │ Saudi Arabia  │ 15% VAT  │
       │ EU countries  │ 20-27%   │
       │ US states     │ 0-10.25% │
       │ India         │ 18% GST  │
       │ Singapore     │ 9% GST   │
       └───────────────┴──────────┘

    4. FX CONVERSION (FXService):
       Invoice currency: USD
       Company currency: AED
       Rate: 1 USD = 3.6725 AED (from exchange_rates table)

       18 currencies supported:
       AED, USD, EUR, GBP, SAR, QAR, PKR, INR, JPY, CNY,
       CHF, CAD, AUD, SGD, HKD, KWD, BHD, OMR

    5. FINAL CALCULATION:
       Invoice amount:    $120,000.00
       Tax:              +  $6,000.00
       Early discount:   -  $2,400.00
       Net payable:       $123,600.00 USD
       In AED:            AED 453,924.30

  INTELLIGENCE: Multi-factor calculation (type + discount + tax + FX)
  DATA FROM: exchange_rates + contracts (discount terms) + TaxService rules
  WRITES TO: payment_runs (calculated amounts)
```

### NOTIFICATION SYSTEM — EVERY EMAIL/ALERT

```
NOTIFICATIONS ARE CREATED AT EVERY STEP:

  ┌─────────────────┬──────────────────────────────────────┬──────────────┐
  │ WHEN             │ EMAIL SENT                           │ TO WHOM      │
  ├─────────────────┼──────────────────────────────────────┼──────────────┤
  │ PR created       │ "PR requires approval"               │ Approver     │
  │ PR approved      │ "PR approved, next level"            │ Next approver│
  │ All approved     │ "PR fully approved, PO created"      │ Requester    │
  │ PO created       │ "New Purchase Order"                 │ Vendor       │
  │ RFQ created      │ "New RFQ — submit quote"            │ Vendors      │
  │ RFQ awarded      │ "You won the RFQ"                   │ Winner       │
  │ GRN recorded     │ "Goods received"                    │ Requester    │
  │ QC failed        │ "Quality inspection FAILED"          │ Procurement  │
  │ RTV created      │ "Return initiated"                  │ Vendor       │
  │ Invoice received │ "Invoice captured"                  │ AP team      │
  │ Match failed     │ "Invoice variance >5%"              │ AP specialist│
  │ Payment pending  │ "Payment requires approval"          │ Finance Dir  │
  │ Payment sent     │ "Payment confirmation"               │ Vendor       │
  │ Amendment        │ "PO modified — re-approval needed"  │ Approver     │
  │ Budget alert     │ "Budget 90% utilized"               │ Budget owner │
  │ Contract expiry  │ "Contract expires in 30 days"        │ Procurement  │
  │ Anomaly found    │ "Duplicate invoice detected"         │ Compliance   │
  └─────────────────┴──────────────────────────────────────┴──────────────┘

HOW EMAILS WORK:

  1. Agent creates record in notification_log:
     INSERT INTO notification_log
       (event_type, document_id, recipient_role, subject, body_preview, status)
     VALUES ('pr_approved', 'PR-2026-001', 'procurement', 'PR Approved', '...', 'pending')

  2. NotificationDispatcher polls every 30 seconds:
     SELECT * FROM notification_log WHERE status = 'pending'

  3. Sends via configured provider:
     EMAIL_PROVIDER=mock     → logs to console (development)
     EMAIL_PROVIDER=sendgrid → sends via SendGrid API
     EMAIL_PROVIDER=smtp     → sends via SMTP server

  4. Updates status:
     UPDATE notification_log SET status = 'sent' WHERE id = X

  19 email templates in email_templates table — one per event type.

  CURRENT STATE: EMAIL_PROVIDER=mock (not sending)
  TO ENABLE: Set SENDGRID_API_KEY=your-key in .env
```

### BACKGROUND AGENTS — ALWAYS RUNNING

```
4 AGENTS RUN CONTINUOUSLY (via scheduler_service.py):

  ┌───────────────────────┬───────────┬────────────────────────────────────┐
  │ AGENT                 │ FREQUENCY │ WHAT IT DOES                       │
  ├───────────────────────┼───────────┼────────────────────────────────────┤
  │ EmailInboxAgent       │ Every     │ Scans IMAP inbox for new invoices  │
  │                       │ 15 min    │ Passes PDFs to InvoiceCaptureAgent │
  │                       │           │ Auto-processes found invoices      │
  ├───────────────────────┼───────────┼────────────────────────────────────┤
  │ AnomalyDetectionAgent │ Every     │ Runs 8 detection rules:           │
  │                       │ 6 hours   │ • Duplicate invoices              │
  │                       │           │ • Spend spikes (>150% of avg)     │
  │                       │           │ • Off-hours POs                   │
  │                       │           │ • Unusual vendor (new + high $)   │
  │                       │           │ • Split POs (avoid approval)      │
  │                       │           │ • Price variance (>20%)           │
  │                       │           │ • Duplicate vendors (name match)  │
  │                       │           │ • Contract bypass (expired vendor)│
  ├───────────────────────┼───────────┼────────────────────────────────────┤
  │ InventoryCheckAgent   │ Every     │ Checks stock levels               │
  │                       │ 4 hours   │ Flags items below reorder point   │
  │                       │           │ Can auto-create PR for restocking │
  ├───────────────────────┼───────────┼────────────────────────────────────┤
  │ ContractMonitoring    │ Daily     │ Checks contract expiry dates:     │
  │ Agent                 │ at 8 AM   │ • 90 days: planning alert         │
  │                       │           │ • 60 days: renewal reminder       │
  │                       │           │ • 30 days: urgent alert           │
  │                       │           │ • 7 days: critical warning        │
  └───────────────────────┴───────────┴────────────────────────────────────┘

  These agents use OpenAI tokens ONLY when they find something.
  Normal scan = just DB queries (no AI cost).
  Finding = AI reasoning + notification (small cost).
```

### AUDIT TRAIL — EVERY ACTION RECORDED

```
TABLES THAT TRACK EVERYTHING:

  agent_actions (5,600+ rows):
    Every agent execution: who ran, what input, what output, success/fail, timing
    Full replay possible: SELECT * FROM agent_actions ORDER BY created_at

  workflow_runs:
    Every P2P workflow from start to finish
    Status: pending → running → waiting_human → completed/failed

  workflow_tasks:
    Every task within a workflow with dependencies

  workflow_events:
    Every event: compliance_passed, budget_verified, vendor_selected, etc.

  notification_log:
    Every email/notification: who, when, what, delivered/failed

  pr_approval_workflows + pr_approval_steps:
    Complete approval chain: who approved, when, with what notes

  procurement_records:
    Every PR ever created

  COMPLIANCE: Full audit trail from request to payment.
  Every decision has: who made it, what data was used, what alternatives were considered.
```

---

## TOTAL AGENTS IN THE SYSTEM: 25

```
CORE P2P AGENTS (on-demand, triggered by chat):
  1. OrchestratorAgent          — Routes queries to correct agent
  2. ComplianceCheckAgent       — Policy validation (7 rules)
  3. BudgetVerificationAgent    — Budget checking + commitment
  4. VendorSelectionAgent       — Vendor scoring (4 dimensions)
  5. ApprovalRoutingAgent       — Multi-level approval chains
  6. RiskAssessmentAgent        — 4-dimension risk scoring
  7. PriceAnalysisAgent         — Price benchmarking
  8. ComplianceCheckAgent       — Policy compliance
  9. InvoiceMatchingAgent       — 3-way matching
  10. DiscrepancyResolutionAgent — Auto-resolve invoice variances
  11. SpendAnalyticsAgent        — Spend analysis + savings
  12. SupplierPerformanceAgent   — Vendor scorecards
  13. ContractMonitoringAgent    — Expiry tracking
  14. InventoryCheckAgent        — Stock level monitoring

PIPELINE AGENTS (9-step invoice-to-payment):
  15. POIntakeAgent              — PO document OCR
  16. PORegistrationAgent        — PO validation vs master data
  17. InvoiceCaptureAgent        — Invoice OCR extraction
  18. InvoiceRoutingAgent        — Route to AP queue
  19. PaymentReadinessAgent      — 7-gate pre-payment check
  20. PaymentCalculationAgent    — Tax + FX + discount math
  21. PaymentApprovalAgent       — Payment-level approval

NEW AGENTIC MODULES (Phase 3-7):
  22. RFQAgent                   — Create/compare/award RFQs
  23. POAmendmentAgent           — PO modifications
  24. ReturnAgent                — Returns to vendor (RTV)
  25. QualityInspectionAgent     — QC checklists + auto-scoring
  26. ReconciliationAgent        — Bank statement matching

BACKGROUND AGENTS (always running):
  27. EmailInboxAgent            — Scans for invoices (every 15 min)
  28. AnomalyDetectionAgent      — Fraud detection (every 6 hours)
```
