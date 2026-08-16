"""API-key authentication for every non-liveness endpoint.

The same secret is accepted two ways, so callers can use whichever their HTTP
client makes natural:

    X-API-Key: <key>
    Authorization: Bearer <key>
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

API_KEY_HEADER = "X-API-Key"

_api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)
_bearer = HTTPBearer(auto_error=False, description="Same secret as X-API-Key.")


async def require_api_key(
    presented: str | None = Security(_api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    presented = presented or (bearer.credentials if bearer else None)
    configured = settings.api_key_list
    if not configured:
        # Fail closed: an unauthenticated trading bridge is never the right default.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: API_KEYS is empty.",
        )

    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing credentials: send {API_KEY_HEADER} or Authorization: Bearer.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # compare_digest against every key so the check is constant-time regardless
    # of which key matched (or whether any did).
    matched = False
    for key in configured:
        if secrets.compare_digest(presented, key):
            matched = True
    if not matched:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
    return presented
