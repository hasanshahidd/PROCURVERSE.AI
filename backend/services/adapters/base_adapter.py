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

    def get_approval_rules(self, document_type: str = None, amount: float = None) -> list:
        """Return approval rules — always from PostgreSQL system tables."""
        return self._pg().get_approval_rules(document_type=document_type, amount=amount)

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

    def source_name(self) -> str:
        """Human-readable name of this adapter's data source."""
        return self.__class__.__name__
