/**
 * Thin typed fetch wrapper around the Backend API.
 *
 * Every service call funnels through here so authentication, timeouts and
 * error shaping live in exactly one place.
 */
import { ApiError } from '@/types';
import { API_BASE_URL } from './config';

const DEFAULT_TIMEOUT_MS = 8_000;

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  query?: Record<string, string | number | boolean | undefined>;
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
}

function buildUrl(endpoint: string, query: RequestOptions['query']): string {
  const url = new URL(`${API_BASE_URL}${endpoint}`, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

export async function apiRequest<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { signal, timeoutMs = DEFAULT_TIMEOUT_MS, query, method = 'GET', body } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  try {
    const response = await fetch(buildUrl(endpoint, query), {
      method,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    if (!response.ok) {
      throw new ApiError(
        `Backend responded ${response.status} ${response.statusText}`,
        response.status,
        endpoint,
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    const message =
      error instanceof DOMException && error.name === 'AbortError'
        ? `Request to ${endpoint} timed out after ${timeoutMs}ms`
        : error instanceof Error
          ? error.message
          : 'Unknown network error';
    throw new ApiError(message, 0, endpoint);
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}
