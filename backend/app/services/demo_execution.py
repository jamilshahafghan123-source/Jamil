"""DemoExecutionWorker — AI Auto against the internal demo account.

THE SEPARATION IS THE POINT. This module reaches no broker: it imports the
demo engine and nothing that can send an order anywhere. A test walks its
AST to prove that, so the guarantee survives edits rather than resting on
present good behaviour.

WHAT IS SHARED AND WHAT IS NOT.
The risk manager is shared: an approved demo trade has passed exactly the
same `risk_engine.evaluate` a broker trade passes, with the same confidence
minimum, R:R minimum, spread ceiling, position cap, daily loss limit and
emergency stop. Sharing it is deliberate — a demo that trades on looser
rules teaches a customer habits that will lose them money later.

The *adapter* is not shared. Approval decides whether a trade may happen;
the venue decides where it goes, and the two questions never touch.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..models import (
    DailyStat,
    DemoAccount,
    DemoPosition,
    DemoPositionSide,
    RiskSettings,
    Signal,
    SignalAction,
    TradeSource,
)
from . import demo_engine, instruments, risk_engine

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DemoExecutionResult:
    executed: bool
    reasons: list[str]
    position_id: int | None = None
    volume: float = 0.0


async def account_for(db: AsyncSession, user_id: int) -> DemoAccount:
    row = (
        await db.execute(select(DemoAccount).where(DemoAccount.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = DemoAccount(
            user_id=user_id,
            starting_balance=demo_engine.DEFAULT_STARTING_BALANCE,
            balance=demo_engine.DEFAULT_STARTING_BALANCE,
        )
        db.add(row)
        await db.flush()
    return row


async def execute_signal(
    db: AsyncSession,
    *,
    user_id: int,
    signal: Signal,
    settings_row: RiskSettings,
    quote: demo_engine.Quote,
    account_balance: float | None = None,
    opportunity_id: int | None = None,
    opportunity_grade: str | None = None,
) -> DemoExecutionResult:
    """Risk-check an AI signal and, if approved, open a *virtual* position.

    `quote` is supplied by the caller. This module never fetches a price,
    which is what keeps it free of any broker import.
    """
    if signal.action not in (SignalAction.BUY, SignalAction.SELL):
        return DemoExecutionResult(False, ["signal is not actionable"])

    # A pause is checked here as well as in the bot's own loop, so it holds
    # for any automated caller rather than only the one that exists today.
    # It is deliberately NOT a risk-engine gate: the risk engine also rules
    # on orders the customer places by hand, and pausing the bot must not
    # stop someone trading their own account.
    if getattr(settings_row, "bot_paused", False):
        return DemoExecutionResult(False, ["the bot is paused"])

    account = await account_for(db, user_id)
    balance = account_balance if account_balance is not None else account.balance

    open_positions = list(
        (
            await db.execute(
                select(DemoPosition).where(DemoPosition.account_id == account.id)
            )
        )
        .scalars()
        .all()
    )

    instrument = instruments.require_tradable(signal.symbol)

    # THE SHARED RISK MANAGER. Same function, same limits, same refusals as
    # the broker path. Nothing about being virtual relaxes a check.
    #
    # `trade_mode` is reported as "demo" because that is the truth: this is a
    # simulated account. That also means the engine's live-account defence
    # can never be satisfied from here, so a REAL-armed setting cannot turn
    # this path into a live trade.
    today = datetime.now(timezone.utc).date()
    stats = (
        await db.execute(
            select(DailyStat).where(
                DailyStat.user_id == user_id, DailyStat.day == today
            )
        )
    ).scalar_one_or_none()

    spread_points = (
        (quote.ask - quote.bid) / instrument.tick_size
        if instrument.tick_size > 0
        else 0.0
    )

    decision = risk_engine.evaluate(
        action=signal.action.value,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        confidence=signal.confidence,
        settings_row=settings_row,
        account={"trade_mode": "demo", "balance": balance, "equity": balance},
        symbol_info={
            "trade_tick_size": instrument.tick_size,
            "trade_tick_value": instrument.tick_value,
            "volume_min": instrument.min_volume,
            "volume_max": instrument.max_volume,
            "volume_step": instrument.volume_step,
        },
        tick={"bid": quote.bid, "ask": quote.ask, "spread_points": spread_points},
        open_positions=[{"ticket": p.id} for p in open_positions],
        # The same daily counters the broker path enforces against.
        stats=stats,
        # Never true from here. A virtual venue has no live account to arm.
        server_allows_real=False,
        # The opportunity engine's own grade, so a POOR setup is refused
        # here rather than merely recorded as poor afterwards.
        opportunity_grade=opportunity_grade,
    )

    signal.risk_approved = decision.approved
    signal.risk_reasons = decision.reasons

    await audit.record(
        db,
        audit.RISK_EVALUATED,
        {
            "venue": "JGOLD_DEMO",
            "signal_id": signal.id,
            "approved": decision.approved,
            "volume": decision.volume,
            "rr": decision.computed_rr,
            "reasons": decision.reasons,
        },
        user_id,
    )

    if not decision.approved:
        await audit.record(
            db,
            audit.RISK_BLOCKED,
            {"venue": "JGOLD_DEMO", "signal_id": signal.id,
             "reasons": decision.reasons},
            user_id,
        )
        return DemoExecutionResult(False, decision.reasons)

    side = (
        DemoPositionSide.BUY
        if signal.action is SignalAction.BUY
        else DemoPositionSide.SELL
    )
    try:
        position = demo_engine.open_position(
            account,
            symbol=signal.symbol,
            side=side,
            volume=decision.volume,
            quote=quote,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            source=TradeSource.AI_AUTO,
            signal_confidence=signal.confidence,
            signal_rr=signal.risk_reward,
            # Carried, not copied: the position points at the opportunity
            # record so setup class, grade, score and session have one
            # home and cannot disagree with themselves.
            opportunity_id=opportunity_id,
        )
    except demo_engine.DemoError as exc:
        return DemoExecutionResult(False, [str(exc)])

    db.add(position)
    signal.executed = True
    await db.flush()

    await audit.record(
        db,
        audit.DEMO_AI_AUTO_EXECUTED,
        {
            "signal_id": signal.id,
            "position_id": position.id,
            "volume": position.volume,
            "confidence": signal.confidence,
        },
        user_id,
    )
    log.info(
        "AI Auto demo opened position user=%s volume=%s", user_id, position.volume
    )
    return DemoExecutionResult(True, [], position.id, position.volume)
