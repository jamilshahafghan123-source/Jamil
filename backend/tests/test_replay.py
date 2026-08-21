"""Replay and backtest foundation (sections 63, 88)."""

import inspect

from app.services import replay


def test_nothing_here_simulates_a_fill():
    """Section 88 forbids faking a backtest.

    The module must have no fill, slippage or P/L simulation in it — the
    interface exists, the pretence does not.
    """
    source = inspect.getsource(replay).lower()
    for forbidden in ("def simulate", "def fill", "def execute",
                      "def backtest_run", "random"):
        assert forbidden not in source, f"replay module contains {forbidden}"


def test_backtesting_is_reported_as_unavailable_with_its_reasons():
    caps = replay.capabilities()
    assert caps["strategy_backtest"]["status"] == "COMING_SOON"
    assert caps["ai_setup_backtest"]["status"] == "COMING_SOON"
    # The reasons are stated, not hand-waved.
    assert len(caps["strategy_backtest"]["missing"]) >= 4
    assert any("spread" in m for m in caps["strategy_backtest"]["missing"])
    assert any("intrabar" in m for m in caps["strategy_backtest"]["missing"])


def test_what_is_genuinely_available_is_named(): 
    caps = replay.capabilities()
    assert "telemetry" in caps["available_today"].lower()


def test_a_replay_frame_only_reveals_real_bars():
    """Replay reveals recorded history; it never generates a bar."""
    bars = [{"time": f"t{i}", "close": i} for i in range(10)]
    frame = replay.build_frame(bars, 4)
    assert frame.bars == bars[:5]
    assert frame.total == 10
    assert frame.finished is False
    # Nothing beyond the source can appear.
    assert all(b in bars for b in frame.bars)


def test_a_frame_index_is_clamped_to_real_history():
    bars = [{"time": f"t{i}"} for i in range(3)]
    assert replay.build_frame(bars, 99).index == 2
    assert replay.build_frame(bars, 99).finished is True
    assert replay.build_frame(bars, -5).index == 0


def test_an_empty_history_produces_an_empty_frame_not_an_invented_one():
    frame = replay.build_frame([], 5)
    assert frame.bars == []
    assert frame.total == 0
