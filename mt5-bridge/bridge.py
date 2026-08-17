"""MT5 Bridge — runs on Windows, next to the MetaTrader 5 terminal.

WHY THIS EXISTS
---------------
The `MetaTrader5` PyPI package is a thin wrapper around the MT5 terminal's
local Windows IPC. It requires:
  * Windows (no Linux/macOS wheels exist), and
  * the MT5 terminal running on the SAME machine.

That makes it impossible to run inside a Cloud Run container. So the backend
stays on Cloud Run and this small service runs on a Windows VM alongside the
terminal, exposing exactly the operations the backend needs over an
authenticated HTTP API.

SECURITY
--------
* Every request must carry `X-Bridge-Token` matching MT5_BRIDGE_TOKEN.
* Broker login/password/server live ONLY here, in this machine's environment.
  They are never returned by any endpoint, so they cannot reach the browser.
* Bind to a private IP and firewall port 8100 to the backend only. Do not
  expose this service to the internet.

Run:  python bridge.py     (or run_bridge.bat)
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - only importable on Windows
    print(
        "ERROR: the MetaTrader5 package is required and is Windows-only.\n"
        "Install on a Windows host with:  pip install MetaTrader5",
        file=sys.stderr,
    )
    raise

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("bridge")

# ------------------------------------------------------------------ config

BRIDGE_TOKEN = os.getenv("MT5_BRIDGE_TOKEN", "")
MT5_LOGIN = os.getenv("MT5_LOGIN", "")
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")  # optional path to terminal64.exe
BRIDGE_HOST = os.getenv("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("BRIDGE_PORT", "8100"))
DEFAULT_SYMBOL = os.getenv("SYMBOL", "XAUUSD")

# Refuse to auto-trade a live account unless the operator opts in HERE too.
# This is a second, independent latch from the backend's ALLOW_REAL_TRADING.
BRIDGE_ALLOW_REAL = os.getenv("BRIDGE_ALLOW_REAL", "false").lower() == "true"

if not BRIDGE_TOKEN:
    print("ERROR: MT5_BRIDGE_TOKEN must be set.", file=sys.stderr)
    sys.exit(1)

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

TRADE_MODE_NAMES = {
    getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0): "demo",
    getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1): "contest",
    getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2): "real",
}


# -------------------------------------------------------------------- auth


async def require_token(x_bridge_token: str = Header(default="")) -> None:
    # Constant-time compare so the token can't be discovered by timing.
    if not secrets.compare_digest(x_bridge_token, BRIDGE_TOKEN):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad bridge token")


# ------------------------------------------------------------ mt5 helpers


def mt5_init() -> bool:
    kwargs: dict[str, Any] = {}
    if MT5_PATH:
        kwargs["path"] = MT5_PATH
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        kwargs.update(
            login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER
        )

    if not mt5.initialize(**kwargs):
        log.error("mt5.initialize failed: %s", mt5.last_error())
        return False

    info = mt5.account_info()
    if info is None:
        log.error("mt5 connected but account_info() is None: %s", mt5.last_error())
        return False

    mode = TRADE_MODE_NAMES.get(info.trade_mode, str(info.trade_mode))
    log.info(
        "MT5 connected: login=%s server=%s type=%s balance=%.2f %s",
        info.login,
        info.server,
        mode.upper(),
        info.balance,
        info.currency,
    )
    if mode == "real" and not BRIDGE_ALLOW_REAL:
        log.warning(
            "LIVE account detected and BRIDGE_ALLOW_REAL is false — this bridge "
            "will REFUSE all order requests. Set BRIDGE_ALLOW_REAL=true only "
            "when you intend to trade real money."
        )
    # Make sure the symbol is selected in Market Watch, else ticks are empty.
    if not mt5.symbol_select(DEFAULT_SYMBOL, True):
        log.warning("could not select symbol %s", DEFAULT_SYMBOL)
    return True


def ensure_connected() -> None:
    if mt5.terminal_info() is None:
        log.warning("MT5 connection lost — reinitialising")
        mt5.shutdown()
        if not mt5_init():
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "MT5 terminal unavailable"
            )


def account_is_real() -> bool:
    info = mt5.account_info()
    return bool(
        info and TRADE_MODE_NAMES.get(info.trade_mode, "") == "real"
    )


def to_iso(ts: int | float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ----------------------------------------------------------------- schemas


class OrderRequest(BaseModel):
    symbol: str
    side: str = Field(pattern="^(BUY|SELL)$")
    volume: float = Field(gt=0, le=100)
    sl: float | None = None
    tp: float | None = None
    comment: str = ""
    deviation: int = Field(default=20, ge=0, le=1000)


class CloseRequest(BaseModel):
    ticket: int
    deviation: int = Field(default=20, ge=0, le=1000)


# --------------------------------------------------------------------- app


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not mt5_init():
        log.error("starting anyway; /health will report mt5_connected=false")
    yield
    mt5.shutdown()
    log.info("MT5 shut down")


app = FastAPI(title="MT5 Bridge", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Unauthenticated liveness probe. Reveals no account details."""
    connected = mt5.terminal_info() is not None and mt5.account_info() is not None
    return {"status": "ok", "mt5_connected": connected}


@app.get("/account", dependencies=[Depends(require_token)])
async def get_account() -> dict:
    ensure_connected()
    a = mt5.account_info()
    if a is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no account info")
    return {
        "login": a.login,
        "server": a.server,
        "currency": a.currency,
        "balance": a.balance,
        "equity": a.equity,
        "margin": a.margin,
        "free_margin": a.margin_free,
        "margin_level": a.margin_level or None,
        "leverage": a.leverage,
        "trade_mode": TRADE_MODE_NAMES.get(a.trade_mode, str(a.trade_mode)),
        "company": a.company,
    }


@app.get("/tick", dependencies=[Depends(require_token)])
async def get_tick(symbol: str = Query(default=DEFAULT_SYMBOL)) -> dict:
    ensure_connected()
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no tick for {symbol}")
    point = info.point or 0.01
    return {
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
        "spread_points": round((tick.ask - tick.bid) / point, 1),
        "time": to_iso(tick.time),
    }


@app.get("/symbol", dependencies=[Depends(require_token)])
async def get_symbol(symbol: str = Query(default=DEFAULT_SYMBOL)) -> dict:
    """Contract specs the backend's position sizing depends on."""
    ensure_connected()
    s = mt5.symbol_info(symbol)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown symbol {symbol}")
    return {
        "symbol": s.name,
        "digits": s.digits,
        "point": s.point,
        "spread": s.spread,
        "trade_contract_size": s.trade_contract_size,
        "trade_tick_size": s.trade_tick_size,
        "trade_tick_value": s.trade_tick_value,
        "volume_min": s.volume_min,
        "volume_max": s.volume_max,
        "volume_step": s.volume_step,
        "trade_stops_level": s.trade_stops_level,
        "trade_freeze_level": s.trade_freeze_level,
    }


@app.get("/bars", dependencies=[Depends(require_token)])
async def get_bars(
    symbol: str = Query(default=DEFAULT_SYMBOL),
    timeframe: str = Query(default="M15"),
    count: int = Query(default=300, ge=10, le=5000),
) -> dict:
    ensure_connected()
    tf = TIMEFRAMES.get(timeframe.upper())
    if tf is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"timeframe must be one of {list(TIMEFRAMES)}",
        )
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"no bars for {symbol} {timeframe}: {mt5.last_error()}",
        )
    return {
        "symbol": symbol,
        "timeframe": timeframe.upper(),
        "bars": [
            {
                "time": to_iso(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "tick_volume": int(r["tick_volume"]),
                "spread": int(r["spread"]),
            }
            for r in rates
        ],
    }


@app.get("/positions", dependencies=[Depends(require_token)])
async def get_positions(symbol: str | None = Query(default=None)) -> dict:
    ensure_connected()
    positions = (
        mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    ) or []
    return {
        "positions": [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "volume": p.volume,
                "price_open": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
                "price_current": p.price_current,
                "profit": p.profit,
                "swap": p.swap,
                "time": to_iso(p.time),
                "comment": p.comment,
            }
            for p in positions
        ]
    }


@app.get("/history", dependencies=[Depends(require_token)])
async def get_history(days: int = Query(default=7, ge=1, le=365)) -> dict:
    ensure_connected()
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    return {
        "deals": [
            {
                "ticket": d.ticket,
                "order": d.order,
                "symbol": d.symbol,
                "type": "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                "volume": d.volume,
                "price": d.price,
                "profit": d.profit,
                "commission": d.commission,
                "swap": d.swap,
                "time": to_iso(d.time),
                "comment": d.comment,
            }
            for d in deals
            if d.symbol  # skip balance/credit entries
        ]
    }


# ------------------------------------------------------------------ writes


@app.post("/order", dependencies=[Depends(require_token)])
async def send_order(req: OrderRequest) -> dict:
    """Send a market order.

    The backend has already run its risk engine. This endpoint adds one
    independent latch: it refuses to trade a LIVE account unless
    BRIDGE_ALLOW_REAL is true on this machine.
    """
    ensure_connected()

    if account_is_real() and not BRIDGE_ALLOW_REAL:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "refusing to trade: account is LIVE and BRIDGE_ALLOW_REAL is false",
        )

    info = mt5.symbol_info(req.symbol)
    tick = mt5.symbol_info_tick(req.symbol)
    if info is None or tick is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown symbol {req.symbol}")
    if not info.visible:
        mt5.symbol_select(req.symbol, True)

    is_buy = req.side == "BUY"
    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    price = tick.ask if is_buy else tick.bid

    request: dict[str, Any] = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": req.symbol,
        "volume": float(req.volume),
        "type": order_type,
        "price": price,
        "deviation": req.deviation,
        "magic": 20260817,
        "comment": req.comment[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    if req.sl is not None:
        request["sl"] = float(req.sl)
    if req.tp is not None:
        request["tp"] = float(req.tp)

    log.info("ORDER REQUEST %s", request)
    result = mt5.order_send(request)

    if result is None:
        err = mt5.last_error()
        log.error("order_send returned None: %s", err)
        return {"success": False, "retcode": None, "comment": str(err), "request": request}

    payload = {
        "success": result.retcode == mt5.TRADE_RETCODE_DONE,
        "retcode": result.retcode,
        "comment": result.comment,
        "ticket": result.order or None,
        "deal": result.deal or None,
        "volume": result.volume,
        "price": result.price,
        "request": request,
    }
    log.info("ORDER RESULT %s", payload)
    return payload


@app.post("/close", dependencies=[Depends(require_token)])
async def close_position(req: CloseRequest) -> dict:
    """Close a position by ticket with an opposite market order."""
    ensure_connected()

    positions = mt5.positions_get(ticket=req.ticket)
    if not positions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no position {req.ticket}")
    p = positions[0]

    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no tick")

    closing_buy = p.type == mt5.POSITION_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": p.symbol,
        "volume": p.volume,
        "type": mt5.ORDER_TYPE_BUY if closing_buy else mt5.ORDER_TYPE_SELL,
        "position": p.ticket,
        "price": tick.ask if closing_buy else tick.bid,
        "deviation": req.deviation,
        "magic": 20260817,
        "comment": "close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    log.info("CLOSE REQUEST %s", request)
    result = mt5.order_send(request)
    if result is None:
        return {"success": False, "comment": str(mt5.last_error())}

    payload = {
        "success": result.retcode == mt5.TRADE_RETCODE_DONE,
        "retcode": result.retcode,
        "comment": result.comment,
        "ticket": req.ticket,
    }
    log.info("CLOSE RESULT %s", payload)
    return payload


if __name__ == "__main__":
    log.info("bridge listening on %s:%s", BRIDGE_HOST, BRIDGE_PORT)
    uvicorn.run(app, host=BRIDGE_HOST, port=BRIDGE_PORT, log_level="info")
