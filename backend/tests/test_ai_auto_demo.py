"""AI Auto against the internal demo account (sections 13, 19, 41).

The claim under test: an approved AI Auto demo signal opens a *virtual*
position and cannot, by any path, reach MT5 — while still having passed
every risk check a broker trade passes.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import (
    DemoAccount,
    DemoPosition,
    DemoTrade,
    ExecutionVenue,
    RiskSettings,
    Signal,
    SignalAction,
    TradeSource,
    TradingMode,
    User,
    UserRole,
)
from app.services import bot, demo_execution, profit_guard
from app.services.demo_engine import Quote


def _referenced(path: str) -> set[str]:
    """Identifiers a module references, ignoring prose in docstrings."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.update((node.module or "").split("."))
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.update(a.name.split("."))
    return names


# ------------------------------------------------------------ isolation


def test_demo_execution_cannot_reach_a_broker():
    """The load-bearing test. AI Auto demo must never touch MT5."""
    referenced = _referenced("app/services/demo_execution.py")
    for forbidden in ("mt5", "mt5_client", "executor", "bridge", "order_send",
                      "BrokerAdapter", "subprocess", "close_all"):
        assert forbidden not in referenced, (
            f"demo execution references {forbidden!r}"
        )


def test_demo_execution_does_share_the_risk_manager():
    """Separation of adapters, not of safety: the risk engine IS shared."""
    referenced = _referenced("app/services/demo_execution.py")
    assert "risk_engine" in referenced
    assert "evaluate" in referenced


def test_demo_execution_can_never_arm_real_trading():
    source = Path("app/services/demo_execution.py").read_text(encoding="utf-8")
    assert "server_allows_real=False" in source
    assert "server_allows_real=True" not in source


def test_the_bot_routes_by_venue_and_returns_before_the_broker_path():
    """A JGOLD_DEMO account must never fall through to executor."""
    source = Path("app/services/bot.py").read_text(encoding="utf-8")
    body = source.split("async def _cycle_for_user")[1]
    branch = body.index("ExecutionVenue.JGOLD_DEMO")
    broker = body.index("executor.execute_signal(")
    assert branch < broker, "venue routing must precede the broker call"
    demo_block = body[branch:broker]
    assert "return" in demo_block, "the demo branch must not fall through"
    assert "executor." not in demo_block


def test_the_default_venue_is_the_broker_bridge():
    """Existing accounts keep behaving exactly as before this column."""
    row = RiskSettings(user_id=1)
    assert RiskSettings.__table__.c.execution_venue.default.arg is (
        ExecutionVenue.MT5_BRIDGE
    )
    assert row.execution_venue in (None, ExecutionVenue.MT5_BRIDGE)


# --------------------------------------------------------------- behaviour


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        user = User(email="auto@example.com", password_hash="x",
                    role=UserRole.CUSTOMER, is_active=True)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        settings_row = RiskSettings(
            user_id=user.id, trading_mode=TradingMode.DEMO, bot_enabled=True,
            execution_venue=ExecutionVenue.JGOLD_DEMO,
            min_confidence=60, min_rr=1.5, max_open_positions=2,
            max_trades_per_day=10, max_lot_size=1.0, max_spread_points=100,
            max_risk_per_trade_pct=1.0,
        )
        db.add(settings_row)
        db.add(DemoAccount(user_id=user.id, starting_balance=100000.0,
                           balance=100000.0))
        await db.commit()
        await db.refresh(settings_row)
    yield {"Session": Session, "user": user, "settings": settings_row}
    await engine.dispose()


def _signal(user_id: int, **over) -> Signal:
    base = dict(
        user_id=user_id, symbol="XAUUSD", action=SignalAction.BUY,
        entry=3000.0, stop_loss=2990.0, take_profit=3030.0,
        risk_reward=3.0, confidence=85, reason="test",
        created_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return Signal(**base)


@pytest.mark.asyncio
async def test_an_approved_signal_opens_a_virtual_position(env):
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id)
        db.add(signal)
        await db.flush()

        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()

    assert result.executed is True
    async with env["Session"]() as db:
        positions = (await db.execute(select(DemoPosition))).scalars().all()
    assert len(positions) == 1
    # Recorded as AI_AUTO so history can tell it from a manual trade.
    assert positions[0].source is TradeSource.AI_AUTO
    assert positions[0].signal_confidence == 85


@pytest.mark.asyncio
async def test_confidence_below_the_minimum_opens_nothing(env):
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, confidence=10)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()
    assert result.executed is False
    assert any("confidence" in r.lower() for r in result.reasons)
    async with env["Session"]() as db:
        assert (await db.execute(select(DemoPosition))).scalars().all() == []


@pytest.mark.asyncio
async def test_emergency_stop_opens_nothing(env):
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.emergency_stop = True
        signal = _signal(env["user"].id)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
    assert result.executed is False


@pytest.mark.asyncio
async def test_a_daily_halt_opens_nothing(env):
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.halted_until_date = date.today()
        signal = _signal(env["user"].id)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
    assert result.executed is False


@pytest.mark.asyncio
async def test_a_no_trade_signal_opens_nothing(env):
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, action=SignalAction.NO_TRADE)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
    assert result.executed is False


@pytest.mark.asyncio
async def test_the_position_cap_is_enforced(env):
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.max_open_positions = 1
        account = (await db.execute(select(DemoAccount))).scalar_one()
        db.add(DemoPosition(
            account_id=account.id, symbol="XAUUSD",
            side=demo_execution.DemoPositionSide.BUY, volume=0.1,
            entry_price=2990.0, source=TradeSource.MANUAL,
            opened_at=datetime.now(timezone.utc),
        ))
        await db.commit()

        signal = _signal(env["user"].id)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
    assert result.executed is False
    assert any("position" in r.lower() for r in result.reasons)


@pytest.mark.asyncio
async def test_a_rejection_is_recorded_on_the_signal(env):
    """The reason survives on the row, so history can explain the refusal."""
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, confidence=5)
        db.add(signal)
        await db.flush()
        await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()
    async with env["Session"]() as db:
        stored = (await db.execute(select(Signal))).scalar_one()
    assert stored.risk_approved is False
    assert stored.risk_reasons


@pytest.mark.asyncio
async def test_a_paused_bot_opens_nothing(env):
    """A pause holds at the execution gate, not only in the bot's loop.

    The loop is one caller. Checking here means a future automated caller
    inherits the hold instead of having to remember it.
    """
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.bot_paused = True
        signal = _signal(env["user"].id)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()
    assert result.executed is False
    assert any("paused" in r.lower() for r in result.reasons)
    async with env["Session"]() as db:
        assert (await db.execute(select(DemoPosition))).scalars().all() == []


@pytest.mark.asyncio
async def test_resuming_lets_the_same_signal_through(env):
    """A pause holds; it does not disarm. The same signal executes after."""
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.bot_paused = False
        signal = _signal(env["user"].id)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()
    assert result.executed is True


def test_the_bot_loop_pauses_opening_without_pausing_management():
    """The pause gate must sit on the OPENING path only.

    A pause that also stopped managing open positions would leave live
    trades unattended, which is worse than either running or stopping.
    """
    source = inspect.getsource(bot._cycle_for_user)
    body = source.split("may_open = ")[1]
    # Reversal handling and profit-taking still run under `autonomous`.
    assert "_manage_strong_reversal" in body
    assert "_manage_profitable_positions" in body
    reversal = body.split("_manage_strong_reversal")[0]
    assert "if not may_open" not in reversal


# ------------------------------------------- the 50% confidence policy


@pytest.mark.asyncio
async def test_a_fifty_percent_signal_reaches_a_demo_position(env):
    """The stated policy, proved end to end.

    At or above 50% a setup is ELIGIBLE — not forced. This asserts the
    whole path: risk engine, sizing, execution, and a real DemoPosition
    row with the money moved on the demo account.
    """
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.min_confidence = 50
        settings_row.min_rr = 1.5
        signal = _signal(env["user"].id, confidence=50)
        db.add(signal)
        await db.flush()

        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()

    assert result.executed is True, result.reasons
    async with env["Session"]() as db:
        positions = (await db.execute(select(DemoPosition))).scalars().all()
    assert len(positions) == 1
    assert positions[0].signal_confidence == 50
    assert positions[0].source is TradeSource.AI_AUTO


@pytest.mark.asyncio
async def test_forty_nine_percent_is_refused(env):
    """Below 50 there is no automatic entry, however it is configured."""
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.min_confidence = 50
        signal = _signal(env["user"].id, confidence=49)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()
    assert result.executed is False
    assert any("confidence" in r.lower() for r in result.reasons)
    async with env["Session"]() as db:
        assert (await db.execute(select(DemoPosition))).scalars().all() == []


@pytest.mark.asyncio
async def test_an_account_asking_for_below_fifty_still_gets_fifty(env):
    """The floor is the platform's, not the account's, to lower."""
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.min_confidence = 10
        signal = _signal(env["user"].id, confidence=30)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()
    assert result.executed is False
    assert any("50" in r for r in result.reasons), result.reasons


@pytest.mark.asyncio
async def test_fifty_percent_does_not_mean_force_a_trade(env):
    """Eligible is not approved. Every other gate still rules.

    Same 50% signal, but the risk/reward is too thin — it must still be
    refused, and for the RR reason rather than the confidence one.
    """
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.min_confidence = 50
        settings_row.min_rr = 1.5
        # Reward barely above risk: 3000 -> 3005 against a 2990 stop.
        signal = _signal(env["user"].id, confidence=50, take_profit=3005.0)
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row, quote=Quote(bid=3000.0, ask=3000.2),
        )
        await db.commit()
    assert result.executed is False
    joined = " ".join(result.reasons).lower()
    assert "risk/reward" in joined or "rr" in joined, result.reasons
    assert "confidence" not in joined, result.reasons


# ------------------------------------------- profit protection (§44)


class _StubTick:
    """One price, no socket. The bot's only market call on this path."""

    def __init__(self, bid: float, ask: float) -> None:
        self._quote = {"bid": bid, "ask": ask}

    async def tick(self, *_a, **_k):
        return self._quote


async def _open_demo_position(env, side: str, entry_bid: float,
                              entry_ask: float) -> int:
    """Open one AI_AUTO position through the real execution path."""
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.min_confidence = 50
        signal = _signal(
            env["user"].id,
            action=SignalAction.BUY if side == "BUY" else SignalAction.SELL,
            entry=entry_ask,
            stop_loss=entry_ask - 10 if side == "BUY" else entry_ask + 10,
            take_profit=entry_ask + 30 if side == "BUY" else entry_ask - 30,
        )
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user"].id, signal=signal,
            settings_row=settings_row,
            quote=Quote(bid=entry_bid, ask=entry_ask),
        )
        await db.commit()
    assert result.executed is True, result.reasons
    async with env["Session"]() as db:
        return (await db.execute(select(DemoPosition))).scalar_one().id


def _analysis(momentum: str, trend: str) -> dict:
    return {"market": {"momentum": momentum},
            "timeframes": [{"timeframe": "M15", "role": "SETUP",
                            "trend": trend}]}


@pytest.mark.asyncio
async def test_the_bot_manages_its_own_demo_positions(env, monkeypatch):
    """The defect: demo positions were opened and then never managed.

    Both managers read mt5.positions(), so an account on the internal
    demo venue had the bot open trades it could not see afterwards.
    """
    position_id = await _open_demo_position(env, "BUY", 3000.0, 3000.2)
    monkeypatch.setattr(bot, "mt5", _StubTick(3020.0, 3020.2))
    bot._profit_state.streaks.clear()

    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, action=SignalAction.SELL,
                         confidence=95)
        signal.analysis = _analysis("FALLING", "DOWN")

        # Cycle one: weakening, but nothing closes on a single reading.
        closed = await bot._manage_profitable_positions(
            db, env["user"], signal, settings_row)
        assert closed is False

    async with env["Session"]() as db:
        assert (await db.execute(select(DemoPosition))).scalars().all() != [], \
            "one weak cycle must not close a profitable position"

    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, action=SignalAction.SELL,
                         confidence=95)
        signal.analysis = _analysis("FALLING", "DOWN")

        # Cycle two: confirmed, so the profit is protected.
        closed = await bot._manage_profitable_positions(
            db, env["user"], signal, settings_row)
        assert closed is True

    async with env["Session"]() as db:
        assert (await db.execute(select(DemoPosition))).scalars().all() == []
        trade = (await db.execute(select(DemoTrade))).scalar_one()
        assert trade.realized_pnl > 0, "it protected a PROFIT"
        assert trade.close_reason == "PROFIT_EXIT_CONFIRMED_REVERSAL"
    assert position_id  # the position that was managed


@pytest.mark.asyncio
async def test_a_supported_demo_position_is_left_alone(env, monkeypatch):
    """Still-supported profit is held, however many cycles run."""
    await _open_demo_position(env, "BUY", 3000.0, 3000.2)
    monkeypatch.setattr(bot, "mt5", _StubTick(3020.0, 3020.2))
    bot._profit_state.streaks.clear()

    for _ in range(5):
        async with env["Session"]() as db:
            settings_row = (await db.execute(select(RiskSettings))).scalar_one()
            signal = _signal(env["user"].id, action=SignalAction.BUY,
                             confidence=88)
            signal.analysis = _analysis("RISING", "UP")
            assert await bot._manage_profitable_positions(
                db, env["user"], signal, settings_row) is False

    async with env["Session"]() as db:
        assert len((await db.execute(select(DemoPosition))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_a_losing_demo_position_is_never_closed_by_this_path(
    env, monkeypatch
):
    """The stop loss owns losing trades. This path must not touch them."""
    await _open_demo_position(env, "BUY", 3000.0, 3000.2)
    # Price well below the entry: the position is losing.
    monkeypatch.setattr(bot, "mt5", _StubTick(2995.0, 2995.2))
    bot._profit_state.streaks.clear()

    for _ in range(4):
        async with env["Session"]() as db:
            settings_row = (await db.execute(select(RiskSettings))).scalar_one()
            signal = _signal(env["user"].id, action=SignalAction.SELL,
                             confidence=99)
            signal.analysis = _analysis("FALLING", "DOWN")
            assert await bot._manage_profitable_positions(
                db, env["user"], signal, settings_row) is False

    async with env["Session"]() as db:
        assert len((await db.execute(select(DemoPosition))).scalars().all()) == 1


# ------------------------------ reversal manager: venue, bar, precedence


@pytest.mark.asyncio
async def test_the_reversal_manager_sees_demo_positions(env, monkeypatch):
    """It read mt5.positions() unconditionally, like the profit manager did.

    On the internal demo venue that is a broker holding none of the bot's
    trades, so a strong opposite signal closed nothing.
    """
    await _open_demo_position(env, "BUY", 3000.0, 3000.2)
    # Below the entry: losing, so the reversal manager owns it.
    monkeypatch.setattr(bot, "mt5", _StubTick(2990.0, 2990.2))

    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, action=SignalAction.SELL,
                         confidence=90)
        closed = await bot._manage_strong_reversal(
            db, env["user"], signal, settings_row)
        assert closed is True

    async with env["Session"]() as db:
        assert (await db.execute(select(DemoPosition))).scalars().all() == []
        trade = (await db.execute(select(DemoTrade))).scalar_one()
        assert trade.close_reason == "STRONG_REVERSAL"


@pytest.mark.asyncio
async def test_a_profitable_position_is_left_to_the_profit_guard(
    env, monkeypatch
):
    """The precedence bug: this runs FIRST in the cycle.

    Without the exclusion, one strong opposite reading closed a
    profitable trade here and the guard's two-cycle confirmation never
    got to apply — exactly the behaviour the guard exists to prevent.
    """
    await _open_demo_position(env, "BUY", 3000.0, 3000.2)
    # Above the entry: in profit.
    monkeypatch.setattr(bot, "mt5", _StubTick(3020.0, 3020.2))

    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, action=SignalAction.SELL,
                         confidence=99)
        closed = await bot._manage_strong_reversal(
            db, env["user"], signal, settings_row)
        assert closed is False

    async with env["Session"]() as db:
        assert len((await db.execute(select(DemoPosition))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_the_reversal_bar_is_not_the_entry_floor(env, monkeypatch):
    """Lowering the entry floor to 50 must not halve reversal protection.

    These were the same number, so item 2 silently weakened this path.
    """
    await _open_demo_position(env, "BUY", 3000.0, 3000.2)
    monkeypatch.setattr(bot, "mt5", _StubTick(2990.0, 2990.2))

    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        settings_row.min_confidence = 50
        # Comfortably over the entry floor, under the reversal bar.
        signal = _signal(env["user"].id, action=SignalAction.SELL,
                         confidence=profit_guard.REVERSAL_CONFIDENCE - 1)
        assert await bot._manage_strong_reversal(
            db, env["user"], signal, settings_row) is False

    async with env["Session"]() as db:
        assert len((await db.execute(select(DemoPosition))).scalars().all()) == 1

    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, action=SignalAction.SELL,
                         confidence=profit_guard.REVERSAL_CONFIDENCE)
        assert await bot._manage_strong_reversal(
            db, env["user"], signal, settings_row) is True


@pytest.mark.asyncio
async def test_a_same_side_signal_reverses_nothing(env, monkeypatch):
    await _open_demo_position(env, "BUY", 3000.0, 3000.2)
    monkeypatch.setattr(bot, "mt5", _StubTick(2990.0, 2990.2))
    async with env["Session"]() as db:
        settings_row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = _signal(env["user"].id, action=SignalAction.BUY,
                         confidence=99)
        assert await bot._manage_strong_reversal(
            db, env["user"], signal, settings_row) is False
    async with env["Session"]() as db:
        assert len((await db.execute(select(DemoPosition))).scalars().all()) == 1
