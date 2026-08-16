"""Start, stop and inspect the autonomous trading loop."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..bot.engine import TradingBot
from ..errors import TerminalUnavailableError
from ..security import require_api_key

router = APIRouter(prefix="/bot", tags=["bot"], dependencies=[Depends(require_api_key)])


class StartRequest(BaseModel):
    """Overrides for one run. Everything else comes from the bridge's config —
    in particular BOT_DRY_RUN, which the API deliberately cannot loosen."""

    model_config = ConfigDict(extra="forbid")

    symbol: str | None = Field(default=None, examples=["XAUUSD"])
    timeframe: str | None = Field(default=None, examples=["M15"])


def get_bot(request: Request) -> TradingBot:
    bot: TradingBot | None = getattr(request.app.state, "bot", None)
    if bot is None:  # pragma: no cover - only if startup was skipped
        raise TerminalUnavailableError("The trading bot is not initialised.")
    return bot


@router.post("/start", summary="Start the trading loop")
async def start(
    request: StartRequest = Body(default=StartRequest()),
    bot: TradingBot = Depends(get_bot),
) -> dict:
    """Refused with `403 bot_not_allowed` unless `BOT_ENABLED=true`.

    A started bot only sends orders when `BOT_DRY_RUN=false`; otherwise it
    records the trades it would have taken. Orders it does send go through the
    same risk policy and pre-flight as a manual order.
    """
    return await bot.start(symbol=request.symbol, timeframe=request.timeframe)


@router.post("/stop", summary="Stop the trading loop")
async def stop(bot: TradingBot = Depends(get_bot)) -> dict:
    """Idempotent — stopping a stopped bot succeeds and changes nothing.

    Open positions are left exactly as they are; stopping the bot stops it
    opening more, it does not close anything.
    """
    return await bot.stop()


@router.get("/status", summary="What the bot is doing and has done")
async def status(bot: TradingBot = Depends(get_bot)) -> dict:
    return bot.status()
