import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# Check pr_approval_workflows schema
cur.execute("""
    SELECT column_name, data_type, character_maximum_length 
    FROM information_schema.columns 
    WHERE table_name = 'pr_approval_workflows' 
    ORDER BY ordinal_position
""")

print("=" * 60)
print("pr_approval_workflows TABLE SCHEMA")
print("=" * 60)
for row in cur.fetchall():
    col_name, data_type, max_len = row
    if max_len:
        print(f"  {col_name}: {data_type}({max_len})")
    else:
        print(f"  {col_name}: {data_type}")

cur.close()
conn.close()
