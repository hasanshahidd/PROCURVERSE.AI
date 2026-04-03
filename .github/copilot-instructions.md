# Procurement AI Platform - AI Agent Instructions

## Quick Start for AI Agents (Actionable Summary)

This top-level guide gives the essential facts an AI coding agent needs to be productive immediately.

- **Primary goal:** Agents orchestrate procurement workflows by reading Odoo (XML-RPC) and writing intelligence to custom tables. Never write directly to Odoo DB.
- **Where to start:** read this file, then `AI_AGENT_ARCHITECTURE_REFERENCE.md` and `COMPLETE_WORKFLOW_ODOO_METHODS.md` for the 20 mapped workflows.
- **Run the system (dev):** start backend and frontend separately.
  - Backend: `uvicorn backend.main:app --reload --host 0.0.0.0 --port 5000`
  - Frontend: `npm run dev` (root workspace) — dev server proxies `/api/*` to port 5000.
- **Env vars required:** `OPENAI_API_KEY`, `DATABASE_URL`, `ODOO_URL`, `ODOO_DB`, `ODOO_USERNAME`, `ODOO_PASSWORD`.
- **Tests & quick checks:**
  - Run unit tests: `pytest backend/tests` or run a single suite (e.g. `python backend/tests/test_risk_agent_week1.py`).
  - Quick DB check: `python backend/check_risk_data.py` (exists for risk assessments).
- **Key files to inspect (fast path):**
  - Agent framework: `backend/agents/__init__.py` (BaseAgent)
  - Orchestrator: `backend/agents/orchestrator.py` (routing + `register_agent`)
  - Tools: `backend/agents/tools.py` (LangChain tools; MUST return JSON strings)
  - Odoo interface: `backend/services/odoo_client.py` (XML-RPC wrappers)
  - Hybrid queries: `backend/services/hybrid_query.py` (custom table access)
  - Workflows: `COMPLETE_WORKFLOW_ODOO_METHODS.md` (20 workflows mapping)
- **Non-obvious conventions (strict):**
  - All writes to Odoo must go through XML-RPC endpoints exposed in `backend/routes/odoo.py` or `odoo_client.py` — do not modify DB rows directly.
  - LangChain tools and agent tools must return JSON-serializable strings (not Python dicts).
  - Confidence threshold: decisions with `confidence < 0.6` are escalated to the `pending_approvals` table (human-in-loop).
  - Audit/logging: use `_log_action()` to record to `agent_actions` table.
- **Adding/updating agents:**
  - Inherit from `BaseAgent` or `ToolBasedAgent` in `backend/agents/`.
  - Implement `observe()`, `decide()`, `_execute_action()`, `learn()`.
  - Register with orchestrator: `register_agent(name, instance)`.
  - Add persistent storage tooling in `backend/agents/tools.py` and migrations in `backend/migrations/`.

This short guide is intended to be high-signal—see the rest of this file below for full policies, detailed architecture, and reference commands.

## Architecture Overview

**Three-mode procurement platform**: Natural Language chatbot + Odoo ERP integration + Autonomous AI Agents for enterprise procurement management.

**Stack:**
- Frontend: React 18 + TypeScript + Vite + Shadcn/ui + Tailwind (port 5173)
- Backend: FastAPI (Python 3.11+) + PostgreSQL + Odoo XML-RPC (port 5000)
- AI: OpenAI GPT-4o-mini for NL→SQL + insights generation + agent orchestration
- Agentic: LangChain 0.1.10 + LangGraph 0.0.26 for multi-agent workflows
- Monorepo: Single root `package.json`, shared types in `shared/`, no `client/package.json`

**TWO DATA SOURCES**:
1. **Odoo ERP**: `odoo_procurement_demo` database (port 5433) - **API-only access via XML-RPC**
2. **Agentic Tables**: 7 custom tables for approval chains, budget tracking, workflows, agent actions & decisions

**Data Flow:**
1. **Odoo**: API calls → `/api/odoo/*` → XML-RPC client → Odoo server (localhost:8069)
2. **Agentic**: Request → `/api/agentic/execute` → Orchestrator → Specialized Agent → Odoo/Database → Result

**Legacy System (Archived Feb 2026):**
- Backed up 500 records from legacy table ($131.4M budget)
- Archived code: `database.py`, `excel_loader.py`, 3 Excel files
- Location: `backend/archive_old_code/legacy_chatbot_code/`
- Documentation: See `LEGACY_BOT_FUNCTIONALITY.md` for restoration guide
- System now 100% agentic-based with Odoo integration

## Critical Development Patterns

### Data Access Rules (CRITICAL!)
**Decision Tree:**
```
Need to READ Odoo data (purchase orders, vendors, products)?
└─ Use Odoo API: `/api/odoo/*` endpoints (NEVER query odoo_procurement_demo directly)

Need to WRITE/UPDATE Odoo data (approve PO, create requisition)?
└─ ALWAYS use Odoo API - direct DB writes corrupt Odoo's state

Need budget or approval decisions?
└─ Use Agentic System: BudgetVerificationAgent or ApprovalRoutingAgent

Need custom approval chains or budget tracking data?
└─ Query custom tables (approval_chains, budget_tracking) via hybrid_query.py
```

**Why?** Odoo enforces business logic through its API. Agentic system provides intelligent decision-making for budget and approval workflows.

### Architecture: Agents WRAP Odoo (CRITICAL UNDERSTANDING!)

**Data Storage Distribution:**
```
Odoo Models: 85% (purchase.order, res.partner, stock.picking, account.move)
Custom Tables: 15% (approval_chains, budget_tracking, agent_actions)
```

**Work Automation Distribution:**
```
Agents: 100% 🤖 (ALL intelligent orchestration & decision-making)
Odoo: 0% automation (just data storage + manual UI)
```

**Pattern (applied to all 20 workflows):**
```python
User Request
    ↓
Orchestrator Agent (routes to specialized agent)
    ↓
Specialized Agent:
  - READ 85% data from Odoo (vendors, POs, stock, invoices)
  - AUTOMATE 100% decision logic (scoring, ML, routing, alerts)
  - WRITE 85% results to Odoo (create PO, confirm, email)
  - LOG 15% agent data to custom tables (decisions, actions, history)
    ↓
Result returned to user (fully automated!)
```

**What Agents Do:**
- **Without Agents**: Odoo is just a database with forms (100% manual work)
- **With Agents**: Fully autonomous procurement (budget checks, approval routing, vendor scoring, risk analysis, contract monitoring - all automatic)

**See [`COMPLETE_WORKFLOW_ODOO_METHODS.md`](../COMPLETE_WORKFLOW_ODOO_METHODS.md) for all 20 workflows with exact Odoo API calls + Agent wrappers.**

### Agentic System Architecture (3-Sprint Accelerated Plan)

**Pattern:** OBSERVE → DECIDE → ACT → LEARN cycle for autonomous procurement workflows.

**Current Status:** Sprint 2 (6 of 17 agents operational)

**Core Components:**
- **BaseAgent** (`backend/agents/__init__.py`): Abstract base class for all agents
  - Human escalation when confidence < 0.6
  - Automatic retry (3 attempts) with exponential backoff via `@retry` decorator
  - Action logging to `agent_actions` table
  - Decision history in `agent_decisions` table
  - Alternative action fallback if primary fails

- **OrchestratorAgent** (`backend/agents/orchestrator.py`): Master router using LLM classification
  - Routes requests to appropriate specialized agent(s)
  - Supports parallel and sequential agent execution
  - Fallback routing when LLM classification uncertain
  - `register_agent(name, instance)` - Dynamic agent registration

- **Specialized Agents** (`backend/agents/`) - **6 of 17 OPERATIONAL (Sprint 2):**
  - `BudgetVerificationAgent` ✅: Checks budget availability, threshold alerts (80%, 90%, 95%)
  - `ApprovalRoutingAgent` ✅: Multi-level approval (Manager→Director→VP/CFO), escalation, dept routing
  - `VendorSelectionAgent` ✅: Multi-criteria vendor scoring (Quality 40%, Price 30%, Delivery 20%, Category 10%)
  - `RiskAssessmentAgent` ✅: 4-dimensional risk analysis (Vendor 30%, Financial 30%, Compliance 25%, Operational 15%)
  - `ContractMonitoringAgent` ✅: Contract expiration tracking (90/60/30/7 day alerts), renewal recommendations, spend analysis
  - `SupplierPerformanceAgent` ✅: 4-dimensional performance evaluation (Delivery 40%, Quality 30%, Price 15%, Communication 15%), 5 performance levels
  - **Current**: 9 agents total (BaseAgent + ToolBasedAgent + Orchestrator + 6 specialized)
  - **Planned**: 17 specialized agents across 3 sprints (11 more agents remaining)

**7 Custom Database Tables:**
```sql
-- Approval chains (12 rows for IT/Finance/Operations/Procurement)
approval_chains(id, department, budget_threshold, approval_level, approver_name, approver_email, status)

-- Real-time budget tracking (8 FY2026 records - CAPEX/OPEX per dept)
budget_tracking(id, department, budget_category, fiscal_year, allocated_budget, spent_budget, 
                committed_budget, available_budget GENERATED, alert_threshold_80/90/95)

-- Agent audit trail (90+ actions logged - ACTIVE PRODUCTION!)
agent_actions(id, agent_name, action_type, input_data JSONB, output_data JSONB, 
              success, error_message, execution_time_ms, created_at)

-- Learning history (awaiting Sprint 3 implementation)
agent_decisions(id, agent_name, decision_context JSONB, decision_made, reasoning, confidence_score, 
                alternatives JSONB, human_override, outcome, created_at)

-- Approval system (NEW Feb 25) - Human oversight for low-confidence AI decisions
pending_approvals(id, pr_number, decision_type, agent_decision JSONB, confidence_score, 
                 status, reviewed_by, reviewed_at, review_notes, created_at)

-- PR workflow tracking (NEW Feb 25)
pr_approval_workflows(id, pr_number, department, total_amount, requester_name, current_level,
                     status, request_data JSONB, created_at, completed_at)

-- Individual approval steps (NEW Feb 25)
pr_approval_steps(id, workflow_id, approval_level, approver_email, approver_name, status,
                 decided_at, notes, rejection_reason, created_at)
```

**12 LangChain Tools** (`backend/agents/tools.py`):
- **Odoo (5)**: get_purchase_orders, get_vendors, create_purchase_order, approve_purchase_order, get_products
- **Budget (4)**: get_approval_chain, check_budget_availability, update_committed_budget, get_department_budget_status
- **Approval (3)**: get_approval_chain, record_approval_decision, escalate_to_next_level
- **Database (4)**: get_approval_chain, check_budget_availability, update_committed_budget, get_department_budget_status
- All tools return JSON strings (LangChain requirement)

**Agentic API Endpoints** (`/api/agentic/*`):
```python
# Master orchestrator endpoint
POST /api/agentic/execute
Body: {"request": "Verify IT budget for $50K", "pr_data": {...}}

# Direct agent testing
POST /api/agentic/budget/verify
Body: {"request": "Check budget", "pr_data": {"department": "IT", "budget": 50000}}
POST /api/agentic/approval/route
Body: {"request": "Route PR", "pr_data": {"department": "Finance", "budget": 75000}}
POST /api/agentic/vendor/recommend
Body: {"request": "Find best vendor", "pr_data": {"category": "Electronics", "budget": 50000}}
POST /api/agentic/risk/assess
Body: {"request": "Assess risks", "pr_data": {"vendor_name": "XYZ", "budget": 100000, "urgency": "High"}}
POST /api/agentic/contract/monitor
Body: {"request": "Monitor contract", "pr_data": {"contract_number": "CNT-001", "end_date": "2026-06-30", "contract_value": 100000, "spent_amount": 75000}}
POST /api/agentic/supplier/evaluate
Body: {"request": "Evaluate supplier", "supplier_data": {"supplier_name": "ABC Corp", "total_orders": 50, "on_time_deliveries": 48, "defective_items": 10, "communication_rating": 4.5}}

# Approval system endpoints (NEW Feb 25)
GET /api/agentic/pending-approvals  # Low-confidence decisions needing human review
GET /api/agentic/pending-approvals/history  # Approved/rejected decisions
POST /api/agentic/pending-approvals/{id}/approve  # Approve AI decision
POST /api/agentic/pending-approvals/{id}/reject  # Reject with reason
GET /api/agentic/approval-workflows  # All PR workflows with progress
GET /api/agentic/my-approvals/{email}?status=pending  # Role-based approval items
POST /api/agentic/my-approvals/{email}/approve  # Approve PR step
POST /api/agentic/my-approvals/{email}/reject  # Reject PR step
GET /api/agentic/my-approvals/{email}/stats  # Approver statistics
GET /api/agentic/approval-chains  # View approval routing configuration

# System monitoring
GET /api/agentic/status      # Agent health and execution stats
GET /api/agentic/agents      # List registered agents (returns 4 specialized agents)
GET /api/agentic/health      # Health check
GET /api/agentic/dashboard/data  # Dashboard metrics and analytics
```

**Creating New Agents:**
```python
from backend.agents import BaseAgent, AgentDecision

class MyAgent(BaseAgent):
    async def observe(self, input_data):
        # OBSERVE: Gather context
        return {"enriched_data": ...}
    
    async def decide(self, observations):
        # DECIDE: Use LLM reasoning
        return AgentDecision(
            action="approve",
            reasoning="Budget available",
            confidence=0.85,
            context=observations
        )
    
    async def _execute_action(self, decision):
        # ACT: Execute via tools
        return {"status": "success"}
    
    async def learn(self, result):
        # LEARN: Update patterns
        self.decision_history.append(result.get("decision"))
```

**Agent Development Rules:**
1. Always inherit from `BaseAgent` or `ToolBasedAgent`
2. Confidence < 0.6 automatically escalates to human
3. Use `@retry` decorator for API calls that may fail
4. Log actions to `agent_actions` table via `_log_action()`
5. All tools must return JSON strings, not Python dicts
7. Run `python backend/tests/verify_all_agents.py` to validate system health
6. Test agents individually before registering with orchestrator

### Project Structure
- **Monorepo setup**: Root `package.json` manages both frontend and backend
- **Client folder**: React app in `client/src/`, uses Vite with proxy to backend
- **Backend folder**: FastAPI app in `backend/`, Python modules with `__init__.py`
- **Backend services**:
  - `database.py`: Archived legacy SQL service (no longer in active runtime)
  - `odoo_client.py`: XML-RPC client for Odoo API (odoo_procurement_demo DB)
  - `openai_client.py`: GPT-4o NL→SQL and insights generation
  - `translation_service.py`: Multi-language translation (en/ur/ar)
  - `hybrid_query.py`: Query classifier & router (general/odoo/approval_chains/budget_tracking/agent_history)
- **Backend routes**:
  - `chat.py`: SSE streaming chatbot with query classification
  - `odoo.py`: Odoo API proxies (purchase orders, vendors, analytics)
  - `agentic.py`: Agentic sy (582 lines), ToolBasedAgent, AgentDecision, AgentStatus classes
  - `orchestrator.py`: OrchestratorAgent (413 lines) for intelligent routing
  - `budget_verification.py`: Budget availability checking (279 lines)
  - `approval_routing.py`: Multi-level approval workflows (372 lines)
  - `vendor_selection.py`: Multi-criteria vendor scoring (491 lines)
  - `risk_assessment.py`: 4-dimensional risk analysis (692 lines)
  - `tools.py`: 12 LangChain tools (5 Odoo + 7 database/approval) - 27KB
  - `risk_assessment.py`: 4-dimensional risk analysis
  - `tools.py`: 12 LangChain tools (5 7 agentic tables with seed data
- **Backend tests** (11 test suites, 42+ test cases):
  - `test_sprint1.py`: Budget & orchestrator tests (4 async tests)
  - `test_approval_agent.py`: Approval routing tests (6 tests)
  - `test_risk_agent.py`: Risk assessment scenarios (4 tests)
  - `test_vendor_agent.py`: Vendor selection comprehensive tests
  - `test_contract_agent.py`: Contract monitoring tests (9 comprehensive scenarios)
  - `test_supplier_agent.py`: Supplier performance tests (8 comprehensive scenarios - 100% pass rate)
  - `verify_all_agents.py`: System-wide validation script
  - `verify_contract_agent.py`: Contract agent structure verification (no API key needed)
  - `verify_supplier_agent.py`: Supplier agent structure verification (no API key needed)
- **Database schema**: See `DATABASE_SCHEMA.md` for complete 7-table structure (backend uses psycopg2 raw SQL, not ORM)
- **Documentation**: 
  - `AGENT_SYSTEM_ANALYSIS.md`: Comprehensive agent architecture deep-dive (2,850+ lines)
  - `AGENT_CONTRACT_MONITORING.md`: ContractMonitoringAgent documentation
  - `AGENT_SUPPLIER_PERFORMANCE.md`: SupplierPerformanceAgent documentation
- **Assets**: `attached_assets/` contains Excel datasets (500-700 records)
- **Vite proxy**: Dev server auto-proxies `/api/*` to `http://localhost:5000`

### Backend (`backend/`)

**Odoo Integration** (`services/odoo_client.py`, `routes/odoo.py`):
- **Connection**: XML-RPC to http://localhost:8069, database `odoo_procurement_demo`
- **Authentication**: Username/password via environment variables, returns `uid`
- **Core method**: `execute_kw(model, method, args, kwargs)` - all Odoo operations use this
- **Example**: `odoo_client.get_purchase_orders(limit=100, domain=[('state', '=', 'draft')])`
- **Models available**: 
  - `purchase.order`: Purchase orders with states (draft/sent/purchase/done/cancel)
  - `purchase.requisition`: Purchase requisitions (requires purchase_requisition module)
  - `res.partner`: Vendors/suppliers
  - `product.product`: Product catalog
  - `stock.picking`: Deliveries and inventory movements
- **API endpoints** (`/api/odoo/*`):
  - GET `/api/odoo/status` - Check Odoo connection
  - GET `/api/odoo/purchase-orders?state=draft&limit=10` - Fetch POs
  - POST `/api/odoo/purchase-orders/action` - Approve/cancel POs
  - GET `/api/odoo/vendors` - Get vendor list
  - GET `/api/odoo/pr90+ records - ACTIVE!): All agent actions with input/output/timing
  - `agent_decisions` (0 records): Decision context, reasoning, confidence scores (awaiting implementation)
  - `pending_approvals`: Low-confidence AI decisions needing human review
  - `pr_approval_workflows`: PR workflow instances with current status
  - `pr_approval_steps`
**Custom Agentic Tables** (`odoo_procurement_demo` database):
- **7 tables** for agentic system (direct SQL access allowed):
  - `approval_chains` (12 rows): Multi-level approval rules per department
  - `budget_tracking` (8 rows): FY2026 budgets for 4 depts × 2 categories (CAPEX/OPEX)
  - `agent_actions` (audit trail): All agent actions with input/output/timing
  - `agent_decisions` (learning history): Decision context, reasoning, confidence scores
  - `pending_approvals` (NEW): Low-confidence AI decisions needing human review
  - `pr_approval_workflows` (NEW): PR workflow instances with current status
  - `pr_approval_steps` (NEW): Individual approval steps for each workflow level
- Query via `hybrid_query.py` functions:
  - `query_approval_chains(department, amount)` - Get required approvers
  - `query_budget_status(department, fiscal_year)` - Get budget availability
  - `query_agent_history()` - Agent performance analytics
- Connection: `psycopg2` with `RealDictCursor` returns list of dicts

**Legacy System (REMOVED Feb 24, 2026):**
- `database.py` archived → `backend/archive_old_code/legacy_chatbot_code/`
- `excel_loader.py` archived → `backend/archive_old_code/legacy_chatbot_code/`
- Legacy table dropped after backup
- 3 Excel files backed up → `backend/archive_old_code/legacy_excel_data/`

**AI Processing** (`services/openai_client.py`):
- SYSTEM_PROMPT (200+ lines): Complete schema docs with query examples
- Pipeline: `process_chat()` → `validate_sql()` → `execute` → `format_response()` → `generate_insights()`
- Multi-query: Handles complex questions requiring 2+ SQL statements
- Insights: Auto-generates patterns/alerts for 2+ results (fails silently on error)
- **CRITICAL**: Always processes in English internally (see Translation below)

**Translation System** (`services/translation_service.py`):
- **Three-layer architecture**: User input (AR/UR) → Translate to EN → Process in EN → Translate back to user language
- **Languages**: English (en), Urdu (ur), Arabic (ar) with RTL support
- **Key functions**:
  - `translate_to_english(text, source_language)`: Converts AR/UR input to EN for processing
  - `translate_from_english(text, target_language)`: Converts EN responses back to AR/UR
  - `is_translation_needed(language)`: Returns `True` only for "ur" or "ar"
- **Structure preservation**: 9 CRITICAL RULES in system prompt ensure markdown tables, numbers, percentages, PR numbers, and formatting survive translation intact
- **Processing language**: ALWAYS "en" after input translation - all `openai_client` calls use English
- **Translation boundaries**: Only translate at system edges (user input/output), never during internal processing
- **Logging**: Comprehensive INFO-level logging shows input/output text, lengths, table markers for debugging

**Streaming API** (`routes/chat.py`):
```python
@router.post("/chat/stream")  # SSE endpoint
async def chat_stream(request: ChatRequest):
    async def generate_stream():
        yield f"data: {json.dumps({'type': 'progress', 'step': 1, 'status': 'active'})}\n\n"
        yield f"data: {json.dumps({'type': 'sql', 'query': sql})}\n\n"
        yield f"data: {json.dumps({'type': 'table', 'data': rows})}\n\n"
        yield f"data: {json.dumps({'type': 'insights', 'insights': text})}\n\n"
        # Word-by-word text streaming
        for word in words:
            yield f"data: {json.dumps({'type': 'text', 'text': word})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
```
Progress steps: 1=analyzing → 2=searching → 3=generating → 4=finalizing

**Excel Loader** (`services/excel_loader.py`):
- Auto-loads on startup if DB empty: `attached_assets/ERP_SAMPLE_DATASET_*.xlsx`
- Handles 127 columns with smart defaults (priority_level="Medium", currency="USD")
- Looks for EXPANDED file first (700 rows), falls back to original (500 rows)

### Frontend (`client/src/`)

**Chat State** (`pages/ChatPage.tsx`):
- Multi-session management with localStorage (`chat_sessions`, `active_session_id`)
- Session structure: `{id, title, timestamp, messages[], language}`
- Title auto-generated from first message (max 50 chars)
- Messages: `{id, role, content, chartData?, insights?, sqlQuery?}`

**SSE Stream Handler** (ChatPage.tsx lines 200-350):
```typescript
const eventSource = new EventSource(`${API_URL}/api/chat/stream`);
eventSource.onmessage = (e) => {
  const event = JSON.parse(e.data);
  switch(event.type) {
    case 'progress': setProgressSteps(...); break;
    case 'sql': setSqlQuery(event.query); break;
    case 'table': setTableData(event.data); break;
    case 'insights': setInsights(event.insights); break;
    case 'text': appendWord(event.text); break; // Word-by-word
  }
};
```

**Chart Auto-Detection** (`components/DataCharts.tsx`):
- Triggers for 2-15 records with suitable structure
- Type detection: time fields → line, single dimension → pie, else → bar
- Example: `{department: "IT", budget: 50000}` → Pie chart
- Uses Recharts with COLORS array for dark mode

**Voice & UI** (`components/`):
- `LanguageSelector.tsx`: Dropdown with 3 languages (en/ur/ar), stores selection in session
- `AgentStatus.tsx`: Real-time agent status badge (5s auto-refresh, shows active/idle count)
- All use Shadcn/ui components - never modify `ui/` base files directly
Sprint 3
**Agent Dashboard** (`pages/AgentDashboard.tsx`):
- Full monitoring UI for agentic system
- 4 stat cards: Active Agents, Total Actions, Budget Checks, Approval Chains
- Agent status table with real-time data from `/api/agentic/status`
- System health panel (PostgreSQL, Odoo, Agentic system)
- Auto-refresh toggle (5-10s intervals)
- Text-to-speech toggle with language-aware voices (en/ur/ar)

**Approval System UI** (`pages/*ApprovalsPage.tsx`) - NEW Feb 25:
- **4 approval pages** for complete workflow management:
  1. `PendingApprovalsPage.tsx`: Review low-confidence AI decisions
     - Pending tab: Awaiting human review
     - History tab: Approved/rejected decisions with timestamps
  2. `ApprovalWorkflowPage.tsx`: Monitor ALL company PRs (global view)
     - Visual stepper showing 3-level progress (Manager→Director→VP/CFO)
     - Filter by status/department
     - NOT for approval actions (monitoring only)
  3. `MyApprovalsPage.tsx`: Role-based approval page (personalized)
     - Shows ONLY items assigned to YOUR emailSprint 3
     - Pending/History tabs with approve/reject actions
     - Statistics dashboard (pending count, approval rate, avg decision time)
     - User switcher dropdown for testing (Mike Manager, Diana Director, Victor VP)
  4. `ApprovalSettingsPage.tsx`: Admin configuration view
     - Shows approval chain rules by department
     - Visual 3-level hierarchy with dollar thresholds
     - Explains how ApprovalRoutingAgent auto-routes PRs

**User Profile System** (`components/MainLayout.tsx`) - NEW Feb 25:
- **Sidebar user profile card** visible on ALL pages
- Shows current user: Avatar, Name, Role (Manager/Director/VP)
- Dropdown to switch between test users (syncs via localStorage)
- Custom event `userChanged` broadcasts profile changes to all pages
- Test users: Mike Manager, Diana Director (default), Victor VP/CFO

**Component Conventions**:
- `QuerySuggestions.tsx`: Context-aware autocomplete (keyboard navigation)
- `ChatSidebar.tsx`: Session list with infinite scroll
- All use Shadcn/ui components - never modify `ui/` base files directly

## Key Development Workflows

**Running Development (Windows PowerShell):**
```powershell
# Terminal 1 - Odoo Server (port 8069)
# Start from Odoo installation directory
python odoo-bin -c odoo.conf -d odoo_procurement_demo

# Terminal 2 - Backend (port 5000)
cd backend
uvicorn backend.main:app --reload --host 0.0.0.0 --port 5000

# Terminal 3 - Frontend (port 5173)
npm run dev  # Runs from root, proxies /api/* to localhost:5000
```

**Environment Setup:**
```env
# Root .env file (required)
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://user:pass@host:5432/odoo_procurement_demo

# Odoo connection (defaults shown, override if needed)
ODOO_URL=http://localhost:8069
ODOO_DB=odoo_procurement_demo
ODOO_USERNAME=admin
ODOO_PASSWORD=admin
```

**Database Operations:**
```python
# Agentic Tables - Direct SQL via hybrid_query
from backend.services import hybrid_query

# Query approval chains
approval_data = hybrid_query.query_approval_chains(department="IT", amount=50000)

# Query budget status
budget_data = hybrid_query.query_budget_status(department="Finance", fiscal_year=2026)

# Odoo ERP - API access only
odoo = get_odoo_client()
pos = odoo.get_purchase_orders(limit=10, domain=[('state', '=', 'draft')])
po_id = odoo.create_purchase_order(partner_id=5, order_lines=[...])
```

**Testing Endpoints:**
```powershell
# Chatbot - Non-streaming (debugging)
curl -X POST http://localhost:5000/api/chat `
  -H "Content-Type: application/json" `
  -d '{"message": "Show high risk PRs", "language": "en"}'

# Odoo - Connection status
curl http://localhost:5000/api/odoo/status

# Odoo - Get purchase orders
curl http://localhost:5000/api/odoo/purchase-orders?state=draft

# Odoo - Approve purchase order
curl -X POST http://localhost:5000/api/odoo/purchase-orders/action `
  -H "Content-Type: application/json" `
  -d '{"po_id": 5, "action": "approve"}'

# Agentic - Orchestrator execution [NEW]
curl -X POST http://localhost:5000/api/agentic/execute `
  -H "Content-Type: application/json" `

# Agentic - Approval routing (Sprint 2)
curl -X POST http://localhost:5000/api/agentic/approval/route `
  -H "Content-Type: application/json" `
  -d '{"request": "Route this PR", "pr_data": {"pr_number": "PR-2026-0001", "department": "IT", "budget": 15000}}'

# Agentic - Vendor recommendation (Sprint 2)
$body = @{ request = "Find best vendor"; pr_data = @{ category = "Electronics"; budget = 50000 } } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:5000/api/agentic/vendor/recommend -Method Post -Body $body -ContentType "application/json"

# Agentic - Risk assessment (Sprint 3)
$body = @{ request = "Assess risks"; pr_data = @{ vendor_name = "XYZ"; budget = 120000; urgency = "High" } } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:5000/api/agentic/risk/assess -Method Post -Body $body -ContentType "application/json"

# Agentic - Direct budget verification
curl -X POST http://localhost:5000/api/agentic/budget/verify `
  -H "Content-Type: application/json" `
  -d '{"request": "Check budget", "pr_data": {"department": "Finance", "budget": 100000, "budget_category": "OPEX"}}'

# Agentic - System status [NEW]
curl http://localhost:5000/api/agentic/status

# Agentic - List registered agents [NEW]
curl http://localhost:5000/api/agentic/agents

# Test Arabic translation (must preserve tables/numbers)
curl -X POST http://localhost:5000/api/chat `
  -H "Content-Type: application/json" `
  -d '{\"message\": \"عرض جميع الأقسام\", \"language\": \"ar\"}'

# Health check
curl http://localhost:5000/api/health
```

**Translation Testing:**
- Use `test_translation.py` to verify table/number preservation offline
- Check terminal logs for `[INPUT TRANSLATION]` and `[OUTPUT TRANSLATION]` markers
- Verify table markers (`|`, `---`) appear in logs before and after translation
- Test with queries that return 2-15 records with tables to trigger chart rendering

## Common Pitfalls & Solutions

1. **SQL Generation Issues:**
   - Check SYSTEM_PROMPT in `openai_client.py` for column names/types
   - Date comparisons: `CAST(date AS DATE)` not `date::DATE`
   - PR numbers: 4 digits with zeros (PR-2024-0045 not PR-2024-45)
   - Ratings: `supplier_rating` is TEXT - never cast to numeric
   - New columns: `requester_name`, `supplier_category`, `budget_category` (CAPEX/OPEX)

2. **Chart Not Rendering:**
   - Requires 2-15 records AND suitable structure
   - Check `shouldShowChart()` in DataCharts.tsx
   - Pie needs categorical field, line needs time dimension

3. **SSE Streaming Breaks:**
   - Must be `Content-Type: text/event-stream`
   - Format: `data: {json}\n\n` (double newline required)
   - Progress steps must be integers 1-4

4. **CORS Errors:**
   - Backend allows: localhost:5173, *.onrender.com, *.vercel.app
   - Update `main.py` CORS:**
   - Agent not executing? Check if registered with orchestrator via `register_agent()`
   - Tool returning wrong type? All tools MUST return JSON strings, not Python dicts
   - Low confidence triggering escalation? This is expected behavior - threshold is 0.6
   - Database connection failing? Ensure `approval_chains` and `budget_tracking` tables exist (run `create_agent_tables.py`)
   - LangChain import errors? Verify package versions: langchain==0.1.10, langchain-openai==0.0.5
   - Agent action not logged? Check `_log_action()` is called in `_execute_action()` method
   - Odoo parameter errors? Check method signatures in `odoo_client.py` (e.g., `get_products(search_term=...)` not `search=`)

8. **Query Classification Issues:**
   - Greeting triggering agents? Classifier should have "general" category for hi/hello/help queries
   - Wrong data source routing? Check `hybrid_query.py` classifier with comprehensive logging
   - Logs show: `[QUERY CLASSIFIER]` → `[CLASSIFICATION RESULT]` → `[ROUTING DECISION]` → `[QUERY RESULT]`
6. **Translation Issues:**
   - Tables/numbers missing in Arabic/Urdu? Check translation prompt has 9 CRITICAL RULES
   - Backend must use `processing_language = "en"` for all `openai_client` calls
   - Translation only at boundaries: input (AR/UR→EN) and output (EN→AR/UR)
   - Never pass `request.language` to openai_client - always use "en"
   - Check logs for table markers: `|`, `---`, numbers should appear in both original and translated

7. **Agentic System Issues [NEW]:**
   - Agent not executing? Check if registered with orchestrator via `register_agent()`
   - Tool returning wrong type? All tools MUST return JSON strings, not Python dicts
   - Low confidence triggeri& 2 - OPERATIONAL!)

**Status:** ✅ Foundation 100% + Approval Agent Complete (Feb 24, 2026)

## Agentic Development Timeline

**Status:** ✅ Phase 3 IN PROGRESS - 10 of 17 Agents Operational (59%)

**Vision:** Transform reactive chatbot into proactive AI agent using LangChain across 4 phases delivering 17 specialized agents.

**4-Phase Development Plan:**
- **Phase 1**: Foundation (3 agents) - ✅ 100% COMPLETE (Feb 23-24)
- **Phase 2**: Core Procurement (4 agents) - ✅ 100% COMPLETE (Feb 25 - Mar 4)
- **Phase 3**: Analytics & Workflows (9 agents) - 🟡 33% COMPLETE (3 of 9) - IN PROGRESS
- **Phase 4**: System Monitoring (1 agent) - ⏳ NOT STARTED
- **Total**: 17 specialized agents including Orchestrator

**Implemented (Sprint 1 - 100% Complete - Feb 2026):**
- ✅ LangChain framework (langchain 0.1.10, langchain-openai 0.0.5, langgraph 0.0.26)
- ✅ Base agent framework with OBSERVE → DECIDE → ACT → LEARN cycle
- ✅ Orchestrator agent with LLM-based routing
- ✅ BudgetVerificationAgent (checks budget availability, threshold alerts)
- ✅ 7 custom database tables (approval_chains, budget_tracking, agent_actions, agent_decisions, pending_approvals, pr_approval_workflows, pr_approval_steps)
- ✅ 12 LangChain tools (5 Odoo + 7 database/approval)
- ✅ API endpoints at `/api/agentic/*`
- ✅ Automatic retry, human escalation, action logging
- ✅ Frontend integration: AgentStatus badge + AgentDashboard page
- ✅ 4 approval system UI pages (PendingApprovals, ApprovalWorkflows, MyApprovals, ApprovalSettings)

**Implemented (Phase 2 - COMPLETE - 4 of 4 agents - 100%):**
1. ✅ **ApprovalRoutingAgent** (Feb 25): Multi-level routing (Manager→Director→VP/CFO), dept-based escalation
2. ✅ **VendorSelectionAgent** (Mar 2): Multi-criteria vendor scoring (Quality 40%, Price 30%, Delivery 20%, Category 10%)
3. ✅ **RiskAssessmentAgent** (Mar 4): 4-dimensional risk analysis (Vendor 30%, Financial 30%, Compliance 25%, Operational 15%)
4. ✅ **SupplierPerformanceAgent** (Mar 4): 4-dimensional evaluation (Delivery 40%, Quality 30%, Price 15%, Communication 15%), 5 performance levels

**Implemented (Phase 3 - PARTIAL - 3 of 9 agents - 33%):**
5. ✅ **PriceAnalysisAgent** (Mar 6): Compares vendor quotes vs market prices, negotiation recommendations
6. ✅ **ComplianceCheckAgent** (Mar 6): Validates PRs against internal policies, preferred vendor lists, external regulations
7. ✅ **ContractRenewalAgent** (Mar 7): Monitors contract expirations (90/60/30/7 day alerts), renewal recommendations, spend analysis

**Planned (Phase 3 - Remaining 6 agents):**
8. ⏳ **InvoiceMatchingAgent** (Mar 8): 3-way matching (PO + Receipt + Invoice), discrepancy detection, auto-approval
9. ⏳ **SpendAnalyticsAgent** (Mar 8): Company spending patterns by dept/category/supplier, cost savings tracking, budget insights
10. ⏳ **InventoryCheckAgent** (Mar 8): Real-time stock monitoring, reorder point alerts, auto-PR creation for low stock
11. ⏳ **DeliveryTrackingAgent** (Mar 10): Track shipments, monitor expected delivery dates, proactive delay alerts
12. ⏳ **ForecastingAgent** (Mar 10): Predict future demand using historical data, recommend quantities, prevent stockouts
13. ⏳ **DocumentProcessingAgent** (Mar 11): OCR invoice extraction, contract parsing, automated data entry

**Planned (Phase 4 - 1 agent):**
14. ⏳ **MonitoringDashboardAgent** (Mar 12): Real-time metrics aggregation, agent performance tracking, system health WebSocket
1, 2026):**
- **Production Metrics**: 90+ agent actions logged (active usage!)
- **Test Coverage**: 11 test suites, 42+ tests, all passing
- **System Health**: 10 specialized agents operational out of 17 planned (59%)
- **Phase Progress**: Phase 1 ✅ | Phase 2 ✅ | Phase 3 🟡 33% | Phase 4 ⏳
- **Documentation**: See `AGENT_SYSTEM_ANALYSIS.md`, `AGENT_CONTRACT_MONITORING.md`, `AGENT_SUPPLIER_PERFORMANCE.md`

**Phase 3 Remaining Work (6 agents):**
- Week 1 (Mar 2-8): InvoiceMatchingAgent, SpendAnalyticsAgent, InventoryCheckAgent
- Week 2 (Mar 9-15): DeliveryTrackingAgent, ForecastingAgent, DocumentProcessingAgent
- Week 3 (Mar 16-22): Phase 4 MonitoringDashboardAgent
- Learning system implementation (populate `agent_decisions` table)
- Enhanced analytics dashboard with trends
- E2E testing for full procurement workflows

**Future Roadmap:**
- Q2 2026: Mobile app + Advanced forecasting
- Q3 2026: SAP/Oracle ERP integrations
- Q4 2026: Multi-tenant & Enterprise featuresmance tracking
- Q4 2026: Full ERP integrations (SAP, Oracle)

**When Adding Features:**
- Understand Odoo API vs direct DB access pattern FIRST
- Test with both chatbot (`/api/chat/stream`) and Odoo endpoints (`/api/odoo/*`)
- Preserve agentic-only architecture with Odoo integration
- Update relevant .md documentation files
- Verify Odoo modules installed before using (run `verify_modules.py`)

## Key Architectural Insights

**Why Two Data Sources?**
- **Odoo (read-only via API)**: Enterprise data with 10+ years of business logic. Direct DB writes would bypass validation, corrupt state, and break workflows. Always use XML-RPC API.
- **Custom Tables (read/write SQL)**: Purpose-built for AI agent coordination. No business logic constraints, optimized for LangChain tool access.

**Why Confidence Thresholds?**
- Agents return confidence scores (0-1). Below 0.6 = automatic human escalation via `pending_approvals` table.
- This prevents AI from making risky decisions autonomously (e.g., approving $500K purchase with 45% confidence).
- Confidence calculation varies by agent: BudgetAgent uses data completeness, VendorAgent uses score gaps, RiskAgent uses risk level.

**Why Orchestrator Pattern?**
- Single entry point (`/api/agentic/execute`) routes to specialized agents based on LLM classification.
- Prevents routing logic duplication across agents. Supports parallel execution (e.g., budget check + vendor selection).
- Direct agent endpoints (`/budget/verify`, `/risk/assess`) exist for testing/debugging only.

**Why OBSERVE→DECIDE→ACT→LEARN Cycle?**
- **OBSERVE**: Enrich context from multiple sources (Odoo, DB, external APIs) before decision-making.
- **DECIDE**: LLM reasoning with structured output (action, confidence, alternatives).
- **ACT**: Execute via tools with retry logic and error handling.
- **LEARN**: Log decisions to `agent_decisions` table for future pattern recognition.

**Why Role-Based UI with Mock Users?**
- Real authentication not implemented yet. Mock users (Mike Manager, Diana Director, Victor VP) simulate different approval levels.
- `localStorage` + `userChanged` event syncs role across all pages, enabling realistic multi-level approval testing.
- In production, replace with actual JWT/OAuth and map user email to approval chains.

**Why Separate Approval Pages?**
- **PendingApprovals**: AI oversight (admin reviews low-confidence agent decisions)
- **ApprovalWorkflows**: Global monitoring (see ALL company PRs, not for action)
- **MyApprovals**: Personal action (approve/reject items assigned to YOU)
- **ApprovalSettings**: System configuration (understand routing rules)
- Clear separation prevents confusion about "where do I approve things?"

## Code Style

**TypeScript:**
- Functional components with hooks
- TanStack Query for API calls
- Wouter for routing (not React Router)
- Tailwind for styling (no CSS modules)

**Python:**
- FastAPI async/await patterns
- Type hints on all functions
- Pydantic models for request/response
- Context managers for DB connections

**File Naming:**
- Components: PascalCase (ChatPage.tsx)
- Services: snake_case (openai_client.py)
- Routes: kebab-case APIs (`/api/chat/stream`)
