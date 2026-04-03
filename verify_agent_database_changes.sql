-- ============================================================
-- SQL Queries to Verify Agent Database Changes
-- Run these in PostgreSQL to see what agents actually modified
-- ============================================================

-- 1. CHECK BUDGET CHANGES (Custom Table)
-- Should show IT/CAPEX committed budget increased by $120,000
SELECT 
    department,
    budget_category,
    fiscal_year,
    allocated_budget,
    spent_budget,
    committed_budget,  -- Should be increased!
    available_budget,  -- Should be decreased!
    last_updated
FROM budget_tracking
WHERE department = 'IT' AND budget_category = 'CAPEX'
ORDER BY last_updated DESC;

-- 2. CHECK AGENT ACTIONS (Audit Trail)
-- Should show last 10 agent executions with timing
SELECT 
    id,
    agent_name,
    action_type,
    success,
    execution_time_ms,
    created_at,
    input_data->>'request' as request_summary,
    output_data->>'status' as result_status
FROM agent_actions
ORDER BY created_at DESC
LIMIT 10;

-- 3. CHECK PENDING APPROVALS (Low Confidence Decisions)
-- Should show VendorSelectionAgent approval (APR-2026-70413)
SELECT 
    id,
    approval_id,
    agent_name,
    decision_type,
    confidence_score,
    status,
    created_at,
    agent_decision->>'reasoning' as decision_reasoning
FROM pending_approvals
WHERE status = 'pending'
ORDER BY created_at DESC
LIMIT 5;

-- 4. CHECK PR APPROVAL WORKFLOWS (Custom Table)
-- Should show any PR workflows created by ApprovalRoutingAgent
SELECT 
    id,
    pr_number,
    department,
    total_amount,
    current_level,
    status,
    created_at
FROM pr_approval_workflows
ORDER BY created_at DESC
LIMIT 5;

-- 5. VERIFY ODOO VENDORS EXIST (Read from Odoo via API)
-- This is Odoo data - agents READ this via API, not direct SQL
-- Run this via: curl http://localhost:5000/api/odoo/vendors?limit=10

-- 6. CHECK ALL BUDGET TRACKING (Full Picture)
-- See all department budgets with utilization
SELECT 
    department,
    budget_category,
    allocated_budget,
    spent_budget,
    committed_budget,
    available_budget,
    ROUND((committed_budget::numeric / allocated_budget * 100), 2) as utilization_pct,
    CASE 
        WHEN available_budget < (allocated_budget * 0.05) THEN '🔴 CRITICAL'
        WHEN available_budget < (allocated_budget * 0.10) THEN '🟠 WARNING'
        WHEN available_budget < (allocated_budget * 0.20) THEN '🟡 ALERT'
        ELSE '🟢 OK'
    END as status
FROM budget_tracking
WHERE fiscal_year = 2026
ORDER BY department, budget_category;

-- 7. COUNT AGENT ACTIVITY (Statistics)
SELECT 
    agent_name,
    COUNT(*) as total_actions,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
    ROUND(AVG(execution_time_ms), 2) as avg_execution_ms,
    MAX(created_at) as last_execution
FROM agent_actions
GROUP BY agent_name
ORDER BY total_actions DESC;

-- ============================================================
-- EXPECTED RESULTS AFTER YOUR TESTS:
-- ============================================================
-- 1. IT/CAPEX committed_budget: Should be $120,000 higher
-- 2. agent_actions: Should have 4+ new records (Risk, Vendor, Supplier, Contract)
-- 3. pending_approvals: Should have APR-2026-70413 (VendorSelectionAgent, confidence 0.55)
-- 4. pr_approval_workflows: May have new workflow if full PR→PO test ran
-- 5. Odoo vendors: Should show Gemini Furniture, Ready Mat (via API, not SQL)
-- ============================================================
