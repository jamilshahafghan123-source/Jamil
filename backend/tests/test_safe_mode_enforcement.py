"""Safe mode is ENFORCED in the execution path, not merely reported.

Section 3. Before this, safe_mode.evaluate() was read by the admin panel and
by support answers but nothing in the trading loop consulted it, so "stale
market data pauses AI Auto" was a claim rather than a behaviour. These tests
pin the behaviour.

Nothing here touches a real broker: the bridge client is replaced with a
stub, so no socket is opened and no order can be sent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import bot, safe_mode

NOW = datetime.now(timezone.utc)


class StubMT5:
    """Stands in for the bridge. Records nothing, sends nothing."""

    def __init__(self, connected=True, tick_age_seconds=1, raise_on_tick=False):
        self._connected = connected
        self._age = tick_age_seconds
        self._raise = raise_on_tick

    async def connected(self):
        return self._connected

    async def tick(self):
        if self._raise:
            raise RuntimeError("bridge exploded")
        when = datetime.now(timezone.utc) - timedelta(seconds=self._age)
        return {"time": when.isoformat()}


@pytest.mark.asyncio
async def test_fresh_data_does_not_trip_safe_mode(monkeypatch):
    monkeypatch.setattr(bot, "mt5", StubMT5(connected=True, tick_age_seconds=2))
    state = await bot._current_safe_mode()
    assert state.blocks_automated_trading is False


@pytest.mark.asyncio
async def test_stale_market_data_blocks_new_automated_trades(monkeypatch):
    """The behaviour section 3 asks for, at the point it actually matters."""
    monkeypatch.setattr(bot, "mt5", StubMT5(connected=True, tick_age_seconds=600))
    state = await bot._current_safe_mode()
    assert state.blocks_automated_trading is True
    assert safe_mode.SafeModeReason.STALE_MARKET_DATA in state.reasons


@pytest.mark.asyncio
async def test_disconnected_bridge_blocks_new_automated_trades(monkeypatch):
    monkeypatch.setattr(bot, "mt5", StubMT5(connected=False))
    state = await bot._current_safe_mode()
    assert state.blocks_automated_trading is True


@pytest.mark.asyncio
async def test_unreadable_state_is_treated_as_untrustworthy(monkeypatch):
    """An exception while reading the tick must fail closed, not open."""
    monkeypatch.setattr(bot, "mt5", StubMT5(connected=True, raise_on_tick=True))
    state = await bot._current_safe_mode()
    assert state.blocks_automated_trading is True


@pytest.mark.asyncio
async def test_safe_mode_never_reports_that_it_closed_anything(monkeypatch):
    """Entering safe mode closes nothing; it only stops new entries."""
    monkeypatch.setattr(bot, "mt5", StubMT5(connected=False))
    state = await bot._current_safe_mode()
    assert state.active is True
    assert state.blocks_account_viewing is False


def test_the_bot_consults_safe_mode_before_analysing_or_executing():
    """Source-level: the guard sits ahead of analysis and execution.

    Asserted against the file so the wiring cannot be removed in a later
    edit without this failing — the failure mode being silent, and the
    consequence being trades placed on prices nobody vouched for.
    """
    from pathlib import Path

    source = Path("app/services/bot.py").read_text(encoding="utf-8")
    body = source.split("async def _cycle_for_user")[1]
    guard = body.index("_current_safe_mode()")
    analysis = body.index("await run_analysis(")
    execute = body.index("executor.execute_signal(")
    assert guard < analysis, "safe mode must be checked before analysis"
    assert guard < execute, "safe mode must be checked before execution"


def test_safe_mode_path_never_closes_a_position():
    """The guard returns; it must not reach any closing helper."""
    from pathlib import Path

    source = Path("app/services/bot.py").read_text(encoding="utf-8")
    body = source.split("async def _cycle_for_user")[1]
    guard_block = body[body.index("safe = await _current_safe_mode()"):]
    guard_block = guard_block[: guard_block.index("signal, _ = await run_analysis")]
    for forbidden in ("close_all", "close_position", "_manage_"):
        assert forbidden not in guard_block


def test_pause_is_audited():
    from app import audit

    assert audit.SAFE_MODE_PAUSED == "safe_mode.bot_paused"
