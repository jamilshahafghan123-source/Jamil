"""Secret handling: redaction, and reporting configuration without values.

Two jobs, both about the same rule — a secret's *value* leaves the process
only as an outbound credential, never as output.

`redact` is defensive depth rather than the primary control. The primary
control is that no response model, projection or diagnostic carries a
secret field in the first place. This exists for the paths where a value
might arrive inside free text anyway: an exception message, a subprocess
error, a bridge response.

`configuration_status` answers "is it set?" and never "what is it?", which
is the only question an operator dashboard needs.
"""

from __future__ import annotations

import re

from ..config import settings

REDACTED = "[REDACTED]"

#: Settings that must never be rendered, logged or returned.
SECRET_SETTINGS: tuple[str, ...] = (
    "JWT_SECRET",
    "MT5_BRIDGE_TOKEN",
    "WINDOWS_AGENT_TOKEN",
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
    "BOOTSTRAP_PASSWORD",
)

#: Key names whose values are stripped from any mapping passed through.
_SENSITIVE_KEY = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|credential|authorization|cookie|dsn)",
    re.IGNORECASE,
)

#: Shapes worth scrubbing out of free text even when no key names it.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # postgres://user:password@host/db and friends
    re.compile(r"(?i)\b[a-z0-9+]+://[^\s:/@]+:[^\s@]+@[^\s]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)\b(sk|pk|rk)-[A-Za-z0-9]{16,}"),
    # long hex, the shape of the tokens this project generates
    re.compile(r"\b[0-9a-f]{32,}\b"),
)


def _live_secret_values() -> tuple[str, ...]:
    values = []
    for name in SECRET_SETTINGS:
        value = getattr(settings, name, None)
        if isinstance(value, str) and len(value) >= 8:
            values.append(value)
    return tuple(values)


def redact(text: object) -> str:
    """Scrub anything secret-shaped, and any live secret, out of text."""
    out = str(text)
    # Exact configured values first: the surest match available.
    for value in _live_secret_values():
        if value in out:
            out = out.replace(value, REDACTED)
    for pattern in _PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def redact_mapping(data: object) -> object:
    """Recursively redact a structure by key name and by value shape."""
    if isinstance(data, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and _SENSITIVE_KEY.search(key)
                else redact_mapping(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [redact_mapping(item) for item in data]
    if isinstance(data, str):
        return redact(data)
    return data


def configuration_status() -> dict[str, str]:
    """SET or MISSING per secret. Never a value, never a length, never a hint."""
    status = {}
    for name in SECRET_SETTINGS:
        value = getattr(settings, name, None)
        status[name] = "SET" if value else "MISSING"
    return status
