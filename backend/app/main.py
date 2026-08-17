"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from .config import settings
from .db import SessionLocal, init_models
from .models import RiskSettings, User
from .routers import account, analysis, auth, risk, trading, ws
from .security import hash_password
from .services import bot
from .services.mt5_client import mt5

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("main")


async def bootstrap_user() -> None:
    """Create the first user if the DB is empty and creds were provided."""
    if not (settings.BOOTSTRAP_EMAIL and settings.BOOTSTRAP_PASSWORD):
        return
    async with SessionLocal() as db:
        count = (await db.execute(select(func.count(User.id)))).scalar_one()
        if count:
            return
        user = User(
            email=settings.BOOTSTRAP_EMAIL.lower(),
            password_hash=hash_password(settings.BOOTSTRAP_PASSWORD),
        )
        db.add(user)
        await db.flush()
        db.add(RiskSettings(user_id=user.id))
        await db.commit()
        log.warning("bootstrap user created: %s", user.email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    await bootstrap_user()
    await mt5.start()
    bot.start()
    log.info(
        "started env=%s symbol=%s real_trading_allowed=%s",
        settings.ENV,
        settings.SYMBOL,
        settings.ALLOW_REAL_TRADING,
    )
    if settings.ALLOW_REAL_TRADING:
        log.warning("ALLOW_REAL_TRADING is TRUE — live orders are possible")
    yield
    await bot.stop()
    await mt5.stop()


app = FastAPI(
    title="MT5 AI Trading Analyst",
    version="1.0.0",
    description="AI market analysis and risk-managed execution for XAUUSD on MetaTrader 5.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(account.router)
app.include_router(analysis.router)
app.include_router(risk.router)
app.include_router(trading.router)
app.include_router(ws.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    """Liveness probe. Never touches the DB or the broker."""
    return {"status": "ok", "env": settings.ENV, "symbol": settings.SYMBOL}


@app.get("/ready", tags=["meta"])
async def ready() -> dict:
    """Readiness: reports bridge state without failing the container."""
    return {
        "status": "ok",
        "bridge_connected": await mt5.connected(),
        "real_trading_allowed": settings.ALLOW_REAL_TRADING,
    }
