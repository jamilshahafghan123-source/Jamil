"""Dev harness: run the real bridge against the stub terminal from the tests.

    python tests/serve_with_stub_terminal.py --port 8443

This is **development tooling only**, for working on the UI from a machine
without MetaTrader 5 (the package is Windows-only). It runs the bridge's real
application code — routing, auth, validation, retcode handling — but swaps the
MetaTrader5 package for tests/fake_mt5.py, so quotes and fills come from a stub
rather than a broker. It is never imported by the application: `python run.py`
always talks to a real terminal, and the app has no mock path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tests.fake_mt5 as fake_mt5  # noqa: E402

sys.modules["MetaTrader5"] = fake_mt5

import uvicorn  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--ssl-certfile", default=None)
    parser.add_argument("--ssl-keyfile", default=None)
    parser.add_argument(
        "--series",
        choices=["xauusd_bullish", "xauusd_bearish", "xauusd_conflicting", "xauusd_thin"],
        default="xauusd_bullish",
        help="Multi-timeframe XAUUSD fixture the stub serves (M15/M5/M1), for "
        "exercising the strategy engine. Default: xauusd_bullish.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.api_key_list:
        print("Set API_KEYS before starting the harness.", file=sys.stderr)
        return 2

    # Give XAUUSD a series with real pullbacks so the analysis pipeline has
    # something to read; the stub's default ramp only ever rises.
    from tests import series

    rates = getattr(series, args.series)()
    fake_mt5.state.rates["XAUUSD"] = rates
    last = series.last_close(rates)
    fake_mt5.state.quotes["XAUUSD"] = (round(last - 0.15, 2), round(last + 0.15, 2))

    print("*" * 78)
    print("STUB TERMINAL — quotes and fills are synthetic, not a real MT5 account.")
    print(f"XAUUSD is serving a synthetic '{args.series}' series.")
    print("Use `python run.py` for a real terminal.")
    print("*" * 78)

    uvicorn.run(
        create_app(settings),
        host=args.host,
        port=args.port,
        log_level="warning",
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
