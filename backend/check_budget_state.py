import psycopg2
from decimal import Decimal

conn = psycopg2.connect('postgresql://postgres:YourStr0ng!Pass@localhost:5433/odoo_procurement_demo')
cur = conn.cursor()

print("=" * 60)
print("BUDGET TRACKING - CURRENT STATE")
print("=" * 60)

# Check IT budget
cur.execute("""
    SELECT department, budget_category, allocated_budget, 
           spent_budget, committed_budget, available_budget
    FROM budget_tracking 
    WHERE department='IT' AND fiscal_year=2026
    ORDER BY budget_category
""")
it_budget = cur.fetchall()

print("\n🔍 IT Department (FY 2026):")
for row in it_budget:
    dept, category, allocated, spent, committed, available = row
    print(f"\n  {category}:")
    print(f"    Allocated:  ${allocated:>12,.2f}")
    print(f"    Spent:      ${spent:>12,.2f}")
    print(f"    Committed:  ${committed:>12,.2f}")
    print(f"    Available:  ${available:>12,.2f}")
    utilization = ((spent + committed) / allocated * 100) if allocated > 0 else 0
    print(f"    Utilization: {utilization:>11.1f}%")

# Check Finance budget
cur.execute("""
    SELECT department, budget_category, allocated_budget, 
           spent_budget, committed_budget, available_budget
    FROM budget_tracking 
    WHERE department='Finance' AND fiscal_year=2026
    ORDER BY budget_category
""")
finance_budget = cur.fetchall()

print("\n\n🔍 Finance Department (FY 2026):")
for row in finance_budget:
    dept, category, allocated, spent, committed, available = row
    print(f"\n  {category}:")
    print(f"    Allocated:  ${allocated:>12,.2f}")
    print(f"    Spent:      ${spent:>12,.2f}")
    print(f"    Committed:  ${committed:>12,.2f}")
    print(f"    Available:  ${available:>12,.2f}")
    utilization = ((spent + committed) / allocated * 100) if allocated > 0 else 0
    print(f"    Utilization: {utilization:>11.1f}%")

print("\n" + "=" * 60)
print("\n❓ EXPECTED vs ACTUAL:")
print("\nTest 1: Verify IT $30K CAPEX")
print("  Expected committed: $800,000 + $30,000 = $830,000")
print(f"  Actual committed:   ${it_budget[0][4]:,.2f}")  # CAPEX is first row
if it_budget[0][4] == Decimal('830000.00'):
    print("  ✅ MATCH - Budget persisted correctly")
elif it_budget[0][4] == Decimal('800000.00'):
    print("  ❌ NO CHANGE - Budget update didn't persist!")
else:
    print(f"  ⚠️  UNEXPECTED VALUE")

print("\nTest 3: Route Finance $55K (should also verify budget)")
print("  Expected: Finance budget should reflect some change")
print(f"  Finance CAPEX committed: ${finance_budget[0][4]:,.2f}")
print(f"  Finance OPEX committed:  ${finance_budget[1][4]:,.2f}")

cur.close()
conn.close()
