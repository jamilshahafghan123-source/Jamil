"""J Gold AI internal demo trading engine (sections 8-11).

VIRTUAL MONEY. This engine simulates fills against real market prices and
sends nothing anywhere. It is deliberately, structurally incapable of
reaching a broker:

    it imports no broker client, no executor, and no bridge.

A test asserts that by reading this module's own imports, so the property
survives future edits rather than resting on present good behaviour. Demo
balance is not broker funds, is not subscription money, and cannot be
withdrawn — there is nothing to withdraw, because the balance exists only
as a row.

PROFIT IS COMPUTED FROM INSTRUMENT METADATA, never from a constant that
happens to suit gold. A position's value per unit of price movement comes
from the registry's tick size and tick value, so the day a second market
is enabled the arithmetic is already right.

Price is supplied by the caller. This module never fetches one, which is
what keeps it pure, synchronous where it can be, and testable against
prices that would be inconvenient to arrange for real.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import (
    DemoAccount,
    DemoPosition,
    DemoPositionSide,
    DemoTrade,
    TradeSource,
)
from .instruments import Instrument, require_tradable

DEFAULT_STARTING_BALANCE = 100000.0


class DemoError(Exception):
    """A demo operation was refused. The message is customer-safe."""


@dataclass(frozen=True, slots=True)
class Quote:
    """A price to value against. Supplied by the caller, never fetched here."""

    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    def entry_for(self, side: DemoPositionSide) -> float:
        """Buy at the ask, sell at the bid — the spread is a real cost."""
        return self.ask if side is DemoPositionSide.BUY else self.bid

    def exit_for(self, side: DemoPositionSide) -> float:
        """Close a buy at the bid, a sell at the ask."""
        return self.bid if side is DemoPositionSide.BUY else self.ask


def position_pnl(
    position: DemoPosition, quote: Quote, instrument: Instrument
) -> float:
    """Floating P/L in account currency.

    `value_per_price_unit` comes from the instrument's own tick size and
    tick value, so this is correct for gold today and for a five-decimal FX
    pair the moment one is enabled.
    """
    exit_price = quote.exit_for(position.side)
    move = exit_price - position.entry_price
    if position.side is DemoPositionSide.SELL:
        move = -move
    return round(move * instrument.value_per_price_unit(position.volume), 2)


def validate_volume(instrument: Instrument, volume: float) -> float:
    """Reject anything outside the instrument's own limits."""
    if volume is None or volume != volume:  # NaN
        raise DemoError("Volume is not a valid number.")
    if volume <= 0:
        raise DemoError("Volume must be greater than zero.")
    if volume < instrument.min_volume:
        raise DemoError(
            f"Minimum volume for {instrument.symbol} is {instrument.min_volume}."
        )
    if volume > instrument.max_volume:
        raise DemoError(
            f"Maximum volume for {instrument.symbol} is {instrument.max_volume}."
        )
    normalised = instrument.normalise_volume(volume)
    if normalised <= 0:
        raise DemoError("Volume rounds to zero at this instrument's step size.")
    return normalised


def validate_stops(
    side: DemoPositionSide,
    entry: float,
    stop_loss: float | None,
    take_profit: float | None,
) -> None:
    """A stop above entry on a buy is a typo, not a strategy."""
    if stop_loss is not None:
        if stop_loss <= 0:
            raise DemoError("Stop loss must be a positive price.")
        if side is DemoPositionSide.BUY and stop_loss >= entry:
            raise DemoError("For a buy, the stop loss must be below the entry.")
        if side is DemoPositionSide.SELL and stop_loss <= entry:
            raise DemoError("For a sell, the stop loss must be above the entry.")
    if take_profit is not None:
        if take_profit <= 0:
            raise DemoError("Take profit must be a positive price.")
        if side is DemoPositionSide.BUY and take_profit <= entry:
            raise DemoError("For a buy, the take profit must be above the entry.")
        if side is DemoPositionSide.SELL and take_profit >= entry:
            raise DemoError("For a sell, the take profit must be below the entry.")


def open_position(
    account: DemoAccount,
    *,
    symbol: str,
    side: DemoPositionSide,
    volume: float,
    quote: Quote,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    source: TradeSource = TradeSource.MANUAL,
    signal_confidence: int | None = None,
    signal_rr: float | None = None,
    opportunity_id: int | None = None,
    now: datetime | None = None,
) -> DemoPosition:
    """Build a virtual position. The caller persists it."""
    instrument = require_tradable(symbol)
    volume = validate_volume(instrument, volume)
    entry = quote.entry_for(side)
    if entry <= 0:
        raise DemoError("No usable market price is available right now.")
    validate_stops(side, entry, stop_loss, take_profit)

    return DemoPosition(
        account_id=account.id,
        symbol=instrument.symbol,
        side=side,
        volume=volume,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        source=source,
        signal_confidence=signal_confidence,
        signal_rr=signal_rr,
        opportunity_id=opportunity_id,
        opened_at=now or datetime.now(timezone.utc),
    )


def close_position(
    account: DemoAccount,
    position: DemoPosition,
    quote: Quote,
    *,
    reason: str = "MANUAL_CLOSE",
    now: datetime | None = None,
) -> DemoTrade:
    """Realise a position. Mutates the account balance; caller persists."""
    instrument = require_tradable(position.symbol)
    pnl = position_pnl(position, quote, instrument)
    account.balance = round(account.balance + pnl, 2)

    return DemoTrade(
        account_id=account.id,
        symbol=position.symbol,
        side=position.side,
        volume=position.volume,
        entry_price=position.entry_price,
        exit_price=quote.exit_for(position.side),
        realized_pnl=pnl,
        source=position.source,
        close_reason=reason,
        signal_confidence=position.signal_confidence,
        signal_rr=position.signal_rr,
        opened_at=position.opened_at,
        closed_at=now or datetime.now(timezone.utc),
    )


def stop_or_target_hit(position: DemoPosition, quote: Quote) -> str | None:
    """Whether this quote would have triggered the position's SL or TP.

    Checked against the price the position would actually close at, not the
    mid — a stop that only triggers on the mid is a stop that lies.
    """
    price = quote.exit_for(position.side)
    if position.side is DemoPositionSide.BUY:
        if position.stop_loss is not None and price <= position.stop_loss:
            return "STOP_LOSS"
        if position.take_profit is not None and price >= position.take_profit:
            return "TAKE_PROFIT"
    else:
        if position.stop_loss is not None and price >= position.stop_loss:
            return "STOP_LOSS"
        if position.take_profit is not None and price <= position.take_profit:
            return "TAKE_PROFIT"
    return None


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    balance: float
    equity: float
    floating_pnl: float
    realized_pnl: float
    free_margin: float
    open_positions: int
    currency: str

    def as_dict(self) -> dict:
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "floating_pnl": round(self.floating_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "free_margin": round(self.free_margin, 2),
            "open_positions": self.open_positions,
            "currency": self.currency,
            # Stated in the payload so no surface can forget to say it.
            "account_type": "J_GOLD_AI_DEMO",
            "virtual_money": True,
            "withdrawable": False,
        }


def snapshot(
    account: DemoAccount,
    positions: list[DemoPosition],
    quotes: dict[str, Quote],
) -> AccountSnapshot:
    """Value the account. Positions without a quote contribute zero, not a
    guess — an unpriced position is unknown, and inventing its value would
    make the equity a lie."""
    floating = 0.0
    for position in positions:
        quote = quotes.get(position.symbol)
        if quote is None:
            continue
        floating += position_pnl(position, quote, require_tradable(position.symbol))

    equity = round(account.balance + floating, 2)
    return AccountSnapshot(
        balance=account.balance,
        equity=equity,
        floating_pnl=round(floating, 2),
        realized_pnl=round(account.balance - account.starting_balance, 2),
        # No leverage model yet; free margin equals equity until one exists.
        free_margin=equity,
        open_positions=len(positions),
        currency=account.currency,
    )
