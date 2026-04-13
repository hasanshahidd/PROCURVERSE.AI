"""
Background jobs package for Procure-AI.

Houses scheduled tasks that run on the server event loop (P1.5+):

- drift_reconciliation:
    R18 — compare session_events (truth) against legacy workflow_runs
    (artifact) every 15 minutes during hybrid mode, daily after P5.
    Records mismatches in session_drift_reports. Read-only on both sides.

Jobs here never mutate Layer 1 (execution_sessions, session_events,
session_gates) nor Layer 2 (ERP) state. They are observers only.
"""
