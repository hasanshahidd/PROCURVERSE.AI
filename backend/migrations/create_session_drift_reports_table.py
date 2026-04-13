"""
Database Migration: Create session_drift_reports table (P1.5 / HF-5 / R18)

Scheduled drift reconciliation job compares the authoritative session_events
state (Layer 1) against the legacy workflow_runs/workflow_tasks state (Layer 2)
during HYBRID mode. Any mismatch is recorded here for operator triage and is
the core measurement behind the P5 gate criterion:

    "zero unresolved drift for 14 consecutive days"

Schema:
  report_id      — UUID PK
  session_id     — FK to execution_sessions (cascade delete)
  detected_at    — when the drift was observed
  session_state  — JSONB snapshot of the folded session state at detect time
  legacy_state   — JSONB snapshot of workflow_runs state at detect time
  resolution     — TEXT (NULL = unresolved, non-null = operator note)
  resolved_by    — UUID/text id of the operator who marked it resolved
  resolved_at    — timestamp of resolution

Usage:
  python -m backend.migrations.create_session_drift_reports_table

Revert:
  DROP TABLE IF EXISTS session_drift_reports CASCADE;
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def create_session_drift_reports_table():
    """Create the drift_reports table + supporting indexes."""

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        print("Creating session_drift_reports table...")

        # ── session_drift_reports ────────────────────────────────────────
        # Append-only log of detected drift between session_events (truth)
        # and legacy workflow_runs (artifact). Read-only from the job's
        # perspective — it never mutates either side.
        print("  - session_drift_reports")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_drift_reports (
                report_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id     UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                detected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                session_state  JSONB NOT NULL DEFAULT '{}'::jsonb,
                legacy_state   JSONB NOT NULL DEFAULT '{}'::jsonb,
                resolution     TEXT,
                resolved_by    TEXT,
                resolved_at    TIMESTAMPTZ
            );
        """)

        # Index: unresolved reports listed newest-first (admin dashboard query)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_drift_unresolved_detected
              ON session_drift_reports(detected_at DESC)
              WHERE resolution IS NULL;
        """)

        # Index: find all drift reports for a given session (per-session view)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_drift_session_detected
              ON session_drift_reports(session_id, detected_at DESC);
        """)

        conn.commit()
        print("session_drift_reports table created successfully.")

        # Verification
        cur.execute("SELECT COUNT(*) FROM session_drift_reports;")
        print(f"  session_drift_reports rows: {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR creating session_drift_reports table: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_session_drift_reports_table()
