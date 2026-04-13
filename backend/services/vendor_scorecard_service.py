"""
Vendor Scorecard, Early Payment Discount & Accrual Services
============================================================
Implements:
  G-10  Vendor Performance Feedback  (VendorScorecardService)
  G-11  Early Payment Discount       (EarlyPaymentDiscountService)
  G-12  Accruals / GRNi              (AccrualService)

Tables used (created by devspec2_gap_tables.py):
  - vendor_scorecard   (G-10)
  - accrual_entries    (G-12)

Tables referenced:
  - grn_headers, grn_line_items, qc_inspection_log
  - vendor_invoices, po_headers
  - vendor_communications

Usage:
    from backend.services.vendor_scorecard_service import (
        get_scorecard_service, get_early_payment_service, get_accrual_service,
    )
    scorecard = get_scorecard_service()
    result    = scorecard.score_transaction(...)
"""

import logging
import os
import uuid
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_conn():
    """Obtain a new psycopg2 connection from DATABASE_URL."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(DATABASE_URL)


def _dec(val) -> float:
    """Coerce Decimal / None to float for JSON serialisation."""
    if val is None:
        return 0.0
    return float(val) if isinstance(val, Decimal) else float(val)


def _rows(cur) -> list:
    """Fetch all rows from a RealDictCursor and coerce Decimals."""
    result = []
    for row in cur.fetchall():
        r = {}
        for k, v in row.items():
            r[k] = float(v) if isinstance(v, Decimal) else v
        result.append(r)
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  G-10: Vendor Scorecard Service
# ═══════════════════════════════════════════════════════════════════════════

# Dimension weights for overall score
WEIGHTS = {
    "delivery_accuracy": 0.25,
    "on_time_delivery":  0.25,
    "quality":           0.25,
    "invoice_accuracy":  0.15,
    "communication":     0.10,
}


class VendorScorecardService:
    """
    Scores vendors on five dimensions per transaction and maintains
    rolling 12-month averages that feed into vendor selection.
    """

    # ------------------------------------------------------------------
    # score_transaction
    # ------------------------------------------------------------------
    def score_transaction(
        self,
        vendor_id: str,
        vendor_name: str,
        po_number: str,
        grn_number: str,
        scoring_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Score a single PO/GRN transaction on 5 dimensions.

        scoring_data keys:
            ordered_qty         float   qty ordered on PO
            received_qty        float   qty received on GRN
            accepted_qty        float   qty passing QC
            delivery_due_date   str     ISO date (promised/requested delivery)
            actual_delivery_date str    ISO date (grn_date)
            invoice_discrepancy str     'none' | 'minor' | 'major'
            response_hours      float   avg vendor response time in hours
            feedback_notes      str     optional free-text

        Returns dict with all dimension scores and the overall score.
        """
        # --- 1. Delivery accuracy: (received / ordered) * 100 -----------
        ordered_qty  = max(float(scoring_data.get("ordered_qty", 0)), 0.0001)
        received_qty = float(scoring_data.get("received_qty", 0))
        delivery_accuracy = min(round((received_qty / ordered_qty) * 100, 2), 100.0)

        # --- 2. On-time delivery ----------------------------------------
        try:
            due_date    = date.fromisoformat(str(scoring_data.get("delivery_due_date", "")))
            actual_date = date.fromisoformat(str(scoring_data.get("actual_delivery_date", "")))
            days_late   = (actual_date - due_date).days
        except (ValueError, TypeError):
            days_late = 0

        if days_late <= 0:
            on_time_delivery = 100.0
        else:
            on_time_delivery = max(round(100 - (days_late * 10), 2), 0.0)

        # --- 3. Quality score: (accepted / received) * 100 --------------
        accepted_qty = float(scoring_data.get("accepted_qty", received_qty))
        recv_safe    = max(received_qty, 0.0001)
        quality_score = min(round((accepted_qty / recv_safe) * 100, 2), 100.0)

        # --- 4. Invoice accuracy ----------------------------------------
        disc = str(scoring_data.get("invoice_discrepancy", "none")).lower()
        if disc in ("none", ""):
            invoice_accuracy = 100.0
        elif disc == "minor":
            invoice_accuracy = 50.0
        else:
            invoice_accuracy = 0.0

        # --- 5. Communication score: 100 if <= 24h, then -5 per extra hour
        response_hours = float(scoring_data.get("response_hours", 0))
        if response_hours <= 24:
            communication_score = 100.0
        else:
            communication_score = max(round(100 - ((response_hours - 24) * 5), 2), 0.0)

        # --- Overall weighted score -------------------------------------
        overall_score = round(
            delivery_accuracy   * WEIGHTS["delivery_accuracy"]
            + on_time_delivery  * WEIGHTS["on_time_delivery"]
            + quality_score     * WEIGHTS["quality"]
            + invoice_accuracy  * WEIGHTS["invoice_accuracy"]
            + communication_score * WEIGHTS["communication"],
            2,
        )

        # --- Determine evaluation period --------------------------------
        now = datetime.now(timezone.utc)
        evaluation_period = now.strftime("%Y-%m")

        # --- Persist to vendor_scorecard --------------------------------
        conn = None
        record_id = None
        rolling_avg = overall_score  # default until we compute real average
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Count running totals for this vendor
                cur.execute(
                    """
                    SELECT
                        COUNT(*)                                          AS total_orders,
                        COUNT(*) FILTER (WHERE on_time_delivery_score >= 80) AS total_on_time,
                        COUNT(*) FILTER (WHERE quality_score >= 80)        AS total_quality_pass,
                        COUNT(*) FILTER (WHERE invoice_accuracy_score >= 80) AS total_invoice_accurate
                    FROM vendor_scorecard
                    WHERE vendor_id = %s
                    """,
                    (vendor_id,),
                )
                totals = cur.fetchone() or {}
                total_orders          = int(totals.get("total_orders", 0)) + 1
                total_on_time         = int(totals.get("total_on_time", 0)) + (1 if on_time_delivery >= 80 else 0)
                total_quality_pass    = int(totals.get("total_quality_pass", 0)) + (1 if quality_score >= 80 else 0)
                total_invoice_accurate = int(totals.get("total_invoice_accurate", 0)) + (1 if invoice_accuracy >= 80 else 0)

                # Rolling 12-month average
                twelve_months_ago = (now - timedelta(days=365)).strftime("%Y-%m")
                cur.execute(
                    """
                    SELECT AVG(overall_score) AS avg_score
                    FROM vendor_scorecard
                    WHERE vendor_id = %s
                      AND evaluation_period >= %s
                    """,
                    (vendor_id, twelve_months_ago),
                )
                avg_row = cur.fetchone()
                if avg_row and avg_row.get("avg_score") is not None:
                    # weighted with new score
                    existing_avg = _dec(avg_row["avg_score"])
                    existing_count = total_orders - 1
                    if existing_count > 0:
                        rolling_avg = round(
                            (existing_avg * existing_count + overall_score) / total_orders, 2
                        )
                    else:
                        rolling_avg = overall_score
                else:
                    rolling_avg = overall_score

                # Insert scorecard row
                cur.execute(
                    """
                    INSERT INTO vendor_scorecard (
                        vendor_id, vendor_name, evaluation_period,
                        po_number, grn_number,
                        delivery_accuracy_score, on_time_delivery_score,
                        quality_score, invoice_accuracy_score, communication_score,
                        overall_score,
                        total_orders, total_on_time, total_quality_pass,
                        total_invoice_accurate, rolling_12m_avg,
                        feedback_notes, scored_by, created_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, NOW()
                    )
                    RETURNING id
                    """,
                    (
                        vendor_id, vendor_name, evaluation_period,
                        po_number, grn_number,
                        delivery_accuracy, on_time_delivery,
                        quality_score, invoice_accuracy, communication_score,
                        overall_score,
                        total_orders, total_on_time, total_quality_pass,
                        total_invoice_accurate, rolling_avg,
                        scoring_data.get("feedback_notes", ""),
                        "system",
                    ),
                )
                returning = cur.fetchone()
                record_id = returning["id"] if returning else None
                conn.commit()

        except Exception as exc:
            logger.error("[VendorScorecard] score_transaction failed: %s", exc)
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

        return {
            "record_id": record_id,
            "vendor_id": vendor_id,
            "vendor_name": vendor_name,
            "po_number": po_number,
            "grn_number": grn_number,
            "evaluation_period": evaluation_period,
            "delivery_accuracy_score": delivery_accuracy,
            "on_time_delivery_score": on_time_delivery,
            "quality_score": quality_score,
            "invoice_accuracy_score": invoice_accuracy,
            "communication_score": communication_score,
            "overall_score": overall_score,
            "rolling_12m_avg": rolling_avg,
            "total_orders": total_orders if conn is None or record_id else 1,
            "weights": WEIGHTS,
        }

    # ------------------------------------------------------------------
    # get_vendor_score
    # ------------------------------------------------------------------
    def get_vendor_score(self, vendor_id: str) -> Dict[str, Any]:
        """
        Return the current rolling 12-month average score and dimension
        averages for *vendor_id*.
        """
        conn = None
        try:
            conn = _get_conn()
            twelve_months_ago = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m")
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        vendor_id,
                        MAX(vendor_name)                         AS vendor_name,
                        COUNT(*)                                 AS total_evaluations,
                        ROUND(AVG(delivery_accuracy_score), 2)   AS avg_delivery_accuracy,
                        ROUND(AVG(on_time_delivery_score), 2)    AS avg_on_time_delivery,
                        ROUND(AVG(quality_score), 2)             AS avg_quality,
                        ROUND(AVG(invoice_accuracy_score), 2)    AS avg_invoice_accuracy,
                        ROUND(AVG(communication_score), 2)       AS avg_communication,
                        ROUND(AVG(overall_score), 2)             AS rolling_12m_avg,
                        MAX(total_orders)                        AS total_orders,
                        MAX(total_on_time)                       AS total_on_time,
                        MAX(total_quality_pass)                  AS total_quality_pass,
                        MAX(total_invoice_accurate)              AS total_invoice_accurate,
                        MAX(created_at)                          AS last_scored_at
                    FROM vendor_scorecard
                    WHERE vendor_id = %s
                      AND evaluation_period >= %s
                    GROUP BY vendor_id
                    """,
                    (vendor_id, twelve_months_ago),
                )
                row = cur.fetchone()
                if not row:
                    return {
                        "vendor_id": vendor_id,
                        "found": False,
                        "message": f"No scorecard data found for vendor {vendor_id} in the last 12 months.",
                    }

                result = dict(row)
                # Coerce Decimals
                for k, v in result.items():
                    if isinstance(v, Decimal):
                        result[k] = float(v)
                result["found"] = True

                # Determine rating tier
                avg = result.get("rolling_12m_avg", 0) or 0
                if avg >= 90:
                    result["tier"] = "Preferred"
                elif avg >= 75:
                    result["tier"] = "Approved"
                elif avg >= 50:
                    result["tier"] = "Conditional"
                else:
                    result["tier"] = "Under Review"

                return result

        except Exception as exc:
            logger.error("[VendorScorecard] get_vendor_score failed: %s", exc)
            return {"vendor_id": vendor_id, "found": False, "error": str(exc)}
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # get_vendor_rankings
    # ------------------------------------------------------------------
    def get_vendor_rankings(self, limit: int = 20) -> Dict[str, Any]:
        """
        Return top and bottom vendors by rolling 12-month average score.
        """
        conn = None
        try:
            conn = _get_conn()
            twelve_months_ago = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m")
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        vendor_id,
                        MAX(vendor_name)                       AS vendor_name,
                        COUNT(*)                               AS evaluations,
                        ROUND(AVG(overall_score), 2)           AS avg_overall,
                        ROUND(AVG(delivery_accuracy_score), 2) AS avg_delivery,
                        ROUND(AVG(on_time_delivery_score), 2)  AS avg_on_time,
                        ROUND(AVG(quality_score), 2)           AS avg_quality,
                        ROUND(AVG(invoice_accuracy_score), 2)  AS avg_invoice,
                        ROUND(AVG(communication_score), 2)     AS avg_comm,
                        MAX(created_at)                        AS last_scored_at
                    FROM vendor_scorecard
                    WHERE evaluation_period >= %s
                    GROUP BY vendor_id
                    HAVING COUNT(*) >= 1
                    ORDER BY avg_overall DESC
                    """,
                    (twelve_months_ago,),
                )
                all_vendors = _rows(cur)

            top_vendors    = all_vendors[:limit]
            bottom_vendors = list(reversed(all_vendors[-limit:])) if len(all_vendors) > limit else list(reversed(all_vendors))

            # Assign tiers
            for v in top_vendors + bottom_vendors:
                avg = v.get("avg_overall", 0) or 0
                if avg >= 90:
                    v["tier"] = "Preferred"
                elif avg >= 75:
                    v["tier"] = "Approved"
                elif avg >= 50:
                    v["tier"] = "Conditional"
                else:
                    v["tier"] = "Under Review"

            return {
                "as_of": datetime.now(timezone.utc).isoformat(),
                "window": "rolling_12_months",
                "total_vendors_scored": len(all_vendors),
                "top_vendors": top_vendors,
                "bottom_vendors": bottom_vendors,
            }

        except Exception as exc:
            logger.error("[VendorScorecard] get_vendor_rankings failed: %s", exc)
            return {"error": str(exc), "top_vendors": [], "bottom_vendors": []}
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # get_scorecard_history
    # ------------------------------------------------------------------
    def get_scorecard_history(self, vendor_id: str, limit: int = 20) -> Dict[str, Any]:
        """
        Return chronological history of scorecard entries for a vendor.
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        id, vendor_id, vendor_name, evaluation_period,
                        po_number, grn_number,
                        delivery_accuracy_score, on_time_delivery_score,
                        quality_score, invoice_accuracy_score, communication_score,
                        overall_score, rolling_12m_avg,
                        total_orders, total_on_time, total_quality_pass,
                        total_invoice_accurate,
                        feedback_notes, scored_by, created_at
                    FROM vendor_scorecard
                    WHERE vendor_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (vendor_id, limit),
                )
                rows = _rows(cur)

            return {
                "vendor_id": vendor_id,
                "total_records": len(rows),
                "history": rows,
            }

        except Exception as exc:
            logger.error("[VendorScorecard] get_scorecard_history failed: %s", exc)
            return {"vendor_id": vendor_id, "total_records": 0, "history": [], "error": str(exc)}
        finally:
            if conn:
                conn.close()


# ═══════════════════════════════════════════════════════════════════════════
#  G-11: Early Payment Discount Service
# ═══════════════════════════════════════════════════════════════════════════

class EarlyPaymentDiscountService:
    """
    Evaluates early-payment discount opportunities on approved invoices.
    Calculates annualised cost-of-capital to help decide whether taking
    the discount is financially advantageous.
    """

    # ------------------------------------------------------------------
    # check_discount_eligibility
    # ------------------------------------------------------------------
    def check_discount_eligibility(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check whether an invoice qualifies for early payment discount.

        invoice_data keys:
            invoice_number   str
            vendor_id        str
            vendor_name      str
            invoice_total    float
            payment_terms    str   e.g. "2/10 Net 30"
            due_date         str   ISO date
            ap_status        str   e.g. "Approved"
            invoice_date     str   ISO date

        Returns eligibility result with discount amount and annualised rate.
        """
        invoice_number = str(invoice_data.get("invoice_number", ""))
        payment_terms  = str(invoice_data.get("payment_terms", ""))
        invoice_total  = float(invoice_data.get("invoice_total", 0))
        ap_status      = str(invoice_data.get("ap_status", "")).lower()
        due_date_str   = str(invoice_data.get("due_date", ""))
        invoice_date_str = str(invoice_data.get("invoice_date", ""))

        result = {
            "invoice_number": invoice_number,
            "vendor_id": invoice_data.get("vendor_id"),
            "vendor_name": invoice_data.get("vendor_name"),
            "invoice_total": invoice_total,
            "payment_terms": payment_terms,
            "eligible": False,
            "reason": "",
        }

        # Only approved / pending invoices qualify
        if ap_status not in ("approved", "pending", "matched"):
            result["reason"] = f"Invoice status '{ap_status}' is not eligible for early payment."
            return result

        # Parse payment terms like "2/10 Net 30"
        discount_pct, discount_days, net_days = self._parse_payment_terms(payment_terms)
        if discount_pct is None:
            result["reason"] = f"Payment terms '{payment_terms}' do not specify an early-payment discount."
            return result

        # Calculate days remaining until discount deadline
        try:
            invoice_date = date.fromisoformat(invoice_date_str)
        except (ValueError, TypeError):
            invoice_date = date.today() - timedelta(days=7)

        try:
            due_date = date.fromisoformat(due_date_str)
        except (ValueError, TypeError):
            due_date = invoice_date + timedelta(days=net_days)

        discount_deadline = invoice_date + timedelta(days=discount_days)
        today = date.today()
        days_until_discount_deadline = (discount_deadline - today).days
        days_until_due = (due_date - today).days

        if days_until_discount_deadline < 0:
            result["reason"] = (
                f"Discount window expired {abs(days_until_discount_deadline)} day(s) ago "
                f"(deadline was {discount_deadline.isoformat()})."
            )
            return result

        # Calculate discount
        days_early = max(days_until_due - days_until_discount_deadline, 0)
        if days_early == 0:
            days_early = net_days - discount_days  # fallback

        calc = self.calculate_discount(invoice_total, discount_pct, days_early)

        result.update({
            "eligible": True,
            "discount_pct": discount_pct,
            "discount_days": discount_days,
            "net_days": net_days,
            "discount_deadline": discount_deadline.isoformat(),
            "days_until_discount_deadline": days_until_discount_deadline,
            "days_until_due": days_until_due,
            **calc,
            "recommendation": (
                "TAKE discount"
                if calc.get("annualized_rate", 0) > 10
                else "EVALUATE — annualised rate is modest"
            ),
        })
        return result

    # ------------------------------------------------------------------
    # calculate_discount
    # ------------------------------------------------------------------
    def calculate_discount(
        self,
        invoice_amount: float,
        discount_pct: float,
        days_early: int,
    ) -> Dict[str, Any]:
        """
        Calculate the discount amount and annualised cost of capital.

        Annualised rate = (discount% / (100 - discount%)) * (365 / days_early)
        E.g. 2/10 Net 30 => (2/98) * (365/20) = 37.24% annualised
        """
        discount_amount = round(invoice_amount * (discount_pct / 100), 2)
        net_payable     = round(invoice_amount - discount_amount, 2)
        savings         = discount_amount

        if days_early > 0 and discount_pct < 100:
            annualized_rate = round(
                (discount_pct / (100 - discount_pct)) * (365 / days_early) * 100, 2
            )
        else:
            annualized_rate = 0.0

        return {
            "discount_amount": discount_amount,
            "net_payable": net_payable,
            "savings": savings,
            "days_early": days_early,
            "annualized_rate": annualized_rate,
        }

    # ------------------------------------------------------------------
    # get_discount_opportunities
    # ------------------------------------------------------------------
    def get_discount_opportunities(self, limit: int = 20) -> Dict[str, Any]:
        """
        Scan approved invoices for early-payment discount opportunities.
        Returns a ranked list (highest annualised savings first).
        """
        conn = None
        opportunities: List[Dict[str, Any]] = []
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        invoice_no       AS invoice_number,
                        vendor_id,
                        vendor_name,
                        invoice_total,
                        payment_terms,
                        due_date,
                        ap_status,
                        invoice_date
                    FROM vendor_invoices
                    WHERE ap_status IN ('Approved', 'Pending', 'Matched')
                      AND payment_terms IS NOT NULL
                      AND payment_terms != ''
                      AND due_date >= CURRENT_DATE
                    ORDER BY invoice_total DESC
                    LIMIT %s
                    """,
                    (limit * 3,),  # fetch more, then filter eligible
                )
                rows = _rows(cur)

            for row in rows:
                inv_data = {
                    "invoice_number": row.get("invoice_number"),
                    "vendor_id": row.get("vendor_id"),
                    "vendor_name": row.get("vendor_name"),
                    "invoice_total": row.get("invoice_total", 0),
                    "payment_terms": row.get("payment_terms", ""),
                    "due_date": str(row.get("due_date", "")),
                    "ap_status": row.get("ap_status", ""),
                    "invoice_date": str(row.get("invoice_date", "")),
                }
                result = self.check_discount_eligibility(inv_data)
                if result.get("eligible"):
                    opportunities.append(result)

                if len(opportunities) >= limit:
                    break

            # Sort by annualised rate descending (best opportunities first)
            opportunities.sort(key=lambda x: x.get("annualized_rate", 0), reverse=True)

            total_potential_savings = sum(o.get("savings", 0) for o in opportunities)

            return {
                "as_of": datetime.now(timezone.utc).isoformat(),
                "total_opportunities": len(opportunities),
                "total_potential_savings": round(total_potential_savings, 2),
                "opportunities": opportunities[:limit],
            }

        except Exception as exc:
            logger.error("[EarlyPayment] get_discount_opportunities failed: %s", exc)
            return {
                "total_opportunities": 0,
                "total_potential_savings": 0,
                "opportunities": [],
                "error": str(exc),
            }
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # Internal: parse payment terms
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_payment_terms(terms: str):
        """
        Parse common payment-term formats:
          "2/10 Net 30"  => (2.0, 10, 30)
          "1.5/15 Net 45" => (1.5, 15, 45)
          "Net 30"        => (None, None, 30)

        Returns (discount_pct, discount_days, net_days) or (None, None, None).
        """
        if not terms:
            return None, None, None

        import re

        terms_clean = terms.strip().upper()

        # Pattern: X/Y NET Z
        m = re.match(r"(\d+(?:\.\d+)?)\s*/\s*(\d+)\s+NET\s+(\d+)", terms_clean)
        if m:
            return float(m.group(1)), int(m.group(2)), int(m.group(3))

        # Pattern: NET Z  (no discount)
        m = re.match(r"NET\s+(\d+)", terms_clean)
        if m:
            return None, None, int(m.group(1))

        return None, None, None


# ═══════════════════════════════════════════════════════════════════════════
#  G-12: Accrual Service (GRNi — Goods Received Not Invoiced)
# ═══════════════════════════════════════════════════════════════════════════

class AccrualService:
    """
    Manages GRNi accruals for period-end close:
      - Create accrual entries when goods are received but not yet invoiced
      - Auto-reverse at period start
      - Query outstanding accruals
    """

    # ------------------------------------------------------------------
    # create_grni_accrual
    # ------------------------------------------------------------------
    def create_grni_accrual(
        self,
        grn_number: str,
        po_number: str,
        vendor_id: str,
        vendor_name: str,
        amount: float,
        gl_account: str,
        cost_center: str,
        fiscal_period: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """
        Create a GRNi accrual entry for goods received but not yet invoiced.

        Returns the created accrual record.
        """
        now = datetime.now(timezone.utc)
        if fiscal_period is None:
            fiscal_period = now.strftime("%Y-%m")
        if fiscal_year is None:
            fiscal_year = now.year

        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check for existing unversed accrual for same GRN + period
                cur.execute(
                    """
                    SELECT id FROM accrual_entries
                    WHERE grn_number = %s
                      AND fiscal_period = %s
                      AND fiscal_year = %s
                      AND accrual_type = 'grni'
                      AND reversed = FALSE
                    LIMIT 1
                    """,
                    (grn_number, fiscal_period, fiscal_year),
                )
                existing = cur.fetchone()
                if existing:
                    return {
                        "created": False,
                        "message": (
                            f"Active GRNi accrual already exists for GRN {grn_number} "
                            f"in period {fiscal_period}/{fiscal_year} (id={existing['id']})."
                        ),
                        "existing_id": existing["id"],
                    }

                cur.execute(
                    """
                    INSERT INTO accrual_entries (
                        accrual_type, grn_number, po_number,
                        vendor_id, vendor_name,
                        gl_account, cost_center,
                        amount, currency,
                        fiscal_period, fiscal_year,
                        posted_by, posted_at, created_at
                    ) VALUES (
                        'grni', %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        'system', NOW(), NOW()
                    )
                    RETURNING *
                    """,
                    (
                        grn_number, po_number,
                        vendor_id, vendor_name,
                        gl_account, cost_center,
                        amount, currency,
                        fiscal_period, fiscal_year,
                    ),
                )
                row = cur.fetchone()
                conn.commit()

                record = dict(row) if row else {}
                for k, v in record.items():
                    if isinstance(v, Decimal):
                        record[k] = float(v)

                record["created"] = True
                logger.info(
                    "[AccrualService] Created GRNi accrual id=%s for GRN %s amount=%s %s",
                    record.get("id"), grn_number, amount, currency,
                )
                return record

        except Exception as exc:
            logger.error("[AccrualService] create_grni_accrual failed: %s", exc)
            if conn:
                conn.rollback()
            return {"created": False, "error": str(exc)}
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # reverse_accrual
    # ------------------------------------------------------------------
    def reverse_accrual(self, accrual_id: int) -> Dict[str, Any]:
        """
        Create a reversal entry for an existing accrual and mark the
        original as reversed.
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Fetch original
                cur.execute(
                    """
                    SELECT * FROM accrual_entries WHERE id = %s
                    """,
                    (accrual_id,),
                )
                original = cur.fetchone()
                if not original:
                    return {"reversed": False, "error": f"Accrual {accrual_id} not found."}

                if original["reversed"]:
                    return {
                        "reversed": False,
                        "error": f"Accrual {accrual_id} is already reversed.",
                    }

                # Insert reversal entry (negative amount)
                reversal_amount = -1 * abs(float(original["amount"]))
                cur.execute(
                    """
                    INSERT INTO accrual_entries (
                        accrual_type, grn_number, po_number,
                        vendor_id, vendor_name,
                        gl_account, cost_center,
                        amount, currency,
                        fiscal_period, fiscal_year,
                        reversal_of,
                        posted_by, posted_at, created_at
                    ) VALUES (
                        'reversal', %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        'system', NOW(), NOW()
                    )
                    RETURNING id
                    """,
                    (
                        original["grn_number"], original["po_number"],
                        original["vendor_id"], original["vendor_name"],
                        original["gl_account"], original["cost_center"],
                        reversal_amount, original.get("currency", "USD"),
                        original["fiscal_period"], original["fiscal_year"],
                        accrual_id,
                    ),
                )
                reversal_row = cur.fetchone()
                reversal_id = reversal_row["id"] if reversal_row else None

                # Mark original as reversed
                cur.execute(
                    """
                    UPDATE accrual_entries
                    SET reversed = TRUE, reversed_at = NOW()
                    WHERE id = %s
                    """,
                    (accrual_id,),
                )
                conn.commit()

                logger.info(
                    "[AccrualService] Reversed accrual id=%s => reversal id=%s",
                    accrual_id, reversal_id,
                )
                return {
                    "reversed": True,
                    "original_accrual_id": accrual_id,
                    "reversal_entry_id": reversal_id,
                    "reversal_amount": reversal_amount,
                }

        except Exception as exc:
            logger.error("[AccrualService] reverse_accrual failed: %s", exc)
            if conn:
                conn.rollback()
            return {"reversed": False, "error": str(exc)}
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # run_period_end_accruals
    # ------------------------------------------------------------------
    def run_period_end_accruals(
        self,
        fiscal_period: str,
        fiscal_year: int,
    ) -> Dict[str, Any]:
        """
        Find all GRNs that have no corresponding invoice and create
        GRNi accrual entries for the specified fiscal period.

        Logic:
          1. SELECT grn_headers LEFT JOIN vendor_invoices ON grn_number
          2. WHERE invoice is NULL (goods received, not invoiced)
          3. JOIN po to get GL account and cost center
          4. Create accrual entry per unmatched GRN
        """
        conn = None
        created = []
        skipped = []
        errors  = []
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Find GRNs without matching invoices
                cur.execute(
                    """
                    SELECT
                        gh.grn_number,
                        gh.po_reference                          AS po_number,
                        gh.vendor_id,
                        gh.vendor_name,
                        COALESCE(
                            SUM(gli.line_value),
                            gh.total_weight_kg * 10              -- fallback estimate
                        )                                        AS grn_value,
                        COALESCE(
                            MAX(pli.gl_account),
                            '210000'                             -- default AP GL
                        )                                        AS gl_account,
                        COALESCE(
                            MAX(pli.cost_center),
                            'GENERAL'
                        )                                        AS cost_center
                    FROM grn_headers gh
                    LEFT JOIN vendor_invoices vi
                        ON vi.grn_reference = gh.grn_number
                    LEFT JOIN grn_line_items gli
                        ON gli.grn_number = gh.grn_number
                    LEFT JOIN po_line_items pli
                        ON pli.po_number = gh.po_reference
                    WHERE vi.id IS NULL
                      AND gh.grn_status IN ('Complete', 'Partial')
                    GROUP BY gh.grn_number, gh.po_reference,
                             gh.vendor_id, gh.vendor_name, gh.total_weight_kg
                    ORDER BY gh.grn_number
                    """
                )
                unmatched_grns = _rows(cur)

            # Create accruals for each unmatched GRN
            for grn in unmatched_grns:
                grn_value = grn.get("grn_value") or 0
                if grn_value <= 0:
                    skipped.append({
                        "grn_number": grn["grn_number"],
                        "reason": "zero or negative value",
                    })
                    continue

                result = self.create_grni_accrual(
                    grn_number=grn["grn_number"],
                    po_number=grn.get("po_number", ""),
                    vendor_id=grn.get("vendor_id", ""),
                    vendor_name=grn.get("vendor_name", ""),
                    amount=grn_value,
                    gl_account=grn.get("gl_account", "210000"),
                    cost_center=grn.get("cost_center", "GENERAL"),
                    fiscal_period=fiscal_period,
                    fiscal_year=fiscal_year,
                )
                if result.get("created"):
                    created.append(result)
                elif result.get("error"):
                    errors.append({
                        "grn_number": grn["grn_number"],
                        "error": result["error"],
                    })
                else:
                    skipped.append({
                        "grn_number": grn["grn_number"],
                        "reason": result.get("message", "already exists"),
                    })

            total_accrued = sum(c.get("amount", 0) for c in created)

            logger.info(
                "[AccrualService] Period-end accruals for %s/%s: created=%d, skipped=%d, errors=%d, total=%s",
                fiscal_period, fiscal_year, len(created), len(skipped), len(errors), total_accrued,
            )

            return {
                "fiscal_period": fiscal_period,
                "fiscal_year": fiscal_year,
                "unmatched_grns_found": len(unmatched_grns),
                "accruals_created": len(created),
                "accruals_skipped": len(skipped),
                "accruals_errors": len(errors),
                "total_accrued_amount": round(total_accrued, 2),
                "created": created,
                "skipped": skipped,
                "errors": errors,
            }

        except Exception as exc:
            logger.error("[AccrualService] run_period_end_accruals failed: %s", exc)
            if conn:
                conn.rollback()
            return {
                "fiscal_period": fiscal_period,
                "fiscal_year": fiscal_year,
                "error": str(exc),
                "accruals_created": 0,
            }
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # run_period_start_reversals
    # ------------------------------------------------------------------
    def run_period_start_reversals(
        self,
        fiscal_period: str,
        fiscal_year: int,
    ) -> Dict[str, Any]:
        """
        Reverse all GRNi accruals from the specified period that have not
        yet been reversed. Typically run at the start of the new period.
        """
        conn = None
        reversed_entries = []
        errors = []
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, grn_number, amount
                    FROM accrual_entries
                    WHERE accrual_type = 'grni'
                      AND fiscal_period = %s
                      AND fiscal_year = %s
                      AND reversed = FALSE
                    ORDER BY id
                    """,
                    (fiscal_period, fiscal_year),
                )
                pending = _rows(cur)

            for entry in pending:
                result = self.reverse_accrual(entry["id"])
                if result.get("reversed"):
                    reversed_entries.append({
                        "original_id": entry["id"],
                        "grn_number": entry.get("grn_number"),
                        "reversal_id": result.get("reversal_entry_id"),
                        "amount": result.get("reversal_amount"),
                    })
                else:
                    errors.append({
                        "accrual_id": entry["id"],
                        "error": result.get("error", "unknown"),
                    })

            total_reversed = sum(abs(r.get("amount", 0)) for r in reversed_entries)

            logger.info(
                "[AccrualService] Period-start reversals for %s/%s: reversed=%d, errors=%d, total=%s",
                fiscal_period, fiscal_year, len(reversed_entries), len(errors), total_reversed,
            )

            return {
                "fiscal_period": fiscal_period,
                "fiscal_year": fiscal_year,
                "accruals_found": len(pending),
                "accruals_reversed": len(reversed_entries),
                "reversal_errors": len(errors),
                "total_reversed_amount": round(total_reversed, 2),
                "reversed": reversed_entries,
                "errors": errors,
            }

        except Exception as exc:
            logger.error("[AccrualService] run_period_start_reversals failed: %s", exc)
            return {
                "fiscal_period": fiscal_period,
                "fiscal_year": fiscal_year,
                "error": str(exc),
                "accruals_reversed": 0,
            }
        finally:
            if conn:
                conn.close()

    # ------------------------------------------------------------------
    # get_outstanding_accruals
    # ------------------------------------------------------------------
    def get_outstanding_accruals(
        self,
        fiscal_period: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all unreversed accrual entries, optionally filtered to a
        specific fiscal period (e.g. "2026-03").
        """
        conn = None
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if fiscal_period:
                    cur.execute(
                        """
                        SELECT
                            ae.id, ae.accrual_type, ae.grn_number, ae.po_number,
                            ae.vendor_id, ae.vendor_name,
                            ae.gl_account, ae.cost_center,
                            ae.amount, ae.currency,
                            ae.fiscal_period, ae.fiscal_year,
                            ae.posted_by, ae.posted_at, ae.created_at
                        FROM accrual_entries ae
                        WHERE ae.accrual_type = 'grni'
                          AND ae.reversed = FALSE
                          AND ae.fiscal_period = %s
                        ORDER BY ae.amount DESC
                        """,
                        (fiscal_period,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            ae.id, ae.accrual_type, ae.grn_number, ae.po_number,
                            ae.vendor_id, ae.vendor_name,
                            ae.gl_account, ae.cost_center,
                            ae.amount, ae.currency,
                            ae.fiscal_period, ae.fiscal_year,
                            ae.posted_by, ae.posted_at, ae.created_at
                        FROM accrual_entries ae
                        WHERE ae.accrual_type = 'grni'
                          AND ae.reversed = FALSE
                        ORDER BY ae.fiscal_period DESC, ae.amount DESC
                        """
                    )
                rows = _rows(cur)

            total_outstanding = sum(r.get("amount", 0) for r in rows)

            # Group by vendor for summary
            vendor_summary: Dict[str, Dict] = {}
            for r in rows:
                vid = r.get("vendor_id", "unknown")
                if vid not in vendor_summary:
                    vendor_summary[vid] = {
                        "vendor_id": vid,
                        "vendor_name": r.get("vendor_name", ""),
                        "total_accrued": 0.0,
                        "entry_count": 0,
                    }
                vendor_summary[vid]["total_accrued"] += r.get("amount", 0)
                vendor_summary[vid]["entry_count"] += 1

            # Sort vendors by total accrued descending
            top_vendors = sorted(
                vendor_summary.values(),
                key=lambda x: x["total_accrued"],
                reverse=True,
            )

            return {
                "as_of": datetime.now(timezone.utc).isoformat(),
                "fiscal_period_filter": fiscal_period,
                "total_outstanding_accruals": len(rows),
                "total_outstanding_amount": round(total_outstanding, 2),
                "by_vendor": top_vendors[:20],
                "entries": rows,
            }

        except Exception as exc:
            logger.error("[AccrualService] get_outstanding_accruals failed: %s", exc)
            return {
                "total_outstanding_accruals": 0,
                "total_outstanding_amount": 0,
                "entries": [],
                "error": str(exc),
            }
        finally:
            if conn:
                conn.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Singleton Factories
# ═══════════════════════════════════════════════════════════════════════════

_scorecard_service: Optional[VendorScorecardService] = None
_early_payment_service: Optional[EarlyPaymentDiscountService] = None
_accrual_service: Optional[AccrualService] = None


def get_scorecard_service() -> VendorScorecardService:
    """Return the singleton VendorScorecardService instance."""
    global _scorecard_service
    if _scorecard_service is None:
        _scorecard_service = VendorScorecardService()
    return _scorecard_service


def get_early_payment_service() -> EarlyPaymentDiscountService:
    """Return the singleton EarlyPaymentDiscountService instance."""
    global _early_payment_service
    if _early_payment_service is None:
        _early_payment_service = EarlyPaymentDiscountService()
    return _early_payment_service


def get_accrual_service() -> AccrualService:
    """Return the singleton AccrualService instance."""
    global _accrual_service
    if _accrual_service is None:
        _accrual_service = AccrualService()
    return _accrual_service
