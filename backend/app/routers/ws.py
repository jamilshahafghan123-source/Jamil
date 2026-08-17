"""WebSocket for live dashboard updates.

Auth: the browser WebSocket API can't set headers, so the JWT is passed as a
query parameter and validated before the socket is accepted. Anything
invalid is closed with 1008 without ever entering the loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import RiskSettings, User
from ..security import decode_token
from ..services.mt5_client import BridgeError, mt5

log = logging.getLogger("ws")
router = APIRouter()


@router.websocket("/ws/live")
async def live(websocket: WebSocket, token: str = Query(...)) -> None:
    try:
        user_id = int(decode_token(token)["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        await websocket.close(code=1008, reason="invalid token")
        return

    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            await websocket.close(code=1008, reason="unknown user")
            return

    await websocket.accept()
    log.info("ws connected user=%s", user_id)

    async def push() -> None:
        while True:
            payload: dict = {"type": "tick"}
            try:
                payload["tick"] = await mt5.tick(settings.SYMBOL)
                payload["positions"] = await mt5.positions(settings.SYMBOL)
                payload["account"] = await mt5.account()
                payload["bridge_connected"] = True
            except BridgeError as e:
                payload["bridge_connected"] = False
                payload["error"] = str(e)

            async with SessionLocal() as db:
                row = (
                    await db.execute(
                        select(RiskSettings).where(RiskSettings.user_id == user_id)
                    )
                ).scalar_one_or_none()
                if row:
                    payload["bot_enabled"] = row.bot_enabled
                    payload["emergency_stop"] = row.emergency_stop
                    payload["trading_mode"] = row.trading_mode.value

            await websocket.send_json(payload)
            await asyncio.sleep(settings.MARKET_POLL_SECONDS)

    task = asyncio.create_task(push())
    try:
        # Reading keeps us aware of client disconnects and drains pings.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws error user=%s", user_id)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        log.info("ws disconnected user=%s", user_id)
