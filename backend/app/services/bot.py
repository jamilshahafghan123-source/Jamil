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
from ..models import (
    ExecutionVenue,
    RiskSettings,
    Signal,
    SignalAction,
    TradingMode,
    User,
)
from . import (
    demo_execution,
    executor,
    maintenance,
    opportunity,
    opportunity_inputs,
    risk_engine,
    safe_mode,
    telemetry,
)
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


async def _manage_profitable_positions(
    db: AsyncSession,
    user: User,
    signal: Signal | None,
    settings_row: RiskSettings,
) -> bool:
    """Close profitable positions when the AI no longer supports holding them.

    Returns True if at least one position was closed.  When that happens the
    caller skips new entries for the remainder of the current bot cycle.
    """
    if settings_row.trading_mode not in (TradingMode.DEMO, TradingMode.REAL):
        return False

    try:
        positions = await mt5.positions(settings.SYMBOL)
    except BridgeError as e:
        log.warning("profit manager: bridge unavailable for user %s: %s", user.id, e)
        return False

    if not positions:
        return False

    ai_action = signal.action.value if signal is not None else "NO_TRADE"
    ai_confidence = int(signal.confidence or 0) if signal is not None else 0
    closed_any = False

    for position in positions:
        profit = float(position.get("profit") or 0.0)

        # Never use this profit-taking rule to close a losing trade.
        if profit <= 0:
            continue

        side = str(position.get("type") or "").upper()
        ticket = int(position["ticket"])

        # Continue holding when the current AI analysis still strongly
        # supports the direction of the existing trade.
        still_strong = (
            ai_action == side
            and ai_confidence >= 65
        )

        if still_strong:
            log.info(
                "profit manager HOLD ticket=%s side=%s profit=%.2f ai=%s confidence=%s",
                ticket,
                side,
                profit,
                ai_action,
                ai_confidence,
            )
            continue

        reason = (
            f"auto_profit_exit: profitable position no longer strongly "
            f"supported; side={side}, ai={ai_action}, "
            f"confidence={ai_confidence}, profit={profit:.2f}"
        )

        result = await executor.close_position(
            db,
            user_id=user.id,
            ticket=ticket,
            reason=reason,
        )

        if result.get("success"):
            closed_any = True
            log.warning(
                "AUTO PROFIT CLOSE ticket=%s side=%s profit=%.2f ai=%s confidence=%s",
                ticket,
                side,
                profit,
                ai_action,
                ai_confidence,
            )
        else:
            log.warning(
                "auto profit close failed ticket=%s result=%s",
                ticket,
                result,
            )

    return closed_any



async def _manage_strong_reversal(
    db: AsyncSession,
    user: User,
    signal,
    settings_row: RiskSettings,
) -> bool:
    """Close an existing position when a strong opposite AI signal appears.

    The bot does NOT open the opposite trade in the same cycle.  It waits
    until the next cycle, re-runs analysis, and only enters if the opposite
    setup is still valid.
    """
    if signal is None or signal.action == SignalAction.NO_TRADE:
        return False

    ai_action = signal.action.value
    ai_confidence = int(signal.confidence or 0)
    min_confidence = int(settings_row.min_confidence or 80)

    if ai_confidence < min_confidence:
        return False

    try:
        positions = await mt5.positions()
    except BridgeError as e:
        log.warning(
            "reversal manager: bridge unavailable for user %s: %s",
            user.id,
            e,
        )
        return False

    closed_any = False

    for position in positions:
        if str(position.get("symbol") or "") != settings.SYMBOL:
            continue

        side = str(position.get("type") or "").upper()

        if side not in ("BUY", "SELL"):
            continue

        # Same direction: nothing to reverse.
        if side == ai_action:
            continue

        ticket = int(position["ticket"])
        profit = float(position.get("profit") or 0.0)

        reason = (
            f"strong_reversal: existing={side}, new={ai_action}, "
            f"confidence={ai_confidence}, min={min_confidence}, "
            f"profit={profit:.2f}"
        )

        result = await executor.close_position(
            db,
            user_id=user.id,
            ticket=ticket,
            reason=reason,
        )

        if result.get("success"):
            closed_any = True
            log.warning(
                "STRONG REVERSAL CLOSE ticket=%s old=%s new=%s "
                "confidence=%s profit=%.2f",
                ticket,
                side,
                ai_action,
                ai_confidence,
                profit,
            )
        else:
            log.warning(
                "strong reversal close failed ticket=%s result=%s",
                ticket,
                result,
            )

    return closed_any


#: Last safe-mode reason set logged per user, so a sustained outage does not
#: fill the log with an identical line every cycle.
_safe_mode_logged: dict[int, tuple] = {}


async def _current_safe_mode() -> safe_mode.SafeModeState:
    """Evaluate safe mode from live readings.

    Any failure to read is itself a reason to stop: an unreadable tick means
    we do not know the price, and not knowing is exactly the state safe mode
    exists for.
    """
    connected = False
    last_tick_at: datetime | None = None
    try:
        connected = await mt5.connected()
        if connected:
            tick = await mt5.tick()
            raw = tick.get("time") if isinstance(tick, dict) else None
            if raw:
                last_tick_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001 - unreadable state is untrustworthy state
        connected = False
        last_tick_at = None
    return safe_mode.evaluate(bridge_connected=connected, last_tick_at=last_tick_at)


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

    # A pause stops the bot OPENING, not the bot working. Management of
    # what is already open carries on: a pause that walked away from live
    # positions would be worse than either running or stopping, and it is
    # not what "hold off for a bit" means to anyone who says it.
    may_open = autonomous and not row.bot_paused

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

    # MAINTENANCE. Same rule as safe mode: stop opening, close nothing.
    window = maintenance.current()
    if window.blocks_automated_trading:
        if _safe_mode_logged.get(user.id) != ("MAINTENANCE",):
            log.warning("bot paused for user %s: maintenance (%s)",
                        user.id, window.reason)
            _safe_mode_logged[user.id] = ("MAINTENANCE",)
        return

    # SAFE MODE. Nothing automated proceeds on state the platform cannot
    # vouch for. This blocks new entries and also skips the analysis-driven
    # position management below, because a decision to close is only as good
    # as the prices behind it — but it closes nothing by itself. A service
    # failure must never become a trading event, so positions already open
    # stay open and remain manageable by hand.
    safe = await _current_safe_mode()
    if safe.blocks_automated_trading:
        reasons = tuple(r.value for r in safe.reasons)
        if _safe_mode_logged.get(user.id) != reasons:
            log.warning("bot paused for user %s by safe mode: %s",
                        user.id, ", ".join(reasons))
            _safe_mode_logged[user.id] = reasons
            await audit.record(
                db, audit.SAFE_MODE_PAUSED, {"reasons": list(reasons)}, user.id
            )
        return
    _safe_mode_logged.pop(user.id, None)

    signal, _ = await run_analysis(db, user.id, settings_row=row)

    # Strong opposite signal: close the existing trade first.
    # Wait until the next cycle and re-analyse before opening the reverse side.
    if autonomous:
        reversed_position = await _manage_strong_reversal(
            db,
            user,
            signal,
            row,
        )
        if reversed_position:
            return

    # Manage existing profitable positions before considering a new entry.
    # If a profitable trade is closed, wait until the next bot cycle before
    # considering another order.
    if autonomous:
        closed_profit = await _manage_profitable_positions(
            db,
            user,
            signal,
            row,
        )
        if closed_profit:
            return

    if signal is None or signal.action == SignalAction.NO_TRADE:
        return

    # ---- TELEMETRY (section 49) --------------------------------------
    #
    # Recorded as soon as the engine has an opinion and BEFORE the risk
    # manager rules, so a setup the risk manager later refuses is still on
    # the record. Without this, a quiet day is unexplainable: "no trades"
    # could equally mean nothing was found, everything was refused, or
    # execution kept failing, and those call for different responses.
    #
    # Every call below swallows its own storage errors. A reporting outage
    # must never become a refused trade.
    opportunity_id: int | None = None
    graded: dict | None = None
    try:
        now = datetime.now(timezone.utc)
        analysis = signal.analysis or {}
        trigger, distance_atr = opportunity_inputs.entry_inputs(analysis)
        graded = opportunity.evaluate(
            direction=signal.action.value,
            confidence=signal.confidence,
            expected_rr=float(signal.risk_reward or 0.0),
            factors=opportunity_inputs.factors_from_analysis(
                analysis,
                direction=signal.action.value,
                moment=now,
                spread_points=(analysis.get("market") or {}).get("spread_points"),
                max_spread_points=row.max_spread_points,
            ),
            timeframe_biases=opportunity_inputs.timeframe_biases(analysis),
            entry_trigger=trigger,
            distance_to_invalidation_atr=distance_atr,
            account_min_confidence=row.min_confidence,
            account_min_rr=row.min_rr,
        )
        opportunity_id = await telemetry.record_opportunity(
            db,
            user_id=user.id,
            symbol=signal.symbol,
            direction=signal.action.value,
            confidence=signal.confidence,
            expected_rr=float(signal.risk_reward or 0.0),
            setup_class=graded["setup_class"],
            grade=graded["score"]["grade"],
            score=graded["score"]["total"],
            required_confidence=graded["requirements"]["min_confidence"],
            required_rr=graded["requirements"]["min_rr"],
            ai_decision=graded["decision"],
            session=opportunity_inputs.session_label(now),
            rejection_reason="; ".join(graded["reasons"]) or None,
            score_breakdown=graded["score"],
        )
    except Exception:  # noqa: BLE001 - telemetry never blocks trading
        log.warning("opportunity telemetry failed for user %s", user.id,
                    exc_info=True)

    if not may_open:
        await telemetry.record_execution(
            db, opportunity_id, result="REJECTED",
            reason="the bot is not opening positions right now",
        )
        return

    # VENUE ROUTING. Approval and destination are separate questions: the
    # risk manager decides whether a trade may happen, the venue decides
    # where it goes. Neither adapter is reachable from the other.
    if row.execution_venue is ExecutionVenue.JGOLD_DEMO:
        try:
            tick = await mt5.tick()
            quote = demo_execution.demo_engine.Quote(
                bid=float(tick.get("bid") or 0.0), ask=float(tick.get("ask") or 0.0)
            )
        except Exception:  # noqa: BLE001 - no price means no trade
            log.warning("AI Auto demo: no usable price for user %s", user.id)
            return
        if quote.bid <= 0 or quote.ask <= 0:
            return

        demo_result = await demo_execution.execute_signal(
            db,
            user_id=user.id,
            signal=signal,
            settings_row=row,
            quote=quote,
            opportunity_id=opportunity_id,
        )
        await db.commit()
        # The risk ruling and what execution did are recorded separately:
        # "risk approved it and execution failed" and "risk refused it"
        # are different days and must not collapse into one status.
        await telemetry.record_risk_decision(
            db, opportunity_id,
            approved=demo_result.executed,
            reason="; ".join(demo_result.reasons) or None,
        )
        await telemetry.record_execution(
            db, opportunity_id,
            result="FILLED" if demo_result.executed else "REJECTED",
            reason=None if demo_result.executed
            else "; ".join(demo_result.reasons) or None,
        )
        log.info(
            "AI Auto demo user=%s executed=%s reasons=%s",
            user.id,
            demo_result.executed,
            demo_result.reasons,
        )
        return

    result = await executor.execute_signal(
        db,
        user_id=user.id,
        signal=signal,
        settings_row=row,
        initiated_by="bot",
    )
    await telemetry.record_risk_decision(
        db, opportunity_id,
        approved=result.executed,
        reason="; ".join(result.reasons) or None,
    )
    await telemetry.record_execution(
        db, opportunity_id,
        result="FILLED" if result.executed else "REJECTED",
        reason=None if result.executed else "; ".join(result.reasons) or None,
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
