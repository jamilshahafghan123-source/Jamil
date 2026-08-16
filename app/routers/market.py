"""Market-data endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Path, Query

from ..dependencies import get_session
from ..mt5 import market
from ..mt5.session import MT5Session
from ..schemas import (
    AccountResponse,
    CandlesResponse,
    SymbolSummary,
    TickResponse,
    Timeframe,
)
from ..security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["market"], dependencies=[Depends(require_api_key)])


@router.get("/account", response_model=AccountResponse, summary="Account snapshot")
async def account(session: MT5Session = Depends(get_session)) -> AccountResponse:
    from ..mt5 import trading

    return AccountResponse(**await trading.get_account(session))


@router.get("/symbols", response_model=list[SymbolSummary], summary="List tradable symbols")
async def symbols(
    search: str | None = Query(default=None, description="Substring filter, e.g. 'EUR'."),
    limit: int = Query(default=200, ge=1, le=5000),
    session: MT5Session = Depends(get_session),
) -> list[SymbolSummary]:
    rows = await market.list_symbols(session, search=search, limit=limit)
    return [SymbolSummary(**row) for row in rows]


@router.get("/symbols/{symbol}", summary="Full symbol specification")
async def symbol_detail(
    symbol: str = Path(..., description="Symbol name as shown in Market Watch."),
    session: MT5Session = Depends(get_session),
) -> dict:
    return await market.ensure_symbol(session, symbol)


@router.get("/ticks/{symbol}", response_model=TickResponse, summary="Latest tick")
async def tick(
    symbol: str,
    session: MT5Session = Depends(get_session),
) -> TickResponse:
    return TickResponse(**await market.get_tick(session, symbol))


@router.get("/candles", response_model=CandlesResponse, summary="OHLC candles")
async def candles(
    symbol: str = Query(..., examples=["EURUSD"]),
    timeframe: Timeframe = Query(default="M15"),
    count: int = Query(default=500, ge=1, le=market.MAX_CANDLES),
    start: datetime | None = Query(
        default=None, description="ISO-8601 start time (UTC assumed when no offset given)."
    ),
    end: datetime | None = Query(
        default=None, description="ISO-8601 end time. With 'start' this returns the full range."
    ),
    offset: int = Query(
        default=0, ge=0, description="Bars to skip back from the current bar. Ignored with 'start'."
    ),
    session: MT5Session = Depends(get_session),
) -> CandlesResponse:
    """Candles are returned oldest-first. The final bar is the one still forming."""
    rows = await market.get_candles(
        session,
        symbol=symbol,
        timeframe=timeframe,
        count=count,
        start=start,
        end=end,
        offset=offset,
    )
    return CandlesResponse(
        symbol=symbol, timeframe=timeframe, count=len(rows), candles=rows
    )
