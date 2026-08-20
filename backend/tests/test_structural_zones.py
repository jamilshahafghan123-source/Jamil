"""Structural detectors behind the AI chart overlays.

These feed zones and markers straight onto the customer's chart, so the
thing worth testing is not that they find something — it is that they find
nothing when nothing is there. A detector that always returns a zone would
make the chart look informative while telling the customer nothing, which is
worse than an empty chart.
"""

from __future__ import annotations

import datetime as dt

from app.services.indicators import (
    fair_value_gaps,
    order_blocks,
    swing_markers,
    swing_points,
)

T0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def bar(i: int, o: float, h: float, lo: float, c: float) -> dict:
    return {
        "time": (T0 + dt.timedelta(minutes=15 * i)).isoformat(),
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "tick_volume": 100,
        "spread": 20,
    }


def flat_series(n: int = 40, price: float = 2000.0) -> list[dict]:
    """Overlapping bars: no imbalance anywhere by construction."""
    return [bar(i, price, price + 1, price - 1, price) for i in range(n)]


# --------------------------------------------------------------- fair value


def test_no_gaps_in_overlapping_bars():
    assert fair_value_gaps(flat_series(), atr_value=1.0) == []


def test_too_few_bars_is_not_an_error():
    assert fair_value_gaps([bar(0, 1, 2, 0, 1)], atr_value=1.0) == []
    assert fair_value_gaps([], atr_value=1.0) == []


def test_bullish_gap_is_found_with_its_band_and_start_bar():
    bars = flat_series(10)
    # Bar 8 opens far above bar 6's high: bar 7 never traded the band.
    bars[8] = bar(8, 2010, 2012, 2008, 2011)
    bars[9] = bar(9, 2011, 2013, 2010, 2012)

    gaps = fair_value_gaps(bars, atr_value=1.0)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["side"] == "bullish"
    assert gap["kind"] == "fvg"
    # The band runs from bar 6's high to bar 8's low.
    assert gap["low"] == 2001.0
    assert gap["high"] == 2008.0
    # Anchored to the middle bar — where the imbalance actually sits.
    assert gap["from_time"] == bars[7]["time"]


def test_bearish_gap_is_found():
    bars = flat_series(10)
    bars[8] = bar(8, 1990, 1992, 1988, 1989)
    bars[9] = bar(9, 1989, 1990, 1987, 1988)

    gaps = fair_value_gaps(bars, atr_value=1.0)

    assert [g["side"] for g in gaps] == ["bearish"]
    assert gaps[0]["low"] == 1992.0
    assert gaps[0]["high"] == 1999.0


def test_mitigated_gap_is_dropped():
    """Once price trades back through the band the imbalance is gone."""
    bars = flat_series(12)
    bars[6] = bar(6, 2010, 2012, 2008, 2011)
    bars[7] = bar(7, 2011, 2013, 2010, 2012)
    # A later bar reaches back down into the 2001–2008 band. Its low is kept
    # below the surrounding highs so that the retrace itself does not open a
    # fresh gap — the test is about mitigation, not about a new imbalance.
    bars[10] = bar(10, 2005, 2006, 2000.5, 2001)

    assert fair_value_gaps(bars, atr_value=1.0) == []


def test_gap_narrower_than_noise_is_ignored():
    bars = flat_series(10)
    # A 0.1 band against a 5.0 ATR is noise, not structure.
    bars[8] = bar(8, 2001.6, 2002.0, 2001.1, 2001.8)
    bars[9] = bar(9, 2001.8, 2002.2, 2001.5, 2002.0)

    assert fair_value_gaps(bars, atr_value=5.0) == []
    # The same band is meaningful when volatility is tiny.
    assert len(fair_value_gaps(bars, atr_value=0.2)) == 1


def test_gaps_are_capped_and_nearest_price_first():
    bars = flat_series(60)
    # Three separate unmitigated bullish gaps, walking away from price.
    for i, base in ((10, 2010), (20, 2030), (30, 2060)):
        bars[i] = bar(i, base, base + 2, base - 2, base + 1)
        bars[i + 1] = bar(i + 1, base + 1, base + 3, base, base + 2)
        for j in range(i + 2, 60):
            bars[j] = bar(j, base + 40, base + 41, base + 39, base + 40)

    gaps = fair_value_gaps(bars, atr_value=1.0, limit=2)

    assert len(gaps) <= 2
    last = bars[-1]["close"]
    distances = [abs((g["low"] + g["high"]) / 2 - last) for g in gaps]
    assert distances == sorted(distances)


# --------------------------------------------------------------- order blocks


def test_no_order_blocks_without_an_impulse():
    bars = flat_series()
    hi, lo = swing_points(
        _arr(bars, "high"), _arr(bars, "low")
    )
    assert order_blocks(bars, list(hi), list(lo), atr_value=5.0) == []


def test_zero_atr_returns_nothing_rather_than_dividing():
    bars = flat_series()
    assert order_blocks(bars, [], [], atr_value=0.0) == []


def test_demand_block_is_the_down_candle_before_the_rally():
    bars = flat_series(20)
    # A swing high to break, then a down candle, then an impulsive rally.
    bars[5] = bar(5, 2000, 2006, 1999, 2001)
    bars[12] = bar(12, 2001, 2001.5, 1997, 1998)   # the down candle
    bars[13] = bar(13, 1998, 2012, 1997.5, 2011)   # impulse clearing 2006
    for j in range(14, 20):
        bars[j] = bar(j, 2011, 2013, 2010, 2012)

    hi, lo = swing_points(_arr(bars, "high"), _arr(bars, "low"))
    blocks = order_blocks(bars, list(hi), list(lo), atr_value=3.0)

    assert [b["side"] for b in blocks] == ["demand"]
    assert blocks[0]["low"] == 1997.0
    assert blocks[0]["high"] == 2001.5
    assert blocks[0]["from_time"] == bars[12]["time"]


# --------------------------------------------------------------- swing points


def test_swing_markers_carry_the_bar_time():
    bars = flat_series(20)
    bars[10] = bar(10, 2000, 2020, 1999, 2001)

    hi, lo = swing_points(_arr(bars, "high"), _arr(bars, "low"))
    markers = swing_markers(bars, list(hi), list(lo))

    highs = [m for m in markers if m["side"] == "high"]
    assert any(m["price"] == 2020.0 and m["time"] == bars[10]["time"] for m in highs)
    # Chronological, so the chart draws them left to right.
    assert [m["time"] for m in markers] == sorted(m["time"] for m in markers)


def test_swing_markers_are_bounded():
    bars = flat_series(80)
    for i in range(5, 75, 5):
        bars[i] = bar(i, 2000, 2000 + i, 1999, 2001)

    hi, lo = swing_points(_arr(bars, "high"), _arr(bars, "low"))
    markers = swing_markers(bars, list(hi), list(lo), limit=4)

    assert len([m for m in markers if m["side"] == "high"]) <= 4
    assert len([m for m in markers if m["side"] == "low"]) <= 4


def test_empty_input_is_safe_everywhere():
    assert swing_markers([], [], []) == []
    assert order_blocks([], [], [], atr_value=1.0) == []
    assert fair_value_gaps([], atr_value=1.0) == []


# ------------------------------------------------------------------ helpers


def _arr(bars: list[dict], key: str):
    import numpy as np

    return np.array([b[key] for b in bars], dtype=float)


# --------------------------------------------- surfaced to the chart


def test_analyze_timeframe_exposes_the_structural_fields():
    """The chart reads these off the analysis, so they must survive the trip.

    Guards against the fields being computed and then silently dropped by
    the dataclass — an overlay that never renders looks identical to a
    market with no structure in it.
    """
    from app.services.indicators import analyze_timeframe

    bars = [
        bar(i, 2000 + i, 2000 + i + 2, 2000 + i - 2, 2000 + i + 1)
        for i in range(60)
    ]
    result = analyze_timeframe("M15", bars)

    assert result is not None
    payload = result.to_dict()
    for key in ("fvg", "order_blocks", "swings"):
        assert key in payload, f"{key} missing from the timeframe payload"
        assert isinstance(payload[key], list)
    # Swings are real on a clean trend, and each carries a plottable time.
    assert all("time" in s and "price" in s for s in payload["swings"])
