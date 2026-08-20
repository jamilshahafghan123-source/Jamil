"""ADMIN-only control centre access (section 81).

The gate is the point of these tests: a customer must not reach the control
centre, and the platform-wide emergency stop must halt automation without
closing anybody's positions.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.deps import require_admin
from app.models import UserRole


class FakeUser:
    def __init__(self, role: UserRole) -> None:
        self.id = 1
        self.email = "someone@example.com"
        self.role = role
        self.is_active = True


@pytest.mark.asyncio
async def test_admin_passes_the_gate():
    admin = FakeUser(UserRole.ADMIN)
    assert await require_admin(admin) is admin


@pytest.mark.asyncio
async def test_customer_is_refused():
    with pytest.raises(HTTPException) as exc:
        await require_admin(FakeUser(UserRole.CUSTOMER))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_refusal_is_404_not_403():
    """A customer probing admin routes should not learn they exist."""
    with pytest.raises(HTTPException) as exc:
        await require_admin(FakeUser(UserRole.CUSTOMER))
    assert exc.value.status_code == 404
    assert "admin" not in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_gate_compares_by_identity_not_truthiness():
    """A role-shaped object must not slip through on a string comparison."""

    class Sneaky:
        value = "ADMIN"

        def __eq__(self, other):  # pragma: no cover - defensive
            return True

        def __bool__(self):
            return True

    user = FakeUser(UserRole.CUSTOMER)
    user.role = Sneaky()  # type: ignore[assignment]
    with pytest.raises(HTTPException):
        await require_admin(user)


def test_emergency_stop_all_closes_nothing():
    """Section 81: stop new automated trades, do not delete positions.

    Asserted against the source so the guarantee cannot be lost in a later
    edit without this failing: the platform-wide stop must never reach the
    executor's closing helpers, unlike the per-user stop which does.
    """
    from pathlib import Path

    source = Path("app/routers/admin.py").read_text(encoding="utf-8")
    body = source.split("async def emergency_stop_all")[1]
    for forbidden in ("close_all", "close_position", "executor."):
        assert forbidden not in body, (
            f"platform-wide emergency stop must not call {forbidden!r}"
        )
    assert "emergency_stop = True" in body
    assert "bot_enabled = False" in body


def test_emergency_stop_all_is_audited():
    from pathlib import Path

    body = Path("app/routers/admin.py").read_text(encoding="utf-8").split(
        "async def emergency_stop_all"
    )[1]
    assert "AuditLog" in body
    assert "admin_emergency_stop_all" in body


def test_every_admin_route_requires_admin():
    """No route may be added to this router without the gate."""
    from app.routers import admin as admin_router

    for route in admin_router.router.routes:
        deps = [d.call for d in route.dependant.dependencies]
        assert require_admin in deps, f"{route.path} is not admin-gated"
