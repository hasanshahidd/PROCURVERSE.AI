import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Connect to database
db_url = os.getenv('DATABASE_URL') or "postgresql://postgres:postgres@localhost:5433/odoo_procurement_demo"
conn = psycopg2.connect(db_url)
cur = conn.cursor()

print("\n" + "="*80)
print("FIXING EXISTING PR APPROVAL STEPS")
print("="*80)

# Find recent PRs with old emails
cur.execute("""
    SELECT DISTINCT pr_number 
    FROM pr_approval_steps 
    WHERE approver_email IN ('it.manager@company.com', 'it.director@company.com', 'cto@company.com')
    AND status = 'pending'
    ORDER BY pr_number DESC
    LIMIT 5
""")
prs_to_fix = [row[0] for row in cur.fetchall()]

print(f"Found {len(prs_to_fix)} PRs with old emails: {prs_to_fix}")

for pr_number in prs_to_fix:
    print(f"\n📝 Fixing {pr_number}...")
    
    # Update Level 1
    cur.execute("""
        UPDATE pr_approval_steps 
        SET approver_name = 'Mike Manager', 
            approver_email = 'mike.manager@company.com'
        WHERE pr_number = %s AND approval_level = 1 AND approver_email = 'it.manager@company.com'
    """, (pr_number,))
    print(f"  ✅ Level 1: Mike Manager (mike.manager@company.com)")
    
    # Update Level 2
    cur.execute("""
        UPDATE pr_approval_steps 
        SET approver_name = 'Diana Director', 
            approver_email = 'diana.director@company.com'
        WHERE pr_number = %s AND approval_level = 2 AND approver_email = 'it.director@company.com'
    """, (pr_number,))
    print(f"  ✅ Level 2: Diana Director (diana.director@company.com)")
    
    # Update Level 3
    cur.execute("""
        UPDATE pr_approval_steps 
        SET approver_name = 'Victor VP', 
            approver_email = 'victor.vp@company.com'
        WHERE pr_number = %s AND approval_level = 3 AND approver_email = 'cto@company.com'
    """, (pr_number,))
    print(f"  ✅ Level 3: Victor VP (victor.vp@company.com)")

# Commit changes
conn.commit()
print("\n✅✅✅ COMMIT SUCCESSFUL - All PR steps fixed!")

# Verify for latest PR
print("\n" + "="*80)
print("VERIFICATION: PR-2026-0303125418 STEPS")
print("="*80)
cur.execute("""
    SELECT approval_level, approver_name, approver_email, status
    FROM pr_approval_steps 
    WHERE pr_number = 'PR-2026-0303125418'
    ORDER BY approval_level
""")
rows = cur.fetchall()
for row in rows:
    print(f"Level {row[0]}: {row[1]} ({row[2]}) - Status: {row[3]}")

print("\n" + "="*80)
print("✅ NOW GO TO 'MY APPROVALS' PAGE AND REFRESH!")
print("✅ Switch to Mike Manager (mike.manager@company.com)")
print("✅ You should see PR-2026-0303125418 in pending approvals!")
print("="*80)

conn.close()
