"""Reset budget_tracking rows back to seed values."""
import os
import psycopg2

DATABASE_URL = os.environ["DATABASE_URL"]

SEED = [
    ("IT",          "OPEX",   3_000_000, 800_000,   500_000),
    ("IT",          "CAPEX",  5_000_000, 1_200_000, 800_000),
    ("Finance",     "OPEX",   2_000_000, 600_000,   300_000),
    ("Finance",     "CAPEX",  1_000_000, 200_000,   150_000),
    ("Operations",  "OPEX",   5_000_000, 1_500_000, 1_000_000),
    ("Operations",  "CAPEX",  8_000_000, 3_000_000, 2_000_000),
    ("Procurement", "OPEX",   1_000_000, 300_000,   200_000),
    ("Procurement", "CAPEX",  500_000,   100_000,   50_000),
]

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

for dept, cat, alloc, spent, committed in SEED:
    cur.execute(
        """
        UPDATE budget_tracking
           SET allocated_budget = %s,
               spent_budget     = %s,
               committed_budget = %s,
               last_updated     = NOW()
         WHERE department      = %s
           AND budget_category = %s
           AND fiscal_year     = 2026
        """,
        (alloc, spent, committed, dept, cat),
    )

conn.commit()

# Print the reset table
cur.execute(
    """
    SELECT department, budget_category,
           allocated_budget, spent_budget,
           committed_budget, available_budget
      FROM budget_tracking
     ORDER BY department, budget_category
    """
)
rows = cur.fetchall()

header = f"{'Dept':<15} {'Cat':<8} {'Allocated':>14} {'Spent':>14} {'Committed':>14} {'Available':>14}"
print(header)
print("-" * len(header))
for r in rows:
    print(
        f"{r[0]:<15} {r[1]:<8} "
        f"${int(r[2]):>13,} ${int(r[3]):>13,} ${int(r[4]):>13,} ${int(r[5]):>13,}"
    )

cur.close()
conn.close()
print("\nBudget reset complete.")
