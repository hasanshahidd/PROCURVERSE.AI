"""
Admin Routes — Operator tooling for P1.5 production hardening.

Currently hosts the drift reconciliation admin surface (R18 / HF-5):

  GET   /admin/drift               — list drift reports (filter by resolution)
  PATCH /admin/drift/{report_id}   — mark a drift report resolved
  POST  /admin/drift/run-now       — trigger an out-of-band reconciliation sweep

These endpoints require authenticated admin access. They are read-mostly —
the only mutating action is a text annotation on an existing drift row.
No session or legacy ERP state is ever mutated from here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.services.rbac import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

class ResolveDriftRequest(BaseModel):
    resolution: str = Field(..., description="Operator note explaining the resolution")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _user_id_of(current_user: Dict[str, Any]) -> str:
    return (
        current_user.get("sub")
        or current_user.get("email")
        or current_user.get("name")
        or "anonymous"
    )


def _fetch_drift_reports(
    status: str,
    session_id: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    from backend.services.nmi_data_service import get_conn
    from psycopg2.extras import RealDictCursor

    clauses: List[str] = []
    params: List[Any] = []

    if status == "unresolved":
        clauses.append("resolution IS NULL")
    elif status == "resolved":
        clauses.append("resolution IS NOT NULL")
    # status == "all" → no clause

    if session_id:
        clauses.append("session_id = %s")
        params.append(session_id)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))

    sql = (
        f"SELECT report_id, session_id, detected_at, session_state, legacy_state, "
        f"resolution, resolved_by, resolved_at "
        f"FROM session_drift_reports {where} "
        f"ORDER BY detected_at DESC LIMIT %s"
    )

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            result: List[Dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                # Serialize datetime fields
                for k, v in list(item.items()):
                    if hasattr(v, "isoformat"):
                        item[k] = v.isoformat()
                # session_id/report_id UUIDs → str
                if item.get("report_id") is not None:
                    item["report_id"] = str(item["report_id"])
                if item.get("session_id") is not None:
                    item["session_id"] = str(item["session_id"])
                result.append(item)
            return result
    finally:
        conn.close()


def _mark_drift_resolved(
    report_id: str,
    resolution: str,
    resolved_by: str,
) -> Optional[Dict[str, Any]]:
    from backend.services.nmi_data_service import get_conn
    from psycopg2.extras import RealDictCursor

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE session_drift_reports
                SET resolution = %s,
                    resolved_by = %s,
                    resolved_at = NOW()
                WHERE report_id = %s
                RETURNING report_id, session_id, detected_at, resolution, resolved_by, resolved_at
                """,
                (resolution, resolved_by, report_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            conn.commit()
            item = dict(row)
            for k, v in list(item.items()):
                if hasattr(v, "isoformat"):
                    item[k] = v.isoformat()
            if item.get("report_id") is not None:
                item["report_id"] = str(item["report_id"])
            if item.get("session_id") is not None:
                item["session_id"] = str(item["session_id"])
            return item
    except Exception as exc:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/drift")
async def list_drift(
    status: str = Query("unresolved", description="'unresolved' | 'resolved' | 'all'"),
    session_id: Optional[str] = Query(None, description="Filter by a specific session"),
    limit: int = Query(50, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """
    List drift reports. By default returns the 50 most recent unresolved
    reports — the view operators watch to measure the P5 gate criterion.
    """
    if status not in ("unresolved", "resolved", "all"):
        raise HTTPException(status_code=400, detail="status must be one of unresolved|resolved|all")

    try:
        reports = _fetch_drift_reports(status=status, session_id=session_id, limit=limit)
    except Exception as exc:
        logger.exception("admin: list_drift failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "reports": reports,
        "count": len(reports),
        "status_filter": status,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.patch("/drift/{report_id}")
async def resolve_drift(
    report_id: str,
    body: ResolveDriftRequest,
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """Mark a drift report resolved with an operator-supplied note."""
    if not body.resolution or not body.resolution.strip():
        raise HTTPException(status_code=400, detail="resolution note is required")

    resolved_by = _user_id_of(current_user)

    try:
        updated = _mark_drift_resolved(report_id, body.resolution.strip(), resolved_by)
    except Exception as exc:
        logger.exception("admin: resolve_drift failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    if not updated:
        raise HTTPException(status_code=404, detail=f"Drift report {report_id} not found")

    return {"success": True, "report": updated}


@router.post("/drift/run-now")
async def run_drift_now(
    current_user: Dict[str, Any] = Depends(require_auth()),
) -> Dict[str, Any]:
    """
    Trigger an out-of-band drift reconciliation sweep. Safe — the job is
    idempotent. Useful when an operator wants to check for drift immediately
    instead of waiting for the 15-minute loop.
    """
    try:
        from backend.jobs.drift_reconciliation import run_drift_reconciliation
        summary = await run_drift_reconciliation()
    except Exception as exc:
        logger.exception("admin: run_drift_now failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"success": True, "summary": summary}
