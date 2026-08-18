"""MT5 setup checker.

Run this BEFORE starting the bridge. It answers, in one go:

  1. Is the MetaTrader5 Python package installed?
  2. Can Python actually reach the running MT5 terminal?
  3. Is this a DEMO account? (it refuses to continue quietly on a live one)
  4. Is "Allow algorithmic trading" switched on?
  5. What is gold called on THIS broker, and is real price data flowing?

Output is plain ASCII on purpose: the Windows console often cannot print
Unicode and would crash on a fancy checkmark.

Usage (Windows PowerShell):
    python check_mt5.py
"""

from __future__ import annotations

import sys

LINE = "=" * 62


def head(text: str) -> None:
    print()
    print(LINE)
    print(f"  {text}")
    print(LINE)


def row(label: str, value: str) -> None:
    print(f"      {label:.<24} {value}")


def main() -> int:
    head("MT5 SETUP CHECK")

    # --- 1. package ----------------------------------------------------
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("\n[1/5] MetaTrader5 package ....... NOT INSTALLED")
        print("\n  FIX: run this command, then try again:")
        print("      pip install MetaTrader5")
        print("\n  If that fails, you are probably not on Windows.")
        print("  The MetaTrader5 package only works on Windows.")
        return 1

    version = getattr(mt5, "__version__", "unknown")
    print(f"\n[1/5] MetaTrader5 package ....... OK (version {version})")

    # --- 2. connection -------------------------------------------------
    if not mt5.initialize():
        print("[2/5] Connect to MT5 terminal ... FAILED")
        print(f"\n  Error from MT5: {mt5.last_error()}")
        print("\n  FIX, in order:")
        print("    1. Is the MetaTrader 5 window open? Open it.")
        print("    2. Are you logged in? Bottom-right should show kb/s numbers.")
        print("    3. Close this window, reopen MT5, then run this again.")
        return 1
    print("[2/5] Connect to MT5 terminal ... OK")

    problems: list[str] = []

    # --- 3. account ----------------------------------------------------
    acct = mt5.account_info()
    if acct is None:
        print("[3/5] Read account ............. FAILED (not logged in)")
        mt5.shutdown()
        return 1

    modes = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
    mode = modes.get(acct.trade_mode, str(acct.trade_mode))

    print("\n[3/5] ACCOUNT")
    row("Login", str(acct.login))
    row("Server", acct.server)
    row("Type", mode + ("   <-- safe, virtual money" if mode != "REAL" else ""))
    row("Balance", f"{acct.balance:,.2f} {acct.currency}")
    row("Leverage", f"1:{acct.leverage}")

    if mode == "REAL":
        print()
        print("  !!  WARNING: THIS IS A LIVE ACCOUNT WITH REAL MONEY.  !!")
        print("  !!  Log into a DEMO account before going any further. !!")
        problems.append("account is LIVE, not demo")

    # --- 4. algo trading ------------------------------------------------
    term = mt5.terminal_info()
    algo_ok = bool(term and term.trade_allowed)

    print("\n[4/5] ALGORITHMIC TRADING")
    row("Allow algo trading", "ENABLED" if algo_ok else "DISABLED  <-- must fix")
    if not algo_ok:
        print()
        print("  FIX: in MetaTrader 5 click")
        print("       Tools -> Options -> Expert Advisors tab")
        print("       tick [x] Allow algorithmic trading, then OK.")
        print("  (Without this MT5 silently refuses every order.)")
        problems.append("algorithmic trading is disabled")

    # --- 5. gold --------------------------------------------------------
    print("\n[5/5] LOOKING FOR GOLD")

    everything = mt5.symbols_get() or ()
    candidates = [
        s.name
        for s in everything
        if "XAU" in s.name.upper() or "GOLD" in s.name.upper()
    ]

    if not candidates:
        print(f"      Scanned {len(everything)} symbols. Found NO gold symbol.")
        print()
        print("  This broker/server does not offer gold.")
        print("  Tell Claude: \"no gold on MetaQuotes-Demo\" and he will point")
        print("  you at a free broker demo that has it.")
        mt5.shutdown()
        head("RESULT: NOT READY")
        return 1

    print(f"      Scanned {len(everything)} symbols, found {len(candidates)} candidate(s).")

    best: str | None = None
    for name in sorted(candidates, key=len):
        print(f"\n      --- {name} ---")
        if not mt5.symbol_select(name, True):
            row("usable", "no (cannot be enabled)")
            continue

        tick = mt5.symbol_info_tick(name)
        info = mt5.symbol_info(name)
        if tick is None or info is None or tick.bid <= 0:
            row("live price", "no data")
            continue

        point = info.point or 0.01
        row("bid / ask", f"{tick.bid} / {tick.ask}")
        row("spread", f"{round((tick.ask - tick.bid) / point)} points")

        bars = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M15, 0, 300)
        n = 0 if bars is None else len(bars)
        row("M15 history bars", str(n))

        if n >= 100 and best is None:
            best = name
            print("      >>> THIS ONE WORKS - use it <<<")

    mt5.shutdown()

    # --- verdict ---------------------------------------------------------
    if best is None:
        problems.append("no gold symbol returned usable price history")

    if problems:
        head("RESULT: NOT READY")
        for p in problems:
            print(f"  - {p}")
        print("\n  Fix the items above, then run this script again.")
        return 1

    head("RESULT: READY")
    print("  Everything checks out. Your account is a DEMO account,")
    print("  algorithmic trading is on, and gold prices are flowing.")
    print()
    print("  COPY THE LINE BELOW AND SEND IT TO CLAUDE:")
    print()
    print(f"      SYMBOL={best}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
