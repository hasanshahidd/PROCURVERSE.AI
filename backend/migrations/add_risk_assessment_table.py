"""
Database Migration: Add Risk Assessment Table
Week 1 Day 3-4: Store risk assessment data for purchase orders

Table Links: Odoo PO ID → Risk Scores
Architecture: Custom table stores agent intelligence, Odoo stores business data
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def add_risk_assessment_table():
    """Create po_risk_assessments table for storing risk analysis"""
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        print("="*70)
        print("WEEK 1 DAY 3-4: Risk Assessment Table Migration")
        print("="*70)
        print()
        print("Creating po_risk_assessments table...")
        
        # Create risk assessment table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS po_risk_assessments (
                id SERIAL PRIMARY KEY,
                
                -- Link to Odoo PO (foreign key reference, not enforced)
                odoo_po_id INTEGER,  -- NULL if risk assessed before PO creation
                pr_number VARCHAR(50),  -- Always have PR number
                
                -- Risk Scores (0-100, higher = more risk)
                total_risk_score DECIMAL(5,2) NOT NULL,  -- Weighted total
                vendor_risk_score DECIMAL(5,2) NOT NULL,
                financial_risk_score DECIMAL(5,2) NOT NULL,
                compliance_risk_score DECIMAL(5,2) NOT NULL,
                operational_risk_score DECIMAL(5,2) NOT NULL,
                
                -- Risk Level Classification
                risk_level VARCHAR(20) NOT NULL,  -- LOW, MEDIUM, HIGH, CRITICAL
                
                -- Detailed Analysis (JSONB for flexibility)
                risk_breakdown JSONB NOT NULL,  -- Full 4-dimension analysis
                mitigation_recommendations JSONB,  -- List of recommended actions
                concerns_identified JSONB,  -- List of concerns per dimension
                
                -- Decision Tracking
                recommended_action VARCHAR(100),  -- approve_low_risk, require_manager_review, etc.
                decision_confidence DECIMAL(3,2),  -- 0.00 to 1.00
                blocked_po_creation BOOLEAN DEFAULT FALSE,  -- TRUE if CRITICAL risk
                
                -- Vendor Context
                vendor_name VARCHAR(255),
                vendor_id INTEGER,
                
                -- Purchase Context
                budget_amount DECIMAL(15,2),
                department VARCHAR(100),
                category VARCHAR(100),
                urgency VARCHAR(20),
                
                -- Timestamps
                assessed_at TIMESTAMP DEFAULT NOW(),
                assessed_by VARCHAR(100) DEFAULT 'RiskAssessmentAgent',
                
                -- Outcome Tracking (for learning)
                actual_outcome VARCHAR(50),  -- success, issue_occurred, escalated
                outcome_notes TEXT,
                outcome_updated_at TIMESTAMP,
                
                -- Constraints
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
        """)
        print("   ✅ Table structure created")
        
        # Create indexes for fast lookups
        print("Creating indexes...")
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_assessments_po 
            ON po_risk_assessments(odoo_po_id);
        """)
        print("   ✅ Index on odoo_po_id")
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_assessments_pr 
            ON po_risk_assessments(pr_number);
        """)
        print("   ✅ Index on pr_number")
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_assessments_level 
            ON po_risk_assessments(risk_level, assessed_at DESC);
        """)
        print("   ✅ Index on risk_level + assessed_at")
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_assessments_vendor 
            ON po_risk_assessments(vendor_name, assessed_at DESC);
        """)
        print("   ✅ Index on vendor_name")
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_assessments_blocked 
            ON po_risk_assessments(blocked_po_creation, assessed_at DESC);
        """)
        print("   ✅ Index on blocked_po_creation")
        
        conn.commit()
        
        print("\n✅ Risk assessment table created successfully!")
        print("\n📊 Table Details:")
        print("   • Table: po_risk_assessments")
        print("   • Purpose: Store agent risk analysis for purchase orders")
        print("   • Link: odoo_po_id references Odoo purchase.order")
        print("   • Scores: 4 dimensions (vendor, financial, compliance, operational)")
        print("   • Levels: LOW, MEDIUM, HIGH, CRITICAL")
        print("   • Features: JSONB for flexible data, outcome tracking for learning")
        print("\n🔗 Integration:")
        print("   • Agents READ from Odoo (vendors, POs, budgets)")
        print("   • Agents CALCULATE risk scores")
        print("   • Agents WRITE risk data to this table")
        print("   • CRITICAL risks block PO creation in Odoo")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error creating risk assessment table: {str(e)}")
        raise
    
    finally:
        cur.close()
        conn.close()


def verify_risk_table():
    """Verify risk assessment table was created"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        print("\n🔍 Verifying risk assessment table...")
        
        # Check table exists
        cur.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_name = 'po_risk_assessments';
        """)
        table_exists = cur.fetchone()[0]
        
        if table_exists:
            print("   ✓ Table exists")
            
            # Check columns
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'po_risk_assessments'
                ORDER BY ordinal_position;
            """)
            columns = cur.fetchall()
            print(f"   ✓ {len(columns)} columns defined")
            
            # Check indexes
            cur.execute("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'po_risk_assessments';
            """)
            indexes = cur.fetchall()
            print(f"   ✓ {len(indexes)} indexes created")
            
            # Check current records
            cur.execute("SELECT COUNT(*) FROM po_risk_assessments;")
            count = cur.fetchone()[0]
            print(f"   ✓ Current records: {count}")
            
            print("\n✅ Risk assessment table verified!")
        else:
            print("   ❌ Table not found!")
            
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    print("\n🚀 Starting risk assessment table migration...\n")
    
    add_risk_assessment_table()
    verify_risk_table()
    
    print("\n" + "="*70)
    print("✅ Migration Complete - Ready for RiskAssessmentAgent Integration!")
    print("="*70)
    print("\nNext Steps:")
    print("  1. Create LangChain tool to write risk data")
    print("  2. Update RiskAssessmentAgent to use tool")
    print("  3. Test with 4 scenarios (LOW/MEDIUM/HIGH/CRITICAL)")
    print("  4. Verify CRITICAL risks block PO creation")
    print()
