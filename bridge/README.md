# MetaTrader 5 FastAPI Bridge

An HTTPS bridge that exposes a MetaTrader 5 terminal over a small REST API:
fetch candles and quotes, place and manage orders, read positions and history.
Built for **demo accounts** — the bridge refuses to trade on a live account
unless you explicitly opt in.

```
HTTP client  ──HTTPS──▶  FastAPI (this directory)  ──IPC──▶  MetaTrader 5 terminal  ──▶  broker
                         X-API-Key / Bearer auth            (must run on the same Windows host)
```

The trading UI in the repository root is the intended client; see the
[root README](../README.md) for running both halves together.

## Requirements

* **Windows** with the MetaTrader 5 terminal installed and logged into your demo
  account. The official `MetaTrader5` package only ships Windows wheels and talks
  to the terminal over local IPC, so the bridge has to run on the same machine.
  (The code imports and its tests run fine on Linux/macOS — only a live
  connection needs Windows.)
* Python 3.10+
* In the terminal: **Tools → Options → Expert Advisors → Allow algorithmic
  trading**, and the **AutoTrading** toolbar button switched on. Without it the
  terminal rejects every order and the bridge returns `403 trading_not_allowed`.

## Setup

```bash
git clone <this repo> && cd Jamil/bridge
python -m venv .venv && .venv\Scripts\activate      # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env                              # cp on POSIX
python -c "import secrets;print(secrets.token_urlsafe(32))"   # paste into API_KEYS
python scripts/generate_dev_cert.py --out certs     # self-signed cert for local HTTPS
python run.py
```

Then open <https://localhost:8443/docs> for the interactive API docs
(click *Authorize* and paste your API key).

`run.py` refuses to start if `API_KEYS` is empty, or if TLS is unconfigured and
`ALLOW_INSECURE_HTTP` is not set — an unauthenticated, unencrypted trading
endpoint is never a safe default.

## Configuration

All settings come from environment variables or `.env` (see `.env.example`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | – | Demo account credentials. Omit all three to attach to whatever account the terminal is already logged into. |
| `MT5_TERMINAL_PATH` | – | Path to `terminal64.exe`. Empty uses the last-used terminal. |
| `MT5_PORTABLE` | `false` | Launch the terminal in portable mode. |
| `MT5_CONNECT_ON_STARTUP` | `true` | Connect during startup instead of on first request. Startup never fails on a bad connection — `/health/ready` reports it and the next request retries. |
| `API_KEYS` | – | Comma-separated keys, accepted as `X-API-Key` or `Authorization: Bearer`. **Required.** |
| `HOST` / `PORT` | `0.0.0.0` / `8443` | Listen address. |
| `SSL_CERTFILE` / `SSL_KEYFILE` | – | TLS material. Set both to serve HTTPS directly. |
| `ALLOW_INSECURE_HTTP` | `false` | Serve plain HTTP — only when a reverse proxy terminates TLS. |
| `CORS_ORIGINS` | – | Comma-separated browser origins. Empty disables CORS entirely. |
| `ALLOW_LIVE_TRADING` | `false` | Required to trade on a non-demo account. |
| `MAX_VOLUME` | `1.0` | Per-order lot ceiling enforced before anything is sent. |
| `DEFAULT_DEVIATION` | `20` | Max slippage in points for market orders. |
| `DEFAULT_MAGIC` | `20260816` | Magic number stamped on orders from this bridge. |
| `RISK_ENABLED` | `true` | Master switch for the risk policy below. |
| `RISK_PER_TRADE_PCT` | `0.5` | Money between entry and stop loss, as a % of balance. |
| `RISK_MAX_DAILY_LOSS_PCT` | `2.0` | Realised + floating loss for the day, as a % of the day's opening balance. |
| `RISK_MAX_POSITIONS` | `2` | Open positions allowed at once. |
| `RISK_MAX_LOT` | `0.10` | Per-order lot ceiling (effective cap is the lower of this and `MAX_VOLUME`). |
| `RISK_REQUIRE_SL` / `RISK_REQUIRE_TP` | `true` | Refuse orders without protective levels. |
| `RISK_ALLOWED_SYMBOLS` | `XAUUSD` | Comma-separated allowlist for orders. Empty allows all. |
| `RISK_MAX_SPREAD_POINTS` | `50` | Refuse market orders while the spread is wider than this. 0 disables. |
| `RISK_CHECK_MARGIN` | `true` | Refuse orders whose required margin exceeds free margin. |
| `PREFLIGHT_ORDER_CHECK` | `true` | Run `order_check()` before `order_send()`. |
| `SIGNAL_TIMEFRAME` / `SIGNAL_CANDLES` | `M15` / `300` | What the analysis pipeline reads. |
| `SIGNAL_MIN_CONFIDENCE` | `60` | Confidence needed before a setup is proposed. |
| `SIGNAL_SL_ATR_MULTIPLE` / `SIGNAL_REWARD_RATIO` | `1.5` / `2.0` | Stop distance in ATR, and the reward-to-risk target. |
| `SIGNAL_MIN_EFFICIENCY` | `0.25` | Efficiency ratio below which the market reads as ranging. |
| `BOT_ENABLED` | `false` | Whether `/bot/start` may run the loop at all. |
| `BOT_DRY_RUN` | `true` | A running bot records decisions and sends nothing until this is false. |
| `BOT_MODE` | `bar` | `bar` decides once per closed candle; `interval` every poll. |
| `BOT_POLL_SECONDS` | `15` | How often the loop looks. |
| `BOT_MAX_TRADES_PER_DAY` | `5` | Hard ceiling on the bot's trades per day. |

## Endpoints

Every endpoint except `GET /health` requires the API key, sent either as
`X-API-Key: <key>` or `Authorization: Bearer <key>`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness. No auth. |
| `GET` | `/health/ready` | Terminal connectivity, account login and demo/real mode. `503` when disconnected. |
| `GET` | `/api/v1/account` | Balance, equity, free margin, leverage, currency. |
| `GET` | `/api/v1/symbols?search=EUR` | Tradable symbols with lot limits and digits. |
| `GET` | `/api/v1/symbols/{symbol}` | Full symbol specification. |
| `GET` | `/api/v1/tick/{symbol}` | Latest bid/ask. |
| `GET` | `/api/v1/candles` | OHLC candles (see below). |
| `POST` | `/api/v1/orders` | Place a market or pending order. |
| `GET` | `/api/v1/orders` | Open pending orders. |
| `DELETE` | `/api/v1/orders/{ticket}` | Cancel a pending order. |
| `GET` | `/api/v1/positions` | Open positions. |
| `POST` | `/api/v1/positions/{ticket}/close` | Close fully or partially. |
| `PATCH` | `/api/v1/positions/{ticket}` | Move stop loss / take profit. |
| `GET` | `/api/v1/signal?symbol=XAUUSD` | Run the analysis pipeline. Read-only. |
| `GET` | `/api/v1/risk` | Risk limits, today's P/L and the remaining loss budget. |
| `GET` | `/api/v1/history/deals` | Closed deals (defaults to the last 7 days). |

The same operations are also served on a compact, verb-shaped surface. These are
aliases over the identical service layer — same risk policy, same pre-flight:

| Method | Path | Same as |
| --- | --- | --- |
| `GET` | `/account` | `/api/v1/account` |
| `GET` | `/market/{symbol}` | symbol spec + quote + candles in one response |
| `GET` | `/positions` | `/api/v1/positions` |
| `GET` | `/orders` | `/api/v1/orders` |
| `POST` | `/trade/buy` | `/api/v1/orders` with `side: buy` |
| `POST` | `/trade/sell` | `/api/v1/orders` with `side: sell` |
| `POST` | `/position/close` | `/api/v1/positions/{ticket}/close`, ticket in the body |
| `POST` | `/bot/start` | start the trading loop |
| `POST` | `/bot/stop` | stop it |
| `GET` | `/bot/status` | what it is doing and has done |

### Candles

```bash
# The 500 most recent M15 bars, oldest first
curl --cacert certs/cert.pem -H "X-API-Key: $KEY" \
  "https://localhost:8443/api/v1/candles?symbol=EURUSD&timeframe=M15&count=500"

# An explicit time range
curl --cacert certs/cert.pem -H "X-API-Key: $KEY" \
  "https://localhost:8443/api/v1/candles?symbol=EURUSD&timeframe=H1\
&start=2026-08-01T00:00:00Z&end=2026-08-08T00:00:00Z"
```

```json
{
  "symbol": "EURUSD",
  "timeframe": "M15",
  "count": 2,
  "candles": [
    {"time": "2026-08-16T09:30:00Z", "open": 1.085, "high": 1.0855, "low": 1.0846,
     "close": 1.0852, "tick_volume": 812, "spread": 8, "real_volume": 0}
  ]
}
```

Timeframes: `M1 M2 M3 M4 M5 M6 M10 M12 M15 M20 M30 H1 H2 H3 H4 H6 H8 H12 D1 W1 MN1`.
Query shapes: `count` (+ optional `offset`) for the newest bars, `start`+`count`
for a forward window, `start`+`end` for a full range. The last bar of a "newest"
query is the one still forming. Timestamps are the terminal's server time,
serialised as UTC — most brokers run a UTC+2/+3 server clock, so compare against
`/api/v1/tick/{symbol}` rather than assuming true UTC.

### Placing orders

```bash
# Market buy with stops
curl --cacert certs/cert.pem -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -X POST https://localhost:8443/api/v1/orders -d '{
    "symbol": "EURUSD", "side": "buy", "volume": 0.10,
    "sl": 1.0800, "tp": 1.0900, "comment": "demo entry"
  }'

# Validate margin/stops without sending anything (order_check)
... -d '{"symbol":"EURUSD","side":"buy","volume":0.10,"dry_run":true}'

# Pending sell limit
... -d '{"symbol":"EURUSD","side":"sell","volume":0.20,"type":"limit","price":1.0950}'
```

Order body fields: `symbol`, `side` (`buy`/`sell`), `volume`, `type`
(`market`/`limit`/`stop`/`stop_limit`), `price` (pending only),
`stop_limit_price`, `sl`, `tp`, `deviation`, `magic`, `comment`, `type_time`
(`gtc`/`day`/`specified`), `expiration`, `filling` (`fok`/`ioc`/`return`),
`dry_run`.

The bridge fills in what MT5 requires and you shouldn't have to: market orders
are priced at the live ask/bid, volumes are snapped to the symbol's lot step,
prices are rounded to the symbol's digits, and the filling mode defaults to
whatever the symbol advertises (FOK, else IOC).

A successful response carries the terminal's result verbatim plus the request
that was sent:

```json
{"retcode": 10009, "retcode_description": "Request completed", "success": true,
 "order": 500123, "deal": 500124, "volume": 0.1, "price": 1.08508,
 "dry_run": false, "sent_request": {"action": 1, "symbol": "EURUSD", "...": "..."}}
```

### Managing positions

```bash
curl ... https://localhost:8443/api/v1/positions
curl ... -X POST https://localhost:8443/api/v1/positions/500123/close -d '{"volume": 0.05}'
curl ... -X PATCH https://localhost:8443/api/v1/positions/500123 -d '{"sl": 1.0830}'
```

`PATCH` only changes the level you send — omitting `tp` keeps the existing one
rather than clearing it. Send `0` to remove a level.

## Errors

Failures return a consistent envelope, never a bare 500:

```json
{"error": "trade_rejected", "message": "Trade rejected by the server: Not enough money to complete the request",
 "details": {"retcode": 10019, "retcode_description": "...", "sent_request": {"...": "..."}}}
```

| Status | `error` | When |
| --- | --- | --- |
| 401 / 403 | – | Missing or wrong API key. |
| 403 | `trading_not_allowed` | Live account without `ALLOW_LIVE_TRADING`, volume over `MAX_VOLUME`, or AutoTrading off in the terminal. |
| 404 | `symbol_not_found` / `not_found` | Unknown symbol, position or order ticket. |
| 422 | `invalid_request` | Bad request shape, or a volume outside the symbol's limits. |
| 403 | `risk_rejected` | The order breached the risk policy. `details.rule` names the limit. |
| 400 | `trade_rejected` | The terminal accepted the call, the trade server said no. MT5 retcode included. |
| 502 | `terminal_call_failed` | An MT5 call failed; `mt5.last_error()` is in `details`. |
| 503 | `terminal_unavailable` | The terminal is closed, not installed, or the IPC link dropped. The connection is retried on the next request. |

## Risk policy

Every order — including dry runs — is checked before it reaches the terminal.
The first breach refuses the order with `403 risk_rejected` and `details.rule`
naming the limit that stopped it:

| Rule | Default | Checks |
| --- | --- | --- |
| `allowed_symbols` | `XAUUSD` | The symbol is on the allowlist. |
| `require_sl` / `require_tp` | on | Both protective levels are present. |
| `max_lot` | `0.10` | Volume is within the lot ceiling. |
| `max_positions` | `2` | Fewer positions open than the limit. |
| `max_spread` | `50 pts` | The live spread is inside the limit (market orders only — a pending order fills at a spread nobody can measure now). |
| `margin` | on | `order_calc_margin()` fits inside free margin. |
| `max_daily_loss` | `2%` | Realised + floating loss for the day is under budget. |
| `risk_per_trade` | `0.5%` | Entry-to-stop distance costs no more than this share of balance, priced from the symbol's tick value. A rejection includes `suggested_volume`, the largest size that would fit. |

`GET /api/v1/risk` returns the same figures the checks use — today's realised and
floating P/L, the remaining loss budget, open position slots and the limits
themselves — so a dashboard can show how much room is left before an order is
refused.

The daily window is the server-day boundary (MT5 reports broker-server time),
and only trading deals count towards it: deposits, withdrawals and credits are
excluded.

## order_check before order_send

Every live order is validated by the terminal before it is sent:

    risk policy -> order_check() -> order_send() -> MT5

A non-zero `order_check` retcode refuses the order with `400 trade_rejected` and
`details.stage = "order_check"`, and nothing is sent. Accepted orders carry the
check's `margin` and `margin_free` back under `preflight`. Set
`PREFLIGHT_ORDER_CHECK=false` for a broker whose `order_check` misbehaves.

## Analysis pipeline

`GET /api/v1/signal?symbol=XAUUSD&timeframe=M15` runs:

    market data -> trend -> support/resistance -> momentum -> volatility
                -> setup -> confidence -> risk manager -> TRADE / NO TRADE

| Stage | What it measures |
| --- | --- |
| Trend | EMA 20/50/200 separation and slope, both in ATR, filtered by Kaufman's efficiency ratio so an oscillation cannot pass as a trend. |
| Support / resistance | Fractal swing pivots clustered into levels; reports room to the nearest level on each side, in ATR. |
| Momentum | RSI (Wilder) and the MACD histogram, discounted when RSI is stretched. |
| Volatility | ATR and its percentile against recent history; an extreme reading stands the pipeline down. |
| Setup | Requires trend and momentum to agree in a tradable regime. Stop is `SIGNAL_SL_ATR_MULTIPLE` × ATR, target `SIGNAL_REWARD_RATIO` × the stop, capped at the level that would block it. |
| Confidence | Transparent weighted blend of the stage scores (trend .35, momentum .30, S/R .20, volatility .15), 0-100. |
| Risk manager | The proposal is sized from `RISK_PER_TRADE_PCT` and run through the same policy that guards `POST /orders`. |

The response carries every stage's numbers and a plain-language note, so a
verdict can always be traced to what produced it. A setup vetoed by the risk
manager is still reported, with `risk.passed = false` and the rule that stopped
it.

**This endpoint never trades.** It returns a `proposal` — pass it to
`POST /orders` to act on it, which re-runs the whole policy. The confidence
score is a weighted blend, not a learned model; swap `score_confidence` in
`app/analysis/signal.py` if you want a real one behind that slot.

## The bot

`POST /bot/start` runs the analysis pipeline on a cadence and hands any proposal
to the same `place_order` path a human uses:

    signal pipeline -> risk manager -> order_check() -> order_send() -> MT5

It owns no trading logic of its own — it decides *when* to look, not what is a
good trade — so every order it sends passes the identical risk policy,
pre-flight and demo guard.

Two independent gates, both safe by default:

| Gate | Default | Effect |
| --- | --- | --- |
| `BOT_ENABLED` | `false` | `/bot/start` refuses with `403 bot_not_allowed`. |
| `BOT_DRY_RUN` | `true` | A running bot records the trades it would have taken and sends nothing. |

In `bar` mode (the default) the loop decides once per closed candle, and
deliberately skips the bar that was already forming when it started — the first
decision comes from a candle that closed under its watch. `interval` mode
decides on every poll instead.

`POST /bot/stop` is idempotent and **leaves open positions exactly as they
are**: it stops the bot opening more, it does not close anything. The loop is
also stopped during application shutdown, so a terminal never goes away
mid-order.

`GET /bot/status` reports what it is watching, its last decision and why, the
trades it took (or would have taken), and the tail of its activity — including
the setups the risk manager refused.

## Safety model

* **Demo-only by default.** Every trading path checks `account_info().trade_mode`
  first and refuses anything that is not a demo/contest account unless
  `ALLOW_LIVE_TRADING=true`.
* **Volume ceiling.** `MAX_VOLUME` is enforced before the order is built, so a
  misplaced decimal point cannot reach the broker.
* **API key required.** Keys are compared with `secrets.compare_digest`, and the
  server refuses to boot without one.
* **HTTPS by default.** Plain HTTP takes a deliberate `ALLOW_INSECURE_HTTP=true`.
* **`dry_run`** routes an order through `order_check` so you can validate margin
  and stops without touching the market.

Self-signed certificates are fine for `localhost`. If you expose the bridge
beyond the machine it runs on, put it behind a real certificate, bind `HOST` to
a private interface, and treat the API key as the credential to your account
that it is.

## Design notes

The `MetaTrader5` package keeps process-global state and is not thread-safe, so
`MT5Session` (`app/mt5/session.py`) owns a single worker thread and funnels every
terminal call through it. That keeps the blocking IPC calls off the event loop
and guarantees they are serialised. Connection loss is detected from
`mt5.last_error()` and the session reconnects on the next request.

```
app/
  config.py          settings (env / .env)
  security.py        X-API-Key dependency
  errors.py          error types -> JSON envelope
  schemas.py         request/response models
  mt5/session.py     connection + single-threaded call plumbing
  mt5/market.py      symbols, candles, ticks
  mt5/trading.py     orders, positions, history, guard rails
  routers/           HTTP layer
run.py               uvicorn entrypoint with TLS
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite injects `tests/fake_mt5.py` as the `MetaTrader5` module, so it runs on
any OS with no terminal and no account: order construction, volume snapping,
filling-mode selection, close/modify, retcode mapping, auth, and the demo-account
guard are all covered against a stand-in terminal.
