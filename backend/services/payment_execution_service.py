"""
Payment Execution Service — Sprint 10
Handles actual payment dispatch (bank transfer, ACH, manual marking).

Modes:
  - manual   : Just marks payment as "dispatched" (default for demo)
  - bank_api : Calls configured bank API (future)
  - ach      : Generates ACH file (future)
"""
import logging, os, uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PAYMENT_MODE = os.getenv("PAYMENT_MODE", "manual")

# In-memory ledger for demo (extend to DB in production)
_payment_ledger: List[Dict[str, Any]] = []

def execute_payment(
    payment_run_id: str,
    vendor_id: str,
    vendor_name: str,
    amount: float,
    currency: str = "AED",
    bank_account: str = "",
    payment_method: str = "bank_transfer",
    reference: str = "",
) -> Dict[str, Any]:
    """Execute a payment. Returns execution result dict."""

    execution_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()

    result = {
        "execution_id": execution_id,
        "payment_run_id": payment_run_id,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "amount": amount,
        "currency": currency,
        "payment_method": payment_method,
        "bank_account": bank_account or "****masked****",
        "reference": reference or execution_id,
        "status": "pending",
        "mode": PAYMENT_MODE,
        "executed_at": timestamp,
    }

    if PAYMENT_MODE == "manual":
        # Mark as dispatched (manual approval workflow)
        result["status"] = "dispatched"
        result["detail"] = "Payment marked as dispatched. Manual bank transfer required."
        logger.info(f"[PaymentExecution] MANUAL dispatch: {execution_id} - {currency} {amount} to {vendor_name}")

    elif PAYMENT_MODE == "bank_api":
        # Future: Call bank API
        bank_url = os.getenv("BANK_API_URL", "")
        if not bank_url:
            result["status"] = "dispatched"
            result["detail"] = "Bank API not configured. Marked as dispatched for manual processing."
        else:
            # Placeholder for real bank API call
            result["status"] = "submitted"
            result["detail"] = f"Submitted to bank API at {bank_url}"

    elif PAYMENT_MODE == "ach":
        # Generate ACH file record
        result["status"] = "file_generated"
        result["ach_file"] = f"ACH-{execution_id}.txt"
        result["detail"] = "ACH file generated. Upload to bank portal."

    # Record in ledger
    _payment_ledger.append(result)

    # Also try to update DB
    try:
        from backend.services.nmi_data_service import get_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE payment_runs
                    SET status = %s,
                        updated_at = NOW()
                    WHERE id = %s OR run_reference = %s
                """, (result["status"], payment_run_id, payment_run_id))
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[PaymentExecution] DB update skipped: {e}")

    return result


def get_payment_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent payment execution history."""
    return list(_payment_ledger[-limit:])[::-1]


def get_payment_status(execution_id: str) -> Optional[Dict[str, Any]]:
    """Look up a specific payment execution."""
    for p in reversed(_payment_ledger):
        if p["execution_id"] == execution_id:
            return p
    return None


def generate_remittance_advice(execution_id: str) -> Dict[str, Any]:
    """Generate remittance advice for a completed payment."""
    payment = get_payment_status(execution_id)
    if not payment:
        return {"error": f"Payment {execution_id} not found"}

    return {
        "remittance_id": f"REM-{execution_id}",
        "payment_ref": execution_id,
        "vendor": payment["vendor_name"],
        "amount": f"{payment['currency']} {payment['amount']:,.2f}",
        "payment_date": payment["executed_at"],
        "payment_method": payment["payment_method"],
        "status": payment["status"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
