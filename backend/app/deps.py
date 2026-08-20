"""Shared FastAPI dependencies: auth, settings row, rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import RiskSettings, Subscription, User, UserRole
from .services import entitlements
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(creds.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or disabled")
    return user


async def get_risk_settings(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> RiskSettings:
    row = (
        await db.execute(select(RiskSettings).where(RiskSettings.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        row = RiskSettings(user_id=user.id)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


# ---------------------------------------------------------------- rate limit

# In-process sliding window. Correct for a single Cloud Run instance; if you
# scale past one instance and need a global limit, move this to Redis /
# Memorystore. Documented rather than silently approximate.
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_key(request: Request) -> str:
    # Cloud Run puts the real client first in X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
    return f"{ip}:{request.url.path}"


def rate_limiter(per_minute: int | None = None) -> Callable[[Request], Awaitable[None]]:
    """Build a sliding-window rate-limit dependency.

    This is a closure, not a callable class, on purpose. This module uses
    `from __future__ import annotations`, so every annotation is a string at
    runtime. FastAPI resolves a dependency's string annotations against
    `call.__globals__` — which a *class instance* does not have. A callable
    instance therefore had its `request: Request` parameter left unresolved
    and was treated as a required **query** parameter, making every route that
    depends on it reject all traffic with 422. A function has `__globals__`,
    so `Request` resolves and the parameter is injected correctly.
    """
    limit = per_minute or settings.RATE_LIMIT_PER_MINUTE

    async def dependency(request: Request) -> None:
        key = _client_key(request)
        now = time.monotonic()
        window = _hits[key]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= limit:
            retry = max(1, int(60 - (now - window[0])))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Rate limit exceeded",
                headers={"Retry-After": str(retry)},
            )
        window.append(now)

    return dependency


rate_limit = rate_limiter()
login_rate_limit = rate_limiter(settings.LOGIN_RATE_LIMIT_PER_MINUTE)


async def require_admin(user: User = Depends(current_user)) -> User:
    """Gate an endpoint to ADMIN accounts.

    Section 81: the control centre must never be reachable by a customer.
    404 rather than 403 on purpose — a customer probing for admin routes
    learns nothing about which ones exist.

    Note this guards only the endpoints that depend on it. The existing
    trading and risk routes still authorise on authentication alone; see
    the note in app/routers/admin.py.
    """
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return user


async def _subscription_for(db: AsyncSession, user: User) -> Subscription | None:
    return (
        await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    ).scalar_one_or_none()


async def require_platform_access(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Gate a paid platform feature.

    ADMIN passes free. A CUSTOMER needs an entitling subscription inside
    its paid period; an account with no row at all has none, so this fails
    closed for every account that predates the subscriptions table.

    403, not 401. A 401 makes the frontend clear the token and bounce to
    login, which for a signed-in customer without a subscription would be a
    loop; 403 lets the app show the subscription page instead. The message
    names no role, plan or provider detail.
    """
    sub = await _subscription_for(db, user)
    allowed = entitlements.has_platform_access(
        role=user.role,
        is_active=user.is_active,
        status=sub.status if sub else None,
        current_period_end=sub.current_period_end if sub else None,
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "An active subscription is required to use this feature.",
        )
    return user


async def require_demo_access(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Gate a demo feature.

    Separate from require_platform_access even though the two currently
    agree, so that opening a free demo is a change to
    services/entitlements.py rather than a re-audit of every route.
    """
    sub = await _subscription_for(db, user)
    allowed = entitlements.has_demo_access(
        role=user.role,
        is_active=user.is_active,
        status=sub.status if sub else None,
        current_period_end=sub.current_period_end if sub else None,
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "An active subscription is required to use this feature.",
        )
    return user
