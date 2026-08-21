"""Protecting an open profit (section 44).

The load-bearing property: ONE cycle can never close a trade. The old
behaviour closed a profitable position the moment a single analysis
stopped supporting it, which is closing on one candle.
"""

from __future__ import annotations

from app.services import profit_guard as g
from app.services.profit_guard import ProfitAction


def analysis(momentum: str = "RISING", trend: str = "UP") -> dict:
    return {
        "market": {"momentum": momentum},
        "timeframes": [
            {"timeframe": "H1", "role": "INTERMEDIATE", "trend": trend},
            {"timeframe": "M15", "role": "SETUP", "trend": trend},
        ],
    }


def assess(**over):
    body = dict(side="BUY", profit=120.0, ai_action="BUY", ai_confidence=80,
                analysis=analysis(), weakening_cycles=0)
    body.update(over)
    return g.assess(**body)


# ------------------------------------------------------------- holding


def test_a_supported_position_is_held():
    d = assess()
    assert d.action is ProfitAction.HOLD
    assert d.should_close is False


def test_a_losing_position_is_not_this_paths_business():
    """The stop loss owns losing trades, and always has."""
    d = assess(profit=-50.0, ai_action="SELL", ai_confidence=99)
    assert d.action is ProfitAction.HOLD
    assert d.should_close is False


# --------------------------------------------------- one cycle is never enough


def test_a_single_weak_cycle_does_not_close_anything():
    """The defect this exists to fix."""
    d = assess(ai_action="NO_TRADE", ai_confidence=0)
    assert d.action is ProfitAction.WEAKENING
    assert d.should_close is False
    assert d.weakening_cycles == 1


def test_a_single_opposing_signal_does_not_close_anything():
    """Even a strong opposite reading has to be seen twice."""
    d = assess(ai_action="SELL", ai_confidence=95,
               analysis=analysis("FALLING", "DOWN"))
    assert d.action is ProfitAction.WEAKENING
    assert d.should_close is False


def test_confidence_one_point_under_the_hold_bar_is_not_a_reversal():
    """64% versus 65% is noise, not a turn."""
    d = assess(ai_confidence=g.HOLD_CONFIDENCE - 1)
    assert d.action is ProfitAction.WEAKENING


# ------------------------------------------------ persistence without evidence


def test_persistent_weakness_alone_still_holds():
    """Drifting support is not a reversal. Something must confirm it."""
    for cycles in (1, 2, 5, 20):
        d = assess(ai_action="NO_TRADE", ai_confidence=0,
                   weakening_cycles=cycles)
        assert d.action is ProfitAction.WEAKENING, cycles
        assert d.should_close is False


def test_momentum_alone_is_not_enough():
    """Momentum flickers between cycles; structure has to agree."""
    d = assess(ai_action="NO_TRADE", ai_confidence=0, weakening_cycles=3,
               analysis=analysis("FALLING", "UP"))
    assert d.action is ProfitAction.WEAKENING


def test_structure_alone_is_not_enough():
    d = assess(ai_action="NO_TRADE", ai_confidence=0, weakening_cycles=3,
               analysis=analysis("RISING", "DOWN"))
    assert d.action is ProfitAction.WEAKENING


# ------------------------------------------------------------ confirmed exits


def test_two_cycles_plus_an_opposing_signal_closes():
    d = assess(ai_action="SELL", ai_confidence=g.REVERSAL_CONFIDENCE,
               weakening_cycles=1)
    assert d.action is ProfitAction.EXIT
    assert d.should_close is True
    assert "opposing SELL" in d.reason
    assert "2 consecutive weakening cycles" in d.reason


def test_two_cycles_plus_momentum_and_structure_closes():
    d = assess(ai_action="NO_TRADE", ai_confidence=0, weakening_cycles=1,
               analysis=analysis("FALLING", "DOWN"))
    assert d.action is ProfitAction.EXIT
    assert "momentum and setup-timeframe trend" in d.reason


def test_a_sell_reverses_on_the_mirror_conditions():
    held = g.assess(side="SELL", profit=90.0, ai_action="SELL",
                    ai_confidence=80, analysis=analysis("FALLING", "DOWN"),
                    weakening_cycles=0)
    assert held.action is ProfitAction.HOLD

    exit_ = g.assess(side="SELL", profit=90.0, ai_action="NO_TRADE",
                     ai_confidence=0, analysis=analysis("RISING", "UP"),
                     weakening_cycles=1)
    assert exit_.action is ProfitAction.EXIT


def test_a_weak_opposing_signal_never_confirms():
    """An opposing reading below the reversal bar is not evidence."""
    d = assess(ai_action="SELL", ai_confidence=g.REVERSAL_CONFIDENCE - 1,
               weakening_cycles=5, analysis=analysis("RISING", "UP"))
    assert d.action is ProfitAction.WEAKENING


# ------------------------------------------------------------ the thresholds


def test_the_reversal_bar_is_not_the_entry_bar():
    """Section: do not lower reversal protection to the 50% entry floor.

    Deciding to keep a profit is a different question from deciding to
    open a trade, and these must be able to move independently.
    """
    assert g.REVERSAL_CONFIDENCE > 50
    assert g.HOLD_CONFIDENCE > 50


def test_the_streak_survives_across_cycles_and_resets_on_support():
    state = g.GuardState()
    assert state.record_weakening("p1") == 1
    assert state.record_weakening("p1") == 2
    assert state.record_weakening("p2") == 1, "positions are counted apart"
    state.clear("p1")
    assert state.record_weakening("p1") == 1, "support resets the streak"
