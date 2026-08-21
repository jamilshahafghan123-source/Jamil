"""Risk settings, trading mode, bot toggle, and the emergency stop."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import (
    current_user,
    get_risk_settings,
    rate_limit,
    require_platform_access,
)
from ..models import DemoPosition, RiskSettings, TradingMode, User
from ..schemas import (
    BotPauseRequest,
    BotToggleRequest,
    ModeChangeRequest,
    RiskSettingsIn,
    RiskSettingsOut,
)
from ..services import bot as bot_service
from ..services import bot_status as bot_status_service
from ..services import executor, maintenance, safe_mode
from ..services.mt5_client import mt5

router = APIRouter(
    prefix="/api/risk",
    tags=["risk"],
    # Gates on the router, so a route added here later is protected by
    # default rather than shipping open.
    dependencies=[Depends(rate_limit), Depends(require_platform_access)],
)

# Typed verbatim by the user before REAL money is ever at stake.
REAL_CONFIRMATION = "I UNDERSTAND THE RISK OF REAL MONEY TRADING"


def _out(row: RiskSettings) -> RiskSettingsOut:
    return RiskSettingsOut(
        max_risk_per_trade_pct=row.max_risk_per_trade_pct,
        max_daily_loss_pct=row.max_daily_loss_pct,
        max_trades_per_day=row.max_trades_per_day,
        max_open_positions=row.max_open_positions,
        max_lot_size=row.max_lot_size,
        min_confidence=row.min_confidence,
        min_rr=row.min_rr,
        max_spread_points=row.max_spread_points,
        trading_mode=row.trading_mode,
        bot_enabled=row.bot_enabled,
        bot_paused=row.bot_paused,
        emergency_stop=row.emergency_stop,
        halted_until_date=row.halted_until_date.isoformat()
        if row.halted_until_date
        else None,
    )


@router.get("/settings", response_model=RiskSettingsOut)
async def get_settings_(row: RiskSettings = Depends(get_risk_settings)) -> RiskSettingsOut:
    return _out(row)


@router.put("/settings", response_model=RiskSettingsOut)
async def update_settings(
    body: RiskSettingsIn,
    user: User = Depends(current_user),
    row: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> RiskSettingsOut:
    before = _out(row).model_dump(mode="json")
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    await audit.record(
        db,
        audit.SETTINGS_UPDATED,
        {"before": before, "after": _out(row).model_dump(mode="json")},
        user.id,
    )
    return _out(row)


@router.post("/mode", response_model=RiskSettingsOut)
async def set_mode(
    body: ModeChangeRequest,
    user: User = Depends(current_user),
    row: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> RiskSettingsOut:
    """Change trading mode.

    REAL requires BOTH:
      1. ALLOW_REAL_TRADING=true in the server environment, and
      2. the exact confirmation phrase in this request body.

    One alone is not enough. Neither is set by default.
    """
    if body.mode == TradingMode.REAL:
        if not settings.ALLOW_REAL_TRADING:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Real trading is disabled on this server. An operator must set "
                "ALLOW_REAL_TRADING=true and redeploy before REAL mode can be armed.",
            )
        if body.confirmation != REAL_CONFIRMATION:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f'To enable REAL trading, send confirmation exactly: "{REAL_CONFIRMATION}"',
            )

    previous = row.trading_mode
    row.trading_mode = body.mode
    await db.commit()
    await db.refresh(row)

    await audit.record(
        db,
        audit.MODE_CHANGED,
        {
            "from": previous.value,
            "to": body.mode.value,
            "server_allows_real": settings.ALLOW_REAL_TRADING,
        },
        user.id,
    )
    return _out(row)


@router.post("/bot", response_model=RiskSettingsOut)
async def toggle_bot(
    body: BotToggleRequest,
    user: User = Depends(current_user),
    row: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> RiskSettingsOut:
    if body.enabled and row.emergency_stop:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Emergency stop is engaged. Clear it before starting the bot.",
        )
    row.bot_enabled = body.enabled
    await db.commit()
    await db.refresh(row)
    await audit.record(db, audit.BOT_TOGGLED, {"enabled": body.enabled}, user.id)
    return _out(row)


@router.post("/bot/pause", response_model=RiskSettingsOut)
async def pause_bot(
    body: BotPauseRequest,
    user: User = Depends(current_user),
    row: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> RiskSettingsOut:
    """Hold the bot without switching it off.

    Pausing leaves bot_enabled alone on purpose. The customer's intent is
    "stop opening things for a while", not "tear down the configuration",
    and resuming should not be an act of re-arming. Open positions keep
    being managed throughout — a pause that abandoned live positions would
    be worse than either running or stopping.

    Resuming is refused while the emergency stop is engaged, for the same
    reason starting is: the stop is the outer control and nothing below it
    may talk past it.
    """
    if not body.paused and row.emergency_stop:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Emergency stop is engaged. Clear it before resuming the bot.",
        )
    row.bot_paused = body.paused
    await db.commit()
    await db.refresh(row)
    await audit.record(db, audit.BOT_TOGGLED, {"paused": body.paused}, user.id)
    return _out(row)


@router.post("/emergency-stop", response_model=RiskSettingsOut)
async def emergency_stop(
    close_positions: bool = True,
    user: User = Depends(current_user),
    row: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> RiskSettingsOut:
    """STOP BOT. Disables the bot, blocks new orders, optionally flattens.

    Deliberately never fails on bridge errors: the local flags must be set
    even if the broker is unreachable, so nothing new can be sent when it
    comes back.
    """
    row.emergency_stop = True
    row.bot_enabled = False
    await db.commit()

    results = []
    if close_positions:
        results = await executor.close_all(db, user_id=user.id, reason="emergency_stop")

    await audit.record(
        db,
        audit.EMERGENCY_STOP,
        {"closed_positions": close_positions, "results": results},
        user.id,
    )
    await db.refresh(row)
    return _out(row)


@router.post("/emergency-stop/clear", response_model=RiskSettingsOut)
async def clear_emergency_stop(
    user: User = Depends(current_user),
    row: RiskSettings = Depends(get_risk_settings),
    db: AsyncSession = Depends(get_db),
) -> RiskSettingsOut:
    """Clear the stop. The bot stays off — restarting it is a separate act."""
    row.emergency_stop = False
    await db.commit()
    await db.refresh(row)
    await audit.record(db, audit.EMERGENCY_STOP, {"cleared": True}, user.id)
    return _out(row)


@router.get("/bot/status")
async def bot_status(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """What the bot is genuinely doing (section 17).

    Every input is an observation, not an assertion: the settings row,
    the platform's maintenance and safe-mode state, whether the venue
    needs a broker, and how many positions are actually open. Nothing
    here reports RUNNING because a switch is on.
    """
    row = (
        await db.execute(
            select(RiskSettings).where(RiskSettings.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No risk settings")

    maintenance_state = maintenance.current()
    started_at, last_cycle_at = bot_service.heartbeat()

    # The internal demo venue has no broker to lose, so a bridge outage is
    # only the bot's problem when execution actually goes to one.
    venue = getattr(row, "execution_venue", None)
    venue_name = getattr(venue, "value", venue) or "MT5_BRIDGE"
    uses_broker = venue_name != "JGOLD_DEMO"

    market_data_ok = True
    broker_connected = True
    safe_state = None
    if uses_broker:
        try:
            health = await mt5.health()
            broker_connected = bool(health.get("connected"))
            market_data_ok = broker_connected
        except Exception:
            # An unreachable bridge is a reportable state, not a 500.
            broker_connected = False
            market_data_ok = False
        safe_state = safe_mode.evaluate(
            bridge_connected=broker_connected, last_tick_at=None
        )

    open_positions = (
        await db.execute(
            select(func.count(DemoPosition.id)).where(
                DemoPosition.user_id == user.id,
                DemoPosition.closed_at.is_(None),
            )
        )
    ).scalar() or 0

    result = bot_status_service.derive(
        bot_enabled=row.bot_enabled,
        emergency_stop=row.emergency_stop,
        trading_mode=row.trading_mode.value,
        paused=row.bot_paused,
        safe_mode_active=bool(safe_state and safe_state.blocks_automated_trading),
        safe_mode_reason=getattr(safe_state, "reason", "") or "",
        maintenance_active=maintenance_state.blocks_automated_trading,
        maintenance_reason=getattr(maintenance_state, "reason", "") or "",
        market_data_ok=market_data_ok,
        broker_connected=broker_connected,
        venue_requires_broker=uses_broker,
        open_positions=int(open_positions),
        # Whether the analysis loop is actually running. Without this the
        # endpoint cannot tell a healthy idle bot from a dead one.
        started_at=started_at,
        last_cycle_at=last_cycle_at,
        interval_seconds=settings.BOT_INTERVAL_SECONDS,
    )
    payload = result.as_dict()
    payload["bot_enabled"] = row.bot_enabled
    payload["last_cycle_at"] = (
        last_cycle_at.isoformat() if last_cycle_at else None
    )
    payload["bot_paused"] = row.bot_paused
    payload["trading_mode"] = row.trading_mode.value
    payload["venue"] = venue_name
    payload["open_positions"] = int(open_positions)
    return payload
