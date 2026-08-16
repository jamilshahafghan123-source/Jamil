"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from .errors import TerminalUnavailableError
from .mt5.session import MT5Session


def get_session(request: Request) -> MT5Session:
    session: MT5Session | None = getattr(request.app.state, "mt5_session", None)
    if session is None:  # pragma: no cover - only if startup was skipped
        raise TerminalUnavailableError("MT5 session is not initialised.")
    return session
