"""Helpers that turn MetaTrader5 return values into plain JSON-able Python."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def to_dict(value: Any) -> dict[str, Any]:
    """MT5 returns namedtuple-like objects; ``_asdict`` is the documented escape hatch."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    as_dict = getattr(value, "_asdict", None)
    if callable(as_dict):
        return {key: _scalar(val) for key, val in as_dict().items()}
    return {
        key: _scalar(getattr(value, key))
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }


def _scalar(value: Any) -> Any:
    """Unwrap numpy scalars so pydantic/JSON see native types."""
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (bytes, str)):
        try:
            return item()
        except (ValueError, TypeError):  # pragma: no cover - defensive
            return value
    return value


def utc(epoch_seconds: Any) -> datetime:
    """MT5 timestamps are epoch seconds in the broker's server timezone."""
    return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc)


def naive_utc(value: datetime) -> datetime:
    """MT5 interprets naive datetimes as UTC, so normalise before passing them in."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def rate_to_candle(row: Any) -> dict[str, Any]:
    """Convert one row of ``copy_rates_*`` (a numpy void) into a dict."""
    return {
        "time": utc(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "tick_volume": int(row["tick_volume"]),
        "spread": int(row["spread"]),
        "real_volume": int(row["real_volume"]),
    }
