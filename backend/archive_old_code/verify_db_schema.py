"""
Database Schema Verification Script

Run this before starting the system to ensure all tables have correct columns.
Prevents runtime errors like "column does not exist"
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

# Expected schema for agentic tables
EXPECTED_SCHEMAS = {
    "approval_chains": [
        "id", "pr_number", "department", "budget_threshold", "approval_level",
        "approver_email", "approver_name", "status", "approved_at", 
        "rejection_reason", "created_at", "updated_at"
    ],
    "budget_tracking": [
        "id", "department", "budget_category", "fiscal_year", "allocated_budget",
        "spent_budget", "committed_budget", "available_budget", 
        "alert_threshold_80", "alert_threshold_90", "alert_threshold_95",
        "last_updated", "created_at"
    ],
    "agent_actions": [
        "id", "agent_name", "action_type", "input_data", "output_data",
        "success", "error_message", "execution_time_ms", "created_at"
    ],
    "agent_decisions": [
        "id", "agent_name", "decision_context", "decision_made", "reasoning",
        "confidence_score", "alternatives", "human_override", "outcome", "created_at"
    ]
}

def verify_table_schema(cursor, table_name, expected_columns):
    """Verify a table has all expected columns"""
    print(f"\n{'='*60}")
    print(f"Verifying table: {table_name}")
    print(f"{'='*60}")
    
    # Check if table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = %s
        );
    """, (table_name,))
    
    table_exists = cursor.fetchone()[0]
    
    if not table_exists:
        print(f"❌ CRITICAL: Table '{table_name}' does NOT exist!")
        print(f"   → Run: python backend/migrations/create_agent_tables.py")
        return False
    
    print(f"✅ Table exists")
    
    # Get actual columns
    cursor.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' 
        AND table_name = %s
        ORDER BY ordinal_position;
    """, (table_name,))
    
    actual_columns = {row[0]: {"type": row[1], "nullable": row[2]} for row in cursor.fetchall()}
    
    print(f"\nExpected {len(expected_columns)} columns, found {len(actual_columns)} columns")
    
    # Check each expected column
    all_good = True
    for col in expected_columns:
        if col in actual_columns:
            col_info = actual_columns[col]
            print(f"  ✅ {col:25s} ({col_info['type']})")
        else:
            print(f"  ❌ {col:25s} MISSING!")
            all_good = False
    
    # Check for extra columns
    extra_cols = set(actual_columns.keys()) - set(expected_columns)
    if extra_cols:
        print(f"\n⚠️  Extra columns found (not in expected schema):")
        for col in extra_cols:
            print(f"  ⚠️  {col}")
    
    # Get row count
    cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
    count = cursor.fetchone()[0]
    print(f"\n📊 Row count: {count}")
    
    return all_good


def verify_all_tables():
    """Verify all agentic tables have correct schemas"""
    print("="*60)
    print("DATABASE SCHEMA VERIFICATION")
    print("="*60)
    
    if not DATABASE_URL:
        print("\n❌ CRITICAL: DATABASE_URL not set!")
        print("   → Set in .env file")
        return False
    
    print(f"\n✅ DATABASE_URL configured")
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        all_tables_ok = True
        
        for table_name, expected_cols in EXPECTED_SCHEMAS.items():
            table_ok = verify_table_schema(cursor, table_name, expected_cols)
            if not table_ok:
                all_tables_ok = False
        
        cursor.close()
        conn.close()
        
        print("\n" + "="*60)
        if all_tables_ok:
            print("✅ ALL TABLES VERIFIED - NO SCHEMA ISSUES")
            print("="*60)
            print("\n🚀 Safe to start the system!")
        else:
            print("❌ SCHEMA ISSUES DETECTED")
            print("="*60)
            print("\n⚠️  Fix required before starting!")
            print("   Run: python backend/migrations/create_agent_tables.py")
        print()
        
        return all_tables_ok
        
    except psycopg2.OperationalError as e:
        print(f"\n❌ CRITICAL: Cannot connect to database!")
        print(f"   Error: {str(e)}")
        print(f"   → Check DATABASE_URL in .env")
        return False
    except Exception as e:
        print(f"\n❌ CRITICAL: Verification failed!")
        print(f"   Error: {str(e)}")
        return False


if __name__ == "__main__":
    success = verify_all_tables()
    exit(0 if success else 1)
