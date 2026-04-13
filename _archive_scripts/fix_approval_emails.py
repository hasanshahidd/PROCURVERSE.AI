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
print("FIXING IT APPROVAL CHAIN EMAILS")
print("="*80)

# Update Level 1: IT Manager
cur.execute("""
    UPDATE approval_chains 
    SET approver_name = 'Mike Manager', 
        approver_email = 'mike.manager@company.com'
    WHERE department = 'IT' AND approval_level = 1
""")
print("✅ Level 1: Updated to Mike Manager (mike.manager@company.com)")

# Update Level 2: IT Director
cur.execute("""
    UPDATE approval_chains 
    SET approver_name = 'Diana Director', 
        approver_email = 'diana.director@company.com'
    WHERE department = 'IT' AND approval_level = 2
""")
print("✅ Level 2: Updated to Diana Director (diana.director@company.com)")

# Update Level 3: CTO -> VP
cur.execute("""
    UPDATE approval_chains 
    SET approver_name = 'Victor VP', 
        approver_email = 'victor.vp@company.com'
    WHERE department = 'IT' AND approval_level = 3
""")
print("✅ Level 3: Updated to Victor VP (victor.vp@company.com)")

# Commit changes
conn.commit()
print("\n✅✅✅ COMMIT SUCCESSFUL - All approval chain emails fixed!")

# Verify the changes
cur.execute("""
    SELECT approval_level, approver_name, approver_email 
    FROM approval_chains 
    WHERE department = 'IT' 
    ORDER BY approval_level
""")
rows = cur.fetchall()

print("\n" + "="*80)
print("UPDATED IT APPROVAL CHAIN")
print("="*80)
for row in rows:
    print(f"Level {row[0]}: {row[1]} ({row[2]})")

print("\n" + "="*80)
print("⚠️ NOTE: Existing PRs (PR-2026-0303125418, etc.) still have OLD emails")
print("         New PRs will use the CORRECT emails")
print("         To test: Create a NEW PR and check 'My Approvals'")
print("="*80)

conn.close()
