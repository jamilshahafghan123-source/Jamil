"""The compact, verb-shaped API surface.

    GET  /account            GET  /market/{symbol}     GET  /positions
    GET  /orders             POST /trade/buy           POST /trade/sell
    POST /position/close

These are thin aliases over the same service functions as `/api/v1/*` — same
risk policy, same pre-flight, same demo guard. Nothing here bypasses anything;
there is one implementation and two ways to address it.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings, get_settings
from ..dependencies import get_session
from ..mt5 import market, trading
from ..mt5.session import MT5Session
from ..schemas import (
    AccountResponse,
    Candle,
    Filling,
    OrderRequest,
    PendingOrder,
    Position,
    Timeframe,
    TradeResult,
)
from ..security import require_api_key

router = APIRouter(tags=["simple"], dependencies=[Depends(require_api_key)])


class TradeRequest(BaseModel):
    """A buy or sell. The side comes from the path, everything else from here."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., examples=["XAUUSD"])
    volume: float = Field(..., gt=0, description="Lots. Snapped to the symbol's step.")
    type: Literal["market", "limit", "stop"] = "market"
    price: float | None = Field(default=None, gt=0, description="Pending orders only.")
    sl: float | None = Field(default=None, ge=0)
    tp: float | None = Field(default=None, ge=0)
    deviation: int | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=24)
    filling: Filling | None = None
    dry_run: bool = False


class ClosePositionByTicket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: int = Field(..., gt=0)
    volume: float | None = Field(default=None, gt=0, description="Partial close.")
    deviation: int | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=24)


class MarketSnapshot(BaseModel):
    """Everything needed to draw and price one symbol, in a single call."""

    symbol: str
    description: str = ""
    digits: int
    point: float
    volume_min: float
    volume_max: float
    volume_step: float
    bid: float
    ask: float
    spread_points: float
    timeframe: Timeframe
    candles: list[Candle]


@router.get("/account", response_model=AccountResponse, summary="Account snapshot")
async def account(session: MT5Session = Depends(get_session)) -> AccountResponse:
    return AccountResponse(**await trading.get_account(session))


@router.get("/market/{symbol}", response_model=MarketSnapshot, summary="Market snapshot")
async def market_snapshot(
    symbol: str = Path(..., examples=["XAUUSD"]),
    timeframe: Timeframe = Query(default="M15"),
    count: int = Query(default=200, ge=1, le=5000),
    session: MT5Session = Depends(get_session),
) -> MarketSnapshot:
    """Symbol specification, the live quote and recent candles in one response."""
    info = await market.ensure_symbol(session, symbol)
    tick = await market.get_tick(session, symbol)
    candles = await market.get_candles(
        session, symbol=symbol, timeframe=timeframe, count=count
    )

    point = float(info.get("point") or 0.0)
    bid, ask = float(tick["bid"]), float(tick["ask"])
    return MarketSnapshot(
        symbol=info.get("name", symbol),
        description=info.get("description", ""),
        digits=int(info.get("digits", 5)),
        point=point,
        volume_min=float(info.get("volume_min", 0.0)),
        volume_max=float(info.get("volume_max", 0.0)),
        volume_step=float(info.get("volume_step", 0.0)),
        bid=bid,
        ask=ask,
        spread_points=round((ask - bid) / point, 1) if point else 0.0,
        timeframe=timeframe,
        candles=candles,
    )


@router.get("/positions", response_model=list[Position], summary="Open positions")
async def positions(
    symbol: str | None = Query(default=None),
    session: MT5Session = Depends(get_session),
) -> list[Position]:
    return [Position(**row) for row in await trading.list_positions(session, symbol=symbol)]


@router.get("/orders", response_model=list[PendingOrder], summary="Pending orders")
async def orders(
    symbol: str | None = Query(default=None),
    session: MT5Session = Depends(get_session),
) -> list[PendingOrder]:
    return [PendingOrder(**row) for row in await trading.list_orders(session, symbol=symbol)]


async def _trade(
    side: Literal["buy", "sell"],
    request: TradeRequest,
    session: MT5Session,
    settings: Settings,
) -> TradeResult:
    order = OrderRequest(
        symbol=request.symbol,
        side=side,
        volume=request.volume,
        type=request.type,
        price=request.price,
        sl=request.sl,
        tp=request.tp,
        deviation=request.deviation,
        comment=request.comment,
        filling=request.filling,
        dry_run=request.dry_run,
    )
    return TradeResult(**await trading.place_order(session, settings, order))


@router.post("/trade/buy", response_model=TradeResult, summary="Buy")
async def trade_buy(
    request: TradeRequest = Body(
        ...,
        openapi_examples={
            "market": {
                "summary": "Market buy with stops",
                "value": {
                    "symbol": "XAUUSD", "volume": 0.10, "sl": 2397.80, "tp": 2410.00
                },
            }
        },
    ),
    session: MT5Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TradeResult:
    return await _trade("buy", request, session, settings)


@router.post("/trade/sell", response_model=TradeResult, summary="Sell")
async def trade_sell(
    request: TradeRequest,
    session: MT5Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TradeResult:
    return await _trade("sell", request, session, settings)


@router.post("/position/close", response_model=TradeResult, summary="Close a position")
async def position_close(
    request: ClosePositionByTicket,
    session: MT5Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TradeResult:
    result: dict[str, Any] = await trading.close_position(
        session,
        settings,
        ticket=request.ticket,
        volume=request.volume,
        deviation=request.deviation,
        comment=request.comment,
    )
    return TradeResult(**result)
