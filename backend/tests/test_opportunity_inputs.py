"""Turning an analysis into opportunity factors (sections 40, 49).

The load-bearing property here is that an unmeasured factor is ABSENT
rather than guessed. `score_opportunity` charges an absent factor its
full weight and records it as "not measured"; supplying a middling value
instead would make the total look measured when it was not.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services import opportunity, opportunity_inputs as oi


def _analysis(**over) -> dict:
    body = {
        "market": {"price": 3000.0, "spread_points": 10, "volatility": 6.0},
        "timeframes": [
            {"timeframe": "H4", "role": "MAJOR", "trend": "UP"},
            {"timeframe": "H1", "role": "INTERMEDIATE", "trend": "UP"},
            {"timeframe": "M15", "role": "SETUP", "trend": "UP", "atr14": 6.0,
             # What the analyst actually emits, and what the entry
             # trigger is now read from.
             "pullback": "SHALLOW", "breakout": "NONE",
             "breakout_confirmed": False, "bos": True},
        ],
        "setup": {
            "confidence_components": {
                "structure": 20, "trend_alignment": 25, "momentum": 15,
                "levels": 10, "liquidity": 5,
            },
            "trigger_text": "break of the M15 high",
            "trigger": 3000.0,
            "stop_loss": 2994.0,
        },
        "zones": {"fvg": [{"side": "bullish"}], "order_blocks": []},
    }
    body.update(over)
    return body


NOON_LONDON_NY = datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc)
TOKYO_ONLY = datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc)
NOTHING_OPEN = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)  # Saturday


# ------------------------------------------------------------- sessions


def test_the_overlap_scores_best_and_a_dead_market_worst():
    assert oi.session_quality(NOON_LONDON_NY) == 1.0
    assert oi.session_quality(TOKYO_ONLY) < oi.session_quality(NOON_LONDON_NY)
    assert oi.session_quality(NOTHING_OPEN) == 0.0


def test_the_session_label_names_the_overlap_rather_than_one_side():
    assert oi.session_label(NOON_LONDON_NY) == "LONDON_NEW_YORK"
    assert oi.session_label(TOKYO_ONLY) == "TOKYO"
    assert oi.session_label(NOTHING_OPEN) == "OFF_SESSION"


# ---------------------------------------------------------- measurement


def test_a_missing_measurement_is_left_out_not_guessed():
    """The whole point: absent, so the score records it as unmeasured."""
    bare = _analysis(setup={}, market={}, timeframes=[], zones={})
    factors = oi.factors_from_analysis(
        bare, direction="BUY", moment=NOON_LONDON_NY
    )
    assert "structure" not in factors
    assert "volatility" not in factors
    assert "spread" not in factors
    # And the engine charges for it rather than renormalising.
    score = opportunity.score_opportunity(factors)
    assert any("structure: not measured" == n for n in score.notes)
    assert score.factors["structure"] == 0.0


def test_candle_confirmation_is_never_supplied():
    """Nothing measures it, so nothing may claim it."""
    factors = oi.factors_from_analysis(
        _analysis(), direction="BUY", moment=NOON_LONDON_NY
    )
    assert "candle_confirmation" not in factors
    notes = opportunity.score_opportunity(factors).notes
    assert "candle_confirmation: not measured" in notes


def test_the_engines_own_derived_factors_are_not_computed_twice():
    """entry_location and higher_timeframe belong to the opportunity engine."""
    factors = oi.factors_from_analysis(
        _analysis(), direction="BUY", moment=NOON_LONDON_NY
    )
    assert "entry_location" not in factors
    assert "higher_timeframe" not in factors


def test_components_are_rescaled_onto_the_engines_own_range():
    """The analyst's points become 0.0-1.0 strengths, not raw scores."""
    factors = oi.factors_from_analysis(
        _analysis(), direction="BUY", moment=NOON_LONDON_NY
    )
    # Full marks on the analyst's scale is full strength on this one.
    assert factors["structure"] == 1.0
    assert factors["trend_alignment"] == 1.0
    half = _analysis()
    half["setup"]["confidence_components"]["structure"] = 10
    assert oi.factors_from_analysis(
        half, direction="BUY", moment=NOON_LONDON_NY
    )["structure"] == 0.5


def test_a_component_above_its_own_maximum_cannot_exceed_full_strength():
    odd = _analysis()
    odd["setup"]["confidence_components"]["structure"] = 999
    factors = oi.factors_from_analysis(
        odd, direction="BUY", moment=NOON_LONDON_NY
    )
    assert factors["structure"] == 1.0


# --------------------------------------------------------- volatility


def test_both_volatility_extremes_score_badly():
    dead = oi.volatility_strength(0.1, 3000.0)
    workable = oi.volatility_strength(6.0, 3000.0)
    wild = oi.volatility_strength(60.0, 3000.0)
    assert workable == 1.0
    assert dead < workable
    assert wild < workable


def test_volatility_without_a_price_is_unmeasured():
    assert oi.volatility_strength(6.0, None) is None
    assert oi.volatility_strength(None, 3000.0) is None
    assert oi.volatility_strength(0.0, 3000.0) is None


# ------------------------------------------------------------- spread


def test_spread_strength_falls_as_the_spread_eats_the_allowance():
    assert oi.spread_strength(0, 50) == 1.0
    assert oi.spread_strength(25, 50) == 0.5
    # At and beyond the limit there is nothing left to earn.
    assert oi.spread_strength(50, 50) == 0.0
    assert oi.spread_strength(500, 50) == 0.0


def test_spread_without_a_limit_is_unmeasured():
    assert oi.spread_strength(10, None) is None
    assert oi.spread_strength(None, 50) is None


# -------------------------------------------------------------- zones


def test_a_zone_against_the_trade_does_not_support_it():
    against = _analysis(zones={"fvg": [{"side": "bearish"}], "order_blocks": []})
    factors = oi.factors_from_analysis(
        against, direction="BUY", moment=NOON_LONDON_NY
    )
    assert factors["fvg"] == 0.0
    assert factors["supply_demand"] == 0.0


# -------------------------------------------------------------- entry


def test_the_entry_trigger_is_named_in_the_engines_own_taxonomy():
    """Prose matched nothing, so entry quality scored 0 on every setup.

    `trigger_text` is a sentence for a human. ENTRY_TRIGGERS is keyed by
    constants. Passing the sentence in meant "no recognised entry
    trigger" every single time and fourteen points that were never
    available to anything.
    """
    trigger, distance = oi.entry_inputs(_analysis())
    assert trigger == "PULLBACK_TO_STRUCTURE"
    assert trigger in opportunity.ENTRY_TRIGGERS
    # 6.0 of price over an ATR of 6.0.
    assert distance == 1.0


def test_each_trigger_traces_to_a_field_the_analyst_measures():
    """Ranked best-first, and UNKNOWN rather than guessed."""
    def tf(**over):
        body = {"timeframe": "M15", "role": "SETUP", "trend": "UP",
                "atr14": 6.0, "pullback": "NONE", "breakout": "NONE",
                "breakout_confirmed": False, "bos": False}
        body.update(over)
        return _analysis(timeframes=[body])

    assert oi.entry_trigger(tf(pullback="DEEP")) == "PULLBACK_TO_STRUCTURE"
    assert oi.entry_trigger(tf(breakout_confirmed=True)) == "RETEST_AFTER_BREAK"
    assert oi.entry_trigger(tf(bos=True)) == "MOMENTUM_RESUMPTION"
    assert oi.entry_trigger(tf(breakout="UP")) == "BREAKOUT_CHASE"
    # Nothing measured: unknown, not invented.
    assert oi.entry_trigger(tf()) is None

    # A confirmed retest outranks a bare break of structure.
    assert oi.entry_trigger(
        tf(breakout_confirmed=True, bos=True)) == "RETEST_AFTER_BREAK"


def test_entry_distance_is_none_without_an_atr():
    no_atr = _analysis(
        timeframes=[{"timeframe": "M15", "role": "SETUP", "trend": "UP"}],
        market={"price": 3000.0},
    )
    _, distance = oi.entry_inputs(no_atr)
    assert distance is None


# ------------------------------------------------- end to end sanity


def test_a_strong_setup_in_the_overlap_grades_well():
    analysis = _analysis()
    trigger, distance = oi.entry_inputs(analysis)
    graded = opportunity.evaluate(
        direction="BUY", confidence=82, expected_rr=2.4,
        factors=oi.factors_from_analysis(
            analysis, direction="BUY", moment=NOON_LONDON_NY,
            spread_points=10, max_spread_points=50,
        ),
        timeframe_biases=oi.timeframe_biases(analysis),
        entry_trigger=trigger, distance_to_invalidation_atr=distance,
    )
    assert graded["score"]["total"] >= 65
    assert graded["qualified"] is True
    # candle_confirmation is measured nowhere in the analyst and costs its
    # full three points, which is the honest outcome and is stated in the
    # breakdown. entry_location is derived by the engine from the trigger
    # this adapter names, so it is never supplied here.
    unmeasured = [n for n in graded["score"]["notes"] if "not measured" in n]
    assert "candle_confirmation: not measured" in unmeasured
    assert not any("structure" in n or "trend_alignment" in n
                   for n in unmeasured), unmeasured


def test_the_same_setup_out_of_hours_scores_lower():
    """Session quality is a real factor, not decoration."""
    analysis = _analysis()
    def total(moment):
        return opportunity.score_opportunity(
            oi.factors_from_analysis(
                analysis, direction="BUY", moment=moment,
                spread_points=10, max_spread_points=50,
            )
        ).total
    assert total(NOTHING_OPEN) < total(NOON_LONDON_NY)
