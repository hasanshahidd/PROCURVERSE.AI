"""
Database Migration: Create Custom Tables for Agentic Procurement
Sprint 1: Custom approval chains, budget tracking, and agent monitoring
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def create_custom_tables():
    """Create custom tables for agentic procurement system"""
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        print("Creating custom tables for agentic procurement...")
        
        # 1. Approval Chains Configuration
        print("Creating approval_chains table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS approval_chains (
                id SERIAL PRIMARY KEY,
                pr_number VARCHAR(20),
                department VARCHAR(50) NOT NULL,
                budget_threshold DECIMAL(15,2) NOT NULL,
                approval_level INTEGER NOT NULL,  -- 1=Manager, 2=Director, 3=VP
                approver_email VARCHAR(255) NOT NULL,
                approver_name VARCHAR(255) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',  -- pending, approved, rejected
                approved_at TIMESTAMP,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT check_approval_level CHECK (approval_level BETWEEN 1 AND 3),
                CONSTRAINT check_status CHECK (status IN ('pending', 'approved', 'rejected', 'escalated'))
            );
        """)
        
        # 2. Budget Tracking and Alerts
        print("Creating budget_tracking table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS budget_tracking (
                id SERIAL PRIMARY KEY,
                department VARCHAR(50) NOT NULL,
                fiscal_year INTEGER NOT NULL,
                budget_category VARCHAR(20) NOT NULL,  -- CAPEX, OPEX
                allocated_budget DECIMAL(15,2) NOT NULL,
                spent_budget DECIMAL(15,2) DEFAULT 0,
                committed_budget DECIMAL(15,2) DEFAULT 0,  -- Approved but not yet spent
                available_budget DECIMAL(15,2) GENERATED ALWAYS AS 
                    (allocated_budget - spent_budget - committed_budget) STORED,
                last_updated TIMESTAMP DEFAULT NOW(),
                alert_threshold_80 BOOLEAN DEFAULT FALSE,
                alert_threshold_90 BOOLEAN DEFAULT FALSE,
                alert_threshold_95 BOOLEAN DEFAULT FALSE,
                CONSTRAINT check_budget_category CHECK (budget_category IN ('CAPEX', 'OPEX')),
                CONSTRAINT unique_dept_year_category UNIQUE (department, fiscal_year, budget_category)
            );
        """)
        
        # 3. Agent Action Logs (for monitoring and debugging)
        print("Creating agent_actions table...")
        cur.execute("""
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
        """)
        
        # 4. Agent Decision History (for learning and improvement)
        print("Creating agent_decisions table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id SERIAL PRIMARY KEY,
                agent_name VARCHAR(100) NOT NULL,
                decision_context JSONB NOT NULL,  -- Input data that led to decision
                decision_made VARCHAR(255) NOT NULL,
                reasoning TEXT,
                confidence_score DECIMAL(3,2) NOT NULL,  -- 0.00 to 1.00
                alternatives JSONB,  -- Alternative actions considered
                human_override BOOLEAN DEFAULT FALSE,
                override_reason TEXT,
                outcome VARCHAR(50),  -- success, failure, partial, escalated
                created_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT check_confidence CHECK (confidence_score BETWEEN 0 AND 1)
            );
        """)
        
        # Create indexes for performance
        print("Creating indexes...")
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_approval_chains_pr 
            ON approval_chains(pr_number);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_approval_chains_status 
            ON approval_chains(status);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_approval_chains_dept 
            ON approval_chains(department, approval_level);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_budget_tracking_dept 
            ON budget_tracking(department, fiscal_year);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_actions_agent 
            ON agent_actions(agent_name, created_at DESC);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_actions_success 
            ON agent_actions(success, created_at DESC);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent 
            ON agent_decisions(agent_name, created_at DESC);
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_decisions_confidence 
            ON agent_decisions(confidence_score);
        """)
        
        # Check if approval chains already exist
        print("Seeding initial approval chains...")
        cur.execute("SELECT COUNT(*) FROM approval_chains;")
        existing_count = cur.fetchone()[0]
        
        if existing_count == 0:
            cur.execute("""
                INSERT INTO approval_chains 
                (department, budget_threshold, approval_level, approver_email, approver_name, status)
                VALUES 
                -- IT Department
                ('IT', 10000, 1, 'it.manager@company.com', 'IT Manager', 'approved'),
                ('IT', 50000, 2, 'it.director@company.com', 'IT Director', 'approved'),
                ('IT', 100000, 3, 'cto@company.com', 'CTO', 'approved'),
                
                -- Finance Department
                ('Finance', 10000, 1, 'finance.manager@company.com', 'Finance Manager', 'approved'),
                ('Finance', 50000, 2, 'finance.director@company.com', 'Finance Director', 'approved'),
                ('Finance', 100000, 3, 'cfo@company.com', 'CFO', 'approved'),
                
                -- Operations Department
                ('Operations', 10000, 1, 'ops.manager@company.com', 'Operations Manager', 'approved'),
                ('Operations', 50000, 2, 'ops.director@company.com', 'Operations Director', 'approved'),
                ('Operations', 100000, 3, 'coo@company.com', 'COO', 'approved'),
                
                -- Procurement Department
                ('Procurement', 10000, 1, 'procurement.manager@company.com', 'Procurement Manager', 'approved'),
                ('Procurement', 50000, 2, 'procurement.director@company.com', 'Procurement Director', 'approved'),
                ('Procurement', 100000, 3, 'cpo@company.com', 'CPO', 'approved');
            """)
        else:
            print(f"   Skipping - {existing_count} approval chains already exist")
        
        # Check if budget data already exists
        print("Seeding initial budget data...")
        cur.execute("SELECT COUNT(*) FROM budget_tracking;")
        budget_count = cur.fetchone()[0]
        
        if budget_count == 0:
            cur.execute("""
                INSERT INTO budget_tracking 
                (department, fiscal_year, budget_category, allocated_budget, spent_budget, committed_budget)
                VALUES 
                -- IT Department
                ('IT', 2026, 'CAPEX', 5000000, 1200000, 800000),
                ('IT', 2026, 'OPEX', 3000000, 800000, 500000),
                
                -- Finance Department
                ('Finance', 2026, 'CAPEX', 1000000, 200000, 150000),
                ('Finance', 2026, 'OPEX', 2000000, 600000, 300000),
                
                -- Operations Department
                ('Operations', 2026, 'CAPEX', 8000000, 3000000, 2000000),
                ('Operations', 2026, 'OPEX', 5000000, 1500000, 1000000),
                
                -- Procurement Department
                ('Procurement', 2026, 'CAPEX', 500000, 100000, 50000),
                ('Procurement', 2026, 'OPEX', 1000000, 300000, 200000);
            """)
        else:
            print(f"   Skipping - {budget_count} budget records already exist")
        
        conn.commit()
        print("\n✅ All custom tables created successfully!")
        print("\n📊 Tables created:")
        print("   1. approval_chains - Multi-level approval routing")
        print("   2. budget_tracking - Real-time budget monitoring")
        print("   3. agent_actions - Agent action audit trail")
        print("   4. agent_decisions - Agent learning history")
        print("\n🔍 Indexes created for optimal performance")
        print("🌱 Seeded with initial approval chains and budget data")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error creating tables: {str(e)}")
        raise
    
    finally:
        cur.close()
        conn.close()


def verify_tables():
    """Verify tables were created successfully"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        tables = [
            'approval_chains',
            'budget_tracking',
            'agent_actions',
            'agent_decisions'
        ]
        
        print("\n🔍 Verifying tables...")
        for table in tables:
            cur.execute(f"""
                SELECT COUNT(*) FROM {table};
            """)
            count = cur.fetchone()[0]
            print(f"   ✓ {table}: {count} records")
        
        print("\n✅ All tables verified!")
        
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    print("="*60)
    print("AGENTIC PROCUREMENT - DATABASE MIGRATION")
    print("Sprint 1: Custom Tables for Approval & Budget Tracking")
    print("="*60)
    print()
    
    create_custom_tables()
    verify_tables()
    
    print("\n" + "="*60)
    print("Migration complete! Ready for agent implementation.")
    print("="*60)
