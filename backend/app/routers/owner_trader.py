"""Private owner-only J Gold conversational market analyst."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import require_admin
from ..models import RiskSettings, User
from ..services import owner_trader

router = APIRouter(prefix="/api/admin/trader", tags=["owner-trader"])


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=2000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    symbol: str = Field(default="XAUUSD", max_length=32)
    timeframe: str = Field(default="M5", max_length=8)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class AskOut(BaseModel):
    answer: str
    model: str


@router.post("/ask", response_model=AskOut)
async def ask_owner_trader(
    body: AskIn,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AskOut:
    risk = (
        await db.execute(
            select(RiskSettings).where(RiskSettings.user_id == user.id)
        )
    ).scalar_one_or_none()

    result = await owner_trader.answer(
        question=body.question,
        timeframe=body.timeframe,
        risk_settings=risk,
        history=[turn.model_dump() for turn in body.history],
    )

    return AskOut(
        answer=result["answer"],
        model=result["model"],
    )
