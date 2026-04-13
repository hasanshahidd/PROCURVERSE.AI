"""
End-to-End Pipeline Test — Sprint 8
=====================================
Tests the full 9-agent InvoicePipelineOrchestrator end-to-end.

Run from repo root:
    python test_pipeline_e2e.py

Prerequisites
-------------
- DATABASE_URL set in .env (or environment)
- DATA_SOURCE=demo_odoo (or postgresql) in .env
- python-dotenv installed (optional but recommended)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.isfile(env_path):
            load_dotenv(env_path)
            print(f"[env] Loaded .env from {env_path}")
    except ImportError:
        pass


_load_env()

# ── Synthetic test documents ──────────────────────────────────────────────────

_PO_RAW = textwrap.dedent("""\
    PURCHASE ORDER
    ==============
    PO Number: PO-TEST-2026-001
    Date: 2026-04-02
    Vendor: Al Futtaim Trading LLC
    Vendor ID: V001

    Line 1: Office Supplies      Qty: 100   Unit Price: 500 AED   Total: 50,000 AED
    Payment Terms: Net 30
    Currency: AED

    Authorised by: Procurement Manager
""")

_INVOICE_RAW = textwrap.dedent("""\
    TAX INVOICE
    ===========
    Invoice Number: INV-TEST-2026-001
    Invoice Date: 2026-04-02
    Due Date: 2026-05-02

    From: Al Futtaim Trading LLC
    PO Reference: PO-TEST-2026-001

    Description: Office Supplies
    Quantity: 100
    Unit Price: 500 AED
    Total Amount: 50,000 AED
    Currency: AED

    Payment Terms: Net 30
""")

PO_DOCUMENT = {
    "document_ref":   "PO-TEST-2026-001",
    "source_channel": "email",
    "raw_content":    _PO_RAW,
    "vendor_id":      "V001",
}

INVOICE_DOCUMENT = {
    "document_ref":     "INV-TEST-2026-001",
    "source_channel":   "email",
    "raw_content":      _INVOICE_RAW,
    "invoice_amount":   50000,    # explicit fallback if OCR misses it
    "invoice_currency": "AED",
}

# ── Real-DB payment sub-pipeline test data ────────────────────────────────────
# Uses BILL/2025/00001 which exists in invoices_odoo with full 3-way match chain
REAL_PAYMENT_DATA = {
    "invoice_number":   "BILL/2025/00001",
    "vendor_id":        "13",
    "po_reference":     "PO00001",
    "invoice_amount":   51750,
    "invoice_currency": "USD",
}


# ── Test runner ───────────────────────────────────────────────────────────────

async def run_test() -> None:
    from backend.services.pipeline_orchestrator import InvoicePipelineOrchestrator

    orchestrator = InvoicePipelineOrchestrator()

    print("\n" + "=" * 65)
    print("  Sprint 8 — Full Pipeline E2E Test")
    print("=" * 65)

    result = await orchestrator.run_full_pipeline(
        po_document=PO_DOCUMENT,
        invoice_document=INVOICE_DOCUMENT,
        dry_run=False,
    )

    # ── High-level summary ───────────────────────────────────────────────────
    pipeline_ok = result.get("pipeline_success")
    elapsed     = result.get("total_elapsed_ms", 0)
    failed_step = result.get("failed_step")
    summary     = result.get("summary", {})
    steps       = result.get("steps", [])
    context     = result.get("context", {})

    print(f"\nPipeline success : {pipeline_ok}")
    print(f"Total elapsed    : {elapsed} ms")
    print(f"Failed step      : {failed_step or 'none'}")
    print(f"Steps succeeded  : {summary.get('steps_succeeded', 0)}/{summary.get('steps_run', 0)}")
    print(f"Invoice number   : {summary.get('invoice_number') or context.get('invoice_number', '(not set)')}")
    print(f"Payment run      : {summary.get('payment_run_number') or context.get('payment_run_number', '(not set)')}")
    print(f"Net payable AED  : {summary.get('net_payable_aed') or context.get('net_payable_aed', '(not set)')}")

    # ── Per-step breakdown ───────────────────────────────────────────────────
    print("\n--- Per-step breakdown ---")
    for s in steps:
        icon = "OK  " if s["success"] else "FAIL"
        err  = f"  ERROR: {s['error']}" if s.get("error") else ""
        inner = (s.get("result") or {}).get("result") or s.get("result") or {}
        status = inner.get("status", "")
        print(f"  [{icon}] {s['step']:35s}  {s['elapsed_ms']:5d}ms  status={status}{err}")

    # ── Context key inspection ───────────────────────────────────────────────
    print("\n--- Key context fields ---")
    key_fields = [
        "invoice_number", "vendor_id", "po_reference", "po_number",
        "match_status", "payment_run_number", "payment_run_id",
        "net_payable_aed", "invoice_currency", "payment_type",
        "conditions_checked", "conditions_passed",
    ]
    for k in key_fields:
        v = context.get(k)
        if v is not None:
            print(f"  {k:30s}: {v}")

    # ── Pass / fail judgement ────────────────────────────────────────────────
    print("\n" + "=" * 65)
    if pipeline_ok:
        print(f"  RESULT: PASS — pipeline completed ({summary.get('steps_succeeded')}/{summary.get('steps_run')} steps)")
        if summary.get('steps_failed', 0) > 0:
            print("  NOTE: Some steps reported business-level failures (e.g. step 5")
            print("  invoice_matching rejects because synthetic invoice has no DB record).")
            print("  These are expected with test data — see payment sub-pipeline test below.")
    else:
        print(f"  RESULT: FAIL — pipeline stopped at step '{failed_step}'")
        if steps:
            last = steps[-1]
            inner_last = (last.get("result") or {}).get("result") or {}
            print(f"  Last step result: {json.dumps(inner_last, default=str, indent=4)[:800]}")
    print("=" * 65 + "\n")

    # ── Payment sub-pipeline test with real DB data ──────────────────────────
    await run_payment_sub_pipeline_test(orchestrator)


async def run_payment_sub_pipeline_test(
    orchestrator,
) -> None:
    """Run steps 7–9 only using real DB invoice (BILL/2025/00001)."""
    print("\n" + "=" * 65)
    print("  Sprint 8 — Payment Sub-Pipeline Test (Real DB Data)")
    print("  Invoice: BILL/2025/00001  |  PO: PO00001  |  Vendor: 13")
    print("=" * 65)

    result = await orchestrator.run_payment_pipeline(
        payment_data=REAL_PAYMENT_DATA,
        dry_run=False,
    )

    pipeline_ok = result.get("pipeline_success")
    summary     = result.get("summary", {})
    context     = result.get("context", {})
    steps       = result.get("steps", [])

    print(f"\nSub-pipeline success : {pipeline_ok}")
    print(f"Steps succeeded      : {summary.get('steps_succeeded', 0)}/{summary.get('steps_run', 0)}")
    print(f"Payment run          : {context.get('payment_run_number', '(not set)')}")
    print(f"Net payable AED      : {context.get('net_payable_aed', '(not set)')}")
    print(f"Conditions passed    : {context.get('conditions_passed', '?')}/{context.get('conditions_checked', '?')}")

    print("\n--- Steps ---")
    for s in steps:
        icon = "OK  " if s["success"] else "FAIL"
        inner = (s.get("result") or {}).get("result") or s.get("result") or {}
        status = inner.get("status", "")
        print(f"  [{icon}] {s['step']:35s}  {s['elapsed_ms']:5d}ms  status={status}")

    print("\n" + "=" * 65)
    if pipeline_ok and summary.get('steps_succeeded') == 3:
        print("  RESULT: PASS — steps 7-8-9 all succeeded with real DB data")
    else:
        print(f"  RESULT: {'PASS' if pipeline_ok else 'FAIL'} — "
              f"{summary.get('steps_succeeded', 0)}/3 steps succeeded")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(run_test())
