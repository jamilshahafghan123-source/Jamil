"""The same setup, sixty times an hour, must produce one trade (§48).

WHAT THIS IS ACTUALLY FOR
-------------------------
The bot re-reads the market every 60 seconds. A setup that stands for an
hour is therefore DETECTED sixty times, and every one of those detections
is a real, valid, fully-qualified setup — it passes confidence, R:R,
spread and grade every single time, because it is the same good setup it
was a minute ago. Nothing in the risk engine can tell them apart: from
its side, sixty identical approvals are sixty correct answers.

The fingerprint is the only thing that can say "this is the trade you
already took".

THE RULE, EXACTLY
-----------------
A detection is suppressed when a PREVIOUS detection that actually FILLED
shares its fingerprint and is still inside that setup class's cooldown.
The fingerprint is (symbol, direction, setup class, structure state,
entry rounded to a 2.0 band); the cooldown is 90 min for A_PLUS, 45 for
STANDARD, 12 for SCALP.

Anchoring on the FILL rather than on the detection is what keeps it from
over-reaching in either direction:

  * a suppressed detection never fills, so a setup that persists for an
    hour cannot keep refreshing its own cooldown and lock itself out; and
  * a detection the risk engine refused never fills either, so a setup
    blocked by the position cap at 10:00 is tradeable the moment the cap
    clears, instead of serving a cooldown for a trade that never happened.

WHAT IT IS NOT
--------------
It is not a risk control and it cannot approve anything. It only ever
subtracts. Everything that gated a trade before still gates it, and a
setup this mechanism allows through is judged exactly as it was before.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone

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
from app.services import bot, opportunity, telemetry

STRUCTURE = "BOS_UP"
BUY_ENTRY = 3000.2
SELL_ENTRY = 3000.0


# ------------------------------------------------------------- harness


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        user = User(email="dup@example.com", password_hash="x",
                    role=UserRole.CUSTOMER, is_active=True)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        db.add(RiskSettings(
            user_id=user.id, trading_mode=TradingMode.DEMO, bot_enabled=True,
            execution_venue=ExecutionVenue.JGOLD_DEMO,
            min_confidence=50, min_rr=1.5,
            # Deliberately ROOMY. Two positions and ten trades a day mean a
            # second entry is refused by the fingerprint or not at all —
            # a cap of one would pass these tests for the wrong reason.
            max_open_positions=2, max_trades_per_day=10,
            max_lot_size=1.0, max_spread_points=100,
            max_risk_per_trade_pct=1.0, max_daily_loss_pct=5.0,
        ))
        db.add(DemoAccount(user_id=user.id, starting_balance=100000.0,
                           balance=100000.0))
        # Something for the first real signal to differ from, so alerting
        # behaves as it does in production rather than as a special case.
        db.add(Signal(user_id=user.id, symbol="XAUUSD",
                      action=SignalAction.NO_TRADE, confidence=20,
                      reason="nothing yet"))
        await db.commit()
    yield {"Session": Session, "user_id": user.id}
    await engine.dispose()


def _payload(direction: str = "BUY", *, structure: str = STRUCTURE,
             entry: float | None = None, confidence: int = 72) -> dict:
    """One analysis, mirrored properly for either direction."""
    buy = direction == "BUY"
    price = entry if entry is not None else (BUY_ENTRY if buy else SELL_ENTRY)
    stop = price - 10.0 if buy else price + 10.0
    target = price + 40.0 if buy else price - 40.0
    return {
        "market": {"price": 3000.0, "spread_points": 20, "volatility": 6.0,
                   "momentum": "RISING" if buy else "FALLING",
                   "regime": "TREND"},
        "timeframes": [{"timeframe": "M15", "role": "SETUP",
                        "trend": "UP" if buy else "DOWN", "atr14": 6.0}],
        "structure": {"pattern": structure},
        "setup": {
            "confidence_components": {"structure": 20, "trend_alignment": 25,
                                      "momentum": 15, "levels": 10,
                                      "liquidity": 5},
            "trigger_text": "break of the M15 high",
            "trigger": price, "stop_loss": stop,
        },
        "zones": {"fvg": [{"side": "bullish" if buy else "bearish"}],
                  "order_blocks": []},
        "signal": {"action": direction, "entry": price, "stop_loss": stop,
                   "take_profit": target, "risk_reward": 4.0,
                   "confidence": confidence, "reason": "test setup"},
    }


class _Bridge:
    """A live, connected broker feed that never sees a position.

    Positions live on the demo venue in this configuration; a bridge that
    invented one would let a cap refuse an entry the fingerprint was
    supposed to be judged on.
    """

    async def connected(self):
        return True

    async def tick(self, *_a, **_k):
        return {"bid": 3000.0, "ask": 3000.2, "spread_points": 20,
                "time": datetime.now(timezone.utc).isoformat()}

    async def account(self):
        return {"balance": 100000.0, "equity": 100000.0,
                "currency": "USD", "trade_mode": "demo"}

    async def positions(self, *_a, **_k):
        return []


async def _cycle(env, monkeypatch, payload: dict) -> None:
    """One complete bot cycle over one analysis."""

    async def fake_snapshot():
        return {"bid": 3000.0, "ask": 3000.2, "spread_points": 20}

    async def fake_analyze(_snapshot, _settings_row):
        return payload, []

    monkeypatch.setattr(bot, "mt5", _Bridge())
    monkeypatch.setattr(bot, "collect_market_data", fake_snapshot)
    monkeypatch.setattr(bot, "analyze", fake_analyze)
    bot._profit_state.streaks.clear()

    async with env["Session"]() as db:
        user = await db.get(User, env["user_id"])
        await bot._cycle_for_user(db, user)


async def _logs(env) -> list[OpportunityLog]:
    async with env["Session"]() as db:
        rows = (await db.execute(
            select(OpportunityLog).order_by(OpportunityLog.id)
        )).scalars().all()
    return list(rows)


async def _positions(env) -> list[DemoPosition]:
    async with env["Session"]() as db:
        rows = (await db.execute(select(DemoPosition))).scalars().all()
    return list(rows)


async def _seed_entered(env, *, direction: str, structure: str = STRUCTURE,
                        entry: float = BUY_ENTRY, minutes_ago: int = 1,
                        setup_class: str = "STANDARD") -> None:
    """A detection that really was entered, `minutes_ago` minutes back.

    Written through the same recorder the bot uses, then aged, so the row
    is exactly the shape production leaves behind.
    """
    async with env["Session"]() as db:
        row_id = await telemetry.record_opportunity(
            db, user_id=env["user_id"], symbol="XAUUSD", direction=direction,
            confidence=72, expected_rr=4.0, setup_class=setup_class,
            grade="EXCELLENT", score=80, required_confidence=50,
            required_rr=1.5, ai_decision=direction, session="LONDON",
            structure_state=structure, entry_price=entry,
        )
        await telemetry.record_risk_decision(db, row_id, approved=True)
        await telemetry.record_execution(db, row_id, result="FILLED")
        row = await db.get(OpportunityLog, row_id)
        row.detected_at = (datetime.now(timezone.utc)
                           - timedelta(minutes=minutes_ago))
        await db.commit()


# ----------------------------------------- 1 & 2: the repeated setup


@pytest.mark.asyncio
async def test_the_same_buy_setup_on_two_cycles_enters_once(env, monkeypatch):
    """The headline case. Sixty identical reads, one trade."""
    payload = _payload("BUY")
    await _cycle(env, monkeypatch, payload)
    assert len(await _positions(env)) == 1, "the first valid setup must trade"

    await _cycle(env, monkeypatch, payload)
    await _cycle(env, monkeypatch, payload)

    assert len(await _positions(env)) == 1, (
        "the same setup re-read must not open a second position"
    )
    logs = await _logs(env)
    assert [r.suppressed_as_duplicate for r in logs] == [False, True, True]
    assert logs[0].execution_result == "FILLED"
    assert all(r.execution_result == "REJECTED" for r in logs[1:])


@pytest.mark.asyncio
async def test_the_same_sell_setup_on_two_cycles_enters_once(env, monkeypatch):
    """SELL is not a special case, and is not allowed to become one."""
    payload = _payload("SELL")
    await _cycle(env, monkeypatch, payload)
    assert len(await _positions(env)) == 1, "a SELL setup must trade too"

    await _cycle(env, monkeypatch, payload)

    assert len(await _positions(env)) == 1
    logs = await _logs(env)
    assert [r.direction for r in logs] == ["SELL", "SELL"]
    assert [r.suppressed_as_duplicate for r in logs] == [False, True]


# --------------------------------------- 3: the two sides are separate


def test_direction_is_part_of_the_fingerprint():
    """Stated at the level it is decided, so it cannot drift silently."""
    common = dict(symbol="XAUUSD", setup_class=opportunity.SetupClass.A_PLUS,
                  structure_state=STRUCTURE, entry=BUY_ENTRY)
    buy = opportunity.Fingerprint.build(direction="BUY", **common)
    sell = opportunity.Fingerprint.build(direction="SELL", **common)
    assert buy != sell


@pytest.mark.asyncio
async def test_a_buy_does_not_suppress_a_sell(env, monkeypatch):
    """An entered BUY must not cost the account the opposite trade.

    Seeded rather than traded, so no open position exists: the reversal
    manager would otherwise close the BUY and end the cycle, and this
    test would pass without the fingerprint being consulted at all.
    """
    await _seed_entered(env, direction="BUY", entry=SELL_ENTRY)

    await _cycle(env, monkeypatch, _payload("SELL"))

    logs = await _logs(env)
    assert len(logs) == 2
    assert logs[1].direction == "SELL"
    assert logs[1].suppressed_as_duplicate is False
    assert logs[1].execution_result == "FILLED"
    assert len(await _positions(env)) == 1


@pytest.mark.asyncio
async def test_a_sell_does_not_suppress_a_buy(env, monkeypatch):
    await _seed_entered(env, direction="SELL", entry=BUY_ENTRY)

    await _cycle(env, monkeypatch, _payload("BUY"))

    logs = await _logs(env)
    assert logs[1].direction == "BUY"
    assert logs[1].suppressed_as_duplicate is False
    assert logs[1].execution_result == "FILLED"


# ------------------------------------- 4: a genuinely different setup


@pytest.mark.asyncio
async def test_a_changed_structure_is_a_new_opportunity(env, monkeypatch):
    """The cooldown blocks repetition, not development.

    Same direction, same entry, one minute later — but the market has
    broken structure since. That is a different setup and must be allowed
    to trade on its own merits.
    """
    await _seed_entered(env, direction="BUY", structure="RANGE_BOUND")

    await _cycle(env, monkeypatch, _payload("BUY", structure="BOS_UP"))

    logs = await _logs(env)
    assert logs[1].structure_state == "BOS_UP"
    assert logs[1].suppressed_as_duplicate is False
    assert logs[1].execution_result == "FILLED"


@pytest.mark.asyncio
async def test_a_moved_entry_area_is_a_new_opportunity(env, monkeypatch):
    """Same structure, different price. Also a different trade."""
    await _seed_entered(env, direction="BUY", entry=BUY_ENTRY)

    await _cycle(env, monkeypatch, _payload("BUY", entry=3002.5))

    logs = await _logs(env)
    assert logs[1].suppressed_as_duplicate is False
    assert logs[1].execution_result == "FILLED"


@pytest.mark.asyncio
async def test_a_two_cent_drift_is_not_a_new_opportunity(env, monkeypatch):
    """The other half of the same claim, and the one that matters more.

    Without a band, ordinary tick noise would mint a new fingerprint
    every cycle and the mechanism would suppress nothing at all.
    """
    await _seed_entered(env, direction="BUY", entry=BUY_ENTRY)

    await _cycle(env, monkeypatch, _payload("BUY", entry=BUY_ENTRY + 0.02))

    logs = await _logs(env)
    assert logs[1].suppressed_as_duplicate is True
    assert await _positions(env) == []


# ------------------------------------------- 5: the cooldown expiring


@pytest.mark.asyncio
async def test_the_same_setup_may_trade_again_once_the_cooldown_passes(
    env, monkeypatch,
):
    """A setup that is still there an hour later is a fresh decision.

    This payload grades STANDARD, which holds for 45 minutes; the seeded
    entry was 46 ago.
    """
    await _seed_entered(env, direction="BUY", minutes_ago=46)

    await _cycle(env, monkeypatch, _payload("BUY"))

    logs = await _logs(env)
    assert logs[1].setup_class == "STANDARD", (
        "the cooldown under test is the one this class actually gets"
    )
    assert logs[1].suppressed_as_duplicate is False
    assert logs[1].execution_result == "FILLED"


@pytest.mark.asyncio
async def test_the_same_setup_is_still_suppressed_inside_the_cooldown(
    env, monkeypatch,
):
    """The boundary from the other side: 44 minutes is still too soon."""
    await _seed_entered(env, direction="BUY", minutes_ago=44)

    await _cycle(env, monkeypatch, _payload("BUY"))

    logs = await _logs(env)
    assert logs[1].suppressed_as_duplicate is True
    assert await _positions(env) == []


def test_each_class_keeps_its_own_cooldown():
    """A scalp may legitimately repeat sooner than a swing setup."""
    assert opportunity.COOLDOWN[opportunity.SetupClass.A_PLUS] > \
        opportunity.COOLDOWN[opportunity.SetupClass.STANDARD] > \
        opportunity.COOLDOWN[opportunity.SetupClass.SCALP]


# ------------------------------ 6: it cannot replace the risk engine


@pytest.mark.asyncio
async def test_suppression_cannot_approve_what_risk_refuses(env, monkeypatch):
    """A brand-new, unsuppressed setup still faces every gate.

    The account asks for 90% confidence and the setup offers 72, so the
    risk engine must refuse a setup the fingerprint has nothing to say
    about. Clearing the duplicate check is not permission to trade.
    """
    async with env["Session"]() as db:
        row = (await db.execute(select(RiskSettings))).scalar_one()
        row.min_confidence = 90
        await db.commit()

    await _cycle(env, monkeypatch, _payload("BUY"))

    logs = await _logs(env)
    assert logs[0].suppressed_as_duplicate is False, "nothing to repeat yet"
    assert logs[0].risk_decision == "REJECTED"
    assert "confidence" in (logs[0].rejection_reason or "").lower()
    assert await _positions(env) == []


@pytest.mark.asyncio
async def test_a_setup_the_risk_engine_refused_does_not_start_a_cooldown(
    env, monkeypatch,
):
    """The reason the anchor is the FILL and not the detection.

    A setup blocked by the position cap must still be tradeable the
    moment the cap clears — not locked out for the rest of a cooldown
    for a trade that never happened.
    """
    async with env["Session"]() as db:
        row = (await db.execute(select(RiskSettings))).scalar_one()
        row.max_open_positions = 1
        account = (await db.execute(select(DemoAccount))).scalar_one()
        # Held at a LOSS, so neither the profit guard nor the reversal
        # manager has business with it and the cycle reaches the entry
        # decision this test is about.
        db.add(DemoPosition(
            account_id=account.id, symbol="XAUUSD",
            side=DemoPositionSide.BUY, volume=0.1, entry_price=3010.0,
            source=TradeSource.MANUAL, opened_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    await _cycle(env, monkeypatch, _payload("BUY"))
    assert len(await _positions(env)) == 1, "the cap must refuse the entry"
    assert (await _logs(env))[0].risk_decision == "REJECTED"

    async with env["Session"]() as db:
        held = (await db.execute(select(DemoPosition))).scalar_one()
        await db.delete(held)
        await db.commit()

    await _cycle(env, monkeypatch, _payload("BUY"))

    logs = await _logs(env)
    assert logs[1].suppressed_as_duplicate is False, (
        "a refused detection must not serve as a cooldown anchor"
    )
    assert logs[1].execution_result == "FILLED"
    assert len(await _positions(env)) == 1


def test_the_duplicate_branch_only_ever_refuses():
    """Structural, because the behavioural version cannot see a bypass.

    A future edit that moved execution above the fingerprint check, or
    that executed inside it, would still pass every test above.
    """
    source = inspect.getsource(bot._cycle_for_user)
    check = source.index("opportunity.is_duplicate(")
    demo = source.index("demo_execution.execute_signal(")
    broker = source.index("executor.execute_signal(")
    assert check < demo < broker, "the check must precede both venues"

    branch = source[source.index("if duplicate:"):]
    branch = branch[:branch.index("if not may_open:")]
    for forbidden in ("execute_signal", "approved=True", "risk_engine"):
        assert forbidden not in branch, (
            f"the duplicate branch must not {forbidden!r}"
        )


def test_a_failed_duplicate_lookup_does_not_refuse_the_trade():
    """Failing open is the right way round for a mechanism that subtracts.

    A lookup that fell over is not evidence about a setup, and must not
    become a refusal the risk engine never made.
    """
    source = inspect.getsource(bot._cycle_for_user)
    block = source[source.index("opportunity.is_duplicate("):]
    block = block[:block.index("try:\n        opportunity_id")]
    handler = block[block.index("except Exception"):]
    assert "return" not in handler, "a failed check must not end the cycle"
    assert "duplicate = True" not in handler


# ------------------------------------------------ 7: it is on the record


@pytest.mark.asyncio
async def test_telemetry_records_the_suppression_and_says_why(
    env, monkeypatch,
):
    """Section 49: a quiet hour has to be explainable afterwards.

    "The engine kept finding the setup it had already traded" and "the
    engine found nothing" are different days, and the log must be able to
    tell them apart without the reader guessing.
    """
    payload = _payload("BUY")
    await _cycle(env, monkeypatch, payload)
    await _cycle(env, monkeypatch, payload)

    entered, repeat = await _logs(env)

    # The entered one carries what a fingerprint is rebuilt from.
    assert entered.structure_state == STRUCTURE
    assert entered.entry_price == pytest.approx(BUY_ENTRY)
    assert entered.suppressed_as_duplicate is False

    assert repeat.suppressed_as_duplicate is True
    assert repeat.execution_result == "REJECTED"
    assert "cooldown" in (repeat.rejection_reason or "")
    assert "min" in (repeat.rejection_reason or "")
    # Still recorded in full, so the day can be reconstructed exactly.
    assert repeat.score == entered.score
    assert repeat.confidence == 72


@pytest.mark.asyncio
async def test_a_row_without_the_new_fields_can_never_suppress_anything(env,
                                                                        monkeypatch):
    """Rows written before migration 014 are silent, not dangerous.

    They have no structure state and no entry price, so no fingerprint can
    be rebuilt from them. Guessing "UNKNOWN"/0.0 instead would let a row
    from last month collide with a live setup and block it.
    """
    async with env["Session"]() as db:
        row_id = await telemetry.record_opportunity(
            db, user_id=env["user_id"], symbol="XAUUSD", direction="BUY",
            confidence=72, expected_rr=4.0, setup_class="A_PLUS",
            grade="EXCELLENT", score=80, required_confidence=50,
            required_rr=1.5, ai_decision="BUY",
        )
        await telemetry.record_execution(db, row_id, result="FILLED")
        legacy = await db.get(OpportunityLog, row_id)
        assert legacy.structure_state is None
        assert legacy.entry_price is None
        assert telemetry.fingerprints([legacy]) == []

    await _cycle(env, monkeypatch, _payload("BUY"))

    logs = await _logs(env)
    assert logs[1].suppressed_as_duplicate is False
    assert logs[1].execution_result == "FILLED"


@pytest.mark.asyncio
async def test_the_cooldown_lookup_only_sees_entered_detections(env):
    """The query, stated directly, because two tests above depend on it."""
    await _seed_entered(env, direction="BUY", entry=BUY_ENTRY)
    async with env["Session"]() as db:
        refused = await telemetry.record_opportunity(
            db, user_id=env["user_id"], symbol="XAUUSD", direction="BUY",
            confidence=72, expected_rr=4.0, setup_class="A_PLUS",
            grade="EXCELLENT", score=80, required_confidence=50,
            required_rr=1.5, ai_decision="BUY",
            structure_state=STRUCTURE, entry_price=3500.0,
        )
        await telemetry.record_execution(db, refused, result="REJECTED")

        every = await telemetry.recent_fingerprints(
            db, env["user_id"], "XAUUSD")
        entered = await telemetry.recent_fingerprints(
            db, env["user_id"], "XAUUSD", entered_only=True)

    assert len(every) == 2
    assert [r.entry_price for r in entered] == [BUY_ENTRY]


@pytest.mark.asyncio
async def test_another_accounts_trade_cannot_suppress_this_one(env,
                                                               monkeypatch):
    """Fingerprints are per account, and a shared symbol does not merge
    two customers' cooldowns."""
    async with env["Session"]() as db:
        other = User(email="other@example.com", password_hash="x",
                     role=UserRole.CUSTOMER, is_active=True)
        db.add(other)
        await db.commit()
        await db.refresh(other)
        row_id = await telemetry.record_opportunity(
            db, user_id=other.id, symbol="XAUUSD", direction="BUY",
            confidence=72, expected_rr=4.0, setup_class="A_PLUS",
            grade="EXCELLENT", score=80, required_confidence=50,
            required_rr=1.5, ai_decision="BUY",
            structure_state=STRUCTURE, entry_price=BUY_ENTRY,
        )
        await telemetry.record_execution(db, row_id, result="FILLED")

    await _cycle(env, monkeypatch, _payload("BUY"))

    async with env["Session"]() as db:
        mine = (await db.execute(select(OpportunityLog).where(
            OpportunityLog.user_id == env["user_id"]))).scalars().all()
    assert mine[0].suppressed_as_duplicate is False
    assert len(await _positions(env)) == 1


# ------------------------------------- no quota, in either direction


def test_nothing_here_counts_trades_taken():
    """Section 41/105: opportunities are an expectation, never a target.

    A mechanism that suppresses repeats is exactly where a "we are short
    of trades today, allow one" rule would be tempting to add. There is
    no such input, and this asserts there is no such input.
    """
    # Identifiers, not prose. The module's own docstring says the words
    # "trade quota" precisely to rule one out, and a text scan that
    # tripped over that would teach people to stop explaining themselves.
    tree = ast.parse(inspect.getsource(opportunity))
    names = {
        node.id if isinstance(node, ast.Name) else node.arg
        if isinstance(node, ast.arg) else node.attr
        for node in ast.walk(tree)
        if isinstance(node, (ast.Name, ast.arg, ast.Attribute))
    }
    names |= {
        key.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for key in [node]
    }
    for forbidden in ("trades_today", "min_trades", "target_trades",
                      "quota", "daily_target"):
        assert forbidden not in names
    cycle = inspect.getsource(bot._cycle_for_user)
    block = cycle[cycle.index("DUPLICATE / COOLDOWN"):
                  cycle.index("if not may_open:")]
    for forbidden in ("trades_today", "quota", "min_trades"):
        assert forbidden not in block
