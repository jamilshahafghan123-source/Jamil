# MT5 Bridge — Windows VM setup

The `MetaTrader5` Python package is a wrapper around the MT5 terminal's local
Windows IPC. It has **no Linux or macOS wheels** and requires the terminal
running on the same machine. That is why the bridge cannot live in the Cloud
Run container, and why this VM exists.

```
Cloud Run (Linux)  ──private VPC──►  Windows VM :8100  ──local IPC──►  MT5 terminal ──►  Broker
  backend, risk,                      bridge.py                        (holds the login)
  AI, database
```

---

## 1. Create the VM

```bash
gcloud compute instances create mt5-bridge \
  --zone=europe-west1-b \
  --machine-type=e2-medium \
  --image-family=windows-2022 \
  --image-project=windows-cloud \
  --boot-disk-size=50GB \
  --network=default \
  --no-address \
  --tags=mt5-bridge
```

`--no-address` gives it no public IP. The backend reaches it over the VPC
connector created by `deploy.sh`. To administer it, use IAP:

```bash
gcloud compute start-iap-tunnel mt5-bridge 3389 --local-host-port=localhost:3389 --zone=europe-west1-b
# then RDP to localhost:3389
gcloud compute reset-windows-password mt5-bridge --zone=europe-west1-b
```

Note the VM's **internal** IP — that is your `MT5_BRIDGE_URL` host:

```bash
gcloud compute instances describe mt5-bridge --zone=europe-west1-b \
  --format='value(networkInterfaces[0].networkIP)'
```

## 2. Firewall — bridge port reachable only from the VPC connector

```bash
gcloud compute firewall-rules create allow-mt5-bridge \
  --network=default \
  --allow=tcp:8100 \
  --source-ranges=10.8.0.0/28 \
  --target-tags=mt5-bridge \
  --description="Cloud Run VPC connector -> MT5 bridge"
```

`10.8.0.0/28` is the connector range from `deploy.sh`. **Never** open 8100 to
`0.0.0.0/0`.

## 3. On the VM

1. **Install Python 3.12** from python.org. Tick *Add python.exe to PATH*.
2. **Install MetaTrader 5** from your broker's site.
3. **Log into your DEMO account** in the terminal, manually, once.
4. **MT5 → Tools → Options → Expert Advisors → ✅ Allow algorithmic trading.**
   Without this every order returns `TRADE_RETCODE_TRADE_DISABLED`.
5. **Add XAUUSD to Market Watch** (right-click → Symbols → find XAUUSD →
   Show). If the symbol isn't selected, ticks and bars come back empty.
   Some brokers name it `XAUUSD.m`, `GOLD`, or `XAUUSDm` — use the exact name
   and set `SYMBOL` to match on both the bridge and the backend.
6. Copy the `mt5-bridge/` folder to the VM, then:

```powershell
cd C:\mt5-bridge
pip install -r requirements.txt
```

7. Edit `run_bridge.bat` with your credentials and the shared token, then run
   it. You should see:

```
MT5 connected: login=12345678 server=YourBroker-Demo type=DEMO balance=10000.00 USD
bridge listening on 0.0.0.0:8100
```

## 4. Verify

On the VM:

```powershell
curl http://127.0.0.1:8100/health
# {"status":"ok","mt5_connected":true}

curl -H "X-Bridge-Token: YOUR_TOKEN" http://127.0.0.1:8100/account
curl -H "X-Bridge-Token: YOUR_TOKEN" "http://127.0.0.1:8100/tick?symbol=XAUUSD"
```

From the deployed backend:

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://mt5ai-backend-xxxx.run.app/ready
# {"status":"ok","bridge_connected":true,"real_trading_allowed":false}
```

## 5. Run it as a service so it survives reboots

Using [NSSM](https://nssm.cc/):

```powershell
nssm install MT5Bridge "C:\Python312\python.exe" "C:\mt5-bridge\bridge.py"
nssm set MT5Bridge AppDirectory C:\mt5-bridge
nssm set MT5Bridge AppEnvironmentExtra ^
  MT5_BRIDGE_TOKEN=your-token ^
  MT5_LOGIN=12345678 ^
  MT5_PASSWORD=your-password ^
  MT5_SERVER=YourBroker-Demo ^
  SYMBOL=XAUUSD ^
  BRIDGE_HOST=0.0.0.0 ^
  BRIDGE_ALLOW_REAL=false
nssm set MT5Bridge Start SERVICE_AUTO_START
nssm start MT5Bridge
```

The MT5 **terminal** must also be running in the same Windows session. Set it
to start on login and enable auto-login for the VM's user, or run the terminal
as a service too.

---

## Cost note

An `e2-medium` Windows VM runs roughly $45–60/month and must stay on during
market hours. If that is too much for a demo trial, run the bridge on your own
Windows PC instead and expose it to Cloud Run over a Tailscale/WireGuard tunnel
or an SSH reverse tunnel. Everything else is unchanged — only `MT5_BRIDGE_URL`
differs.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `mt5_connected: false` | Terminal not running, or not logged in. Open it and check. |
| `initialize failed, error = (-6, 'Terminal: Authorization failed')` | Wrong login/password/server. The server string must match the broker's exactly. |
| Empty `/bars` or `/tick` | Symbol not in Market Watch, or wrong symbol name for your broker. |
| `retcode 10027` | Algorithmic trading disabled — step 4 above. |
| `retcode 10018` | Market closed. Gold trades ~23h/day Sun–Fri; there is a daily break. |
| `retcode 10019` | Not enough money for that lot size. |
| `retcode 10016` | Invalid stops — SL/TP too close to price. The backend checks `trade_stops_level`, but some brokers widen it dynamically. |
| Backend says `bridge unreachable` | Firewall rule, wrong internal IP, or the VPC connector isn't attached to the Cloud Run service. |
| `bridge rejected token` | `MT5_BRIDGE_TOKEN` differs between the VM and Secret Manager. |
