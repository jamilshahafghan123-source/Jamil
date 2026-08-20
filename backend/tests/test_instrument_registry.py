"""The market universe (sections 4, 5).

The rule this file exists to enforce: a symbol without a live feed is
never priced. Everything else here is about the registry staying honest
as it grows.
"""

import pytest

from app.services import instruments as reg
from app.services.instruments import AssetClass, InstrumentStatus


def test_only_xauusd_is_tradable():
    assert reg.tradable_symbols() == ("XAUUSD",)


def test_only_symbols_with_a_feed_are_priceable():
    """The gate on showing any number at all.

    If a second symbol ever becomes priceable it must be because a feed
    was connected, and this assertion is the place that forces the change
    to be deliberate.
    """
    assert reg.priceable_symbols() == ("XAUUSD",)


def test_every_non_priceable_instrument_declares_a_reason():
    for instrument in reg.all_instruments():
        if instrument.priceable:
            continue
        assert instrument.status in (
            InstrumentStatus.COMING_SOON,
            InstrumentStatus.UNSUPPORTED,
            InstrumentStatus.DISABLED,
        )


def test_tradable_implies_priceable():
    """Nothing may be traded that cannot be priced."""
    for instrument in reg.all_instruments():
        if instrument.tradable:
            assert instrument.priceable


def test_every_asset_class_is_represented():
    covered = {i.asset_class for i in reg.all_instruments()}
    assert {
        AssetClass.METALS, AssetClass.FOREX, AssetClass.CRYPTO,
        AssetClass.INDICES, AssetClass.FUTURES, AssetClass.ETFS,
        AssetClass.STOCKS,
    } <= covered


def test_symbols_are_unique():
    symbols = [i.symbol for i in reg.all_instruments()]
    assert len(symbols) == len(set(symbols))


def test_every_instrument_has_usable_contract_maths():
    """A zero tick size silently makes every P/L zero."""
    for instrument in reg.all_instruments():
        assert instrument.tick_size > 0, instrument.symbol
        assert instrument.tick_value > 0, instrument.symbol
        assert instrument.volume_step > 0, instrument.symbol
        assert instrument.min_volume <= instrument.max_volume, instrument.symbol
        assert instrument.value_per_price_unit(1.0) > 0, instrument.symbol


def test_jpy_pairs_are_not_quoted_to_five_decimals():
    """A yen pair quoted like a euro pair is off by two orders of magnitude."""
    for symbol in ("USDJPY", "EURJPY"):
        instrument = reg.get(symbol)
        assert instrument.digits == 3
        assert instrument.quote_currency == "JPY"


def test_opening_an_untradable_symbol_is_refused():
    with pytest.raises(reg.InstrumentNotTradableError):
        reg.require_tradable("TSLA")


def test_unknown_symbol_is_refused():
    with pytest.raises(reg.UnknownInstrumentError):
        reg.require_tradable("NOT_A_SYMBOL")


# ------------------------------------------------------------- search

def test_exact_symbol_ranks_first():
    assert reg.search("XAUUSD")[0]["symbol"] == "XAUUSD"


def test_search_finds_instruments_by_common_name():
    for query, expected in (
        ("tesla", "TSLA"), ("apple", "AAPL"), ("bitcoin", "BTCUSD"),
        ("ftse", "UK100"), ("dax", "GER40"), ("cable", "GBPUSD"),
    ):
        symbols = [r["symbol"] for r in reg.search(query)]
        assert expected in symbols, f"{query} did not find {expected}"


def test_search_returns_forthcoming_symbols_with_their_status():
    """Answering "do you have TSLA?" honestly means saying "not yet"."""
    hit = next(r for r in reg.search("TSLA") if r["symbol"] == "TSLA")
    assert hit["status"] == "COMING_SOON"
    assert hit["tradable"] is False
    assert hit["priceable"] is False


def test_search_never_returns_a_price():
    """The registry has no business carrying quotes; this keeps it that way."""
    for result in reg.search(""):
        for forbidden in ("price", "bid", "ask", "last", "change"):
            assert forbidden not in result, f"{result['symbol']} leaked {forbidden}"


def test_empty_query_lists_the_universe():
    assert len(reg.search("", limit=50)) == len(reg.all_instruments())


def test_search_respects_its_limit():
    assert len(reg.search("", limit=5)) == 5
