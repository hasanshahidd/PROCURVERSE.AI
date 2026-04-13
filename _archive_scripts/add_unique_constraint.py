import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL') or 'postgresql://postgres:postgres@localhost:5433/odoo_procurement_demo')
cur = conn.cursor()

print("\n" + "="*80)
print("ADDING UNIQUE CONSTRAINT TO PREVENT DUPLICATE APPROVAL STEPS")
print("="*80)

# Check if constraint already exists
cur.execute("""
    SELECT constraint_name 
    FROM information_schema.table_constraints 
    WHERE table_name = 'pr_approval_steps' 
    AND constraint_type = 'UNIQUE'
""")
existing_constraints = [row[0] for row in cur.fetchall()]

print(f"Existing unique constraints: {existing_constraints}")

# Add unique constraint on (pr_number, approver_email, approval_level)
constraint_name = "uq_pr_approver_level"

if constraint_name not in existing_constraints:
    print(f"\n✅ Adding unique constraint '{constraint_name}'...")
    try:
        cur.execute("""
            ALTER TABLE pr_approval_steps 
            ADD CONSTRAINT uq_pr_approver_level 
            UNIQUE (pr_number, approver_email, approval_level)
        """)
        conn.commit()
        print(f"✅ Constraint added successfully!")
        print(f"   This prevents the same approver from having multiple entries")
        print(f"   for the same PR at the same approval level.")
    except Exception as e:
        print(f"❌ Failed to add constraint: {e}")
        print(f"   This might be because duplicates already exist.")
        print(f"   Let's check for existing duplicates...")
        
        conn.rollback()
        
        # Check for duplicates
        cur.execute("""
            SELECT pr_number, approver_email, approval_level, COUNT(*) as count
            FROM pr_approval_steps
            GROUP BY pr_number, approver_email, approval_level
            HAVING COUNT(*) > 1
            ORDER BY count DESC
        """)
        duplicates = cur.fetchall()
        
        if duplicates:
            print(f"\n⚠️ FOUND {len(duplicates)} DUPLICATE ENTRIES:")
            for dup in duplicates:
                print(f"   {dup[0]} | {dup[1]} | Level {dup[2]} | {dup[3]} times")
            
            print(f"\n🔧 REMOVING DUPLICATES (keeping only the oldest entry)...")
            for pr_num, email, level, count in duplicates:
                # Keep oldest, delete rest
                cur.execute("""
                    DELETE FROM pr_approval_steps
                    WHERE id IN (
                        SELECT id FROM pr_approval_steps
                        WHERE pr_number = %s AND approver_email = %s AND approval_level = %s
                        ORDER BY id DESC
                        OFFSET 1
                    )
                """, (pr_num, email, level))
                print(f"   ✅ Removed {count-1} duplicate(s) for {pr_num} / {email} / Level {level}")
            
            conn.commit()
            print(f"\n✅ All duplicates removed")
            
            # Now try adding constraint again
            print(f"\n✅ Trying to add constraint again...")
            cur.execute("""
                ALTER TABLE pr_approval_steps 
                ADD CONSTRAINT uq_pr_approver_level 
                UNIQUE (pr_number, approver_email, approval_level)
            """)
            conn.commit()
            print(f"✅✅✅ Constraint added successfully!")
        else:
            print(f"❌ No duplicates found, but constraint still failed to add")
else:
    print(f"ℹ️ Unique constraint already exists: {constraint_name}")

conn.close()
print("="*80)
print("✅ DUPLICATE PREVENTION SETUP COMPLETE")
print("="*80)
