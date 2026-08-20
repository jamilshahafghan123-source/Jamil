import { useCallback, useEffect, useRef, useState } from "react";
import { api, fmt, liveSocketUrl } from "../lib/api";
import type {
  Analysis,
  DashboardSnapshot,
  Deal,
  ExecutionResult,
  LiveMessage,
  OrderLog,
  RiskSettings,
  Signal,
  TradingMode,
} from "../lib/types";
import { Badge, Banner, Card, Empty, Spinner, Stat } from "../components/Primitives";
import { Brand } from "../components/Brand";
import { SupportChat } from "../components/SupportChat";
import { ControlCentre } from "./ControlCentre";
import { NotificationBell } from "../components/NotificationBell";
import {
  AnalysisPanel,
  DealHistory,
  ModeSwitch,
  OrderHistory,
  PositionsTable,
  PriceBox,
  RiskPanel,
} from "../components/Panels";
import { SignalCard } from "../components/SignalCard";
import { BarChart } from "../components/Bar";

const REAL_CONFIRMATION = "I UNDERSTAND THE RISK OF REAL MONEY TRADING";

export function Dashboard({ onLogout }: { onLogout: () => void }) {
  // Dashboard renders only for ADMIN (see App.tsx), so this view switch is
  // already behind the role gate — and every endpoint it reaches is gated
  // again server-side by require_admin.
  const [view, setView] = useState<"dashboard" | "control">("dashboard");

  const [snap, setSnap] = useState<DashboardSnapshot | null>(null);
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [signal, setSignal] = useState<Signal | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [orders, setOrders] = useState<OrderLog[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [execResult, setExecResult] = useState<ExecutionResult | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [savingRisk, setSavingRisk] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [closingTicket, setClosingTicket] = useState<number | null>(null);
  const [wsUp, setWsUp] = useState(false);
  const [realModal, setRealModal] = useState(false);
  const [realPhrase, setRealPhrase] = useState("");

  const wsRef = useRef<WebSocket | null>(null);

  const guard = useCallback(async (fn: () => Promise<void>) => {
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const refresh = useCallback(async () => {
    await guard(async () => {
      const [d, r, s, o, h] = await Promise.all([
        api.dashboard(),
        api.getRisk(),
        api.signals(1),
        api.orderLogs(25),
        api.deals(7),
      ]);
      setSnap(d);
      setRisk(r);
      setOrders(o);
      setDeals(h);
      if (s.length) setSignal(s[0]);
    });
  }, [guard]);

  useEffect(() => {
    void refresh();
  }, [refresh, guard]);

  // Live socket, with automatic reconnect.
  useEffect(() => {
    let closed = false;
    let retry: number | undefined;

    function connect() {
      const url = liveSocketUrl();
      if (!url || closed) return;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => setWsUp(true);
      ws.onmessage = (ev) => {
        const msg: LiveMessage = JSON.parse(ev.data);
        setSnap((prev) =>
          prev
            ? {
                ...prev,
                tick: msg.tick ?? prev.tick,
                positions: msg.positions ?? prev.positions,
                account: msg.account ?? prev.account,
                status: {
                  ...prev.status,
                  bridge_connected: msg.bridge_connected,
                  bot_enabled: msg.bot_enabled ?? prev.status.bot_enabled,
                  emergency_stop: msg.emergency_stop ?? prev.status.emergency_stop,
                  trading_mode: msg.trading_mode ?? prev.status.trading_mode,
                },
              }
            : prev,
        );
      };
      ws.onclose = () => {
        setWsUp(false);
        if (!closed) retry = window.setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
    }

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  // Poll the slower-moving parts; the socket covers price and positions.
  useEffect(() => {
    const id = setInterval(() => void refresh(), 20000);
    return () => clearInterval(id);
  }, [refresh]);

  async function runAnalysis() {
    setAnalysing(true);
    setExecResult(null);
    await guard(async () => {
      const res = await api.runAnalysis();
      setSignal(res.signal);
      setAnalysis(res.analysis);
    });
    setAnalysing(false);
  }

  async function execute(signalId: number, volume?: number) {
    setExecuting(true);
    await guard(async () => {
      const res = await api.execute(signalId, volume);
      setExecResult(res);
      await refresh();
    });
    setExecuting(false);
  }

  async function closePosition(ticket: number) {
    setClosingTicket(ticket);
    await guard(async () => {
      await api.closePosition(ticket);
      await refresh();
    });
    setClosingTicket(null);
  }

  async function changeMode(mode: TradingMode) {
    if (mode === "REAL") {
      setRealModal(true);
      return;
    }
    await guard(async () => setRisk(await api.setMode(mode)));
  }

  async function confirmReal() {
    await guard(async () => {
      setRisk(await api.setMode("REAL", realPhrase));
      setRealModal(false);
      setRealPhrase("");
    });
  }

  async function toggleBot(enabled: boolean) {
    await guard(async () => {
      setRisk(await api.toggleBot(enabled));
      await refresh();
    });
  }

  async function emergencyStop() {
    await guard(async () => {
      setRisk(await api.emergencyStop(true));
      await refresh();
    });
  }

  async function clearStop() {
    await guard(async () => setRisk(await api.clearEmergencyStop()));
  }

  if (!snap || !risk) {
    return (
      <div className="login-wrap">
        <div className="row">
          <Spinner /> <span className="dim">Loading dashboard…</span>
        </div>
      </div>
    );
  }

  const { account, tick, positions, status } = snap;

  const sortedDeals = [...deals].sort(
    (a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()
  );

  // Match only FILLED AI orders to their real MT5 position IDs.
  const filledAiOrders = orders.filter(
    (o) => o.status === "FILLED" && o.broker_ticket !== null
  );

  const aiPositionIds = new Set<number>();

  for (const order of filledAiOrders) {
    const entryDeal = deals.find(
      (d) => d.order === order.broker_ticket
    );

    if (entryDeal) {
      aiPositionIds.add(entryDeal.position_id);
    }
  }

  // Only MT5 deals belonging to positions opened by this AI.
  const aiDeals = sortedDeals.filter(
    (d) => aiPositionIds.has(d.position_id)
  );

  const todayKey = new Date().toISOString().slice(0, 10);

  const todayClosedDeals = aiDeals.filter(
    (d) => d.time.slice(0, 10) === todayKey && d.entry === 1
  );

  const todayProfit = todayClosedDeals.reduce(
    (sum, d) => sum + d.profit + d.commission + d.swap,
    0
  );

  const aiOpenPositions = positions.filter(
    (p) => aiPositionIds.has(p.ticket)
  );

  const liveProfit = aiOpenPositions.reduce(
    (sum, p) => sum + p.profit,
    0
  );

  const latestClosedDeal =
    aiDeals.find((d) => d.entry === 1) ?? null;
  const currency = account?.currency ? `${account.currency} ` : "";
  const isLiveAccount = account?.trade_mode === "real";

  if (view === "control") {
    return <ControlCentre onBack={() => setView("dashboard")} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Brand size={22} />
          <span className="sub">XAUUSD AI Analyst</span>
        </div>

        <Badge tone={status.bridge_connected ? "up" : "down"} live={status.bridge_connected}>
          {status.bridge_connected ? "MT5 connected" : "MT5 offline"}
        </Badge>
        {wsUp && <Badge tone="neutral">Live feed</Badge>}
        {account && (
          <Badge tone={isLiveAccount ? "down" : "gold"}>
            {account.trade_mode} · {account.login}
          </Badge>
        )}

        <div className="topbar-spacer" />

        <ModeSwitch
          mode={risk.trading_mode}
          serverAllowsReal={status.real_trading_allowed_by_server}
          onChange={changeMode}
          disabled={risk.emergency_stop}
        />

        <button
          className={`btn ${risk.bot_enabled ? "" : "primary"}`}
          onClick={() => toggleBot(!risk.bot_enabled)}
          disabled={risk.emergency_stop}
        >
          {risk.bot_enabled ? "Pause bot" : "Start bot"}
        </button>

        <button className="btn danger btn-stop" onClick={emergencyStop}>
          Stop bot
        </button>

        <NotificationBell />
        <button className="btn sm" onClick={() => setView("control")}>
          Control Centre
        </button>
        <button className="btn sm" onClick={onLogout}>
          Sign out
        </button>
      </header>

      <main className="main stack">
        {error && (
          <Banner tone="err">
            <div style={{ flex: 1 }}>{error}</div>
            <button className="btn sm" onClick={() => setError(null)}>
              Dismiss
            </button>
          </Banner>
        )}

        {risk.emergency_stop && (
          <Banner tone="err">
            <div style={{ flex: 1 }}>
              <strong>Emergency stop engaged.</strong> No new orders will be sent.
            </div>
            <button className="btn sm" onClick={clearStop}>
              Clear stop
            </button>
          </Banner>
        )}

        {status.halted_today && (
          <Banner tone="warn">
            <strong>Daily loss limit reached.</strong> Trading is halted until the
            next UTC day.
          </Banner>
        )}

        {isLiveAccount && risk.trading_mode !== "REAL" && (
          <Banner tone="warn">
            The connected MT5 account is a <strong>LIVE</strong> account, but the
            trading mode is {risk.trading_mode}. The risk engine will refuse to
            auto-trade it.
          </Banner>
        )}

        {risk.trading_mode === "REAL" && (
          <Banner tone="err">
            <strong>REAL MONEY MODE IS ARMED.</strong> Approved signals will be
            sent to the live account automatically.
          </Banner>
        )}

        {/* ---- stats ---- */}
        <div className="grid stats">
          <Stat label="Balance" value={fmt.money(account?.balance, currency)} />
          <Stat label="Equity" value={fmt.money(account?.equity, currency)} />
          <Stat label="Free margin" value={fmt.money(account?.free_margin, currency)} />
          <Stat
            label="P/L today"
            value={fmt.signed(status.pnl_today)}
            tone={status.pnl_today >= 0 ? "up" : "down"}
            sub={`${status.trades_today} / ${risk.max_trades_per_day} trades`}
          />
          <Stat
            label="Open positions"
            value={`${positions.length} / ${risk.max_open_positions}`}
            sub={`max ${risk.max_lot_size} lots`}
          />
          <Stat
            label="Bot"
            value={risk.bot_enabled ? "RUNNING" : "PAUSED"}
            tone={risk.bot_enabled ? "up" : undefined}
            sub={risk.trading_mode}
          />
        </div>

        {/* ---- price + signal | analysis ---- */}
        <div className="grid cols-2">
          <div className="stack">
            <Card title="Live market">
              <PriceBox
                bid={tick?.bid}
                ask={tick?.ask}
                spread={tick?.spread_points}
                time={tick?.time}
              />
              {/* Live XAUUSD candles, straight from MT5 via the backend.
                  Passing the analysis lets the chart draw the very same
                  levels the analyst panel lists — never a second opinion. */}
              <BarChart analysis={analysis} />
            </Card>

            <Card
              title="AI signal"
              actions={
                <button className="btn primary" onClick={runAnalysis} disabled={analysing}>
                  {analysing ? <Spinner /> : null} {analysing ? "Analysing…" : "Run analysis"}
                </button>
              }
              flush
            >
              <SignalCard
                signal={signal}
                mode={risk.trading_mode}
                onExecute={execute}
                busy={executing}
                lastResult={execResult}
              />
            </Card>

            <Card title="Open positions" flush>
              <PositionsTable
                positions={positions}
                onClose={closePosition}
                busyTicket={closingTicket}
              />
            </Card>
          </div>

          <div className="stack">
            <Card title="Multi-timeframe analysis" flush>
              <AnalysisPanel analysis={analysis} />
            </Card>

            <Card title="Risk settings">
              <RiskPanel
                settings={risk}
                saving={savingRisk}
                onSave={async (patch) => {
                  setSavingRisk(true);
                  await guard(async () => setRisk(await api.saveRisk(patch)));
                  setSavingRisk(false);
                }}
              />
            </Card>
          </div>
        </div>

        <div className="stats">
          <Stat
            label="Live Profit"
            value={`${currency}${liveProfit.toFixed(2)}`}
            tone={liveProfit >= 0 ? "up" : "down"}
            sub={`${positions.length} open position${positions.length === 1 ? "" : "s"}`}
          />

          <Stat
            label="Today's Realized Profit"
            value={`${currency}${todayProfit.toFixed(2)}`}
            tone={todayProfit >= 0 ? "up" : "down"}
            sub={`${todayClosedDeals.length} closed profit/loss deals`}
          />

          <Stat
            label="Latest Closed Trade"
            value={
              latestClosedDeal
                ? `${latestClosedDeal.type} ${currency}${latestClosedDeal.profit.toFixed(2)}`
                : "—"
            }
            tone={
              !latestClosedDeal
                ? undefined
                : latestClosedDeal.profit >= 0
                  ? "up"
                  : "down"
            }
            sub={
              latestClosedDeal
                ? `${latestClosedDeal.symbol} - ${latestClosedDeal.volume.toFixed(2)} lots`
                : "No closed trade yet"
            }
          />
        </div>

        {/* ---- history ---- */}
        <div className="grid cols-2">
          <Card title="AI filled orders" flush>
            <OrderHistory orders={orders.filter((o) => o.status === "FILLED")} />
          </Card>
          <Card title="AI closed deals (7 days)" flush>
            {aiDeals.filter((d) => d.entry === 1).length ? (
              <DealHistory deals={aiDeals.filter((d) => d.entry === 1).slice(0, 25)} />
            ) : (
              <Empty>No AI closed deals.</Empty>
            )}
          </Card>
        </div>
      </main>

      {realModal && (
        <div className="modal-backdrop" onClick={() => setRealModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Enable REAL money trading?</h2>
            <p>
              This lets the bot send orders to a live brokerage account using real
              funds. Losses are real and immediate. The risk limits you configured
              still apply, but they are not a guarantee against loss.
            </p>
            <p>
              Type the phrase below exactly to continue:
              <br />
              <code style={{ color: "var(--gold)", fontSize: 12 }}>
                {REAL_CONFIRMATION}
              </code>
            </p>
            <div className="field">
              <input
                value={realPhrase}
                onChange={(e) => setRealPhrase(e.target.value)}
                placeholder="Type the confirmation phrase"
                aria-label="Confirmation phrase"
              />
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setRealModal(false)}>
                Cancel
              </button>
              <button
                className="btn danger"
                disabled={realPhrase !== REAL_CONFIRMATION}
                onClick={confirmReal}
              >
                Enable real trading
              </button>
            </div>
          </div>
        </div>
      )}

      <SupportChat />
    </div>
  );
}
