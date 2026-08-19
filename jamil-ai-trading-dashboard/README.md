# Jamil AI Trading Dashboard

A professional dark-theme web dashboard for analysing and monitoring **GOLD (XAUUSD)**
trading through MetaTrader 5.

> ## ⚠️ Demo only
>
> This build is a **demo environment**. It contains **no real-money trading code path**.
> There is no order-placement function, no broker credential handling and no automatic
> execution anywhere in this repository. Trading controls are rendered in a disabled
> state so their status is visible, and they stay disabled until a later phase is
> explicitly configured and reviewed on both the frontend and the backend.
>
> All prices, balances, positions, trade history and AI output shown today are
> **locally generated sample data**, labelled as such on every panel.

---

## Architecture

The browser never connects to MetaTrader 5 directly:

```
Website (this app)
   ↓  HTTPS / JSON
Backend API            ← owns auth, risk enforcement, AI calls, caching
   ↓
MT5 Bridge             ← Windows host running the MetaTrader5 Python API
   ↓
MetaTrader 5 terminal
   ↓
Demo broker
```

The frontend talks only to the Backend API. Everything it needs is behind a small
service layer (`src/services/`), so switching from demo data to live data is an
environment-variable change — no component edits.

---

## Getting started

```bash
cd jamil-ai-trading-dashboard
npm install
npm run dev
```

Local URL: **http://localhost:5173/**

| Script            | What it does                                  |
| ----------------- | --------------------------------------------- |
| `npm run dev`     | Vite dev server with hot reload                |
| `npm run build`   | Type-check (`tsc -b`) then production build    |
| `npm run preview` | Serve the built `dist/` output                 |
| `npm run lint`    | ESLint over the whole project                  |

### Configuration

Copy `.env.example` to `.env`. With no backend URL set, the dashboard runs entirely on
demo data.

| Variable                | Default | Meaning                                                   |
| ----------------------- | ------- | --------------------------------------------------------- |
| `VITE_API_BASE_URL`     | *empty* | Base URL of the Backend API. Empty ⇒ demo data.           |
| `VITE_FORCE_DEMO_DATA`  | `true`  | Keep demo data even when a backend URL is set.            |
| `VITE_DEV_API_PROXY`    | —       | Dev-server proxy target for `/api` during `npm run dev`.  |
| `VITE_TRADING_ENABLED`  | `false` | Master switch for order UI. Not implemented in this build. |

To go live against the backend: set `VITE_API_BASE_URL=https://your-backend` and
`VITE_FORCE_DEMO_DATA=false`.

---

## Screens

| Route         | Contents                                                                   |
| ------------- | -------------------------------------------------------------------------- |
| `/`           | Full dashboard: market card, chart, AI analyst, account, positions, risk, connection |
| `/markets`    | GOLD quote, watchlist, large chart, timeframe reference                     |
| `/ai-analyst` | Expanded AI analysis with the chart and a "how to read this" guide          |
| `/positions`  | Positions table, account snapshot, risk limits                              |
| `/history`    | Closed demo trades with win rate, profit factor and filters                 |
| `/settings`   | Data source, architecture, safety policy, risk limits, connection status    |

---

## Project structure

```
src/
  components/
    account/      AccountPanel            – balance, equity, margin, today's P/L
    ai/           AiAnalystPanel          – bias, confidence, levels, scenario, explanation
    chart/        CandleChart, ChartPanel – lightweight-charts candles + volume
    layout/       AppShell, Header, SafetyBanner, PageHeading, Logo
    market/       GoldMarketCard          – price, bid, ask, spread, change, session
    positions/    PositionsTable
    risk/         RiskPanel               – risk limits and demo-trading status
    status/       ConnectionPanel         – backend / bridge / AI health
    ui/           Panel, Badge, Stat, Meter, Segmented, Toggle, RangeField, …
  context/        DashboardProvider       – one polling layer shared by every page
  demo/           marketEngine, analysisEngine, portfolio, timeframes, random
  services/       apiClient + one module per backend resource
  lib/            format, indicators, cn
  types/          shared domain types (mirror the API payloads)
```

### Demo data engine

`src/demo/marketEngine.ts` generates ~42 days of one-minute XAUUSD candles from a seeded
PRNG with a session-dependent volatility profile, then aggregates them into 5m/15m/30m/1h/4h
so every timeframe agrees on price. A tick loop advances the last candle once per second.

`src/demo/analysisEngine.ts` derives the AI panel from ordinary indicators (EMA stack, RSI,
ATR, clustered swing highs/lows). It is a stand-in for the backend AI service, not a model.

---

## Backend API — endpoints to build next

The service layer already calls these paths. Implementing them and pointing
`VITE_API_BASE_URL` at the backend is the whole integration.

### Market data

| Method | Path | Query | Returns |
| ------ | ---- | ----- | ------- |
| `GET` | `/api/v1/market/quote` | `symbol` | `Quote` — `bid`, `ask`, `price`, `spreadPoints`, `dayChange`, `dayChangePercent`, `dayHigh`, `dayLow`, `dayOpen`, `previousClose`, `session`, `digits`, `updatedAt` |
| `GET` | `/api/v1/market/candles` | `symbol`, `timeframe` (`1m…4h`), `limit` | `Candle[]` — `{ time (epoch seconds), open, high, low, close, volume }`, oldest first |
| `GET` | `/api/v1/market/symbols` | — | Tradable instruments for the watchlist |

### AI analysis

| Method | Path | Query | Returns |
| ------ | ---- | ----- | ------- |
| `GET` | `/api/v1/ai/analysis` | `symbol`, `timeframe` | `AiAnalysis` — `bias`, `confidence`, `trend`, `momentum`, `support[]`, `resistance[]`, `entryZone`, `stopLoss`, `takeProfit[]`, `riskReward`, `explanation`, `factors[]`, `generatedAt`, `modelName` |

The model call belongs on the backend so the API key never reaches the browser.

### Account & trading records

| Method | Path | Returns |
| ------ | ---- | ------- |
| `GET` | `/api/v1/account` | `AccountSnapshot` — `accountType` (must be `demo`), `balance`, `equity`, `margin`, `freeMargin`, `marginLevel`, `todayPnl`, `openPositions` |
| `GET` | `/api/v1/positions` | `Position[]` — symbol, direction, volume, entry, current, SL, TP, P/L, status |
| `GET` | `/api/v1/history/trades` | `HistoryTrade[]` — closed trades with `closeReason` |

### Risk

| Method | Path | Notes |
| ------ | ---- | ----- |
| `GET` | `/api/v1/risk/settings` | `RiskSettings` |
| `PUT` | `/api/v1/risk/settings` | Must **reject** `liveTradingEnabled: true` server-side. The UI is not the safety boundary. |

### Health

| Method | Path | Returns |
| ------ | ---- | ------- |
| `GET` | `/api/v1/health` | `{ backend, mt5Bridge, ai, lastMarketDataAt, errors[] }`, each service `{ state: 'connected' \| 'degraded' \| 'disconnected', detail, latencyMs }` |

### Recommended next steps

1. `GET /api/v1/health` first — it lights up the whole connection panel.
2. `GET /api/v1/market/quote` + `/candles` — the dashboard becomes live.
3. `GET /api/v1/account` + `/positions` — real demo-account state.
4. `GET /api/v1/ai/analysis` — move the analysis server-side.
5. `GET|PUT /api/v1/risk/settings` — persist limits and enforce them before the bridge.
6. Optional: replace polling with `WS /api/v1/stream` pushing `quote` / `candle` /
   `position` events. Only `DashboardProvider` would change.

Any future order endpoint must be demo-account-only, require a stop loss, be rejected
when the MT5 login is a live account, and stay behind an explicit configuration flag.

---

## Tech stack

React 19 · TypeScript 5.9 · Vite 7 · Tailwind CSS 4 · lightweight-charts 5 ·
react-router 7 · lucide-react
