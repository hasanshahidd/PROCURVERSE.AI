"""
Database Migration: Create Approval System Tables
Sprint 2: Human-in-the-loop approval UI for low-confidence decisions and multi-level workflows
"""

import psycopg2
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def create_approval_system_tables():
    """Create 3 tables for approval system UI"""
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        print("🚀 Creating approval system tables...")
        
        # 1. Pending Approvals (Low-Confidence Decisions)
        print("📋 Creating pending_approvals table...")
        cur.execute("""
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
        """)
        
        # Create indexes for pending_approvals
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_status 
            ON pending_approvals(status);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_agent 
            ON pending_approvals(agent_name);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_created 
            ON pending_approvals(created_at DESC);
        """)
        
        # 2. PR Approval Workflows (Multi-Level Approval Tracking)
        print("🔀 Creating pr_approval_workflows table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pr_approval_workflows (
                pr_number TEXT PRIMARY KEY,
                department TEXT NOT NULL CHECK (department IN ('IT', 'Finance', 'Operations', 'Procurement')),
                total_amount DECIMAL(15,2) NOT NULL,
                requester_name TEXT NOT NULL,
                request_data JSONB DEFAULT '{}'::jsonb,
                current_approval_level INT DEFAULT 1,
                workflow_status TEXT DEFAULT 'in_progress' CHECK (workflow_status IN ('in_progress', 'completed', 'rejected')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create indexes for pr_approval_workflows
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_workflow_status 
            ON pr_approval_workflows(workflow_status);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_workflow_dept 
            ON pr_approval_workflows(department);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_workflow_created 
            ON pr_approval_workflows(created_at DESC);
        """)
        
        # 3. PR Approval Steps (Individual Steps in Approval Chain)
        print("📝 Creating pr_approval_steps table...")
        cur.execute("""
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
        """)
        
        # Create indexes for pr_approval_steps
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_steps_pr 
            ON pr_approval_steps(pr_number);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_steps_approver 
            ON pr_approval_steps(approver_email);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_steps_status 
            ON pr_approval_steps(status);
        """)
        
        conn.commit()
        print("✅ Tables created successfully!")
        
        # Insert seed data
        print("\n🌱 Inserting seed data...")
        
        # Seed pending approvals
        print("   - Pending approvals (2 items)...")
        cur.execute("""
            INSERT INTO pending_approvals (approval_id, agent_name, request_type, request_data, recommendation, confidence_score, reasoning, status)
            VALUES 
            ('APR-2026-0001', 'VendorSelectionAgent', 'vendor_selection', 
             '{"category": "Electronics", "budget": 50000, "required_by": "2026-03-15"}'::jsonb, 
             '{"vendor_id": 14, "vendor_name": "Gemini Furniture", "score": 69, "quality": 65, "price": 70, "delivery": 75, "category_match": 60}'::jsonb,
             0.55, 
             'Multiple vendors scored similarly. Quality scores: Gemini Furniture (65), Deco Addict (70), Azure Interior (68). Price is competitive but not the lowest. Recommend human review for strategic vendor selection.', 
             'pending'),
            ('APR-2026-0002', 'BudgetVerificationAgent', 'budget_check', 
             '{"department": "IT", "budget": 75000, "budget_category": "CAPEX", "fiscal_year": 2026}'::jsonb, 
             '{"approved": true, "available_budget": 80000, "utilization_rate": 0.94, "threshold_alert": "95%"}'::jsonb,
             0.58, 
             'Budget availability confirmed but very close to 95% threshold. Remaining budget: $5,000. This purchase would push utilization to 99%. Recommend human review for budget allocation strategy.', 
             'pending')
            ON CONFLICT (approval_id) DO NOTHING;
        """)
        
        # Seed PR workflows
        print("   - PR approval workflows (3 workflows)...")
        now = datetime.now()
        cur.execute("""
            INSERT INTO pr_approval_workflows (pr_number, department, total_amount, requester_name, current_approval_level, workflow_status, created_at)
            VALUES 
            ('PR-2026-0001', 'IT', 45000, 'Alice Johnson', 2, 'in_progress', %s),
            ('PR-2026-0002', 'Finance', 120000, 'Bob Smith', 3, 'in_progress', %s),
            ('PR-2026-0003', 'Operations', 8000, 'Carol White', 1, 'in_progress', %s)
            ON CONFLICT (pr_number) DO NOTHING;
        """, (
            now - timedelta(days=5),
            now - timedelta(days=3),
            now - timedelta(hours=6)
        ))
        
        # Seed PR approval steps
        print("   - PR approval steps (9 steps)...")
        cur.execute("""
            INSERT INTO pr_approval_steps (pr_number, approval_level, approver_name, approver_email, status, approved_at, notes)
            VALUES 
            -- PR-2026-0001 (IT, $45K) - Manager approved, Director pending
            ('PR-2026-0001', 1, 'Mike Manager', 'mike.manager@company.com', 'approved', %s, 'Approved - align with IT roadmap'),
            ('PR-2026-0001', 2, 'Diana Director', 'diana.director@company.com', 'pending', NULL, NULL),
            ('PR-2026-0001', 3, 'Victor VP', 'victor.vp@company.com', 'pending', NULL, NULL),
            
            -- PR-2026-0002 (Finance, $120K) - Manager and Director approved, VP pending
            ('PR-2026-0002', 1, 'Mike Manager', 'mike.manager@company.com', 'approved', %s, 'Looks good from my side'),
            ('PR-2026-0002', 2, 'Diana Director', 'diana.director@company.com', 'approved', %s, 'Approved - within budget'),
            ('PR-2026-0002', 3, 'Victor VP', 'victor.vp@company.com', 'pending', NULL, NULL),
            
            -- PR-2026-0003 (Operations, $8K) - Manager pending (low amount, single level needed)
            ('PR-2026-0003', 1, 'Mike Manager', 'mike.manager@company.com', 'pending', NULL, NULL),
            ('PR-2026-0003', 2, 'Diana Director', 'diana.director@company.com', 'pending', NULL, NULL),
            ('PR-2026-0003', 3, 'Victor VP', 'victor.vp@company.com', 'pending', NULL, NULL)
            ON CONFLICT DO NOTHING;
        """, (
            now - timedelta(days=4, hours=12),
            now - timedelta(days=2, hours=18),
            now - timedelta(days=2, hours=6)
        ))
        
        conn.commit()
        print("✅ Seed data inserted!")
        
        # Print summary
        print("\n📊 Database Summary:")
        cur.execute("SELECT COUNT(*) FROM pending_approvals WHERE status = 'pending'")
        pending_count = cur.fetchone()[0]
        print(f"   ✅ Pending approvals: {pending_count}")
        
        cur.execute("SELECT COUNT(*) FROM pr_approval_workflows WHERE workflow_status = 'in_progress'")
        workflows_count = cur.fetchone()[0]
        print(f"   ✅ Active workflows: {workflows_count}")
        
        cur.execute("SELECT COUNT(*) FROM pr_approval_steps WHERE status = 'pending'")
        steps_count = cur.fetchone()[0]
        print(f"   ✅ Pending approval steps: {steps_count}")
        
        print("\n🎉 Migration Complete!")
        print("\n📝 Next Steps:")
        print("   1. Start backend: cd backend && uvicorn backend.main:app --reload --port 5000")
        print("   2. Start frontend: npm run dev")
        print("   3. Login and navigate to Pending Approvals page")
        print("   4. Badge should show '2' pending items")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error creating tables: {e}")
        raise
        
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_approval_system_tables()
