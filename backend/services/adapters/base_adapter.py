"""
IDataSourceAdapter — Abstract base class for all ERP / data source adapters.

Every adapter (PostgreSQL, Odoo, SAP, NetSuite) must implement this interface.
Agents ONLY call methods on this interface — they never know which ERP is behind it.

Switch ERP:  set DATA_SOURCE=odoo  in .env  →  OdooAdapter activates automatically.
"""

from abc import ABC, abstractmethod
from typing import Any


class IDataSourceAdapter(ABC):
    """
    Contract that every ERP adapter must fulfil.
    Method signatures are ERP-neutral — args use business terms, not ERP field names.
    """

    # ── Master Data ────────────────────────────────────────────────────────────

    @abstractmethod
    def get_vendors(self, active_only: bool = True, limit: int = 200) -> list:
        """Return vendor/supplier master records."""

    @abstractmethod
    def get_items(self, item_code: str = None, category: str = None) -> list:
        """Return item / product catalog records."""

    @abstractmethod
    def get_cost_centers(self) -> list:
        """Return cost center master records."""

    @abstractmethod
    def get_exchange_rates(self) -> list:
        """Return current currency exchange rates."""

    # ── Procurement (Source-to-Contract) ──────────────────────────────────────

    @abstractmethod
    def get_purchase_requisitions(self, status: str = None, limit: int = 100) -> list:
        """Return purchase requisitions."""

    @abstractmethod
    def get_approved_suppliers(self, item_code: str = None, category: str = None) -> list:
        """Return approved supplier list entries."""

    @abstractmethod
    def get_rfq_headers(self, status: str = None, limit: int = 50) -> list:
        """Return RFQ headers."""

    @abstractmethod
    def get_vendor_quotes(self, item_name: str = None, limit: int = 50) -> list:
        """Return vendor quote responses."""

    @abstractmethod
    def get_contracts(self, vendor_id: str = None, limit: int = 50) -> list:
        """Return supplier contracts."""

    # ── Purchase Orders ────────────────────────────────────────────────────────

    @abstractmethod
    def get_purchase_orders(self, status: str = None, limit: int = 100) -> list:
        """Return purchase order headers + lines."""

    # ── Warehouse / GRN ───────────────────────────────────────────────────────

    @abstractmethod
    def get_grn_headers(self, grn_number: str = None, po_number: str = None, limit: int = 50) -> list:
        """Return goods receipt notes."""

    # ── Accounts Payable ──────────────────────────────────────────────────────

    @abstractmethod
    def get_vendor_invoices(self, invoice_no: str = None, limit: int = 50) -> list:
        """Return vendor invoices with 3-way match data."""

    @abstractmethod
    def get_ap_aging(self) -> list:
        """Return AP aging report."""

    @abstractmethod
    def get_payment_proposals(self, limit: int = 50) -> list:
        """Return payment proposals."""

    # ── Finance / Reporting ───────────────────────────────────────────────────

    @abstractmethod
    def get_budget_vs_actuals(self, cost_center: str = None) -> list:
        """Return budget vs actual spend."""

    @abstractmethod
    def get_spend_analytics(self, period: str = None, limit: int = 200) -> list:
        """Return multi-dimensional spend analytics."""

    @abstractmethod
    def get_vendor_performance(self, vendor_id: str = None) -> list:
        """Return vendor KPI / performance scores."""

    # ── Inventory ─────────────────────────────────────────────────────────────

    @abstractmethod
    def get_inventory_status(self, item_code: str = None) -> list:
        """Return current stock levels vs reorder points."""

    # ── System ────────────────────────────────────────────────────────────────

    @abstractmethod
    def get_table_registry(self) -> list:
        """Return table_registry metadata (module + ERP mappings)."""

    # ── Operational / System tables (ERP-neutral, always PostgreSQL) ──────────
    # These tables (approval_rules, budget_tracking, po_risk_assessments …)
    # always live in PostgreSQL, regardless of which ERP adapter is active.
    # The base class delegates to PostgreSQLAdapter so ALL adapters inherit
    # working implementations without duplication.

    def _pg(self):
        """Return a PostgreSQLAdapter instance for system-table access."""
        from backend.services.adapters.postgresql_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter()

    def get_approval_rules(self, document_type: str = None, amount: float = None, department: str = None) -> list:
        """Return approval rules — always from PostgreSQL system tables."""
        return self._pg().get_approval_rules(document_type=document_type, amount=amount, department=department)

    def get_pending_approvals(self, status: str = None, document_type: str = None) -> list:
        """Return pending approval records — always from PostgreSQL."""
        return self._pg().get_pending_approvals(status=status, document_type=document_type)

    def create_pending_approval(self, data: dict) -> dict:
        """Insert a new pending approval record."""
        return self._pg().create_pending_approval(data)

    def update_approval_status(self, approval_id: int, status: str, notes: str = '') -> dict:
        """Update approval status."""
        return self._pg().update_approval_status(approval_id, status, notes)

    def get_budget_tracking(self, department: str = None, category: str = None) -> list:
        """Return budget_tracking rows — always from PostgreSQL."""
        return self._pg().get_budget_tracking(department=department, category=category)

    def commit_budget(self, department: str, category: str, amount: float) -> dict:
        """Atomically commit budget (row-level lock) — always PostgreSQL."""
        return self._pg().commit_budget(department, category, amount)

    def store_risk_assessment(self, data: dict) -> dict:
        """Store risk assessment — always PostgreSQL."""
        return self._pg().store_risk_assessment(data)

    def log_agent_action(self, agent_name: str, action_type: str,
                         input_data: dict, output_data: dict, success: bool) -> None:
        """Append to agent_actions audit log — always PostgreSQL."""
        self._pg().log_agent_action(agent_name, action_type, input_data, output_data, success)

    # ── Sprint-6 Pipeline System Tables (always PostgreSQL) ───────────────────

    def log_notification(self, data: dict) -> dict:
        """Log an outbound notification — always PostgreSQL."""
        return self._pg().log_notification(data)

    def mark_notification_sent(self, notification_id: int) -> None:
        """Mark a notification as sent — always PostgreSQL."""
        self._pg().mark_notification_sent(notification_id)

    def log_ocr_ingestion(self, data: dict) -> dict:
        """Log OCR extraction result — always PostgreSQL."""
        return self._pg().log_ocr_ingestion(data)

    def log_discrepancy(self, data: dict) -> dict:
        """Log a 3-way match discrepancy — always PostgreSQL."""
        return self._pg().log_discrepancy(data)

    def get_discrepancies(self, invoice_number: str = None,
                          status: str = None, limit: int = 50) -> list:
        """Return discrepancy_log rows — always PostgreSQL."""
        return self._pg().get_discrepancies(invoice_number=invoice_number,
                                            status=status, limit=limit)

    def resolve_discrepancy(self, discrepancy_id: int,
                             resolution_notes: str, resolved_by: str) -> dict:
        """Mark discrepancy resolved — always PostgreSQL."""
        return self._pg().resolve_discrepancy(discrepancy_id, resolution_notes, resolved_by)

    def place_invoice_hold(self, data: dict) -> dict:
        """Place a hold on an invoice — always PostgreSQL."""
        return self._pg().place_invoice_hold(data)

    def release_invoice_hold(self, invoice_number: str, resolved_by: str) -> dict:
        """Release all active holds on an invoice — always PostgreSQL."""
        return self._pg().release_invoice_hold(invoice_number, resolved_by)

    def get_active_holds(self, invoice_number: str = None) -> list:
        """Return active invoice holds — always PostgreSQL."""
        return self._pg().get_active_holds(invoice_number=invoice_number)

    def create_payment_run(self, data: dict) -> dict:
        """Create a payment run record — always PostgreSQL."""
        return self._pg().create_payment_run(data)

    def create_purchase_order_from_pr(self, data: dict) -> dict:
        """Create a PO from an approved PR. Routes to correct ERP table via adapter.

        In demo mode: writes to the ERP-specific PO table (e.g., odoo_purchase_orders).
        In live mode: subclasses override to call real ERP API (XML-RPC, OData, etc.).

        Args:
            data: dict with pr_number, vendor_name, product_name, quantity,
                  unit_price, total_amount, department, currency
        Returns:
            dict with success, po_number, po_id
        """
        return self._pg().create_purchase_order_from_pr(data)

    def create_purchase_order_from_pr_tx(self, conn, data: dict) -> dict:
        """
        Transactional variant of create_purchase_order_from_pr (HF-2 / R12).
        Uses the caller's connection — does NOT commit or close. Intended
        for use inside `async with adapter.transaction() as conn:` alongside
        SessionService.append_event_tx so both writes commit atomically.
        """
        return self._pg().create_purchase_order_from_pr_tx(conn, data)

    def get_email_template(self, event_type: str) -> dict:
        """Return email template for event — always PostgreSQL."""
        return self._pg().get_email_template(event_type)

    def get_users_by_role(self, role: str) -> list:
        """Return active users by role — always PostgreSQL."""
        return self._pg().get_users_by_role(role)

    # ── UAT-003: Approval Workflow management (always PostgreSQL) ─────────────

    def get_approval_workflow(self, pr_number: str) -> dict:
        """Return existing pr_approval_workflows row — always PostgreSQL."""
        return self._pg().get_approval_workflow(pr_number)

    def create_approval_workflow(self, data: dict) -> dict:
        """Create pr_approval_workflows row — always PostgreSQL."""
        return self._pg().create_approval_workflow(data)

    def create_approval_step(self, data: dict) -> dict:
        """Create pr_approval_steps row — always PostgreSQL."""
        return self._pg().create_approval_step(data)

    # ── Layer 1: Execution Session Orchestration (always PostgreSQL) ──────────
    # Thin CRUD for the new session orchestration tables. These are called
    # ONLY from backend/services/session_service.py (single-writer rule, R9).
    # All methods delegate to PostgreSQLAdapter because Layer 1 tables are
    # PostgreSQL-only by design — LISTEN/NOTIFY, gen_random_uuid(), and
    # partial unique indexes have no portable equivalents.

    def insert_execution_session(self, data: dict) -> dict:
        """Insert a new execution_sessions row. Idempotent via request_fingerprint."""
        return self._pg().insert_execution_session(data)

    def get_execution_session(self, session_id: str) -> dict:
        """Return an execution_sessions row by session_id, or {} if not found."""
        return self._pg().get_execution_session(session_id)

    def get_execution_session_by_fingerprint(self, request_fingerprint: str) -> dict:
        """Return an execution_sessions row by request_fingerprint, or {}."""
        return self._pg().get_execution_session_by_fingerprint(request_fingerprint)

    def get_execution_session_by_workflow_run_id(self, workflow_run_id: str) -> dict:
        """Return the execution_sessions row attached to a workflow_run_id, or {}."""
        return self._pg().get_execution_session_by_workflow_run_id(workflow_run_id)

    def update_execution_session_workflow_run_id(self, session_id: str, workflow_run_id: str) -> dict:
        """Attach a workflow_run_id to an execution_sessions row."""
        return self._pg().update_execution_session_workflow_run_id(session_id, workflow_run_id)

    def list_execution_sessions(self, user_id: str = None, status: str = None,
                                kind: str = None, limit: int = 50) -> list:
        """Return a filtered list of execution_sessions."""
        return self._pg().list_execution_sessions(
            user_id=user_id, status=status, kind=kind, limit=limit
        )

    def update_execution_session_phase(self, session_id: str, new_phase: str,
                                       new_status: str, expected_version: int) -> dict:
        """Atomically update current_phase / current_status with optimistic lock."""
        return self._pg().update_execution_session_phase(
            session_id, new_phase, new_status, expected_version
        )

    def append_session_event(self, session_id: str, event_type: str, actor: str,
                             payload: dict, caused_by_event_id: str = None) -> dict:
        """
        Append an event to session_events under a single transaction:
          1) UPDATE execution_sessions SET last_event_sequence = last_event_sequence + 1
          2) INSERT INTO session_events (..., sequence_number)
        Returns {success, event_id, sequence_number}.
        """
        return self._pg().append_session_event(
            session_id, event_type, actor, payload, caused_by_event_id
        )

    # ── HF-2 / R12 transactional outbox ─────────────────────────────────

    def begin_tx(self):
        """Return a fresh DB connection with autocommit=False (sync primitive)."""
        return self._pg().begin_tx()

    def transaction(self):
        """
        Async context manager yielding a DB connection. Commits on clean exit,
        rolls back on exception, always closes. See postgresql_adapter.transaction.
        """
        return self._pg().transaction()

    def append_session_event_outbox_tx(self, conn, session_id: str,
                                        event_type: str, actor: str,
                                        payload: dict,
                                        caused_by_event_id: str = None) -> dict:
        """
        Write a session event into session_event_outbox using the caller's
        transaction. Does NOT commit. Used by R12 transactional outbox flow.
        """
        return self._pg().append_session_event_outbox_tx(
            conn, session_id, event_type, actor, payload, caused_by_event_id
        )

    def pump_outbox_once(self, batch_size: int = 100) -> dict:
        """
        Run one iteration of the outbox pump: move uncommitted outbox rows
        into session_events and fire NOTIFY. Returns {success, published, stuck_count}.
        """
        return self._pg().pump_outbox_once(batch_size=batch_size)

    # ── HF-4 / R8 / R19 snapshot primitives ──────────────────────────────

    def write_session_snapshot_tx(self, conn, session_id: str,
                                   at_sequence_number: int) -> dict:
        """Write a session_snapshots row in the caller's transaction — PG only."""
        return self._pg().write_session_snapshot_tx(conn, session_id, at_sequence_number)

    def get_latest_snapshot(self, session_id: str,
                             at_or_before_seq: int = None) -> dict:
        """Return the latest session_snapshots row, optionally bounded by seq."""
        return self._pg().get_latest_snapshot(session_id, at_or_before_seq=at_or_before_seq)

    def verify_snapshot_hash(self, session_id: str,
                              at_sequence_number: int,
                              expected_hash: str) -> bool:
        """R19: recompute hash from session_events and compare to stored hash."""
        return self._pg().verify_snapshot_hash(session_id, at_sequence_number, expected_hash)

    def list_session_events(self, session_id: str, since_sequence: int = 0,
                            limit: int = 1000) -> list:
        """Return session_events for a session, ordered by sequence_number ASC."""
        return self._pg().list_session_events(
            session_id, since_sequence=since_sequence, limit=limit
        )

    def insert_session_gate(self, data: dict) -> dict:
        """Insert a session_gates row."""
        return self._pg().insert_session_gate(data)

    def get_session_gate(self, gate_id: str) -> dict:
        """Return a session_gates row by gate_id."""
        return self._pg().get_session_gate(gate_id)

    def list_session_gates(self, session_id: str = None, status: str = None,
                           gate_type: str = None) -> list:
        """Return filtered session_gates rows."""
        return self._pg().list_session_gates(
            session_id=session_id, status=status, gate_type=gate_type
        )

    def resolve_session_gate(self, gate_id: str, decision: dict,
                             resolved_by: str, gate_resolution_id: str) -> dict:
        """
        Resolve a gate idempotently via gate_resolution_id (R13).
        Duplicate resolution attempts with the same gate_resolution_id return
        the prior stored decision without re-applying.
        """
        return self._pg().resolve_session_gate(
            gate_id, decision, resolved_by, gate_resolution_id
        )

    def source_name(self) -> str:
        """Human-readable name of this adapter's data source."""
        return self.__class__.__name__
