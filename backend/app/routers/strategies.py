"""Customer strategies (sections 32-37).

Ownership is enforced IN THE QUERY, never after the fetch: every
statement carries `Strategy.user_id == user.id`, so a mismatched id
returns nothing to check rather than returning a row that then has to be
rejected. A missing row and someone else's row are the same 404, which
also means this cannot be used to discover that another customer's
strategy exists.

Every rule is re-parsed through services.strategy on write AND on read.
A row altered directly in the database still cannot smuggle in anything
outside the closed vocabulary, because nothing here trusts stored JSON.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import current_user, rate_limit, require_platform_access
from ..models import Strategy, StrategyActionMode, User
from ..services import strategy as rules

router = APIRouter(
    prefix="/api/strategies",
    tags=["strategies"],
    dependencies=[Depends(rate_limit), Depends(require_platform_access)],
)

MAX_PER_USER = 50


class StrategyIn(BaseModel):
    name: str = PydanticField(min_length=1, max_length=80)
    symbol: str = PydanticField(min_length=1, max_length=24)
    timeframe: str = PydanticField(default="M15", max_length=8)
    direction: str = PydanticField(pattern="^(BUY|SELL)$")
    action_mode: str = "ALERT_ONLY"
    rule: dict
    notes: str = PydanticField(default="", max_length=500)
    enabled: bool = True


def _validated(body: StrategyIn) -> rules.StrategyDefinition:
    """Parse or refuse. A 400 with the reason beats a silent coercion."""
    try:
        return rules.parse_strategy(body.model_dump())
    except rules.StrategyError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None


def _out(row: Strategy) -> dict:
    """Serialise, re-validating the stored rule on the way out."""
    try:
        parsed = rules.parse_node(row.rule)
        rule_payload = parsed.as_dict()
        description = rules.describe(parsed)
        valid = True
    except rules.StrategyError as e:
        # A rule that no longer parses is reported as invalid rather than
        # rendered: it must not silently look runnable.
        rule_payload = {}
        description = [f"This strategy can no longer be read: {e}"]
        valid = False
    return {
        "id": row.id,
        "name": row.name,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "direction": row.direction,
        "action_mode": row.action_mode.value,
        "rule": rule_payload,
        "description": description,
        "valid": valid,
        "notes": row.notes,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/vocabulary")
async def vocabulary(_user: User = Depends(current_user)) -> dict:
    """Everything a rule may refer to.

    The builder reads its options from here rather than hard-coding them,
    so the UI cannot offer a field the backend would reject.
    """
    return {
        "fields": [
            {
                "field": f.value,
                "boolean": f in rules.BOOLEAN_FIELDS,
                "zone": f in rules.ZONE_FIELDS,
                "labels": sorted(rules.LABEL_VALUES.get(f, [])),
            }
            for f in rules.Field
        ],
        "operators": [o.value for o in rules.Operator],
        "logic": [l.value for l in rules.Logic],
        "action_modes": [m.value for m in rules.ActionMode],
        "timeframes": sorted(rules.TIMEFRAMES),
        "limits": {
            "max_conditions": rules.MAX_CONDITIONS,
            "max_depth": rules.MAX_DEPTH,
            "max_strategies": MAX_PER_USER,
        },
        "note": (
            "Strategies are built from these conditions only. No code of "
            "any kind is accepted or executed, and a strategy proposes a "
            "setup — the risk manager still decides."
        ),
    }


@router.get("")
async def list_strategies(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (
        await db.execute(
            select(Strategy)
            .where(Strategy.user_id == user.id)
            .order_by(Strategy.updated_at.desc())
        )
    ).scalars().all()
    return [_out(row) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_strategy(
    body: StrategyIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    definition = _validated(body)

    existing = (
        await db.execute(
            select(Strategy.id).where(Strategy.user_id == user.id)
        )
    ).scalars().all()
    if len(existing) >= MAX_PER_USER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"You already have {MAX_PER_USER} strategies. Delete one first.",
        )

    row = Strategy(
        user_id=user.id,
        name=definition.name,
        symbol=definition.symbol,
        timeframe=definition.timeframe,
        direction=definition.direction,
        action_mode=StrategyActionMode(definition.action_mode.value),
        rule=definition.rule.as_dict(),
        notes=definition.notes,
        enabled=definition.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.put("/{strategy_id}")
async def update_strategy(
    strategy_id: int,
    body: StrategyIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    definition = _validated(body)
    row = (
        await db.execute(
            select(Strategy).where(
                Strategy.id == strategy_id, Strategy.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")

    row.name = definition.name
    row.symbol = definition.symbol
    row.timeframe = definition.timeframe
    row.direction = definition.direction
    row.action_mode = StrategyActionMode(definition.action_mode.value)
    row.rule = definition.rule.as_dict()
    row.notes = definition.notes
    row.enabled = definition.enabled
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.post("/{strategy_id}/clone", status_code=status.HTTP_201_CREATED)
async def clone_strategy(
    strategy_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(Strategy).where(
                Strategy.id == strategy_id, Strategy.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")

    # A clone starts disabled: copying a running strategy should not
    # quietly double what it does.
    copy = Strategy(
        user_id=user.id, name=f"{row.name} (copy)"[:80], symbol=row.symbol,
        timeframe=row.timeframe, direction=row.direction,
        action_mode=row.action_mode, rule=row.rule, notes=row.notes,
        enabled=False,
    )
    db.add(copy)
    await db.commit()
    await db.refresh(copy)
    return _out(copy)


@router.post("/{strategy_id}/enabled")
async def set_enabled(
    strategy_id: int,
    enabled: bool,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(Strategy).where(
                Strategy.id == strategy_id, Strategy.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    if enabled:
        # Refuse to enable something that no longer parses.
        try:
            rules.parse_node(row.rule)
        except rules.StrategyError as e:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"This strategy can no longer be read: {e}",
            ) from None
    row.enabled = enabled
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        delete(Strategy).where(
            Strategy.id == strategy_id, Strategy.user_id == user.id
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    return {"deleted": strategy_id}
