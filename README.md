# MT5 Trading Desk

A Next.js trading UI backed by a FastAPI MetaTrader 5 bridge. Every number on
screen — account, quotes, candles, positions, order results — comes from a real
MT5 terminal. There is no demo or mock data path in the application.

```
Browser ──▶ Next.js route handlers ──▶ FastAPI bridge ──▶ MetaTrader 5 terminal ──▶ broker
           /api/mt5/*                  bridge/            (Windows host)
           holds MT5_BRIDGE_TOKEN       X-API-Key / Bearer
```

The browser never reaches the bridge. `MT5_BRIDGE_URL` and `MT5_BRIDGE_TOKEN`
are read only inside `lib/bridge.ts`, which imports `server-only`, so importing
it from a client component is a build error and the token cannot end up in
browser JavaScript.

| | |
| --- | --- |
| `app/`, `components/`, `lib/`, `hooks/` | Next.js UI and server-side proxy |
| `bridge/` | FastAPI ↔ MetaTrader 5 bridge ([its README](bridge/README.md)) |

## Running it

**1. The bridge** (on the Windows machine with MetaTrader 5 installed):

```bash
cd bridge
pip install -r requirements.txt
cp .env.example .env            # MT5 credentials + API_KEYS + TLS certificate
python scripts/generate_dev_cert.py --out certs
python run.py                   # https://localhost:8443
```

**2. The UI:**

```bash
npm install
cp .env.example .env.local      # MT5_BRIDGE_URL + MT5_BRIDGE_TOKEN (= the bridge's API_KEYS)
npm run dev                     # http://localhost:3000
```

`MT5_BRIDGE_TOKEN` must match one of the bridge's `API_KEYS`. If the bridge uses
a self-signed certificate, point `MT5_BRIDGE_CA_CERT` at `bridge/certs/cert.pem`
so TLS still verifies.

## Server-side routes

The UI only ever calls these. Each one proxies to the bridge and returns
`{ ok: true, data }` or `{ ok: false, error: { code, message, offline } }`.

| Route | Bridge call | Purpose |
| --- | --- | --- |
| `GET /api/mt5/status` | `GET /health` + `/health/ready` | Bridge reachable, terminal connected, account, safety flag |
| `GET /api/mt5/account` | `GET /account` | Balance, equity, margin, free margin, status |
| `GET /api/mt5/symbols` | `GET /symbols` | Instrument list with lot limits |
| `GET /api/mt5/tick/{symbol}` | `GET /tick/{symbol}` | Live bid/ask |
| `GET /api/mt5/candles` | `GET /candles` | OHLC candles for the chart |
| `GET /api/mt5/positions` | `GET /positions` | Real open positions |
| `GET /api/mt5/risk` | `GET /risk` | Risk limits, today's P/L, remaining loss budget |
| `POST /api/mt5/orders` | `POST /orders` | Market / limit / stop, with volume, SL and TP |
| `POST /api/mt5/positions/{ticket}/close` | `POST /positions/{ticket}/close` | Close a real position |

## The safety flag

`MT5_ALLOW_LIVE_ORDERS` is the server-side master switch for execution, and it
ships **off**. While it is off:

* `POST /api/mt5/orders` still sends the order to the bridge, but as a
  `dry_run`, so MT5's `order_check` verdict (retcode, comment, margin) comes
  back for real. The route answers **HTTP 423** and the UI shows *"Not sent to
  the market — live execution disabled"* next to the actual MT5 retcode.
  Nothing reaches the market and no success is invented.
* `POST /api/mt5/positions/{ticket}/close` is refused outright with 423 — there
  is no dry-run for a close, so the route never reports one that did not happen.
* Everything else — status, account, prices, candles, positions — is fully live.

Turn execution on only after you have confirmed the connection, account figures,
prices, candles and positions look right:

```bash
MT5_ALLOW_LIVE_ORDERS=true npm run start
```

The bridge keeps its own independent guard (`ALLOW_LIVE_TRADING`), which refuses
to trade on any account that is not a demo account.

## Risk policy

The bridge enforces a fixed risk policy before any order reaches the terminal,
and the desk mirrors it so the ticket cannot submit something certain to be
refused. Defaults, all configurable in `bridge/.env`:

| Limit | Default |
| --- | --- |
| Risk per trade (entry → stop loss) | 0.5% of balance |
| Maximum daily loss (realised + floating) | 2% of the day's opening balance |
| Maximum open positions | 2 |
| Maximum lot | 0.10 |
| Stop loss / take profit | both required |
| Tradable symbols | XAUUSD |
| Account type | demo only |

The Risk panel shows how much of today's loss budget is left and how many
position slots remain. A breach comes back as `403 risk_rejected` with the rule
that stopped it, and a `risk_per_trade` rejection includes the largest volume
that would have fitted. Details are in the [bridge README](bridge/README.md#risk-policy).

## Connection states

The header badge is the single source of truth, and never shows green unless the
terminal is actually connected:

| Badge | Meaning |
| --- | --- |
| `Bridge connected · demo #123456` | Bridge reachable and the MT5 terminal is logged in |
| `Bridge up · terminal disconnected` | The bridge answered but has no terminal session |
| `MT5 Bridge Offline` | The bridge did not respond — panels say so instead of showing stale or fake data |
| `Bridge not configured` | `MT5_BRIDGE_URL` / `MT5_BRIDGE_TOKEN` are missing on the server |

Panels keep the last good value on a transient refresh failure and label it as
stale; they never substitute placeholder numbers.

## Development without a Windows host

MetaTrader 5's Python package is Windows-only. To work on the UI elsewhere, run
the bridge's real application code against the stub terminal from its test
suite:

```bash
cd bridge
API_KEYS=dev-token ALLOW_INSECURE_HTTP=true python tests/serve_with_stub_terminal.py --port 8443
```

Quotes and fills are then synthetic and the harness says so on startup. It is
dev tooling only — `python run.py` always talks to a real terminal, and the
application itself has no mock path.

## Checks

```bash
npm run typecheck && npm run build     # UI
cd bridge && pytest                    # bridge (40 tests)
```
