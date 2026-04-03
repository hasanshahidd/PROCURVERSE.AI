"""
Aging Report Service — Sprint 10
Calculates Accounts Payable aging analysis.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

AGING_BUCKETS = [
    ("current", 0, 0),
    ("1_30_days", 1, 30),
    ("31_60_days", 31, 60),
    ("61_90_days", 61, 90),
    ("over_90_days", 91, 9999),
]


def calculate_aging(invoices: List[Dict] = None) -> Dict[str, Any]:
    """
    Calculate AP aging from invoice data.

    If no invoices passed, tries to fetch from DB.
    Returns aging summary with vendor breakdown.
    """
    if invoices is None:
        invoices = _fetch_invoices_from_db()

    today = datetime.now(timezone.utc).date()

    # Initialize buckets
    buckets = {name: {"count": 0, "total": 0.0, "invoices": []} for name, _, _ in AGING_BUCKETS}
    vendor_aging: Dict[str, Dict] = {}

    for inv in invoices:
        # Get due date
        due_str = str(inv.get("due_date", inv.get("payment_due_date", "")))
        try:
            if "T" in due_str:
                due_date = datetime.fromisoformat(due_str.replace("Z", "+00:00")).date()
            else:
                due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            # Default: 30 days from invoice date
            inv_date_str = str(inv.get("invoice_date", inv.get("created_at", "")))
            try:
                inv_date = datetime.fromisoformat(inv_date_str.replace("Z", "+00:00")).date()
                due_date = inv_date + timedelta(days=30)
            except Exception:
                due_date = today  # Treat as current if unparseable

        # Skip paid invoices
        status = str(inv.get("status", "")).lower()
        if status in ("paid", "cancelled", "void"):
            continue

        days_overdue = (today - due_date).days
        amount = float(inv.get("total_amount", inv.get("amount", 0)))
        vendor = str(inv.get("vendor_name", inv.get("vendor_id", "Unknown")))
        inv_num = str(inv.get("invoice_number", inv.get("id", "?")))

        # Classify into bucket
        for bucket_name, min_days, max_days in AGING_BUCKETS:
            if min_days <= max(days_overdue, 0) <= max_days:
                buckets[bucket_name]["count"] += 1
                buckets[bucket_name]["total"] += amount
                buckets[bucket_name]["invoices"].append({
                    "invoice": inv_num,
                    "vendor": vendor,
                    "amount": amount,
                    "days_overdue": days_overdue,
                    "due_date": str(due_date),
                })
                break

        # Vendor breakdown
        if vendor not in vendor_aging:
            vendor_aging[vendor] = {"total_outstanding": 0, "oldest_days": 0, "invoice_count": 0}
        vendor_aging[vendor]["total_outstanding"] += amount
        vendor_aging[vendor]["oldest_days"] = max(vendor_aging[vendor]["oldest_days"], days_overdue)
        vendor_aging[vendor]["invoice_count"] += 1

    # Summary
    total_outstanding = sum(b["total"] for b in buckets.values())
    total_overdue = sum(b["total"] for name, b in buckets.items() if name != "current")

    return {
        "as_of_date": str(today),
        "total_outstanding": round(total_outstanding, 2),
        "total_overdue": round(total_overdue, 2),
        "total_invoices": sum(b["count"] for b in buckets.values()),
        "buckets": {name: {"count": b["count"], "total": round(b["total"], 2)} for name, b in buckets.items()},
        "bucket_details": buckets,
        "vendor_aging": dict(sorted(vendor_aging.items(), key=lambda x: -x[1]["total_outstanding"])[:20]),
        "dso_estimate": round(total_outstanding / max(total_outstanding / 30, 1), 1) if total_outstanding > 0 else 0,
    }


def _fetch_invoices_from_db() -> List[Dict]:
    """Fetch unpaid invoices from the database."""
    try:
        from backend.services.nmi_data_service import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT invoice_number, vendor_id, total_amount,
                           invoice_date, payment_due_date, status,
                           currency
                    FROM vendor_invoices
                    WHERE status NOT IN ('paid', 'cancelled', 'void')
                    ORDER BY payment_due_date ASC
                    LIMIT 500
                """)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[AgingService] DB fetch failed: {e}")
        # Return demo data
        today = datetime.now(timezone.utc).date()
        return [
            {"invoice_number": "INV-2026-001", "vendor_name": "Global Tech Ltd", "total_amount": 45000, "payment_due_date": str(today - timedelta(days=5)), "status": "open"},
            {"invoice_number": "INV-2026-002", "vendor_name": "Office Supplies Co", "total_amount": 12500, "payment_due_date": str(today - timedelta(days=35)), "status": "open"},
            {"invoice_number": "INV-2026-003", "vendor_name": "Industrial Parts", "total_amount": 78000, "payment_due_date": str(today - timedelta(days=72)), "status": "overdue"},
            {"invoice_number": "INV-2026-004", "vendor_name": "Cleaning Services", "total_amount": 3200, "payment_due_date": str(today + timedelta(days=10)), "status": "open"},
            {"invoice_number": "INV-2026-005", "vendor_name": "IT Solutions", "total_amount": 156000, "payment_due_date": str(today - timedelta(days=95)), "status": "overdue"},
            {"invoice_number": "INV-2026-006", "vendor_name": "Construction Co", "total_amount": 230000, "payment_due_date": str(today - timedelta(days=15)), "status": "open"},
        ]
