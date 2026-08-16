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
