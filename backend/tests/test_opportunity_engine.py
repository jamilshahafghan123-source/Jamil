"""Opportunity engine (sections 41-49).

The engine exists to find MORE legitimate intraday setups without
lowering the bar for bad ones. Both halves of that sentence are tested
here, and the second half is the one that matters most.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import opportunity as O
from app.services.opportunity import Grade, Regime, SetupClass


def strong_factors() -> dict[str, float]:
    return {
        "structure": 0.9, "trend_alignment": 0.9, "entry_location": 0.9,
        "higher_timeframe": 0.85, "momentum": 0.8, "session_quality": 0.9,
        "liquidity": 0.8, "fvg": 0.7, "support_resistance": 0.8,
        "supply_demand": 0.7, "volatility": 0.7, "candle_confirmation": 0.8,
        "spread": 0.9,
    }


def weak_factors() -> dict[str, float]:
    return {k: 0.2 for k in O.FACTOR_WEIGHTS}


# ---------------------------------------------------- the safety floor

def test_no_class_or_regime_can_drop_below_the_absolute_floor():
    """Section 47: inactivity is never solved by admitting poor signals.

    Every combination of class, regime and account setting is checked,
    so a future regime adjustment cannot quietly open a hole.
    """
    for setup_class in SetupClass:
        for regime in list(Regime) + [None]:
            for confidence, rr in ((None, None), (0, 0.0), (1, 0.01), (-50, -5.0)):
                requirement = O.requirements_for(
                    setup_class, regime, confidence, rr
                )
                assert requirement.min_confidence >= O.ABSOLUTE_FLOOR.min_confidence
                assert requirement.min_rr >= O.ABSOLUTE_FLOOR.min_rr
                assert requirement.max_spread_points <= O.ABSOLUTE_FLOOR.max_spread_points


def test_the_account_owns_the_confidence_dimension():
    """The number on the settings screen is the number that applies.

    Confidence used to be a tightening only, so an account asking for 50
    silently ran at the class requirement of 68 with nothing anywhere
    saying so. A threshold the customer cannot see is not a safety
    feature. It now moves in both directions, bounded below by the
    platform's stated policy floor.
    """
    base = O.requirements_for(SetupClass.STANDARD)
    assert base.min_confidence == 68, "the platform's own opinion, unchanged"

    asked_for_50 = O.requirements_for(
        SetupClass.STANDARD, account_min_confidence=50)
    assert asked_for_50.min_confidence == 50

    strict = O.requirements_for(SetupClass.STANDARD, account_min_confidence=88)
    assert strict.min_confidence == 88


def test_no_account_setting_can_buy_an_entry_below_the_policy_floor():
    """Below 50% there is no automatic entry, whatever is configured."""
    for value in (49, 10, 1, 0, -5):
        for setup_class in SetupClass:
            for regime in list(Regime) + [None]:
                requirement = O.requirements_for(
                    setup_class, regime, account_min_confidence=value)
                assert requirement.min_confidence == 50


def test_risk_reward_spread_and_grade_are_still_a_tightening_only():
    """Relaxing confidence must not carry the other dimensions with it.

    They are not the dimension being delegated to the account, so an
    account may make the platform stricter on them and never looser.
    """
    loose = O.requirements_for(SetupClass.STANDARD, account_min_confidence=50,
                               account_min_rr=0.2)
    base = O.requirements_for(SetupClass.STANDARD)
    assert loose.min_rr == base.min_rr
    assert loose.max_spread_points == base.max_spread_points
    assert loose.min_grade == base.min_grade

    strict = O.requirements_for(SetupClass.STANDARD, account_min_rr=2.75)
    assert strict.min_rr == 2.75


def test_the_garbage_signal_from_the_specification_is_refused():
    """47% confidence and 0.44 RR — named in section 47 as what must NOT pass."""
    result = O.evaluate(
        direction="BUY", confidence=47, expected_rr=0.44,
        factors=weak_factors(),
    )
    assert result["qualified"] is False
    assert result["decision"] == "NO_TRADE"
    assert any("confidence" in r for r in result["reasons"])
    assert any("risk/reward" in r for r in result["reasons"])


def test_a_poor_grade_is_refused_however_confident_the_signal_claims_to_be():
    result = O.evaluate(
        direction="BUY", confidence=99, expected_rr=5.0, factors=weak_factors(),
    )
    assert result["qualified"] is False
    assert result["score"]["grade"] == Grade.POOR.value


# ------------------------------------------- the problem being solved

def test_a_good_scalp_qualifies_where_a_single_global_gate_rejected_it():
    """The exact case section 41 complains about.

    A well-formed scalp at 1.2 RR fails a global 1.5 RR gate, which is a
    swing-trade standard applied to a product that is not a swing trade.
    Under its own class it qualifies — and still has to be confident,
    well-graded and inside a tighter spread limit.
    """
    result = O.evaluate(
        direction="BUY", confidence=71, expected_rr=1.2,
        factors=strong_factors(), hold_minutes=20,
    )
    assert result["setup_class"] == SetupClass.SCALP.value
    assert result["qualified"] is True
    # The same numbers under the old universal swing gate:
    assert 1.2 < 1.5


def test_a_scalp_must_be_more_confident_than_a_standard_setup():
    """A lower RR bar is paid for with a higher confidence bar."""
    scalp = O.requirements_for(SetupClass.SCALP)
    standard = O.requirements_for(SetupClass.STANDARD)
    assert scalp.min_rr < standard.min_rr
    assert scalp.min_confidence > standard.min_confidence
    assert scalp.max_spread_points < standard.max_spread_points


def test_setup_class_follows_the_setup_not_the_convenience_of_a_lower_bar():
    """Nothing may relabel a setup SCALP just to face an easier RR test."""
    score = O.score_opportunity(strong_factors())
    assert O.classify_setup(score, expected_rr=2.4) is SetupClass.A_PLUS
    assert O.classify_setup(score, expected_rr=1.7) is SetupClass.STANDARD
    # A short hold is what makes a scalp, and it is the caller's measurement.
    assert O.classify_setup(score, expected_rr=2.4, hold_minutes=15) is SetupClass.SCALP


# -------------------------------------------- weighted multi-timeframe

def test_m1_disagreement_does_not_veto_a_strong_higher_timeframe_setup():
    """Section 45's worked example.

    D1/H4/H1/M15 bullish with M5 pulling back and M1 turning is a
    textbook continuation entry. A unanimity rule rejects it; weighting
    keeps it, at a small cost.
    """
    biases = {"D1": "BULLISH", "H4": "BULLISH", "H1": "BULLISH",
              "M30": "BULLISH", "M15": "BULLISH", "M5": "BEARISH",
              "M1": "BEARISH"}
    alignment = O.timeframe_alignment(biases, "BUY")
    assert alignment > 0.8
    assert alignment < 1.0


def test_full_agreement_scores_higher_than_partial():
    full = {tf: "BULLISH" for tf in O.TIMEFRAME_WEIGHT}
    partial = dict(full, M1="BEARISH", M5="BEARISH")
    assert O.timeframe_alignment(full, "BUY") == pytest.approx(1.0)
    assert O.timeframe_alignment(partial, "BUY") < 1.0


def test_opposing_higher_timeframes_score_low():
    biases = {"D1": "BEARISH", "H4": "BEARISH", "H1": "BEARISH", "M15": "BULLISH"}
    assert O.timeframe_alignment(biases, "BUY") < 0.25


def test_neutral_counts_as_half_not_as_agreement():
    assert O.timeframe_alignment({"H1": "NEUTRAL"}, "BUY") == pytest.approx(0.5)


def test_unmeasured_timeframes_are_excluded_rather_than_assumed():
    assert O.timeframe_alignment({}, "BUY") == 0.0


# ---------------------------------------------------- entry quality

def test_reacting_to_structure_beats_chasing_a_finished_move():
    """Section 46: entering before the move is over is the whole point."""
    early, _ = O.entry_quality("PULLBACK_TO_STRUCTURE", 0.5)
    late, _ = O.entry_quality("BREAKOUT_CHASE", 0.5)
    assert early > late


def test_distance_from_invalidation_discounts_the_entry():
    near, _ = O.entry_quality("PULLBACK_TO_STRUCTURE", 0.5)
    far, note = O.entry_quality("PULLBACK_TO_STRUCTURE", 2.5)
    assert far < near
    assert "already priced in" in note


def test_an_unrecognised_trigger_scores_nothing():
    quality, note = O.entry_quality("VIBES", 0.5)
    assert quality == 0.0
    assert "No recognised entry trigger" in note


# --------------------------------------------------------- scoring

def test_unmeasured_factors_score_zero_rather_than_being_renormalised():
    """Three known factors must not score like thirteen."""
    partial = O.score_opportunity({"structure": 1.0, "trend_alignment": 1.0})
    full = O.score_opportunity({k: 1.0 for k in O.FACTOR_WEIGHTS})
    assert partial.total < full.total
    assert full.total == 100
    assert any("not measured" in n for n in partial.notes)


def test_factor_strengths_are_clamped():
    inflated = O.score_opportunity({k: 99.0 for k in O.FACTOR_WEIGHTS})
    assert inflated.total == 100
    negative = O.score_opportunity({k: -5.0 for k in O.FACTOR_WEIGHTS})
    assert negative.total == 0


def test_score_breakdown_is_returned_for_every_factor():
    """A number a customer cannot interrogate is not an explanation."""
    result = O.evaluate(direction="BUY", confidence=80, expected_rr=2.0,
                        factors=strong_factors())
    assert set(result["score"]["factors"]) == set(O.FACTOR_WEIGHTS)


# ------------------------------------------------ regime awareness

def test_a_quiet_session_demands_more_than_a_trend():
    quiet = O.requirements_for(SetupClass.STANDARD, Regime.QUIET)
    trend = O.requirements_for(SetupClass.STANDARD, Regime.TREND)
    assert quiet.min_confidence > trend.min_confidence
    assert quiet.min_rr > trend.min_rr


# ---------------------------------------------- duplicates / cooldown

def test_the_same_setup_inside_its_cooldown_is_suppressed():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    fp = O.Fingerprint.build("XAUUSD", "BUY", SetupClass.SCALP, "HH_HL", 3000.0)
    recent = [(fp, now - timedelta(minutes=5))]
    duplicate, reason = O.is_duplicate(fp, recent, SetupClass.SCALP, now)
    assert duplicate is True
    assert "cooldown" in reason


def test_the_same_setup_after_its_cooldown_is_allowed_again():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    fp = O.Fingerprint.build("XAUUSD", "BUY", SetupClass.SCALP, "HH_HL", 3000.0)
    recent = [(fp, now - timedelta(minutes=30))]
    duplicate, _ = O.is_duplicate(fp, recent, SetupClass.SCALP, now)
    assert duplicate is False


def test_a_real_structure_change_is_never_suppressed():
    """Cooldown blocks repetition, not development."""
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    before = O.Fingerprint.build("XAUUSD", "BUY", SetupClass.STANDARD, "HH_HL", 3000.0)
    after = O.Fingerprint.build("XAUUSD", "BUY", SetupClass.STANDARD, "BOS_UP", 3000.0)
    duplicate, _ = O.is_duplicate(after, [(before, now)], SetupClass.STANDARD, now)
    assert duplicate is False


def test_a_rescored_signal_is_still_the_same_signal():
    """Confidence is deliberately not part of the fingerprint."""
    a = O.Fingerprint.build("XAUUSD", "BUY", SetupClass.STANDARD, "HH_HL", 3000.10)
    b = O.Fingerprint.build("XAUUSD", "BUY", SetupClass.STANDARD, "HH_HL", 3000.90)
    assert a == b


def test_the_opposite_direction_is_not_a_duplicate():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    buy = O.Fingerprint.build("XAUUSD", "BUY", SetupClass.SCALP, "HH_HL", 3000.0)
    sell = O.Fingerprint.build("XAUUSD", "SELL", SetupClass.SCALP, "HH_HL", 3000.0)
    duplicate, _ = O.is_duplicate(sell, [(buy, now)], SetupClass.SCALP, now)
    assert duplicate is False


# ------------------------------------------------- no trade quota

def test_the_engine_has_no_notion_of_how_many_trades_have_been_taken():
    """Sections 41 and 105: 4-8 is an expectation, never a target.

    `evaluate` takes no count of trades so far and no time of day left to
    fill, so it structurally cannot loosen to reach a number. This test
    fails the moment such a parameter is introduced.
    """
    import inspect

    parameters = set(inspect.signature(O.evaluate).parameters)
    for forbidden in ("trades_today", "target", "quota", "remaining",
                      "trades_taken", "daily_target"):
        assert forbidden not in parameters


def test_identical_inputs_always_produce_the_identical_verdict():
    """No drift, no time-of-day loosening, no randomness."""
    kwargs = dict(direction="BUY", confidence=64, expected_rr=1.45,
                  factors=strong_factors())
    first = O.evaluate(**kwargs)
    for _ in range(20):
        assert O.evaluate(**kwargs) == first


# ------------------------------------------------------- telemetry

def test_ai_risk_and_execution_outcomes_stay_separate():
    """Section 40: a quiet day must be explainable to its actual cause."""
    record = O.OpportunityRecord(
        detected_at=datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc),
        symbol="XAUUSD", session="LONDON", setup_class=SetupClass.STANDARD,
        grade=Grade.GOOD, score=70, direction="BUY", confidence=72,
        expected_rr=1.8, required_confidence=68, required_rr=1.5,
        ai_decision="BUY", risk_decision="REJECTED",
        risk_reason="daily loss limit reached", execution_result=None,
    )
    payload = record.as_dict()
    assert payload["ai_decision"] == "BUY"
    assert payload["risk_decision"] == "REJECTED"
    assert payload["execution_result"] is None
    assert payload["required_confidence"] == 68


def test_evaluate_reports_the_requirements_that_actually_applied():
    result = O.evaluate(direction="BUY", confidence=60, expected_rr=1.0,
                        factors=strong_factors(), hold_minutes=15)
    assert result["requirements"]["min_confidence"] == 70
    assert result["requirements"]["min_rr"] == 1.1
    assert result["reasons"]
