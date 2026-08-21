"""Recording opportunity telemetry (sections 40, 49).

One place that writes `opportunity_logs`, so the three outcomes are
always filled in the same order by the same code: what the AI decided,
what the risk manager ruled, what execution did.

Recording must never be able to break trading. Every function here
swallows its own storage errors and reports the failure through the
return value instead of raising — a telemetry outage is a reporting
problem, and turning it into a refused trade would be a far worse one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import OpportunityLog

log = logging.getLogger(__name__)


async def record_opportunity(
    db: AsyncSession,
    *,
    user_id: int,
    symbol: str,
    direction: str,
    confidence: int,
    expected_rr: float,
    setup_class: str,
    grade: str,
    score: int,
    required_confidence: int,
    required_rr: float,
    ai_decision: str,
    session: str = "",
    rejection_reason: str | None = None,
    score_breakdown: dict | None = None,
) -> int | None:
    """Write the AI's half of the record. Returns the row id, or None.

    Called as soon as the engine has an opinion, BEFORE the risk manager
    rules — so a setup the risk manager later refuses is still on the
    record, which is the entire point of section 49.
    """
    row = OpportunityLog(
        user_id=user_id,
        detected_at=datetime.now(timezone.utc),
        symbol=symbol,
        session=session,
        setup_class=setup_class,
        grade=grade,
        score=score,
        direction=direction,
        confidence=confidence,
        expected_rr=expected_rr,
        required_confidence=required_confidence,
        required_rr=required_rr,
        ai_decision=ai_decision,
        rejection_reason=rejection_reason,
        score_breakdown=score_breakdown or {},
    )
    try:
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id
    except Exception:  # pragma: no cover - storage failure path
        # Never let a reporting failure stop a trade being evaluated.
        log.warning("opportunity telemetry write failed", exc_info=True)
        await db.rollback()
        return None


async def record_risk_decision(
    db: AsyncSession, opportunity_id: int | None, *,
    approved: bool, reason: str | None = None,
) -> None:
    """Attach the risk manager's ruling to an existing record."""
    if opportunity_id is None:
        return
    try:
        row = await db.get(OpportunityLog, opportunity_id)
        if row is None:
            return
        row.risk_decision = "APPROVED" if approved else "REJECTED"
        row.risk_reason = reason
        await db.commit()
    except Exception:  # pragma: no cover - storage failure path
        log.warning("risk telemetry write failed", exc_info=True)
        await db.rollback()


async def record_execution(
    db: AsyncSession, opportunity_id: int | None, *,
    result: str, reason: str | None = None,
) -> None:
    """Attach what execution actually did.

    `result` is FILLED, REJECTED or FAILED. Kept apart from the risk
    ruling because "risk approved it and the broker refused it" and "risk
    refused it" are different days.
    """
    if opportunity_id is None:
        return
    try:
        row = await db.get(OpportunityLog, opportunity_id)
        if row is None:
            return
        row.execution_result = result
        if reason:
            row.rejection_reason = reason
        await db.commit()
    except Exception:  # pragma: no cover - storage failure path
        log.warning("execution telemetry write failed", exc_info=True)
        await db.rollback()


async def record_outcome(
    db: AsyncSession, opportunity_id: int | None, *, pnl: float,
) -> None:
    """Attach realised P/L once the resulting position closed."""
    if opportunity_id is None:
        return
    try:
        row = await db.get(OpportunityLog, opportunity_id)
        if row is None:
            return
        row.outcome_pnl = pnl
        await db.commit()
    except Exception:  # pragma: no cover - storage failure path
        log.warning("outcome telemetry write failed", exc_info=True)
        await db.rollback()


async def recent_fingerprints(
    db: AsyncSession, user_id: int, symbol: str, limit: int = 40,
) -> list[OpportunityLog]:
    """Recent detections, for the duplicate/cooldown check (section 48)."""
    rows = (
        await db.execute(
            select(OpportunityLog)
            .where(
                OpportunityLog.user_id == user_id,
                OpportunityLog.symbol == symbol.upper(),
            )
            .order_by(OpportunityLog.detected_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)
