@echo off
REM ===================================================================
REM  MT5 Bridge launcher (Windows)
REM
REM  1. Install MetaTrader 5 and log into your DEMO account manually.
REM  2. In MT5: Tools > Options > Expert Advisors >
REM       [x] Allow algorithmic trading
REM  3. Add XAUUSD to Market Watch (right-click > Symbols > find XAUUSD).
REM  4. Fill in the values below, then run this file.
REM
REM  Do NOT commit this file after filling in real credentials.
REM ===================================================================

set MT5_BRIDGE_TOKEN=CHANGE_ME_LONG_RANDOM_STRING
set MT5_LOGIN=
set MT5_PASSWORD=
set MT5_SERVER=
set SYMBOL=XAUUSD

REM Optional: explicit terminal path if you have several installs.
set MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

REM Listen on the private NIC so the backend can reach it.
REM Use 127.0.0.1 while testing locally.
set BRIDGE_HOST=0.0.0.0
set BRIDGE_PORT=8100

REM SAFETY LATCH: leave false unless you intend to trade real money.
set BRIDGE_ALLOW_REAL=false

python bridge.py
pause
