/**
 * Market data service.
 *
 * Contract for the Backend API:
 *   GET /api/v1/market/quote?symbol=XAUUSD              -> Quote
 *   GET /api/v1/market/candles?symbol&timeframe&limit   -> Candle[]
 */
import type { Candle, Quote, Sourced, Timeframe } from '@/types';
import { apiRequest } from './apiClient';
import { API_ENDPOINTS, USE_DEMO_DATA } from './config';
import { demoMarket, DEMO_SYMBOL } from '@/demo/marketEngine';
import { DEFAULT_CANDLE_COUNT } from '@/demo/timeframes';

function sourced<T>(data: T, live: boolean): Sourced<T> {
  return { data, source: live ? 'live' : 'demo', receivedAt: new Date().toISOString() };
}

export async function fetchQuote(
  symbol: string = DEMO_SYMBOL,
  signal?: AbortSignal,
): Promise<Sourced<Quote>> {
  if (USE_DEMO_DATA) {
    demoMarket.tick();
    return sourced(demoMarket.getQuote(), false);
  }
  const quote = await apiRequest<Quote>(API_ENDPOINTS.quote, { query: { symbol }, signal });
  return sourced(quote, true);
}

export async function fetchCandles(
  timeframe: Timeframe,
  symbol: string = DEMO_SYMBOL,
  limit: number = DEFAULT_CANDLE_COUNT[timeframe],
  signal?: AbortSignal,
): Promise<Sourced<Candle[]>> {
  if (USE_DEMO_DATA) {
    return sourced(demoMarket.getCandles(timeframe, limit), false);
  }
  const candles = await apiRequest<Candle[]>(API_ENDPOINTS.candles, {
    query: { symbol, timeframe, limit },
    signal,
  });
  return sourced(candles, true);
}
