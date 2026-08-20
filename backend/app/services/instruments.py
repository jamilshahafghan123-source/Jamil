"""Instrument registry (sections 4, 10).

The demo engine cannot ask the broker for contract specifications — the
whole point is that it never talks to MT5 — so the numbers a position's
value depends on live here.

Every instrument carries its own contract size, tick size and tick value.
Nothing computes profit as `(exit - entry) * volume * 100` with a constant
that happens to be right for gold; that constant is the reason platforms
report nonsense the day they add a second market. XAUUSD is the only
instrument ENABLED, and the others are declared with real specifications
so that enabling one is a status change rather than a rewrite.

`COMING_SOON` instruments are never priced and never traded. They exist so
the symbol selector can show what is planned without inventing a market.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class AssetClass(str, enum.Enum):
    METALS = "METALS"
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"
    INDICES = "INDICES"
    STOCKS = "STOCKS"
    ENERGY = "ENERGY"


class InstrumentStatus(str, enum.Enum):
    ENABLED = "ENABLED"
    COMING_SOON = "COMING_SOON"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    display_name: str
    asset_class: AssetClass
    status: InstrumentStatus
    #: Price decimals for display.
    digits: int
    #: Units of the base per 1.0 lot.
    contract_size: float
    #: Smallest price increment that changes value.
    tick_size: float
    #: Account currency gained per tick per lot.
    tick_value: float
    min_volume: float
    max_volume: float
    volume_step: float
    quote_currency: str = "USD"
    base_currency: str = ""
    #: 24/7 markets do not close; used later for session awareness.
    always_open: bool = False

    @property
    def tradable(self) -> bool:
        return self.status is InstrumentStatus.ENABLED

    def normalise_volume(self, volume: float) -> float:
        """Round to the instrument's step. Does not clamp — see validate."""
        steps = round(volume / self.volume_step)
        return round(steps * self.volume_step, 8)

    def value_per_price_unit(self, volume: float) -> float:
        """Account currency gained per 1.0 of price movement, for `volume`.

        Derived from tick size and tick value rather than assumed, so an
        instrument quoted in fractions of a cent works the same way gold
        does.
        """
        if self.tick_size <= 0:
            return 0.0
        return (self.tick_value / self.tick_size) * volume

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "display_name": self.display_name,
            "asset_class": self.asset_class.value,
            "status": self.status.value,
            "tradable": self.tradable,
            "digits": self.digits,
            "contract_size": self.contract_size,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "min_volume": self.min_volume,
            "max_volume": self.max_volume,
            "volume_step": self.volume_step,
            "quote_currency": self.quote_currency,
        }


#: XAUUSD is the only tradable instrument. The rest are declared with real
#: specifications so enabling one is a status change, not a rewrite.
_INSTRUMENTS: tuple[Instrument, ...] = (
    Instrument(
        symbol="XAUUSD", display_name="Gold / US Dollar",
        asset_class=AssetClass.METALS, status=InstrumentStatus.ENABLED,
        digits=2, contract_size=100.0, tick_size=0.01, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="XAU",
    ),
    Instrument(
        symbol="XAGUSD", display_name="Silver / US Dollar",
        asset_class=AssetClass.METALS, status=InstrumentStatus.COMING_SOON,
        digits=3, contract_size=5000.0, tick_size=0.001, tick_value=5.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="XAG",
    ),
    Instrument(
        symbol="EURUSD", display_name="Euro / US Dollar",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=0.00001, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="EUR",
    ),
    Instrument(
        symbol="GBPUSD", display_name="British Pound / US Dollar",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=0.00001, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="GBP",
    ),
    Instrument(
        symbol="BTCUSD", display_name="Bitcoin / US Dollar",
        asset_class=AssetClass.CRYPTO, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=0.01, max_volume=10.0, volume_step=0.01,
        base_currency="BTC", always_open=True,
    ),
    Instrument(
        symbol="US100", display_name="US Tech 100",
        asset_class=AssetClass.INDICES, status=InstrumentStatus.COMING_SOON,
        digits=1, contract_size=1.0, tick_size=0.1, tick_value=0.1,
        min_volume=0.1, max_volume=50.0, volume_step=0.1,
    ),
)

_BY_SYMBOL = {i.symbol: i for i in _INSTRUMENTS}

DEFAULT_SYMBOL = "XAUUSD"


class UnknownInstrumentError(Exception):
    """The symbol is not in the registry."""


class InstrumentNotTradableError(Exception):
    """The symbol exists but is not enabled for trading."""


def get(symbol: str) -> Instrument:
    try:
        return _BY_SYMBOL[(symbol or "").upper()]
    except KeyError:
        raise UnknownInstrumentError(f"Unknown symbol: {symbol!r}") from None


def require_tradable(symbol: str) -> Instrument:
    """The only door for anything that intends to open a position."""
    instrument = get(symbol)
    if not instrument.tradable:
        raise InstrumentNotTradableError(
            f"{instrument.symbol} is not available for trading yet."
        )
    return instrument


def all_instruments() -> tuple[Instrument, ...]:
    return _INSTRUMENTS


def by_asset_class() -> dict[str, list[dict]]:
    """Grouped for the symbol selector."""
    grouped: dict[str, list[dict]] = {}
    for instrument in _INSTRUMENTS:
        grouped.setdefault(instrument.asset_class.value, []).append(
            instrument.as_dict()
        )
    return grouped
