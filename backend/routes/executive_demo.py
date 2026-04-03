"""
Executive Demo Routes
Provides websocket stream and replay endpoint for the fullscreen executive theater.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services import agent_event_stream

logger = logging.getLogger(__name__)

router = APIRouter(tags=["executive-demo"])


@router.websocket("/ws/executive-demo")
async def executive_demo_websocket(websocket: WebSocket):
    """
    Live websocket channel for synchronized technical-panel and business-panel events.
    """
    await websocket.accept()
    queue = await agent_event_stream.subscribe_executive_events()

    try:
        await websocket.send_json(
            {
                "event_type": "connection",
                "timestamp": None,
                "payload": {"message": "Connected to executive demo stream."},
            }
        )

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25.0)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"event_type": "keepalive", "payload": {"message": "alive"}})
    except WebSocketDisconnect:
        logger.info("[EXECUTIVE DEMO] WebSocket client disconnected")
    finally:
        await agent_event_stream.unsubscribe_executive_events(queue)


@router.get("/api/executive-demo/last-session")
async def get_last_executive_demo_session():
    """
    Return the full event log of the most recently completed execution.
    """
    return {
        "status": "success",
        "session": agent_event_stream.get_last_executive_session(),
    }
