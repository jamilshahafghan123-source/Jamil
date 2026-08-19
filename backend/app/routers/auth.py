"""Authentication: login and current-user lookup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..config import settings
from ..db import get_db
from ..deps import current_user, login_rate_limit
from ..models import RiskSettings, User, UserRole
from ..schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    email = body.email.lower()

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists",
        )

    try:
        password_hash = hash_password(body.password)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            str(e),
        ) from e

    user = User(
        email=email,
        password_hash=password_hash,
        role=UserRole.CUSTOMER,
        is_active=True,
    )

    db.add(user)
    await db.flush()

    db.add(RiskSettings(user_id=user.id))

    await db.commit()
    await db.refresh(user)

    return user


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
