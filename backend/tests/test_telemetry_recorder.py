"""Telemetry recording (sections 40, 49)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import OpportunityLog, User, UserRole
from app.services import telemetry


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        user = User(email="a@example.com", password_hash="x",
                    role=UserRole.CUSTOMER, is_active=True)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        yield session, user.id
    await engine.dispose()


async def _detect(session, user_id, **over):
    body = dict(
        user_id=user_id, symbol="XAUUSD", direction="BUY", confidence=72,
        expected_rr=1.8, setup_class="STANDARD", grade="GOOD", score=70,
        required_confidence=68, required_rr=1.5, ai_decision="BUY",
        session="LONDON",
    )
    body.update(over)
    return await telemetry.record_opportunity(session, **body)


@pytest.mark.asyncio
async def test_a_detection_is_recorded_before_risk_rules_on_it(db):
    """A setup the risk manager later refuses must still be on the record.

    Recording only what got executed would answer "what did we trade?"
    while section 49 asks "what did we see, and why did we not trade it?"
    """
    session, user_id = db
    row_id = await _detect(session, user_id)
    assert row_id is not None
    row = await session.get(OpportunityLog, row_id)
    assert row.ai_decision == "BUY"
    assert row.risk_decision is None
    assert row.execution_result is None


@pytest.mark.asyncio
async def test_each_stage_fills_only_its_own_column(db):
    session, user_id = db
    row_id = await _detect(session, user_id)

    await telemetry.record_risk_decision(session, row_id, approved=False,
                                         reason="spread too wide")
    row = await session.get(OpportunityLog, row_id)
    assert row.risk_decision == "REJECTED"
    assert row.risk_reason == "spread too wide"
    assert row.ai_decision == "BUY"          # untouched
    assert row.execution_result is None      # untouched

    await telemetry.record_execution(session, row_id, result="FAILED",
                                     reason="bridge unreachable")
    row = await session.get(OpportunityLog, row_id)
    assert row.execution_result == "FAILED"
    assert row.risk_decision == "REJECTED"   # still untouched


@pytest.mark.asyncio
async def test_the_outcome_is_attached_when_the_position_settles(db):
    session, user_id = db
    row_id = await _detect(session, user_id)
    await telemetry.record_execution(session, row_id, result="FILLED")
    await telemetry.record_outcome(session, row_id, pnl=-18.5)
    row = await session.get(OpportunityLog, row_id)
    assert row.outcome_pnl == -18.5
    assert row.execution_result == "FILLED"


@pytest.mark.asyncio
async def test_recording_against_a_missing_id_is_a_no_op(db):
    """A telemetry gap must never raise into the trading path."""
    session, _ = db
    await telemetry.record_risk_decision(session, None, approved=True)
    await telemetry.record_execution(session, 999999, result="FILLED")
    await telemetry.record_outcome(session, None, pnl=1.0)


@pytest.mark.asyncio
async def test_a_no_trade_records_the_thresholds_it_missed(db):
    session, user_id = db
    row_id = await _detect(
        session, user_id, ai_decision="NO_TRADE", setup_class="SCALP",
        confidence=61, required_confidence=70, required_rr=1.1,
        rejection_reason="confidence 61% below 70% required for a SCALP setup",
    )
    row = await session.get(OpportunityLog, row_id)
    assert row.ai_decision == "NO_TRADE"
    assert row.required_confidence == 70
    assert "SCALP" in row.rejection_reason


@pytest.mark.asyncio
async def test_recent_detections_are_scoped_to_owner_and_symbol(db):
    session, user_id = db
    await _detect(session, user_id, symbol="XAUUSD")
    await _detect(session, user_id, symbol="XAGUSD")
    rows = await telemetry.recent_fingerprints(session, user_id, "XAUUSD")
    assert [r.symbol for r in rows] == ["XAUUSD"]
