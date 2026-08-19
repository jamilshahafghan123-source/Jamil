#!/usr/bin/env python3
"""Read-only end-to-end diagnostic for the MT5 integration.

Walks every hop of:

    You -> Backend API -> MT5 Bridge -> MetaTrader 5 -> XAUUSD

and reports exactly which hop fails and why.

SAFETY
------
This script only ever issues GET requests, plus one POST to
`/api/auth/login` if you supply credentials. It never calls /order or
/close and cannot place, modify, or close a trade. It never prints your
bridge token, password, or any account credential.

Usage (Windows, from the repo root):

    set MT5_BRIDGE_TOKEN=<your token>
    python tools\\diagnose_readonly.py

    # or point it somewhere else
    python tools\\diagnose_readonly.py --bridge http://127.0.0.1:8100 ^
        --backend http://localhost:8080 --email you@example.com --password ...

Only the standard library is used, so it runs anywhere Python does.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 10

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if os.name == "nt" and not os.environ.get("WT_SESSION"):
    # Old consoles render ANSI as garbage; plain text is better than noise.
    GREEN = RED = YELLOW = DIM = RESET = ""

_failures: list[str] = []
_warnings: list[str] = []


def ok(msg: str, detail: str = "") -> None:
    print(f"  {GREEN}[PASS]{RESET} {msg}" + (f"  {DIM}{detail}{RESET}" if detail else ""))


def fail(msg: str, hint: str = "") -> None:
    print(f"  {RED}[FAIL]{RESET} {msg}")
    if hint:
        print(f"         {YELLOW}fix:{RESET} {hint}")
    _failures.append(msg)


def warn(msg: str, hint: str = "") -> None:
    print(f"  {YELLOW}[WARN]{RESET} {msg}")
    if hint:
        print(f"         {DIM}{hint}{RESET}")
    _warnings.append(msg)


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def http(
    url: str, *, headers: dict | None = None, body: dict | None = None
) -> tuple[int, object, str]:
    """Return (status, parsed_json_or_None, error_text)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw), ""
            except json.JSONDecodeError:
                return r.status, None, raw[:200]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), raw[:300]
        except json.JSONDecodeError:
            return e.code, None, raw[:300]
    except urllib.error.URLError as e:
        return 0, None, str(e.reason)
    except Exception as e:  # socket errors, DNS, timeouts
        return 0, None, f"{type(e).__name__}: {e}"


def check_bridge(base: str, token: str, symbol: str) -> bool:
    section(f"HOP 1-2  Bridge -> MetaTrader 5   ({base})")

    status, body, err = http(f"{base}/health")
    if status == 0:
        fail(
            f"cannot reach the bridge: {err}",
            "Is bridge.py running? If the backend is in Docker, the bridge must "
            "bind BRIDGE_HOST=0.0.0.0 (not 127.0.0.1) to accept container traffic.",
        )
        return False
    if status != 200 or not isinstance(body, dict):
        fail(f"/health returned HTTP {status}: {err}")
        return False

    ok("bridge /health reachable", f"HTTP {status}")
    if body.get("mt5_connected") is True:
        ok("bridge reports mt5_connected=true")
    else:
        fail(
            "bridge is up but mt5_connected=false",
            "MetaTrader 5 must be running and logged in on this machine.",
        )
        return False

    if not token:
        warn(
            "no MT5_BRIDGE_TOKEN provided — skipping authenticated reads",
            "set MT5_BRIDGE_TOKEN to test /account, /tick, /bars, /positions",
        )
        return True

    hdr = {"X-Bridge-Token": token}

    status, body, err = http(f"{base}/account", headers=hdr)
    if status == 401:
        fail(
            "bridge rejected the token (401)",
            "MT5_BRIDGE_TOKEN must be byte-identical in run_bridge.bat and the "
            "backend .env. Watch for trailing spaces or quotes in the .bat file.",
        )
    elif status == 200 and isinstance(body, dict):
        mode = body.get("trade_mode")
        ok(
            "GET /account",
            f"login={body.get('login')} mode={mode} "
            f"balance={body.get('balance')} {body.get('currency')}",
        )
        if mode == "real":
            warn(
                "this MT5 account is a REAL-money account",
                "Keep BRIDGE_ALLOW_REAL=false. Prefer a demo login for testing.",
            )
        elif mode == "demo":
            ok("account trade_mode is 'demo'")
    else:
        fail(f"GET /account -> HTTP {status}: {err}")

    q = urllib.parse.urlencode({"symbol": symbol})
    status, body, err = http(f"{base}/tick?{q}", headers=hdr)
    if status == 200 and isinstance(body, dict):
        ok(
            f"GET /tick ({symbol})",
            f"bid={body.get('bid')} ask={body.get('ask')} "
            f"spread={body.get('spread_points')}pts",
        )
    elif status == 404:
        fail(
            f"no tick for {symbol} (404)",
            f"Add {symbol} to MT5 Market Watch (right-click > Symbols). The exact "
            "name may differ per broker, e.g. XAUUSD.m or GOLD.",
        )
    else:
        fail(f"GET /tick -> HTTP {status}: {err}")

    status, body, err = http(f"{base}/symbol?{q}", headers=hdr)
    if status == 200 and isinstance(body, dict):
        ok(
            f"GET /symbol ({symbol})",
            f"digits={body.get('digits')} contract={body.get('trade_contract_size')} "
            f"vol_min={body.get('volume_min')}",
        )
    else:
        fail(f"GET /symbol -> HTTP {status}: {err}")

    for tf in ("M1", "M5", "M15", "H1"):
        qq = urllib.parse.urlencode({"symbol": symbol, "timeframe": tf, "count": 50})
        status, body, err = http(f"{base}/bars?{qq}", headers=hdr)
        if status == 200 and isinstance(body, dict):
            bars = body.get("bars") or []
            if bars:
                ok(f"GET /bars {tf}", f"{len(bars)} bars, last close={bars[-1].get('close')}")
            else:
                fail(f"GET /bars {tf} returned 0 bars")
        else:
            fail(f"GET /bars {tf} -> HTTP {status}: {err}")

    status, body, err = http(f"{base}/positions?{q}", headers=hdr)
    if status == 200 and isinstance(body, dict):
        ok("GET /positions", f"{len(body.get('positions') or [])} open")
    else:
        fail(f"GET /positions -> HTTP {status}: {err}")

    return True


def check_backend(base: str, email: str, password: str) -> None:
    section(f"HOP 3-4  You -> Backend -> Bridge   ({base})")

    status, body, err = http(f"{base}/health")
    if status == 0:
        fail(f"cannot reach the backend: {err}", "Is the backend container running?")
        return
    ok("backend /health reachable", f"HTTP {status}")

    status, body, err = http(f"{base}/ready")
    if status == 200 and isinstance(body, dict):
        if body.get("bridge_connected"):
            ok("backend reports bridge_connected=true")
        else:
            fail(
                "backend cannot reach the bridge (bridge_connected=false)",
                "MT5_BRIDGE_URL is wrong *as seen from inside the container*. "
                "From Docker on Windows use http://host.docker.internal:8100. "
                "Verify with: docker compose config | findstr MT5_BRIDGE_URL",
            )
        if body.get("real_trading_allowed"):
            warn("backend has ALLOW_REAL_TRADING=true", "Set it to false for demo work.")
        else:
            ok("backend ALLOW_REAL_TRADING=false")
    else:
        fail(f"/ready -> HTTP {status}: {err}")

    if not (email and password):
        warn(
            "no --email/--password given — skipping authenticated API checks",
            "pass them to test /api/status and /api/dashboard",
        )
        return

    status, body, err = http(
        f"{base}/api/auth/login", body={"email": email, "password": password}
    )
    if status == 422:
        fail(
            "login rejected with 422 (missing query parameter)",
            "This is the rate-limiter dependency bug. Ensure deps.py builds the "
            "limiter with a closure (rate_limiter(...)) rather than a callable "
            "class, then rebuild the backend image.",
        )
        return
    if status == 401:
        fail("login rejected (401)", "Wrong email/password, or the user does not exist.")
        return
    if status != 200 or not isinstance(body, dict) or "access_token" not in body:
        fail(f"login -> HTTP {status}: {err}")
        return
    ok("POST /api/auth/login")
    hdr = {"Authorization": f"Bearer {body['access_token']}"}

    status, body, err = http(f"{base}/api/status", headers=hdr)
    if status == 200 and isinstance(body, dict):
        ok(
            "GET /api/status",
            f"bridge_connected={body.get('bridge_connected')} "
            f"bot_enabled={body.get('bot_enabled')} mode={body.get('trading_mode')}",
        )
        if not body.get("bot_enabled"):
            warn(
                "the agent is idle: bot_enabled=false",
                "Enable read-only analysis with trading_mode=MANUAL, then "
                "POST /api/risk/bot {\"enabled\": true}. MANUAL never executes.",
            )
        if body.get("emergency_stop"):
            warn("emergency_stop is engaged", "Clear it via /api/risk/emergency-stop/clear")
    else:
        fail(f"GET /api/status -> HTTP {status}: {err}")

    status, body, err = http(f"{base}/api/dashboard", headers=hdr)
    if status == 200 and isinstance(body, dict):
        tick = body.get("tick")
        acct = body.get("account")
        if tick and acct:
            ok(
                "GET /api/dashboard",
                f"XAUUSD bid={tick.get('bid')} ask={tick.get('ask')} | "
                f"equity={acct.get('equity')}",
            )
        else:
            fail(
                "dashboard returned null account/tick",
                "The endpoint swallows bridge errors. See /ready above for the cause.",
            )
    else:
        fail(f"GET /api/dashboard -> HTTP {status}: {err}")

    status, body, err = http(f"{base}/api/analysis/signals?limit=1", headers=hdr)
    if status == 200 and isinstance(body, list):
        if body:
            s = body[0]
            ok("GET /api/analysis/signals", f"latest: {s.get('action')} conf={s.get('confidence')}")
            if "ANTHROPIC_API_KEY" in str(s.get("reason") or ""):
                warn(
                    "the AI analyst is not configured",
                    "Set ANTHROPIC_API_KEY in the backend .env; until then every "
                    "signal is NO_TRADE. This does not affect market-data reads.",
                )
        else:
            warn("no signals recorded yet", "Signals appear after the agent runs a cycle.")
    else:
        fail(f"GET /api/analysis/signals -> HTTP {status}: {err}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only MT5 integration diagnostic.")
    ap.add_argument("--bridge", default=os.getenv("BRIDGE_URL", "http://127.0.0.1:8100"))
    ap.add_argument("--backend", default=os.getenv("BACKEND_URL", "http://localhost:8080"))
    ap.add_argument("--symbol", default=os.getenv("SYMBOL", "XAUUSD"))
    ap.add_argument("--token", default=os.getenv("MT5_BRIDGE_TOKEN", ""))
    ap.add_argument("--email", default=os.getenv("DIAG_EMAIL", ""))
    ap.add_argument("--password", default=os.getenv("DIAG_PASSWORD", ""))
    ap.add_argument("--skip-backend", action="store_true")
    args = ap.parse_args()

    print("MT5 integration diagnostic — READ-ONLY (never places or closes a trade)")
    print(f"{DIM}bridge={args.bridge}  backend={args.backend}  symbol={args.symbol}{RESET}")

    check_bridge(args.bridge.rstrip("/"), args.token, args.symbol)
    if not args.skip_backend:
        check_backend(args.backend.rstrip("/"), args.email, args.password)

    section("SUMMARY")
    if _failures:
        print(f"  {RED}{len(_failures)} check(s) failed:{RESET}")
        for f in _failures:
            print(f"    - {f}")
    else:
        print(f"  {GREEN}All checks passed.{RESET}")
    if _warnings:
        print(f"  {YELLOW}{len(_warnings)} warning(s):{RESET}")
        for w in _warnings:
            print(f"    - {w}")
    print()
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
