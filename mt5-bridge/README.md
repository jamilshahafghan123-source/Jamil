# MT5 Bridge

Runs on **Windows**, next to the MetaTrader 5 terminal. Exposes an
authenticated HTTP API that the Cloud Run backend calls.

## Why it can't run in the cloud container

The `MetaTrader5` PyPI package wraps the MT5 terminal's local Windows IPC.
There are no Linux/macOS wheels, and the terminal must be running on the same
machine. A Linux container therefore cannot use it at all.

Splitting it out also keeps your broker password on one machine: it lives only
in this process's environment, is never sent to the backend, never stored in
the database, and is not returned by any endpoint.

## Quick start

```powershell
pip install -r requirements.txt
# edit run_bridge.bat with your token and demo credentials
run_bridge.bat
```

Expected output:

```
MT5 connected: login=12345678 server=YourBroker-Demo type=DEMO balance=10000.00 USD
bridge listening on 0.0.0.0:8100
```

Full setup, firewalling, and running it as a Windows service:
[`../deploy/windows-vm-setup.md`](../deploy/windows-vm-setup.md).

## Endpoints

All except `/health` require the `X-Bridge-Token` header.

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{status, mt5_connected}` — no account details |
| GET | `/account` | balance, equity, margin, leverage, **trade_mode** |
| GET | `/tick?symbol=` | bid, ask, spread in points |
| GET | `/symbol?symbol=` | contract size, tick value/size, volume min/max/step, stops level |
| GET | `/bars?symbol=&timeframe=&count=` | OHLCV bars |
| GET | `/positions?symbol=` | open positions |
| GET | `/history?days=` | closed deals |
| POST | `/order` | send a market order |
| POST | `/close` | close a position by ticket |

`/symbol` matters more than it looks: the backend's position sizing uses the
broker's real `trade_tick_value` and `trade_tick_size` rather than a hardcoded
contract size, so sizing stays correct across brokers.

## Safety latch

`BRIDGE_ALLOW_REAL` (default `false`) is an **independent** second latch from
the backend's `ALLOW_REAL_TRADING`. If the connected account is live and this
is false, `/order` returns 403 no matter what the backend asked for.

Leave it false unless you intend to trade real money.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `MT5_BRIDGE_TOKEN` | yes | Must match the backend's value |
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | no | Omit to use whatever account the terminal is already logged into |
| `MT5_PATH` | no | Explicit `terminal64.exe` path if you have several installs |
| `SYMBOL` | no | Default `XAUUSD`; match your broker's exact name |
| `BRIDGE_HOST` / `BRIDGE_PORT` | no | Default `127.0.0.1:8100` |
| `BRIDGE_ALLOW_REAL` | no | Default `false` |
