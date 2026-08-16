"""Trading operations: orders, positions and history."""

from __future__ import annotations

import logging
from datetime import datetime
from types import ModuleType
from typing import Any

from ..config import Settings
from ..errors import (
    InvalidRequestError,
    NotFoundError,
    TradeRejectedError,
    TradingNotAllowedError,
)
from .convert import naive_utc, to_dict, utc
from .market import ensure_symbol
from .session import MT5Session

logger = logging.getLogger(__name__)

TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010
TRADE_RETCODE_PLACED = 10008
SUCCESS_RETCODES = frozenset({TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL, TRADE_RETCODE_PLACED})

RETCODE_DESCRIPTIONS = {
    10004: "Requote",
    10006: "Request rejected",
    10007: "Request cancelled by trader",
    10008: "Order placed",
    10009: "Request completed",
    10010: "Only part of the request was completed",
    10011: "Request processing error",
    10012: "Request cancelled by timeout",
    10013: "Invalid request",
    10014: "Invalid volume in the request",
    10015: "Invalid price in the request",
    10016: "Invalid stops in the request",
    10017: "Trade is disabled",
    10018: "Market is closed",
    10019: "Not enough money to complete the request",
    10020: "Prices changed",
    10021: "No quotes to process the request",
    10022: "Invalid order expiration date",
    10023: "Order state changed",
    10024: "Too frequent requests",
    10025: "No changes in request",
    10026: "Autotrading disabled by server",
    10027: "Autotrading disabled by client terminal",
    10028: "Request locked for processing",
    10029: "Order or position frozen",
    10030: "Invalid order filling type",
    10031: "No connection with the trade server",
    10032: "Operation allowed only for live accounts",
    10033: "Pending orders limit reached",
    10034: "Volume limit for this symbol reached",
    10035: "Incorrect or prohibited order type",
    10036: "Position with the specified id has already been closed",
    10038: "Close volume exceeds the current position volume",
    10039: "A close order already exists for this position",
    10040: "Number of open positions limit reached",
    10041: "Pending order activation rejected, order cancelled",
    10042: "Rejected: 'Only long positions are allowed' is set",
    10043: "Rejected: 'Only short positions are allowed' is set",
    10044: "Rejected: 'Only position closing is allowed' is set",
    10045: "Rejected: position closing is allowed by FIFO rule only",
    10046: "Rejected: opposite positions on a single symbol are disabled",
}

# side + order kind -> MetaTrader5 constant name
_ORDER_TYPE_NAMES = {
    ("buy", "market"): "ORDER_TYPE_BUY",
    ("sell", "market"): "ORDER_TYPE_SELL",
    ("buy", "limit"): "ORDER_TYPE_BUY_LIMIT",
    ("sell", "limit"): "ORDER_TYPE_SELL_LIMIT",
    ("buy", "stop"): "ORDER_TYPE_BUY_STOP",
    ("sell", "stop"): "ORDER_TYPE_SELL_STOP",
    ("buy", "stop_limit"): "ORDER_TYPE_BUY_STOP_LIMIT",
    ("sell", "stop_limit"): "ORDER_TYPE_SELL_STOP_LIMIT",
}

POSITION_SIDE = {0: "buy", 1: "sell"}

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2


def describe_retcode(retcode: int) -> str:
    return RETCODE_DESCRIPTIONS.get(int(retcode), f"Unknown retcode {retcode}")


# --- guard rails -------------------------------------------------------------


async def assert_trading_allowed(
    session: MT5Session, settings: Settings, *, volume: float | None = None
) -> None:
    """Demo-account guard, terminal AutoTrading check and volume cap."""
    if not session.is_demo and not settings.allow_live_trading:
        raise TradingNotAllowedError(
            "Refusing to trade: the connected account is not a demo account. "
            "Set ALLOW_LIVE_TRADING=true to override.",
            details={"account_trade_mode": session.trade_mode_name},
        )

    if volume is not None and volume > settings.max_volume:
        raise TradingNotAllowedError(
            f"Volume {volume} exceeds the configured MAX_VOLUME of {settings.max_volume}.",
            details={"volume": volume, "max_volume": settings.max_volume},
        )

    terminal = await session.run(lambda mt5: mt5.terminal_info())
    if terminal is not None and not getattr(terminal, "trade_allowed", True):
        raise TradingNotAllowedError(
            "AutoTrading is disabled in the MetaTrader 5 terminal "
            "(enable the AutoTrading button / Tools > Options > Expert Advisors)."
        )


# --- account ------------------------------------------------------------------


async def get_account(session: MT5Session) -> dict[str, Any]:
    info = await session.run(lambda mt5: mt5.account_info())
    if info is None:
        raise await session.fail("Could not read account info.")
    data = to_dict(info)
    data["trade_mode_name"] = session.trade_mode_name
    data["is_demo"] = session.is_demo
    return data


# --- normalisation ------------------------------------------------------------


def normalize_volume(volume: float, symbol_info: dict[str, Any]) -> float:
    step = float(symbol_info.get("volume_step") or 0.01)
    minimum = float(symbol_info.get("volume_min") or step)
    maximum = float(symbol_info.get("volume_max") or 0.0)

    # Snap to the broker's lot step; float inputs are rarely exact multiples.
    decimals = max(0, len(f"{step:.8f}".rstrip("0").split(".")[1]))
    normalized = round(round(volume / step) * step, decimals)

    if normalized < minimum:
        raise InvalidRequestError(
            f"Volume {volume} is below the symbol minimum of {minimum}.",
            details={"volume_min": minimum, "volume_step": step},
        )
    if maximum and normalized > maximum:
        raise InvalidRequestError(
            f"Volume {volume} is above the symbol maximum of {maximum}.",
            details={"volume_max": maximum, "volume_step": step},
        )
    return normalized


def round_price(price: float | None, symbol_info: dict[str, Any]) -> float | None:
    if price is None:
        return None
    return round(float(price), int(symbol_info.get("digits", 5)))


def resolve_filling(
    mt5: ModuleType, symbol_info: dict[str, Any], requested: str | None
) -> int:
    if requested:
        constant = getattr(mt5, f"ORDER_FILLING_{requested.upper()}", None)
        if constant is None:
            raise InvalidRequestError(f"Unsupported filling mode: {requested}")
        return int(constant)

    mask = int(symbol_info.get("filling_mode") or 0)
    if mask & SYMBOL_FILLING_FOK:
        return int(mt5.ORDER_FILLING_FOK)
    if mask & SYMBOL_FILLING_IOC:
        return int(mt5.ORDER_FILLING_IOC)
    return int(mt5.ORDER_FILLING_RETURN)


def build_comment(settings: Settings, comment: str | None) -> str:
    text = f"{settings.order_comment_prefix}:{comment}" if comment else settings.order_comment_prefix
    return text[:31]  # MT5 silently truncates longer comments


# --- orders -------------------------------------------------------------------


def _unpack_send_result(result: Any) -> dict[str, Any]:
    data = to_dict(result)
    data.pop("request", None)
    retcode = int(data.get("retcode", 0))
    data["retcode"] = retcode
    data["retcode_description"] = describe_retcode(retcode)
    data["success"] = retcode in SUCCESS_RETCODES
    return data


async def place_order(
    session: MT5Session, settings: Settings, req: Any
) -> dict[str, Any]:
    """Send a market or pending order. ``req`` is an OrderRequest schema object."""
    symbol_info = await ensure_symbol(session, req.symbol)
    volume = normalize_volume(req.volume, symbol_info)
    await assert_trading_allowed(session, settings, volume=volume)

    price = round_price(req.price, symbol_info)
    sl = round_price(req.sl, symbol_info)
    tp = round_price(req.tp, symbol_info)
    stop_limit = round_price(req.stop_limit_price, symbol_info)
    deviation = req.deviation if req.deviation is not None else settings.default_deviation
    magic = req.magic if req.magic is not None else settings.default_magic
    comment = build_comment(settings, req.comment)
    is_market = req.type == "market"
    expiration = naive_utc(req.expiration) if req.expiration else None

    def _build(mt5: ModuleType) -> dict[str, Any]:
        order_type = getattr(mt5, _ORDER_TYPE_NAMES[(req.side, req.type)])
        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL if is_market else mt5.TRADE_ACTION_PENDING,
            "symbol": req.symbol,
            "volume": volume,
            "type": int(order_type),
            "deviation": deviation,
            "magic": magic,
            "comment": comment,
            "type_filling": resolve_filling(mt5, symbol_info, req.filling),
        }

        if is_market:
            tick = mt5.symbol_info_tick(req.symbol)
            if tick is None:
                raise InvalidRequestError(
                    f"No quotes available for '{req.symbol}'; the market may be closed.",
                    details={"symbol": req.symbol},
                )
            request["price"] = float(tick.ask if req.side == "buy" else tick.bid)
        else:
            request["price"] = price
            request["type_time"] = getattr(mt5, f"ORDER_TIME_{req.type_time.upper()}")
            if expiration is not None:
                request["expiration"] = expiration
            if stop_limit is not None:
                request["stoplimit"] = stop_limit

        if sl is not None:
            request["sl"] = sl
        if tp is not None:
            request["tp"] = tp
        return request

    request = await session.run(_build)

    if req.dry_run:
        check = await session.run(lambda mt5: mt5.order_check(request))
        if check is None:
            raise await session.fail("order_check failed.", request=request)
        data = to_dict(check)
        data.pop("request", None)
        retcode = int(data.get("retcode", 0))
        data["retcode"] = retcode
        data["retcode_description"] = "Check passed" if retcode == 0 else describe_retcode(retcode)
        data["success"] = retcode == 0
        data["dry_run"] = True
        data["sent_request"] = _jsonable_request(request)
        return data

    result = await session.run(lambda mt5: mt5.order_send(request))
    if result is None:
        raise await session.fail(
            "order_send returned no result.", request=_jsonable_request(request)
        )

    data = _unpack_send_result(result)
    data["dry_run"] = False
    data["sent_request"] = _jsonable_request(request)
    if not data["success"]:
        raise TradeRejectedError(
            f"Trade rejected by the server: {data['retcode_description']}",
            details=data,
        )
    logger.info(
        "Order accepted: %s %s %s -> order=%s deal=%s",
        req.side,
        volume,
        req.symbol,
        data.get("order"),
        data.get("deal"),
    )
    return data


def _jsonable_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (value.isoformat() if isinstance(value, datetime) else value)
        for key, value in request.items()
    }


async def list_positions(
    session: MT5Session, *, symbol: str | None = None
) -> list[dict[str, Any]]:
    def _get(mt5: ModuleType) -> Any:
        return mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()

    positions = await session.run(_get)
    if positions is None:
        raise await session.fail("Could not read open positions.")
    return [_position_payload(p) for p in positions]


def _position_payload(position: Any) -> dict[str, Any]:
    data = to_dict(position)
    data["side"] = POSITION_SIDE.get(int(data.get("type", 0)), "unknown")
    data["time"] = utc(data["time"]) if "time" in data else None
    return data


async def get_position(session: MT5Session, ticket: int) -> Any:
    positions = await session.run(lambda mt5: mt5.positions_get(ticket=ticket))
    if not positions:
        raise NotFoundError(
            f"No open position with ticket {ticket}.", details={"ticket": ticket}
        )
    return positions[0]


async def close_position(
    session: MT5Session,
    settings: Settings,
    *,
    ticket: int,
    volume: float | None = None,
    deviation: int | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    position = await get_position(session, ticket)
    symbol = position.symbol
    symbol_info = await ensure_symbol(session, symbol)

    close_volume = float(position.volume) if volume is None else normalize_volume(volume, symbol_info)
    if close_volume > float(position.volume) + 1e-9:
        raise InvalidRequestError(
            f"Cannot close {close_volume} lots: the position holds {position.volume}.",
            details={"position_volume": float(position.volume)},
        )

    await assert_trading_allowed(session, settings, volume=close_volume)
    position_side = int(position.type)
    dev = deviation if deviation is not None else settings.default_deviation
    text = build_comment(settings, comment or "close")

    def _build(mt5: ModuleType) -> dict[str, Any]:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise InvalidRequestError(
                f"No quotes available for '{symbol}'; the market may be closed.",
                details={"symbol": symbol},
            )
        # Close by sending the opposite deal against the position ticket.
        if position_side == 0:  # long -> sell at bid
            order_type, price = mt5.ORDER_TYPE_SELL, float(tick.bid)
        else:  # short -> buy at ask
            order_type, price = mt5.ORDER_TYPE_BUY, float(tick.ask)
        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": int(ticket),
            "symbol": symbol,
            "volume": close_volume,
            "type": int(order_type),
            "price": price,
            "deviation": dev,
            "magic": int(getattr(position, "magic", settings.default_magic)),
            "comment": text,
            "type_filling": resolve_filling(mt5, symbol_info, None),
        }

    request = await session.run(_build)
    result = await session.run(lambda mt5: mt5.order_send(request))
    if result is None:
        raise await session.fail("order_send returned no result while closing.", ticket=ticket)

    data = _unpack_send_result(result)
    data["sent_request"] = _jsonable_request(request)
    if not data["success"]:
        raise TradeRejectedError(
            f"Close rejected by the server: {data['retcode_description']}", details=data
        )
    return data


async def modify_position(
    session: MT5Session,
    settings: Settings,
    *,
    ticket: int,
    sl: float | None,
    tp: float | None,
) -> dict[str, Any]:
    if sl is None and tp is None:
        raise InvalidRequestError("Provide at least one of 'sl' or 'tp'.")

    position = await get_position(session, ticket)
    symbol_info = await ensure_symbol(session, position.symbol)
    await assert_trading_allowed(session, settings)

    # 0.0 clears the level in MT5, which is what "not provided" should keep doing:
    # fall back to the level the position already carries.
    new_sl = round_price(sl, symbol_info) if sl is not None else float(position.sl)
    new_tp = round_price(tp, symbol_info) if tp is not None else float(position.tp)

    def _build(mt5: ModuleType) -> dict[str, Any]:
        return {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": position.symbol,
            "sl": new_sl,
            "tp": new_tp,
        }

    request = await session.run(_build)
    result = await session.run(lambda mt5: mt5.order_send(request))
    if result is None:
        raise await session.fail("order_send returned no result while modifying.", ticket=ticket)

    data = _unpack_send_result(result)
    data["sent_request"] = _jsonable_request(request)
    if not data["success"]:
        raise TradeRejectedError(
            f"Modify rejected by the server: {data['retcode_description']}", details=data
        )
    return data


async def list_orders(session: MT5Session, *, symbol: str | None = None) -> list[dict[str, Any]]:
    def _get(mt5: ModuleType) -> Any:
        return mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()

    orders = await session.run(_get)
    if orders is None:
        raise await session.fail("Could not read pending orders.")

    payload = []
    for order in orders:
        data = to_dict(order)
        if "time_setup" in data:
            data["time_setup"] = utc(data["time_setup"])
        payload.append(data)
    return payload


async def cancel_order(session: MT5Session, settings: Settings, *, ticket: int) -> dict[str, Any]:
    orders = await session.run(lambda mt5: mt5.orders_get(ticket=ticket))
    if not orders:
        raise NotFoundError(
            f"No pending order with ticket {ticket}.", details={"ticket": ticket}
        )
    await assert_trading_allowed(session, settings)

    def _build(mt5: ModuleType) -> dict[str, Any]:
        return {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}

    request = await session.run(_build)
    result = await session.run(lambda mt5: mt5.order_send(request))
    if result is None:
        raise await session.fail("order_send returned no result while cancelling.", ticket=ticket)

    data = _unpack_send_result(result)
    data["sent_request"] = _jsonable_request(request)
    if not data["success"]:
        raise TradeRejectedError(
            f"Cancel rejected by the server: {data['retcode_description']}", details=data
        )
    return data


async def list_deals(
    session: MT5Session, *, start: datetime, end: datetime, symbol: str | None = None
) -> list[dict[str, Any]]:
    def _get(mt5: ModuleType) -> Any:
        if symbol:
            return mt5.history_deals_get(naive_utc(start), naive_utc(end), group=symbol)
        return mt5.history_deals_get(naive_utc(start), naive_utc(end))

    deals = await session.run(_get)
    if deals is None:
        raise await session.fail("Could not read deal history.")

    payload = []
    for deal in deals:
        data = to_dict(deal)
        if "time" in data:
            data["time"] = utc(data["time"])
        payload.append(data)
    return payload
