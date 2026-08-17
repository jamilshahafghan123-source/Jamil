"""HTTP client for the MT5 bridge.

This is the ONLY module in the backend that talks to the broker. It runs on
Cloud Run (Linux); the bridge runs on a Windows VM next to the MT5 terminal,
because the `MetaTrader5` Python package is a Windows-only wrapper around the
terminal's local IPC and cannot run in a Linux container.

Broker credentials live on the Windows VM and in Secret Manager. They are
never sent to, stored by, or rendered by the frontend.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger("mt5_client")


class BridgeError(RuntimeError):
    """The bridge was unreachable, unauthorized, or returned an error."""


class MT5Client:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.MT5_BRIDGE_URL.rstrip("/"),
            timeout=settings.MT5_BRIDGE_TIMEOUT,
            headers={"X-Bridge-Token": settings.MT5_BRIDGE_TOKEN},
        )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _req(self, method: str, path: str, **kw: Any) -> Any:
        if self._client is None:
            raise BridgeError("MT5 client not started")
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise BridgeError(f"bridge unreachable: {e}") from e
        if r.status_code == 401:
            raise BridgeError("bridge rejected token (check MT5_BRIDGE_TOKEN)")
        if r.status_code >= 400:
            raise BridgeError(f"bridge {r.status_code}: {r.text[:300]}")
        return r.json()

    # ------------------------------------------------------------ reads

    async def health(self) -> dict:
        return await self._req("GET", "/health")

    async def connected(self) -> bool:
        try:
            h = await self.health()
            return bool(h.get("mt5_connected"))
        except BridgeError:
            return False

    async def account(self) -> dict:
        return await self._req("GET", "/account")

    async def tick(self, symbol: str) -> dict:
        return await self._req("GET", "/tick", params={"symbol": symbol})

    async def symbol_info(self, symbol: str) -> dict:
        """Contract size, tick value/size, volume min/max/step, stops level."""
        return await self._req("GET", "/symbol", params={"symbol": symbol})

    async def bars(self, symbol: str, timeframe: str, count: int) -> list[dict]:
        data = await self._req(
            "GET",
            "/bars",
            params={"symbol": symbol, "timeframe": timeframe, "count": count},
        )
        return data.get("bars", [])

    async def positions(self, symbol: str | None = None) -> list[dict]:
        params = {"symbol": symbol} if symbol else {}
        data = await self._req("GET", "/positions", params=params)
        return data.get("positions", [])

    async def history(self, days: int = 7) -> list[dict]:
        data = await self._req("GET", "/history", params={"days": days})
        return data.get("deals", [])

    # ----------------------------------------------------------- writes
    # Nothing here may be called except from services/executor.py, which
    # runs the risk engine first. See the executor for that invariant.

    async def market_order(
        self,
        *,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: float | None,
        take_profit: float | None,
        comment: str = "",
        deviation: int = 20,
    ) -> dict:
        payload = {
            "symbol": symbol,
            "side": side,
            "volume": round(volume, 2),
            "sl": stop_loss,
            "tp": take_profit,
            "comment": comment[:31],  # MT5 truncates past 31 chars
            "deviation": deviation,
        }
        return await self._req("POST", "/order", json=payload)

    async def close_position(self, ticket: int, deviation: int = 20) -> dict:
        return await self._req(
            "POST", "/close", json={"ticket": ticket, "deviation": deviation}
        )


mt5 = MT5Client()


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
