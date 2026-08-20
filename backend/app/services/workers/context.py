"""Read-only projections of real state, one per data scope.

Section 75: each worker receives only what its role needs. These are built
by *allowlist* — every field is named explicitly and copied out of the ORM
object. A denylist would fail open the day someone adds a column; this
fails closed, because a new column is invisible until somebody adds a line
here on purpose.

Nothing in this module reads config, so no secret is reachable from a
projection even by accident: no JWT_SECRET, no MT5_BRIDGE_TOKEN, no
ANTHROPIC_API_KEY, no DATABASE_URL, no password hash.

Projections are frozen. A worker cannot mutate what it was shown and have
that mean anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .capabilities import DataScope, WorkerRole, require_scope


@dataclass(frozen=True, slots=True)
class AccountProfile:
    """Who the customer is. No password hash, ever."""

    user_id: int
    email: str
    role: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class TradingStatus:
    """Why the bot is or is not trading — section 65's worked example.

    Carries each gate's live value *and* the configured minimum beside it,
    so an explanation can cite both rather than asserting a verdict.
    """

    bot_enabled: bool
    trading_mode: str
    emergency_stop: bool
    halted_today: bool
    last_signal_action: str | None
    last_confidence: int | None
    min_confidence: int
    last_rr: float | None
    min_rr: float
    trades_today: int
    max_trades_per_day: int
    open_positions: int
    max_open_positions: int


@dataclass(frozen=True, slots=True)
class RiskEnvelope:
    """The configured limits. Read-only — changing one is a WRITE."""

    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_trades_per_day: int
    max_open_positions: int
    max_lot_size: float
    min_confidence: int
    min_rr: float
    max_spread_points: int


@dataclass(frozen=True, slots=True)
class BrokerConnectivity:
    """Whether the broker link is up. Never credentials or endpoints."""

    connected: bool
    account_type: str | None
    currency: str | None
    server_allows_real: bool


def project_account_profile(role: WorkerRole, user: Any) -> AccountProfile:
    require_scope(role, DataScope.ACCOUNT_PROFILE)
    return AccountProfile(
        user_id=user.id,
        email=user.email,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        is_active=bool(user.is_active),
    )


def project_risk_envelope(role: WorkerRole, settings: Any) -> RiskEnvelope:
    require_scope(role, DataScope.RISK_SETTINGS)
    return RiskEnvelope(
        max_risk_per_trade_pct=float(settings.max_risk_per_trade_pct),
        max_daily_loss_pct=float(settings.max_daily_loss_pct),
        max_trades_per_day=int(settings.max_trades_per_day),
        max_open_positions=int(settings.max_open_positions),
        max_lot_size=float(settings.max_lot_size),
        min_confidence=int(settings.min_confidence),
        min_rr=float(settings.min_rr),
        max_spread_points=int(settings.max_spread_points),
    )


def project_trading_status(
    role: WorkerRole,
    settings: Any,
    *,
    last_signal: Any | None = None,
    trades_today: int = 0,
    open_positions: int = 0,
    halted_today: bool = False,
) -> TradingStatus:
    require_scope(role, DataScope.TRADING_STATUS)
    action = None
    confidence = None
    rr = None
    if last_signal is not None:
        raw = getattr(last_signal, "action", None)
        action = raw.value if hasattr(raw, "value") else (str(raw) if raw else None)
        confidence = getattr(last_signal, "confidence", None)
        confidence = int(confidence) if confidence is not None else None
        rr = getattr(last_signal, "rr", None)
        rr = float(rr) if rr is not None else None
    return TradingStatus(
        bot_enabled=bool(settings.bot_enabled),
        trading_mode=(
            settings.trading_mode.value
            if hasattr(settings.trading_mode, "value")
            else str(settings.trading_mode)
        ),
        emergency_stop=bool(settings.emergency_stop),
        halted_today=bool(halted_today),
        last_signal_action=action,
        last_confidence=confidence,
        min_confidence=int(settings.min_confidence),
        last_rr=rr,
        min_rr=float(settings.min_rr),
        trades_today=int(trades_today),
        max_trades_per_day=int(settings.max_trades_per_day),
        open_positions=int(open_positions),
        max_open_positions=int(settings.max_open_positions),
    )


def project_broker_connectivity(
    role: WorkerRole,
    *,
    connected: bool,
    account_type: str | None,
    currency: str | None,
    server_allows_real: bool,
) -> BrokerConnectivity:
    require_scope(role, DataScope.BROKER_CONNECTIVITY)
    return BrokerConnectivity(
        connected=bool(connected),
        account_type=account_type,
        currency=currency,
        server_allows_real=bool(server_allows_real),
    )
