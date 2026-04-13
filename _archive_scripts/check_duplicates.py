import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL') or 'postgresql://postgres:postgres@localhost:5433/odoo_procurement_demo')
cur = conn.cursor(cursor_factory=RealDictCursor)

print("\n" + "="*80)
print("MIKE MANAGER APPROVAL ITEMS (mike.manager@company.com)")
print("="*80)

cur.execute("""
    SELECT pr_number, approval_level, approver_email, status, id
    FROM pr_approval_steps 
    WHERE approver_email = 'mike.manager@company.com' 
    ORDER BY pr_number DESC, approval_level
""")
rows = cur.fetchall()

for r in rows:
    print(f"ID: {r['id']:4d} | {r['pr_number']:20s} | Level {r['approval_level']} | {r['status']:10s}")

print(f"\nTotal: {len(rows)} entries")

# Check for duplicates
print("\n" + "="*80)
print("DUPLICATE PR CHECK")
print("="*80)

cur.execute("""
    SELECT pr_number, approval_level, COUNT(*) as count
    FROM pr_approval_steps 
    WHERE approver_email = 'mike.manager@company.com'
    GROUP BY pr_number, approval_level
    HAVING COUNT(*) > 1
    ORDER BY pr_number DESC
""")
duplicates = cur.fetchall()

if duplicates:
    print("⚠️ FOUND DUPLICATES:")
    for d in duplicates:
        print(f"  {d['pr_number']} - Level {d['approval_level']}: {d['count']} entries")
else:
    print("✅ No duplicates found")

# Check all recent workflows
print("\n" + "="*80)
print("RECENT PR WORKFLOWS")
print("="*80)

cur.execute("""
    SELECT pr_number, department, total_amount, current_approval_level, workflow_status
    FROM pr_approval_workflows
    WHERE pr_number LIKE 'PR-2026%'
    ORDER BY pr_number DESC
    LIMIT 10
""")
workflows = cur.fetchall()

for w in workflows:
    print(f"{w['pr_number']:20s} | {w['department']:10s} | ${w['total_amount']:10,.0f} | Level {w['current_approval_level']} | {w['workflow_status']}")

conn.close()
print("="*80)
