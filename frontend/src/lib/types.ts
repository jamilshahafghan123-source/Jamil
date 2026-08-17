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
}

export interface Analysis {
  symbol?: string;
  generated_at?: string;
  model?: string;
  bias: "BULLISH" | "BEARISH" | "NEUTRAL";
  summary: string;
  timeframes: TimeframeView[];
  entry_zones: LevelZone[];
  warnings: string[];
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
