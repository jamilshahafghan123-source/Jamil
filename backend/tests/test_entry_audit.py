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


async def _graded_attempt(env, direction: str, *, grade: str,
                          confidence: int = 50, geometry: dict | None = None,
                          **settings_over):
    """One signal carrying an opportunity grade, through the real path."""
    geometry = geometry or GEOMETRY[direction]
    async with env["Session"]() as db:
        row = (await db.execute(select(RiskSettings))).scalar_one()
        # Restored below. A helper that leaves a setting changed makes the
        # NEXT case fail for the previous case's reason, which is a very
        # slow way to learn that the tests are not independent.
        previous = {k: getattr(row, k) for k in settings_over}
        for key, value in settings_over.items():
            setattr(row, key, value)
        signal = Signal(
            user_id=env["user_id"], symbol="XAUUSD",
            action=SignalAction[direction], confidence=confidence,
            reason="grade rule", **geometry,
            risk_reward=round(
                abs(geometry["take_profit"] - geometry["entry"])
                / abs(geometry["entry"] - geometry["stop_loss"]), 2),
        )
        db.add(signal)
        await db.flush()
        result = await demo_execution.execute_signal(
            db, user_id=env["user_id"], signal=signal, settings_row=row,
            quote=QUOTE, opportunity_grade=grade,
        )
        for key, value in previous.items():
            setattr(row, key, value)
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
@pytest.mark.parametrize("grade", ["POOR"])
@pytest.mark.asyncio
async def test_a_low_grade_setup_is_refused_in_both_directions(
    env, direction, grade
):
    """Grade was scored, recorded, and never enforced.

    A POOR setup with adequate confidence and risk/reward executed.
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
@pytest.mark.parametrize("grade", ["ACCEPTABLE", "GOOD", "EXCELLENT"])
@pytest.mark.asyncio
async def test_an_adequate_grade_still_executes(env, direction, grade):
    """The gate must not close the door on setups that deserve to trade.

    ACCEPTABLE trades: the gate sits at the platform's declared floor,
    not the class's GOOD, because the score behind the grade cannot be
    calibrated without live data. Refusing everything would be as wrong
    as refusing nothing.
    """
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


# ------------------------------------------------ the account's R:R rule


def test_the_account_rr_applies_unless_the_class_is_stricter():
    """min_rr 1.5 stands, except where the setup class demands more.

    A scalp's own 1.1 must not pull the account's 1.5 down, and A+'s 2.0
    must not be pulled down either. R:R tightens; it never loosens.
    """
    from app.services.opportunity import Regime, SetupClass, requirements_for

    scalp = requirements_for(SetupClass.SCALP, account_min_rr=1.5)
    assert scalp.min_rr == 1.5, "the class's easier 1.1 must not win"

    standard = requirements_for(SetupClass.STANDARD, account_min_rr=1.5)
    assert standard.min_rr == 1.5

    a_plus = requirements_for(SetupClass.A_PLUS, account_min_rr=1.5)
    assert a_plus.min_rr == 2.0, "the class's stricter 2.0 must win"

    # And no regime can drop any of them below the account's number.
    for setup_class in SetupClass:
        for regime in list(Regime) + [None]:
            requirement = requirements_for(
                setup_class, regime, account_min_confidence=50,
                account_min_rr=1.5)
            assert requirement.min_rr >= 1.5, (setup_class, regime)


# --------------------------------- replay and support cannot reach execution


def test_no_support_or_chat_module_can_reach_the_execution_path():
    """Support may read and recommend. It may not trade.

    Checked by imports rather than by intent: a module that cannot reach
    the executor cannot be talked into using it.
    """
    import ast
    import pathlib

    root = pathlib.Path("app/services/support")
    assert root.is_dir()

    banned = {"executor", "demo_execution", "risk_engine", "mt5_client",
              "demo_engine"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = set(node.module.split("."))
                assert not (parts & banned), f"{path.name} imports {node.module}"
                assert not ({a.name for a in node.names} & banned), \
                    f"{path.name} imports from {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not (set(alias.name.split(".")) & banned), \
                        f"{path.name} imports {alias.name}"


def test_the_ask_route_never_calls_an_execution_function():
    """The customer-facing chat route, specifically."""
    import ast
    import inspect

    from app.routers import support as router

    tree = ast.parse(inspect.getsource(router.ask))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("execute_signal", "open_position", "close_position",
                      "close_all", "order_send", "evaluate_and_execute"):
        assert forbidden not in called, forbidden


def test_grade_is_not_a_universal_good():
    """An ordinary setup needs ACCEPTABLE, not GOOD.

    A score of 55 that also clears confidence, risk/reward, spread,
    sizing, exposure and the daily loss limit has nothing honest left
    against it. Refusing it for wanting 62 is a preference, not a risk
    control. POOR is where the platform stops.
    """
    from app.services.opportunity import (
        ABSOLUTE_FLOOR, Grade, Regime, SetupClass, requirements_for,
    )

    assert ABSOLUTE_FLOOR.min_grade is Grade.ACCEPTABLE
    assert requirements_for(SetupClass.STANDARD).min_grade is Grade.ACCEPTABLE
    assert requirements_for(SetupClass.SCALP).min_grade is Grade.ACCEPTABLE

    # A_PLUS keeps the stricter standard. It is only ever assigned to a
    # setup that already scored EXCELLENT, so this records the claim
    # rather than raising the bar for ordinary trades.
    assert requirements_for(SetupClass.A_PLUS).min_grade is Grade.GOOD

    # And no regime or account setting can drop any class below the floor.
    for setup_class in SetupClass:
        for regime in list(Regime) + [None]:
            requirement = requirements_for(
                setup_class, regime, account_min_confidence=50,
                account_min_rr=1.5)
            assert requirement.min_grade in (Grade.ACCEPTABLE, Grade.GOOD)


def test_a_plus_is_only_ever_reached_from_an_excellent_score():
    """So its stricter grade requirement can never block a normal trade."""
    from app.services.opportunity import (
        Grade, OpportunityScore, SetupClass, classify_setup,
    )

    for grade in (Grade.POOR, Grade.ACCEPTABLE, Grade.GOOD):
        assert classify_setup(
            OpportunityScore(total=60, grade=grade), expected_rr=3.0
        ) is not SetupClass.A_PLUS

    assert classify_setup(
        OpportunityScore(total=80, grade=Grade.EXCELLENT), expected_rr=2.0
    ) is SetupClass.A_PLUS


def test_mirrored_bull_and_bear_data_score_identically():
    """BUY and SELL must be scored by the same yardstick.

    An RSI of 0.0 — maximum bearish exhaustion — was read as neutral 50
    because 0.0 is falsy, so a BUY at RSI 100 took the exhaustion penalty
    and the mirrored SELL did not. The two directions differed by five
    confidence points on identical, mirrored input.
    """
    from app.services.setup_engine import _confidence

    def view(trend: str, momentum: str, rsi: float) -> dict:
        return {
            "timeframe": "M15", "role": "SETUP", "trend": trend,
            "momentum": momentum, "rsi14": rsi, "atr14": 6.0,
            "structure_detail": {"pattern": "UNCLEAR"},
            "support_levels": [], "resistance_levels": [], "liquidity": [],
            "volume": {"relative": 1.0},
        }

    bull = {"hierarchy": {"higher_aligned": True},
            "timeframes": [view("UP", "RISING", 100.0)]}
    bear = {"hierarchy": {"higher_aligned": True},
            "timeframes": [view("DOWN", "FALLING", 0.0)]}

    buy_total, buy_comp = _confidence(bull, "BUY", bull["timeframes"][0], 2.0)
    sell_total, sell_comp = _confidence(bear, "SELL", bear["timeframes"][0], 2.0)

    assert buy_comp["momentum"] == sell_comp["momentum"], \
        "exhaustion must cost both directions the same"
    assert buy_total == sell_total


def test_a_missing_rsi_is_still_treated_as_neutral():
    """The fix must not turn "absent" into 0 and penalise every SELL."""
    from app.services.setup_engine import _confidence

    tf = {
        "timeframe": "M15", "role": "SETUP", "trend": "DOWN",
        "momentum": "FALLING", "atr14": 6.0,
        "structure_detail": {"pattern": "UNCLEAR"},
        "support_levels": [], "resistance_levels": [], "liquidity": [],
        "volume": {"relative": 1.0},
    }
    _, comp = _confidence({"timeframes": [tf]}, "SELL", tf, 2.0)
    # No rsi14 key at all: neutral, so no exhaustion penalty.
    assert comp["momentum"] == 15


# ================================================= the grade rule, in full
#
#   POOR        -> blocked
#   ACCEPTABLE  -> eligible when every other gate passes
#   GOOD        -> eligible, and a stronger opportunity
#
# Each case is run for BUY and SELL, because a rule that holds one way
# and not the other is the failure this file exists to catch.


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_case_1_poor_is_blocked(env, direction):
    result = await _graded_attempt(env, direction, grade="POOR")
    assert result.executed is False
    assert any("grade" in r.lower() for r in result.reasons), result.reasons
    assert await _positions(env) == []


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_case_2_acceptable_with_every_other_gate_passing_trades(
    env, direction
):
    """The change you asked for: 55 is not a reason to refuse a good trade."""
    result = await _graded_attempt(env, direction, grade="ACCEPTABLE")
    assert result.executed is True, result.reasons
    positions = await _positions(env)
    assert len(positions) == 1
    assert positions[0].side is DemoPositionSide[direction]


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_case_3_good_trades(env, direction):
    result = await _graded_attempt(env, direction, grade="GOOD")
    assert result.executed is True, result.reasons
    assert len(await _positions(env)) == 1


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.parametrize("grade", ["ACCEPTABLE", "GOOD", "EXCELLENT"])
@pytest.mark.asyncio
async def test_case_4_forty_nine_percent_is_blocked_whatever_the_grade(
    env, direction, grade
):
    """Confidence is its own gate. A good score cannot buy an entry."""
    result = await _graded_attempt(env, direction, grade=grade, confidence=49)
    assert result.executed is False
    assert any("confidence" in r.lower() for r in result.reasons), result.reasons
    assert await _positions(env) == []


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.parametrize("grade", ["ACCEPTABLE", "GOOD", "EXCELLENT"])
@pytest.mark.asyncio
async def test_case_5_bad_risk_reward_is_blocked_whatever_the_grade(
    env, direction, grade
):
    result = await _graded_attempt(env, direction, grade=grade,
                                   geometry=THIN_RR[direction])
    assert result.executed is False
    assert any("risk/reward" in r.lower() for r in result.reasons), result.reasons
    assert await _positions(env) == []


@pytest.mark.asyncio
async def test_case_6_buy_and_sell_behave_identically(env):
    """Same grade, same geometry, mirrored — same answer both ways."""
    for grade, expected in (("POOR", False), ("ACCEPTABLE", True),
                            ("GOOD", True)):
        outcomes = {}
        for direction in BOTH:
            async with env["Session"]() as db:
                for position in (
                    await db.execute(select(DemoPosition))
                ).scalars().all():
                    await db.delete(position)
                await db.commit()
            outcomes[direction] = (
                await _graded_attempt(env, direction, grade=grade)
            ).executed
        assert outcomes["BUY"] == outcomes["SELL"] == expected, (grade, outcomes)


@pytest.mark.parametrize("direction", BOTH)
@pytest.mark.asyncio
async def test_case_7_every_other_gate_still_refuses_an_acceptable_setup(
    env, direction
):
    """ACCEPTABLE buys nothing but the grade check itself.

    Each of these is a different gate refusing the same otherwise-valid
    ACCEPTABLE setup, which is what "eligible when all other gates pass"
    has to mean.
    """
    # Spread.
    wide = await _graded_attempt(env, direction, grade="ACCEPTABLE",
                                 max_spread_points=1)
    assert wide.executed is False
    assert any("spread" in r.lower() for r in wide.reasons), wide.reasons

    # Emergency stop.
    stopped = await _graded_attempt(env, direction, grade="ACCEPTABLE",
                                    emergency_stop=True)
    assert stopped.executed is False
    assert any("emergency" in r.lower() for r in stopped.reasons)

    # Sizing: no room to risk anything.
    tiny = await _graded_attempt(env, direction, grade="ACCEPTABLE",
                                 max_lot_size=0.0)
    assert tiny.executed is False

    # SL/TP sanity: the opposite direction's geometry.
    inverted = GEOMETRY["SELL" if direction == "BUY" else "BUY"]
    flipped = await _graded_attempt(env, direction, grade="ACCEPTABLE",
                                    geometry=inverted)
    assert flipped.executed is False
    assert any("requires" in r for r in flipped.reasons), flipped.reasons

    assert await _positions(env) == []

    # Exposure: fill the account, then try again.
    assert (await _graded_attempt(env, "BUY", grade="ACCEPTABLE")).executed
    assert (await _graded_attempt(env, "SELL", grade="ACCEPTABLE")).executed
    capped = await _graded_attempt(env, direction, grade="ACCEPTABLE")
    assert capped.executed is False
    assert any("open positions" in r.lower() for r in capped.reasons)
