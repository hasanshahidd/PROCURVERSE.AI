"""
Database Migration: Create Execution Session Tables (P0)

Layer 1 — Session Orchestration tables for the P2P workflow execution-session
architecture. These are thin, append-only tables that track in-flight workflow
state and reference (but never copy) ERP business entities.

Tables created:
  execution_sessions   — master row per P2P run (state-machine current_phase/status)
  session_events       — append-only ordered event log (sequence_number per session)
  session_gates        — human-gate pointers with decision_context snapshot
  session_snapshots    — periodic folded-state checkpoints for fast replay

Also creates:
  notify_session_event() trigger function + AFTER INSERT trigger on session_events
    → fires pg_notify('session_<session_id>', '<sequence_number>') on every insert
    → consumed by the SSE endpoint at GET /api/sessions/:id/events

Usage:
  python -m backend.migrations.create_execution_session_tables

Revert:
  DROP TABLE IF EXISTS session_snapshots, session_gates, session_events, execution_sessions CASCADE;
  DROP FUNCTION IF EXISTS notify_session_event();
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def create_execution_session_tables():
    """Create the 4 session orchestration tables + the LISTEN/NOTIFY trigger."""

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        print("Creating execution session tables...")

        # ── 1. execution_sessions ─────────────────────────────────────────
        # Thin master row per P2P run. Holds state-machine position, never
        # business data. References ERP entities only by id (workflow_run_id).
        print("  - execution_sessions")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS execution_sessions (
                session_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_kind          TEXT NOT NULL,
                initiated_by_user_id  TEXT NOT NULL,
                request_fingerprint   TEXT NOT NULL,
                current_phase         TEXT NOT NULL DEFAULT 'starting',
                current_status        TEXT NOT NULL DEFAULT 'running',
                workflow_run_id       TEXT,
                request_summary       JSONB NOT NULL DEFAULT '{}'::jsonb,
                last_event_sequence   BIGINT NOT NULL DEFAULT 0,
                snapshot_version      INT NOT NULL DEFAULT 0,
                version               INT NOT NULL DEFAULT 1,
                created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at          TIMESTAMPTZ,
                CONSTRAINT chk_session_status CHECK (
                    current_status IN ('running', 'paused_human', 'completed', 'failed', 'cancelled')
                ),
                CONSTRAINT uniq_request_fingerprint UNIQUE (request_fingerprint)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user_status
              ON execution_sessions(initiated_by_user_id, current_status);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_workflow
              ON execution_sessions(workflow_run_id);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_kind_status
              ON execution_sessions(session_kind, current_status);
        """)

        # ── 2. session_events ─────────────────────────────────────────────
        # Append-only, ordered, idempotent. The event IS the state change.
        # sequence_number is per-session monotonic, enforced by UNIQUE.
        print("  - session_events")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_events (
                event_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id         UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                sequence_number    BIGINT NOT NULL,
                event_type         TEXT NOT NULL,
                actor              TEXT NOT NULL,
                payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
                caused_by_event_id UUID REFERENCES session_events(event_id),
                created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uniq_session_sequence UNIQUE (session_id, sequence_number)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_session_seq
              ON session_events(session_id, sequence_number);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type_created
              ON session_events(event_type, created_at DESC);
        """)

        # ── 3. session_gates ──────────────────────────────────────────────
        # Pointer + status + auditable decision_context snapshot.
        # Holds NO policy logic — the orchestrator decides what to do on resolve.
        # R13: gate_resolution_id enables idempotent resolve submissions.
        print("  - session_gates")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_gates (
                gate_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id          UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                gate_type           TEXT NOT NULL,
                gate_ref            JSONB NOT NULL DEFAULT '{}'::jsonb,
                decision_context    JSONB NOT NULL DEFAULT '{}'::jsonb,
                required_role       TEXT,
                status              TEXT NOT NULL DEFAULT 'pending',
                decision            JSONB,
                gate_resolution_id  UUID,
                resolved_by         TEXT,
                resolved_at         TIMESTAMPTZ,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_gate_status CHECK (status IN ('pending', 'resolved', 'expired'))
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_gates_session_status
              ON session_gates(session_id, status);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_gates_type_status
              ON session_gates(gate_type, status);
        """)
        # R13: partial unique index on resolved gate resolutions
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_gate_resolution
              ON session_gates(gate_id, gate_resolution_id)
              WHERE gate_resolution_id IS NOT NULL;
        """)

        # ── 4. session_snapshots ──────────────────────────────────────────
        # R8 + R19: periodic folded-state checkpoints for bounded replay cost.
        # content_hash (R19) enables detection of silent snapshot corruption.
        print("  - session_snapshots")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_snapshots (
                snapshot_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id          UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                at_sequence_number  BIGINT NOT NULL,
                state               JSONB NOT NULL,
                content_hash        TEXT NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uniq_snapshot_session_seq UNIQUE (session_id, at_sequence_number)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_session_seq
              ON session_snapshots(session_id, at_sequence_number DESC);
        """)

        # ── 5. notify_session_event() trigger ─────────────────────────────
        # pg_notify fires on every session_events insert, carrying the
        # sequence_number. SSE listeners (backend/routes/sessions.py) LISTEN
        # on "session_<session_id>" and re-fetch the row from the DB on each
        # notification — the DB remains the sole source of truth for events.
        print("  - notify_session_event() trigger")
        cur.execute("""
            CREATE OR REPLACE FUNCTION notify_session_event()
            RETURNS trigger AS $$
            BEGIN
                PERFORM pg_notify(
                    'session_' || NEW.session_id::text,
                    NEW.sequence_number::text
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        cur.execute("""
            DROP TRIGGER IF EXISTS trg_notify_session_event ON session_events;
        """)
        cur.execute("""
            CREATE TRIGGER trg_notify_session_event
            AFTER INSERT ON session_events
            FOR EACH ROW EXECUTE FUNCTION notify_session_event();
        """)

        conn.commit()
        print("Execution session tables created successfully.")

        # Print verification row counts
        cur.execute("SELECT COUNT(*) FROM execution_sessions;")
        print(f"  execution_sessions rows: {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM session_events;")
        print(f"  session_events rows:     {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM session_gates;")
        print(f"  session_gates rows:      {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM session_snapshots;")
        print(f"  session_snapshots rows:  {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR creating session tables: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_execution_session_tables()
