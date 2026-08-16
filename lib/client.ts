/** Browser-side fetch helper. Talks only to /api/mt5/*, never to the bridge. */
import type { ApiResponse } from "./types";

export class ApiClientError extends Error {
  readonly code: string;
  readonly offline: boolean;
  readonly details: unknown;
  readonly status: number;

  constructor(
    code: string,
    message: string,
    options: { offline?: boolean; details?: unknown; status?: number } = {},
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.offline = options.offline ?? false;
    this.details = options.details ?? null;
    this.status = options.status ?? 0;
  }
}

export async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, cache: "no-store" });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiClientError("network_error", "Could not reach the trading server.", {
      offline: true,
    });
  }

  const payload = (await response.json().catch(() => null)) as ApiResponse<T> | null;

  if (!payload) {
    throw new ApiClientError("bad_response", `Unreadable server response (HTTP ${response.status}).`, {
      status: response.status,
    });
  }

  if (!payload.ok) {
    throw new ApiClientError(payload.error.code, payload.error.message, {
      offline: payload.error.offline,
      details: payload.error.details,
      status: response.status,
    });
  }

  return payload.data;
}
