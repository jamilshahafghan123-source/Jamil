"""Risk management.

This module is the sole authority on whether an order may be sent and how
large it may be. It is pure: it takes a proposal plus real account/market
state and returns a verdict. It never calls the broker.

The AI cannot bypass it because the AI has no path to the broker — the only
code that calls `mt5.market_order` is `executor.py`, and the executor calls
`evaluate()` first, unconditionally, on every path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ..models import DailyStat, RiskSettings, TradingMode
from . import opportunity


@dataclass
class RiskDecision:
    approved: bool
    volume: float = 0.0
    reasons: list[str] = field(default_factory=list)
    # Populated for transparency in the audit log / UI.
    risk_amount: float = 0.0
    sl_distance: float = 0.0
    computed_rr: float = 0.0
    #: Which setup class's thresholds were applied, and what they were.
    #: Section 59 requires a refusal to say exactly what it wanted.
    setup_class: str = "STANDARD"
    required_confidence: int = 0
    required_rr: float = 0.0

    def block(self, reason: str) -> "RiskDecision":
        self.approved = False
        self.volume = 0.0
        self.reasons.append(reason)
        return self


def requirement_class(setup_class: str | None) -> str:
    """Name the class, defaulting to STANDARD for an unlabelled signal.

    An unrecognised label must never fall through to something more
    permissive, so anything unknown is treated as STANDARD rather than as
    a scalp.
    """
    try:
        return opportunity.SetupClass(str(setup_class).upper()).value
    except (ValueError, AttributeError):
        return opportunity.SetupClass.STANDARD.value


def _requirement_for(settings_row, setup_class, regime):
    """Resolve the thresholds for this signal.

    The account settings go in as a tightening only — see
    opportunity.requirements_for — so no configuration can lower this
    platform below its own floor.
    """
    try:
        regime_value = opportunity.Regime(str(regime).upper()) if regime else None
    except ValueError:
        regime_value = None
    return opportunity.requirements_for(
        opportunity.SetupClass(requirement_class(setup_class)),
        regime_value,
        account_min_confidence=settings_row.min_confidence,
        account_min_rr=settings_row.min_rr,
    )


def _round_to_step(volume: float, step: float) -> float:
    if step <= 0:
        return round(volume, 2)
    # Always round DOWN — never take more risk than sizing allows.
    steps = math.floor(volume / step + 1e-9)
    return round(steps * step, 8)


def position_size(
    *,
    balance: float,
    risk_pct: float,
    sl_distance: float,
    symbol_info: dict,
    max_lot: float,
) -> tuple[float, float]:
    """Volume such that hitting the stop loses ~risk_pct of balance.

    Uses the broker's own tick_value / tick_size rather than a hardcoded
    contract size, so this stays correct across brokers and instruments:

        loss_per_lot = (sl_distance / tick_size) * tick_value

    Returns (volume, risk_amount).
    """
    risk_amount = balance * (risk_pct / 100.0)
    tick_size = float(symbol_info.get("trade_tick_size") or 0.0)
    tick_value = float(symbol_info.get("trade_tick_value") or 0.0)

    if tick_size <= 0 or tick_value <= 0 or sl_distance <= 0:
        return 0.0, risk_amount

    loss_per_lot = (sl_distance / tick_size) * tick_value
    if loss_per_lot <= 0:
        return 0.0, risk_amount

    raw = risk_amount / loss_per_lot

    vol_min = float(symbol_info.get("volume_min") or 0.01)
    vol_max = float(symbol_info.get("volume_max") or 100.0)
    vol_step = float(symbol_info.get("volume_step") or 0.01)

    capped = min(raw, vol_max, max_lot)
    volume = _round_to_step(capped, vol_step)

    # Below the broker minimum we cannot trade at all — do NOT round up to
    # vol_min, that would silently exceed the user's risk limit.
    if volume < vol_min:
        return 0.0, risk_amount

    return volume, risk_amount


def evaluate(
    *,
    action: str,
    entry: float | None,
    stop_loss: float | None,
    take_profit: float | None,
    confidence: int,
    settings_row: RiskSettings,
    account: dict,
    symbol_info: dict,
    tick: dict,
    open_positions: list[dict],
    stats: DailyStat | None,
    server_allows_real: bool,
    requested_volume: float | None = None,
    setup_class: str | None = None,
    regime: str | None = None,
) -> RiskDecision:
    """Run every gate. Order matters: cheapest and most absolute first."""
    d = RiskDecision(approved=True)
    today = datetime.now(timezone.utc).date()

    # ---- 1. Absolute stops -------------------------------------------
    if settings_row.emergency_stop:
        return d.block("EMERGENCY STOP is engaged")

    if action not in ("BUY", "SELL"):
        return d.block(f"action is {action} — nothing to execute")

    # ---- 2. Mode gating ----------------------------------------------
    mode = settings_row.trading_mode
    if mode == TradingMode.MANUAL:
        # Manual mode still allows human-initiated orders; the caller passes
        # requested_volume for those. Autonomous callers are blocked upstream.
        pass
    elif mode == TradingMode.REAL and not server_allows_real:
        return d.block(
            "REAL mode requested but ALLOW_REAL_TRADING is false on the server"
        )

    # Defence in depth: the broker tells us what kind of account this is.
    # Refuse to auto-trade a live account unless REAL is explicitly armed.
    broker_mode = str(account.get("trade_mode", "")).lower()
    if broker_mode == "real" and mode != TradingMode.REAL:
        return d.block(
            f"connected account is LIVE but trading mode is {mode.value} — refusing"
        )
    if broker_mode != "real" and mode == TradingMode.REAL:
        d.reasons.append(
            f"note: REAL mode armed but broker reports a {broker_mode} account"
        )

    # ---- 3. Daily halt ------------------------------------------------
    if settings_row.halted_until_date and settings_row.halted_until_date >= today:
        return d.block("trading halted for today (daily loss limit reached)")

    balance = float(account.get("balance") or 0.0)
    equity = float(account.get("equity") or 0.0)
    if balance <= 0:
        return d.block("account balance is zero or unavailable")

    if stats:
        # Daily loss limit, measured against the balance at day start.
        base = stats.start_balance or balance
        loss_limit = base * (settings_row.max_daily_loss_pct / 100.0)
        # Realized losses plus current open drawdown.
        floating = equity - balance
        day_pnl = stats.realized_pnl + min(floating, 0.0)
        if day_pnl <= -loss_limit:
            return d.block(
                f"daily loss limit hit: {day_pnl:.2f} <= -{loss_limit:.2f}"
            )
        if stats.trades_opened >= settings_row.max_trades_per_day:
            return d.block(
                f"max trades per day reached "
                f"({stats.trades_opened}/{settings_row.max_trades_per_day})"
            )

    # ---- 4. Exposure --------------------------------------------------
    if len(open_positions) >= settings_row.max_open_positions:
        return d.block(
            f"max open positions reached "
            f"({len(open_positions)}/{settings_row.max_open_positions})"
        )

    # ---- 5. Signal quality --------------------------------------------
    #
    # Setup-aware thresholds (sections 42-47). A scalp and a swing setup
    # are different products and are held to different, individually
    # calibrated standards. `requirements_for` treats the account's own
    # settings as a TIGHTENING only and clamps everything to an absolute
    # floor, so this can never end up more permissive than the platform's
    # own minimum however it is configured.
    requirement = _requirement_for(settings_row, setup_class, regime)
    d.setup_class = requirement_class(setup_class)
    d.required_confidence = requirement.min_confidence
    d.required_rr = requirement.min_rr

    if confidence < requirement.min_confidence:
        return d.block(
            f"confidence {confidence} below {requirement.min_confidence} "
            f"required for a {d.setup_class} setup"
        )

    # Spread is gated by whichever limit is TIGHTER — the account's or the
    # setup class's. A scalp's edge is small enough that spread alone can
    # erase it, so its own limit is stricter than the account default.
    spread = float(tick.get("spread_points") or 0.0)
    spread_limit = min(
        float(settings_row.max_spread_points), requirement.max_spread_points
    )
    if spread > spread_limit:
        return d.block(
            f"spread {spread:.0f} points exceeds max {spread_limit:.0f} "
            f"for a {d.setup_class} setup"
        )

    # ---- 6. Order sanity ----------------------------------------------
    if entry is None or stop_loss is None or take_profit is None:
        return d.block("entry, stop_loss and take_profit are all required")

    if action == "BUY" and not (stop_loss < entry < take_profit):
        return d.block("BUY requires stop_loss < entry < take_profit")
    if action == "SELL" and not (take_profit < entry < stop_loss):
        return d.block("SELL requires take_profit < entry < stop_loss")

    sl_distance = abs(entry - stop_loss)
    tp_distance = abs(take_profit - entry)
    d.sl_distance = sl_distance
    if sl_distance <= 0:
        return d.block("stop loss distance is zero")

    d.computed_rr = round(tp_distance / sl_distance, 2)
    if d.computed_rr < requirement.min_rr:
        return d.block(
            f"risk/reward {d.computed_rr} below {requirement.min_rr} "
            f"required for a {d.setup_class} setup"
        )

    # Broker minimum stop distance (points -> price).
    point = float(symbol_info.get("point") or 0.01)
    stops_level = float(symbol_info.get("trade_stops_level") or 0.0)
    min_dist = stops_level * point
    if min_dist > 0 and sl_distance < min_dist:
        return d.block(
            f"stop loss {sl_distance:.2f} closer than broker minimum {min_dist:.2f}"
        )

    # ---- 7. Sizing -----------------------------------------------------
    volume, risk_amount = position_size(
        balance=balance,
        risk_pct=settings_row.max_risk_per_trade_pct,
        sl_distance=sl_distance,
        symbol_info=symbol_info,
        max_lot=settings_row.max_lot_size,
    )
    d.risk_amount = round(risk_amount, 2)

    if requested_volume is not None:
        # A human asked for a specific size. Honour it only if it is no
        # riskier than the computed size and within the hard lot cap.
        vol_step = float(symbol_info.get("volume_step") or 0.01)
        req = _round_to_step(requested_volume, vol_step)
        if req > settings_row.max_lot_size:
            return d.block(
                f"requested volume {req} exceeds max lot size "
                f"{settings_row.max_lot_size}"
            )
        if volume > 0 and req > volume:
            return d.block(
                f"requested volume {req} exceeds risk-based size {volume}"
            )
        volume = req

    if volume <= 0:
        return d.block(
            f"computed position size is below the broker minimum for a "
            f"{settings_row.max_risk_per_trade_pct}% risk on {balance:.2f} "
            f"with a {sl_distance:.2f} stop — reduce the stop distance or "
            f"increase risk %"
        )

    if volume > settings_row.max_lot_size:
        return d.block(f"volume {volume} exceeds max lot size {settings_row.max_lot_size}")

    d.volume = volume
    d.reasons.append(
        f"approved: {volume} lots, risking ~{risk_amount:.2f} "
        f"{account.get('currency', '')} over {sl_distance:.2f} points, RR {d.computed_rr}"
    )
    return d


def should_halt_for_day(
    stats: DailyStat, settings_row: RiskSettings, equity: float, balance: float
) -> bool:
    """True when realized + floating loss has breached the daily limit."""
    base = stats.start_balance or balance
    if base <= 0:
        return False
    limit = base * (settings_row.max_daily_loss_pct / 100.0)
    day_pnl = stats.realized_pnl + min(equity - balance, 0.0)
    return day_pnl <= -limit
