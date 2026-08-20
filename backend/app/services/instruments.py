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
    FUTURES = "FUTURES"
    ETFS = "ETFS"
    STOCKS = "STOCKS"
    ENERGY = "ENERGY"


class InstrumentStatus(str, enum.Enum):
    """What the platform can honestly do with this symbol today.

    ENABLED      real prices, real demo execution
    DATA_ONLY    real prices, charting and analysis, but no execution
    COMING_SOON  declared and specified, but no data feed yet
    UNSUPPORTED  will not be offered; kept so search can say so plainly
    DISABLED     temporarily withdrawn by an operator

    Nothing outside ENABLED and DATA_ONLY may ever be priced. A symbol
    without a feed shows its status, never a number.
    """

    ENABLED = "ENABLED"
    DATA_ONLY = "DATA_ONLY"
    COMING_SOON = "COMING_SOON"
    UNSUPPORTED = "UNSUPPORTED"
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
    #: 24/7 markets do not close; used for session awareness.
    always_open: bool = False
    #: Extra search terms — a company or common name a user would type.
    aliases: tuple[str, ...] = ()

    @property
    def tradable(self) -> bool:
        return self.status is InstrumentStatus.ENABLED

    @property
    def priceable(self) -> bool:
        """Whether a real feed exists. The gate on showing any number."""
        return self.status in (
            InstrumentStatus.ENABLED, InstrumentStatus.DATA_ONLY
        )

    def matches(self, query: str) -> bool:
        """Symbol, display name, class or aliases — for global search."""
        q = (query or "").strip().lower()
        if not q:
            return True
        haystack = " ".join((
            self.symbol, self.display_name, self.asset_class.value,
            self.base_currency, self.quote_currency, " ".join(self.aliases),
        )).lower()
        return q in haystack

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
            "base_currency": self.base_currency,
            "priceable": self.priceable,
            "always_open": self.always_open,
            "aliases": list(self.aliases),
        }


#: XAUUSD is the only tradable instrument. The rest are declared with real
#: specifications so enabling one is a status change, not a rewrite.
#: XAUUSD is the only ENABLED instrument: it is the only symbol with a live
#: feed behind it. Everything else is declared with real contract
#: specifications so enabling one is a status change rather than a rewrite,
#: and until then is never priced. A COMING_SOON symbol shows its status in
#: search and the watchlist, never a number.
_INSTRUMENTS: tuple[Instrument, ...] = (
    # ---- METALS
    Instrument(
        symbol="XAUUSD", display_name="Gold / US Dollar",
        asset_class=AssetClass.METALS, status=InstrumentStatus.ENABLED,
        digits=2, contract_size=100.0, tick_size=0.01, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="XAU", aliases=("gold",),
    ),
    Instrument(
        symbol="XAGUSD", display_name="Silver / US Dollar",
        asset_class=AssetClass.METALS, status=InstrumentStatus.COMING_SOON,
        digits=3, contract_size=5000.0, tick_size=0.001, tick_value=5.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="XAG", aliases=("silver",),
    ),
    Instrument(
        symbol="XPTUSD", display_name="Platinum / US Dollar",
        asset_class=AssetClass.METALS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=100.0, tick_size=0.01, tick_value=1.0,
        min_volume=0.01, max_volume=50.0, volume_step=0.01,
        base_currency="XPT", aliases=("platinum",),
    ),

    # ---- ENERGY
    Instrument(
        symbol="USOIL", display_name="WTI Crude Oil",
        asset_class=AssetClass.ENERGY, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1000.0, tick_size=0.01, tick_value=10.0,
        min_volume=0.01, max_volume=50.0, volume_step=0.01,
        aliases=("oil", "wti", "crude"),
    ),

    # ---- FOREX
    Instrument(
        symbol="EURUSD", display_name="Euro / US Dollar",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=1e-05, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="EUR", aliases=('euro', 'fiber'),
    ),
    Instrument(
        symbol="GBPUSD", display_name="British Pound / US Dollar",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=1e-05, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="GBP", aliases=('cable', 'sterling', 'pound'),
    ),
    Instrument(
        symbol="USDJPY", display_name="US Dollar / Japanese Yen",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=3, contract_size=100000.0, tick_size=0.001, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="USD", quote_currency="JPY", aliases=('yen',),
    ),
    Instrument(
        symbol="USDCHF", display_name="US Dollar / Swiss Franc",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=1e-05, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="USD", aliases=('swissy', 'franc'),
    ),
    Instrument(
        symbol="AUDUSD", display_name="Australian Dollar / US Dollar",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=1e-05, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="AUD", aliases=('aussie',),
    ),
    Instrument(
        symbol="NZDUSD", display_name="New Zealand Dollar / US Dollar",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=1e-05, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="NZD", aliases=('kiwi',),
    ),
    Instrument(
        symbol="USDCAD", display_name="US Dollar / Canadian Dollar",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=1e-05, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="USD", aliases=('loonie',),
    ),
    Instrument(
        symbol="EURJPY", display_name="Euro / Japanese Yen",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=3, contract_size=100000.0, tick_size=0.001, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="EUR", quote_currency="JPY", aliases=(),
    ),
    Instrument(
        symbol="EURGBP", display_name="Euro / British Pound",
        asset_class=AssetClass.FOREX, status=InstrumentStatus.COMING_SOON,
        digits=5, contract_size=100000.0, tick_size=1e-05, tick_value=1.0,
        min_volume=0.01, max_volume=100.0, volume_step=0.01,
        base_currency="EUR", quote_currency="GBP", aliases=(),
    ),

    # ---- CRYPTO
    Instrument(
        symbol="BTCUSD", display_name="Bitcoin / US Dollar",
        asset_class=AssetClass.CRYPTO, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=0.01, max_volume=10.0, volume_step=0.01,
        base_currency="BTC", always_open=True, aliases=('bitcoin',),
    ),
    Instrument(
        symbol="ETHUSD", display_name="Ethereum / US Dollar",
        asset_class=AssetClass.CRYPTO, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=0.01, max_volume=10.0, volume_step=0.01,
        base_currency="ETH", always_open=True, aliases=('ethereum', 'ether'),
    ),

    # ---- INDICES
    Instrument(
        symbol="US100", display_name="US Tech 100",
        asset_class=AssetClass.INDICES, status=InstrumentStatus.COMING_SOON,
        digits=1, contract_size=1.0, tick_size=0.1, tick_value=0.1,
        min_volume=0.1, max_volume=50.0, volume_step=0.1, aliases=('nasdaq', 'ndx'),
    ),
    Instrument(
        symbol="US30", display_name="US Wall Street 30",
        asset_class=AssetClass.INDICES, status=InstrumentStatus.COMING_SOON,
        digits=1, contract_size=1.0, tick_size=0.1, tick_value=0.1,
        min_volume=0.1, max_volume=50.0, volume_step=0.1, aliases=('dow', 'dow jones'),
    ),
    Instrument(
        symbol="SP500", display_name="US 500",
        asset_class=AssetClass.INDICES, status=InstrumentStatus.COMING_SOON,
        digits=1, contract_size=1.0, tick_size=0.1, tick_value=0.1,
        min_volume=0.1, max_volume=50.0, volume_step=0.1, aliases=('spx', 's&p', 'sp500'),
    ),
    Instrument(
        symbol="GER40", display_name="Germany 40",
        asset_class=AssetClass.INDICES, status=InstrumentStatus.COMING_SOON,
        digits=1, contract_size=1.0, tick_size=0.1, tick_value=0.1,
        min_volume=0.1, max_volume=50.0, volume_step=0.1, aliases=('dax',),
    ),
    Instrument(
        symbol="UK100", display_name="UK 100",
        asset_class=AssetClass.INDICES, status=InstrumentStatus.COMING_SOON,
        digits=1, contract_size=1.0, tick_size=0.1, tick_value=0.1,
        min_volume=0.1, max_volume=50.0, volume_step=0.1, aliases=('ftse',),
    ),
    Instrument(
        symbol="JP225", display_name="Japan 225",
        asset_class=AssetClass.INDICES, status=InstrumentStatus.COMING_SOON,
        digits=1, contract_size=1.0, tick_size=1.0, tick_value=1.0,
        min_volume=0.1, max_volume=50.0, volume_step=0.1, aliases=('nikkei',),
    ),

    # ---- FUTURES (tick size and value are the exchange's own)
    Instrument(
        symbol="ES", display_name="E-mini S&P 500 Future",
        asset_class=AssetClass.FUTURES, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.25, tick_value=12.5,
        min_volume=1.0, max_volume=50.0, volume_step=1.0, aliases=('emini', 'es1', 's&p future'),
    ),
    Instrument(
        symbol="NQ", display_name="E-mini Nasdaq 100 Future",
        asset_class=AssetClass.FUTURES, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.25, tick_value=5.0,
        min_volume=1.0, max_volume=50.0, volume_step=1.0, aliases=('emini nasdaq',),
    ),
    Instrument(
        symbol="MNQ", display_name="Micro E-mini Nasdaq 100 Future",
        asset_class=AssetClass.FUTURES, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.25, tick_value=0.5,
        min_volume=1.0, max_volume=50.0, volume_step=1.0, aliases=('micro nasdaq',),
    ),
    Instrument(
        symbol="GC", display_name="Gold Future",
        asset_class=AssetClass.FUTURES, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.1, tick_value=10.0,
        min_volume=1.0, max_volume=50.0, volume_step=1.0, aliases=('gold future', 'comex gold'),
    ),
    Instrument(
        symbol="SI", display_name="Silver Future",
        asset_class=AssetClass.FUTURES, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.005, tick_value=25.0,
        min_volume=1.0, max_volume=50.0, volume_step=1.0, aliases=('silver future',),
    ),

    # ---- ETFS
    Instrument(
        symbol="SPY", display_name="SPDR S&P 500 ETF Trust",
        asset_class=AssetClass.ETFS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('spdr', 's&p etf'),
    ),
    Instrument(
        symbol="QQQ", display_name="Invesco QQQ Trust",
        asset_class=AssetClass.ETFS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('nasdaq etf',),
    ),

    # ---- STOCKS
    Instrument(
        symbol="AAPL", display_name="Apple Inc.",
        asset_class=AssetClass.STOCKS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('apple',),
    ),
    Instrument(
        symbol="MSFT", display_name="Microsoft Corporation",
        asset_class=AssetClass.STOCKS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('microsoft',),
    ),
    Instrument(
        symbol="NVDA", display_name="NVIDIA Corporation",
        asset_class=AssetClass.STOCKS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('nvidia',),
    ),
    Instrument(
        symbol="TSLA", display_name="Tesla, Inc.",
        asset_class=AssetClass.STOCKS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('tesla',),
    ),
    Instrument(
        symbol="AMZN", display_name="Amazon.com, Inc.",
        asset_class=AssetClass.STOCKS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('amazon',),
    ),
    Instrument(
        symbol="META", display_name="Meta Platforms, Inc.",
        asset_class=AssetClass.STOCKS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('facebook',),
    ),
    Instrument(
        symbol="GOOGL", display_name="Alphabet Inc.",
        asset_class=AssetClass.STOCKS, status=InstrumentStatus.COMING_SOON,
        digits=2, contract_size=1.0, tick_size=0.01, tick_value=0.01,
        min_volume=1.0, max_volume=10000.0, volume_step=1.0, aliases=('google', 'alphabet'),
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


def search(query: str, limit: int = 25) -> list[dict]:
    """Global symbol search (section 5).

    Ranked so an exact symbol wins, then a symbol prefix, then anything
    matching the name or an alias. Unsupported and forthcoming symbols are
    included on purpose — a customer typing "TSLA" deserves to be told it
    is coming rather than that it does not exist — but they carry their
    status and are never accompanied by a price.
    """
    q = (query or "").strip().lower()
    matches = [i for i in _INSTRUMENTS if i.matches(q)]

    def rank(instrument: Instrument) -> tuple[int, str]:
        symbol = instrument.symbol.lower()
        if symbol == q:
            return (0, symbol)
        if symbol.startswith(q):
            return (1, symbol)
        if instrument.display_name.lower().startswith(q):
            return (2, symbol)
        return (3, symbol)

    matches.sort(key=rank)
    return [i.as_dict() for i in matches[:limit]]


def tradable_symbols() -> tuple[str, ...]:
    return tuple(i.symbol for i in _INSTRUMENTS if i.tradable)


def priceable_symbols() -> tuple[str, ...]:
    """The only symbols any price may ever be shown for."""
    return tuple(i.symbol for i in _INSTRUMENTS if i.priceable)
