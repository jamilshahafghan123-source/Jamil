"""AI analysis and signals. Nothing here can move money."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..deps import current_user, rate_limit
from ..models import Signal, User
from ..schemas import SignalOut
from ..services import bot
from ..services.indicators import TIMEFRAMES
from ..services.mt5_client import BridgeError, mt5

router = APIRouter(
    prefix="/api/analysis", tags=["analysis"], dependencies=[Depends(rate_limit)]
)


@router.get("/indicators")
async def raw_indicators(_: User = Depends(current_user)) -> dict:
    """The deterministic snapshot, with no AI involved.

    Useful for verifying that what the AI is shown matches the market.
    """
    try:
        return await bot.collect_market_data()
    except BridgeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"MT5 bridge: {e}")


@router.post("/run")
async def run_analysis(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Run the full pipeline up to (not including) execution."""
    try:
        signal, analysis = await bot.run_analysis(db, user.id)
    except BridgeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"MT5 bridge: {e}")

    return {
        "signal": SignalOut.model_validate(signal).model_dump(mode="json"),
        "analysis": analysis,
    }


@router.get("/signals", response_model=list[SignalOut])
async def list_signals(
    limit: int = Query(25, ge=1, le=100),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Signal]:
    rows = (
        await db.execute(
            select(Signal)
            .where(Signal.user_id == user.id)
            .order_by(desc(Signal.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


@router.get("/signals/{signal_id}")
async def get_signal(
    signal_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sig = await db.get(Signal, signal_id)
    if sig is None or sig.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signal not found")
    return {
        "signal": SignalOut.model_validate(sig).model_dump(mode="json"),
        "analysis": sig.analysis,
        "market_snapshot": sig.market_snapshot,
    }


@router.get("/bars")
async def bars(
    timeframe: str = Query("M15"),
    count: int = Query(200, ge=10, le=1000),
    _: User = Depends(current_user),
) -> dict:
    if timeframe not in TIMEFRAMES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"timeframe must be one of {TIMEFRAMES}",
        )
    try:
        return {
            "symbol": settings.SYMBOL,
            "timeframe": timeframe,
            "bars": await mt5.bars(settings.SYMBOL, timeframe, count),
        }
    except BridgeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"MT5 bridge: {e}")
