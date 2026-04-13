"""
Session Event Outbox Pump (P1.5 / HF-2 / R12)

Moves rows from session_event_outbox → session_events on a short interval.
The insert into session_events fires the pg_notify trigger, making the event
visible to SSE listeners on /api/sessions/:id/events.

Two-phase commit semantics via the outbox table:
  Phase 1 — handler writes ERP row + outbox row in one transaction.
  Phase 2 — pump moves outbox row to session_events in a second transaction.

If the pump is down, events accumulate in the outbox and are delivered on
restart. SSE clients see a delay, never wrong state.

Run on a short interval (default 100ms) so under healthy conditions the gap
between a handler committing and the event becoming visible is bounded.

Consumers:
- backend/main.py — registers an asyncio task calling outbox_pump_loop on
  startup, gated by OUTBOX_PUMP_ENABLED env var.

Observability:
- Each run logs published count and a "stuck count" (rows uncommitted > 60s).
- R12 health rule: stuck_count must be 0 for the P5 gate criterion.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from backend.services.adapters.factory import get_adapter

logger = logging.getLogger(__name__)

# Default interval chosen so healthy-case latency between commit and publish
# is imperceptible (~100ms). Override via OUTBOX_PUMP_INTERVAL_SECONDS.
DEFAULT_INTERVAL_SECONDS = 0.1
DEFAULT_BATCH_SIZE = 100


async def pump_once(batch_size: int = DEFAULT_BATCH_SIZE) -> Dict[str, Any]:
    """
    Single iteration of the pump. Publishes up to `batch_size` outbox rows
    and returns a summary dict for observability.

    Synchronous work wrapped in an async function so it can be awaited from
    the loop without blocking the event loop for long (psycopg2 calls yield
    via the event loop's default thread pool executor in practice).
    """
    started = datetime.now(timezone.utc)
    adapter = get_adapter()
    try:
        result = adapter.pump_outbox_once(batch_size=batch_size)
    except Exception as exc:
        logger.exception("outbox_pump: pump_outbox_once raised: %s", exc)
        return {"success": False, "error": str(exc), "published": 0, "stuck_count": 0}

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    published = result.get("published", 0)
    stuck = result.get("stuck_count", 0)

    if published > 0 or stuck > 0:
        logger.info(
            "outbox_pump: published=%d stuck_count=%d duration_ms=%d",
            published, stuck, duration_ms,
        )

    if stuck > 0:
        logger.warning(
            "outbox_pump: %d rows stuck uncommitted > 60s — R12 health signal",
            stuck,
        )

    return {
        **result,
        "duration_ms": duration_ms,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


async def outbox_pump_loop(
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """
    Long-running pump loop. Runs until cancelled. Exceptions inside a single
    iteration are swallowed — the loop continues.
    """
    logger.info(
        "outbox_pump: loop starting interval=%.3fs batch=%d",
        interval_seconds, batch_size,
    )
    while True:
        try:
            await pump_once(batch_size=batch_size)
        except asyncio.CancelledError:
            logger.info("outbox_pump: loop cancelled, exiting")
            raise
        except Exception as exc:
            logger.exception("outbox_pump: iteration raised, will retry: %s", exc)
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("outbox_pump: loop cancelled during sleep, exiting")
            raise


if __name__ == "__main__":
    # Manual smoke test: python -m backend.jobs.outbox_pump
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = asyncio.run(pump_once())
    print(json.dumps(result, indent=2, default=str))
