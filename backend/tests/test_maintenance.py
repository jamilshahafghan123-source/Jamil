"""Maintenance mode (sections 5, 21).

The two properties that matter: it stops new risk, and it never closes a
position. A maintenance window that liquidated somebody would be a far
worse outcome than the problem it was opened for.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import maintenance


def test_starts_inactive():
    assert maintenance.current().active is False


def test_enter_and_exit():
    state = maintenance.enter("Database restore", detail="backup #3")
    assert state.active is True
    assert state.reason == "Database restore"
    assert state.since is not None
    assert maintenance.current().active is True

    maintenance.exit_(detail="done")
    assert maintenance.current().active is False


def test_blocks_new_risk_but_never_closing():
    """The asymmetry is the whole design."""
    maintenance.enter("Database restore")
    state = maintenance.current()
    assert state.blocks_automated_trading is True
    assert state.blocks_new_broker_execution is True
    # Never trap someone in a trade.
    assert state.blocks_closing_a_position is False


def test_never_blocks_viewing_or_support():
    maintenance.enter("Database restore")
    state = maintenance.current()
    assert state.blocks_account_viewing is False
    assert state.blocks_support is False


def test_does_not_expire_on_its_own():
    """A window ends because somebody ended it, not because time passed."""
    maintenance.enter("Database restore", now=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert maintenance.current().active is True


def test_customer_message_names_no_internals():
    text = maintenance.CUSTOMER_MESSAGE.lower()
    for leak in ("docker", "container", "postgres", "database", "port",
                 "backup", "restore", "bridge"):
        assert leak not in text
    assert "positions" in text


def test_nothing_in_the_module_closes_a_position():
    from pathlib import Path

    source = Path("app/services/maintenance.py").read_text(encoding="utf-8")
    for forbidden in ("close_all", "close_position", "executor"):
        assert forbidden not in source


def test_the_bot_checks_maintenance_before_analysing_or_executing():
    """Source-level, so the wiring cannot be silently removed."""
    from pathlib import Path

    body = Path("app/services/bot.py").read_text(encoding="utf-8").split(
        "async def _cycle_for_user"
    )[1]
    guard = body.index("maintenance.current()")
    assert guard < body.index("await run_analysis(")
    assert guard < body.index("executor.execute_signal(")


def test_the_maintenance_guard_closes_nothing():
    from pathlib import Path

    body = Path("app/services/bot.py").read_text(encoding="utf-8").split(
        "async def _cycle_for_user"
    )[1]
    block = body[body.index("window = maintenance.current()"):]
    block = block[: block.index("# SAFE MODE")]
    for forbidden in ("close_all", "close_position", "_manage_"):
        assert forbidden not in block


def test_trading_execute_is_guarded_but_close_is_not():
    """Opening is blocked; closing stays available by design."""
    from pathlib import Path

    source = Path("app/routers/trading.py").read_text(encoding="utf-8")
    execute = source.split("async def execute_signal")[1].split("@router.post")[0]
    assert "_refuse_if_maintenance()" in execute

    close = source.split("async def close_position")[1].split("@router.post")[0]
    assert "_refuse_if_maintenance()" not in close

    close_all = source.split("async def close_all")[1]
    assert "_refuse_if_maintenance()" not in close_all
