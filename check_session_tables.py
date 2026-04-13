"""One-off: verify the 6 session-layer tables exist in the DB."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

EXPECTED = [
    "execution_sessions",
    "session_drift_reports",
    "session_event_outbox",
    "session_events",
    "session_gates",
    "session_snapshots",
]

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute(
    "SELECT tablename FROM pg_tables WHERE tablename = ANY(%s) ORDER BY tablename",
    (EXPECTED,),
)
found = {r[0] for r in cur.fetchall()}
conn.close()

print("Found tables:")
for t in EXPECTED:
    mark = "OK " if t in found else "MISSING"
    print(f"  [{mark}] {t}")

missing = [t for t in EXPECTED if t not in found]
if missing:
    print(f"\n{len(missing)} table(s) still missing — run the matching migration.")
else:
    print("\nAll 6 session-layer tables present.")
