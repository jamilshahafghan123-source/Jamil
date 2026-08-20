"""Security response headers (section 11).

Two rules shape what is set here:

* HSTS only over real HTTPS in production. Sending it on localhost pins the
  browser to https://localhost for months and is a genuinely painful thing
  to undo, so it is gated on ENV *and* on the request actually arriving over
  TLS.
* The CSP allows the inline styles and the same-origin websocket the app
  actually uses, and nothing else. A policy that breaks the app gets turned
  off, which is worse than a policy that is merely tight.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings

CSP = "; ".join(
    (
        "default-src 'self'",
        # Vite emits a small inline style block; scripts stay strict.
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "connect-src 'self' ws: wss:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        # Modern replacement for X-Frame-Options; both are sent.
        "frame-ancestors 'none'",
    )
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        # HSTS: production, over TLS, only. See the module docstring.
        if settings.ENV == "prod" and request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
