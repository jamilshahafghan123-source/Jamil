"use client";

import { useEffect, useMemo, useState } from "react";

import { usePolling } from "@/hooks/usePolling";
import { number, price, timeAgo } from "@/lib/format";
import {
  TIMEFRAMES,
  type Account,
  type BridgeStatus,
  type CandlesPayload,
  type Position,
  type RiskState,
  type SignalResult,
  type SymbolSummary,
  type TicketPreset,
  type Tick,
  type Timeframe,
} from "@/lib/types";
import AccountPanel from "./AccountPanel";
import CandleChart from "./CandleChart";
import ConnectionBadge, { ExecutionBadge } from "./ConnectionBadge";
import OrderTicket from "./OrderTicket";
import PositionsTable from "./PositionsTable";
import RiskPanel from "./RiskPanel";
import SignalPanel from "./SignalPanel";
import { ErrorNotice, Panel, RefreshIndicator } from "./ui";

const POLL = {
  status: 10_000,
  account: 5_000,
  positions: 5_000,
  tick: 2_000,
  candles: 30_000,
  risk: 10_000,
  signal: 30_000,
};

const DEFAULT_SYMBOL = "EURUSD";
const CANDLE_COUNT = 300;

export default function TradingDesk() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useState<Timeframe>("M15");

  const status = usePolling<BridgeStatus>("/api/mt5/status", POLL.status);
  const online = Boolean(status.data?.connected);

  // Everything below only polls once the terminal is actually connected.
  const symbols = usePolling<SymbolSummary[]>("/api/mt5/symbols", 0, { enabled: online });
  const account = usePolling<Account>("/api/mt5/account", POLL.account, { enabled: online });
  const positions = usePolling<Position[]>("/api/mt5/positions", POLL.positions, {
    enabled: online,
  });
  const risk = usePolling<RiskState>("/api/mt5/risk", POLL.risk, { enabled: online });
  const signal = usePolling<SignalResult>(
    `/api/mt5/signal?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`,
    POLL.signal,
    { enabled: online },
  );

  // A setup the operator loaded from the signal panel into the order ticket.
  const [preset, setPreset] = useState<TicketPreset | null>(null);
  const tick = usePolling<Tick>(`/api/mt5/tick/${encodeURIComponent(symbol)}`, POLL.tick, {
    enabled: online,
  });
  const candles = usePolling<CandlesPayload>(
    `/api/mt5/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&count=${CANDLE_COUNT}`,
    POLL.candles,
    { enabled: online },
  );

  // Open on a symbol the risk policy actually allows, falling back to whatever
  // this account offers.
  const [symbolPinned, setSymbolPinned] = useState(false);

  useEffect(() => {
    if (symbolPinned) return;
    const allowed = risk.data?.limits.allowed_symbols ?? [];
    if (allowed.length && !allowed.includes(symbol)) {
      setSymbol(allowed[0]);
      return;
    }
    const list = symbols.data;
    if (list?.length && !list.some((entry) => entry.name === symbol)) {
      setSymbol(list[0].name);
    }
  }, [risk.data, symbols.data, symbol, symbolPinned]);

  const chooseSymbol = (next: string) => {
    setSymbolPinned(true);
    setSymbol(next);
  };

  const symbolInfo = useMemo(
    () => symbols.data?.find((entry) => entry.name === symbol) ?? null,
    [symbols.data, symbol],
  );
  const digits = symbolInfo?.digits ?? 5;

  const refreshTrading = () => {
    account.refresh();
    positions.refresh();
    risk.refresh();
  };

  const spread =
    tick.data && symbolInfo
      ? (tick.data.ask - tick.data.bid) / symbolInfo.point
      : null;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          MT5 Trading Desk<span>FastAPI bridge</span>
        </div>
        <ConnectionBadge status={status.data} loading={status.loading} />
        <ExecutionBadge status={status.data} />
        <button
          type="button"
          className="btn small ghost"
          onClick={() => {
            status.refresh();
            if (online) {
              refreshTrading();
              tick.refresh();
              candles.refresh();
              signal.refresh();
            }
          }}
        >
          Refresh
        </button>
      </header>

      <BridgeNotice status={status.data} loading={status.loading} onRetry={status.refresh} />

      <div className="desk">
        <div className="stack">
          <Panel
            title="Chart"
            tight
            actions={
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <select
                  value={symbol}
                  onChange={(event) => chooseSymbol(event.target.value)}
                  disabled={!online || !symbols.data?.length}
                  aria-label="Symbol"
                  style={{
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    padding: "6px 8px",
                    fontFamily: "var(--mono)",
                  }}
                >
                  {symbols.data?.length ? (
                    symbols.data.map((entry) => (
                      <option key={entry.name} value={entry.name}>
                        {entry.name}
                      </option>
                    ))
                  ) : (
                    <option value={symbol}>{symbol}</option>
                  )}
                </select>
                <div className="seg" role="group" aria-label="Timeframe">
                  {TIMEFRAMES.map((frame) => (
                    <button
                      key={frame}
                      type="button"
                      className={frame === timeframe ? "active" : ""}
                      onClick={() => setTimeframe(frame)}
                      disabled={!online}
                    >
                      {frame}
                    </button>
                  ))}
                </div>
                <RefreshIndicator
                  refreshing={candles.refreshing}
                  label={`updated ${timeAgo(candles.lastUpdated)}`}
                />
              </div>
            }
          >
            <div className="quote">
              <div className="side">
                <span className="label">Bid</span>
                <span className="price down">{price(tick.data?.bid, digits)}</span>
              </div>
              <div className="side">
                <span className="label">Ask</span>
                <span className="price up">{price(tick.data?.ask, digits)}</span>
              </div>
              <div className="side">
                <span className="label">Spread</span>
                <span className="price" style={{ fontSize: 17 }}>
                  {spread == null ? "—" : `${number(spread, 1)} pts`}
                </span>
              </div>
              <div style={{ marginLeft: "auto", textAlign: "right" }}>
                <div className="muted" style={{ fontSize: 11 }}>
                  {symbolInfo?.description || symbol}
                </div>
                <div className="muted" style={{ fontSize: 11 }}>
                  tick {timeAgo(tick.lastUpdated)}
                </div>
              </div>
            </div>

            {tick.error && online ? (
              <div style={{ padding: "0 14px 12px" }}>
                <ErrorNotice error={tick.error} onRetry={tick.refresh} />
              </div>
            ) : null}

            <div style={{ padding: "0 8px 12px" }}>
              <CandleChart
                candles={candles.data?.candles ?? []}
                digits={digits}
                loading={candles.loading}
                error={candles.error}
                online={online}
                onRetry={candles.refresh}
              />
            </div>
          </Panel>

          <PositionsTable
            state={positions}
            liveExecutionEnabled={Boolean(status.data?.live_orders_enabled)}
            online={online}
            onClosed={refreshTrading}
          />
        </div>

        <div className="stack">
          <AccountPanel state={account} online={online} />
          <RiskPanel state={risk} online={online} />
          <SignalPanel
            state={signal}
            online={online}
            digits={digits}
            onUseProposal={(proposal) =>
              setPreset({
                side: proposal.side,
                type: proposal.type,
                volume: proposal.volume,
                sl: proposal.sl,
                tp: proposal.tp,
                nonce: Date.now(),
              })
            }
          />
          <OrderTicket
            symbol={symbol}
            symbolInfo={symbolInfo}
            tick={tick.data}
            risk={risk.data}
            preset={preset}
            liveExecutionEnabled={Boolean(status.data?.live_orders_enabled)}
            bridgeReady={online}
            onOrderPlaced={refreshTrading}
          />
        </div>
      </div>

      <p className="footnote">
        Every figure on this page comes from the MetaTrader 5 terminal through the FastAPI
        bridge. The browser never talks to the bridge directly and never receives the bridge
        token — all traffic goes through this server&apos;s <code>/api/mt5/*</code> routes.
      </p>
    </main>
  );
}

/** Full-width explanation whenever the desk is not showing live MT5 data. */
function BridgeNotice({
  status,
  loading,
  onRetry,
}: {
  status: BridgeStatus | null;
  loading: boolean;
  onRetry: () => void;
}) {
  if (loading && !status) return null;

  if (!status || !status.configured) {
    return (
      <div className="notice error" style={{ marginBottom: 16 }} role="alert">
        <div style={{ flex: 1 }}>
          <strong>MT5 Bridge Offline — not configured</strong>
          <span>
            Set <code>MT5_BRIDGE_URL</code> and <code>MT5_BRIDGE_TOKEN</code> in the server
            environment, then restart. No trading data can be shown until then.
          </span>
        </div>
        <button type="button" className="btn small ghost" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }

  if (!status.reachable) {
    return (
      <div className="notice error" style={{ marginBottom: 16 }} role="alert">
        <div style={{ flex: 1 }}>
          <strong>MT5 Bridge Offline</strong>
          <span>
            {status.detail ?? "The bridge did not respond."} Prices, positions and orders are
            unavailable — nothing on this page is simulated.
          </span>
        </div>
        <button type="button" className="btn small ghost" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }

  if (!status.connected) {
    return (
      <div className="notice warn" style={{ marginBottom: 16 }} role="alert">
        <div style={{ flex: 1 }}>
          <strong>Bridge reachable, MT5 terminal not connected</strong>
          <span>
            {status.detail ??
              "The bridge is running but has no MetaTrader 5 terminal session. Start the terminal and log into the account."}
          </span>
        </div>
        <button type="button" className="btn small ghost" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }

  if (!status.live_orders_enabled) {
    return (
      <div className="notice warn" style={{ marginBottom: 16 }}>
        <div>
          <strong>Live execution is disabled</strong>
          <span>
            Market data, account and positions are live. Orders are validated against MT5 and
            the real result is shown, but nothing is sent to the market until
            <code> MT5_ALLOW_LIVE_ORDERS=true</code> on the server.
          </span>
        </div>
      </div>
    );
  }

  return null;
}
