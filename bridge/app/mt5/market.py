"""Market-data operations: symbols, candles and ticks."""

from __future__ import annotations

from datetime import datetime
from types import ModuleType
from typing import Any

from ..errors import InvalidRequestError, SymbolNotFoundError
from .convert import naive_utc, rate_to_candle, to_dict
from .session import MT5Session

# Ceiling on a single candle request, so one call cannot pin the terminal thread.
MAX_CANDLES = 20_000


def resolve_timeframe(mt5: ModuleType, name: str) -> int:
    """Map ``"M15"`` to ``mt5.TIMEFRAME_M15`` (resolved from the package, not hard-coded)."""
    constant = getattr(mt5, f"TIMEFRAME_{name.upper()}", None)
    if constant is None:
        raise InvalidRequestError(f"Unsupported timeframe: {name}")
    return int(constant)


async def ensure_symbol(session: MT5Session, symbol: str) -> dict[str, Any]:
    """Look the symbol up and add it to Market Watch if the terminal hides it."""

    def _select(mt5: ModuleType) -> Any:
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                return None
            info = mt5.symbol_info(symbol)
        return info

    info = await session.run(_select)
    if info is None:
        raise SymbolNotFoundError(
            f"Symbol '{symbol}' is not available on this account.",
            details={"symbol": symbol},
        )
    return to_dict(info)


async def list_symbols(
    session: MT5Session, *, search: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    def _get(mt5: ModuleType) -> Any:
        # MT5's group filter uses '*' wildcards, e.g. "*EUR*".
        if search:
            return mt5.symbols_get(group=f"*{search}*")
        return mt5.symbols_get()

    symbols = await session.run(_get)
    if symbols is None:
        raise await session.fail("Could not list symbols.")

    return [
        {
            "name": s.name,
            "description": getattr(s, "description", ""),
            "path": getattr(s, "path", ""),
            "digits": int(s.digits),
            "point": float(s.point),
            "spread": int(getattr(s, "spread", 0)),
            "trade_mode": int(getattr(s, "trade_mode", 0)),
            "volume_min": float(getattr(s, "volume_min", 0.0)),
            "volume_max": float(getattr(s, "volume_max", 0.0)),
            "volume_step": float(getattr(s, "volume_step", 0.0)),
            "visible": bool(getattr(s, "visible", False)),
        }
        for s in symbols[:limit]
    ]


async def get_tick(session: MT5Session, symbol: str) -> dict[str, Any]:
    await ensure_symbol(session, symbol)
    tick = await session.run(lambda mt5: mt5.symbol_info_tick(symbol))
    if tick is None:
        raise await session.fail(f"No tick available for '{symbol}'.", symbol=symbol)
    data = to_dict(tick)
    data["symbol"] = symbol
    return data


async def get_candles(
    session: MT5Session,
    *,
    symbol: str,
    timeframe: str,
    count: int = 500,
    start: datetime | None = None,
    end: datetime | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch OHLC candles.

    Three query shapes, mirroring the three ``copy_rates_*`` calls:
      * ``start`` + ``end``  -> every candle inside the range
      * ``start`` + ``count``-> ``count`` candles starting at ``start``
      * ``count`` (+ ``offset``) -> the most recent candles, newest last
    """
    if count > MAX_CANDLES:
        raise InvalidRequestError(
            f"count must be <= {MAX_CANDLES}.", details={"count": count}
        )
    if start and end and end <= start:
        raise InvalidRequestError("'end' must be later than 'start'.")

    await ensure_symbol(session, symbol)

    def _fetch(mt5: ModuleType) -> Any:
        tf = resolve_timeframe(mt5, timeframe)
        if start and end:
            return mt5.copy_rates_range(symbol, tf, naive_utc(start), naive_utc(end))
        if start:
            return mt5.copy_rates_from(symbol, tf, naive_utc(start), count)
        return mt5.copy_rates_from_pos(symbol, tf, offset, count)

    rates = await session.run(_fetch)
    if rates is None:
        raise await session.fail(
            f"Could not load candles for '{symbol}'.",
            symbol=symbol,
            timeframe=timeframe,
        )
    return [rate_to_candle(row) for row in rates]
