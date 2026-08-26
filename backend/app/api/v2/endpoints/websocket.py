"""Versioned WebSocket endpoint for API v2."""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.contracts import ok
from app.services.websocket_service import connection_manager

router = APIRouter()
logger = logging.getLogger(__name__)


def _event(name: str, payload: dict | None = None) -> dict:
    return {
        "version": "v2",
        "event": name,
        "timestamp": int(datetime.now().timestamp() * 1000),
        "data": payload or {},
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)
    await connection_manager.send_personal(websocket, _event("connected", {"message": "WebSocket connected"}))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await connection_manager.send_personal(websocket, _event("error", {"message": "Invalid JSON"}))
                continue

            action = message.get("action")
            if action == "ping":
                await connection_manager.send_personal(websocket, _event("pong"))
                continue

            if action == "subscribe":
                channel = message.get("channel")
                exchange = message.get("exchange")
                symbol = message.get("symbol")
                timeframe = message.get("timeframe")
                if not channel or not exchange:
                    await connection_manager.send_personal(websocket, _event("error", {"message": "Missing channel or exchange"}))
                    continue
                sub_key = await connection_manager.subscribe(websocket, channel, exchange, symbol, timeframe)
                await connection_manager.send_personal(
                    websocket,
                    _event("subscribed", {
                        "channel": channel,
                        "exchange": exchange,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "subscription": sub_key,
                    }),
                )
                continue

            if action == "unsubscribe":
                await connection_manager.unsubscribe(
                    websocket,
                    message.get("channel"),
                    message.get("exchange"),
                    message.get("symbol"),
                    message.get("timeframe"),
                )
                await connection_manager.send_personal(
                    websocket,
                    _event("unsubscribed", {
                        "channel": message.get("channel"),
                        "exchange": message.get("exchange"),
                        "symbol": message.get("symbol"),
                        "timeframe": message.get("timeframe"),
                    }),
                )
                continue

            await connection_manager.send_personal(websocket, _event("error", {"message": f"Unknown action: {action}"}))

    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket)
    except Exception:
        logger.exception("WebSocket error")
        await connection_manager.disconnect(websocket)


@router.get("/ws/stats")
async def websocket_stats():
    return ok(connection_manager.get_stats())
