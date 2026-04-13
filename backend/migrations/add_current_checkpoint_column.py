"""
Database Migration: Add current_checkpoint column to execution_sessions (HF-4 / R17)

R17 — Partial completion states. A handler can mark sub-step progress with a
checkpoint name so that retry from the checkpoint re-runs only the part *after*
the checkpoint, not the entire phase. The column is NULL until a handler emits
phase_checkpointed.

This is a P1.5 hardening migration. Idempotent: safe to run multiple times.

Usage:
  python -m backend.migrations.add_current_checkpoint_column

Revert:
  ALTER TABLE execution_sessions DROP COLUMN IF EXISTS current_checkpoint;
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def add_current_checkpoint_column():
    """Add current_checkpoint TEXT NULL column to execution_sessions."""

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        print("Adding current_checkpoint column to execution_sessions...")
        cur.execute("""
            ALTER TABLE execution_sessions
            ADD COLUMN IF NOT EXISTS current_checkpoint TEXT;
        """)
        conn.commit()
        print("  - current_checkpoint column added (or already present)")

        # Verify the column exists
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'execution_sessions'
              AND column_name = 'current_checkpoint';
        """)
        row = cur.fetchone()
        if row:
            print(f"  verified: {row[0]} {row[1]} nullable={row[2]}")
        else:
            print("  WARNING: column not found after ALTER")

    except Exception as e:
        conn.rollback()
        print(f"ERROR adding current_checkpoint column: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    add_current_checkpoint_column()
