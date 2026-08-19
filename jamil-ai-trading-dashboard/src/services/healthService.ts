/**
 * Connection health for the Website -> Backend -> MT5 Bridge chain.
 *
 * Contract for the Backend API:
 *   GET /api/v1/health -> {
 *     backend: { state, detail },
 *     mt5Bridge: { state, detail, latencyMs },
 *     ai: { state, detail },
 *     lastMarketDataAt: string | null,
 *     errors: { at, service, message }[]
 *   }
 */
import type { ConnectionStatus, ServiceHealth, ServiceState } from '@/types';
import { ApiError } from '@/types';
import { apiRequest } from './apiClient';
import { API_BASE_URL, API_ENDPOINTS, USE_DEMO_DATA } from './config';

interface HealthResponse {
  backend?: { state?: ServiceState; detail?: string; latencyMs?: number | null };
  mt5Bridge?: { state?: ServiceState; detail?: string; latencyMs?: number | null };
  ai?: { state?: ServiceState; detail?: string; latencyMs?: number | null };
  lastMarketDataAt?: string | null;
  errors?: { at: string; service: string; message: string }[];
}

function service(
  id: ServiceHealth['id'],
  label: string,
  state: ServiceState,
  detail: string,
  latencyMs: number | null = null,
): ServiceHealth {
  return { id, label, state, detail, latencyMs, lastCheckedAt: new Date().toISOString() };
}

export async function fetchConnectionStatus(
  lastMarketDataAt: string | null,
  signal?: AbortSignal,
): Promise<ConnectionStatus> {
  if (USE_DEMO_DATA) {
    const detail = API_BASE_URL
      ? 'Demo data forced on (VITE_FORCE_DEMO_DATA=true)'
      : 'No backend configured — set VITE_API_BASE_URL';
    return {
      services: [
        service('backend', 'Backend API', 'disconnected', detail),
        service('mt5-bridge', 'MT5 Bridge', 'disconnected', 'Unreachable without the Backend API'),
        service('ai', 'AI Analyst', 'disconnected', 'Running the local demo rule engine instead'),
      ],
      lastMarketDataAt,
      errors: [],
    };
  }

  const startedAt = performance.now();
  try {
    const health = await apiRequest<HealthResponse>(API_ENDPOINTS.health, {
      signal,
      timeoutMs: 5_000,
    });
    const roundTrip = Math.round(performance.now() - startedAt);

    return {
      services: [
        service(
          'backend',
          'Backend API',
          health.backend?.state ?? 'connected',
          health.backend?.detail ?? `Healthy · ${API_BASE_URL}`,
          health.backend?.latencyMs ?? roundTrip,
        ),
        service(
          'mt5-bridge',
          'MT5 Bridge',
          health.mt5Bridge?.state ?? 'disconnected',
          health.mt5Bridge?.detail ?? 'No status reported by the backend',
          health.mt5Bridge?.latencyMs ?? null,
        ),
        service(
          'ai',
          'AI Analyst',
          health.ai?.state ?? 'disconnected',
          health.ai?.detail ?? 'No status reported by the backend',
          health.ai?.latencyMs ?? null,
        ),
      ],
      lastMarketDataAt: health.lastMarketDataAt ?? lastMarketDataAt,
      errors: health.errors ?? [],
    };
  } catch (error) {
    const message = error instanceof ApiError ? error.message : 'Backend health check failed';
    return {
      services: [
        service('backend', 'Backend API', 'disconnected', message),
        service('mt5-bridge', 'MT5 Bridge', 'disconnected', 'Unknown — backend unreachable'),
        service('ai', 'AI Analyst', 'disconnected', 'Unknown — backend unreachable'),
      ],
      lastMarketDataAt,
      errors: [{ at: new Date().toISOString(), service: 'backend', message }],
    };
  }
}
