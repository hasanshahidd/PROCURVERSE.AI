import os, psycopg2
from psycopg2.extras import RealDictCursor
import json
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL') or 'postgresql://postgres:postgres@localhost:5433/odoo_procurement_demo')
cur = conn.cursor(cursor_factory=RealDictCursor)

# Get IT approval chain
cur.execute("""
    SELECT approval_level, approver_name, approver_email, budget_threshold 
    FROM approval_chains 
    WHERE department='IT' AND status='approved'
    ORDER BY approval_level
""")
it_approvers = cur.fetchall()

print("=== IT Department Approvers ===")
print(json.dumps(it_approvers, indent=2, default=str))

# Get all departments
cur.execute("""
    SELECT department, approval_level, approver_name, budget_threshold 
    FROM approval_chains 
    WHERE status='approved'
    ORDER BY department, approval_level
""")
all_approvers = cur.fetchall()

print("\n=== All Department Approvers ===")
for row in all_approvers:
    print(f"{row['department']:15} Level {row['approval_level']}: {row['approver_name']:25} (${row['budget_threshold']:,})")

cur.close()
conn.close()
