"""A stand-in for the MetaTrader5 package.

The real package ships Windows-only wheels and needs a running terminal, so the
test-suite injects this module as ``sys.modules["MetaTrader5"]``. It mimics the
subset of the API the bridge uses, including the namedtuple-shaped return values
and the ``None``-plus-``last_error()`` failure convention.
"""

from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timedelta, timezone
from typing import Any

# --- constants ----------------------------------------------------------------

TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
TIMEFRAME_H1, TIMEFRAME_H4 = 16385, 16388
TIMEFRAME_D1, TIMEFRAME_W1, TIMEFRAME_MN1 = 16408, 32769, 49153

ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 2, 3
ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP = 4, 5
ORDER_TYPE_BUY_STOP_LIMIT, ORDER_TYPE_SELL_STOP_LIMIT = 6, 7

TRADE_ACTION_DEAL, TRADE_ACTION_PENDING = 1, 5
TRADE_ACTION_SLTP, TRADE_ACTION_MODIFY, TRADE_ACTION_REMOVE = 6, 7, 8

ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
ORDER_TIME_GTC, ORDER_TIME_DAY, ORDER_TIME_SPECIFIED, ORDER_TIME_SPECIFIED_DAY = 0, 1, 2, 3

SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2

TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED = 10009, 10008
TRADE_RETCODE_NO_MONEY = 10019

ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2

# --- structures ---------------------------------------------------------------

AccountInfo = namedtuple(
    "AccountInfo",
    "login trade_mode balance equity margin margin_free currency leverage server name trade_allowed",
)
TerminalInfo = namedtuple("TerminalInfo", "connected trade_allowed path build")
SymbolInfo = namedtuple(
    "SymbolInfo",
    "name description path digits point spread trade_mode visible volume_min volume_max"
    " volume_step filling_mode trade_tick_size trade_tick_value trade_contract_size",
)
Tick = namedtuple("Tick", "time bid ask last volume")
SendResult = namedtuple(
    "SendResult", "retcode deal order volume price bid ask comment request_id retcode_external"
)
CheckResult = namedtuple(
    "CheckResult", "retcode balance equity margin margin_free margin_level comment"
)
PositionInfo = namedtuple(
    "PositionInfo",
    "ticket time symbol type volume price_open sl tp price_current profit magic comment",
)
OrderInfo = namedtuple(
    "OrderInfo",
    "ticket time_setup symbol type volume_initial volume_current price_open sl tp magic comment",
)
DealInfo = namedtuple(
    "DealInfo", "ticket order time symbol type volume price profit swap commission comment"
)

# --- mutable state ------------------------------------------------------------


class _State:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.initialize_ok = True
        self.error: tuple[int, str] = (1, "Success")
        self.trade_mode = ACCOUNT_TRADE_MODE_DEMO
        self.terminal_trade_allowed = True
        self.next_ticket = 500_001
        self.positions: dict[int, PositionInfo] = {}
        self.orders: dict[int, OrderInfo] = {}
        # symbol -> explicit candle rows, for tests that shape the series.
        self.rates: dict[str, list[dict]] = {}
        self.account = AccountInfo(
            login=5031234, trade_mode=ACCOUNT_TRADE_MODE_DEMO, balance=10_000.0,
            equity=10_050.0, margin=120.0, margin_free=9_930.0, currency="USD",
            leverage=100, server="MetaQuotes-Demo", name="Demo Account",
            trade_allowed=True,
        )
        self.deals: list[DealInfo] = []
        self.sent_requests: list[dict[str, Any]] = []
        self.symbols: dict[str, SymbolInfo] = {
            "EURUSD": SymbolInfo(
                name="EURUSD", description="Euro vs US Dollar", path="Forex\\EURUSD",
                digits=5, point=0.00001, spread=8, trade_mode=4, visible=True,
                volume_min=0.01, volume_max=100.0, volume_step=0.01,
                filling_mode=SYMBOL_FILLING_FOK,
                trade_tick_size=0.00001, trade_tick_value=1.0, trade_contract_size=100_000.0,
            ),
            "GBPUSD": SymbolInfo(
                name="GBPUSD", description="Great Britain Pound vs US Dollar",
                path="Forex\\GBPUSD", digits=5, point=0.00001, spread=12, trade_mode=4,
                visible=False, volume_min=0.01, volume_max=50.0, volume_step=0.01,
                filling_mode=SYMBOL_FILLING_IOC,
                trade_tick_size=0.00001, trade_tick_value=1.0, trade_contract_size=100_000.0,
            ),
            # 100 oz contract, 0.01 tick = 1.00 account currency per lot.
            "XAUUSD": SymbolInfo(
                name="XAUUSD", description="Gold vs US Dollar", path="Metals\\XAUUSD",
                digits=2, point=0.01, spread=30, trade_mode=4, visible=True,
                volume_min=0.01, volume_max=20.0, volume_step=0.01,
                filling_mode=SYMBOL_FILLING_FOK,
                trade_tick_size=0.01, trade_tick_value=1.0, trade_contract_size=100.0,
            ),
        }
        self.quotes = {
            "EURUSD": (1.08500, 1.08508),
            "GBPUSD": (1.26400, 1.26412),
            "XAUUSD": (2401.50, 2401.80),
        }

    def ticket(self) -> int:
        self.next_ticket += 1
        return self.next_ticket


state = _State()


def reset() -> None:
    state.reset()


# --- lifecycle ----------------------------------------------------------------


def initialize(path: str | None = None, **kwargs: Any) -> bool:
    if not state.initialize_ok:
        state.error = (-10005, "IPC timeout")
        return False
    state.initialized = True
    return True


def login(*args: Any, **kwargs: Any) -> bool:
    return state.initialized


def shutdown() -> None:
    state.initialized = False


def last_error() -> tuple[int, str]:
    return state.error


def _require_init() -> bool:
    if not state.initialized:
        state.error = (-10004, "Terminal not initialized")
        return False
    return True


def account_info() -> AccountInfo | None:
    if not _require_init():
        return None
    # trade_mode stays on the state so tests can flip demo/real independently.
    return state.account._replace(trade_mode=state.trade_mode)


def terminal_info() -> TerminalInfo | None:
    if not _require_init():
        return None
    return TerminalInfo(
        connected=True, trade_allowed=state.terminal_trade_allowed,
        path="C:\\MT5", build=4260,
    )


# --- market data --------------------------------------------------------------


def symbol_info(symbol: str) -> SymbolInfo | None:
    if not _require_init():
        return None
    return state.symbols.get(symbol)


def symbol_select(symbol: str, enable: bool = True) -> bool:
    info = state.symbols.get(symbol)
    if info is None:
        state.error = (4301, "Unknown symbol")
        return False
    state.symbols[symbol] = info._replace(visible=enable)
    return True


def symbols_get(group: str | None = None) -> tuple[SymbolInfo, ...]:
    values = list(state.symbols.values())
    if group:
        needle = group.strip("*").upper()
        values = [s for s in values if needle in s.name.upper()]
    return tuple(values)


def symbol_info_tick(symbol: str) -> Tick | None:
    if symbol not in state.quotes:
        state.error = (4301, "Unknown symbol")
        return None
    bid, ask = state.quotes[symbol]
    return Tick(
        time=int(datetime.now(tz=timezone.utc).timestamp()),
        bid=bid, ask=ask, last=bid, volume=1,
    )


def _make_rates(symbol: str, count: int, step_seconds: int, first_time: datetime) -> list[dict]:
    # Real MT5 returns a numpy structured array; rows support row["field"] access,
    # which is all the bridge relies on, so plain dicts stand in fine here.
    # Tests that care about the shape of the series (the analysis pipeline) inject
    # their own bars instead of using the ramp below.
    override = state.rates.get(symbol)
    if override is not None:
        return [dict(row) for row in override[-count:]]

    bid = state.quotes.get(symbol, (1.0, 1.0))[0]
    rows = []
    for i in range(count):
        base = bid + i * 0.0001
        rows.append(
            {
                "time": int((first_time + timedelta(seconds=i * step_seconds)).timestamp()),
                "open": base,
                "high": base + 0.0005,
                "low": base - 0.0004,
                "close": base + 0.0002,
                "tick_volume": 100 + i,
                "spread": 8,
                "real_volume": 0,
            }
        )
    return rows


def _timeframe_seconds(timeframe: int) -> int:
    if timeframe >= TIMEFRAME_D1:
        return 86_400
    if timeframe >= TIMEFRAME_H1:
        return (timeframe - 16_384) * 3_600
    return timeframe * 60


def copy_rates_from_pos(symbol: str, timeframe: int, start_pos: int, count: int):
    if symbol not in state.symbols:
        state.error = (4301, "Unknown symbol")
        return None
    step = _timeframe_seconds(timeframe)
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    first = now - timedelta(seconds=step * (count + start_pos))
    return _make_rates(symbol, count, step, first)


def copy_rates_from(symbol: str, timeframe: int, date_from: datetime, count: int):
    if symbol not in state.symbols:
        state.error = (4301, "Unknown symbol")
        return None
    return _make_rates(
        symbol, count, _timeframe_seconds(timeframe), date_from.replace(tzinfo=timezone.utc)
    )


def copy_rates_range(symbol: str, timeframe: int, date_from: datetime, date_to: datetime):
    if symbol not in state.symbols:
        state.error = (4301, "Unknown symbol")
        return None
    step = _timeframe_seconds(timeframe)
    span = int((date_to - date_from).total_seconds())
    count = max(1, span // step)
    return _make_rates(symbol, count, step, date_from.replace(tzinfo=timezone.utc))


def order_calc_margin(
    order_type: int, symbol: str, volume: float, price: float
) -> float | None:
    """Margin for `volume` lots, mirroring MT5: contract value / leverage."""
    if not _require_init():
        return None
    info = state.symbols.get(symbol)
    if info is None:
        return None
    contract = float(info.trade_contract_size)
    return round(price * contract * volume / state.account.leverage, 2)


# --- trading ------------------------------------------------------------------


def order_check(request: dict) -> CheckResult | None:
    if not _require_init():
        return None
    if request.get("volume", 0) > 5:
        return CheckResult(
            retcode=TRADE_RETCODE_NO_MONEY, balance=10_000.0, equity=10_050.0, margin=0.0,
            margin_free=0.0, margin_level=0.0, comment="Not enough money",
        )
    return CheckResult(
        retcode=0, balance=10_000.0, equity=10_050.0, margin=120.0,
        margin_free=9_930.0, margin_level=8_375.0, comment="Done",
    )


def order_send(request: dict) -> SendResult | None:
    if not _require_init():
        return None
    state.sent_requests.append(dict(request))
    action = request["action"]

    if request.get("volume", 0) > 5:  # stand-in for a server-side rejection
        return SendResult(
            retcode=TRADE_RETCODE_NO_MONEY, deal=0, order=0, volume=0.0, price=0.0,
            bid=0.0, ask=0.0, comment="No money", request_id=1, retcode_external=0,
        )

    if action == TRADE_ACTION_DEAL and request.get("position"):
        return _close(request)
    if action == TRADE_ACTION_DEAL:
        return _open(request)
    if action == TRADE_ACTION_PENDING:
        return _pending(request)
    if action == TRADE_ACTION_SLTP:
        return _sltp(request)
    if action == TRADE_ACTION_REMOVE:
        return _remove(request)

    return SendResult(
        retcode=10013, deal=0, order=0, volume=0.0, price=0.0, bid=0.0, ask=0.0,
        comment="Invalid request", request_id=0, retcode_external=0,
    )


def _open(request: dict) -> SendResult:
    ticket = state.ticket()
    price = float(request["price"])
    state.positions[ticket] = PositionInfo(
        ticket=ticket,
        time=int(datetime.now(tz=timezone.utc).timestamp()),
        symbol=request["symbol"],
        type=ORDER_TYPE_BUY if request["type"] == ORDER_TYPE_BUY else ORDER_TYPE_SELL,
        volume=float(request["volume"]), price_open=price,
        sl=float(request.get("sl", 0.0)), tp=float(request.get("tp", 0.0)),
        price_current=price, profit=0.0, magic=int(request.get("magic", 0)),
        comment=request.get("comment", ""),
    )
    deal = state.ticket()
    state.deals.append(
        DealInfo(
            ticket=deal, order=ticket, time=int(datetime.now(tz=timezone.utc).timestamp()),
            symbol=request["symbol"], type=request["type"], volume=float(request["volume"]),
            price=price, profit=0.0, swap=0.0, commission=0.0,
            comment=request.get("comment", ""),
        )
    )
    return SendResult(
        retcode=TRADE_RETCODE_DONE, deal=deal, order=ticket, volume=float(request["volume"]),
        price=price, bid=price, ask=price, comment="Request completed", request_id=1,
        retcode_external=0,
    )


def _close(request: dict) -> SendResult:
    ticket = int(request["position"])
    position = state.positions.get(ticket)
    if position is None:
        return SendResult(
            retcode=10036, deal=0, order=0, volume=0.0, price=0.0, bid=0.0, ask=0.0,
            comment="Position already closed", request_id=0, retcode_external=0,
        )
    volume = float(request["volume"])
    remaining = round(position.volume - volume, 8)
    if remaining > 0:
        state.positions[ticket] = position._replace(volume=remaining)
    else:
        del state.positions[ticket]
    deal = state.ticket()
    return SendResult(
        retcode=TRADE_RETCODE_DONE, deal=deal, order=state.ticket(), volume=volume,
        price=float(request["price"]), bid=float(request["price"]), ask=float(request["price"]),
        comment="Request completed", request_id=1, retcode_external=0,
    )


def _pending(request: dict) -> SendResult:
    ticket = state.ticket()
    state.orders[ticket] = OrderInfo(
        ticket=ticket, time_setup=int(datetime.now(tz=timezone.utc).timestamp()),
        symbol=request["symbol"], type=request["type"], volume_initial=float(request["volume"]),
        volume_current=float(request["volume"]), price_open=float(request["price"]),
        sl=float(request.get("sl", 0.0)), tp=float(request.get("tp", 0.0)),
        magic=int(request.get("magic", 0)), comment=request.get("comment", ""),
    )
    return SendResult(
        retcode=TRADE_RETCODE_PLACED, deal=0, order=ticket, volume=float(request["volume"]),
        price=float(request["price"]), bid=0.0, ask=0.0, comment="Order placed",
        request_id=1, retcode_external=0,
    )


def _sltp(request: dict) -> SendResult:
    ticket = int(request["position"])
    position = state.positions.get(ticket)
    if position is None:
        return SendResult(
            retcode=10036, deal=0, order=0, volume=0.0, price=0.0, bid=0.0, ask=0.0,
            comment="Position already closed", request_id=0, retcode_external=0,
        )
    state.positions[ticket] = position._replace(
        sl=float(request.get("sl", 0.0)), tp=float(request.get("tp", 0.0))
    )
    return SendResult(
        retcode=TRADE_RETCODE_DONE, deal=0, order=ticket, volume=0.0, price=0.0,
        bid=0.0, ask=0.0, comment="Request completed", request_id=1, retcode_external=0,
    )


def _remove(request: dict) -> SendResult:
    ticket = int(request["order"])
    if state.orders.pop(ticket, None) is None:
        return SendResult(
            retcode=10013, deal=0, order=0, volume=0.0, price=0.0, bid=0.0, ask=0.0,
            comment="Invalid request", request_id=0, retcode_external=0,
        )
    return SendResult(
        retcode=TRADE_RETCODE_DONE, deal=0, order=ticket, volume=0.0, price=0.0,
        bid=0.0, ask=0.0, comment="Request completed", request_id=1, retcode_external=0,
    )


def positions_get(symbol: str | None = None, ticket: int | None = None, **kwargs: Any):
    if not _require_init():
        return None
    values = list(state.positions.values())
    if ticket is not None:
        values = [p for p in values if p.ticket == ticket]
    if symbol:
        values = [p for p in values if p.symbol == symbol]
    return tuple(values)


def orders_get(symbol: str | None = None, ticket: int | None = None, **kwargs: Any):
    if not _require_init():
        return None
    values = list(state.orders.values())
    if ticket is not None:
        values = [o for o in values if o.ticket == ticket]
    if symbol:
        values = [o for o in values if o.symbol == symbol]
    return tuple(values)


def history_deals_get(date_from: datetime, date_to: datetime, group: str | None = None, **kwargs):
    if not _require_init():
        return None
    values = state.deals
    if group:
        needle = group.strip("*").upper()
        values = [d for d in values if needle in d.symbol.upper()]
    return tuple(values)
