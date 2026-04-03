"""
Add odoo_po_id column to pr_approval_workflows table
This tracks which Odoo PO was created from each approved PR
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def add_odoo_po_id_column():
    """Add odoo_po_id to track PR → PO linkage"""
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        print("=" * 80)
        print("🔧 ADDING odoo_po_id COLUMN TO pr_approval_workflows")
        print("=" * 80)
        
        # Check if column already exists
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'pr_approval_workflows' 
              AND column_name = 'odoo_po_id'
        """)
        
        if cur.fetchone():
            print("ℹ️  Column odoo_po_id already exists - skipping")
            return
        
        # Add odoo_po_id column
        print("📝 Adding odoo_po_id column (nullable integer)...")
        cur.execute("""
            ALTER TABLE pr_approval_workflows 
            ADD COLUMN odoo_po_id INTEGER
        """)
        
        # Add index for quick lookups
        print("🔍 Creating index on odoo_po_id...")
        cur.execute("""
            CREATE INDEX idx_workflow_odoo_po 
            ON pr_approval_workflows(odoo_po_id)
        """)
        
        conn.commit()
        
        print("✅ Column added successfully!")
        print("   - odoo_po_id: INTEGER (nullable)")
        print("   - Index: idx_workflow_odoo_po")
        print("=" * 80)
        print("✅ MIGRATION COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {str(e)}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    add_odoo_po_id_column()
