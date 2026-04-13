"""
Quick script to verify risk assessments stored in database
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor(cursor_factory=RealDictCursor)

print("\nRISK ASSESSMENTS IN DATABASE")
print("="*80)

cur.execute("""
    SELECT id, pr_number, total_risk_score, risk_level, blocked_po_creation, 
           vendor_name, budget_amount, assessed_at
    FROM po_risk_assessments
    ORDER BY id DESC
    LIMIT 10
""")

records = cur.fetchall()

for record in records:
    print(f"\n#{record['id']}: {record['pr_number']}")
    print(f"  Vendor: {record['vendor_name']}")
    print(f"  Budget: ${record['budget_amount']:,.0f}")
    print(f"  Risk Score: {record['total_risk_score']:.1f}/100")
    print(f"  Risk Level: {record['risk_level']}")
    print(f"  PO Blocked: {record['blocked_po_creation']}")
    print(f"  Assessed: {record['assessed_at']}")

print(f"\nTotal: {len(records)} risk assessments found")
print("="*80)

cur.close()
conn.close()
