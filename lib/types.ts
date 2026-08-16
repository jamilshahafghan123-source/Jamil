/**
 * Shapes returned by the MT5 bridge, plus the envelope the browser sees.
 * Safe to import from client components - no secrets, no server imports.
 */

export type Account = {
  login: number;
  balance: number;
  equity: number;
  margin: number;
  margin_free: number;
  margin_level?: number;
  profit?: number;
  currency: string;
  leverage: number;
  server?: string;
  name?: string;
  trade_mode_name?: string | null;
  is_demo?: boolean;
  trade_allowed?: boolean;
};

export type SymbolSummary = {
  name: string;
  description: string;
  digits: number;
  point: number;
  spread: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
};

export type Tick = {
  symbol: string;
  bid: number;
  ask: number;
  last?: number | null;
  time?: number;
};

export type Candle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
  spread: number;
  real_volume: number;
};

export type CandlesPayload = {
  symbol: string;
  timeframe: string;
  count: number;
  candles: Candle[];
};

export type Position = {
  ticket: number;
  symbol: string;
  side: string;
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  time: string | null;
  comment?: string;
  magic?: number;
};

export type TradeResult = {
  retcode: number;
  retcode_description: string;
  success: boolean;
  order?: number | null;
  deal?: number | null;
  volume?: number | null;
  price?: number | null;
  comment?: string | null;
  dry_run?: boolean;
  sent_request?: Record<string, unknown> | null;
  risk?: RiskAssessment | null;
};

export type RiskLimits = {
  risk_per_trade_pct: number;
  max_daily_loss_pct: number;
  max_positions: number;
  max_lot: number;
  require_sl: boolean;
  require_tp: boolean;
  allowed_symbols: string[];
  demo_only: boolean;
};

export type RiskState = {
  enabled: boolean;
  currency: string;
  balance: number;
  equity: number;
  opening_balance: number;
  daily: { realized: number; floating: number; total: number; open_positions: number };
  daily_loss: number;
  daily_loss_pct: number;
  daily_loss_budget: number;
  daily_loss_remaining: number;
  daily_loss_limit_hit: boolean;
  open_positions: number;
  positions_remaining: number;
  limits: RiskLimits;
};

export type TimeframeRead = {
  timeframe: string;
  bias: "bullish" | "bearish" | "neutral";
  strength: number;
  reasons: string[];
  [key: string]: unknown;
};

export type SignalDirection = "BUY" | "SELL" | "NO_TRADE";

export type TargetSet = { tp1: number | null; tp2: number | null; tp3: number | null };

/** One verdict from the XAUUSD multi-timeframe strategy engine. */
export type SignalResult = {
  symbol: string;
  direction: SignalDirection;
  signal_score: number;
  min_score: number;
  entry: number | null;
  stop_loss: number | null;
  take_profit: TargetSet;
  risk_reward: TargetSet;
  trend: {
    primary: string;
    trend_timeframe: string;
    structure_timeframe: string;
    trigger_timeframe: string;
  };
  reasons: string[];
  timeframe_confirmation: { aligned: boolean; roles: Record<string, TimeframeRead> };
  timestamp: string;
  /** Which target the order proposal carries, since an MT5 order has one TP. */
  order_target: keyof TargetSet;
  price: { bid: number; ask: number };
  as_of: string | null;
  /** Execution-facing view of the same verdict. */
  decision: "trade" | "no_trade";
  proposal: {
    symbol: string;
    side: OrderSide;
    type: OrderType;
    volume: number;
    sl: number;
    tp: number;
  } | null;
  risk?: { passed: boolean; rule?: string; [key: string]: unknown };
};

export type BotTrade = {
  at: string;
  bar: string;
  symbol: string;
  side: OrderSide;
  volume: number;
  sl: number;
  tp: number;
  direction: SignalDirection;
  score: number;
  executed: boolean;
  detail: string;
  order: number | null;
  deal: number | null;
};

export type BotEvent = { at: string; kind: string; message: string };

export type BotStatus = {
  running: boolean;
  enabled: boolean;
  dry_run: boolean;
  mode: string;
  poll_seconds: number;
  symbol: string | null;
  timeframe: string | null;
  started_at: string | null;
  stopped_at: string | null;
  last_evaluated_at: string | null;
  last_bar: string | null;
  last_decision: {
    at: string;
    bar: string;
    decision: string;
    direction: SignalDirection;
    score: number;
    reason: string;
  } | null;
  trades_today: number;
  max_trades_per_day: number;
  trades: BotTrade[];
  events: BotEvent[];
};

/** A setup loaded from the signal panel into the order ticket. */
export type TicketPreset = {
  side: OrderSide;
  type: OrderType;
  volume: number;
  sl: number;
  tp: number;
  /** Changes on every load so the same setup can be re-applied. */
  nonce: number;
};

/** Risk figures the bridge attaches to an accepted or checked order. */
export type RiskAssessment = {
  enabled: boolean;
  risk_money?: number;
  risk_pct?: number;
  risk_budget?: number;
  daily_loss_pct?: number;
  open_positions?: number;
};

export type OrderType = "market" | "limit" | "stop";
export type OrderSide = "buy" | "sell";

export type OrderRequestBody = {
  symbol: string;
  side: OrderSide;
  volume: number;
  type: OrderType;
  price?: number;
  sl?: number;
  tp?: number;
  comment?: string;
  dry_run?: boolean;
};

/** Order response, plus whether the safety flag let it reach the market. */
export type OrderOutcome = TradeResult & {
  executed: boolean;
  execution_blocked_reason?: "live_execution_disabled";
};

export type BridgeStatus = {
  configured: boolean;
  reachable: boolean;
  /** Terminal connected to an MT5 account. */
  connected: boolean;
  login: number | null;
  trade_mode: string | null;
  is_demo: boolean;
  /** MT5_ALLOW_LIVE_ORDERS on this server. */
  live_orders_enabled: boolean;
  detail: string | null;
};

/** Every /api/mt5/* route answers with this envelope. */
export type ApiSuccess<T> = { ok: true; data: T };
export type ApiFailure = {
  ok: false;
  error: { code: string; message: string; offline: boolean; details?: unknown };
};
export type ApiResponse<T> = ApiSuccess<T> | ApiFailure;

export const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
