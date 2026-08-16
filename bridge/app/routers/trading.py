"""Trading endpoints: orders, positions and deal history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Query, status

from ..config import Settings, get_settings
from ..dependencies import get_session
from ..mt5 import trading
from ..mt5.session import MT5Session
from ..schemas import (
    ClosePositionRequest,
    Deal,
    ModifyPositionRequest,
    OrderRequest,
    PendingOrder,
    Position,
    TradeResult,
)
from ..security import require_api_key

router = APIRouter(prefix="/api/v1", tags=["trading"], dependencies=[Depends(require_api_key)])


@router.post(
    "/orders",
    response_model=TradeResult,
    status_code=status.HTTP_201_CREATED,
    summary="Place a market or pending order",
)
async def place_order(
    request: OrderRequest = Body(
        ...,
        openapi_examples={
            "market_buy": {
                "summary": "Market buy with stops",
                "value": {
                    "symbol": "EURUSD",
                    "side": "buy",
                    "volume": 0.1,
                    "type": "market",
                    "sl": 1.0800,
                    "tp": 1.0900,
                    "comment": "demo entry",
                },
            },
            "pending_sell_limit": {
                "summary": "Sell limit, good till cancelled",
                "value": {
                    "symbol": "EURUSD",
                    "side": "sell",
                    "volume": 0.2,
                    "type": "limit",
                    "price": 1.0950,
                },
            },
            "validate_only": {
                "summary": "Validate margin without sending",
                "value": {
                    "symbol": "EURUSD",
                    "side": "buy",
                    "volume": 0.1,
                    "dry_run": True,
                },
            },
        },
    ),
    session: MT5Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TradeResult:
    """Rejected trades return HTTP 400 with the MT5 retcode in `details`."""
    return TradeResult(**await trading.place_order(session, settings, request))


@router.get("/orders", response_model=list[PendingOrder], summary="List pending orders")
async def list_orders(
    symbol: str | None = Query(default=None),
    session: MT5Session = Depends(get_session),
) -> list[PendingOrder]:
    return [PendingOrder(**row) for row in await trading.list_orders(session, symbol=symbol)]


@router.delete("/orders/{ticket}", response_model=TradeResult, summary="Cancel a pending order")
async def cancel_order(
    ticket: int,
    session: MT5Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TradeResult:
    return TradeResult(**await trading.cancel_order(session, settings, ticket=ticket))


@router.get("/positions", response_model=list[Position], summary="List open positions")
async def list_positions(
    symbol: str | None = Query(default=None),
    session: MT5Session = Depends(get_session),
) -> list[Position]:
    return [Position(**row) for row in await trading.list_positions(session, symbol=symbol)]


@router.post(
    "/positions/{ticket}/close",
    response_model=TradeResult,
    summary="Close a position (fully or partially)",
)
async def close_position(
    ticket: int,
    request: ClosePositionRequest = Body(default=ClosePositionRequest()),
    session: MT5Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TradeResult:
    return TradeResult(
        **await trading.close_position(
            session,
            settings,
            ticket=ticket,
            volume=request.volume,
            deviation=request.deviation,
            comment=request.comment,
        )
    )


@router.patch(
    "/positions/{ticket}",
    response_model=TradeResult,
    summary="Modify stop loss / take profit",
)
async def modify_position(
    ticket: int,
    request: ModifyPositionRequest,
    session: MT5Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TradeResult:
    return TradeResult(
        **await trading.modify_position(
            session, settings, ticket=ticket, sl=request.sl, tp=request.tp
        )
    )


@router.get("/history/deals", response_model=list[Deal], summary="Closed deal history")
async def history_deals(
    start: datetime | None = Query(default=None, description="Defaults to 7 days ago."),
    end: datetime | None = Query(default=None, description="Defaults to now."),
    symbol: str | None = Query(default=None, description="Symbol or group filter, e.g. 'EURUSD'."),
    session: MT5Session = Depends(get_session),
) -> list[Deal]:
    now = datetime.now(tz=timezone.utc)
    rows = await trading.list_deals(
        session,
        start=start or now - timedelta(days=7),
        end=end or now,
        symbol=symbol,
    )
    return [Deal(**row) for row in rows]
