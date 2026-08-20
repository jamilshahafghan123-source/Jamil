# XAUUSD AI Trading Analyst

A cloud-deployable AI market analyst and risk-managed trade executor for
**MetaTrader 5** and **XAUUSD (gold)**.

React + TypeScript dashboard · Python/FastAPI backend · PostgreSQL · real MT5
integration via a Windows bridge · Google Cloud Run.

> **Ships in DEMO/MANUAL mode. Real-money trading is disabled and requires
> three independent, deliberate actions to enable.** See
> [Real trading](#real-trading-is-off-by-default).

---

## Read this first: why there is a "bridge"

The `MetaTrader5` Python package is a thin wrapper around the MT5 terminal's
**local Windows IPC**. It has no Linux or macOS builds and it requires the MT5
terminal running on the *same machine*. It therefore **cannot run inside a
Cloud Run container**, which is Linux.

So the system is split. This is not a workaround — it is the only correct
architecture for MT5 in the cloud, and it has a security benefit: your broker
password never leaves the Windows host.

```
┌──────────────┐   HTTPS    ┌───────────────────────┐  private VPC  ┌─────────────────┐
│   Browser    │──────────► │  Cloud Run (Linux)    │──────────────►│  Windows VM     │
│  dashboard   │◄──WS────── │  FastAPI backend      │◄──────────────│  MT5 bridge     │
└──────────────┘            │  • JWT auth           │  X-Bridge-    │  + MT5 terminal │
                            │  • indicators         │  Token        │  (holds login)  │
                            │  • AI analyst         │               └────────┬────────┘
                            │  • RISK ENGINE        │                        │
                            │  • executor           │                     broker
                            │  • audit log          │
                            └──────────┬────────────┘
                                       │
                              ┌────────▼────────┐
                              │  Cloud SQL      │
                              │  PostgreSQL     │
                              └─────────────────┘
```

---

## The pipeline, and why it's split into four parts

Your requirement was a clean separation between market data, AI analysis, risk
management, and execution — and that the AI must never bypass risk. That is
enforced structurally, not by convention:

```
1. MARKET DATA      services/mt5_client.py    Real bars & ticks from the broker.
        ▼
2. INDICATORS       services/indicators.py    Deterministic Python maths.
        ▼                                     Trend, S/R, breakouts, pullbacks,
                                              liquidity, ATR, RSI, EMA.
3. AI ANALYST       services/analyst.py       Sees ONLY the output of step 2.
        ▼                                     Returns a *proposal*.
4. RISK ENGINE      services/risk_engine.py   Pure function. Approves, resizes,
        ▼                                     or rejects. Never calls the broker.
5. EXECUTOR         services/executor.py      The ONLY code that can send an
                                              order. Calls step 4 first, always.
```

**How "the AI cannot invent prices" is enforced.** The model is never asked to
recall a number. It receives a JSON snapshot of real computed values, and its
schema-constrained output is then re-checked against the live tick by
`validate_against_market()`. An entry more than ~3 ATR from the market, a stop
on the wrong side of entry, or an out-of-range confidence downgrades the whole
signal to `NO_TRADE`. Prices are never silently "corrected" — a corrected price
is still a price nobody decided to trade. Covered by tests in
`tests/test_analyst_validation.py`.

**How "the AI cannot bypass risk" is enforced.** The analyst has no import of
`executor` or `mt5_client`. The only code path to `mt5.market_order()` is
`executor.execute_signal()`, and its first action is `risk_engine.evaluate()`.
The bot loop has no special privilege — it goes through the same function a
human clicking *Place order* does.

---

## What's in the box

| Feature | Where |
|---|---|
| MT5 account connect, balance/equity/margin | `mt5-bridge/bridge.py`, `routers/account.py` |
| Live XAUUSD price + spread, WebSocket push | `routers/ws.py` |
| Multi-timeframe analysis (M1/M5/M15/H1) | `services/indicators.py` |
| Trend, S/R, breakouts, pullbacks, liquidity, entry zones | same |
| AI signal: BUY/SELL/NO_TRADE + entry/SL/TP/RR/confidence/reason | `services/analyst.py` |
| MANUAL / DEMO / REAL modes | `routers/risk.py` |
| Max risk per trade, daily loss, trades/day, open positions, lot size | `services/risk_engine.py` |
| Auto-halt on daily loss, emergency STOP BOT | `services/bot.py`, `routers/risk.py` |
| Audit log of every decision; order request + broker response logged | `audit.py`, `models.py` |
| JWT auth, CORS, input validation, rate limiting | `security.py`, `deps.py`, `schemas.py` |
| 42 tests over the risk engine and validation | `backend/tests/` |

---

# 1. What files were created

```
Jamil/
├── README.md                     ← you are here
├── .env.example                  every setting, nothing secret
├── .gitignore                    keeps .env and keys out of git
├── docker-compose.yml            local stack: db + backend + frontend
│
├── backend/                      ── FastAPI, runs on Cloud Run (Linux)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py               app startup, CORS, health/ready
│   │   ├── config.py             env-driven settings, prod guards
│   │   ├── db.py                 async SQLAlchemy engine + session
│   │   ├── models.py             User, RiskSettings, Signal, OrderLog,
│   │   │                         AuditLog, DailyStat
│   │   ├── schemas.py            all request/response validation
│   │   ├── security.py           bcrypt hashing, JWT issue/verify
│   │   ├── deps.py               auth dependency, rate limiter
│   │   ├── audit.py              append-only audit logging
│   │   ├── routers/
│   │   │   ├── auth.py           login, /me
│   │   │   ├── account.py        account, tick, positions, history, status
│   │   │   ├── analysis.py       run analysis, list signals, raw indicators
│   │   │   ├── risk.py           settings, mode, bot toggle, EMERGENCY STOP
│   │   │   ├── trading.py        execute signal, close position(s)
│   │   │   └── ws.py             /ws/live WebSocket
│   │   └── services/
│   │       ├── mt5_client.py     HTTP client → the bridge (only broker path)
│   │       ├── indicators.py     deterministic TA, no AI
│   │       ├── analyst.py        Claude analyst + output validation
│   │       ├── risk_engine.py    pure risk decisions + position sizing
│   │       ├── executor.py       the single choke point for orders
│   │       └── bot.py            pipeline + background loop
│   └── tests/
│       ├── test_risk_engine.py         28 tests
│       └── test_analyst_validation.py  14 tests
│
├── mt5-bridge/                   ── runs on WINDOWS, next to MT5
│   ├── bridge.py                 authenticated HTTP API over MetaTrader5
│   ├── requirements.txt
│   ├── run_bridge.bat            launcher; fill in your credentials
│   └── README.md
│
├── frontend/                     ── React + TypeScript dashboard
│   ├── Dockerfile                multi-stage → nginx
│   ├── nginx.conf                serves SPA, proxies /api and /ws
│   ├── package.json / tsconfig*.json / vite.config.ts / index.html
│   └── src/
│       ├── main.tsx, App.tsx, index.css
│       ├── lib/api.ts            typed API client + JWT handling
│       ├── lib/types.ts          shared types
│       ├── pages/Login.tsx
│       ├── pages/Dashboard.tsx
│       └── components/           Primitives, Panels, SignalCard
│
└── deploy/
    ├── deploy.sh                 one-shot Google Cloud deploy
    ├── cloudbuild.yaml           CI: test → build → deploy
    └── windows-vm-setup.md       the MT5 bridge VM, step by step
```

---

# 2. What you need to install

**On your computer (development):**

| Tool | Version | For |
|---|---|---|
| Python | 3.11+ | backend |
| Node.js | 20+ | frontend |
| Docker Desktop | latest | the easy path — runs everything |
| Google Cloud SDK | latest | deployment only |

**On the Windows machine (the MT5 bridge) — required, no way around it:**

| Tool | For |
|---|---|
| Windows 10/11 or Windows Server 2019+ | the `MetaTrader5` package is Windows-only |
| Python 3.11+ | running `bridge.py` |
| MetaTrader 5 terminal | your broker's download |
| An MT5 **demo** account | free from any broker |

**Accounts you'll need:**

- An MT5 demo account (free — IC Markets, Pepperstone, XM, FXTM, etc.)
- An Anthropic API key for the AI analyst → https://console.anthropic.com/settings/keys
- A Google Cloud project with billing enabled (deployment only)

---

# 3. How to run it locally

### The short version (Docker)

```bash
cd Jamil
cp .env.example .env
```

Edit `.env` and set at minimum:

```ini
JWT_SECRET=<paste: openssl rand -hex 32>
MT5_BRIDGE_TOKEN=<paste: openssl rand -hex 32>
ANTHROPIC_API_KEY=sk-ant-...
BOOTSTRAP_EMAIL=you@example.com
BOOTSTRAP_PASSWORD=pick-a-strong-password
MT5_BRIDGE_URL=http://host.docker.internal:8100
```

Then:

```bash
docker compose up --build
```

Open **http://localhost:8081** and sign in with the bootstrap credentials.

The dashboard will show **MT5 offline** until you start the bridge (step 4).
Everything else — login, risk settings, the audit trail — works without it.

### Updating an install you already have

Not a first run? See **[`docs/LOCAL_UPDATE.md`](docs/LOCAL_UPDATE.md)** — it
covers pulling the branch, applying the SQL in `backend/migrations/` that
`create_all` cannot apply for you, and rebuilding, without dropping anything.

### Without Docker

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://mt5ai:mt5ai@localhost:5432/mt5ai"
export JWT_SECRET="$(openssl rand -hex 32)"
export MT5_BRIDGE_TOKEN="dev-token"
export ANTHROPIC_API_KEY="sk-ant-..."
export BOOTSTRAP_EMAIL="you@example.com" BOOTSTRAP_PASSWORD="dev-password"
uvicorn app.main:app --reload --port 8080
```

Frontend (second terminal):

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, proxies /api and /ws to :8080
```

Run the tests:

```bash
cd backend && python -m pytest      # 42 passed
cd frontend && npm run build        # typecheck + production build
```

API docs are at **http://localhost:8080/docs**.

---

# 4. How to connect MetaTrader 5

This runs on **Windows**. For local testing your own Windows PC is fine; for
production use a Windows VM (step 5).

**1 — Install MT5 and log into a demo account.** Download from your broker,
open the terminal, log in with your demo credentials. Do this manually once so
you know the credentials work.

**2 — Enable algorithmic trading.**
`Tools → Options → Expert Advisors → ☑ Allow algorithmic trading`.
Without this, every order comes back `TRADE_RETCODE_TRADE_DISABLED`.

**3 — Add XAUUSD to Market Watch.**
Right-click Market Watch → Symbols → find XAUUSD → Show.
If it isn't selected, ticks and bars come back empty.
Some brokers use `XAUUSD.m`, `GOLD`, or `XAUUSDm` — note the **exact** name and
set `SYMBOL` to it in both `.env` and `run_bridge.bat`.

**4 — Install and start the bridge.**

```powershell
cd C:\path\to\Jamil\mt5-bridge
pip install -r requirements.txt
```

Edit `run_bridge.bat` — set `MT5_BRIDGE_TOKEN` (the same value as your `.env`),
`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`. Then run it. You should see:

```
MT5 connected: login=12345678 server=YourBroker-Demo type=DEMO balance=10000.00 USD
bridge listening on 0.0.0.0:8100
```

**5 — Verify.**

```powershell
curl http://127.0.0.1:8100/health
# {"status":"ok","mt5_connected":true}

curl -H "X-Bridge-Token: YOUR_TOKEN" http://127.0.0.1:8100/account
```

Reload the dashboard — the badge should flip to **MT5 connected** and your
balance should appear.

> Your broker password lives only on this machine, in the bridge's environment.
> It is never sent to the backend, never stored in the database, and no API
> endpoint returns it.

---

# 5. How to deploy to Google Cloud

**Order matters: the Windows VM first**, because the backend needs its internal
IP.

### 5a — The MT5 bridge VM

Follow **[deploy/windows-vm-setup.md](deploy/windows-vm-setup.md)** in full. In
short:

```bash
gcloud compute instances create mt5-bridge \
  --zone=europe-west1-b --machine-type=e2-medium \
  --image-family=windows-2022 --image-project=windows-cloud \
  --boot-disk-size=50GB --no-address --tags=mt5-bridge

gcloud compute firewall-rules create allow-mt5-bridge \
  --allow=tcp:8100 --source-ranges=10.8.0.0/28 --target-tags=mt5-bridge
```

Then RDP in over IAP, install Python + MT5 + the bridge, and run it as a
service. Note the VM's **internal** IP.

### 5b — Everything else

```bash
export PROJECT_ID=your-gcp-project
export REGION=europe-west1
export MT5_BRIDGE_URL=http://10.128.0.5:8100    # the VM's internal IP
export MT5_BRIDGE_TOKEN=<same token as the VM>
export ANTHROPIC_API_KEY=sk-ant-...

chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

That script creates the Artifact Registry repo, a Cloud SQL Postgres instance,
Secret Manager entries, a Serverless VPC connector (so Cloud Run can reach the
VM privately), then builds and deploys both services and wires up IAM and CORS.
It prints your dashboard URL at the end.

**Create your first user** by redeploying once with the bootstrap variables,
signing in, then removing them:

```bash
gcloud run services update mt5ai-backend --region $REGION \
  --update-env-vars BOOTSTRAP_EMAIL=you@example.com,BOOTSTRAP_PASSWORD='<strong>'
# sign in once, then:
gcloud run services update mt5ai-backend --region $REGION \
  --remove-env-vars BOOTSTRAP_EMAIL,BOOTSTRAP_PASSWORD
```

**How secrets are handled.** Nothing sensitive is in the images or the repo.
`DATABASE_URL`, `JWT_SECRET`, `MT5_BRIDGE_TOKEN` and `ANTHROPIC_API_KEY` live in
Secret Manager and are injected at runtime with `--set-secrets`. Broker
credentials never leave the Windows VM.

**Continuous deployment:** `deploy/cloudbuild.yaml` runs the test suite first
and refuses to build if it fails. It pins `ALLOW_REAL_TRADING=false` on every
deploy so a routine push can never silently arm live trading.

> **Why `--min-instances 1 --max-instances 1`:** the bot loop and the
> in-process rate limiter both assume one instance. Scaling to N would run the
> bot N times per tick. If you need to scale out, move the loop to Cloud
> Scheduler hitting a dedicated endpoint and the rate limiter to Memorystore.

**Rough cost:** Cloud Run ~$5–15/mo, Cloud SQL `db-f1-micro` ~$8/mo, the
Windows VM ~$45–60/mo (the big one), plus Anthropic API usage. To trial it
cheaply, run the bridge on your own Windows PC over a Tailscale tunnel and skip
the VM entirely.

---

# 6. How to test with an MT5 demo account

**Step 1 — Confirm the plumbing.** Sign in. You should see *MT5 connected*, a
`demo` badge with your account number, and your real demo balance.

**Step 2 — Check the market data is real.** Compare the Bid/Ask on the
dashboard with the MT5 terminal. They should match. Then hit
`GET /api/analysis/indicators` (via `/docs`) to see the exact deterministic
snapshot the AI will receive — every support level, ATR and RSI value in there
is computed from your broker's own bars.

**Step 3 — Run an analysis.** Click **Run analysis**. In ~10–30s you get a
signal with entry, stop, target, R:R, confidence, and a written rationale, plus
the multi-timeframe breakdown. Cross-check the levels it cites against the
snapshot from step 2 — they should correspond. Most of the time on a quiet
market you'll get `NO_TRADE`; that is the system working, not failing.

**Step 4 — Place one trade by hand (MANUAL mode).** Leave the lot box blank so
the risk engine sizes it. Click **Place BUY/SELL order**. Then:

- The position appears in *Open positions* **and** in your MT5 terminal.
- The *Order log* shows the request and the broker's retcode.
- If it's rejected, the exact risk reasons are printed — that's the engine
  working.

**Step 5 — Prove the risk limits actually bite.** This is the important test.
In *Risk settings*:

| Set this | Then | Expected |
|---|---|---|
| `Min confidence` = 99 | Run analysis, try to execute | Blocked: "confidence N below minimum 99" |
| `Max spread` = 1 | Try to execute | Blocked: "spread … exceeds max 1" |
| `Max open positions` = 1 | Open one, try a second | Blocked: "max open positions reached" |
| `Max trades / day` = 1 | Trade once, try again | Blocked: "max trades per day reached" |
| `Max risk / trade` = 0.01 | Try to execute | Blocked: size below broker minimum |
| `Min risk/reward` = 5 | Try to execute | Blocked: "risk/reward … below minimum 5" |

Every one of these also lands in `audit_logs` with the full reasoning.

**Step 6 — Test the emergency stop.** With a position open, hit **STOP BOT**.
Positions close, the bot disables, and new orders are refused until you clear
the stop. Verify in the MT5 terminal that the position really closed.

**Step 7 — Let the bot run (DEMO mode).** Switch to **DEMO**, click **Start
bot**. Every 60s it runs the full pipeline and auto-executes anything the risk
engine approves. Watch the *Order log* and the audit trail. Leave it for a
session before you'd ever consider more.

**Step 8 — Verify the daily-loss halt.** Set `Max daily loss` to something
small (e.g. 0.2%) and let the bot trade until it trips. The dashboard shows
*Daily loss limit reached*, and no further orders are sent until the next UTC
day.

---

## Real trading is OFF by default

Enabling it takes **three independent, deliberate actions**. No single mistake,
config slip, or routine deploy can arm it:

1. **Server:** an operator sets `ALLOW_REAL_TRADING=true` and redeploys.
   (`cloudbuild.yaml` pins it to `false`, so this must be done on purpose.)
2. **Bridge:** an operator sets `BRIDGE_ALLOW_REAL=true` on the Windows VM.
   Otherwise the bridge refuses any order on a live account, whatever the
   backend says.
3. **User:** in the dashboard, switch to REAL and type
   `I UNDERSTAND THE RISK OF REAL MONEY TRADING` exactly.

Plus a fourth, automatic guard: if the broker reports a **live** account while
the mode is MANUAL or DEMO, the risk engine refuses to trade at all.

**Honest warning.** This is real trading infrastructure with genuine risk
controls, but it is not a profitable strategy and nothing here should be read
as financial advice. The AI analyses recent price structure; it has no view on
news, macro, or your broker's execution quality. Test on demo for a long time.
Never risk money you can't afford to lose.

---

## API reference

Full interactive docs at `/docs`. Summary:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Get a JWT |
| GET | `/api/dashboard` | Account + tick + positions + status, one call |
| GET | `/api/account` · `/api/market/tick` · `/api/positions` | Individual reads |
| GET | `/api/history/deals` · `/api/history/orders` | Trade & order history |
| GET | `/api/status` | Bot status, P/L today, bridge health |
| GET | `/api/analysis/indicators` | The deterministic snapshot (no AI) |
| POST | `/api/analysis/run` | Full pipeline → a signal (never executes) |
| GET | `/api/analysis/signals` · `/{id}` | Signal history and detail |
| GET/PUT | `/api/risk/settings` | Read/update the risk envelope |
| POST | `/api/risk/mode` | MANUAL / DEMO / REAL (REAL needs confirmation) |
| POST | `/api/risk/bot` | Start/pause the bot |
| POST | `/api/risk/emergency-stop` | **STOP BOT** + flatten |
| POST | `/api/trading/execute` | Execute a signal (risk-checked) |
| POST | `/api/trading/close` · `/close-all` | Close positions |
| WS | `/ws/live?token=…` | Live price, positions, account |

## Security summary

- **Auth:** bcrypt password hashing, HS256 JWT bearer tokens, expiry enforced.
- **Broker credentials:** only ever on the Windows bridge host. Not in the DB,
  not in the API, not in the frontend bundle.
- **Bridge auth:** shared secret compared in constant time; bind privately and
  firewall to the VPC connector only.
- **CORS:** exact origins; `*` is rejected outright when `ENV=prod`.
- **Input validation:** every request body and query param goes through
  Pydantic with explicit bounds.
- **Rate limiting:** per-IP sliding window, stricter on login.
- **Audit:** every analysis, risk decision, order request and broker response
  is appended to `audit_logs` / `order_logs` and never mutated.
- **Secrets:** nothing hard-coded; `.gitignore` blocks `.env` and keys.

## Known limitations

Stated plainly rather than discovered later:

- **The Windows VM is a real cost and a single point of failure.** If it dies,
  the backend degrades to read-only (`bridge_connected: false`) — it will not
  place or manage trades.
- **Single-instance backend.** See the `--max-instances 1` note above.
- **The rate limiter is in-process.** Correct for one instance; move to
  Memorystore if you scale out.
- **Schema is created on startup**, not migrated. Add Alembic before you have
  production data you care about.
- **`realized_pnl` in `daily_stats` is only incremented by this system.**
  Trades you place by hand in the MT5 terminal count toward equity-based
  checks but not the realized-loss counter.
- **No backtesting.** This analyses live markets only.
