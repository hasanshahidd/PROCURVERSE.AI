"""
Database Migration: Create session_event_outbox table (P1.5 / HF-2 / R12)

Transactional outbox for session events that must commit atomically with an
ERP write. The outbox pattern guarantees:

    ERP write + event append are in the same transaction.
    Either both commit or both roll back.
    The event becomes visible to SSE listeners only after the pump publishes it.

Flow:
  1. Handler opens a transaction, writes to an ERP table, and calls
     SessionService.append_event_tx(tx, ...). This variant inserts into
     session_event_outbox only — NOT into session_events, NOT via pg_notify.
  2. Transaction commits. ERP row + outbox row are both durable.
  3. A separate outbox pump task scans session_event_outbox
     WHERE committed_at IS NULL, inserts into session_events (which fires
     NOTIFY via the existing trigger), and marks the outbox row committed.
  4. If the pump is down, events queue up in the outbox and are delivered
     on the next run. SSE clients see a delay but never see wrong state.

Schema:
  outbox_id          — UUID PK
  session_id         — FK to execution_sessions
  sequence_number    — per-session monotonic (assigned by append_event_tx, same
                       mechanism as session_events: UPDATE ... RETURNING)
  event_type         — closed vocabulary
  actor              — 'orchestrator' or 'user:<id>'
  payload            — JSONB, ids only
  caused_by_event_id — optional chain-of-causation
  created_at         — when the tx committed (best-effort client clock)
  committed_at       — when the pump published this row (NULL = not yet)

Usage:
  python -m backend.migrations.create_session_event_outbox_table

Revert:
  DROP TABLE IF EXISTS session_event_outbox CASCADE;
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def create_session_event_outbox_table():
    """Create the outbox table + its pump-friendly index."""

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    try:
        print("Creating session_event_outbox table...")

        # ── session_event_outbox ─────────────────────────────────────────
        # Mirrors session_events shape plus a committed_at column the pump uses
        # to track publication progress. No NOTIFY trigger on this table —
        # notifications fire only when the pump inserts into session_events.
        print("  - session_event_outbox")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS session_event_outbox (
                outbox_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id         UUID NOT NULL REFERENCES execution_sessions(session_id) ON DELETE CASCADE,
                sequence_number    BIGINT NOT NULL,
                event_type         TEXT NOT NULL,
                actor              TEXT NOT NULL,
                payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
                caused_by_event_id UUID,
                created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                committed_at       TIMESTAMPTZ,
                CONSTRAINT uniq_outbox_session_sequence UNIQUE (session_id, sequence_number)
            );
        """)

        # Index: the pump scans uncommitted rows oldest-first, so we need a
        # partial index to make "WHERE committed_at IS NULL ORDER BY created_at"
        # cheap even as the table grows.
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_outbox_uncommitted
              ON session_event_outbox(created_at)
              WHERE committed_at IS NULL;
        """)

        # Secondary index: observability lookups by session_id
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_outbox_session_seq
              ON session_event_outbox(session_id, sequence_number);
        """)

        conn.commit()
        print("session_event_outbox table created successfully.")

        cur.execute("SELECT COUNT(*) FROM session_event_outbox;")
        print(f"  session_event_outbox rows: {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR creating session_event_outbox table: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_session_event_outbox_table()
