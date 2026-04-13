"""
Fix budget_tracking schema - Add missing created_at column
Run this script to add the created_at column to budget_tracking table
"""

import psycopg2
import os
from dotenv import load_dotenv

def fix_schema():
    # Load environment variables
    load_dotenv()
    db_url = os.getenv('DATABASE_URL')
    
    if not db_url:
        print("DATABASE_URL not found in environment")
        return False
    
    try:
        # Connect to database
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        print("\nFixing budget_tracking schema...")
        print("=" * 60)
        
        # Check if column already exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'budget_tracking' 
            AND column_name = 'created_at'
        """)
        
        if cursor.fetchone():
            print("Column 'created_at' already exists - no action needed")
            cursor.close()
            conn.close()
            return True
        
        # Add the missing column
        print("\nAdding 'created_at' column to budget_tracking...")
        cursor.execute("""
            ALTER TABLE budget_tracking 
            ADD COLUMN created_at TIMESTAMP DEFAULT NOW()
        """)
        
        # Update existing rows with current timestamp
        cursor.execute("""
            UPDATE budget_tracking 
            SET created_at = NOW() 
            WHERE created_at IS NULL
        """)
        
        conn.commit()
        
        # Verify the fix
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'budget_tracking' 
            ORDER BY ordinal_position
        """)
        
        columns = [row[0] for row in cursor.fetchall()]
        
        print(f"\nSuccessfully added 'created_at' column")
        print(f"\nbudget_tracking now has {len(columns)} columns:")
        for col in columns:
            print(f"   - {col}")
        
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 60)
        print("Schema fix completed successfully!")
        print("   Run verify_db_schema.py to confirm all tables are correct")
        
        return True
        
    except Exception as e:
        print(f"\nError fixing schema: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    success = fix_schema()
    exit(0 if success else 1)
