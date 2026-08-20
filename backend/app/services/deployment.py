"""Deployment readiness (section 5) and version tracking (section 4).

Reports READY or NOT_READY with reasons. It runs *checks*; it does not
deploy, roll back, or run git. Rollback targets, when that is built, must
come from a validated registry — this module deliberately offers no way to
name an arbitrary commit, because "let the automation pick a commit" is how
a rollback becomes an outage.

Version is read from the environment (APP_VERSION / GIT_COMMIT), which a
build pipeline sets. Nothing here shells out to git.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..config import settings
from .secrets import SECRET_SETTINGS


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    blocking: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict:
        return {
            "status": "READY" if self.ready else "NOT_READY",
            "blocking": list(self.blocking),
            "warnings": list(self.warnings),
        }


def version_info() -> dict:
    """What is running. Set by the build; never derived by running git."""
    return {
        "version": os.environ.get("APP_VERSION") or "unknown",
        "commit": (os.environ.get("GIT_COMMIT") or "unknown")[:12],
        "last_known_good": os.environ.get("LAST_KNOWN_GOOD_VERSION") or "unknown",
        "environment": settings.ENV,
    }


def evaluate(
    *,
    database_reachable: bool,
    backup_present: bool,
    tests_passed: bool | None = None,
    frontend_built: bool | None = None,
    real_trading_approved: bool = False,
) -> Readiness:
    """Decide whether this build is safe to ship.

    Unknown is not the same as passing: a check whose result was not
    supplied becomes a warning, never a silent success.
    """
    blocking: list[str] = []
    warnings: list[str] = []

    # The one that matters most: real money must never ship on by accident.
    if settings.ALLOW_REAL_TRADING and not real_trading_approved:
        blocking.append(
            "ALLOW_REAL_TRADING is enabled but has not been explicitly approved "
            "for this deployment."
        )

    if not database_reachable:
        blocking.append("The database is not reachable.")
    if not backup_present:
        blocking.append("No verified backup exists to roll back to.")

    missing = [
        name
        for name in ("JWT_SECRET", "DATABASE_URL", "MT5_BRIDGE_TOKEN")
        if not getattr(settings, name, None)
    ]
    if missing:
        # Names only. Never values, not even truncated.
        blocking.append(f"Required settings are missing: {', '.join(missing)}")

    if settings.ENV == "prod":
        if "*" in settings.CORS_ORIGINS:
            blocking.append("CORS is set to '*' in production.")
        for name in SECRET_SETTINGS:
            value = getattr(settings, name, None)
            if isinstance(value, str) and value.lower().startswith("change_me"):
                blocking.append(f"{name} still holds a placeholder value.")

    if tests_passed is False:
        blocking.append("The backend test suite is failing.")
    elif tests_passed is None:
        warnings.append("Backend test result was not supplied to this check.")

    if frontend_built is False:
        blocking.append("The frontend build is failing.")
    elif frontend_built is None:
        warnings.append("Frontend build result was not supplied to this check.")

    return Readiness(not blocking, tuple(blocking), tuple(warnings))
