"""AI Auto against the internal demo account (sections 13, 19, 41).

The claim under test: an approved AI Auto demo signal opens a *virtual*
position and cannot, by any path, reach MT5 — while still having passed
every risk check a broker trade passes.
"""

from __future__ import annotations

import ast
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
    ExecutionVenue,
    RiskSettings,
    Signal,
    SignalAction,
    TradeSource,
    TradingMode,
    User,
    UserRole,
)
from app.services import demo_execution
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
