-- =============================================================================
-- AGENTIC PROCUREMENT PLATFORM - Custom Tables Setup
-- Give this file to Replit and say: "Run this SQL in your PostgreSQL database"
-- =============================================================================

-- =============================================================================
-- TABLE 1: approval_chains
-- =============================================================================
CREATE TABLE IF NOT EXISTS approval_chains (
    id SERIAL PRIMARY KEY,
    pr_number VARCHAR(20),
    department VARCHAR(50) NOT NULL,
    budget_threshold DECIMAL(15,2) NOT NULL,
    approval_level INTEGER NOT NULL,
    approver_email VARCHAR(255) NOT NULL,
    approver_name VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    approved_at TIMESTAMP,
    rejection_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT check_approval_level CHECK (approval_level BETWEEN 1 AND 3),
    CONSTRAINT check_status CHECK (status IN ('pending', 'approved', 'rejected', 'escalated'))
);

CREATE INDEX IF NOT EXISTS idx_approval_chains_pr ON approval_chains(pr_number);
CREATE INDEX IF NOT EXISTS idx_approval_chains_status ON approval_chains(status);
CREATE INDEX IF NOT EXISTS idx_approval_chains_dept ON approval_chains(department, approval_level);

-- Seed data: 12 approval chain rows (IT, Finance, Operations, Procurement)
INSERT INTO approval_chains (department, budget_threshold, approval_level, approver_email, approver_name, status)
VALUES 
    ('IT', 10000, 1, 'mike.manager@company.com', 'Mike Manager', 'approved'),
    ('IT', 50000, 2, 'diana.director@company.com', 'Diana Director', 'approved'),
    ('IT', 100000, 3, 'victor.vp@company.com', 'Victor VP', 'approved'),
    ('Finance', 10000, 1, 'finance.manager@company.com', 'Finance Manager', 'approved'),
    ('Finance', 50000, 2, 'finance.director@company.com', 'Finance Director', 'approved'),
    ('Finance', 100000, 3, 'cfo@company.com', 'CFO', 'approved'),
    ('Operations', 10000, 1, 'ops.manager@company.com', 'Operations Manager', 'approved'),
    ('Operations', 50000, 2, 'ops.director@company.com', 'Operations Director', 'approved'),
    ('Operations', 100000, 3, 'coo@company.com', 'COO', 'approved'),
    ('Procurement', 10000, 1, 'procurement.manager@company.com', 'Procurement Manager', 'approved'),
    ('Procurement', 50000, 2, 'procurement.director@company.com', 'Procurement Director', 'approved'),
    ('Procurement', 100000, 3, 'cpo@company.com', 'CPO', 'approved')
ON CONFLICT DO NOTHING;


-- =============================================================================
-- TABLE 2: budget_tracking
-- =============================================================================
CREATE TABLE IF NOT EXISTS budget_tracking (
    id SERIAL PRIMARY KEY,
    department VARCHAR(50) NOT NULL,
    fiscal_year INTEGER NOT NULL,
    budget_category VARCHAR(20) NOT NULL,
    allocated_budget DECIMAL(15,2) NOT NULL,
    spent_budget DECIMAL(15,2) DEFAULT 0,
    committed_budget DECIMAL(15,2) DEFAULT 0,
    available_budget DECIMAL(15,2) GENERATED ALWAYS AS 
        (allocated_budget - spent_budget - committed_budget) STORED,
    last_updated TIMESTAMP DEFAULT NOW(),
    alert_threshold_80 BOOLEAN DEFAULT FALSE,
    alert_threshold_90 BOOLEAN DEFAULT FALSE,
    alert_threshold_95 BOOLEAN DEFAULT FALSE,
    CONSTRAINT check_budget_category CHECK (budget_category IN ('CAPEX', 'OPEX')),
    CONSTRAINT unique_dept_year_category UNIQUE (department, fiscal_year, budget_category)
);

CREATE INDEX IF NOT EXISTS idx_budget_tracking_dept ON budget_tracking(department, fiscal_year);

-- Seed data: 8 budget rows for FY2026
INSERT INTO budget_tracking (department, fiscal_year, budget_category, allocated_budget, spent_budget, committed_budget)
VALUES 
    ('IT', 2026, 'CAPEX', 5000000, 1200000, 800000),
    ('IT', 2026, 'OPEX', 3000000, 800000, 500000),
    ('Finance', 2026, 'CAPEX', 1000000, 200000, 150000),
    ('Finance', 2026, 'OPEX', 2000000, 600000, 300000),
    ('Operations', 2026, 'CAPEX', 8000000, 3000000, 2000000),
    ('Operations', 2026, 'OPEX', 5000000, 1500000, 1000000),
    ('Procurement', 2026, 'CAPEX', 500000, 100000, 50000),
    ('Procurement', 2026, 'OPEX', 1000000, 300000, 200000)
ON CONFLICT (department, fiscal_year, budget_category) DO NOTHING;


-- =============================================================================
-- TABLE 3: agent_actions  (audit trail)
-- =============================================================================
CREATE TABLE IF NOT EXISTS agent_actions (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    input_data JSONB,
    output_data JSONB,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT check_execution_time CHECK (execution_time_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_agent_actions_agent ON agent_actions(agent_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_actions_success ON agent_actions(success, created_at DESC);


-- =============================================================================
-- TABLE 4: agent_decisions  (learning history)
-- =============================================================================
CREATE TABLE IF NOT EXISTS agent_decisions (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL,
    decision_context JSONB NOT NULL,
    decision_made VARCHAR(255) NOT NULL,
    reasoning TEXT,
    confidence_score DECIMAL(3,2) NOT NULL,
    alternatives JSONB,
    human_override BOOLEAN DEFAULT FALSE,
    override_reason TEXT,
    outcome VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT check_confidence CHECK (confidence_score BETWEEN 0 AND 1)
);

CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent ON agent_decisions(agent_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_confidence ON agent_decisions(confidence_score);


-- =============================================================================
-- TABLE 5: pending_approvals  (human-in-loop for low confidence AI decisions)
-- =============================================================================
CREATE TABLE IF NOT EXISTS pending_approvals (
    approval_id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    request_type TEXT NOT NULL,
    request_data JSONB NOT NULL,
    recommendation JSONB NOT NULL,
    confidence_score FLOAT NOT NULL CHECK (confidence_score >= 0 AND confidence_score < 0.6),
    reasoning TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP,
    reviewed_by TEXT,
    review_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_approvals(status);
CREATE INDEX IF NOT EXISTS idx_pending_agent ON pending_approvals(agent_name);
CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_approvals(created_at DESC);

-- Seed: 2 sample pending approval items
INSERT INTO pending_approvals (approval_id, agent_name, request_type, request_data, recommendation, confidence_score, reasoning, status)
VALUES 
    ('APR-2026-0001', 'VendorSelectionAgent', 'vendor_selection', 
     '{"category": "Electronics", "budget": 50000}'::jsonb, 
     '{"vendor_name": "Gemini Furniture", "score": 69}'::jsonb,
     0.55, 
     'Multiple vendors scored similarly. Recommend human review for strategic vendor selection.', 
     'pending'),
    ('APR-2026-0002', 'BudgetVerificationAgent', 'budget_check', 
     '{"department": "IT", "budget": 75000, "budget_category": "CAPEX"}'::jsonb, 
     '{"approved": true, "available_budget": 80000, "utilization_rate": 0.94}'::jsonb,
     0.58, 
     'Budget availability confirmed but very close to 95% threshold. Recommend human review.', 
     'pending')
ON CONFLICT (approval_id) DO NOTHING;


-- =============================================================================
-- TABLE 6: pr_approval_workflows
-- =============================================================================
CREATE TABLE IF NOT EXISTS pr_approval_workflows (
    pr_number TEXT PRIMARY KEY,
    department TEXT NOT NULL CHECK (department IN ('IT', 'Finance', 'Operations', 'Procurement')),
    total_amount DECIMAL(15,2) NOT NULL,
    requester_name TEXT NOT NULL,
    request_data JSONB DEFAULT '{}'::jsonb,
    current_approval_level INT DEFAULT 1,
    workflow_status TEXT DEFAULT 'in_progress' CHECK (workflow_status IN ('in_progress', 'completed', 'rejected')),
    odoo_po_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_workflow_status ON pr_approval_workflows(workflow_status);
CREATE INDEX IF NOT EXISTS idx_workflow_dept ON pr_approval_workflows(department);
CREATE INDEX IF NOT EXISTS idx_workflow_created ON pr_approval_workflows(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_odoo_po ON pr_approval_workflows(odoo_po_id);

-- Seed: 3 sample PR workflows
INSERT INTO pr_approval_workflows (pr_number, department, total_amount, requester_name, current_approval_level, workflow_status)
VALUES 
    ('PR-2026-0001', 'IT', 45000, 'Alice Johnson', 2, 'in_progress'),
    ('PR-2026-0002', 'Finance', 120000, 'Bob Smith', 1, 'in_progress'),
    ('PR-2026-0003', 'Operations', 8500, 'Carol White', 1, 'completed')
ON CONFLICT (pr_number) DO NOTHING;


-- =============================================================================
-- TABLE 7: pr_approval_steps
-- =============================================================================
CREATE TABLE IF NOT EXISTS pr_approval_steps (
    id SERIAL PRIMARY KEY,
    pr_number TEXT NOT NULL REFERENCES pr_approval_workflows(pr_number) ON DELETE CASCADE,
    approval_level INT NOT NULL CHECK (approval_level IN (1, 2, 3)),
    approver_name TEXT NOT NULL,
    approver_email TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    approved_at TIMESTAMP,
    rejection_reason TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_steps_pr ON pr_approval_steps(pr_number);
CREATE INDEX IF NOT EXISTS idx_steps_approver ON pr_approval_steps(approver_email);
CREATE INDEX IF NOT EXISTS idx_steps_status ON pr_approval_steps(status);

-- Seed: Approval steps for the 3 PR workflows above
INSERT INTO pr_approval_steps (pr_number, approval_level, approver_name, approver_email, status, approved_at)
VALUES
    -- PR-2026-0001: Level 1 approved, Level 2 pending
    ('PR-2026-0001', 1, 'Mike Manager', 'mike.manager@company.com', 'approved', NOW() - INTERVAL '2 days'),
    ('PR-2026-0001', 2, 'Diana Director', 'diana.director@company.com', 'pending', NULL),
    ('PR-2026-0001', 3, 'Victor VP', 'victor.vp@company.com', 'pending', NULL),
    -- PR-2026-0002: All pending
    ('PR-2026-0002', 1, 'Finance Manager', 'finance.manager@company.com', 'pending', NULL),
    ('PR-2026-0002', 2, 'Finance Director', 'finance.director@company.com', 'pending', NULL),
    ('PR-2026-0002', 3, 'CFO', 'cfo@company.com', 'pending', NULL),
    -- PR-2026-0003: Level 1 only, completed
    ('PR-2026-0003', 1, 'Operations Manager', 'ops.manager@company.com', 'approved', NOW() - INTERVAL '1 day')
ON CONFLICT DO NOTHING;


-- =============================================================================
-- TABLE 8: po_risk_assessments
-- =============================================================================
CREATE TABLE IF NOT EXISTS po_risk_assessments (
    id SERIAL PRIMARY KEY,
    odoo_po_id INTEGER,
    pr_number VARCHAR(50),
    total_risk_score DECIMAL(5,2) NOT NULL,
    vendor_risk_score DECIMAL(5,2) NOT NULL,
    financial_risk_score DECIMAL(5,2) NOT NULL,
    compliance_risk_score DECIMAL(5,2) NOT NULL,
    operational_risk_score DECIMAL(5,2) NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    risk_breakdown JSONB NOT NULL,
    mitigation_recommendations JSONB,
    concerns_identified JSONB,
    recommended_action VARCHAR(100),
    decision_confidence DECIMAL(3,2),
    blocked_po_creation BOOLEAN DEFAULT FALSE,
    vendor_name VARCHAR(255),
    vendor_id INTEGER,
    budget_amount DECIMAL(15,2),
    department VARCHAR(100),
    category VARCHAR(100),
    urgency VARCHAR(20),
    assessed_at TIMESTAMP DEFAULT NOW(),
    assessed_by VARCHAR(100) DEFAULT 'RiskAssessmentAgent',
    actual_outcome VARCHAR(50),
    outcome_notes TEXT,
    outcome_updated_at TIMESTAMP,
    CONSTRAINT check_risk_level CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    CONSTRAINT check_risk_scores CHECK (
        total_risk_score >= 0 AND total_risk_score <= 100 AND
        vendor_risk_score >= 0 AND vendor_risk_score <= 100 AND
        financial_risk_score >= 0 AND financial_risk_score <= 100 AND
        compliance_risk_score >= 0 AND compliance_risk_score <= 100 AND
        operational_risk_score >= 0 AND operational_risk_score <= 100
    ),
    CONSTRAINT check_confidence CHECK (decision_confidence BETWEEN 0 AND 1)
);

CREATE INDEX IF NOT EXISTS idx_risk_assessments_po ON po_risk_assessments(odoo_po_id);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_pr ON po_risk_assessments(pr_number);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_level ON po_risk_assessments(risk_level);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_date ON po_risk_assessments(assessed_at DESC);


-- =============================================================================
-- DONE
-- =============================================================================
SELECT 'approval_chains' as table_name, COUNT(*) as rows FROM approval_chains
UNION ALL SELECT 'budget_tracking', COUNT(*) FROM budget_tracking
UNION ALL SELECT 'agent_actions', COUNT(*) FROM agent_actions
UNION ALL SELECT 'agent_decisions', COUNT(*) FROM agent_decisions
UNION ALL SELECT 'pending_approvals', COUNT(*) FROM pending_approvals
UNION ALL SELECT 'pr_approval_workflows', COUNT(*) FROM pr_approval_workflows
UNION ALL SELECT 'pr_approval_steps', COUNT(*) FROM pr_approval_steps
UNION ALL SELECT 'po_risk_assessments', COUNT(*) FROM po_risk_assessments;
