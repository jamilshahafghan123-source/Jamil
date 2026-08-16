"""FastAPI application factory for the MetaTrader 5 bridge."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .errors import BridgeError, bridge_error_handler
from .bot.engine import TradingBot
from .mt5.session import MT5Session
from .routers import bot as bot_router
from .routers import health, market, simple, trading

APP_NAME = "mt5-fastapi-bridge"
APP_VERSION = "1.0.0"

logger = logging.getLogger(__name__)

DESCRIPTION = """
HTTPS bridge to a MetaTrader 5 terminal.

* **Market data** - symbols, latest ticks and OHLC candles.
* **Trading** - market and pending orders, position close/modify, deal history.

Every endpoint except `/health` requires an `X-API-Key` header.
Trading is refused unless the connected account is a demo account
(override with `ALLOW_LIVE_TRADING=true`).
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        session = MT5Session(settings)
        app.state.mt5_session = session
        app.state.settings = settings
        app.state.bot = TradingBot(session, settings)
        if not settings.tls_enabled:
            logger.warning(
                "TLS is not configured (SSL_CERTFILE / SSL_KEYFILE). Serve this API "
                "over HTTPS, either directly or behind a TLS-terminating proxy."
            )
        await session.startup()
        try:
            yield
        finally:
            # Stop the loop before the terminal goes away, so a shutdown can
            # never leave a bot mid-order against a closing session.
            await app.state.bot.stop()
            await session.shutdown()

    app = FastAPI(
        title="MetaTrader 5 Bridge",
        description=DESCRIPTION,
        version=APP_VERSION,
        lifespan=lifespan,
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_exception_handler(BridgeError, bridge_error_handler)

    app.include_router(health.router)
    app.include_router(market.router)
    app.include_router(trading.router)
    app.include_router(simple.router)
    app.include_router(bot_router.router)
    return app


app = create_app()
