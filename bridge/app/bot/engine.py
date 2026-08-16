"""The autonomous trading loop.

    signal pipeline -> risk manager -> order_check() -> order_send() -> MT5

The bot owns no trading logic of its own. It decides *when* to look, asks the
pipeline what it sees, and hands any proposal to the same `place_order` path a
human uses — so every order it sends passes the identical risk policy,
pre-flight and demo-account guard.

Two independent gates, both on the safe side by default:

* ``BOT_ENABLED``  - false means /bot/start refuses outright.
* ``BOT_DRY_RUN``  - true means a running bot records what it would have done
  and sends nothing. This is the default even when the bot is enabled.

Everything it does is recorded in `status()`, including the decisions it chose
not to act on, so a run can be audited after the fact.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from ..analysis import signal as signal_pipeline
from ..config import Settings
from ..errors import BridgeError, InvalidRequestError, TradingNotAllowedError
from ..mt5 import risk, trading
from ..mt5.session import MT5Session
from ..schemas import OrderRequest

logger = logging.getLogger(__name__)

# Keep the tail of what happened; this is a status endpoint, not a database.
HISTORY_LIMIT = 50


class BotNotAllowedError(TradingNotAllowedError):
    """The bot cannot start: disabled by config, or already running."""

    error_code = "bot_not_allowed"


class TradingBot:
    """One loop per process. Start, stop, and ask what it has been doing."""

    def __init__(self, session: MT5Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

        self._symbol = ""
        self._timeframe = ""
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._last_evaluated_at: datetime | None = None
        self._last_bar: str | None = None
        self._last_decision: dict[str, Any] | None = None
        self._trades: deque[dict[str, Any]] = deque(maxlen=HISTORY_LIMIT)
        self._events: deque[dict[str, Any]] = deque(maxlen=HISTORY_LIMIT)

    # -- configuration ---------------------------------------------------------

    def _default_symbol(self) -> str:
        if self._settings.bot_symbol.strip():
            return self._settings.bot_symbol.strip().upper()
        allowed = self._settings.allowed_symbol_list
        if allowed:
            return allowed[0]
        raise InvalidRequestError(
            "No symbol to trade: set BOT_SYMBOL or RISK_ALLOWED_SYMBOLS."
        )

    def _default_timeframe(self) -> str:
        return (self._settings.bot_timeframe or self._settings.signal_timeframe).upper()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # -- lifecycle -------------------------------------------------------------

    async def start(
        self, *, symbol: str | None = None, timeframe: str | None = None
    ) -> dict[str, Any]:
        if not self._settings.bot_enabled:
            raise BotNotAllowedError(
                "The bot is disabled on this bridge (BOT_ENABLED is not true).",
                details={"bot_enabled": False},
            )
        if self.running:
            raise BotNotAllowedError(
                "The bot is already running. Stop it before starting a new run.",
                details=self.status(),
            )

        # Refuse to start on an account the bridge would not let us trade anyway.
        await trading.assert_trading_allowed(self._session, self._settings)

        self._symbol = (symbol or self._default_symbol()).upper()
        self._timeframe = (timeframe or self._default_timeframe()).upper()
        self._stopping.clear()
        self._started_at = datetime.now(tz=timezone.utc)
        self._stopped_at = None
        self._last_bar = None
        self._task = asyncio.create_task(self._run(), name="mt5-trading-bot")

        self._record_event(
            "started",
            f"Watching {self._symbol} {self._timeframe} in "
            f"{'dry-run' if self._settings.bot_dry_run else 'LIVE'} mode.",
        )
        logger.info(
            "Bot started: %s %s mode=%s dry_run=%s",
            self._symbol,
            self._timeframe,
            self._settings.bot_mode,
            self._settings.bot_dry_run,
        )
        return self.status()

    async def stop(self) -> dict[str, Any]:
        """Idempotent: stopping a stopped bot is a no-op, not an error."""
        if not self.running:
            self._stopped_at = self._stopped_at or datetime.now(tz=timezone.utc)
            return self.status()

        self._stopping.set()
        task = self._task
        assert task is not None
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - teardown
            pass
        self._task = None
        self._stopped_at = datetime.now(tz=timezone.utc)
        self._record_event("stopped", "Stopped by request.")
        logger.info("Bot stopped")
        return self.status()

    # -- the loop --------------------------------------------------------------

    async def _run(self) -> None:
        try:
            while not self._stopping.is_set():
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except BridgeError as error:
                    # A bad tick must not kill the loop: log it, keep watching.
                    self._record_event("error", error.message)
                    logger.warning("Bot iteration failed: %s", error.message)
                except Exception as error:  # noqa: BLE001 - last line of defence
                    self._record_event("error", f"Unexpected: {error}")
                    logger.exception("Bot iteration crashed")

                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._settings.bot_poll_seconds
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass

    async def _tick(self) -> None:
        result = await signal_pipeline.generate(
            self._session,
            self._settings,
            symbol=self._symbol,
            timeframe=self._timeframe,
        )
        self._last_evaluated_at = datetime.now(tz=timezone.utc)

        bar = str(result.get("as_of"))
        if self._settings.bot_mode == "bar":
            # One decision per closed candle: the forming bar's timestamp only
            # changes when the previous one closed.
            if bar == self._last_bar:
                return
            first_look = self._last_bar is None
            self._last_bar = bar
            if first_look:
                # Do not act on a bar that was already forming when we started;
                # wait for one to close under our watch.
                self._record_event(
                    "waiting", f"Watching from bar {bar}; first decision on the next close."
                )
                return

        self._last_decision = {
            "at": self._last_evaluated_at,
            "bar": bar,
            "decision": result["decision"],
            "confidence": result["confidence"],
            "reason": (result["reasons"] or [""])[0],
        }

        if result["decision"] != "trade" or not result.get("proposal"):
            self._record_event(
                "no_trade",
                f"{result['confidence']}% — {(result['reasons'] or ['no setup'])[0]}",
            )
            return

        await self._act(result)

    async def _act(self, result: dict[str, Any]) -> None:
        traded_today = self._trades_today()
        if (
            self._settings.bot_max_trades_per_day
            and traded_today >= self._settings.bot_max_trades_per_day
        ):
            self._record_event(
                "capped",
                f"Daily trade cap reached ({traded_today}/"
                f"{self._settings.bot_max_trades_per_day}); standing down.",
            )
            return

        proposal = dict(result["proposal"])

        if self._settings.bot_dry_run:
            self._record_trade(result, executed=False, detail="dry run — not sent")
            return

        order = OrderRequest(**proposal)
        try:
            sent = await trading.place_order(self._session, self._settings, order)
        except BridgeError as error:
            # A rejection is a normal outcome, not a loop failure.
            self._record_event("rejected", f"{error.error_code}: {error.message}")
            return

        self._record_trade(
            result,
            executed=True,
            detail=f"retcode {sent['retcode']} — {sent['retcode_description']}",
            order=sent.get("order"),
            deal=sent.get("deal"),
        )
        logger.info(
            "Bot placed %s %s %s (order %s)",
            proposal["side"],
            proposal["volume"],
            proposal["symbol"],
            sent.get("order"),
        )

    # -- bookkeeping -----------------------------------------------------------

    def _trades_today(self) -> int:
        start = risk.day_start()
        return sum(1 for trade in self._trades if trade["at"] >= start and trade["executed"])

    def _record_trade(
        self,
        result: dict[str, Any],
        *,
        executed: bool,
        detail: str,
        order: int | None = None,
        deal: int | None = None,
    ) -> None:
        proposal = result["proposal"]
        entry = {
            "at": datetime.now(tz=timezone.utc),
            "bar": str(result.get("as_of")),
            "symbol": proposal["symbol"],
            "side": proposal["side"],
            "volume": proposal["volume"],
            "sl": proposal["sl"],
            "tp": proposal["tp"],
            "confidence": result["confidence"],
            "executed": executed,
            "detail": detail,
            "order": order,
            "deal": deal,
        }
        self._trades.appendleft(entry)
        self._record_event(
            "trade" if executed else "would_trade",
            f"{proposal['side']} {proposal['volume']} {proposal['symbol']} "
            f"@ {result['confidence']}% — {detail}",
        )

    def _record_event(self, kind: str, message: str) -> None:
        self._events.appendleft(
            {"at": datetime.now(tz=timezone.utc), "kind": kind, "message": message}
        )

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "enabled": self._settings.bot_enabled,
            "dry_run": self._settings.bot_dry_run,
            "mode": self._settings.bot_mode,
            "poll_seconds": self._settings.bot_poll_seconds,
            "symbol": self._symbol or None,
            "timeframe": self._timeframe or None,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "last_evaluated_at": self._last_evaluated_at,
            "last_bar": self._last_bar,
            "last_decision": self._last_decision,
            "trades_today": self._trades_today(),
            "max_trades_per_day": self._settings.bot_max_trades_per_day,
            "trades": list(self._trades)[:10],
            "events": list(self._events)[:10],
        }
