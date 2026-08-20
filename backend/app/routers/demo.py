"""J Gold AI internal demo trading (sections 8-15).

Gated by require_demo_access, which today agrees with platform access and
becomes a free-demo switch by changing services/entitlements.py alone.

Maintenance blocks *opening* and never blocks closing, matching the rule
the rest of the platform already follows: a maintenance window must not
trap someone in a position.

Every route derives the account from current_user. There is no path that
takes an account id, so one customer's demo account is unreachable from
another's session by construction rather than by check.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..db import get_db
from ..deps import current_user, rate_limiter, require_demo_access
from ..models import (
    AuditLog,
    DemoAccount,
    DemoPosition,
    DemoPositionSide,
    DemoTrade,
    TradeSource,
    User,
)
from ..services import demo_engine, instruments, maintenance
from ..services.mt5_client import BridgeError, mt5

router = APIRouter(
    prefix="/api/demo",
    tags=["demo"],
    dependencies=[Depends(rate_limiter(60))],
)


class OpenIn(BaseModel):
    symbol: str = Field(default=instruments.DEFAULT_SYMBOL, max_length=24)
    side: DemoPositionSide
    volume: float = Field(gt=0, le=1000)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    source: TradeSource = TradeSource.MANUAL
    signal_confidence: int | None = Field(default=None, ge=0, le=100)
    signal_rr: float | None = Field(default=None, ge=0)


async def _account_for(db: AsyncSession, user: User) -> DemoAccount:
    """One account per user, created on first use."""
    row = (
        await db.execute(select(DemoAccount).where(DemoAccount.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        row = DemoAccount(
            user_id=user.id,
            starting_balance=demo_engine.DEFAULT_STARTING_BALANCE,
            balance=demo_engine.DEFAULT_STARTING_BALANCE,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _quote(symbol: str) -> demo_engine.Quote | None:
    """Live price for valuation. A failure yields None, never a made-up price."""
    try:
        tick = await mt5.tick()
    except (BridgeError, Exception):  # noqa: BLE001 - unpriced is a state
        return None
    if not isinstance(tick, dict):
        return None
    bid = float(tick.get("bid") or 0.0)
    ask = float(tick.get("ask") or 0.0)
    if bid <= 0 or ask <= 0:
        return None
    return demo_engine.Quote(bid=bid, ask=ask)


async def _open_positions(db: AsyncSession, account: DemoAccount) -> list[DemoPosition]:
    return list(
        (
            await db.execute(
                select(DemoPosition)
                .where(DemoPosition.account_id == account.id)
                .order_by(DemoPosition.id.desc())
            )
        )
        .scalars()
        .all()
    )


def _position_out(p: DemoPosition, pnl: float | None) -> dict:
    return {
        "id": p.id,
        "symbol": p.symbol,
        "side": p.side.value,
        "volume": p.volume,
        "entry_price": p.entry_price,
        "stop_loss": p.stop_loss,
        "take_profit": p.take_profit,
        "source": p.source.value,
        "signal_confidence": p.signal_confidence,
        "signal_rr": p.signal_rr,
        "opened_at": p.opened_at.isoformat() if p.opened_at else None,
        "floating_pnl": pnl,
    }


@router.get("/account")
async def get_account(
    user: User = Depends(require_demo_access), db: AsyncSession = Depends(get_db)
) -> dict:
    """Account state, positions, and whether trading is currently possible."""
    account = await _account_for(db, user)
    positions = await _open_positions(db, account)
    quote = await _quote(instruments.DEFAULT_SYMBOL)
    quotes = {instruments.DEFAULT_SYMBOL: quote} if quote else {}

    snap = demo_engine.snapshot(account, positions, quotes)
    window = maintenance.current()
    return {
        "account": snap.as_dict(),
        "starting_balance": account.starting_balance,
        "positions": [
            _position_out(
                p,
                demo_engine.position_pnl(p, quotes[p.symbol],
                                         instruments.get(p.symbol))
                if p.symbol in quotes
                else None,
            )
            for p in positions
        ],
        "market_price": {"bid": quote.bid, "ask": quote.ask} if quote else None,
        "can_open": quote is not None and not window.blocks_new_broker_execution,
        "blocked_reason": (
            maintenance.CUSTOMER_MESSAGE
            if window.blocks_new_broker_execution
            else None
            if quote
            else "Live market data is unavailable, so no price can be quoted."
        ),
    }


@router.get("/instruments")
async def list_instruments(_user: User = Depends(current_user)) -> dict:
    """The symbol selector. COMING_SOON entries are never priced."""
    return {
        "default": instruments.DEFAULT_SYMBOL,
        "by_asset_class": instruments.by_asset_class(),
    }


@router.post("/positions")
async def open_position(
    body: OpenIn,
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Open a virtual position. Nothing here reaches a broker."""
    window = maintenance.current()
    if window.blocks_new_broker_execution:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, maintenance.CUSTOMER_MESSAGE
        )

    try:
        instrument = instruments.require_tradable(body.symbol)
    except instruments.UnknownInstrumentError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown symbol") from None
    except instruments.InstrumentNotTradableError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    quote = await _quote(instrument.symbol)
    if quote is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Live market data is unavailable, so no order can be priced.",
        )

    account = await _account_for(db, user)
    open_now = await _open_positions(db, account)
    if len(open_now) >= 20:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The demo account has reached its open position limit.",
        )

    try:
        position = demo_engine.open_position(
            account,
            symbol=instrument.symbol,
            side=body.side,
            volume=body.volume,
            quote=quote,
            stop_loss=body.stop_loss,
            take_profit=body.take_profit,
            source=body.source,
            signal_confidence=body.signal_confidence,
            signal_rr=body.signal_rr,
        )
    except demo_engine.DemoError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    db.add(position)
    db.add(
        AuditLog(
            user_id=user.id,
            event=audit.DEMO_POSITION_OPENED,
            detail={"symbol": position.symbol, "side": position.side.value,
                    "volume": position.volume, "source": position.source.value},
        )
    )
    await db.commit()
    await db.refresh(position)
    return {"position": _position_out(position, 0.0), "virtual_money": True}


@router.post("/positions/{position_id}/close")
async def close_position(
    position_id: int,
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Close a virtual position.

    Deliberately NOT blocked during maintenance: closing reduces exposure,
    and a maintenance window must never trap someone in a trade.
    """
    account = await _account_for(db, user)
    position = (
        await db.execute(
            select(DemoPosition).where(
                DemoPosition.id == position_id,
                # Ownership is part of the lookup, not a check afterwards.
                DemoPosition.account_id == account.id,
            )
        )
    ).scalar_one_or_none()
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")

    quote = await _quote(position.symbol)
    if quote is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Live market data is unavailable, so the position cannot be priced.",
        )

    trade = demo_engine.close_position(account, position, quote)
    db.add(trade)
    await db.delete(position)
    await db.commit()
    return {"realized_pnl": trade.realized_pnl, "balance": account.balance}


@router.get("/trades")
async def list_trades(
    limit: int = 100,
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    account = await _account_for(db, user)
    rows = (
        (
            await db.execute(
                select(DemoTrade)
                .where(DemoTrade.account_id == account.id)
                .order_by(DemoTrade.id.desc())
                .limit(min(max(limit, 1), 500))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": t.id, "symbol": t.symbol, "side": t.side.value,
            "volume": t.volume, "entry_price": t.entry_price,
            "exit_price": t.exit_price, "realized_pnl": t.realized_pnl,
            "source": t.source.value, "close_reason": t.close_reason,
            "signal_confidence": t.signal_confidence, "signal_rr": t.signal_rr,
            "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            "account_type": "J_GOLD_AI_DEMO",
        }
        for t in rows
    ]


class ResetIn(BaseModel):
    confirm: bool = False


@router.post("/reset")
async def reset_demo(
    body: ResetIn,
    user: User = Depends(require_demo_access),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reset the virtual account.

    Touches nothing but this user's demo rows: no broker account, no MT5
    account, no subscription, no profile.
    """
    if not body.confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reset was not confirmed.")

    account = await _account_for(db, user)
    for position in await _open_positions(db, account):
        await db.delete(position)
    for trade in (
        (await db.execute(select(DemoTrade).where(DemoTrade.account_id == account.id)))
        .scalars()
        .all()
    ):
        await db.delete(trade)

    account.balance = account.starting_balance
    account.reset_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            user_id=user.id, event=audit.DEMO_RESET, detail={}
        )
    )
    await db.commit()
    return {"balance": account.balance, "detail": "Demo account reset."}
