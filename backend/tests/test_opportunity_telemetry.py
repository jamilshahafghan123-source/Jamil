"""Opportunity telemetry storage and views (section 49).

The questions section 49 asks by name — why were only two trades taken,
why were eight setups rejected — are only answerable if the three
outcomes stay apart. These tests hold that apart.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, get_db
from app.main import app
from app.models import (
    OpportunityLog, RiskSettings, Subscription, SubscriptionStatus, User,
    UserRole,
)
from app.security import create_access_token
from app.services import bot, telemetry


def _log(user_id: int, **over) -> OpportunityLog:
    base = dict(
        user_id=user_id,
        detected_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        symbol="XAUUSD", session="LONDON", setup_class="STANDARD",
        grade="GOOD", score=70, direction="BUY", confidence=72,
        expected_rr=1.8, required_confidence=68, required_rr=1.5,
        ai_decision="BUY", risk_decision="APPROVED", execution_result="FILLED",
        score_breakdown={"structure": 14.4},
    )
    base.update(over)
    return OpportunityLog(**base)


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        alice = User(email="alice@example.com", password_hash="x",
                     role=UserRole.CUSTOMER, is_active=True)
        bob = User(email="bob@example.com", password_hash="x",
                   role=UserRole.CUSTOMER, is_active=True)
        admin = User(email="admin@example.com", password_hash="x",
                     role=UserRole.ADMIN, is_active=True)
        db.add_all([alice, bob, admin])
        await db.commit()
        for u in (alice, bob, admin):
            await db.refresh(u)
            db.add(RiskSettings(user_id=u.id))
            db.add(Subscription(user_id=u.id, status=SubscriptionStatus.ACTIVE,
                                plan="monthly", current_period_end=None))
        await db.commit()
        ids = {"alice": alice.id, "bob": bob.id, "admin": admin.id}
        tokens = {k: create_access_token(str(v)) for k, v in ids.items()}

    async def override_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield {"client": client, "tokens": tokens, "ids": ids, "Session": Session}
    app.dependency_overrides.clear()
    await engine.dispose()


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.mark.asyncio
async def test_a_customer_sees_only_their_own_opportunities(env):
    async with env["Session"]() as db:
        db.add(_log(env["ids"]["alice"], symbol="XAUUSD"))
        db.add(_log(env["ids"]["bob"], symbol="XAGUSD"))
        await db.commit()

    r = await env["client"].get("/api/opportunities", headers=_h(env["tokens"]["alice"]))
    assert r.status_code == 200
    symbols = {o["symbol"] for o in r.json()["opportunities"]}
    assert symbols == {"XAUUSD"}


@pytest.mark.asyncio
async def test_the_three_outcomes_stay_separate(env):
    """Section 40: AI, risk and execution answer different questions.

    A day with no trades has completely different causes depending on
    which of the three refused, so none of them may be folded into a
    single status.
    """
    async with env["Session"]() as db:
        db.add(_log(env["ids"]["alice"], ai_decision="BUY",
                    risk_decision="REJECTED",
                    risk_reason="daily loss limit reached",
                    execution_result=None))
        await db.commit()

    row = (await env["client"].get(
        "/api/opportunities", headers=_h(env["tokens"]["alice"]))).json()["opportunities"][0]
    assert row["ai_decision"] == "BUY"
    assert row["risk_decision"] == "REJECTED"
    assert row["execution_result"] is None
    assert row["risk_reason"] == "daily loss limit reached"


@pytest.mark.asyncio
async def test_a_refusal_reports_the_thresholds_that_applied(env):
    """Section 59: a NO TRADE must say exactly what it wanted."""
    async with env["Session"]() as db:
        db.add(_log(env["ids"]["alice"], ai_decision="NO_TRADE",
                    setup_class="SCALP", confidence=61, expected_rr=1.0,
                    required_confidence=70, required_rr=1.1,
                    risk_decision=None, execution_result=None,
                    rejection_reason="confidence 61% below 70% required for a SCALP setup"))
        await db.commit()

    row = (await env["client"].get(
        "/api/opportunities", headers=_h(env["tokens"]["alice"]))).json()["opportunities"][0]
    assert row["required_confidence"] == 70
    assert row["required_rr"] == 1.1
    assert "SCALP" in row["rejection_reason"]


@pytest.mark.asyncio
async def test_the_summary_counts_each_stage(env):
    async with env["Session"]() as db:
        db.add(_log(env["ids"]["alice"], ai_decision="NO_TRADE",
                    risk_decision=None, execution_result=None))
        db.add(_log(env["ids"]["alice"], ai_decision="BUY",
                    risk_decision="REJECTED", execution_result=None,
                    risk_reason="spread too wide"))
        db.add(_log(env["ids"]["alice"], ai_decision="BUY",
                    risk_decision="APPROVED", execution_result="FILLED",
                    outcome_pnl=25.0))
        await db.commit()

    summary = (await env["client"].get(
        "/api/opportunities", headers=_h(env["tokens"]["alice"]))).json()["summary"]
    assert summary["detected"] == 3
    assert summary["ai_no_trade"] == 1
    assert summary["risk_rejected"] == 1
    assert summary["executed"] == 1
    assert summary["top_rejection_reasons"][0]["reason"] == "spread too wide"


@pytest.mark.asyncio
async def test_a_win_rate_is_withheld_until_it_means_something(env):
    """One winning trade is not a 100% win rate.

    Quoting a rate off a couple of samples is the most misleading number
    a trading platform can show, so it is withheld with the count stated
    instead.
    """
    async with env["Session"]() as db:
        db.add(_log(env["ids"]["alice"], execution_result="FILLED", outcome_pnl=10.0))
        await db.commit()

    summary = (await env["client"].get(
        "/api/opportunities", headers=_h(env["tokens"]["alice"]))).json()["summary"]
    assert summary["win_rate"] is None
    assert "too few" in summary["rate_note"]


@pytest.mark.asyncio
async def test_a_win_rate_appears_once_there_is_enough_behind_it(env):
    async with env["Session"]() as db:
        for pnl in (10.0, 20.0, -5.0, 30.0, -8.0, 12.0):
            db.add(_log(env["ids"]["alice"], execution_result="FILLED",
                        outcome_pnl=pnl))
        await db.commit()

    summary = (await env["client"].get(
        "/api/opportunities", headers=_h(env["tokens"]["alice"]))).json()["summary"]
    assert summary["win_rate"] == pytest.approx(66.7, abs=0.1)
    assert summary["settled"] == 6


@pytest.mark.asyncio
async def test_the_admin_view_aggregates_across_customers(env):
    async with env["Session"]() as db:
        db.add(_log(env["ids"]["alice"]))
        db.add(_log(env["ids"]["bob"]))
        await db.commit()

    r = await env["client"].get("/api/admin/opportunities",
                                headers=_h(env["tokens"]["admin"]))
    assert r.status_code == 200
    assert r.json()["customers"] == 2
    assert r.json()["summary"]["detected"] == 2


@pytest.mark.asyncio
async def test_a_customer_cannot_reach_the_admin_view(env):
    r = await env["client"].get("/api/admin/opportunities",
                                headers=_h(env["tokens"]["alice"]))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_the_customer_view_states_there_is_no_trade_target(env):
    """Sections 41 and 105: 4-8 is an expectation, never a target."""
    r = await env["client"].get("/api/opportunities",
                                headers=_h(env["tokens"]["alice"]))
    assert "no trade target" in r.json()["note"].lower()


@pytest.mark.asyncio
async def test_older_rows_fall_outside_the_requested_window(env):
    async with env["Session"]() as db:
        db.add(_log(env["ids"]["alice"],
                    detected_at=datetime.now(timezone.utc) - timedelta(days=9)))
        await db.commit()

    one_day = await env["client"].get("/api/opportunities?days=1",
                                      headers=_h(env["tokens"]["alice"]))
    ten_days = await env["client"].get("/api/opportunities?days=14",
                                       headers=_h(env["tokens"]["alice"]))
    assert one_day.json()["summary"]["detected"] == 0
    assert ten_days.json()["summary"]["detected"] == 1


# --------------------------------------------- the bot actually records


def test_the_bot_cycle_records_before_the_risk_manager_rules():
    """Telemetry is written where it can explain a quiet day.

    `opportunity_logs` existed with nothing writing to it, so the log was
    permanently empty and "no trades today" was unexplainable. These
    assertions pin the ORDER: the opportunity is recorded as soon as the
    engine has an opinion, before execution, so a setup the risk manager
    later refuses is still on the record.
    """
    source = inspect.getsource(bot._cycle_for_user)

    assert "telemetry.record_opportunity" in source
    assert "telemetry.record_risk_decision" in source
    assert "telemetry.record_execution" in source

    recorded = source.index("telemetry.record_opportunity")
    executed = source.index("demo_execution.execute_signal")
    assert recorded < executed, "the opportunity must be on record first"


def test_a_held_bot_still_records_why_nothing_was_opened():
    """A pause that recorded nothing would look identical to a dead engine."""
    source = inspect.getsource(bot._cycle_for_user)
    after_gate = source.split("if not may_open:")[1].split("return")[0]
    assert "record_execution" in after_gate


def test_telemetry_failures_cannot_stop_a_trade():
    """Every recorder swallows its own storage errors.

    A reporting outage becoming a refused trade would be a far worse
    failure than the outage.
    """
    source = inspect.getsource(telemetry)
    for name in ("record_opportunity", "record_risk_decision",
                 "record_execution", "record_outcome"):
        body = source.split(f"async def {name}(")[1].split("\nasync def ")[0]
        assert "except Exception" in body, name
        assert "raise" not in body, name

# ------------------------------- a real cycle, end to end, with stubs


@pytest.mark.asyncio
async def test_a_bot_cycle_writes_telemetry_fires_an_alert_and_executes(
    env, monkeypatch
):
    """One cycle, everything it is supposed to do, actually done.

    The AST tests above pin the ORDER of the calls. This runs the cycle
    and checks the rows: an opportunity recorded with the risk ruling and
    the fill attached, an alert fired for the signal change, and a
    DemoPosition linked back to the opportunity it came from. All three
    had complete machinery and no caller at some point in this branch, so
    all three are asserted by execution rather than by structure.
    """
    from sqlalchemy import select

    from app.models import (
        Alert, AlertKind, DemoAccount, DemoPosition, ExecutionVenue,
        Signal, SignalAction, TradingMode,
    )

    Session = env["Session"]
    user_id = env["ids"]["alice"]

    async with Session() as db:
        row = (await db.execute(select(RiskSettings).where(
            RiskSettings.user_id == user_id))).scalar_one()
        row.trading_mode = TradingMode.DEMO
        row.bot_enabled = True
        row.execution_venue = ExecutionVenue.JGOLD_DEMO
        row.min_confidence = 50
        row.min_rr = 1.5
        row.max_open_positions = 2
        row.max_trades_per_day = 10
        row.max_lot_size = 1.0
        row.max_spread_points = 100
        row.max_risk_per_trade_pct = 1.0
        row.max_daily_loss_pct = 5.0
        db.add(DemoAccount(user_id=user_id, starting_balance=100000.0,
                           balance=100000.0))
        db.add(Alert(user_id=user_id, kind=AlertKind.AI_SIGNAL_CHANGE,
                     symbol="XAUUSD", enabled=True, repeatable=True))
        # A previous read for the new one to differ FROM. The first signal
        # on a fresh account notifies nobody, deliberately: with nothing
        # before it there is no change to report.
        db.add(Signal(user_id=user_id, symbol="XAUUSD",
                      action=SignalAction.NO_TRADE, confidence=20,
                      reason="nothing yet"))
        await db.commit()

    now = datetime.now(timezone.utc).isoformat()

    class Bridge:
        async def connected(self):
            return True

        async def tick(self, *_a, **_k):
            return {"bid": 3000.0, "ask": 3000.2, "spread_points": 20,
                    "time": now}

        async def account(self):
            return {"balance": 100000.0, "equity": 100000.0,
                    "currency": "USD", "trade_mode": "demo"}

        async def positions(self, *_a, **_k):
            return []

    payload = {
        "market": {"price": 3000.0, "spread_points": 20, "volatility": 6.0,
                   "momentum": "RISING", "regime": "TREND"},
        "timeframes": [{"timeframe": "M15", "role": "SETUP", "trend": "UP",
                        "atr14": 6.0}],
        "setup": {
            "confidence_components": {"structure": 20, "trend_alignment": 25,
                                      "momentum": 15, "levels": 10,
                                      "liquidity": 5},
            "trigger_text": "break of the M15 high",
            "trigger": 3000.2, "stop_loss": 2990.0,
        },
        "zones": {"fvg": [{"bias": "BULLISH"}], "order_blocks": []},
        "signal": {"action": "BUY", "entry": 3000.2, "stop_loss": 2990.0,
                   "take_profit": 3040.0, "risk_reward": 4.0,
                   "confidence": 72, "reason": "test setup"},
    }

    async def fake_snapshot():
        return {"bid": 3000.0, "ask": 3000.2, "spread_points": 20}

    async def fake_analyze(_snapshot, _settings_row):
        return payload, []

    monkeypatch.setattr(bot, "mt5", Bridge())
    monkeypatch.setattr(bot, "collect_market_data", fake_snapshot)
    monkeypatch.setattr(bot, "analyze", fake_analyze)
    bot._profit_state.streaks.clear()

    async with Session() as db:
        user = await db.get(User, user_id)
        await bot._cycle_for_user(db, user)

    async with Session() as db:
        logs = (await db.execute(select(OpportunityLog).where(
            OpportunityLog.user_id == user_id))).scalars().all()
        assert len(logs) == 1, "the cycle must record what it saw"
        record = logs[0]
        assert record.direction == "BUY"
        assert record.confidence == 72
        assert record.setup_class in ("A_PLUS", "STANDARD", "SCALP")
        assert 0 < record.score <= 100
        assert record.session, "the session it was detected in"
        # Three separate outcomes, all three filled by one cycle.
        assert record.ai_decision in ("BUY", "NO_TRADE")
        assert record.risk_decision == "APPROVED"
        assert record.execution_result == "FILLED"

        alert = (await db.execute(select(Alert).where(
            Alert.user_id == user_id))).scalar_one()
        assert alert.trigger_count == 1, "a new BUY is a change worth telling"
        assert "NO_TRADE to BUY" in alert.last_message
        assert alert.acknowledged is False

        positions = (await db.execute(select(DemoPosition))).scalars().all()
        assert len(positions) == 1
        assert positions[0].opportunity_id == record.id, \
            "the position points back at the opportunity it came from"


@pytest.mark.asyncio
async def test_a_suppressed_repeat_is_its_own_stage_in_the_feed(env):
    """Section 48 read back through section 49.

    A repeat never reaches the risk manager, so it has no risk ruling. If
    the feed could not say why it stopped, the funnel would show a
    detection that simply vanished — and counting it under "risk
    rejected" would overstate what the risk manager actually refused.
    """
    async with env["Session"]() as db:
        db.add(_log(env["ids"]["alice"], ai_decision="BUY",
                    risk_decision=None, execution_result="REJECTED",
                    suppressed_as_duplicate=True,
                    rejection_reason=("same STANDARD setup seen 3 min ago; "
                                      "42 min of cooldown left")))
        db.add(_log(env["ids"]["alice"], ai_decision="BUY",
                    risk_decision="APPROVED", execution_result="FILLED"))
        await db.commit()

    feed = (await env["client"].get(
        "/api/opportunities", headers=_h(env["tokens"]["alice"]))).json()
    assert feed["summary"]["suppressed_duplicates"] == 1
    assert feed["summary"]["risk_rejected"] == 0
    assert feed["summary"]["executed"] == 1

    rows = {r["execution_result"]: r for r in feed["opportunities"]}
    assert rows["REJECTED"]["suppressed_as_duplicate"] is True
    assert "cooldown" in rows["REJECTED"]["rejection_reason"]
    assert rows["FILLED"]["suppressed_as_duplicate"] is False
