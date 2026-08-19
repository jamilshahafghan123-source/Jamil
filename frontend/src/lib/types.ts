export type TradingMode = "MANUAL" | "DEMO" | "REAL";
export type SignalAction = "BUY" | "SELL" | "NO_TRADE";
export type Trend = "UP" | "DOWN" | "RANGE";

export interface AccountInfo {
  login: number;
  server: string;
  currency: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  margin_level: number | null;
  leverage: number;
  trade_mode: string; // "demo" | "contest" | "real"
  company: string;
}

export interface Tick {
  symbol: string;
  bid: number;
  ask: number;
  spread_points: number;
  time: string;
}

/** Timeframes the MT5 bridge understands. */
export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1";

/** One OHLC candle, exactly as GET /api/analysis/bars returns it. */
export interface Bar {
  /** ISO-8601 UTC timestamp of the candle open, e.g. "2026-08-19T03:00:00+00:00". */
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
  spread: number;
}

export interface BarsResponse {
  symbol: string;
  timeframe: Timeframe;
  bars: Bar[];
}

export interface Position {
  ticket: number;
  symbol: string;
  type: "BUY" | "SELL";
  volume: number;
  price_open: number;
  sl: number;
  tp: number;
  price_current: number;
  profit: number;
  swap: number;
  time: string;
  comment: string;
}

export interface Deal {
  ticket: number;
  order: number;
  position_id: number;
  entry: number;
  symbol: string;
  type: string;
  volume: number;
  price: number;
  profit: number;
  commission: number;
  swap: number;
  time: string;
  comment: string;
}

export interface BotStatus {
  bot_enabled: boolean;
  emergency_stop: boolean;
  trading_mode: TradingMode;
  real_trading_allowed_by_server: boolean;
  bridge_connected: boolean;
  halted_today: boolean;
  trades_today: number;
  pnl_today: number;
  last_signal_at: string | null;
}

export interface DashboardSnapshot {
  account: AccountInfo | null;
  tick: Tick | null;
  positions: Position[];
  status: BotStatus;
}

export interface Signal {
  id: number;
  created_at: string;
  symbol: string;
  action: SignalAction;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_reward: number | null;
  confidence: number;
  reason: string;
  risk_approved: boolean | null;
  risk_reasons: string[] | null;
  executed: boolean;
}

export interface LevelZone {
  low: number;
  high: number;
  label: string;
}

export interface TimeframeView {
  timeframe: string;
  trend: Trend;
  structure: string;
  support: number[];
  resistance: number[];
  breakout: string;
  pullback: string;
  liquidity: LevelZone[];
  notes: string;
  // --- added by the upgraded analyst -------------------------------
  role?: string; // MAJOR | INTERMEDIATE | SETUP | REFINEMENT
  structure_text?: string;
  regime?: Regime;
  momentum?: Momentum;
  rsi14?: number;
  adx14?: number;
  atr14?: number;
  ema20?: number;
  ema50?: number;
  ema200?: number;
  macd_hist?: number;
  bos?: boolean;
  choch?: boolean;
  breakout_confirmed?: boolean;
  support_levels?: PriceLevel[];
  resistance_levels?: PriceLevel[];
  volume?: VolumeView;
}

export type SetupStage = "WATCH" | "ENTRY_TRIGGER" | "CONFIRMED_SETUP";
export type Regime = "TRENDING" | "RANGING" | "EXPANSION" | "CONSOLIDATION" | "UNKNOWN";
export type Momentum = "RISING" | "FALLING" | "NEUTRAL";
export type LevelStrength = "HIGH" | "MEDIUM" | "LOW";

/** A ranked support/resistance level with the evidence behind it. */
export interface PriceLevel {
  price: number;
  strength: LevelStrength;
  touches: number;
  reason: string;
  distance: number;
}

export interface SessionLevel {
  label: string; // PDH | PDL | PWH | PWL
  price: number;
  reason: string;
}

/** Tick volume — a count of price changes, never traded contracts. */
export interface VolumeView {
  type: "TICK_VOLUME";
  current: number;
  average: number;
  relative: number;
  trend: "EXPANDING" | "CONTRACTING" | "STEADY" | "UNKNOWN";
  state: "HIGH" | "NORMAL" | "LOW" | "UNKNOWN";
}

export interface StructureView {
  pattern: string;
  bos: boolean;
  choch: boolean;
  description: string;
}

export interface TargetView {
  price: number;
  reason: string;
  risk_reward: number;
}

/** The deterministic setup. Every number here is computed, not model output. */
export interface TradeSetup {
  action: SignalAction;
  stage: SetupStage;
  confidence: number;
  confidence_components: Record<string, number>;
  entry_low: number | null;
  entry_high: number | null;
  trigger: number | null;
  trigger_text: string;
  stop_loss: number | null;
  stop_loss_reason: string;
  take_profit_1: number | null;
  take_profit_2: number | null;
  take_profit_3: number | null;
  targets: TargetView[];
  risk_reward: number | null;
  invalidation: string;
  next_target: number | null;
  next_target_reason: string;
  summary: string;
  reasons: string[];
  warnings: string[];
  blocking_reason: string | null;
}

export interface GroupBias {
  bias: "BULLISH" | "BEARISH" | "RANGE" | "UNKNOWN";
  timeframes: string[];
  agree: boolean;
}

export interface Hierarchy {
  major: GroupBias;
  intermediate: GroupBias;
  setup: GroupBias;
  refinement: GroupBias;
  higher_aligned: boolean;
}

export interface Analysis {
  symbol?: string;
  generated_at?: string;
  model?: string;
  bias: "BULLISH" | "BEARISH" | "NEUTRAL";
  headline?: string;
  summary: string;
  timeframes: TimeframeView[];
  entry_zones: LevelZone[];
  warnings: string[];
  // --- added by the upgraded analyst -------------------------------
  market?: {
    price: number;
    bid: number;
    ask: number;
    spread_points: number;
    trend: string;
    regime: Regime;
    momentum: Momentum;
    volatility: number;
    confluence_score: number;
  };
  hierarchy?: Hierarchy;
  structure?: StructureView;
  levels?: {
    support: PriceLevel[];
    resistance: PriceLevel[];
    session: SessionLevel[];
    liquidity_above: LevelZone[];
    liquidity_below: LevelZone[];
  };
  volume?: VolumeView;
  setup?: TradeSetup;
  reasons?: string[];
}

export interface RiskSettings {
  max_risk_per_trade_pct: number;
  max_daily_loss_pct: number;
  max_trades_per_day: number;
  max_open_positions: number;
  max_lot_size: number;
  min_confidence: number;
  min_rr: number;
  max_spread_points: number;
  trading_mode: TradingMode;
  bot_enabled: boolean;
  emergency_stop: boolean;
  halted_until_date: string | null;
}

export interface OrderLog {
  id: number;
  created_at: string;
  mode: TradingMode;
  symbol: string;
  action: SignalAction;
  volume: number;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  status: "REQUESTED" | "FILLED" | "REJECTED" | "ERROR";
  broker_ticket: number | null;
  broker_retcode: number | null;
  broker_comment: string | null;
}

export interface ExecutionResult {
  executed: boolean;
  reasons: string[];
  order_log_id: number | null;
  ticket: number | null;
  volume: number;
}

export interface LiveMessage {
  type: string;
  tick?: Tick;
  positions?: Position[];
  account?: AccountInfo;
  bridge_connected: boolean;
  bot_enabled?: boolean;
  emergency_stop?: boolean;
  trading_mode?: TradingMode;
  error?: string;
}
