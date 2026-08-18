/**
 * Account, positions and trade history.
 *
 * Contract for the Backend API:
 *   GET /api/v1/account                      -> AccountSnapshot
 *   GET /api/v1/positions                    -> Position[]
 *   GET /api/v1/history/trades?from&to&limit -> HistoryTrade[]
 */
import type { AccountSnapshot, HistoryTrade, Position, Sourced } from '@/types';
import { apiRequest } from './apiClient';
import { API_ENDPOINTS, USE_DEMO_DATA } from './config';
import { buildDemoAccount, buildDemoHistory, buildDemoPositions } from '@/demo/portfolio';

export async function fetchPositions(signal?: AbortSignal): Promise<Sourced<Position[]>> {
  if (USE_DEMO_DATA) {
    return { data: buildDemoPositions(), source: 'demo', receivedAt: new Date().toISOString() };
  }
  const positions = await apiRequest<Position[]>(API_ENDPOINTS.positions, { signal });
  return { data: positions, source: 'live', receivedAt: new Date().toISOString() };
}

export async function fetchAccount(signal?: AbortSignal): Promise<Sourced<AccountSnapshot>> {
  if (USE_DEMO_DATA) {
    return {
      data: buildDemoAccount(buildDemoPositions()),
      source: 'demo',
      receivedAt: new Date().toISOString(),
    };
  }
  const account = await apiRequest<AccountSnapshot>(API_ENDPOINTS.account, { signal });
  return { data: account, source: 'live', receivedAt: new Date().toISOString() };
}

export async function fetchHistory(
  limit = 50,
  signal?: AbortSignal,
): Promise<Sourced<HistoryTrade[]>> {
  if (USE_DEMO_DATA) {
    return {
      data: buildDemoHistory().slice(0, limit),
      source: 'demo',
      receivedAt: new Date().toISOString(),
    };
  }
  const trades = await apiRequest<HistoryTrade[]>(API_ENDPOINTS.history, {
    query: { limit },
    signal,
  });
  return { data: trades, source: 'live', receivedAt: new Date().toISOString() };
}
