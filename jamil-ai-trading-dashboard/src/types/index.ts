/**
 * Shared domain types for the Jamil AI Trading Dashboard.
 *
 * These mirror the payloads the Backend API is expected to return, so the
 * service layer can be switched from demo data to live data without any
 * component changes.
 */

/** Where a piece of data came from. Rendered in the UI — never hidden. */
export type DataSource = 'demo' | 'live';

/** Every payload carries provenance so the UI can label it honestly. */
export interface Sourced<T> {
  data: T;
  source: DataSource;
  /** ISO-8601 timestamp of when the payload was produced. */
  receivedAt: string;
}

export type Timeframe = '1m' | '5m' | '15m' | '30m' | '1h' | '4h';

export interface TimeframeMeta {
  id: Timeframe;
  label: string;
  /** Duration of one candle, in seconds. */
  seconds: number;
}

export type MarketSession = 'open' | 'closed' | 'pre-market' | 'after-hours';

export interface Quote {
  symbol: string;
  description: string;
  bid: number;
  ask: number;
  /** Mid price, i.e. (bid + ask) / 2. */
  price: number;
  /** Spread expressed in points (0.01 for XAUUSD). */
  spreadPoints: number;
  /** Absolute change against the daily open, in price units. */
  dayChange: number;
  /** Change against the daily open, in percent. */
  dayChangePercent: number;
  dayHigh: number;
  dayLow: number;
  dayOpen: number;
  previousClose: number;
  session: MarketSession;
  /** Price decimals used for display. */
  digits: number;
  updatedAt: string;
}

export interface Candle {
  /** Unix epoch seconds of the candle open. */
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type MarketBias = 'bullish' | 'bearish' | 'neutral';
export type TrendStrength = 'strong' | 'moderate' | 'weak' | 'flat';
export type MomentumState = 'accelerating' | 'steady' | 'fading' | 'reversing';

export interface PriceLevel {
  label: string;
  price: number;
  /** 0..1 — how strongly the level has been respected in the sampled data. */
  strength: number;
}

export interface AiAnalysis {
  symbol: string;
  timeframe: Timeframe;
  bias: MarketBias;
  /** 0..100 */
  confidence: number;
  trend: {
    direction: MarketBias;
    strength: TrendStrength;
    description: string;
  };
  momentum: {
    state: MomentumState;
    /** Relative Strength Index, 0..100. */
    rsi: number;
    description: string;
  };
  support: PriceLevel[];
  resistance: PriceLevel[];
  entryZone: { from: number; to: number };
  stopLoss: number;
  takeProfit: number[];
  riskReward: number;
  /** Human-readable reasoning shown to the user. */
  explanation: string;
  /** Short bullet points backing the bias. */
  factors: { label: string; value: string; sentiment: MarketBias }[];
  generatedAt: string;
  modelName: string;
}

export type AccountType = 'demo' | 'live';

export interface AccountSnapshot {
  accountType: AccountType;
  broker: string;
  login: string;
  currency: string;
  leverage: number;
  balance: number;
  equity: number;
  margin: number;
  freeMargin: number;
  /** Percentage; null when there is no margin in use. */
  marginLevel: number | null;
  todayPnl: number;
  todayPnlPercent: number;
  openPositions: number;
  updatedAt: string;
}

export type PositionDirection = 'buy' | 'sell';
export type PositionStatus = 'open' | 'pending' | 'closed';

export interface Position {
  id: string;
  symbol: string;
  direction: PositionDirection;
  volume: number;
  entryPrice: number;
  currentPrice: number;
  stopLoss: number | null;
  takeProfit: number | null;
  pnl: number;
  pnlPercent: number;
  swap: number;
  commission: number;
  status: PositionStatus;
  openedAt: string;
}

export interface HistoryTrade {
  id: string;
  symbol: string;
  direction: PositionDirection;
  volume: number;
  entryPrice: number;
  exitPrice: number;
  stopLoss: number | null;
  takeProfit: number | null;
  pnl: number;
  pnlPercent: number;
  /** Why the trade ended. */
  closeReason: 'take-profit' | 'stop-loss' | 'manual' | 'timeout';
  openedAt: string;
  closedAt: string;
}

export interface RiskSettings {
  /** Percent of equity risked on a single trade. */
  riskPerTradePercent: number;
  /** Percent of starting-of-day equity allowed to be lost in one day. */
  maxDailyLossPercent: number;
  maxOpenPositions: number;
  /** When true, an order without a stop loss is rejected. */
  requireStopLoss: boolean;
  /** Hard safety switch. Stays false for the whole demo phase. */
  liveTradingEnabled: boolean;
  /** Demo trading (paper orders through the bridge) may be toggled later. */
  demoTradingEnabled: boolean;
  maxLotSize: number;
}

/** Live counters used to show how much of each risk budget is consumed. */
export interface RiskUsage {
  dailyLossUsed: number;
  dailyLossLimit: number;
  openPositions: number;
  positionsWithoutStop: number;
  updatedAt: string;
}

export type ServiceState = 'connected' | 'degraded' | 'disconnected' | 'checking';

export interface ServiceHealth {
  id: 'backend' | 'mt5-bridge' | 'ai';
  label: string;
  state: ServiceState;
  detail: string;
  /** Round-trip latency in milliseconds, when known. */
  latencyMs: number | null;
  lastCheckedAt: string;
}

export interface ConnectionStatus {
  services: ServiceHealth[];
  lastMarketDataAt: string | null;
  errors: { at: string; service: string; message: string }[];
}

/** Thrown by the API client so the UI can show a real error rather than mock. */
export class ApiError extends Error {
  readonly status: number;
  readonly endpoint: string;

  constructor(message: string, status: number, endpoint: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.endpoint = endpoint;
  }
}
