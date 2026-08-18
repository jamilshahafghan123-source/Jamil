/**
 * Runtime configuration for the data layer.
 *
 * The dashboard runs on demo data until a Backend API base URL is configured.
 * The browser never talks to MetaTrader 5 directly:
 *
 *   Website -> Backend API -> MT5 Bridge -> MetaTrader 5 -> Demo broker
 */

function flag(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value === '') return fallback;
  return value.toLowerCase() === 'true' || value === '1';
}

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

/** True when no backend is configured, or demo mode is forced on. */
export const USE_DEMO_DATA =
  API_BASE_URL === '' || flag(import.meta.env.VITE_FORCE_DEMO_DATA, true);

/**
 * Master switch for any order-placing UI.
 *
 * SAFETY: this stays false for the entire demo phase. Even when it is flipped
 * on later, the backend must independently enforce demo-account-only trading.
 */
export const TRADING_ENABLED = flag(import.meta.env.VITE_TRADING_ENABLED, false);

/** Polling intervals in milliseconds. */
export const POLL_INTERVALS = {
  quote: 1_000,
  candles: 5_000,
  account: 3_000,
  positions: 3_000,
  analysis: 20_000,
  health: 6_000,
} as const;

export const API_ENDPOINTS = {
  health: '/api/v1/health',
  quote: '/api/v1/market/quote',
  candles: '/api/v1/market/candles',
  symbols: '/api/v1/market/symbols',
  analysis: '/api/v1/ai/analysis',
  account: '/api/v1/account',
  positions: '/api/v1/positions',
  history: '/api/v1/history/trades',
  riskSettings: '/api/v1/risk/settings',
} as const;
