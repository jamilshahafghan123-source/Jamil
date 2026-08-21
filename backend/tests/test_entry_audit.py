"""BUY/SELL entry audit: the full path, both directions, equally.

    market data -> analysis -> signal -> confidence -> risk engine
    -> opportunity requirements -> execution -> position

The rules under test:

  * below 50% confidence there is no automatic entry, either direction;
  * at 50% and above a signal is ELIGIBLE, and only enters if every other
    gate also passes;
  * BUY and SELL are held to the same standard, and neither can execute
    as the other;
  * entry, stop loss and take profit belong to the same direction.

Every case is written as a matched pair. A rule that holds for BUY and
not for SELL is the failure mode this file exists to catch, and a test
that only ever checks BUY would never see it.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import (
    DemoAccount,
    DemoPosition,
    DemoPositionSide,
    ExecutionVenue,
    OpportunityLog,
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

# One quote, used everywhere, so the two directions differ only by side.
BID, ASK = 3000.00, 3000.20
QUOTE = Quote(bid=BID, ask=ASK)

#: Mirror-image geometry. A BUY risks 10 below the ask to make 40 above
#: it; a SELL risks 10 above the bid to make 40 below it. Both are 4.0 R.
GEOMETRY = {
    "BUY": {"entry": ASK, "stop_loss": ASK - 10, "take_profit": ASK + 40},
    "SELL": {"entry": BID, "stop_loss": BID + 10, "take_profit": BID - 40},
}

#: Barely-positive reward: 10 risked to make 5, which is 0.5 R and below
#: the account's 1.5 minimum in both directions.
THIN_RR = {
    "BUY": {"entry": ASK, "stop_loss": ASK - 10, "take_profit": ASK + 5},
    "SELL": {"entry": BID, "stop_loss": BID + 10, "take_profit": BID - 5},
}

BOTH = ["BUY", "SELL"]


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        user = User(email="audit@example.com", password_hash="x",
                    role=UserRole.CUSTOMER, is_active=True)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add_all([
            RiskSettings(
                user_id=user.id, trading_mode=TradingMode.DEMO,
                bot_enabled=True, emergency_stop=False,
                execution_venue=ExecutionVenue.JGOLD_DEMO,
                # The account under audit: 50% floor, 1.5 R minimum.
                min_confidence=50, min_rr=1.5,
                max_open_positions=2, max_trades_per_day=10,
                max_lot_size=1.0, max_spread_points=100,
                max_risk_per_trade_pct=1.0, max_daily_loss_pct=5.0,
            ),
            DemoAccount(user_id=user.id, starting_balance=100000.0,
                        balance=100000.0),
        ])
        await db.commit()
    yield {"Session": Session, "user_id": user.id}
    await engine.dispose()


async def _attempt(env, direction: str, *, confidence: int = 50,
                   geometry: dict | None = None, **settings_over):
    """Run one signal through risk and execution. Returns the result."""
    geometry = geometry or GEOMETRY[direction]
    async with env["Session"]() as db:
        row = (await db.execute(select(RiskSettings))).scalar_one()
        for key, value in settings_over.items():
            setattr(row, key, value)
        signal = Signal(
            user_id=env["user_id"], symbol="XAUUSD",
            action=SignalAction[direction], confidence=confidence,
            reason="entry audit", **geometry,
            risk_reward=round(
                abs(geometry["take_profit"] - geometry["entry"])
                / abs(geometry["entry"] - geometry["stop_loss"]), 2),
        )
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user_id"], signal=signal,
            settings_row=row, quote=QUOTE,
        )
        await db.commit()
        return result


async def _positions(env) -> list[DemoPosition]:
    async with env["Session"]() as db:
        return list((await db.execute(select(DemoPosition))).scalars().all())


# ------------------------------------------------ 1 & 2: below the floor


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_forty_nine_percent_is_blocked(env, direction):
    result = await _attempt(env, direction, confidence=49)
    assert result.executed is False
    assert any("confidence" in r.lower() for r in result.reasons), result.reasons
    assert await _positions(env) == []


# --------------------------------------------- 3 & 4: fifty percent enters


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_fifty_percent_with_every_gate_passing_executes(env, direction):
    result = await _attempt(env, direction, confidence=50)
    assert result.executed is True, result.reasons
    positions = await _positions(env)
    assert len(positions) == 1
    assert positions[0].side is DemoPositionSide[direction]


# --------------------------------------------------- 5 & 6: risk / reward


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_fifty_percent_with_bad_risk_reward_is_blocked(env, direction):
    """Eligible is not approved: the confidence gate passed, RR did not."""
    result = await _attempt(env, direction, confidence=50,
                            geometry=THIN_RR[direction])
    assert result.executed is False
    joined = " ".join(result.reasons).lower()
    assert "risk/reward" in joined, result.reasons
    assert "confidence" not in joined, result.reasons
    assert await _positions(env) == []


# ------------------------------------------------- 7 & 8: emergency stop


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_emergency_stop_blocks_both_directions(env, direction):
    result = await _attempt(env, direction, confidence=90,
                            emergency_stop=True)
    assert result.executed is False
    assert any("emergency" in r.lower() for r in result.reasons), result.reasons
    assert await _positions(env) == []


# ------------------------------------------------------ 9: position cap


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_the_position_cap_blocks_both_directions(env, direction):
    """Fill the account to its cap, then try each side."""
    assert (await _attempt(env, "BUY", confidence=80)).executed is True
    assert (await _attempt(env, "SELL", confidence=80)).executed is True
    assert len(await _positions(env)) == 2  # max_open_positions

    result = await _attempt(env, direction, confidence=95)
    assert result.executed is False
    assert any("open positions" in r.lower() for r in result.reasons), \
        result.reasons
    assert len(await _positions(env)) == 2


# ------------------------------- 10: the resulting position, both ways


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_the_resulting_position_matches_its_direction(env, direction):
    """Side, entry side of the spread, and stop/target on the right sides."""
    async with env["Session"]() as db:
        log = OpportunityLog(
            user_id=env["user_id"], symbol="XAUUSD", session="LONDON",
            setup_class="STANDARD", grade="GOOD", score=71,
            direction=direction, confidence=72, expected_rr=4.0,
            required_confidence=50, required_rr=1.5, ai_decision=direction,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        opportunity_id = log.id

    geometry = GEOMETRY[direction]
    async with env["Session"]() as db:
        row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = Signal(
            user_id=env["user_id"], symbol="XAUUSD",
            action=SignalAction[direction], confidence=72,
            reason="entry audit", risk_reward=4.0, **geometry,
        )
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user_id"], signal=signal, settings_row=row,
            quote=QUOTE, opportunity_id=opportunity_id,
        )
        await db.commit()
    assert result.executed is True, result.reasons

    position = (await _positions(env))[0]
    assert position.side is DemoPositionSide[direction]
    assert position.source is TradeSource.AI_AUTO

    # A buy fills at the ask, a sell at the bid. Filling either at the
    # wrong side of the spread would hand the customer a free half-spread
    # that does not exist.
    assert position.entry_price == (ASK if direction == "BUY" else BID)

    # Stop and target on the correct sides of the entry.
    if direction == "BUY":
        assert position.stop_loss < position.entry_price < position.take_profit
    else:
        assert position.take_profit < position.entry_price < position.stop_loss

    assert position.opportunity_id == opportunity_id
    async with env["Session"]() as db:
        linked = await db.get(OpportunityLog, position.opportunity_id)
        assert linked.direction == direction, \
            "the position must link to an opportunity for its OWN direction"


# ------------------------------------------- a BUY may never become a SELL


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_the_executed_side_always_matches_the_signal(env, direction):
    await _attempt(env, direction, confidence=80)
    position = (await _positions(env))[0]
    assert position.side.value == direction


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_inverted_geometry_is_refused_rather_than_flipped(env, direction):
    """A BUY carrying SELL geometry is a fault, not an instruction.

    The dangerous failure is silently treating it as the other direction.
    It must be refused with the stop/target ordering named.
    """
    inverted = GEOMETRY["SELL" if direction == "BUY" else "BUY"]
    result = await _attempt(env, direction, confidence=90, geometry=inverted)
    assert result.executed is False
    assert any(direction in r and "requires" in r for r in result.reasons), \
        result.reasons
    assert await _positions(env) == []


# ---------------------------------------------------- opportunity grade


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.parametrize("grade", ["POOR", "ACCEPTABLE"])
@pytest.mark.asyncio
async def test_a_low_grade_setup_is_refused_in_both_directions(
    env, direction, grade
):
    """Grade was scored, recorded, and never enforced.

    A POOR setup with adequate confidence and risk/reward executed. The
    class requirement is GOOD, so both of these must be refused.
    """
    geometry = GEOMETRY[direction]
    async with env["Session"]() as db:
        row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = Signal(
            user_id=env["user_id"], symbol="XAUUSD",
            action=SignalAction[direction], confidence=90,
            reason="entry audit", risk_reward=4.0, **geometry,
        )
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user_id"], signal=signal, settings_row=row,
            quote=QUOTE, opportunity_grade=grade,
        )
        await db.commit()

    assert result.executed is False, result.reasons
    assert any("grade" in r.lower() for r in result.reasons), result.reasons
    assert await _positions(env) == []


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.parametrize("grade", ["GOOD", "EXCELLENT"])
@pytest.mark.asyncio
async def test_an_adequate_grade_still_executes(env, direction, grade):
    """The gate must not close the door on setups that deserve to trade."""
    geometry = GEOMETRY[direction]
    async with env["Session"]() as db:
        row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = Signal(
            user_id=env["user_id"], symbol="XAUUSD",
            action=SignalAction[direction], confidence=50,
            reason="entry audit", risk_reward=4.0, **geometry,
        )
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user_id"], signal=signal, settings_row=row,
            quote=QUOTE, opportunity_grade=grade,
        )
        await db.commit()
    assert result.executed is True, result.reasons


@pytest.mark.asyncio
async def test_an_unrecognised_grade_is_not_a_pass(env):
    """A value nothing recognises must not sail through the gate."""
    async with env["Session"]() as db:
        row = (await db.execute(select(RiskSettings))).scalar_one()
        signal = Signal(
            user_id=env["user_id"], symbol="XAUUSD", action=SignalAction.BUY,
            confidence=90, reason="entry audit", risk_reward=4.0,
            **GEOMETRY["BUY"],
        )
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user_id"], signal=signal, settings_row=row,
            quote=QUOTE, opportunity_grade="SPLENDID",
        )
        await db.commit()
    assert result.executed is False
    assert any("grade" in r.lower() for r in result.reasons), result.reasons


def test_unknown_and_poor_are_different_answers():
    """"Not measured" is not "measured and bad", and vice versa."""
    from app.services.opportunity import Grade, meets_grade

    assert meets_grade(None, Grade.GOOD) is None
    assert meets_grade("POOR", Grade.GOOD) is False
    assert meets_grade("GOOD", Grade.GOOD) is True
    assert meets_grade("EXCELLENT", Grade.GOOD) is True
    assert meets_grade("ACCEPTABLE", Grade.ACCEPTABLE) is True


def test_the_autonomous_path_always_supplies_a_grade():
    """The gate is only a gate if the caller feeds it.

    A grade is optional on the signature, because a hand-placed order has
    no opportunity behind it. The BOT has one every time, so if it ever
    stops passing it the gate silently stops applying.
    """
    import inspect

    from app.services import bot

    source = inspect.getsource(bot._cycle_for_user)
    assert "opportunity_grade=graded" in source

    # And a grading failure must not be swallowed as a telemetry failure,
    # which would leave the grade None and the gate open.
    grading = source.split("graded = opportunity.evaluate")[1].split(
        "telemetry.record_opportunity")[0]
    assert "return" in grading, \
        "a setup whose quality could not be assessed must not be traded"
