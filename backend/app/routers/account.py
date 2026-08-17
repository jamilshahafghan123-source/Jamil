"""Account, live price, positions, and trade history — all read-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..deps import current_user, get_risk_settings, rate_limit
from ..models import OrderLog, RiskSettings, Signal, User
from ..schemas import (
    AccountInfo,
    BotStatus,
    DashboardSnapshot,
    Deal,
    OrderLogOut,
    Position,
    Tick,
)
from ..services import executor
from ..services.mt5_client import BridgeError, mt5

router = APIRouter(prefix="/api", tags=["account"], dependencies=[Depends(rate_limit)])


def _bridge_error(e: BridgeError) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"MT5 bridge: {e}")


@router.get("/account", response_model=AccountInfo)
async def get_account(_: User = Depends(current_user)) -> AccountInfo:
    try:
        return AccountInfo(**await mt5.account())
    except BridgeError as e:
        raise _bridge_error(e)


@router.get("/market/tick", response_model=Tick)
async def get_tick(_: User = Depends(current_user)) -> Tick:
    try:
        return Tick(**await mt5.tick(settings.SYMBOL))
    except BridgeError as e:
        raise _bridge_error(e)


@router.get("/positions", response_model=list[Position])
async def get_positions(_: User = Depends(current_user)) -> list[Position]:
    try:
        return [Position(**p) for p in await mt5.positions(settings.SYMBOL)]
    except BridgeError as e:
        raise _bridge_error(e)


@router.get("/history/deals", response_model=list[Deal])
async def get_deals(
    days: int = Query(7, ge=1, le=90), _: User = Depends(current_user)
) -> list[Deal]:
    try:
        return [Deal(**d) for d in await mt5.history(days)]
    except BridgeError as e:
        raise _bridge_error(e)


@router.get("/history/orders", response_model=list[OrderLogOut])
async def get_order_logs(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrderLog]:
    rows = (
        await db.execute(
            select(OrderLog)
            .where(OrderLog.user_id == user.id)
            .order_by(desc(OrderLog.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


@router.get("/status", response_model=BotStatus)
async def get_status(
    user: User = Depends(current_user),
    risk: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> BotStatus:
    connected = await mt5.connected()

    balance = 0.0
    equity = 0.0
    if connected:
        try:
            acct = await mt5.account()
            balance = float(acct.get("balance") or 0.0)
            equity = float(acct.get("equity") or 0.0)
        except BridgeError:
            connected = False

    stats = await executor.get_or_create_daily_stat(db, user.id, balance)
    last = (
        await db.execute(
            select(Signal.created_at)
            .where(Signal.user_id == user.id)
            .order_by(desc(Signal.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()

    return BotStatus(
        bot_enabled=risk.bot_enabled,
        emergency_stop=risk.emergency_stop,
        trading_mode=risk.trading_mode,
        real_trading_allowed_by_server=settings.ALLOW_REAL_TRADING,
        bridge_connected=connected,
        halted_today=bool(risk.halted_until_date and risk.halted_until_date >= today),
        trades_today=stats.trades_opened,
        # Realized plus current floating, which is what a trader actually feels.
        pnl_today=round(stats.realized_pnl + (equity - balance), 2),
        last_signal_at=last,
    )


@router.get("/dashboard", response_model=DashboardSnapshot)
async def dashboard(
    user: User = Depends(current_user),
    risk: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> DashboardSnapshot:
    """One round trip for the whole dashboard, degrading gracefully."""
    account = tick = None
    positions: list[Position] = []
    try:
        account = AccountInfo(**await mt5.account())
        tick = Tick(**await mt5.tick(settings.SYMBOL))
        positions = [Position(**p) for p in await mt5.positions(settings.SYMBOL)]
    except BridgeError:
        pass  # status below reports bridge_connected=False

    status_obj = await get_status(user=user, risk=risk, db=db)
    return DashboardSnapshot(
        account=account, tick=tick, positions=positions, status=status_obj
    )
