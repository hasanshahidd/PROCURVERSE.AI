import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Connect to database
db_url = os.getenv('DATABASE_URL') or "postgresql://postgres:postgres@localhost:5433/odoo_procurement_demo"
print(f"Connecting to: {db_url.split('@')[1] if '@' in db_url else db_url}")
conn = psycopg2.connect(db_url)
cur = conn.cursor(cursor_factory=RealDictCursor)

# Check IT approval chain
print("\n" + "="*80)
print("IT APPROVAL CHAIN CONFIGURATION")
print("="*80)
cur.execute("""
    SELECT id, department, budget_threshold, approval_level, approver_name, approver_email 
    FROM approval_chains 
    WHERE department = 'IT' 
    ORDER BY approval_level
""")
it_rows = cur.fetchall()
for row in it_rows:
    print(f"Level {row['approval_level']}: {row['approver_name']} ({row['approver_email']}) - Threshold: ${row['budget_threshold']:,.0f}")

# Check latest PR approval steps
print("\n" + "="*80)
print("LATEST PR APPROVAL STEPS (PR-2026-0303125418)")
print("="*80)
cur.execute("""
    SELECT pr_number, approval_level, approver_name, approver_email, status
    FROM pr_approval_steps 
    WHERE pr_number = 'PR-2026-0303125418'
    ORDER BY approval_level
""")
pr_rows = cur.fetchall()
if pr_rows:
    for row in pr_rows:
        print(f"Level {row['approval_level']}: {row['approver_name']} ({row['approver_email']}) - Status: {row['status']}")
else:
    print("❌ NO APPROVAL STEPS FOUND FOR THIS PR!")

# Check all recent approval steps
print("\n" + "="*80)
print("ALL RECENT APPROVAL STEPS (Last 5 PRs)")
print("="*80)
cur.execute("""
    SELECT pr_number, approval_level, approver_email, status
    FROM pr_approval_steps 
    WHERE pr_number LIKE 'PR-2026%'
    ORDER BY pr_number DESC, approval_level
    LIMIT 15
""")
all_rows = cur.fetchall()
if all_rows:
    for row in all_rows:
        print(f"{row['pr_number']} - Level {row['approval_level']}: {row['approver_email']} ({row['status']})")
else:
    print("❌ NO APPROVAL STEPS FOUND!")

conn.close()

print("\n" + "="*80)
print("EXPECTED FRONTEND USER EMAILS")
print("="*80)
print("mike.manager@company.com")
print("diana.director@company.com")
print("victor.vp@company.com")
print("="*80)
