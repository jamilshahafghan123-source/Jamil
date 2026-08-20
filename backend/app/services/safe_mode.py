"""System-wide SAFE MODE — fail closed when the platform is uncertain.

Section 84. The rule this encodes: automated trading must never continue
through a state the system cannot vouch for. Uncertainty is not neutral.
Stale prices, an unreachable bridge or an unverifiable risk engine are all
reasons to stop opening new automated positions, because each one means the
numbers a decision would rest on are not known to be true.

Two things it deliberately does NOT do:

* It does not close anything. Entering safe mode stops *new* automated
  execution; positions already open stay open and remain manageable. A
  mass close triggered by a monitoring blip would itself be the incident.
* It does not lock customers out. Login, account viewing, history, support
  and diagnostics all stay available, because a customer whose bot has
  paused is exactly the customer who needs to see why.

Evaluation is pure: it takes readings and returns a verdict, touching no
database and no network, so it is cheap to call on every cycle and trivial
to test against states that would be dangerous to reproduce for real.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


class SafeModeReason(str, enum.Enum):
    """Why the system stopped trusting itself. Section 84's trigger list."""

    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    MISSING_PRICES = "MISSING_PRICES"
    INCONSISTENT_CANDLES = "INCONSISTENT_CANDLES"
    RISK_ENGINE_UNAVAILABLE = "RISK_ENGINE_UNAVAILABLE"
    BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"
    BRIDGE_AUTH_FAILURE = "BRIDGE_AUTH_FAILURE"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    DATABASE_DEGRADED = "DATABASE_DEGRADED"
    INSTRUMENT_METADATA_UNAVAILABLE = "INSTRUMENT_METADATA_UNAVAILABLE"


#: What a customer is told, per reason. Plain language, no blame, no jargon,
#: and never a raw exception — section 84 asks for an understandable reason.
_CUSTOMER_MESSAGE: dict[SafeModeReason, str] = {
    SafeModeReason.STALE_MARKET_DATA: (
        "Market data has not updated recently, so automated trading is paused "
        "until prices are live again."
    ),
    SafeModeReason.MISSING_PRICES: (
        "Live prices are unavailable, so automated trading is paused."
    ),
    SafeModeReason.INCONSISTENT_CANDLES: (
        "Price history looks inconsistent, so automated trading is paused "
        "until it can be verified."
    ),
    SafeModeReason.RISK_ENGINE_UNAVAILABLE: (
        "Risk checks are unavailable, so no automated trade can be approved."
    ),
    SafeModeReason.BROKER_UNAVAILABLE: (
        "The trading connection is unavailable, so automated trading is paused."
    ),
    SafeModeReason.BRIDGE_AUTH_FAILURE: (
        "The trading connection needs to be re-authorised. Automated trading "
        "is paused and the operator has been notified."
    ),
    SafeModeReason.EXECUTION_FAILURE: (
        "Order execution reported a problem, so automated trading is paused."
    ),
    SafeModeReason.DATABASE_DEGRADED: (
        "A storage problem was detected, so automated trading is paused."
    ),
    SafeModeReason.INSTRUMENT_METADATA_UNAVAILABLE: (
        "Instrument details are unavailable, so position sizes cannot be "
        "calculated safely and automated trading is paused."
    ),
}

#: The banner text section 84 asks to show customers.
SAFE_MODE_BANNER = "AUTOMATED TRADING TEMPORARILY PAUSED"

#: How old the last tick may be before prices count as stale.
DEFAULT_MAX_TICK_AGE = timedelta(seconds=90)


@dataclass(frozen=True, slots=True)
class SafeModeState:
    """The verdict. `active` is the only thing execution paths need."""

    active: bool
    reasons: tuple[SafeModeReason, ...] = ()
    banner: str | None = None
    #: One line per reason, safe to show a customer.
    customer_messages: tuple[str, ...] = field(default=())

    @property
    def blocks_automated_trading(self) -> bool:
        """Safe mode blocks new automated entries. Always, no override."""
        return self.active

    @property
    def blocks_account_viewing(self) -> bool:
        """It never does. Kept explicit so the intent is not re-litigated."""
        return False

    def as_dict(self) -> dict:
        return {
            "active": self.active,
            "reasons": [r.value for r in self.reasons],
            "banner": self.banner,
            "customer_messages": list(self.customer_messages),
        }


def evaluate(
    *,
    bridge_connected: bool,
    bridge_authenticated: bool = True,
    last_tick_at: datetime | None,
    now: datetime | None = None,
    max_tick_age: timedelta = DEFAULT_MAX_TICK_AGE,
    risk_engine_available: bool = True,
    database_healthy: bool = True,
    instrument_metadata_available: bool = True,
    recent_execution_failures: int = 0,
    execution_failure_threshold: int = 3,
    candles_consistent: bool = True,
) -> SafeModeState:
    """Decide whether the platform may keep trading automatically.

    Every parameter defaults to the *healthy* value so a caller that has
    not wired a check yet does not accidentally trip safe mode — but the
    two that matter most, connectivity and tick age, are required, so they
    cannot be forgotten.
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[SafeModeReason] = []

    # Authentication is checked before connectivity: a bridge that answers
    # but rejects the token is a credential problem, not an outage, and
    # section 83 is explicit that we must not retry or guess at secrets.
    if not bridge_authenticated:
        reasons.append(SafeModeReason.BRIDGE_AUTH_FAILURE)
    elif not bridge_connected:
        reasons.append(SafeModeReason.BROKER_UNAVAILABLE)

    if last_tick_at is None:
        reasons.append(SafeModeReason.MISSING_PRICES)
    else:
        # A tick timestamped in the future is as untrustworthy as an old one.
        age = now - _as_aware(last_tick_at)
        if age > max_tick_age or age < -max_tick_age:
            reasons.append(SafeModeReason.STALE_MARKET_DATA)

    if not candles_consistent:
        reasons.append(SafeModeReason.INCONSISTENT_CANDLES)
    if not risk_engine_available:
        reasons.append(SafeModeReason.RISK_ENGINE_UNAVAILABLE)
    if not database_healthy:
        reasons.append(SafeModeReason.DATABASE_DEGRADED)
    if not instrument_metadata_available:
        reasons.append(SafeModeReason.INSTRUMENT_METADATA_UNAVAILABLE)
    if recent_execution_failures >= execution_failure_threshold:
        reasons.append(SafeModeReason.EXECUTION_FAILURE)

    if not reasons:
        return SafeModeState(active=False)

    ordered = tuple(reasons)
    return SafeModeState(
        active=True,
        reasons=ordered,
        banner=SAFE_MODE_BANNER,
        customer_messages=tuple(_CUSTOMER_MESSAGE[r] for r in ordered),
    )


def _as_aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC rather than raising mid-evaluation."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
