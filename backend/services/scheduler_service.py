"""
Scheduler Service — Sprint 9
==============================
Background task scheduler for periodic agent runs.
Uses asyncio tasks (no external scheduler needed).

Scheduled tasks:
- Email inbox scan: every 15 minutes
- Anomaly detection: every 6 hours
- Inventory check: every 4 hours
- Contract expiry check: daily at 8am (checked every hour)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# ── Intervals ─────────────────────────────────────────────────────────────────
_EMAIL_SCAN_INTERVAL_SEC = 15 * 60       # 15 minutes
_ANOMALY_DETECT_INTERVAL_SEC = 6 * 3600  # 6 hours
_INVENTORY_CHECK_INTERVAL_SEC = 4 * 3600 # 4 hours
_CONTRACT_CHECK_INTERVAL_SEC = 3600      # check every hour; fires only at 08:xx

# Track whether the scheduler has been started (prevent double-start)
_scheduler_started: bool = False


# ── Public entry point ────────────────────────────────────────────────────────

async def start_scheduler() -> None:
    """
    Start all background periodic tasks.

    Called once from the FastAPI startup event.  Safe to call multiple times —
    subsequent calls are no-ops.
    """
    global _scheduler_started
    if _scheduler_started:
        logger.info("[Scheduler] Already running — skipping re-start.")
        return

    _scheduler_started = True
    logger.info("[Scheduler] Starting background task scheduler...")

    # Launch all periodic tasks concurrently; they run indefinitely.
    asyncio.create_task(_run_email_inbox_scan(), name="scheduler:email_inbox")
    asyncio.create_task(_run_anomaly_detection(), name="scheduler:anomaly_detection")
    asyncio.create_task(_run_inventory_check(), name="scheduler:inventory_check")
    asyncio.create_task(_run_contract_expiry_check(), name="scheduler:contract_expiry")

    logger.info(
        "[Scheduler] Background tasks registered: email_inbox (15 min), "
        "anomaly_detection (6 h), inventory_check (4 h), contract_expiry (daily 08:00)."
    )


# ── Periodic task runners ─────────────────────────────────────────────────────

async def _run_email_inbox_scan() -> None:
    """Poll the email inbox for new invoices every 15 minutes."""
    logger.info("[Scheduler] email_inbox_scan task started (interval=15 min)")
    while True:
        await asyncio.sleep(_EMAIL_SCAN_INTERVAL_SEC)
        await _safe_run(
            "email_inbox_scan",
            _invoke_email_inbox_scan,
        )


async def _run_anomaly_detection() -> None:
    """Run anomaly detection every 6 hours."""
    logger.info("[Scheduler] anomaly_detection task started (interval=6 h)")
    # Initial delay so it doesn't run immediately on startup
    await asyncio.sleep(60)
    while True:
        await _safe_run("anomaly_detection", _invoke_anomaly_detection)
        await asyncio.sleep(_ANOMALY_DETECT_INTERVAL_SEC)


async def _run_inventory_check() -> None:
    """Run inventory check every 4 hours."""
    logger.info("[Scheduler] inventory_check task started (interval=4 h)")
    await asyncio.sleep(120)  # Brief startup delay
    while True:
        await _safe_run("inventory_check", _invoke_inventory_check)
        await asyncio.sleep(_INVENTORY_CHECK_INTERVAL_SEC)


async def _run_contract_expiry_check() -> None:
    """
    Check contract expiry daily at approximately 08:00 local time.

    Wakes every hour and fires only when the current hour is 8.
    """
    logger.info("[Scheduler] contract_expiry_check task started (daily at 08:00)")
    last_fired_date: str = ""
    while True:
        await asyncio.sleep(_CONTRACT_CHECK_INTERVAL_SEC)
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if now.hour == 8 and today != last_fired_date:
            last_fired_date = today
            await _safe_run("contract_expiry_check", _invoke_contract_expiry_check)


# ── Agent invocations ─────────────────────────────────────────────────────────

async def _invoke_email_inbox_scan() -> None:
    """Invoke EmailInboxAgent."""
    from backend.agents.email_inbox_agent import EmailInboxAgent

    agent = EmailInboxAgent()
    result = await agent.execute({"max_emails": 20, "auto_process": True})
    processed = (
        result.get("result", {}).get("processed_count", 0)
        if isinstance(result.get("result"), dict)
        else 0
    )
    logger.info("[Scheduler] email_inbox_scan complete — processed=%s", processed)


async def _invoke_anomaly_detection() -> None:
    """Invoke AnomalyDetectionAgent."""
    from backend.agents.anomaly_detection_agent import AnomalyDetectionAgent

    agent = AnomalyDetectionAgent()
    result = await agent.execute({"lookback_days": 30, "severity_threshold": "LOW"})
    logged = (
        result.get("result", {}).get("new_anomalies_logged", 0)
        if isinstance(result.get("result"), dict)
        else 0
    )
    logger.info("[Scheduler] anomaly_detection complete — logged=%s", logged)


async def _invoke_inventory_check() -> None:
    """Invoke InventoryCheckAgent."""
    from backend.agents.inventory_check import InventoryCheckAgent

    agent = InventoryCheckAgent()
    try:
        result = await agent.execute({"check_type": "full_scan", "auto_create_pr": True})
        inner = result.get("result") if isinstance(result, dict) else None
        summary = inner.get("inventory_summary", {}) if isinstance(inner, dict) else {}
        low_stock = summary.get("low_stock_count", 0) if isinstance(summary, dict) else 0
    except Exception as inv_err:
        logger.warning("[Scheduler] inventory_check had an issue: %s", inv_err)
        low_stock = 0
    logger.info("[Scheduler] inventory_check complete — low_stock_items=%s", low_stock)


async def _invoke_contract_expiry_check() -> None:
    """Invoke ContractMonitoringAgent for expiry checks."""
    try:
        from backend.agents.contract_monitoring import ContractMonitoringAgent

        agent = ContractMonitoringAgent()
        result = await agent.execute({"check_type": "expiry_check"})
        logger.info("[Scheduler] contract_expiry_check complete — result=%s", result.get("status"))
    except Exception as exc:
        logger.warning(
            "[Scheduler] contract_expiry_check skipped (agent not available): %s", exc
        )


# ── Safe wrapper ──────────────────────────────────────────────────────────────

async def _safe_run(
    task_name: str,
    coro_fn: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    """
    Execute *coro_fn* and swallow all exceptions so one failing task
    never brings down the other scheduled tasks.
    """
    try:
        logger.debug("[Scheduler] Running task: %s", task_name)
        await coro_fn()
    except Exception as exc:
        logger.error(
            "[Scheduler] Task '%s' raised an exception: %s", task_name, exc,
            exc_info=True,
        )
