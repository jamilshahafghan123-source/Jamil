"""Indicator maths, checked against hand-computed values."""

from __future__ import annotations

import pytest

from app.analysis import indicators


def test_sma_matches_the_arithmetic_mean():
    values = [1, 2, 3, 4, 5, 6]
    result = indicators.sma(values, 3)
    assert result[:2] == [None, None]
    assert result[2] == pytest.approx(2.0)
    assert result[-1] == pytest.approx(5.0)


def test_ema_seeds_from_the_sma_then_weights_recent_bars():
    values = [1, 2, 3, 4, 5]
    result = indicators.ema(values, 3)
    assert result[2] == pytest.approx(2.0)  # SMA of 1,2,3
    # multiplier 0.5: (4 - 2) * 0.5 + 2 = 3
    assert result[3] == pytest.approx(3.0)
    assert result[4] == pytest.approx(4.0)


def test_ema_is_empty_when_history_is_shorter_than_the_period():
    assert indicators.ema([1, 2], 5) == [None, None]


def test_rsi_is_100_when_every_bar_rises():
    closes = list(range(1, 40))
    assert indicators.rsi(closes, 14)[-1] == pytest.approx(100.0)


def test_rsi_is_zero_when_every_bar_falls():
    closes = list(range(40, 1, -1))
    assert indicators.rsi(closes, 14)[-1] == pytest.approx(0.0)


def test_rsi_sits_near_the_middle_for_an_even_market():
    closes = [100 + (1 if i % 2 else -1) for i in range(60)]
    assert 40 < indicators.rsi(closes, 14)[-1] < 60


def test_macd_histogram_is_positive_in_an_uptrend():
    closes = [100 + i for i in range(80)]
    line, signal, histogram = indicators.macd(closes)
    assert line[-1] > 0
    assert signal[-1] is not None
    assert histogram[-1] == pytest.approx(line[-1] - signal[-1])


def test_true_range_uses_the_previous_close():
    highs = [10, 12]
    lows = [9, 11]
    closes = [9.5, 11.5]
    # Second bar: max(12-11, |12-9.5|, |11-9.5|) = 2.5
    assert indicators.true_range(highs, lows, closes)[1] == pytest.approx(2.5)


def test_atr_tracks_a_constant_range():
    highs = [11] * 30
    lows = [10] * 30
    closes = [10.5] * 30
    assert indicators.atr(highs, lows, closes, 14)[-1] == pytest.approx(1.0, abs=0.01)


def test_percentile_rank():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert indicators.percentile_rank(values, 5) == pytest.approx(50.0)
    assert indicators.percentile_rank(values, 10) == pytest.approx(100.0)


def test_swing_points_finds_the_obvious_pivots():
    highs = [1, 2, 5, 2, 1, 2, 1]
    lows = [5, 4, 3, 4, 1, 4, 5]
    swing_highs, swing_lows = indicators.swing_points(highs, lows, reach=2)
    assert [index for index, _ in swing_highs] == [2]
    assert [index for index, _ in swing_lows] == [4]


def test_cluster_levels_merges_nearby_pivots():
    points = [(0, 100.0), (1, 100.4), (2, 105.0)]
    levels = indicators.cluster_levels(points, tolerance=1.0)
    assert len(levels) == 2
    assert levels[0]["touches"] == 2
    assert levels[0]["price"] == pytest.approx(100.2)
    assert levels[1]["price"] == pytest.approx(105.0)


def test_efficiency_ratio_is_high_for_a_straight_line():
    closes = [100 + i for i in range(60)]
    assert indicators.efficiency_ratio(closes, 30) == pytest.approx(1.0)


def test_efficiency_ratio_collapses_for_an_oscillation():
    closes = [100 + (5 if i % 2 else -5) for i in range(60)]
    assert indicators.efficiency_ratio(closes, 30) < 0.05


def test_efficiency_ratio_needs_enough_history():
    assert indicators.efficiency_ratio([1, 2, 3], 30) is None


def test_slope_per_bar_ignores_the_leading_gap():
    values = [None, None, 1.0, 2.0, 3.0, 4.0]
    assert indicators.slope_per_bar(values, 3) == pytest.approx(1.0)
