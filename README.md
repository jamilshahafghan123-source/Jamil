# MetaTrader 5 FastAPI Bridge

An HTTPS bridge that exposes a MetaTrader 5 terminal over a small REST API:
fetch candles and quotes, place and manage orders, read positions and history.
Built for **demo accounts** — the bridge refuses to trade on a live account
unless you explicitly opt in.

```
HTTP client  ──HTTPS──▶  FastAPI (this repo)  ──IPC──▶  MetaTrader 5 terminal  ──▶  broker
                          X-API-Key auth                (must run on the same Windows host)
```

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
git clone <this repo> && cd Jamil
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
| `API_KEYS` | – | Comma-separated keys accepted in the `X-API-Key` header. **Required.** |
| `HOST` / `PORT` | `0.0.0.0` / `8443` | Listen address. |
| `SSL_CERTFILE` / `SSL_KEYFILE` | – | TLS material. Set both to serve HTTPS directly. |
| `ALLOW_INSECURE_HTTP` | `false` | Serve plain HTTP — only when a reverse proxy terminates TLS. |
| `CORS_ORIGINS` | – | Comma-separated browser origins. Empty disables CORS entirely. |
| `ALLOW_LIVE_TRADING` | `false` | Required to trade on a non-demo account. |
| `MAX_VOLUME` | `1.0` | Per-order lot ceiling enforced before anything is sent. |
| `DEFAULT_DEVIATION` | `20` | Max slippage in points for market orders. |
| `DEFAULT_MAGIC` | `20260816` | Magic number stamped on orders from this bridge. |

## Endpoints

Every endpoint except `GET /health` requires `X-API-Key`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness. No auth. |
| `GET` | `/health/ready` | Terminal connectivity, account login and demo/real mode. `503` when disconnected. |
| `GET` | `/api/v1/account` | Balance, equity, free margin, leverage, currency. |
| `GET` | `/api/v1/symbols?search=EUR` | Tradable symbols with lot limits and digits. |
| `GET` | `/api/v1/symbols/{symbol}` | Full symbol specification. |
| `GET` | `/api/v1/ticks/{symbol}` | Latest bid/ask. |
| `GET` | `/api/v1/candles` | OHLC candles (see below). |
| `POST` | `/api/v1/orders` | Place a market or pending order. |
| `GET` | `/api/v1/orders` | Open pending orders. |
| `DELETE` | `/api/v1/orders/{ticket}` | Cancel a pending order. |
| `GET` | `/api/v1/positions` | Open positions. |
| `POST` | `/api/v1/positions/{ticket}/close` | Close fully or partially. |
| `PATCH` | `/api/v1/positions/{ticket}` | Move stop loss / take profit. |
| `GET` | `/api/v1/history/deals` | Closed deals (defaults to the last 7 days). |

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
`/api/v1/ticks/{symbol}` rather than assuming true UTC.

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
| 401 / 403 | – | Missing or wrong `X-API-Key`. |
| 403 | `trading_not_allowed` | Live account without `ALLOW_LIVE_TRADING`, volume over `MAX_VOLUME`, or AutoTrading off in the terminal. |
| 404 | `symbol_not_found` / `not_found` | Unknown symbol, position or order ticket. |
| 422 | `invalid_request` | Bad request shape, or a volume outside the symbol's limits. |
| 400 | `trade_rejected` | The terminal accepted the call, the trade server said no. MT5 retcode included. |
| 502 | `terminal_call_failed` | An MT5 call failed; `mt5.last_error()` is in `details`. |
| 503 | `terminal_unavailable` | The terminal is closed, not installed, or the IPC link dropped. The connection is retried on the next request. |

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
