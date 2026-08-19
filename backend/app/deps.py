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
from .models import RiskSettings, User
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
