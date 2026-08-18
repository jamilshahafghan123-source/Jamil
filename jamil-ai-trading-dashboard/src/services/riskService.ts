/**
 * Risk configuration service.
 *
 * Contract for the Backend API:
 *   GET /api/v1/risk/settings  -> RiskSettings
 *   PUT /api/v1/risk/settings  -> RiskSettings
 *
 * SAFETY: `liveTradingEnabled` is never sent as true from this build. The
 * backend must reject it independently — the UI is not the safety boundary.
 */
import type { AccountSnapshot, Position, RiskSettings, RiskUsage, Sourced } from '@/types';
import { apiRequest } from './apiClient';
import { API_ENDPOINTS, USE_DEMO_DATA } from './config';
import { buildDemoRiskUsage, DEMO_RISK_SETTINGS } from '@/demo/portfolio';

let demoSettings: RiskSettings = { ...DEMO_RISK_SETTINGS };

export async function fetchRiskSettings(signal?: AbortSignal): Promise<Sourced<RiskSettings>> {
  if (USE_DEMO_DATA) {
    return { data: { ...demoSettings }, source: 'demo', receivedAt: new Date().toISOString() };
  }
  const settings = await apiRequest<RiskSettings>(API_ENDPOINTS.riskSettings, { signal });
  return { data: settings, source: 'live', receivedAt: new Date().toISOString() };
}

export async function saveRiskSettings(
  patch: Partial<RiskSettings>,
  signal?: AbortSignal,
): Promise<Sourced<RiskSettings>> {
  // Live trading cannot be turned on from the UI in this build.
  const safePatch: Partial<RiskSettings> = { ...patch, liveTradingEnabled: false };

  if (USE_DEMO_DATA) {
    demoSettings = { ...demoSettings, ...safePatch };
    return { data: { ...demoSettings }, source: 'demo', receivedAt: new Date().toISOString() };
  }
  const settings = await apiRequest<RiskSettings>(API_ENDPOINTS.riskSettings, {
    method: 'PUT',
    body: safePatch,
    signal,
  });
  return { data: settings, source: 'live', receivedAt: new Date().toISOString() };
}

/** Derived locally from the account + positions the backend already returned. */
export function deriveRiskUsage(
  account: AccountSnapshot,
  positions: Position[],
  settings: RiskSettings,
): RiskUsage {
  return buildDemoRiskUsage(account, positions, settings);
}
