"""Client for the Windows-side recovery agent.

The agent is a small trusted service running next to MT5 and Docker on the
Windows host. This module is the only thing that talks to it.

WHAT THE WIRE LOOKS LIKE
------------------------
One fixed endpoint per operation, resolved through a lookup table. There is
no path built by concatenation and no body carrying a command, so a caller
cannot steer the request anywhere the table does not already go. The agent
is expected to expose exactly these paths and nothing resembling an exec.

AUTHENTICATION
--------------
A dedicated secret, WINDOWS_AGENT_TOKEN, separate from MT5_BRIDGE_TOKEN so
that neither one's compromise or rotation touches the other. It is read
from the environment, never logged, never returned by any endpoint, and
never sent to the frontend. A 401 or 403 is surfaced as `auth_failure`
rather than a generic error, because the two demand opposite responses:
a failed operation may be retried, whereas bad credentials must stop and
ask a human — section 4 forbids guessing, rewriting or copying secrets.

NOT CONFIGURED IS NOT BROKEN
----------------------------
With no URL or token set, every call returns `unavailable`. That reports
honestly as UNKNOWN rather than DOWN, and — this is the point — means a
deployment with no Windows agent behaves exactly as it does today instead
of filling the incident log with failures about a machine that was never
supposed to exist.
"""

from __future__ import annotations

import logging

import httpx

from ...config import settings
from .operations import Operation, OperationResult

log = logging.getLogger(__name__)

#: Fixed endpoint per operation. A lookup, never a format string.
_PATHS: dict[Operation, tuple[str, str]] = {
    Operation.CHECK_MT5: ("GET", "/check/mt5"),
    Operation.CHECK_BRIDGE: ("GET", "/check/bridge"),
    Operation.CHECK_PORT_8100: ("GET", "/check/port-8100"),
    Operation.CHECK_DOCKER: ("GET", "/check/docker"),
    Operation.CHECK_BACKEND: ("GET", "/check/backend"),
    Operation.CHECK_FRONTEND: ("GET", "/check/frontend"),
    Operation.CHECK_DATABASE: ("GET", "/check/database"),
    Operation.RESTART_BRIDGE: ("POST", "/restart/bridge"),
    Operation.RESTART_BACKEND: ("POST", "/restart/backend"),
    Operation.RESTART_FRONTEND: ("POST", "/restart/frontend"),
    Operation.RESTART_DATABASE: ("POST", "/restart/database"),
    Operation.START_MT5: ("POST", "/start/mt5"),
    Operation.VERIFY_HEALTH: ("GET", "/verify/health"),
}

assert set(_PATHS) == set(Operation), "every operation needs exactly one path"


class WindowsAgent:
    """Typed client. Every public method takes an Operation, never a string."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._base = (base_url if base_url is not None
                      else getattr(settings, "WINDOWS_AGENT_URL", None) or "")
        self._token = (token if token is not None
                       else getattr(settings, "WINDOWS_AGENT_TOKEN", None) or "")
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._base and self._token)

    async def run(self, operation: Operation) -> OperationResult:
        """Perform one allow-listed operation."""
        if not self.configured:
            return OperationResult(
                operation, ok=False, unavailable=True,
                detail="No Windows recovery agent is configured.",
            )

        method, path = _PATHS[operation]
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.request(
                    method,
                    f"{self._base.rstrip('/')}{path}",
                    headers={"X-Agent-Token": self._token},
                )
        except Exception as exc:  # noqa: BLE001 - unreachable host is a result
            # The message is logged without the token, which is only ever in
            # the header and never in the URL.
            log.warning("windows agent unreachable for %s: %s",
                        operation.value, type(exc).__name__)
            return OperationResult(
                operation, ok=False,
                detail="The Windows recovery agent could not be reached.",
            )

        if res.status_code in (401, 403):
            log.error("windows agent rejected our credentials for %s",
                      operation.value)
            return OperationResult(
                operation, ok=False, auth_failure=True,
                detail=("The Windows recovery agent rejected the configured "
                        "credentials. Verification is required."),
            )

        if res.status_code >= 400:
            return OperationResult(
                operation, ok=False,
                detail=f"The agent reported failure (HTTP {res.status_code}).",
            )

        detail = ""
        try:
            body = res.json()
            if isinstance(body, dict):
                # Only a known key is read back, so an agent that returned
                # something unexpected cannot inject it into our records.
                detail = str(body.get("detail", ""))[:500]
        except Exception:  # noqa: BLE001 - a non-JSON 200 is still a success
            detail = ""

        return OperationResult(operation, ok=True, detail=detail)


#: Module-level instance, mirroring how mt5_client exposes `mt5`.
agent = WindowsAgent()
