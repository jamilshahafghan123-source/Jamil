"""In-app alert evaluation (section 62).

DELIVERY IS IN-APP ONLY, and that is a deliberate limit rather than a
first step. Section 62 forbids faking email, SMS or push while no
provider is configured, so this module has no notion of them: there is no
channel field, no delivery adapter and no queue. An alert fires by
becoming visible inside the application, and nothing here claims
otherwise.

Evaluation is pure. `evaluate` takes the alert and the current market
state and returns a message or None; it performs no I/O and mutates
nothing, so the same inputs always give the same answer and the whole
thing is testable without a database or a feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Alert, AlertKind


@dataclass(frozen=True, slots=True)
class MarketState:
    """Everything alert evaluation is allowed to look at.

    A field left None means "not known right now". No condition treats an
    unknown as a zero or as a crossing — an alert that fired because the
    feed was down would be worse than one that stayed quiet.
    """

    symbol: str
    price: float | None = None
    previous_price: float | None = None
    session: str | None = None
    session_opening: bool = False
    session_high: float | None = None
    session_low: float | None = None
    ai_signal: str | None = None
    previous_ai_signal: str | None = None
    confidence: int | None = None
    risk_reward: float | None = None
    opportunity_score: int | None = None
    closed_position: dict | None = None


def _crossed(previous: float | None, current: float | None, level: float
             ) -> bool:
    """A crossing needs both sides. One price is a position, not a move."""
    if previous is None or current is None:
        return False
    return (previous < level <= current) or (previous > level >= current)


def evaluate(alert: Alert, market: MarketState) -> str | None:
    """The message this alert should fire with, or None.

    Pure: no I/O, no mutation. The caller decides what to do with a
    message, which keeps "did it fire?" separate from "what happened
    next?".
    """
    if not alert.enabled:
        return None
    if alert.symbol.upper() != market.symbol.upper():
        return None
    # A one-shot alert that has already fired stays quiet.
    if alert.trigger_count > 0 and not alert.repeatable:
        return None

    kind = alert.kind
    level = alert.threshold

    if kind is AlertKind.PRICE_ABOVE:
        if level is None or market.price is None:
            return None
        return (f"{alert.symbol} traded at {market.price:.2f}, above "
                f"{level:.2f}.") if market.price > level else None

    if kind is AlertKind.PRICE_BELOW:
        if level is None or market.price is None:
            return None
        return (f"{alert.symbol} traded at {market.price:.2f}, below "
                f"{level:.2f}.") if market.price < level else None

    if kind is AlertKind.PRICE_CROSSES:
        if level is None:
            return None
        return (f"{alert.symbol} crossed {level:.2f} "
                f"(now {market.price:.2f}).") if _crossed(
                    market.previous_price, market.price, level) else None

    if kind is AlertKind.SESSION_OPEN:
        if not market.session_opening or not market.session:
            return None
        if alert.session and alert.session.upper() != market.session.upper():
            return None
        return f"The {market.session.replace('_', ' ').title()} session has opened."

    if kind is AlertKind.SESSION_HIGH_BREAK:
        if market.session_high is None or market.price is None:
            return None
        return (f"{alert.symbol} broke the session high "
                f"{market.session_high:.2f}.") if market.price > market.session_high else None

    if kind is AlertKind.SESSION_LOW_BREAK:
        if market.session_low is None or market.price is None:
            return None
        return (f"{alert.symbol} broke the session low "
                f"{market.session_low:.2f}.") if market.price < market.session_low else None

    if kind is AlertKind.AI_SIGNAL_CHANGE:
        if market.ai_signal is None or market.previous_ai_signal is None:
            return None
        if market.ai_signal == market.previous_ai_signal:
            return None
        return (f"J Gold AI changed its read on {alert.symbol}: "
                f"{market.previous_ai_signal} to {market.ai_signal}.")

    if kind is AlertKind.CONFIDENCE_ABOVE:
        if level is None or market.confidence is None:
            return None
        return (f"AI confidence on {alert.symbol} reached "
                f"{market.confidence}%.") if market.confidence >= level else None

    if kind is AlertKind.RR_ABOVE:
        if level is None or market.risk_reward is None:
            return None
        return (f"A setup on {alert.symbol} offers "
                f"{market.risk_reward:.2f} R:R.") if market.risk_reward >= level else None

    if kind is AlertKind.OPPORTUNITY_SCORE_ABOVE:
        if level is None or market.opportunity_score is None:
            return None
        return (f"Opportunity score on {alert.symbol} reached "
                f"{market.opportunity_score}.") if market.opportunity_score >= level else None

    if kind in (AlertKind.POSITION_CLOSED, AlertKind.STOP_LOSS_HIT,
                AlertKind.TAKE_PROFIT_HIT):
        closed = market.closed_position
        if not closed:
            return None
        reason = str(closed.get("reason", "")).upper()
        wanted = {
            AlertKind.STOP_LOSS_HIT: "STOP_LOSS",
            AlertKind.TAKE_PROFIT_HIT: "TAKE_PROFIT",
        }.get(kind)
        if wanted and reason != wanted:
            return None
        pnl = closed.get("pnl")
        tail = f" P/L {pnl:+.2f}." if isinstance(pnl, (int, float)) else "."
        label = reason.replace("_", " ").lower() or "closed"
        return f"{alert.symbol} position {label}{tail}"

    return None


#: Which kinds need a threshold, so the API can refuse an incomplete alert
#: rather than storing one that can never fire.
NEEDS_THRESHOLD = frozenset({
    AlertKind.PRICE_ABOVE, AlertKind.PRICE_BELOW, AlertKind.PRICE_CROSSES,
    AlertKind.CONFIDENCE_ABOVE, AlertKind.RR_ABOVE,
    AlertKind.OPPORTUNITY_SCORE_ABOVE,
})

#: Kinds scoped to a named session.
NEEDS_SESSION = frozenset({AlertKind.SESSION_OPEN})

KIND_LABEL: dict[AlertKind, str] = {
    AlertKind.PRICE_ABOVE: "Price rises above",
    AlertKind.PRICE_BELOW: "Price falls below",
    AlertKind.PRICE_CROSSES: "Price crosses",
    AlertKind.SESSION_OPEN: "Session opens",
    AlertKind.SESSION_HIGH_BREAK: "Session high broken",
    AlertKind.SESSION_LOW_BREAK: "Session low broken",
    AlertKind.AI_SIGNAL_CHANGE: "AI signal changes",
    AlertKind.CONFIDENCE_ABOVE: "AI confidence reaches",
    AlertKind.RR_ABOVE: "Risk/reward reaches",
    AlertKind.OPPORTUNITY_SCORE_ABOVE: "Opportunity score reaches",
    AlertKind.POSITION_CLOSED: "A position closes",
    AlertKind.STOP_LOSS_HIT: "A stop loss is hit",
    AlertKind.TAKE_PROFIT_HIT: "A take profit is hit",
}


# --------------------------------------------------------------- firing
#
# Evaluation above is pure. These two do the I/O, and they are the ONLY
# things that write trigger state — so "did it match?" and "what happened
# next?" stay separate questions with separate tests.


async def fire(db: AsyncSession, row: Alert, message: str) -> None:
    """Mark an alert as fired. The only place that writes trigger state."""
    row.triggered_at = datetime.now(timezone.utc)
    row.trigger_count += 1
    row.last_message = message
    row.acknowledged = False
    await db.commit()


async def dispatch(
    db: AsyncSession, *, user_id: int, market: MarketState
) -> list[tuple[Alert, str]]:
    """Evaluate this customer's alerts against the market and fire matches.

    THE MISSING CALLER. Every piece of this system existed — the kinds,
    the rules, the table, the endpoints, the panel — and nothing ever
    called `evaluate`, so no alert could fire and `trigger_count` stayed
    at zero forever. An alert nobody evaluates is a promise, not a
    feature.

    Returns what fired, so the caller can log or report it. Scoped to one
    customer by query, so a dispatch for one account can never touch
    another's alerts.
    """
    rows = (
        (
            await db.execute(
                select(Alert).where(
                    Alert.user_id == user_id,
                    Alert.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    fired: list[tuple[Alert, str]] = []
    for row in rows:
        message = evaluate(row, market)
        if message is None:
            continue
        await fire(db, row, message)
        fired.append((row, message))
    return fired
