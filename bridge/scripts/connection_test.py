"""Read-only demo-connection test. Run this on the Windows host with MT5 open.

    cd bridge
    python scripts/connection_test.py --login 5054539011 --server MetaQuotes-Demo

It connects to the terminal using bridge/.env, checks the account, the symbol,
the three strategy timeframes and the signal engine, then prints a PASS/FAIL
report.

**It cannot trade.** `order_send` is replaced with a guard that raises before
the call reaches the terminal, so a bug anywhere in the path below would abort
the test rather than place an order. Nothing here opens, modifies or closes
anything, and the test does not enable any live-trading flag.

Your password is read from .env into memory and is never printed or logged.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis import signal as signal_pipeline  # noqa: E402
from app.config import Settings  # noqa: E402
from app.mt5 import market  # noqa: E402
from app.mt5.session import MT5Session, import_mt5  # noqa: E402

OK, BAD, WARN = "PASS", "FAIL", "WARN"

# How stale a quote or candle may be before the feed is treated as not live.
# Generous, because gold still has a daily break and a weekend.
FRESH_TICK = timedelta(minutes=15)


class Report:
    """Collects the result lines the run has to end with."""

    def __init__(self) -> None:
        self.lines: dict[str, str] = {}
        self.notes: list[str] = []

    def record(self, name: str, verdict: str, detail: str = "") -> str:
        self.lines[name] = verdict
        mark = {OK: "  OK ", BAD: " FAIL", WARN: " WARN"}[verdict]
        print(f"[{mark}] {name}{': ' + detail if detail else ''}")
        return verdict

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"        - {text}")


class OrderGuard:
    """Replaces mt5.order_send for the duration of the test."""

    def __init__(self) -> None:
        self.attempts = 0

    def __call__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.attempts += 1
        raise AssertionError(
            "connection_test attempted to send an order. This test is read-only; "
            "aborting rather than trading."
        )


def describe_config(settings: Settings, report: Report) -> None:
    print("\n--- 1. bridge/.env configuration " + "-" * 44)
    env_file = ROOT / ".env"
    if not env_file.exists():
        report.record("Config file", BAD, f"{env_file} not found")
        return

    print(f"        .env found at {env_file}")
    try:
        import MetaTrader5

        print(f"        MetaTrader5 package {getattr(MetaTrader5, '__version__', '?')}")
    except ImportError:
        print("        MetaTrader5 package NOT INSTALLED")
    print(f"        MT5_LOGIN            = {settings.mt5_login}")
    print(f"        MT5_SERVER           = {settings.mt5_server}")
    print(f"        MT5_PASSWORD         = {'set' if settings.mt5_password else 'NOT SET'}"
          "  (never printed)")
    print(f"        MT5_TERMINAL_PATH    = {settings.mt5_terminal_path or '(auto-detect)'}")
    print(f"        RISK_ALLOWED_SYMBOLS = {', '.join(settings.allowed_symbol_list) or '(any)'}")
    print(f"        ALLOW_LIVE_TRADING   = {settings.allow_live_trading}")
    print(f"        BOT_ENABLED          = {settings.bot_enabled}")
    print(f"        BOT_DRY_RUN          = {settings.bot_dry_run}")

    if not settings.has_credentials:
        report.record(
            "Config file", WARN,
            "MT5_LOGIN/MT5_PASSWORD/MT5_SERVER are not all set — the bridge will "
            "attach to whichever account the terminal is already logged into",
        )
    else:
        report.record("Config file", OK, "credentials present")


async def check_account(
    session: MT5Session, expected_login: int | None, expected_server: str | None, report: Report
) -> None:
    print("\n--- 2. account " + "-" * 62)
    info = await session.run(lambda mt5: mt5.account_info())
    if info is None:
        report.record("Account", BAD, "account_info() returned nothing")
        report.record("Server", BAD, "unknown")
        return

    print(f"        login    = {info.login}")
    print(f"        server   = {info.server}")
    print(f"        name     = {info.name}")
    print(f"        currency = {info.currency}   balance = {info.balance}   equity = {info.equity}")
    print(f"        mode     = {session.trade_mode_name}")

    if expected_login is None or int(info.login) == int(expected_login):
        report.record("Account", OK, f"{info.login}")
    else:
        report.record("Account", BAD, f"connected to {info.login}, expected {expected_login}")

    if expected_server is None or str(info.server).strip() == expected_server.strip():
        report.record("Server", OK, f"{info.server}")
    else:
        report.record("Server", BAD, f"connected to '{info.server}', expected '{expected_server}'")

    if session.is_demo:
        report.record("Demo account", OK, session.trade_mode_name or "demo")
    else:
        report.record(
            "Demo account", BAD,
            f"account reports '{session.trade_mode_name}' — the bridge refuses to trade it",
        )


async def check_symbol(session: MT5Session, symbol: str, report: Report) -> bool:
    print(f"\n--- 3. {symbol} " + "-" * (62 - len(symbol)))
    try:
        info = await market.ensure_symbol(session, symbol)
    except Exception as error:  # noqa: BLE001 - report, do not crash
        report.record(f"{symbol}", BAD, f"not available: {error}")
        return False

    print(f"        digits = {info.get('digits')}   point = {info.get('point')}")
    print(f"        volume min/step/max = {info.get('volume_min')} / "
          f"{info.get('volume_step')} / {info.get('volume_max')}")

    tick = await market.get_tick(session, symbol)
    bid, ask = float(tick["bid"]), float(tick["ask"])
    point = float(info.get("point") or 0.01)
    quoted_at = datetime.fromtimestamp(int(tick.get("time", 0)), tz=timezone.utc)
    age = datetime.now(tz=timezone.utc) - quoted_at

    print(f"        bid = {bid}   ask = {ask}   spread = {(ask - bid) / point:.0f} points")
    print(f"        quoted at {quoted_at:%Y-%m-%d %H:%M:%S} UTC ({age.total_seconds():.0f}s ago)")

    if bid <= 0 or ask <= 0:
        report.record(f"{symbol}", BAD, "quote has no price")
        return False
    if age > FRESH_TICK:
        report.record(
            f"{symbol}", WARN,
            f"quote is {age.total_seconds() / 60:.0f} minutes old — market closed, or the "
            "symbol is not subscribed in Market Watch",
        )
        return True

    report.record(f"{symbol}", OK, f"live quote {bid}/{ask}")
    return True


async def check_timeframes(
    session: MT5Session, symbol: str, settings: Settings, report: Report
) -> bool:
    print("\n--- 4. timeframes " + "-" * 59)
    wanted = [
        (settings.strategy_trend_timeframe, settings.strategy_trend_candles, 210),
        (settings.strategy_structure_timeframe, settings.strategy_structure_candles, 60),
        (settings.strategy_trigger_timeframe, settings.strategy_trigger_candles, 60),
    ]
    all_good = True

    for timeframe, count, needed in wanted:
        label = f"{timeframe} data"
        try:
            candles = await signal_pipeline.closed_candles(
                session, symbol=symbol, timeframe=timeframe, count=count
            )
        except Exception as error:  # noqa: BLE001
            report.record(label, BAD, str(error))
            all_good = False
            continue

        if len(candles) == 0:
            report.record(label, BAD, "no candles returned")
            all_good = False
            continue

        newest = datetime.fromisoformat(str(candles.time[-1]).replace("Z", "+00:00"))
        print(f"        {timeframe}: {len(candles)} closed bars, newest closed "
              f"{newest:%Y-%m-%d %H:%M} UTC, last close {candles.close[-1]}")

        if len(candles) < needed:
            report.record(
                label, BAD,
                f"{len(candles)} closed bars, the strategy needs {needed}",
            )
            all_good = False
        else:
            report.record(label, OK, f"{len(candles)} closed bars")

    return all_good


async def check_signal(
    session: MT5Session, settings: Settings, symbol: str, report: Report
) -> None:
    print("\n--- 5. signal engine " + "-" * 56)
    try:
        signal = await signal_pipeline.generate(session, settings, symbol=symbol)
    except Exception as error:  # noqa: BLE001
        report.record("Signal engine", BAD, f"{type(error).__name__}: {error}")
        return

    print(f"        direction    = {signal['direction']}")
    print(f"        signal score = {signal['signal_score']} (needs {signal['min_score']})")
    print(f"        entry        = {signal['entry']}")
    print(f"        stop loss    = {signal['stop_loss']}")
    print(f"        take profit  = {signal['take_profit']}")
    print(f"        risk/reward  = {signal['risk_reward']}")
    print(f"        aligned      = {signal['timeframe_confirmation']['aligned']}")
    for role, read in signal["timeframe_confirmation"].get("roles", {}).items():
        print(f"        {role:10} {read['timeframe']:4} {read['bias']}")
    print("        reasons:")
    for reason in signal["reasons"]:
        print(f"          - {reason}")

    if signal["direction"] not in {"BUY", "SELL", "NO_TRADE"}:
        report.record("Signal engine", BAD, f"unexpected direction {signal['direction']!r}")
        return

    # A NO_TRADE verdict is a working engine, not a failure.
    report.record(
        "Signal engine", OK,
        f"{signal['direction']} at score {signal['signal_score']}",
    )
    if signal["direction"] == "NO_TRADE":
        report.note("NO_TRADE is a valid result — the engine ran and declined to trade.")


async def check_untouched(session: MT5Session, before: tuple[int, int], report: Report) -> None:
    print("\n--- 6. nothing was touched " + "-" * 50)
    positions = await session.run(lambda mt5: mt5.positions_get()) or ()
    orders = await session.run(lambda mt5: mt5.orders_get()) or ()
    after = (len(positions), len(orders))

    print(f"        open positions: {before[0]} before, {after[0]} after")
    print(f"        pending orders: {before[1]} before, {after[1]} after")

    if after == before:
        report.record("Account untouched", OK, "no positions or orders changed")
    else:
        report.record("Account untouched", BAD, f"{before} -> {after}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", type=int, default=None, help="Expected account number.")
    parser.add_argument("--server", default=None, help="Expected broker server name.")
    parser.add_argument("--symbol", default="XAUUSD")
    args = parser.parse_args()

    report = Report()
    # Load .env by absolute path. pydantic-settings resolves a relative env_file
    # against the working directory, so running this from anywhere but bridge/
    # would silently load no credentials while the file sat right there.
    settings = Settings(_env_file=ROOT / ".env")

    print("=" * 78)
    print("MT5 DEMO CONNECTION TEST — read-only, places no orders")
    print("=" * 78)
    print(f"python {sys.version.split()[0]}  |  {sys.platform}  |  cwd {Path.cwd()}")

    describe_config(settings, report)

    # Belt and braces: make trading impossible for the rest of this process.
    guard = OrderGuard()
    try:
        mt5_module = import_mt5()
    except Exception as error:  # noqa: BLE001
        report.record("MT5 connection", BAD, str(error))
        summarise(report, guard)
        return 1
    mt5_module.order_send = guard

    print("\n--- connecting " + "-" * 62)
    session = MT5Session(settings)
    try:
        await session.connect()
    except Exception as error:  # noqa: BLE001
        report.record("MT5 connection", BAD, str(error))
        print("\n        The terminal must be running and logged in on this machine,")
        print("        with Tools > Options > Expert Advisors > 'Allow algorithmic")
        print("        trading' enabled, before the bridge can attach.")
        summarise(report, guard)
        return 1

    terminal = await session.run(lambda mt5: mt5.terminal_info())
    print(f"        terminal build {getattr(terminal, 'build', '?')}, "
          f"connected={getattr(terminal, 'connected', '?')}, "
          f"algo trading allowed={getattr(terminal, 'trade_allowed', '?')}")
    report.record("MT5 connection", OK, "attached to the running terminal")

    try:
        positions = await session.run(lambda mt5: mt5.positions_get()) or ()
        orders = await session.run(lambda mt5: mt5.orders_get()) or ()
        before = (len(positions), len(orders))

        await check_account(session, args.login, args.server, report)
        symbol_ok = await check_symbol(session, args.symbol, report)
        data_ok = await check_timeframes(session, args.symbol, settings, report)

        if symbol_ok and data_ok:
            await check_signal(session, settings, args.symbol, report)
        else:
            report.record("Signal engine", BAD, "skipped — symbol or candle data unavailable")

        await check_untouched(session, before, report)
    finally:
        await session.shutdown()

    summarise(report, guard, settings)
    return 0 if all(v != BAD for v in report.lines.values()) else 1


def summarise(report: Report, guard: OrderGuard, settings: Settings | None = None) -> None:
    print("\n" + "=" * 78)
    print("RESULT")
    print("=" * 78)
    for name, verdict in report.lines.items():
        print(f"  {name:<20} {verdict}")

    if settings is not None:
        print(f"  {'Bot':<20} STOPPED (no loop runs in this test process)")
        print(f"  {'BOT_ENABLED':<20} {str(settings.bot_enabled).upper()}")
        print(f"  {'Dry run':<20} {'ON' if settings.bot_dry_run else 'OFF'}")
        print(f"  {'Live trading flag':<20} "
              f"{'ON' if settings.allow_live_trading else 'OFF (demo only)'}")
    print(f"  {'Orders placed':<20} {guard.attempts}")

    if guard.attempts:
        print("\n  !! An order send was attempted and blocked. Report this — it is a bug.")
    if report.notes:
        print("\nNotes:")
        for note in report.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
