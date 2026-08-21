"""Opportunity telemetry (section 49).

Answers the questions section 49 asks by name: why were only two trades
taken, why were eight setups rejected, and which setup classes and
sessions actually performed.

The three outcomes stay separate throughout — AI decision, risk ruling,
execution result — because a day with no trades has completely different
causes depending on which of the three did the refusing.

Ownership is enforced in the query. A customer sees their own
opportunities; the admin view aggregates across the platform and is
gated by `require_admin`, which 404s for anyone else.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user, rate_limit, require_admin, require_platform_access
from ..models import OpportunityLog, User

router = APIRouter(
    prefix="/api/opportunities",
    tags=["opportunities"],
    dependencies=[Depends(rate_limit), Depends(require_platform_access)],
)

admin_router = APIRouter(
    prefix="/api/admin/opportunities",
    tags=["admin"],
    dependencies=[Depends(rate_limit), Depends(require_admin)],
)


def _row(log: OpportunityLog) -> dict:
    return {
        "id": log.id,
        "detected_at": log.detected_at.isoformat() if log.detected_at else None,
        "symbol": log.symbol,
        "session": log.session,
        "setup_class": log.setup_class,
        "grade": log.grade,
        "score": log.score,
        "direction": log.direction,
        "confidence": log.confidence,
        "expected_rr": log.expected_rr,
        "required_confidence": log.required_confidence,
        "required_rr": log.required_rr,
        "ai_decision": log.ai_decision,
        "risk_decision": log.risk_decision,
        "risk_reason": log.risk_reason,
        "execution_result": log.execution_result,
        "rejection_reason": log.rejection_reason,
        "outcome_pnl": log.outcome_pnl,
        "score_breakdown": log.score_breakdown or {},
        # Section 48. Without this a suppressed repeat reads as a
        # detection that simply vanished: it has no risk ruling, because
        # it never reached the risk engine.
        "suppressed_as_duplicate": log.suppressed_as_duplicate,
    }


def _summarise(rows: list[OpportunityLog]) -> dict:
    """Aggregate a day without inventing anything it does not contain.

    Rates are reported as counts alongside the percentage, so a "100% win
    rate" drawn from one trade cannot be mistaken for a track record.
    """
    executed = [r for r in rows if r.execution_result == "FILLED"]
    settled = [r for r in executed if r.outcome_pnl is not None]
    wins = [r for r in settled if (r.outcome_pnl or 0) > 0]
    losses = [r for r in settled if (r.outcome_pnl or 0) < 0]

    rejected = [r for r in rows if r.risk_decision == "REJECTED"]
    no_trade = [r for r in rows if r.ai_decision == "NO_TRADE"]
    # Counted separately from `risk_rejected` on purpose: these never
    # reached the risk engine, and folding them in would overstate how
    # much the risk manager refused.
    duplicates = [r for r in rows if r.suppressed_as_duplicate]

    summary = {
        "detected": len(rows),
        "ai_proposed": len(rows) - len(no_trade),
        "ai_no_trade": len(no_trade),
        "risk_rejected": len(rejected),
        "suppressed_duplicates": len(duplicates),
        "executed": len(executed),
        "settled": len(settled),
        "wins": len(wins),
        "losses": len(losses),
        "by_setup_class": dict(Counter(r.setup_class for r in rows)),
        "by_session": dict(Counter(r.session for r in rows if r.session)),
        "by_grade": dict(Counter(r.grade for r in rows)),
        "top_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in Counter(
                r.risk_reason or r.rejection_reason
                for r in rows
                if (r.risk_reason or r.rejection_reason)
            ).most_common(5)
        ],
    }

    # Only report a rate once there is enough behind it to mean anything.
    if len(settled) >= 5:
        summary["win_rate"] = round(len(wins) / len(settled) * 100, 1)
        summary["net_pnl"] = round(sum(r.outcome_pnl or 0 for r in settled), 2)
    else:
        summary["win_rate"] = None
        summary["net_pnl"] = (
            round(sum(r.outcome_pnl or 0 for r in settled), 2) if settled else None
        )
        summary["rate_note"] = (
            f"{len(settled)} settled trade(s) — too few to quote a win rate."
        )
    return summary


def _window(days: int) -> datetime:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    return datetime.combine(start.date(), time(0, 0), tzinfo=timezone.utc)


@router.get("")
async def my_opportunities(
    days: int = Query(1, ge=1, le=30),
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """This customer's opportunities, newest first, with the day's summary."""
    rows = (
        await db.execute(
            select(OpportunityLog)
            .where(
                OpportunityLog.user_id == user.id,
                OpportunityLog.detected_at >= _window(days),
            )
            .order_by(OpportunityLog.detected_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return {
        "days": days,
        "summary": _summarise(list(rows)),
        "opportunities": [_row(r) for r in rows],
        "note": (
            "Every opportunity the engine detected, including the ones it "
            "declined. There is no trade target: a day with no qualifying "
            "setup correctly produces no trades."
        ),
    }


@admin_router.get("")
async def all_opportunities(
    days: int = Query(1, ge=1, le=30),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Platform-wide telemetry for the control centre."""
    rows = (
        await db.execute(
            select(OpportunityLog)
            .where(OpportunityLog.detected_at >= _window(days))
            .order_by(OpportunityLog.detected_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    rows = list(rows)
    return {
        "days": days,
        "summary": _summarise(rows),
        "opportunities": [_row(r) for r in rows],
        "customers": len({r.user_id for r in rows}),
    }
