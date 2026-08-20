import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { Brand } from "../components/Brand";
import { SupportChat } from "../components/SupportChat";
import {
  TradingChart,
  type ChartCoordinates,
  type PriceLine,
  type TradeMarker,
} from "../components/TradingChart";
import { AIPanel, type AISetup } from "../components/AIPanel";
import { IndicatorPanel, useIndicators } from "../components/IndicatorPanel";
import { DrawingLayer, TOOLS, type DrawingKind } from "../components/DrawingLayer";
import { SessionLayer } from "../components/SessionLayer";
import { SymbolSearch } from "../components/SymbolSearch";
import { TechnicalSummary } from "../components/TechnicalSummary";
import { BrokerCentre } from "../components/BrokerCentre";
import { LanguagePicker } from "../components/LanguagePicker";
import { ObjectTree } from "../components/ObjectTree";
import { StrategyBuilder } from "../components/StrategyBuilder";
import { useLanguage } from "../i18n/useLanguage";
import {
  AIOverlayLayer,
  type AIStructureMark,
  type AISwing,
  type AIZone,
} from "../components/AIOverlayLayer";
import { useDrawings } from "../components/useDrawings";
import type {
  Analysis,
  Bar,
  DemoAccountResponse,
  DemoTrade,
  InstrumentInfo,
  RiskSettings,
  SessionMap,
  Signal,
  Timeframe,
} from "../lib/types";

/**
 * J Gold AI customer trading workspace.
 *
 * ACCOUNT MODE. This page trades the J Gold AI internal demo account —
 * virtual money that never reaches MT5. That is not a label on a screen:
 * every order here calls /api/demo/*, and the demo engine behind it imports
 * no broker client at all. The MT5 demo account is a different thing, and
 * the copy says "J Gold AI Demo" everywhere rather than just "demo" so the
 * two cannot be confused.
 *
 * The chart is the page. Controls are compact, the panels are secondary,
 * and none of the homepage's decorative treatment comes in here.
 */

const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

/** Bars per timeframe. Enough for context without over-fetching. */
const BAR_COUNT = 300;

function money(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}${currency} ${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "up" : "down";
}

export function TradingWorkspace({
  onLogout,
  onOpenOverview,
}: {
  onLogout: () => void;
  /** Present whenever this account also has the Overview dashboard. */
  onOpenOverview?: () => void;
}) {
  const { t } = useLanguage();
  const [symbol, setSymbol] = useState("XAUUSD");
  const [timeframe, setTimeframe] = useState<Timeframe>("M15");
  const [bars, setBars] = useState<Bar[]>([]);
  const [barsError, setBarsError] = useState<string | null>(null);
  const [loadingBars, setLoadingBars] = useState(true);

  const [instruments, setInstruments] = useState<
    Record<string, InstrumentInfo[]>
  >({});
  const [account, setAccount] = useState<DemoAccountResponse | null>(null);
  const [trades, setTrades] = useState<DemoTrade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [tab, setTab] = useState<"positions" | "history" | "ai">("positions");

  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [volume, setVolume] = useState("0.10");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [ticketError, setTicketError] = useState<string | null>(null);
  const [pendingOrder, setPendingOrder] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [risk, setRisk] = useState<RiskSettings | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [showAI, setShowAI] = useState(true);
  const [aiSetup, setAiSetup] = useState<AISetup | null>(null);

  // J Gold AI Session Map. Fetched on the same beat as the bars it is
  // measured from, so the boxes can never describe a different window than
  // the candles on screen.
  const [sessionMap, setSessionMap] = useState<SessionMap | null>(null);
  const [showSessions, setShowSessions] = useState(false);
  const [showPrevLevels, setShowPrevLevels] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [sideTab, setSideTab] = useState<"ai" | "technicals" | "objects">("ai");
  const [brokersOpen, setBrokersOpen] = useState(false);
  const [strategiesOpen, setStrategiesOpen] = useState(false);

  // Indicator state and calculations. Memoised on `bars`, so a poll that
  // returns an unchanged array recomputes nothing.
  const { configs, setConfigs, overlays, readouts } = useIndicators(bars);

  // Customer drawings. Scoped to symbol AND timeframe, reloaded on either
  // change, and entirely separate from the AI overlays above.
  const [tool, setTool] = useState<DrawingKind | "CURSOR">("CURSOR");
  const [coords, setCoords] = useState<ChartCoordinates | null>(null);
  const draw = useDrawings(symbol, timeframe);

  // One in-flight bars request at a time; a timeframe click mid-flight must
  // not let a stale response land after the new one.
  const barsRequest = useRef<AbortController | null>(null);

  const loadBars = useCallback(async () => {
    barsRequest.current?.abort();
    const controller = new AbortController();
    barsRequest.current = controller;
    setLoadingBars(true);
    try {
      const res = await api.bars(timeframe, BAR_COUNT, symbol, controller.signal);
      setBars(res.bars);
      setBarsError(null);
    } catch (err) {
      if (controller.signal.aborted) return;
      // A safe explanation beats "Failed to fetch".
      setBarsError(
        err instanceof Error && err.message
          ? err.message
          : "Market data is unavailable right now.",
      );
    } finally {
      if (!controller.signal.aborted) setLoadingBars(false);
    }
  }, [symbol, timeframe]);

  /**
   * Session boxes and previous-period levels.
   *
   * Loaded only while one of the two overlays is switched on: a customer
   * who never opens the session map should not pay for the request on
   * every poll.
   */
  const loadSessions = useCallback(async () => {
    if (!showSessions && !showPrevLevels) return;
    try {
      setSessionMap(await api.sessionMap(timeframe));
    } catch {
      /* the overlay stays as it was; the chart itself is unaffected */
    }
  }, [timeframe, showSessions, showPrevLevels]);

  const loadAccount = useCallback(async () => {
    try {
      setAccount(await api.demoAccount());
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Demo account unavailable");
    }
  }, []);

  const loadTrades = useCallback(async () => {
    try {
      setTrades(await api.demoTrades());
    } catch {
      /* history simply stays as it was */
    }
  }, []);

  /**
   * AI decision history. These are the analyses the engine actually stored,
   * including the ones that decided NOT to trade — which are the more
   * useful half of the record, so they are shown rather than filtered out.
   */
  const loadSignals = useCallback(async () => {
    try {
      setSignals(await api.signals(25));
    } catch {
      /* the tab keeps whatever it already had */
    }
  }, []);

  useEffect(() => {
    void loadBars();
  }, [loadBars]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    void loadAccount();
    void loadTrades();
    void loadSignals();
    void api.demoInstruments().then((r) => setInstruments(r.by_asset_class));
    // Risk settings supply the minimums the AI panel shows each gate
    // against. A failure leaves them null and the panel falls back to
    // documented defaults rather than inventing a threshold.
    void api.getRisk().then(setRisk).catch(() => setRisk(null));
  }, [loadAccount, loadTrades, loadSignals]);

  // One poll for account state. Bars refresh on the same beat rather than
  // running a second timer against the same backend.
  useEffect(() => {
    const t = window.setInterval(() => {
      void loadAccount();
      void loadBars();
      void loadSessions();
    }, 15_000);
    return () => window.clearInterval(t);
  }, [loadAccount, loadBars, loadSessions]);

  const price = account?.market_price ?? null;
  const spread = price ? price.ask - price.bid : null;

  const parsedVolume = Number.parseFloat(volume);
  const parsedSl = stopLoss.trim() ? Number.parseFloat(stopLoss) : null;
  const parsedTp = takeProfit.trim() ? Number.parseFloat(takeProfit) : null;

  const instrument = useMemo(() => {
    for (const group of Object.values(instruments)) {
      const found = group.find((i) => i.symbol === symbol);
      if (found) return found;
    }
    return null;
  }, [instruments, symbol]);

  /** Risk and RR from the instrument's own tick maths, not a gold constant. */
  const estimate = useMemo(() => {
    if (!price || !instrument || !Number.isFinite(parsedVolume)) return null;
    const entry = side === "BUY" ? price.ask : price.bid;
    const perUnit = (instrument.tick_value / instrument.tick_size) * parsedVolume;
    const risk =
      parsedSl != null ? Math.abs(entry - parsedSl) * perUnit : null;
    const reward =
      parsedTp != null ? Math.abs(parsedTp - entry) * perUnit : null;
    const rr = risk && reward && risk > 0 ? reward / risk : null;
    return { entry, risk, reward, rr };
  }, [price, instrument, parsedVolume, parsedSl, parsedTp, side]);

  /**
   * AI overlays. Deliberately a separate array from anything a user
   * creates, and cleared by its own control — turning AI analysis off must
   * never remove a customer's own work.
   */
  const aiLines: PriceLine[] = useMemo(() => {
    if (!showAI || !analysis) return [];
    const out: PriceLine[] = [];
    for (const level of analysis.levels?.support ?? []) {
      out.push({ price: level.price, label: "AI support", colour: "#3fb950",
                 dashed: true });
    }
    for (const level of analysis.levels?.resistance ?? []) {
      out.push({ price: level.price, label: "AI resistance", colour: "#f4564a",
                 dashed: true });
    }
    if (aiSetup?.entry != null) {
      out.push({ price: aiSetup.entry, label: "AI entry", colour: "#d9a441" });
    }
    if (aiSetup?.stopLoss != null) {
      out.push({ price: aiSetup.stopLoss, label: "AI SL", colour: "#f4564a" });
    }
    if (aiSetup?.takeProfit != null) {
      out.push({ price: aiSetup.takeProfit, label: "AI TP", colour: "#3fb950" });
    }
    return out.slice(0, 12);
  }, [showAI, analysis, aiSetup]);

  /**
   * Previous-period levels (section 10).
   *
   * Kept in their own memo and their own colour so they never read as part
   * of the AI's opinion — PDH is a fact about yesterday, not a call.
   */
  const previousLevelLines: PriceLine[] = useMemo(() => {
    if (!showPrevLevels || !sessionMap) return [];
    const out: PriceLine[] = [];
    for (const level of sessionMap.previous_levels) {
      out.push({ price: level.high, label: level.high_label,
                 colour: "#9aa3b0", dashed: true });
      out.push({ price: level.low, label: level.low_label,
                 colour: "#9aa3b0", dashed: true });
    }
    return out;
  }, [showPrevLevels, sessionMap]);

  const chartLines = useMemo(
    () => [...aiLines, ...previousLevelLines],
    [aiLines, previousLevelLines],
  );

  /**
   * Structural AI overlays: measured imbalances, order blocks, liquidity
   * pools and swing points. Same rule as the AI price lines — a separate
   * array from anything the customer drew, gated by the same toggle, and
   * empty whenever the engine found nothing.
   */
  /**
   * Prefer the row for the timeframe on screen: a structure measured on M1
   * is a hairline on H4 and tells the customer nothing there. The setup
   * timeframe is the fallback when the analysis did not cover this one.
   */
  const aiTimeframe = useMemo(
    () => analysis?.timeframes?.find((t) => t.timeframe === timeframe),
    [analysis, timeframe],
  );

  const aiZones: AIZone[] = useMemo(() => {
    if (!showAI || !analysis) return [];
    const fallback = analysis.zones;
    const fvg = aiTimeframe?.fvg ?? fallback?.fvg ?? [];
    const blocks = aiTimeframe?.order_blocks ?? fallback?.order_blocks ?? [];
    const pools = aiTimeframe?.liquidity ?? fallback?.liquidity ?? [];
    return [
      ...fvg,
      ...blocks,
      ...pools.map((pool) => ({ ...pool, kind: "liquidity" as const })),
    ].slice(0, 10);
  }, [showAI, analysis, aiTimeframe]);

  const aiSwings: AISwing[] = useMemo(() => {
    if (!showAI) return [];
    return (aiTimeframe?.swings ?? analysis?.swings ?? []).slice(-12);
  }, [showAI, analysis, aiTimeframe]);

  /**
   * BOS / CHoCH are reported by the engine as booleans against the setup
   * timeframe, so the level drawn is the swing the break happened at. When
   * no swing is available the mark is dropped rather than guessed.
   */
  const aiStructure: AIStructureMark[] = useMemo(() => {
    if (!showAI || !analysis?.structure) return [];
    // BOS/CHoCH are reported per timeframe too, so use the displayed one
    // when the analysis carries it. Note the two vocabularies: the
    // per-timeframe row says "HH-HL", the structure detail says
    // "HIGHER_HIGH_HIGHER_LOW". Both are checked rather than assuming one.
    const row = aiTimeframe;
    const usingRow = row != null && (row.bos != null || row.choch != null);
    const bos = usingRow ? (row.bos ?? false) : analysis.structure.bos;
    const choch = usingRow ? (row.choch ?? false) : analysis.structure.choch;
    if (!bos && !choch) return [];

    const pattern = usingRow
      ? (row.structure ?? "")
      : analysis.structure.pattern;
    const bullish =
      pattern === "HH-HL" || pattern === "HIGHER_HIGH_HIGHER_LOW";

    const swings = row?.swings ?? analysis.swings ?? [];
    const lastHigh = [...swings].reverse().find((m) => m.side === "high");
    const lastLow = [...swings].reverse().find((m) => m.side === "low");
    // A break of structure extends the trend, so it sits at the swing the
    // trend just cleared; a change of character sits at the opposite one.
    const target = bos
      ? (bullish ? lastHigh : lastLow)
      : (bullish ? lastLow : lastHigh);
    if (!target) return [];
    return [{
      kind: bos ? "BOS" : "CHOCH",
      price: target.price,
      label: bos ? "Break of structure" : "Change of character",
    }];
  }, [showAI, analysis, aiTimeframe]);

  const markers: TradeMarker[] = useMemo(() => {
    const open = (account?.positions ?? []).map((p) => ({
      time: p.opened_at ?? new Date().toISOString(),
      side: p.side,
      source: p.source,
      text: `${p.source === "MANUAL" ? "" : "AI "}${p.side} ${p.volume}`,
    }));
    const closed = trades.slice(0, 30).map((t) => ({
      time: t.closed_at ?? new Date().toISOString(),
      side: t.side,
      source: t.source,
      exit: true,
      text: `exit ${t.realized_pnl >= 0 ? "+" : ""}${t.realized_pnl}`,
    }));
    return [...open, ...closed];
  }, [account, trades]);

  async function submitOrder() {
    setPendingOrder(true);
    setTicketError(null);
    try {
      await api.demoOpen({
        symbol,
        side,
        volume: parsedVolume,
        stop_loss: parsedSl,
        take_profit: parsedTp,
        // Recorded as AI_ASSIST when the values came from a setup, so the
        // history can tell an assisted trade from a hand-typed one.
        source: aiSetup ? "AI_ASSIST" : "MANUAL",
        signal_confidence: aiSetup?.confidence ?? null,
        signal_rr: aiSetup?.rr ?? null,
      });
      setNotice(`${side} ${parsedVolume} ${symbol} opened on virtual money.`);
      await loadAccount();
    } catch (err) {
      setTicketError(err instanceof Error ? err.message : "Order rejected");
    } finally {
      setPendingOrder(false);
      setConfirming(false);
    }
  }

  async function closePosition(id: number) {
    try {
      const res = await api.demoClose(id);
      setNotice(`Closed. Realised ${money(res.realized_pnl)}.`);
      await loadAccount();
      await loadTrades();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not close position");
    }
  }

  async function resetDemo() {
    try {
      const res = await api.demoReset();
      setNotice(res.detail);
      await loadAccount();
      await loadTrades();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setResetting(false);
    }
  }

  const acct = account?.account ?? null;
  const canOpen = account?.can_open ?? false;

  return (
    <div className="jg-ws">
      {/* ------------------------------------------------------- toolbar */}
      <header className="jg-ws-top">
        <Brand size={22} />
        <span className="jg-ws-mode">J GOLD AI DEMO</span>

        <button
          type="button"
          className="btn sm"
          onClick={() => setSearchOpen(true)}
          title="Search every market in the J Gold AI universe"
        >
          {t("workspace.searchMarkets")}
        </button>
        <select
          className="jg-ws-select"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          aria-label="Symbol"
        >
          {Object.entries(instruments).map(([group, list]) => (
            <optgroup key={group} label={group}>
              {list.map((i) => (
                <option key={i.symbol} value={i.symbol} disabled={!i.tradable}>
                  {i.symbol}
                  {i.tradable ? "" : " — coming soon"}
                </option>
              ))}
            </optgroup>
          ))}
        </select>

        <div className="jg-tf">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              className={tf === timeframe ? "jg-tf-btn active" : "jg-tf-btn"}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>

        <IndicatorPanel
          configs={configs}
          setConfigs={setConfigs}
          readouts={[]}
        />

        <div className="jg-spacer" />
        <button
          type="button"
          className={showAI ? "btn sm active" : "btn sm"}
          onClick={() => setShowAI((v) => !v)}
        >
          AI overlays {showAI ? "on" : "off"}
        </button>
        <button
          type="button"
          className="btn sm"
          onClick={() => {
            // Clears AI overlays only. User content is untouched.
            setAnalysis(null);
            setAiSetup(null);
          }}
        >
          Clear AI
        </button>
        <button
          type="button"
          className={showSessions ? "btn sm active" : "btn sm"}
          onClick={() => setShowSessions((v) => !v)}
          title="Sydney, Tokyo, London and New York ranges"
        >
          {t("workspace.sessions")}
        </button>
        <button
          type="button"
          className={showPrevLevels ? "btn sm active" : "btn sm"}
          onClick={() => setShowPrevLevels((v) => !v)}
          title="Previous day, week and month high/low"
        >
          {t("workspace.previousLevels")}
        </button>
        <button
          type="button"
          className="btn sm"
          onClick={() => setStrategiesOpen(true)}
          title="Build and manage strategies"
        >
          Strategies
        </button>
        <button
          type="button"
          className="btn sm"
          onClick={() => setBrokersOpen(true)}
          title="Broker connection centre"
        >
          {t("workspace.brokers")}
        </button>
        <button type="button" className="btn sm" onClick={() => setResetting(true)}>
          {t("workspace.resetDemo")}
        </button>
        {onOpenOverview && (
          <button type="button" className="btn sm" onClick={onOpenOverview}
                  title="Account overview and summaries">
            Overview
          </button>
        )}
        <LanguagePicker />
        <button type="button" className="btn sm" onClick={onLogout}>
          {t("nav.signOut")}
        </button>
      </header>

      {/* ------------------------------------------------------- metrics */}
      <div className="jg-ws-metrics">
        <Metric label={t("account.balance")} value={money(acct?.balance, acct?.currency)} />
        <Metric label={t("account.equity")} value={money(acct?.equity, acct?.currency)} />
        <Metric label={t("account.freeMargin")} value={money(acct?.free_margin, acct?.currency)} />
        <Metric
          label={t("account.floatingPnl")}
          value={money(acct?.floating_pnl, acct?.currency)}
          tone={pnlClass(acct?.floating_pnl)}
        />
        <Metric
          label={t("account.realisedPnl")}
          value={money(acct?.realized_pnl, acct?.currency)}
          tone={pnlClass(acct?.realized_pnl)}
        />
        <Metric
          label="Sessions open"
          value={
            sessionMap?.active.length
              ? sessionMap.active.map((a) => a.display_name).join(", ")
              : showSessions || showPrevLevels
                ? "None"
                : "—"
          }
        />
        <Metric
          label="Market"
          value={price ? `${price.bid.toFixed(2)} / ${price.ask.toFixed(2)}` : "—"}
          sub={spread != null ? `spread ${spread.toFixed(2)}` : undefined}
        />
      </div>

      {notice && (
        <p className="jg-ws-notice" role="status">
          {notice}
        </p>
      )}
      {account?.blocked_reason && (
        <p className="jg-ws-blocked">{account.blocked_reason}</p>
      )}

      {/* --------------------------------------------------- chart + ticket */}
      <div className="jg-ws-main">
        <nav className="jg-draw-tools" aria-label="Drawing tools">
          {TOOLS.map((t) => (
            <button
              key={t.kind}
              type="button"
              title={t.hint}
              aria-label={t.hint}
              className={tool === t.kind ? "jg-draw-tool active" : "jg-draw-tool"}
              onClick={() => setTool(t.kind as DrawingKind | "CURSOR")}
            >
              {t.label}
            </button>
          ))}
          <span className="jg-draw-sep" />
          <button type="button" title="Undo" aria-label="Undo"
                  className="jg-draw-tool" disabled={!draw.canUndo}
                  onClick={() => void draw.undo()}>↺</button>
          <button type="button" title="Redo" aria-label="Redo"
                  className="jg-draw-tool" disabled={!draw.canRedo}
                  onClick={() => void draw.redo()}>↻</button>
          <button
            type="button" title="Lock selected" aria-label="Lock selected"
            className="jg-draw-tool" disabled={draw.selectedId == null}
            onClick={() =>
              draw.selectedId != null && void draw.toggle(draw.selectedId, "locked")
            }
          >🔒</button>
          <button
            type="button" title="Hide selected" aria-label="Hide selected"
            className="jg-draw-tool" disabled={draw.selectedId == null}
            onClick={() =>
              draw.selectedId != null && void draw.toggle(draw.selectedId, "hidden")
            }
          >👁</button>
          <button
            type="button" title="Delete selected" aria-label="Delete selected"
            className="jg-draw-tool" disabled={draw.selectedId == null}
            onClick={() => draw.selectedId != null && void draw.remove(draw.selectedId)}
          >🗑</button>
          <button
            type="button" title="Clear my drawings"
            aria-label="Clear my drawings"
            className="jg-draw-tool"
            onClick={() => void draw.clear()}
          >✕</button>
        </nav>

        <section className="jg-ws-chart">
          {barsError ? (
            <div className="jg-ws-chart-empty">{barsError}</div>
          ) : loadingBars && bars.length === 0 ? (
            <div className="jg-ws-chart-empty">Loading {symbol} {timeframe}…</div>
          ) : bars.length === 0 ? (
            <div className="jg-ws-chart-empty">
              No candles returned for {timeframe}.
            </div>
          ) : (
            <div className="jg-chart-stack">
              <TradingChart
                bars={bars}
              markers={markers}
              priceLines={chartLines}
                overlays={overlays}
                height={460}
                onCoordinates={setCoords}
              />
              <SessionLayer
                coords={coords}
                ranges={showSessions ? (sessionMap?.sessions ?? []) : []}
                showFill
                showHighLow
              />
              <AIOverlayLayer
                coords={coords}
                zones={aiZones}
                swings={aiSwings}
                structure={aiStructure}
              />
              <DrawingLayer
                coords={coords}
                tool={tool}
                drawings={draw.drawings}
                selectedId={draw.selectedId}
                onSelect={draw.setSelectedId}
                onCreate={draw.create}
                onMove={draw.move}
              />
            </div>
          )}
          {readouts.length > 0 && (
            <div className="jg-ind-readouts">
              {readouts.map((r) => (
                <div key={r.id} className="jg-ind-readout">
                  <span className="jg-ind-readout-label">{r.label}</span>
                  <span className="jg-ind-readout-value">{r.value}</span>
                  <span className="jg-ind-readout-note">{r.note}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <aside className="jg-ws-ticket">
          <h3>{t("ticket.title")}</h3>
          <p className="jg-ws-virtual">VIRTUAL MONEY — J Gold AI demo</p>

          <div className="jg-side-toggle">
            <button
              type="button"
              className={side === "BUY" ? "jg-side buy active" : "jg-side buy"}
              onClick={() => setSide("BUY")}
            >
              BUY
            </button>
            <button
              type="button"
              className={side === "SELL" ? "jg-side sell active" : "jg-side sell"}
              onClick={() => setSide("SELL")}
            >
              SELL
            </button>
          </div>

          <label className="jg-ws-field">
            <span>Volume</span>
            <input
              type="number"
              step={instrument?.volume_step ?? 0.01}
              min={instrument?.min_volume ?? 0.01}
              max={instrument?.max_volume ?? 100}
              value={volume}
              onChange={(e) => setVolume(e.target.value)}
            />
          </label>
          <label className="jg-ws-field">
            <span>Stop loss</span>
            <input
              type="number"
              step="0.01"
              value={stopLoss}
              onChange={(e) => setStopLoss(e.target.value)}
              placeholder="optional"
            />
          </label>
          <label className="jg-ws-field">
            <span>Take profit</span>
            <input
              type="number"
              step="0.01"
              value={takeProfit}
              onChange={(e) => setTakeProfit(e.target.value)}
              placeholder="optional"
            />
          </label>

          <dl className="jg-ws-estimate">
            <div>
              <dt>Entry</dt>
              <dd>{estimate ? estimate.entry.toFixed(2) : "—"}</dd>
            </div>
            <div>
              <dt>Risk</dt>
              <dd>{estimate?.risk != null ? money(estimate.risk) : "—"}</dd>
            </div>
            <div>
              <dt>R:R</dt>
              <dd>{estimate?.rr != null ? estimate.rr.toFixed(2) : "—"}</dd>
            </div>
          </dl>

          {ticketError && <p className="jg-ws-error">{ticketError}</p>}

          <button
            type="button"
            className="jg-btn primary"
            style={{ width: "100%" }}
            disabled={!canOpen || pendingOrder || !Number.isFinite(parsedVolume)}
            onClick={() => setConfirming(true)}
          >
            {canOpen ? `Place ${side} order` : "Trading unavailable"}
          </button>

          <div className="jg-side-tabs" role="tablist" aria-label="Sidebar">
            <button
              type="button"
              role="tab"
              aria-selected={sideTab === "ai"}
              className={sideTab === "ai" ? "jg-chip active" : "jg-chip"}
              onClick={() => setSideTab("ai")}
            >
              AI analysis
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={sideTab === "technicals"}
              className={sideTab === "technicals" ? "jg-chip active" : "jg-chip"}
              onClick={() => setSideTab("technicals")}
            >
              Technicals
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={sideTab === "objects"}
              className={sideTab === "objects" ? "jg-chip active" : "jg-chip"}
              onClick={() => setSideTab("objects")}
            >
              Objects ({draw.drawings.length})
            </button>
          </div>

          {sideTab === "objects" && (
            <ObjectTree
              drawings={draw.drawings}
              symbol={symbol}
              timeframe={timeframe}
              selectedId={draw.selectedId}
              onSelect={draw.setSelectedId}
              onToggle={draw.toggle}
              onDelete={draw.remove}
            />
          )}

          {sideTab === "technicals" && (
            <TechnicalSummary bars={bars} timeframe={timeframe} />
          )}

          <div hidden={sideTab !== "ai"}>
          <AIPanel
            risk={risk}
            onAnalysis={(next) => {
              setAnalysis(next);
              // A fresh analysis is a new row in the AI history, so pull it
              // now rather than making the customer switch tabs to find out.
              if (next) void loadSignals();
            }}
            onUseSetup={(setup) => {
              // AI ASSIST: this fills the form. It does not submit it, and
              // there is no path from here to an order.
              setAiSetup(setup);
              setSide(setup.side);
              if (setup.stopLoss != null) setStopLoss(String(setup.stopLoss));
              if (setup.takeProfit != null) setTakeProfit(String(setup.takeProfit));
              setTicketError(null);
              setNotice(
                `AI setup loaded into the ticket (${setup.side}, confidence ` +
                  `${setup.confidence}%). Review and confirm to place it.`,
              );
            }}
          />
          </div>
        </aside>
      </div>

      {/* ---------------------------------------------- positions / history */}
      <section className="jg-ws-bottom">
        <div className="jg-ws-tabs">
          <button
            type="button"
            className={tab === "positions" ? "jg-chip active" : "jg-chip"}
            onClick={() => setTab("positions")}
          >
            Open positions ({account?.positions.length ?? 0})
          </button>
          <button
            type="button"
            className={tab === "history" ? "jg-chip active" : "jg-chip"}
            onClick={() => setTab("history")}
          >
            Trade history ({trades.length})
          </button>
          <button
            type="button"
            className={tab === "ai" ? "jg-chip active" : "jg-chip"}
            onClick={() => { setTab("ai"); void loadSignals(); }}
          >
            AI history ({signals.length})
          </button>
        </div>

        <div className="jg-ws-table-wrap">
          {tab === "ai" ? (
            <table className="jg-ws-table">
              <thead>
                <tr>
                  <th>When</th><th>Symbol</th><th>Decision</th><th>Confidence</th>
                  <th>Entry</th><th>SL</th><th>TP</th><th>R:R</th>
                  <th>Risk gate</th><th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {signals.length === 0 && (
                  <tr>
                    <td colSpan={10} className="jg-ws-empty">
                      No AI analyses yet. Run one from the AI panel.
                    </td>
                  </tr>
                )}
                {signals.map((s) => (
                  <tr key={s.id}>
                    <td>{new Date(s.created_at).toLocaleString()}</td>
                    <td>{s.symbol}</td>
                    <td className={
                      s.action === "BUY" ? "up"
                        : s.action === "SELL" ? "down" : "jg-src"
                    }>
                      {s.action.replace("_", " ")}
                    </td>
                    <td>{s.confidence}%</td>
                    <td>{s.entry?.toFixed(2) ?? "—"}</td>
                    <td>{s.stop_loss?.toFixed(2) ?? "—"}</td>
                    <td>{s.take_profit?.toFixed(2) ?? "—"}</td>
                    <td>{s.risk_reward?.toFixed(2) ?? "—"}</td>
                    {/* null means the risk engine never ruled on it, which
                        is not the same as a rejection and is not shown as
                        one. */}
                    <td className={
                      s.risk_approved == null ? "jg-src"
                        : s.risk_approved ? "up" : "down"
                    }>
                      {s.risk_approved == null
                        ? "not assessed"
                        : s.risk_approved ? "approved" : "rejected"}
                    </td>
                    <td className="jg-ai-reason" title={s.reason}>
                      {s.risk_reasons?.length
                        ? s.risk_reasons.join("; ")
                        : s.reason || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : tab === "positions" ? (
            <table className="jg-ws-table">
              <thead>
                <tr>
                  <th>Symbol</th><th>Side</th><th>Source</th><th>Volume</th>
                  <th>Entry</th><th>SL</th><th>TP</th><th>Floating</th><th />
                </tr>
              </thead>
              <tbody>
                {(account?.positions ?? []).length === 0 && (
                  <tr><td colSpan={9} className="jg-ws-empty">No open positions.</td></tr>
                )}
                {(account?.positions ?? []).map((p) => (
                  <tr key={p.id}>
                    <td>{p.symbol}</td>
                    <td className={p.side === "BUY" ? "up" : "down"}>{p.side}</td>
                    <td className="jg-src">{p.source.replace("_", " ")}</td>
                    <td>{p.volume}</td>
                    <td>{p.entry_price.toFixed(2)}</td>
                    <td>{p.stop_loss?.toFixed(2) ?? "—"}</td>
                    <td>{p.take_profit?.toFixed(2) ?? "—"}</td>
                    <td className={pnlClass(p.floating_pnl)}>
                      {money(p.floating_pnl)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn sm"
                        onClick={() => void closePosition(p.id)}
                      >
                        Close
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="jg-ws-table">
              <thead>
                <tr>
                  <th>Closed</th><th>Symbol</th><th>Side</th><th>Source</th>
                  <th>Volume</th><th>Entry</th><th>Exit</th><th>Realised</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 && (
                  <tr><td colSpan={9} className="jg-ws-empty">No closed trades yet.</td></tr>
                )}
                {trades.map((t) => (
                  <tr key={t.id}>
                    <td>{t.closed_at ? new Date(t.closed_at).toLocaleString() : "—"}</td>
                    <td>{t.symbol}</td>
                    <td className={t.side === "BUY" ? "up" : "down"}>{t.side}</td>
                    <td className="jg-src">{t.source.replace("_", " ")}</td>
                    <td>{t.volume}</td>
                    <td>{t.entry_price.toFixed(2)}</td>
                    <td>{t.exit_price.toFixed(2)}</td>
                    <td className={pnlClass(t.realized_pnl)}>
                      {money(t.realized_pnl)}
                    </td>
                    <td className="jg-src">{t.close_reason.replace(/_/g, " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {/* ------------------------------------------------- confirmations */}
      {confirming && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="jg-confirm">
            <h3>Confirm order</h3>
            <dl className="jg-ws-confirm-list">
              <div><dt>Account</dt><dd>J Gold AI Demo — VIRTUAL MONEY</dd></div>
              <div><dt>Symbol</dt><dd>{symbol}</dd></div>
              <div><dt>Side</dt><dd>{side}</dd></div>
              <div><dt>Volume</dt><dd>{volume}</dd></div>
              <div><dt>Entry</dt><dd>{estimate ? estimate.entry.toFixed(2) : "—"}</dd></div>
              <div><dt>Stop loss</dt><dd>{parsedSl?.toFixed(2) ?? "none"}</dd></div>
              <div><dt>Take profit</dt><dd>{parsedTp?.toFixed(2) ?? "none"}</dd></div>
              <div><dt>Risk</dt><dd>{estimate?.risk != null ? money(estimate.risk) : "—"}</dd></div>
              <div><dt>R:R</dt><dd>{estimate?.rr != null ? estimate.rr.toFixed(2) : "—"}</dd></div>
            </dl>
            <div className="jg-confirm-actions">
              <button type="button" className="btn" onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="jg-btn primary"
                disabled={pendingOrder}
                onClick={() => void submitOrder()}
              >
                {pendingOrder ? "Placing…" : `Place ${side}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {resetting && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="jg-confirm">
            <h3>Reset the demo account?</h3>
            <p>
              Virtual balance returns to its starting value and all virtual
              positions and history are cleared. Your subscription, profile and
              any broker account are <strong>not</strong> affected.
            </p>
            <div className="jg-confirm-actions">
              <button type="button" className="btn" onClick={() => setResetting(false)}>
                Cancel
              </button>
              <button type="button" className="btn danger" onClick={() => void resetDemo()}>
                Reset demo
              </button>
            </div>
          </div>
        </div>
      )}

      <SymbolSearch
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        current={symbol}
        onPick={(picked) => {
          setSymbol(picked);
          setSearchOpen(false);
        }}
      />

      <StrategyBuilder
        open={strategiesOpen}
        onClose={() => setStrategiesOpen(false)}
        symbol={symbol}
        timeframe={timeframe}
      />

      <BrokerCentre open={brokersOpen} onClose={() => setBrokersOpen(false)} />

      <SupportChat />
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="jg-ws-metric">
      <span className="jg-ws-metric-label">{label}</span>
      <span className={`jg-ws-metric-value ${tone ?? ""}`}>{value}</span>
      {sub && <span className="jg-ws-metric-sub">{sub}</span>}
    </div>
  );
}
