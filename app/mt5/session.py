"""Connection management for the MetaTrader 5 terminal.

The MetaTrader5 package talks to a single terminal over IPC using process-global
state, and it is not thread-safe. Every call therefore goes through one dedicated
worker thread (``ThreadPoolExecutor(max_workers=1)``) so the blocking terminal
calls are serialised and never block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
from typing import Any, Callable, TypeVar

from ..config import Settings
from ..errors import BridgeError, TerminalCallError, TerminalUnavailableError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# mt5.account_info().trade_mode
ACCOUNT_TRADE_MODE_DEMO = 0
ACCOUNT_TRADE_MODE_CONTEST = 1
ACCOUNT_TRADE_MODE_REAL = 2

# mt5.last_error() codes that mean the IPC link to the terminal is gone.
# RES_E_AUTH_FAILED (-6) plus the RES_E_INTERNAL_FAIL_* family (<= -10000).
CONNECTION_ERROR_CODES = frozenset({-6, -10000, -10001, -10002, -10003, -10004, -10005})

TRADE_MODE_NAMES = {
    ACCOUNT_TRADE_MODE_DEMO: "demo",
    ACCOUNT_TRADE_MODE_CONTEST: "contest",
    ACCOUNT_TRADE_MODE_REAL: "real",
}


def import_mt5() -> ModuleType:
    """Import the MetaTrader5 package, with a useful message when it is absent."""
    try:
        import MetaTrader5 as mt5  # noqa: N813  (upstream package name)
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise TerminalUnavailableError(
            "The MetaTrader5 package is not installed. It ships Windows-only "
            "wheels, so the bridge must run on the same Windows host as the "
            "MetaTrader 5 terminal.",
            details={"import_error": str(exc)},
        ) from exc
    return mt5


class MT5Session:
    """Owns the terminal connection and the single thread that talks to it."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")
        self._lock = asyncio.Lock()
        self._mt5: ModuleType | None = None
        self._connected = False
        self._account_login: int | None = None
        self._trade_mode: int | None = None

    # -- lifecycle -------------------------------------------------------------

    async def startup(self) -> None:
        if not self._settings.mt5_connect_on_startup:
            return
        try:
            await self.connect()
        except (TerminalUnavailableError, TerminalCallError) as exc:
            # Do not take the whole API down: /health/ready reports the problem
            # and the next request retries the connection.
            logger.warning("Deferred MT5 connection: %s", exc.message)

    async def shutdown(self) -> None:
        async with self._lock:
            if self._connected and self._mt5 is not None:
                mt5 = self._mt5
                await self._submit(mt5.shutdown)
            self._connected = False
        self._executor.shutdown(wait=True, cancel_futures=True)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def account_login(self) -> int | None:
        return self._account_login

    @property
    def trade_mode(self) -> int | None:
        return self._trade_mode

    @property
    def trade_mode_name(self) -> str | None:
        if self._trade_mode is None:
            return None
        return TRADE_MODE_NAMES.get(self._trade_mode, f"unknown({self._trade_mode})")

    @property
    def is_demo(self) -> bool:
        return self._trade_mode in (ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST)

    # -- call plumbing ---------------------------------------------------------

    async def _submit(self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, *args)

    async def run(self, fn: Callable[[ModuleType], T]) -> T:
        """Run ``fn(mt5)`` on the terminal thread, connecting first if needed."""
        await self.ensure_connected()
        mt5 = self._mt5
        assert mt5 is not None
        return await self._submit(fn, mt5)

    async def ensure_connected(self) -> None:
        if self._connected:
            return
        await self.connect()

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return

            mt5 = self._mt5 or import_mt5()
            self._mt5 = mt5
            settings = self._settings

            kwargs: dict[str, Any] = {"timeout": settings.mt5_timeout_ms}
            if settings.mt5_portable:
                kwargs["portable"] = True
            if settings.has_credentials:
                kwargs["login"] = int(settings.mt5_login)  # type: ignore[arg-type]
                kwargs["password"] = settings.mt5_password.get_secret_value()  # type: ignore[union-attr]
                kwargs["server"] = settings.mt5_server

            path = settings.mt5_terminal_path

            def _initialize(m: ModuleType) -> bool:
                if path:
                    return bool(m.initialize(path, **kwargs))
                return bool(m.initialize(**kwargs))

            ok = await self._submit(_initialize, mt5)
            if not ok:
                code, message = await self._submit(mt5.last_error)
                raise TerminalUnavailableError(
                    "Could not initialize the MetaTrader 5 terminal.",
                    details={"mt5_error_code": code, "mt5_error": message},
                )

            account = await self._submit(mt5.account_info)
            if account is None:
                code, message = await self._submit(mt5.last_error)
                await self._submit(mt5.shutdown)
                raise TerminalUnavailableError(
                    "Terminal initialized but no account is logged in.",
                    details={"mt5_error_code": code, "mt5_error": message},
                )

            self._account_login = int(account.login)
            self._trade_mode = int(account.trade_mode)
            self._connected = True
            logger.info(
                "Connected to MT5 account %s (%s) on %s",
                self._account_login,
                self.trade_mode_name,
                getattr(account, "server", "?"),
            )

    async def disconnect(self) -> None:
        """Drop the connection so the next call reconnects."""
        async with self._lock:
            if self._connected and self._mt5 is not None:
                try:
                    await self._submit(self._mt5.shutdown)
                except Exception:  # pragma: no cover - best effort teardown
                    logger.exception("MT5 shutdown failed")
            self._connected = False

    async def ping(self) -> bool:
        """Verify the terminal is still alive; marks the session dead if not."""
        if not self._connected:
            return False
        mt5 = self._mt5
        assert mt5 is not None
        info = await self._submit(mt5.terminal_info)
        if info is None:
            await self.disconnect()
            return False
        return True

    async def last_error(self) -> tuple[int, str]:
        mt5 = self._mt5
        if mt5 is None:
            return (0, "MetaTrader5 package not loaded")
        code, message = await self._submit(mt5.last_error)
        return int(code), str(message)

    async def fail(self, message: str, **details: Any) -> BridgeError:
        """Build the error for a failed MT5 call, annotated with mt5.last_error().

        Connection-level failures (the RES_E_INTERNAL_FAIL_* family, and a
        rejected login) also drop the session so the next request reconnects.
        """
        code, error = await self.last_error()
        payload = {"mt5_error_code": code, "mt5_error": error, **details}
        if code in CONNECTION_ERROR_CODES or code <= -10000:
            await self.disconnect()
            return TerminalUnavailableError(
                f"{message} The terminal connection was lost; it will be retried "
                "on the next request.",
                details=payload,
            )
        return TerminalCallError(message, details=payload)
