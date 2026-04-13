"""
Gap Features API Routes — Dev Spec 2.0
========================================
Endpoints for G-01 through G-14 gap features.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gaps", tags=["gap-features"])
DB_URL = os.environ.get('DATABASE_URL')

# ══════════════════════════════════════════════════════════════════════════════
# G-01: Vendor KYC & Onboarding
# ══════════════════════════════════════════════════════════════════════════════

class VendorKYCRequest(BaseModel):
    vendor_id: str
    vendor_name: str
    contact_email: Optional[str] = ''
    category: Optional[str] = ''
    country: Optional[str] = ''
    registration_number: Optional[str] = ''
    tax_id: Optional[str] = ''
    bank_name: Optional[str] = ''
    bank_account_no: Optional[str] = ''
    iban_swift: Optional[str] = ''
    insurance_expiry: Optional[str] = None
    registration_certificate: Optional[bool] = False
    tax_certificate: Optional[bool] = False

@router.post("/kyc/check")
async def check_vendor_kyc(body: VendorKYCRequest):
    """Run KYC validation on a vendor."""
    try:
        from backend.agents.vendor_onboarding_agent import onboard_vendor
        result = await onboard_vendor(body.dict())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/kyc/status/{vendor_id}")
async def get_kyc_status(vendor_id: str):
    """Get KYC status for a vendor."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM vendor_kyc
            WHERE vendor_id = %s
            ORDER BY created_at DESC LIMIT 1
        """, (vendor_id,))
        row = cur.fetchone()
        if not row:
            return {"status": "no_kyc_record", "vendor_id": vendor_id}
        result = dict(row)
        # Serialize datetimes and Decimals
        for k, v in result.items():
            if hasattr(v, 'isoformat'):
                result[k] = v.isoformat()
            elif isinstance(v, __import__('decimal').Decimal):
                result[k] = float(v)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@router.get("/kyc/expiring")
async def get_expiring_kyc(days: int = 30):
    """Get vendors with KYC expiring within N days."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT vendor_id, kyc_status, expiry_date, compliance_score
            FROM vendor_kyc
            WHERE expiry_date IS NOT NULL
              AND expiry_date <= CURRENT_DATE + INTERVAL '%s days'
              AND kyc_status = 'approved'
            ORDER BY expiry_date ASC
        """, (days,))
        rows = cur.fetchall()
        return {"count": len(rows), "expiring_vendors": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# G-02: Contract Linkage on PO
# ══════════════════════════════════════════════════════════════════════════════

class ContractValidationRequest(BaseModel):
    po_number: str
    vendor_id: Optional[str] = ''
    vendor_name: str
    items: Optional[List[Dict[str, Any]]] = []
    total_amount: Optional[float] = 0

@router.post("/contract/validate-po")
async def validate_po_contract(body: ContractValidationRequest):
    """Validate PO prices against active contracts."""
    try:
        from backend.services.contract_linkage_service import get_contract_linkage_service
        svc = get_contract_linkage_service()
        return svc.validate_po_against_contract(body.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/contract/maverick-check/{po_number}")
async def check_maverick_spend(po_number: str, vendor_name: str = '', amount: float = 0):
    """Check if a PO is maverick spend (no contract)."""
    try:
        from backend.services.contract_linkage_service import get_contract_linkage_service
        svc = get_contract_linkage_service()
        return svc.check_maverick_spend(po_number, vendor_name, amount)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/contract/links/{po_number}")
async def get_po_contract_links(po_number: str):
    """Get contract links for a PO."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT * FROM po_contract_link WHERE po_number = %s ORDER BY created_at DESC
        """, (po_number,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, 'isoformat'): d[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): d[k] = float(v)
            result.append(d)
        return {"po_number": po_number, "links": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# G-03: Goods Returns & Debit Notes
# ══════════════════════════════════════════════════════════════════════════════

class GoodsReturnRequest(BaseModel):
    grn_number: Optional[str] = ''
    po_number: Optional[str] = ''
    vendor_id: Optional[str] = ''
    vendor_name: str
    return_reason: str = 'quality_failure'
    return_type: str = 'full_return'
    items: Optional[List[Dict[str, Any]]] = []
    total_return_qty: Optional[float] = 1
    total_return_value: Optional[float] = 0
    notes: Optional[str] = ''

@router.post("/returns/create")
async def create_goods_return(body: GoodsReturnRequest):
    """Create a goods return with automatic debit note generation."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        return_number = f"RET-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        debit_note_number = f"DN-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        cur.execute("""
            INSERT INTO grn_returns (
                return_number, grn_number, po_number, vendor_id, vendor_name,
                return_reason, return_type, items, total_return_qty, total_return_value,
                debit_note_number, debit_note_amount, debit_note_status,
                status, initiated_by, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'issued', 'initiated', 'system', %s)
            RETURNING *
        """, (
            return_number, body.grn_number, body.po_number, body.vendor_id, body.vendor_name,
            body.return_reason, body.return_type, json.dumps(body.items),
            body.total_return_qty, body.total_return_value,
            debit_note_number, body.total_return_value, body.notes
        ))
        row = dict(cur.fetchone())
        conn.commit()

        # Send vendor communication
        try:
            from backend.services.vendor_communication_service import get_vendor_comm_service
            comm_svc = get_vendor_comm_service()
            comm_svc.send_debit_note(return_number, body.vendor_name, body.vendor_id, body.total_return_value, body.return_reason)
        except Exception:
            pass

        for k, v in row.items():
            if hasattr(v, 'isoformat'): row[k] = v.isoformat()
            elif isinstance(v, __import__('decimal').Decimal): row[k] = float(v)

        return {
            "status": "success",
            "return_number": return_number,
            "debit_note_number": debit_note_number,
            "debit_note_amount": body.total_return_value,
            "message": f"Return {return_number} created. Debit note {debit_note_number} issued for ${body.total_return_value:,.2f}.",
            "data": row
        }
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@router.get("/returns/list")
async def list_returns(status: Optional[str] = None, vendor_id: Optional[str] = None, limit: int = 50):
    """List goods returns."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = "SELECT * FROM grn_returns WHERE 1=1"
        params = []
        if status:
            query += " AND status = %s"
            params.append(status)
        if vendor_id:
            query += " AND vendor_id = %s"
            params.append(vendor_id)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(query, params)
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, 'isoformat'): d[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): d[k] = float(v)
            result.append(d)
        return {"count": len(result), "returns": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@router.post("/returns/{return_number}/resolve")
async def resolve_return(return_number: str, resolution: str = 'credit_note', credit_amount: float = 0):
    """Resolve a goods return (credit note, replacement, refund, or write-off)."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            UPDATE grn_returns SET
                credit_resolution = %s, credit_amount = %s,
                status = 'resolved', resolved_at = NOW(), updated_at = NOW()
            WHERE return_number = %s RETURNING *
        """, (resolution, credit_amount, return_number))
        row = cur.fetchone()
        conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail=f"Return {return_number} not found")
        return {"status": "resolved", "return_number": return_number, "resolution": resolution, "credit_amount": credit_amount}
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# G-04: Duplicate Invoice Detection
# ══════════════════════════════════════════════════════════════════════════════

class DuplicateCheckRequest(BaseModel):
    vendor_id: Optional[str] = ''
    vendor_name: str
    invoice_number: str
    amount: float
    currency: str = 'USD'
    invoice_date: Optional[str] = None
    source_channel: Optional[str] = 'portal'

@router.post("/invoice/dedup-check")
async def check_duplicate_invoice(body: DuplicateCheckRequest):
    """Check if an invoice is a potential duplicate."""
    try:
        from backend.services.duplicate_invoice_detector import get_duplicate_detector
        detector = get_duplicate_detector()
        return detector.check(body.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/invoice/dedup-log")
async def get_dedup_log(resolution: Optional[str] = None, limit: int = 50):
    """Get duplicate invoice detection log."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = "SELECT * FROM invoice_dedup_log WHERE 1=1"
        params = []
        if resolution:
            query += " AND resolution = %s"
            params.append(resolution)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(query, params)
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, 'isoformat'): d[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): d[k] = float(v)
            result.append(d)
        return {"count": len(result), "dedup_log": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@router.post("/invoice/dedup-resolve/{dedup_id}")
async def resolve_dedup(dedup_id: int, resolution: str = 'confirmed_duplicate', resolved_by: str = 'system'):
    """Resolve a duplicate invoice detection."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            UPDATE invoice_dedup_log SET resolution = %s, resolved_by = %s, resolved_at = NOW()
            WHERE id = %s RETURNING id, invoice_number, resolution
        """, (resolution, resolved_by, dedup_id))
        row = cur.fetchone()
        conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="Dedup record not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# G-05: Exception Resolution Workflow
# ══════════════════════════════════════════════════════════════════════════════

class CreateExceptionRequest(BaseModel):
    exception_type: str
    severity: str = 'MEDIUM'
    source_document_type: Optional[str] = None
    source_document_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    description: str
    assigned_to: Optional[str] = None

@router.post("/exceptions/create")
async def create_exception(body: CreateExceptionRequest):
    """Create a new exception in the queue."""
    try:
        from backend.services.exception_resolution_service import get_exception_service
        svc = get_exception_service()
        return svc.create_exception(body.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exceptions/open")
async def get_open_exceptions(severity: Optional[str] = None, assigned_to: Optional[str] = None):
    """Get open exceptions."""
    try:
        from backend.services.exception_resolution_service import get_exception_service
        svc = get_exception_service()
        return svc.get_open_exceptions(severity=severity, assigned_to=assigned_to)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exceptions/stats")
async def get_exception_stats():
    """Get exception queue statistics."""
    try:
        from backend.services.exception_resolution_service import get_exception_service
        svc = get_exception_service()
        return svc.get_exception_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/exceptions/{exception_id}/assign")
async def assign_exception(exception_id: str, assignee: str):
    """Assign an exception to a user."""
    try:
        from backend.services.exception_resolution_service import get_exception_service
        svc = get_exception_service()
        return svc.assign_exception(exception_id, assignee)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/exceptions/{exception_id}/resolve")
async def resolve_exception(exception_id: str, resolution_action: str, notes: str = '', resolved_by: str = 'system'):
    """Resolve an exception."""
    try:
        from backend.services.exception_resolution_service import get_exception_service
        svc = get_exception_service()
        return svc.resolve_exception(exception_id, resolution_action, notes, resolved_by)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/exceptions/{exception_id}/escalate")
async def escalate_exception(exception_id: str, reason: str = ''):
    """Escalate an exception."""
    try:
        from backend.services.exception_resolution_service import get_exception_service
        svc = get_exception_service()
        return svc.escalate_exception(exception_id, reason)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/exceptions/check-sla")
async def check_sla_breaches():
    """Check and flag SLA breaches."""
    try:
        from backend.services.exception_resolution_service import get_exception_service
        svc = get_exception_service()
        return svc.check_sla_breaches()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
# G-06: Vendor Communication
# ══════════════════════════════════════════════════════════════════════════════

class VendorCommRequest(BaseModel):
    vendor_id: Optional[str] = ''
    vendor_name: str
    communication_type: str
    document_type: Optional[str] = None
    document_id: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    channel: str = 'email'

@router.post("/vendor-comm/send")
async def send_vendor_communication(body: VendorCommRequest):
    """Send a communication to a vendor."""
    try:
        from backend.services.vendor_communication_service import get_vendor_comm_service
        svc = get_vendor_comm_service()
        return svc.send_communication(
            vendor_id=body.vendor_id, vendor_name=body.vendor_name,
            comm_type=body.communication_type, document_type=body.document_type,
            document_id=body.document_id, subject=body.subject,
            body=body.body, channel=body.channel
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/vendor-comm/history")
async def get_vendor_comm_history(vendor_id: Optional[str] = None, comm_type: Optional[str] = None, limit: int = 50):
    """Get vendor communication history."""
    try:
        from backend.services.vendor_communication_service import get_vendor_comm_service
        svc = get_vendor_comm_service()
        return svc.get_vendor_communications(vendor_id=vendor_id, comm_type=comm_type, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
# G-08: Budget Commitment Reconciliation
# ══════════════════════════════════════════════════════════════════════════════

class BudgetCommitmentRequest(BaseModel):
    department: str
    fiscal_year: Optional[int] = None
    reference_type: str
    reference_id: str
    amount: float
    description: str = ''

@router.post("/budget/commit")
async def record_budget_commitment(body: BudgetCommitmentRequest):
    """Record a budget commitment (PR approved)."""
    try:
        from backend.services.budget_ledger_service import get_budget_ledger_service
        svc = get_budget_ledger_service()
        return svc.record_commitment(
            department=body.department, fiscal_year=body.fiscal_year,
            reference_type=body.reference_type, reference_id=body.reference_id,
            amount=body.amount, description=body.description
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/budget/release")
async def release_budget_commitment(body: BudgetCommitmentRequest):
    """Release a budget commitment (PR/PO cancelled)."""
    try:
        from backend.services.budget_ledger_service import get_budget_ledger_service
        svc = get_budget_ledger_service()
        return svc.release_commitment(
            department=body.department, fiscal_year=body.fiscal_year,
            reference_type=body.reference_type, reference_id=body.reference_id,
            amount=body.amount, description=body.description
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/budget/balance/{department}")
async def get_budget_balance(department: str, fiscal_year: Optional[int] = None):
    """Get department budget balance."""
    try:
        from backend.services.budget_ledger_service import get_budget_ledger_service
        svc = get_budget_ledger_service()
        return svc.get_department_balance(department, fiscal_year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/budget/summary")
async def get_budget_summary(fiscal_year: Optional[int] = None):
    """Get budget summary for all departments."""
    try:
        from backend.services.budget_ledger_service import get_budget_ledger_service
        svc = get_budget_ledger_service()
        return svc.get_budget_summary(fiscal_year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/budget/reconcile/{department}")
async def reconcile_budget(department: str, fiscal_year: Optional[int] = None):
    """Reconcile budget commitments vs actuals."""
    try:
        from backend.services.budget_ledger_service import get_budget_ledger_service
        svc = get_budget_ledger_service()
        return svc.reconcile_department(department, fiscal_year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
# G-10: Vendor Scorecard
# ══════════════════════════════════════════════════════════════════════════════

class ScoreTransactionRequest(BaseModel):
    vendor_id: str
    vendor_name: str
    po_number: Optional[str] = ''
    grn_number: Optional[str] = ''
    ordered_qty: Optional[float] = 0
    received_qty: Optional[float] = 0
    accepted_qty: Optional[float] = 0
    days_late: Optional[int] = 0
    invoice_discrepancy: Optional[str] = 'none'
    response_hours: Optional[float] = 24

@router.post("/scorecard/score")
async def score_vendor_transaction(body: ScoreTransactionRequest):
    """Score a vendor transaction."""
    try:
        from backend.services.vendor_scorecard_service import get_scorecard_service
        svc = get_scorecard_service()
        return svc.score_transaction(
            vendor_id=body.vendor_id, vendor_name=body.vendor_name,
            po_number=body.po_number, grn_number=body.grn_number,
            scoring_data={
                'ordered_qty': body.ordered_qty, 'received_qty': body.received_qty,
                'accepted_qty': body.accepted_qty, 'days_late': body.days_late,
                'invoice_discrepancy': body.invoice_discrepancy,
                'response_hours': body.response_hours,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/scorecard/{vendor_id}")
async def get_vendor_scorecard(vendor_id: str):
    """Get vendor scorecard with rolling average."""
    try:
        from backend.services.vendor_scorecard_service import get_scorecard_service
        svc = get_scorecard_service()
        return svc.get_vendor_score(vendor_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/scorecard/rankings/top")
async def get_vendor_rankings(limit: int = 20):
    """Get vendor rankings."""
    try:
        from backend.services.vendor_scorecard_service import get_scorecard_service
        svc = get_scorecard_service()
        return svc.get_vendor_rankings(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
# G-11: Early Payment Discount
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/early-payment/opportunities")
async def get_early_payment_opportunities(limit: int = 20):
    """Get invoices eligible for early payment discounts."""
    try:
        from backend.services.vendor_scorecard_service import get_early_payment_service
        svc = get_early_payment_service()
        return svc.get_discount_opportunities(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class EarlyPaymentCheckRequest(BaseModel):
    invoice_number: str
    vendor_name: str
    total_amount: float
    payment_terms: str = 'Net 30'
    invoice_date: Optional[str] = None

@router.post("/early-payment/check")
async def check_early_payment(body: EarlyPaymentCheckRequest):
    """Check early payment discount eligibility."""
    try:
        from backend.services.vendor_scorecard_service import get_early_payment_service
        svc = get_early_payment_service()
        return svc.check_discount_eligibility(body.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
# G-12: Accruals
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/accruals/period-end")
async def run_period_end_accruals(fiscal_period: str, fiscal_year: int):
    """Run period-end GRNi accruals."""
    try:
        from backend.services.vendor_scorecard_service import get_accrual_service
        svc = get_accrual_service()
        return svc.run_period_end_accruals(fiscal_period, fiscal_year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/accruals/period-start-reversal")
async def run_period_start_reversals(fiscal_period: str, fiscal_year: int):
    """Run period-start accrual reversals."""
    try:
        from backend.services.vendor_scorecard_service import get_accrual_service
        svc = get_accrual_service()
        return svc.run_period_start_reversals(fiscal_period, fiscal_year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/accruals/outstanding")
async def get_outstanding_accruals(fiscal_period: Optional[str] = None):
    """Get outstanding GRNi accruals."""
    try:
        from backend.services.vendor_scorecard_service import get_accrual_service
        svc = get_accrual_service()
        return svc.get_outstanding_accruals(fiscal_period)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
# G-13: FX Controls
# ══════════════════════════════════════════════════════════════════════════════

class FXLockRequest(BaseModel):
    invoice_number: str
    currency: str
    fx_rate: float
    base_currency: str = 'USD'
    invoice_amount: float

@router.post("/fx/lock-rate")
async def lock_fx_rate(body: FXLockRequest):
    """Lock FX rate for an invoice at approval time."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        base_amount = round(body.invoice_amount * body.fx_rate, 2)
        from datetime import timedelta
        expiry = (datetime.now() + timedelta(days=5)).date()

        cur.execute("""
            UPDATE vendor_invoices SET
                fx_rate_locked = %s, fx_rate_lock_date = NOW(),
                fx_rate_expiry = %s, base_currency_amount = %s
            WHERE invoice_number = %s
            RETURNING invoice_number, fx_rate_locked, fx_rate_expiry, base_currency_amount
        """, (body.fx_rate, expiry, base_amount, body.invoice_number))
        row = cur.fetchone()
        conn.commit()

        # Check exposure threshold
        exposure_warning = None
        if base_amount > 50000:
            exposure_warning = f"FX exposure ${base_amount:,.2f} exceeds $50,000 threshold. Finance approval required."

        return {
            "status": "locked",
            "invoice_number": body.invoice_number,
            "fx_rate": body.fx_rate,
            "base_currency_amount": base_amount,
            "expiry": str(expiry),
            "exposure_warning": exposure_warning,
        }
    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@router.get("/fx/exposure")
async def get_fx_exposure():
    """Get total FX exposure across open invoices."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT currency, COUNT(*) as invoice_count,
                   SUM(total_amount) as total_foreign,
                   SUM(base_currency_amount) as total_base
            FROM vendor_invoices
            WHERE currency != 'USD' AND status NOT IN ('paid', 'cancelled')
              AND fx_rate_locked IS NOT NULL
            GROUP BY currency
        """)
        rows = cur.fetchall()
        result = []
        total_exposure = 0
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if isinstance(v, __import__('decimal').Decimal): d[k] = float(v)
            total_exposure += d.get('total_base', 0) or 0
            result.append(d)
        return {
            "total_exposure_usd": total_exposure,
            "requires_approval": total_exposure > 50000,
            "by_currency": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# G-14: Audit Trail
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/audit/transaction/{document_id}")
async def get_transaction_audit(document_id: str):
    """Get complete audit trail for a transaction (per-transaction trace)."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        audit_trail = []

        # Check agent_actions
        cur.execute("""
            SELECT id, agent_name, action_type, input_data::text, output_data::text,
                   success, created_at
            FROM agent_actions
            WHERE input_data::text ILIKE %s OR output_data::text ILIKE %s
            ORDER BY created_at ASC LIMIT 50
        """, (f'%{document_id}%', f'%{document_id}%'))
        for r in cur.fetchall():
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, 'isoformat'): d[k] = v.isoformat()
            audit_trail.append({**d, 'source': 'agent_actions'})

        # Check workflow_events if table exists
        try:
            cur.execute("""
                SELECT event_type, event_data::text, source_agent, created_at
                FROM workflow_events
                WHERE workflow_run_id = %s OR event_data::text ILIKE %s
                ORDER BY created_at ASC LIMIT 50
            """, (document_id, f'%{document_id}%'))
            for r in cur.fetchall():
                d = dict(r)
                for k, v in d.items():
                    if hasattr(v, 'isoformat'): d[k] = v.isoformat()
                audit_trail.append({**d, 'source': 'workflow_events'})
        except:
            pass

        # Check exception_queue
        try:
            cur.execute("""
                SELECT exception_id, exception_type, severity, status,
                       resolution_action, resolved_at, created_at
                FROM exception_queue
                WHERE source_document_id = %s
                ORDER BY created_at ASC
            """, (document_id,))
            for r in cur.fetchall():
                d = dict(r)
                for k, v in d.items():
                    if hasattr(v, 'isoformat'): d[k] = v.isoformat()
                audit_trail.append({**d, 'source': 'exception_queue'})
        except:
            pass

        # Sort all by created_at
        audit_trail.sort(key=lambda x: x.get('created_at', ''))

        return {
            "document_id": document_id,
            "audit_entries": len(audit_trail),
            "trail": audit_trail,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

@router.get("/audit/compliance-summary")
async def get_compliance_summary():
    """Get policy compliance summary across all transactions."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        summary = {}

        # Maverick spend count
        try:
            cur.execute("SELECT COUNT(*) as count FROM po_contract_link WHERE maverick_flag = TRUE")
            summary['maverick_spend_count'] = cur.fetchone()['count']
        except:
            summary['maverick_spend_count'] = 0

        # Exception stats
        try:
            cur.execute("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE sla_breached) as breached FROM exception_queue")
            row = cur.fetchone()
            summary['total_exceptions'] = row['total']
            summary['sla_breaches'] = row['breached']
        except:
            summary['total_exceptions'] = 0
            summary['sla_breaches'] = 0

        # Duplicate invoices
        try:
            cur.execute("SELECT COUNT(*) as count FROM invoice_dedup_log WHERE resolution = 'confirmed_duplicate'")
            summary['confirmed_duplicates'] = cur.fetchone()['count']
        except:
            summary['confirmed_duplicates'] = 0

        # KYC compliance
        try:
            cur.execute("""
                SELECT kyc_status, COUNT(*) as count
                FROM vendor_kyc GROUP BY kyc_status
            """)
            summary['kyc_status'] = {r['kyc_status']: r['count'] for r in cur.fetchall()}
        except:
            summary['kyc_status'] = {}

        # Returns/debit notes
        try:
            cur.execute("SELECT COUNT(*) as count, SUM(debit_note_amount) as total FROM grn_returns WHERE debit_note_number IS NOT NULL")
            row = cur.fetchone()
            summary['debit_notes_issued'] = row['count']
            summary['debit_notes_total'] = float(row['total'] or 0)
        except:
            summary['debit_notes_issued'] = 0
            summary['debit_notes_total'] = 0

        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# G-09: Partial Delivery (uses existing GRN endpoints enhanced)
# G-07: Spend Analytics (covered by existing SpendAnalyticsAgent)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/delivery/partial-status/{po_number}")
async def get_partial_delivery_status(po_number: str):
    """Get partial delivery status for a PO."""
    conn = None
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get PO header
        cur.execute("""
            SELECT po_number, vendor_name, total_amount, total_qty,
                   delivery_mode, total_received_qty, remaining_qty, delivery_complete
            FROM po_headers WHERE po_number = %s
        """, (po_number,))
        po = cur.fetchone()
        if not po:
            raise HTTPException(status_code=404, detail=f"PO {po_number} not found")
        po_dict = dict(po)
        for k, v in po_dict.items():
            if isinstance(v, __import__('decimal').Decimal): po_dict[k] = float(v)

        # Get GRNs
        cur.execute("""
            SELECT grn_number, grn_type, partial_seq, total_qty as received_qty,
                   cumulative_qty, status, received_date
            FROM grn_headers WHERE po_number = %s ORDER BY partial_seq ASC
        """, (po_number,))
        grns = []
        for r in cur.fetchall():
            d = dict(r)
            for k, v in d.items():
                if hasattr(v, 'isoformat'): d[k] = v.isoformat()
                elif isinstance(v, __import__('decimal').Decimal): d[k] = float(v)
            grns.append(d)

        return {
            "po": po_dict,
            "deliveries": grns,
            "delivery_count": len(grns),
            "is_complete": po_dict.get('delivery_complete', False),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()
