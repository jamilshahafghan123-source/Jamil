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
import {
  DrawingLayer, TOOLS, TOOL_GROUPS, type DrawingKind,
} from "../components/DrawingLayer";
import { SessionLayer } from "../components/SessionLayer";
import { SymbolSearch } from "../components/SymbolSearch";
import { TechnicalSummary } from "../components/TechnicalSummary";
import { BrokerCentre } from "../components/BrokerCentre";
import { LanguagePicker } from "../components/LanguagePicker";
import { ObjectTree } from "../components/ObjectTree";
import { StrategyBuilder } from "../components/StrategyBuilder";
import { OpportunityLog } from "../components/OpportunityLog";
import { AlertsPanel } from "../components/AlertsPanel";
import { IndicatorPane } from "../components/IndicatorPane";
import { BotPanel } from "../components/BotPanel";
import { QuickTrade } from "../components/QuickTrade";
import { DataWindow } from "../components/DataWindow";
import { ReplayBar } from "../components/ReplayBar";
import { AskPanel } from "../components/AskPanel";
import { DrawingStyleBar } from "../components/DrawingStyleBar";
import { money } from "../lib/format";
import { ScreenerPanel } from "../components/ScreenerPanel";
import {
  NotConfigured, RailPanel, RightRail, type PanelId, type RailItem,
} from "../components/RightRail";
import type { LogicalRange } from "lightweight-charts";
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

/**
 * Chart intervals, in ascending duration.
 *
 * All but M45 are served natively by MT5. M45 has no native constant —
 * 45 minutes does not divide an hour — but it divides a day exactly, so
 * the backend aggregates it from three M15 bars anchored to midnight UTC
 * and labels it as derived. Tick, second and range bars are deliberately
 * absent: the feed reports completed candles, so they cannot be produced
 * correctly and are not approximated.
 */
const TIMEFRAMES: Timeframe[] = [
  "M1", "M2", "M3", "M5", "M10", "M15", "M30", "M45",
  "H1", "H2", "H3", "H4", "D1",
];

/** Intervals the platform builds rather than receives. */
const DERIVED_TIMEFRAMES = new Set<Timeframe>(["M45"]);

/**
 * Visible history range (section 8) — how much of the past is on screen,
 * which is a different question from the candle interval. Each entry says
 * how many bars that span needs, and the chart is asked to show that many.
 */
const RANGES: { id: string; label: string; days: number }[] = [
  { id: "1D", label: "1D", days: 1 },
  { id: "5D", label: "5D", days: 5 },
  { id: "1M", label: "1M", days: 30 },
  { id: "3M", label: "3M", days: 90 },
  { id: "6M", label: "6M", days: 180 },
  { id: "YTD", label: "YTD", days: 0 },
  { id: "1Y", label: "1Y", days: 365 },
  { id: "5Y", label: "5Y", days: 1825 },
  { id: "ALL", label: "All", days: -1 },
];

const TIMEFRAME_MINUTES: Record<Timeframe, number> = {
  M1: 1, M2: 2, M3: 3, M5: 5, M10: 10, M15: 15, M30: 30, M45: 45,
  H1: 60, H2: 120, H3: 180, H4: 240, D1: 1440,
};

/** Bars per timeframe. Enough for context without over-fetching. */
const BAR_COUNT = 300;

function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "up" : "down";
}

/**
 * The right rail. Icons are plain geometry drawn here — original marks,
 * not a licensed icon set. Order puts the panels a trader reaches for
 * during a session first.
 */
const RAIL_ITEMS: RailItem[] = [
  { id: "trade", label: "Trade", glyph: "\u21C5" },
  { id: "bot", label: "Bot", glyph: "\u25C8" },
  { id: "watchlist", label: "Watchlist", glyph: "\u2630" },
  { id: "alerts", label: "Alerts", glyph: "\u25D4" },
  { id: "objects", label: "Object tree", glyph: "\u29C9" },
  { id: "technicals", label: "Technicals", glyph: "\u25A4" },
  { id: "data", label: "Data window", glyph: "\u2637" },
  { id: "chat", label: "Ask J Gold AI", glyph: "\u25CC" },
  { id: "account", label: "Account", glyph: "$" },
  { id: "news", label: "News", glyph: "\u25A6" },
  { id: "calendar", label: "Calendar", glyph: "\u25A3" },
  { id: "sentiment", label: "Sentiment", glyph: "\u25D0" },
  { id: "screener", label: "Screener", glyph: "\u229E" },
];

const PANEL_TITLES: Record<PanelId, string> = {
  trade: "Order ticket", bot: "Bot", watchlist: "Watchlist",
  alerts: "Alerts", objects: "Object tree", technicals: "Technicals",
  account: "Account", news: "News", calendar: "Calendar",
  sentiment: "Sentiment", screener: "Screener", data: "Data window",
  chat: "Ask J Gold AI", products: "Products", help: "Help",
  ai: "AI analysis", strategies: "Strategies", brokers: "Brokers",
};

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
  const [tab, setTab] = useState<"positions" | "history" | "ai" | "opportunities">("positions");

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
  const [sideTab, setSideTab] = useState<"ai" | "technicals" | "objects" | "alerts">("ai");
  const [brokersOpen, setBrokersOpen] = useState(false);
  /**
   * One panel at a time. Null means none — and when none is open the grid
   * column does not exist at all, so the chart takes the whole width.
   */
  const [panel, setPanel] = useState<PanelId | null>("trade");
  const [bottomOpen, setBottomOpen] = useState(true);
  const [quickTrade, setQuickTrade] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [hoverBar, setHoverBar] = useState<number | null>(null);
  /**
   * Chart cleanliness (section 6). A chart carrying twenty drawings and
   * eight studies becomes unreadable, so everything is dimmable in one
   * click WITHOUT deleting anything — hiding and clearing are different
   * intentions and must not share a button.
   */
  const [showDrawings, setShowDrawings] = useState(true);
  const [showIndicators, setShowIndicators] = useState(true);
  const [visibleRange, setVisibleRange] = useState<string>("1D");

  /**
   * Replay reveals a prefix of the bars already loaded. It never
   * generates a candle, and while it is on the chart is fed the slice
   * rather than the live array — so what is on screen is exactly what
   * the market did, up to that point.
   */
  const [replayOn, setReplayOn] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState(1);

  const stepReplay = useCallback(() => {
    setReplayIndex((current) => {
      if (current >= bars.length - 1) {
        // Stop at the end of recorded history rather than looping; a
        // replay that silently restarted would look like new data.
        setReplayPlaying(false);
        return bars.length - 1;
      }
      return current + 1;
    });
  }, [bars.length]);

  const visibleBars = replayOn ? bars.slice(0, replayIndex + 1) : bars;
  const workspace = useRef<HTMLDivElement>(null);

  /**
   * True fullscreen via the browser API rather than a CSS class, so the
   * page chrome genuinely disappears. The chart's own ResizeObserver
   * picks up the new size, so nothing needs to be told to redraw.
   *
   * The state follows the DOM rather than the click: Escape exits
   * fullscreen without going through our button, and a flag that only
   * tracked clicks would then be wrong.
   */
  useEffect(() => {
    const sync = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    } else {
      void workspace.current?.requestFullscreen().catch(() => {});
    }
  }, []);
  const [strategiesOpen, setStrategiesOpen] = useState(false);

  // Indicator state and calculations. Memoised on `bars`, so a poll that
  // returns an unchanged array recomputes nothing.
  // Indicators recompute on the replayed slice, so a study never shows a
  // value derived from candles the replay has not reached yet.
  const { configs, setConfigs, overlays, readouts, panes } =
    useIndicators(replayOn ? bars.slice(0, replayIndex + 1) : bars);

  // Customer drawings. Scoped to symbol AND timeframe, reloaded on either
  // change, and entirely separate from the AI overlays above.
  const [tool, setTool] = useState<DrawingKind | "CURSOR">("CURSOR");
  const [coords, setCoords] = useState<ChartCoordinates | null>(null);
  /**
   * Shared visible range for the lower panes. Whoever moves publishes it
   * and the others follow, so the panes stay aligned with the candles
   * above them through every zoom and pan.
   */
  const [paneRange, setPaneRange] = useState<LogicalRange | null>(null);
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
      const span = RANGES.find((r) => r.id === visibleRange);
      const minutes = TIMEFRAME_MINUTES[timeframe] ?? 15;
      const wanted = !span || span.days <= 0
        ? BAR_COUNT
        : Math.ceil((span.days * 1440) / minutes);
      // 1000 is the backend's own ceiling. A longer span at a fine
      // interval simply shows as much as the feed will serve, rather
      // than failing the request outright.
      const count = Math.max(60, Math.min(wanted, 1000));
      const res = await api.bars(timeframe, count, symbol, controller.signal);
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
  }, [symbol, timeframe, visibleRange]);

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

    // A stop on the wrong side of entry is not a small risk — it is not a
    // stop at all. Taking the absolute distance would turn that mistake
    // into a confident-looking number and a flattering R:R, so the side is
    // checked and the fault is reported instead of averaged away.
    const stopBehind = parsedSl == null
      ? null : side === "BUY" ? parsedSl < entry : parsedSl > entry;
    const targetAhead = parsedTp == null
      ? null : side === "BUY" ? parsedTp > entry : parsedTp < entry;

    const risk = stopBehind ? Math.abs(entry - parsedSl!) * perUnit : null;
    const reward = targetAhead ? Math.abs(parsedTp! - entry) * perUnit : null;
    const rr = risk && reward && risk > 0 ? reward / risk : null;

    const at = entry.toFixed(instrument.digits);
    const fault =
      stopBehind === false
        ? `A ${side} stop belongs ${side === "BUY" ? "below" : "above"} ${at}`
        : targetAhead === false
        ? `A ${side} target belongs ${side === "BUY" ? "above" : "below"} ${at}`
        : null;

    return { entry, risk, reward, rr, fault };
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
    <div className={fullscreen ? "jg-ws fullscreen" : "jg-ws"} ref={workspace}>
      {/* ---------------------------------------------- global header */}
      <header className="jg-ws-head">
        <Brand size={20} />
        <span className="jg-ws-mode">J GOLD AI DEMO</span>

        <div className="jg-head-price">
          <strong>{symbol}</strong>
          <span className="jg-head-last">
            {price ? price.ask.toFixed(instrument?.digits ?? 2) : "—"}
          </span>
          <span className="jg-head-spread">
            {price ? `spread ${(price.ask - price.bid).toFixed(2)}` : "no feed"}
          </span>
        </div>

        <div className="jg-spacer" />

        <LanguagePicker />
        {onOpenOverview && (
          <button type="button" className="btn sm" onClick={onOpenOverview}
                  title="Account overview and summaries">
            Overview
          </button>
        )}
        <button type="button" className="btn sm" onClick={onLogout}>
          {t("nav.signOut")}
        </button>
      </header>

      {/* ------------------------------------------------ chart toolbar */}
      <div className="jg-ws-top">
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
              title={DERIVED_TIMEFRAMES.has(tf)
                ? `${tf} is aggregated from M15 bars, anchored to midnight UTC`
                : `${tf} candles`}
            >
              {tf}
              {DERIVED_TIMEFRAMES.has(tf) && (
                <span className="jg-tf-derived" aria-hidden="true">*</span>
              )}
            </button>
          ))}
        </div>

        {/* Visible history is a separate question from candle interval:
            "the last month" and "15-minute candles" are both answers, to
            different questions. Conflating them is a common and confusing
            shortcut. */}
        <div className="jg-tf jg-range" role="group" aria-label="Visible range">
          {RANGES.map((range) => (
            <button
              key={range.id}
              type="button"
              className={range.id === visibleRange ? "jg-tf-btn active" : "jg-tf-btn"}
              onClick={() => setVisibleRange(range.id)}
              title={`Show about ${range.label} of history`}
            >
              {range.label}
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
        <button
          type="button"
          className={showDrawings ? "btn sm active" : "btn sm"}
          onClick={() => setShowDrawings((v) => !v)}
          title={showDrawings
            ? "Hide my drawings — nothing is deleted"
            : "Show my drawings"}
        >
          Drawings ({draw.drawings.length})
        </button>
        <button
          type="button"
          className={showIndicators ? "btn sm active" : "btn sm"}
          onClick={() => setShowIndicators((v) => !v)}
          title={showIndicators ? "Hide indicators" : "Show indicators"}
        >
          Studies ({configs.filter((c) => c.enabled).length})
        </button>
        <ReplayBar
          active={replayOn}
          index={replayIndex}
          total={bars.length}
          playing={replayPlaying}
          speed={replaySpeed}
          onToggleActive={() => {
            // Start part-way in, so there is chart to read immediately
            // rather than a single candle on an empty pane.
            setReplayIndex(Math.max(0, Math.floor(bars.length * 0.6)));
            setReplayOn(true);
            setReplayPlaying(false);
          }}
          onPlayPause={() => setReplayPlaying((v) => !v)}
          onStep={stepReplay}
          onJump={(delta) =>
            setReplayIndex((current) =>
              Math.max(0, Math.min(bars.length - 1, current + delta)))}
          onSpeed={setReplaySpeed}
          onReset={() => { setReplayIndex(0); setReplayPlaying(false); }}
          onExit={() => { setReplayOn(false); setReplayPlaying(false); }}
        />
        <button
          type="button"
          className={bottomOpen ? "btn sm active" : "btn sm"}
          onClick={() => setBottomOpen((v) => !v)}
          title="Show or hide the positions panel"
        >
          Panel
        </button>
        <button
          type="button"
          className={quickTrade ? "btn sm active" : "btn sm"}
          onClick={() => setQuickTrade((v) => !v)}
          title="Show or hide the quick trade control"
        >
          Quick trade
        </button>
        <button
          type="button"
          className="btn sm"
          onClick={toggleFullscreen}
          title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
        >
          {fullscreen ? "Exit full" : "Fullscreen"}
        </button>
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
          {/* One button per GROUP, opening a flyout. Twenty-five tools do
              not fit a 46px rail, and widening the rail or shrinking the
              icons both cost the chart the space this layout exists to
              give it. */}
          {TOOL_GROUPS.map((group) => {
            const holdsActive = group.kinds.includes(tool);
            return (
              <div key={group.id} className="jg-draw-group">
                <button
                  type="button"
                  className={holdsActive ? "jg-draw-tool active" : "jg-draw-tool"}
                  title={group.label}
                  aria-label={group.label}
                  aria-expanded={openGroup === group.id}
                  onClick={() => {
                    // A single-tool group selects immediately; there is
                    // nothing to choose between.
                    if (group.kinds.length === 1) {
                      setTool(group.kinds[0] as DrawingKind | "CURSOR");
                      setOpenGroup(null);
                      return;
                    }
                    setOpenGroup(openGroup === group.id ? null : group.id);
                  }}
                >
                  {group.glyph}
                  {group.kinds.length > 1 && (
                    <span className="jg-draw-more" aria-hidden="true" />
                  )}
                </button>

                {openGroup === group.id && (
                  <div className="jg-draw-flyout" role="menu"
                       aria-label={group.label}>
                    {group.kinds.map((kind) => {
                      const meta = TOOLS.find((entry) => entry.kind === kind);
                      return (
                        <button
                          key={kind}
                          type="button"
                          role="menuitem"
                          className={tool === kind
                            ? "jg-draw-flyout-item active" : "jg-draw-flyout-item"}
                          onClick={() => {
                            setTool(kind as DrawingKind | "CURSOR");
                            setOpenGroup(null);
                          }}
                        >
                          <span className="jg-draw-flyout-glyph">
                            {meta?.label ?? "?"}
                          </span>
                          {meta?.hint ?? kind}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}

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
            <div
              className="jg-chart-stack"
              /* The drawing layer sits above the canvas and its shapes take
                 pointer events so they can be selected, which means a large
                 shape swallows the chart's own crosshair. Resolving the
                 hovered bar here, from the shared coordinate bridge, works
                 whatever happens to be layered on top. */
              onMouseMove={(event) => {
                if (!coords || bars.length === 0) return;
                const box = event.currentTarget.getBoundingClientRect();
                const time = coords.xToTime(event.clientX - box.left);
                if (time == null) { setHoverBar(null); return; }
                const index = bars.findIndex((bar) => bar.time === time);
                setHoverBar(index >= 0 ? index : null);
              }}
              onMouseLeave={() => setHoverBar(null)}
            >
              {(() => {
                const selected = draw.drawings.find(
                  (d) => d.id === draw.selectedId,
                );
                if (!selected || !showDrawings) return null;
                return (
                  <DrawingStyleBar
                    drawing={selected}
                    onStyle={(patch) => draw.setStyle(selected.id, patch)}
                    onToggle={(field) => draw.toggle(selected.id, field)}
                    onDelete={() => draw.remove(selected.id)}
                    onClose={() => draw.setSelectedId(null)}
                  />
                );
              })()}
              <span className={replayOn ? "jg-live-badge replay" : "jg-live-badge"}>
                {replayOn ? "REPLAY" : "LIVE"}
              </span>
              {quickTrade && (
                <QuickTrade
                  instrument={instrument}
                  bid={price?.bid ?? null}
                  ask={price?.ask ?? null}
                  volume={volume}
                  onVolume={setVolume}
                  side={side}
                  onSide={setSide}
                  stopLoss={stopLoss}
                  takeProfit={takeProfit}
                  onStopLoss={setStopLoss}
                  onTakeProfit={setTakeProfit}
                  onPlace={() => setConfirming(true)}
                  /* Replay shows a past price. Placing an order against
                     it would open at a rate the market left behind hours
                     ago, so trading is closed while replay is on. */
                  disabled={!canOpen || pendingOrder || replayOn}
                  disabledReason={replayOn
                    ? "Replay is showing past candles — trading is paused."
                    : account?.blocked_reason ?? null}
                  onHide={() => setQuickTrade(false)}
                  estimate={estimate}
                  currency={acct?.currency ?? "USD"}
                />
              )}
              <TradingChart
                bars={visibleBars}
              markers={markers}
              priceLines={chartLines}
                overlays={showIndicators ? overlays : []}
                onCoordinates={setCoords}
                onVisibleRangeChange={setPaneRange}
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
                drawings={showDrawings ? draw.drawings : []}
                selectedId={draw.selectedId}
                onSelect={draw.setSelectedId}
                onCreate={draw.create}
                onMove={draw.move}
              />
            </div>
          )}

          {/* Lower panes: oscillators and volume, each with its own scale.
              lightweight-charts 4.x has no multi-pane API, so each is its
              own small chart kept in step with the main one. */}
          {showIndicators && panes.map((pane) => (
            <IndicatorPane
              key={pane.id}
              bars={bars}
              title={pane.title}
              series={pane.series}
              guides={pane.guides}
              externalRange={paneRange}
              onRangeChange={setPaneRange}
              onRemove={() =>
                setConfigs((current) => current.filter((c) => c.id !== pane.id))}
            />
          ))}

          {showIndicators && readouts.length > 0 && (
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

        {panel === "trade" && (
        <aside className="jg-ws-ticket">
          <div className="jg-panel-head">
            <h3>{t("ticket.title")}</h3>
            <div className="jg-spacer" />
            <button type="button" className="jg-panel-close"
                    onClick={() => setPanel(null)}
                    title="Close — the chart takes the space back"
                    aria-label="Close order ticket">×</button>
          </div>
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
              <dd>
                {estimate?.risk != null
                  ? money(estimate.risk, acct?.currency) : "—"}
              </dd>
            </div>
            <div>
              <dt>Profit</dt>
              <dd>
                {estimate?.reward != null
                  ? money(estimate.reward, acct?.currency) : "—"}
              </dd>
            </div>
            <div>
              <dt>R:R</dt>
              <dd>{estimate?.rr != null ? estimate.rr.toFixed(2) : "—"}</dd>
            </div>
          </dl>

          {estimate?.fault && <p className="jg-ws-error">{estimate.fault}</p>}

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
            <button
              type="button"
              role="tab"
              aria-selected={sideTab === "alerts"}
              className={sideTab === "alerts" ? "jg-chip active" : "jg-chip"}
              onClick={() => setSideTab("alerts")}
            >
              Alerts
            </button>
          </div>

          {sideTab === "alerts" && <AlertsPanel symbol={symbol} />}

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
        )}

        {panel && panel !== "trade" && (
          <RailPanel title={PANEL_TITLES[panel]} onClose={() => setPanel(null)}>
            {panel === "watchlist" && (
              <NotConfigured
                what="Live watchlist quotes"
                detail="Only XAUUSD has a live feed. Use Search markets to see every instrument and its status — nothing here will show a price the platform cannot source."
              />
            )}
            {panel === "news" && (
              <NotConfigured
                what="News"
                detail="No news provider is connected. Headlines will appear here once one is, and never before — invented headlines are the last thing anyone should trade on."
              />
            )}
            {panel === "calendar" && (
              <NotConfigured
                what="Economic calendar"
                detail="No calendar provider is connected. Event times and forecasts must come from a real source."
              />
            )}
            {panel === "sentiment" && (
              <NotConfigured
                what="Community sentiment"
                detail="Not enough J Gold AI customer activity to report an aggregate without exposing individuals. A percentage invented to fill this space would be worse than an empty panel."
              />
            )}
            {panel === "screener" && <ScreenerPanel currentSymbol={symbol} />}
            {panel === "chat" && (
              <AskPanel symbol={symbol} timeframe={timeframe} />
            )}
            {panel === "alerts" && <AlertsPanel symbol={symbol} />}
            {panel === "objects" && (
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
            {panel === "data" && (
              <DataWindow
                bars={bars}
                hoverIndex={hoverBar}
                timeframe={timeframe}
                symbol={symbol}
                readouts={readouts}
                analysis={analysis}
              />
            )}
            {panel === "technicals" && (
              <TechnicalSummary bars={bars} timeframe={timeframe} />
            )}
            {panel === "bot" && (
              <BotPanel
                account={account}
                positions={account?.positions ?? []}
                risk={risk}
                onRiskChange={setRisk}
              />
            )}
            {panel === "account" && (
              <div className="jg-account-panel">
                <p className="jg-ws-virtual">VIRTUAL MONEY — J Gold AI demo</p>
                <dl className="jg-account-list">
                  <div><dt>{t("account.balance")}</dt>
                       <dd>{money(acct?.balance, acct?.currency)}</dd></div>
                  <div><dt>{t("account.equity")}</dt>
                       <dd>{money(acct?.equity, acct?.currency)}</dd></div>
                  <div><dt>{t("account.freeMargin")}</dt>
                       <dd>{money(acct?.free_margin, acct?.currency)}</dd></div>
                  <div><dt>{t("account.floatingPnl")}</dt>
                       <dd className={pnlClass(acct?.floating_pnl)}>
                         {money(acct?.floating_pnl, acct?.currency)}</dd></div>
                  <div><dt>{t("account.realisedPnl")}</dt>
                       <dd className={pnlClass(acct?.realized_pnl)}>
                         {money(acct?.realized_pnl, acct?.currency)}</dd></div>
                  <div><dt>Open positions</dt>
                       <dd>{acct?.open_positions ?? 0}</dd></div>
                </dl>
                <button type="button" className="btn sm"
                        onClick={() => setResetting(true)}>
                  {t("workspace.resetDemo")}
                </button>
              </div>
            )}
            {panel === "ai" && (
              <p className="jg-cc-note">
                The AI analysis panel is in the sidebar beside the order
                ticket. Open Trade to reach it.
              </p>
            )}
            {(panel === "products" ||
              panel === "help" || panel === "strategies" ||
              panel === "brokers") && (
              <p className="jg-cc-note">
                Use the toolbar button for this — it opens as a full dialog
                rather than a side panel.
              </p>
            )}
          </RailPanel>
        )}

        <RightRail items={RAIL_ITEMS} active={panel}
                   onToggle={(id) => setPanel(panel === id ? null : id)} />
      </div>

      {/* ------------------------------------------ positions / history */}
      <section className="jg-ws-bottom" hidden={!bottomOpen}>
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
          <button
            type="button"
            className={tab === "opportunities" ? "jg-chip active" : "jg-chip"}
            onClick={() => setTab("opportunities")}
            title="Every setup detected, including the ones declined"
          >
            Opportunities
          </button>
        </div>

        {/* The opportunity log brings its own scrolling and controls, so it
            sits outside the shared table wrapper. */}
        {tab === "opportunities" && <OpportunityLog />}

        <div className="jg-ws-table-wrap" hidden={tab === "opportunities"}>
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
              <div><dt>Risk</dt><dd>
                {estimate?.risk != null
                  ? money(estimate.risk, acct?.currency) : "—"}</dd></div>
              <div><dt>Profit</dt><dd>
                {estimate?.reward != null
                  ? money(estimate.reward, acct?.currency) : "—"}</dd></div>
              <div><dt>R:R</dt><dd>{estimate?.rr != null ? estimate.rr.toFixed(2) : "—"}</dd></div>
            </dl>
            {estimate?.fault && (
              <p className="jg-ws-error">{estimate.fault}</p>
            )}
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

