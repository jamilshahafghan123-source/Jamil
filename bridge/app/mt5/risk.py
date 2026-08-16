"""Pre-trade risk policy.

Every order passes through :func:`evaluate_order` before it reaches the terminal.
The policy is deliberately boring and absolute: a check either passes or the
order is refused with the numbers that made the decision, so a rejection can
always be explained.

Limits come from Settings (see .env.example):

    RISK_PER_TRADE_PCT        money between entry and stop loss, % of balance
    RISK_MAX_DAILY_LOSS_PCT   realised + floating loss for the day, % of the
                              day's opening balance
    RISK_MAX_POSITIONS        open positions allowed at once
    RISK_MAX_LOT              per-order lot ceiling
    RISK_REQUIRE_SL/TP        refuse orders without protective levels
    RISK_ALLOWED_SYMBOLS      symbol allowlist for orders
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from types import ModuleType
from typing import Any

from ..config import Settings
from ..errors import BridgeError
from .convert import naive_utc, to_dict
from .session import MT5Session

logger = logging.getLogger(__name__)

# mt5 deal types that move money. Anything else (balance operations, credits,
# corrections) is not trading P/L and must not count towards the daily loss.
DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
TRADING_DEAL_TYPES = frozenset({DEAL_TYPE_BUY, DEAL_TYPE_SELL})


class RiskRejectedError(BridgeError):
    """An order was refused by the risk policy before it was sent."""

    status_code = 403
    error_code = "risk_rejected"


def day_start(now: datetime | None = None) -> datetime:
    """Start of the current UTC day.

    MT5 timestamps are broker-server time reported as epoch seconds, so this is
    the server's day boundary, not necessarily local midnight.
    """
    moment = now or datetime.now(tz=timezone.utc)
    return datetime.combine(moment.date(), time.min, tzinfo=timezone.utc)


def money_at_risk(
    *,
    entry: float,
    stop_loss: float,
    volume: float,
    symbol_info: dict[str, Any],
) -> float | None:
    """Loss in account currency if price travels from entry to the stop loss.

    Uses the symbol's tick value, falling back to contract size for symbols that
    do not report one. Returns None when neither is available, which callers
    must treat as "cannot verify" rather than "no risk".
    """
    distance = abs(entry - stop_loss)
    if distance <= 0 or volume <= 0:
        return 0.0

    tick_size = float(symbol_info.get("trade_tick_size") or symbol_info.get("point") or 0.0)
    tick_value = float(symbol_info.get("trade_tick_value") or 0.0)
    if tick_size > 0 and tick_value > 0:
        return (distance / tick_size) * tick_value * volume

    contract_size = float(symbol_info.get("trade_contract_size") or 0.0)
    if contract_size > 0:
        # Correct for instruments quoted in the account currency (XAUUSD/USD).
        return distance * contract_size * volume

    return None


def suggested_volume(
    *,
    entry: float,
    stop_loss: float,
    balance: float,
    settings: Settings,
    symbol_info: dict[str, Any],
) -> float | None:
    """Largest volume whose stop-loss risk still fits RISK_PER_TRADE_PCT."""
    unit_risk = money_at_risk(
        entry=entry, stop_loss=stop_loss, volume=1.0, symbol_info=symbol_info
    )
    if not unit_risk or unit_risk <= 0 or balance <= 0:
        return None

    budget = balance * settings.risk_per_trade_pct / 100
    raw = budget / unit_risk

    step = float(symbol_info.get("volume_step") or 0.01)
    decimals = max(0, len(f"{step:.8f}".rstrip("0").split(".")[1]))
    floored = round((raw // step) * step, decimals)

    capped = min(floored, settings.risk_max_lot, settings.max_volume)
    minimum = float(symbol_info.get("volume_min") or step)
    return capped if capped >= minimum else 0.0


async def daily_pnl(session: MT5Session) -> dict[str, Any]:
    """Realised and floating profit/loss for the current server day."""
    start = day_start()
    now = datetime.now(tz=timezone.utc)

    def _deals(mt5: ModuleType) -> Any:
        return mt5.history_deals_get(naive_utc(start), naive_utc(now))

    deals = await session.run(_deals)
    realized = 0.0
    if deals:
        for deal in deals:
            data = to_dict(deal)
            if int(data.get("type", -1)) not in TRADING_DEAL_TYPES:
                continue
            realized += (
                float(data.get("profit") or 0.0)
                + float(data.get("swap") or 0.0)
                + float(data.get("commission") or 0.0)
            )

    positions = await session.run(lambda mt5: mt5.positions_get())
    floating = sum(float(to_dict(p).get("profit") or 0.0) for p in positions or ())

    return {
        "since": start,
        "realized": round(realized, 2),
        "floating": round(floating, 2),
        "total": round(realized + floating, 2),
        "open_positions": len(positions or ()),
    }


async def snapshot(session: MT5Session, settings: Settings) -> dict[str, Any]:
    """Current risk state — what the desk shows and what the checks act on."""
    account = await session.run(lambda mt5: mt5.account_info())
    if account is None:
        raise await session.fail("Could not read account info for the risk snapshot.")

    balance = float(account.balance)
    pnl = await daily_pnl(session)

    # The day opened with whatever we have now minus what today's trading did.
    opening_balance = balance - pnl["realized"]
    loss = max(0.0, -pnl["total"])
    loss_pct = (loss / opening_balance * 100) if opening_balance > 0 else 0.0
    budget = opening_balance * settings.risk_max_daily_loss_pct / 100

    return {
        "enabled": settings.risk_enabled,
        "currency": account.currency,
        "balance": balance,
        "equity": float(account.equity),
        "opening_balance": round(opening_balance, 2),
        "daily": pnl,
        "daily_loss": round(loss, 2),
        "daily_loss_pct": round(loss_pct, 3),
        "daily_loss_budget": round(budget, 2),
        "daily_loss_remaining": round(max(0.0, budget - loss), 2),
        "daily_loss_limit_hit": loss_pct >= settings.risk_max_daily_loss_pct > 0,
        "open_positions": pnl["open_positions"],
        "positions_remaining": max(0, settings.risk_max_positions - pnl["open_positions"]),
        "limits": {
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "max_daily_loss_pct": settings.risk_max_daily_loss_pct,
            "max_positions": settings.risk_max_positions,
            "max_lot": min(settings.risk_max_lot, settings.max_volume),
            "require_sl": settings.risk_require_sl,
            "require_tp": settings.risk_require_tp,
            "allowed_symbols": settings.allowed_symbol_list,
            "demo_only": not settings.allow_live_trading,
        },
    }


async def evaluate_order(
    session: MT5Session,
    settings: Settings,
    *,
    symbol: str,
    volume: float,
    entry: float,
    sl: float | None,
    tp: float | None,
    symbol_info: dict[str, Any],
) -> dict[str, Any]:
    """Run the policy. Raises RiskRejectedError on the first breach."""
    if not settings.risk_enabled:
        return {"enabled": False, "checks": []}

    def reject(rule: str, message: str, **details: Any) -> RiskRejectedError:
        logger.warning("Risk policy rejected an order (%s): %s", rule, message)
        return RiskRejectedError(message, details={"rule": rule, "symbol": symbol, **details})

    allowed = settings.allowed_symbol_list
    if allowed and symbol.upper() not in allowed:
        raise reject(
            "allowed_symbols",
            f"'{symbol}' is not on the trading allowlist ({', '.join(allowed)}).",
            allowed_symbols=allowed,
        )

    if settings.risk_require_sl and not sl:
        raise reject("require_sl", "A stop loss is required on every order.")
    if settings.risk_require_tp and not tp:
        raise reject("require_tp", "A take profit is required on every order.")

    lot_cap = min(settings.risk_max_lot, settings.max_volume)
    if volume > lot_cap:
        raise reject(
            "max_lot",
            f"Volume {volume} exceeds the maximum lot of {lot_cap}.",
            volume=volume,
            max_lot=lot_cap,
        )

    state = await snapshot(session, settings)

    if state["open_positions"] >= settings.risk_max_positions:
        raise reject(
            "max_positions",
            f"{state['open_positions']} positions are already open; the limit is "
            f"{settings.risk_max_positions}.",
            open_positions=state["open_positions"],
            max_positions=settings.risk_max_positions,
        )

    if state["daily_loss_limit_hit"]:
        raise reject(
            "max_daily_loss",
            f"The daily loss limit is reached: {state['daily_loss_pct']}% of the day's "
            f"opening balance against a {settings.risk_max_daily_loss_pct}% cap. "
            "No new orders until the next trading day.",
            daily_loss=state["daily_loss"],
            daily_loss_pct=state["daily_loss_pct"],
            max_daily_loss_pct=settings.risk_max_daily_loss_pct,
        )

    assessment: dict[str, Any] = {
        "enabled": True,
        "daily_loss_pct": state["daily_loss_pct"],
        "daily_loss_remaining": state["daily_loss_remaining"],
        "open_positions": state["open_positions"],
    }

    if sl and settings.risk_per_trade_pct > 0:
        risk_money = money_at_risk(
            entry=entry, stop_loss=sl, volume=volume, symbol_info=symbol_info
        )
        if risk_money is None:
            raise reject(
                "risk_per_trade",
                f"Cannot price the stop-loss risk for '{symbol}': the symbol reports "
                "neither a tick value nor a contract size.",
            )

        balance = state["balance"]
        risk_pct = (risk_money / balance * 100) if balance > 0 else 0.0
        budget = balance * settings.risk_per_trade_pct / 100

        # Tolerance for float noise only - not a soft limit.
        if risk_money > budget + 1e-9:
            fit = suggested_volume(
                entry=entry,
                stop_loss=sl,
                balance=balance,
                settings=settings,
                symbol_info=symbol_info,
            )
            raise reject(
                "risk_per_trade",
                f"This order risks {risk_money:.2f} {state['currency']} "
                f"({risk_pct:.2f}% of balance) between entry and stop loss; the limit is "
                f"{settings.risk_per_trade_pct}% ({budget:.2f} {state['currency']})."
                + (f" Largest volume that fits: {fit}." if fit else ""),
                risk_money=round(risk_money, 2),
                risk_pct=round(risk_pct, 3),
                risk_budget=round(budget, 2),
                max_risk_pct=settings.risk_per_trade_pct,
                suggested_volume=fit,
            )

        assessment["risk_money"] = round(risk_money, 2)
        assessment["risk_pct"] = round(risk_pct, 3)
        assessment["risk_budget"] = round(budget, 2)

    return assessment
