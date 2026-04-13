"""
Budget Ledger Service -- G-08 Dev Spec 2.0
============================================
Tracks budget allocations, commitments, actuals, releases, and adjustments
per department and fiscal year.  Provides reconciliation and summary views.

Ledger entry types:
  allocation  - Initial / revised budget amount
  commitment  - Encumbered when a PR is approved
  release     - Freed when a PR or PO is cancelled
  actual      - Recorded at payment / invoice approval
  adjustment  - Variance correction (positive or negative)
  transfer    - Inter-department budget move (future)

Running-balance formula (after each entry):
  available = SUM(allocation) - SUM(commitment) - SUM(actual)
              + SUM(release)  + SUM(adjustment)

Usage:
    from backend.services.budget_ledger_service import get_budget_ledger_service
    svc = get_budget_ledger_service()
    svc.record_commitment('IT', 2026, 'PR', 'PR-2026-042', 15000.00, 'Server procurement')
    balance = svc.get_department_balance('IT', 2026)
"""

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_fiscal_year() -> int:
    """Return the current calendar year as the default fiscal year."""
    return datetime.now(timezone.utc).year


def _dec_to_float(value):
    """Safely convert Decimal to float for JSON serialisation."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row_to_dict(row: dict) -> dict:
    """Normalise a RealDictRow: Decimals -> float, dates -> str."""
    out = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime,)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BudgetLedgerService:
    """
    Manages the budget_ledger table for commitment accounting.

    Every mutation goes through ``_post_entry()`` which computes the
    running balance as of the new row and persists it atomically.
    """

    # -- internal plumbing ---------------------------------------------------

    def _get_conn(self):
        """Obtain a fresh psycopg2 connection."""
        if not DB_URL:
            raise ValueError("DATABASE_URL environment variable is not set")
        return psycopg2.connect(DB_URL)

    def _compute_running_balance(self, cur, department: str, fiscal_year: int) -> float:
        """
        Compute the current available balance for *department* / *fiscal_year*
        from all existing ledger rows.

        available = allocations - commitments - actuals + releases + adjustments
        """
        cur.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN entry_type = 'allocation'  THEN amount ELSE 0 END), 0) AS allocated,
                COALESCE(SUM(CASE WHEN entry_type = 'commitment'  THEN amount ELSE 0 END), 0) AS committed,
                COALESCE(SUM(CASE WHEN entry_type = 'actual'      THEN amount ELSE 0 END), 0) AS actual,
                COALESCE(SUM(CASE WHEN entry_type = 'release'     THEN amount ELSE 0 END), 0) AS released,
                COALESCE(SUM(CASE WHEN entry_type = 'adjustment'  THEN amount ELSE 0 END), 0) AS adjusted
            FROM budget_ledger
            WHERE department = %s AND fiscal_year = %s
            """,
            (department, fiscal_year),
        )
        row = cur.fetchone()
        allocated  = float(row["allocated"])
        committed  = float(row["committed"])
        actual     = float(row["actual"])
        released   = float(row["released"])
        adjusted   = float(row["adjusted"])
        return round(allocated - committed - actual + released + adjusted, 2)

    def _post_entry(
        self,
        department: str,
        fiscal_year: int,
        entry_type: str,
        reference_type: Optional[str],
        reference_id: Optional[str],
        amount: float,
        description: str,
        posted_by: str = "system",
    ) -> Dict[str, Any]:
        """
        Core method -- insert a single ledger row and compute its running
        balance inside one transaction.

        Returns the newly created entry as a dict.
        """
        conn = None
        try:
            conn = self._get_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Compute the running balance *including* this new entry
            current_balance = self._compute_running_balance(cur, department, fiscal_year)

            # Apply the effect of the new entry on the balance
            if entry_type == "allocation":
                running_balance = current_balance + amount
            elif entry_type == "commitment":
                running_balance = current_balance - amount
            elif entry_type == "actual":
                running_balance = current_balance - amount
            elif entry_type == "release":
                running_balance = current_balance + amount
            elif entry_type == "adjustment":
                running_balance = current_balance + amount
            elif entry_type == "transfer":
                running_balance = current_balance + amount  # positive = incoming
            else:
                running_balance = current_balance

            running_balance = round(running_balance, 2)

            now = datetime.now(timezone.utc)
            fiscal_period = now.strftime("%Y-%m")  # e.g. "2026-04"

            cur.execute(
                """
                INSERT INTO budget_ledger
                    (department, fiscal_year, fiscal_period, entry_type,
                     reference_type, reference_id, amount, running_balance,
                     description, posted_by, posted_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    department,
                    fiscal_year,
                    fiscal_period,
                    entry_type,
                    reference_type,
                    reference_id,
                    amount,
                    running_balance,
                    description,
                    posted_by,
                    now,
                    now,
                ),
            )
            entry = _row_to_dict(dict(cur.fetchone()))
            conn.commit()

            logger.info(
                "[BudgetLedger] %s | dept=%s fy=%s amount=%.2f balance=%.2f ref=%s/%s",
                entry_type.upper(),
                department,
                fiscal_year,
                amount,
                running_balance,
                reference_type,
                reference_id,
            )
            return entry

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error("[BudgetLedger] _post_entry failed: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    # -- public API ----------------------------------------------------------

    def record_commitment(
        self,
        department: str,
        fiscal_year: int,
        reference_type: str,
        reference_id: str,
        amount: float,
        description: str,
        posted_by: str = "system",
    ) -> Dict[str, Any]:
        """
        Record a budget commitment (encumbrance).

        Typically called when a Purchase Requisition is approved.

        Args:
            department:     Department code (e.g. "IT", "Finance").
            fiscal_year:    Fiscal year the budget belongs to.
            reference_type: Source document type (e.g. "PR", "PO").
            reference_id:   Source document number.
            amount:         Commitment amount (positive).
            description:    Human-readable note.
            posted_by:      User or system identifier.

        Returns:
            The newly created ledger entry dict.
        """
        return self._post_entry(
            department=department,
            fiscal_year=fiscal_year,
            entry_type="commitment",
            reference_type=reference_type,
            reference_id=reference_id,
            amount=abs(amount),
            description=description,
            posted_by=posted_by,
        )

    def release_commitment(
        self,
        department: str,
        fiscal_year: int,
        reference_type: str,
        reference_id: str,
        amount: float,
        description: str,
        posted_by: str = "system",
    ) -> Dict[str, Any]:
        """
        Release a previously recorded commitment.

        Called when a PR or PO is cancelled or reduced.

        Returns:
            The newly created ledger entry dict.
        """
        return self._post_entry(
            department=department,
            fiscal_year=fiscal_year,
            entry_type="release",
            reference_type=reference_type,
            reference_id=reference_id,
            amount=abs(amount),
            description=description,
            posted_by=posted_by,
        )

    def record_actual(
        self,
        department: str,
        fiscal_year: int,
        reference_type: str,
        reference_id: str,
        amount: float,
        description: str,
        posted_by: str = "system",
    ) -> Dict[str, Any]:
        """
        Record actual expenditure.

        Called at invoice approval or payment execution.

        Returns:
            The newly created ledger entry dict.
        """
        return self._post_entry(
            department=department,
            fiscal_year=fiscal_year,
            entry_type="actual",
            reference_type=reference_type,
            reference_id=reference_id,
            amount=abs(amount),
            description=description,
            posted_by=posted_by,
        )

    def record_adjustment(
        self,
        department: str,
        fiscal_year: int,
        reference_type: str,
        reference_id: str,
        amount: float,
        description: str,
        posted_by: str = "system",
    ) -> Dict[str, Any]:
        """
        Record a variance adjustment.

        Positive amount increases the available budget; negative decreases it.

        Returns:
            The newly created ledger entry dict.
        """
        return self._post_entry(
            department=department,
            fiscal_year=fiscal_year,
            entry_type="adjustment",
            reference_type=reference_type,
            reference_id=reference_id,
            amount=amount,  # preserve sign for adjustments
            description=description,
            posted_by=posted_by,
        )

    def record_allocation(
        self,
        department: str,
        fiscal_year: int,
        amount: float,
        description: str,
        posted_by: str = "system",
    ) -> Dict[str, Any]:
        """
        Record an initial or supplementary budget allocation.

        Args:
            department:  Department code.
            fiscal_year: Fiscal year.
            amount:      Allocation amount (positive).
            description: Note (e.g. "FY2026 approved budget").
            posted_by:   User or system identifier.

        Returns:
            The newly created ledger entry dict.
        """
        return self._post_entry(
            department=department,
            fiscal_year=fiscal_year,
            entry_type="allocation",
            reference_type="BUDGET",
            reference_id=f"ALLOC-{department}-{fiscal_year}",
            amount=abs(amount),
            description=description,
            posted_by=posted_by,
        )

    # -- queries -------------------------------------------------------------

    def get_department_balance(
        self, department: str, fiscal_year: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Return the current budget position for a department.

        Returns:
            {
                department, fiscal_year,
                allocated, committed, actual, released, adjusted,
                available, utilization_pct
            }
        """
        fy = fiscal_year or _current_fiscal_year()
        conn = None
        try:
            conn = self._get_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN entry_type = 'allocation'  THEN amount ELSE 0 END), 0) AS allocated,
                    COALESCE(SUM(CASE WHEN entry_type = 'commitment'  THEN amount ELSE 0 END), 0) AS committed,
                    COALESCE(SUM(CASE WHEN entry_type = 'actual'      THEN amount ELSE 0 END), 0) AS actual,
                    COALESCE(SUM(CASE WHEN entry_type = 'release'     THEN amount ELSE 0 END), 0) AS released,
                    COALESCE(SUM(CASE WHEN entry_type = 'adjustment'  THEN amount ELSE 0 END), 0) AS adjusted,
                    COUNT(*)                                                                       AS entry_count
                FROM budget_ledger
                WHERE department = %s AND fiscal_year = %s
                """,
                (department, fy),
            )
            row = cur.fetchone()

            allocated  = float(row["allocated"])
            committed  = float(row["committed"])
            actual     = float(row["actual"])
            released   = float(row["released"])
            adjusted   = float(row["adjusted"])
            available  = round(allocated - committed - actual + released + adjusted, 2)

            utilization_pct = 0.0
            if allocated > 0:
                utilization_pct = round(((committed + actual - released) / allocated) * 100, 2)

            return {
                "department": department,
                "fiscal_year": fy,
                "allocated": round(allocated, 2),
                "committed": round(committed, 2),
                "actual": round(actual, 2),
                "released": round(released, 2),
                "adjusted": round(adjusted, 2),
                "available": available,
                "utilization_pct": min(utilization_pct, 100.0),
                "entry_count": int(row["entry_count"]),
            }

        except Exception as e:
            logger.error("[BudgetLedger] get_department_balance failed: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    def get_ledger_entries(
        self,
        department: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        entry_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve ledger entries with optional filters.

        Args:
            department: Filter by department (None = all).
            fiscal_year: Filter by fiscal year (None = all).
            entry_type:  Filter by entry type (None = all).
            limit:       Maximum rows to return (default 100).

        Returns:
            List of ledger entry dicts ordered by posted_at descending.
        """
        conn = None
        try:
            conn = self._get_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            conditions: List[str] = []
            params: list = []

            if department:
                conditions.append("department = %s")
                params.append(department)
            if fiscal_year:
                conditions.append("fiscal_year = %s")
                params.append(fiscal_year)
            if entry_type:
                conditions.append("entry_type = %s")
                params.append(entry_type)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            params.append(limit)

            cur.execute(
                f"""
                SELECT *
                FROM budget_ledger
                {where}
                ORDER BY posted_at DESC, id DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
            return [_row_to_dict(dict(r)) for r in rows]

        except Exception as e:
            logger.error("[BudgetLedger] get_ledger_entries failed: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    def reconcile_department(
        self, department: str, fiscal_year: int
    ) -> Dict[str, Any]:
        """
        Full reconciliation for a department / fiscal year.

        Compares total commitments against actuals, identifies outstanding
        commitments (encumbrances not yet realised as actuals), and flags
        variances per reference document.

        Returns:
            {
                department, fiscal_year, balance,
                open_commitments: [{reference_type, reference_id, committed, actual, variance}],
                total_open_commitment, total_variance,
                reconciled_at
            }
        """
        conn = None
        try:
            conn = self._get_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Aggregate commitments and actuals grouped by reference document
            cur.execute(
                """
                SELECT
                    reference_type,
                    reference_id,
                    COALESCE(SUM(CASE WHEN entry_type = 'commitment' THEN amount ELSE 0 END), 0) AS committed,
                    COALESCE(SUM(CASE WHEN entry_type = 'release'    THEN amount ELSE 0 END), 0) AS released,
                    COALESCE(SUM(CASE WHEN entry_type = 'actual'     THEN amount ELSE 0 END), 0) AS actual,
                    COALESCE(SUM(CASE WHEN entry_type = 'adjustment' THEN amount ELSE 0 END), 0) AS adjusted
                FROM budget_ledger
                WHERE department = %s
                  AND fiscal_year = %s
                  AND entry_type IN ('commitment', 'release', 'actual', 'adjustment')
                  AND reference_type IS NOT NULL
                GROUP BY reference_type, reference_id
                ORDER BY reference_type, reference_id
                """,
                (department, fiscal_year),
            )
            ref_rows = cur.fetchall()

            open_commitments: List[Dict[str, Any]] = []
            total_open_commitment = 0.0
            total_variance = 0.0

            for r in ref_rows:
                committed = float(r["committed"])
                released  = float(r["released"])
                actual    = float(r["actual"])
                adjusted  = float(r["adjusted"])

                net_commitment = committed - released
                variance = round(net_commitment - actual + adjusted, 2)

                entry = {
                    "reference_type": r["reference_type"],
                    "reference_id": r["reference_id"],
                    "committed": round(committed, 2),
                    "released": round(released, 2),
                    "net_commitment": round(net_commitment, 2),
                    "actual": round(actual, 2),
                    "adjusted": round(adjusted, 2),
                    "variance": variance,
                    "status": "open" if variance > 0.01 else ("over" if variance < -0.01 else "matched"),
                }
                open_commitments.append(entry)

                if variance > 0:
                    total_open_commitment += variance
                total_variance += abs(variance)

            # Get the overall balance
            balance = self.get_department_balance(department, fiscal_year)

            return {
                "department": department,
                "fiscal_year": fiscal_year,
                "balance": balance,
                "open_commitments": open_commitments,
                "total_open_commitment": round(total_open_commitment, 2),
                "total_variance": round(total_variance, 2),
                "document_count": len(open_commitments),
                "matched_count": sum(1 for c in open_commitments if c["status"] == "matched"),
                "open_count": sum(1 for c in open_commitments if c["status"] == "open"),
                "over_count": sum(1 for c in open_commitments if c["status"] == "over"),
                "reconciled_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("[BudgetLedger] reconcile_department failed: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    def get_budget_summary(
        self, fiscal_year: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Return a summary across all departments for a fiscal year.

        Returns:
            {
                fiscal_year,
                departments: [{department, allocated, committed, actual, available, utilization_pct}],
                totals: {allocated, committed, actual, available, utilization_pct}
            }
        """
        fy = fiscal_year or _current_fiscal_year()
        conn = None
        try:
            conn = self._get_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    department,
                    COALESCE(SUM(CASE WHEN entry_type = 'allocation'  THEN amount ELSE 0 END), 0) AS allocated,
                    COALESCE(SUM(CASE WHEN entry_type = 'commitment'  THEN amount ELSE 0 END), 0) AS committed,
                    COALESCE(SUM(CASE WHEN entry_type = 'actual'      THEN amount ELSE 0 END), 0) AS actual,
                    COALESCE(SUM(CASE WHEN entry_type = 'release'     THEN amount ELSE 0 END), 0) AS released,
                    COALESCE(SUM(CASE WHEN entry_type = 'adjustment'  THEN amount ELSE 0 END), 0) AS adjusted,
                    COUNT(*)                                                                       AS entry_count
                FROM budget_ledger
                WHERE fiscal_year = %s
                GROUP BY department
                ORDER BY department
                """,
                (fy,),
            )
            rows = cur.fetchall()

            departments: List[Dict[str, Any]] = []
            totals = {
                "allocated": 0.0,
                "committed": 0.0,
                "actual": 0.0,
                "released": 0.0,
                "adjusted": 0.0,
                "available": 0.0,
            }

            for row in rows:
                allocated  = float(row["allocated"])
                committed  = float(row["committed"])
                actual     = float(row["actual"])
                released   = float(row["released"])
                adjusted   = float(row["adjusted"])
                available  = round(allocated - committed - actual + released + adjusted, 2)

                utilization_pct = 0.0
                if allocated > 0:
                    utilization_pct = round(
                        ((committed + actual - released) / allocated) * 100, 2
                    )

                dept_summary = {
                    "department": row["department"],
                    "allocated": round(allocated, 2),
                    "committed": round(committed, 2),
                    "actual": round(actual, 2),
                    "released": round(released, 2),
                    "adjusted": round(adjusted, 2),
                    "available": available,
                    "utilization_pct": min(utilization_pct, 100.0),
                    "entry_count": int(row["entry_count"]),
                }
                departments.append(dept_summary)

                totals["allocated"]  += allocated
                totals["committed"]  += committed
                totals["actual"]     += actual
                totals["released"]   += released
                totals["adjusted"]   += adjusted
                totals["available"]  += available

            # Round totals
            for k in totals:
                totals[k] = round(totals[k], 2)

            total_utilization = 0.0
            if totals["allocated"] > 0:
                total_utilization = round(
                    ((totals["committed"] + totals["actual"] - totals["released"])
                     / totals["allocated"]) * 100,
                    2,
                )

            return {
                "fiscal_year": fy,
                "departments": departments,
                "department_count": len(departments),
                "totals": {
                    **totals,
                    "utilization_pct": min(total_utilization, 100.0),
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("[BudgetLedger] get_budget_summary failed: %s", e)
            raise
        finally:
            if conn:
                conn.close()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_instance: Optional[BudgetLedgerService] = None


def get_budget_ledger_service() -> BudgetLedgerService:
    """Return (or create) the module-level BudgetLedgerService singleton."""
    global _instance
    if _instance is None:
        _instance = BudgetLedgerService()
    return _instance
