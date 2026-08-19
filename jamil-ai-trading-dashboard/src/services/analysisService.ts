/**
 * AI analysis service.
 *
 * Contract for the Backend API:
 *   GET /api/v1/ai/analysis?symbol=XAUUSD&timeframe=15m -> AiAnalysis
 *
 * The backend owns the model call. The frontend only renders the result and is
 * responsible for labelling it as analysis rather than a guaranteed outcome.
 */
import type { AiAnalysis, Sourced, Timeframe } from '@/types';
import { apiRequest } from './apiClient';
import { API_ENDPOINTS, USE_DEMO_DATA } from './config';
import { buildDemoAnalysis } from '@/demo/analysisEngine';
import { demoMarket, DEMO_SYMBOL } from '@/demo/marketEngine';
import { DEFAULT_CANDLE_COUNT } from '@/demo/timeframes';

export async function fetchAnalysis(
  timeframe: Timeframe,
  symbol: string = DEMO_SYMBOL,
  signal?: AbortSignal,
): Promise<Sourced<AiAnalysis>> {
  if (USE_DEMO_DATA) {
    const candles = demoMarket.getCandles(timeframe, DEFAULT_CANDLE_COUNT[timeframe]);
    return {
      data: buildDemoAnalysis(candles, timeframe),
      source: 'demo',
      receivedAt: new Date().toISOString(),
    };
  }
  const analysis = await apiRequest<AiAnalysis>(API_ENDPOINTS.analysis, {
    query: { symbol, timeframe },
    signal,
    timeoutMs: 20_000,
  });
  return { data: analysis, source: 'live', receivedAt: new Date().toISOString() };
}
