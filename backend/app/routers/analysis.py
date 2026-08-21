"""AI analysis and signals. Nothing here can move money."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..deps import current_user, rate_limit, require_platform_access
from ..models import Signal, User
from ..schemas import SignalOut
from ..services import bot
from ..services.indicators import TIMEFRAMES
from ..services.mt5_client import BridgeError, mt5
from ..services import replay as replay_service
from ..services import resample
from ..services import sessions as session_map

router = APIRouter(
    prefix="/api/analysis",
    tags=["analysis"],
    # Gates on the router, so a route added here later is protected by
    # default rather than shipping open.
    dependencies=[Depends(rate_limit), Depends(require_platform_access)],
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
    # TIMEFRAMES now covers every timeframe the MT5 bridge exposes
    # (M1 … D1), so the chart's timeframe buttons all resolve.
    requested = timeframe.upper()
    derived = resample.source_for(requested)

    if derived is None and requested not in resample.NATIVE_MINUTES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"timeframe must be one of {resample.supported()}",
        )

    try:
        if derived is None:
            return {
                "symbol": settings.SYMBOL,
                "timeframe": requested,
                "derived_from": None,
                "bars": await mt5.bars(settings.SYMBOL, requested, count),
            }

        # A derived interval needs enough source bars to fill the same
        # number of buckets, so the request is scaled up rather than
        # returning a third of the history the caller asked for.
        source, minutes = derived
        per_bucket = minutes // resample.NATIVE_MINUTES[source]
        source_bars = await mt5.bars(
            settings.SYMBOL, source, min(count * per_bucket, 5000)
        )
        return {
            "symbol": settings.SYMBOL,
            "timeframe": requested,
            "derived_from": source,
            "derivation_note": (
                f"{requested} is not served by the feed. These bars are "
                f"aggregated from {per_bucket} {source} bars each, anchored "
                f"to midnight UTC."
            ),
            "bars": resample.resample(source_bars, requested)[-count:],
        }
    except BridgeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"MT5 bridge: {e}")


@router.get("/sessions")
async def market_sessions(
    timeframe: str = Query("M15"),
    count: int = Query(500, ge=50, le=1000),
    days: int = Query(3, ge=1, le=7),
    _: User = Depends(current_user),
) -> dict:
    """Session boxes and previous-period levels for the chart.

    Both are measured from the same bars the chart is showing, so a level
    drawn here is one the user can see the price making. A window the
    loaded history does not reach is omitted rather than estimated.
    """
    if timeframe not in TIMEFRAMES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"timeframe must be one of {TIMEFRAMES}",
        )
    try:
        bars = await mt5.bars(settings.SYMBOL, timeframe, count)
    except BridgeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"MT5 bridge: {e}")

    now = datetime.now(timezone.utc)
    return {
        "symbol": settings.SYMBOL,
        "timeframe": timeframe,
        "sessions": session_map.session_ranges(bars, days=days, now=now),
        "previous_levels": session_map.previous_levels(bars, now=now),
        "active": [
            {"session": s.name.value, "display_name": s.display_name,
             "colour": s.colour}
            for s in session_map.active_at(now)
        ],
        "definitions": [
            {"session": s.name.value, "display_name": s.display_name,
             "timezone": s.tz, "colour": s.colour,
             "opens_local": s.opens.strftime("%H:%M"),
             "closes_local": s.closes.strftime("%H:%M")}
            for s in session_map.SESSIONS
        ],
    }


@router.get("/replay/capabilities")
async def replay_capabilities(_: User = Depends(current_user)) -> dict:
    """What replay and backtesting can honestly do (section 63).

    Served rather than hard-coded in the UI, so a badge cannot drift out
    of step with what the backend actually supports.
    """
    return replay_service.capabilities()


@router.get("/timeframes")
async def timeframes(_: User = Depends(current_user)) -> dict:
    """Which chart intervals the platform can genuinely serve.

    Split into native and derived so the selector can say where a bar came
    from. Anything absent from both lists is unsupported and is not
    offered — an interval the feed cannot produce is never approximated.
    """
    return {
        "native": [
            {"timeframe": tf, "minutes": minutes}
            for tf, minutes in sorted(
                resample.NATIVE_MINUTES.items(), key=lambda kv: kv[1]
            )
        ],
        "derived": [
            {
                "timeframe": tf,
                "minutes": minutes,
                "source": source,
                "note": (
                    f"Aggregated from {minutes // resample.NATIVE_MINUTES[source]}"
                    f" {source} bars, anchored to midnight UTC."
                ),
            }
            for tf, (source, minutes) in resample.DERIVED.items()
        ],
        "unsupported_note": (
            "Tick, second and range bars are not offered: the feed reports "
            "completed candles, so they cannot be produced correctly and "
            "will not be approximated."
        ),
    }
