@echo off
REM ===================================================================
REM  MT5 Bridge launcher (Windows)
REM
REM  BEFORE RUNNING:
REM    1. MetaTrader 5 must be OPEN and LOGGED IN to your demo account.
REM    2. Tools > Options > Expert Advisors > [x] Allow algorithmic trading
REM    3. Run check_mt5.py once and make sure it says RESULT: READY
REM
REM  No broker password is needed or stored here. The bridge attaches to
REM  the terminal you are already logged into, so your credentials never
REM  leave MetaTrader 5.
REM ===================================================================

REM The exact symbol name YOUR broker uses for gold.
REM check_mt5.py prints the correct value for your account.
set SYMBOL=GOLD

REM Listen on this machine only. Nothing on your network can reach it.
set BRIDGE_HOST=127.0.0.1
set BRIDGE_PORT=8100

REM SAFETY LATCH - leave false. Even if the backend asked, the bridge
REM refuses to place orders on a live account while this is false.
set BRIDGE_ALLOW_REAL=false

REM A shared secret is generated automatically on first run and saved to
REM .bridge_token so it stays the same across restarts. To pin your own,
REM uncomment the next line:
REM set MT5_BRIDGE_TOKEN=your-own-long-random-string

python bridge.py
pause
