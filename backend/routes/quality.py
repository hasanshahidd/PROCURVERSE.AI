"""
Data Quality Routes
====================
GET  /api/quality/scan-all    — Scan all ERP tables, return full quality report
GET  /api/quality/scan/{name} — Scan a specific table with detailed column analysis
GET  /api/quality/summary     — Quick summary (scores per ERP, worst tables)
"""

import logging
from typing import Optional
from fastapi import APIRouter, Query, HTTPException

from backend.services.data_quality_service import scan_table, scan_all_erp_tables

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/scan-all")
async def scan_all():
    """Scan all ERP tables for data quality issues. Returns scores per ERP and per table."""
    try:
        report = scan_all_erp_tables()
        return report
    except Exception as e:
        log.error("scan_all failed: %s", e)
        raise HTTPException(500, str(e))


@router.get("/scan/{table_name}")
async def scan_single(table_name: str):
    """Scan a specific table with detailed per-column quality analysis."""
    report = scan_table(table_name)
    if 'error' in report:
        raise HTTPException(404, report['error'])
    return report


@router.get("/summary")
async def quality_summary():
    """Quick summary: overall score, per-ERP scores, worst/best tables."""
    try:
        report = scan_all_erp_tables()
        return {
            'overall_score': report['overall_score'],
            'overall_grade': report['overall_grade'],
            'total_tables': report['total_tables'],
            'total_issues': report['total_issues'],
            'erp_summary': report['erp_summary'],
            'worst_tables': report['worst_tables'],
            'best_tables': report['best_tables'],
            'scanned_at': report['scanned_at'],
        }
    except Exception as e:
        log.error("quality_summary failed: %s", e)
        raise HTTPException(500, str(e))
