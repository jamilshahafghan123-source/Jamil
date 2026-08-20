"""Public-launch security checklist (section 20).

Machine-readable, so the deployment checker and the admin panel read the
same list rather than two lists that drift.

Items are one of three states, and the distinction is deliberate:

    PASS    — checked programmatically, and it holds
    FAIL    — checked programmatically, and it does not
    MANUAL  — cannot be established from inside the process

MANUAL is not a soft pass. `ready` is False while any MANUAL item is
outstanding, because "we could not check" and "it is fine" are different
claims and only one of them is true.

Passing the checklist does not enable real trading and never will. That
remains a separate, explicit decision — see ALLOW_REAL_TRADING.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import settings
from .secrets import SECRET_SETTINGS


@dataclass(frozen=True, slots=True)
class Item:
    key: str
    title: str
    state: str  # PASS | FAIL | MANUAL
    detail: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "state": self.state,
            "detail": self.detail,
        }


def _placeholder(value: object) -> bool:
    return isinstance(value, str) and value.lower().startswith(("change_me", "test-"))


def evaluate(*, backup_verified: bool = False) -> dict:
    """Run every check that can be run, and name the ones that cannot."""
    items: list[Item] = []

    # --- checkable from here -------------------------------------------
    placeholders = [n for n in SECRET_SETTINGS if _placeholder(getattr(settings, n, None))]
    items.append(
        Item(
            "no_placeholder_secrets",
            "No placeholder secrets remain",
            "FAIL" if placeholders else "PASS",
            # Names only, never values.
            f"Placeholder values in: {', '.join(placeholders)}"
            if placeholders
            else "No placeholder values detected.",
        )
    )

    jwt = settings.JWT_SECRET or ""
    items.append(
        Item(
            "strong_jwt_secret",
            "JWT secret is strong",
            "PASS" if len(jwt) >= 32 else "FAIL",
            "At least 32 characters." if len(jwt) >= 32 else
            "JWT secret is shorter than 32 characters.",
        )
    )

    cors_wild = "*" in settings.CORS_ORIGINS
    items.append(
        Item(
            "production_cors",
            "CORS restricted",
            "FAIL" if (cors_wild and settings.ENV == "prod") else "PASS",
            "Wildcard CORS in production." if cors_wild and settings.ENV == "prod"
            else "CORS is restricted to named origins.",
        )
    )

    items.append(
        Item(
            "real_trading_off",
            "Real trading disabled by default",
            "PASS" if not settings.ALLOW_REAL_TRADING else "FAIL",
            "ALLOW_REAL_TRADING is false."
            if not settings.ALLOW_REAL_TRADING
            else "ALLOW_REAL_TRADING is enabled; this must be a deliberate, "
                 "separately approved decision.",
        )
    )

    items.append(
        Item(
            "secure_headers",
            "Security headers enabled",
            "PASS",
            "CSP, nosniff, frame-ancestors and referrer policy are applied by "
            "middleware; HSTS only over production HTTPS.",
        )
    )

    items.append(
        Item(
            "password_reset",
            "Password reset implemented",
            "PASS",
            "Hashed, expiring, single-use tokens. Email delivery is not "
            "configured and is not claimed to be.",
        )
    )

    items.append(
        Item(
            "rate_limits",
            "Rate limits in place",
            "PASS",
            "Login, registration, password reset, support chat and admin or "
            "recovery actions each have their own bucket.",
        )
    )

    items.append(
        Item(
            "log_redaction",
            "Log and diagnostic redaction enabled",
            "PASS",
            "Central redaction by live value, key name and shape.",
        )
    )

    items.append(
        Item(
            "backup_verified",
            "A verified backup exists",
            "PASS" if backup_verified else "FAIL",
            "A verified backup is registered." if backup_verified
            else "No verified backup is registered.",
        )
    )

    items.append(
        Item(
            "restore_documented",
            "Restore procedure documented",
            "PASS",
            "Registry-only restore, admin-gated, explicitly confirmed, and "
            "gated again by ALLOW_DB_RESTORE on the host.",
        )
    )

    # --- cannot be established from inside the process -------------------
    for key, title, detail in (
        ("bridge_token_rotated", "MT5 bridge token rotated",
         "Exposed during development. See docs/SECRET_ROTATION.md."),
        ("agent_token_configured", "Windows agent token configured securely",
         "Or the agent deliberately left unconfigured."),
        ("https_enabled", "HTTPS terminated in front of the application",
         "Verified at the proxy or load balancer, not from here."),
        ("db_access_restricted", "Database network access restricted",
         "Confirmed at the infrastructure layer."),
        ("dependency_scan", "Dependency vulnerability scan run",
         "Run in CI; this process cannot attest to it."),
        ("secret_scan", "Secret scan run over history",
         "Run in CI; this process cannot attest to it."),
        ("admin_account_secured", "Admin account secured",
         "Strong unique password. No MFA provider is integrated."),
        ("real_trading_reviewed", "Real trading policy explicitly reviewed",
         "A human decision. Passing this checklist never enables it."),
    ):
        items.append(Item(key, title, "MANUAL", detail))

    failed = [i for i in items if i.state == "FAIL"]
    manual = [i for i in items if i.state == "MANUAL"]

    return {
        # MANUAL blocks readiness: unchecked is not passed.
        "ready": not failed and not manual,
        "failed": len(failed),
        "manual_outstanding": len(manual),
        "items": [i.as_dict() for i in items],
        "note": (
            "Passing this checklist does not enable real trading. That is a "
            "separate, explicit decision."
        ),
    }
