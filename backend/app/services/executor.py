"""Trade execution.

INVARIANT: this is the only module permitted to call `mt5.market_order` or
`mt5.close_position`. Every path through it calls `risk_engine.evaluate()`
first and refuses to proceed unless the decision is approved.

If you add a new execution path, it goes here, and it calls the risk engine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..config import settings
from ..models import (
    DailyStat,
    OrderLog,
    OrderStatus,
    RiskSettings,
    Signal,
    SignalAction,
    TradingMode,
)
from . import risk_engine
from .mt5_client import BridgeError, mt5

log = logging.getLogger("executor")


async def get_or_create_daily_stat(
    db: AsyncSession, user_id: int, balance: float
) -> DailyStat:
    today = datetime.now(timezone.utc).date()
    row = (
        await db.execute(
            select(DailyStat).where(
                DailyStat.user_id == user_id, DailyStat.day == today
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DailyStat(
            user_id=user_id, day=today, start_balance=balance, trades_opened=0
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


class ExecutionResult:
    def __init__(
        self,
        *,
        executed: bool,
        reasons: list[str],
        order_log_id: int | None = None,
        ticket: int | None = None,
        volume: float = 0.0,
    ) -> None:
        self.executed = executed
        self.reasons = reasons
        self.order_log_id = order_log_id
        self.ticket = ticket
        self.volume = volume

    def as_dict(self) -> dict:
        return {
            "executed": self.executed,
            "reasons": self.reasons,
            "order_log_id": self.order_log_id,
            "ticket": self.ticket,
            "volume": self.volume,
        }


async def execute_signal(
    db: AsyncSession,
    *,
    user_id: int,
    signal: Signal,
    settings_row: RiskSettings,
    requested_volume: float | None = None,
    initiated_by: str = "bot",
) -> ExecutionResult:
    """Risk-check a signal and, if approved, send it to the broker."""

    # --- gather real state -------------------------------------------
    try:
        account = await mt5.account()
        tick = await mt5.tick(settings.SYMBOL)
        symbol_info = await mt5.symbol_info(settings.SYMBOL)
        open_positions = await mt5.positions(settings.SYMBOL)
    except BridgeError as e:
        reasons = [f"cannot reach MT5 bridge: {e}"]
        await audit.record(
            db, audit.RISK_BLOCKED, {"reasons": reasons, "signal_id": signal.id}, user_id
        )
        return ExecutionResult(executed=False, reasons=reasons)

    stats = await get_or_create_daily_stat(
        db, user_id, float(account.get("balance") or 0.0)
    )

    # --- THE GATE ------------------------------------------------------
    decision = risk_engine.evaluate(
        action=signal.action.value,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        confidence=signal.confidence,
        settings_row=settings_row,
        account=account,
        symbol_info=symbol_info,
        tick=tick,
        open_positions=open_positions,
        stats=stats,
        server_allows_real=settings.ALLOW_REAL_TRADING,
        requested_volume=requested_volume,
    )

    signal.risk_approved = decision.approved
    signal.risk_reasons = decision.reasons
    await db.commit()

    await audit.record(
        db,
        audit.RISK_EVALUATED,
        {
            "signal_id": signal.id,
            "approved": decision.approved,
            "volume": decision.volume,
            "risk_amount": decision.risk_amount,
            "rr": decision.computed_rr,
            "reasons": decision.reasons,
            "initiated_by": initiated_by,
            "mode": settings_row.trading_mode.value,
        },
        user_id,
    )

    if not decision.approved:
        await audit.record(
            db,
            audit.RISK_BLOCKED,
            {"signal_id": signal.id, "reasons": decision.reasons},
            user_id,
        )
        return ExecutionResult(executed=False, reasons=decision.reasons)

    # --- log the request BEFORE sending it ----------------------------
    request_payload = {
        "symbol": settings.SYMBOL,
        "side": signal.action.value,
        "volume": decision.volume,
        "sl": signal.stop_loss,
        "tp": signal.take_profit,
        "initiated_by": initiated_by,
        "mode": settings_row.trading_mode.value,
    }
    order = OrderLog(
        user_id=user_id,
        signal_id=signal.id,
        mode=settings_row.trading_mode,
        symbol=settings.SYMBOL,
        action=signal.action,
        volume=decision.volume,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        status=OrderStatus.REQUESTED,
        request_payload=request_payload,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    await audit.record(db, audit.ORDER_REQUESTED, request_payload, user_id)

    # --- send ----------------------------------------------------------
    try:
        result = await mt5.market_order(
            symbol=settings.SYMBOL,
            side=signal.action.value,
            volume=decision.volume,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            comment=f"AI#{signal.id}",
        )
    except BridgeError as e:
        order.status = OrderStatus.ERROR
        order.broker_comment = str(e)[:255]
        order.response_payload = {"error": str(e)}
        await db.commit()
        await audit.record(
            db, audit.ORDER_RESULT, {"order_id": order.id, "error": str(e)}, user_id
        )
        return ExecutionResult(
            executed=False,
            reasons=[f"broker send failed: {e}"],
            order_log_id=order.id,
        )

    order.response_payload = result
    order.broker_retcode = result.get("retcode")
    order.broker_comment = str(result.get("comment", ""))[:255]
    order.broker_ticket = result.get("ticket")
    ok = bool(result.get("success"))
    order.status = OrderStatus.FILLED if ok else OrderStatus.REJECTED

    if ok:
        signal.executed = True
        stats.trades_opened += 1

    await db.commit()
    await audit.record(
        db,
        audit.ORDER_RESULT,
        {
            "order_id": order.id,
            "success": ok,
            "retcode": order.broker_retcode,
            "ticket": order.broker_ticket,
            "comment": order.broker_comment,
        },
        user_id,
    )

    return ExecutionResult(
        executed=ok,
        reasons=decision.reasons
        + ([] if ok else [f"broker rejected: {order.broker_comment}"]),
        order_log_id=order.id,
        ticket=order.broker_ticket,
        volume=decision.volume,
    )


async def close_position(
    db: AsyncSession, *, user_id: int, ticket: int, reason: str = "manual"
) -> dict:
    """Closing is always permitted — reducing exposure is never blocked."""
    try:
        result = await mt5.close_position(ticket)
    except BridgeError as e:
        await audit.record(
            db, audit.POSITION_CLOSED, {"ticket": ticket, "error": str(e)}, user_id
        )
        return {"success": False, "error": str(e)}

    await audit.record(
        db,
        audit.POSITION_CLOSED,
        {"ticket": ticket, "reason": reason, "result": result},
        user_id,
    )
    return result


async def close_all(db: AsyncSession, *, user_id: int, reason: str) -> list[dict]:
    try:
        positions = await mt5.positions(settings.SYMBOL)
    except BridgeError as e:
        return [{"success": False, "error": str(e)}]
    out = []
    for p in positions:
        out.append(
            await close_position(
                db, user_id=user_id, ticket=int(p["ticket"]), reason=reason
            )
        )
    return out
