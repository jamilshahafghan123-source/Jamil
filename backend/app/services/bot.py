"""The analysis pipeline and the background bot loop.

Pipeline stages, deliberately separate modules so no stage can skip another:

    market data  ->  indicators (deterministic)  ->  AI analyst (proposal)
                 ->  risk engine (verdict)       ->  executor (broker)

The bot loop only *drives* this pipeline on a timer. It has no special
privileges: it goes through `executor.execute_signal` exactly like a human
clicking "Execute" does.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..config import settings
from ..db import SessionLocal
from ..models import RiskSettings, Signal, SignalAction, TradingMode, User
from . import executor, risk_engine
from .analyst import analyze
from .indicators import TIMEFRAMES, build_snapshot
from .mt5_client import BridgeError, mt5

log = logging.getLogger("bot")

_task: asyncio.Task | None = None
# Users we've already explained the idleness for, so the reason is logged
# once per state change instead of every cycle.
_idle_logged: set[int] = set()


async def collect_market_data() -> dict:
    """Pull the live tick plus bar history for every timeframe."""
    tick = await mt5.tick(settings.SYMBOL)
    bars: dict[str, list[dict]] = {}
    for tf in TIMEFRAMES:
        bars[tf] = await mt5.bars(settings.SYMBOL, tf, settings.BARS_PER_TF)
    return build_snapshot(settings.SYMBOL, tick, bars)


async def run_analysis(
    db: AsyncSession,
    user_id: int,
    *,
    persist: bool = True,
    settings_row: RiskSettings | None = None,
) -> tuple[Signal | None, dict]:
    """Stages 1-3: data -> indicators -> AI -> persisted Signal.

    Produces a proposal. Executes nothing.
    """
    await audit.record(db, audit.ANALYSIS_REQUESTED, {"symbol": settings.SYMBOL}, user_id)

    try:
        snapshot = await collect_market_data()
    except BridgeError as e:
        await audit.record(db, audit.ANALYSIS_FAILED, {"error": str(e)}, user_id)
        raise

    # The setup engine reads the user's minimums so the UI can explain a
    # rejection. It never relaxes them, and risk_engine.evaluate still runs
    # independently before anything is sent to the broker.
    if settings_row is None:
        settings_row = (
            await db.execute(
                select(RiskSettings).where(RiskSettings.user_id == user_id)
            )
        ).scalar_one_or_none()

    analysis, problems = await analyze(snapshot, settings_row)

    if problems:
        await audit.record(
            db,
            audit.AI_OUTPUT_REJECTED,
            {"problems": problems, "bid": snapshot["bid"], "ask": snapshot["ask"]},
            user_id,
        )

    sig_data = analysis.get("signal", {})
    action = SignalAction(sig_data.get("action", "NO_TRADE"))

    signal = Signal(
        user_id=user_id,
        symbol=settings.SYMBOL,
        action=action,
        entry=sig_data.get("entry"),
        stop_loss=sig_data.get("stop_loss"),
        take_profit=sig_data.get("take_profit"),
        risk_reward=sig_data.get("risk_reward"),
        confidence=int(sig_data.get("confidence") or 0),
        reason=str(sig_data.get("reason") or ""),
        market_snapshot=snapshot,
        analysis=analysis,
    )

    if persist:
        db.add(signal)
        await db.commit()
        await db.refresh(signal)
        await audit.record(
            db,
            audit.SIGNAL_CREATED,
            {
                "signal_id": signal.id,
                "action": action.value,
                "confidence": signal.confidence,
                "entry": signal.entry,
            },
            user_id,
        )

    await audit.record(
        db,
        audit.ANALYSIS_COMPLETED,
        {"action": action.value, "confidence": signal.confidence},
        user_id,
    )
    return signal, analysis


async def _cycle_for_user(db: AsyncSession, user: User) -> None:
    row = (
        await db.execute(select(RiskSettings).where(RiskSettings.user_id == user.id))
    ).scalar_one_or_none()
    if row is None or not row.bot_enabled or row.emergency_stop:
        # Log the reason once. A silently idle bot looks identical to a
        # broken one, which is what makes this state so confusing.
        if user.id not in _idle_logged:
            reason = (
                "no risk-settings row"
                if row is None
                else "emergency_stop engaged"
                if row.emergency_stop
                else "bot_enabled is false (enable it: POST /api/risk/bot)"
            )
            log.info("bot idle for user %s: %s", user.id, reason)
            _idle_logged.add(user.id)
        return

    _idle_logged.discard(user.id)

    # Autonomous execution is DEMO/REAL only. MANUAL still generates signals
    # for the dashboard; a human decides.
    autonomous = row.trading_mode in (TradingMode.DEMO, TradingMode.REAL)

    # Clear a stale halt at the UTC day roll.
    today = datetime.now(timezone.utc).date()
    if row.halted_until_date and row.halted_until_date < today:
        row.halted_until_date = None
        await db.commit()

    if row.halted_until_date and row.halted_until_date >= today:
        return

    # Check the daily loss limit before doing any work.
    try:
        account = await mt5.account()
        stats = await executor.get_or_create_daily_stat(
            db, user.id, float(account.get("balance") or 0.0)
        )
        if risk_engine.should_halt_for_day(
            stats,
            row,
            float(account.get("equity") or 0.0),
            float(account.get("balance") or 0.0),
        ):
            row.halted_until_date = today
            await db.commit()
            await audit.record(
                db,
                audit.DAILY_LIMIT_HIT,
                {"realized": stats.realized_pnl, "equity": account.get("equity")},
                user.id,
            )
            log.warning("user %s halted for the day", user.id)
            return
    except BridgeError as e:
        log.warning("bot: bridge unavailable for user %s: %s", user.id, e)
        return

    signal, _ = await run_analysis(db, user.id, settings_row=row)
    if signal is None or signal.action == SignalAction.NO_TRADE:
        return

    if not autonomous:
        return

    result = await executor.execute_signal(
        db,
        user_id=user.id,
        signal=signal,
        settings_row=row,
        initiated_by="bot",
    )
    log.info(
        "bot cycle user=%s executed=%s reasons=%s",
        user.id,
        result.executed,
        result.reasons,
    )


async def _loop() -> None:
    log.info("bot loop started (interval=%ss)", settings.BOT_INTERVAL_SECONDS)
    while True:
        try:
            async with SessionLocal() as db:
                users = (
                    await db.execute(select(User).where(User.is_active.is_(True)))
                ).scalars().all()
                for user in users:
                    try:
                        await _cycle_for_user(db, user)
                    except Exception:
                        log.exception("bot cycle failed for user %s", user.id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("bot loop iteration failed")
        await asyncio.sleep(settings.BOT_INTERVAL_SECONDS)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
