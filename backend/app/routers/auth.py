"""Authentication: login and current-user lookup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import current_user, login_rate_limit
from ..models import RiskSettings, User
from ..schemas import LoginRequest, TokenResponse, UserOut
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(login_rate_limit),
) -> TokenResponse:
    user = (
        await db.execute(select(User).where(User.email == body.email.lower()))
    ).scalar_one_or_none()

    # Same error and roughly the same work either way — don't leak which
    # emails exist.
    if user is None or not verify_password(body.password, user.password_hash):
        await audit.record(db, audit.LOGIN_FAILED, {"email": body.email.lower()})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")

    # Make sure a settings row exists from the first login.
    existing = (
        await db.execute(select(RiskSettings).where(RiskSettings.user_id == user.id))
    ).scalar_one_or_none()
    if existing is None:
        db.add(RiskSettings(user_id=user.id))
        await db.commit()

    await audit.record(db, audit.LOGIN_SUCCESS, {"email": user.email}, user.id)

    return TokenResponse(
        access_token=create_access_token(str(user.id), {"email": user.email}),
        expires_in=settings.ACCESS_TOKEN_MINUTES * 60,
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user
